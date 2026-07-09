from pathlib import Path

import pytest

from modules.research_agent_controller import (
    SkillDatabaseAccess,
    SkillExecutionMode,
    SkillStatus,
    build_default_skill_registry,
)
from modules.research_agent_controller.skills.evidence_tools import EVIDENCE_SKILL_WRAPPERS


def test_screening_registry_contract_exists_and_is_stub_safe_executable() -> None:
    from modules.research_agent_controller.skills.screening_contract import (
        SCREENING_OUTPUT_ARTIFACTS,
        SCREENING_REQUIRED_INPUT_ARTIFACTS,
    )

    registry = build_default_skill_registry()
    contract = registry.get_skill("screen_novelty_feasibility_risk")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.database_access == SkillDatabaseAccess.NONE
    assert contract.execution_mode == SkillExecutionMode.LLM_ASSISTED
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert contract.writes_artifacts is True
    assert contract.required_artifacts == SCREENING_REQUIRED_INPUT_ARTIFACTS
    assert contract.produced_artifacts == SCREENING_OUTPUT_ARTIFACTS
    assert "raw_retrieval_candidates_not_allowed_for_screening" in contract.validation_rules
    assert "missing_candidate_ideas_artifact" in contract.failure_modes
    assert "screening_requires_gap_and_evidence_basis" in contract.failure_modes
    assert "screen_novelty_feasibility_risk" in EVIDENCE_SKILL_WRAPPERS


