import json
import os
from pathlib import Path

import pytest

from screening_v2_helpers import ScriptedScreeningLLM

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ClaudeCodeCliBackendConfig,
    ControllerStepStatus,
    RealClaudeCodeCliBackend,
    SkillRegistry,
    build_default_skill_registry,
    build_explicit_screening_plan,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_agent_controller.skills.screening_contract import (
    SCREENING_OUTPUT_ARTIFACTS,
    SCREENING_REQUIRED_INPUT_ARTIFACTS,
)
from modules.research_agent_controller.skills.screening_tools import (
    FORBIDDEN_SCREENING_CLAIMS,
    validate_screening_artifact,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_screening_run_once_task"
OPTIONAL_INPUT_ARTIFACTS = [
    "ideas/candidate_ideas.md",
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]
INPUT_ARTIFACTS = SCREENING_REQUIRED_INPUT_ARTIFACTS + OPTIONAL_INPUT_ARTIFACTS
OUTPUT_ARTIFACTS = SCREENING_OUTPUT_ARTIFACTS
FORBIDDEN_SKILLS = {
    "retrieve_sources",
    "create_evidence_seeds",
    "extract_evidence_cards",
    "enrich_evidence_cards",
    "rank_evidence",
    "build_minimal_topic_to_evidence_report",
    "build_landscape",
    "map_gaps",
    "generate_candidate_ideas",
    "create_experiment_matrix",
    "build_claim_ledger",
    "draft_manuscript_section",
}
FORBIDDEN_MARKDOWN_SECTIONS = [
    "## Experiment Plan",
    "## Experimental Protocol",
    "## Manuscript Draft",
    "## Final Claims",
]


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    plan = build_explicit_screening_plan(TASK_ID, TOPIC).as_dict()
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: explicit-screening\n\n"
            "This is a one-step real Claude CLI screening run_once smoke test. "
            "The only permitted platform skill execution is screen_novelty_feasibility_risk.\n"
        ),
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_screening_inputs(workspace_root)
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


