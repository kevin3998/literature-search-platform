import json
from pathlib import Path

from modules.research_agent_controller import (
    AgentTaskStatus,
    ClaudeCodeBackedMinimalController,
    ControllerStepStatus,
    FakeCliControllerBackend,
    SkillExecutionStatus,
    build_minimal_topic_to_evidence_plan,
    read_jsonl_events,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "large language models in materials discovery"


def _workspace(tmp_path: Path, task_id: str = "task_123") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        task_id,
        task_markdown=f"# Task\n\nResearch topic: {TOPIC}\n",
        plan_markdown="# Plan\n\nInitial workspace plan.\n",
    )
    return tmp_path / "research_agent/research_tasks" / task_id


def _call_tool(skill_name: str, *, input_artifacts=None, output_artifacts=None, parameters=None) -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": "task_123",
        "decision": {
            "decision_type": "CALL_TOOL",
            "reason": f"Run {skill_name}.",
            "skill_request": {
                "skill_name": skill_name,
                "input_artifacts": list(input_artifacts or []),
                "output_artifacts": list(output_artifacts or []),
                "parameters": dict(parameters or {}),
                "reason": f"Run {skill_name}.",
            },
        },
        "notes": [],
        "warnings": [],
    }


def _stop(decision_type: str, reason: str = "Stop.") -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": "task_123",
        "decision": {
            "decision_type": decision_type,
            "reason": reason,
        },
        "notes": [],
        "warnings": [],
    }


