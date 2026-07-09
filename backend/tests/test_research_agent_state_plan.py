from pathlib import Path

import pytest

from modules.research_agent_controller import (
    AgentDecision,
    AgentDecisionType,
    AgentPlan,
    AgentState,
    AgentStep,
    AgentStepStatus,
    AgentTaskStatus,
    ControllerDecision,
    ControllerDecisionType,
    StopCondition,
    ValidationStatus,
)
from modules.research_workspace import ResearchWorkspaceStore


def test_agent_step_serializes_and_rehydrates_with_valid_enums() -> None:
    step = AgentStep(
        step_id="retrieve",
        name="Retrieve source candidates",
        description="Collect local evidence candidates.",
        status=AgentStepStatus.RUNNING,
        skill_name="retrieve_source_candidates",
        required_artifacts=["task.md"],
        produced_artifacts=["retrieval/source_candidates.json"],
        validation_status=ValidationStatus.DEGRADED_WITH_WARNING,
        warnings=["figure coverage missing"],
    )

    data = step.as_dict()

    assert data["status"] == "running"
    assert data["validation_status"] == "degraded_with_warning"
    assert data["skill_name"] == "retrieve_source_candidates"
    assert isinstance(data["created_at"], float)
    assert AgentStep.from_dict(data).as_dict() == data


def test_invalid_agent_step_status_is_rejected() -> None:
    with pytest.raises(ValueError):
        AgentStep(step_id="bad", name="Bad", status="invented")

    with pytest.raises(ValueError):
        AgentStep.from_dict({"step_id": "bad", "name": "Bad", "status": "invented"})


def test_agent_plan_adds_steps_sets_current_and_rejects_duplicates() -> None:
    plan = AgentPlan(
        plan_id="plan_1",
        task_id="task_123",
        title="Topic to evidence",
        goal="Build controller-readable plan.",
        stop_conditions=[StopCondition.ALL_STEPS_COMPLETED, "manual_stop"],
    )
    first = AgentStep(step_id="s1", name="Prepare workspace")
    second = AgentStep(step_id="s2", name="Validate artifacts")

    plan.add_step(first)
    plan.add_step(second)
    plan.set_current_step("s2")

    assert plan.current_step() is second
    assert plan.as_dict()["stop_conditions"] == ["all_steps_completed", "manual_stop"]

    with pytest.raises(ValueError):
        plan.add_step(AgentStep(step_id="s2", name="Duplicate"))

    with pytest.raises(ValueError):
        plan.set_current_step("missing")


def test_agent_plan_updates_step_status_and_supports_mark_helpers() -> None:
    plan = AgentPlan(plan_id="plan_1", task_id="task_123", title="Plan", goal="Goal")
    plan.add_step(AgentStep(step_id="s1", name="One"))
    plan.add_step(AgentStep(step_id="s2", name="Two"))
    plan.add_step(AgentStep(step_id="s3", name="Three"))

    before = plan.steps[0].updated_at
    updated = plan.update_step_status(
        "s1",
        "failed",
        validation_status="failed",
        warning="retry required",
        error="tool timeout",
    )
    plan.mark_step_completed("s2")
    plan.mark_step_skipped("s3", warning="not needed")

    assert updated.status == AgentStepStatus.FAILED
    assert updated.validation_status == ValidationStatus.FAILED
    assert updated.warnings == ["retry required"]
    assert updated.error == "tool timeout"
    assert updated.updated_at >= before
    assert plan.steps[1].status == AgentStepStatus.COMPLETED
    assert plan.steps[2].status == AgentStepStatus.SKIPPED
    assert plan.steps[2].warnings == ["not needed"]


def test_agent_plan_from_dict_rehydrates_nested_steps_and_validates_stop_conditions() -> None:
    plan = AgentPlan(plan_id="plan_1", task_id="task_123", title="Plan", goal="Goal")
    plan.add_step(AgentStep(step_id="s1", name="One"))
    plan.set_current_step("s1")
    data = plan.as_dict()

    rehydrated = AgentPlan.from_dict(data)

    assert rehydrated.current_step().step_id == "s1"
    assert rehydrated.as_dict() == data

    bad = dict(data)
    bad["stop_conditions"] = ["unknown_stop"]
    with pytest.raises(ValueError):
        AgentPlan.from_dict(bad)


