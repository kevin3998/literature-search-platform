import pytest

from modules.research_agent_controller import (
    SkillDatabaseAccess,
    SkillStatus,
    build_default_skill_registry,
)
from modules.research_agent_controller.skills.evidence_tools import EVIDENCE_SKILL_WRAPPERS


def test_manuscript_drafting_registry_contract_exists_and_is_available_after_p2_m14_2() -> None:
    from modules.research_agent_controller.skills.manuscript_contract import (
        MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
        MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
    )

    registry = build_default_skill_registry()
    contract = registry.get_skill("draft_manuscript_section")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.database_access == SkillDatabaseAccess.NONE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert contract.writes_artifacts is True
    assert contract.required_artifacts == MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS
    assert contract.produced_artifacts == MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS
    assert "raw_retrieval_candidates_not_allowed_for_manuscript_drafting" in contract.validation_rules
    assert "missing_claim_ledger_artifact" in contract.failure_modes
    assert "manuscript_drafting_requires_traceable_claims" in contract.failure_modes
    assert "draft_manuscript_section" in EVIDENCE_SKILL_WRAPPERS
    assert registry.get_skill("draft_evidence_grounded_report").status == SkillStatus.STUB
    assert "draft_evidence_grounded_report" not in EVIDENCE_SKILL_WRAPPERS


