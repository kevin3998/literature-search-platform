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
    build_explicit_landscape_plan,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_landscape_run_once_task"
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
FORBIDDEN_MARKDOWN_SECTIONS = [
    "## Research Gaps",
    "## Candidate Ideas",
    "## Novelty Screening",
    "## Experiment Plan",
    "## Manuscript Draft",
]


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    plan = build_explicit_landscape_plan(TASK_ID, TOPIC).as_dict()
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: explicit-landscape\n\n"
            "This is a one-step real Claude CLI landscape run_once smoke test. "
            "The only permitted platform skill execution is build_landscape.\n"
        ),
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_landscape_inputs(workspace_root)
    return workspace_root


def _write_landscape_inputs(workspace_root: Path) -> None:
    card = {
        "evidence_id": "ecard_001",
        "seed_id": "seed_001",
        "paper_id": "paper_001",
        "source": {
            "source_path": "paper_001/sections/results.md",
            "asset_type": "text",
            "section_id": "results",
            "locator": {"section": "Results"},
        },
        "primary_role": "mechanism",
        "secondary_roles": ["performance"],
        "normalized_statement": "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
        "verbatim_snippet": "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
        "entities": {
            "materials": ["alkaline HER catalysts"],
            "methods": ["oxygen vacancy engineering"],
            "metrics": ["HER activity"],
            "conditions": ["alkaline"],
            "characterization_tools": ["XPS"],
            "mechanisms": ["water dissociation", "hydrogen adsorption"],
        },
        "relations": [],
        "support": {"support_strength": "direct", "extraction_confidence": 0.8},
        "relevance": {"topic": TOPIC, "relevance_score": 0.91},
    }
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {"artifact_type": "evidence_cards", "stage": "enriched", "task_id": TASK_ID, "cards": [card]},
    )
    _write_json(
        workspace_root / "ranked_evidence/evidence_selection.json",
        {
            "artifact_type": "evidence_selection",
            "selected_cards": [card],
            "ranked_cards": [
                {
                    "rank": 1,
                    "evidence_id": "ecard_001",
                    "score": 0.91,
                    "score_components": {"relevance": 0.91},
                    "selected": True,
                    "selection_reasons": ["high_score"],
                    "card": card,
                }
            ],
            "warnings": ["dominant_paper_warning"],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/coverage_diagnostics.json",
        {
            "artifact_type": "coverage_diagnostics",
            "coverage": {
                "missing_required_roles": ["figure_evidence"],
                "source_type_coverage": {"text": 1},
            },
            "warnings": ["missing_figure_source_type"],
        },
    )
    _write_json(
        workspace_root / "reports/minimal_topic_to_evidence_report.json",
        {
            "artifact_type": "minimal_topic_to_evidence_report",
            "task_id": TASK_ID,
            "evidence_references": ["ecard_001"],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _landscape_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("build_landscape"))
    return registry


def _real_landscape_run_once_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
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
                    "topic": TOPIC,
                    "landscape_scope": "explicit_topic_landscape",
                    "require_evidence_ids": True,
                },
                "reason": "The explicit landscape plan has the required enriched and ranked evidence artifacts, so request the deterministic landscape wrapper.",
            },
            "artifact_refs": INPUT_ARTIFACTS,
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The only allowed next step is the explicit landscape step.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a one-step research controller run_once smoke test for explicit landscape.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = build_landscape.\n"
        "The workspace already has evidence/evidence_cards.enriched.json, ranked_evidence/evidence_selection.json, "
        "ranked_evidence/coverage_diagnostics.json, and reports/minimal_topic_to_evidence_report.json.\n"
        "Do not request retrieve_sources, create_evidence_seeds, extract_evidence_cards, enrich_evidence_cards, "
        "rank_evidence, report generation, gaps, ideas, experiments, claim ledger, or manuscript skills.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not execute the skill yourself. Do not generate landscape content yourself.\n"
        "Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Return only a cli_controller_contract_v1 envelope matching this shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI landscape run_once smoke test is opt-in only",
)
def test_real_claude_cli_landscape_one_step_run_once_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = _landscape_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _real_landscape_run_once_prompt,
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
    landscape = _read_json(workspace_root / "landscape/literature_landscape.json")
    diagnostics = _read_json(workspace_root / "landscape/landscape_coverage_diagnostics.json")
    markdown = (workspace_root / "landscape/literature_landscape.md").read_text(encoding="utf-8")
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    forbidden_present = [section for section in FORBIDDEN_MARKDOWN_SECTIONS if section in markdown]
    non_landscape_executed = [
        skill for skill in executed_skills
        if skill in {
            "retrieve_sources",
            "create_evidence_seeds",
            "extract_evidence_cards",
            "enrich_evidence_cards",
            "rank_evidence",
            "build_minimal_topic_to_evidence_report",
            "map_gaps",
            "generate_candidate_ideas",
            "screen_novelty_feasibility_risk",
            "create_experiment_matrix",
            "build_claim_ledger",
            "draft_manuscript_section",
        }
    ]
    summary = {
        "real_cli_invoked": response.metadata.get("backend_error") != "real_invocation_disabled",
        "exit_code": response.exit_code,
        "timed_out": response.timed_out,
        "format_issue": detect_cli_output_format_issue(response.raw_output or ""),
        "parse_success": parse_result.decision is not None if parse_result else False,
        "validation_success": parse_result.accepted if parse_result else False,
        "decision_type": decision.decision_type.value if decision else None,
        "skill_name": skill_name,
        "run_once_count": 1,
        "run_until_stop_called": False,
        "executed_skills": executed_skills,
        "non_landscape_executed": non_landscape_executed,
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")),
        "tool_calls_count": len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")),
        "validation_results_count": len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")),
        "state_status": state.get("status"),
        "plan_contains_build_landscape": "build_landscape" in plan_md,
        "landscape_schema_version": landscape.get("schema_version"),
        "landscape_evidence_ids": landscape.get("evidence_ids"),
        "landscape_cluster_count": len(landscape.get("clusters") or []),
        "markdown_contains_evidence_references": "## Evidence References" in markdown,
        "forbidden_markdown_sections": forbidden_present,
        "coverage_warnings": diagnostics.get("warnings"),
        "violations": [violation.violation_type.value for violation in parse_result.violations] if parse_result else [],
        "warnings": result.warnings,
        "controller_status": result.status.value,
    }
    print("REAL_CLAUDE_CLI_LANDSCAPE_RUN_ONCE_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert result.status == ControllerStepStatus.SUCCESS
    assert response is not None
    assert parse_result.accepted is True
    assert decision.decision_type.value == "CALL_TOOL"
    assert skill_name == "build_landscape"
    assert executed_skills == ["build_landscape"]
    assert non_landscape_executed == []
    assert output_artifacts == OUTPUT_ARTIFACTS
    for artifact_path in OUTPUT_ARTIFACTS:
        assert (workspace_root / artifact_path).exists()
        assert artifact_path in manifest_artifacts
    assert landscape["schema_version"] == "landscape_v1"
    assert landscape["evidence_ids"] == ["ecard_001"]
    assert landscape["clusters"]
    assert all(cluster["evidence_ids"] for cluster in landscape["clusters"])
    assert all(claim["evidence_ids"] for cluster in landscape["clusters"] for claim in cluster["representative_claims"])
    assert "## Evidence References" in markdown
    assert "ecard_001" in markdown
    assert "paper_001/sections/results.md" in markdown
    assert forbidden_present == []
    assert diagnostics["warnings"] == ["missing_figure_source_type", "dominant_paper_warning"]
    assert len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")) >= 1
    assert state["status"] == "running"
    assert "build_landscape" in state["completed_steps"]
    assert "build_landscape" in plan_md
    assert not (workspace_root / "gaps/gaps.json").exists()
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()
    assert not (workspace_root / "screening/idea_screening.json").exists()
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()
    assert not (workspace_root / "manuscript/section.md").exists()
