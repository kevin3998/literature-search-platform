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
from modules.research_agent_controller.skills.manuscript_contract import (
    MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
)
from modules.research_agent_controller.skills.manuscript_tools import validate_manuscript_draft_artifact
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "manuscript_draft_task"


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(TASK_ID, task_markdown=f"# Task\n\nTopic: {TOPIC}\n")
    return tmp_path / "research_agent/research_tasks" / TASK_ID


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _execution(workspace_root: Path, *, input_artifacts: list[str] | None = None) -> SkillExecutionInput:
    return SkillExecutionInput(
        task_id=TASK_ID,
        workspace_root=str(workspace_root),
        skill_name="draft_manuscript_section",
        input_artifacts=list(input_artifacts or []),
        parameters={"topic": TOPIC, "target_section": "discussion_scaffold"},
    )


def _write_manuscript_inputs(workspace_root: Path) -> None:
    claim_ledger = {
        "schema_version": "claim_ledger_v1",
        "task_id": TASK_ID,
        "topic": TOPIC,
        "claim_ledger_id": "claim_ledger_manuscript_draft_task",
        "input_artifacts": [],
        "experiment_matrix_id": "experiment_matrix_manuscript_draft_task",
        "screening_id": "idea_screening_manuscript_draft_task",
        "idea_set_id": "candidate_ideas_manuscript_draft_task",
        "gap_map_id": "gap_map_manuscript_draft_task",
        "landscape_id": "landscape_manuscript_draft_task",
        "evidence_ids": ["ecard_001", "ecard_002"],
        "source_paper_ids": ["paper_001", "paper_002"],
        "claims": [
            _claim(
                "claim_literature_1",
                "Literature evidence records that oxygen vacancies modulate water dissociation in alkaline HER catalysts.",
                "literature_observation",
                "evidence_supported_literature_claim",
                ["evidence/evidence_cards.enriched.json", "ranked_evidence/evidence_selection.json"],
                evidence_ids=["ecard_001"],
                source_paper_ids=["paper_001"],
                allowed_downstream_use="background_context",
                support_level="medium",
            ),
            _claim(
                "claim_gap_1",
                "Gap records describe limited comparison coverage for oxygen-vacancy-tuned catalysts.",
                "gap_statement",
                "evidence_grounded_candidate",
                ["gaps/gap_map.json"],
                gap_ids=["gap_comparison_001"],
                evidence_ids=["ecard_001", "ecard_002"],
                source_paper_ids=["paper_001", "paper_002"],
                allowed_downstream_use="gap_framing",
                support_level="low",
            ),
            _claim(
                "claim_hypothesis_1",
                "Oxygen vacancy modulation remains a candidate hypothesis requiring validation.",
                "candidate_hypothesis",
                "hypothesis_requires_validation",
                ["claims/claim_ledger.json", "experiments/experiment_matrix.json"],
                source_idea_ids=["idea_gap_comparison_001"],
                source_experiment_ids=["exp_idea_gap_comparison_001"],
                gap_ids=["gap_comparison_001"],
                evidence_ids=["ecard_001", "ecard_002"],
                source_paper_ids=["paper_001", "paper_002"],
                allowed_downstream_use="hypothesis_framing",
                support_level="low",
            ),
            _claim(
                "claim_screening_1",
                "Screening remains preliminary and requires external novelty, feasibility, and risk review.",
                "screening_assessment",
                "screening_preliminary",
                ["screening/idea_screening_results.json"],
                source_idea_ids=["idea_gap_comparison_001"],
                gap_ids=["gap_comparison_001"],
                evidence_ids=["ecard_001"],
                source_paper_ids=["paper_001"],
                allowed_downstream_use="limitation_only",
                support_level="low",
                warnings=["screening_sparse_fixture"],
            ),
            _claim(
                "claim_matrix_1",
                "Experiment matrix entry is a planning scaffold rather than an experimental result.",
                "experiment_matrix_rationale",
                "matrix_planning_scaffold",
                ["experiments/experiment_matrix.json"],
                source_idea_ids=["idea_gap_comparison_001"],
                source_experiment_ids=["exp_idea_gap_comparison_001"],
                gap_ids=["gap_comparison_001"],
                evidence_ids=["ecard_002"],
                source_paper_ids=["paper_002"],
                allowed_downstream_use="planning_rationale",
                support_level="low",
                warnings=["experiment_matrix_sparse_fixture"],
            ),
            _claim(
                "claim_rejected_1",
                "This rejected overclaim is not suitable for draft use.",
                "limitation_statement",
                "rejected_overclaim",
                ["claims/claim_ledger.json"],
                evidence_ids=[],
                allowed_downstream_use="not_for_manuscript_claim",
                support_level="none",
                warnings=["rejected_overclaim_fixture"],
            ),
        ],
        "ledger_scope": {"real_experiments_interpreted": False, "manuscript_drafting_performed": False},
        "claim_policy": {"not_a_final_claim": True, "not_experimentally_validated": True, "requires_human_review": True},
        "limitations": ["Claim ledger is deterministic and requires human review."],
        "warnings": ["claim_ledger_warning", "experiment_matrix_sparse_fixture", "screening_sparse_fixture"],
    }
    _write_json(workspace_root / "claims/claim_ledger.json", claim_ledger)
    _write_json(
        workspace_root / "claims/claim_ledger_diagnostics.json",
        {
            "artifact_type": "claim_ledger_diagnostics",
            "claim_ledger_id": "claim_ledger_manuscript_draft_task",
            "claim_count": len(claim_ledger["claims"]),
            "warnings": ["claim_ledger_diagnostics_warning"],
            "schema_version": "claim_ledger_v1",
        },
    )
    _write_text(workspace_root / "claims/claim_ledger.md", "# Claim Ledger\n\n## Evidence References\n\n- evidence_id=ecard_001\n")
    _write_upstream_inputs(workspace_root)


