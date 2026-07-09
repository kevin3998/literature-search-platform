import json
from pathlib import Path

from screening_v2_helpers import valid_screening_v2_artifact

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
from modules.research_agent_controller.skills.experiment_matrix_contract import EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS
from modules.research_agent_controller.skills.experiment_matrix_tools import validate_experiment_matrix_artifact
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "experiment_matrix_task"


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
        skill_name="create_experiment_matrix",
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


def _write_experiment_matrix_inputs(workspace_root: Path) -> None:
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
            "ranked_cards": [{"evidence_id": card["evidence_id"], "card": card, "selected": True} for card in cards],
            "warnings": ["dominant_paper_warning"],
        },
    )
    _write_json(
        workspace_root / "ranked_evidence/coverage_diagnostics.json",
        {
            "artifact_type": "coverage_diagnostics",
            "coverage": {"missing_required_roles": ["figure_evidence"], "source_type_coverage": {"text": 2}},
            "warnings": ["missing_figure_source_type"],
        },
    )
    _write_json(
        workspace_root / "landscape/literature_landscape.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "landscape_id": "landscape_experiment_matrix_task",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "clusters": [
                {
                    "cluster_id": "cluster_mechanism",
                    "title": "Mechanism Cluster",
                    "evidence_ids": ["ecard_001"],
                    "source_paper_ids": ["paper_001"],
                    "representative_claims": [
                        {"claim": "Oxygen vacancies modulate water dissociation.", "evidence_ids": ["ecard_001"]}
                    ],
                }
            ],
            "coverage": {"coverage_warnings": ["landscape_sparse_cluster"]},
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "landscape_id": "landscape_experiment_matrix_task",
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "gaps/gap_map.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "gap_map_id": "gap_map_experiment_matrix_task",
            "landscape_id": "landscape_experiment_matrix_task",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "gaps": [
                {
                    "gap_id": "gap_comparison_001",
                    "gap_type": "comparison_gap",
                    "title": "Limited comparison coverage",
                    "basis": {
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "evidence_ids": ["ecard_001", "ecard_002"],
                        "coverage_warnings": ["landscape_sparse_cluster"],
                        "diagnostic_refs": ["axis_coverage:mechanistic_role"],
                    },
                    "not_an_idea": True,
                    "warnings": [],
                }
            ],
            "coverage": {"coverage_warnings": ["gap_sparse_axis_warning"]},
            "supporting_evidence": [
                {"evidence_id": "ecard_001", "paper_id": "paper_001", "gap_ids": ["gap_comparison_001"]},
                {"evidence_id": "ecard_002", "paper_id": "paper_002", "gap_ids": ["gap_comparison_001"]},
            ],
            "warnings": ["gap_sparse_axis_warning"],
            "schema_version": "gap_map_v1",
        },
    )
    _write_json(
        workspace_root / "gaps/gap_coverage_diagnostics.json",
        {
            "artifact_type": "gap_coverage_diagnostics",
            "gap_map_id": "gap_map_experiment_matrix_task",
            "warnings": ["gap_sparse_axis_warning"],
            "schema_version": "gap_map_v1",
        },
    )
    _write_json(
        workspace_root / "ideas/candidate_ideas.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "idea_set_id": "candidate_ideas_experiment_matrix_task",
            "gap_map_id": "gap_map_experiment_matrix_task",
            "landscape_id": "landscape_experiment_matrix_task",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "ideas": [
                {
                    "idea_id": "idea_gap_comparison_001",
                    "title": "Candidate idea from comparison gap",
                    "summary": "This candidate direction is grounded in the comparison gap and requires screening.",
                    "gap_basis": {
                        "gap_ids": ["gap_comparison_001"],
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "evidence_ids": ["ecard_001", "ecard_002"],
                        "coverage_warnings": ["landscape_sparse_cluster"],
                    },
                    "evidence_basis": {
                        "supporting_evidence_ids": ["ecard_001", "ecard_002"],
                        "source_paper_ids": ["paper_001", "paper_002"],
                    },
                    "rationale": "The idea is grounded in gap_comparison_001 and selected evidence.",
                    "constraints": ["Requires external novelty search.", "Requires expert feasibility review."],
                    "not_yet_screened": True,
                    "requires_novelty_screening": True,
                    "requires_feasibility_screening": True,
                    "warnings": ["idea_sparse_support_warning"],
                }
            ],
            "warnings": ["idea_generation_sparse_fixture"],
            "schema_version": "candidate_ideas_v1",
        },
    )
    _write_json(
        workspace_root / "ideas/idea_generation_diagnostics.json",
        {
            "artifact_type": "idea_generation_diagnostics",
            "idea_set_id": "candidate_ideas_experiment_matrix_task",
            "warnings": ["idea_generation_sparse_fixture"],
            "schema_version": "candidate_ideas_v1",
        },
    )
    _write_json(
        workspace_root / "screening/idea_screening_results.json",
        valid_screening_v2_artifact(
            task_id=TASK_ID,
            screening_id="idea_screening_experiment_matrix_task",
            idea_set_id="candidate_ideas_experiment_matrix_task",
            gap_map_id="gap_map_experiment_matrix_task",
            landscape_id="landscape_experiment_matrix_task",
        ),
    )
    _write_json(
        workspace_root / "screening/screening_diagnostics.json",
        {
            "artifact_type": "screening_diagnostics",
            "screening_id": "idea_screening_experiment_matrix_task",
            "warnings": ["screening_diagnostics_fixture"],
            "schema_version": "idea_screening_v2",
        },
    )