def test_manuscript_contract_declares_legal_optional_and_forbidden_inputs() -> None:
    from modules.research_agent_controller.skills.manuscript_contract import (
        MANUSCRIPT_DRAFT_FORBIDDEN_INPUT_ARTIFACTS,
        MANUSCRIPT_DRAFT_OPTIONAL_INPUT_ARTIFACTS,
        MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
        validate_manuscript_drafting_input_artifacts,
    )

    assert MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS == [
        "claims/claim_ledger.json",
        "claims/claim_ledger_diagnostics.json",
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
    assert MANUSCRIPT_DRAFT_OPTIONAL_INPUT_ARTIFACTS == [
        "claims/claim_ledger.md",
        "experiments/experiment_matrix.md",
        "screening/idea_screening_results.md",
        "ideas/candidate_ideas.md",
        "gaps/gap_map.md",
        "landscape/literature_landscape.md",
        "reports/minimal_topic_to_evidence_report.json",
    ]
    assert "retrieval/source_candidate_packet.json" in MANUSCRIPT_DRAFT_FORBIDDEN_INPUT_ARTIFACTS
    assert "retrieval/retrieval_warnings.json" in MANUSCRIPT_DRAFT_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_card_seeds.json" in MANUSCRIPT_DRAFT_FORBIDDEN_INPUT_ARTIFACTS
    assert "evidence/evidence_cards.initial.json" in MANUSCRIPT_DRAFT_FORBIDDEN_INPUT_ARTIFACTS

    errors = validate_manuscript_drafting_input_artifacts(
        [
            "retrieval/source_candidate_packet.json",
            "raw_chunks/paper_001/chunk_001.json",
            "papers/paper_001.md",
            "claims/claim_ledger.md",
            "evidence/evidence_cards.initial.json",
        ]
    )

    assert "raw_retrieval_candidates_not_allowed_for_manuscript_drafting" in errors
    assert "raw_chunks_not_allowed_for_manuscript_drafting:raw_chunks/paper_001/chunk_001.json" in errors
    assert "raw_markdown_not_allowed_for_manuscript_drafting:papers/paper_001.md" in errors
    assert "unenriched_evidence_not_allowed_for_manuscript_drafting:evidence/evidence_cards.initial.json" in errors
    assert "missing_claim_ledger_artifact" in errors
    assert "manuscript_drafting_requires_claim_ledger" in errors
    assert "manuscript_drafting_requires_traceable_claims" in errors


def test_manuscript_output_paths_and_markdown_sections_are_bounded() -> None:
    from modules.research_agent_controller.skills.manuscript_contract import (
        MANUSCRIPT_DRAFT_ALLOWED_MARKDOWN_SECTIONS,
        MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS,
        MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
    )

    assert MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS == [
        "drafts/manuscript_section_draft.json",
        "drafts/manuscript_section_draft.md",
        "drafts/manuscript_section_diagnostics.json",
    ]
    assert "Evidence References" in MANUSCRIPT_DRAFT_ALLOWED_MARKDOWN_SECTIONS
    assert "Background Context Draft" in MANUSCRIPT_DRAFT_ALLOWED_MARKDOWN_SECTIONS
    assert "Final Abstract" in MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Final Results" in MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Final Discussion" in MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Final Conclusion" in MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Final Claims" in MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS
    assert "Submission-Ready Manuscript" in MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS


def test_manuscript_schema_serializes_and_requires_bounded_draft_blocks() -> None:
    from modules.research_agent_controller.skills.manuscript_contract import (
        MANUSCRIPT_DRAFT_SCHEMA_VERSION,
        CitationMapRecord,
        DraftBlock,
        ManuscriptSectionDraftArtifact,
        UnsupportedClaimRecord,
    )

    block = DraftBlock(
        block_id="block_001",
        block_type="hypothesis_framing",
        text="This hypothesis framing remains preliminary and requires validation.",
        claim_ids=["claim_001"],
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        allowed_downstream_use="draft_hypothesis_framing",
        support_level="low",
        not_experimentally_validated=True,
    )
    citation = CitationMapRecord(
        citation_id="cite_001",
        claim_id="claim_001",
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        source_artifacts=["claims/claim_ledger.json"],
        citation_status="evidence_grounded",
    )
    unsupported = UnsupportedClaimRecord(
        unsupported_claim_id="unsupported_001",
        text="This would be too strong for current evidence.",
        reason="overclaim",
        source_artifacts=["claims/claim_ledger.json"],
        recommended_action="downgrade",
    )
    artifact = ManuscriptSectionDraftArtifact(
        task_id="task_1",
        topic="oxygen vacancy engineering for alkaline HER catalysts",
        draft_id="draft_task_1",
        draft_type="manuscript_section",
        target_section="hypothesis_and_rationale",
        input_artifacts=["claims/claim_ledger.json"],
        claim_ledger_id="claim_ledger_task_1",
        experiment_matrix_id="experiment_matrix_task_1",
        screening_id="idea_screening_task_1",
        idea_set_id="candidate_ideas_task_1",
        gap_map_id="gap_map_task_1",
        landscape_id="landscape_task_1",
        evidence_ids=["ecard_001"],
        source_paper_ids=["paper_001"],
        draft_blocks=[block],
        citation_map=[citation],
        unsupported_claims=[unsupported],
    )

    data = artifact.as_dict()

    assert data["schema_version"] == MANUSCRIPT_DRAFT_SCHEMA_VERSION
    assert data["draft_blocks"][0]["block_id"] == "block_001"
    assert data["draft_blocks"][0]["block_type"] == "hypothesis_framing"
    assert data["draft_blocks"][0]["claim_ids"] == ["claim_001"]
    assert data["draft_blocks"][0]["evidence_ids"] == ["ecard_001"]
    assert data["draft_blocks"][0]["requires_human_review"] is True
    assert data["draft_blocks"][0]["not_final_text"] is True
    assert data["draft_blocks"][0]["not_peer_reviewed"] is True
    assert data["draft_blocks"][0]["not_experimentally_validated"] is True
    assert data["citation_map"][0]["claim_id"] == "claim_001"
    assert data["citation_map"][0]["evidence_ids"] == ["ecard_001"]
    assert data["unsupported_claims"][0]["reason"] == "overclaim"

    with pytest.raises(ValueError, match="draft_block_requires_block_id"):
        DraftBlock(
            block_id="",
            block_type="context",
            text="Missing id.",
            claim_ids=["claim_001"],
        )

    with pytest.raises(ValueError, match="draft_block_requires_claim_ids"):
        DraftBlock(
            block_id="block_missing_claims",
            block_type="evidence_summary",
            text="Evidence summary without claims.",
        )

    with pytest.raises(ValueError, match="draft_block_requires_human_review"):
        DraftBlock(
            block_id="block_review",
            block_type="context",
            text="Bad review flag.",
            claim_ids=["claim_001"],
            requires_human_review=False,
        )

    with pytest.raises(ValueError, match="unsupported_claim_invalid_reason"):
        UnsupportedClaimRecord(
            unsupported_claim_id="unsupported_bad",
            text="Bad reason.",
            reason="publish_anyway",
            source_artifacts=["claims/claim_ledger.json"],
            recommended_action="remove",
        )


def test_p2_m14_contract_and_wrapper_do_not_implement_controller_cli_or_database_behavior() -> None:
    source_paths = [
        "backend/modules/research_agent_controller/skills/manuscript_contract.py",
        "backend/modules/research_agent_controller/skills/manuscript_tools.py",
        "backend/modules/research_agent_controller/skill_registry.py",
    ]
    sources = "\n".join(open(path, encoding="utf-8").read() for path in source_paths)

    forbidden_tokens = [
        "RealClaudeCodeCliBackend",
        "ClaudeCodeBackedMinimalController",
        "PlatformNativeFallbackController",
        "subprocess",
        "sqlite",
        "LiteratureResearchService",
        "core.memory_db",
        "OpenAI",
        "DeepSeek",
        "llm_client",
    ]
    for token in forbidden_tokens:
        assert token not in sources
    assert "draft_manuscript_section" in EVIDENCE_SKILL_WRAPPERS
    assert "draft_evidence_grounded_report" not in EVIDENCE_SKILL_WRAPPERS