def _claim(
    claim_id: str,
    claim_text: str,
    claim_type: str,
    claim_status: str,
    source_artifacts: list[str],
    *,
    evidence_ids: list[str],
    source_paper_ids: list[str] | None = None,
    source_idea_ids: list[str] | None = None,
    source_experiment_ids: list[str] | None = None,
    gap_ids: list[str] | None = None,
    allowed_downstream_use: str = "not_for_manuscript_claim",
    support_level: str = "low",
    warnings: list[str] | None = None,
) -> dict:
    return {
        "claim_id": claim_id,
        "claim_text": claim_text,
        "claim_type": claim_type,
        "claim_status": claim_status,
        "source_artifacts": source_artifacts,
        "source_idea_ids": list(source_idea_ids or []),
        "source_experiment_ids": list(source_experiment_ids or []),
        "gap_ids": list(gap_ids or []),
        "evidence_ids": list(evidence_ids),
        "source_paper_ids": list(source_paper_ids or []),
        "supporting_evidence": [{"evidence_id": evidence_id} for evidence_id in evidence_ids],
        "upstream_dependencies": {
            "experiment_matrix_ids": ["experiment_matrix_manuscript_draft_task"],
            "screening_ids": ["idea_screening_manuscript_draft_task"],
            "idea_set_ids": ["candidate_ideas_manuscript_draft_task"],
            "landscape_cluster_ids": ["cluster_mechanism"],
            "diagnostic_refs": ["coverage:missing_figure_source_type"],
        },
        "support_level": support_level,
        "allowed_downstream_use": allowed_downstream_use,
        "prohibited_uses": ["final_claim", "manuscript_conclusion"],
        "limitations": ["Requires human review."],
        "not_a_final_claim": True,
        "not_experimentally_validated": True,
        "requires_human_review": True,
        "warnings": list(warnings or []),
    }


