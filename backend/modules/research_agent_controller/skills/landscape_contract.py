"""P2-M8.1 Landscape skill contract and artifact schema.

This module defines metadata and JSON-safe schema objects only. It does not
generate landscape artifacts and does not execute controller or retrieval code.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

LANDSCAPE_SCHEMA_VERSION = "landscape_v1"

LANDSCAPE_REQUIRED_INPUT_ARTIFACTS = [
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
]

LANDSCAPE_OPTIONAL_INPUT_ARTIFACTS = [
    "reports/minimal_topic_to_evidence_report.json",
]

LANDSCAPE_FORBIDDEN_INPUT_ARTIFACTS = [
    "retrieval/source_candidate_packet.json",
    "retrieval/retrieval_warnings.json",
    "evidence/evidence_card_seeds.json",
    "evidence/evidence_cards.initial.json",
]

LANDSCAPE_OUTPUT_ARTIFACTS = [
    "landscape/literature_landscape.json",
    "landscape/literature_landscape.md",
    "landscape/landscape_coverage_diagnostics.json",
]

LANDSCAPE_INITIAL_AXES = [
    "material_system",
    "synthesis_strategy",
    "defect_type",
    "mechanistic_role",
    "performance_metric",
    "characterization_method",
    "application_condition",
]

LANDSCAPE_ALLOWED_MARKDOWN_SECTIONS = [
    "Scope",
    "Evidence Base",
    "Landscape Axes",
    "Main Evidence Clusters",
    "Coverage Diagnostics",
    "Limitations",
    "Evidence References",
]

LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS = [
    "Research Gaps",
    "Candidate Ideas",
    "Novelty Screening",
    "Experiment Plan",
    "Manuscript Draft",
]

LANDSCAPE_VALIDATION_EXPECTATIONS = [
    "input_artifacts_exist",
    "inputs_are_validated_enriched_evidence_cards_or_selected_evidence",
    "no_retrieval_inputs",
    "output_json_parseable",
    "schema_version_is_landscape_v1",
    "every_cluster_has_evidence_ids",
    "every_representative_claim_references_evidence_id",
    "markdown_contains_evidence_references",
    "markdown_excludes_gap_idea_novelty_experiment_manuscript_sections",
    "coverage_diagnostics_preserved",
]


@dataclass
class LandscapeAxis:
    axis_id: str
    name: str
    description: str = ""
    values: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.values = list(self.values or [])

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LandscapeAxis":
        return cls(
            axis_id=data["axis_id"],
            name=data["name"],
            description=data.get("description", ""),
            values=list(data.get("values") or []),
        )


@dataclass
class LandscapeCluster:
    cluster_id: str
    title: str
    description: str = ""
    axis_values: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    representative_claims: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "low"
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.axis_values = dict(self.axis_values or {})
        self.evidence_ids = _dedupe(self.evidence_ids)
        if not self.evidence_ids:
            raise ValueError("cluster_requires_evidence_ids")
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.representative_claims = [dict(claim) for claim in self.representative_claims or []]
        self.confidence = _coerce_confidence(self.confidence)
        self.warnings = list(self.warnings or [])
        for index, claim in enumerate(self.representative_claims):
            evidence_refs = _dedupe(claim.get("evidence_ids") or [])
            if not evidence_refs:
                raise ValueError(f"representative_claim_requires_evidence_ids:{index}")
            claim["evidence_ids"] = evidence_refs

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LandscapeCluster":
        return cls(
            cluster_id=data["cluster_id"],
            title=data["title"],
            description=data.get("description", ""),
            axis_values=dict(data.get("axis_values") or {}),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            representative_claims=list(data.get("representative_claims") or []),
            confidence=data.get("confidence", "low"),
            warnings=list(data.get("warnings") or []),
        )


@dataclass
class RepresentativeEvidence:
    evidence_id: str
    paper_id: str
    role: str = ""
    source_type: str = ""
    source_path: str = ""
    cluster_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("representative_evidence_requires_evidence_id")
        self.cluster_ids = _dedupe(self.cluster_ids)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepresentativeEvidence":
        return cls(
            evidence_id=data["evidence_id"],
            paper_id=data.get("paper_id", ""),
            role=data.get("role", ""),
            source_type=data.get("source_type", ""),
            source_path=data.get("source_path", ""),
            cluster_ids=list(data.get("cluster_ids") or []),
            reason=data.get("reason", ""),
        )


@dataclass
class LandscapeArtifact:
    task_id: str
    topic: str
    landscape_id: str
    input_artifacts: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    landscape_axes: list[LandscapeAxis | dict[str, Any]] = field(default_factory=list)
    clusters: list[LandscapeCluster | dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    representative_evidence: list[RepresentativeEvidence | dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    schema_version: str = LANDSCAPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.input_artifacts = list(self.input_artifacts or [])
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.landscape_axes = [
            axis if isinstance(axis, LandscapeAxis) else LandscapeAxis.from_dict(axis)
            for axis in self.landscape_axes
        ]
        self.clusters = [
            cluster if isinstance(cluster, LandscapeCluster) else LandscapeCluster.from_dict(cluster)
            for cluster in self.clusters
        ]
        self.coverage = dict(self.coverage or {})
        self.representative_evidence = [
            item if isinstance(item, RepresentativeEvidence) else RepresentativeEvidence.from_dict(item)
            for item in self.representative_evidence
        ]
        self.limitations = list(self.limitations or [])
        self.warnings = list(self.warnings or [])
        if self.schema_version != LANDSCAPE_SCHEMA_VERSION:
            raise ValueError("unsupported_landscape_schema_version")
        cluster_evidence = {evidence_id for cluster in self.clusters for evidence_id in cluster.evidence_ids}
        if self.clusters and not cluster_evidence:
            raise ValueError("landscape_requires_cluster_evidence_ids")

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "topic": self.topic,
            "landscape_id": self.landscape_id,
            "input_artifacts": list(self.input_artifacts),
            "evidence_ids": list(self.evidence_ids),
            "source_paper_ids": list(self.source_paper_ids),
            "landscape_axes": [axis.as_dict() for axis in self.landscape_axes],
            "clusters": [cluster.as_dict() for cluster in self.clusters],
            "coverage": dict(self.coverage),
            "representative_evidence": [item.as_dict() for item in self.representative_evidence],
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LandscapeArtifact":
        return cls(
            task_id=data["task_id"],
            topic=data["topic"],
            landscape_id=data["landscape_id"],
            input_artifacts=list(data.get("input_artifacts") or []),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            landscape_axes=list(data.get("landscape_axes") or []),
            clusters=list(data.get("clusters") or []),
            coverage=dict(data.get("coverage") or {}),
            representative_evidence=list(data.get("representative_evidence") or []),
            limitations=list(data.get("limitations") or []),
            warnings=list(data.get("warnings") or []),
            created_at=data.get("created_at", time.time()),
            schema_version=data.get("schema_version", LANDSCAPE_SCHEMA_VERSION),
        )


def validate_landscape_input_artifacts(input_artifacts: list[str]) -> list[str]:
    errors: list[str] = []
    for artifact_path in input_artifacts:
        if artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_landscape")
        elif artifact_path in {"evidence/evidence_card_seeds.json", "evidence/evidence_cards.initial.json"}:
            errors.append(f"unenriched_evidence_not_allowed_for_landscape:{artifact_path}")
        elif artifact_path.endswith(".md") and artifact_path not in LANDSCAPE_OPTIONAL_INPUT_ARTIFACTS:
            errors.append(f"raw_markdown_not_allowed_for_landscape:{artifact_path}")

    missing = [path for path in LANDSCAPE_REQUIRED_INPUT_ARTIFACTS if path not in input_artifacts]
    errors.extend(f"missing_landscape_input:{path}" for path in missing)
    return _dedupe(errors)


def _coerce_confidence(value: str) -> str:
    if value not in {"low", "medium", "high"}:
        raise ValueError(f"invalid_landscape_confidence:{value}")
    return value


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "LANDSCAPE_ALLOWED_MARKDOWN_SECTIONS",
    "LANDSCAPE_FORBIDDEN_INPUT_ARTIFACTS",
    "LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS",
    "LANDSCAPE_INITIAL_AXES",
    "LANDSCAPE_OPTIONAL_INPUT_ARTIFACTS",
    "LANDSCAPE_OUTPUT_ARTIFACTS",
    "LANDSCAPE_REQUIRED_INPUT_ARTIFACTS",
    "LANDSCAPE_SCHEMA_VERSION",
    "LANDSCAPE_VALIDATION_EXPECTATIONS",
    "LandscapeArtifact",
    "LandscapeAxis",
    "LandscapeCluster",
    "RepresentativeEvidence",
    "validate_landscape_input_artifacts",
]
