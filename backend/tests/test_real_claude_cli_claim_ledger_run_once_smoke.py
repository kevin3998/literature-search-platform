import json
import os
from pathlib import Path

import pytest

from screening_v2_helpers import valid_screening_v2_artifact

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ClaudeCodeCliBackendConfig,
    ControllerStepStatus,
    RealClaudeCodeCliBackend,
    SkillRegistry,
    build_default_skill_registry,
    build_explicit_claim_ledger_plan,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_agent_controller.skills.claim_ledger_contract import (
    CLAIM_LEDGER_OUTPUT_ARTIFACTS,
    CLAIM_LEDGER_OPTIONAL_INPUT_ARTIFACTS,
    CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
)
from modules.research_agent_controller.skills.claim_ledger_tools import (
    FORBIDDEN_CLAIM_LEDGER_PHRASES,
    validate_claim_ledger_artifact,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_claim_ledger_run_once_task"
INPUT_ARTIFACTS = CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS + CLAIM_LEDGER_OPTIONAL_INPUT_ARTIFACTS
OUTPUT_ARTIFACTS = CLAIM_LEDGER_OUTPUT_ARTIFACTS
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
    "screen_novelty_feasibility_risk",
    "create_experiment_matrix",
    "draft_manuscript_section",
}
FORBIDDEN_MARKDOWN_SECTIONS = [
    "## Manuscript Draft",
    "## Abstract",
    "## Results And Discussion",
    "## Conclusion",
    "## Final Claims",
]


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    plan = build_explicit_claim_ledger_plan(TASK_ID, TOPIC).as_dict()
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: explicit-claim-ledger\n\n"
            "This is a one-step real Claude CLI claim ledger run_once smoke test. "
            "The only permitted platform skill execution is build_claim_ledger.\n"
        ),
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_claim_ledger_inputs(workspace_root)
    return workspace_root


