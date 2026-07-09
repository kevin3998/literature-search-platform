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
from modules.research_agent_controller.skills.screening_tools import validate_screening_artifact
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "screening_task"


class ScriptedScreeningLLM:
    def __init__(self, payload: dict | None = None, text: str | None = None) -> None:
        self.payload = payload
        self.text = text
        self.messages = []

    async def stream_chat(self, messages, tools=None):
        self.messages.append(messages)
        text = self.text if self.text is not None else json.dumps(self.payload or _valid_llm_screening_payload(), ensure_ascii=False)
        yield {"type": "content", "text": text}


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
        skill_name="screen_novelty_feasibility_risk",
        input_artifacts=list(input_artifacts or []),
        parameters={"topic": TOPIC},
    )


def _valid_llm_screening_payload() -> dict:
    return {
        "screened_ideas": [
            {
                "idea_id": "idea_gap_comparison_001",
                "source_idea_title": "Candidate idea from comparison gap",
                "gap_ids": ["gap_comparison_001"],
                "evidence_ids": ["ecard_001", "ecard_002"],
                "local_novelty_triage": {
                    "judgment": "partial_overlap_with_local_evidence",
                    "confidence": "medium",
                    "closest_local_prior_evidence": [
                        {
                            "evidence_id": "ecard_001",
                            "paper_id": "paper_001",
                            "overlap": "Both discuss oxygen-vacancy modulation of alkaline HER mechanisms.",
                            "difference": "The candidate targets comparison coverage rather than asserting a validated route.",
                        }
                    ],
                    "rationale": "The local evidence overlaps mechanistically but does not fully cover the comparison gap.",
                    "limitations": ["Only local evidence cards were considered."],
                },
                "external_novelty_search": {
                    "status": "not_performed",
                    "required": True,
                    "rationale": "External prior-work search is required before novelty claims.",
                },
                "feasibility_triage": {
                    "judgment": "partially_supported",
                    "confidence": "medium",
                    "supporting_evidence": ["ecard_001", "ecard_002"],
                    "missing_requirements": ["synthesis route", "characterization evidence"],
                    "constraints": ["Requires expert feasibility review."],
                    "rationale": "Evidence supports the mechanism context but not complete execution conditions.",
                },
                "risk_triage": {
                    "judgment": "evidence_gap_risk",
                    "confidence": "medium",
                    "risk_factors": ["limited figure evidence", "sparse comparison coverage"],
                    "follow_up": ["external novelty search", "expert feasibility review", "risk review"],
                    "rationale": "The main risk is evidence coverage rather than a proven technical blocker.",
                },
                "overall_triage": {
                    "judgment": "advance_to_external_novelty_search",
                    "rationale": "The idea is locally grounded but needs external novelty search before prioritization.",
                    "required_follow_up": ["external novelty search", "expert feasibility review", "risk review"],
                },
                "not_an_experiment_plan": True,
                "not_a_validated_claim": True,
            }
        ]
    }


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
        "entities": {"materials": ["alkaline HER catalysts"], "mechanisms": ["water dissociation"]},
        "relations": [],
        "support": {"support_strength": "direct", "extraction_confidence": 0.8},
        "relevance": {"topic": TOPIC, "relevance_score": 0.91},
    }