def _fake_acquire_evidence(query: str, has_history: bool = False, **options: object) -> dict:
    return {
        "evidence_candidates": [
            {
                "evidence_id": "ev_1",
                "paper_id": "paper_1",
                "title": "LLMs for materials discovery",
                "year": 2025,
                "journal": "Materials AI",
                "kind": "text",
                "snippet": "Large language models can extract synthesis-property relations from papers.",
                "source_path": "literature-data/paper_1/full_text.json",
                "source_locator": {"section": "Results"},
                "relevance_score": 0.91,
            }
        ],
        "expanded_assets": [],
        "query_plan": {"query": query},
        "coverage": {"limit": options.get("limit")},
        "breadth": {"has_history": has_history},
        "warnings": ["asset_retrieval_no_expanded_assets_from_fake"],
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fake_backend_returns_outputs_and_falls_back_to_stop_blocked() -> None:
    backend = FakeCliControllerBackend([_stop("STOP_SUCCESS", "Done.")])

    first = json.loads(backend.next_output({"task_id": "task_123"}))
    second = json.loads(backend.next_output({"task_id": "task_123"}))

    assert first["decision"]["decision_type"] == "STOP_SUCCESS"
    assert second["decision"]["decision_type"] == "STOP_BLOCKED"
    assert len(backend.snapshots) == 2


def test_plan_template_contains_only_minimal_topic_to_evidence_skills() -> None:
    plan = build_minimal_topic_to_evidence_plan("task_123", TOPIC)

    assert [step.skill_name for step in plan.steps] == [
        "retrieve_sources",
        "create_evidence_seeds",
        "extract_evidence_cards",
        "enrich_evidence_cards",
        "rank_evidence",
        "build_minimal_topic_to_evidence_report",
    ]
    assert "build_landscape" not in {step.skill_name for step in plan.steps}


def test_run_once_executes_available_skill_and_updates_state_manifest_and_logs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    backend = FakeCliControllerBackend(
        [
            _call_tool(
                "retrieve_sources",
                output_artifacts=["retrieval/source_candidate_packet.json"],
                parameters={"topic": TOPIC, "retrieval_budget": 5},
            )
        ]
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root=workspace_root,
        task_id="task_123",
        cli_backend=backend,
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.SUCCESS
    assert result.skill_result.status == SkillExecutionStatus.SUCCESS
    assert (workspace_root / "retrieval/source_candidate_packet.json").exists()
    state = _read_json(workspace_root / "state.json")
    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    assert state["status"] == "running"
    assert "retrieve_sources" in state["completed_steps"]
    assert state["artifact_index"]["retrieval/source_candidate_packet.json"] == "retrieve_sources:retrieval/source_candidate_packet.json"
    assert any(item["path"] == "retrieval/source_candidate_packet.json" for item in manifest["artifacts"])
    assert read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    assert "retrieve_sources" in (workspace_root / "plan.md").read_text(encoding="utf-8")


def test_unknown_stub_and_raw_retrieval_report_decisions_are_rejected_without_tool_execution(tmp_path: Path) -> None:
    for envelope, expected in [
        (_call_tool("missing_skill"), "UNREGISTERED_SKILL"),
            (
                _call_tool(
                    "draft_manuscript_section",
                    input_artifacts=["claims/claim_ledger.json"],
                    output_artifacts=["manuscript/section.md"],
                ),
                "DISALLOWED_WRITE_PATH",
            ),
        (
            _call_tool(
                "build_minimal_topic_to_evidence_report",
                input_artifacts=["retrieval/source_candidate_packet.json"],
                output_artifacts=["reports/minimal_topic_to_evidence_report.md"],
                parameters={"topic": TOPIC},
            ),
            "RAW_RETRIEVAL_TO_REPORT",
        ),
    ]:
        workspace_root = _workspace(tmp_path, task_id=f"task_{expected.lower()}")
        envelope["task_id"] = workspace_root.name
        controller = ClaudeCodeBackedMinimalController(
            workspace_root=workspace_root,
            task_id=workspace_root.name,
            cli_backend=FakeCliControllerBackend([envelope]),
        )

        result = controller.run_once()

        assert result.status == ControllerStepStatus.BLOCKED
        assert expected in result.errors
        assert read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
        assert not (workspace_root / "logs/tool_calls.jsonl").exists()


def test_backend_cannot_directly_write_state_plan_or_manifest(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")

    class AttemptingBackend(FakeCliControllerBackend):
        def next_output(self, snapshot: dict) -> str:
            assert snapshot["state"]["status"] == "initialized"
            return json.dumps(_stop("STOP_BLOCKED", "Need manual input."))

    controller = ClaudeCodeBackedMinimalController(
        workspace_root=workspace_root,
        task_id="task_123",
        cli_backend=AttemptingBackend([]),
    )
    result = controller.run_once()

    assert result.status == ControllerStepStatus.BLOCKED
    assert (workspace_root / "state.json").read_text(encoding="utf-8") != before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") != before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest


def test_validation_failed_stops_loop_before_next_backend_decision(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    (workspace_root / "evidence/evidence_cards.initial.json").write_text(
        json.dumps({"cards": [{"seed_id": "seed_missing_required_fields"}]}),
        encoding="utf-8",
    )
    backend = FakeCliControllerBackend(
        [
            _call_tool(
                "validate_evidence_cards",
                input_artifacts=["evidence/evidence_cards.initial.json"],
                output_artifacts=["evidence/evidence_validation.json"],
                parameters={"input_path": "evidence/evidence_cards.initial.json"},
            ),
            _stop("STOP_SUCCESS", "Should not be consumed."),
        ]
    )
    controller = ClaudeCodeBackedMinimalController(workspace_root, "task_123", backend)

    results = controller.run_until_stop()

    assert len(results) == 1
    assert results[0].status == ControllerStepStatus.VALIDATION_FAILED
    assert len(backend.snapshots) == 1
    assert _read_json(workspace_root / "state.json")["status"] == "validation_failed"


def test_stop_success_and_stop_blocked_stop_loop(tmp_path: Path) -> None:
    success_root = _workspace(tmp_path, "task_success")
    success = _stop("STOP_SUCCESS", "Complete.")
    success["task_id"] = "task_success"
    controller = ClaudeCodeBackedMinimalController(success_root, "task_success", FakeCliControllerBackend([success]))
    success_results = controller.run_until_stop()

    blocked_root = _workspace(tmp_path, "task_blocked")
    blocked = _stop("STOP_BLOCKED", "Blocked.")
    blocked["task_id"] = "task_blocked"
    blocked_controller = ClaudeCodeBackedMinimalController(blocked_root, "task_blocked", FakeCliControllerBackend([blocked]))
    blocked_results = blocked_controller.run_until_stop()

    assert success_results[-1].status == ControllerStepStatus.STOP_SUCCESS
    assert _read_json(success_root / "state.json")["status"] == AgentTaskStatus.COMPLETED.value
    assert blocked_results[-1].status == ControllerStepStatus.BLOCKED
    assert _read_json(blocked_root / "state.json")["status"] == AgentTaskStatus.BLOCKED.value


def test_max_steps_prevents_infinite_loop_and_marks_budget_exceeded(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    backend = FakeCliControllerBackend(
        [
            _call_tool("validate_artifact_manifest"),
            _call_tool("validate_artifact_manifest"),
            _call_tool("validate_artifact_manifest"),
        ]
    )
    controller = ClaudeCodeBackedMinimalController(workspace_root, "task_123", backend, max_steps=2)

    results = controller.run_until_stop()

    assert results[-1].status == ControllerStepStatus.BUDGET_EXCEEDED
    assert _read_json(workspace_root / "state.json")["status"] == "budget_exceeded"
    assert len(backend.snapshots) == 2


def test_retrieve_sources_without_acquire_function_enters_blocked_state(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        "task_123",
        FakeCliControllerBackend([_call_tool("retrieve_sources", parameters={"topic": TOPIC})]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.BLOCKED
    assert "missing_acquire_evidence_fn" in result.errors
    assert _read_json(workspace_root / "state.json")["status"] == "blocked"


def test_fake_minimal_topic_to_evidence_chain_runs_to_stop_success(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    outputs = [
        _call_tool("retrieve_sources", output_artifacts=["retrieval/source_candidate_packet.json"], parameters={"topic": TOPIC}),
        _call_tool("create_evidence_seeds"),
        _call_tool("extract_evidence_cards", parameters={"topic": TOPIC}),
        _call_tool("enrich_evidence_cards", parameters={"topic": TOPIC}),
        _call_tool("rank_evidence"),
        _call_tool("build_minimal_topic_to_evidence_report", parameters={"topic": TOPIC}),
        _stop("STOP_SUCCESS", "Minimal evidence report complete."),
    ]
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        "task_123",
        FakeCliControllerBackend(outputs),
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    results = controller.run_until_stop()

    assert results[-1].status == ControllerStepStatus.STOP_SUCCESS
    assert _read_json(workspace_root / "state.json")["status"] == "completed"
    assert (workspace_root / "reports/minimal_topic_to_evidence_report.md").exists()
    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    assert any(item["path"] == "reports/minimal_topic_to_evidence_report.md" for item in manifest["artifacts"])
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 6


def test_a7a_sources_do_not_include_real_cli_database_frontend_or_workflow_dependencies() -> None:
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "backend/modules/research_agent_controller/cli_backend.py",
            "backend/modules/research_agent_controller/cli_backed_controller.py",
            "backend/modules/research_agent_controller/plan_templates.py",
        ]
    )

    forbidden = [
        "subprocess",
        "os.system",
        "\"claude\"",
        "'claude'",
        "native_fallback_controller",
        "core.memory_db",
        "sqlite",
        "frontend",
        "workflow_router",
        "modules.workflow",
    ]
    for token in forbidden:
        assert token not in sources
