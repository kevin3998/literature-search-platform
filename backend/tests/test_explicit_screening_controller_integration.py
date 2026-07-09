import json
from pathlib import Path

import pytest

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ControllerStepStatus,
    FakeCliControllerBackend,
    NativeFallbackStepStatus,
    PlatformNativeFallbackController,
    SkillExecutionInput,
    SkillExecutionStatus,
    build_explicit_idea_generation_plan,
    build_explicit_screening_plan,
    build_minimal_topic_to_evidence_plan,
    read_jsonl_events,
)
from modules.research_agent_controller.skills import execute_evidence_skill
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "explicit_screening_task"


class ScriptedScreeningLLM:
    provider = "scripted"
    model = "screening-fixture"

    async def stream_chat(self, messages, tools=None):
        packet = _packet_from_messages(messages)
        idea = packet["candidate_ideas"][0]
        gap_ids = idea["gap_basis"]["gap_ids"]
        evidence_ids = idea["evidence_basis"]["supporting_evidence_ids"]
        evidence_map = packet["evidence_reference_map"]
        first_evidence = evidence_ids[0]
        payload = {
            "screened_ideas": [
                {
                    "idea_id": idea["idea_id"],
                    "source_idea_title": idea["title"],
                    "gap_ids": gap_ids,
                    "evidence_ids": evidence_ids,
                    "local_novelty_triage": {
                        "judgment": "partial_overlap_with_local_evidence",
                        "confidence": "medium",
                        "closest_local_prior_evidence": [
                            {
                                "evidence_id": first_evidence,
                                "paper_id": evidence_map[first_evidence]["paper_id"],
                                "overlap": "Local evidence discusses related oxygen-vacancy HER mechanisms.",
                                "difference": "The candidate is framed as a scoped triage direction rather than a validated result.",
                            }
                        ],
                        "rationale": "The candidate overlaps local mechanism evidence but is not fully covered by the local packet.",
                        "limitations": ["Only local evidence artifacts were considered."],
                    },
                    "external_novelty_search": {
                        "status": "not_performed",
                        "required": True,
                        "rationale": "External prior-work search is required before novelty claims.",
                    },
                    "feasibility_triage": {
                        "judgment": "partially_supported",
                        "confidence": "medium",
                        "supporting_evidence": evidence_ids,
                        "missing_requirements": ["synthesis details", "characterization evidence"],
                        "constraints": ["Requires expert feasibility review."],
                        "rationale": "The evidence supports the mechanism context but not complete execution requirements.",
                    },
                    "risk_triage": {
                        "judgment": "evidence_gap_risk",
                        "confidence": "medium",
                        "risk_factors": ["local evidence coverage is limited"],
                        "follow_up": ["external novelty search", "expert feasibility review", "risk review"],
                        "rationale": "The main risk is limited local coverage rather than a proven blocker.",
                    },
                    "overall_triage": {
                        "judgment": "advance_to_external_novelty_search",
                        "rationale": "The idea is locally grounded and should next receive external novelty search.",
                        "required_follow_up": ["external novelty search", "expert feasibility review", "risk review"],
                    },
                    "not_an_experiment_plan": True,
                    "not_a_validated_claim": True,
                }
            ]
        }
        yield {"type": "content", "text": json.dumps(payload, ensure_ascii=False)}


def _packet_from_messages(messages) -> dict:
    content = "\n".join(str(message.get("content", "")) for message in messages)
    marker = "EVIDENCE_PACKET_JSON:\n"
    return json.loads(content.split(marker, 1)[1])


def _workspace(tmp_path: Path, *, plan_kind: str) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    if plan_kind == "minimal":
        plan = build_minimal_topic_to_evidence_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "idea":
        plan = build_explicit_idea_generation_plan(TASK_ID, TOPIC).as_dict()
    elif plan_kind == "screening":
        plan = build_explicit_screening_plan(TASK_ID, TOPIC).as_dict()
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


def _execute_chain_through_ideas(workspace_root: Path) -> None:
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