def _write_screening_inputs(workspace_root: Path) -> None:
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
            "landscape_id": "landscape_screening_task",
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
            "landscape_id": "landscape_screening_task",
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root / "gaps/gap_map.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "gap_map_id": "gap_map_screening_task",
            "landscape_id": "landscape_screening_task",
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
            "gap_map_id": "gap_map_screening_task",
            "warnings": ["gap_sparse_axis_warning"],
            "schema_version": "gap_map_v1",
        },
    )
    _write_json(
        workspace_root / "ideas/candidate_ideas.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "idea_set_id": "candidate_ideas_screening_task",
            "input_artifacts": [],
            "gap_map_id": "gap_map_screening_task",
            "landscape_id": "landscape_screening_task",
            "evidence_ids": ["ecard_001", "ecard_002"],
            "source_paper_ids": ["paper_001", "paper_002"],
            "ideas": [
                {
                    "idea_id": "idea_gap_comparison_001",
                    "title": "Candidate idea from comparison gap",
                    "summary": "This candidate direction is grounded in the comparison gap and requires screening.",
                    "idea_type": "comparative_study",
                    "gap_basis": {
                        "gap_ids": ["gap_comparison_001"],
                        "gap_types": ["comparison_gap"],
                        "landscape_cluster_ids": ["cluster_mechanism"],
                        "evidence_ids": ["ecard_001", "ecard_002"],
                        "coverage_warnings": ["landscape_sparse_cluster"],
                        "diagnostic_refs": ["axis_coverage:mechanistic_role"],
                    },
                    "evidence_basis": {
                        "supporting_evidence_ids": ["ecard_001", "ecard_002"],
                        "source_paper_ids": ["paper_001", "paper_002"],
                        "representative_claim_refs": ["landscape:cluster_mechanism:claim_1"],
                    },
                    "rationale": "The idea is grounded in gap_comparison_001 and selected evidence.",
                    "expected_contribution": "Clarify a documented comparison gap after downstream checks.",
                    "assumptions": ["Evidence coverage is sparse."],
                    "constraints": ["Requires external novelty search.", "Requires expert feasibility review."],
                    "not_yet_screened": True,
                    "requires_novelty_screening": True,
                    "requires_feasibility_screening": True,
                    "warnings": ["idea_sparse_support_warning"],
                }
            ],
            "generation_scope": {"source": "validated_gap_records"},
            "constraints": {"not_yet_screened": True},
            "limitations": ["Candidate ideas are unscreened."],
            "warnings": ["gap_sparse_axis_warning", "landscape_sparse_cluster", "missing_figure_source_type"],
            "created_at": 0,
            "schema_version": "candidate_ideas_v1",
        },
    )
    _write_json(
        workspace_root / "ideas/idea_generation_diagnostics.json",
        {
            "artifact_type": "idea_generation_diagnostics",
            "idea_set_id": "candidate_ideas_screening_task",
            "num_input_gaps": 1,
            "num_generated_ideas": 1,
            "warnings": ["idea_generation_sparse_fixture"],
            "downstream_screening_required": True,
            "schema_version": "candidate_ideas_v1",
        },
    )


def test_screening_skill_is_available_and_executable_after_p2_m11_2() -> None:
    registry = build_default_skill_registry()
    contract = registry.get_skill("screen_novelty_feasibility_risk")

    assert contract.status == SkillStatus.AVAILABLE
    assert contract.execution_mode.value == "llm_assisted"
    assert contract.requires_evidence_cards is True
    assert contract.allows_raw_chunks is False
    assert "screen_novelty_feasibility_risk" in EVIDENCE_SKILL_WRAPPERS


