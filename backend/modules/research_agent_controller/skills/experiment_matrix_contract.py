"""P2-M12.1 experiment matrix skill contract and artifact schema.

This module defines metadata and JSON-safe schema objects only. It does not
generate experiment matrices, protocols, recipes, manuscripts, or final claims.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

EXPERIMENT_MATRIX_SCHEMA_VERSION = "experiment_matrix_v1"

EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS = [
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

EXPERIMENT_MATRIX_OPTIONAL_INPUT_ARTIFACTS = [
    "screening/idea_screening_results.md",
    "ideas/candidate_ideas.md",
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]

EXPERIMENT_MATRIX_FORBIDDEN_INPUT_ARTIFACTS = [
    "retrieval/source_candidate_packet.json",
    "retrieval/retrieval_warnings.json",
    "evidence/evidence_card_seeds.json",
    "evidence/evidence_cards.initial.json",
]

EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS = [
    "experiments/experiment_matrix.json",
    "experiments/experiment_matrix.md",
    "experiments/experiment_matrix_diagnostics.json",
]

EXPERIMENT_MATRIX_ALLOWED_MARKDOWN_SECTIONS = [
    "Scope",
    "Screening And Evidence Base",
    "Candidate Experiment Matrix",
    "Variables And Controls",
    "Characterization Targets",
    "Data To Record",
    "Required Expert Review",
    "Limitations",
    "Evidence References",
]

EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS = [
    "Experimental Protocol",
    "Step-by-step Procedure",
    "Synthesis Recipe",
    "Safety Protocol",
    "Manuscript Draft",
    "Final Claims",
]

EXPERIMENT_MATRIX_VARIABLE_ROLES = [
    "composition",
    "structure",
    "defect",
    "synthesis_condition",
    "treatment_condition",
    "characterization_condition",
    "performance_condition",
    "comparison_factor",
]

EXPERIMENT_MATRIX_CHARACTERIZATION_PURPOSES = [
    "verify_structure",
    "verify_defect",
    "verify_composition",
    "verify_mechanism",
    "verify_performance",
    "compare_control",
]

EXPERIMENT_MATRIX_VALIDATION_EXPECTATIONS = [
    "input_artifacts_exist",
    "screening_results_json_exists_and_parseable",
    "screening_schema_version_is_idea_screening_v2",
    "candidate_ideas_json_exists_and_parseable",
    "candidate_ideas_schema_version_is_candidate_ideas_v1",
    "no_retrieval_inputs",
    "every_screened_idea_has_idea_gap_and_evidence_refs",
    "every_screened_idea_not_an_experiment_plan",
    "every_screened_idea_not_a_validated_claim",
    "gap_map_json_exists_and_parseable",
    "landscape_json_exists_and_parseable",
    "output_json_parseable",
    "schema_version_is_experiment_matrix_v1",
    "every_experiment_candidate_references_source_idea_id",
    "every_experiment_candidate_references_screening_basis",
    "every_experiment_candidate_preserves_gap_ids_and_evidence_ids",
    "not_a_protocol_is_true",
    "not_a_validated_claim_is_true",
    "requires_expert_review_is_true",
    "markdown_contains_evidence_references",
    "markdown_excludes_protocol_recipe_safety_manuscript_final_claim_sections",
    "experiment_matrix_does_not_claim_feasibility_performance_or_validation",
]


@dataclass
class ExperimentScreeningBasis:
    novelty_status: str
    feasibility_status: str
    risk_status: str
    required_follow_up: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.novelty_status:
            raise ValueError("experiment_screening_basis_requires_novelty_status")
        if not self.feasibility_status:
            raise ValueError("experiment_screening_basis_requires_feasibility_status")
        if not self.risk_status:
            raise ValueError("experiment_screening_basis_requires_risk_status")
        self.required_follow_up = _dedupe(self.required_follow_up)
        self.limitations = _dedupe(self.limitations)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentScreeningBasis":
        return cls(
            novelty_status=data.get("novelty_status", ""),
            feasibility_status=data.get("feasibility_status", ""),
            risk_status=data.get("risk_status", ""),
            required_follow_up=list(data.get("required_follow_up") or []),
            limitations=list(data.get("limitations") or []),
        )


@dataclass
class DesignVariable:
    variable_id: str
    name: str
    role: str
    allowed_level_description: str
    rationale: str
    evidence_refs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    not_a_stepwise_instruction: bool = True

    def __post_init__(self) -> None:
        if not self.variable_id:
            raise ValueError("design_variable_requires_variable_id")
        if not self.name:
            raise ValueError("design_variable_requires_name")
        if self.role not in EXPERIMENT_MATRIX_VARIABLE_ROLES:
            raise ValueError(f"invalid_design_variable_role:{self.role}")
        if not self.allowed_level_description:
            raise ValueError("design_variable_requires_allowed_level_description")
        if self.not_a_stepwise_instruction is not True:
            raise ValueError("design_variable_must_not_be_stepwise_instruction")
        self.evidence_refs = _dedupe(self.evidence_refs)
        self.constraints = _dedupe(self.constraints)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DesignVariable":
        return cls(
            variable_id=data.get("variable_id", ""),
            name=data.get("name", ""),
            role=data.get("role", ""),
            allowed_level_description=data.get("allowed_level_description", ""),
            rationale=data.get("rationale", ""),
            evidence_refs=list(data.get("evidence_refs") or []),
            constraints=list(data.get("constraints") or []),
            not_a_stepwise_instruction=bool(data.get("not_a_stepwise_instruction", True)),
        )


@dataclass
class CharacterizationTarget:
    target_id: str
    target: str
    purpose: str
    linked_gap_ids: list[str] = field(default_factory=list)
    linked_evidence_ids: list[str] = field(default_factory=list)
    expected_evidence_type: str = ""
    limitations: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("characterization_target_requires_target_id")
        if not self.target:
            raise ValueError("characterization_target_requires_target")
        if self.purpose not in EXPERIMENT_MATRIX_CHARACTERIZATION_PURPOSES:
            raise ValueError(f"invalid_characterization_purpose:{self.purpose}")
        self.linked_gap_ids = _dedupe(self.linked_gap_ids)
        self.linked_evidence_ids = _dedupe(self.linked_evidence_ids)
        self.limitations = _dedupe(self.limitations)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterizationTarget":
        return cls(
            target_id=data.get("target_id", ""),
            target=data.get("target", ""),
            purpose=data.get("purpose", ""),
            linked_gap_ids=list(data.get("linked_gap_ids") or []),
            linked_evidence_ids=list(data.get("linked_evidence_ids") or []),
            expected_evidence_type=data.get("expected_evidence_type", ""),
            limitations=list(data.get("limitations") or []),
        )


@dataclass
class ExperimentCandidate:
    experiment_id: str
    source_idea_id: str
    screened_idea_ref: str
    objective: str
    hypothesis_under_test: str
    gap_ids: list[str]
    evidence_ids: list[str]
    screening_basis: ExperimentScreeningBasis | dict[str, Any]
    design_variables: list[DesignVariable | dict[str, Any]] = field(default_factory=list)
    control_groups: list[str] = field(default_factory=list)
    comparison_groups: list[str] = field(default_factory=list)
    characterization_targets: list[CharacterizationTarget | dict[str, Any]] = field(default_factory=list)
    expected_observations: list[str] = field(default_factory=list)
    decision_criteria: list[str] = field(default_factory=list)
    data_to_record: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    not_a_protocol: bool = True
    not_a_validated_claim: bool = True
    requires_expert_review: bool = True
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_candidate_requires_experiment_id")
        if not self.source_idea_id:
            raise ValueError("experiment_candidate_requires_source_idea_id")
        if not self.screened_idea_ref:
            raise ValueError("experiment_candidate_requires_screened_idea_ref")
        self.gap_ids = _dedupe(self.gap_ids)
        self.evidence_ids = _dedupe(self.evidence_ids)
        if not self.gap_ids:
            raise ValueError("experiment_candidate_requires_gap_ids")
        if not self.evidence_ids:
            raise ValueError("experiment_candidate_requires_evidence_ids")
        if self.not_a_protocol is not True:
            raise ValueError("experiment_candidate_must_not_be_protocol")
        if self.not_a_validated_claim is not True:
            raise ValueError("experiment_candidate_must_not_be_validated_claim")
        if self.requires_expert_review is not True:
            raise ValueError("experiment_candidate_requires_expert_review")
        self.screening_basis = (
            self.screening_basis
            if isinstance(self.screening_basis, ExperimentScreeningBasis)
            else ExperimentScreeningBasis.from_dict(self.screening_basis)
        )
        self.design_variables = [
            item if isinstance(item, DesignVariable) else DesignVariable.from_dict(item)
            for item in self.design_variables
        ]
        self.characterization_targets = [
            item if isinstance(item, CharacterizationTarget) else CharacterizationTarget.from_dict(item)
            for item in self.characterization_targets
        ]
        self.control_groups = _dedupe(self.control_groups)
        self.comparison_groups = _dedupe(self.comparison_groups)
        self.expected_observations = _dedupe(self.expected_observations)
        self.decision_criteria = _dedupe(self.decision_criteria)
        self.data_to_record = _dedupe(self.data_to_record)
        self.constraints = _dedupe(self.constraints)
        self.risk_notes = _dedupe(self.risk_notes)
        self.warnings = _dedupe(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["screening_basis"] = self.screening_basis.as_dict()
        data["design_variables"] = [item.as_dict() for item in self.design_variables]
        data["characterization_targets"] = [item.as_dict() for item in self.characterization_targets]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentCandidate":
        return cls(
            experiment_id=data.get("experiment_id", ""),
            source_idea_id=data.get("source_idea_id", ""),
            screened_idea_ref=data.get("screened_idea_ref", ""),
            objective=data.get("objective", ""),
            hypothesis_under_test=data.get("hypothesis_under_test", ""),
            gap_ids=list(data.get("gap_ids") or []),
            evidence_ids=list(data.get("evidence_ids") or []),
            screening_basis=dict(data.get("screening_basis") or {}),
            design_variables=list(data.get("design_variables") or []),
            control_groups=list(data.get("control_groups") or []),
            comparison_groups=list(data.get("comparison_groups") or []),
            characterization_targets=list(data.get("characterization_targets") or []),
            expected_observations=list(data.get("expected_observations") or []),
            decision_criteria=list(data.get("decision_criteria") or []),
            data_to_record=list(data.get("data_to_record") or []),
            constraints=list(data.get("constraints") or []),
            risk_notes=list(data.get("risk_notes") or []),
            not_a_protocol=bool(data.get("not_a_protocol", True)),
            not_a_validated_claim=bool(data.get("not_a_validated_claim", True)),
            requires_expert_review=bool(data.get("requires_expert_review", True)),
            warnings=list(data.get("warnings") or []),
        )


@dataclass
class ExperimentMatrixArtifact:
    task_id: str
    topic: str
    experiment_matrix_id: str
    input_artifacts: list[str]
    screening_id: str
    idea_set_id: str
    gap_map_id: str
    landscape_id: str
    evidence_ids: list[str]
    source_paper_ids: list[str]
    experiment_candidates: list[ExperimentCandidate | dict[str, Any]]
    matrix_scope: dict[str, Any] = field(default_factory=dict)
    design_policy: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    schema_version: str = EXPERIMENT_MATRIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXPERIMENT_MATRIX_SCHEMA_VERSION:
            raise ValueError(f"invalid_experiment_matrix_schema_version:{self.schema_version}")
        if not self.experiment_matrix_id:
            raise ValueError("experiment_matrix_requires_id")
        if not self.screening_id:
            raise ValueError("experiment_matrix_requires_screening_id")
        if not self.idea_set_id:
            raise ValueError("experiment_matrix_requires_idea_set_id")
        if not self.gap_map_id:
            raise ValueError("experiment_matrix_requires_gap_map_id")
        if not self.landscape_id:
            raise ValueError("experiment_matrix_requires_landscape_id")
        self.input_artifacts = _dedupe(self.input_artifacts)
        self.evidence_ids = _dedupe(self.evidence_ids)
        self.source_paper_ids = _dedupe(self.source_paper_ids)
        self.experiment_candidates = [
            item if isinstance(item, ExperimentCandidate) else ExperimentCandidate.from_dict(item)
            for item in self.experiment_candidates
        ]
        self.limitations = _dedupe(self.limitations)
        self.warnings = _dedupe(self.warnings)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["experiment_candidates"] = [item.as_dict() for item in self.experiment_candidates]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentMatrixArtifact":
        return cls(
            task_id=data.get("task_id", ""),
            topic=data.get("topic", ""),
            experiment_matrix_id=data.get("experiment_matrix_id", ""),
            input_artifacts=list(data.get("input_artifacts") or []),
            screening_id=data.get("screening_id", ""),
            idea_set_id=data.get("idea_set_id", ""),
            gap_map_id=data.get("gap_map_id", ""),
            landscape_id=data.get("landscape_id", ""),
            evidence_ids=list(data.get("evidence_ids") or []),
            source_paper_ids=list(data.get("source_paper_ids") or []),
            experiment_candidates=list(data.get("experiment_candidates") or []),
            matrix_scope=dict(data.get("matrix_scope") or {}),
            design_policy=dict(data.get("design_policy") or {}),
            limitations=list(data.get("limitations") or []),
            warnings=list(data.get("warnings") or []),
            created_at=float(data.get("created_at", time.time())),
            schema_version=data.get("schema_version", EXPERIMENT_MATRIX_SCHEMA_VERSION),
        )


def validate_experiment_matrix_input_artifacts(input_artifacts: list[str]) -> list[str]:
    errors: list[str] = []
    artifact_set = set(input_artifacts or [])
    for artifact_path in input_artifacts:
        if artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_experiment_matrix")
        elif artifact_path.startswith(("raw_chunks/", "chunks/")):
            errors.append(f"raw_chunks_not_allowed_for_experiment_matrix:{artifact_path}")
        elif artifact_path in {"evidence/evidence_card_seeds.json", "evidence/evidence_cards.initial.json"}:
            errors.append(f"unenriched_evidence_not_allowed_for_experiment_matrix:{artifact_path}")
        elif artifact_path.endswith(".md") and artifact_path not in EXPERIMENT_MATRIX_OPTIONAL_INPUT_ARTIFACTS:
            errors.append(f"raw_markdown_not_allowed_for_experiment_matrix:{artifact_path}")

    if "screening/idea_screening_results.json" not in artifact_set:
        errors.append("missing_screening_results_artifact")

    basis_requirements = {
        "screening/idea_screening_results.json",
        "ideas/candidate_ideas.json",
        "gaps/gap_map.json",
        "landscape/literature_landscape.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    }
    if not basis_requirements.issubset(artifact_set):
        errors.append("experiment_matrix_requires_gap_and_evidence_basis")

    missing = [
        path
        for path in EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS
        if path not in artifact_set and path != "screening/idea_screening_results.json"
    ]
    errors.extend(f"missing_experiment_matrix_input:{path}" for path in missing)
    return _dedupe(errors)


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "EXPERIMENT_MATRIX_ALLOWED_MARKDOWN_SECTIONS",
    "EXPERIMENT_MATRIX_CHARACTERIZATION_PURPOSES",
    "EXPERIMENT_MATRIX_FORBIDDEN_INPUT_ARTIFACTS",
    "EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS",
    "EXPERIMENT_MATRIX_OPTIONAL_INPUT_ARTIFACTS",
    "EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS",
    "EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS",
    "EXPERIMENT_MATRIX_SCHEMA_VERSION",
    "EXPERIMENT_MATRIX_VALIDATION_EXPECTATIONS",
    "EXPERIMENT_MATRIX_VARIABLE_ROLES",
    "CharacterizationTarget",
    "DesignVariable",
    "ExperimentCandidate",
    "ExperimentMatrixArtifact",
    "ExperimentScreeningBasis",
    "validate_experiment_matrix_input_artifacts",
]