def _write_upstream_inputs(workspace_root: Path) -> None:
    base = {
        "task_id": TASK_ID,
        "topic": TOPIC,
        "evidence_ids": ["ecard_001", "ecard_002"],
        "source_paper_ids": ["paper_001", "paper_002"],
        "warnings": ["upstream_warning"],
    }
    for relative_path, payload in {
        "experiments/experiment_matrix.json": {
            **base,
            "experiment_matrix_id": "experiment_matrix_manuscript_draft_task",
            "screening_id": "idea_screening_manuscript_draft_task",
            "idea_set_id": "candidate_ideas_manuscript_draft_task",
            "gap_map_id": "gap_map_manuscript_draft_task",
            "landscape_id": "landscape_manuscript_draft_task",
            "experiment_candidates": [{"experiment_id": "exp_idea_gap_comparison_001", "evidence_ids": ["ecard_001"]}],
            "schema_version": "experiment_matrix_v1",
        },
        "experiments/experiment_matrix_diagnostics.json": {"artifact_type": "experiment_matrix_diagnostics", "warnings": ["experiment_matrix_diag_warning"], "schema_version": "experiment_matrix_v1"},
        "screening/idea_screening_results.json": valid_screening_v2_artifact(
            task_id=TASK_ID,
            screening_id="idea_screening_manuscript_draft_task",
            idea_set_id="candidate_ideas_manuscript_draft_task",
            gap_map_id="gap_map_manuscript_draft_task",
            landscape_id="landscape_manuscript_draft_task",
        ),
        "screening/screening_diagnostics.json": {"artifact_type": "screening_diagnostics", "warnings": ["screening_diag_warning"], "schema_version": "idea_screening_v2"},
        "ideas/candidate_ideas.json": {**base, "idea_set_id": "candidate_ideas_manuscript_draft_task", "schema_version": "candidate_ideas_v1"},
        "ideas/idea_generation_diagnostics.json": {"artifact_type": "idea_generation_diagnostics", "warnings": ["idea_diag_warning"], "schema_version": "candidate_ideas_v1"},
        "gaps/gap_map.json": {**base, "gap_map_id": "gap_map_manuscript_draft_task", "schema_version": "gap_map_v1"},
        "gaps/gap_coverage_diagnostics.json": {"artifact_type": "gap_coverage_diagnostics", "warnings": ["gap_diag_warning"], "schema_version": "gap_map_v1"},
        "landscape/literature_landscape.json": {**base, "landscape_id": "landscape_manuscript_draft_task", "schema_version": "landscape_v1"},
        "landscape/landscape_coverage_diagnostics.json": {"artifact_type": "landscape_coverage_diagnostics", "warnings": ["landscape_diag_warning"], "schema_version": "landscape_v1"},
        "evidence/evidence_cards.enriched.json": {
            "artifact_type": "evidence_cards",
            "stage": "enriched",
            "cards": [
                {"evidence_id": "ecard_001", "paper_id": "paper_001", "normalized_statement": "Oxygen vacancy evidence."},
                {"evidence_id": "ecard_002", "paper_id": "paper_002", "normalized_statement": "Sparse comparison evidence."},
            ],
            "warnings": ["enriched_warning"],
        },
        "ranked_evidence/evidence_selection.json": {"artifact_type": "evidence_selection", "selected_cards": [{"evidence_id": "ecard_001"}], "warnings": ["selection_warning"]},
        "ranked_evidence/coverage_diagnostics.json": {"artifact_type": "coverage_diagnostics", "warnings": ["coverage_warning"]},
    }.items():
        _write_json(workspace_root / relative_path, payload)
    for relative_path in [
        "experiments/experiment_matrix.md",
        "screening/idea_screening_results.md",
        "ideas/candidate_ideas.md",
        "gaps/gap_map.md",
        "landscape/literature_landscape.md",
    ]:
        _write_text(workspace_root / relative_path, "# Fixture\n\n## Evidence References\n\n- evidence_id=ecard_001\n")
    _write_json(
        workspace_root / "reports/minimal_topic_to_evidence_report.json",
        {"artifact_type": "minimal_topic_to_evidence_report", "evidence_references": ["ecard_001"]},
    )


