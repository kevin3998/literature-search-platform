from pathlib import Path

import pytest

from modules.research_agent_controller import SkillStatus, build_default_skill_registry
from modules.research_agent_controller.skills.evidence_tools import EVIDENCE_SKILL_WRAPPERS


def test_map_gaps_registry_contract_is_available_and_evidence_gated() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("map_gaps")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert contract.writes_artifacts is True
    assert contract.produced_artifacts == [
        "gaps/gap_map.json",
        "gaps/gap_map.md",
        "gaps/gap_coverage_diagnostics.json",
    ]
    assert "landscape/literature_landscape.json" in contract.required_artifacts
    assert "landscape/landscape_coverage_diagnostics.json" in contract.required_artifacts
    assert "evidence/evidence_cards.enriched.json" in contract.required_artifacts
    assert "ranked_evidence/evidence_selection.json" in contract.required_artifacts
    assert "ranked_evidence/coverage_diagnostics.json" in contract.required_artifacts


def test_map_gaps_has_stub_safe_executable_wrapper() -> None:
    assert "map_gaps" in EVIDENCE_SKILL_WRAPPERS


def test_gap_contract_declares_legal_and_forbidden_inputs() -> None:
    from modules.research_agent_controller.skills.gap_contract import (
        GAP_FORBIDDEN_INPUT_ARTIFACTS,
        GAP_REQUIRED_INPUT_ARTIFACTS,
        validate_gap_mapping_input_artifacts,
    )

    assert GAP_REQUIRED_INPUT_ARTIFACTS == [
        "landscape/literature_landscape.json",
        "landscape/landscape_coverage_diagnostics.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    ]
    assert "retrieval/source_candidate_packet.json" in GAP_FORBIDDEN_INPUT_ARTIFACTS
    assert "retrieval/retrieval_warnings.json" in GAP_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_card_seeds.json" in GAP_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_cards.initial.json" in GAP_FORBIDDEN_INPUT_ARTIFACTS

    errors = validate_gap_mapping_input_artifacts(
        [
            "retrieval/source_candidate_packet.json",
            "raw_chunks/paper_001/chunk_001.json",
            "papers/paper_001.md",
            "evidence/evidence_card_seeds.json",
            "landscape/literature_landscape.md",
        ]
    )

    assert "raw_retrieval_candidates_not_allowed_for_gap_mapping" in errors
    assert "raw_chunks_not_allowed_for_gap_mapping:raw_chunks/paper_001/chunk_001.json" in errors
    assert "raw_markdown_not_allowed_for_gap_mapping:papers/paper_001.md" in errors
    assert "unenriched_evidence_not_allowed_for_gap_mapping:evidence/evidence_card_seeds.json" in errors
    assert "missing_landscape_artifact" in errors


def test_gap_output_paths_and_markdown_sections_are_bounded() -> None:
    from modules.research_agent_controller.skills.gap_contract import (
        GAP_ALLOWED_MARKDOWN_SECTIONS,
        GAP_FORBIDDEN_MARKDOWN_SECTIONS,
        GAP_OUTPUT_ARTIFACTS,
    )

    assert GAP_OUTPUT_ARTIFACTS == [
        "gaps/gap_map.json",
        "gaps/gap_map.md",
        "gaps/gap_coverage_diagnostics.json",
    ]
    assert "Evidence References" in GAP_ALLOWED_MARKDOWN_SECTIONS
    assert "Candidate Ideas" in GAP_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Proposed Research Directions" in GAP_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Novelty Screening" in GAP_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Feasibility Screening" in GAP_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Experiment Plan" in GAP_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Manuscript Draft" in GAP_FORBIDDEN_MARKDOWN_SECTIONS


def test_gap_map_schema_serializes_and_requires_basis_not_idea() -> None:
    from modules.research_agent_controller.skills.gap_contract import (
        GAP_MAP_SCHEMA_VERSION,
        GapAxis,
        GapBasis,
        GapMapArtifact,
        GapRecord,
        SupportingEvidence,
    )

    artifact = GapMapArtifact(
        task_id="task_1",
        topic="oxygen vacancy engineering for alkaline HER catalysts",
        gap_map_id="gap_map_task_1",
        input_artifacts=[
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        landscape_id="landscape_task_1",
        evidence_ids=["ev_1"],
        source_paper_ids=["paper_1"],
        gap_axes=[
            GapAxis(
                axis_id="mechanistic_role",
                name="Mechanistic role",
                description="Coverage gaps across mechanistic roles.",
                source="landscape_axes",
            )
        ],
        gaps=[
            GapRecord(
                gap_id="gap_1",
                gap_type="coverage_gap",
                title="Limited direct mechanism coverage",
                description="Few selected cards directly cover water dissociation mechanisms.",
                axis_values={"mechanistic_role": ["water dissociation"]},
                basis=GapBasis(evidence_ids=["ev_1"], diagnostic_refs=["ranking:coverage_warnings"]),
                severity="medium",
                confidence="medium",
            )
        ],
        coverage={"num_evidence_cards": 1, "coverage_warnings": ["limited mechanism coverage"]},
        supporting_evidence=[
            SupportingEvidence(
                evidence_id="ev_1",
                paper_id="paper_1",
                role="mechanism",
                source_type="text",
                gap_ids=["gap_1"],
                reason="Selected mechanism evidence anchors the gap.",
            )
        ],
    )

    data = artifact.as_dict()

    assert data["schema_version"] == GAP_MAP_SCHEMA_VERSION
    assert data["gaps"][0]["basis"]["evidence_ids"] == ["ev_1"]
    assert data["gaps"][0]["not_an_idea"] is True
    assert data["supporting_evidence"][0]["evidence_id"] == "ev_1"

    with pytest.raises(ValueError, match="gap_requires_basis"):
        GapRecord(
            gap_id="unsupported",
            gap_type="coverage_gap",
            title="Unsupported gap",
            description="No basis.",
            basis=GapBasis(),
        )

    with pytest.raises(ValueError, match="gap_must_not_be_candidate_idea"):
        GapRecord(
            gap_id="idea_like",
            gap_type="coverage_gap",
            title="Idea-like gap",
            description="Should not pass.",
            basis=GapBasis(evidence_ids=["ev_1"]),
            not_an_idea=False,
        )


def test_gap_contract_boundary_has_no_runtime_or_database_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/gap_contract.py").read_text(encoding="utf-8")
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
        "modules.evidence_workflow",
        "modules.workflow",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in source