def test_agent_state_serializes_rehydrates_and_validates_status() -> None:
    decision = ControllerDecision(
        decision_id="d1",
        task_id="task_123",
        decision_type=AgentDecisionType.CALL_TOOL,
        reason="Need retrieval candidates.",
        target_step_id="s1",
        skill_name="retrieve_source_candidates",
    )
    state = AgentState(
        task_id="task_123",
        status=AgentTaskStatus.RUNNING,
        current_phase="retrieval",
        current_step_id="s1",
        pending_steps=["s1"],
        artifact_index={"task": "task.md"},
        last_decision=decision,
        last_action={"type": "none"},
    )

    data = state.as_dict()

    assert data["status"] == "running"
    assert data["last_decision"]["decision_type"] == "CALL_TOOL"
    assert AgentState.from_dict(data).as_dict() == data

    with pytest.raises(ValueError):
        AgentState(task_id="task_123", status="made_up")


def test_agent_state_record_step_status_keeps_status_lists_exclusive() -> None:
    state = AgentState(task_id="task_123", pending_steps=["s1", "s2"])

    state.record_step_status("s1", AgentStepStatus.RUNNING)
    state.record_step_status("s1", AgentStepStatus.COMPLETED)
    state.record_step_status("s2", AgentStepStatus.FAILED)
    state.record_step_status("s3", AgentStepStatus.SKIPPED)

    assert state.pending_steps == []
    assert state.completed_steps == ["s1"]
    assert state.failed_steps == ["s2"]
    assert state.skipped_steps == ["s3"]


def test_agent_state_upgrades_a1_workspace_state_without_modifying_a1_store(tmp_path: Path) -> None:
    workspace_store = ResearchWorkspaceStore(tmp_path)
    workspace_store.create_workspace("task_123")
    a1_state = workspace_store.read_state("task_123")

    agent_state = AgentState.from_workspace_state(a1_state)

    assert agent_state.task_id == "task_123"
    assert agent_state.status == AgentTaskStatus.INITIALIZED
    assert agent_state.current_phase == "workspace"
    assert agent_state.as_dict()["artifact_index"] == {}


def test_controller_decision_uses_bounded_vocabulary_and_agent_alias() -> None:
    decision = ControllerDecision(
        decision_id="decision_1",
        task_id="task_123",
        decision_type=ControllerDecisionType.VALIDATE_ARTIFACT,
        reason="Validate report artifact before stopping.",
        input_artifacts=["reports/minimal.md"],
        output_artifacts=["audit/validation.json"],
        validation_status="not_validated",
        warnings=["best effort only"],
    )

    data = decision.as_dict()

    assert data["decision_type"] == "VALIDATE_ARTIFACT"
    assert data["validation_status"] == "not_validated"
    assert AgentDecision is ControllerDecision
    assert ControllerDecision.from_dict(data).as_dict() == data

    with pytest.raises(ValueError):
        ControllerDecision(
            decision_id="decision_2",
            task_id="task_123",
            decision_type="FREEFORM_DECISION",
            reason="Should fail.",
        )


def test_invalid_validation_status_and_task_status_are_rejected() -> None:
    with pytest.raises(ValueError):
        AgentStep(step_id="s1", name="One", validation_status="unknown")

    with pytest.raises(ValueError):
        ControllerDecision(
            decision_id="d1",
            task_id="task_123",
            decision_type="STOP_SUCCESS",
            reason="Stop.",
            validation_status="unknown",
        )

    with pytest.raises(ValueError):
        AgentState.from_dict({"task_id": "task_123", "status": "unknown"})


def test_research_agent_controller_has_no_runtime_database_cli_dependencies() -> None:
    sources = Path("backend/modules/research_agent_controller/schemas.py").read_text(encoding="utf-8")

    forbidden = [
        "core.memory_db",
        "sqlite",
        "LiteratureResearchService",
        "cli_backed_controller",
        "native_fallback_controller",
        "Claude Code CLI",
    ]
    for token in forbidden:
        assert token not in sources
