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
    build_explicit_manuscript_scaffold_plan,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_agent_controller.skills.manuscript_contract import (
    MANUSCRIPT_DRAFT_OPTIONAL_INPUT_ARTIFACTS,
    MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
    MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
    MANUSCRIPT_DRAFT_SCHEMA_VERSION,
)
from modules.research_agent_controller.skills.manuscript_tools import (
    FINAL_TEXT_MARKERS,
    UNVALIDATED_RESULT_MARKERS,
    validate_manuscript_draft_artifact,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_manuscript_drafting_run_once_task"
INPUT_ARTIFACTS = MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS + MANUSCRIPT_DRAFT_OPTIONAL_INPUT_ARTIFACTS
OUTPUT_ARTIFACTS = MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS
FORBIDDEN_UPSTREAM_SKILLS = {
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
    "build_claim_ledger",
}
FORBIDDEN_MARKDOWN_SECTIONS = [
    "## Final Abstract",
    "## Final Results",
    "## Final Discussion",
    "## Final Conclusion",
    "## Final Claims",
    "## Submission-Ready Manuscript",
]
FORBIDDEN_TEXT_MARKERS = FINAL_TEXT_MARKERS + UNVALIDATED_RESULT_MARKERS


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    plan = build_explicit_manuscript_scaffold_plan(TASK_ID, TOPIC).as_dict()
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: explicit-manuscript-scaffold\n\n"
            "This is a one-step real Claude CLI manuscript drafting run_once smoke test. "
            "The only permitted platform skill execution is draft_manuscript_section.\n"
        ),
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_manuscript_inputs(workspace_root)
    return workspace_root


