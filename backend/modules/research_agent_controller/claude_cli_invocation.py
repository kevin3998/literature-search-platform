"""Opt-in real Claude Code CLI invocation backend for A7b.

This module only invokes the CLI when explicitly enabled by configuration. It
does not execute research skills or mutate workspace artifacts.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .cli_contract import CLI_CONTROLLER_SCHEMA_VERSION
from .skill_registry import SkillRegistry, build_default_skill_registry

BACKEND_NAME = "real_claude_code_cli"


@dataclass
class ClaudeCodeCliBackendConfig:
    enabled: bool = False
    cli_binary: str = "claude"
    working_directory: str | None = None
    timeout_seconds: int = 60
    max_output_chars: int = 20000
    extra_env: dict[str, str] = field(default_factory=dict)
    allow_real_invocation: bool = False
    cli_args: list[str] = field(
        default_factory=lambda: ["-p", "--permission-mode", "plan", "--no-session-persistence"]
    )

    def __post_init__(self) -> None:
        self.timeout_seconds = max(1, int(self.timeout_seconds))
        self.max_output_chars = max(1, int(self.max_output_chars))
        self.extra_env = {str(key): str(value) for key, value in dict(self.extra_env or {}).items()}
        self.cli_args = [str(arg) for arg in list(self.cli_args or [])]
        self.cli_binary = str(self.cli_binary or "claude")

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "cli_binary": self.cli_binary,
            "working_directory": self.working_directory,
            "timeout_seconds": self.timeout_seconds,
            "max_output_chars": self.max_output_chars,
            "extra_env": dict(self.extra_env),
            "allow_real_invocation": self.allow_real_invocation,
            "cli_args": list(self.cli_args),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaudeCodeCliBackendConfig":
        return cls(
            enabled=bool(data.get("enabled", False)),
            cli_binary=data.get("cli_binary", "claude"),
            working_directory=data.get("working_directory"),
            timeout_seconds=data.get("timeout_seconds", 60),
            max_output_chars=data.get("max_output_chars", 20000),
            extra_env=dict(data.get("extra_env", {})),
            allow_real_invocation=bool(data.get("allow_real_invocation", False)),
            cli_args=list(data.get("cli_args", ["-p", "--permission-mode", "plan", "--no-session-persistence"])),
        )


@dataclass
class CliBackendResponse:
    raw_output: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    duration_seconds: float = 0.0
    backend_name: str = BACKEND_NAME
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.metadata = dict(self.metadata or {})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliBackendResponse":
        return cls(
            raw_output=data.get("raw_output", ""),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code"),
            timed_out=bool(data.get("timed_out", False)),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            backend_name=data.get("backend_name", BACKEND_NAME),
            metadata=dict(data.get("metadata", {})),
        )


class RealClaudeCodeCliBackend:
    """Real CLI backend that remains inert unless explicitly enabled."""

    def __init__(
        self,
        config: ClaudeCodeCliBackendConfig | dict[str, Any] | None = None,
        *,
        registry: SkillRegistry | None = None,
        contract: dict[str, Any] | None = None,
    ):
        self.config = (
            config
            if isinstance(config, ClaudeCodeCliBackendConfig)
            else ClaudeCodeCliBackendConfig.from_dict(config or {})
        )
        self.registry = registry or build_default_skill_registry()
        self.contract = dict(contract or {})
        self.last_response: CliBackendResponse | None = None

    def next_output(self, snapshot: dict[str, Any]) -> str:
        response = self.invoke(snapshot)
        return response.raw_output

    def invoke(self, snapshot: dict[str, Any]) -> CliBackendResponse:
        started = time.monotonic()
        task_id = str(snapshot.get("task_id") or "")
        if not self.config.enabled or not self.config.allow_real_invocation:
            return self._record(
                CliBackendResponse(
                    raw_output=_stop_blocked(task_id, "Real Claude Code CLI invocation is disabled."),
                    duration_seconds=_elapsed(started),
                    metadata={"backend_error": "real_invocation_disabled"},
                )
            )

        cwd, cwd_error = _validated_working_directory(self.config.working_directory, snapshot)
        if cwd_error:
            return self._record(
                CliBackendResponse(
                    raw_output=_stop_blocked(task_id, cwd_error),
                    duration_seconds=_elapsed(started),
                    metadata={"backend_error": "invalid_working_directory", "detail": cwd_error},
                )
            )

        prompt = build_claude_cli_controller_prompt(snapshot, self.registry, self.contract)
        command = [self.config.cli_binary, *self.config.cli_args, prompt]
        env = dict(os.environ)
        env.update(self.config.extra_env)

        try:
            completed = subprocess.run(
                command,
                shell=False,
                cwd=str(cwd),
                timeout=self.config.timeout_seconds,
                capture_output=True,
                text=True,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _trim(_to_text(exc.output), self.config.max_output_chars)
            stderr = _trim(_to_text(exc.stderr), self.config.max_output_chars)
            return self._record(
                CliBackendResponse(
                    raw_output=_stop_blocked(task_id, "Claude Code CLI invocation timed out."),
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=None,
                    timed_out=True,
                    duration_seconds=_elapsed(started),
                    metadata={"backend_error": "timeout", "timeout_seconds": self.config.timeout_seconds},
                )
            )

        stdout = _trim(completed.stdout or "", self.config.max_output_chars)
        stderr = _trim(completed.stderr or "", self.config.max_output_chars)
        if completed.returncode == 0:
            raw_output = stdout
            metadata: dict[str, Any] = {"command": _redacted_command(command)}
        elif stdout:
            raw_output = stdout
            metadata = {"backend_error": "nonzero_exit", "command": _redacted_command(command)}
        else:
            raw_output = _stop_blocked(task_id, "Claude Code CLI returned a nonzero exit code without stdout.")
            metadata = {"backend_error": "nonzero_exit_without_stdout", "command": _redacted_command(command)}

        return self._record(
            CliBackendResponse(
                raw_output=_trim(raw_output, self.config.max_output_chars),
                stdout=stdout,
                stderr=stderr,
                exit_code=completed.returncode,
                timed_out=False,
                duration_seconds=_elapsed(started),
                metadata=metadata,
            )
        )

    def _record(self, response: CliBackendResponse) -> CliBackendResponse:
        self.last_response = response
        return response


def build_claude_cli_controller_prompt(
    snapshot: dict[str, Any],
    registry: SkillRegistry | None = None,
    contract: dict[str, Any] | None = None,
) -> str:
    registry_obj = registry or build_default_skill_registry()
    allowed_skills = [skill.name for skill in registry_obj.list_available_skills()]
    prompt_payload = {
        "schema_version": CLI_CONTROLLER_SCHEMA_VERSION,
        "task_id": snapshot.get("task_id"),
        "allowed_skills": allowed_skills,
        "workspace_snapshot": snapshot,
        "contract": contract or {},
    }
    return (
        "You are the Claude Code CLI controller backend for a research workspace.\n"
        "Output JSON only. You must output exactly one JSON object.\n"
        "Your entire stdout must start with { and end with }.\n"
        "Do not wrap the JSON in Markdown.\n"
        "Do not use ```json fences or any other code fences.\n"
        "Do not include explanations before or after the JSON.\n"
        "Do not include comments.\n"
        "Do not include natural language.\n"
        "The output will be parsed by json.loads(raw_stdout). Any Markdown code fence or extra text "
        "will be rejected as UNPARSEABLE_OUTPUT.\n"
        f"The JSON must conform to {CLI_CONTROLLER_SCHEMA_VERSION}.\n"
        "Allowed decision_type values: CALL_TOOL, VALIDATE_ARTIFACT, RETRY_WITH_ADJUSTED_INPUT, "
        "BRANCH_PLAN, SKIP_WITH_WARNING, REQUEST_USER_INPUT, STOP_SUCCESS, STOP_BLOCKED.\n"
        "The decision field must be a JSON object. Do not set decision to a string.\n"
        "CALL_TOOL decisions must include skill_request.\n"
        f"Allowed skill_name values: {', '.join(allowed_skills)}.\n"
        "Must not execute skills directly. Only request a registered skill through skill_request.\n"
        "Must not use shell commands.\n"
        "Must not directly modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Must not access or modify databases.\n"
        "Must not route raw retrieval artifacts into report generation.\n"
        "Must not generate landscape, gaps, ideas, novelty screening, full reports, experiments, "
        "claim ledgers, or manuscript sections.\n"
        "If you cannot comply with the output format, output a valid STOP_BLOCKED JSON envelope.\n"
        "If you cannot choose a safe bounded action, output STOP_BLOCKED or REQUEST_USER_INPUT.\n"
        "Return one envelope object with fields schema_version, task_id, decision, notes, warnings.\n"
        "A valid STOP_BLOCKED envelope example is exactly shaped like this: "
        '{"schema_version":"cli_controller_contract_v1","task_id":"'
        f'{snapshot.get("task_id") or ""}'
        '","decision":{"decision_type":"STOP_BLOCKED","reason":"Cannot choose a safe bounded action."},'
        '"notes":[],"warnings":[]}.\n'
        "A valid CALL_TOOL envelope must put decision_type and skill_request inside the decision object.\n"
        "\n"
        "Context JSON:\n"
        f"{json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)}"
    )


def detect_cli_output_format_issue(raw_output: str) -> str:
    value = str(raw_output or "")
    stripped = value.strip()
    if not stripped:
        return "empty_output"
    if stripped.startswith("```"):
        return "fenced_json"
    if not (stripped.startswith("{") and stripped.endswith("}")):
        if "{" in stripped and "}" in stripped:
            return "extra_text"
        return "unknown"
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return "unknown"
    if isinstance(parsed, dict) and "schema_version" in parsed:
        return "none"
    if isinstance(parsed, dict) and ("result" in parsed or "type" in parsed):
        return "claude_wrapper_json"
    return "unknown"


def _validated_working_directory(working_directory: str | None, snapshot: dict[str, Any]) -> tuple[Path, str | None]:
    project_root = Path(__file__).resolve().parents[3]
    cwd = Path(working_directory).expanduser() if working_directory else project_root
    try:
        resolved = cwd.resolve()
    except OSError as exc:
        return cwd, f"working_directory_not_resolvable:{exc}"
    allowed_roots = [project_root.resolve()]
    workspace_root = snapshot.get("workspace_root")
    if workspace_root:
        try:
            allowed_roots.append(Path(str(workspace_root)).resolve())
        except OSError:
            pass
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved, None
        except ValueError:
            continue
    return resolved, "working_directory_must_be_project_or_workspace_scoped"


def _stop_blocked(task_id: str, reason: str) -> str:
    return json.dumps(
        {
            "schema_version": CLI_CONTROLLER_SCHEMA_VERSION,
            "task_id": task_id,
            "decision": {
                "decision_type": "STOP_BLOCKED",
                "reason": reason,
            },
            "notes": [],
            "warnings": [reason],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _trim(value: str, max_chars: int) -> str:
    return value[:max_chars]


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _elapsed(started: float) -> float:
    return max(0.0, time.monotonic() - started)


def _redacted_command(command: list[str]) -> list[str]:
    if not command:
        return []
    return [*command[:-1], "<prompt>"]


__all__ = [
    "ClaudeCodeCliBackendConfig",
    "CliBackendResponse",
    "RealClaudeCodeCliBackend",
    "build_claude_cli_controller_prompt",
    "detect_cli_output_format_issue",
]
