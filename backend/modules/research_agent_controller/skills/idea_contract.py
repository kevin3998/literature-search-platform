"""P2-M10.1 idea generation skill contract and artifact schema.

This module defines metadata and JSON-safe schema objects only. It does not
generate candidate ideas and does not execute any platform runtime code.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

CANDIDATE_IDEAS_SCHEMA_VERSION = "candidate_ideas_v1"

IDEA_REQUIRED_INPUT_ARTIFACTS = [
    "gaps/gap_map.json",
    "gaps/gap_coverage_diagnostics.json",
    "landscape/literature_landscape.json",
    "landscape/landscape_coverage_diagnostics.json",
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
]

IDEA_OPTIONAL_INPUT_ARTIFACTS = [
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]

IDEA_FORBIDDEN_INPUT_ARTIFACTS = [
    "retrieval/source_candidate_packet.json",
    "retrieval/retrieval_warnings.json",
    "evidence/evidence_card_seeds.json",
    "evidence/evidence_cards.initial.json",
]

IDEA_OUTPUT_ARTIFACTS = [
    "ideas/candidate_ideas.json",
    "ideas/candidate_ideas.md",
    "ideas/idea_generation_diagnostics.json",
]

IDEA_ALLOWED_TYPES = [
    "mechanism_hypothesis",
    "material_strategy",
    "synthesis_strategy",
    "characterization_strategy",
    "performance_validation",
    "comparative_study",
    "data_integration",
]

IDEA_ALLOWED_MARKDOWN_SECTIONS = [
    "Scope",
    "Gap And Evidence Base",
    "Candidate Idea Set",
    "Assumptions And Constraints",
    "Required Downstream Screening",
    "Limitations",
    "Evidence References",
]

IDEA_FORBIDDEN_MARKDOWN_SECTIONS = [
    "Novelty Screening",
    "Feasibility Screening",
    "Risk Screening",
    "Experiment Plan",
    "Manuscript Draft",
]

IDEA_VALIDATION_EXPECTATIONS = [
    "input_artifacts_exist",
    "gap_map_json_exists_and_parseable",
    "gap_map_schema_version_is_gap_map_v1",
    "no_retrieval_inputs",
    "landscape_json_exists_and_parseable",
    "enriched_evidence_cards_and_selected_evidence_present",
    "output_json_parseable",
    "schema_version_is_candidate_ideas_v1",
    "every_idea_has_gap_basis",
    "every_idea_has_evidence_basis",
    "every_idea_references_gap_id",
    "every_idea_references_evidence_id",
    "every_idea_not_yet_screened",
    "every_idea_requires_novelty_screening",
    "every_idea_requires_feasibility_screening",
    "markdown_contains_evidence_references",
    "markdown_excludes_novelty_feasibility_risk_experiment_manuscript_sections",
    "no_idea_claims_novelty_feasibility_or_validation_as_fact",
]


@dataclass
class CandidateIdeaGapBasis:
    gap_ids: list[str] = field(default_factory=list)
    gap_types: list[str] = field(default_factory=list)
    landscape_cluster_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    coverage_warnings: list[str] = field(default_factory=list)
    diagnostic_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.gap_ids = _dedupe(self.gap_ids)
        self.gap_types = _dedupe(self.gap_types)
        self.landscape_cluster_ids = _dedupe(self.landscape_cluster_ids)
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.coverage_warnings = _dedupe(self.coverage_warnings)
        self.diagnostic_refs = _dedupe(self.diagnostic_refs)

    def has_gap_support(self) -> bool:
        return bool(self.gap_ids)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateIdeaGapBasis":
        return cls(
            gap_ids=list(data.get("gap_ids") or []),
            gap_types=list(data.get("gap_types") or []),
            landscape_cluster_ids=list(data.get("landscape_cluster_ids") or []),
            evidence_ids=list(data.get("evidence_ids") or []),
            coverage_warnings=list(data.get("coverage_warnings") or []),
            diagnostic_refs=list(data.get("diagnostic_refs") or []),
        )


@dataclass
class CandidateIdeaEvidenceBasis:
    supporting_evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    representative_claim_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.supporting_evidence_ids = _dedupe(self.supporting_evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.representative_claim_refs = _dedupe(self.representative_claim_refs)

    def has_evidence_support(self) -> bool:
        return bool(self.supporting_evidence_ids)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateIdeaEvidenceBasis":
        return cls(
            supporting_evidence_ids=list(data.get("supporting_evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            representative_claim_refs=list(data.get("representative_claim_refs") or []),
        )


@dataclass
class CandidateIdeaRecord:
    idea_id: str
    title: str
    summary: str
    idea_type: str
    gap_basis: CandidateIdeaGapBasis | dict[str, Any] = field(default_factory=CandidateIdeaGapBasis)
    evidence_basis: CandidateIdeaEvidenceBasis | dict[str, Any] = field(default_factory=CandidateIdeaEvidenceBasis)
    rationale: str = ""
    expected_contribution: str = ""
    assumptions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    not_yet_screened: bool = True
    requires_novelty_screening: bool = True
    requires_feasibility_screening: bool = True
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.idea_type not in IDEA_ALLOWED_TYPES:
            raise ValueError(f"invalid_candidate_idea_type:{self.idea_type}")
        self.gap_basis = (
            self.gap_basis
            if isinstance(self.gap_basis, CandidateIdeaGapBasis)
            else CandidateIdeaGapBasis.from_dict(self.gap_basis)
        )
        self.evidence_basis = (
            self.evidence_basis
            if isinstance(self.evidence_basis, CandidateIdeaEvidenceBasis)
            else CandidateIdeaEvidenceBasis.from_dict(self.evidence_basis)
        )
        if not self.gap_basis.has_gap_support():
            raise ValueError("candidate_idea_requires_gap_basis")
        if not self.evidence_basis.has_evidence_support():
            raise ValueError("candidate_idea_requires_evidence_basis")
        if self.not_yet_screened is not True:
            raise ValueError("candidate_idea_must_remain_unscreened")
        if self.requires_novelty_screening is not True:
            raise ValueError("candidate_idea_requires_novelty_screening")
        if self.requires_feasibility_screening is not True:
            raise ValueError("candidate_idea_requires_feasibility_screening")
        self.assumptions = list(self.assumptions or [])
        self.constraints = list(self.constraints or [])
        self.warnings = list(self.warnings or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "title": self.title,
            "summary": self.summary,
            "idea_type": self.idea_type,
            "gap_basis": self.gap_basis.as_dict(),
            "evidence_basis": self.evidence_basis.as_dict(),
            "rationale": self.rationale,
            "expected_contribution": self.expected_contribution,
            "assumptions": list(self.assumptions),
            "constraints": list(self.constraints),
            "not_yet_screened": self.not_yet_screened,
            "requires_novelty_screening": self.requires_novelty_screening,
            "requires_feasibility_screening": self.requires_feasibility_screening,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateIdeaRecord":
        return cls(
            idea_id=data["idea_id"],
            title=data["title"],
            summary=data["summary"],
            idea_type=data["idea_type"],
            gap_basis=dict(data.get("gap_basis") or {}),
            evidence_basis=dict(data.get("evidence_basis") or {}),
            rationale=data.get("rationale", ""),
            expected_contribution=data.get("expected_contribution", ""),
            assumptions=list(data.get("assumptions") or []),
            constraints=list(data.get("constraints") or []),
            not_yet_screened=bool(data.get("not_yet_screened", True)),
            requires_novelty_screening=bool(data.get("requires_novelty_screening", True)),
            requires_feasibility_screening=bool(data.get("requires_feasibility_screening", True)),
            warnings=list(data.get("warnings") or []),
        )


@dataclass
class CandidateIdeaArtifact:
    task_id: str
    topic: str
    idea_set_id: str
    input_artifacts: list[str] = field(default_factory=list)
    gap_map_id: str = ""
    landscape_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    ideas: list[CandidateIdeaRecord | dict[str, Any]] = field(default_factory=list)
    generation_scope: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    schema_version: str = CANDIDATE_IDEAS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.input_artifacts = list(self.input_artifacts or [])
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.ideas = [
            idea if isinstance(idea, CandidateIdeaRecord) else CandidateIdeaRecord.from_dict(idea)
            for idea in self.ideas
        ]
        self.generation_scope = dict(self.generation_scope or {})
        self.constraints = dict(self.constraints or {})
        self.limitations = list(self.limitations or [])
        self.warnings = list(self.warnings or [])
        if self.schema_version != CANDIDATE_IDEAS_SCHEMA_VERSION:
            raise ValueError("unsupported_candidate_ideas_schema_version")
        if self.ideas and not all(idea.gap_basis.has_gap_support() for idea in self.ideas):
            raise ValueError("candidate_idea_requires_gap_basis")
        if self.ideas and not all(idea.evidence_basis.has_evidence_support() for idea in self.ideas):
            raise ValueError("candidate_idea_requires_evidence_basis")

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "topic": self.topic,
            "idea_set_id": self.idea_set_id,
            "input_artifacts": list(self.input_artifacts),
            "gap_map_id": self.gap_map_id,
            "landscape_id": self.landscape_id,
            "evidence_ids": list(self.evidence_ids),
            "source_paper_ids": list(self.source_paper_ids),
            "ideas": [idea.as_dict() for idea in self.ideas],
            "generation_scope": dict(self.generation_scope),
            "constraints": dict(self.constraints),
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateIdeaArtifact":
        return cls(
            task_id=data["task_id"],
            topic=data["topic"],
            idea_set_id=data["idea_set_id"],
            input_artifacts=list(data.get("input_artifacts") or []),
            gap_map_id=data.get("gap_map_id", ""),
            landscape_id=data.get("landscape_id", ""),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            ideas=list(data.get("ideas") or []),
            generation_scope=dict(data.get("generation_scope") or {}),
            constraints=dict(data.get("constraints") or {}),
            limitations=list(data.get("limitations") or []),
            warnings=list(data.get("warnings") or []),
            created_at=data.get("created_at", time.time()),
            schema_version=data.get("schema_version", CANDIDATE_IDEAS_SCHEMA_VERSION),
        )


def validate_idea_generation_input_artifacts(input_artifacts: list[str]) -> list[str]:
    errors: list[str] = []
    artifact_set = set(input_artifacts or [])
    for artifact_path in input_artifacts:
        if artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_idea_generation")
        elif artifact_path.startswith(("raw_chunks/", "chunks/")):
            errors.append(f"raw_chunks_not_allowed_for_idea_generation:{artifact_path}")
        elif artifact_path in {"evidence/evidence_card_seeds.json", "evidence/evidence_cards.initial.json"}:
            errors.append(f"unenriched_evidence_not_allowed_for_idea_generation:{artifact_path}")
        elif artifact_path.endswith(".md") and artifact_path not in IDEA_OPTIONAL_INPUT_ARTIFACTS:
            errors.append(f"raw_markdown_not_allowed_for_idea_generation:{artifact_path}")

    if "gaps/gap_map.json" not in artifact_set:
        errors.append("missing_gap_map_artifact")

    evidence_requirements = {
        "gaps/gap_map.json",
        "landscape/literature_landscape.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    }
    if not evidence_requirements.issubset(artifact_set):
        errors.append("idea_generation_requires_evidence_references")

    missing = [
        path
        for path in IDEA_REQUIRED_INPUT_ARTIFACTS
        if path not in artifact_set and path != "gaps/gap_map.json"
    ]
    errors.extend(f"missing_idea_generation_input:{path}" for path in missing)
    return _dedupe(errors)


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "CANDIDATE_IDEAS_SCHEMA_VERSION",
    "IDEA_ALLOWED_MARKDOWN_SECTIONS",
    "IDEA_ALLOWED_TYPES",
    "IDEA_FORBIDDEN_INPUT_ARTIFACTS",
    "IDEA_FORBIDDEN_MARKDOWN_SECTIONS",
    "IDEA_OPTIONAL_INPUT_ARTIFACTS",
    "IDEA_OUTPUT_ARTIFACTS",
    "IDEA_REQUIRED_INPUT_ARTIFACTS",
    "IDEA_VALIDATION_EXPECTATIONS",
    "CandidateIdeaArtifact",
    "CandidateIdeaEvidenceBasis",
    "CandidateIdeaGapBasis",
    "CandidateIdeaRecord",
    "validate_idea_generation_input_artifacts",
]
