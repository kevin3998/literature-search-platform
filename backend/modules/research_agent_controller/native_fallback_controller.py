"""Platform-native deterministic fallback controller for A8.

This controller is a regression baseline and unavailable-external-controller
fallback. It chooses the next minimal topic-to-evidence skill from workspace
artifacts and delegates execution to the registered A4 skill wrappers.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from modules.research_workspace import ResearchWorkspaceStore

from .audit import append_controller_event, record_skill_execution_result
from .schemas import AgentDecisionType, AgentTaskStatus, ControllerDecision, ValidationStatus
from .skill_registry import (
    SkillExecutionInput,
    SkillExecutionResult,
    SkillExecutionStatus,
    SkillRegistry,
    build_default_skill_registry,
)
from .skills import (
    execute_evidence_skill,
    validate_candidate_ideas_artifact,
    validate_claim_ledger_artifact,
    validate_experiment_matrix_artifact,
    validate_gap_map_artifact,
    validate_manuscript_draft_artifact,
    validate_screening_artifact,
)
from .skills.claim_ledger_contract import (
    CLAIM_LEDGER_OUTPUT_ARTIFACTS,
    CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
    validate_claim_ledger_input_artifacts,
)
from .skills.experiment_matrix_contract import validate_experiment_matrix_input_artifacts
from .skills.gap_contract import validate_gap_mapping_input_artifacts
from .skills.idea_contract import validate_idea_generation_input_artifacts
from .skills.manuscript_contract import (
    MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
    MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
    validate_manuscript_drafting_input_artifacts,
)
from .skills.screening_contract import validate_screening_input_artifacts
from .validators import (
    ArtifactValidationResult,
    validate_artifact_manifest,
    validate_evidence_card_artifact,
    validate_ranking_selection_artifact,
    validate_report_inputs,
)

SOURCE_PACKET_PATH = "retrieval/source_candidate_packet.json"
RETRIEVAL_WARNINGS_PATH = "retrieval/retrieval_warnings.json"
SEEDS_PATH = "evidence/evidence_card_seeds.json"
INITIAL_CARDS_PATH = "evidence/evidence_cards.initial.json"
ENRICHED_CARDS_PATH = "evidence/evidence_cards.enriched.json"
SELECTION_PATH = "ranked_evidence/evidence_selection.json"
COVERAGE_DIAGNOSTICS_PATH = "ranked_evidence/coverage_diagnostics.json"
REPORT_MD_PATH = "reports/minimal_topic_to_evidence_report.md"
REPORT_JSON_PATH = "reports/minimal_topic_to_evidence_report.json"
LANDSCAPE_JSON_PATH = "landscape/literature_landscape.json"
LANDSCAPE_MD_PATH = "landscape/literature_landscape.md"
LANDSCAPE_COVERAGE_DIAGNOSTICS_PATH = "landscape/landscape_coverage_diagnostics.json"
GAP_MAP_JSON_PATH = "gaps/gap_map.json"
GAP_MAP_MD_PATH = "gaps/gap_map.md"
GAP_COVERAGE_DIAGNOSTICS_PATH = "gaps/gap_coverage_diagnostics.json"
IDEAS_JSON_PATH = "ideas/candidate_ideas.json"
IDEAS_MD_PATH = "ideas/candidate_ideas.md"
IDEA_GENERATION_DIAGNOSTICS_PATH = "ideas/idea_generation_diagnostics.json"
SCREENING_JSON_PATH = "screening/idea_screening_results.json"
SCREENING_MD_PATH = "screening/idea_screening_results.md"
SCREENING_DIAGNOSTICS_PATH = "screening/screening_diagnostics.json"
EXPERIMENT_MATRIX_JSON_PATH = "experiments/experiment_matrix.json"
EXPERIMENT_MATRIX_MD_PATH = "experiments/experiment_matrix.md"
EXPERIMENT_MATRIX_DIAGNOSTICS_PATH = "experiments/experiment_matrix_diagnostics.json"
CLAIM_LEDGER_JSON_PATH = "claims/claim_ledger.json"
CLAIM_LEDGER_MD_PATH = "claims/claim_ledger.md"
CLAIM_LEDGER_DIAGNOSTICS_PATH = "claims/claim_ledger_diagnostics.json"
MANUSCRIPT_DRAFT_JSON_PATH = "drafts/manuscript_section_draft.json"
MANUSCRIPT_DRAFT_MD_PATH = "drafts/manuscript_section_draft.md"
MANUSCRIPT_DRAFT_DIAGNOSTICS_PATH = "drafts/manuscript_section_diagnostics.json"

CONTROLLER_SOURCE = "platform_native_fallback"


class NativeFallbackStepStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    VALIDATION_FAILED = "validation_failed"
    STOP_SUCCESS = "stop_success"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class NativeFallbackStepResult:
    task_id: str
    step_index: int
    status: NativeFallbackStepStatus | str
    next_skill: str | None = None
    decision: ControllerDecision | None = None
    skill_result: SkillExecutionResult | None = None
    validation_results: list[ArtifactValidationResult] = field(default_factory=list)
    stop_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.status, NativeFallbackStepStatus):
            self.status = NativeFallbackStepStatus(self.status)
        self.validation_results = list(self.validation_results or [])
        self.warnings = list(self.warnings or [])
        self.errors = list(self.errors or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step_index": self.step_index,
            "status": self.status.value,
            "next_skill": self.next_skill,
            "decision": self.decision.as_dict() if self.decision else None,
            "skill_result": self.skill_result.as_dict() if self.skill_result else None,
            "validation_results": [result.as_dict() for result in self.validation_results],
            "stop_reason": self.stop_reason,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class PlatformNativeFallbackController:
    """Deterministic minimal topic-to-evidence fallback controller."""

    def __init__(
        self,
        workspace_root: str | Path,
        task_id: str,
        *,
        topic: str,
        registry: SkillRegistry | None = None,
        max_steps: int = 12,
        retrieval_budget: int | None = None,
        selection_budget: int | None = None,
        scope_lock: dict[str, Any] | None = None,
        task_profile_id: str = "topic-to-report",
        acquire_evidence_fn: Callable[..., dict[str, Any]] | None = None,
        extractor: Callable[..., dict[str, Any]] | None = None,
        classifier: Callable[..., dict[str, Any]] | None = None,
        llm_client: Any | None = None,
    ):
        self.workspace_root = Path(workspace_root)
        self.task_id = task_id
        self.topic = topic
        self.registry = registry or build_default_skill_registry()
        self.max_steps = max(1, int(max_steps))
        self.retrieval_budget = retrieval_budget
        self.selection_budget = selection_budget
        self.scope_lock = dict(scope_lock or {})
        self.task_profile_id = task_profile_id
        self.acquire_evidence_fn = acquire_evidence_fn
        self.extractor = extractor
        self.classifier = classifier
        self.llm_client = llm_client
        self.step_index = 0
        self.store = _store_from_workspace_root(self.workspace_root, task_id)

    def run_once(self) -> NativeFallbackStepResult:
        current_index = self.step_index
        self.step_index += 1
        next_skill = self._determine_next_skill()

        if next_skill is None:
            decision = self._decision(
                AgentDecisionType.STOP_SUCCESS,
                "Minimal topic-to-evidence artifacts are complete.",
            )
            self._append_controller_event(decision, "Native fallback stopped successfully.")
            self._update_state(
                AgentTaskStatus.COMPLETED,
                last_decision=decision,
                last_action={"step_index": current_index, "decision_type": AgentDecisionType.STOP_SUCCESS.value},
            )
            self._write_plan_summary(AgentTaskStatus.COMPLETED.value, "Minimal topic-to-evidence artifacts are complete.", [])
            return NativeFallbackStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=NativeFallbackStepStatus.STOP_SUCCESS,
                decision=decision,
                stop_reason="all_steps_completed",
            )

        input_artifacts = self._input_artifacts_for(next_skill)
        preflight = self._preflight(next_skill, input_artifacts)
        if preflight is not None and preflight.validation_status == ValidationStatus.FAILED:
            decision = self._decision(
                AgentDecisionType.CALL_TOOL,
                f"Native fallback selected {next_skill}.",
                skill_name=next_skill,
                input_artifacts=input_artifacts,
                output_artifacts=self._output_artifacts_for(next_skill),
            )
            self._append_controller_event(decision, "Preflight validation failed.", errors=preflight.errors)
            self._update_state(
                AgentTaskStatus.VALIDATION_FAILED,
                blockers=preflight.errors,
                last_decision=decision,
                last_action={"step_index": current_index, "validation": preflight.as_dict()},
            )
            self._write_plan_summary(AgentTaskStatus.VALIDATION_FAILED.value, next_skill, preflight.errors)
            return NativeFallbackStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=NativeFallbackStepStatus.VALIDATION_FAILED,
                next_skill=next_skill,
                decision=decision,
                validation_results=[preflight],
                errors=preflight.errors,
                stop_reason="validation_failed",
            )

        missing_inputs = [path for path in input_artifacts if not _exists(self.workspace_root, path)]
        if missing_inputs:
            errors = _missing_input_errors(next_skill, missing_inputs)
            decision = self._decision(
                AgentDecisionType.CALL_TOOL,
                f"Native fallback selected {next_skill}.",
                skill_name=next_skill,
                input_artifacts=input_artifacts,
            )
            skill_result = SkillExecutionResult(
                task_id=self.task_id,
                skill_name=next_skill,
                status=SkillExecutionStatus.BLOCKED,
                input_artifacts=input_artifacts,
                errors=errors,
            )
            self._append_controller_event(decision, "Required input artifact is missing.", errors=errors)
            self._update_after_terminal_tool_result(AgentTaskStatus.BLOCKED, decision, skill_result, errors)
            self._write_plan_summary(AgentTaskStatus.BLOCKED.value, next_skill, errors)
            return NativeFallbackStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=NativeFallbackStepStatus.BLOCKED,
                next_skill=next_skill,
                decision=decision,
                skill_result=skill_result,
                errors=errors,
                stop_reason="missing_input_artifact",
            )

        decision = self._decision(
            AgentDecisionType.CALL_TOOL,
            f"Native fallback selected {next_skill}.",
            skill_name=next_skill,
            input_artifacts=input_artifacts,
            output_artifacts=self._output_artifacts_for(next_skill),
        )
        self._append_controller_event(decision, f"Native fallback selected {next_skill}.")

        execution_input = SkillExecutionInput(
            task_id=self.task_id,
            workspace_root=str(self.workspace_root),
            skill_name=next_skill,
            input_artifacts=input_artifacts,
            parameters=self._parameters_for(next_skill),
            requested_by=CONTROLLER_SOURCE,
        )
        skill_result = execute_evidence_skill(
            execution_input,
            registry=self.registry,
            acquire_evidence_fn=self.acquire_evidence_fn,
            extractor=self.extractor,
            classifier=self.classifier,
            llm_client=self.llm_client,
        )
        record_skill_execution_result(skill_result, self.workspace_root)

        validation_results = self._run_validation_gates(skill_result, execution_input)
        if preflight is not None:
            validation_results.insert(0, preflight)
        failed_validations = [result for result in validation_results if result.validation_status == ValidationStatus.FAILED]
        if failed_validations or skill_result.status == SkillExecutionStatus.VALIDATION_FAILED:
            errors = list(skill_result.errors)
            for result in failed_validations:
                errors.extend(result.errors)
            errors = list(dict.fromkeys(errors))
            self._update_after_terminal_tool_result(AgentTaskStatus.VALIDATION_FAILED, decision, skill_result, errors)
            self._write_plan_summary(AgentTaskStatus.VALIDATION_FAILED.value, next_skill, errors)
            return NativeFallbackStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=NativeFallbackStepStatus.VALIDATION_FAILED,
                next_skill=next_skill,
                decision=decision,
                skill_result=skill_result,
                validation_results=validation_results,
                errors=errors,
                stop_reason="validation_failed",
            )

        if skill_result.status == SkillExecutionStatus.BLOCKED:
            self._update_after_terminal_tool_result(AgentTaskStatus.BLOCKED, decision, skill_result, skill_result.errors)
            self._write_plan_summary(AgentTaskStatus.BLOCKED.value, next_skill, skill_result.errors)
            return NativeFallbackStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=NativeFallbackStepStatus.BLOCKED,
                next_skill=next_skill,
                decision=decision,
                skill_result=skill_result,
                validation_results=validation_results,
                errors=list(skill_result.errors),
                stop_reason="skill_blocked",
            )

        if skill_result.status == SkillExecutionStatus.FAILED:
            self._update_after_terminal_tool_result(AgentTaskStatus.FAILED, decision, skill_result, skill_result.errors)
            self._write_plan_summary(AgentTaskStatus.FAILED.value, next_skill, skill_result.errors)
            return NativeFallbackStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=NativeFallbackStepStatus.FAILED,
                next_skill=next_skill,
                decision=decision,
                skill_result=skill_result,
                validation_results=validation_results,
                errors=list(skill_result.errors),
                stop_reason="skill_failed",
            )

        warnings = list(skill_result.warnings)
        for result in validation_results:
            warnings.extend(result.warnings)
        warnings = list(dict.fromkeys(warnings))
        self._update_after_success(decision, skill_result, warnings=warnings)
        self._write_plan_summary(AgentTaskStatus.RUNNING.value, next_skill, warnings)
        return NativeFallbackStepResult(
            task_id=self.task_id,
            step_index=current_index,
            status=NativeFallbackStepStatus.SUCCESS,
            next_skill=next_skill,
            decision=decision,
            skill_result=skill_result,
            validation_results=validation_results,
            warnings=warnings,
        )

    def run_until_stop(self, max_steps: int | None = None) -> list[NativeFallbackStepResult]:
        limit = max(1, int(max_steps or self.max_steps))
        results: list[NativeFallbackStepResult] = []
        terminal = {
            NativeFallbackStepStatus.BLOCKED,
            NativeFallbackStepStatus.FAILED,
            NativeFallbackStepStatus.VALIDATION_FAILED,
            NativeFallbackStepStatus.STOP_SUCCESS,
        }
        while len(results) < limit:
            result = self.run_once()
            results.append(result)
            if result.status in terminal:
                return results

        budget = NativeFallbackStepResult(
            task_id=self.task_id,
            step_index=self.step_index,
            status=NativeFallbackStepStatus.BUDGET_EXCEEDED,
            stop_reason="max_steps_reached",
            errors=["max_steps_reached"],
        )
        self._update_state(
            AgentTaskStatus.BUDGET_EXCEEDED,
            blockers=["max_steps_reached"],
            last_action={"step_index": self.step_index, "stop_reason": "max_steps_reached"},
        )
        self._write_plan_summary(AgentTaskStatus.BUDGET_EXCEEDED.value, "max_steps_reached", ["max_steps_reached"])
        append_controller_event(
            self.workspace_root,
            {
                "event_id": f"native_fallback_budget:{self.task_id}:{time.time()}",
                "task_id": self.task_id,
                "event_type": "controller_event",
                "message": "Native fallback stopped because max_steps was reached.",
                "errors": ["max_steps_reached"],
                "metadata": {"max_steps": limit, "controller_source": CONTROLLER_SOURCE},
            },
        )
        results.append(budget)
        return results

    def _determine_next_skill(self) -> str | None:
        if not _exists(self.workspace_root, SOURCE_PACKET_PATH):
            return "retrieve_sources"
        if not _exists(self.workspace_root, SEEDS_PATH):
            return "create_evidence_seeds"
        if not _exists(self.workspace_root, INITIAL_CARDS_PATH):
            return "extract_evidence_cards"
        if not _exists(self.workspace_root, ENRICHED_CARDS_PATH):
            return "enrich_evidence_cards"
        if not _exists(self.workspace_root, SELECTION_PATH):
            return "rank_evidence"
        if not _exists(self.workspace_root, COVERAGE_DIAGNOSTICS_PATH):
            return "rank_evidence"
        if not _exists(self.workspace_root, REPORT_MD_PATH) or not _exists(self.workspace_root, REPORT_JSON_PATH):
            return "build_minimal_topic_to_evidence_report"
        if self._explicit_landscape_requested() and (
            not _exists(self.workspace_root, LANDSCAPE_JSON_PATH)
            or not _exists(self.workspace_root, LANDSCAPE_MD_PATH)
            or not _exists(self.workspace_root, LANDSCAPE_COVERAGE_DIAGNOSTICS_PATH)
        ):
            return "build_landscape"
        if self._explicit_gap_mapping_requested() and (
            not _exists(self.workspace_root, GAP_MAP_JSON_PATH)
            or not _exists(self.workspace_root, GAP_MAP_MD_PATH)
            or not _exists(self.workspace_root, GAP_COVERAGE_DIAGNOSTICS_PATH)
        ):
            return "map_gaps"
        if self._explicit_idea_generation_requested() and (
            not _exists(self.workspace_root, IDEAS_JSON_PATH)
            or not _exists(self.workspace_root, IDEAS_MD_PATH)
            or not _exists(self.workspace_root, IDEA_GENERATION_DIAGNOSTICS_PATH)
        ):
            return "generate_candidate_ideas"
        if self._explicit_screening_requested() and (
            not _exists(self.workspace_root, SCREENING_JSON_PATH)
            or not _exists(self.workspace_root, SCREENING_MD_PATH)
            or not _exists(self.workspace_root, SCREENING_DIAGNOSTICS_PATH)
        ):
            return "screen_novelty_feasibility_risk"
        if self._explicit_experiment_matrix_requested() and (
            not _exists(self.workspace_root, EXPERIMENT_MATRIX_JSON_PATH)
            or not _exists(self.workspace_root, EXPERIMENT_MATRIX_MD_PATH)
            or not _exists(self.workspace_root, EXPERIMENT_MATRIX_DIAGNOSTICS_PATH)
        ):
            return "create_experiment_matrix"
        if self._explicit_claim_ledger_requested() and (
            not _exists(self.workspace_root, CLAIM_LEDGER_JSON_PATH)
            or not _exists(self.workspace_root, CLAIM_LEDGER_MD_PATH)
            or not _exists(self.workspace_root, CLAIM_LEDGER_DIAGNOSTICS_PATH)
        ):
            return "build_claim_ledger"
        if self._explicit_manuscript_scaffold_requested() and (
            not _exists(self.workspace_root, MANUSCRIPT_DRAFT_JSON_PATH)
            or not _exists(self.workspace_root, MANUSCRIPT_DRAFT_MD_PATH)
            or not _exists(self.workspace_root, MANUSCRIPT_DRAFT_DIAGNOSTICS_PATH)
        ):
            return "draft_manuscript_section"
        return None

    def _input_artifacts_for(self, skill_name: str) -> list[str]:
        return {
            "retrieve_sources": [],
            "create_evidence_seeds": [SOURCE_PACKET_PATH],
            "extract_evidence_cards": [SEEDS_PATH],
            "enrich_evidence_cards": [INITIAL_CARDS_PATH],
            "rank_evidence": [ENRICHED_CARDS_PATH],
            "build_minimal_topic_to_evidence_report": [
                ENRICHED_CARDS_PATH,
                SELECTION_PATH,
                COVERAGE_DIAGNOSTICS_PATH,
            ],
            "build_landscape": [
                ENRICHED_CARDS_PATH,
                SELECTION_PATH,
                COVERAGE_DIAGNOSTICS_PATH,
            ],
            "map_gaps": [
                LANDSCAPE_JSON_PATH,
                LANDSCAPE_COVERAGE_DIAGNOSTICS_PATH,
                ENRICHED_CARDS_PATH,
                SELECTION_PATH,
                COVERAGE_DIAGNOSTICS_PATH,
            ],
            "generate_candidate_ideas": [
                GAP_MAP_JSON_PATH,
                GAP_COVERAGE_DIAGNOSTICS_PATH,
                LANDSCAPE_JSON_PATH,
                LANDSCAPE_COVERAGE_DIAGNOSTICS_PATH,
                ENRICHED_CARDS_PATH,
                SELECTION_PATH,
                COVERAGE_DIAGNOSTICS_PATH,
            ],
            "screen_novelty_feasibility_risk": [
                IDEAS_JSON_PATH,
                IDEA_GENERATION_DIAGNOSTICS_PATH,
                GAP_MAP_JSON_PATH,
                GAP_COVERAGE_DIAGNOSTICS_PATH,
                LANDSCAPE_JSON_PATH,
                LANDSCAPE_COVERAGE_DIAGNOSTICS_PATH,
                ENRICHED_CARDS_PATH,
                SELECTION_PATH,
                COVERAGE_DIAGNOSTICS_PATH,
            ],
            "create_experiment_matrix": [
                SCREENING_JSON_PATH,
                SCREENING_DIAGNOSTICS_PATH,
                IDEAS_JSON_PATH,
                IDEA_GENERATION_DIAGNOSTICS_PATH,
                GAP_MAP_JSON_PATH,
                GAP_COVERAGE_DIAGNOSTICS_PATH,
                LANDSCAPE_JSON_PATH,
                LANDSCAPE_COVERAGE_DIAGNOSTICS_PATH,
                ENRICHED_CARDS_PATH,
                SELECTION_PATH,
                COVERAGE_DIAGNOSTICS_PATH,
            ],
            "build_claim_ledger": CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
            "draft_manuscript_section": MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
        }.get(skill_name, [])

    def _output_artifacts_for(self, skill_name: str) -> list[str]:
        return {
            "retrieve_sources": [SOURCE_PACKET_PATH, RETRIEVAL_WARNINGS_PATH],
            "create_evidence_seeds": [SEEDS_PATH],
            "extract_evidence_cards": [INITIAL_CARDS_PATH],
            "enrich_evidence_cards": [ENRICHED_CARDS_PATH],
            "rank_evidence": [SELECTION_PATH, COVERAGE_DIAGNOSTICS_PATH],
            "build_minimal_topic_to_evidence_report": [REPORT_MD_PATH, REPORT_JSON_PATH],
            "build_landscape": [
                LANDSCAPE_JSON_PATH,
                LANDSCAPE_MD_PATH,
                LANDSCAPE_COVERAGE_DIAGNOSTICS_PATH,
            ],
            "map_gaps": [
                GAP_MAP_JSON_PATH,
                GAP_MAP_MD_PATH,
                GAP_COVERAGE_DIAGNOSTICS_PATH,
            ],
            "generate_candidate_ideas": [
                IDEAS_JSON_PATH,
                IDEAS_MD_PATH,
                IDEA_GENERATION_DIAGNOSTICS_PATH,
            ],
            "screen_novelty_feasibility_risk": [
                SCREENING_JSON_PATH,
                SCREENING_MD_PATH,
                SCREENING_DIAGNOSTICS_PATH,
            ],
            "create_experiment_matrix": [
                EXPERIMENT_MATRIX_JSON_PATH,
                EXPERIMENT_MATRIX_MD_PATH,
                EXPERIMENT_MATRIX_DIAGNOSTICS_PATH,
            ],
            "build_claim_ledger": CLAIM_LEDGER_OUTPUT_ARTIFACTS,
            "draft_manuscript_section": MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
        }.get(skill_name, [])

    def _parameters_for(self, skill_name: str) -> dict[str, Any]:
        parameters: dict[str, Any] = {"task_profile_id": self.task_profile_id}
        if skill_name in {
            "retrieve_sources",
            "extract_evidence_cards",
            "enrich_evidence_cards",
            "build_minimal_topic_to_evidence_report",
            "build_landscape",
            "map_gaps",
            "generate_candidate_ideas",
            "screen_novelty_feasibility_risk",
            "create_experiment_matrix",
            "build_claim_ledger",
            "draft_manuscript_section",
        }:
            parameters["topic"] = self.topic
        if skill_name == "draft_manuscript_section":
            parameters["target_section"] = "discussion_scaffold"
        if skill_name == "retrieve_sources" and self.scope_lock:
            parameters["scope_lock"] = dict(self.scope_lock)
        if skill_name == "retrieve_sources" and self.retrieval_budget is not None:
            parameters["retrieval_budget"] = self.retrieval_budget
        if skill_name == "rank_evidence" and self.selection_budget is not None:
            parameters["retrieval_budget"] = self.selection_budget
            parameters["selection_budget"] = self.selection_budget
        if skill_name == "build_minimal_topic_to_evidence_report":
            parameters["report_scope"] = "minimal_topic_to_evidence"
            parameters["require_evidence_ids"] = True
        return parameters

    def _preflight(self, skill_name: str, input_artifacts: list[str]) -> ArtifactValidationResult | None:
        if skill_name == "enrich_evidence_cards":
            result = validate_evidence_card_artifact(self.workspace_root, self.task_id, INITIAL_CARDS_PATH, enriched=False)
            if result.validation_status == ValidationStatus.FAILED:
                return result
        if skill_name == "rank_evidence":
            result = validate_evidence_card_artifact(self.workspace_root, self.task_id, ENRICHED_CARDS_PATH, enriched=True)
            if result.validation_status == ValidationStatus.FAILED:
                return result
        if skill_name == "build_minimal_topic_to_evidence_report":
            report_inputs = validate_report_inputs(self.workspace_root, self.task_id, input_artifacts)
            if report_inputs.validation_status == ValidationStatus.FAILED:
                return report_inputs
            selection = validate_ranking_selection_artifact(self.workspace_root, self.task_id, SELECTION_PATH)
            if selection.validation_status == ValidationStatus.FAILED:
                return selection
            cards = validate_evidence_card_artifact(self.workspace_root, self.task_id, ENRICHED_CARDS_PATH, enriched=True)
            if cards.validation_status == ValidationStatus.FAILED:
                return cards
            return report_inputs
        if skill_name == "build_landscape":
            if any(path.startswith("retrieval/") for path in input_artifacts):
                return ArtifactValidationResult(
                    artifact_id="landscape_inputs",
                    artifact_type="landscape_inputs",
                    path=",".join(input_artifacts),
                    validation_status=ValidationStatus.FAILED,
                    validator_name="landscape_input_gate",
                    errors=["raw_retrieval_candidates_not_allowed_for_landscape"],
                    metadata={"input_artifacts": list(input_artifacts)},
                )
        if skill_name == "map_gaps":
            input_errors = validate_gap_mapping_input_artifacts(input_artifacts)
            forbidden_errors = [error for error in input_errors if "not_allowed_for_gap_mapping" in error]
            if forbidden_errors:
                return ArtifactValidationResult(
                    artifact_id="gap_mapping_inputs",
                    artifact_type="gap_mapping_inputs",
                    path=",".join(input_artifacts),
                    validation_status=ValidationStatus.FAILED,
                    validator_name="gap_mapping_input_gate",
                    errors=forbidden_errors,
                    metadata={"input_artifacts": list(input_artifacts)},
                )
        if skill_name == "generate_candidate_ideas":
            input_errors = validate_idea_generation_input_artifacts(input_artifacts)
            forbidden_errors = [error for error in input_errors if "not_allowed_for_idea_generation" in error]
            if forbidden_errors:
                return ArtifactValidationResult(
                    artifact_id="idea_generation_inputs",
                    artifact_type="idea_generation_inputs",
                    path=",".join(input_artifacts),
                    validation_status=ValidationStatus.FAILED,
                    validator_name="idea_generation_input_gate",
                    errors=forbidden_errors,
                    metadata={"input_artifacts": list(input_artifacts)},
                )
        if skill_name == "screen_novelty_feasibility_risk":
            input_errors = validate_screening_input_artifacts(input_artifacts)
            forbidden_errors = [error for error in input_errors if "not_allowed_for_screening" in error]
            if forbidden_errors:
                return ArtifactValidationResult(
                    artifact_id="screening_inputs",
                    artifact_type="screening_inputs",
                    path=",".join(input_artifacts),
                    validation_status=ValidationStatus.FAILED,
                    validator_name="screening_input_gate",
                    errors=forbidden_errors,
                    metadata={"input_artifacts": list(input_artifacts)},
                )
        if skill_name == "create_experiment_matrix":
            input_errors = validate_experiment_matrix_input_artifacts(input_artifacts)
            forbidden_errors = [
                error
                for error in input_errors
                if "not_allowed_for_experiment_matrix" in error
                or error == "raw_retrieval_candidates_not_allowed_for_experiment_matrix"
            ]
            if forbidden_errors:
                return ArtifactValidationResult(
                    artifact_id="experiment_matrix_inputs",
                    artifact_type="experiment_matrix_inputs",
                    path=",".join(input_artifacts),
                    validation_status=ValidationStatus.FAILED,
                    validator_name="experiment_matrix_input_gate",
                    errors=forbidden_errors,
                    metadata={"input_artifacts": list(input_artifacts)},
                )
        if skill_name == "build_claim_ledger":
            input_errors = validate_claim_ledger_input_artifacts(input_artifacts)
            forbidden_errors = [
                error
                for error in input_errors
                if "not_allowed_for_claim_ledger" in error
                or error == "raw_retrieval_candidates_not_allowed_for_claim_ledger"
            ]
            if forbidden_errors:
                return ArtifactValidationResult(
                    artifact_id="claim_ledger_inputs",
                    artifact_type="claim_ledger_inputs",
                    path=",".join(input_artifacts),
                    validation_status=ValidationStatus.FAILED,
                    validator_name="claim_ledger_input_gate",
                    errors=forbidden_errors,
                    metadata={"input_artifacts": list(input_artifacts)},
                )
        if skill_name == "draft_manuscript_section":
            input_errors = validate_manuscript_drafting_input_artifacts(input_artifacts)
            forbidden_errors = [
                error
                for error in input_errors
                if "not_allowed_for_manuscript_drafting" in error
                or error == "raw_retrieval_candidates_not_allowed_for_manuscript_drafting"
            ]
            if forbidden_errors:
                return ArtifactValidationResult(
                    artifact_id="manuscript_drafting_inputs",
                    artifact_type="manuscript_drafting_inputs",
                    path=",".join(input_artifacts),
                    validation_status=ValidationStatus.FAILED,
                    validator_name="manuscript_drafting_input_gate",
                    errors=forbidden_errors,
                    metadata={"input_artifacts": list(input_artifacts)},
                )
        return None

    def _run_validation_gates(
        self,
        skill_result: SkillExecutionResult,
        execution_input: SkillExecutionInput,
    ) -> list[ArtifactValidationResult]:
        results: list[ArtifactValidationResult] = []
        if skill_result.skill_name == "extract_evidence_cards" and INITIAL_CARDS_PATH in skill_result.output_artifacts:
            results.append(validate_evidence_card_artifact(self.workspace_root, self.task_id, INITIAL_CARDS_PATH, enriched=False))
        elif skill_result.skill_name == "enrich_evidence_cards" and ENRICHED_CARDS_PATH in skill_result.output_artifacts:
            results.append(validate_evidence_card_artifact(self.workspace_root, self.task_id, ENRICHED_CARDS_PATH, enriched=True))
        elif skill_result.skill_name == "rank_evidence" and SELECTION_PATH in skill_result.output_artifacts:
            results.append(validate_ranking_selection_artifact(self.workspace_root, self.task_id, SELECTION_PATH))
        elif skill_result.skill_name == "build_landscape" and LANDSCAPE_JSON_PATH in skill_result.output_artifacts:
            results.append(
                ArtifactValidationResult(
                    artifact_id="literature_landscape",
                    artifact_type="landscape",
                    path=LANDSCAPE_JSON_PATH,
                    validation_status=ValidationStatus.PASSED,
                    validator_name="landscape_output_gate",
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "map_gaps" and GAP_MAP_JSON_PATH in skill_result.output_artifacts:
            try:
                gap_map = _read_json(self.workspace_root, GAP_MAP_JSON_PATH)
                markdown = (self.workspace_root / GAP_MAP_MD_PATH).read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["gap_map_output_missing"]
            else:
                errors = validate_gap_map_artifact(gap_map, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="gap_map",
                    artifact_type="gap_map",
                    path=GAP_MAP_JSON_PATH,
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="gap_map_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "generate_candidate_ideas" and IDEAS_JSON_PATH in skill_result.output_artifacts:
            try:
                ideas = _read_json(self.workspace_root, IDEAS_JSON_PATH)
                markdown = (self.workspace_root / IDEAS_MD_PATH).read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["candidate_ideas_output_missing"]
            else:
                errors = validate_candidate_ideas_artifact(ideas, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="candidate_ideas",
                    artifact_type="candidate_ideas",
                    path=IDEAS_JSON_PATH,
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="candidate_ideas_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "screen_novelty_feasibility_risk" and SCREENING_JSON_PATH in skill_result.output_artifacts:
            try:
                screening = _read_json(self.workspace_root, SCREENING_JSON_PATH)
                markdown = (self.workspace_root / SCREENING_MD_PATH).read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["screening_output_missing"]
            else:
                errors = validate_screening_artifact(screening, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="idea_screening",
                    artifact_type="idea_screening",
                    path=SCREENING_JSON_PATH,
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="screening_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "create_experiment_matrix" and EXPERIMENT_MATRIX_JSON_PATH in skill_result.output_artifacts:
            try:
                experiment_matrix = _read_json(self.workspace_root, EXPERIMENT_MATRIX_JSON_PATH)
                markdown = (self.workspace_root / EXPERIMENT_MATRIX_MD_PATH).read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["experiment_matrix_output_missing"]
            else:
                errors = validate_experiment_matrix_artifact(experiment_matrix, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="experiment_matrix",
                    artifact_type="experiment_matrix",
                    path=EXPERIMENT_MATRIX_JSON_PATH,
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="experiment_matrix_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "build_claim_ledger" and CLAIM_LEDGER_JSON_PATH in skill_result.output_artifacts:
            try:
                claim_ledger = _read_json(self.workspace_root, CLAIM_LEDGER_JSON_PATH)
                markdown = (self.workspace_root / CLAIM_LEDGER_MD_PATH).read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["claim_ledger_output_missing"]
            else:
                errors = validate_claim_ledger_artifact(claim_ledger, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="claim_ledger",
                    artifact_type="claim_ledger",
                    path=CLAIM_LEDGER_JSON_PATH,
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="claim_ledger_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "draft_manuscript_section" and MANUSCRIPT_DRAFT_JSON_PATH in skill_result.output_artifacts:
            try:
                draft = _read_json(self.workspace_root, MANUSCRIPT_DRAFT_JSON_PATH)
                markdown = (self.workspace_root / MANUSCRIPT_DRAFT_MD_PATH).read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["manuscript_draft_output_missing"]
            else:
                errors = validate_manuscript_draft_artifact(draft, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="manuscript_section_draft",
                    artifact_type="manuscript_section_draft",
                    path=MANUSCRIPT_DRAFT_JSON_PATH,
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="manuscript_draft_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        results.append(validate_artifact_manifest(self.workspace_root, self.task_id))
        return results

    def _explicit_landscape_requested(self) -> bool:
        try:
            plan_text = self.store.read_plan(self.task_id)
        except FileNotFoundError:
            return False
        return "build_landscape" in plan_text

    def _explicit_gap_mapping_requested(self) -> bool:
        try:
            plan_text = self.store.read_plan(self.task_id)
        except FileNotFoundError:
            return False
        return "map_gaps" in plan_text

    def _explicit_idea_generation_requested(self) -> bool:
        try:
            plan_text = self.store.read_plan(self.task_id)
        except FileNotFoundError:
            return False
        return "generate_candidate_ideas" in plan_text

    def _explicit_screening_requested(self) -> bool:
        try:
            plan_text = self.store.read_plan(self.task_id)
        except FileNotFoundError:
            return False
        return "screen_novelty_feasibility_risk" in plan_text

    def _explicit_experiment_matrix_requested(self) -> bool:
        try:
            plan_text = self.store.read_plan(self.task_id)
        except FileNotFoundError:
            return False
        return "create_experiment_matrix" in plan_text

    def _explicit_claim_ledger_requested(self) -> bool:
        try:
            plan_text = self.store.read_plan(self.task_id)
        except FileNotFoundError:
            return False
        return "build_claim_ledger" in plan_text

    def _explicit_manuscript_scaffold_requested(self) -> bool:
        try:
            plan_text = self.store.read_plan(self.task_id)
        except FileNotFoundError:
            return False
        return "draft_manuscript_section" in plan_text

    def _decision(
        self,
        decision_type: AgentDecisionType,
        reason: str,
        *,
        skill_name: str | None = None,
        input_artifacts: list[str] | None = None,
        output_artifacts: list[str] | None = None,
    ) -> ControllerDecision:
        return ControllerDecision(
            decision_id=f"native_fallback:{self.task_id}:{self.step_index}:{decision_type.value}",
            task_id=self.task_id,
            decision_type=decision_type,
            reason=reason,
            target_step_id=skill_name,
            skill_name=skill_name,
            input_artifacts=list(input_artifacts or []),
            output_artifacts=list(output_artifacts or []),
        )

    def _append_controller_event(
        self,
        decision: ControllerDecision,
        message: str,
        *,
        errors: list[str] | None = None,
    ) -> None:
        append_controller_event(
            self.workspace_root,
            {
                "event_id": f"native_fallback:{self.task_id}:{time.time()}",
                "task_id": self.task_id,
                "event_type": "controller_event",
                "decision_type": decision.decision_type.value,
                "target_step_id": decision.target_step_id,
                "message": message,
                "artifacts": [*decision.input_artifacts, *decision.output_artifacts],
                "warnings": list(decision.warnings),
                "errors": list(errors or []),
                "metadata": {
                    "controller_source": CONTROLLER_SOURCE,
                    "skill_name": decision.skill_name,
                },
            },
        )

    def _update_after_success(
        self,
        decision: ControllerDecision,
        skill_result: SkillExecutionResult,
        *,
        warnings: list[str],
    ) -> None:
        state = self.store.read_state(self.task_id)
        completed_steps = _append_unique(state.get("completed_steps", []), skill_result.skill_name)
        pending_steps = [step for step in state.get("pending_steps", []) if step != skill_result.skill_name]
        artifact_index = dict(state.get("artifact_index", {}))
        for path in skill_result.output_artifacts:
            artifact_index[path] = f"{skill_result.skill_name}:{path}"
        state.update(
            {
                "status": AgentTaskStatus.RUNNING.value,
                "current_phase": CONTROLLER_SOURCE,
                "completed_steps": completed_steps,
                "pending_steps": pending_steps,
                "artifact_index": artifact_index,
                "last_decision": decision.as_dict(),
                "last_action": {
                    "controller_source": CONTROLLER_SOURCE,
                    "skill_name": skill_result.skill_name,
                    "status": skill_result.status.value,
                    "output_artifacts": list(skill_result.output_artifacts),
                },
                "warnings": _append_many(state.get("warnings", []), warnings),
                "blockers": list(state.get("blockers", [])),
            }
        )
        self.store.write_state(self.task_id, state)

    def _update_after_terminal_tool_result(
        self,
        status: AgentTaskStatus,
        decision: ControllerDecision,
        skill_result: SkillExecutionResult,
        errors: list[str],
    ) -> None:
        self._update_state(
            status,
            blockers=errors,
            warnings=skill_result.warnings,
            last_decision=decision,
            last_action={
                "controller_source": CONTROLLER_SOURCE,
                "skill_name": skill_result.skill_name,
                "status": skill_result.status.value,
                "errors": list(skill_result.errors),
            },
        )

    def _update_state(
        self,
        status: AgentTaskStatus,
        *,
        blockers: list[str] | None = None,
        warnings: list[str] | None = None,
        last_decision: ControllerDecision | None = None,
        last_action: dict[str, Any] | None = None,
    ) -> None:
        state = self.store.read_state(self.task_id)
        state["status"] = status.value
        state["current_phase"] = CONTROLLER_SOURCE
        if blockers:
            state["blockers"] = _append_many(state.get("blockers", []), blockers)
        if warnings:
            state["warnings"] = _append_many(state.get("warnings", []), warnings)
        if last_decision is not None:
            state["last_decision"] = last_decision.as_dict()
        if last_action is not None:
            state["last_action"] = dict(last_action)
        self.store.write_state(self.task_id, state)

    def _write_plan_summary(self, status: str, message: str, warnings_or_errors: list[str]) -> None:
        existing = self.store.read_plan(self.task_id)
        lines = [
            "# Plan",
            "",
            "## Native Fallback Controller Status",
            f"- Status: {status}",
            f"- Step index: {self.step_index}",
            f"- Message: {message}",
        ]
        if warnings_or_errors:
            lines.append("- Notes:")
            lines.extend(f"  - {item}" for item in warnings_or_errors)
        lines.append("")
        lines.append("## Previous Plan")
        lines.append(existing)
        self.store.write_plan(self.task_id, "\n".join(lines))


def _store_from_workspace_root(workspace_root: Path, task_id: str) -> ResearchWorkspaceStore:
    if workspace_root.name != task_id:
        raise ValueError("workspace_root must point at the task workspace directory")
    return ResearchWorkspaceStore(workspace_root.parents[2])


def _exists(workspace_root: Path, relative_path: str) -> bool:
    return (workspace_root / relative_path).exists()


def _read_json(workspace_root: Path, relative_path: str) -> Any:
    return json.loads((workspace_root / relative_path).read_text(encoding="utf-8"))


def _missing_input_errors(skill_name: str, missing_inputs: list[str]) -> list[str]:
    errors: list[str] = []
    for path in missing_inputs:
        if skill_name == "map_gaps" and path == LANDSCAPE_JSON_PATH:
            errors.append("missing_landscape_artifact")
        elif skill_name == "generate_candidate_ideas" and path == GAP_MAP_JSON_PATH:
            errors.append("missing_gap_map_artifact")
        elif skill_name == "generate_candidate_ideas":
            errors.append(f"missing_idea_generation_input:{path}")
        elif skill_name == "screen_novelty_feasibility_risk" and path == IDEAS_JSON_PATH:
            errors.append("missing_candidate_ideas_artifact")
        elif skill_name == "screen_novelty_feasibility_risk":
            errors.append(f"missing_screening_input:{path}")
        elif skill_name == "create_experiment_matrix" and path == SCREENING_JSON_PATH:
            errors.append("missing_screening_results_artifact")
        elif skill_name == "create_experiment_matrix" and path == IDEAS_JSON_PATH:
            errors.append("missing_candidate_ideas_artifact")
        elif skill_name == "create_experiment_matrix" and path == GAP_MAP_JSON_PATH:
            errors.append("missing_gap_map_artifact")
        elif skill_name == "create_experiment_matrix" and path == LANDSCAPE_JSON_PATH:
            errors.append("missing_landscape_artifact")
        elif skill_name == "create_experiment_matrix":
            errors.append(f"missing_experiment_matrix_input:{path}")
        elif skill_name == "build_claim_ledger" and path == EXPERIMENT_MATRIX_JSON_PATH:
            errors.append("missing_experiment_matrix_artifact")
        elif skill_name == "build_claim_ledger" and path == SCREENING_JSON_PATH:
            errors.append("missing_screening_results_artifact")
        elif skill_name == "build_claim_ledger" and path == IDEAS_JSON_PATH:
            errors.append("missing_candidate_ideas_artifact")
        elif skill_name == "build_claim_ledger" and path == GAP_MAP_JSON_PATH:
            errors.append("missing_gap_map_artifact")
        elif skill_name == "build_claim_ledger" and path == LANDSCAPE_JSON_PATH:
            errors.append("missing_landscape_artifact")
        elif skill_name == "build_claim_ledger":
            errors.append(f"missing_claim_ledger_input:{path}")
        elif skill_name == "draft_manuscript_section" and path == CLAIM_LEDGER_JSON_PATH:
            errors.append("missing_claim_ledger_artifact")
        elif skill_name == "draft_manuscript_section" and path == EXPERIMENT_MATRIX_JSON_PATH:
            errors.append("missing_experiment_matrix_artifact")
        elif skill_name == "draft_manuscript_section" and path == SCREENING_JSON_PATH:
            errors.append("missing_screening_results_artifact")
        elif skill_name == "draft_manuscript_section" and path == IDEAS_JSON_PATH:
            errors.append("missing_candidate_ideas_artifact")
        elif skill_name == "draft_manuscript_section" and path == GAP_MAP_JSON_PATH:
            errors.append("missing_gap_map_artifact")
        elif skill_name == "draft_manuscript_section" and path == LANDSCAPE_JSON_PATH:
            errors.append("missing_landscape_artifact")
        elif skill_name == "draft_manuscript_section":
            errors.append(f"missing_manuscript_drafting_input:{path}")
        else:
            errors.append(f"missing_input_artifact:{path}")
    return errors


def _append_unique(values: list[str], value: str) -> list[str]:
    result = list(values or [])
    if value not in result:
        result.append(value)
    return result


def _append_many(values: list[str], additions: list[str]) -> list[str]:
    result = list(values or [])
    for value in additions or []:
        if value and value not in result:
            result.append(value)
    return result


__all__ = [
    "CONTROLLER_SOURCE",
    "NativeFallbackStepResult",
    "NativeFallbackStepStatus",
    "PlatformNativeFallbackController",
]