def test_manuscript_drafting_skill_is_available_and_executable_after_p2_m14_2() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("draft_manuscript_section")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert "draft_manuscript_section" in EVIDENCE_SKILL_WRAPPERS
    assert registry.get_skill("draft_evidence_grounded_report").status == SkillStatus.STUB
    assert "draft_evidence_grounded_report" not in EVIDENCE_SKILL_WRAPPERS


def test_manuscript_drafting_wrapper_writes_bounded_schema_and_markdown(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_manuscript_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.SUCCESS
    assert result.output_artifacts == MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS
    artifact = _read_json(workspace_root / "drafts/manuscript_section_draft.json")
    diagnostics = _read_json(workspace_root / "drafts/manuscript_section_diagnostics.json")
    markdown = (workspace_root / "drafts/manuscript_section_draft.md").read_text(encoding="utf-8")

    assert artifact["schema_version"] == "manuscript_section_draft_v1"
    assert artifact["draft_id"]
    assert artifact["claim_ledger_id"] == "claim_ledger_manuscript_draft_task"
    assert artifact["experiment_matrix_id"] == "experiment_matrix_manuscript_draft_task"
    assert artifact["screening_id"] == "idea_screening_manuscript_draft_task"
    assert artifact["idea_set_id"] == "candidate_ideas_manuscript_draft_task"
    assert artifact["gap_map_id"] == "gap_map_manuscript_draft_task"
    assert artifact["landscape_id"] == "landscape_manuscript_draft_task"
    assert artifact["draft_blocks"]
    assert all(block["block_id"] for block in artifact["draft_blocks"])
    assert all(block["block_type"] for block in artifact["draft_blocks"])
    assert all(block["text"] for block in artifact["draft_blocks"])
    assert all(block["claim_ids"] for block in artifact["draft_blocks"] if block["block_type"] not in {"transition", "caution"})
    assert any(block["evidence_ids"] for block in artifact["draft_blocks"])
    assert all(block["requires_human_review"] is True for block in artifact["draft_blocks"])
    assert all(block["not_final_text"] is True for block in artifact["draft_blocks"])
    assert all(block["not_peer_reviewed"] is True for block in artifact["draft_blocks"])
    assert all(block["not_experimentally_validated"] is True for block in artifact["draft_blocks"])
    assert artifact["citation_map"]
    assert all(item["claim_id"] for item in artifact["citation_map"])
    assert all(item["evidence_ids"] for item in artifact["citation_map"])
    assert all(item["source_paper_ids"] for item in artifact["citation_map"])
    assert artifact["unsupported_claims"]
    assert any(item["reason"] == "overclaim" for item in artifact["unsupported_claims"])
    assert "## Evidence References" in markdown
    for forbidden in ["## Final Abstract", "## Final Results", "## Final Discussion", "## Final Conclusion", "## Final Claims", "## Submission-Ready Manuscript"]:
        assert forbidden not in markdown
    assert validate_manuscript_draft_artifact(artifact, markdown) == []
    assert diagnostics["draft_block_count"] == len(artifact["draft_blocks"])
    assert "claim_ledger_warning" in artifact["warnings"]
    assert "coverage_warning" in artifact["warnings"]
    assert result.metadata["llm_called"] is False
    assert result.metadata["final_manuscript_generated"] is False
    assert result.metadata["final_claims_generated"] is False


def test_manuscript_draft_result_can_be_registered_in_manifest_and_audit(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_manuscript_inputs(workspace_root)
    result = execute_evidence_skill(_execution(workspace_root))

    record_skill_execution_result(result, workspace_root)

    manifest = load_artifact_manifest(workspace_root, TASK_ID)
    paths = {artifact.path for artifact in manifest.artifacts}
    assert set(result.output_artifacts).issubset(paths)
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")


def test_manuscript_drafting_rejects_retrieval_input_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_manuscript_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root, input_artifacts=["retrieval/source_candidate_packet.json"]))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_manuscript_drafting" in result.errors
    assert not (workspace_root / "drafts/manuscript_section_draft.json").exists()


