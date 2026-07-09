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
    build_explicit_claim_ledger_plan,
    build_explicit_experiment_matrix_plan,
    build_explicit_gap_mapping_plan,
    build_explicit_idea_generation_plan,
    build_explicit_landscape_plan,
    build_explicit_screening_plan,
    build_minimal_topic_to_evidence_plan,
    read_jsonl_events,
)
from modules.research_agent_controller.skills import execute_evidence_skill
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "explicit_claim_ledger_task"


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
    elif plan_kind == "screening":
        plan = build_explicit_screening_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "experiment_matrix":
        plan = build_explicit_experiment_matrix_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "claim_ledger":
        plan = build_explicit_claim_ledger_plan(TASK_ID, TOPIC).as_dict()
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


def _run_native(workspace_root: Path, *, max_steps: int = 20) -> list:
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        llm_client=ScriptedScreeningLLM(),
        max_steps=max_steps,
    )
    return controller.run_until_stop()


def _execute_chain_through_experiment_matrix(workspace_root: Path) -> None:
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
        ("create_experiment_matrix", {"topic": TOPIC}),
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


def _claim_ledger_inputs() -> list[str]:
    return [
        "experiments/experiment_matrix.json",
        "experiments/experiment_matrix_diagnostics.json",
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


def _claim_ledger_outputs() -> list[str]:
    return [
        "claims/claim_ledger.json",
        "claims/claim_ledger.md",
        "claims/claim_ledger_diagnostics.json",
    ]


@pytest.mark.parametrize(
    ("plan_kind", "expected_last", "forbidden_paths"),
    [
        ("minimal", "build_minimal_topic_to_evidence_report", ["landscape/literature_landscape.json", "claims/claim_ledger.json"]),
        ("landscape", "build_landscape", ["gaps/gap_map.json", "claims/claim_ledger.json"]),
        ("gap", "map_gaps", ["ideas/candidate_ideas.json", "claims/claim_ledger.json"]),
        ("idea", "generate_candidate_ideas", ["screening/idea_screening_results.json", "claims/claim_ledger.json"]),
        ("screening", "screen_novelty_feasibility_risk", ["experiments/experiment_matrix.json", "claims/claim_ledger.json"]),
        ("experiment_matrix", "create_experiment_matrix", ["claims/claim_ledger.json"]),
    ],
)
def test_non_claim_ledger_plans_do_not_auto_enter_claim_ledger(
    tmp_path: Path,
    plan_kind: str,
    expected_last: str,
    forbidden_paths: list[str],
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind=plan_kind)

    results = _run_native(workspace_root)

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert executed[-1] == expected_last
    assert "build_claim_ledger" not in executed
    for path in forbidden_paths:
        assert not (workspace_root / path).exists()


def test_explicit_claim_ledger_plan_executes_after_experiment_matrix_and_updates_audit_state_and_plan(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="claim_ledger")

    results = _run_native(workspace_root, max_steps=18)

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert executed[-1] == "build_claim_ledger"
    assert executed.count("build_claim_ledger") == 1
    for path in _claim_ledger_outputs():
        assert (workspace_root / path).exists()

    artifact = _read_json(workspace_root / "claims/claim_ledger.json")
    markdown = (workspace_root / "claims/claim_ledger.md").read_text(encoding="utf-8")
    assert artifact["schema_version"] == "claim_ledger_v1"
    assert artifact["claims"]
    assert all(claim["claim_id"] for claim in artifact["claims"])
    assert all(claim["claim_type"] for claim in artifact["claims"])
    assert all(claim["claim_status"] for claim in artifact["claims"])
    assert all(claim["source_artifacts"] for claim in artifact["claims"])
    assert all(claim["not_a_final_claim"] is True for claim in artifact["claims"])
    assert all(claim["not_experimentally_validated"] is True for claim in artifact["claims"])
    assert all(claim["requires_human_review"] is True for claim in artifact["claims"])
    assert "## Evidence References" in markdown
    for forbidden in ["## Manuscript Draft", "## Abstract", "## Results And Discussion", "## Conclusion", "## Final Claims"]:
        assert forbidden not in markdown

    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    manifest_paths = {item["path"] for item in manifest["artifacts"]}
    assert set(_claim_ledger_outputs()).issubset(manifest_paths)
    assert any(
        event.get("metadata", {}).get("skill_name") == "build_claim_ledger"
        and event.get("metadata", {}).get("controller_source") == "platform_native_fallback"
        for event in read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    )
    assert any(event.get("skill_name") == "build_claim_ledger" for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl"))
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    state = _read_json(workspace_root / "state.json")
    assert "build_claim_ledger" in state["completed_steps"]
    assert "claims/claim_ledger.json" in state["artifact_index"]
    assert "build_claim_ledger" in (workspace_root / "plan.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("missing_path", "expected_error"),
    [
        ("experiments/experiment_matrix.json", "missing_experiment_matrix_artifact"),
        ("screening/idea_screening_results.json", "missing_screening_results_artifact"),
        ("ideas/candidate_ideas.json", "missing_candidate_ideas_artifact"),
        ("gaps/gap_map.json", "missing_gap_map_artifact"),
        ("landscape/literature_landscape.json", "missing_landscape_artifact"),
        ("evidence/evidence_cards.enriched.json", "missing_claim_ledger_input:evidence/evidence_cards.enriched.json"),
        ("ranked_evidence/evidence_selection.json", "missing_claim_ledger_input:ranked_evidence/evidence_selection.json"),
    ],
)
def test_explicit_claim_ledger_blocks_when_required_inputs_are_missing(
    tmp_path: Path,
    missing_path: str,
    expected_error: str,
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="claim_ledger")
    _execute_chain_through_experiment_matrix(workspace_root)
    (workspace_root / missing_path).unlink()
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, acquire_evidence_fn=_fake_acquire_evidence)
    controller._determine_next_skill = lambda: "build_claim_ledger"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert expected_error in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_explicit_claim_ledger_validation_fails_for_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="claim_ledger")
    _execute_chain_through_experiment_matrix(workspace_root)
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, acquire_evidence_fn=_fake_acquire_evidence)
    controller._determine_next_skill = lambda: "build_claim_ledger"
    controller._input_artifacts_for = lambda skill_name: ["retrieval/source_candidate_packet.json"]

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_claim_ledger" in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda matrix: matrix.update({"experiment_candidates": []}), "claim_ledger_requires_experiment_matrix"),
        (
            lambda matrix: matrix["experiment_candidates"][0].update({"evidence_ids": []}),
            "claim_ledger_requires_traceable_evidence_basis",
        ),
        (
            lambda matrix: matrix["experiment_candidates"][0].update({"hypothesis_under_test": "We demonstrate this validated result will improve performance."}),
            "claim_ledger_rejects_validated_result_claim",
        ),
    ],
)
def test_explicit_claim_ledger_validation_fails_for_invalid_experiment_matrix(
    tmp_path: Path,
    mutate,
    expected_error: str,
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="claim_ledger")
    _execute_chain_through_experiment_matrix(workspace_root)
    matrix = _read_json(workspace_root / "experiments/experiment_matrix.json")
    mutate(matrix)
    _write_json(workspace_root / "experiments/experiment_matrix.json", matrix)
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, acquire_evidence_fn=_fake_acquire_evidence)
    controller._determine_next_skill = lambda: "build_claim_ledger"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert expected_error in result.errors
    assert not (workspace_root / "claims/claim_ledger.json").exists()


def test_cli_backed_fake_backend_can_explicitly_request_claim_ledger(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="claim_ledger")
    _execute_chain_through_experiment_matrix(workspace_root)
    envelope = _call_tool(
        "build_claim_ledger",
        input_artifacts=_claim_ledger_inputs(),
        output_artifacts=_claim_ledger_outputs(),
        parameters={"topic": TOPIC},
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.SUCCESS
    assert result.parse_result.accepted is True
    assert result.skill_result.skill_name == "build_claim_ledger"
    assert (workspace_root / "claims/claim_ledger.json").exists()
    assert "build_claim_ledger" in _read_json(workspace_root / "state.json")["completed_steps"]


def test_cli_backed_fake_backend_rejects_manuscript_draft_before_explicit_controller_integration(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="claim_ledger")
    envelope = _call_tool(
        "draft_manuscript_section",
        input_artifacts=["claims/claim_ledger.json"],
        output_artifacts=["manuscript/section.md"],
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.BLOCKED
    assert "DISALLOWED_WRITE_PATH" in result.errors or "OUT_OF_SCOPE_SKILL" in result.errors
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
