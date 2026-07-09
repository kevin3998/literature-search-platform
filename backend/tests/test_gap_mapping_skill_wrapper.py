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
from modules.research_agent_controller.skills.gap_tools import validate_gap_map_artifact
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "gap_task"


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(TASK_ID, task_markdown=f"# Task\n\nTopic: {TOPIC}\n")
    return tmp_path / "research_agent/research_tasks" / TASK_ID


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _execution(workspace_root: Path, *, input_artifacts: list[str] | None = None) -> SkillExecutionInput:
    return SkillExecutionInput(
        task_id=TASK_ID,
        workspace_root=str(workspace_root),
        skill_name="map_gaps",
        input_artifacts=list(input_artifacts or []),
        parameters={"topic": TOPIC},
    )


def _card(evidence_id: str, paper_id: str, *, source_type: str = "text", role: str = "mechanism") -> dict:
    return {
        "evidence_id": evidence_id,
        "seed_id": f"seed_{evidence_id}",
        "paper_id": paper_id,
        "source": {
            "source_path": f"{paper_id}/sections/results.md",
            "asset_type": source_type,
            "section_id": "results",
            "locator": {"section": "Results"},
        },
        "primary_role": role,
        "secondary_roles": ["performance"],
        "normalized_statement": "Oxygen vacancies modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
        "verbatim_snippet": "Oxygen vacancies modulate water dissociation and hydrogen adsorption in alkaline HER catalysts.",
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


def _write_gap_inputs(workspace_root: Path) -> None:
    cards = [_card("ecard_001", "paper_001"), _card("ecard_002", "paper_001", role="performance")]
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {
            "artifact_type": "evidence_cards",
            "stage": "enriched",
            "task_id": TASK_ID,
            "topic": TOPIC,
            "cards": cards,
            "warnings": [],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/evidence_selection.json",
        {
            "artifact_type": "evidence_selection",
            "selected_cards": cards,
            "ranked_cards": [
                {
                    "rank": index + 1,
                    "evidence_id": card["evidence_id"],
                    "score": 0.9 - index * 0.1,
                    "score_components": {"relevance": 0.9 - index * 0.1},
                    "selected": True,
                    "selection_reasons": ["high_score"],
                    "card": card,
                }
                for index, card in enumerate(cards)
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
                "source_type_coverage": {"text": 2},
                "role_distribution": {"mechanism": 1, "performance": 1},
            },
            "warnings": ["missing_figure_source_type"],
        },
    )
    _write_json(
        workspace_root / "landscape/literature_landscape.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "landscape_id": "landscape_gap_task",
            "input_artifacts": [
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001"],
            "landscape_axes": [
                {
                    "axis_id": "mechanistic_role",
                    "name": "Mechanistic Role",
                    "description": "Mechanistic roles represented in evidence.",
                    "values": ["water dissociation"],
                }
            ],
            "clusters": [
                {
                    "cluster_id": "cluster_mechanism",
                    "title": "Mechanism Cluster",
                    "description": "Sparse mechanism evidence.",
                    "axis_values": {"mechanistic_role": "water dissociation"},
                    "evidence_ids": ["ecard_001"],
                    "source_paper_ids": ["paper_001"],
                    "representative_claims": [
                        {"claim": "Oxygen vacancies modulate water dissociation.", "evidence_ids": ["ecard_001"]}
                    ],
                    "confidence": "medium",
                    "warnings": [],
                }
            ],
            "coverage": {
                "num_landscape_clusters": 1,
                "num_evidence_cards": 2,
                "num_selected_evidence": 2,
                "num_source_papers": 1,
                "source_type_distribution": {"text": 2},
                "role_distribution": {"mechanism": 1, "performance": 1},
                "missing_roles": ["figure_evidence"],
                "dominant_source_warning": True,
                "coverage_warnings": ["landscape_sparse_cluster"],
            },
            "representative_evidence": [],
            "limitations": [],
            "warnings": ["landscape_sparse_cluster"],
            "created_at": 0,
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "task_id": TASK_ID,
            "landscape_id": "landscape_gap_task",
            "coverage": {
                "missing_roles": ["figure_evidence"],
                "dominant_source_warning": True,
                "coverage_warnings": ["landscape_sparse_cluster"],
            },
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )


def test_map_gaps_is_available_and_executable_after_p2_m9_2() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("map_gaps")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert "map_gaps" in EVIDENCE_SKILL_WRAPPERS


def test_map_gaps_generates_gap_artifacts_with_grounded_schema_and_markdown(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_gap_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.SUCCESS
    assert result.output_artifacts == [
        "gaps/gap_map.json",
        "gaps/gap_map.md",
        "gaps/gap_coverage_diagnostics.json",
    ]
    gap_map = _read_json(workspace_root / "gaps/gap_map.json")
    diagnostics = _read_json(workspace_root / "gaps/gap_coverage_diagnostics.json")
    markdown = (workspace_root / "gaps/gap_map.md").read_text(encoding="utf-8")

    assert gap_map["schema_version"] == "gap_map_v1"
    assert gap_map["gap_map_id"]
    assert gap_map["landscape_id"] == "landscape_gap_task"
    assert gap_map["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert gap_map["gaps"]
    assert all(gap["basis"] for gap in gap_map["gaps"])
    assert all(gap["not_an_idea"] is True for gap in gap_map["gaps"])
    gap_ids = {gap["gap_id"] for gap in gap_map["gaps"]}
    assert all(set(item["gap_ids"]).issubset(gap_ids) and item["gap_ids"] for item in gap_map["supporting_evidence"])
    assert "missing_figure_source_type" in gap_map["warnings"]
    assert "landscape_sparse_cluster" in gap_map["warnings"]
    assert "dominant_paper_warning" in gap_map["warnings"]
    assert diagnostics["gap_count"] == len(gap_map["gaps"])
    assert "## Evidence References" in markdown
    assert "evidence_id=ecard_001" in markdown
    assert "landscape_cluster_id=cluster_mechanism" in markdown
    forbidden_sections = [
        "## Candidate Ideas",
        "## Proposed Research Directions",
        "## Novelty Screening",
        "## Feasibility Screening",
        "## Experiment Plan",
        "## Manuscript Draft",
    ]
    for section in forbidden_sections:
        assert section not in markdown
    assert validate_gap_map_artifact(gap_map, markdown) == []


def test_map_gaps_result_can_be_registered_in_manifest_and_audit(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_gap_inputs(workspace_root)
    result = execute_evidence_skill(_execution(workspace_root))

    record_skill_execution_result(result, workspace_root)

    manifest = load_artifact_manifest(workspace_root, TASK_ID)
    paths = {artifact.path for artifact in manifest.artifacts}
    assert set(result.output_artifacts).issubset(paths)
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")


def test_map_gaps_rejects_retrieval_input_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_gap_inputs(workspace_root)

    result = execute_evidence_skill(
        _execution(workspace_root, input_artifacts=["retrieval/source_candidate_packet.json"])
    )

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_gap_mapping" in result.errors
    assert not (workspace_root / "gaps/gap_map.json").exists()


def test_map_gaps_blocks_when_landscape_json_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_gap_inputs(workspace_root)
    (workspace_root / "landscape/literature_landscape.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_landscape_artifact" in result.errors


def test_map_gaps_blocks_when_enriched_cards_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_gap_inputs(workspace_root)
    (workspace_root / "evidence/evidence_cards.enriched.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:evidence/evidence_cards.enriched.json" in result.errors


def test_map_gaps_blocks_when_selected_evidence_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_gap_inputs(workspace_root)
    (workspace_root / "ranked_evidence/evidence_selection.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:ranked_evidence/evidence_selection.json" in result.errors


def test_gap_map_validation_rejects_idea_sections_and_missing_basis() -> None:
    invalid_gap_map = {
        "schema_version": "gap_map_v1",
        "gap_map_id": "gap_map_task",
        "landscape_id": "landscape_task",
        "evidence_ids": ["ecard_001"],
        "gaps": [{"gap_id": "gap_1", "basis": {}, "not_an_idea": False}],
        "supporting_evidence": [{"evidence_id": "ecard_001", "gap_ids": []}],
    }
    markdown = "# Gap Map\n\n## Candidate Ideas\n\nUnsupported future idea.\n"

    errors = validate_gap_map_artifact(invalid_gap_map, markdown)

    assert "gap_missing_basis:0" in errors
    assert "gap_must_not_be_candidate_idea:0" in errors
    assert "supporting_evidence_missing_gap_ids:0" in errors
    assert "markdown_missing_evidence_references" in errors
    assert "forbidden_gap_markdown_section:Candidate Ideas" in errors


def test_p2_m14_plus_skills_remain_non_executable() -> None:
    future_skills = {
        "draft_evidence_grounded_report",
    }
    registry = build_default_skill_registry()

    assert future_skills.isdisjoint(EVIDENCE_SKILL_WRAPPERS)
    assert future_skills.issubset({skill.name for skill in registry.list_stub_skills()})
    assert registry.get_skill("build_claim_ledger").status == SkillStatus.AVAILABLE
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS


def test_gap_tools_have_no_cli_llm_database_or_controller_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/gap_tools.py").read_text(encoding="utf-8")
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
        "modules.evidence_workflow",
        "modules.workflow",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in source
