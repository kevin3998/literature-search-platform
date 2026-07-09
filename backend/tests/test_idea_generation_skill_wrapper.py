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
from modules.research_agent_controller.skills.idea_tools import validate_candidate_ideas_artifact
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "idea_task"


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
        skill_name="generate_candidate_ideas",
        input_artifacts=list(input_artifacts or []),
        parameters={"topic": TOPIC},
    )


def _card(evidence_id: str, paper_id: str, *, role: str = "mechanism") -> dict:
    return {
        "evidence_id": evidence_id,
        "seed_id": f"seed_{evidence_id}",
        "paper_id": paper_id,
        "source": {
            "source_path": f"{paper_id}/sections/results.md",
            "asset_type": "text",
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


def _write_idea_inputs(workspace_root: Path) -> None:
    cards = [_card("ecard_001", "paper_001"), _card("ecard_002", "paper_002", role="performance")]
    _write_json(
        workspace_root / "evidence/evidence_cards.enriched.json",
        {
            "artifact_type": "evidence_cards",
            "stage": "enriched",
            "task_id": TASK_ID,
            "topic": TOPIC,
            "cards": cards,
            "warnings": ["enriched_sparse_role_warning"],
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
            "landscape_id": "landscape_idea_task",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "landscape_axes": [
                {
                    "axis_id": "mechanistic_role",
                    "name": "Mechanistic Role",
                    "values": ["water dissociation"],
                }
            ],
            "clusters": [
                {
                    "cluster_id": "cluster_mechanism",
                    "title": "Mechanism Cluster",
                    "axis_values": {"mechanistic_role": "water dissociation"},
                    "evidence_ids": ["ecard_001"],
                    "source_paper_ids": ["paper_001"],
                    "representative_claims": [
                        {"claim": "Oxygen vacancies modulate water dissociation.", "evidence_ids": ["ecard_001"]}
                    ],
                    "warnings": [],
                }
            ],
            "coverage": {
                "num_landscape_clusters": 1,
                "num_evidence_cards": 2,
                "num_selected_evidence": 2,
                "num_source_papers": 2,
                "coverage_warnings": ["landscape_sparse_cluster"],
            },
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "task_id": TASK_ID,
            "landscape_id": "landscape_idea_task",
            "coverage": {"coverage_warnings": ["landscape_sparse_cluster"]},
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    gap_map = {
        "task_id": TASK_ID,
        "topic": TOPIC,
        "gap_map_id": "gap_map_idea_task",
        "input_artifacts": [
            "landscape/literature_landscape.json",
            "landscape/landscape_coverage_diagnostics.json",
            "evidence/evidence_cards.enriched.json",
            "ranked_evidence/evidence_selection.json",
            "ranked_evidence/coverage_diagnostics.json",
        ],
        "landscape_id": "landscape_idea_task",
        "evidence_ids": ["ecard_001", "ecard_002"],
        "source_paper_ids": ["paper_001", "paper_002"],
        "gap_axes": [],
        "gaps": [
            {
                "gap_id": "gap_comparison_001",
                "gap_type": "comparison_gap",
                "title": "Limited comparison coverage for mechanistic role",
                "description": "The selected evidence covers one observed mechanistic role.",
                "axis_values": {"mechanistic_role": ["water dissociation"]},
                "basis": {
                    "landscape_cluster_ids": ["cluster_mechanism"],
                    "evidence_ids": ["ecard_001", "ecard_002"],
                    "coverage_warnings": ["landscape_sparse_cluster"],
                    "diagnostic_refs": ["axis_coverage:mechanistic_role"],
                },
                "severity": "medium",
                "confidence": "medium",
                "not_an_idea": True,
                "warnings": [],
            },
            {
                "gap_id": "gap_no_evidence",
                "gap_type": "coverage_gap",
                "title": "Unsupported weak gap",
                "description": "This gap lacks evidence basis and should be skipped.",
                "axis_values": {},
                "basis": {
                    "landscape_cluster_ids": [],
                    "evidence_ids": [],
                    "coverage_warnings": ["weak_gap_warning"],
                    "diagnostic_refs": ["coverage:weak_gap"],
                },
                "severity": "low",
                "confidence": "low",
                "not_an_idea": True,
                "warnings": [],
            },
        ],
        "coverage": {"coverage_warnings": ["gap_sparse_axis_warning"]},
        "supporting_evidence": [
            {
                "evidence_id": "ecard_001",
                "paper_id": "paper_001",
                "role": "mechanism",
                "source_type": "text",
                "gap_ids": ["gap_comparison_001"],
                "reason": "Selected mechanism evidence anchors the gap.",
            },
            {
                "evidence_id": "ecard_002",
                "paper_id": "paper_002",
                "role": "performance",
                "source_type": "text",
                "gap_ids": ["gap_comparison_001"],
                "reason": "Selected performance evidence anchors the gap.",
            },
        ],
        "limitations": ["Gap map is deterministic."],
        "warnings": ["gap_sparse_axis_warning"],
        "created_at": 0,
        "schema_version": "gap_map_v1",
    }
    _write_json(workspace_root / "gaps/gap_map.json", gap_map)
    _write_json(
        workspace_root / "gaps/gap_coverage_diagnostics.json",
        {
            "artifact_type": "gap_coverage_diagnostics",
            "task_id": TASK_ID,
            "gap_map_id": "gap_map_idea_task",
            "gap_count": 2,
            "warnings": ["gap_sparse_axis_warning"],
            "schema_version": "gap_map_v1",
        },
    )


def test_generate_candidate_ideas_is_available_and_executable_after_p2_m10_2() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("generate_candidate_ideas")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert "generate_candidate_ideas" in EVIDENCE_SKILL_WRAPPERS


def test_generate_candidate_ideas_writes_bounded_schema_and_markdown(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_idea_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.SUCCESS
    assert result.output_artifacts == [
        "ideas/candidate_ideas.json",
        "ideas/candidate_ideas.md",
        "ideas/idea_generation_diagnostics.json",
    ]
    artifact = _read_json(workspace_root / "ideas/candidate_ideas.json")
    diagnostics = _read_json(workspace_root / "ideas/idea_generation_diagnostics.json")
    markdown = (workspace_root / "ideas/candidate_ideas.md").read_text(encoding="utf-8")

    assert artifact["schema_version"] == "candidate_ideas_v1"
    assert artifact["idea_set_id"]
    assert artifact["gap_map_id"] == "gap_map_idea_task"
    assert artifact["landscape_id"] == "landscape_idea_task"
    assert artifact["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert artifact["ideas"]
    assert len(artifact["ideas"]) == 1
    assert all(idea["gap_basis"]["gap_ids"] for idea in artifact["ideas"])
    assert all(idea["evidence_basis"]["supporting_evidence_ids"] for idea in artifact["ideas"])
    assert all(idea["not_yet_screened"] is True for idea in artifact["ideas"])
    assert all(idea["requires_novelty_screening"] is True for idea in artifact["ideas"])
    assert all(idea["requires_feasibility_screening"] is True for idea in artifact["ideas"])
    assert "gap_sparse_axis_warning" in artifact["warnings"]
    assert "landscape_sparse_cluster" in artifact["warnings"]
    assert "missing_figure_source_type" in artifact["warnings"]
    assert diagnostics["num_input_gaps"] == 2
    assert diagnostics["num_valid_gaps"] == 1
    assert diagnostics["num_generated_ideas"] == 1
    assert diagnostics["skipped_gap_ids"] == ["gap_no_evidence"]
    assert diagnostics["downstream_screening_required"] is True
    assert diagnostics["forbidden_claim_checks"]["passed"] is True
    assert "## Evidence References" in markdown
    assert "idea_id=idea_gap_comparison_001" in markdown
    assert "gap_id=gap_comparison_001" in markdown
    assert "evidence_id=ecard_001" in markdown
    assert "paper_id=paper_001" in markdown
    assert "landscape_cluster_id=cluster_mechanism" in markdown
    for forbidden in [
        "## Novelty Screening",
        "## Feasibility Screening",
        "## Risk Screening",
        "## Experiment Plan",
        "## Manuscript Draft",
    ]:
        assert forbidden not in markdown
    assert "is novel" not in json.dumps(artifact).lower()
    assert "is feasible" not in json.dumps(artifact).lower()
    assert validate_candidate_ideas_artifact(artifact, markdown) == []


def test_generate_candidate_ideas_result_can_be_registered_in_manifest_and_audit(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_idea_inputs(workspace_root)
    result = execute_evidence_skill(_execution(workspace_root))

    record_skill_execution_result(result, workspace_root)

    manifest = load_artifact_manifest(workspace_root, TASK_ID)
    paths = {artifact.path for artifact in manifest.artifacts}
    assert set(result.output_artifacts).issubset(paths)
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")


def test_generate_candidate_ideas_rejects_retrieval_input_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_idea_inputs(workspace_root)

    result = execute_evidence_skill(
        _execution(workspace_root, input_artifacts=["retrieval/source_candidate_packet.json"])
    )

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_idea_generation" in result.errors
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()


def test_generate_candidate_ideas_blocks_when_gap_map_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_idea_inputs(workspace_root)
    (workspace_root / "gaps/gap_map.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_gap_map_artifact" in result.errors


def test_generate_candidate_ideas_blocks_when_landscape_json_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_idea_inputs(workspace_root)
    (workspace_root / "landscape/literature_landscape.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:landscape/literature_landscape.json" in result.errors


def test_generate_candidate_ideas_blocks_when_enriched_cards_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_idea_inputs(workspace_root)
    (workspace_root / "evidence/evidence_cards.enriched.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:evidence/evidence_cards.enriched.json" in result.errors


def test_generate_candidate_ideas_blocks_when_selected_evidence_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_idea_inputs(workspace_root)
    (workspace_root / "ranked_evidence/evidence_selection.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:ranked_evidence/evidence_selection.json" in result.errors


def test_candidate_ideas_validation_rejects_forbidden_claims_and_sections() -> None:
    artifact = {
        "schema_version": "candidate_ideas_v1",
        "idea_set_id": "ideas_task",
        "gap_map_id": "gap_map_task",
        "landscape_id": "landscape_task",
        "evidence_ids": ["ecard_001"],
        "ideas": [
            {
                "idea_id": "idea_1",
                "title": "Unsupported idea",
                "summary": "This is novel and will improve performance.",
                "idea_type": "comparative_study",
                "gap_basis": {"gap_ids": ["gap_1"]},
                "evidence_basis": {"supporting_evidence_ids": ["ecard_001"]},
                "not_yet_screened": True,
                "requires_novelty_screening": True,
                "requires_feasibility_screening": True,
            }
        ],
    }
    markdown = "# Candidate Ideas\n\n## Novelty Screening\n\nThis is novel.\n"

    errors = validate_candidate_ideas_artifact(artifact, markdown)

    assert "forbidden_candidate_ideas_markdown_section:Novelty Screening" in errors
    assert "markdown_missing_evidence_references" in errors
    assert "unsupported_candidate_idea_claim" in errors


def test_p2_m14_plus_skills_remain_non_executable() -> None:
    future_skills = {
        "draft_evidence_grounded_report",
    }
    registry = build_default_skill_registry()

    assert future_skills.isdisjoint(EVIDENCE_SKILL_WRAPPERS)
    assert future_skills.issubset({skill.name for skill in registry.list_stub_skills()})
    assert registry.get_skill("build_claim_ledger").status == SkillStatus.AVAILABLE
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS


def test_idea_tools_have_no_cli_llm_database_or_controller_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/idea_tools.py").read_text(encoding="utf-8")
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
