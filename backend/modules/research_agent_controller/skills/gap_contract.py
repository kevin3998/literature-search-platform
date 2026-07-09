"""P2-M9.1 Gap mapping skill contract and artifact schema.

This module defines metadata and JSON-safe schema objects only. It does not
generate gap artifacts and does not execute any platform runtime code.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

GAP_MAP_SCHEMA_VERSION = "gap_map_v1"

GAP_REQUIRED_INPUT_ARTIFACTS = [
    "landscape/literature_landscape.json",
    "landscape/landscape_coverage_diagnostics.json",
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
]

GAP_OPTIONAL_INPUT_ARTIFACTS = [
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]

GAP_FORBIDDEN_INPUT_ARTIFACTS = [
    "retrieval/source_candidate_packet.json",
    "retrieval/retrieval_warnings.json",
    "evidence/evidence_card_seeds.json",
    "evidence/evidence_cards.initial.json",
]

GAP_OUTPUT_ARTIFACTS = [
    "gaps/gap_map.json",
    "gaps/gap_map.md",
    "gaps/gap_coverage_diagnostics.json",
]

GAP_INITIAL_AXES = [
    "material_system",
    "mechanistic_role",
    "defect_type",
    "synthesis_strategy",
    "performance_metric",
    "characterization_method",
    "application_condition",
    "source_type",
    "evidence_role",
]

GAP_ALLOWED_TYPES = [
    "coverage_gap",
    "comparison_gap",
    "evidence_quality_gap",
    "source_type_gap",
    "role_gap",
    "condition_gap",
]

GAP_ALLOWED_MARKDOWN_SECTIONS = [
    "Scope",
    "Evidence And Landscape Base",
    "Gap Axes",
    "Identified Evidence Gaps",
    "Coverage Diagnostics",
    "Limitations",
    "Evidence References",
]

GAP_FORBIDDEN_MARKDOWN_SECTIONS = [
    "Candidate Ideas",
    "Proposed Research Directions",
    "Novelty Screening",
    "Feasibility Screening",
    "Experiment Plan",
    "Manuscript Draft",
]

GAP_VALIDATION_EXPECTATIONS = [
    "input_artifacts_exist",
    "landscape_json_exists_and_parseable",
    "landscape_schema_version_is_landscape_v1",
    "no_retrieval_inputs",
    "enriched_evidence_cards_and_selected_evidence_present",
    "output_json_parseable",
    "schema_version_is_gap_map_v1",
    "every_gap_has_basis",
    "every_gap_basis_references_evidence_landscape_or_diagnostics",
    "no_gap_is_candidate_idea",
    "markdown_contains_evidence_references",
    "markdown_excludes_idea_novelty_feasibility_experiment_manuscript_sections",
    "coverage_diagnostics_preserved",
]


@dataclass
class GapAxis:
    axis_id: str
    name: str
    description: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GapAxis":
        return cls(
            axis_id=data["axis_id"],
            name=data["name"],
            description=data.get("description", ""),
            source=data.get("source", ""),
        )


@dataclass
class GapBasis:
    landscape_cluster_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    coverage_warnings: list[str] = field(default_factory=list)
    diagnostic_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.landscape_cluster_ids = _dedupe(self.landscape_cluster_ids)
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.coverage_warnings = _dedupe(self.coverage_warnings)
        self.diagnostic_refs = _dedupe(self.diagnostic_refs)

    def has_support(self) -> bool:
        return any(
            [
                self.landscape_cluster_ids,
                self.evidence_ids,
                self.coverage_warnings,
                self.diagnostic_refs,
            ]
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GapBasis":
        return cls(
            landscape_cluster_ids=list(data.get("landscape_cluster_ids") or []),
            evidence_ids=list(data.get("evidence_ids") or []),
            coverage_warnings=list(data.get("coverage_warnings") or []),
            diagnostic_refs=list(data.get("diagnostic_refs") or []),
        )


@dataclass
class GapRecord:
    gap_id: str
    gap_type: str
    title: str
    description: str = ""
    axis_values: dict[str, Any] = field(default_factory=dict)
    basis: GapBasis | dict[str, Any] = field(default_factory=GapBasis)
    severity: str = "low"
    confidence: str = "low"
    not_an_idea: bool = True
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.gap_type not in GAP_ALLOWED_TYPES:
            raise ValueError(f"invalid_gap_type:{self.gap_type}")
        self.axis_values = dict(self.axis_values or {})
        self.basis = self.basis if isinstance(self.basis, GapBasis) else GapBasis.from_dict(self.basis)
        if not self.basis.has_support():
            raise ValueError("gap_requires_basis")
        self.severity = _coerce_level(self.severity, "severity")
        self.confidence = _coerce_level(self.confidence, "confidence")
        if self.not_an_idea is not True:
            raise ValueError("gap_must_not_be_candidate_idea")
        self.warnings = list(self.warnings or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type,
            "title": self.title,
            "description": self.description,
            "axis_values": dict(self.axis_values),
            "basis": self.basis.as_dict(),
            "severity": self.severity,
            "confidence": self.confidence,
            "not_an_idea": self.not_an_idea,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GapRecord":
        return cls(
            gap_id=data["gap_id"],
            gap_type=data["gap_type"],
            title=data["title"],
            description=data.get("description", ""),
            axis_values=dict(data.get("axis_values") or {}),
            basis=dict(data.get("basis") or {}),
            severity=data.get("severity", "low"),
            confidence=data.get("confidence", "low"),
            not_an_idea=bool(data.get("not_an_idea", True)),
            warnings=list(data.get("warnings") or []),
        )


@dataclass
class SupportingEvidence:
    evidence_id: str
    paper_id: str = ""
    role: str = ""
    source_type: str = ""
    gap_ids: list[str] = field(default_factory=list)
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("supporting_evidence_requires_evidence_id")
        self.gap_ids = _dedupe(self.gap_ids)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SupportingEvidence":
        return cls(
            evidence_id=data["evidence_id"],
            paper_id=data.get("paper_id", ""),
            role=data.get("role", ""),
            source_type=data.get("source_type", ""),
            gap_ids=list(data.get("gap_ids") or []),
            reason=data.get("reason", ""),
        )


@dataclass
class GapMapArtifact:
    task_id: str
    topic: str
    gap_map_id: str
    input_artifacts: list[str] = field(default_factory=list)
    landscape_id: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    source_paper_ids: list[str] = field(default_factory=list)
    gap_axes: list[GapAxis | dict[str, Any]] = field(default_factory=list)
    gaps: list[GapRecord | dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    supporting_evidence: list[SupportingEvidence | dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    schema_version: str = GAP_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.input_artifacts = list(self.input_artifacts or [])
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.gap_axes = [
            axis if isinstance(axis, GapAxis) else GapAxis.from_dict(axis)
            for axis in self.gap_axes
        ]
        self.gaps = [
            gap if isinstance(gap, GapRecord) else GapRecord.from_dict(gap)
            for gap in self.gaps
        ]
        self.coverage = dict(self.coverage or {})
        self.supporting_evidence = [
            item if isinstance(item, SupportingEvidence) else SupportingEvidence.from_dict(item)
            for item in self.supporting_evidence
        ]
        self.limitations = list(self.limitations or [])
        self.warnings = list(self.warnings or [])
        if self.schema_version != GAP_MAP_SCHEMA_VERSION:
            raise ValueError("unsupported_gap_map_schema_version")
        if self.gaps and not any(gap.basis.has_support() for gap in self.gaps):
            raise ValueError("gap_mapping_requires_evidence_references")

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "topic": self.topic,
            "gap_map_id": self.gap_map_id,
            "input_artifacts": list(self.input_artifacts),
            "landscape_id": self.landscape_id,
            "evidence_ids": list(self.evidence_ids),
            "source_paper_ids": list(self.source_paper_ids),
            "gap_axes": [axis.as_dict() for axis in self.gap_axes],
            "gaps": [gap.as_dict() for gap in self.gaps],
            "coverage": dict(self.coverage),
            "supporting_evidence": [item.as_dict() for item in self.supporting_evidence],
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GapMapArtifact":
        return cls(
            task_id=data["task_id"],
            topic=data["topic"],
            gap_map_id=data["gap_map_id"],
            input_artifacts=list(data.get("input_artifacts") or []),
            landscape_id=data.get("landscape_id", ""),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            gap_axes=list(data.get("gap_axes") or []),
            gaps=list(data.get("gaps") or []),
            coverage=dict(data.get("coverage") or {}),
            supporting_evidence=list(data.get("supporting_evidence") or []),
            limitations=list(data.get("limitations") or []),
            warnings=list(data.get("warnings") or []),
            created_at=data.get("created_at", time.time()),
            schema_version=data.get("schema_version", GAP_MAP_SCHEMA_VERSION),
        )


def validate_gap_mapping_input_artifacts(input_artifacts: list[str]) -> list[str]:
    errors: list[str] = []
    artifact_set = set(input_artifacts or [])
    for artifact_path in input_artifacts:
        if artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_gap_mapping")
        elif artifact_path.startswith(("raw_chunks/", "chunks/")):
            errors.append(f"raw_chunks_not_allowed_for_gap_mapping:{artifact_path}")
        elif artifact_path in {"evidence/evidence_card_seeds.json", "evidence/evidence_cards.initial.json"}:
            errors.append(f"unenriched_evidence_not_allowed_for_gap_mapping:{artifact_path}")
        elif artifact_path.endswith(".md") and artifact_path not in GAP_OPTIONAL_INPUT_ARTIFACTS:
            errors.append(f"raw_markdown_not_allowed_for_gap_mapping:{artifact_path}")

    if "landscape/literature_landscape.json" not in artifact_set:
        errors.append("missing_landscape_artifact")

    evidence_requirements = {
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    }
    if not evidence_requirements.issubset(artifact_set):
        errors.append("gap_mapping_requires_evidence_references")

    missing = [
        path
        for path in GAP_REQUIRED_INPUT_ARTIFACTS
        if path not in artifact_set and path != "landscape/literature_landscape.json"
    ]
    errors.extend(f"missing_gap_mapping_input:{path}" for path in missing)
    return _dedupe(errors)


def _coerce_level(value: str, field_name: str) -> str:
    if value not in {"low", "medium", "high"}:
        raise ValueError(f"invalid_gap_{field_name}:{value}")
    return value


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "GAP_ALLOWED_MARKDOWN_SECTIONS",
    "GAP_ALLOWED_TYPES",
    "GAP_FORBIDDEN_INPUT_ARTIFACTS",
    "GAP_FORBIDDEN_MARKDOWN_SECTIONS",
    "GAP_INITIAL_AXES",
    "GAP_MAP_SCHEMA_VERSION",
    "GAP_OPTIONAL_INPUT_ARTIFACTS",
    "GAP_OUTPUT_ARTIFACTS",
    "GAP_REQUIRED_INPUT_ARTIFACTS",
    "GAP_VALIDATION_EXPECTATIONS",
    "GapAxis",
    "GapBasis",
    "GapMapArtifact",
    "GapRecord",
    "SupportingEvidence",
    "validate_gap_mapping_input_artifacts",
]
