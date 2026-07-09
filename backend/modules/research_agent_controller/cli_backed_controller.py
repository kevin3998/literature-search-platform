"""Minimal mockable CLI-backed controller loop for A7a."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from modules.research_workspace import ResearchWorkspaceStore

from .audit import (
    append_controller_event,
    record_skill_execution_result,
    read_jsonl_events,
)
from .cli_backend import CliControllerBackend, ControllerWorkspaceSnapshot
from .cli_contract import (
    CliDecisionParseResult,
    CliWorkspaceAccessPolicy,
    cli_decision_to_controller_audit_event,
    cli_decision_to_controller_decision,
    cli_violation_to_controller_audit_event,
    parse_cli_output,
)
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
    CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
    validate_claim_ledger_input_artifacts,
)
from .skills.experiment_matrix_contract import validate_experiment_matrix_input_artifacts
from .skills.gap_contract import validate_gap_mapping_input_artifacts
from .skills.idea_contract import validate_idea_generation_input_artifacts
from .skills.manuscript_contract import (
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


class ControllerStepStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    VALIDATION_FAILED = "validation_failed"
    STOP_SUCCESS = "stop_success"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class ControllerStepResult:
    task_id: str
    step_index: int
    status: ControllerStepStatus | str
    parse_result: CliDecisionParseResult | None = None
    decision: ControllerDecision | None = None
    skill_result: SkillExecutionResult | None = None
    validation_results: list[ArtifactValidationResult] = field(default_factory=list)
    stop_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.status, ControllerStepStatus):
            self.status = ControllerStepStatus(self.status)
        self.validation_results = list(self.validation_results or [])
        self.warnings = list(self.warnings or [])
        self.errors = list(self.errors or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step_index": self.step_index,
            "status": self.status.value,
            "parse_result": self.parse_result.as_dict() if self.parse_result else None,
            "decision": self.decision.as_dict() if self.decision else None,
            "skill_result": self.skill_result.as_dict() if self.skill_result else None,
            "validation_results": [result.as_dict() for result in self.validation_results],
            "stop_reason": self.stop_reason,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class ClaudeCodeBackedMinimalController:
    """A7a platform loop using a mockable backend and registered skill wrappers."""

    def __init__(
        self,
        workspace_root: str | Path,
        task_id: str,
        cli_backend: CliControllerBackend,
        registry: SkillRegistry | None = None,
        max_steps: int = 12,
        acquire_evidence_fn: Callable[..., dict[str, Any]] | None = None,
        extractor: Callable[..., dict[str, Any]] | None = None,
        classifier: Callable[..., dict[str, Any]] | None = None,
        llm_client: Any | None = None,
    ):
        self.workspace_root = Path(workspace_root)
        self.task_id = task_id
        self.cli_backend = cli_backend
        self.registry = registry or build_default_skill_registry()
        self.max_steps = max(1, int(max_steps))
        self.acquire_evidence_fn = acquire_evidence_fn
        self.extractor = extractor
        self.classifier = classifier
        self.llm_client = llm_client
        self.step_index = 0
        self.store = _store_from_workspace_root(self.workspace_root, task_id)

    def run_once(self) -> ControllerStepResult:
        current_index = self.step_index
        snapshot = self._snapshot(current_index)
        raw_output = self.cli_backend.next_output(snapshot.as_dict())
        parse_result = parse_cli_output(raw_output, registry=self.registry, policy=self._workspace_policy())
        self.step_index += 1

        if not parse_result.accepted or parse_result.decision is None:
            errors = [violation.violation_type.value for violation in parse_result.violations]
            for violation in parse_result.violations:
                append_controller_event(
                    self.workspace_root,
                    cli_violation_to_controller_audit_event(violation, self.task_id),
                )
            self._update_state(
                AgentTaskStatus.BLOCKED,
                blockers=errors,
                last_action={"step_index": current_index, "parse_result": parse_result.as_dict()},
            )
            self._write_plan_summary(AgentTaskStatus.BLOCKED.value, "CLI decision rejected.", errors)
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.BLOCKED,
                parse_result=parse_result,
                errors=errors,
                stop_reason="contract_violation",
            )

        cli_decision = parse_result.decision
        controller_decision = cli_decision_to_controller_decision(cli_decision)
        append_controller_event(self.workspace_root, cli_decision_to_controller_audit_event(cli_decision))

        if cli_decision.decision_type == AgentDecisionType.STOP_SUCCESS:
            self._update_state(
                AgentTaskStatus.COMPLETED,
                last_decision=controller_decision,
                last_action={"step_index": current_index, "decision_type": "STOP_SUCCESS"},
            )
            self._write_plan_summary(AgentTaskStatus.COMPLETED.value, cli_decision.reason, [])
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.STOP_SUCCESS,
                parse_result=parse_result,
                decision=controller_decision,
                stop_reason=cli_decision.reason,
                warnings=cli_decision.warnings,
            )

        if cli_decision.decision_type == AgentDecisionType.STOP_BLOCKED:
            self._update_state(
                AgentTaskStatus.BLOCKED,
                blockers=[cli_decision.reason],
                last_decision=controller_decision,
                last_action={"step_index": current_index, "decision_type": "STOP_BLOCKED"},
            )
            self._write_plan_summary(AgentTaskStatus.BLOCKED.value, cli_decision.reason, [cli_decision.reason])
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.BLOCKED,
                parse_result=parse_result,
                decision=controller_decision,
                stop_reason=cli_decision.reason,
                warnings=cli_decision.warnings,
            )

        if cli_decision.decision_type != AgentDecisionType.CALL_TOOL or cli_decision.skill_request is None:
            error = f"unsupported_decision_type:{cli_decision.decision_type.value}"
            self._update_state(
                AgentTaskStatus.BLOCKED,
                blockers=[error],
                last_decision=controller_decision,
                last_action={"step_index": current_index, "decision_type": cli_decision.decision_type.value},
            )
            self._write_plan_summary(AgentTaskStatus.BLOCKED.value, error, [error])
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.BLOCKED,
                parse_result=parse_result,
                decision=controller_decision,
                errors=[error],
                stop_reason="unsupported_decision",
            )

        preflight = self._preflight_inputs(cli_decision.skill_request.skill_name, cli_decision.skill_request)
        if preflight is not None and preflight.validation_status == ValidationStatus.FAILED:
            self._update_state(
                AgentTaskStatus.VALIDATION_FAILED,
                blockers=preflight.errors,
                last_decision=controller_decision,
                last_action={"step_index": current_index, "validation": preflight.as_dict()},
            )
            self._write_plan_summary(AgentTaskStatus.VALIDATION_FAILED.value, "Input validation failed.", preflight.errors)
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.VALIDATION_FAILED,
                parse_result=parse_result,
                decision=controller_decision,
                validation_results=[preflight],
                errors=preflight.errors,
                stop_reason="validation_failed",
            )

        execution_input = SkillExecutionInput(
            task_id=self.task_id,
            workspace_root=str(self.workspace_root),
            skill_name=cli_decision.skill_request.skill_name,
            input_artifacts=self._execution_input_artifacts(cli_decision.skill_request.skill_name, cli_decision.skill_request),
            parameters=cli_decision.skill_request.parameters,
            requested_by="cli_backed_minimal_controller",
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
        failed_validations = [result for result in validation_results if result.validation_status == ValidationStatus.FAILED]
        if failed_validations or skill_result.status == SkillExecutionStatus.VALIDATION_FAILED:
            errors = list(skill_result.errors)
            for result in failed_validations:
                errors.extend(result.errors)
            self._update_after_terminal_tool_result(
                AgentTaskStatus.VALIDATION_FAILED,
                controller_decision,
                skill_result,
                errors,
            )
            self._write_plan_summary(AgentTaskStatus.VALIDATION_FAILED.value, skill_result.skill_name, errors)
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.VALIDATION_FAILED,
                parse_result=parse_result,
                decision=controller_decision,
                skill_result=skill_result,
                validation_results=validation_results,
                errors=list(dict.fromkeys(errors)),
                stop_reason="validation_failed",
            )

        if skill_result.status == SkillExecutionStatus.BLOCKED:
            self._update_after_terminal_tool_result(
                AgentTaskStatus.BLOCKED,
                controller_decision,
                skill_result,
                skill_result.errors,
            )
            self._write_plan_summary(AgentTaskStatus.BLOCKED.value, skill_result.skill_name, skill_result.errors)
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.BLOCKED,
                parse_result=parse_result,
                decision=controller_decision,
                skill_result=skill_result,
                validation_results=validation_results,
                errors=list(skill_result.errors),
                stop_reason="skill_blocked",
            )

        if skill_result.status == SkillExecutionStatus.FAILED:
            self._update_after_terminal_tool_result(
                AgentTaskStatus.FAILED,
                controller_decision,
                skill_result,
                skill_result.errors,
            )
            self._write_plan_summary(AgentTaskStatus.FAILED.value, skill_result.skill_name, skill_result.errors)
            return ControllerStepResult(
                task_id=self.task_id,
                step_index=current_index,
                status=ControllerStepStatus.FAILED,
                parse_result=parse_result,
                decision=controller_decision,
                skill_result=skill_result,
                validation_results=validation_results,
                errors=list(skill_result.errors),
                stop_reason="skill_failed",
            )

        self._update_after_success(controller_decision, skill_result)
        self._write_plan_summary(AgentTaskStatus.RUNNING.value, skill_result.skill_name, skill_result.warnings)
        return ControllerStepResult(
            task_id=self.task_id,
            step_index=current_index,
            status=ControllerStepStatus.SUCCESS,
            parse_result=parse_result,
            decision=controller_decision,
            skill_result=skill_result,
            validation_results=validation_results,
            warnings=list(skill_result.warnings),
        )

    def run_until_stop(self) -> list[ControllerStepResult]:
        results: list[ControllerStepResult] = []
        terminal = {
            ControllerStepStatus.BLOCKED,
            ControllerStepStatus.FAILED,
            ControllerStepStatus.VALIDATION_FAILED,
            ControllerStepStatus.STOP_SUCCESS,
        }
        while len(results) < self.max_steps:
            result = self.run_once()
            results.append(result)
            if result.status in terminal:
                return results

        budget_result = ControllerStepResult(
            task_id=self.task_id,
            step_index=self.step_index,
            status=ControllerStepStatus.BUDGET_EXCEEDED,
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
                "event_id": f"controller_budget:{self.task_id}:{time.time()}",
                "task_id": self.task_id,
                "event_type": "controller_event",
                "message": "Controller stopped because max_steps was reached.",
                "errors": ["max_steps_reached"],
                "metadata": {"max_steps": self.max_steps},
            },
        )
        results.append(budget_result)
        return results

    def _snapshot(self, step_index: int) -> ControllerWorkspaceSnapshot:
        return ControllerWorkspaceSnapshot(
            task_id=self.task_id,
            task_md=self.store.read_task(self.task_id),
            plan_md=self.store.read_plan(self.task_id),
            state=self.store.read_state(self.task_id),
            artifact_manifest=self.store.read_artifact_manifest(self.task_id),
            recent_events=self._recent_events(),
            step_index=step_index,
        )

    def _recent_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for path in ("logs/controller_events.jsonl", "logs/tool_calls.jsonl", "logs/validation_results.jsonl"):
            events.extend(read_jsonl_events(self.workspace_root, path)[-3:])
        return events[-9:]

    def _workspace_policy(self) -> CliWorkspaceAccessPolicy:
        return CliWorkspaceAccessPolicy(
            task_id=self.task_id,
            workspace_root=str(self.workspace_root),
            allowed_read_paths=[
                "task.md",
                "plan.md",
                "state.json",
                "audit/",
                "retrieval/",
                "evidence/",
                "ranked_evidence/",
                "reports/",
                "landscape/",
                "gaps/",
                "ideas/",
                "screening/",
                "experiments/",
                "claims/",
                "drafts/",
            ],
            allowed_write_paths=[
                "retrieval/",
                "evidence/",
                "ranked_evidence/",
                "reports/",
                "landscape/",
                "gaps/",
                "ideas/",
                "screening/",
                "experiments/",
                "claims/",
                "drafts/",
                "logs/",
                "audit/",
            ],
            forbidden_paths=[
                "state.json",
                "plan.md",
                "audit/artifact_manifest.json",
            ],
        )

    def _preflight_inputs(self, skill_name: str, request: Any) -> ArtifactValidationResult | None:
        input_artifacts = self._execution_input_artifacts(skill_name, request)
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
            return None
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
            return None
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
            return None
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
            return None
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
            return None
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
            return None
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
        if skill_name != "build_minimal_topic_to_evidence_report":
            return None
        report_inputs = validate_report_inputs(self.workspace_root, self.task_id, input_artifacts)
        if report_inputs.validation_status == ValidationStatus.FAILED:
            return report_inputs
        if input_artifacts == ["ranked_evidence/evidence_selection.json"]:
            selection = validate_ranking_selection_artifact(self.workspace_root, self.task_id, input_artifacts[0])
            if selection.validation_status == ValidationStatus.FAILED:
                return selection
        elif input_artifacts == ["evidence/evidence_cards.enriched.json"]:
            cards = validate_evidence_card_artifact(
                self.workspace_root,
                self.task_id,
                input_artifacts[0],
                enriched=True,
            )
            if cards.validation_status == ValidationStatus.FAILED:
                return cards
        return report_inputs

    def _execution_input_artifacts(self, skill_name: str, request: Any) -> list[str]:
        if request.input_artifacts:
            return list(request.input_artifacts)
        if skill_name == "build_minimal_topic_to_evidence_report":
            if (self.workspace_root / "ranked_evidence/evidence_selection.json").exists():
                return ["ranked_evidence/evidence_selection.json"]
            return ["evidence/evidence_cards.enriched.json"]
        if skill_name == "build_landscape":
            return [
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ]
        if skill_name == "map_gaps":
            return [
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ]
        if skill_name == "generate_candidate_ideas":
            return [
                "gaps/gap_map.json",
                "gaps/gap_coverage_diagnostics.json",
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ]
        if skill_name == "screen_novelty_feasibility_risk":
            return [
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
        if skill_name == "create_experiment_matrix":
            return [
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
        if skill_name == "build_claim_ledger":
            return list(CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS)
        if skill_name == "draft_manuscript_section":
            return list(MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS)
        return []

    def _run_validation_gates(
        self,
        skill_result: SkillExecutionResult,
        execution_input: SkillExecutionInput,
    ) -> list[ArtifactValidationResult]:
        results: list[ArtifactValidationResult] = []
        if skill_result.skill_name == "extract_evidence_cards" and "evidence/evidence_cards.initial.json" in skill_result.output_artifacts:
            results.append(
                validate_evidence_card_artifact(
                    self.workspace_root,
                    self.task_id,
                    "evidence/evidence_cards.initial.json",
                    enriched=False,
                )
            )
        elif skill_result.skill_name == "enrich_evidence_cards" and "evidence/evidence_cards.enriched.json" in skill_result.output_artifacts:
            results.append(
                validate_evidence_card_artifact(
                    self.workspace_root,
                    self.task_id,
                    "evidence/evidence_cards.enriched.json",
                    enriched=True,
                )
            )
        elif skill_result.skill_name == "rank_evidence" and "ranked_evidence/evidence_selection.json" in skill_result.output_artifacts:
            results.append(validate_ranking_selection_artifact(self.workspace_root, self.task_id))
        elif skill_result.skill_name == "build_landscape" and "landscape/literature_landscape.json" in skill_result.output_artifacts:
            results.append(
                ArtifactValidationResult(
                    artifact_id="literature_landscape",
                    artifact_type="landscape",
                    path="landscape/literature_landscape.json",
                    validation_status=ValidationStatus.PASSED,
                    validator_name="landscape_output_gate",
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "map_gaps" and "gaps/gap_map.json" in skill_result.output_artifacts:
            try:
                gap_map = json.loads((self.workspace_root / "gaps/gap_map.json").read_text(encoding="utf-8"))
                markdown = (self.workspace_root / "gaps/gap_map.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["gap_map_output_missing"]
            else:
                errors = validate_gap_map_artifact(gap_map, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="gap_map",
                    artifact_type="gap_map",
                    path="gaps/gap_map.json",
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="gap_map_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "generate_candidate_ideas" and "ideas/candidate_ideas.json" in skill_result.output_artifacts:
            try:
                ideas = json.loads((self.workspace_root / "ideas/candidate_ideas.json").read_text(encoding="utf-8"))
                markdown = (self.workspace_root / "ideas/candidate_ideas.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["candidate_ideas_output_missing"]
            else:
                errors = validate_candidate_ideas_artifact(ideas, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="candidate_ideas",
                    artifact_type="candidate_ideas",
                    path="ideas/candidate_ideas.json",
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="candidate_ideas_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "screen_novelty_feasibility_risk" and "screening/idea_screening_results.json" in skill_result.output_artifacts:
            try:
                screening = json.loads((self.workspace_root / "screening/idea_screening_results.json").read_text(encoding="utf-8"))
                markdown = (self.workspace_root / "screening/idea_screening_results.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["screening_output_missing"]
            else:
                errors = validate_screening_artifact(screening, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="idea_screening",
                    artifact_type="idea_screening",
                    path="screening/idea_screening_results.json",
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="screening_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "create_experiment_matrix" and "experiments/experiment_matrix.json" in skill_result.output_artifacts:
            try:
                experiment_matrix = json.loads((self.workspace_root / "experiments/experiment_matrix.json").read_text(encoding="utf-8"))
                markdown = (self.workspace_root / "experiments/experiment_matrix.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["experiment_matrix_output_missing"]
            else:
                errors = validate_experiment_matrix_artifact(experiment_matrix, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="experiment_matrix",
                    artifact_type="experiment_matrix",
                    path="experiments/experiment_matrix.json",
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="experiment_matrix_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "build_claim_ledger" and "claims/claim_ledger.json" in skill_result.output_artifacts:
            try:
                claim_ledger = json.loads((self.workspace_root / "claims/claim_ledger.json").read_text(encoding="utf-8"))
                markdown = (self.workspace_root / "claims/claim_ledger.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["claim_ledger_output_missing"]
            else:
                errors = validate_claim_ledger_artifact(claim_ledger, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="claim_ledger",
                    artifact_type="claim_ledger",
                    path="claims/claim_ledger.json",
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="claim_ledger_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "draft_manuscript_section" and "drafts/manuscript_section_draft.json" in skill_result.output_artifacts:
            try:
                draft = json.loads((self.workspace_root / "drafts/manuscript_section_draft.json").read_text(encoding="utf-8"))
                markdown = (self.workspace_root / "drafts/manuscript_section_draft.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                errors = ["manuscript_draft_output_missing"]
            else:
                errors = validate_manuscript_draft_artifact(draft, markdown)
            results.append(
                ArtifactValidationResult(
                    artifact_id="manuscript_section_draft",
                    artifact_type="manuscript_section_draft",
                    path="drafts/manuscript_section_draft.json",
                    validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
                    validator_name="manuscript_draft_output_gate",
                    errors=errors,
                    metadata={"output_artifacts": list(skill_result.output_artifacts)},
                    warnings=list(skill_result.warnings),
                )
            )
        elif skill_result.skill_name == "validate_evidence_cards":
            input_path = execution_input.parameters.get("input_path")
            if input_path:
                results.append(
                    validate_evidence_card_artifact(
                        self.workspace_root,
                        self.task_id,
                        str(input_path),
                        enriched=str(input_path).endswith("enriched.json"),
                    )
                )
        results.append(validate_artifact_manifest(self.workspace_root, self.task_id))
        return results

    def _update_after_success(self, decision: ControllerDecision, skill_result: SkillExecutionResult) -> None:
        state = self.store.read_state(self.task_id)
        completed_steps = _append_unique(state.get("completed_steps", []), skill_result.skill_name)
        pending_steps = [step for step in state.get("pending_steps", []) if step != skill_result.skill_name]
        artifact_index = dict(state.get("artifact_index", {}))
        for path in skill_result.output_artifacts:
            artifact_index[path] = f"{skill_result.skill_name}:{path}"
        state.update(
            {
                "status": AgentTaskStatus.RUNNING.value,
                "current_phase": "controller_loop",
                "completed_steps": completed_steps,
                "pending_steps": pending_steps,
                "artifact_index": artifact_index,
                "last_decision": decision.as_dict(),
                "last_action": {
                    "skill_name": skill_result.skill_name,
                    "status": skill_result.status.value,
                    "output_artifacts": list(skill_result.output_artifacts),
                },
                "warnings": _append_many(state.get("warnings", []), skill_result.warnings),
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
        state["current_phase"] = "controller_loop"
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
            "## Controller Status",
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
    "ClaudeCodeBackedMinimalController",
    "ControllerStepResult",
    "ControllerStepStatus",
]