def test_manuscript_drafting_blocks_when_required_inputs_are_missing(tmp_path: Path) -> None:
    cases = [
        ("claims/claim_ledger.json", "missing_claim_ledger_artifact"),
        ("experiments/experiment_matrix.json", "missing_experiment_matrix_artifact"),
        ("screening/idea_screening_results.json", "missing_screening_results_artifact"),
        ("ideas/candidate_ideas.json", "missing_candidate_ideas_artifact"),
        ("gaps/gap_map.json", "missing_gap_map_artifact"),
        ("landscape/literature_landscape.json", "missing_landscape_artifact"),
        ("evidence/evidence_cards.enriched.json", "missing_manuscript_drafting_input:evidence/evidence_cards.enriched.json"),
    ]
    for relative_path, expected_error in cases:
        workspace_root = _workspace(tmp_path / relative_path.replace("/", "_"))
        _write_manuscript_inputs(workspace_root)
        (workspace_root / relative_path).unlink()

        result = execute_evidence_skill(_execution(workspace_root))

        assert result.status == SkillExecutionStatus.BLOCKED
        assert expected_error in result.errors
        assert not (workspace_root / "drafts/manuscript_section_draft.json").exists()


def test_manuscript_drafting_rejects_invalid_claim_ledger(tmp_path: Path) -> None:
    cases = [
        (lambda ledger: ledger.update({"claims": []}), "manuscript_drafting_requires_claim_ledger"),
        (
            lambda ledger: ledger["claims"][0].update({"evidence_ids": [], "source_artifacts": []}),
            "manuscript_drafting_requires_traceable_claims",
        ),
        (
            lambda ledger: ledger["claims"][0].update({"claim_text": "We demonstrate this validated result is publication-ready."}),
            "manuscript_drafting_rejects_unvalidated_claims",
        ),
        (
            lambda ledger: ledger["claims"][0].update({"not_a_final_claim": False}),
            "manuscript_drafting_rejects_final_claim_overwrite",
        ),
    ]
    for mutate, expected_error in cases:
        workspace_root = _workspace(tmp_path / expected_error)
        _write_manuscript_inputs(workspace_root)
        ledger = _read_json(workspace_root / "claims/claim_ledger.json")
        mutate(ledger)
        _write_json(workspace_root / "claims/claim_ledger.json", ledger)

        result = execute_evidence_skill(_execution(workspace_root))

        assert result.status == SkillExecutionStatus.VALIDATION_FAILED
        assert expected_error in result.errors
        assert not (workspace_root / "drafts/manuscript_section_draft.json").exists()


def test_manuscript_draft_validation_rejects_forbidden_sections_and_phrases(tmp_path: Path) -> None:
    artifact = {
        "schema_version": "manuscript_section_draft_v1",
        "draft_id": "draft_bad",
        "draft_blocks": [
            {
                "block_id": "block_001",
                "block_type": "hypothesis_framing",
                "text": "We demonstrate this validated result is publication-ready.",
                "claim_ids": ["claim_001"],
                "evidence_ids": ["ecard_001"],
                "source_paper_ids": ["paper_001"],
                "requires_human_review": True,
                "not_final_text": True,
                "not_peer_reviewed": True,
                "not_experimentally_validated": True,
            }
        ],
        "citation_map": [{"claim_id": "claim_001", "evidence_ids": ["ecard_001"], "source_paper_ids": ["paper_001"], "source_artifacts": ["claims/claim_ledger.json"]}],
    }
    markdown = "# Manuscript Section Draft\n\n## Final Conclusion\n\nWe conclude this is ready for publication.\n"

    errors = validate_manuscript_draft_artifact(artifact, markdown)

    assert "forbidden_manuscript_draft_markdown_section:Final Conclusion" in errors
    assert "markdown_missing_evidence_references" in errors
    assert "manuscript_drafting_rejects_final_claim_overwrite" in errors


def test_manuscript_tools_have_no_cli_llm_database_or_controller_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/manuscript_tools.py").read_text(encoding="utf-8")
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
    ]
    for token in forbidden:
        assert token not in source
