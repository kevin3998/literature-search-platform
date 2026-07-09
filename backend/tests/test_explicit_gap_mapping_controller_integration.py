import json
from pathlib import Path

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ControllerStepStatus,
    FakeCliControllerBackend,
    NativeFallbackStepStatus,
    PlatformNativeFallbackController,
    SkillExecutionInput,
    SkillExecutionStatus,
    build_explicit_gap_mapping_plan,
    build_explicit_landscape_plan,
    build_minimal_topic_to_evidence_plan,
    read_jsonl_events,
)
from modules.research_agent_controller.skills import execute_evidence_skill
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "explicit_gap_task"


def _workspace(tmp_path: Path, *, plan_kind: str) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    if plan_kind == "minimal":
        plan = build_minimal_topic_to_evidence_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "landscape":
        plan = build_explicit_landscape_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "gap":
        plan = build_explicit_gap_mapping_plan(TASK_ID, TOPIC).as_dict()
    else:
        raise ValueError(plan_kind)
    store.create_workspace(
        TASK_ID,
        task_markdown=f"# Task\n\nTopic: {TOPIC}\n",
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    return tmp_path / "research_agent/research_tasks" / TASK_ID


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
            },
            {
                "evidence_id": "ev_2",
                "paper_id": "paper_1",
                "title": "Oxygen vacancy engineering for alkaline HER catalysts",
                "year": 2024,
                "journal": "Example Journal",
                "kind": "text",
                "snippet": "Oxygen vacancies improve HER activity under alkaline conditions.",
                "source_path": "paper_1/sections/results.md",
                "source_locator": {"section": "Results"},
                "relevance_score": 0.88,
            },
        ],
        "expanded_assets": [],
        "query_plan": {"query": query},
        "coverage": {"limit": options.get("limit")},
        "breadth": {"has_history": has_history},
        "warnings": [],
    }


def _execute_chain_through_landscape(workspace_root: Path) -> None:
    for skill_name, parameters in [
        ("retrieve_sources", {"topic": TOPIC, "retrieval_budget": 5}),
        ("create_evidence_seeds", {}),
        ("extract_evidence_cards", {"topic": TOPIC}),
        ("enrich_evidence_cards", {"topic": TOPIC}),
        ("rank_evidence", {"retrieval_budget": 5}),
        ("build_minimal_topic_to_evidence_report", {"topic": TOPIC}),
        ("build_landscape", {"topic": TOPIC}),
    ]:
        result = execute_evidence_skill(
            SkillExecutionInput(
                task_id=TASK_ID,
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
        "task_id": TASK_ID,
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


def test_default_fallback_minimal_chain_still_does_not_generate_gap_artifacts(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="minimal")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    results = controller.run_until_stop()

    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert [result.next_skill for result in results if result.next_skill][-1] == "build_minimal_topic_to_evidence_report"
    assert not (workspace_root / "landscape/literature_landscape.json").exists()
    assert not (workspace_root / "gaps/gap_map.json").exists()


def test_explicit_landscape_plan_still_stops_after_landscape_without_gap_mapping(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="landscape")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    results = controller.run_until_stop()

    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert "build_landscape" in [result.next_skill for result in results if result.next_skill]
    assert "map_gaps" not in [result.next_skill for result in results if result.next_skill]
    assert (workspace_root / "landscape/literature_landscape.json").exists()
    assert not (workspace_root / "gaps/gap_map.json").exists()


def test_explicit_gap_mapping_plan_executes_map_gaps_after_landscape(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="gap")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=12,
    )

    results = controller.run_until_stop()

    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    executed = [result.next_skill for result in results if result.next_skill]
    assert executed[-2:] == ["build_landscape", "map_gaps"]
    assert (workspace_root / "gaps/gap_map.json").exists()
    assert (workspace_root / "gaps/gap_map.md").exists()
    assert (workspace_root / "gaps/gap_coverage_diagnostics.json").exists()
    gap_map = _read_json(workspace_root / "gaps/gap_map.json")
    markdown = (workspace_root / "gaps/gap_map.md").read_text(encoding="utf-8")
    assert gap_map["schema_version"] == "gap_map_v1"
    assert all(gap["basis"] for gap in gap_map["gaps"])
    assert all(gap["not_an_idea"] is True for gap in gap_map["gaps"])
    assert "## Evidence References" in markdown
    for forbidden in [
        "## Candidate Ideas",
        "## Novelty Screening",
        "## Feasibility Screening",
        "## Experiment Plan",
        "## Manuscript Draft",
    ]:
        assert forbidden not in markdown

    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    paths = {item["path"] for item in manifest["artifacts"]}
    assert {
        "gaps/gap_map.json",
        "gaps/gap_map.md",
        "gaps/gap_coverage_diagnostics.json",
    }.issubset(paths)
    assert any(event.get("skill_name") == "map_gaps" for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl"))
    assert any(
        event.get("metadata", {}).get("skill_name") == "map_gaps"
        and event.get("metadata", {}).get("controller_source") == "platform_native_fallback"
        for event in read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    )
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    state = _read_json(workspace_root / "state.json")
    assert "map_gaps" in state["completed_steps"]
    assert "gaps/gap_map.json" in state["artifact_index"]
    assert "map_gaps" in (workspace_root / "plan.md").read_text(encoding="utf-8")


def test_explicit_gap_mapping_plan_blocks_when_gap_inputs_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="gap")
    _execute_chain_through_landscape(workspace_root)
    (workspace_root / "landscape/literature_landscape.json").unlink()
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "map_gaps"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_landscape_artifact" in result.errors


def test_explicit_gap_mapping_plan_validation_fails_for_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="gap")
    _execute_chain_through_landscape(workspace_root)
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "map_gaps"
    controller._input_artifacts_for = lambda skill_name: ["retrieval/source_candidate_packet.json"]

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_gap_mapping" in result.errors
    assert not (workspace_root / "gaps/gap_map.json").exists()


def test_cli_backed_fake_backend_can_explicitly_request_map_gaps(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="gap")
    _execute_chain_through_landscape(workspace_root)
    envelope = _call_tool(
        "map_gaps",
        input_artifacts=[
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        output_artifacts=[
            "gaps/gap_map.json",
            "gaps/gap_map.md",
            "gaps/gap_coverage_diagnostics.json",
        ],
        parameters={"topic": TOPIC},
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.SUCCESS
    assert result.skill_result.skill_name == "map_gaps"
    assert (workspace_root / "gaps/gap_map.json").exists()
    assert "map_gaps" in _read_json(workspace_root / "state.json")["completed_steps"]


def test_cli_backed_fake_backend_screening_request_blocks_without_candidate_ideas(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="gap")
    envelope = _call_tool(
        "screen_novelty_feasibility_risk",
        input_artifacts=["ideas/candidate_ideas.json"],
        output_artifacts=["screening/idea_screening.json"],
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.BLOCKED
    assert "missing_candidate_ideas_artifact" in result.errors
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_explicit_gap_mapping_sources_have_no_real_cli_llm_database_or_workflow_dependency() -> None:
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