def _write_claim_ledger_inputs(workspace_root: Path) -> None:
    cards = [
        {
            "evidence_id": "ecard_001",
            "paper_id": "paper_001",
            "normalized_statement": "Oxygen vacancies modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
            "verbatim_snippet": "Oxygen vacancies modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
            "primary_role": "mechanism",
            "source": {"source_path": "paper_001/sections/results.md", "asset_type": "text"},
        },
        {
            "evidence_id": "ecard_002",
            "paper_id": "paper_002",
            "normalized_statement": "Comparative alkaline HER measurements are sparse for oxygen-vacancy-tuned catalysts.",
            "verbatim_snippet": "Comparative alkaline HER measurements are sparse for oxygen-vacancy-tuned catalysts.",
            "primary_role": "performance",
            "source": {"source_path": "paper_002/sections/results.md", "asset_type": "text"},
        },
    ]
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
            "ranked_cards": [{"evidence_id": card["evidence_id"], "card": card, "selected": True} for card in cards],
            "warnings": ["dominant_paper_warning"],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/coverage_diagnostics.json",
        {
            "artifact_type": "coverage_diagnostics",
            "coverage": {"missing_required_roles": ["figure_evidence"], "source_type_coverage": {"text": 2}},
            "warnings": ["missing_figure_source_type"],
        },
    )
    _write_json(
        workspace_root / "landscape/literature_landscape.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "landscape_id": "landscape_claim_ledger_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "clusters": [
                {
                    "cluster_id": "cluster_mechanism",
                    "title": "Mechanism Cluster",
                    "evidence_ids": ["ecard_001"],
                    "source_paper_ids": ["paper_001"],
                    "representative_claims": [
                        {"claim": "Oxygen vacancies modulate water dissociation.", "evidence_ids": ["ecard_001"]}
                    ],
                }
            ],
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "landscape_id": "landscape_claim_ledger_run_once",
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
            "gap_map_id": "gap_map_claim_ledger_run_once",
            "landscape_id": "landscape_claim_ledger_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "gaps": [
                {
                    "gap_id": "gap_comparison_001",
                    "gap_type": "comparison_gap",
                    "title": "Limited comparison coverage",
                    "basis": {
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "evidence_ids": ["ecard_001", "ecard_002"],
                        "coverage_warnings": ["landscape_sparse_cluster"],
                        "diagnostic_refs": ["axis_coverage:mechanistic_role"],
                    },
                    "not_an_idea": True,
                    "warnings": ["gap_record_sparse_warning"],
                }
            ],
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
            "gap_map_id": "gap_map_claim_ledger_run_once",
            "warnings": ["gap_diagnostics_fixture"],
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
            "idea_set_id": "candidate_ideas_claim_ledger_run_once",
            "gap_map_id": "gap_map_claim_ledger_run_once",
            "landscape_id": "landscape_claim_ledger_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "ideas": [
                {
                    "idea_id": "idea_gap_comparison_001",
                    "title": "Candidate idea from comparison gap",
                    "summary": "This candidate direction is grounded in the comparison gap and requires screening.",
                    "gap_basis": {
                        "gap_ids": ["gap_comparison_001"],
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "evidence_ids": ["ecard_001", "ecard_002"],
                    },
                    "evidence_basis": {
                        "supporting_evidence_ids": ["ecard_001", "ecard_002"],
                        "source_paper_ids": ["paper_001", "paper_002"],
                    },
                    "not_yet_screened": True,
                    "requires_novelty_screening": True,
                    "requires_feasibility_screening": True,
                    "warnings": ["idea_sparse_support_warning"],
                }
            ],
            "warnings": ["idea_generation_sparse_fixture"],
            "schema_version": "candidate_ideas_v1",
        },
    )
    _write_json(
        workspace_root / "ideas/idea_generation_diagnostics.json",
        {
            "artifact_type": "idea_generation_diagnostics",
            "idea_set_id": "candidate_ideas_claim_ledger_run_once",
            "warnings": ["idea_generation_diagnostics_fixture"],
            "schema_version": "candidate_ideas_v1",
        },
    )
    _write_text(
        workspace_root / "ideas/candidate_ideas.md",
        "# Candidate Ideas\n\n## Evidence References\n\n- idea_id=idea_gap_comparison_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "screening/idea_screening_results.json",
        valid_screening_v2_artifact(
            task_id=TASK_ID,
            screening_id="idea_screening_claim_ledger_run_once",
            idea_set_id="candidate_ideas_claim_ledger_run_once",
            gap_map_id="gap_map_claim_ledger_run_once",
            landscape_id="landscape_claim_ledger_run_once",
        ),
    )
    _write_json(
        workspace_root / "screening/screening_diagnostics.json",
        {
            "artifact_type": "screening_diagnostics",
            "screening_id": "idea_screening_claim_ledger_run_once",
            "warnings": ["screening_diagnostics_fixture"],
            "schema_version": "idea_screening_v2",
        },
    )
    _write_text(
        workspace_root / "screening/idea_screening_results.md",
        "# Idea Screening Results\n\n## Evidence References\n\n- idea_id=idea_gap_comparison_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "experiments/experiment_matrix.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "experiment_matrix_id": "experiment_matrix_claim_ledger_run_once",
            "input_artifacts": [],
            "screening_id": "idea_screening_claim_ledger_run_once",
            "idea_set_id": "candidate_ideas_claim_ledger_run_once",
            "gap_map_id": "gap_map_claim_ledger_run_once",
            "landscape_id": "landscape_claim_ledger_run_once",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "experiment_candidates": [
                {
                    "experiment_id": "exp_idea_gap_comparison_001",
                    "source_idea_id": "idea_gap_comparison_001",
                    "screened_idea_ref": "idea_screening_claim_ledger_run_once:idea_gap_comparison_001",
                    "objective": "Compare oxygen-vacancy-related catalyst variants against a baseline control.",
                    "hypothesis_under_test": "Oxygen vacancy modulation remains a candidate hypothesis requiring validation.",
                    "gap_ids": ["gap_comparison_001"],
                    "evidence_ids": ["ecard_001", "ecard_002"],
                    "screening_basis": {
                        "novelty_status": "requires_external_search",
                        "feasibility_status": "requires_expert_review",
                        "risk_status": "requires_risk_review",
                        "required_follow_up": ["external novelty search", "expert feasibility review", "risk review"],
                        "limitations": ["No external or expert review has been performed."],
                    },
                    "design_variables": [{"variable_id": "var_001", "name": "oxygen vacancy level"}],
                    "characterization_targets": [{"target_id": "target_001", "target": "oxygen vacancy indication"}],
                    "limitations": ["Planning scaffold only."],
                    "not_a_protocol": True,
                    "not_a_validated_claim": True,
                    "requires_expert_review": True,
                    "warnings": ["experiment_matrix_sparse_fixture"],
                }
            ],
            "limitations": ["No experiment has been performed."],
            "warnings": ["experiment_matrix_sparse_fixture"],
            "schema_version": "experiment_matrix_v1",
        },
    )
    _write_json(
        workspace_root / "experiments/experiment_matrix_diagnostics.json",
        {
            "artifact_type": "experiment_matrix_diagnostics",
            "experiment_matrix_id": "experiment_matrix_claim_ledger_run_once",
            "experiment_candidate_count": 1,
            "warnings": ["experiment_matrix_diagnostics_fixture"],
            "schema_version": "experiment_matrix_v1",
        },
    )
    _write_text(
        workspace_root / "experiments/experiment_matrix.md",
        "# Experiment Matrix\n\n## Evidence References\n\n- experiment_id=exp_idea_gap_comparison_001; evidence_id=ecard_001\n",
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


def _claim_ledger_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("build_claim_ledger"))
    return registry


