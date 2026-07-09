import json
from pathlib import Path

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ControllerStepStatus,
    FakeCliControllerBackend,
    NativeFallbackStepStatus,
    PlatformNativeFallbackController,
    SkillExecutionStatus,
    build_default_skill_registry,
    build_explicit_landscape_plan,
    build_minimal_topic_to_evidence_plan,
    read_jsonl_events,
)
from modules.research_agent_controller.skills import execute_evidence_skill
from modules.research_agent_controller.skill_registry import SkillExecutionInput
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"


def _workspace(tmp_path: Path, task_id: str = "explicit_landscape_task", *, explicit_plan: bool = False) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    plan = (
        build_explicit_landscape_plan(task_id, TOPIC).as_dict()
        if explicit_plan
        else build_minimal_topic_to_evidence_plan(task_id, TOPIC).as_dict()
    )
    plan_markdown = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True)
    store.create_workspace(
        task_id,
        task_markdown=f"# Task\n\nTopic: {TOPIC}\n",
        plan_markdown=plan_markdown,
    )
    return tmp_path / "research_agent/research_tasks" / task_id


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fake_acquire_evidence(query: str, has_history: bool = False, **options: object) -> dict:
    return {
        "evidence_candidates": [
            {
                "evidence_id": "ev_1",
                "paper_id": "paper_1",
                "title": "Oxygen vacancy engineering for alkaline HER catalysts",
                "year": 2024,
                "journal": "Example Journal",
                "kind": "text",
                "snippet": "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
                "source_path": "paper_1/sections/results.md",
                "source_locator": {"section": "Results"},
                "relevance_score": 0.91,
            }
        ],
        "expanded_assets": [],
        "query_plan": {"query": query},
        "coverage": {"limit": options.get("limit")},
        "breadth": {"has_history": has_history},
        "warnings": [],
    }


def _execute_minimal_chain(workspace_root: Path, task_id: str = "explicit_landscape_task") -> None:
    for skill_name, parameters in [
        ("retrieve_sources", {"topic": TOPIC, "retrieval_budget": 5}),
        ("create_evidence_seeds", {}),
        ("extract_evidence_cards", {"topic": TOPIC}),
        ("enrich_evidence_cards", {"topic": TOPIC}),
        ("rank_evidence", {"retrieval_budget": 5}),
        ("build_minimal_topic_to_evidence_report", {"topic": TOPIC}),
    ]:
        result = execute_evidence_skill(
            SkillExecutionInput(
                task_id=task_id,
                workspace_root=str(workspace_root),
                skill_name=skill_name,
                parameters=parameters,
            ),
            acquire_evidence_fn=_fake_acquire_evidence,
        )
        assert result.status == SkillExecutionStatus.SUCCESS


def _call_tool(skill_name: str, *, input_artifacts=None, output_artifacts=None, parameters=None) -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": "explicit_landscape_task",
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


def test_default_fallback_still_stops_at_minimal_report_without_landscape(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, explicit_plan=False)
    controller = PlatformNativeFallbackController(
        workspace_root,
        "explicit_landscape_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    results = controller.run_until_stop()

    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert [result.next_skill for result in results if result.next_skill][-1] == "build_minimal_topic_to_evidence_report"
    assert not (workspace_root / "landscape/literature_landscape.json").exists()
    assert "build_landscape" not in _read_json(workspace_root / "state.json")["completed_steps"]


def test_explicit_landscape_plan_executes_build_landscape_after_minimal_report(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, explicit_plan=True)
    controller = PlatformNativeFallbackController(
        workspace_root,
        "explicit_landscape_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    results = controller.run_until_stop()

    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert "build_landscape" in [result.next_skill for result in results if result.next_skill]
    assert (workspace_root / "landscape/literature_landscape.json").exists()
    assert (workspace_root / "landscape/literature_landscape.md").exists()
    assert (workspace_root / "landscape/landscape_coverage_diagnostics.json").exists()
    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    paths = {item["path"] for item in manifest["artifacts"]}
    assert "landscape/literature_landscape.json" in paths
    assert "landscape/literature_landscape.md" in paths
    assert "landscape/landscape_coverage_diagnostics.json" in paths
    assert any(event.get("skill_name") == "build_landscape" for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl"))
    assert any(event.get("metadata", {}).get("skill_name") == "build_landscape" for event in read_jsonl_events(workspace_root, "logs/controller_events.jsonl"))
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    state = _read_json(workspace_root / "state.json")
    assert "build_landscape" in state["completed_steps"]
    assert "build_landscape" in (workspace_root / "plan.md").read_text(encoding="utf-8")


def test_explicit_landscape_plan_blocks_when_inputs_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, explicit_plan=True)
    controller = PlatformNativeFallbackController(
        workspace_root,
        "explicit_landscape_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "build_landscape"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_input_artifact:evidence/evidence_cards.enriched.json" in result.errors


def test_explicit_landscape_plan_rejects_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, explicit_plan=True)
    _execute_minimal_chain(workspace_root)
    controller = PlatformNativeFallbackController(
        workspace_root,
        "explicit_landscape_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
    )
    controller._determine_next_skill = lambda: "build_landscape"
    controller._input_artifacts_for = lambda skill_name: ["retrieval/source_candidate_packet.json"]

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_landscape" in result.errors
    assert not (workspace_root / "landscape/literature_landscape.json").exists()


def test_cli_backed_fake_backend_can_explicitly_request_build_landscape(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, explicit_plan=True)
    _execute_minimal_chain(workspace_root)
    envelope = _call_tool(
        "build_landscape",
        input_artifacts=[
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        output_artifacts=[
            "landscape/literature_landscape.json",
            "landscape/literature_landscape.md",
            "landscape/landscape_coverage_diagnostics.json",
        ],
        parameters={"topic": TOPIC},
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        "explicit_landscape_task",
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.SUCCESS
    assert result.skill_result.skill_name == "build_landscape"
    assert (workspace_root / "landscape/literature_landscape.json").exists()
    assert "build_landscape" in _read_json(workspace_root / "state.json")["completed_steps"]


def test_cli_backed_fake_backend_screening_request_blocks_without_candidate_ideas(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, explicit_plan=True)
    envelope = _call_tool(
        "screen_novelty_feasibility_risk",
        input_artifacts=["ideas/candidate_ideas.json"],
        output_artifacts=["screening/idea_screening.json"],
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        "explicit_landscape_task",
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.BLOCKED
    assert "missing_candidate_ideas_artifact" in result.errors
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_explicit_landscape_sources_have_no_real_cli_llm_database_or_workflow_dependency() -> None:
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "backend/modules/research_agent_controller/native_fallback_controller.py",
            "backend/modules/research_agent_controller/cli_backed_controller.py",
            "backend/modules/research_agent_controller/plan_templates.py",
        ]
    )
    forbidden = [
        "RealClaudeCodeCliBackend",
        "subprocess",
        "os.system",
        "LiteratureResearchService",
        "core.memory_db",
        "sqlite",
        "OpenAI",
        "DeepSeek",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in sources