def test_default_minimal_plan_still_stops_before_landscape_gap_idea_and_screening(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="minimal")
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
    assert executed[-1] == "build_minimal_topic_to_evidence_report"
    assert "screen_novelty_feasibility_risk" not in executed
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_explicit_idea_generation_plan_still_stops_before_screening(tmp_path: Path) -> None:
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
    assert executed[-1] == "generate_candidate_ideas"
    assert "screen_novelty_feasibility_risk" not in executed
    assert (workspace_root / "ideas/candidate_ideas.json").exists()
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_explicit_screening_plan_executes_screening_after_candidate_ideas(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="screening")
    controller = PlatformNativeFallbackController(
        workspace_root,
        TASK_ID,
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        llm_client=ScriptedScreeningLLM(),
        max_steps=14,
    )

    results = controller.run_until_stop()

    executed = [result.next_skill for result in results if result.next_skill]
    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert executed[-1] == "screen_novelty_feasibility_risk"
    assert (workspace_root / "screening/idea_screening_results.json").exists()
    assert (workspace_root / "screening/idea_screening_results.md").exists()
    assert (workspace_root / "screening/screening_diagnostics.json").exists()
    screening = _read_json(workspace_root / "screening/idea_screening_results.json")
    markdown = (workspace_root / "screening/idea_screening_results.md").read_text(encoding="utf-8")
    assert screening["schema_version"] == "idea_screening_v2"
    assert screening["analysis_mode"] == "llm_assisted_local_evidence_triage"
    assert all(item["idea_id"] for item in screening["screened_ideas"])
    assert all(item["gap_ids"] and item["evidence_ids"] for item in screening["screened_ideas"])
    assert all(item["local_novelty_triage"]["judgment"] for item in screening["screened_ideas"])
    assert all(item["external_novelty_search"]["status"] == "not_performed" for item in screening["screened_ideas"])
    assert all(item["feasibility_triage"]["judgment"] for item in screening["screened_ideas"])
    assert all(item["risk_triage"]["judgment"] for item in screening["screened_ideas"])
    assert all(item["not_an_experiment_plan"] is True for item in screening["screened_ideas"])
    assert all(item["not_a_validated_claim"] is True for item in screening["screened_ideas"])
    assert "# LLM 辅助筛选摘要" in markdown
    assert "## 证据引用" in markdown
    assert "## Experiment Plan" not in markdown
    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    paths = {item["path"] for item in manifest["artifacts"]}
    assert {
        "screening/idea_screening_results.json",
        "screening/idea_screening_results.md",
        "screening/screening_diagnostics.json",
    }.issubset(paths)
    assert any(
        event.get("metadata", {}).get("skill_name") == "screen_novelty_feasibility_risk"
        and event.get("metadata", {}).get("controller_source") == "platform_native_fallback"
        for event in read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    )
    assert any(
        event.get("skill_name") == "screen_novelty_feasibility_risk"
        for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")
    )
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    state = _read_json(workspace_root / "state.json")
    assert "screen_novelty_feasibility_risk" in state["completed_steps"]
    assert "screening/idea_screening_results.json" in state["artifact_index"]
    assert "screen_novelty_feasibility_risk" in (workspace_root / "plan.md").read_text(encoding="utf-8")


def test_explicit_screening_blocks_when_candidate_ideas_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="screening")
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, max_steps=1)
    controller._determine_next_skill = lambda: "screen_novelty_feasibility_risk"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_candidate_ideas_artifact" in result.errors


@pytest.mark.parametrize(
    ("missing_path", "expected_error"),
    [
        ("gaps/gap_map.json", "missing_screening_input:gaps/gap_map.json"),
        ("landscape/literature_landscape.json", "missing_screening_input:landscape/literature_landscape.json"),
        ("evidence/evidence_cards.enriched.json", "missing_screening_input:evidence/evidence_cards.enriched.json"),
        ("ranked_evidence/evidence_selection.json", "missing_screening_input:ranked_evidence/evidence_selection.json"),
    ],
)
def test_explicit_screening_blocks_when_required_inputs_are_missing(
    tmp_path: Path,
    missing_path: str,
    expected_error: str,
) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="screening")
    _execute_chain_through_ideas(workspace_root)
    (workspace_root / missing_path).unlink()
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, max_steps=1)
    controller._determine_next_skill = lambda: "screen_novelty_feasibility_risk"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert expected_error in result.errors


def test_explicit_screening_validation_fails_for_retrieval_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="screening")
    _execute_chain_through_ideas(workspace_root)
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, max_steps=1)
    controller._determine_next_skill = lambda: "screen_novelty_feasibility_risk"
    controller._input_artifacts_for = lambda skill_name: ["retrieval/source_candidate_packet.json"]

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_screening" in result.errors
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_explicit_screening_validation_fails_for_candidate_idea_without_basis(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="screening")
    _execute_chain_through_ideas(workspace_root)
    candidate = _read_json(workspace_root / "ideas/candidate_ideas.json")
    candidate["ideas"][0]["gap_basis"] = {"gap_ids": []}
    candidate["ideas"][0]["evidence_basis"] = {"supporting_evidence_ids": []}
    (workspace_root / "ideas/candidate_ideas.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    controller = PlatformNativeFallbackController(workspace_root, TASK_ID, topic=TOPIC, max_steps=1)
    controller._determine_next_skill = lambda: "screen_novelty_feasibility_risk"

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "screening_requires_gap_and_evidence_basis" in result.errors
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_cli_backed_fake_backend_can_explicitly_request_screening(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="screening")
    _execute_chain_through_ideas(workspace_root)
    envelope = _call_tool(
        "screen_novelty_feasibility_risk",
        input_artifacts=[
            "ideas/candidate_ideas.json",
            "ideas/idea_generation_diagnostics.json",
            "gaps/gap_map.json",
            "gaps/gap_coverage_diagnostics.json",
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        output_artifacts=[
            "screening/idea_screening_results.json",
            "screening/idea_screening_results.md",
            "screening/screening_diagnostics.json",
        ],
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
    assert result.skill_result.skill_name == "screen_novelty_feasibility_risk"
    assert (workspace_root / "screening/idea_screening_results.json").exists()
    assert "screen_novelty_feasibility_risk" in _read_json(workspace_root / "state.json")["completed_steps"]


def test_cli_backed_fake_backend_explicit_claim_ledger_request_blocks_without_inputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, plan_kind="screening")
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


def test_explicit_screening_controller_sources_have_no_real_cli_llm_database_or_workflow_dependency() -> None:
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
