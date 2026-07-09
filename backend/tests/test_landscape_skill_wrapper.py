import json
from pathlib import Path

from modules.research_agent_controller import (
    SkillExecutionInput,
    SkillExecutionStatus,
    SkillStatus,
    build_default_skill_registry,
    load_artifact_manifest,
    read_jsonl_events,
    record_skill_execution_result,
)
from modules.research_agent_controller.skills import EVIDENCE_SKILL_WRAPPERS, execute_evidence_skill
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"


def _workspace(tmp_path: Path, task_id: str = "landscape_task") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(task_id, task_markdown=f"# Task\n\nTopic: {TOPIC}\n")
    return tmp_path / "research_agent/research_tasks" / task_id


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _execution(workspace_root: Path, *, input_artifacts: list[str] | None = None) -> SkillExecutionInput:
    return SkillExecutionInput(
        task_id="landscape_task",
        workspace_root=str(workspace_root),
        skill_name="build_landscape",
        input_artifacts=list(input_artifacts or []),
        parameters={"topic": TOPIC},
    )


def _write_landscape_inputs(workspace_root: Path) -> None:
    card = {
        "evidence_id": "ecard_001",
        "seed_id": "seed_001",
        "paper_id": "paper_001",
        "source": {
            "source_path": "paper_001/sections/results.md",
            "asset_type": "text",
            "section_id": "results",
            "locator": {"section": "Results"},
        },
        "primary_role": "mechanism",
        "secondary_roles": ["performance"],
        "normalized_statement": "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
        "verbatim_snippet": "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
        "entities": {
            "materials": ["alkaline HER catalysts"],
            "methods": ["oxygen vacancy engineering"],
            "metrics": ["HER activity"],
            "conditions": ["alkaline"],
            "characterization_tools": ["XPS"],
            "mechanisms": ["water dissociation", "hydrogen adsorption"],
        },
        "relations": [],
        "support": {"support_strength": "direct", "extraction_confidence": 0.8},
        "relevance": {"topic": TOPIC, "relevance_score": 0.91},
    }
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {"artifact_type": "evidence_cards", "stage": "enriched", "task_id": "landscape_task", "cards": [card]},
    )
    _write_json(
        workspace_root / "ranked_evidence/evidence_selection.json",
        {
            "artifact_type": "evidence_selection",
            "selected_cards": [card],
            "ranked_cards": [
                {
                    "rank": 1,
                    "evidence_id": "ecard_001",
                    "score": 0.91,
                    "score_components": {"relevance": 0.91},
                    "selected": True,
                    "selection_reasons": ["high_score"],
                    "card": card,
                }
            ],
            "warnings": ["dominant_paper_warning"],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/coverage_diagnostics.json",
        {
            "artifact_type": "coverage_diagnostics",
            "coverage": {
                "missing_required_roles": ["figure_evidence"],
                "source_type_coverage": {"text": 1},
            },
            "warnings": ["missing_figure_source_type"],
        },
    )


def test_build_landscape_is_available_and_executable_after_p2_m8_2() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("build_landscape")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert "build_landscape" in EVIDENCE_SKILL_WRAPPERS


def test_build_landscape_generates_json_markdown_and_coverage_artifacts(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_landscape_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.SUCCESS
    assert result.output_artifacts == [
        "landscape/literature_landscape.json",
        "landscape/literature_landscape.md",
        "landscape/landscape_coverage_diagnostics.json",
    ]
    landscape = _read_json(workspace_root / "landscape/literature_landscape.json")
    diagnostics = _read_json(workspace_root / "landscape/landscape_coverage_diagnostics.json")
    markdown = (workspace_root / "landscape/literature_landscape.md").read_text(encoding="utf-8")

    assert landscape["schema_version"] == "landscape_v1"
    assert landscape["evidence_ids"] == ["ecard_001"]
    assert landscape["clusters"]
    assert all(cluster["evidence_ids"] for cluster in landscape["clusters"])
    assert all(claim["evidence_ids"] for cluster in landscape["clusters"] for claim in cluster["representative_claims"])
    assert diagnostics["warnings"] == ["missing_figure_source_type", "dominant_paper_warning"]
    assert "## Evidence References" in markdown
    assert "ecard_001" in markdown
    assert "paper_001/sections/results.md" in markdown
    forbidden_sections = ["## Research Gaps", "## Candidate Ideas", "## Novelty Screening", "## Experiment Plan", "## Manuscript Draft"]
    for section in forbidden_sections:
        assert section not in markdown


def test_build_landscape_result_can_be_registered_in_manifest_and_audit(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_landscape_inputs(workspace_root)
    result = execute_evidence_skill(_execution(workspace_root))

    record_skill_execution_result(result, workspace_root)

    manifest = load_artifact_manifest(workspace_root, "landscape_task")
    paths = {artifact.path for artifact in manifest.artifacts}
    assert set(result.output_artifacts).issubset(paths)
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")


def test_build_landscape_rejects_retrieval_input_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_landscape_inputs(workspace_root)

    result = execute_evidence_skill(
        _execution(workspace_root, input_artifacts=["retrieval/source_candidate_packet.json"])
    )

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_landscape" in result.errors
    assert not (workspace_root / "landscape/literature_landscape.json").exists()


def test_build_landscape_blocks_when_enriched_cards_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:evidence/evidence_cards.enriched.json" in result.errors


def test_build_landscape_blocks_when_selection_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {"artifact_type": "evidence_cards", "stage": "enriched", "task_id": "landscape_task", "cards": []},
    )

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:ranked_evidence/evidence_selection.json" in result.errors


def test_future_p2_m14_plus_skills_remain_non_executable() -> None:
    future_skills = {
        "draft_evidence_grounded_report",
    }
    registry = build_default_skill_registry()

    assert future_skills.isdisjoint(EVIDENCE_SKILL_WRAPPERS)
    assert future_skills.issubset({skill.name for skill in registry.list_stub_skills()})
    assert registry.get_skill("build_claim_ledger").status == SkillStatus.AVAILABLE
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS


def test_landscape_tools_have_no_cli_llm_database_or_workflow_dependencies() -> None:
    source = Path("backend/modules/research_agent_controller/skills/landscape_tools.py").read_text(encoding="utf-8")
    forbidden = [
        "RealClaudeCodeCliBackend",
        "ClaudeCodeBackedMinimalController",
        "PlatformNativeFallbackController",
        "LiteratureResearchService",
        "core.memory_db",
        "sqlite",
        "subprocess",
        "claude",
        "OpenAI",
        "DeepSeek",
        "llm_client",
        "modules.workflow",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in source
