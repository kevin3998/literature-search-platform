"""P2-M14.1 manuscript-adjacent drafting skill contract and schema.

This module defines metadata and JSON-safe schema objects only. It does not
draft manuscript text, generate final claims, call external services, or
interpret experimental results.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

MANUSCRIPT_DRAFT_SCHEMA_VERSION = "manuscript_section_draft_v1"

MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS = [
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

MANUSCRIPT_DRAFT_OPTIONAL_INPUT_ARTIFACTS = [
    "claims/claim_ledger.md",
    "experiments/experiment_matrix.md",
    "screening/idea_screening_results.md",
    "ideas/candidate_ideas.md",
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]

MANUSCRIPT_DRAFT_FORBIDDEN_INPUT_ARTIFACTS = [
    "retrieval/source_candidate_packet.json",
    "retrieval/retrieval_warnings.json",
    "evidence/evidence_card_seeds.json",
    "evidence/evidence_cards.initial.json",
]

MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS = [
    "drafts/manuscript_section_draft.json",
    "drafts/manuscript_section_draft.md",
    "drafts/manuscript_section_diagnostics.json",
]

MANUSCRIPT_DRAFT_ALLOWED_MARKDOWN_SECTIONS = [
    "Draft Scope",
    "Source Artifact Base",
    "Draft Blocks",
    "Citation Map",
    "Unsupported Or Downgraded Claims",
    "Limitations",
    "Required Human Review",
    "Evidence References",
    "Background Context Draft",
    "Literature-Grounded Gap Framing Draft",
    "Hypothesis And Rationale Draft",
    "Limitations Draft",
    "Discussion Scaffold",
]

MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS = [
    "Final Abstract",
    "Final Results",
    "Final Discussion",
    "Final Conclusion",
    "Final Claims",
    "Submission-Ready Manuscript",
]

MANUSCRIPT_DRAFT_TYPES = [
    "manuscript_section",
    "evidence_grounded_report_section",
    "discussion_scaffold",
]

MANUSCRIPT_TARGET_SECTIONS = [
    "background",
    "literature_review",
    "research_gap",
    "hypothesis_and_rationale",
    "limitations",
    "discussion_scaffold",
]

DRAFT_BLOCK_TYPES = [
    "context",
    "evidence_summary",
    "gap_framing",
    "hypothesis_framing",
    "rationale",
    "limitation",
    "transition",
    "caution",
]

DRAFT_ALLOWED_DOWNSTREAM_USES = [
    "draft_context",
    "draft_gap_framing",
    "draft_hypothesis_framing",
    "draft_limitation",
    "not_for_final_submission",
]

DRAFT_SUPPORT_LEVELS = ["none", "low", "medium", "high"]

CITATION_STATUS_VALUES = [
    "evidence_grounded",
    "needs_manual_verification",
    "insufficient_support",
]

UNSUPPORTED_CLAIM_REASONS = [
    "no_claim_ledger_basis",
    "no_evidence_basis",
    "overclaim",
    "final_claim_attempt",
    "experimental_validation_not_available",
]

UNSUPPORTED_CLAIM_ACTIONS = [
    "remove",
    "downgrade",
    "rewrite_as_hypothesis",
    "move_to_limitations",
    "request_user_input",
]

MANUSCRIPT_DRAFT_VALIDATION_EXPECTATIONS = [
    "input_artifacts_exist",
    "claim_ledger_json_exists_and_parseable",
    "claim_ledger_schema_version_is_claim_ledger_v1",
    "experiment_matrix_json_exists_and_parseable",
    "experiment_matrix_schema_version_is_experiment_matrix_v1",
    "screening_results_json_exists_and_parseable",
    "screening_schema_version_is_idea_screening_v2",
    "candidate_ideas_json_exists_and_parseable",
    "candidate_ideas_schema_version_is_candidate_ideas_v1",
    "gap_map_json_exists_and_parseable",
    "gap_map_schema_version_is_gap_map_v1",
    "landscape_json_exists_and_parseable",
    "landscape_schema_version_is_landscape_v1",
    "no_retrieval_inputs",
    "claim_ledger_contains_claims",
    "every_draft_block_references_claim_ids_unless_transition_or_caution",
    "evidence_bearing_draft_blocks_reference_evidence_ids",
    "draft_blocks_do_not_introduce_unsupported_claims",
    "draft_blocks_do_not_upgrade_preliminary_claims_into_validated_results",
    "every_draft_block_requires_human_review",
    "every_draft_block_not_final_text",
    "every_draft_block_not_peer_reviewed",
    "candidate_screening_experiment_blocks_not_experimentally_validated",
    "markdown_contains_evidence_references",
    "markdown_excludes_final_sections",
    "artifact_does_not_assert_validation_performance_readiness_or_final_conclusions",
]


@dataclass
class DraftBlock:
    block_id: str
    block_type: str
    text: str
    claim_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    allowed_downstream_use: str = "not_for_final_submission"
    support_level: str = "none"
    requires_human_review: bool = True
    not_final_text: bool = True
    not_peer_reviewed: bool = True
    not_experimentally_validated: bool = True
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.block_id:
            raise ValueError("draft_block_requires_block_id")
        if not self.block_type:
            raise ValueError("draft_block_requires_block_type")
        if self.block_type not in DRAFT_BLOCK_TYPES:
            raise ValueError(f"invalid_draft_block_type:{self.block_type}")
        if not self.text:
            raise ValueError("draft_block_requires_text")
        if self.block_type not in {"transition", "caution"} and not self.claim_ids:
            raise ValueError("draft_block_requires_claim_ids")
        if self.allowed_downstream_use not in DRAFT_ALLOWED_DOWNSTREAM_USES:
            raise ValueError(f"invalid_draft_allowed_downstream_use:{self.allowed_downstream_use}")
        if self.support_level not in DRAFT_SUPPORT_LEVELS:
            raise ValueError(f"invalid_draft_support_level:{self.support_level}")
        if self.requires_human_review is not True:
            raise ValueError("draft_block_requires_human_review")
        if self.not_final_text is not True:
            raise ValueError("draft_block_must_not_be_final_text")
        if self.not_peer_reviewed is not True:
            raise ValueError("draft_block_must_not_be_peer_reviewed")
        if self.not_experimentally_validated is not True:
            raise ValueError("draft_block_must_not_be_experimentally_validated")
        self.claim_ids = _dedupe(self.claim_ids)
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.warnings = _dedupe(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftBlock":
        return cls(
            block_id=data.get("block_id", ""),
            block_type=data.get("block_type", ""),
            text=data.get("text", ""),
            claim_ids=list(data.get("claim_ids") or []),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            allowed_downstream_use=data.get("allowed_downstream_use", "not_for_final_submission"),
            support_level=data.get("support_level", "none"),
            requires_human_review=bool(data.get("requires_human_review", True)),
            not_final_text=bool(data.get("not_final_text", True)),
            not_peer_reviewed=bool(data.get("not_peer_reviewed", True)),
            not_experimentally_validated=bool(data.get("not_experimentally_validated", True)),
            warnings=list(data.get("warnings") or []),
        )


@dataclass
class CitationMapRecord:
    citation_id: str
    claim_id: str
    evidence_ids: list[str]
    source_paper_ids: list[str]
    source_artifacts: list[str]
    citation_status: str = "needs_manual_verification"

    def __post_init__(self) -> None:
        if not self.citation_id:
            raise ValueError("citation_map_requires_citation_id")
        if not self.claim_id:
            raise ValueError("citation_map_requires_claim_id")
        if not self.evidence_ids:
            raise ValueError("citation_map_requires_evidence_ids")
        if not self.source_paper_ids:
            raise ValueError("citation_map_requires_source_paper_ids")
        if not self.source_artifacts:
            raise ValueError("citation_map_requires_source_artifacts")
        if self.citation_status not in CITATION_STATUS_VALUES:
            raise ValueError(f"invalid_citation_status:{self.citation_status}")
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.source_artifacts = _dedupe(self.source_artifacts)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CitationMapRecord":
        return cls(
            citation_id=data.get("citation_id", ""),
            claim_id=data.get("claim_id", ""),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            source_artifacts=list(data.get("source_artifacts") or []),
            citation_status=data.get("citation_status", "needs_manual_verification"),
        )


@dataclass
class UnsupportedClaimRecord:
    unsupported_claim_id: str
    text: str
    reason: str
    source_artifacts: list[str]
    recommended_action: str

    def __post_init__(self) -> None:
        if not self.unsupported_claim_id:
            raise ValueError("unsupported_claim_requires_id")
        if not self.text:
            raise ValueError("unsupported_claim_requires_text")
        if self.reason not in UNSUPPORTED_CLAIM_REASONS:
            raise ValueError(f"unsupported_claim_invalid_reason:{self.reason}")
        if not self.source_artifacts:
            raise ValueError("unsupported_claim_requires_source_artifacts")
        if self.recommended_action not in UNSUPPORTED_CLAIM_ACTIONS:
            raise ValueError(f"unsupported_claim_invalid_action:{self.recommended_action}")
        self.source_artifacts = _dedupe(self.source_artifacts)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UnsupportedClaimRecord":
        return cls(
            unsupported_claim_id=data.get("unsupported_claim_id", ""),
            text=data.get("text", ""),
            reason=data.get("reason", ""),
            source_artifacts=list(data.get("source_artifacts") or []),
            recommended_action=data.get("recommended_action", ""),
        )


@dataclass
class ManuscriptSectionDraftArtifact:
    task_id: str
    topic: str
    draft_id: str
    draft_type: str
    target_section: str
    input_artifacts: list[str]
    claim_ledger_id: str
    experiment_matrix_id: str
    screening_id: str
    idea_set_id: str
    gap_map_id: str
    landscape_id: str
    evidence_ids: list[str]
    source_paper_ids: list[str]
    draft_blocks: list[DraftBlock | dict[str, Any]]
    citation_map: list[CitationMapRecord | dict[str, Any]] = field(default_factory=list)
    unsupported_claims: list[UnsupportedClaimRecord | dict[str, Any]] = field(default_factory=list)
    draft_policy: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    schema_version: str = MANUSCRIPT_DRAFT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MANUSCRIPT_DRAFT_SCHEMA_VERSION:
            raise ValueError(f"invalid_manuscript_draft_schema_version:{self.schema_version}")
        if not self.draft_id:
            raise ValueError("manuscript_draft_requires_id")
        if self.draft_type not in MANUSCRIPT_DRAFT_TYPES:
            raise ValueError(f"invalid_manuscript_draft_type:{self.draft_type}")
        if self.target_section not in MANUSCRIPT_TARGET_SECTIONS:
            raise ValueError(f"invalid_manuscript_target_section:{self.target_section}")
        if not self.claim_ledger_id:
            raise ValueError("manuscript_draft_requires_claim_ledger_id")
        if not self.evidence_ids:
            raise ValueError("manuscript_draft_requires_evidence_ids")
        self.input_artifacts = _dedupe(self.input_artifacts)
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.draft_blocks = [item if isinstance(item, DraftBlock) else DraftBlock.from_dict(item) for item in self.draft_blocks]
        if not self.draft_blocks:
            raise ValueError("manuscript_draft_requires_draft_blocks")
        self.citation_map = [
            item if isinstance(item, CitationMapRecord) else CitationMapRecord.from_dict(item)
            for item in self.citation_map
        ]
        self.unsupported_claims = [
            item if isinstance(item, UnsupportedClaimRecord) else UnsupportedClaimRecord.from_dict(item)
            for item in self.unsupported_claims
        ]
        self.limitations = _dedupe(self.limitations)
        self.warnings = _dedupe(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["draft_blocks"] = [block.as_dict() for block in self.draft_blocks]
        data["citation_map"] = [record.as_dict() for record in self.citation_map]
        data["unsupported_claims"] = [record.as_dict() for record in self.unsupported_claims]
        return data


def validate_manuscript_drafting_input_artifacts(input_artifacts: list[str]) -> list[str]:
    errors: list[str] = []
    artifact_set = set(input_artifacts or [])
    for artifact_path in input_artifacts:
        if artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_manuscript_drafting")
        elif artifact_path.startswith(("raw_chunks/", "chunks/")):
            errors.append(f"raw_chunks_not_allowed_for_manuscript_drafting:{artifact_path}")
        elif artifact_path in {"evidence/evidence_card_seeds.json", "evidence/evidence_cards.initial.json"}:
            errors.append(f"unenriched_evidence_not_allowed_for_manuscript_drafting:{artifact_path}")
        elif artifact_path.endswith(".md") and artifact_path not in MANUSCRIPT_DRAFT_OPTIONAL_INPUT_ARTIFACTS:
            errors.append(f"raw_markdown_not_allowed_for_manuscript_drafting:{artifact_path}")

    if "claims/claim_ledger.json" not in artifact_set:
        errors.append("missing_claim_ledger_artifact")
        errors.append("manuscript_drafting_requires_claim_ledger")

    basis_requirements = {
        "claims/claim_ledger.json",
        "experiments/experiment_matrix.json",
        "screening/idea_screening_results.json",
        "ideas/candidate_ideas.json",
        "gaps/gap_map.json",
        "landscape/literature_landscape.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    }
    if not basis_requirements.issubset(artifact_set):
        errors.append("manuscript_drafting_requires_traceable_claims")

    missing = [
        path
        for path in MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS
        if path not in artifact_set and path != "claims/claim_ledger.json"
    ]
    errors.extend(f"missing_manuscript_drafting_input:{path}" for path in missing)
    return _dedupe(errors)


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "CITATION_STATUS_VALUES",
    "DRAFT_ALLOWED_DOWNSTREAM_USES",
    "DRAFT_BLOCK_TYPES",
    "DRAFT_SUPPORT_LEVELS",
    "MANUSCRIPT_DRAFT_ALLOWED_MARKDOWN_SECTIONS",
    "MANUSCRIPT_DRAFT_FORBIDDEN_INPUT_ARTIFACTS",
    "MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS",
    "MANUSCRIPT_DRAFT_OPTIONAL_INPUT_ARTIFACTS",
    "MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS",
    "MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS",
    "MANUSCRIPT_DRAFT_SCHEMA_VERSION",
    "MANUSCRIPT_DRAFT_TYPES",
    "MANUSCRIPT_DRAFT_VALIDATION_EXPECTATIONS",
    "MANUSCRIPT_TARGET_SECTIONS",
    "UNSUPPORTED_CLAIM_ACTIONS",
    "UNSUPPORTED_CLAIM_REASONS",
    "CitationMapRecord",
    "DraftBlock",
    "ManuscriptSectionDraftArtifact",
    "UnsupportedClaimRecord",
    "validate_manuscript_drafting_input_artifacts",
]
