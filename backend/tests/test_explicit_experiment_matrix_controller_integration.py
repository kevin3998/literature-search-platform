import json
from pathlib import Path

import pytest

from screening_v2_helpers import ScriptedScreeningLLM

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ControllerStepStatus,
    FakeCliControllerBackend,
    NativeFallbackStepStatus,
    PlatformNativeFallbackController,
    SkillExecutionInput,
    SkillExecutionStatus,
    build_explicit_experiment_matrix_plan,
    build_explicit_screening_plan,
    build_minimal_topic_to_evidence_plan,
    read_jsonl_events,
)
from modules.research_agent_controller.skills import execute_evidence_skill
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "explicit_experiment_matrix_task"


def _workspace(tmp_path: Path, *, plan_kind: str) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    if plan_kind == "minimal":
        plan = build_minimal_topic_to_evidence_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "screening":
        plan = build_explicit_screening_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "experiment_matrix":
        plan = build_explicit_experiment_matrix_plan(TASK_ID, TOPIC).as_dict()
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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


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


def _execute_chain_through_screening(workspace_root: Path) -> None:
    for skill_name, parameters in [
        ("retrieve_sources", {"topic": TOPIC, "retrieval_budget": 5}),
        ("create_evidence_seeds", {}),
        ("extract_evidence_cards", {"topic": TOPIC}),
        ("enrich_evidence_cards", {"topic": TOPIC}),
        ("rank_evidence", {"retrieval_budget": 5}),
        ("build_minimal_topic_to_evidence_report", {"topic": TOPIC}),
        ("build_landscape", {"topic": TOPIC}),
        ("map_gaps", {"topic": TOPIC}),
        ("generate_candidate_ideas", {"topic": TOPIC}),
        ("screen_novelty_feasibility_risk", {"topic": TOPIC}),
    ]:
        result = execute_evidence_skill(
            SkillExecutionInput(
                task_id=TASK_ID,
                workspace_root=str(workspace_root),
                skill_name=skill_name,
                parameters=parameters,
            ),
            acquire_evidence_fn=_fake_acquire_evidence,
            llm_client=ScriptedScreeningLLM() if skill_name == "screen_novelty_feasibility_risk" else None,
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


def _experiment_matrix_inputs() -> list[str]:
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


def _experiment_matrix_outputs() -> list[str]:
    return [
        "experiments/experiment_matrix.json",
        "experiments/experiment_matrix.md",
        "experiments/experiment_matrix_diagnostics.json",
    ]


def test_default_minimal_and_explicit_screening_plans_do_not_auto_enter_experiment_matrix(tmp_path: Path) -> None:
    minimal_root = _workspace(tmp_path / "minimal", plan_kind="minimal")
    minimal = PlatformNativeFallbackController(
        minimal_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )
    minimal_results = minimal.run_until_stop()
    minimal_executed = [result.next_skill for result in minimal_results if result.next_skill]

    assert minimal_results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert minimal_executed[-1] == "build_minimal_topic_to_evidence_report"
    assert "create_experiment_matrix" not in minimal_executed
    assert not (minimal_root / "experiments/experiment_matrix.json").exists()

    screening_root = _workspace(tmp_path / "screening", plan_kind="screening")
    screening = PlatformNativeFallbackController(
        screening_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        llm_client=ScriptedScreeningLLM(),
        max_steps=14,
    )
    screening_results = screening.run_until_stop()
    screening_executed = [result.next_skill for result in screening_results if result.next_skill]

    assert screening_results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert screening_executed[-1] == "screen_novelty_feasibility_risk"
    assert "create_experiment_matrix" not in screening_executed
    assert (screening_root / "screening/idea_screening_results.json").exists()
    assert not (screening_root / "experiments/experiment_matrix.json").exists()


def test_explicit_experiment_matrix_plan_executes_after_screening_and_updates_audit_state_and_plan(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="experiment_matrix")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        llm_client=ScriptedScreeningLLM(),
        max_steps=16,
    )

    results = controller.run_until_stop()

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert executed[-1] == "create_experiment_matrix"
    assert executed.count("create_experiment_matrix") == 1
    for path in _experiment_matrix_outputs():
        assert (workspace_root / path).exists()

    artifact = _read_json(workspace_root / "experiments/experiment_matrix.json")
    markdown = (workspace_root / "experiments/experiment_matrix.md").read_text(encoding="utf-8")
    assert artifact["schema_version"] == "experiment_matrix_v1"
    assert artifact["experiment_candidates"]
    candidate = artifact["experiment_candidates"][0]
    assert candidate["source_idea_id"]
    assert candidate["screening_basis"]
    assert candidate["gap_ids"] and candidate["evidence_ids"]
    assert candidate["not_a_protocol"] is True
    assert candidate["not_a_validated_claim"] is True
    assert candidate["requires_expert_review"] is True
    assert all(variable["not_a_stepwise_instruction"] is True for variable in candidate["design_variables"])
    assert "## Evidence References" in markdown
    for forbidden in [
        "## Experimental Protocol",
        "## Step-by-step Procedure",
        "## Synthesis Recipe",
        "## Safety Protocol",
        "## Manuscript Draft",
        "## Final Claims",
    ]:
        assert forbidden not in markdown

    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    manifest_paths = {item["path"] for item in manifest["artifacts"]}
    assert set(_experiment_matrix_outputs()).issubset(manifest_paths)
    assert any(
        event.get("metadata", {}).get("skill_name") == "create_experiment_matrix"
        and event.get("metadata", {}).get("controller_source") == "platform_native_fallback"
        for event in read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    )
    assert any(event.get("skill_name") == "create_experiment_matrix" for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl"))
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    state = _read_json(workspace_root / "state.json")
    assert "create_experiment_matrix" in state["completed_steps"]
    assert "experiments/experiment_matrix.json" in state["artifact_index"]
    assert "create_experiment_matrix" in (workspace_root / "plan.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("missing_path", "expected_error"),
    [
        ("screening/idea_screening_results.json", "missing_screening_results_artifact"),
        ("ideas/candidate_ideas.json", "missing_candidate_ideas_artifact"),
        ("gaps/gap_map.json", "missing_gap_map_artifact"),
        ("landscape/literature_landscape.json", "missing_landscape_artifact"),
        ("evidence/evidence_cards.enriched.json", "missing_experiment_matrix_input:evidence/evidence_cards.enriched.json"),
        ("ranked_evidence/evidence_selection.json", "missing_experiment_matrix_input:ranked_evidence/evidence_selection.json"),
    ],
)
def test_explicit_experiment_matrix_blocks_when_required_inputs_are_missing(
    tmp_path: Path,
    missing_path: str,
    expected_error: str,
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="experiment_matrix")
    _execute_chain_through_screening(workspace_root)
    (workspace_root / missing_path).unlink()
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, max_steps=1)
    controller._determine_next_skill = lambda: "create_experiment_matrix"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert expected_error in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_explicit_experiment_matrix_validation_fails_for_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="experiment_matrix")
    _execute_chain_through_screening(workspace_root)
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, max_steps=1)
    controller._determine_next_skill = lambda: "create_experiment_matrix"
    controller._input_artifacts_for = lambda skill_name: ["retrieval/source_candidate_packet.json"]

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_experiment_matrix" in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda screening: screening.update({"screened_ideas": []}), "experiment_matrix_requires_screened_ideas"),
        (
            lambda screening: (
                screening["screened_ideas"][0].update({"gap_ids": []}),
                screening["screened_ideas"][0].update({"evidence_ids": []}),
            ),
            "experiment_matrix_requires_gap_and_evidence_basis",
        ),
        (
            lambda screening: screening["screened_ideas"][0]["external_novelty_search"].update({"status": "performed"}),
            "external_novelty_search_status_must_be_not_performed:0",
        ),
    ],
)
def test_explicit_experiment_matrix_validation_fails_for_invalid_screening(
    tmp_path: Path,
    mutate,
    expected_error: str,
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="experiment_matrix")
    _execute_chain_through_screening(workspace_root)
    screening = _read_json(workspace_root / "screening/idea_screening_results.json")
    mutate(screening)
    _write_json(workspace_root / "screening/idea_screening_results.json", screening)
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, max_steps=1)
    controller._determine_next_skill = lambda: "create_experiment_matrix"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert expected_error in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_cli_backed_fake_backend_can_explicitly_request_experiment_matrix(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="experiment_matrix")
    _execute_chain_through_screening(workspace_root)
    envelope = _call_tool(
        "create_experiment_matrix",
        input_artifacts=_experiment_matrix_inputs(),
        output_artifacts=_experiment_matrix_outputs(),
        parameters={"topic": TOPIC},
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
        llm_client=ScriptedScreeningLLM(),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.SUCCESS
    assert result.parse_result.accepted is True
    assert result.skill_result.skill_name == "create_experiment_matrix"
    assert (workspace_root / "experiments/experiment_matrix.json").exists()
    assert "create_experiment_matrix" in _read_json(workspace_root / "state.json")["completed_steps"]


def test_cli_backed_fake_backend_explicit_claim_ledger_request_blocks_without_inputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="experiment_matrix")
    envelope = _call_tool(
        "build_claim_ledger",
        input_artifacts=["experiments/experiment_matrix.json"],
        output_artifacts=["claims/claim_ledger.json"],
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.BLOCKED
    assert result.parse_result.accepted is True
    assert result.skill_result.skill_name == "build_claim_ledger"
    assert "missing_experiment_matrix_artifact" in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_experiment_matrix_controller_sources_have_no_real_cli_llm_database_or_workflow_dependency() -> None:
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