def test_screening_contract_declares_legal_and_forbidden_inputs() -> None:
    from modules.research_agent_controller.skills.screening_contract import (
        SCREENING_FORBIDDEN_INPUT_ARTIFACTS,
        SCREENING_OPTIONAL_INPUT_ARTIFACTS,
        SCREENING_REQUIRED_INPUT_ARTIFACTS,
        validate_screening_input_artifacts,
    )

    assert SCREENING_REQUIRED_INPUT_ARTIFACTS == [
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
    assert SCREENING_OPTIONAL_INPUT_ARTIFACTS == [
        "ideas/candidate_ideas.md",
        "gaps/gap_map.md",
        "landscape/literature_landscape.md",
        "reports/minimal_topic_to_evidence_report.json",
    ]
    assert "retrieval/source_candidate_packet.json" in SCREENING_FORBIDDEN_INPUT_ARTIFACTS
    assert "retrieval/retrieval_warnings.json" in SCREENING_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_card_seeds.json" in SCREENING_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_cards.initial.json" in SCREENING_FORBIDDEN_INPUT_ARTIFACTS

    errors = validate_screening_input_artifacts(
        [
            "retrieval/source_candidate_packet.json",
            "raw_chunks/paper_001/chunk_001.json",
            "papers/paper_001.md",
            "ideas/candidate_ideas.md",
            "gaps/gap_map.md",
            "landscape/literature_landscape.md",
            "evidence/evidence_cards.initial.json",
        ]
    )

    assert "raw_retrieval_candidates_not_allowed_for_screening" in errors
    assert "raw_chunks_not_allowed_for_screening:raw_chunks/paper_001/chunk_001.json" in errors
    assert "raw_markdown_not_allowed_for_screening:papers/paper_001.md" in errors
    assert "unenriched_evidence_not_allowed_for_screening:evidence/evidence_cards.initial.json" in errors
    assert "missing_candidate_ideas_artifact" in errors
    assert "screening_requires_gap_and_evidence_basis" in errors


def test_screening_output_paths_and_markdown_sections_are_bounded() -> None:
    from modules.research_agent_controller.skills.screening_contract import (
        SCREENING_ALLOWED_MARKDOWN_SECTIONS,
        SCREENING_FORBIDDEN_MARKDOWN_SECTIONS,
        SCREENING_OUTPUT_ARTIFACTS,
    )

    assert SCREENING_OUTPUT_ARTIFACTS == [
        "screening/idea_screening_results.json",
        "screening/idea_screening_results.md",
        "screening/screening_diagnostics.json",
    ]
    assert "证据引用" in SCREENING_ALLOWED_MARKDOWN_SECTIONS
    assert "Experiment Plan" in SCREENING_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Experimental Protocol" in SCREENING_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Manuscript Draft" in SCREENING_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Final Claims" in SCREENING_FORBIDDEN_MARKDOWN_SECTIONS


def test_screening_schema_serializes_and_requires_source_gap_evidence_and_boundary_flags() -> None:
    from modules.research_agent_controller.skills.screening_contract import (
        IDEA_SCREENING_SCHEMA_VERSION,
        ScreenedIdeaRecord,
        IdeaScreeningArtifact,
    )

    screened = ScreenedIdeaRecord(
        idea_id="idea_1",
        source_idea_title="Compare oxygen vacancy stabilization routes",
        gap_ids=["gap_1"],
        evidence_ids=["ecard_001"],
        local_novelty_triage={
            "judgment": "partial_overlap_with_local_evidence",
            "confidence": "low",
            "closest_local_prior_evidence": [],
            "rationale": "Local evidence overlaps the candidate mechanism.",
            "limitations": ["No external novelty search."],
        },
        external_novelty_search={"status": "not_performed", "required": True, "rationale": "External search required."},
        feasibility_triage={
            "judgment": "partially_supported",
            "confidence": "low",
            "supporting_evidence": ["ecard_001"],
            "missing_requirements": ["synthesis evidence"],
            "constraints": [],
            "rationale": "Evidence supports mechanism context only.",
        },
        risk_triage={
            "judgment": "evidence_gap_risk",
            "confidence": "low",
            "risk_factors": ["limited evidence"],
            "follow_up": ["expert review"],
            "rationale": "Coverage is incomplete.",
        },
        overall_triage={
            "judgment": "advance_to_external_novelty_search",
            "rationale": "Local triage remains uncertain.",
            "required_follow_up": ["external novelty search", "feasibility review"],
        },
    )
    artifact = IdeaScreeningArtifact(
        task_id="task_1",
        topic="oxygen vacancy engineering for alkaline HER catalysts",
        screening_id="screening_task_1",
        input_artifacts=["ideas/candidate_ideas.json"],
        idea_set_id="candidate_ideas_task_1",
        gap_map_id="gap_map_task_1",
        landscape_id="landscape_task_1",
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        screened_ideas=[screened],
    )

    data = artifact.as_dict()

    assert data["schema_version"] == IDEA_SCREENING_SCHEMA_VERSION
    assert data["schema_version"] == "idea_screening_v2"
    assert data["screened_ideas"][0]["idea_id"] == "idea_1"
    assert data["screened_ideas"][0]["gap_ids"] == ["gap_1"]
    assert data["screened_ideas"][0]["evidence_ids"] == ["ecard_001"]
    assert data["screened_ideas"][0]["local_novelty_triage"]["judgment"] == "partial_overlap_with_local_evidence"
    assert data["screened_ideas"][0]["external_novelty_search"]["status"] == "not_performed"
    assert data["screened_ideas"][0]["not_an_experiment_plan"] is True
    assert data["screened_ideas"][0]["not_a_validated_claim"] is True

    with pytest.raises(ValueError, match="screened_idea_requires_source_idea_id"):
        ScreenedIdeaRecord(idea_id="", source_idea_title="Missing source", gap_ids=["gap_1"], evidence_ids=["ecard_001"])

    with pytest.raises(ValueError, match="screened_idea_requires_gap_ids"):
        ScreenedIdeaRecord(idea_id="idea_1", source_idea_title="Missing gap", gap_ids=[], evidence_ids=["ecard_001"])

    with pytest.raises(ValueError, match="screened_idea_requires_evidence_ids"):
        ScreenedIdeaRecord(idea_id="idea_1", source_idea_title="Missing evidence", gap_ids=["gap_1"], evidence_ids=[])

    with pytest.raises(ValueError, match="screening_must_not_be_experiment_plan"):
        ScreenedIdeaRecord(
            idea_id="idea_1",
            source_idea_title="Bad flag",
            gap_ids=["gap_1"],
            evidence_ids=["ecard_001"],
            not_an_experiment_plan=False,
        )

    with pytest.raises(ValueError, match="screening_must_not_be_validated_claim"):
        ScreenedIdeaRecord(
            idea_id="idea_1",
            source_idea_title="Bad flag",
            gap_ids=["gap_1"],
            evidence_ids=["ecard_001"],
            not_a_validated_claim=False,
        )


def test_screening_contract_boundary_has_no_runtime_controller_cli_or_database_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/screening_contract.py").read_text(encoding="utf-8")
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
