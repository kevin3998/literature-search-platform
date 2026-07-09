from pathlib import Path

import pytest

from modules.research_agent_controller import (
    SkillDatabaseAccess,
    SkillStatus,
    build_default_skill_registry,
)
from modules.research_agent_controller.skills.evidence_tools import EVIDENCE_SKILL_WRAPPERS


def test_experiment_matrix_registry_contract_exists_and_is_stub_safe_available() -> None:
    from modules.research_agent_controller.skills.experiment_matrix_contract import (
        EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS,
        EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
    )

    registry = build_default_skill_registry()
    contract = registry.get_skill("create_experiment_matrix")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.database_access == SkillDatabaseAccess.NONE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert contract.writes_artifacts is True
    assert contract.required_artifacts == EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS
    assert contract.produced_artifacts == EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS
    assert "raw_retrieval_candidates_not_allowed_for_experiment_matrix" in contract.validation_rules
    assert "missing_screening_results_artifact" in contract.failure_modes
    assert "experiment_matrix_requires_screened_ideas" in contract.failure_modes
    assert "create_experiment_matrix" in EVIDENCE_SKILL_WRAPPERS


def test_experiment_matrix_contract_declares_legal_optional_and_forbidden_inputs() -> None:
    from modules.research_agent_controller.skills.experiment_matrix_contract import (
        EXPERIMENT_MATRIX_FORBIDDEN_INPUT_ARTIFACTS,
        EXPERIMENT_MATRIX_OPTIONAL_INPUT_ARTIFACTS,
        EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
        validate_experiment_matrix_input_artifacts,
    )

    assert EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS == [
        "screening/idea_screening_results.json",
        "screening/screening_diagnostics.json",
        "ideas/candidate_ideas.json",
        "ideas/idea_generation_diagnostics.json",
        "gaps/gap_map.json",
        "gaps/gap_coverage_diagnostics.json",
        "landscape/literature_landscape.json",
        "landscape/landscape_coverage_diagnostics.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    ]
    assert EXPERIMENT_MATRIX_OPTIONAL_INPUT_ARTIFACTS == [
        "screening/idea_screening_results.md",
        "ideas/candidate_ideas.md",
        "gaps/gap_map.md",
        "landscape/literature_landscape.md",
        "reports/minimal_topic_to_evidence_report.json",
    ]
    assert "retrieval/source_candidate_packet.json" in EXPERIMENT_MATRIX_FORBIDDEN_INPUT_ARTIFACTS
    assert "retrieval/retrieval_warnings.json" in EXPERIMENT_MATRIX_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_card_seeds.json" in EXPERIMENT_MATRIX_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_cards.initial.json" in EXPERIMENT_MATRIX_FORBIDDEN_INPUT_ARTIFACTS

    errors = validate_experiment_matrix_input_artifacts(
        [
            "retrieval/source_candidate_packet.json",
            "raw_chunks/paper_001/chunk_001.json",
            "papers/paper_001.md",
            "screening/idea_screening_results.md",
            "ideas/candidate_ideas.md",
            "evidence/evidence_cards.initial.json",
        ]
    )

    assert "raw_retrieval_candidates_not_allowed_for_experiment_matrix" in errors
    assert "raw_chunks_not_allowed_for_experiment_matrix:raw_chunks/paper_001/chunk_001.json" in errors
    assert "raw_markdown_not_allowed_for_experiment_matrix:papers/paper_001.md" in errors
    assert "unenriched_evidence_not_allowed_for_experiment_matrix:evidence/evidence_cards.initial.json" in errors
    assert "missing_screening_results_artifact" in errors
    assert "experiment_matrix_requires_gap_and_evidence_basis" in errors


def test_experiment_matrix_output_paths_and_markdown_sections_are_bounded() -> None:
    from modules.research_agent_controller.skills.experiment_matrix_contract import (
        EXPERIMENT_MATRIX_ALLOWED_MARKDOWN_SECTIONS,
        EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS,
        EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS,
    )

    assert EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS == [
        "experiments/experiment_matrix.json",
        "experiments/experiment_matrix.md",
        "experiments/experiment_matrix_diagnostics.json",
    ]
    assert "Evidence References" in EXPERIMENT_MATRIX_ALLOWED_MARKDOWN_SECTIONS
    assert "Experimental Protocol" in EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Step-by-step Procedure" in EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Synthesis Recipe" in EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Safety Protocol" in EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Manuscript Draft" in EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Final Claims" in EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS


def test_experiment_matrix_schema_serializes_and_requires_traceable_bounded_candidates() -> None:
    from modules.research_agent_controller.skills.experiment_matrix_contract import (
        EXPERIMENT_MATRIX_SCHEMA_VERSION,
        CharacterizationTarget,
        DesignVariable,
        ExperimentCandidate,
        ExperimentMatrixArtifact,
        ExperimentScreeningBasis,
    )

    candidate = ExperimentCandidate(
        experiment_id="exp_idea_1",
        source_idea_id="idea_1",
        screened_idea_ref="screening_1:idea_1",
        objective="Compare a bounded oxygen vacancy variable against a control condition.",
        hypothesis_under_test="Oxygen vacancy modulation should be tested as a hypothesis, not treated as a claim.",
        gap_ids=["gap_1"],
        evidence_ids=["ecard_001"],
        screening_basis=ExperimentScreeningBasis(
            novelty_status="requires_external_search",
            feasibility_status="requires_expert_review",
            risk_status="requires_risk_review",
            required_follow_up=["external novelty search", "expert feasibility review", "risk review"],
            limitations=["P2-M12.1 is contract-only."],
        ),
        design_variables=[
            DesignVariable(
                variable_id="var_1",
                name="oxygen vacancy level",
                role="defect",
                allowed_level_description="bounded qualitative levels only; no synthesis recipe",
                rationale="Linked to screened idea idea_1.",
                evidence_refs=["ecard_001"],
            )
        ],
        control_groups=["baseline catalyst without the candidate variation"],
        comparison_groups=["candidate variation group"],
        characterization_targets=[
            CharacterizationTarget(
                target_id="target_1",
                target="oxygen vacancy indication",
                purpose="verify_defect",
                linked_gap_ids=["gap_1"],
                linked_evidence_ids=["ecard_001"],
                expected_evidence_type="characterization evidence",
            )
        ],
        expected_observations=["Record observations needed to evaluate the hypothesis."],
        decision_criteria=["Compare against controls without asserting guaranteed performance improvement."],
        data_to_record=["sample id", "condition label", "characterization readout"],
        constraints=["Requires expert review before execution."],
        risk_notes=["No safety protocol is specified in P2-M12.1."],
    )
    artifact = ExperimentMatrixArtifact(
        task_id="task_1",
        topic="oxygen vacancy engineering for alkaline HER catalysts",
        experiment_matrix_id="experiment_matrix_task_1",
        input_artifacts=["screening/idea_screening_results.json"],
        screening_id="idea_screening_task_1",
        idea_set_id="candidate_ideas_task_1",
        gap_map_id="gap_map_task_1",
        landscape_id="landscape_task_1",
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        experiment_candidates=[candidate],
    )

    data = artifact.as_dict()

    assert data["schema_version"] == EXPERIMENT_MATRIX_SCHEMA_VERSION
    assert data["experiment_candidates"][0]["source_idea_id"] == "idea_1"
    assert data["experiment_candidates"][0]["gap_ids"] == ["gap_1"]
    assert data["experiment_candidates"][0]["evidence_ids"] == ["ecard_001"]
    assert data["experiment_candidates"][0]["screening_basis"]["novelty_status"] == "requires_external_search"
    assert data["experiment_candidates"][0]["not_a_protocol"] is True
    assert data["experiment_candidates"][0]["not_a_validated_claim"] is True
    assert data["experiment_candidates"][0]["requires_expert_review"] is True
    assert data["experiment_candidates"][0]["design_variables"][0]["not_a_stepwise_instruction"] is True

    with pytest.raises(ValueError, match="experiment_candidate_requires_source_idea_id"):
        ExperimentCandidate(
            experiment_id="exp_missing_idea",
            source_idea_id="",
            screened_idea_ref="screening_1:idea_1",
            objective="Missing source idea.",
            hypothesis_under_test="Missing source idea.",
            gap_ids=["gap_1"],
            evidence_ids=["ecard_001"],
            screening_basis=ExperimentScreeningBasis(
                novelty_status="requires_external_search",
                feasibility_status="requires_expert_review",
                risk_status="requires_risk_review",
            ),
        )

    with pytest.raises(ValueError, match="experiment_candidate_requires_gap_ids"):
        ExperimentCandidate(
            experiment_id="exp_missing_gap",
            source_idea_id="idea_1",
            screened_idea_ref="screening_1:idea_1",
            objective="Missing gaps.",
            hypothesis_under_test="Missing gaps.",
            gap_ids=[],
            evidence_ids=["ecard_001"],
            screening_basis=ExperimentScreeningBasis(
                novelty_status="requires_external_search",
                feasibility_status="requires_expert_review",
                risk_status="requires_risk_review",
            ),
        )

    with pytest.raises(ValueError, match="experiment_candidate_requires_evidence_ids"):
        ExperimentCandidate(
            experiment_id="exp_missing_evidence",
            source_idea_id="idea_1",
            screened_idea_ref="screening_1:idea_1",
            objective="Missing evidence.",
            hypothesis_under_test="Missing evidence.",
            gap_ids=["gap_1"],
            evidence_ids=[],
            screening_basis=ExperimentScreeningBasis(
                novelty_status="requires_external_search",
                feasibility_status="requires_expert_review",
                risk_status="requires_risk_review",
            ),
        )

    with pytest.raises(ValueError, match="experiment_candidate_must_not_be_protocol"):
        ExperimentCandidate(
            experiment_id="exp_bad_protocol",
            source_idea_id="idea_1",
            screened_idea_ref="screening_1:idea_1",
            objective="Bad protocol flag.",
            hypothesis_under_test="Bad protocol flag.",
            gap_ids=["gap_1"],
            evidence_ids=["ecard_001"],
            screening_basis=ExperimentScreeningBasis(
                novelty_status="requires_external_search",
                feasibility_status="requires_expert_review",
                risk_status="requires_risk_review",
            ),
            not_a_protocol=False,
        )

    with pytest.raises(ValueError, match="experiment_candidate_requires_expert_review"):
        ExperimentCandidate(
            experiment_id="exp_bad_review",
            source_idea_id="idea_1",
            screened_idea_ref="screening_1:idea_1",
            objective="Bad expert review flag.",
            hypothesis_under_test="Bad expert review flag.",
            gap_ids=["gap_1"],
            evidence_ids=["ecard_001"],
            screening_basis=ExperimentScreeningBasis(
                novelty_status="requires_external_search",
                feasibility_status="requires_expert_review",
                risk_status="requires_risk_review",
            ),
            requires_expert_review=False,
        )


def test_experiment_matrix_contract_boundary_has_no_runtime_controller_cli_or_database_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/experiment_matrix_contract.py").read_text(encoding="utf-8")
    forbidden = [
        "RealClaudeCodeCliBackend",
        "ClaudeCodeBackedMinimalController",
        "PlatformNativeFallbackController",
        "execute_evidence_skill",
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


def test_p2_m14_plus_skills_remain_non_executable() -> None:
    future_skills = {
        "draft_evidence_grounded_report",
    }
    registry = build_default_skill_registry()

    assert future_skills.isdisjoint(EVIDENCE_SKILL_WRAPPERS)
    assert future_skills.issubset({skill.name for skill in registry.list_stub_skills()})
    assert registry.get_skill("build_claim_ledger").status == SkillStatus.AVAILABLE
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS
