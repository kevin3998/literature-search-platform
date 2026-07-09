"""P2-M13.1 claim ledger skill contract and artifact schema.

This module defines metadata and JSON-safe schema objects only. It does not
build claim ledgers, draft manuscripts, generate final claims, or interpret
experimental results.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

CLAIM_LEDGER_SCHEMA_VERSION = "claim_ledger_v1"

CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS = [
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

CLAIM_LEDGER_OPTIONAL_INPUT_ARTIFACTS = [
    "experiments/experiment_matrix.md",
    "screening/idea_screening_results.md",
    "ideas/candidate_ideas.md",
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]

CLAIM_LEDGER_FORBIDDEN_INPUT_ARTIFACTS = [
    "retrieval/source_candidate_packet.json",
    "retrieval/retrieval_warnings.json",
    "evidence/evidence_card_seeds.json",
    "evidence/evidence_cards.initial.json",
]

CLAIM_LEDGER_OUTPUT_ARTIFACTS = [
    "claims/claim_ledger.json",
    "claims/claim_ledger.md",
    "claims/claim_ledger_diagnostics.json",
]

CLAIM_LEDGER_ALLOWED_MARKDOWN_SECTIONS = [
    "Scope",
    "Upstream Evidence And Artifact Base",
    "Claim Records",
    "Claim Status Summary",
    "Claims Not Suitable For Manuscript Use",
    "Limitations",
    "Required Human Review",
    "Evidence References",
]

CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS = [
    "Manuscript Draft",
    "Abstract",
    "Results And Discussion",
    "Conclusion",
    "Final Claims",
]

CLAIM_TYPE_VALUES = [
    "literature_observation",
    "evidence_summary",
    "gap_statement",
    "candidate_hypothesis",
    "screening_assessment",
    "experiment_matrix_rationale",
    "limitation_statement",
]

CLAIM_STATUS_VALUES = [
    "evidence_supported_literature_claim",
    "evidence_grounded_candidate",
    "hypothesis_requires_validation",
    "screening_preliminary",
    "matrix_planning_scaffold",
    "insufficient_support",
    "rejected_overclaim",
]

CLAIM_SUPPORT_LEVELS = ["none", "low", "medium", "high"]

CLAIM_ALLOWED_DOWNSTREAM_USES = [
    "background_context",
    "gap_framing",
    "hypothesis_framing",
    "planning_rationale",
    "limitation_only",
    "not_for_manuscript_claim",
]

CLAIM_LEDGER_VALIDATION_EXPECTATIONS = [
    "input_artifacts_exist",
    "experiment_matrix_json_exists_and_parseable",
    "experiment_matrix_schema_version_is_experiment_matrix_v1",
    "screening_results_json_exists_and_parseable",
    "screening_schema_version_is_idea_screening_v2",
    "candidate_ideas_json_exists_and_parseable",
    "candidate_ideas_schema_version_is_candidate_ideas_v1",
    "no_retrieval_inputs",
    "experiment_candidates_preserve_source_idea_gap_and_evidence_basis",
    "screening_results_do_not_contain_final_claims",
    "output_json_parseable",
    "schema_version_is_claim_ledger_v1",
    "every_claim_has_claim_id_claim_type_and_claim_status",
    "every_claim_references_source_artifacts",
    "every_evidence_bearing_claim_references_evidence_ids",
    "not_a_final_claim_is_true",
    "not_experimentally_validated_is_true",
    "requires_human_review_is_true",
    "markdown_contains_evidence_references",
    "markdown_excludes_manuscript_abstract_results_conclusion_final_claim_sections",
    "claim_ledger_does_not_assert_validation_performance_or_final_conclusions",
]


@dataclass
class UpstreamDependencies:
    experiment_matrix_ids: list[str] = field(default_factory=list)
    screening_ids: list[str] = field(default_factory=list)
    idea_set_ids: list[str] = field(default_factory=list)
    landscape_cluster_ids: list[str] = field(default_factory=list)
    diagnostic_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.experiment_matrix_ids = _dedupe(self.experiment_matrix_ids)
        self.screening_ids = _dedupe(self.screening_ids)
        self.idea_set_ids = _dedupe(self.idea_set_ids)
        self.landscape_cluster_ids = _dedupe(self.landscape_cluster_ids)
        self.diagnostic_refs = _dedupe(self.diagnostic_refs)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpstreamDependencies":
        return cls(
            experiment_matrix_ids=list(data.get("experiment_matrix_ids") or []),
            screening_ids=list(data.get("screening_ids") or []),
            idea_set_ids=list(data.get("idea_set_ids") or []),
            landscape_cluster_ids=list(data.get("landscape_cluster_ids") or []),
            diagnostic_refs=list(data.get("diagnostic_refs") or []),
        )


@dataclass
class ClaimRecord:
    claim_id: str
    claim_text: str
    claim_type: str
    claim_status: str
    source_artifacts: list[str]
    source_idea_ids: list[str] = field(default_factory=list)
    source_experiment_ids: list[str] = field(default_factory=list)
    gap_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    upstream_dependencies: UpstreamDependencies | dict[str, Any] = field(default_factory=UpstreamDependencies)
    support_level: str = "none"
    allowed_downstream_use: str = "not_for_manuscript_claim"
    prohibited_uses: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    not_a_final_claim: bool = True
    not_experimentally_validated: bool = True
    requires_human_review: bool = True
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.claim_id:
            raise ValueError("claim_record_requires_claim_id")
        if not self.claim_type:
            raise ValueError("claim_record_requires_claim_type")
        if self.claim_type not in CLAIM_TYPE_VALUES:
            raise ValueError(f"invalid_claim_type:{self.claim_type}")
        if not self.claim_status:
            raise ValueError("claim_record_requires_claim_status")
        if self.claim_status not in CLAIM_STATUS_VALUES:
            raise ValueError(f"invalid_claim_status:{self.claim_status}")
        if not self.source_artifacts:
            raise ValueError("claim_record_requires_source_artifacts")
        if self.claim_status not in {"insufficient_support", "rejected_overclaim"} and not self.evidence_ids:
            raise ValueError("claim_record_requires_evidence_ids")
        if self.support_level not in CLAIM_SUPPORT_LEVELS:
            raise ValueError(f"invalid_claim_support_level:{self.support_level}")
        if self.allowed_downstream_use not in CLAIM_ALLOWED_DOWNSTREAM_USES:
            raise ValueError(f"invalid_allowed_downstream_use:{self.allowed_downstream_use}")
        if self.not_a_final_claim is not True:
            raise ValueError("claim_record_must_not_be_final_claim")
        if self.not_experimentally_validated is not True:
            raise ValueError("claim_record_must_not_be_experimentally_validated")
        if self.requires_human_review is not True:
            raise ValueError("claim_record_requires_human_review")
        self.source_artifacts = _dedupe(self.source_artifacts)
        self.source_idea_ids = _dedupe(self.source_idea_ids)
        self.source_experiment_ids = _dedupe(self.source_experiment_ids)
        self.gap_ids = _dedupe(self.gap_ids)
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.upstream_dependencies = (
            self.upstream_dependencies
            if isinstance(self.upstream_dependencies, UpstreamDependencies)
            else UpstreamDependencies.from_dict(self.upstream_dependencies)
        )
        self.prohibited_uses = _dedupe(self.prohibited_uses)
        self.limitations = _dedupe(self.limitations)
        self.warnings = _dedupe(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["upstream_dependencies"] = self.upstream_dependencies.as_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaimRecord":
        return cls(
            claim_id=data.get("claim_id", ""),
            claim_text=data.get("claim_text", ""),
            claim_type=data.get("claim_type", ""),
            claim_status=data.get("claim_status", ""),
            source_artifacts=list(data.get("source_artifacts") or []),
            source_idea_ids=list(data.get("source_idea_ids") or []),
            source_experiment_ids=list(data.get("source_experiment_ids") or []),
            gap_ids=list(data.get("gap_ids") or []),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            supporting_evidence=list(data.get("supporting_evidence") or []),
            upstream_dependencies=dict(data.get("upstream_dependencies") or {}),
            support_level=data.get("support_level", "none"),
            allowed_downstream_use=data.get("allowed_downstream_use", "not_for_manuscript_claim"),
            prohibited_uses=list(data.get("prohibited_uses") or []),
            limitations=list(data.get("limitations") or []),
            not_a_final_claim=bool(data.get("not_a_final_claim", True)),
            not_experimentally_validated=bool(data.get("not_experimentally_validated", True)),
            requires_human_review=bool(data.get("requires_human_review", True)),
            warnings=list(data.get("warnings") or []),
        )


@dataclass
class ClaimLedgerArtifact:
    task_id: str
    topic: str
    claim_ledger_id: str
    input_artifacts: list[str]
    experiment_matrix_id: str
    screening_id: str
    idea_set_id: str
    gap_map_id: str
    landscape_id: str
    evidence_ids: list[str]
    source_paper_ids: list[str]
    claims: list[ClaimRecord | dict[str, Any]]
    ledger_scope: dict[str, Any] = field(default_factory=dict)
    claim_policy: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    schema_version: str = CLAIM_LEDGER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CLAIM_LEDGER_SCHEMA_VERSION:
            raise ValueError(f"invalid_claim_ledger_schema_version:{self.schema_version}")
        if not self.claim_ledger_id:
            raise ValueError("claim_ledger_requires_id")
        if not self.experiment_matrix_id:
            raise ValueError("claim_ledger_requires_experiment_matrix_id")
        if not self.screening_id:
            raise ValueError("claim_ledger_requires_screening_id")
        if not self.idea_set_id:
            raise ValueError("claim_ledger_requires_idea_set_id")
        if not self.gap_map_id:
            raise ValueError("claim_ledger_requires_gap_map_id")
        if not self.landscape_id:
            raise ValueError("claim_ledger_requires_landscape_id")
        self.input_artifacts = _dedupe(self.input_artifacts)
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.claims = [item if isinstance(item, ClaimRecord) else ClaimRecord.from_dict(item) for item in self.claims]
        self.limitations = _dedupe(self.limitations)
        self.warnings = _dedupe(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["claims"] = [claim.as_dict() for claim in self.claims]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClaimLedgerArtifact":
        return cls(
            task_id=data.get("task_id", ""),
            topic=data.get("topic", ""),
            claim_ledger_id=data.get("claim_ledger_id", ""),
            input_artifacts=list(data.get("input_artifacts") or []),
            experiment_matrix_id=data.get("experiment_matrix_id", ""),
            screening_id=data.get("screening_id", ""),
            idea_set_id=data.get("idea_set_id", ""),
            gap_map_id=data.get("gap_map_id", ""),
            landscape_id=data.get("landscape_id", ""),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            claims=list(data.get("claims") or []),
            ledger_scope=dict(data.get("ledger_scope") or {}),
            claim_policy=dict(data.get("claim_policy") or {}),
            limitations=list(data.get("limitations") or []),
            warnings=list(data.get("warnings") or []),
            created_at=float(data.get("created_at", time.time())),
            schema_version=data.get("schema_version", CLAIM_LEDGER_SCHEMA_VERSION),
        )


def validate_claim_ledger_input_artifacts(input_artifacts: list[str]) -> list[str]:
    errors: list[str] = []
    artifact_set = set(input_artifacts or [])
    for artifact_path in input_artifacts:
        if artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_claim_ledger")
        elif artifact_path.startswith(("raw_chunks/", "chunks/")):
            errors.append(f"raw_chunks_not_allowed_for_claim_ledger:{artifact_path}")
        elif artifact_path in {"evidence/evidence_card_seeds.json", "evidence/evidence_cards.initial.json"}:
            errors.append(f"unenriched_evidence_not_allowed_for_claim_ledger:{artifact_path}")
        elif artifact_path.endswith(".md") and artifact_path not in CLAIM_LEDGER_OPTIONAL_INPUT_ARTIFACTS:
            errors.append(f"raw_markdown_not_allowed_for_claim_ledger:{artifact_path}")

    if "experiments/experiment_matrix.json" not in artifact_set:
        errors.append("missing_experiment_matrix_artifact")

    basis_requirements = {
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
        errors.append("claim_ledger_requires_traceable_evidence_basis")

    missing = [
        path
        for path in CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS
        if path not in artifact_set and path != "experiments/experiment_matrix.json"
    ]
    errors.extend(f"missing_claim_ledger_input:{path}" for path in missing)
    return _dedupe(errors)


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "CLAIM_ALLOWED_DOWNSTREAM_USES",
    "CLAIM_LEDGER_ALLOWED_MARKDOWN_SECTIONS",
    "CLAIM_LEDGER_FORBIDDEN_INPUT_ARTIFACTS",
    "CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS",
    "CLAIM_LEDGER_OPTIONAL_INPUT_ARTIFACTS",
    "CLAIM_LEDGER_OUTPUT_ARTIFACTS",
    "CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS",
    "CLAIM_LEDGER_SCHEMA_VERSION",
    "CLAIM_LEDGER_VALIDATION_EXPECTATIONS",
    "CLAIM_STATUS_VALUES",
    "CLAIM_SUPPORT_LEVELS",
    "CLAIM_TYPE_VALUES",
    "ClaimLedgerArtifact",
    "ClaimRecord",
    "UpstreamDependencies",
    "validate_claim_ledger_input_artifacts",
]
