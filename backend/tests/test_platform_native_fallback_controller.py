import json
from pathlib import Path

import pytest

from modules.research_agent_controller import (
    NativeFallbackStepStatus,
    PlatformNativeFallbackController,
    SkillExecutionStatus,
    ValidationStatus,
    read_jsonl_events,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "large language models in materials discovery"


def _workspace(tmp_path: Path, task_id: str = "native_task") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        task_id,
        task_markdown=f"# Task\n\nResearch topic: {TOPIC}\n",
        plan_markdown="# Plan\n\nNative fallback baseline.\n",
    )
    return tmp_path / "research_agent/research_tasks" / task_id


def _fake_acquire_evidence(query: str, has_history: bool = False, **options: object) -> dict:
    _fake_acquire_evidence.calls.append({"query": query, "has_history": has_history, "options": dict(options)})
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


_fake_acquire_evidence.calls = []


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_native_fallback_controller_does_not_call_claude_cli(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _fake_acquire_evidence.calls = []

    def forbidden_subprocess(*args, **kwargs):
        raise AssertionError("native fallback controller must not call subprocess")

    monkeypatch.setattr("subprocess.run", forbidden_subprocess)
    controller = PlatformNativeFallbackController(
        workspace_root,
        "native_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.SUCCESS
    assert result.skill_result.skill_name == "retrieve_sources"
    assert _fake_acquire_evidence.calls


def test_run_once_from_empty_workspace_selects_retrieve_sources(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _fake_acquire_evidence.calls = []
    controller = PlatformNativeFallbackController(
        workspace_root,
        "native_task",
        topic=TOPIC,
        retrieval_budget=5,
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.SUCCESS
    assert result.next_skill == "retrieve_sources"
    assert result.skill_result.status == SkillExecutionStatus.SUCCESS
    assert (workspace_root / "retrieval/source_candidate_packet.json").exists()
    assert (workspace_root / "retrieval/retrieval_warnings.json").exists()
    state = _read_json(workspace_root / "state.json")
    manifest = _read_json(workspace_root / "audit/artifact_manifest.json")
    assert state["status"] == "running"
    assert "retrieve_sources" in state["completed_steps"]
    assert any(item["path"] == "retrieval/source_candidate_packet.json" for item in manifest["artifacts"])
    assert read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")
    assert read_jsonl_events(workspace_root, "logs/validation_results.jsonl")


def test_run_once_after_retrieval_selects_create_evidence_seeds(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _fake_acquire_evidence.calls = []
    controller = PlatformNativeFallbackController(
        workspace_root,
        "native_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
    )
    first = controller.run_once()
    assert first.next_skill == "retrieve_sources"

    second = controller.run_once()

    assert second.status == NativeFallbackStepStatus.SUCCESS
    assert second.next_skill == "create_evidence_seeds"
    assert second.skill_result.output_artifacts == ["evidence/evidence_card_seeds.json"]
    assert (workspace_root / "evidence/evidence_card_seeds.json").exists()


def test_run_until_stop_completes_minimal_topic_to_evidence_chain(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _fake_acquire_evidence.calls = []
    controller = PlatformNativeFallbackController(
        workspace_root,
        "native_task",
        topic=TOPIC,
        retrieval_budget=5,
        selection_budget=5,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    results = controller.run_until_stop()

    assert results[-1].status == NativeFallbackStepStatus.STOP_SUCCESS
    assert [result.next_skill for result in results if result.next_skill] == [
        "retrieve_sources",
        "create_evidence_seeds",
        "extract_evidence_cards",
        "enrich_evidence_cards",
        "rank_evidence",
        "build_minimal_topic_to_evidence_report",
    ]
    assert (workspace_root / "reports/minimal_topic_to_evidence_report.md").exists()
    assert (workspace_root / "reports/minimal_topic_to_evidence_report.json").exists()
    state = _read_json(workspace_root / "state.json")
    assert state["status"] == "completed"
    assert "build_minimal_topic_to_evidence_report" in state["completed_steps"]
    validation_events = read_jsonl_events(workspace_root, "logs/validation_results.jsonl")
    assert any(event.get("validator_name") == "ranking_selection_gate" for event in validation_events)
    assert any(event.get("validator_name") == "report_input_gate" for event in validation_events)
    assert len(read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")) == 6


def test_raw_retrieval_report_input_is_rejected_before_tool_execution(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    controller = PlatformNativeFallbackController(workspace_root, "native_task", topic=TOPIC)
    monkeypatch.setattr(controller, "_determine_next_skill", lambda: "build_minimal_topic_to_evidence_report")
    monkeypatch.setattr(
        controller,
        "_input_artifacts_for",
        lambda skill_name: ["retrieval/source_candidate_packet.json"],
    )

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_report" in result.errors
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()


def test_missing_input_artifact_blocks_skill_execution(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    controller = PlatformNativeFallbackController(workspace_root, "native_task", topic=TOPIC)
    monkeypatch.setattr(controller, "_determine_next_skill", lambda: "extract_evidence_cards")

    result = controller.run_once()

    assert result.status == NativeFallbackStepStatus.BLOCKED
    assert "missing_input_artifact:evidence/evidence_card_seeds.json" in result.errors
    assert result.skill_result.status == SkillExecutionStatus.BLOCKED


def test_max_steps_prevents_infinite_loop(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    controller = PlatformNativeFallbackController(
        workspace_root,
        "native_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=1,
    )

    results = controller.run_until_stop()

    assert results[-1].status == NativeFallbackStepStatus.BUDGET_EXCEEDED
    assert _read_json(workspace_root / "state.json")["status"] == "budget_exceeded"


def test_native_fallback_does_not_execute_future_stub_skills(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    controller = PlatformNativeFallbackController(
        workspace_root,
        "native_task",
        topic=TOPIC,
        acquire_evidence_fn=_fake_acquire_evidence,
        max_steps=10,
    )

    controller.run_until_stop()

    executed = [event.get("skill_name") for event in read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")]
    forbidden = {
        "build_landscape",
        "map_gaps",
        "generate_candidate_ideas",
        "draft_evidence_grounded_report",
    }
    assert forbidden.isdisjoint(executed)
    assert not (workspace_root / "landscape/landscape.json").exists()
    assert not (workspace_root / "landscape/literature_landscape.json").exists()
    assert not (workspace_root / "landscape/literature_landscape.md").exists()
    assert not (workspace_root / "gaps/gaps.json").exists()
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()


def test_native_fallback_source_has_no_cli_runtime_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/native_fallback_controller.py").read_text(encoding="utf-8")
    forbidden = [
        "RealClaudeCodeCliBackend",
        "CliOutputEnvelope",
        "parse_cli_output",
        "subprocess",
        "claude",
        "core.memory_db",
        "sqlite",
        "modules.workflow",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in source
