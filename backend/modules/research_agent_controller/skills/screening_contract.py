"""P2-M11.1 screening skill contract and artifact schema.

This module defines metadata and JSON-safe schema objects only. It does not
screen ideas, execute platform runtime code, call LLMs, or invoke external
services.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

IDEA_SCREENING_SCHEMA_VERSION = "idea_screening_v2"

SCREENING_REQUIRED_INPUT_ARTIFACTS = [
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

SCREENING_OPTIONAL_INPUT_ARTIFACTS = [
    "ideas/candidate_ideas.md",
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]

SCREENING_FORBIDDEN_INPUT_ARTIFACTS = [
    "retrieval/source_candidate_packet.json",
    "retrieval/retrieval_warnings.json",
    "evidence/evidence_card_seeds.json",
    "evidence/evidence_cards.initial.json",
]

SCREENING_OUTPUT_ARTIFACTS = [
    "screening/idea_screening_results.json",
    "screening/idea_screening_results.md",
    "screening/screening_diagnostics.json",
]

SCREENING_ALLOWED_MARKDOWN_SECTIONS = [
    "范围",
    "边界",
    "候选想法筛选",
    "局部新颖性筛选",
    "可行性筛选",
    "风险筛选",
    "必要后续检查",
    "局限",
    "证据引用",
]

SCREENING_FORBIDDEN_MARKDOWN_SECTIONS = [
    "Experiment Plan",
    "Experimental Protocol",
    "Manuscript Draft",
    "Final Claims",
]

NOVELTY_STATUS_VALUES = [
    "not_screened",
    "insufficient_evidence",
    "potentially_incremental",
    "potentially_distinct",
    "requires_external_search",
]

FEASIBILITY_STATUS_VALUES = [
    "not_screened",
    "insufficient_evidence",
    "low",
    "medium",
    "high",
    "requires_expert_review",
]

RISK_STATUS_VALUES = [
    "not_screened",
    "low",
    "medium",
    "high",
    "requires_risk_review",
]

SCREENING_CONFIDENCE_VALUES = ["low", "medium", "high"]

LOCAL_NOVELTY_TRIAGE_VALUES = [
    "likely_distinct_from_local_evidence",
    "partial_overlap_with_local_evidence",
    "likely_overlapping_local_prior",
    "insufficient_local_evidence",
]

EXTERNAL_NOVELTY_SEARCH_STATUS_VALUES = ["not_performed"]

FEASIBILITY_TRIAGE_VALUES = [
    "locally_supported",
    "partially_supported",
    "weakly_supported",
    "under_specified",
    "insufficient_evidence",
]

RISK_TRIAGE_VALUES = [
    "low_information_risk",
    "evidence_gap_risk",
    "mechanism_risk",
    "synthesis_risk",
    "characterization_risk",
    "scope_risk",
    "mixed_risk",
]

OVERALL_TRIAGE_VALUES = [
    "advance_to_external_novelty_search",
    "needs_more_local_evidence",
    "revise_candidate_scope",
    "deprioritize_for_now",
]

OVERALL_SCREENING_STATUS_VALUES = [
    "not_recommended_yet",
    "needs_external_novelty_check",
    "needs_feasibility_review",
    "ready_for_experiment_planning_candidate",
]

SCREENING_VALIDATION_EXPECTATIONS = [
    "input_artifacts_exist",
    "candidate_ideas_json_exists_and_parseable",
    "candidate_ideas_schema_version_is_candidate_ideas_v1",
    "no_retrieval_inputs",
    "every_candidate_idea_has_gap_basis",
    "every_candidate_idea_has_evidence_basis",
    "every_candidate_idea_not_yet_screened_before_screening",
    "gap_map_json_exists_and_parseable",
    "landscape_json_exists_and_parseable",
    "output_json_parseable",
    "schema_version_is_idea_screening_v2",
    "every_screened_idea_references_source_idea_id",
    "every_screened_idea_preserves_gap_ids_and_evidence_ids",
    "local_novelty_triage_has_rationale_and_limitations",
    "external_novelty_search_status_is_not_performed",
    "feasibility_triage_has_rationale",
    "risk_triage_has_rationale_and_risk_factors",
    "overall_triage_has_required_follow_up",
    "llm_output_references_only_known_local_artifact_ids",
    "not_an_experiment_plan_is_true",
    "not_a_validated_claim_is_true",
    "markdown_contains_evidence_references",
    "markdown_excludes_experiment_protocol_manuscript_final_claim_sections",
    "screening_does_not_claim_final_novelty_or_feasibility",
]


@dataclass
class ScreeningAssessment:
    status: str = "not_screened"
    basis: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: str = "low"
    constraints: list[str] = field(default_factory=list)
    required_resources: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        allowed = set(NOVELTY_STATUS_VALUES + FEASIBILITY_STATUS_VALUES)
        if self.status not in allowed:
            raise ValueError(f"invalid_screening_assessment_status:{self.status}")
        if self.confidence not in SCREENING_CONFIDENCE_VALUES:
            raise ValueError(f"invalid_screening_confidence:{self.confidence}")
        self.basis = _dedupe(self.basis)
        self.limitations = _dedupe(self.limitations)
        self.constraints = _dedupe(self.constraints)
        self.required_resources = _dedupe(self.required_resources)
        if not self.basis and not self.limitations:
            raise ValueError("screening_assessment_requires_basis_or_limitations")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreeningAssessment":
        return cls(
            status=data.get("status", "not_screened"),
            basis=list(data.get("basis") or []),
            limitations=list(data.get("limitations") or []),
            confidence=data.get("confidence", "low"),
            constraints=list(data.get("constraints") or []),
            required_resources=list(data.get("required_resources") or []),
        )


@dataclass
class ScreeningRiskAssessment:
    status: str = "not_screened"
    risk_factors: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)
    mitigation_notes: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: str = "low"

    def __post_init__(self) -> None:
        if self.status not in RISK_STATUS_VALUES:
            raise ValueError(f"invalid_risk_screening_status:{self.status}")
        if self.confidence not in SCREENING_CONFIDENCE_VALUES:
            raise ValueError(f"invalid_screening_confidence:{self.confidence}")
        self.risk_factors = _dedupe(self.risk_factors)
        self.basis = _dedupe(self.basis)
        self.mitigation_notes = _dedupe(self.mitigation_notes)
        self.limitations = _dedupe(self.limitations)
        if not (self.risk_factors or self.basis or self.limitations):
            raise ValueError("risk_screening_requires_basis_or_limitations")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreeningRiskAssessment":
        return cls(
            status=data.get("status", "not_screened"),
            risk_factors=list(data.get("risk_factors") or []),
            basis=list(data.get("basis") or []),
            mitigation_notes=list(data.get("mitigation_notes") or []),
            limitations=list(data.get("limitations") or []),
            confidence=data.get("confidence", "low"),
        )


@dataclass
class ScreeningOverallAssessment:
    status: str = "not_recommended_yet"
    rationale: str = ""
    required_follow_up: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in OVERALL_SCREENING_STATUS_VALUES:
            raise ValueError(f"invalid_overall_screening_status:{self.status}")
        self.required_follow_up = _dedupe(self.required_follow_up)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreeningOverallAssessment":
        return cls(
            status=data.get("status", "not_recommended_yet"),
            rationale=data.get("rationale", ""),
            required_follow_up=list(data.get("required_follow_up") or []),
        )


@dataclass
class ScreenedIdeaRecord:
    idea_id: str
    source_idea_title: str
    gap_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    local_novelty_triage: dict[str, Any] = field(default_factory=dict)
    external_novelty_search: dict[str, Any] = field(default_factory=dict)
    feasibility_triage: dict[str, Any] = field(default_factory=dict)
    risk_triage: dict[str, Any] = field(default_factory=dict)
    overall_triage: dict[str, Any] = field(default_factory=dict)
    not_an_experiment_plan: bool = True
    not_a_validated_claim: bool = True
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.idea_id:
            raise ValueError("screened_idea_requires_source_idea_id")
        self.gap_ids = _dedupe(self.gap_ids)
        self.evidence_ids = _dedupe(self.evidence_ids)
        if not self.gap_ids:
            raise ValueError("screened_idea_requires_gap_ids")
        if not self.evidence_ids:
            raise ValueError("screened_idea_requires_evidence_ids")
        self.local_novelty_triage = dict(self.local_novelty_triage or {})
        self.external_novelty_search = dict(self.external_novelty_search or {})
        self.feasibility_triage = dict(self.feasibility_triage or {})
        self.risk_triage = dict(self.risk_triage or {})
        self.overall_triage = dict(self.overall_triage or {})
        if self.not_an_experiment_plan is not True:
            raise ValueError("screening_must_not_be_experiment_plan")
        if self.not_a_validated_claim is not True:
            raise ValueError("screening_must_not_be_validated_claim")
        self.warnings = _dedupe(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "source_idea_title": self.source_idea_title,
            "gap_ids": list(self.gap_ids),
            "evidence_ids": list(self.evidence_ids),
            "local_novelty_triage": dict(self.local_novelty_triage),
            "external_novelty_search": dict(self.external_novelty_search),
            "feasibility_triage": dict(self.feasibility_triage),
            "risk_triage": dict(self.risk_triage),
            "overall_triage": dict(self.overall_triage),
            "not_an_experiment_plan": self.not_an_experiment_plan,
            "not_a_validated_claim": self.not_a_validated_claim,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreenedIdeaRecord":
        return cls(
            idea_id=data.get("idea_id", ""),
            source_idea_title=data.get("source_idea_title", ""),
            gap_ids=list(data.get("gap_ids") or []),
            evidence_ids=list(data.get("evidence_ids") or []),
            local_novelty_triage=dict(data.get("local_novelty_triage") or {}),
            external_novelty_search=dict(data.get("external_novelty_search") or {}),
            feasibility_triage=dict(data.get("feasibility_triage") or {}),
            risk_triage=dict(data.get("risk_triage") or {}),
            overall_triage=dict(data.get("overall_triage") or {}),
            not_an_experiment_plan=bool(data.get("not_an_experiment_plan", True)),
            not_a_validated_claim=bool(data.get("not_a_validated_claim", True)),
            warnings=list(data.get("warnings") or []),
        )


@dataclass
class IdeaScreeningArtifact:
    task_id: str
    topic: str
    screening_id: str
    input_artifacts: list[str] = field(default_factory=list)
    idea_set_id: str = ""
    gap_map_id: str = ""
    landscape_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    screened_ideas: list[ScreenedIdeaRecord | dict[str, Any]] = field(default_factory=list)
    analysis_mode: str = "llm_assisted_local_evidence_triage"
    llm_provenance: dict[str, Any] = field(default_factory=dict)
    screening_scope: dict[str, Any] = field(default_factory=dict)
    screening_policy: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    schema_version: str = IDEA_SCREENING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.input_artifacts = list(self.input_artifacts or [])
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.screened_ideas = [
            idea if isinstance(idea, ScreenedIdeaRecord) else ScreenedIdeaRecord.from_dict(idea)
            for idea in self.screened_ideas
        ]
        self.screening_scope = dict(self.screening_scope or {})
        self.llm_provenance = dict(self.llm_provenance or {})
        self.screening_policy = dict(self.screening_policy or {})
        self.limitations = list(self.limitations or [])
        self.warnings = list(self.warnings or [])
        if self.schema_version != IDEA_SCREENING_SCHEMA_VERSION:
            raise ValueError("unsupported_idea_screening_schema_version")
        if self.screened_ideas and not all(idea.gap_ids for idea in self.screened_ideas):
            raise ValueError("screened_idea_requires_gap_ids")
        if self.screened_ideas and not all(idea.evidence_ids for idea in self.screened_ideas):
            raise ValueError("screened_idea_requires_evidence_ids")

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "topic": self.topic,
            "screening_id": self.screening_id,
            "input_artifacts": list(self.input_artifacts),
            "idea_set_id": self.idea_set_id,
            "gap_map_id": self.gap_map_id,
            "landscape_id": self.landscape_id,
            "evidence_ids": list(self.evidence_ids),
            "source_paper_ids": list(self.source_paper_ids),
            "screened_ideas": [idea.as_dict() for idea in self.screened_ideas],
            "analysis_mode": self.analysis_mode,
            "llm_provenance": dict(self.llm_provenance),
            "screening_scope": dict(self.screening_scope),
            "screening_policy": dict(self.screening_policy),
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IdeaScreeningArtifact":
        return cls(
            task_id=data["task_id"],
            topic=data["topic"],
            screening_id=data["screening_id"],
            input_artifacts=list(data.get("input_artifacts") or []),
            idea_set_id=data.get("idea_set_id", ""),
            gap_map_id=data.get("gap_map_id", ""),
            landscape_id=data.get("landscape_id", ""),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            screened_ideas=list(data.get("screened_ideas") or []),
            analysis_mode=data.get("analysis_mode", "llm_assisted_local_evidence_triage"),
            llm_provenance=dict(data.get("llm_provenance") or {}),
            screening_scope=dict(data.get("screening_scope") or {}),
            screening_policy=dict(data.get("screening_policy") or {}),
            limitations=list(data.get("limitations") or []),
            warnings=list(data.get("warnings") or []),
            created_at=data.get("created_at", time.time()),
            schema_version=data.get("schema_version", IDEA_SCREENING_SCHEMA_VERSION),
        )


def validate_screening_input_artifacts(input_artifacts: list[str]) -> list[str]:
    errors: list[str] = []
    artifact_set = set(input_artifacts or [])
    for artifact_path in input_artifacts:
        if artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_screening")
        elif artifact_path.startswith(("raw_chunks/", "chunks/")):
            errors.append(f"raw_chunks_not_allowed_for_screening:{artifact_path}")
        elif artifact_path in {"evidence/evidence_card_seeds.json", "evidence/evidence_cards.initial.json"}:
            errors.append(f"unenriched_evidence_not_allowed_for_screening:{artifact_path}")
        elif artifact_path.endswith(".md") and artifact_path not in SCREENING_OPTIONAL_INPUT_ARTIFACTS:
            errors.append(f"raw_markdown_not_allowed_for_screening:{artifact_path}")

    if "ideas/candidate_ideas.json" not in artifact_set:
        errors.append("missing_candidate_ideas_artifact")

    basis_requirements = {
        "ideas/candidate_ideas.json",
        "gaps/gap_map.json",
        "landscape/literature_landscape.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    }
    if not basis_requirements.issubset(artifact_set):
        errors.append("screening_requires_gap_and_evidence_basis")

    missing = [
        path
        for path in SCREENING_REQUIRED_INPUT_ARTIFACTS
        if path not in artifact_set and path != "ideas/candidate_ideas.json"
    ]
    errors.extend(f"missing_screening_input:{path}" for path in missing)
    return _dedupe(errors)


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "FEASIBILITY_STATUS_VALUES",
    "IDEA_SCREENING_SCHEMA_VERSION",
    "NOVELTY_STATUS_VALUES",
    "OVERALL_SCREENING_STATUS_VALUES",
    "RISK_STATUS_VALUES",
    "SCREENING_ALLOWED_MARKDOWN_SECTIONS",
    "SCREENING_CONFIDENCE_VALUES",
    "SCREENING_FORBIDDEN_INPUT_ARTIFACTS",
    "SCREENING_FORBIDDEN_MARKDOWN_SECTIONS",
    "SCREENING_OPTIONAL_INPUT_ARTIFACTS",
    "SCREENING_OUTPUT_ARTIFACTS",
    "SCREENING_REQUIRED_INPUT_ARTIFACTS",
    "SCREENING_VALIDATION_EXPECTATIONS",
    "IdeaScreeningArtifact",
    "ScreenedIdeaRecord",
    "ScreeningAssessment",
    "ScreeningOverallAssessment",
    "ScreeningRiskAssessment",
    "validate_screening_input_artifacts",
]
