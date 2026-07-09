from pathlib import Path

import pytest

from modules.research_agent_controller import SkillStatus, build_default_skill_registry
from modules.research_agent_controller.skills.evidence_tools import EVIDENCE_SKILL_WRAPPERS


def test_build_landscape_registry_contract_is_available_and_evidence_gated() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("build_landscape")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert contract.writes_artifacts is True
    assert contract.produced_artifacts == [
        "landscape/literature_landscape.json",
        "landscape/literature_landscape.md",
        "landscape/landscape_coverage_diagnostics.json",
    ]
    assert "evidence/evidence_cards.enriched.json" in contract.required_artifacts
    assert "ranked_evidence/evidence_selection.json" in contract.required_artifacts
    assert "ranked_evidence/coverage_diagnostics.json" in contract.required_artifacts


def test_build_landscape_has_stub_safe_executable_wrapper() -> None:
    assert "build_landscape" in EVIDENCE_SKILL_WRAPPERS


def test_landscape_contract_declares_legal_and_forbidden_inputs() -> None:
    from modules.research_agent_controller.skills.landscape_contract import (
        LANDSCAPE_FORBIDDEN_INPUT_ARTIFACTS,
        LANDSCAPE_REQUIRED_INPUT_ARTIFACTS,
        validate_landscape_input_artifacts,
    )

    assert LANDSCAPE_REQUIRED_INPUT_ARTIFACTS == [
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    ]
    assert "retrieval/source_candidate_packet.json" in LANDSCAPE_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_card_seeds.json" in LANDSCAPE_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_cards.initial.json" in LANDSCAPE_FORBIDDEN_INPUT_ARTIFACTS

    errors = validate_landscape_input_artifacts(["retrieval/source_candidate_packet.json"])

    assert "raw_retrieval_candidates_not_allowed_for_landscape" in errors


def test_landscape_output_paths_and_markdown_sections_are_bounded() -> None:
    from modules.research_agent_controller.skills.landscape_contract import (
        LANDSCAPE_ALLOWED_MARKDOWN_SECTIONS,
        LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS,
        LANDSCAPE_OUTPUT_ARTIFACTS,
    )

    assert LANDSCAPE_OUTPUT_ARTIFACTS == [
        "landscape/literature_landscape.json",
        "landscape/literature_landscape.md",
        "landscape/landscape_coverage_diagnostics.json",
    ]
    assert "Evidence References" in LANDSCAPE_ALLOWED_MARKDOWN_SECTIONS
    assert "Research Gaps" in LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Candidate Ideas" in LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Novelty Screening" in LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Experiment Plan" in LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Manuscript Draft" in LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS


def test_landscape_schema_serializes_and_requires_evidence_references() -> None:
    from modules.research_agent_controller.skills.landscape_contract import (
        LANDSCAPE_SCHEMA_VERSION,
        LandscapeArtifact,
        LandscapeAxis,
        LandscapeCluster,
        RepresentativeEvidence,
    )

    artifact = LandscapeArtifact(
        task_id="task_1",
        topic="oxygen vacancy engineering for alkaline HER catalysts",
        landscape_id="landscape_task_1",
        input_artifacts=[
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
        ],
        evidence_ids=["ev_1"],
        source_paper_ids=["paper_1"],
        landscape_axes=[
            LandscapeAxis(
                axis_id="mechanistic_role",
                name="Mechanistic role",
                description="Mechanistic roles represented in the evidence cards.",
                values=["water dissociation"],
            )
        ],
        clusters=[
            LandscapeCluster(
                cluster_id="cluster_1",
                title="Vacancy-assisted water dissociation",
                description="Evidence about oxygen vacancies and water dissociation.",
                axis_values={"mechanistic_role": ["water dissociation"]},
                evidence_ids=["ev_1"],
                source_paper_ids=["paper_1"],
                representative_claims=[
                    {
                        "claim": "Oxygen vacancies can modulate water dissociation.",
                        "evidence_ids": ["ev_1"],
                    }
                ],
                confidence="medium",
            )
        ],
        coverage={"num_evidence_cards": 1, "num_selected_evidence": 1},
        representative_evidence=[
            RepresentativeEvidence(
                evidence_id="ev_1",
                paper_id="paper_1",
                role="mechanism",
                source_type="text",
                cluster_ids=["cluster_1"],
                reason="Representative mechanism evidence.",
            )
        ],
    )

    data = artifact.as_dict()

    assert data["schema_version"] == LANDSCAPE_SCHEMA_VERSION
    assert data["clusters"][0]["evidence_ids"] == ["ev_1"]
    assert data["representative_evidence"][0]["evidence_id"] == "ev_1"

    with pytest.raises(ValueError, match="cluster_requires_evidence_ids"):
        LandscapeCluster(
            cluster_id="unsupported",
            title="Unsupported cluster",
            description="No evidence.",
            evidence_ids=[],
        )


def test_landscape_contract_boundary_has_no_runtime_or_database_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/landscape_contract.py").read_text(encoding="utf-8")
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
