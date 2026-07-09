import json
import os
from pathlib import Path

import pytest

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ClaudeCodeCliBackendConfig,
    ControllerStepStatus,
    RealClaudeCodeCliBackend,
    SkillRegistry,
    build_default_skill_registry,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_run_once_task"


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n\n"
            "This is a one-step real Claude CLI run_once smoke test. "
            "The only permitted skill request is retrieve_sources.\n"
        ),
        plan_markdown=(
            "# Plan\n\n"
            "Step 1: request retrieve_sources only. Do not request any other skill. "
            "The platform will execute at most one run_once step.\n"
        ),
    )
    return tmp_path / "research_agent/research_tasks" / TASK_ID


def _retrieve_only_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("retrieve_sources"))
    return registry


def _real_run_once_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
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
                "reason": "The workspace has no retrieval artifacts, so request topic-scoped source retrieval.",
            },
            "artifact_refs": [],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The only allowed next step is retrieving source candidates.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a one-step research controller run_once smoke test.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = retrieve_sources.\n"
        "Do not request create_evidence_seeds, extract_evidence_cards, enrich_evidence_cards, rank_evidence, "
        "report generation, landscape, gaps, ideas, experiments, claim ledger, or manuscript skills.\n"
        "Do not execute the skill yourself. Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Return only a cli_controller_contract_v1 envelope matching this shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


def _fake_acquire_evidence(query: str, has_history: bool = False, **options: object) -> dict:
    _fake_acquire_evidence.calls.append(
        {
            "query": query,
            "has_history": has_history,
            "options": dict(options),
        }
    )
    return {
        "evidence_candidates": [
            {
                "evidence_id": "src_001",
                "source_evidence_id": "src_001",
                "paper_id": "paper_001",
                "title": "Oxygen vacancy engineering for alkaline HER catalysts",
                "doi": "10.0000/example",
                "year": 2024,
                "journal": "Example Journal",
                "kind": "text",
                "snippet": (
                    "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts."
                ),
                "source_path": "paper_001/sections/results.md",
                "source_locator": {"section": "Results"},
                "section_id": "results",
                "chunk_index": 0,
                "asset_type": "text",
                "relevance_score": 0.91,
            }
        ],
        "expanded_assets": [],
        "query_plan": {"query": query},
        "coverage": {"limit": options.get("limit")},
        "breadth": {"has_history": has_history},
        "warnings": ["fake_acquire_evidence_used"],
    }


_fake_acquire_evidence.calls = []


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI one-step run_once smoke test is opt-in only",
)
def test_real_claude_cli_one_step_run_once_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = _retrieve_only_registry()
    _fake_acquire_evidence.calls = []
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _real_run_once_prompt,
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
    controller = ClaudeCodeBackedMinimalController(
        workspace_root=workspace_root,
        task_id=TASK_ID,
        cli_backend=backend,
        registry=registry,
        max_steps=1,
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    result = controller.run_once()

    response = backend.last_response
    parse_result = result.parse_result
    decision = parse_result.decision if parse_result else None
    skill_name = decision.skill_request.skill_name if decision and decision.skill_request else None
    executed_skills = []
    if (workspace_root / "logs/tool_calls.jsonl").exists():
        executed_skills = [event.get("skill_name") for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")]
    manifest_artifacts = [item["path"] for item in _read_json(workspace_root / "audit/artifact_manifest.json")["artifacts"]]
    output_artifacts = result.skill_result.output_artifacts if result.skill_result else []
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    summary = {
        "real_cli_invoked": response.metadata.get("backend_error") != "real_invocation_disabled",
        "exit_code": response.exit_code,
        "timed_out": response.timed_out,
        "format_issue": detect_cli_output_format_issue(response.raw_output or ""),
        "parse_success": parse_result.decision is not None if parse_result else False,
        "validation_success": parse_result.accepted if parse_result else False,
        "decision_type": decision.decision_type.value if decision else None,
        "skill_name": skill_name,
        "run_once_executed": True,
        "executed_skills": executed_skills,
        "fake_acquire_evidence_called": bool(_fake_acquire_evidence.calls),
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")),
        "tool_calls_count": len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")),
        "validation_results_count": len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")),
        "state_status": state.get("status"),
        "plan_step_status": "retrieve_sources" if "retrieve_sources" in plan_md else None,
        "violations": [violation.violation_type.value for violation in parse_result.violations] if parse_result else [],
        "warnings": result.warnings,
        "controller_status": result.status.value,
    }
    print("REAL_CLAUDE_CLI_ONE_STEP_RUN_ONCE_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert result.status == ControllerStepStatus.SUCCESS
    assert response is not None
    assert parse_result.accepted is True
    assert decision.decision_type.value == "CALL_TOOL"
    assert skill_name == "retrieve_sources"
    assert executed_skills == ["retrieve_sources"]
    assert bool(_fake_acquire_evidence.calls) is True
    assert "retrieval/source_candidate_packet.json" in output_artifacts
    assert "retrieval/retrieval_warnings.json" in output_artifacts
    assert (workspace_root / "retrieval/source_candidate_packet.json").exists()
    assert (workspace_root / "retrieval/retrieval_warnings.json").exists()
    assert "retrieval/source_candidate_packet.json" in manifest_artifacts
    assert "retrieval/retrieval_warnings.json" in manifest_artifacts
    assert len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")) >= 1
    assert state["status"] == "running"
    assert "retrieve_sources" in state["completed_steps"]
    assert "retrieve_sources" in plan_md
    assert not (workspace_root / "evidence/evidence_card_seeds.json").exists()
    assert not (workspace_root / "evidence/evidence_cards.initial.json").exists()
    assert not (workspace_root / "reports/minimal_topic_to_evidence_report.md").exists()
