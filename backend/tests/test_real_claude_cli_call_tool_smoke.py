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
TASK_ID = "smoke_call_tool_task"


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n\n"
            "This is a CALL_TOOL contract smoke test. The workspace has no retrieval artifacts yet. "
            "Do not execute tools or modify workspace files.\n"
        ),
        plan_markdown=(
            "# Plan\n\n"
            "The next registered skill request should be retrieve_sources. "
            "Only return the cli_controller_contract_v1 envelope.\n"
        ),
    )
    return tmp_path / "research_agent/research_tasks" / TASK_ID


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
        task_id=TASK_ID,
        workspace_root=str(workspace_root),
        allowed_read_paths=["task.md", "plan.md", "state.json", "audit/artifact_manifest.json", "retrieval/"],
        allowed_write_paths=["retrieval/"],
        forbidden_paths=["state.json", "plan.md", "audit/artifact_manifest.json"],
    )


def _preview(value: str, limit: int = 500) -> str:
    return value.replace("\n", "\\n")[:limit]


def _call_tool_smoke_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
    expected = {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_retrieve_sources",
            "skill_request": {
                "skill_name": "retrieve_sources",
                "input_artifacts": [],
                "output_artifacts": [
                    "retrieval/source_candidate_packet.json",
                    "retrieval/retrieval_warnings.json",
                ],
                "parameters": {
                    "topic": TOPIC,
                    "task_profile_id": "topic-to-report",
                    "retrieval_budget": 5,
                },
                "reason": (
                    "The workspace has no retrieval artifact yet, so the next bounded action is to request "
                    "topic-scoped source retrieval."
                ),
            },
            "artifact_refs": [],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The first step in the minimal topic-to-evidence plan is retrieving source candidates.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a research agent controller contract smoke test.\n"
        "You must output exactly one bare JSON object.\n"
        "Your entire stdout must start with { and end with }.\n"
        "Do not use Markdown. Do not use code fences. Do not include explanations.\n"
        "Your task is to request the next registered skill.\n"
        "You must choose decision_type = CALL_TOOL.\n"
        "You must choose skill_name = retrieve_sources.\n"
        "Do not execute the skill. Do not run shell commands. Do not modify files.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Do not access or mutate databases.\n"
        "Return only a cli_controller_contract_v1 envelope.\n"
        "Use this exact structure and fill it as JSON, with decision as an object and skill_request present:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI CALL_TOOL smoke test is opt-in only",
)
def test_real_claude_cli_call_tool_contract_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")
    registry = _retrieve_only_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _call_tool_smoke_prompt,
    )

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
    input_artifacts = []
    output_artifacts = []
    parameters = {}
    if parse_result.decision is not None:
        decision_type = parse_result.decision.decision_type.value
        if parse_result.decision.skill_request is not None:
            request = parse_result.decision.skill_request
            skill_name = request.skill_name
            input_artifacts = request.input_artifacts
            output_artifacts = request.output_artifacts
            parameters = request.parameters

    result = "passed" if parse_result.accepted and decision_type == "CALL_TOOL" and skill_name == "retrieve_sources" else "failed_expectation"
    summary = {
        "real_cli_invoked": response.metadata.get("backend_error") != "real_invocation_disabled",
        "exit_code": response.exit_code,
        "timed_out": response.timed_out,
        "stdout_chars": len(response.stdout or ""),
        "stderr_chars": len(response.stderr or ""),
        "format_issue": detect_cli_output_format_issue(response.raw_output or ""),
        "parse_success": parse_result.decision is not None,
        "validation_success": parse_result.accepted,
        "decision_type": decision_type,
        "expected_decision_type": "CALL_TOOL",
        "skill_name": skill_name,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "parameters": parameters,
        "violations": [violation.violation_type.value for violation in parse_result.violations],
        "result": result,
        "raw_output_preview": _preview(response.raw_output or ""),
    }
    print("REAL_CLAUDE_CLI_CALL_TOOL_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert response.raw_output
    assert (workspace_root / "state.json").read_text(encoding="utf-8") == before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") == before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
