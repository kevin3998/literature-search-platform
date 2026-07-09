import json
from pathlib import Path

from screening_v2_helpers import valid_screening_v2_artifact

from modules.research_agent_controller import (
    SkillExecutionInput,
    SkillExecutionStatus,
    SkillStatus,
    build_default_skill_registry,
    load_artifact_manifest,
    read_jsonl_events,
    record_skill_execution_result,
)
from modules.research_agent_controller.skills import EVIDENCE_SKILL_WRAPPERS, execute_evidence_skill
from modules.research_agent_controller.skills.claim_ledger_contract import CLAIM_LEDGER_OUTPUT_ARTIFACTS
from modules.research_agent_controller.skills.claim_ledger_tools import validate_claim_ledger_artifact
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "claim_ledger_task"


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(TASK_ID, task_markdown=f"# Task\n\nTopic: {TOPIC}\n")
    return tmp_path / "research_agent/research_tasks" / TASK_ID


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _execution(workspace_root: Path, *, input_artifacts: list[str] | None = None) -> SkillExecutionInput:
    return SkillExecutionInput(
        task_id=TASK_ID,
        workspace_root=str(workspace_root),
        skill_name="build_claim_ledger",
        input_artifacts=list(input_artifacts or []),
        parameters={"topic": TOPIC},
    )


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
            "landscape_id": "landscape_claim_ledger_task",
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
            "landscape_id": "landscape_claim_ledger_task",
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
            "gap_map_id": "gap_map_claim_ledger_task",
            "landscape_id": "landscape_claim_ledger_task",
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
            "gap_map_id": "gap_map_claim_ledger_task",
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
            "idea_set_id": "candidate_ideas_claim_ledger_task",
            "gap_map_id": "gap_map_claim_ledger_task",
            "landscape_id": "landscape_claim_ledger_task",
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
            "idea_set_id": "candidate_ideas_claim_ledger_task",
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
            screening_id="idea_screening_claim_ledger_task",
            idea_set_id="candidate_ideas_claim_ledger_task",
            gap_map_id="gap_map_claim_ledger_task",
            landscape_id="landscape_claim_ledger_task",
        ),
    )
    _write_json(
        workspace_root / "screening/screening_diagnostics.json",
        {
            "artifact_type": "screening_diagnostics",
            "screening_id": "idea_screening_claim_ledger_task",
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
            "experiment_matrix_id": "experiment_matrix_claim_ledger_task",
            "input_artifacts": [],
            "screening_id": "idea_screening_claim_ledger_task",
            "idea_set_id": "candidate_ideas_claim_ledger_task",
            "gap_map_id": "gap_map_claim_ledger_task",
            "landscape_id": "landscape_claim_ledger_task",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "experiment_candidates": [
                {
                    "experiment_id": "exp_idea_gap_comparison_001",
                    "source_idea_id": "idea_gap_comparison_001",
                    "screened_idea_ref": "idea_screening_claim_ledger_task:idea_gap_comparison_001",
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
            "experiment_matrix_id": "experiment_matrix_claim_ledger_task",
            "experiment_candidate_count": 1,
            "warnings": ["experiment_matrix_diagnostics_fixture"],
            "schema_version": "experiment_matrix_v1",
        },
    )
    _write_text(
        workspace_root / "experiments/experiment_matrix.md",
        "# Experiment Matrix\n\n## Evidence References\n\n- experiment_id=exp_idea_gap_comparison_001; evidence_id=ecard_001\n",
    )


def test_claim_ledger_skill_is_available_and_executable_after_p2_m13_2() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("build_claim_ledger")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS
    assert registry.get_skill("draft_evidence_grounded_report").status == SkillStatus.STUB
    assert "draft_evidence_grounded_report" not in EVIDENCE_SKILL_WRAPPERS


def test_claim_ledger_wrapper_writes_bounded_schema_and_markdown(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_claim_ledger_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.SUCCESS
    assert result.output_artifacts == CLAIM_LEDGER_OUTPUT_ARTIFACTS
    artifact = _read_json(workspace_root / "claims/claim_ledger.json")
    diagnostics = _read_json(workspace_root / "claims/claim_ledger_diagnostics.json")
    markdown = (workspace_root / "claims/claim_ledger.md").read_text(encoding="utf-8")

    assert artifact["schema_version"] == "claim_ledger_v1"
    assert artifact["claim_ledger_id"]
    assert artifact["experiment_matrix_id"] == "experiment_matrix_claim_ledger_task"
    assert artifact["screening_id"] == "idea_screening_claim_ledger_task"
    assert artifact["idea_set_id"] == "candidate_ideas_claim_ledger_task"
    assert artifact["gap_map_id"] == "gap_map_claim_ledger_task"
    assert artifact["landscape_id"] == "landscape_claim_ledger_task"
    assert artifact["claims"]
    claim_types = {claim["claim_type"] for claim in artifact["claims"]}
    assert {
        "literature_observation",
        "gap_statement",
        "candidate_hypothesis",
        "screening_assessment",
        "experiment_matrix_rationale",
        "limitation_statement",
    }.issubset(claim_types)
    for claim in artifact["claims"]:
        assert claim["claim_id"]
        assert claim["claim_type"]
        assert claim["claim_status"]
        assert claim["source_artifacts"]
        if claim["claim_status"] not in {"insufficient_support", "rejected_overclaim"}:
            assert claim["evidence_ids"]
        assert claim["not_a_final_claim"] is True
        assert claim["not_experimentally_validated"] is True
        assert claim["requires_human_review"] is True
    assert "## Evidence References" in markdown
    for forbidden in [
        "## Manuscript Draft",
        "## Abstract",
        "## Results And Discussion",
        "## Conclusion",
        "## Final Claims",
    ]:
        assert forbidden not in markdown
    assert validate_claim_ledger_artifact(artifact, markdown) == []
    assert diagnostics["claim_count"] == len(artifact["claims"])
    assert "experiment_matrix_sparse_fixture" in artifact["warnings"]
    assert "screening_sparse_fixture" in artifact["warnings"]
    assert result.metadata["llm_called"] is False
    assert result.metadata["manuscript_drafting_performed"] is False
    assert result.metadata["final_claims_generated"] is False


def test_claim_ledger_result_can_be_registered_in_manifest_and_audit(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_claim_ledger_inputs(workspace_root)
    result = execute_evidence_skill(_execution(workspace_root))

    record_skill_execution_result(result, workspace_root)

    manifest = load_artifact_manifest(workspace_root, TASK_ID)
    paths = {artifact.path for artifact in manifest.artifacts}
    assert set(result.output_artifacts).issubset(paths)
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")


def test_claim_ledger_rejects_retrieval_input_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_claim_ledger_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root, input_artifacts=["retrieval/source_candidate_packet.json"]))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_claim_ledger" in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_claim_ledger_blocks_when_required_inputs_are_missing(tmp_path: Path) -> None:
    cases = [
        ("experiments/experiment_matrix.json", "missing_experiment_matrix_artifact"),
        ("screening/idea_screening_results.json", "missing_screening_results_artifact"),
        ("ideas/candidate_ideas.json", "missing_candidate_ideas_artifact"),
        ("gaps/gap_map.json", "missing_gap_map_artifact"),
        ("landscape/literature_landscape.json", "missing_landscape_artifact"),
        ("evidence/evidence_cards.enriched.json", "missing_input_artifact:evidence/evidence_cards.enriched.json"),
    ]
    for relative_path, expected_error in cases:
        workspace_root = _workspace(tmp_path / relative_path.replace("/", "_"))
        _write_claim_ledger_inputs(workspace_root)
        (workspace_root / relative_path).unlink()

        result = execute_evidence_skill(_execution(workspace_root))

        assert result.status == SkillExecutionStatus.BLOCKED
        assert expected_error in result.errors
        assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_claim_ledger_rejects_experiment_matrix_without_candidates(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_claim_ledger_inputs(workspace_root)
    experiment_matrix = _read_json(workspace_root / "experiments/experiment_matrix.json")
    experiment_matrix["experiment_candidates"] = []
    _write_json(workspace_root / "experiments/experiment_matrix.json", experiment_matrix)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "claim_ledger_requires_experiment_matrix" in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_claim_ledger_rejects_candidate_without_traceable_evidence_basis(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_claim_ledger_inputs(workspace_root)
    experiment_matrix = _read_json(workspace_root / "experiments/experiment_matrix.json")
    experiment_matrix["experiment_candidates"][0]["evidence_ids"] = []
    _write_json(workspace_root / "experiments/experiment_matrix.json", experiment_matrix)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "claim_ledger_requires_traceable_evidence_basis" in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_claim_ledger_rejects_validated_result_claim_language(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_claim_ledger_inputs(workspace_root)
    experiment_matrix = _read_json(workspace_root / "experiments/experiment_matrix.json")
    experiment_matrix["experiment_candidates"][0]["hypothesis_under_test"] = "We demonstrate this validated mechanism will improve performance."
    _write_json(workspace_root / "experiments/experiment_matrix.json", experiment_matrix)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "claim_ledger_rejects_validated_result_claim" in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_claim_ledger_validation_rejects_forbidden_claims_and_sections() -> None:
    artifact = {
        "schema_version": "claim_ledger_v1",
        "claim_ledger_id": "claim_ledger_task",
        "experiment_matrix_id": "experiment_matrix_task",
        "screening_id": "screening_task",
        "idea_set_id": "ideas_task",
        "gap_map_id": "gap_map_task",
        "landscape_id": "landscape_task",
        "evidence_ids": ["ecard_001"],
        "claims": [
            {
                "claim_id": "claim_001",
                "claim_text": "We demonstrate this experimentally validated result.",
                "claim_type": "candidate_hypothesis",
                "claim_status": "hypothesis_requires_validation",
                "source_artifacts": ["experiments/experiment_matrix.json"],
                "evidence_ids": ["ecard_001"],
                "not_a_final_claim": True,
                "not_experimentally_validated": True,
                "requires_human_review": True,
            }
        ],
    }
    markdown = "# Claim Ledger\n\n## Abstract\n\nWe conclude this is ready for publication.\n"

    errors = validate_claim_ledger_artifact(artifact, markdown)

    assert "forbidden_claim_ledger_markdown_section:Abstract" in errors
    assert "markdown_missing_evidence_references" in errors
    assert "claim_ledger_rejects_validated_result_claim" in errors


def test_claim_ledger_tools_have_no_cli_llm_database_or_controller_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/claim_ledger_tools.py").read_text(encoding="utf-8")
    forbidden = [
        "RealClaudeCodeCliBackend",
        "ClaudeCodeBackedMinimalController",
        "PlatformNativeFallbackController",
        "LiteratureResearchService",
        "core.memory_db",
        "sqlite",
        "subprocess",
        "claude",
        "OpenAI",
        "DeepSeek",
        "llm_client",
        "modules.evidence_workflow",
        "modules.workflow",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in source
