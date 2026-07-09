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
TASK_ID = "smoke_real_cli_landscape_decision_task"
INPUT_ARTIFACTS = [
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
    "reports/minimal_topic_to_evidence_report.json",
]
OUTPUT_ARTIFACTS = [
    "landscape/literature_landscape.json",
    "landscape/literature_landscape.md",
    "landscape/landscape_coverage_diagnostics.json",
]


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n\n"
            "This is a bounded landscape decision smoke test. The workspace already has enriched "
            "Evidence Cards, ranked evidence, coverage diagnostics, and a minimal topic-to-evidence report. "
            "Do not execute tools or modify workspace files.\n"
        ),
        plan_markdown=(
            "# Plan\n\n"
            "- retrieve_sources: completed\n"
            "- create_evidence_seeds: completed\n"
            "- extract_evidence_cards: completed\n"
            "- enrich_evidence_cards: completed\n"
            "- rank_evidence: completed\n"
            "- build_minimal_topic_to_evidence_report: completed\n"
            "- build_landscape: pending\n\n"
            "The next valid explicit step is build_landscape.\n"
        ),
    )
    _write_json(
        workspace_root=tmp_path / "research_agent/research_tasks" / TASK_ID,
        relative_path="evidence/evidence_cards.enriched.json",
        payload={"artifact_type": "evidence_cards", "stage": "enriched", "cards": []},
    )
    _write_json(
        workspace_root=tmp_path / "research_agent/research_tasks" / TASK_ID,
        relative_path="ranked_evidence/evidence_selection.json",
        payload={"artifact_type": "evidence_selection", "selected_cards": []},
    )
    _write_json(
        workspace_root=tmp_path / "research_agent/research_tasks" / TASK_ID,
        relative_path="ranked_evidence/coverage_diagnostics.json",
        payload={"artifact_type": "coverage_diagnostics", "coverage": {}, "warnings": []},
    )
    _write_json(
        workspace_root=tmp_path / "research_agent/research_tasks" / TASK_ID,
        relative_path="reports/minimal_topic_to_evidence_report.json",
        payload={"artifact_type": "minimal_topic_to_evidence_report", "evidence_references": []},
    )
    return tmp_path / "research_agent/research_tasks" / TASK_ID


def _write_json(workspace_root: Path, relative_path: str, payload: dict) -> None:
    path = workspace_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _snapshot(workspace_root: Path) -> dict:
    return {
        "task_id": workspace_root.name,
        "workspace_root": str(workspace_root),
        "task_md": (workspace_root / "task.md").read_text(encoding="utf-8"),
        "plan_md": (workspace_root / "plan.md").read_text(encoding="utf-8"),
        "state": json.loads((workspace_root / "state.json").read_text(encoding="utf-8")),
        "artifact_manifest": {
            "task_id": workspace_root.name,
            "artifacts": [
                {"artifact_id": path, "artifact_type": "input", "path": path}
                for path in INPUT_ARTIFACTS
            ],
            "cli_controller_ready": False,
        },
        "recent_events": [],
        "step_index": 0,
    }


def _landscape_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("build_landscape"))
    return registry


def _policy(workspace_root: Path) -> CliWorkspaceAccessPolicy:
    return CliWorkspaceAccessPolicy(
        task_id=TASK_ID,
        workspace_root=str(workspace_root),
        allowed_read_paths=[
            "task.md",
            "plan.md",
            "state.json",
            "audit/artifact_manifest.json",
            "evidence/",
            "ranked_evidence/",
            "reports/",
        ],
        allowed_write_paths=["landscape/"],
        forbidden_paths=["state.json", "plan.md", "audit/artifact_manifest.json"],
    )


def _preview(value: str, limit: int = 500) -> str:
    return value.replace("\n", "\\n")[:limit]


def _landscape_decision_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
    expected = {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_build_landscape",
            "skill_request": {
                "skill_name": "build_landscape",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "landscape_scope": "explicit_topic_landscape",
                    "require_evidence_ids": True,
                },
                "reason": (
                    "The explicit landscape plan has the required enriched and ranked evidence artifacts, "
                    "so the next bounded action is to build the landscape artifact."
                ),
            },
            "artifact_refs": INPUT_ARTIFACTS,
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The explicit landscape step should run after selected evidence and minimal report artifacts exist.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a bounded controller contract smoke test.\n"
        "You must output exactly one bare JSON object.\n"
        "Your entire stdout must start with { and end with }.\n"
        "Do not use Markdown. Do not use code fences. Do not include explanations.\n"
        "The workspace already has:\n"
        "- evidence/evidence_cards.enriched.json\n"
        "- ranked_evidence/evidence_selection.json\n"
        "- ranked_evidence/coverage_diagnostics.json\n"
        "- reports/minimal_topic_to_evidence_report.json\n"
        "The explicit landscape plan requires the next skill: build_landscape.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = build_landscape.\n"
        "Do not execute the skill.\n"
        "Do not generate landscape content.\n"
        "Do not generate gap map.\n"
        "Do not generate ideas.\n"
        "Do not generate novelty screening, experiment plan, or manuscript text.\n"
        "Do not modify files. Do not run shell commands. Do not access or mutate database.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Return only a cli_controller_contract_v1 envelope matching this exact intended shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI landscape decision smoke test is opt-in only",
)
def test_real_claude_cli_landscape_decision_contract_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")
    registry = _landscape_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _landscape_decision_prompt,
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
    if parse_result.decision is not None:
        decision_type = parse_result.decision.decision_type.value
        if parse_result.decision.skill_request is not None:
            request = parse_result.decision.skill_request
            skill_name = request.skill_name
            input_artifacts = request.input_artifacts
            output_artifacts = request.output_artifacts

    retrieval_input_present = any(path.startswith("retrieval/") for path in input_artifacts)
    p2_m9_requested = skill_name in {
        "map_gaps",
        "generate_candidate_ideas",
        "screen_novelty_feasibility_risk",
        "create_experiment_matrix",
        "build_claim_ledger",
        "draft_manuscript_section",
    }
    result = (
        "passed"
        if (
            parse_result.accepted
            and decision_type == "CALL_TOOL"
            and skill_name == "build_landscape"
            and not retrieval_input_present
            and output_artifacts == OUTPUT_ARTIFACTS
            and not p2_m9_requested
        )
        else "failed_expectation"
    )
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
        "retrieval_input_present": retrieval_input_present,
        "p2_m9_requested": p2_m9_requested,
        "violations": [violation.violation_type.value for violation in parse_result.violations],
        "result": result,
        "raw_output_preview": _preview(response.raw_output or ""),
    }
    print("REAL_CLAUDE_CLI_LANDSCAPE_DECISION_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert response.raw_output
    assert parse_result.accepted is True
    assert decision_type == "CALL_TOOL"
    assert skill_name == "build_landscape"
    assert input_artifacts == INPUT_ARTIFACTS
    assert output_artifacts == OUTPUT_ARTIFACTS
    assert retrieval_input_present is False
    assert p2_m9_requested is False
    assert (workspace_root / "state.json").read_text(encoding="utf-8") == before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") == before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
    assert not (workspace_root / "landscape/literature_landscape.json").exists()
