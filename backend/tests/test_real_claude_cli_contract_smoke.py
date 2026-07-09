import json
import os
from pathlib import Path

import pytest

from modules.research_agent_controller import (
    ClaudeCodeCliBackendConfig,
    CliWorkspaceAccessPolicy,
    RealClaudeCodeCliBackend,
    SkillRegistry,
    build_default_skill_registry,
    detect_cli_output_format_issue,
    parse_cli_output,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"


def _workspace(tmp_path: Path, task_id: str = "smoke_task") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        task_id,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n\n"
            "This is an opt-in real Claude CLI contract smoke test. "
            "Do not execute tools or modify workspace files.\n"
        ),
        plan_markdown=(
            "# Plan\n\n"
            "Return one bounded cli_controller_contract_v1 envelope. "
            "Prefer STOP_BLOCKED if a safe next action is uncertain.\n"
        ),
    )
    return tmp_path / "research_agent/research_tasks" / task_id


def _snapshot(workspace_root: Path) -> dict:
    return {
        "task_id": workspace_root.name,
        "workspace_root": str(workspace_root),
        "task_md": (workspace_root / "task.md").read_text(encoding="utf-8"),
        "plan_md": (workspace_root / "plan.md").read_text(encoding="utf-8"),
        "state": json.loads((workspace_root / "state.json").read_text(encoding="utf-8")),
        "artifact_manifest": json.loads((workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")),
        "recent_events": [],
        "step_index": 0,
    }


def _retrieve_only_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("retrieve_sources"))
    return registry


def _policy(workspace_root: Path) -> CliWorkspaceAccessPolicy:
    return CliWorkspaceAccessPolicy(
        task_id=workspace_root.name,
        workspace_root=str(workspace_root),
        allowed_read_paths=[
            "task.md",
            "plan.md",
            "state.json",
            "audit/artifact_manifest.json",
            "retrieval/",
        ],
        allowed_write_paths=["retrieval/"],
        forbidden_paths=[
            "state.json",
            "plan.md",
            "audit/artifact_manifest.json",
        ],
    )


def _preview(value: str, limit: int = 500) -> str:
    value = value.replace("\n", "\\n")
    return value[:limit]


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI smoke test is opt-in only",
)
def test_real_claude_cli_contract_smoke(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")
    registry = _retrieve_only_registry()

    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(
            enabled=True,
            allow_real_invocation=True,
            working_directory=str(Path.cwd()),
            timeout_seconds=int(os.getenv("REAL_CLAUDE_CLI_TIMEOUT_SECONDS", "60")),
            max_output_chars=20000,
        ),
        registry=registry,
    )

    response = backend.invoke(_snapshot(workspace_root))
    parse_result = parse_cli_output(response.raw_output, registry=registry, policy=_policy(workspace_root))

    decision_type = None
    skill_name = None
    if parse_result.decision is not None:
        decision_type = parse_result.decision.decision_type.value
        if parse_result.decision.skill_request is not None:
            skill_name = parse_result.decision.skill_request.skill_name

    summary = {
        "real_cli_invoked": response.metadata.get("backend_error") != "real_invocation_disabled",
        "exit_code": response.exit_code,
        "timed_out": response.timed_out,
        "stdout_chars": len(response.stdout or ""),
        "stderr_chars": len(response.stderr or ""),
        "parse_success": parse_result.decision is not None,
        "validation_success": parse_result.accepted,
        "decision_type": decision_type,
        "skill_name": skill_name,
        "violations": [violation.violation_type.value for violation in parse_result.violations],
        "format_issue": detect_cli_output_format_issue(response.raw_output or ""),
        "backend_error": response.metadata.get("backend_error"),
        "raw_output_preview": _preview(response.raw_output or ""),
    }
    print("REAL_CLAUDE_CLI_CONTRACT_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert response.raw_output
    assert (workspace_root / "state.json").read_text(encoding="utf-8") == before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") == before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
