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
    build_explicit_idea_generation_plan,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_agent_controller.skills.idea_contract import (
    IDEA_OUTPUT_ARTIFACTS,
    IDEA_REQUIRED_INPUT_ARTIFACTS,
)
from modules.research_agent_controller.skills.idea_tools import validate_candidate_ideas_artifact
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_idea_generation_run_once_task"
OPTIONAL_INPUT_ARTIFACTS = [
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]
INPUT_ARTIFACTS = IDEA_REQUIRED_INPUT_ARTIFACTS + OPTIONAL_INPUT_ARTIFACTS
OUTPUT_ARTIFACTS = IDEA_OUTPUT_ARTIFACTS
FORBIDDEN_MARKDOWN_SECTIONS = [
    "## Novelty Screening",
    "## Feasibility Screening",
    "## Risk Screening",
    "## Experiment Plan",
    "## Manuscript Draft",
]
FORBIDDEN_CLAIM_PHRASES = [
    "is novel",
    "is feasible",
    "has been validated",
    "experimentally validated",
    "will improve",
    "will enhance",
    "proves that",
    "confirms that",
    "should be synthesized",
    "should be tested",
]
FORBIDDEN_SKILLS = {
    "retrieve_sources",
    "create_evidence_seeds",
    "extract_evidence_cards",
    "enrich_evidence_cards",
    "rank_evidence",
    "build_minimal_topic_to_evidence_report",
    "build_landscape",
    "map_gaps",
    "screen_novelty_feasibility_risk",
    "create_experiment_matrix",
    "build_claim_ledger",
    "draft_manuscript_section",
}


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    plan = build_explicit_idea_generation_plan(TASK_ID, TOPIC).as_dict()
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: explicit-idea-generation\n\n"
            "This is a one-step real Claude CLI idea generation run_once smoke test. "
            "The only permitted platform skill execution is generate_candidate_ideas.\n"
        ),
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_idea_inputs(workspace_root)
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


