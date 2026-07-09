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
    build_explicit_manuscript_scaffold_plan,
    build_explicit_screening_plan,
    build_minimal_topic_to_evidence_plan,
    load_artifact_manifest,
    read_jsonl_events,
)
from modules.research_agent_controller.skills import execute_evidence_skill
from modules.research_agent_controller.skills.manuscript_contract import (
    MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
    MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "explicit_manuscript_task"


def _workspace(tmp_path: Path, *, plan_kind: str) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    builders = {
        "minimal": build_minimal_topic_to_evidence_plan,
        "landscape": build_explicit_landscape_plan,
        "gap": build_explicit_gap_mapping_plan,
        "idea": build_explicit_idea_generation_plan,
        "screening": build_explicit_screening_plan,
        "experiment_matrix": build_explicit_experiment_matrix_plan,
        "claim_ledger": build_explicit_claim_ledger_plan,
        "manuscript": build_explicit_manuscript_scaffold_plan,
    }
    plan = builders[plan_kind](TASK_ID, TOPIC).as_dict()
    store.create_workspace(
        TASK_ID,
        task_markdown=f"# Task\n\nTopic: {TOPIC}\n",
        plan_markdown=json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
    )
    return tmp_path / "research_agent/research_tasks" / TASK_ID


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
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


def _run_native(workspace_root: Path, *, max_steps: int = 24) -> list:
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        llm_client=ScriptedScreeningLLM(),
        max_steps=max_steps,
    )
    return controller.run_until_stop()


def _execution(workspace_root: Path, skill_name: str, parameters: dict | None = None) -> SkillExecutionInput:
    return SkillExecutionInput(
        task_id=TASK_ID,
        workspace_root=str(workspace_root),
        skill_name=skill_name,
        parameters=dict(parameters or {}),
    )