def test_experiment_matrix_skill_is_available_and_executable_after_p2_m12_2() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("create_experiment_matrix")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert "create_experiment_matrix" in EVIDENCE_SKILL_WRAPPERS


def test_experiment_matrix_wrapper_writes_bounded_schema_and_markdown(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_experiment_matrix_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.SUCCESS
    assert result.output_artifacts == EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS
    artifact = _read_json(workspace_root / "experiments/experiment_matrix.json")
    diagnostics = _read_json(workspace_root / "experiments/experiment_matrix_diagnostics.json")
    markdown = (workspace_root / "experiments/experiment_matrix.md").read_text(encoding="utf-8")

    assert artifact["schema_version"] == "experiment_matrix_v1"
    assert artifact["experiment_matrix_id"]
    assert artifact["screening_id"] == "idea_screening_experiment_matrix_task"
    assert artifact["idea_set_id"] == "candidate_ideas_experiment_matrix_task"
    assert artifact["gap_map_id"] == "gap_map_experiment_matrix_task"
    assert artifact["landscape_id"] == "landscape_experiment_matrix_task"
    assert artifact["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert artifact["experiment_candidates"]
    candidate = artifact["experiment_candidates"][0]
    assert candidate["source_idea_id"] == "idea_gap_comparison_001"
    assert candidate["screening_basis"]["novelty_status"] == "requires_external_search"
    assert candidate["screening_basis"]["feasibility_status"] == "requires_expert_review"
    assert candidate["screening_basis"]["risk_status"] == "requires_risk_review"
    assert candidate["gap_ids"] == ["gap_comparison_001"]
    assert candidate["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert candidate["not_a_protocol"] is True
    assert candidate["not_a_validated_claim"] is True
    assert candidate["requires_expert_review"] is True
    assert candidate["design_variables"]
    assert all(variable["not_a_stepwise_instruction"] is True for variable in candidate["design_variables"])
    assert diagnostics["experiment_candidate_count"] == 1
    assert "screening_sparse_fixture" in artifact["warnings"]
    assert "missing_figure_source_type" in artifact["warnings"]
    assert "## Evidence References" in markdown
    assert "experiment_id=exp_idea_gap_comparison_001" in markdown
    assert "idea_id=idea_gap_comparison_001" in markdown
    assert "gap_id=gap_comparison_001" in markdown
    assert "evidence_id=ecard_001" in markdown
    assert "paper_id=paper_001" in markdown
    assert "landscape_cluster_id=cluster_mechanism" in markdown
    for forbidden in [
        "## Experimental Protocol",
        "## Step-by-step Procedure",
        "## Synthesis Recipe",
        "## Safety Protocol",
        "## Manuscript Draft",
        "## Final Claims",
    ]:
        assert forbidden not in markdown
    assert validate_experiment_matrix_artifact(artifact, markdown) == []


def test_experiment_matrix_result_can_be_registered_in_manifest_and_audit(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_experiment_matrix_inputs(workspace_root)
    result = execute_evidence_skill(_execution(workspace_root))

    record_skill_execution_result(result, workspace_root)

    manifest = load_artifact_manifest(workspace_root, TASK_ID)
    paths = {artifact.path for artifact in manifest.artifacts}
    assert set(result.output_artifacts).issubset(paths)
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")


def test_experiment_matrix_rejects_retrieval_input_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_experiment_matrix_inputs(workspace_root)

    result = execute_evidence_skill(
        _execution(workspace_root, input_artifacts=["retrieval/source_candidate_packet.json"])
    )

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_experiment_matrix" in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_experiment_matrix_blocks_when_required_inputs_are_missing(tmp_path: Path) -> None:
    cases = [
        ("screening/idea_screening_results.json", "missing_screening_results_artifact"),
        ("ideas/candidate_ideas.json", "missing_candidate_ideas_artifact"),
        ("gaps/gap_map.json", "missing_gap_map_artifact"),
        ("landscape/literature_landscape.json", "missing_landscape_artifact"),
        ("evidence/evidence_cards.enriched.json", "missing_input_artifact:evidence/evidence_cards.enriched.json"),
    ]
    for relative_path, expected_error in cases:
        workspace_root = _workspace(tmp_path / relative_path.replace("/", "_"))
        _write_experiment_matrix_inputs(workspace_root)
        (workspace_root / relative_path).unlink()

        result = execute_evidence_skill(_execution(workspace_root))

        assert result.status == SkillExecutionStatus.BLOCKED
        assert expected_error in result.errors
        assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_experiment_matrix_rejects_screening_without_screened_ideas(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_experiment_matrix_inputs(workspace_root)
    screening = _read_json(workspace_root / "screening/idea_screening_results.json")
    screening["screened_ideas"] = []
    _write_json(workspace_root / "screening/idea_screening_results.json", screening)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "experiment_matrix_requires_screened_ideas" in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_experiment_matrix_rejects_screened_idea_without_gap_or_evidence_basis(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_experiment_matrix_inputs(workspace_root)
    screening = _read_json(workspace_root / "screening/idea_screening_results.json")
    screening["screened_ideas"][0]["gap_ids"] = []
    screening["screened_ideas"][0]["evidence_ids"] = []
    _write_json(workspace_root / "screening/idea_screening_results.json", screening)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "experiment_matrix_requires_gap_and_evidence_basis" in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_experiment_matrix_rejects_v1_screening_schema(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_experiment_matrix_inputs(workspace_root)
    screening = _read_json(workspace_root / "screening/idea_screening_results.json")
    screening["schema_version"] = "idea_screening_v1"
    _write_json(workspace_root / "screening/idea_screening_results.json", screening)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "invalid_screening_schema_version" in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_experiment_matrix_rejects_screening_that_performed_external_search(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_experiment_matrix_inputs(workspace_root)
    screening = _read_json(workspace_root / "screening/idea_screening_results.json")
    screening["screened_ideas"][0]["external_novelty_search"]["status"] = "performed"
    _write_json(workspace_root / "screening/idea_screening_results.json", screening)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "external_novelty_search_status_must_be_not_performed:0" in result.errors
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()


def test_experiment_matrix_validation_rejects_forbidden_claims_and_sections() -> None:
    artifact = {
        "schema_version": "experiment_matrix_v1",
        "experiment_matrix_id": "experiment_matrix_task",
        "screening_id": "screening_task",
        "idea_set_id": "ideas_task",
        "gap_map_id": "gap_map_task",
        "landscape_id": "landscape_task",
        "evidence_ids": ["ecard_001"],
        "experiment_candidates": [
            {
                "experiment_id": "exp_1",
                "source_idea_id": "idea_1",
                "screened_idea_ref": "screening_task:idea_1",
                "gap_ids": ["gap_1"],
                "evidence_ids": ["ecard_001"],
                "screening_basis": {
                    "novelty_status": "requires_external_search",
                    "feasibility_status": "requires_expert_review",
                    "risk_status": "requires_risk_review",
                },
                "design_variables": [{"not_a_stepwise_instruction": True}],
                "not_a_protocol": True,
                "not_a_validated_claim": True,
                "requires_expert_review": True,
            }
        ],
    }
    markdown = "# Experiment Matrix\n\n## Experimental Protocol\n\nThis is feasible and will improve performance.\n"

    errors = validate_experiment_matrix_artifact(artifact, markdown)

    assert "forbidden_experiment_matrix_markdown_section:Experimental Protocol" in errors
    assert "markdown_missing_evidence_references" in errors
    assert "unsupported_experiment_matrix_claim" in errors


def test_p2_m14_plus_skills_remain_non_executable_after_claim_ledger_wrapper() -> None:
    future_skills = {
        "draft_evidence_grounded_report",
    }
    registry = build_default_skill_registry()

    assert future_skills.isdisjoint(EVIDENCE_SKILL_WRAPPERS)
    assert future_skills.issubset({skill.name for skill in registry.list_stub_skills()})
    assert registry.get_skill("build_claim_ledger").status == SkillStatus.AVAILABLE
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS


def test_experiment_matrix_tools_have_no_cli_llm_database_or_controller_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/experiment_matrix_tools.py").read_text(encoding="utf-8")
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