def test_screening_requires_llm_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "llm_required_for_screening" in result.errors
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_screening_wrapper_writes_bounded_schema_and_markdown(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    llm = ScriptedScreeningLLM()

    result = execute_evidence_skill(_execution(workspace_root), llm_client=llm)

    assert result.status == SkillExecutionStatus.SUCCESS
    assert result.output_artifacts == [
        "screening/idea_screening_results.json",
        "screening/idea_screening_results.md",
        "screening/screening_diagnostics.json",
    ]
    artifact = _read_json(workspace_root / "screening/idea_screening_results.json")
    diagnostics = _read_json(workspace_root / "screening/screening_diagnostics.json")
    markdown = (workspace_root / "screening/idea_screening_results.md").read_text(encoding="utf-8")

    assert artifact["schema_version"] == "idea_screening_v2"
    assert artifact["analysis_mode"] == "llm_assisted_local_evidence_triage"
    assert artifact["llm_provenance"]["external_novelty_search_performed"] is False
    assert artifact["screening_id"]
    assert artifact["idea_set_id"] == "candidate_ideas_screening_task"
    assert artifact["gap_map_id"] == "gap_map_screening_task"
    assert artifact["landscape_id"] == "landscape_screening_task"
    assert artifact["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert artifact["screened_ideas"]
    assert len(artifact["screened_ideas"]) == 1
    screened = artifact["screened_ideas"][0]
    assert screened["idea_id"] == "idea_gap_comparison_001"
    assert screened["gap_ids"] == ["gap_comparison_001"]
    assert screened["evidence_ids"] == ["ecard_001", "ecard_002"]
    assert screened["local_novelty_triage"]["judgment"] == "partial_overlap_with_local_evidence"
    assert screened["external_novelty_search"]["status"] == "not_performed"
    assert screened["feasibility_triage"]["judgment"] == "partially_supported"
    assert screened["risk_triage"]["judgment"] == "evidence_gap_risk"
    assert screened["overall_triage"]["judgment"] == "advance_to_external_novelty_search"
    assert {"external novelty search", "expert feasibility review", "risk review"}.issubset(
        set(screened["overall_triage"]["required_follow_up"])
    )
    assert screened["not_an_experiment_plan"] is True
    assert screened["not_a_validated_claim"] is True
    assert "gap_sparse_axis_warning" in artifact["warnings"]
    assert "landscape_sparse_cluster" in artifact["warnings"]
    assert "missing_figure_source_type" in artifact["warnings"]
    assert diagnostics["num_input_ideas"] == 1
    assert diagnostics["num_screened_ideas"] == 1
    assert diagnostics["analysis_mode"] == "llm_assisted_local_evidence_triage"
    assert diagnostics["external_novelty_search_performed"] is False
    assert diagnostics["llm_called"] is True
    assert diagnostics["forbidden_claim_checks"]["passed"] is True
    assert "# LLM 辅助筛选摘要" in markdown
    assert "## 证据引用" in markdown
    assert "局部新颖性筛选：与本地证据部分重叠" in markdown
    assert "idea_id=idea_gap_comparison_001" in markdown
    assert "gap_id=gap_comparison_001" in markdown
    assert "evidence_id=ecard_001" in markdown
    assert "paper_id=paper_001" in markdown
    assert "landscape_cluster_id=cluster_mechanism" in markdown
    assert "diagnostic reference=" not in markdown
    assert "screening/screening_diagnostics.json" in markdown
    for forbidden in [
        "## Experiment Plan",
        "## Experimental Protocol",
        "## Manuscript Draft",
        "## Final Claims",
    ]:
        assert forbidden not in markdown
    serialized = json.dumps(artifact, ensure_ascii=False).lower()
    for forbidden_phrase in ["is novel", "confirmed novel", "definitely novel", "is feasible", "ready to synthesize", "ready to test", "will improve"]:
        assert forbidden_phrase not in serialized
        assert forbidden_phrase not in markdown.lower()
    assert validate_screening_artifact(artifact, markdown) == []


def test_screening_prompt_and_markdown_are_human_readable_chinese(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    llm = ScriptedScreeningLLM()

    result = execute_evidence_skill(_execution(workspace_root), llm_client=llm)

    assert result.status == SkillExecutionStatus.SUCCESS
    prompt_text = "\n".join(message["content"] for message in llm.messages[0])
    markdown = (workspace_root / "screening/idea_screening_results.md").read_text(encoding="utf-8")

    assert "用中文撰写" in prompt_text
    assert "# LLM 辅助筛选摘要" in markdown
    assert "## 范围" in markdown
    assert "## 边界" in markdown
    assert "## 证据引用" in markdown
    assert "局部新颖性筛选：与本地证据部分重叠" in markdown
    assert "外部新颖性检索：未执行" in markdown


def test_screening_result_can_be_registered_in_manifest_and_audit(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    result = execute_evidence_skill(_execution(workspace_root), llm_client=ScriptedScreeningLLM())

    record_skill_execution_result(result, workspace_root)

    manifest = load_artifact_manifest(workspace_root, TASK_ID)
    paths = {artifact.path for artifact in manifest.artifacts}
    assert set(result.output_artifacts).issubset(paths)
    assert read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")


def test_screening_rejects_retrieval_input_without_writing_outputs(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)

    result = execute_evidence_skill(
        _execution(workspace_root, input_artifacts=["retrieval/source_candidate_packet.json"])
    )

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "raw_retrieval_candidates_not_allowed_for_screening" in result.errors
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_screening_blocks_when_candidate_ideas_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    (workspace_root / "ideas/candidate_ideas.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_candidate_ideas_artifact" in result.errors


def test_screening_blocks_when_gap_map_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    (workspace_root / "gaps/gap_map.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:gaps/gap_map.json" in result.errors


def test_screening_blocks_when_landscape_json_is_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    (workspace_root / "landscape/literature_landscape.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:landscape/literature_landscape.json" in result.errors


def test_screening_blocks_when_enriched_cards_are_missing(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    (workspace_root / "evidence/evidence_cards.enriched.json").unlink()

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.BLOCKED
    assert "missing_input_artifact:evidence/evidence_cards.enriched.json" in result.errors


def test_screening_rejects_candidate_idea_without_gap_or_evidence_basis(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    candidate = _read_json(workspace_root / "ideas/candidate_ideas.json")
    candidate["ideas"][0]["gap_basis"] = {"gap_ids": []}
    candidate["ideas"][0]["evidence_basis"] = {"supporting_evidence_ids": []}
    _write_json(workspace_root / "ideas/candidate_ideas.json", candidate)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "screening_requires_gap_and_evidence_basis" in result.errors
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_screening_rejects_candidate_idea_already_screened(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    candidate = _read_json(workspace_root / "ideas/candidate_ideas.json")
    candidate["ideas"][0]["not_yet_screened"] = False
    _write_json(workspace_root / "ideas/candidate_ideas.json", candidate)

    result = execute_evidence_skill(_execution(workspace_root))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "screening_requires_unscreened_candidate_ideas" in result.errors
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_screening_rejects_llm_unknown_evidence_reference(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    payload = _valid_llm_screening_payload()
    payload["screened_ideas"][0]["evidence_ids"] = ["ecard_missing"]

    result = execute_evidence_skill(_execution(workspace_root), llm_client=ScriptedScreeningLLM(payload))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "unknown_screening_evidence_id:idea_gap_comparison_001:ecard_missing" in result.errors
    assert not (workspace_root / "screening/idea_screening_results.json").exists()


def test_screening_rejects_llm_unknown_gap_reference(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    payload = _valid_llm_screening_payload()
    payload["screened_ideas"][0]["gap_ids"] = ["gap_missing"]

    result = execute_evidence_skill(_execution(workspace_root), llm_client=ScriptedScreeningLLM(payload))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "unknown_screening_gap_id:idea_gap_comparison_001:gap_missing" in result.errors


def test_screening_rejects_llm_forbidden_claim(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _write_screening_inputs(workspace_root)
    payload = _valid_llm_screening_payload()
    payload["screened_ideas"][0]["local_novelty_triage"]["rationale"] = "This is confirmed novel."

    result = execute_evidence_skill(_execution(workspace_root), llm_client=ScriptedScreeningLLM(payload))

    assert result.status == SkillExecutionStatus.VALIDATION_FAILED
    assert "unsupported_screening_claim" in result.errors


def test_screening_validation_rejects_forbidden_claims_and_sections() -> None:
    artifact = {
        "schema_version": "idea_screening_v2",
        "screening_id": "screening_task",
        "idea_set_id": "ideas_task",
        "gap_map_id": "gap_map_task",
        "landscape_id": "landscape_task",
        "evidence_ids": ["ecard_001"],
        "screened_ideas": [
            {
                "idea_id": "idea_1",
                "source_idea_title": "Unsupported screen",
                "gap_ids": ["gap_1"],
                "evidence_ids": ["ecard_001"],
                "local_novelty_triage": {"judgment": "partial_overlap_with_local_evidence", "confidence": "low", "closest_local_prior_evidence": [], "rationale": "This idea is confirmed novel.", "limitations": ["x"]},
                "external_novelty_search": {"status": "not_performed", "required": True, "rationale": "Needs search."},
                "feasibility_triage": {"judgment": "partially_supported", "confidence": "low", "supporting_evidence": ["ecard_001"], "missing_requirements": ["x"], "constraints": [], "rationale": "No review."},
                "risk_triage": {"judgment": "evidence_gap_risk", "confidence": "low", "risk_factors": ["x"], "follow_up": ["review"], "rationale": "No review."},
                "overall_triage": {"judgment": "advance_to_external_novelty_search", "rationale": "Needs checks.", "required_follow_up": []},
                "not_an_experiment_plan": True,
                "not_a_validated_claim": True,
            }
        ],
    }
    markdown = "# Idea Screening Results\n\n## Experiment Plan\n\nThis idea is feasible.\n"

    errors = validate_screening_artifact(artifact, markdown)

    assert "forbidden_screening_markdown_section:Experiment Plan" in errors
    assert "markdown_missing_evidence_references" in errors
    assert "unsupported_screening_claim" in errors


def test_p2_m14_plus_skills_remain_non_executable() -> None:
    future_skills = {
        "draft_evidence_grounded_report",
    }
    registry = build_default_skill_registry()

    assert future_skills.isdisjoint(EVIDENCE_SKILL_WRAPPERS)
    assert future_skills.issubset({skill.name for skill in registry.list_stub_skills()})
    assert registry.get_skill("build_claim_ledger").status == SkillStatus.AVAILABLE
    assert "build_claim_ledger" in EVIDENCE_SKILL_WRAPPERS


def test_screening_tools_have_no_cli_llm_database_or_controller_dependency() -> None:
    source = Path("backend/modules/research_agent_controller/skills/screening_tools.py").read_text(encoding="utf-8")
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
        "modules.evidence_workflow",
        "modules.workflow",
        "workflow_router",
    ]
    for token in forbidden:
        assert token not in source
