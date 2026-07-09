import pytest

from modules.research_agent_controller import (
    SkillDatabaseAccess,
    SkillStatus,
    build_default_skill_registry,
)
from modules.research_agent_controller.skills.evidence_tools import EVIDENCE_SKILL_WRAPPERS


def test_claim_ledger_registry_contract_exists_and_is_stub_safe_available() -> None:
    from modules.research_agent_controller.skills.claim_ledger_contract import (
        CLAIM_LEDGER_OUTPUT_ARTIFACTS,
        CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
    )

    registry = build_default_skill_registry()
    contract = registry.get_skill("build_claim_ledger")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.database_access == SkillDatabaseAccess.NONE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert contract.writes_artifacts is True
    assert contract.required_artifacts == CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS
    assert contract.produced_artifacts == CLAIM_LEDGER_OUTPUT_ARTIFACTS
    assert "raw_retrieval_candidates_not_allowed_for_claim_ledger" in contract.validation_rules
    assert "missing_experiment_matrix_artifact" in contract.failure_modes
    assert "claim_ledger_requires_traceable_evidence_basis" in contract.failure_modes
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS


def test_claim_ledger_contract_declares_legal_optional_and_forbidden_inputs() -> None:
    from modules.research_agent_controller.skills.claim_ledger_contract import (
        CLAIM_LEDGER_FORBIDDEN_INPUT_ARTIFACTS,
        CLAIM_LEDGER_OPTIONAL_INPUT_ARTIFACTS,
        CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
        validate_claim_ledger_input_artifacts,
    )

    assert CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS == [
        "experiments/experiment_matrix.json",
        "experiments/experiment_matrix_diagnostics.json",
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
    assert CLAIM_LEDGER_OPTIONAL_INPUT_ARTIFACTS == [
        "experiments/experiment_matrix.md",
        "screening/idea_screening_results.md",
        "ideas/candidate_ideas.md",
        "gaps/gap_map.md",
        "landscape/literature_landscape.md",
        "reports/minimal_topic_to_evidence_report.json",
    ]
    assert "retrieval/source_candidate_packet.json" in CLAIM_LEDGER_FORBIDDEN_INPUT_ARTIFACTS
    assert "retrieval/retrieval_warnings.json" in CLAIM_LEDGER_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_card_seeds.json" in CLAIM_LEDGER_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_cards.initial.json" in CLAIM_LEDGER_FORBIDDEN_INPUT_ARTIFACTS

    errors = validate_claim_ledger_input_artifacts(
        [
            "retrieval/source_candidate_packet.json",
            "raw_chunks/paper_001/chunk_001.json",
            "papers/paper_001.md",
            "experiments/experiment_matrix.md",
            "evidence/evidence_cards.initial.json",
        ]
    )

    assert "raw_retrieval_candidates_not_allowed_for_claim_ledger" in errors
    assert "raw_chunks_not_allowed_for_claim_ledger:raw_chunks/paper_001/chunk_001.json" in errors
    assert "raw_markdown_not_allowed_for_claim_ledger:papers/paper_001.md" in errors
    assert "unenriched_evidence_not_allowed_for_claim_ledger:evidence/evidence_cards.initial.json" in errors
    assert "missing_experiment_matrix_artifact" in errors
    assert "claim_ledger_requires_traceable_evidence_basis" in errors


def test_claim_ledger_output_paths_and_markdown_sections_are_bounded() -> None:
    from modules.research_agent_controller.skills.claim_ledger_contract import (
        CLAIM_LEDGER_ALLOWED_MARKDOWN_SECTIONS,
        CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS,
        CLAIM_LEDGER_OUTPUT_ARTIFACTS,
    )

    assert CLAIM_LEDGER_OUTPUT_ARTIFACTS == [
        "claims/claim_ledger.json",
        "claims/claim_ledger.md",
        "claims/claim_ledger_diagnostics.json",
    ]
    assert "Evidence References" in CLAIM_LEDGER_ALLOWED_MARKDOWN_SECTIONS
    assert "Manuscript Draft" in CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Abstract" in CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Results And Discussion" in CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Conclusion" in CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Final Claims" in CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS


def test_claim_ledger_schema_serializes_and_requires_bounded_claim_records() -> None:
    from modules.research_agent_controller.skills.claim_ledger_contract import (
        CLAIM_LEDGER_SCHEMA_VERSION,
        ClaimLedgerArtifact,
        ClaimRecord,
        UpstreamDependencies,
    )

    claim = ClaimRecord(
        claim_id="claim_001",
        claim_text="Oxygen vacancy effects remain a candidate hypothesis requiring validation.",
        claim_type="candidate_hypothesis",
        claim_status="hypothesis_requires_validation",
        source_artifacts=["experiments/experiment_matrix.json"],
        source_idea_ids=["idea_gap_comparison_001"],
        source_experiment_ids=["exp_idea_gap_comparison_001"],
        gap_ids=["gap_comparison_001"],
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        supporting_evidence=[{"evidence_id": "ecard_001", "paper_id": "paper_001"}],
        upstream_dependencies=UpstreamDependencies(
            experiment_matrix_ids=["experiment_matrix_task_1"],
            screening_ids=["idea_screening_task_1"],
            idea_set_ids=["candidate_ideas_task_1"],
            landscape_cluster_ids=["cluster_mechanism"],
            diagnostic_refs=["coverage:missing_figure_source_type"],
        ),
        support_level="low",
        allowed_downstream_use="hypothesis_framing",
        prohibited_uses=["final_claim", "manuscript_conclusion"],
        limitations=["Requires experimental validation and human review."],
    )
    artifact = ClaimLedgerArtifact(
        task_id="task_1",
        topic="oxygen vacancy engineering for alkaline HER catalysts",
        claim_ledger_id="claim_ledger_task_1",
        input_artifacts=["experiments/experiment_matrix.json"],
        experiment_matrix_id="experiment_matrix_task_1",
        screening_id="idea_screening_task_1",
        idea_set_id="candidate_ideas_task_1",
        gap_map_id="gap_map_task_1",
        landscape_id="landscape_task_1",
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        claims=[claim],
    )

    data = artifact.as_dict()

    assert data["schema_version"] == CLAIM_LEDGER_SCHEMA_VERSION
    assert data["claims"][0]["claim_id"] == "claim_001"
    assert data["claims"][0]["claim_type"] == "candidate_hypothesis"
    assert data["claims"][0]["claim_status"] == "hypothesis_requires_validation"
    assert data["claims"][0]["source_artifacts"] == ["experiments/experiment_matrix.json"]
    assert data["claims"][0]["evidence_ids"] == ["ecard_001"]
    assert data["claims"][0]["not_a_final_claim"] is True
    assert data["claims"][0]["not_experimentally_validated"] is True
    assert data["claims"][0]["requires_human_review"] is True

    with pytest.raises(ValueError, match="claim_record_requires_claim_id"):
        ClaimRecord(
            claim_id="",
            claim_text="Missing id.",
            claim_type="candidate_hypothesis",
            claim_status="hypothesis_requires_validation",
            source_artifacts=["experiments/experiment_matrix.json"],
            evidence_ids=["ecard_001"],
        )

    with pytest.raises(ValueError, match="invalid_claim_type"):
        ClaimRecord(
            claim_id="claim_bad_type",
            claim_text="Bad type.",
            claim_type="final_conclusion",
            claim_status="hypothesis_requires_validation",
            source_artifacts=["experiments/experiment_matrix.json"],
            evidence_ids=["ecard_001"],
        )

    with pytest.raises(ValueError, match="claim_record_must_not_be_final_claim"):
        ClaimRecord(
            claim_id="claim_final",
            claim_text="Bad final claim.",
            claim_type="candidate_hypothesis",
            claim_status="hypothesis_requires_validation",
            source_artifacts=["experiments/experiment_matrix.json"],
            evidence_ids=["ecard_001"],
            not_a_final_claim=False,
        )


def test_legacy_evidence_grounded_report_skill_remains_stub_after_claim_ledger_wrapper() -> None:
    registry = build_default_skill_registry()

    assert registry.get_skill("build_claim_ledger").status == SkillStatus.AVAILABLE
    assert registry.get_skill("draft_manuscript_section").status == SkillStatus.AVAILABLE
    assert registry.get_skill("draft_evidence_grounded_report").status == SkillStatus.STUB
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS
    assert "draft_manuscript_section" in EVIDENCE_SKILL_WRAPPERS
    assert "draft_evidence_grounded_report" not in EVIDENCE_SKILL_WRAPPERS
