"""Static research skill registry contracts.

A3 declares which research skills a future controller may request. The registry
stores metadata only; it does not execute skills or import research runtimes.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class SkillExecutionMode(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    HYBRID = "hybrid"
    EXTERNAL = "external"


class SkillDatabaseAccess(str, Enum):
    NONE = "none"
    READ_ONLY = "read_only"
    FORBIDDEN = "forbidden"


class SkillStatus(str, Enum):
    AVAILABLE = "available"
    STUB = "stub"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"


class SkillExecutionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    VALIDATION_FAILED = "validation_failed"


@dataclass
class ArtifactRequirement:
    artifact_type: str
    path_hint: str = ""
    required: bool = True
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRequirement":
        return cls(
            artifact_type=data["artifact_type"],
            path_hint=data.get("path_hint", ""),
            required=bool(data.get("required", True)),
            description=data.get("description", ""),
        )


@dataclass
class SkillContract:
    name: str
    purpose: str
    status: SkillStatus | str = SkillStatus.AVAILABLE
    execution_mode: SkillExecutionMode | str = SkillExecutionMode.DETERMINISTIC
    database_access: SkillDatabaseAccess | str = SkillDatabaseAccess.NONE
    input_artifacts: list[ArtifactRequirement | dict[str, Any]] = field(default_factory=list)
    output_artifacts: list[ArtifactRequirement | dict[str, Any]] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    produced_artifacts: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    based_on_modules: list[str] = field(default_factory=list)
    writes_artifacts: bool = True
    allows_raw_chunks: bool = False
    requires_evidence_cards: bool = False
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.status = _coerce_enum(SkillStatus, self.status, "status")
        self.execution_mode = _coerce_enum(SkillExecutionMode, self.execution_mode, "execution_mode")
        self.database_access = _coerce_enum(SkillDatabaseAccess, self.database_access, "database_access")
        self.input_artifacts = [_artifact_requirement(item) for item in self.input_artifacts]
        self.output_artifacts = [_artifact_requirement(item) for item in self.output_artifacts]
        self.required_artifacts = list(self.required_artifacts or [])
        self.produced_artifacts = list(self.produced_artifacts or [])
        self.validation_rules = list(self.validation_rules or [])
        self.failure_modes = list(self.failure_modes or [])
        self.based_on_modules = list(self.based_on_modules or [])
        self.notes = list(self.notes or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "status": self.status.value,
            "execution_mode": self.execution_mode.value,
            "database_access": self.database_access.value,
            "input_artifacts": [artifact.as_dict() for artifact in self.input_artifacts],
            "output_artifacts": [artifact.as_dict() for artifact in self.output_artifacts],
            "required_artifacts": list(self.required_artifacts),
            "produced_artifacts": list(self.produced_artifacts),
            "validation_rules": list(self.validation_rules),
            "failure_modes": list(self.failure_modes),
            "based_on_modules": list(self.based_on_modules),
            "writes_artifacts": self.writes_artifacts,
            "allows_raw_chunks": self.allows_raw_chunks,
            "requires_evidence_cards": self.requires_evidence_cards,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillContract":
        return cls(
            name=data["name"],
            purpose=data["purpose"],
            status=data.get("status", SkillStatus.AVAILABLE.value),
            execution_mode=data.get("execution_mode", SkillExecutionMode.DETERMINISTIC.value),
            database_access=data.get("database_access", SkillDatabaseAccess.NONE.value),
            input_artifacts=list(data.get("input_artifacts", [])),
            output_artifacts=list(data.get("output_artifacts", [])),
            required_artifacts=list(data.get("required_artifacts", [])),
            produced_artifacts=list(data.get("produced_artifacts", [])),
            validation_rules=list(data.get("validation_rules", [])),
            failure_modes=list(data.get("failure_modes", [])),
            based_on_modules=list(data.get("based_on_modules", [])),
            writes_artifacts=bool(data.get("writes_artifacts", True)),
            allows_raw_chunks=bool(data.get("allows_raw_chunks", False)),
            requires_evidence_cards=bool(data.get("requires_evidence_cards", False)),
            notes=list(data.get("notes", [])),
        )


@dataclass
class SkillExecutionInput:
    task_id: str
    workspace_root: str
    skill_name: str
    input_artifacts: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    requested_by: str = "controller"

    def __post_init__(self) -> None:
        self.input_artifacts = list(self.input_artifacts or [])
        self.parameters = dict(self.parameters or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workspace_root": self.workspace_root,
            "skill_name": self.skill_name,
            "input_artifacts": list(self.input_artifacts),
            "parameters": dict(self.parameters),
            "requested_by": self.requested_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillExecutionInput":
        return cls(
            task_id=data["task_id"],
            workspace_root=data["workspace_root"],
            skill_name=data["skill_name"],
            input_artifacts=list(data.get("input_artifacts", [])),
            parameters=dict(data.get("parameters", {})),
            requested_by=data.get("requested_by", "controller"),
        )


@dataclass
class SkillExecutionResult:
    task_id: str
    skill_name: str
    status: SkillExecutionStatus | str
    input_artifacts: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = _coerce_enum(SkillExecutionStatus, self.status, "status")
        self.input_artifacts = list(self.input_artifacts or [])
        self.output_artifacts = list(self.output_artifacts or [])
        self.warnings = list(self.warnings or [])
        self.errors = list(self.errors or [])
        self.metadata = dict(self.metadata or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "skill_name": self.skill_name,
            "status": self.status.value,
            "input_artifacts": list(self.input_artifacts),
            "output_artifacts": list(self.output_artifacts),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillExecutionResult":
        return cls(
            task_id=data["task_id"],
            skill_name=data["skill_name"],
            status=data["status"],
            input_artifacts=list(data.get("input_artifacts", [])),
            output_artifacts=list(data.get("output_artifacts", [])),
            warnings=list(data.get("warnings", [])),
            errors=list(data.get("errors", [])),
            metadata=dict(data.get("metadata", {})),
        )


class SkillRegistry:
    """Registry of approved research skill contracts."""

    def __init__(self, skills: list[SkillContract | dict[str, Any]] | None = None):
        self._skills: dict[str, SkillContract] = {}
        for skill in skills or []:
            self.register_skill(skill)

    def register_skill(self, skill: SkillContract | dict[str, Any]) -> SkillContract:
        contract = skill if isinstance(skill, SkillContract) else SkillContract.from_dict(skill)
        if contract.name in self._skills:
            raise ValueError(f"duplicate skill name: {contract.name!r}")
        self._skills[contract.name] = contract
        return contract

    def get_skill(self, name: str) -> SkillContract:
        if name not in self._skills:
            raise KeyError(f"unregistered skill: {name!r}")
        return self._skills[name]

    def list_skills(self) -> list[SkillContract]:
        return [self._skills[name] for name in sorted(self._skills)]

    def list_available_skills(self) -> list[SkillContract]:
        return [skill for skill in self.list_skills() if skill.status == SkillStatus.AVAILABLE]

    def list_stub_skills(self) -> list[SkillContract]:
        return [skill for skill in self.list_skills() if skill.status == SkillStatus.STUB]

    def validate_skill_request_name(self, name: str) -> str:
        self.get_skill(name)
        return name

    def is_registered(self, name: str) -> bool:
        return name in self._skills


def build_default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    for skill in _default_available_skills() + _default_stub_skills():
        registry.register_skill(skill)
    return registry


def _default_available_skills() -> list[SkillContract]:
    return [
        _skill(
            name="retrieve_sources",
            purpose="Find topic-scoped source candidates from the local literature library.",
            based_on_modules=["M4"],
            database_access=SkillDatabaseAccess.READ_ONLY,
            allows_raw_chunks=True,
            produced_type="source_candidates",
            produced_path="retrieval/source_candidates.json",
            validation_rules=["source_candidate_packet_has_topic", "coverage_warnings_recorded"],
            failure_modes=["retrieval_timeout", "insufficient_source_candidates"],
            notes=["Contract only; execution is introduced in A4."],
        ),
        _skill(
            name="create_evidence_seeds",
            purpose="Normalize retrieved source candidates into EvidenceCardSeed artifacts.",
            based_on_modules=["M1", "M4"],
            allows_raw_chunks=True,
            input_type="source_candidates",
            input_path="retrieval/source_candidates.json",
            produced_type="evidence_card_seeds",
            produced_path="evidence/evidence_card_seeds.json",
            validation_rules=["seed_provenance_present", "seed_asset_type_supported"],
            failure_modes=["missing_source_candidate_fields", "seed_validation_failed"],
        ),
        _skill(
            name="extract_evidence_cards",
            purpose="Create initial Evidence Cards from EvidenceCardSeed artifacts.",
            based_on_modules=["M5"],
            input_type="evidence_card_seeds",
            input_path="evidence/evidence_card_seeds.json",
            produced_type="evidence_cards",
            produced_path="evidence/evidence_cards.json",
            validation_rules=["initial_cards_validate_against_schema", "unsupported_parts_recorded"],
            failure_modes=["missing_seed_text", "initial_extraction_failed"],
        ),
        _skill(
            name="enrich_evidence_cards",
            purpose="Add role/entity/relation enrichment to Evidence Cards.",
            based_on_modules=["M6"],
            requires_evidence_cards=True,
            input_type="evidence_cards",
            input_path="evidence/evidence_cards.json",
            produced_type="enriched_evidence_cards",
            produced_path="evidence/evidence_cards.json",
            validation_rules=["exactly_one_primary_role", "relations_are_valid"],
            failure_modes=["role_coverage_missing", "enrichment_validation_failed"],
        ),
        _skill(
            name="rank_evidence",
            purpose="Rank and diversify enriched Evidence Cards.",
            based_on_modules=["M7"],
            requires_evidence_cards=True,
            input_type="evidence_cards",
            input_path="evidence/evidence_cards.json",
            produced_type="evidence_selection",
            produced_path="ranked_evidence/evidence_selection.json",
            validation_rules=["selection_has_score_components", "diversity_warnings_recorded"],
            failure_modes=["empty_evidence_cards", "selection_budget_unfilled"],
        ),
        _skill(
            name="build_minimal_topic_to_evidence_report",
            purpose="Build minimal topic-to-evidence report from Evidence Cards or selected evidence.",
            based_on_modules=["M6.5"],
            requires_evidence_cards=True,
            input_type="evidence_cards",
            input_path="evidence/evidence_cards.json",
            produced_type="minimal_topic_to_evidence_report",
            produced_path="reports/minimal_topic_to_evidence_report.md",
            validation_rules=["every_claim_has_evidence_reference", "coverage_warnings_listed"],
            failure_modes=["missing_evidence_cards", "report_validation_failed"],
        ),
        _skill(
            name="validate_evidence_cards",
            purpose="Validate Evidence Card schema, provenance, role, snippet, and source fields.",
            based_on_modules=["M1", "M6"],
            requires_evidence_cards=True,
            writes_artifacts=True,
            input_type="evidence_cards",
            input_path="evidence/evidence_cards.json",
            produced_type="validation_result",
            produced_path="audit/evidence_card_validation.json",
            validation_rules=["validation_result_is_structured", "errors_are_traceable_to_card_ids"],
            failure_modes=["invalid_evidence_card_schema", "missing_provenance"],
        ),
        _skill(
            name="validate_artifact_manifest",
            purpose="Validate workspace artifact manifest completeness and status.",
            based_on_modules=["A1", "future A5"],
            input_type="artifact_manifest",
            input_path="audit/artifact_manifest.json",
            produced_type="artifact_manifest_validation",
            produced_path="audit/artifact_manifest_validation.json",
            validation_rules=["required_artifacts_declared", "artifact_paths_are_workspace_relative"],
            failure_modes=["missing_artifact_manifest", "artifact_manifest_incomplete"],
        ),
    ]


def _default_stub_skills() -> list[SkillContract]:
    return [
        _landscape_stub(),
        _gap_mapping_stub(),
        _idea_generation_stub(),
        _screening_stub(),
        _stub(
            "draft_evidence_grounded_report",
            "Draft an evidence-grounded research report.",
            input_type="evidence_cards",
            produced_type="report",
            produced_path="reports/evidence_grounded_report.md",
        ),
        _experiment_matrix_stub(),
        _claim_ledger_stub(),
        _manuscript_drafting_stub(),
    ]


def _idea_generation_stub() -> SkillContract:
    required_artifacts = [
        "gaps/gap_map.json",
        "gaps/gap_coverage_diagnostics.json",
        "landscape/literature_landscape.json",
        "landscape/landscape_coverage_diagnostics.json",
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    ]
    produced_artifacts = [
        "ideas/candidate_ideas.json",
        "ideas/candidate_ideas.md",
        "ideas/idea_generation_diagnostics.json",
    ]
    validation_rules = [
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
        "raw_retrieval_candidates_not_allowed_for_idea_generation",
    ]
    return SkillContract(
        name="generate_candidate_ideas",
        purpose=(
            "Generate evidence-constrained candidate research ideas from validated gap maps, "
            "landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics."
        ),
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="gap_map_json",
                path_hint="gaps/gap_map.json",
                required=True,
                description="Structured gap map artifact using schema_version gap_map_v1.",
            ),
            ArtifactRequirement(
                artifact_type="gap_coverage_diagnostics",
                path_hint="gaps/gap_coverage_diagnostics.json",
                required=True,
                description="Diagnostics preserving the gap mapping basis and limitations.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_json",
                path_hint="landscape/literature_landscape.json",
                required=True,
                description="Structured literature landscape used to ground idea context.",
            ),
            ArtifactRequirement(
                artifact_type="landscape_coverage_diagnostics",
                path_hint="landscape/landscape_coverage_diagnostics.json",
                required=True,
                description="Landscape coverage diagnostics used as idea constraints.",
            ),
            ArtifactRequirement(
                artifact_type="enriched_evidence_cards",
                path_hint="evidence/evidence_cards.enriched.json",
                required=True,
                description="Validated enriched Evidence Cards; seeds and initial cards are not allowed.",
            ),
            ArtifactRequirement(
                artifact_type="evidence_selection",
                path_hint="ranked_evidence/evidence_selection.json",
                required=True,
                description="Selected evidence used to keep candidate ideas evidence-grounded.",
            ),
            ArtifactRequirement(
                artifact_type="ranking_coverage_diagnostics",
                path_hint="ranked_evidence/coverage_diagnostics.json",
                required=True,
                description="Ranking coverage diagnostics used as idea constraints.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_markdown",
                path_hint="gaps/gap_map.md",
                required=False,
                description="Optional readable gap map companion; it cannot replace gap map JSON.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_markdown",
                path_hint="landscape/literature_landscape.md",
                required=False,
                description="Optional readable landscape companion; it cannot replace landscape JSON.",
            ),
            ArtifactRequirement(
                artifact_type="minimal_topic_to_evidence_report",
                path_hint="reports/minimal_topic_to_evidence_report.json",
                required=False,
                description="Optional evidence-grounded summary; it cannot replace source artifacts.",
            ),
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="candidate_ideas_json",
                path_hint="ideas/candidate_ideas.json",
                required=True,
                description="Structured candidate idea set using schema_version candidate_ideas_v1.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_markdown",
                path_hint="ideas/candidate_ideas.md",
                required=True,
                description="Human-readable candidate ideas with Evidence References and no screening sections.",
            ),
            ArtifactRequirement(
                artifact_type="idea_generation_diagnostics",
                path_hint="ideas/idea_generation_diagnostics.json",
                required=True,
                description="Diagnostics preserving input coverage, constraints, and limitations.",
            ),
        ],
        required_artifacts=required_artifacts,
        produced_artifacts=produced_artifacts,
        validation_rules=validation_rules,
        failure_modes=[
            "skill_not_implemented",
            "missing_gap_map_artifact",
            "idea_generation_requires_evidence_references",
            "candidate_idea_requires_gap_basis",
            "candidate_idea_requires_evidence_basis",
            "raw_retrieval_candidates_not_allowed_for_idea_generation",
            "unsupported_candidate_idea_claim",
        ],
        based_on_modules=["P2-M10.2"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=[
            "P2-M10.2 deterministic stub-safe wrapper is available.",
            "Candidate ideas must remain unscreened and must not claim novelty, feasibility, or validation.",
            "Idea outputs must not include novelty screening, feasibility screening, risk screening, experiment plans, or manuscript drafts.",
        ],
    )


def _experiment_matrix_stub() -> SkillContract:
    required_artifacts = [
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
    produced_artifacts = [
        "experiments/experiment_matrix.json",
        "experiments/experiment_matrix.md",
        "experiments/experiment_matrix_diagnostics.json",
    ]
    validation_rules = [
        "input_artifacts_exist",
        "screening_results_json_exists_and_parseable",
        "screening_schema_version_is_idea_screening_v2",
        "candidate_ideas_json_exists_and_parseable",
        "candidate_ideas_schema_version_is_candidate_ideas_v1",
        "raw_retrieval_candidates_not_allowed_for_experiment_matrix",
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
    return SkillContract(
        name="create_experiment_matrix",
        purpose=(
            "Define structured experiment matrix boundaries from screening results, candidate ideas, "
            "gap maps, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics."
        ),
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="idea_screening_results_json",
                path_hint="screening/idea_screening_results.json",
                required=True,
                description="Structured P2-M11 screening result using schema_version idea_screening_v2.",
            ),
            ArtifactRequirement(
                artifact_type="screening_diagnostics",
                path_hint="screening/screening_diagnostics.json",
                required=True,
                description="Diagnostics preserving screening limitations and follow-up requirements.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_json",
                path_hint="ideas/candidate_ideas.json",
                required=True,
                description="Structured P2-M10 candidate ideas using schema_version candidate_ideas_v1.",
            ),
            ArtifactRequirement(
                artifact_type="idea_generation_diagnostics",
                path_hint="ideas/idea_generation_diagnostics.json",
                required=True,
                description="Diagnostics preserving idea generation constraints.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_json",
                path_hint="gaps/gap_map.json",
                required=True,
                description="Structured gap map used to preserve gap basis.",
            ),
            ArtifactRequirement(
                artifact_type="gap_coverage_diagnostics",
                path_hint="gaps/gap_coverage_diagnostics.json",
                required=True,
                description="Gap diagnostics used as matrix limitations.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_json",
                path_hint="landscape/literature_landscape.json",
                required=True,
                description="Structured landscape artifact used to preserve landscape basis.",
            ),
            ArtifactRequirement(
                artifact_type="landscape_coverage_diagnostics",
                path_hint="landscape/landscape_coverage_diagnostics.json",
                required=True,
                description="Landscape diagnostics used as matrix limitations.",
            ),
            ArtifactRequirement(
                artifact_type="enriched_evidence_cards",
                path_hint="evidence/evidence_cards.enriched.json",
                required=True,
                description="Validated enriched Evidence Cards; seeds and initial cards are not allowed.",
            ),
            ArtifactRequirement(
                artifact_type="evidence_selection",
                path_hint="ranked_evidence/evidence_selection.json",
                required=True,
                description="Selected evidence used to keep matrix candidates evidence-grounded.",
            ),
            ArtifactRequirement(
                artifact_type="ranking_coverage_diagnostics",
                path_hint="ranked_evidence/coverage_diagnostics.json",
                required=True,
                description="Ranking diagnostics used as matrix limitations.",
            ),
            ArtifactRequirement(
                artifact_type="idea_screening_results_markdown",
                path_hint="screening/idea_screening_results.md",
                required=False,
                description="Optional readable screening companion; it cannot replace screening JSON.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_markdown",
                path_hint="ideas/candidate_ideas.md",
                required=False,
                description="Optional readable candidate idea companion; it cannot replace candidate ideas JSON.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_markdown",
                path_hint="gaps/gap_map.md",
                required=False,
                description="Optional readable gap map companion; it cannot replace gap map JSON.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_markdown",
                path_hint="landscape/literature_landscape.md",
                required=False,
                description="Optional readable landscape companion; it cannot replace landscape JSON.",
            ),
            ArtifactRequirement(
                artifact_type="minimal_topic_to_evidence_report",
                path_hint="reports/minimal_topic_to_evidence_report.json",
                required=False,
                description="Optional evidence-grounded summary; it cannot replace source artifacts.",
            ),
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="experiment_matrix_json",
                path_hint="experiments/experiment_matrix.json",
                required=True,
                description="Structured experiment matrix artifact using schema_version experiment_matrix_v1.",
            ),
            ArtifactRequirement(
                artifact_type="experiment_matrix_markdown",
                path_hint="experiments/experiment_matrix.md",
                required=True,
                description="Human-readable matrix with Evidence References and no protocol sections.",
            ),
            ArtifactRequirement(
                artifact_type="experiment_matrix_diagnostics",
                path_hint="experiments/experiment_matrix_diagnostics.json",
                required=True,
                description="Diagnostics preserving matrix scope, limitations, and review requirements.",
            ),
        ],
        required_artifacts=required_artifacts,
        produced_artifacts=produced_artifacts,
        validation_rules=validation_rules,
        failure_modes=[
            "skill_not_implemented",
            "missing_screening_results_artifact",
            "experiment_matrix_requires_screened_ideas",
            "experiment_matrix_requires_gap_and_evidence_basis",
            "experiment_matrix_requires_conservative_screening_status",
            "raw_retrieval_candidates_not_allowed_for_experiment_matrix",
            "unsupported_experiment_matrix_claim",
        ],
        based_on_modules=["P2-M12.1", "P2-M12.2"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=[
            "P2-M12.2 deterministic stub-safe wrapper is available.",
            "Experiment matrix outputs must not include protocols, recipes, safety procedures, manuscripts, or final claims.",
            "Screening results are preliminary and must not be treated as final validated claims.",
        ],
    )


def _claim_ledger_stub() -> SkillContract:
    required_artifacts = [
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
    produced_artifacts = [
        "claims/claim_ledger.json",
        "claims/claim_ledger.md",
        "claims/claim_ledger_diagnostics.json",
    ]
    validation_rules = [
        "input_artifacts_exist",
        "experiment_matrix_json_exists_and_parseable",
        "experiment_matrix_schema_version_is_experiment_matrix_v1",
        "screening_results_json_exists_and_parseable",
        "screening_schema_version_is_idea_screening_v2",
        "candidate_ideas_json_exists_and_parseable",
        "candidate_ideas_schema_version_is_candidate_ideas_v1",
        "raw_retrieval_candidates_not_allowed_for_claim_ledger",
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
    return SkillContract(
        name="build_claim_ledger",
        purpose=(
            "Define a traceable claim ledger boundary from experiment matrix artifacts, screening results, "
            "candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, selected evidence, "
            "and diagnostics."
        ),
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="experiment_matrix_json",
                path_hint="experiments/experiment_matrix.json",
                required=True,
                description="Structured P2-M12 experiment matrix using schema_version experiment_matrix_v1.",
            ),
            ArtifactRequirement(
                artifact_type="experiment_matrix_diagnostics",
                path_hint="experiments/experiment_matrix_diagnostics.json",
                required=True,
                description="Diagnostics preserving experiment matrix limitations and review requirements.",
            ),
            ArtifactRequirement(
                artifact_type="idea_screening_results_json",
                path_hint="screening/idea_screening_results.json",
                required=True,
                description="Structured P2-M11 screening result using schema_version idea_screening_v2.",
            ),
            ArtifactRequirement(
                artifact_type="screening_diagnostics",
                path_hint="screening/screening_diagnostics.json",
                required=True,
                description="Diagnostics preserving screening limitations and follow-up requirements.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_json",
                path_hint="ideas/candidate_ideas.json",
                required=True,
                description="Structured P2-M10 candidate ideas using schema_version candidate_ideas_v1.",
            ),
            ArtifactRequirement(
                artifact_type="idea_generation_diagnostics",
                path_hint="ideas/idea_generation_diagnostics.json",
                required=True,
                description="Diagnostics preserving idea generation constraints.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_json",
                path_hint="gaps/gap_map.json",
                required=True,
                description="Structured gap map used to preserve gap basis.",
            ),
            ArtifactRequirement(
                artifact_type="gap_coverage_diagnostics",
                path_hint="gaps/gap_coverage_diagnostics.json",
                required=True,
                description="Gap diagnostics used as claim ledger limitations.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_json",
                path_hint="landscape/literature_landscape.json",
                required=True,
                description="Structured landscape artifact used to preserve landscape basis.",
            ),
            ArtifactRequirement(
                artifact_type="landscape_coverage_diagnostics",
                path_hint="landscape/landscape_coverage_diagnostics.json",
                required=True,
                description="Landscape diagnostics used as claim ledger limitations.",
            ),
            ArtifactRequirement(
                artifact_type="enriched_evidence_cards",
                path_hint="evidence/evidence_cards.enriched.json",
                required=True,
                description="Validated enriched Evidence Cards; seeds and initial cards are not allowed.",
            ),
            ArtifactRequirement(
                artifact_type="evidence_selection",
                path_hint="ranked_evidence/evidence_selection.json",
                required=True,
                description="Selected evidence used to keep claim records evidence-grounded.",
            ),
            ArtifactRequirement(
                artifact_type="ranking_coverage_diagnostics",
                path_hint="ranked_evidence/coverage_diagnostics.json",
                required=True,
                description="Ranking diagnostics used as claim ledger limitations.",
            ),
            ArtifactRequirement(
                artifact_type="experiment_matrix_markdown",
                path_hint="experiments/experiment_matrix.md",
                required=False,
                description="Optional readable experiment matrix companion; it cannot replace experiment matrix JSON.",
            ),
            ArtifactRequirement(
                artifact_type="idea_screening_results_markdown",
                path_hint="screening/idea_screening_results.md",
                required=False,
                description="Optional readable screening companion; it cannot replace screening JSON.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_markdown",
                path_hint="ideas/candidate_ideas.md",
                required=False,
                description="Optional readable candidate idea companion; it cannot replace candidate ideas JSON.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_markdown",
                path_hint="gaps/gap_map.md",
                required=False,
                description="Optional readable gap map companion; it cannot replace gap map JSON.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_markdown",
                path_hint="landscape/literature_landscape.md",
                required=False,
                description="Optional readable landscape companion; it cannot replace landscape JSON.",
            ),
            ArtifactRequirement(
                artifact_type="minimal_topic_to_evidence_report",
                path_hint="reports/minimal_topic_to_evidence_report.json",
                required=False,
                description="Optional evidence-grounded summary; it cannot replace source artifacts.",
            ),
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="claim_ledger_json",
                path_hint="claims/claim_ledger.json",
                required=True,
                description="Structured claim ledger artifact using schema_version claim_ledger_v1.",
            ),
            ArtifactRequirement(
                artifact_type="claim_ledger_markdown",
                path_hint="claims/claim_ledger.md",
                required=True,
                description="Human-readable claim ledger with Evidence References and no manuscript sections.",
            ),
            ArtifactRequirement(
                artifact_type="claim_ledger_diagnostics",
                path_hint="claims/claim_ledger_diagnostics.json",
                required=True,
                description="Diagnostics preserving claim scope, limitations, and review requirements.",
            ),
        ],
        required_artifacts=required_artifacts,
        produced_artifacts=produced_artifacts,
        validation_rules=validation_rules,
        failure_modes=[
            "missing_experiment_matrix_artifact",
            "claim_ledger_requires_experiment_matrix",
            "claim_ledger_requires_traceable_evidence_basis",
            "claim_ledger_requires_non_final_claim_status",
            "claim_ledger_rejects_validated_result_claim",
            "raw_retrieval_candidates_not_allowed_for_claim_ledger",
        ],
        based_on_modules=["P2-M13.1", "P2-M13.2"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=[
            "P2-M13.2 deterministic stub-safe wrapper is available.",
            "Experiment matrix entries are planning scaffolds and must not be treated as validated experimental claims.",
            "Claim ledger outputs must not include abstracts, manuscript conclusions, final claims, or experimental result interpretation.",
        ],
    )


def _manuscript_drafting_stub() -> SkillContract:
    required_artifacts = [
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
    produced_artifacts = [
        "drafts/manuscript_section_draft.json",
        "drafts/manuscript_section_draft.md",
        "drafts/manuscript_section_diagnostics.json",
    ]
    validation_rules = [
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
        "raw_retrieval_candidates_not_allowed_for_manuscript_drafting",
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
    return SkillContract(
        name="draft_manuscript_section",
        purpose=(
            "Assemble a bounded manuscript-adjacent draft scaffold from claim ledger artifacts, "
            "experiment matrix artifacts, screening results, candidate ideas, gap maps, landscape artifacts, "
            "enriched Evidence Cards, selected evidence, and diagnostics."
        ),
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="claim_ledger_json",
                path_hint="claims/claim_ledger.json",
                required=True,
                description="Structured P2-M13 claim ledger using schema_version claim_ledger_v1.",
            ),
            ArtifactRequirement(
                artifact_type="claim_ledger_diagnostics",
                path_hint="claims/claim_ledger_diagnostics.json",
                required=True,
                description="Claim ledger diagnostics preserving limitations and review requirements.",
            ),
            ArtifactRequirement(
                artifact_type="experiment_matrix_json",
                path_hint="experiments/experiment_matrix.json",
                required=True,
                description="Structured P2-M12 experiment matrix using schema_version experiment_matrix_v1.",
            ),
            ArtifactRequirement(
                artifact_type="experiment_matrix_diagnostics",
                path_hint="experiments/experiment_matrix_diagnostics.json",
                required=True,
                description="Experiment matrix diagnostics preserving planning limitations.",
            ),
            ArtifactRequirement(
                artifact_type="idea_screening_results_json",
                path_hint="screening/idea_screening_results.json",
                required=True,
                description="Structured P2-M11 screening result using schema_version idea_screening_v2.",
            ),
            ArtifactRequirement(
                artifact_type="screening_diagnostics",
                path_hint="screening/screening_diagnostics.json",
                required=True,
                description="Screening diagnostics preserving preliminary review limitations.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_json",
                path_hint="ideas/candidate_ideas.json",
                required=True,
                description="Structured P2-M10 candidate ideas using schema_version candidate_ideas_v1.",
            ),
            ArtifactRequirement(
                artifact_type="idea_generation_diagnostics",
                path_hint="ideas/idea_generation_diagnostics.json",
                required=True,
                description="Idea generation diagnostics preserving candidate idea constraints.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_json",
                path_hint="gaps/gap_map.json",
                required=True,
                description="Structured gap map used to preserve gap basis.",
            ),
            ArtifactRequirement(
                artifact_type="gap_coverage_diagnostics",
                path_hint="gaps/gap_coverage_diagnostics.json",
                required=True,
                description="Gap diagnostics used as draft limitations.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_json",
                path_hint="landscape/literature_landscape.json",
                required=True,
                description="Structured landscape artifact used to preserve landscape basis.",
            ),
            ArtifactRequirement(
                artifact_type="landscape_coverage_diagnostics",
                path_hint="landscape/landscape_coverage_diagnostics.json",
                required=True,
                description="Landscape diagnostics used as draft limitations.",
            ),
            ArtifactRequirement(
                artifact_type="enriched_evidence_cards",
                path_hint="evidence/evidence_cards.enriched.json",
                required=True,
                description="Validated enriched Evidence Cards; seeds and initial cards are not allowed.",
            ),
            ArtifactRequirement(
                artifact_type="evidence_selection",
                path_hint="ranked_evidence/evidence_selection.json",
                required=True,
                description="Selected evidence used to keep draft blocks evidence-grounded.",
            ),
            ArtifactRequirement(
                artifact_type="ranking_coverage_diagnostics",
                path_hint="ranked_evidence/coverage_diagnostics.json",
                required=True,
                description="Ranking diagnostics used as draft limitations.",
            ),
            ArtifactRequirement(
                artifact_type="claim_ledger_markdown",
                path_hint="claims/claim_ledger.md",
                required=False,
                description="Optional readable claim ledger companion; it cannot replace claim ledger JSON.",
            ),
            ArtifactRequirement(
                artifact_type="experiment_matrix_markdown",
                path_hint="experiments/experiment_matrix.md",
                required=False,
                description="Optional readable experiment matrix companion; it cannot replace experiment matrix JSON.",
            ),
            ArtifactRequirement(
                artifact_type="idea_screening_results_markdown",
                path_hint="screening/idea_screening_results.md",
                required=False,
                description="Optional readable screening companion; it cannot replace screening JSON.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_markdown",
                path_hint="ideas/candidate_ideas.md",
                required=False,
                description="Optional readable candidate idea companion; it cannot replace candidate ideas JSON.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_markdown",
                path_hint="gaps/gap_map.md",
                required=False,
                description="Optional readable gap map companion; it cannot replace gap map JSON.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_markdown",
                path_hint="landscape/literature_landscape.md",
                required=False,
                description="Optional readable landscape companion; it cannot replace landscape JSON.",
            ),
            ArtifactRequirement(
                artifact_type="minimal_topic_to_evidence_report",
                path_hint="reports/minimal_topic_to_evidence_report.json",
                required=False,
                description="Optional evidence-grounded summary; it cannot replace source artifacts.",
            ),
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="manuscript_section_draft_json",
                path_hint="drafts/manuscript_section_draft.json",
                required=True,
                description="Structured manuscript-adjacent draft artifact using schema_version manuscript_section_draft_v1.",
            ),
            ArtifactRequirement(
                artifact_type="manuscript_section_draft_markdown",
                path_hint="drafts/manuscript_section_draft.md",
                required=True,
                description="Human-readable draft scaffold with Evidence References and no final manuscript sections.",
            ),
            ArtifactRequirement(
                artifact_type="manuscript_section_diagnostics",
                path_hint="drafts/manuscript_section_diagnostics.json",
                required=True,
                description="Diagnostics preserving draft scope, unsupported claims, limitations, and review requirements.",
            ),
        ],
        required_artifacts=required_artifacts,
        produced_artifacts=produced_artifacts,
        validation_rules=validation_rules,
        failure_modes=[
            "missing_claim_ledger_artifact",
            "manuscript_drafting_requires_claim_ledger",
            "manuscript_drafting_requires_traceable_claims",
            "manuscript_drafting_rejects_unvalidated_claims",
            "manuscript_drafting_rejects_final_claim_overwrite",
            "manuscript_drafting_rejects_raw_experimental_result_claims",
            "raw_retrieval_candidates_not_allowed_for_manuscript_drafting",
        ],
        based_on_modules=["P2-M14.1", "P2-M14.2"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=[
            "P2-M14.2 deterministic stub-safe wrapper is available.",
            "Claim ledger records are traceability scaffolds and must not be treated as validated experimental conclusions.",
            "Draft artifacts remain manuscript-adjacent, human-review-required, and not submission-ready.",
        ],
    )


def _screening_stub() -> SkillContract:
    required_artifacts = [
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
    produced_artifacts = [
        "screening/idea_screening_results.json",
        "screening/idea_screening_results.md",
        "screening/screening_diagnostics.json",
    ]
    validation_rules = [
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
        "local_novelty_feasibility_risk_triage_fields_have_rationale_or_limitations",
        "not_an_experiment_plan_is_true",
        "not_a_validated_claim_is_true",
        "markdown_contains_evidence_references",
        "markdown_excludes_experiment_protocol_manuscript_final_claim_sections",
        "screening_does_not_claim_final_novelty_or_feasibility",
        "raw_retrieval_candidates_not_allowed_for_screening",
    ]
    return SkillContract(
        name="screen_novelty_feasibility_risk",
        purpose=(
            "Perform LLM-assisted, evidence-grounded local novelty, feasibility, and risk triage for "
            "candidate ideas using candidate idea artifacts, gap maps, landscape artifacts, enriched "
            "Evidence Cards, selected evidence, and diagnostics."
        ),
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.LLM_ASSISTED,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="candidate_ideas_json",
                path_hint="ideas/candidate_ideas.json",
                required=True,
                description="Structured P2-M10 candidate ideas using schema_version candidate_ideas_v1.",
            ),
            ArtifactRequirement(
                artifact_type="idea_generation_diagnostics",
                path_hint="ideas/idea_generation_diagnostics.json",
                required=True,
                description="Diagnostics preserving idea generation constraints and skipped gaps.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_json",
                path_hint="gaps/gap_map.json",
                required=True,
                description="Structured gap map artifact used to preserve gap basis.",
            ),
            ArtifactRequirement(
                artifact_type="gap_coverage_diagnostics",
                path_hint="gaps/gap_coverage_diagnostics.json",
                required=True,
                description="Gap coverage diagnostics used as screening limitations.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_json",
                path_hint="landscape/literature_landscape.json",
                required=True,
                description="Structured literature landscape used to preserve landscape basis.",
            ),
            ArtifactRequirement(
                artifact_type="landscape_coverage_diagnostics",
                path_hint="landscape/landscape_coverage_diagnostics.json",
                required=True,
                description="Landscape diagnostics used as screening limitations.",
            ),
            ArtifactRequirement(
                artifact_type="enriched_evidence_cards",
                path_hint="evidence/evidence_cards.enriched.json",
                required=True,
                description="Validated enriched Evidence Cards; seeds and initial cards are not allowed.",
            ),
            ArtifactRequirement(
                artifact_type="evidence_selection",
                path_hint="ranked_evidence/evidence_selection.json",
                required=True,
                description="Selected evidence used to keep screening evidence-grounded.",
            ),
            ArtifactRequirement(
                artifact_type="ranking_coverage_diagnostics",
                path_hint="ranked_evidence/coverage_diagnostics.json",
                required=True,
                description="Ranking diagnostics used as screening limitations.",
            ),
            ArtifactRequirement(
                artifact_type="candidate_ideas_markdown",
                path_hint="ideas/candidate_ideas.md",
                required=False,
                description="Optional readable candidate idea companion; it cannot replace candidate ideas JSON.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_markdown",
                path_hint="gaps/gap_map.md",
                required=False,
                description="Optional readable gap map companion; it cannot replace gap map JSON.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_markdown",
                path_hint="landscape/literature_landscape.md",
                required=False,
                description="Optional readable landscape companion; it cannot replace landscape JSON.",
            ),
            ArtifactRequirement(
                artifact_type="minimal_topic_to_evidence_report",
                path_hint="reports/minimal_topic_to_evidence_report.json",
                required=False,
                description="Optional evidence-grounded summary; it cannot replace source artifacts.",
            ),
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="idea_screening_results_json",
                path_hint="screening/idea_screening_results.json",
                required=True,
                description="Structured screening result using schema_version idea_screening_v2.",
            ),
            ArtifactRequirement(
                artifact_type="idea_screening_results_markdown",
                path_hint="screening/idea_screening_results.md",
                required=True,
                description="Human-readable screening summary with Evidence References and no experiment plan.",
            ),
            ArtifactRequirement(
                artifact_type="screening_diagnostics",
                path_hint="screening/screening_diagnostics.json",
                required=True,
                description="Diagnostics preserving screening scope, limitations, and follow-up checks.",
            ),
        ],
        required_artifacts=required_artifacts,
        produced_artifacts=produced_artifacts,
        validation_rules=validation_rules,
        failure_modes=[
            "skill_not_implemented",
            "missing_candidate_ideas_artifact",
            "screening_requires_gap_and_evidence_basis",
            "screening_requires_unscreened_candidate_ideas",
            "llm_required_for_screening",
            "invalid_llm_screening_json",
            "unknown_screening_evidence_id",
            "unknown_screening_gap_id",
            "unknown_screening_paper_id",
            "raw_retrieval_candidates_not_allowed_for_screening",
            "unsupported_screening_claim",
        ],
        based_on_modules=["P2-M11.2", "P2-M11-llm-assisted"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=[
            "P2-M11.2 LLM-assisted evidence-grounded screening wrapper is available.",
            "Screening must consume P2-M10 candidate ideas and must not regenerate ideas.",
            "LLM output must pass strict local artifact reference validation before artifacts are written.",
            "Screening outputs must not include experiment plans, protocols, manuscripts, or final validated claims.",
        ],
    )


def _gap_mapping_stub() -> SkillContract:
    return SkillContract(
        name="map_gaps",
        purpose=(
            "Map evidence coverage gaps from landscape artifacts, enriched Evidence Cards, "
            "selected evidence, and coverage diagnostics."
        ),
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="literature_landscape_json",
                path_hint="landscape/literature_landscape.json",
                required=True,
                description="Structured landscape artifact using schema_version landscape_v1.",
            ),
            ArtifactRequirement(
                artifact_type="landscape_coverage_diagnostics",
                path_hint="landscape/landscape_coverage_diagnostics.json",
                required=True,
                description="Landscape-specific diagnostics used as gap mapping basis.",
            ),
            ArtifactRequirement(
                artifact_type="enriched_evidence_cards",
                path_hint="evidence/evidence_cards.enriched.json",
                required=True,
                description="Validated enriched Evidence Cards; seeds and initial cards are not allowed.",
            ),
            ArtifactRequirement(
                artifact_type="evidence_selection",
                path_hint="ranked_evidence/evidence_selection.json",
                required=True,
                description="Selected evidence used to keep gaps grounded in ranked evidence.",
            ),
            ArtifactRequirement(
                artifact_type="ranking_coverage_diagnostics",
                path_hint="ranked_evidence/coverage_diagnostics.json",
                required=True,
                description="Ranking coverage diagnostics used to identify coverage weaknesses.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_markdown",
                path_hint="landscape/literature_landscape.md",
                required=False,
                description="Optional readable landscape companion; it cannot replace landscape JSON.",
            ),
            ArtifactRequirement(
                artifact_type="minimal_topic_to_evidence_report",
                path_hint="reports/minimal_topic_to_evidence_report.json",
                required=False,
                description="Optional evidence-grounded summary; it cannot replace source artifacts.",
            ),
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="gap_map_json",
                path_hint="gaps/gap_map.json",
                required=True,
                description="Structured gap map artifact using schema_version gap_map_v1.",
            ),
            ArtifactRequirement(
                artifact_type="gap_map_markdown",
                path_hint="gaps/gap_map.md",
                required=True,
                description="Human-readable gap map with Evidence References and no idea sections.",
            ),
            ArtifactRequirement(
                artifact_type="gap_coverage_diagnostics",
                path_hint="gaps/gap_coverage_diagnostics.json",
                required=True,
                description="Diagnostics preserving coverage basis and limitations.",
            ),
        ],
        required_artifacts=[
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        produced_artifacts=[
            "gaps/gap_map.json",
            "gaps/gap_map.md",
            "gaps/gap_coverage_diagnostics.json",
        ],
        validation_rules=[
            "input_artifacts_exist",
            "landscape_json_exists_and_parseable",
            "landscape_schema_version_is_landscape_v1",
            "raw_retrieval_candidates_not_allowed_for_gap_mapping",
            "enriched_evidence_cards_and_selected_evidence_present",
            "output_json_parseable",
            "schema_version_is_gap_map_v1",
            "every_gap_has_basis",
            "every_gap_basis_references_evidence_landscape_or_diagnostics",
            "no_gap_is_candidate_idea",
            "markdown_contains_evidence_references",
            "markdown_excludes_idea_novelty_feasibility_experiment_manuscript_sections",
            "coverage_diagnostics_preserved",
        ],
        failure_modes=[
            "skill_not_implemented",
            "missing_landscape_artifact",
            "gap_mapping_requires_evidence_references",
            "raw_retrieval_candidates_not_allowed_for_gap_mapping",
            "unsupported_gap_claim",
        ],
        based_on_modules=["P2-M9.2"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=[
            "P2-M9.2 deterministic stub-safe wrapper is available.",
            "Gap outputs must not include candidate ideas, novelty screening, feasibility screening, experiment plans, or manuscript drafts.",
        ],
    )


def _landscape_stub() -> SkillContract:
    return SkillContract(
        name="build_landscape",
        purpose=(
            "Build a topic-level literature landscape from enriched Evidence Cards, "
            "selected evidence, and coverage diagnostics."
        ),
        status=SkillStatus.AVAILABLE,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type="enriched_evidence_cards",
                path_hint="evidence/evidence_cards.enriched.json",
                required=True,
                description="Validated enriched Evidence Cards; raw seeds and initial cards are not allowed.",
            ),
            ArtifactRequirement(
                artifact_type="evidence_selection",
                path_hint="ranked_evidence/evidence_selection.json",
                required=True,
                description="Ranked or selected evidence used to keep landscape clusters representative.",
            ),
            ArtifactRequirement(
                artifact_type="coverage_diagnostics",
                path_hint="ranked_evidence/coverage_diagnostics.json",
                required=True,
                description="Coverage diagnostics from evidence ranking.",
            ),
            ArtifactRequirement(
                artifact_type="minimal_topic_to_evidence_report",
                path_hint="reports/minimal_topic_to_evidence_report.json",
                required=False,
                description="Optional evidence-grounded summary; it cannot replace Evidence Cards.",
            ),
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type="literature_landscape_json",
                path_hint="landscape/literature_landscape.json",
                required=True,
                description="Structured landscape artifact using schema_version landscape_v1.",
            ),
            ArtifactRequirement(
                artifact_type="literature_landscape_markdown",
                path_hint="landscape/literature_landscape.md",
                required=True,
                description="Human-readable landscape with Evidence References.",
            ),
            ArtifactRequirement(
                artifact_type="landscape_coverage_diagnostics",
                path_hint="landscape/landscape_coverage_diagnostics.json",
                required=True,
                description="Landscape-specific coverage and limitation diagnostics.",
            ),
        ],
        required_artifacts=[
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        produced_artifacts=[
            "landscape/literature_landscape.json",
            "landscape/literature_landscape.md",
            "landscape/landscape_coverage_diagnostics.json",
        ],
        validation_rules=[
            "input_artifacts_exist",
            "inputs_are_validated_enriched_evidence_cards_or_selected_evidence",
            "raw_retrieval_candidates_not_allowed_for_landscape",
            "output_json_parseable",
            "schema_version_is_landscape_v1",
            "every_cluster_has_evidence_ids",
            "every_representative_claim_references_evidence_id",
            "markdown_contains_evidence_references",
            "markdown_excludes_gap_idea_novelty_experiment_manuscript_sections",
            "coverage_diagnostics_preserved",
        ],
        failure_modes=[
            "skill_not_implemented",
            "missing_enriched_evidence_cards",
            "missing_evidence_selection",
            "raw_retrieval_candidates_not_allowed_for_landscape",
            "unsupported_landscape_claim",
        ],
        based_on_modules=["P2-M8.1"],
        writes_artifacts=True,
        allows_raw_chunks=False,
        requires_evidence_cards=True,
        notes=[
            "P2-M8.2 deterministic stub-safe wrapper is available.",
            "Landscape outputs must not include gaps, candidate ideas, novelty screening, experiment plans, or manuscript drafts.",
        ],
    )


def _skill(
    *,
    name: str,
    purpose: str,
    based_on_modules: list[str],
    produced_type: str,
    produced_path: str,
    validation_rules: list[str],
    failure_modes: list[str],
    status: SkillStatus | str = SkillStatus.AVAILABLE,
    execution_mode: SkillExecutionMode | str = SkillExecutionMode.DETERMINISTIC,
    database_access: SkillDatabaseAccess | str = SkillDatabaseAccess.NONE,
    input_type: str = "task",
    input_path: str = "task.md",
    allows_raw_chunks: bool = False,
    requires_evidence_cards: bool = False,
    writes_artifacts: bool = True,
    notes: list[str] | None = None,
) -> SkillContract:
    return SkillContract(
        name=name,
        purpose=purpose,
        status=status,
        execution_mode=execution_mode,
        database_access=database_access,
        input_artifacts=[
            ArtifactRequirement(
                artifact_type=input_type,
                path_hint=input_path,
                required=True,
                description=f"Required input artifact for {name}.",
            )
        ],
        output_artifacts=[
            ArtifactRequirement(
                artifact_type=produced_type,
                path_hint=produced_path,
                required=True,
                description=f"Produced artifact declared by {name}.",
            )
        ],
        required_artifacts=[input_path],
        produced_artifacts=[produced_path],
        validation_rules=validation_rules,
        failure_modes=failure_modes,
        based_on_modules=based_on_modules,
        writes_artifacts=writes_artifacts,
        allows_raw_chunks=allows_raw_chunks,
        requires_evidence_cards=requires_evidence_cards,
        notes=list(notes or []),
    )


def _stub(
    name: str,
    purpose: str,
    *,
    input_type: str,
    produced_type: str,
    produced_path: str,
) -> SkillContract:
    return _skill(
        name=name,
        purpose=purpose,
        status=SkillStatus.STUB,
        execution_mode=SkillExecutionMode.DETERMINISTIC,
        database_access=SkillDatabaseAccess.NONE,
        input_type=input_type,
        input_path=_input_path_for(input_type),
        produced_type=produced_type,
        produced_path=produced_path,
        validation_rules=["prerequisite_artifacts_declared", "raw_chunks_not_allowed"],
        failure_modes=["skill_not_implemented", "missing_prerequisite_artifact"],
        based_on_modules=["future"],
        requires_evidence_cards=True,
        notes=["Stub only; execution is intentionally not implemented in A3."],
    )


def _input_path_for(input_type: str) -> str:
    return {
        "evidence_cards": "evidence/evidence_cards.json",
        "landscape": "landscape/landscape.json",
        "gaps": "gaps/gaps.json",
        "ideas": "ideas/candidate_ideas.json",
        "screening": "screening/idea_screening.json",
        "claim_ledger": "claim_ledger/claim_ledger.json",
    }.get(input_type, "task.md")


def _artifact_requirement(value: ArtifactRequirement | dict[str, Any]) -> ArtifactRequirement:
    if isinstance(value, ArtifactRequirement):
        return value
    if isinstance(value, dict):
        return ArtifactRequirement.from_dict(value)
    raise TypeError("artifact requirements must be ArtifactRequirement or dict")


def _coerce_enum(enum_cls: type[Enum], value: Enum | str, field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ValueError(f"invalid {field_name}: {value!r}; expected one of: {allowed}") from exc


__all__ = [
    "ArtifactRequirement",
    "SkillContract",
    "SkillDatabaseAccess",
    "SkillExecutionMode",
    "SkillExecutionInput",
    "SkillExecutionResult",
    "SkillExecutionStatus",
    "SkillRegistry",
    "SkillStatus",
    "build_default_skill_registry",
]
