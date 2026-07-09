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
    build_explicit_gap_mapping_plan,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_gap_mapping_run_once_task"
INPUT_ARTIFACTS = [
    "landscape/literature_landscape.json",
    "landscape/landscape_coverage_diagnostics.json",
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]
REQUIRED_INPUT_ARTIFACTS = [
    "landscape/literature_landscape.json",
    "landscape/landscape_coverage_diagnostics.json",
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
]
OUTPUT_ARTIFACTS = [
    "gaps/gap_map.json",
    "gaps/gap_map.md",
    "gaps/gap_coverage_diagnostics.json",
]
FORBIDDEN_MARKDOWN_SECTIONS = [
    "## Candidate Ideas",
    "## Proposed Research Directions",
    "## Novelty Screening",
    "## Feasibility Screening",
    "## Experiment Plan",
    "## Manuscript Draft",
]
FORBIDDEN_SKILLS = {
    "retrieve_sources",
    "create_evidence_seeds",
    "extract_evidence_cards",
    "enrich_evidence_cards",
    "rank_evidence",
    "build_minimal_topic_to_evidence_report",
    "build_landscape",
    "generate_candidate_ideas",
    "screen_novelty_feasibility_risk",
    "create_experiment_matrix",
    "build_claim_ledger",
    "draft_manuscript_section",
}


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    plan = build_explicit_gap_mapping_plan(TASK_ID, TOPIC).as_dict()
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: explicit-gap-mapping\n\n"
            "This is a one-step real Claude CLI gap mapping run_once smoke test. "
            "The only permitted platform skill execution is map_gaps.\n"
        ),
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_gap_inputs(workspace_root)
    return workspace_root


