"""Controller-readable plan, state, and decision schemas.

A2 defines bounded data contracts only. It does not execute tools, validate a
skill registry, invoke a CLI controller, or persist database state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class AgentTaskStatus(str, Enum):
    INITIALIZED = "initialized"
    RUNNING = "running"
    BLOCKED = "blocked"
    VALIDATION_FAILED = "validation_failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ValidationStatus(str, Enum):
    NOT_VALIDATED = "not_validated"
    PASSED = "passed"
    FAILED = "failed"
    DEGRADED_WITH_WARNING = "degraded_with_warning"
    SKIPPED = "skipped"


class AgentDecisionType(str, Enum):
    CALL_TOOL = "CALL_TOOL"
    VALIDATE_ARTIFACT = "VALIDATE_ARTIFACT"
    RETRY_WITH_ADJUSTED_INPUT = "RETRY_WITH_ADJUSTED_INPUT"
    BRANCH_PLAN = "BRANCH_PLAN"
    SKIP_WITH_WARNING = "SKIP_WITH_WARNING"
    REQUEST_USER_INPUT = "REQUEST_USER_INPUT"
    STOP_SUCCESS = "STOP_SUCCESS"
    STOP_BLOCKED = "STOP_BLOCKED"


ControllerDecisionType = AgentDecisionType


class StopCondition(str, Enum):
    ALL_STEPS_COMPLETED = "all_steps_completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    VALIDATION_FAILED = "validation_failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    USER_INPUT_REQUIRED = "user_input_required"
    TOOL_FAILED = "tool_failed"
    MANUAL_STOP = "manual_stop"


@dataclass
class AgentStep:
    step_id: str
    name: str
    description: str = ""
    status: AgentStepStatus | str = AgentStepStatus.PENDING
    skill_name: str | None = None
    required_artifacts: list[str] = field(default_factory=list)
    produced_artifacts: list[str] = field(default_factory=list)
    validation_status: ValidationStatus | str = ValidationStatus.NOT_VALIDATED
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.status = _coerce_enum(AgentStepStatus, self.status, "status")
        self.validation_status = _coerce_enum(ValidationStatus, self.validation_status, "validation_status")
        self.required_artifacts = list(self.required_artifacts or [])
        self.produced_artifacts = list(self.produced_artifacts or [])
        self.warnings = list(self.warnings or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "skill_name": self.skill_name,
            "required_artifacts": list(self.required_artifacts),
            "produced_artifacts": list(self.produced_artifacts),
            "validation_status": self.validation_status.value,
            "warnings": list(self.warnings),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentStep":
        return cls(
            step_id=data["step_id"],
            name=data["name"],
            description=data.get("description", ""),
            status=data.get("status", AgentStepStatus.PENDING.value),
            skill_name=data.get("skill_name"),
            required_artifacts=list(data.get("required_artifacts", [])),
            produced_artifacts=list(data.get("produced_artifacts", [])),
            validation_status=data.get("validation_status", ValidationStatus.NOT_VALIDATED.value),
            warnings=list(data.get("warnings", [])),
            error=data.get("error"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class AgentPlan:
    plan_id: str
    task_id: str
    title: str
    goal: str
    steps: list[AgentStep | dict[str, Any]] = field(default_factory=list)
    current_step_id: str | None = None
    stop_conditions: list[StopCondition | str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.steps = [step if isinstance(step, AgentStep) else AgentStep.from_dict(step) for step in self.steps]
        self.stop_conditions = [
            _coerce_enum(StopCondition, condition, "stop_conditions") for condition in self.stop_conditions
        ]
        self.warnings = list(self.warnings or [])
        if self.current_step_id is not None and self.current_step() is None:
            raise ValueError(f"unknown current_step_id: {self.current_step_id!r}")

    def add_step(self, step: AgentStep | dict[str, Any]) -> AgentStep:
        step_obj = step if isinstance(step, AgentStep) else AgentStep.from_dict(step)
        if any(existing.step_id == step_obj.step_id for existing in self.steps):
            raise ValueError(f"duplicate step_id: {step_obj.step_id!r}")
        self.steps.append(step_obj)
        self.updated_at = time.time()
        return step_obj

    def set_current_step(self, step_id: str | None) -> None:
        if step_id is not None and self._find_step(step_id) is None:
            raise ValueError(f"unknown step_id: {step_id!r}")
        self.current_step_id = step_id
        self.updated_at = time.time()

    def current_step(self) -> AgentStep | None:
        if self.current_step_id is None:
            return None
        return self._find_step(self.current_step_id)

    def update_step_status(
        self,
        step_id: str,
        status: AgentStepStatus | str,
        *,
        validation_status: ValidationStatus | str | None = None,
        warning: str | None = None,
        error: str | None = None,
    ) -> AgentStep:
        step = self._find_step(step_id)
        if step is None:
            raise ValueError(f"unknown step_id: {step_id!r}")
        step.status = _coerce_enum(AgentStepStatus, status, "status")
        if validation_status is not None:
            step.validation_status = _coerce_enum(ValidationStatus, validation_status, "validation_status")
        if warning:
            step.warnings.append(warning)
        if error is not None:
            step.error = error
        now = time.time()
        step.updated_at = now
        self.updated_at = now
        return step

    def mark_step_completed(self, step_id: str) -> AgentStep:
        return self.update_step_status(step_id, AgentStepStatus.COMPLETED)

    def mark_step_failed(self, step_id: str, *, error: str | None = None) -> AgentStep:
        return self.update_step_status(step_id, AgentStepStatus.FAILED, error=error)

    def mark_step_skipped(self, step_id: str, *, warning: str | None = None) -> AgentStep:
        return self.update_step_status(step_id, AgentStepStatus.SKIPPED, warning=warning)

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "title": self.title,
            "goal": self.goal,
            "steps": [step.as_dict() for step in self.steps],
            "current_step_id": self.current_step_id,
            "stop_conditions": [condition.value for condition in self.stop_conditions],
            "warnings": list(self.warnings),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentPlan":
        return cls(
            plan_id=data["plan_id"],
            task_id=data["task_id"],
            title=data["title"],
            goal=data["goal"],
            steps=list(data.get("steps", [])),
            current_step_id=data.get("current_step_id"),
            stop_conditions=list(data.get("stop_conditions", [])),
            warnings=list(data.get("warnings", [])),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

    def _find_step(self, step_id: str) -> AgentStep | None:
        return next((step for step in self.steps if step.step_id == step_id), None)


@dataclass
class ControllerDecision:
    decision_id: str
    task_id: str
    decision_type: AgentDecisionType | str
    reason: str
    target_step_id: str | None = None
    skill_name: str | None = None
    input_artifacts: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    validation_status: ValidationStatus | str = ValidationStatus.NOT_VALIDATED
    warnings: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.decision_type = _coerce_enum(AgentDecisionType, self.decision_type, "decision_type")
        self.validation_status = _coerce_enum(ValidationStatus, self.validation_status, "validation_status")
        self.input_artifacts = list(self.input_artifacts or [])
        self.output_artifacts = list(self.output_artifacts or [])
        self.warnings = list(self.warnings or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "task_id": self.task_id,
            "decision_type": self.decision_type.value,
            "reason": self.reason,
            "target_step_id": self.target_step_id,
            "skill_name": self.skill_name,
            "input_artifacts": list(self.input_artifacts),
            "output_artifacts": list(self.output_artifacts),
            "validation_status": self.validation_status.value,
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ControllerDecision":
        return cls(
            decision_id=data["decision_id"],
            task_id=data["task_id"],
            decision_type=data["decision_type"],
            reason=data.get("reason", ""),
            target_step_id=data.get("target_step_id"),
            skill_name=data.get("skill_name"),
            input_artifacts=list(data.get("input_artifacts", [])),
            output_artifacts=list(data.get("output_artifacts", [])),
            validation_status=data.get("validation_status", ValidationStatus.NOT_VALIDATED.value),
            warnings=list(data.get("warnings", [])),
            created_at=data.get("created_at", time.time()),
        )


AgentDecision = ControllerDecision


@dataclass
class AgentState:
    task_id: str
    status: AgentTaskStatus | str = AgentTaskStatus.INITIALIZED
    current_phase: str = "planning"
    current_step_id: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
    artifact_index: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    last_decision: ControllerDecision | dict[str, Any] | None = None
    last_action: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.status = _coerce_enum(AgentTaskStatus, self.status, "status")
        self.completed_steps = list(self.completed_steps or [])
        self.pending_steps = list(self.pending_steps or [])
        self.failed_steps = list(self.failed_steps or [])
        self.skipped_steps = list(self.skipped_steps or [])
        self.artifact_index = dict(self.artifact_index or {})
        self.warnings = list(self.warnings or [])
        self.blockers = list(self.blockers or [])
        if isinstance(self.last_decision, dict):
            self.last_decision = ControllerDecision.from_dict(self.last_decision)
        if self.last_action is not None:
            self.last_action = dict(self.last_action)

    def record_step_status(self, step_id: str, status: AgentStepStatus | str) -> None:
        step_status = _coerce_enum(AgentStepStatus, status, "status")
        for values in (self.completed_steps, self.pending_steps, self.failed_steps, self.skipped_steps):
            while step_id in values:
                values.remove(step_id)

        if step_status == AgentStepStatus.PENDING:
            self.pending_steps.append(step_id)
        elif step_status == AgentStepStatus.COMPLETED:
            self.completed_steps.append(step_id)
        elif step_status == AgentStepStatus.FAILED:
            self.failed_steps.append(step_id)
        elif step_status == AgentStepStatus.SKIPPED:
            self.skipped_steps.append(step_id)
        self.updated_at = time.time()

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "current_phase": self.current_phase,
            "current_step_id": self.current_step_id,
            "completed_steps": list(self.completed_steps),
            "pending_steps": list(self.pending_steps),
            "failed_steps": list(self.failed_steps),
            "skipped_steps": list(self.skipped_steps),
            "artifact_index": dict(self.artifact_index),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "last_decision": self.last_decision.as_dict() if self.last_decision else None,
            "last_action": dict(self.last_action) if self.last_action is not None else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        return cls(
            task_id=data["task_id"],
            status=data.get("status", AgentTaskStatus.INITIALIZED.value),
            current_phase=data.get("current_phase", "planning"),
            current_step_id=data.get("current_step_id"),
            completed_steps=list(data.get("completed_steps", [])),
            pending_steps=list(data.get("pending_steps", [])),
            failed_steps=list(data.get("failed_steps", [])),
            skipped_steps=list(data.get("skipped_steps", [])),
            artifact_index=dict(data.get("artifact_index", {})),
            warnings=list(data.get("warnings", [])),
            blockers=list(data.get("blockers", [])),
            last_decision=data.get("last_decision"),
            last_action=data.get("last_action"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )

    @classmethod
    def from_workspace_state(cls, data: dict[str, Any]) -> "AgentState":
        return cls(
            task_id=data["task_id"],
            status=data.get("status", AgentTaskStatus.INITIALIZED.value),
            current_phase=data.get("current_phase", "planning"),
            current_step_id=data.get("current_step_id"),
            completed_steps=list(data.get("completed_steps", [])),
            pending_steps=list(data.get("pending_steps", [])),
            failed_steps=list(data.get("failed_steps", [])),
            skipped_steps=list(data.get("skipped_steps", [])),
            artifact_index=dict(data.get("artifact_index", {})),
            warnings=list(data.get("warnings", [])),
            blockers=list(data.get("blockers", [])),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


def _coerce_enum(enum_cls: type[Enum], value: Enum | str, field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ValueError(f"invalid {field_name}: {value!r}; expected one of: {allowed}") from exc
