import json
from pathlib import Path

import pytest

from modules.research_agent_controller import (
    SkillExecutionInput,
    SkillExecutionResult,
    SkillExecutionStatus,
    build_default_skill_registry,
)
from modules.research_agent_controller.skills import (
    EVIDENCE_SKILL_WRAPPERS,
    execute_evidence_skill,
    get_evidence_skill_wrapper,
)
from modules.research_workspace import ResearchWorkspaceStore


AVAILABLE_SKILLS = {
    "retrieve_sources",
    "create_evidence_seeds",
    "extract_evidence_cards",
    "enrich_evidence_cards",
    "rank_evidence",
    "build_landscape",
    "map_gaps",
    "generate_candidate_ideas",
    "screen_novelty_feasibility_risk",
    "create_experiment_matrix",
    "build_claim_ledger",
    "draft_manuscript_section",
    "build_minimal_topic_to_evidence_report",
    "validate_evidence_cards",
    "validate_artifact_manifest",
}


def _workspace(tmp_path: Path, task_id: str = "task_123") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(task_id)
    return tmp_path / "research_agent/research_tasks" / task_id


def _input(workspace_root: Path, skill_name: str, **parameters: object) -> SkillExecutionInput:
    return SkillExecutionInput(
        task_id="task_123",
        workspace_root=str(workspace_root),
        skill_name=skill_name,
        parameters=dict(parameters),
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fake_acquire_evidence(query: str, has_history: bool = False, **options: object) -> dict:
    return {
        "evidence_candidates": [
            {
                "evidence_id": "ev_1",
                "paper_id": "paper_1",
                "title": "LLMs for material discovery",
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


def test_skill_execution_input_and_result_round_trip() -> None:
    execution_input = SkillExecutionInput(
        task_id="task_123",
        workspace_root="/tmp/workspace",
        skill_name="retrieve_sources",
        input_artifacts=["task.md"],
        parameters={"topic": "LLMs in materials discovery"},
        requested_by="controller",
    )
    result = SkillExecutionResult(
        task_id="task_123",
        skill_name="retrieve_sources",
        status=SkillExecutionStatus.SUCCESS,
        input_artifacts=["task.md"],
        output_artifacts=["retrieval/source_candidate_packet.json"],
        warnings=["best_effort"],
        metadata={"candidate_count": 1},
    )

    assert SkillExecutionInput.from_dict(execution_input.as_dict()).as_dict() == execution_input.as_dict()
    assert SkillExecutionResult.from_dict(result.as_dict()).as_dict() == result.as_dict()
    assert result.as_dict()["status"] == "success"

    with pytest.raises(ValueError):
        SkillExecutionResult(task_id="task_123", skill_name="bad", status="invented")


def test_each_available_skill_has_wrapper_and_stub_skills_do_not() -> None:
    registry = build_default_skill_registry()

    assert set(EVIDENCE_SKILL_WRAPPERS) == AVAILABLE_SKILLS
    for skill in registry.list_available_skills():
        assert get_evidence_skill_wrapper(skill.name) is not None

    for skill in registry.list_stub_skills():
        with pytest.raises(KeyError):
            get_evidence_skill_wrapper(skill.name)


def test_unknown_or_future_stub_skill_cannot_execute(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    unknown = execute_evidence_skill(_input(workspace_root, "missing_skill"))
    stub = execute_evidence_skill(_input(workspace_root, "draft_evidence_grounded_report"))

    assert unknown.status == SkillExecutionStatus.BLOCKED
    assert "unregistered skill" in unknown.errors[0]
    assert stub.status == SkillExecutionStatus.BLOCKED
    assert "no executable wrapper" in stub.errors[0]


def test_retrieve_sources_blocks_without_acquire_function_and_writes_artifacts_with_fake_retrieval(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    blocked = execute_evidence_skill(
        _input(workspace_root, "retrieve_sources", topic="large language models in material discovery")
    )
    assert blocked.status == SkillExecutionStatus.BLOCKED
    assert "missing_acquire_evidence_fn" in blocked.errors

    result = execute_evidence_skill(
        _input(
            workspace_root,
            "retrieve_sources",
            topic="large language models in material discovery",
            retrieval_budget=5,
        ),
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    assert result.status == SkillExecutionStatus.SUCCESS
    assert "retrieval/source_candidate_packet.json" in result.output_artifacts
    packet = _read_json(workspace_root / "retrieval/source_candidate_packet.json")
    warnings = _read_json(workspace_root / "retrieval/retrieval_warnings.json")
    assert packet["topic"] == "large language models in material discovery"
    assert packet["evidence_card_seeds"][0]["paper_id"] == "paper_1"
    assert warnings["warnings"]


def test_create_evidence_seeds_extract_enrich_rank_and_report_pipeline(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    retrieve = execute_evidence_skill(
        _input(workspace_root, "retrieve_sources", topic="large language models in material discovery"),
        acquire_evidence_fn=_fake_acquire_evidence,
    )
    assert retrieve.status == SkillExecutionStatus.SUCCESS

    seeds = execute_evidence_skill(_input(workspace_root, "create_evidence_seeds"))
    assert seeds.status == SkillExecutionStatus.SUCCESS
    seed_artifact = _read_json(workspace_root / "evidence/evidence_card_seeds.json")
    assert seed_artifact["seed_count"] == 1
    assert seed_artifact["seeds"][0]["paper_id"] == "paper_1"

    initial = execute_evidence_skill(
        _input(workspace_root, "extract_evidence_cards", topic="large language models in material discovery")
    )
    assert initial.status == SkillExecutionStatus.SUCCESS
    initial_cards = _read_json(workspace_root / "evidence/evidence_cards.initial.json")
    assert initial_cards["card_count"] == 1
    assert initial_cards["cards"][0]["evidence_id"].startswith("ecard_")

    enriched = execute_evidence_skill(
        _input(workspace_root, "enrich_evidence_cards", topic="large language models in material discovery")
    )
    assert enriched.status == SkillExecutionStatus.SUCCESS
    enriched_cards = _read_json(workspace_root / "evidence/evidence_cards.enriched.json")
    assert enriched_cards["card_count"] == 1
    assert enriched_cards["cards"][0]["relations"] == []

    ranked = execute_evidence_skill(_input(workspace_root, "rank_evidence", retrieval_budget=3))
    assert ranked.status == SkillExecutionStatus.SUCCESS
    selection = _read_json(workspace_root / "ranked_evidence/evidence_selection.json")
    coverage = _read_json(workspace_root / "ranked_evidence/coverage_diagnostics.json")
    assert selection["selected_count"] == 1
    assert coverage["coverage"]

    report = execute_evidence_skill(
        _input(workspace_root, "build_minimal_topic_to_evidence_report", topic="large language models in material discovery")
    )
    assert report.status == SkillExecutionStatus.SUCCESS
    markdown = (workspace_root / "reports/minimal_topic_to_evidence_report.md").read_text(encoding="utf-8")
    assert "Minimal Topic-to-Evidence Report" in markdown
    assert enriched_cards["cards"][0]["evidence_id"] in markdown


def test_report_wrapper_rejects_raw_retrieval_candidate_input(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    execute_evidence_skill(
        _input(workspace_root, "retrieve_sources", topic="large language models in material discovery"),
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    result = execute_evidence_skill(
        SkillExecutionInput(
            task_id="task_123",
            workspace_root=str(workspace_root),
            skill_name="build_minimal_topic_to_evidence_report",
            input_artifacts=["retrieval/source_candidate_packet.json"],
            parameters={"topic": "large language models in material discovery"},
        )
    )

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_report" in result.errors
    assert not (workspace_root / "reports/minimal_topic_to_evidence_report.md").exists()


def test_validate_evidence_cards_writes_result_without_modifying_cards(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    execute_evidence_skill(
        _input(workspace_root, "retrieve_sources", topic="large language models in material discovery"),
        acquire_evidence_fn=_fake_acquire_evidence,
    )
    execute_evidence_skill(_input(workspace_root, "create_evidence_seeds"))
    execute_evidence_skill(_input(workspace_root, "extract_evidence_cards", topic="large language models in material discovery"))

    cards_path = workspace_root / "evidence/evidence_cards.initial.json"
    before = cards_path.read_text(encoding="utf-8")
    result = execute_evidence_skill(
        _input(workspace_root, "validate_evidence_cards", input_path="evidence/evidence_cards.initial.json")
    )
    after = cards_path.read_text(encoding="utf-8")

    assert result.status == SkillExecutionStatus.SUCCESS
    assert before == after
    validation = _read_json(workspace_root / "evidence/evidence_validation.json")
    assert validation["valid"] is True
    assert validation["card_count"] == 1


def test_validate_artifact_manifest_writes_validation_result(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    result = execute_evidence_skill(_input(workspace_root, "validate_artifact_manifest"))

    assert result.status == SkillExecutionStatus.SUCCESS
    validation = _read_json(workspace_root / "audit/artifact_manifest_validation.json")
    assert validation["valid"] is True
    assert validation["task_id"] == "task_123"


def test_missing_input_artifact_returns_blocked_without_unhandled_exception(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    result = execute_evidence_skill(_input(workspace_root, "create_evidence_seeds"))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact" in result.errors[0]


def test_evidence_tools_have_no_cli_database_frontend_or_workflow_dependencies() -> None:
    source = Path("backend/modules/research_agent_controller/skills/evidence_tools.py").read_text(encoding="utf-8")

    forbidden = [
        "cli_backed_controller",
        "native_fallback_controller",
        "Claude Code CLI",
        "sqlite",
        "core.memory_db",
        "frontend",
        "modules.workflow",
        "LiteratureResearchService",
    ]
    for token in forbidden:
        assert token not in source