def _card(evidence_id: str, paper_id: str, *, role: str = "mechanism") -> dict:
    return {
        "evidence_id": evidence_id,
        "seed_id": f"seed_{evidence_id}",
        "paper_id": paper_id,
        "source": {
            "source_path": f"{paper_id}/sections/results.md",
            "asset_type": "text",
            "section_id": "results",
            "locator": {"section": "Results"},
        },
        "primary_role": role,
        "secondary_roles": ["performance"],
        "normalized_statement": "Oxygen vacancies modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
        "verbatim_snippet": "Oxygen vacancies modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
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


def _write_gap_inputs(workspace_root: Path) -> None:
    cards = [_card("ecard_001", "paper_001"), _card("ecard_002", "paper_001", role="performance")]
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {
            "artifact_type": "evidence_cards",
            "stage": "enriched",
            "task_id": TASK_ID,
            "topic": TOPIC,
            "cards": cards,
            "warnings": [],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/evidence_selection.json",
        {
            "artifact_type": "evidence_selection",
            "selected_cards": cards,
            "ranked_cards": [
                {
                    "rank": index + 1,
                    "evidence_id": card["evidence_id"],
                    "score": 0.9 - index * 0.1,
                    "score_components": {"relevance": 0.9 - index * 0.1},
                    "selected": True,
                    "selection_reasons": ["high_score"],
                    "card": card,
                }
                for index, card in enumerate(cards)
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
                "source_type_coverage": {"text": 2},
                "role_distribution": {"mechanism": 1, "performance": 1},
            },
            "warnings": ["missing_figure_source_type"],
        },
    )
    _write_json(
        workspace_root / "landscape/literature_landscape.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "landscape_id": "landscape_gap_run_once",
            "input_artifacts": [
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001"],
            "landscape_axes": [
                {
                    "axis_id": "mechanistic_role",
                    "name": "Mechanistic Role",
                    "description": "Mechanistic roles represented in evidence.",
                    "values": ["water dissociation"],
                }
            ],
            "clusters": [
                {
                    "cluster_id": "cluster_mechanism",
                    "title": "Mechanism Cluster",
                    "description": "Sparse mechanism evidence.",
                    "axis_values": {"mechanistic_role": "water dissociation"},
                    "evidence_ids": ["ecard_001"],
                    "source_paper_ids": ["paper_001"],
                    "representative_claims": [
                        {"claim": "Oxygen vacancies modulate water dissociation.", "evidence_ids": ["ecard_001"]}
                    ],
                    "confidence": "medium",
                    "warnings": [],
                }
            ],
            "coverage": {
                "num_landscape_clusters": 1,
                "num_evidence_cards": 2,
                "num_selected_evidence": 2,
                "num_source_papers": 1,
                "source_type_distribution": {"text": 2},
                "role_distribution": {"mechanism": 1, "performance": 1},
                "missing_roles": ["figure_evidence"],
                "dominant_source_warning": True,
                "coverage_warnings": ["landscape_sparse_cluster"],
            },
            "representative_evidence": [],
            "limitations": [],
            "warnings": ["landscape_sparse_cluster"],
            "created_at": 0,
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "task_id": TASK_ID,
            "landscape_id": "landscape_gap_run_once",
            "coverage": {
                "missing_roles": ["figure_evidence"],
                "dominant_source_warning": True,
                "coverage_warnings": ["landscape_sparse_cluster"],
            },
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_text(
        workspace_root / "landscape/literature_landscape.md",
        "# Literature Landscape\n\n## Evidence References\n\n- evidence_id=ecard_001; paper_id=paper_001\n",
    )
    _write_json(
        workspace_root / "reports/minimal_topic_to_evidence_report.json",
        {
            "artifact_type": "minimal_topic_to_evidence_report",
            "scope": "minimal_topic_to_evidence",
            "evidence_references": ["ecard_001", "ecard_002"],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _gap_mapping_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("map_gaps"))
    return registry


def _real_gap_mapping_run_once_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
    expected = {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_map_gaps",
            "skill_request": {
                "skill_name": "map_gaps",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "topic": TOPIC,
                    "gap_mapping_scope": "explicit_topic_gap_map",
                    "require_evidence_basis": True,
                    "forbid_candidate_ideas": True,
                },
                "reason": "The explicit gap mapping plan has the required landscape and evidence artifacts, so request the deterministic gap mapping wrapper.",
            },
            "artifact_refs": REQUIRED_INPUT_ARTIFACTS,
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The only allowed next step is the explicit gap mapping step.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a one-step research controller run_once smoke test for explicit gap mapping.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = map_gaps.\n"
        "The workspace already has landscape/literature_landscape.json, "
        "landscape/landscape_coverage_diagnostics.json, landscape/literature_landscape.md, "
        "evidence/evidence_cards.enriched.json, ranked_evidence/evidence_selection.json, "
        "ranked_evidence/coverage_diagnostics.json, and reports/minimal_topic_to_evidence_report.json.\n"
        "Do not request retrieve_sources, create_evidence_seeds, extract_evidence_cards, enrich_evidence_cards, "
        "rank_evidence, report generation, build_landscape, ideas, novelty screening, experiments, claim ledger, "
        "or manuscript skills.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not execute the skill yourself. Do not generate gap content yourself.\n"
        "Do not generate candidate ideas, novelty screening, feasibility screening, experiment plans, or manuscript text.\n"
        "Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Return only a cli_controller_contract_v1 envelope matching this shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI gap mapping run_once smoke test is opt-in only",
)
def test_real_claude_cli_gap_mapping_one_step_run_once_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = _gap_mapping_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _real_gap_mapping_run_once_prompt,
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
    gap_map = _read_json(workspace_root / "gaps/gap_map.json")
    diagnostics = _read_json(workspace_root / "gaps/gap_coverage_diagnostics.json")
    markdown = (workspace_root / "gaps/gap_map.md").read_text(encoding="utf-8")
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    gap_ids = {gap["gap_id"] for gap in gap_map.get("gaps") or []}
    forbidden_present = [section for section in FORBIDDEN_MARKDOWN_SECTIONS if section in markdown]
    forbidden_executed = [skill for skill in executed_skills if skill in FORBIDDEN_SKILLS]
    supporting_evidence_valid = all(
        set(item.get("gap_ids") or []).issubset(gap_ids) and item.get("gap_ids")
        for item in gap_map.get("supporting_evidence") or []
    )
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
        "forbidden_executed": forbidden_executed,
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")),
        "tool_calls_count": len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")),
        "validation_results_count": len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")),
        "state_status": state.get("status"),
        "plan_contains_map_gaps": "map_gaps" in plan_md,
        "gap_schema_version": gap_map.get("schema_version"),
        "landscape_id": gap_map.get("landscape_id"),
        "evidence_ids": gap_map.get("evidence_ids"),
        "gap_count": len(gap_map.get("gaps") or []),
        "every_gap_has_basis": all(gap.get("basis") for gap in gap_map.get("gaps") or []),
        "every_gap_not_an_idea": all(gap.get("not_an_idea") is True for gap in gap_map.get("gaps") or []),
        "supporting_evidence_valid": supporting_evidence_valid,
        "markdown_contains_evidence_references": "## Evidence References" in markdown,
        "forbidden_markdown_sections": forbidden_present,
        "coverage_warnings": diagnostics.get("warnings"),
        "violations": [violation.violation_type.value for violation in parse_result.violations] if parse_result else [],
        "warnings": result.warnings,
        "controller_status": result.status.value,
    }
    print("REAL_CLAUDE_CLI_GAP_MAPPING_RUN_ONCE_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert result.status == ControllerStepStatus.SUCCESS
    assert response is not None
    assert parse_result.accepted is True
    assert decision.decision_type.value == "CALL_TOOL"
    assert skill_name == "map_gaps"
    assert executed_skills == ["map_gaps"]
    assert forbidden_executed == []
    assert output_artifacts == OUTPUT_ARTIFACTS
    for artifact_path in OUTPUT_ARTIFACTS:
        assert (workspace_root / artifact_path).exists()
        assert artifact_path in manifest_artifacts
    assert gap_map["schema_version"] == "gap_map_v1"
    assert gap_map["landscape_id"]
    assert gap_map["evidence_ids"]
    assert gap_map["gaps"]
    assert all(gap["basis"] for gap in gap_map["gaps"])
    assert all(gap["not_an_idea"] is True for gap in gap_map["gaps"])
    assert supporting_evidence_valid is True
    assert "## Evidence References" in markdown
    assert forbidden_present == []
    assert "landscape_sparse_cluster" in gap_map["warnings"]
    assert "missing_figure_source_type" in gap_map["warnings"]
    assert diagnostics["warnings"]
    assert len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")) >= 1
    assert state["status"] == "running"
    assert "map_gaps" in state["completed_steps"]
    assert "gaps/gap_map.json" in state["artifact_index"]
    assert "map_gaps" in plan_md
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()
    assert not (workspace_root / "screening/idea_screening.json").exists()
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()
    assert not (workspace_root / "manuscript/section.md").exists()