def _execute_chain_through_claim_ledger(workspace_root: Path) -> None:
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
        ("build_claim_ledger", {"topic": TOPIC}),
    ]:
        result = execute_evidence_skill(
            _execution(workspace_root, skill_name, parameters),
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


@pytest.mark.parametrize(
    ("plan_kind", "expected_last", "forbidden_paths"),
    [
        ("minimal", "build_minimal_topic_to_evidence_report", ["landscape/literature_landscape.json", "drafts/manuscript_section_draft.json"]),
        ("landscape", "build_landscape", ["gaps/gap_map.json", "drafts/manuscript_section_draft.json"]),
        ("gap", "map_gaps", ["ideas/candidate_ideas.json", "drafts/manuscript_section_draft.json"]),
        ("idea", "generate_candidate_ideas", ["screening/idea_screening_results.json", "drafts/manuscript_section_draft.json"]),
        ("screening", "screen_novelty_feasibility_risk", ["experiments/experiment_matrix.json", "drafts/manuscript_section_draft.json"]),
        ("experiment_matrix", "create_experiment_matrix", ["claims/claim_ledger.json", "drafts/manuscript_section_draft.json"]),
        ("claim_ledger", "build_claim_ledger", ["drafts/manuscript_section_draft.json"]),
    ],
)
def test_non_manuscript_plans_do_not_auto_enter_manuscript_drafting(
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
    assert "draft_manuscript_section" not in executed
    for path in forbidden_paths:
        assert not (workspace_root / path).exists()


def test_explicit_manuscript_scaffold_plan_executes_after_claim_ledger_and_updates_audit_state_and_plan(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="manuscript")

    results = _run_native(workspace_root)

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert executed[-1] == "draft_manuscript_section"
    assert executed.count("draft_manuscript_section") == 1
    for path in MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS:
        assert (workspace_root / path).exists()

    artifact = _read_json(workspace_root / "drafts/manuscript_section_draft.json")
    markdown = (workspace_root / "drafts/manuscript_section_draft.md").read_text(encoding="utf-8")
    assert artifact["schema_version"] == "manuscript_section_draft_v1"
    assert artifact["draft_id"]
    assert artifact["claim_ledger_id"]
    assert artifact["experiment_matrix_id"]
    assert artifact["screening_id"]
    assert artifact["idea_set_id"]
    assert artifact["gap_map_id"]
    assert artifact["landscape_id"]
    assert artifact["draft_blocks"]
    assert all(block["block_id"] and block["block_type"] and block["text"] for block in artifact["draft_blocks"])
    assert all(block["claim_ids"] for block in artifact["draft_blocks"] if block["block_type"] not in {"transition", "caution"})
    assert any(block["evidence_ids"] for block in artifact["draft_blocks"])
    assert all(block["requires_human_review"] is True for block in artifact["draft_blocks"])
    assert all(block["not_final_text"] is True for block in artifact["draft_blocks"])
    assert all(block["not_peer_reviewed"] is True for block in artifact["draft_blocks"])
    assert all(block["not_experimentally_validated"] is True for block in artifact["draft_blocks"])
    assert artifact["citation_map"]
    assert all(item["claim_id"] and item["evidence_ids"] and item["source_paper_ids"] for item in artifact["citation_map"])
    assert artifact["unsupported_claims"]
    assert "## Evidence References" in markdown
    for forbidden in ["## Final Abstract", "## Final Results", "## Final Discussion", "## Final Conclusion", "## Final Claims", "## Submission-Ready Manuscript"]:
        assert forbidden not in markdown

    manifest_paths = {artifact.path for artifact in load_artifact_manifest(workspace_root, TASK_ID).artifacts}
    assert set(MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS).issubset(manifest_paths)
    assert any(
        event.get("metadata", {}).get("skill_name") == "draft_manuscript_section"
        and event.get("metadata", {}).get("controller_source") == "platform_native_fallback"
        for event in read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    )
    assert any(event.get("skill_name") == "draft_manuscript_section" for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl"))
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    state = _read_json(workspace_root / "state.json")
    assert "draft_manuscript_section" in state["completed_steps"]
    assert "drafts/manuscript_section_draft.json" in state["artifact_index"]
    assert "draft_manuscript_section" in (workspace_root / "plan.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("missing_path", "expected_error"),
    [
        ("claims/claim_ledger.json", "missing_claim_ledger_artifact"),
        ("experiments/experiment_matrix.json", "missing_experiment_matrix_artifact"),
        ("screening/idea_screening_results.json", "missing_screening_results_artifact"),
        ("ideas/candidate_ideas.json", "missing_candidate_ideas_artifact"),
        ("gaps/gap_map.json", "missing_gap_map_artifact"),
        ("landscape/literature_landscape.json", "missing_landscape_artifact"),
        ("evidence/evidence_cards.enriched.json", "missing_manuscript_drafting_input:evidence/evidence_cards.enriched.json"),
        ("ranked_evidence/evidence_selection.json", "missing_manuscript_drafting_input:ranked_evidence/evidence_selection.json"),
    ],
)
def test_explicit_manuscript_drafting_blocks_when_required_inputs_are_missing(
    tmp_path: Path,
    missing_path: str,
    expected_error: str,
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="manuscript")
    _execute_chain_through_claim_ledger(workspace_root)
    (workspace_root / missing_path).unlink()
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, acquire_evidence_fn=_fake_acquire_evidence)
    controller._determine_next_skill = lambda: "draft_manuscript_section"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert expected_error in result.errors
    assert not (workspace_root / "drafts/manuscript_section_draft.json").exists()


def test_explicit_manuscript_drafting_validation_fails_for_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="manuscript")
    _execute_chain_through_claim_ledger(workspace_root)
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, acquire_evidence_fn=_fake_acquire_evidence)
    controller._input_artifacts_for = lambda skill_name: ["retrieval/source_candidate_packet.json"]

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_manuscript_drafting" in result.errors
    assert not (workspace_root / "drafts/manuscript_section_draft.json").exists()


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda ledger: ledger.update({"claims": []}), "manuscript_drafting_requires_claim_ledger"),
        (
            lambda ledger: ledger["claims"][0].update({"evidence_ids": [], "source_artifacts": []}),
            "manuscript_drafting_requires_traceable_claims",
        ),
        (
            lambda ledger: ledger["claims"][0].update({"claim_text": "We demonstrate this validated result is publication-ready."}),
            "manuscript_drafting_rejects_unvalidated_claims",
        ),
    ],
)
def test_explicit_manuscript_drafting_validation_fails_for_invalid_claim_ledger(
    tmp_path: Path,
    mutate,
    expected_error: str,
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="manuscript")
    _execute_chain_through_claim_ledger(workspace_root)
    ledger = _read_json(workspace_root / "claims/claim_ledger.json")
    mutate(ledger)
    _write_json(workspace_root / "claims/claim_ledger.json", ledger)
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, acquire_evidence_fn=_fake_acquire_evidence)

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert expected_error in result.errors
    assert not (workspace_root / "drafts/manuscript_section_draft.json").exists()


def test_cli_backed_fake_backend_can_explicitly_request_manuscript_drafting(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="manuscript")
    _execute_chain_through_claim_ledger(workspace_root)
    envelope = _call_tool(
        "draft_manuscript_section",
        input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
        parameters={"topic": TOPIC, "target_section": "discussion_scaffold"},
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.SUCCESS
    assert result.parse_result.accepted is True
    assert result.skill_result.skill_name == "draft_manuscript_section"
    assert (workspace_root / "drafts/manuscript_section_draft.json").exists()
    assert "draft_manuscript_section" in _read_json(workspace_root / "state.json")["completed_steps"]


def test_cli_backed_fake_backend_still_rejects_draft_evidence_grounded_report(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="manuscript")
    envelope = _call_tool(
        "draft_evidence_grounded_report",
        input_artifacts=["claims/claim_ledger.json"],
        output_artifacts=["drafts/future_report.md"],
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root,
        TASK_ID,
        FakeCliControllerBackend([envelope]),
    )

    result = controller.run_once()

    assert result.status == ControllerStepStatus.BLOCKED
    assert "UNAVAILABLE_SKILL" in result.errors or "OUT_OF_SCOPE_SKILL" in result.errors
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
