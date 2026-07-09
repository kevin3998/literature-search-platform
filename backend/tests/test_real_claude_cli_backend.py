import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.research_agent_controller import (
    ClaudeCodeCliBackendConfig,
    CliBackendResponse,
    RealClaudeCodeCliBackend,
    build_claude_cli_controller_prompt,
    build_default_skill_registry,
    detect_cli_output_format_issue,
)
from modules.research_workspace import ResearchWorkspaceStore


def _workspace(tmp_path: Path, task_id: str = "task_123") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        task_id,
        task_markdown="# Task\n\nResearch LLMs in materials discovery.\n",
        plan_markdown="# Plan\n\nUse the minimal topic-to-evidence loop.\n",
    )
    return tmp_path / "research_agent/research_tasks" / task_id


def _snapshot(workspace_root: Path) -> dict:
    return {
        "task_id": workspace_root.name,
        "task_md": (workspace_root / "task.md").read_text(encoding="utf-8"),
        "plan_md": (workspace_root / "plan.md").read_text(encoding="utf-8"),
        "state": json.loads((workspace_root / "state.json").read_text(encoding="utf-8")),
        "artifact_manifest": json.loads((workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")),
        "recent_events": [],
        "step_index": 0,
    }


def _valid_envelope(task_id: str = "task_123") -> str:
    return json.dumps(
        {
            "schema_version": "cli_controller_contract_v1",
            "task_id": task_id,
            "decision": {
                "decision_type": "STOP_BLOCKED",
                "reason": "Unit test response.",
            },
            "notes": [],
            "warnings": [],
        },
        sort_keys=True,
    )


def test_real_backend_defaults_disabled_and_does_not_call_subprocess(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    def fail_run(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fail_run)
    backend = RealClaudeCodeCliBackend()

    raw_output = backend.next_output(_snapshot(workspace_root))

    assert json.loads(raw_output)["decision"]["decision_type"] == "STOP_BLOCKED"
    assert backend.last_response.metadata["backend_error"] == "real_invocation_disabled"
    assert backend.last_response.exit_code is None


def test_allow_real_invocation_false_rejects_even_when_enabled(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    def fail_run(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fail_run)
    backend = RealClaudeCodeCliBackend(ClaudeCodeCliBackendConfig(enabled=True, allow_real_invocation=False))

    response = backend.invoke(_snapshot(workspace_root))

    assert response.metadata["backend_error"] == "real_invocation_disabled"
    assert json.loads(response.raw_output)["decision"]["decision_type"] == "STOP_BLOCKED"


def test_enabled_backend_calls_subprocess_with_shell_false_timeout_env_and_prompt(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    calls = []

    def fake_run(command, **kwargs):  # noqa: ANN001
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=_valid_envelope("task_123"), stderr="", returncode=0)

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fake_run)
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(
            enabled=True,
            allow_real_invocation=True,
            cli_binary="claude",
            working_directory=str(Path.cwd()),
            timeout_seconds=12,
            extra_env={"A7B_TEST": "1"},
        )
    )

    raw_output = backend.next_output(_snapshot(workspace_root))

    assert json.loads(raw_output)["schema_version"] == "cli_controller_contract_v1"
    command, kwargs = calls[0]
    assert command[0] == "claude"
    assert command[1:5] == ["-p", "--permission-mode", "plan", "--no-session-persistence"]
    assert "cli_controller_contract_v1" in command[-1]
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 12
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["cwd"] == str(Path.cwd().resolve())
    assert kwargs["env"]["A7B_TEST"] == "1"
    assert backend.last_response.exit_code == 0


def test_nonzero_exit_code_and_stderr_are_captured(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    def fake_run(command, **kwargs):  # noqa: ANN001
        return SimpleNamespace(stdout=_valid_envelope("task_123"), stderr="warning from cli", returncode=7)

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fake_run)
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(enabled=True, allow_real_invocation=True, working_directory=str(Path.cwd()))
    )

    response = backend.invoke(_snapshot(workspace_root))

    assert response.exit_code == 7
    assert response.stderr == "warning from cli"
    assert json.loads(response.raw_output)["decision"]["decision_type"] == "STOP_BLOCKED"


def test_nonzero_exit_without_stdout_returns_stop_blocked(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    def fake_run(command, **kwargs):  # noqa: ANN001
        return SimpleNamespace(stdout="", stderr="fatal cli error", returncode=2)

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fake_run)
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(enabled=True, allow_real_invocation=True, working_directory=str(Path.cwd()))
    )

    response = backend.invoke(_snapshot(workspace_root))

    assert response.exit_code == 2
    assert response.metadata["backend_error"] == "nonzero_exit_without_stdout"
    assert json.loads(response.raw_output)["decision"]["decision_type"] == "STOP_BLOCKED"