def _write_screening_inputs(workspace_root: Path) -> None:
    cards = [_card("ecard_001", "paper_001"), _card("ecard_002", "paper_002", role="performance")]
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {
            "artifact_type": "evidence_cards",
            "stage": "enriched",
            "task_id": TASK_ID,
            "topic": TOPIC,
            "cards": cards,
            "warnings": ["enriched_sparse_role_warning"],
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
            "landscape_id": "landscape_screening_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "landscape_axes": [{"axis_id": "mechanistic_role", "name": "Mechanistic Role"}],
            "clusters": [
                {
                    "cluster_id": "cluster_mechanism",
                    "title": "Mechanism Cluster",
                    "axis_values": {"mechanistic_role": "water dissociation"},
                    "evidence_ids": ["ecard_001"],
                    "source_paper_ids": ["paper_001"],
                    "representative_claims": [
                        {"claim": "Oxygen vacancies modulate water dissociation.", "evidence_ids": ["ecard_001"]}
                    ],
                    "warnings": [],
                }
            ],
            "coverage": {"coverage_warnings": ["landscape_sparse_cluster"]},
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "task_id": TASK_ID,
            "landscape_id": "landscape_screening_run_once",
            "coverage": {"coverage_warnings": ["landscape_sparse_cluster"]},
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_text(
        workspace_root / "landscape/literature_landscape.md",
        "# Literature Landscape\n\n## Evidence References\n\n- evidence_id=ecard_001; paper_id=paper_001\n",
    )
    _write_json(
        workspace_root / "gaps/gap_map.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "gap_map_id": "gap_map_screening_run_once",
            "landscape_id": "landscape_screening_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "gaps": [
                {
                    "gap_id": "gap_comparison_001",
                    "gap_type": "comparison_gap",
                    "title": "Limited comparison coverage for mechanistic role",
                    "description": "The selected evidence covers one observed mechanistic role.",
                    "basis": {
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "evidence_ids": ["ecard_001", "ecard_002"],
                        "coverage_warnings": ["landscape_sparse_cluster"],
                        "diagnostic_refs": ["axis_coverage:mechanistic_role"],
                    },
                    "not_an_idea": True,
                    "warnings": [],
                }
            ],
            "coverage": {"coverage_warnings": ["gap_sparse_axis_warning"]},
            "supporting_evidence": [
                {"evidence_id": "ecard_001", "paper_id": "paper_001", "gap_ids": ["gap_comparison_001"]},
                {"evidence_id": "ecard_002", "paper_id": "paper_002", "gap_ids": ["gap_comparison_001"]},
            ],
            "warnings": ["gap_sparse_axis_warning"],
            "schema_version": "gap_map_v1",
        },
    )
    _write_json(
        workspace_root / "gaps/gap_coverage_diagnostics.json",
        {
            "artifact_type": "gap_coverage_diagnostics",
            "task_id": TASK_ID,
            "gap_map_id": "gap_map_screening_run_once",
            "warnings": ["gap_sparse_axis_warning"],
            "schema_version": "gap_map_v1",
        },
    )
    _write_text(
        workspace_root / "gaps/gap_map.md",
        "# Gap Map\n\n## Evidence References\n\n- gap_id=gap_comparison_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "ideas/candidate_ideas.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "idea_set_id": "candidate_ideas_screening_run_once",
            "input_artifacts": [],
            "gap_map_id": "gap_map_screening_run_once",
            "landscape_id": "landscape_screening_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "ideas": [
                {
                    "idea_id": "idea_gap_comparison_001",
                    "title": "Candidate idea from comparison gap",
                    "summary": "This candidate direction is grounded in the comparison gap and requires screening.",
                    "idea_type": "comparative_study",
                    "gap_basis": {
                        "gap_ids": ["gap_comparison_001"],
                        "gap_types": ["comparison_gap"],
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "evidence_ids": ["ecard_001", "ecard_002"],
                        "coverage_warnings": ["landscape_sparse_cluster"],
                        "diagnostic_refs": ["axis_coverage:mechanistic_role"],
                    },
                    "evidence_basis": {
                        "supporting_evidence_ids": ["ecard_001", "ecard_002"],
                        "source_paper_ids": ["paper_001", "paper_002"],
                        "representative_claim_refs": ["landscape:cluster_mechanism:claim_1"],
                    },
                    "rationale": "The idea is grounded in gap_comparison_001 and selected evidence.",
                    "expected_contribution": "Clarify a documented comparison gap after downstream checks.",
                    "assumptions": ["Evidence coverage is sparse."],
                    "constraints": ["Requires external novelty search.", "Requires expert feasibility review."],
                    "not_yet_screened": True,
                    "requires_novelty_screening": True,
                    "requires_feasibility_screening": True,
                    "warnings": ["idea_sparse_support_warning"],
                }
            ],
            "generation_scope": {"source": "validated_gap_records"},
            "constraints": {"not_yet_screened": True},
            "limitations": ["Candidate ideas are unscreened."],
            "warnings": ["gap_sparse_axis_warning", "landscape_sparse_cluster", "missing_figure_source_type"],
            "created_at": 0,
            "schema_version": "candidate_ideas_v1",
        },
    )
    _write_json(
        workspace_root / "ideas/idea_generation_diagnostics.json",
        {
            "artifact_type": "idea_generation_diagnostics",
            "idea_set_id": "candidate_ideas_screening_run_once",
            "num_input_gaps": 1,
            "num_generated_ideas": 1,
            "warnings": ["idea_generation_sparse_fixture"],
            "downstream_screening_required": True,
            "schema_version": "candidate_ideas_v1",
        },
    )
    _write_text(
        workspace_root / "ideas/candidate_ideas.md",
        "# Candidate Ideas\n\n## Evidence References\n\n- idea_id=idea_gap_comparison_001; gap_id=gap_comparison_001; evidence_id=ecard_001\n",
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


def _screening_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("screen_novelty_feasibility_risk"))
    return registry


