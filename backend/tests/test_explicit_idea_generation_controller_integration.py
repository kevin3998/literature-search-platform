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
    build_explicit_idea_generation_plan,
    build_explicit_landscape_plan,
    build_minimal_topic_to_evidence_plan,
    read_jsonl_events,
)
from modules.research_agent_controller.skills import execute_evidence_skill
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "explicit_idea_task"


def _workspace(tmp_path: Path, *, plan_kind: str) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    if plan_kind == "minimal":
        plan = build_minimal_topic_to_evidence_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "landscape":
        plan = build_explicit_landscape_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "gap":
        plan = build_explicit_gap_mapping_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "idea":
        plan = build_explicit_idea_generation_plan(TASK_ID, TOPIC).as_dict()
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
                "paper_id": "paper_2",
                "title": "Defect catalysts for alkaline HER",
                "year": 2024,
                "journal": "Example Journal",
                "kind": "text",
                "snippet": "Defect engineering changes adsorption and activity descriptors.",
                "source_path": "paper_2/sections/results.md",
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


def _execute_chain_through_gaps(workspace_root: Path) -> None:
    for skill_name, parameters in [
        ("retrieve_sources", {"topic": TOPIC, "retrieval_budget": 5}),
        ("create_evidence_seeds", {}),
        ("extract_evidence_cards", {"topic": TOPIC}),
        ("enrich_evidence_cards", {"topic": TOPIC}),
        ("rank_evidence", {"retrieval_budget": 5}),
        ("build_minimal_topic_to_evidence_report", {"topic": TOPIC}),
        ("build_landscape", {"topic": TOPIC}),
        ("map_gaps", {"topic": TOPIC}),
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


def test_default_fallback_minimal_chain_still_stops_at_minimal_report(tmp_path: Path) -> None:
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
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()


def test_explicit_landscape_plan_still_stops_at_landscape(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="landscape")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    results = controller.run_until_stop()

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert "build_landscape" in executed
    assert "map_gaps" not in executed
    assert "generate_candidate_ideas" not in executed
    assert (workspace_root / "landscape/literature_landscape.json").exists()
    assert not (workspace_root / "gaps/gap_map.json").exists()
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()


def test_explicit_gap_mapping_plan_still_stops_at_map_gaps(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="gap")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=12,
    )

    results = controller.run_until_stop()

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert executed[-2:] == ["build_landscape", "map_gaps"]
    assert "generate_candidate_ideas" not in executed
    assert (workspace_root / "gaps/gap_map.json").exists()
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()


def test_explicit_idea_generation_plan_executes_generate_candidate_ideas_after_gap_map(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=13,
    )

    results = controller.run_until_stop()

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert executed[-3:] == ["build_landscape", "map_gaps", "generate_candidate_ideas"]
    assert (workspace_root / "ideas/candidate_ideas.json").exists()
    assert (workspace_root / "ideas/candidate_ideas.md").exists()
    assert (workspace_root / "ideas/idea_generation_diagnostics.json").exists()
    ideas = _read_json(workspace_root / "ideas/candidate_ideas.json")
    markdown = (workspace_root / "ideas/candidate_ideas.md").read_text(encoding="utf-8")
    assert ideas["schema_version"] == "candidate_ideas_v1"
    assert ideas["ideas"]
    assert all(idea["gap_basis"]["gap_ids"] for idea in ideas["ideas"])
    assert all(idea["evidence_basis"]["supporting_evidence_ids"] for idea in ideas["ideas"])
    assert all(idea["not_yet_screened"] is True for idea in ideas["ideas"])
    assert all(idea["requires_novelty_screening"] is True for idea in ideas["ideas"])
    assert all(idea["requires_feasibility_screening"] is True for idea in ideas["ideas"])
    assert "## Evidence References" in markdown
    for forbidden in [
        "## Novelty Screening",
        "## Feasibility Screening",
        "## Risk Screening",
        "## Experiment Plan",
        "## Manuscript Draft",
    ]:
        assert forbidden not in markdown
    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    paths = {item["path"] for item in manifest["artifacts"]}
    assert {
        "ideas/candidate_ideas.json",
        "ideas/candidate_ideas.md",
        "ideas/idea_generation_diagnostics.json",
    }.issubset(paths)
    assert any(event.get("skill_name") == "generate_candidate_ideas" for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl"))
    assert any(
        event.get("metadata", {}).get("skill_name") == "generate_candidate_ideas"
        and event.get("metadata", {}).get("controller_source") == "platform_native_fallback"
        for event in read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    )
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    state = _read_json(workspace_root / "state.json")
    assert "generate_candidate_ideas" in state["completed_steps"]
    assert "ideas/candidate_ideas.json" in state["artifact_index"]
    assert "generate_candidate_ideas" in (workspace_root / "plan.md").read_text(encoding="utf-8")


def test_explicit_idea_generation_blocks_when_gap_map_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "generate_candidate_ideas"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_gap_map_artifact" in result.errors


def test_explicit_idea_generation_blocks_when_required_inputs_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    _execute_chain_through_gaps(workspace_root)
    (workspace_root / "landscape/literature_landscape.json").unlink()
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "generate_candidate_ideas"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_idea_generation_input:landscape/literature_landscape.json" in result.errors


def test_explicit_idea_generation_blocks_when_enriched_cards_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    _execute_chain_through_gaps(workspace_root)
    (workspace_root / "evidence/evidence_cards.enriched.json").unlink()
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "generate_candidate_ideas"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_idea_generation_input:evidence/evidence_cards.enriched.json" in result.errors


def test_explicit_idea_generation_blocks_when_selected_evidence_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    _execute_chain_through_gaps(workspace_root)
    (workspace_root / "ranked_evidence/evidence_selection.json").unlink()
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "generate_candidate_ideas"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_idea_generation_input:ranked_evidence/evidence_selection.json" in result.errors


def test_explicit_idea_generation_validation_fails_for_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    _execute_chain_through_gaps(workspace_root)
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )
    controller._determine_next_skill = lambda: "generate_candidate_ideas"
    controller._input_artifacts_for = lambda skill_name: ["retrieval/source_candidate_packet.json"]

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_idea_generation" in result.errors
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()


def test_cli_backed_fake_backend_can_explicitly_request_generate_candidate_ideas(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    _execute_chain_through_gaps(workspace_root)
    envelope = _call_tool(
        "generate_candidate_ideas",
        input_artifacts=[
            "gaps/gap_map.json",
            "gaps/gap_coverage_diagnostics.json",
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        output_artifacts=[
            "ideas/candidate_ideas.json",
            "ideas/candidate_ideas.md",
            "ideas/idea_generation_diagnostics.json",
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
    assert result.skill_result.skill_name == "generate_candidate_ideas"
    assert (workspace_root / "ideas/candidate_ideas.json").exists()
    assert "generate_candidate_ideas" in _read_json(workspace_root / "state.json")["completed_steps"]


def test_cli_backed_fake_backend_rejects_screening_with_raw_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="idea")
    envelope = _call_tool(
        "screen_novelty_feasibility_risk",
        input_artifacts=["retrieval/source_candidate_packet.json"],
        output_artifacts=[
            "screening/idea_screening_results.json",
            "screening/idea_screening_results.md",
            "screening/screening_diagnostics.json",
        ],
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_screening" in result.errors
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_explicit_idea_generation_sources_have_no_real_cli_llm_database_or_workflow_dependency() -> None:
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