def test_timeout_is_captured_and_converted_to_stop_blocked(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    def fake_run(command, **kwargs):  # noqa: ANN001
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"], output="partial out", stderr="partial err")

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fake_run)
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(enabled=True, allow_real_invocation=True, working_directory=str(Path.cwd()))
    )

    response = backend.invoke(_snapshot(workspace_root))

    assert response.timed_out is True
    assert response.stdout == "partial out"
    assert response.stderr == "partial err"
    assert response.metadata["backend_error"] == "timeout"
    assert json.loads(response.raw_output)["decision"]["decision_type"] == "STOP_BLOCKED"


def test_max_output_chars_truncates_stdout_stderr_and_raw_output(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    def fake_run(command, **kwargs):  # noqa: ANN001
        return SimpleNamespace(stdout="x" * 100, stderr="y" * 100, returncode=0)

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fake_run)
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(
            enabled=True,
            allow_real_invocation=True,
            working_directory=str(Path.cwd()),
            max_output_chars=10,
        )
    )

    response = backend.invoke(_snapshot(workspace_root))

    assert response.stdout == "x" * 10
    assert response.stderr == "y" * 10
    assert response.raw_output == "x" * 10


def test_prompt_contains_contract_allowed_skills_and_safety_constraints(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    prompt = build_claude_cli_controller_prompt(_snapshot(workspace_root), build_default_skill_registry())

    assert "cli_controller_contract_v1" in prompt
    assert "retrieve_sources" in prompt
    assert "build_minimal_topic_to_evidence_report" in prompt
    assert "JSON only" in prompt
    assert "exactly one JSON object" in prompt
    assert "entire stdout must start with { and end with }" in prompt
    assert "Do not wrap the JSON in Markdown" in prompt
    assert "Do not use ```json fences" in prompt
    assert "json.loads(raw_stdout)" in prompt
    assert "UNPARSEABLE_OUTPUT" in prompt
    assert '"decision":{' in prompt
    assert "must be a JSON object" in prompt
    assert "Do not set decision to a string" in prompt
    assert "Must not execute skills" in prompt
    assert "Must not directly modify state.json, plan.md, or audit/artifact_manifest.json" in prompt
    assert "Must not access or modify databases" in prompt
    assert "Must not use shell commands" in prompt
    assert "Must not route raw retrieval artifacts into report generation" in prompt
    assert "build_landscape" in prompt
    assert "map_gaps" in prompt
    assert "generate_candidate_ideas" in prompt
    assert "screen_novelty_feasibility_risk" in prompt
    assert "novelty screening" in prompt


def test_detect_cli_output_format_issue_classifies_common_failures() -> None:
    assert detect_cli_output_format_issue('{"schema_version":"cli_controller_contract_v1"}') == "none"
    assert detect_cli_output_format_issue('```json\n{"schema_version":"cli_controller_contract_v1"}\n```') == "fenced_json"
    assert detect_cli_output_format_issue('Here is JSON:\n{"schema_version":"cli_controller_contract_v1"}') == "extra_text"
    assert detect_cli_output_format_issue("") == "empty_output"
    assert detect_cli_output_format_issue('{"type":"result","result":"{}"}') == "claude_wrapper_json"
    assert detect_cli_output_format_issue("[1, 2, 3]") == "unknown"


def test_real_backend_does_not_modify_workspace_or_execute_skill(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")

    def fake_run(command, **kwargs):  # noqa: ANN001
        return SimpleNamespace(stdout=_valid_envelope("task_123"), stderr="", returncode=0)

    monkeypatch.setattr("modules.research_agent_controller.claude_cli_invocation.subprocess.run", fake_run)
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(enabled=True, allow_real_invocation=True, working_directory=str(Path.cwd()))
    )

    backend.next_output(_snapshot(workspace_root))

    assert (workspace_root / "state.json").read_text(encoding="utf-8") == before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") == before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()


def test_response_round_trip() -> None:
    response = CliBackendResponse(
        raw_output="{}",
        stdout="{}",
        stderr="",
        exit_code=0,
        timed_out=False,
        duration_seconds=0.1,
        metadata={"ok": True},
    )

    assert CliBackendResponse.from_dict(response.as_dict()).as_dict() == response.as_dict()


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI integration test is opt-in only",
)
def test_optional_real_claude_cli_smoke_test_is_opt_in(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(
            enabled=True,
            allow_real_invocation=True,
            working_directory=str(Path.cwd()),
            timeout_seconds=30,
        )
    )

    response = backend.invoke(_snapshot(workspace_root))

    assert isinstance(response.raw_output, str)
