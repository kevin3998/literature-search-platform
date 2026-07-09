import json
from pathlib import Path

from modules.research_agent_controller import (
    AgentDecisionType,
    AuditEventType,
    CliContractViolation,
    CliViolationType,
    CliWorkspaceAccessPolicy,
    ControllerDecision,
    build_default_skill_registry,
    cli_decision_to_controller_audit_event,
    cli_decision_to_controller_decision,
    cli_violation_to_controller_audit_event,
    parse_cli_output,
    validate_cli_skill_request,
)
from modules.research_workspace import ResearchWorkspaceStore


def _workspace(tmp_path: Path, task_id: str = "task_123") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(task_id)
    return tmp_path / "research_agent/research_tasks" / task_id


def _policy(workspace_root: Path, task_id: str = "task_123") -> CliWorkspaceAccessPolicy:
    return CliWorkspaceAccessPolicy(
        task_id=task_id,
        workspace_root=str(workspace_root),
        allowed_read_paths=[
            "task.md",
            "plan.md",
            "state.json",
            "audit/artifact_manifest.json",
            "retrieval/",
            "evidence/",
            "ranked_evidence/",
            "reports/",
        ],
        allowed_write_paths=[
            "retrieval/",
            "evidence/",
            "ranked_evidence/",
            "reports/",
            "logs/",
        ],
        forbidden_paths=[
            "state.json",
            "plan.md",
            "audit/artifact_manifest.json",
        ],
    )


def _valid_envelope() -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": "task_123",
        "decision": {
            "decision_type": "CALL_TOOL",
            "reason": "Retrieve source candidates for the topic.",
            "skill_request": {
                "skill_name": "retrieve_sources",
                "input_artifacts": [],
                "output_artifacts": ["retrieval/source_candidate_packet.json"],
                "parameters": {"topic": "large language models in materials discovery"},
                "reason": "Need topic-scoped source candidates.",
            },
        },
        "notes": [],
        "warnings": [],
    }


def _violation_types(result) -> list[CliViolationType]:
    return [violation.violation_type for violation in result.violations]


def test_valid_cli_output_envelope_parses_and_validates(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    result = parse_cli_output(
        json.dumps(_valid_envelope()),
        registry=build_default_skill_registry(),
        policy=_policy(workspace_root),
    )

    assert result.accepted is True
    assert result.envelope.task_id == "task_123"
    assert result.decision.decision_type == AgentDecisionType.CALL_TOOL
    assert result.decision.skill_request.skill_name == "retrieve_sources"
    assert result.violations == []
    assert result.as_dict()["accepted"] is True


def test_non_json_cli_output_returns_unparseable_violation() -> None:
    result = parse_cli_output("not json")

    assert result.accepted is False
    assert _violation_types(result) == [CliViolationType.UNPARSEABLE_OUTPUT]


def test_invalid_decision_type_is_rejected() -> None:
    envelope = _valid_envelope()
    envelope["decision"]["decision_type"] = "DO_WHATEVER"

    result = parse_cli_output(json.dumps(envelope))

    assert result.accepted is False
    assert _violation_types(result) == [CliViolationType.UNKNOWN_DECISION_TYPE]


def test_call_tool_requires_skill_request() -> None:
    envelope = _valid_envelope()
    envelope["decision"].pop("skill_request")

    result = parse_cli_output(json.dumps(envelope))

    assert result.accepted is False
    assert _violation_types(result) == [CliViolationType.MISSING_REQUIRED_FIELD]


def test_stop_decisions_may_omit_skill_request() -> None:
    envelope = _valid_envelope()
    envelope["decision"] = {
        "decision_type": "STOP_SUCCESS",
        "reason": "All planned evidence artifacts are complete.",
    }

    result = parse_cli_output(json.dumps(envelope))

    assert result.accepted is True
    assert result.decision.skill_request is None


def test_unknown_skill_is_rejected(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    envelope = _valid_envelope()
    envelope["decision"]["skill_request"]["skill_name"] = "invent_new_skill"

    result = parse_cli_output(
        json.dumps(envelope),
        registry=build_default_skill_registry(),
        policy=_policy(workspace_root),
    )

    assert result.accepted is False
    assert _violation_types(result) == [CliViolationType.UNREGISTERED_SKILL]


def test_experiment_matrix_request_is_rejected_before_explicit_controller_integration(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    envelope = _valid_envelope()
    envelope["decision"]["skill_request"]["skill_name"] = "create_experiment_matrix"
    envelope["decision"]["skill_request"]["input_artifacts"] = ["screening/idea_screening_results.json"]
    envelope["decision"]["skill_request"]["output_artifacts"] = ["experiments/experiment_matrix.json"]

    result = parse_cli_output(
        json.dumps(envelope),
        registry=build_default_skill_registry(),
        policy=_policy(workspace_root),
    )

    assert result.accepted is False
    assert set(_violation_types(result)).issubset(
        {CliViolationType.DISALLOWED_READ_PATH, CliViolationType.DISALLOWED_WRITE_PATH}
    )
    assert CliViolationType.DISALLOWED_WRITE_PATH in _violation_types(result)


def test_available_skill_request_passes_validation(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    result = parse_cli_output(json.dumps(_valid_envelope()))

    violations = validate_cli_skill_request(
        result.decision.skill_request,
        build_default_skill_registry(),
        _policy(workspace_root),
    )

    assert violations == []


def test_report_skill_rejects_raw_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    envelope = _valid_envelope()
    envelope["decision"]["skill_request"] = {
        "skill_name": "build_minimal_topic_to_evidence_report",
        "input_artifacts": ["retrieval/source_candidate_packet.json"],
        "output_artifacts": ["reports/minimal_topic_to_evidence_report.md"],
        "parameters": {},
        "reason": "Build report from raw retrieval.",
    }

    result = parse_cli_output(
        json.dumps(envelope),
        registry=build_default_skill_registry(),
        policy=_policy(workspace_root),
    )

    assert result.accepted is False
    assert CliViolationType.RAW_RETRIEVAL_TO_REPORT in _violation_types(result)


def test_workspace_access_policy_allows_relative_reads_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    policy = _policy(workspace_root)

    assert policy.is_read_allowed("evidence/evidence_cards.enriched.json") is True
    assert policy.is_read_allowed("/tmp/outside.json") is False
    assert policy.is_read_allowed("../outside.json") is False
    assert policy.is_read_allowed("audit/../../outside.json") is False
    assert policy.validate_artifact_ref("ranked_evidence/evidence_selection.json") == []
    assert policy.validate_artifact_ref("/tmp/outside.json")[0].violation_type == CliViolationType.INVALID_ARTIFACT_REFERENCE


def test_workspace_access_policy_rejects_disallowed_writes(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    policy = _policy(workspace_root)

    assert policy.is_write_allowed("reports/minimal_topic_to_evidence_report.md") is True
    assert policy.is_write_allowed("state.json") is False
    assert policy.is_write_allowed("audit/artifact_manifest.json") is False
    assert policy.is_write_allowed("manuscript/draft.md") is False


def test_shell_database_and_schema_mutation_requests_are_rejected(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    registry = build_default_skill_registry()
    policy = _policy(workspace_root)

    for parameter_key, expected in [
        ("shell_command", CliViolationType.SHELL_COMMAND_NOT_ALLOWED),
        ("database_mutation", CliViolationType.DATABASE_MUTATION_ATTEMPT),
        ("schema_mutation", CliViolationType.SCHEMA_MUTATION_ATTEMPT),
    ]:
        envelope = _valid_envelope()
        envelope["decision"]["skill_request"]["parameters"] = {parameter_key: True}

        result = parse_cli_output(json.dumps(envelope), registry=registry, policy=policy)

        assert result.accepted is False
        assert expected in _violation_types(result)


def test_valid_cli_decision_converts_to_a2_controller_decision(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    result = parse_cli_output(
        json.dumps(_valid_envelope()),
        registry=build_default_skill_registry(),
        policy=_policy(workspace_root),
    )

    decision = cli_decision_to_controller_decision(result.decision)

    assert isinstance(decision, ControllerDecision)
    assert decision.task_id == "task_123"
    assert decision.decision_type == AgentDecisionType.CALL_TOOL
    assert decision.skill_name == "retrieve_sources"
    assert decision.output_artifacts == ["retrieval/source_candidate_packet.json"]
    assert decision.reason == "Retrieve source candidates for the topic."


def test_violation_and_decision_convert_to_controller_audit_events(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    result = parse_cli_output(
        json.dumps(_valid_envelope()),
        registry=build_default_skill_registry(),
        policy=_policy(workspace_root),
    )
    decision_event = cli_decision_to_controller_audit_event(result.decision)
    violation = CliContractViolation(
        violation_type=CliViolationType.DISALLOWED_WRITE_PATH,
        message="Write path is not allowed.",
        path="state.json",
    )
    violation_event = cli_violation_to_controller_audit_event(violation, "task_123")

    assert decision_event.event_type == AuditEventType.CONTROLLER_EVENT
    assert decision_event.task_id == "task_123"
    assert decision_event.decision_type == "CALL_TOOL"
    assert "retrieval/source_candidate_packet.json" in decision_event.artifacts
    assert violation_event.event_type == AuditEventType.CONTROLLER_EVENT
    assert violation_event.errors == ["DISALLOWED_WRITE_PATH"]
    assert violation_event.metadata["violation_type"] == "DISALLOWED_WRITE_PATH"
    assert not (workspace_root / "logs/controller_events.jsonl").exists()


def test_cli_contract_module_has_no_runtime_database_or_skill_execution_dependencies() -> None:
    source = Path("backend/modules/research_agent_controller/cli_contract.py").read_text(encoding="utf-8")

    forbidden = [
        "cli_backed_controller",
        "native_fallback_controller",
        "evidence_tools",
        "execute_evidence_skill",
        "LiteratureResearchService",
        "core.memory_db",
        "sqlite",
        "workflow_router",
        "frontend",
        "OpenAI",
        "DeepSeek",
        "llm_client",
        "subprocess",
        "os.system",
    ]
    for token in forbidden:
        assert token not in source