def _write_manuscript_inputs(workspace_root: Path) -> None:
    evidence_ids = ["ecard_001", "ecard_002"]
    source_paper_ids = ["paper_001", "paper_002"]
    _write_json(
        workspace_root / "claims/claim_ledger.json",
        {
            "schema_version": "claim_ledger_v1",
            "task_id": TASK_ID,
            "topic": TOPIC,
            "claim_ledger_id": "claim_ledger_manuscript_run_once",
            "input_artifacts": [
                "experiments/experiment_matrix.json",
                "screening/idea_screening_results.json",
                "ideas/candidate_ideas.json",
                "gaps/gap_map.json",
                "landscape/literature_landscape.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
            ],
            "experiment_matrix_id": "experiment_matrix_manuscript_run_once",
            "screening_id": "idea_screening_manuscript_run_once",
            "idea_set_id": "candidate_ideas_manuscript_run_once",
            "gap_map_id": "gap_map_manuscript_run_once",
            "landscape_id": "landscape_manuscript_run_once",
            "evidence_ids": evidence_ids,
            "source_paper_ids": source_paper_ids,
            "claims": [
                {
                    "claim_id": "claim_001",
                    "claim_text": "Oxygen vacancy descriptors are linked to alkaline HER discussion through water dissociation and hydrogen adsorption evidence.",
                    "claim_type": "evidence_summary",
                    "claim_status": "evidence_supported_literature_claim",
                    "source_artifacts": ["evidence/evidence_cards.enriched.json", "ranked_evidence/evidence_selection.json"],
                    "source_idea_ids": [],
                    "source_experiment_ids": [],
                    "gap_ids": ["gap_comparison_001"],
                    "evidence_ids": ["ecard_001"],
                    "source_paper_ids": ["paper_001"],
                    "supporting_evidence": [{"evidence_id": "ecard_001", "paper_id": "paper_001"}],
                    "upstream_dependencies": {
                        "experiment_matrix_ids": ["experiment_matrix_manuscript_run_once"],
                        "screening_ids": ["idea_screening_manuscript_run_once"],
                        "idea_set_ids": ["candidate_ideas_manuscript_run_once"],
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "diagnostic_refs": ["ranked_evidence/coverage_diagnostics.json"],
                    },
                    "support_level": "medium",
                    "allowed_downstream_use": "background_context",
                    "prohibited_uses": ["final_claim", "experimental_result_interpretation"],
                    "limitations": ["Fixture evidence is sparse and requires human review."],
                    "not_a_final_claim": True,
                    "not_experimentally_validated": True,
                    "requires_human_review": True,
                    "warnings": ["claim_sparse_support_warning"],
                },
                {
                    "claim_id": "claim_002",
                    "claim_text": "The upstream gap map frames comparative alkaline HER coverage as limited across catalyst variants.",
                    "claim_type": "gap_statement",
                    "claim_status": "evidence_grounded_candidate",
                    "source_artifacts": ["gaps/gap_map.json", "landscape/literature_landscape.json"],
                    "source_idea_ids": ["idea_gap_comparison_001"],
                    "source_experiment_ids": [],
                    "gap_ids": ["gap_comparison_001"],
                    "evidence_ids": ["ecard_002"],
                    "source_paper_ids": ["paper_002"],
                    "supporting_evidence": [{"evidence_id": "ecard_002", "paper_id": "paper_002"}],
                    "upstream_dependencies": {
                        "experiment_matrix_ids": ["experiment_matrix_manuscript_run_once"],
                        "screening_ids": ["idea_screening_manuscript_run_once"],
                        "idea_set_ids": ["candidate_ideas_manuscript_run_once"],
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "diagnostic_refs": ["gaps/gap_coverage_diagnostics.json"],
                    },
                    "support_level": "low",
                    "allowed_downstream_use": "gap_framing",
                    "prohibited_uses": ["final_claim", "experimental_result_interpretation"],
                    "limitations": ["Comparison coverage is incomplete."],
                    "not_a_final_claim": True,
                    "not_experimentally_validated": True,
                    "requires_human_review": True,
                    "warnings": ["gap_claim_sparse_warning"],
                },
                {
                    "claim_id": "claim_003",
                    "claim_text": "The experiment matrix records a planning rationale for comparing vacancy-related catalyst variants with baseline controls.",
                    "claim_type": "experiment_matrix_rationale",
                    "claim_status": "matrix_planning_scaffold",
                    "source_artifacts": ["experiments/experiment_matrix.json"],
                    "source_idea_ids": ["idea_gap_comparison_001"],
                    "source_experiment_ids": ["exp_idea_gap_comparison_001"],
                    "gap_ids": ["gap_comparison_001"],
                    "evidence_ids": ["ecard_001", "ecard_002"],
                    "source_paper_ids": source_paper_ids,
                    "supporting_evidence": [
                        {"evidence_id": "ecard_001", "paper_id": "paper_001"},
                        {"evidence_id": "ecard_002", "paper_id": "paper_002"},
                    ],
                    "upstream_dependencies": {
                        "experiment_matrix_ids": ["experiment_matrix_manuscript_run_once"],
                        "screening_ids": ["idea_screening_manuscript_run_once"],
                        "idea_set_ids": ["candidate_ideas_manuscript_run_once"],
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "diagnostic_refs": ["experiments/experiment_matrix_diagnostics.json"],
                    },
                    "support_level": "low",
                    "allowed_downstream_use": "planning_rationale",
                    "prohibited_uses": ["final_claim", "experimental_result_interpretation"],
                    "limitations": ["Planning rationale only."],
                    "not_a_final_claim": True,
                    "not_experimentally_validated": True,
                    "requires_human_review": True,
                    "warnings": ["experiment_matrix_sparse_fixture"],
                },
            ],
            "ledger_scope": {"scope": "explicit_claim_ledger_grounded_manuscript_scaffold"},
            "claim_policy": {
                "not_final_claim": True,
                "requires_human_review": True,
                "not_experimentally_validated": True,
            },
            "limitations": ["Human review is required before any manuscript use."],
            "warnings": ["claim_ledger_sparse_fixture"],
        },
    )
    _write_json(
        workspace_root / "claims/claim_ledger_diagnostics.json",
        {
            "artifact_type": "claim_ledger_diagnostics",
            "schema_version": "claim_ledger_v1",
            "claim_ledger_id": "claim_ledger_manuscript_run_once",
            "claim_count": 3,
            "warnings": ["claim_ledger_diagnostics_fixture"],
        },
    )
    _write_text(
        workspace_root / "claims/claim_ledger.md",
        "# Claim Ledger\n\n## Evidence References\n\n- claim_id=claim_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "experiments/experiment_matrix.json",
        {
            "schema_version": "experiment_matrix_v1",
            "experiment_matrix_id": "experiment_matrix_manuscript_run_once",
            "screening_id": "idea_screening_manuscript_run_once",
            "idea_set_id": "candidate_ideas_manuscript_run_once",
            "gap_map_id": "gap_map_manuscript_run_once",
            "landscape_id": "landscape_manuscript_run_once",
            "evidence_ids": evidence_ids,
            "source_paper_ids": source_paper_ids,
            "experiment_candidates": [{"experiment_id": "exp_idea_gap_comparison_001", "evidence_ids": evidence_ids}],
            "warnings": ["experiment_matrix_sparse_fixture"],
        },
    )
    _write_json(
        workspace_root / "experiments/experiment_matrix_diagnostics.json",
        {
            "schema_version": "experiment_matrix_v1",
            "artifact_type": "experiment_matrix_diagnostics",
            "experiment_matrix_id": "experiment_matrix_manuscript_run_once",
            "warnings": ["experiment_matrix_diagnostics_fixture"],
        },
    )
    _write_text(
        workspace_root / "experiments/experiment_matrix.md",
        "# Experiment Matrix\n\n## Evidence References\n\n- experiment_id=exp_idea_gap_comparison_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "screening/idea_screening_results.json",
        valid_screening_v2_artifact(
            task_id=TASK_ID,
            screening_id="idea_screening_manuscript_run_once",
            idea_set_id="candidate_ideas_manuscript_run_once",
            gap_map_id="gap_map_manuscript_run_once",
            landscape_id="landscape_manuscript_run_once",
            evidence_ids=evidence_ids,
            source_paper_ids=source_paper_ids,
        ),
    )
    _write_json(
        workspace_root / "screening/screening_diagnostics.json",
        {
            "schema_version": "idea_screening_v2",
            "artifact_type": "screening_diagnostics",
            "screening_id": "idea_screening_manuscript_run_once",
            "warnings": ["screening_diagnostics_fixture"],
        },
    )
    _write_text(
        workspace_root / "screening/idea_screening_results.md",
        "# Idea Screening Results\n\n## Evidence References\n\n- idea_id=idea_gap_comparison_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "ideas/candidate_ideas.json",
        {
            "schema_version": "candidate_ideas_v1",
            "idea_set_id": "candidate_ideas_manuscript_run_once",
            "gap_map_id": "gap_map_manuscript_run_once",
            "landscape_id": "landscape_manuscript_run_once",
            "evidence_ids": evidence_ids,
            "source_paper_ids": source_paper_ids,
            "ideas": [{"idea_id": "idea_gap_comparison_001", "evidence_basis": {"supporting_evidence_ids": evidence_ids}}],
            "warnings": ["idea_generation_sparse_fixture"],
        },
    )
    _write_json(
        workspace_root / "ideas/idea_generation_diagnostics.json",
        {
            "schema_version": "candidate_ideas_v1",
            "artifact_type": "idea_generation_diagnostics",
            "idea_set_id": "candidate_ideas_manuscript_run_once",
            "warnings": ["idea_generation_diagnostics_fixture"],
        },
    )
    _write_text(
        workspace_root / "ideas/candidate_ideas.md",
        "# Candidate Ideas\n\n## Evidence References\n\n- idea_id=idea_gap_comparison_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "gaps/gap_map.json",
        {
            "schema_version": "gap_map_v1",
            "gap_map_id": "gap_map_manuscript_run_once",
            "landscape_id": "landscape_manuscript_run_once",
            "evidence_ids": evidence_ids,
            "source_paper_ids": source_paper_ids,
            "gaps": [{"gap_id": "gap_comparison_001", "evidence_ids": evidence_ids}],
            "warnings": ["gap_sparse_axis_warning"],
        },
    )
    _write_json(
        workspace_root / "gaps/gap_coverage_diagnostics.json",
        {
            "schema_version": "gap_map_v1",
            "artifact_type": "gap_coverage_diagnostics",
            "gap_map_id": "gap_map_manuscript_run_once",
            "warnings": ["gap_diagnostics_fixture"],
        },
    )
    _write_text(
        workspace_root / "gaps/gap_map.md",
        "# Gap Map\n\n## Evidence References\n\n- gap_id=gap_comparison_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "landscape/literature_landscape.json",
        {
            "schema_version": "landscape_v1",
            "landscape_id": "landscape_manuscript_run_once",
            "evidence_ids": evidence_ids,
            "source_paper_ids": source_paper_ids,
            "clusters": [{"cluster_id": "cluster_mechanism", "evidence_ids": evidence_ids}],
            "warnings": ["landscape_sparse_cluster"],
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "schema_version": "landscape_v1",
            "artifact_type": "landscape_coverage_diagnostics",
            "landscape_id": "landscape_manuscript_run_once",
            "warnings": ["landscape_diagnostics_fixture"],
        },
    )
    _write_text(
        workspace_root / "landscape/literature_landscape.md",
        "# Literature Landscape\n\n## Evidence References\n\n- cluster_id=cluster_mechanism; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {
            "artifact_type": "evidence_cards",
            "stage": "enriched",
            "task_id": TASK_ID,
            "cards": [
                {"evidence_id": "ecard_001", "paper_id": "paper_001", "primary_role": "mechanism"},
                {"evidence_id": "ecard_002", "paper_id": "paper_002", "primary_role": "performance"},
            ],
            "warnings": ["enriched_sparse_role_warning"],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/evidence_selection.json",
        {
            "artifact_type": "evidence_selection",
            "selected_cards": [
                {"evidence_id": "ecard_001", "paper_id": "paper_001"},
                {"evidence_id": "ecard_002", "paper_id": "paper_002"},
            ],
            "warnings": ["dominant_paper_warning"],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/coverage_diagnostics.json",
        {
            "artifact_type": "coverage_diagnostics",
            "coverage": {"missing_required_roles": ["figure_evidence"]},
            "warnings": ["missing_figure_source_type"],
        },
    )
    _write_json(
        workspace_root / "reports/minimal_topic_to_evidence_report.json",
        {
            "artifact_type": "minimal_topic_to_evidence_report",
            "scope": "minimal_topic_to_evidence",
            "evidence_references": evidence_ids,
            "warnings": ["minimal_report_fixture"],
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


def _manuscript_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("draft_manuscript_section"))
    return registry


def _real_manuscript_run_once_prompt(
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
            "target_step_id": "step_draft_manuscript_section",
            "skill_request": {
                "skill_name": "draft_manuscript_section",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "topic": TOPIC,
                    "draft_scope": "explicit_claim_ledger_grounded_manuscript_scaffold",
                    "target_section": "discussion_scaffold",
                    "require_claim_ledger_basis": True,
                    "require_traceable_evidence_basis": True,
                    "forbid_final_manuscript": True,
                    "forbid_final_claims": True,
                    "forbid_validated_result_claims": True,
                    "forbid_publication_ready_text": True,
                },
                "reason": (
                    "The explicit manuscript scaffold plan has required claim ledger, experiment matrix, "
                    "screening, idea, gap, landscape, evidence, ranking, and diagnostics artifacts, so request "
                    "the deterministic manuscript scaffold wrapper."
                ),
            },
            "artifact_refs": [
                "claims/claim_ledger.json",
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
            "reason": "The only allowed next step is explicit manuscript scaffold drafting.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a one-step research controller run_once smoke test for explicit manuscript scaffold drafting.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = draft_manuscript_section.\n"
        "The workspace already has claims/claim_ledger.json, claims/claim_ledger_diagnostics.json, "
        "claims/claim_ledger.md, experiments/experiment_matrix.json, experiments/experiment_matrix_diagnostics.json, "
        "experiments/experiment_matrix.md, screening/idea_screening_results.json, screening/screening_diagnostics.json, "
        "screening/idea_screening_results.md, ideas/candidate_ideas.json, ideas/idea_generation_diagnostics.json, "
        "ideas/candidate_ideas.md, gaps/gap_map.json, gaps/gap_coverage_diagnostics.json, gaps/gap_map.md, "
        "landscape/literature_landscape.json, landscape/landscape_coverage_diagnostics.json, "
        "landscape/literature_landscape.md, evidence/evidence_cards.enriched.json, "
        "ranked_evidence/evidence_selection.json, ranked_evidence/coverage_diagnostics.json, and "
        "reports/minimal_topic_to_evidence_report.json.\n"
        "Do not request retrieve_sources, create_evidence_seeds, extract_evidence_cards, enrich_evidence_cards, "
        "rank_evidence, report generation, build_landscape, map_gaps, generate_candidate_ideas, screening, "
        "experiment matrix, claim ledger, draft_evidence_grounded_report, or any future skill.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not execute the skill yourself. Do not generate manuscript content yourself.\n"
        "Do not generate final manuscript content, final abstract, final results, final discussion, final conclusion, or final claims.\n"
        "Do not claim experimental validation. Do not claim candidate hypotheses are proven.\n"
        "Do not claim performance will improve. Do not generate publication-ready text.\n"
        "Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Return only a cli_controller_contract_v1 envelope matching this shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI manuscript drafting run_once smoke test is opt-in only",
)
def test_real_claude_cli_manuscript_drafting_one_step_run_once_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = _manuscript_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _real_manuscript_run_once_prompt,
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
    draft = _read_json(workspace_root / "drafts/manuscript_section_draft.json")
    diagnostics = _read_json(workspace_root / "drafts/manuscript_section_diagnostics.json")
    markdown = (workspace_root / "drafts/manuscript_section_draft.md").read_text(encoding="utf-8")
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    draft_blocks = draft.get("draft_blocks") or []
    citation_map = draft.get("citation_map") or []
    forbidden_executed = [skill for skill in executed_skills if skill in FORBIDDEN_UPSTREAM_SKILLS]
    forbidden_sections = [section for section in FORBIDDEN_MARKDOWN_SECTIONS if section in markdown]
    lowered_markdown = markdown.lower()
    forbidden_phrases = [phrase for phrase in FORBIDDEN_TEXT_MARKERS if phrase in lowered_markdown]
    validation_errors = validate_manuscript_draft_artifact(draft, markdown)
    every_block_has_id = all(block.get("block_id") for block in draft_blocks)
    every_block_has_type = all(block.get("block_type") for block in draft_blocks)
    every_block_has_text = all(block.get("text") for block in draft_blocks)
    non_transition_blocks_have_claims = all(
        block.get("claim_ids")
        for block in draft_blocks
        if block.get("block_type") not in {"transition", "caution"}
    )
    evidence_blocks_preserve_evidence = all(
        block.get("evidence_ids")
        for block in draft_blocks
        if block.get("evidence_ids")
    )
    every_block_requires_review = all(block.get("requires_human_review") is True for block in draft_blocks)
    every_block_not_final = all(block.get("not_final_text") is True for block in draft_blocks)
    every_block_not_peer_reviewed = all(block.get("not_peer_reviewed") is True for block in draft_blocks)
    every_block_not_validated = all(block.get("not_experimentally_validated") is True for block in draft_blocks)
    citation_map_preserves_sources = all(
        item.get("claim_id") and item.get("evidence_ids") and item.get("source_paper_ids") and item.get("source_artifacts")
        for item in citation_map
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
        "draft_evidence_grounded_report_requested": skill_name == "draft_evidence_grounded_report",
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")),
        "tool_calls_count": len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")),
        "validation_results_count": len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")),
        "state_status": state.get("status"),
        "plan_contains_manuscript_step": "draft_manuscript_section" in plan_md,
        "draft_schema_version": draft.get("schema_version"),
        "draft_id": draft.get("draft_id"),
        "claim_ledger_id": draft.get("claim_ledger_id"),
        "experiment_matrix_id": draft.get("experiment_matrix_id"),
        "screening_id": draft.get("screening_id"),
        "idea_set_id": draft.get("idea_set_id"),
        "gap_map_id": draft.get("gap_map_id"),
        "landscape_id": draft.get("landscape_id"),
        "evidence_ids": draft.get("evidence_ids"),
        "source_paper_ids": draft.get("source_paper_ids"),
        "draft_block_count": len(draft_blocks),
        "citation_map_count": len(citation_map),
        "unsupported_claim_count": len(draft.get("unsupported_claims") or []),
        "every_block_has_id": every_block_has_id,
        "every_block_has_type": every_block_has_type,
        "every_block_has_text": every_block_has_text,
        "non_transition_blocks_have_claims": non_transition_blocks_have_claims,
        "evidence_blocks_preserve_evidence": evidence_blocks_preserve_evidence,
        "every_block_requires_human_review": every_block_requires_review,
        "every_block_not_final_text": every_block_not_final,
        "every_block_not_peer_reviewed": every_block_not_peer_reviewed,
        "every_block_not_experimentally_validated": every_block_not_validated,
        "citation_map_preserves_sources": citation_map_preserves_sources,
        "diagnostics_warnings": diagnostics.get("warnings"),
        "markdown_contains_evidence_references": "## Evidence References" in markdown,
        "markdown_contains_required_human_review": "## Required Human Review" in markdown,
        "forbidden_markdown_sections": forbidden_sections,
        "forbidden_phrases": forbidden_phrases,
        "manuscript_validation_errors": validation_errors,
        "violations": [violation.violation_type.value for violation in parse_result.violations] if parse_result else [],
        "warnings": result.warnings,
        "controller_status": result.status.value,
    }
    print("REAL_CLAUDE_CLI_MANUSCRIPT_DRAFTING_RUN_ONCE_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert result.status == ControllerStepStatus.SUCCESS
    assert response is not None
    assert parse_result.accepted is True
    assert decision.decision_type.value == "CALL_TOOL"
    assert skill_name == "draft_manuscript_section"
    assert input_artifacts == INPUT_ARTIFACTS
    assert executed_skills == ["draft_manuscript_section"]
    assert forbidden_executed == []
    assert output_artifacts == OUTPUT_ARTIFACTS
    for artifact_path in OUTPUT_ARTIFACTS:
        assert (workspace_root / artifact_path).exists()
        assert artifact_path in manifest_artifacts
    assert draft["schema_version"] == MANUSCRIPT_DRAFT_SCHEMA_VERSION
    assert draft["draft_id"]
    assert draft["claim_ledger_id"] == "claim_ledger_manuscript_run_once"
    assert draft["experiment_matrix_id"] == "experiment_matrix_manuscript_run_once"
    assert draft["screening_id"] == "idea_screening_manuscript_run_once"
    assert draft["idea_set_id"] == "candidate_ideas_manuscript_run_once"
    assert draft["gap_map_id"] == "gap_map_manuscript_run_once"
    assert draft["landscape_id"] == "landscape_manuscript_run_once"
    assert draft["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert "source_paper_ids" in draft
    assert draft_blocks
    assert "citation_map" in draft
    assert "unsupported_claims" in draft
    assert every_block_has_id is True
    assert every_block_has_type is True
    assert every_block_has_text is True
    assert non_transition_blocks_have_claims is True
    assert evidence_blocks_preserve_evidence is True
    assert every_block_requires_review is True
    assert every_block_not_final is True
    assert every_block_not_peer_reviewed is True
    assert every_block_not_validated is True
    assert citation_map_preserves_sources is True
    assert diagnostics["draft_block_count"] == len(draft_blocks)
    assert diagnostics["warnings"]
    assert "## Evidence References" in markdown
    assert "## Required Human Review" in markdown
    assert forbidden_sections == []
    assert forbidden_phrases == []
    assert validation_errors == []
    assert len(read_jsonl_events(workspace_root, "logs/controller_events.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 1
    assert len(read_jsonl_events(workspace_root, "logs/validation_results.jsonl")) >= 1
    assert state["status"] == "running"
    assert "draft_manuscript_section" in state["completed_steps"]
    assert "drafts/manuscript_section_draft.json" in state["artifact_index"]
    assert "draft_manuscript_section" in plan_md
    assert not (workspace_root / "manuscript/section.md").exists()