def _write_idea_inputs(workspace_root: Path) -> None:
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
            "landscape_id": "landscape_idea_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "landscape_axes": [
                {
                    "axis_id": "mechanistic_role",
                    "name": "Mechanistic Role",
                    "values": ["water dissociation"],
                }
            ],
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
            "coverage": {
                "num_landscape_clusters": 1,
                "num_evidence_cards": 2,
                "num_selected_evidence": 2,
                "num_source_papers": 2,
                "coverage_warnings": ["landscape_sparse_cluster"],
            },
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "task_id": TASK_ID,
            "landscape_id": "landscape_idea_run_once",
            "coverage": {"coverage_warnings": ["landscape_sparse_cluster"]},
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_text(
        workspace_root / "landscape/literature_landscape.md",
        "# Literature Landscape\n\n## Evidence References\n\n- evidence_id=ecard_001; paper_id=paper_001\n",
    )
    gap_map = {
        "task_id": TASK_ID,
        "topic": TOPIC,
        "gap_map_id": "gap_map_idea_run_once",
        "input_artifacts": [
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        "landscape_id": "landscape_idea_run_once",
        "evidence_ids": ["ecard_001", "ecard_002"],
        "source_paper_ids": ["paper_001", "paper_002"],
        "gap_axes": [],
        "gaps": [
            {
                "gap_id": "gap_comparison_001",
                "gap_type": "comparison_gap",
                "title": "Limited comparison coverage for mechanistic role",
                "description": "The selected evidence covers one observed mechanistic role.",
                "axis_values": {"mechanistic_role": ["water dissociation"]},
                "basis": {
                    "landscape_cluster_ids": ["cluster_mechanism"],
                    "evidence_ids": ["ecard_001", "ecard_002"],
                    "coverage_warnings": ["landscape_sparse_cluster"],
                    "diagnostic_refs": ["axis_coverage:mechanistic_role"],
                },
                "severity": "medium",
                "confidence": "medium",
                "not_an_idea": True,
                "warnings": [],
            },
            {
                "gap_id": "gap_no_evidence",
                "gap_type": "coverage_gap",
                "title": "Unsupported weak gap",
                "description": "This gap lacks evidence basis and should be skipped.",
                "axis_values": {},
                "basis": {
                    "landscape_cluster_ids": [],
                    "evidence_ids": [],
                    "coverage_warnings": ["weak_gap_warning"],
                    "diagnostic_refs": ["coverage:weak_gap"],
                },
                "severity": "low",
                "confidence": "low",
                "not_an_idea": True,
                "warnings": [],
            },
        ],
        "coverage": {"coverage_warnings": ["gap_sparse_axis_warning"]},
        "supporting_evidence": [
            {
                "evidence_id": "ecard_001",
                "paper_id": "paper_001",
                "role": "mechanism",
                "source_type": "text",
                "gap_ids": ["gap_comparison_001"],
                "reason": "Selected mechanism evidence anchors the gap.",
            },
            {
                "evidence_id": "ecard_002",
                "paper_id": "paper_002",
                "role": "performance",
                "source_type": "text",
                "gap_ids": ["gap_comparison_001"],
                "reason": "Selected performance evidence anchors the gap.",
            },
        ],
        "limitations": ["Gap map is deterministic."],
        "warnings": ["gap_sparse_axis_warning"],
        "created_at": 0,
        "schema_version": "gap_map_v1",
    }
    _write_json(workspace_root / "gaps/gap_map.json", gap_map)
    _write_json(
        workspace_root / "gaps/gap_coverage_diagnostics.json",
        {
            "artifact_type": "gap_coverage_diagnostics",
            "task_id": TASK_ID,
            "gap_map_id": "gap_map_idea_run_once",
            "gap_count": 2,
            "warnings": ["gap_sparse_axis_warning"],
            "schema_version": "gap_map_v1",
        },
    )
    _write_text(
        workspace_root / "gaps/gap_map.md",
        "# Gap Map\n\n## Evidence References\n\n- gap_id=gap_comparison_001; evidence_id=ecard_001\n",
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


def _idea_generation_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("generate_candidate_ideas"))
    return registry


def _real_idea_generation_run_once_prompt(
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
            "target_step_id": "step_generate_candidate_ideas",
            "skill_request": {
                "skill_name": "generate_candidate_ideas",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "topic": TOPIC,
                    "idea_generation_scope": "explicit_gap_grounded_candidate_ideas",
                    "require_gap_basis": True,
                    "require_evidence_basis": True,
                    "mark_not_yet_screened": True,
                    "forbid_novelty_or_feasibility_claims": True,
                },
                "reason": "The explicit idea generation plan has required gap, landscape, evidence, and diagnostics artifacts, so request the deterministic idea generation wrapper.",
            },
            "artifact_refs": IDEA_REQUIRED_INPUT_ARTIFACTS,
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The only allowed next step is explicit candidate idea generation.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a one-step research controller run_once smoke test for explicit idea generation.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = generate_candidate_ideas.\n"
        "The workspace already has gaps/gap_map.json, gaps/gap_coverage_diagnostics.json, gaps/gap_map.md, "
        "landscape/literature_landscape.json, landscape/landscape_coverage_diagnostics.json, "
        "landscape/literature_landscape.md, evidence/evidence_cards.enriched.json, "
        "ranked_evidence/evidence_selection.json, ranked_evidence/coverage_diagnostics.json, and "
        "reports/minimal_topic_to_evidence_report.json.\n"
        "Do not request retrieve_sources, create_evidence_seeds, extract_evidence_cards, enrich_evidence_cards, "
        "rank_evidence, report generation, build_landscape, map_gaps, novelty screening, feasibility screening, "
        "risk screening, experiments, claim ledger, or manuscript skills.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not execute the skill yourself. Do not generate idea content yourself.\n"
        "Do not claim ideas are novel, feasible, validated, or experimentally confirmed.\n"
        "Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Return only a cli_controller_contract_v1 envelope matching this shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI idea generation run_once smoke test is opt-in only",
)
def test_real_claude_cli_idea_generation_one_step_run_once_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = _idea_generation_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _real_idea_generation_run_once_prompt,
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
    input_artifacts = decision.skill_request.input_artifacts if decision and decision.skill_request else []
    output_artifacts = result.skill_result.output_artifacts if result.skill_result else []
    executed_skills = []
    if (workspace_root / "logs/tool_calls.jsonl").exists():
        executed_skills = [event.get("skill_name") for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")]
    manifest_artifacts = [item["path"] for item in _read_json(workspace_root / "audit/artifact_manifest.json")["artifacts"]]
    ideas = _read_json(workspace_root / "ideas/candidate_ideas.json")
    diagnostics = _read_json(workspace_root / "ideas/idea_generation_diagnostics.json")
    markdown = (workspace_root / "ideas/candidate_ideas.md").read_text(encoding="utf-8")
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    forbidden_executed = [skill for skill in executed_skills if skill in FORBIDDEN_SKILLS]
    forbidden_sections = [section for section in FORBIDDEN_MARKDOWN_SECTIONS if section in markdown]
    combined_text = f"{json.dumps(ideas, ensure_ascii=False)}\n{markdown}".lower()
    forbidden_claims = [phrase for phrase in FORBIDDEN_CLAIM_PHRASES if phrase in combined_text]
    idea_validation_errors = validate_candidate_ideas_artifact(ideas, markdown)
    every_idea_has_gap_basis = all(idea.get("gap_basis", {}).get("gap_ids") for idea in ideas.get("ideas") or [])
    every_idea_has_evidence_basis = all(
        idea.get("evidence_basis", {}).get("supporting_evidence_ids") for idea in ideas.get("ideas") or []
    )
    every_idea_not_yet_screened = all(idea.get("not_yet_screened") is True for idea in ideas.get("ideas") or [])
    every_idea_requires_novelty = all(
        idea.get("requires_novelty_screening") is True for idea in ideas.get("ideas") or []
    )
    every_idea_requires_feasibility = all(
        idea.get("requires_feasibility_screening") is True for idea in ideas.get("ideas") or []
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
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")),
        "tool_calls_count": len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")),
        "validation_results_count": len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")),
        "state_status": state.get("status"),
        "plan_contains_generate_candidate_ideas": "generate_candidate_ideas" in plan_md,
        "idea_schema_version": ideas.get("schema_version"),
        "idea_set_id": ideas.get("idea_set_id"),
        "gap_map_id": ideas.get("gap_map_id"),
        "landscape_id": ideas.get("landscape_id"),
        "evidence_ids": ideas.get("evidence_ids"),
        "idea_count": len(ideas.get("ideas") or []),
        "every_idea_has_gap_basis": every_idea_has_gap_basis,
        "every_idea_has_evidence_basis": every_idea_has_evidence_basis,
        "every_idea_not_yet_screened": every_idea_not_yet_screened,
        "every_idea_requires_novelty_screening": every_idea_requires_novelty,
        "every_idea_requires_feasibility_screening": every_idea_requires_feasibility,
        "markdown_contains_evidence_references": "## Evidence References" in markdown,
        "forbidden_markdown_sections": forbidden_sections,
        "forbidden_claims": forbidden_claims,
        "idea_validation_errors": idea_validation_errors,
        "coverage_warnings": ideas.get("warnings"),
        "diagnostics": {
            "num_input_gaps": diagnostics.get("num_input_gaps"),
            "num_valid_gaps": diagnostics.get("num_valid_gaps"),
            "num_generated_ideas": diagnostics.get("num_generated_ideas"),
            "downstream_screening_required": diagnostics.get("downstream_screening_required"),
        },
        "violations": [violation.violation_type.value for violation in parse_result.violations] if parse_result else [],
        "warnings": result.warnings,
        "controller_status": result.status.value,
    }
    print("REAL_CLAUDE_CLI_IDEA_GENERATION_RUN_ONCE_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert result.status == ControllerStepStatus.SUCCESS
    assert response is not None
    assert parse_result.accepted is True
    assert decision.decision_type.value == "CALL_TOOL"
    assert skill_name == "generate_candidate_ideas"
    assert input_artifacts == INPUT_ARTIFACTS
    assert executed_skills == ["generate_candidate_ideas"]
    assert forbidden_executed == []
    assert output_artifacts == OUTPUT_ARTIFACTS
    for artifact_path in OUTPUT_ARTIFACTS:
        assert (workspace_root / artifact_path).exists()
        assert artifact_path in manifest_artifacts
    assert ideas["schema_version"] == "candidate_ideas_v1"
    assert ideas["idea_set_id"]
    assert ideas["gap_map_id"] == "gap_map_idea_run_once"
    assert ideas["landscape_id"] == "landscape_idea_run_once"
    assert ideas["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert ideas["ideas"]
    assert every_idea_has_gap_basis is True
    assert every_idea_has_evidence_basis is True
    assert every_idea_not_yet_screened is True
    assert every_idea_requires_novelty is True
    assert every_idea_requires_feasibility is True
    assert "gap_sparse_axis_warning" in ideas["warnings"]
    assert "landscape_sparse_cluster" in ideas["warnings"]
    assert "missing_figure_source_type" in ideas["warnings"]
    assert diagnostics["num_input_gaps"] == 2
    assert diagnostics["num_valid_gaps"] == 1
    assert diagnostics["num_generated_ideas"] == 1
    assert diagnostics["downstream_screening_required"] is True
    assert diagnostics["forbidden_claim_checks"]["passed"] is True
    assert "## Evidence References" in markdown
    assert forbidden_sections == []
    assert forbidden_claims == []
    assert idea_validation_errors == []
    assert len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")) >= 1
    assert state["status"] == "running"
    assert "generate_candidate_ideas" in state["completed_steps"]
    assert "ideas/candidate_ideas.json" in state["artifact_index"]
    assert "generate_candidate_ideas" in plan_md
    assert not (workspace_root / "screening/idea_screening.json").exists()
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()
    assert not (workspace_root / "manuscript/section.md").exists()