def _real_claim_ledger_run_once_prompt(
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
            "target_step_id": "step_build_claim_ledger",
            "skill_request": {
                "skill_name": "build_claim_ledger",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "topic": TOPIC,
                    "claim_ledger_scope": "explicit_experiment_matrix_grounded_claim_ledger",
                    "require_traceable_evidence_basis": True,
                    "require_non_final_claim_status": True,
                    "forbid_manuscript_drafting": True,
                    "forbid_final_claims": True,
                    "forbid_validated_result_claims": True,
                },
                "reason": (
                    "The explicit claim ledger plan has required experiment matrix, screening, idea, gap, "
                    "landscape, evidence, ranking, and diagnostics artifacts, so request the deterministic "
                    "claim ledger wrapper."
                ),
            },
            "artifact_refs": [
                "experiments/experiment_matrix.json",
                "screening/idea_screening_results.json",
                "ideas/candidate_ideas.json",
                "gaps/gap_map.json",
                "landscape/literature_landscape.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The only allowed next step is explicit claim ledger construction.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a one-step research controller run_once smoke test for explicit claim ledger construction.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = build_claim_ledger.\n"
        "The workspace already has experiments/experiment_matrix.json, experiments/experiment_matrix_diagnostics.json, "
        "experiments/experiment_matrix.md, screening/idea_screening_results.json, screening/screening_diagnostics.json, "
        "screening/idea_screening_results.md, ideas/candidate_ideas.json, ideas/idea_generation_diagnostics.json, "
        "ideas/candidate_ideas.md, gaps/gap_map.json, gaps/gap_coverage_diagnostics.json, gaps/gap_map.md, "
        "landscape/literature_landscape.json, landscape/landscape_coverage_diagnostics.json, "
        "landscape/literature_landscape.md, evidence/evidence_cards.enriched.json, "
        "ranked_evidence/evidence_selection.json, ranked_evidence/coverage_diagnostics.json, and "
        "reports/minimal_topic_to_evidence_report.json.\n"
        "Do not request retrieve_sources, create_evidence_seeds, extract_evidence_cards, enrich_evidence_cards, "
        "rank_evidence, report generation, build_landscape, map_gaps, generate_candidate_ideas, screening, "
        "experiment matrix, manuscript skills, or any P2-M14+ skill.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not execute the skill yourself. Do not generate claim ledger content yourself.\n"
        "Do not generate manuscript content, abstract, results or discussion, conclusion, or final claims.\n"
        "Do not claim experimental validation. Do not claim candidate hypotheses are proven.\n"
        "Do not claim performance will improve.\n"
        "Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Return only a cli_controller_contract_v1 envelope matching this shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI claim ledger run_once smoke test is opt-in only",
)
def test_real_claude_cli_claim_ledger_one_step_run_once_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = _claim_ledger_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _real_claim_ledger_run_once_prompt,
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
    claim_ledger = _read_json(workspace_root / "claims/claim_ledger.json")
    diagnostics = _read_json(workspace_root / "claims/claim_ledger_diagnostics.json")
    markdown = (workspace_root / "claims/claim_ledger.md").read_text(encoding="utf-8")
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    claims = claim_ledger.get("claims") or []
    forbidden_executed = [skill for skill in executed_skills if skill in FORBIDDEN_SKILLS]
    forbidden_sections = [section for section in FORBIDDEN_MARKDOWN_SECTIONS if section in markdown]
    claim_text_blob = "\n".join(str(claim.get("claim_text", "")) for claim in claims).lower()
    forbidden_phrases = [
        phrase
        for phrase in FORBIDDEN_CLAIM_LEDGER_PHRASES
        if phrase in claim_text_blob
    ]
    validation_errors = validate_claim_ledger_artifact(claim_ledger, markdown)
    every_claim_has_id = all(claim.get("claim_id") for claim in claims)
    every_claim_has_type = all(claim.get("claim_type") for claim in claims)
    every_claim_has_status = all(claim.get("claim_status") for claim in claims)
    every_claim_has_sources = all(claim.get("source_artifacts") for claim in claims)
    evidence_claims_preserve_evidence = all(
        claim.get("evidence_ids")
        for claim in claims
        if claim.get("claim_status") not in {"insufficient_support", "rejected_overclaim"}
    )
    every_claim_not_final = all(claim.get("not_a_final_claim") is True for claim in claims)
    every_claim_not_validated = all(claim.get("not_experimentally_validated") is True for claim in claims)
    every_claim_requires_review = all(claim.get("requires_human_review") is True for claim in claims)
    upstream_dependencies_preserved = any(claim.get("upstream_dependencies") for claim in claims)
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
        "plan_contains_claim_ledger": "build_claim_ledger" in plan_md,
        "claim_ledger_schema_version": claim_ledger.get("schema_version"),
        "claim_ledger_id": claim_ledger.get("claim_ledger_id"),
        "experiment_matrix_id": claim_ledger.get("experiment_matrix_id"),
        "screening_id": claim_ledger.get("screening_id"),
        "idea_set_id": claim_ledger.get("idea_set_id"),
        "gap_map_id": claim_ledger.get("gap_map_id"),
        "landscape_id": claim_ledger.get("landscape_id"),
        "evidence_ids": claim_ledger.get("evidence_ids"),
        "claim_count": len(claims),
        "every_claim_has_id": every_claim_has_id,
        "every_claim_has_type": every_claim_has_type,
        "every_claim_has_status": every_claim_has_status,
        "every_claim_has_sources": every_claim_has_sources,
        "evidence_claims_preserve_evidence": evidence_claims_preserve_evidence,
        "every_claim_not_final": every_claim_not_final,
        "every_claim_not_experimentally_validated": every_claim_not_validated,
        "every_claim_requires_review": every_claim_requires_review,
        "upstream_dependencies_preserved": upstream_dependencies_preserved,
        "diagnostics_warnings": diagnostics.get("warnings"),
        "markdown_contains_evidence_references": "## Evidence References" in markdown,
        "forbidden_markdown_sections": forbidden_sections,
        "forbidden_phrases": forbidden_phrases,
        "claim_ledger_validation_errors": validation_errors,
        "violations": [violation.violation_type.value for violation in parse_result.violations] if parse_result else [],
        "warnings": result.warnings,
        "controller_status": result.status.value,
    }
    print("REAL_CLAUDE_CLI_CLAIM_LEDGER_RUN_ONCE_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert result.status == ControllerStepStatus.SUCCESS
    assert response is not None
    assert parse_result.accepted is True
    assert decision.decision_type.value == "CALL_TOOL"
    assert skill_name == "build_claim_ledger"
    assert input_artifacts == INPUT_ARTIFACTS
    assert executed_skills == ["build_claim_ledger"]
    assert forbidden_executed == []
    assert output_artifacts == OUTPUT_ARTIFACTS
    for artifact_path in OUTPUT_ARTIFACTS:
        assert (workspace_root / artifact_path).exists()
        assert artifact_path in manifest_artifacts
    assert claim_ledger["schema_version"] == "claim_ledger_v1"
    assert claim_ledger["claim_ledger_id"]
    assert claim_ledger["experiment_matrix_id"] == "experiment_matrix_claim_ledger_run_once"
    assert claim_ledger["screening_id"] == "idea_screening_claim_ledger_run_once"
    assert claim_ledger["idea_set_id"] == "candidate_ideas_claim_ledger_run_once"
    assert claim_ledger["gap_map_id"] == "gap_map_claim_ledger_run_once"
    assert claim_ledger["landscape_id"] == "landscape_claim_ledger_run_once"
    assert claim_ledger["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert claims
    assert every_claim_has_id is True
    assert every_claim_has_type is True
    assert every_claim_has_status is True
    assert every_claim_has_sources is True
    assert evidence_claims_preserve_evidence is True
    assert every_claim_not_final is True
    assert every_claim_not_validated is True
    assert every_claim_requires_review is True
    assert upstream_dependencies_preserved is True
    assert "experiment_matrix_sparse_fixture" in claim_ledger["warnings"]
    assert "screening_sparse_fixture" in claim_ledger["warnings"]
    assert diagnostics["claim_count"] == len(claims)
    assert "## Evidence References" in markdown
    assert forbidden_sections == []
    assert forbidden_phrases == []
    assert validation_errors == []
    assert len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")) >= 1
    assert state["status"] == "running"
    assert "build_claim_ledger" in state["completed_steps"]
    assert "claims/claim_ledger.json" in state["artifact_index"]
    assert "build_claim_ledger" in plan_md
    assert not (workspace_root / "manuscript/section.md").exists()
