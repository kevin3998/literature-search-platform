from pathlib import Path

import pytest

from modules.research_agent_controller import (
    SkillDatabaseAccess,
    SkillStatus,
    build_default_skill_registry,
)
from modules.research_agent_controller.skills.evidence_tools import EVIDENCE_SKILL_WRAPPERS


def test_generate_candidate_ideas_registry_contract_is_available_and_evidence_gated() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("generate_candidate_ideas")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert contract.database_access == SkillDatabaseAccess.NONE
    assert contract.writes_artifacts is True
    assert contract.required_artifacts == [
        "gaps/gap_map.json",
        "gaps/gap_coverage_diagnostics.json",
        "landscape/literature_landscape.json",
        "landscape/landscape_coverage_diagnostics.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    ]
    assert contract.produced_artifacts == [
        "ideas/candidate_ideas.json",
        "ideas/candidate_ideas.md",
        "ideas/idea_generation_diagnostics.json",
    ]
    assert "raw_retrieval_candidates_not_allowed_for_idea_generation" in contract.validation_rules
    assert "candidate_idea_requires_gap_basis" in contract.failure_modes


def test_generate_candidate_ideas_screening_and_experiment_matrix_are_executable_while_p2_m13_plus_remain_stubbed() -> None:
    assert "generate_candidate_ideas" in EVIDENCE_SKILL_WRAPPERS
    assert "screen_novelty_feasibility_risk" in EVIDENCE_SKILL_WRAPPERS
    assert "create_experiment_matrix" in EVIDENCE_SKILL_WRAPPERS
    assert "draft_manuscript_section" in EVIDENCE_SKILL_WRAPPERS
    assert "draft_evidence_grounded_report" not in EVIDENCE_SKILL_WRAPPERS


def test_idea_contract_declares_legal_and_forbidden_inputs() -> None:
    from modules.research_agent_controller.skills.idea_contract import (
        IDEA_FORBIDDEN_INPUT_ARTIFACTS,
        IDEA_REQUIRED_INPUT_ARTIFACTS,
        validate_idea_generation_input_artifacts,
    )

    assert IDEA_REQUIRED_INPUT_ARTIFACTS == [
        "gaps/gap_map.json",
        "gaps/gap_coverage_diagnostics.json",
        "landscape/literature_landscape.json",
        "landscape/landscape_coverage_diagnostics.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    ]
    assert "retrieval/source_candidate_packet.json" in IDEA_FORBIDDEN_INPUT_ARTIFACTS
    assert "retrieval/retrieval_warnings.json" in IDEA_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_card_seeds.json" in IDEA_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_cards.initial.json" in IDEA_FORBIDDEN_INPUT_ARTIFACTS

    errors = validate_idea_generation_input_artifacts(
        [
            "retrieval/source_candidate_packet.json",
            "raw_chunks/paper_001/chunk_001.json",
            "papers/paper_001.md",
            "evidence/evidence_cards.initial.json",
            "gaps/gap_map.md",
            "landscape/literature_landscape.md",
        ]
    )

    assert "raw_retrieval_candidates_not_allowed_for_idea_generation" in errors
    assert "raw_chunks_not_allowed_for_idea_generation:raw_chunks/paper_001/chunk_001.json" in errors
    assert "raw_markdown_not_allowed_for_idea_generation:papers/paper_001.md" in errors
    assert "unenriched_evidence_not_allowed_for_idea_generation:evidence/evidence_cards.initial.json" in errors
    assert "missing_gap_map_artifact" in errors
    assert "idea_generation_requires_evidence_references" in errors


def test_idea_output_paths_and_markdown_sections_are_bounded() -> None:
    from modules.research_agent_controller.skills.idea_contract import (
        IDEA_ALLOWED_MARKDOWN_SECTIONS,
        IDEA_FORBIDDEN_MARKDOWN_SECTIONS,
        IDEA_OUTPUT_ARTIFACTS,
    )

    assert IDEA_OUTPUT_ARTIFACTS == [
        "ideas/candidate_ideas.json",
        "ideas/candidate_ideas.md",
        "ideas/idea_generation_diagnostics.json",
    ]
    assert "Evidence References" in IDEA_ALLOWED_MARKDOWN_SECTIONS
    assert "Novelty Screening" in IDEA_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Feasibility Screening" in IDEA_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Risk Screening" in IDEA_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Experiment Plan" in IDEA_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Manuscript Draft" in IDEA_FORBIDDEN_MARKDOWN_SECTIONS


def test_candidate_idea_schema_serializes_and_requires_gap_and_evidence_basis() -> None:
    from modules.research_agent_controller.skills.idea_contract import (
        CANDIDATE_IDEAS_SCHEMA_VERSION,
        CandidateIdeaArtifact,
        CandidateIdeaEvidenceBasis,
        CandidateIdeaGapBasis,
        CandidateIdeaRecord,
    )

    idea = CandidateIdeaRecord(
        idea_id="idea_1",
        title="Compare oxygen vacancy stabilization routes",
        summary="Evaluate whether synthesis route differences explain the sparse mechanism coverage.",
        idea_type="comparative_study",
        gap_basis=CandidateIdeaGapBasis(
            gap_ids=["gap_1"],
            gap_types=["comparison_gap"],
            landscape_cluster_ids=["cluster_1"],
            evidence_ids=["ecard_001"],
            coverage_warnings=["limited_axis_mechanistic_role"],
            diagnostic_refs=["gap_map:gaps:gap_1"],
        ),
        evidence_basis=CandidateIdeaEvidenceBasis(
            supporting_evidence_ids=["ecard_001"],
            source_paper_ids=["paper_001"],
            representative_claim_refs=["landscape:cluster_1:claim_1"],
        ),
        rationale="The idea is grounded in a comparison gap and one supporting Evidence Card.",
        expected_contribution="Clarify whether synthesis route is a missing comparison axis.",
        assumptions=["Coverage is sparse in the current evidence base."],
        constraints=["Requires downstream novelty and feasibility screening."],
    )
    artifact = CandidateIdeaArtifact(
        task_id="task_1",
        topic="oxygen vacancy engineering for alkaline HER catalysts",
        idea_set_id="ideas_task_1",
        input_artifacts=[
            "gaps/gap_map.json",
            "gaps/gap_coverage_diagnostics.json",
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        gap_map_id="gap_map_task_1",
        landscape_id="landscape_task_1",
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        ideas=[idea],
    )

    data = artifact.as_dict()

    assert data["schema_version"] == CANDIDATE_IDEAS_SCHEMA_VERSION
    assert data["ideas"][0]["gap_basis"]["gap_ids"] == ["gap_1"]
    assert data["ideas"][0]["evidence_basis"]["supporting_evidence_ids"] == ["ecard_001"]
    assert data["ideas"][0]["not_yet_screened"] is True
    assert data["ideas"][0]["requires_novelty_screening"] is True
    assert data["ideas"][0]["requires_feasibility_screening"] is True

    with pytest.raises(ValueError, match="candidate_idea_requires_gap_basis"):
        CandidateIdeaRecord(
            idea_id="unsupported_gap",
            title="Unsupported gap",
            summary="No gap basis.",
            idea_type="comparative_study",
            gap_basis=CandidateIdeaGapBasis(),
            evidence_basis=CandidateIdeaEvidenceBasis(supporting_evidence_ids=["ecard_001"]),
        )

    with pytest.raises(ValueError, match="candidate_idea_requires_evidence_basis"):
        CandidateIdeaRecord(
            idea_id="unsupported_evidence",
            title="Unsupported evidence",
            summary="No evidence basis.",
            idea_type="comparative_study",
            gap_basis=CandidateIdeaGapBasis(gap_ids=["gap_1"]),
            evidence_basis=CandidateIdeaEvidenceBasis(),
        )

    with pytest.raises(ValueError, match="candidate_idea_must_remain_unscreened"):
        CandidateIdeaRecord(
            idea_id="screened",
            title="Already screened",
            summary="Should not pass P2-M10.1 contract.",
            idea_type="comparative_study",
            gap_basis=CandidateIdeaGapBasis(gap_ids=["gap_1"]),
            evidence_basis=CandidateIdeaEvidenceBasis(supporting_evidence_ids=["ecard_001"]),
            not_yet_screened=False,
        )


def test_idea_contract_boundary_has_no_runtime_or_database_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/idea_contract.py").read_text(encoding="utf-8")
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
        "llm_client",
        "modules.evidence_workflow",
        "modules.workflow",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in source