def _real_screening_run_once_prompt(
    snapshot: dict,
    registry: SkillRegistry | None = None,
    contract: dict | None = None,
) -> str:
    expected = {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_screen_novelty_feasibility_risk",
            "skill_request": {
                "skill_name": "screen_novelty_feasibility_risk",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "topic": TOPIC,
                    "screening_scope": "explicit_candidate_idea_screening",
                    "require_gap_and_evidence_basis": True,
                    "forbid_experiment_plan": True,
                    "forbid_final_claims": True,
                    "preserve_unscreened_candidate_boundaries": True,
                },
                "reason": "The explicit screening plan has required candidate ideas, gap, landscape, evidence, and diagnostics artifacts, so request the deterministic screening wrapper.",
            },
            "artifact_refs": [
                "ideas/candidate_ideas.json",
                "ideas/idea_generation_diagnostics.json",
                "gaps/gap_map.json",
                "landscape/literature_landscape.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The only allowed next step is explicit screening.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a one-step research controller run_once smoke test for explicit screening.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = screen_novelty_feasibility_risk.\n"
        "The workspace already has ideas/candidate_ideas.json, ideas/idea_generation_diagnostics.json, "
        "ideas/candidate_ideas.md, gaps/gap_map.json, gaps/gap_coverage_diagnostics.json, gaps/gap_map.md, "
        "landscape/literature_landscape.json, landscape/landscape_coverage_diagnostics.json, "
        "landscape/literature_landscape.md, evidence/evidence_cards.enriched.json, "
        "ranked_evidence/evidence_selection.json, ranked_evidence/coverage_diagnostics.json, and "
        "reports/minimal_topic_to_evidence_report.json.\n"
        "Do not request retrieve_sources, create_evidence_seeds, extract_evidence_cards, enrich_evidence_cards, "
        "rank_evidence, report generation, build_landscape, map_gaps, generate_candidate_ideas, experiments, "
        "claim ledger, or manuscript skills.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not execute the skill yourself. Do not generate screening content yourself.\n"
        "Do not claim novelty is proven. Do not claim feasibility is proven. Do not finalize risk.\n"
        "Do not generate experiment plan, experimental protocol, manuscript content, or final claims.\n"
        "Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Return only a cli_controller_contract_v1 envelope matching this shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI screening run_once smoke test is opt-in only",
)
def test_real_claude_cli_screening_one_step_run_once_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = _screening_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _real_screening_run_once_prompt,
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
        llm_client=ScriptedScreeningLLM(),
        max_steps=1,
    )

    result = controller.run_once()

    response = backend.last_response
    parse_result = result.parse_result
    decision = parse_result.decision if parse_result else None
    skill_name = decision.skill_request.skill_name if decision and decision.skill_request else None
    input_artifacts = decision.skill_request.input_artifacts if decision and decision.skill_request else []
    output_artifacts = result.skill_result.output_artifacts if result.skill_result else []
    executed_skills = []
    if (workspace_root / "logs/tool_calls.jsonl").exists():
        executed_skills = [event.get("skill_name") for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")]
    manifest_artifacts = [item["path"] for item in _read_json(workspace_root / "audit/artifact_manifest.json")["artifacts"]]
    screening = _read_json(workspace_root / "screening/idea_screening_results.json")
    diagnostics = _read_json(workspace_root / "screening/screening_diagnostics.json")
    markdown = (workspace_root / "screening/idea_screening_results.md").read_text(encoding="utf-8")
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    screened_ideas = screening.get("screened_ideas") or []
    forbidden_executed = [skill for skill in executed_skills if skill in FORBIDDEN_SKILLS]
    forbidden_sections = [section for section in FORBIDDEN_MARKDOWN_SECTIONS if section in markdown]
    claim_text = "\n".join(
        [
            markdown,
            json.dumps(screening.get("screening_scope", {}), ensure_ascii=False),
            json.dumps(screening.get("limitations", []), ensure_ascii=False),
            json.dumps(screening.get("screening_policy", {}), ensure_ascii=False),
        ]
    ).lower()
    forbidden_claims = [phrase for phrase in FORBIDDEN_SCREENING_CLAIMS if phrase in claim_text]
    validation_errors = validate_screening_artifact(screening, markdown)
    every_idea_has_id = all(idea.get("idea_id") for idea in screened_ideas)
    every_idea_has_gap_ids = all(idea.get("gap_ids") for idea in screened_ideas)
    every_idea_has_evidence_ids = all(idea.get("evidence_ids") for idea in screened_ideas)
    every_novelty_has_basis = all(
        idea.get("local_novelty_triage", {}).get("rationale") and idea.get("local_novelty_triage", {}).get("limitations")
        for idea in screened_ideas
    )
    every_feasibility_has_basis = all(
        idea.get("feasibility_triage", {}).get("rationale")
        for idea in screened_ideas
    )
    every_risk_has_basis = all(
        idea.get("risk_triage", {}).get("risk_factors") and idea.get("risk_triage", {}).get("rationale")
        for idea in screened_ideas
    )
    novelty_statuses = [idea.get("local_novelty_triage", {}).get("judgment") for idea in screened_ideas]
    feasibility_statuses = [idea.get("feasibility_triage", {}).get("judgment") for idea in screened_ideas]
    risk_statuses = [idea.get("risk_triage", {}).get("judgment") for idea in screened_ideas]
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
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")),
        "tool_calls_count": len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")),
        "validation_results_count": len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")),
        "state_status": state.get("status"),
        "plan_contains_screening": "screen_novelty_feasibility_risk" in plan_md,
        "screening_schema_version": screening.get("schema_version"),
        "screening_id": screening.get("screening_id"),
        "idea_set_id": screening.get("idea_set_id"),
        "gap_map_id": screening.get("gap_map_id"),
        "landscape_id": screening.get("landscape_id"),
        "evidence_ids": screening.get("evidence_ids"),
        "screened_idea_count": len(screened_ideas),
        "every_idea_has_id": every_idea_has_id,
        "every_idea_has_gap_ids": every_idea_has_gap_ids,
        "every_idea_has_evidence_ids": every_idea_has_evidence_ids,
        "every_novelty_has_basis_or_limitations": every_novelty_has_basis,
        "every_feasibility_has_basis_or_limitations": every_feasibility_has_basis,
        "every_risk_has_basis_or_limitations": every_risk_has_basis,
        "novelty_statuses": novelty_statuses,
        "feasibility_statuses": feasibility_statuses,
        "risk_statuses": risk_statuses,
        "markdown_contains_evidence_references": "## Evidence References" in markdown,
        "forbidden_markdown_sections": forbidden_sections,
        "forbidden_claims": forbidden_claims,
        "screening_validation_errors": validation_errors,
        "diagnostics_warnings": diagnostics.get("warnings"),
        "violations": [violation.violation_type.value for violation in parse_result.violations] if parse_result else [],
        "warnings": result.warnings,
        "controller_status": result.status.value,
    }
    print("REAL_CLAUDE_CLI_SCREENING_RUN_ONCE_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert result.status == ControllerStepStatus.SUCCESS
    assert response is not None
    assert parse_result.accepted is True
    assert decision.decision_type.value == "CALL_TOOL"
    assert skill_name == "screen_novelty_feasibility_risk"
    assert input_artifacts == INPUT_ARTIFACTS
    assert executed_skills == ["screen_novelty_feasibility_risk"]
    assert forbidden_executed == []
    assert output_artifacts == OUTPUT_ARTIFACTS
    for artifact_path in OUTPUT_ARTIFACTS:
        assert (workspace_root / artifact_path).exists()
        assert artifact_path in manifest_artifacts
    assert screening["schema_version"] == "idea_screening_v2"
    assert screening["analysis_mode"] == "llm_assisted_local_evidence_triage"
    assert screening["screening_id"]
    assert screening["idea_set_id"] == "candidate_ideas_screening_run_once"
    assert screening["gap_map_id"] == "gap_map_screening_run_once"
    assert screening["landscape_id"] == "landscape_screening_run_once"
    assert screening["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert screened_ideas
    assert every_idea_has_id is True
    assert every_idea_has_gap_ids is True
    assert every_idea_has_evidence_ids is True
    assert every_novelty_has_basis is True
    assert every_feasibility_has_basis is True
    assert every_risk_has_basis is True
    assert set(novelty_statuses).issubset(
        {
            "likely_distinct_from_local_evidence",
            "partial_overlap_with_local_evidence",
            "likely_overlapping_local_prior",
            "insufficient_local_evidence",
        }
    )
    assert set(feasibility_statuses).issubset(
        {"locally_supported", "partially_supported", "weakly_supported", "under_specified", "insufficient_evidence"}
    )
    assert set(risk_statuses).issubset(
        {
            "low_information_risk",
            "evidence_gap_risk",
            "mechanism_risk",
            "synthesis_risk",
            "characterization_risk",
            "scope_risk",
            "mixed_risk",
        }
    )
    assert all(idea["not_an_experiment_plan"] is True for idea in screened_ideas)
    assert all(idea["not_a_validated_claim"] is True for idea in screened_ideas)
    assert "gap_sparse_axis_warning" in screening["warnings"]
    assert "landscape_sparse_cluster" in screening["warnings"]
    assert "missing_figure_source_type" in screening["warnings"]
    assert diagnostics["num_input_ideas"] == 1
    assert diagnostics["num_screened_ideas"] == 1
    assert diagnostics["external_novelty_search_performed"] is False
    assert diagnostics["expert_feasibility_review_performed"] is False
    assert diagnostics["risk_review_performed"] is False
    assert diagnostics["forbidden_claim_checks"]["passed"] is True
    assert "## Evidence References" in markdown
    assert forbidden_sections == []
    assert forbidden_claims == []
    assert validation_errors == []
    assert len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")) >= 1
    assert state["status"] == "running"
    assert "screen_novelty_feasibility_risk" in state["completed_steps"]
    assert "screening/idea_screening_results.json" in state["artifact_index"]
    assert "screen_novelty_feasibility_risk" in plan_md
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()
    assert not (workspace_root / "manuscript/section.md").exists()
