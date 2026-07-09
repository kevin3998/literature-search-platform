import json
import os
from pathlib import Path

import pytest

from screening_v2_helpers import valid_screening_v2_artifact

from modules.research_agent_controller import (
    ClaudeCodeCliBackendConfig,
    CliWorkspaceAccessPolicy,
    RealClaudeCodeCliBackend,
    SkillRegistry,
    SkillStatus,
    build_default_skill_registry,
    detect_cli_output_format_issue,
    parse_cli_output,
)
from modules.research_agent_controller.skills.experiment_matrix_contract import (
    EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS,
    EXPERIMENT_MATRIX_OPTIONAL_INPUT_ARTIFACTS,
    EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
    validate_experiment_matrix_input_artifacts,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_experiment_matrix_decision_task"
INPUT_ARTIFACTS = EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS + EXPERIMENT_MATRIX_OPTIONAL_INPUT_ARTIFACTS
OUTPUT_ARTIFACTS = EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS
P2_M13_PLUS_SKILLS = {
    "build_claim_ledger",
    "draft_manuscript_section",
}


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n\n"
            "This is a bounded experiment matrix decision smoke test. The workspace already has "
            "screening results, candidate ideas, gap map, landscape, enriched Evidence Cards, ranked "
            "evidence, diagnostics, and a minimal report. Do not execute tools or modify workspace files.\n"
        ),
        plan_markdown=(
            "# Plan\n\n"
            "- retrieve_sources: completed\n"
            "- create_evidence_seeds: completed\n"
            "- extract_evidence_cards: completed\n"
            "- enrich_evidence_cards: completed\n"
            "- rank_evidence: completed\n"
            "- build_minimal_topic_to_evidence_report: completed\n"
            "- build_landscape: completed\n"
            "- map_gaps: completed\n"
            "- generate_candidate_ideas: completed\n"
            "- screen_novelty_feasibility_risk: completed\n"
            "- create_experiment_matrix: pending\n\n"
            "The next valid explicit step is create_experiment_matrix.\n"
        ),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_json(
        workspace_root,
        "screening/idea_screening_results.json",
        valid_screening_v2_artifact(
            task_id=TASK_ID,
            screening_id="idea_screening_smoke_experiment_matrix",
            idea_set_id="candidate_ideas_smoke_experiment_matrix",
            gap_map_id="gap_map_smoke_experiment_matrix",
            landscape_id="landscape_smoke_experiment_matrix",
            evidence_ids=["ecard_001"],
            source_paper_ids=["paper_001"],
        ),
    )
    _write_json(
        workspace_root,
        "screening/screening_diagnostics.json",
        {
            "schema_version": "idea_screening_v2",
            "artifact_type": "screening_diagnostics",
            "screening_id": "idea_screening_smoke_experiment_matrix",
            "warnings": ["experiment_matrix_decision_smoke_fixture"],
        },
    )
    _write_text(
        workspace_root,
        "screening/idea_screening_results.md",
        "# Idea Screening Results\n\n- idea_id=idea_001; gap_id=gap_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root,
        "ideas/candidate_ideas.json",
        {
            "schema_version": "candidate_ideas_v1",
            "task_id": TASK_ID,
            "idea_set_id": "candidate_ideas_smoke_experiment_matrix",
            "gap_map_id": "gap_map_smoke_experiment_matrix",
            "landscape_id": "landscape_smoke_experiment_matrix",
            "ideas": [{"idea_id": "idea_001", "gap_basis": {"gap_ids": ["gap_001"]}, "evidence_basis": {"supporting_evidence_ids": ["ecard_001"]}}],
        },
    )
    _write_json(
        workspace_root,
        "ideas/idea_generation_diagnostics.json",
        {
            "schema_version": "candidate_ideas_v1",
            "artifact_type": "idea_generation_diagnostics",
            "idea_set_id": "candidate_ideas_smoke_experiment_matrix",
            "warnings": ["idea_generation_smoke_fixture"],
        },
    )
    _write_text(workspace_root, "ideas/candidate_ideas.md", "# Candidate Ideas\n\n- idea_id=idea_001\n")
    _write_json(
        workspace_root,
        "gaps/gap_map.json",
        {
            "schema_version": "gap_map_v1",
            "artifact_type": "gap_map",
            "task_id": TASK_ID,
            "gap_map_id": "gap_map_smoke_experiment_matrix",
            "landscape_id": "landscape_smoke_experiment_matrix",
            "gaps": [{"gap_id": "gap_001", "gap_type": "comparison_gap", "evidence_ids": ["ecard_001"]}],
        },
    )
    _write_json(
        workspace_root,
        "gaps/gap_coverage_diagnostics.json",
        {
            "schema_version": "gap_map_v1",
            "artifact_type": "gap_coverage_diagnostics",
            "gap_map_id": "gap_map_smoke_experiment_matrix",
            "warnings": ["gap_sparse_axis_warning"],
        },
    )
    _write_text(workspace_root, "gaps/gap_map.md", "# Gap Map\n\n- gap_id=gap_001; evidence_id=ecard_001\n")
    _write_json(
        workspace_root,
        "landscape/literature_landscape.json",
        {
            "schema_version": "landscape_v1",
            "artifact_type": "literature_landscape",
            "task_id": TASK_ID,
            "landscape_id": "landscape_smoke_experiment_matrix",
            "clusters": [{"cluster_id": "cluster_001", "evidence_ids": ["ecard_001"]}],
        },
    )
    _write_json(
        workspace_root,
        "landscape/landscape_coverage_diagnostics.json",
        {
            "schema_version": "landscape_v1",
            "artifact_type": "landscape_coverage_diagnostics",
            "landscape_id": "landscape_smoke_experiment_matrix",
            "warnings": ["landscape_sparse_cluster"],
        },
    )
    _write_text(
        workspace_root,
        "landscape/literature_landscape.md",
        "# Literature Landscape\n\n- cluster_id=cluster_001; evidence_id=ecard_001\n",
    )
    _write_json(
        workspace_root,
        "evidence/evidence_cards.enriched.json",
        {
            "artifact_type": "evidence_cards",
            "stage": "enriched",
            "task_id": TASK_ID,
            "cards": [{"evidence_id": "ecard_001", "paper_id": "paper_001", "primary_role": "mechanism"}],
        },
    )
    _write_json(
        workspace_root,
        "ranked_evidence/evidence_selection.json",
        {
            "artifact_type": "evidence_selection",
            "selected_cards": [{"evidence_id": "ecard_001", "paper_id": "paper_001"}],
            "warnings": ["dominant_paper_warning"],
        },
    )
    _write_json(
        workspace_root,
        "ranked_evidence/coverage_diagnostics.json",
        {
            "artifact_type": "coverage_diagnostics",
            "coverage": {"missing_required_roles": ["figure_evidence"]},
            "warnings": ["missing_figure_source_type"],
        },
    )
    _write_json(
        workspace_root,
        "reports/minimal_topic_to_evidence_report.json",
        {
            "artifact_type": "minimal_topic_to_evidence_report",
            "scope": "minimal_topic_to_evidence",
            "evidence_references": ["ecard_001"],
        },
    )
    return workspace_root


def _write_json(workspace_root: Path, relative_path: str, payload: dict) -> None:
    path = workspace_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(workspace_root: Path, relative_path: str, text: str) -> None:
    path = workspace_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _snapshot(workspace_root: Path) -> dict:
    return {
        "task_id": workspace_root.name,
        "workspace_root": str(workspace_root),
        "task_md": (workspace_root / "task.md").read_text(encoding="utf-8"),
        "plan_md": (workspace_root / "plan.md").read_text(encoding="utf-8"),
        "state": json.loads((workspace_root / "state.json").read_text(encoding="utf-8")),
        "artifact_manifest": {
            "task_id": workspace_root.name,
            "artifacts": [{"artifact_id": path, "artifact_type": "input", "path": path} for path in INPUT_ARTIFACTS],
            "cli_controller_ready": False,
        },
        "recent_events": [],
        "step_index": 0,
    }


def _experiment_matrix_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("create_experiment_matrix"))
    return registry


def _policy(workspace_root: Path) -> CliWorkspaceAccessPolicy:
    return CliWorkspaceAccessPolicy(
        task_id=TASK_ID,
        workspace_root=str(workspace_root),
        allowed_read_paths=[
            "task.md",
            "plan.md",
            "state.json",
            "audit/artifact_manifest.json",
            "screening/",
            "ideas/",
            "gaps/",
            "landscape/",
            "evidence/",
            "ranked_evidence/",
            "reports/",
        ],
        allowed_write_paths=["experiments/"],
        forbidden_paths=["state.json", "plan.md", "audit/artifact_manifest.json"],
    )


def _preview(value: str, limit: int = 500) -> str:
    return value.replace("\n", "\\n")[:limit]


def _experiment_matrix_decision_prompt(
    snapshot: dict,
    registry: SkillRegistry | None = None,
    contract: dict | None = None,
) -> str:
    expected = {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_create_experiment_matrix",
            "skill_request": {
                "skill_name": "create_experiment_matrix",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "experiment_matrix_scope": "explicit_screening_grounded_experiment_matrix",
                    "require_screening_basis": True,
                    "require_gap_and_evidence_basis": True,
                    "forbid_protocol_generation": True,
                    "forbid_stepwise_instructions": True,
                    "forbid_final_claims": True,
                },
                "reason": (
                    "The explicit experiment matrix plan has the required screening results, candidate ideas, "
                    "gap map, landscape, enriched evidence, ranked evidence, and diagnostics artifacts, so the "
                    "next bounded action is to create an experiment matrix."
                ),
            },
            "artifact_refs": [
                "screening/idea_screening_results.json",
                "ideas/candidate_ideas.json",
                "gaps/gap_map.json",
                "landscape/literature_landscape.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The explicit experiment matrix step should run after validated screening artifacts exist.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }
    return (
        "You are inside a bounded controller contract smoke test.\n"
        "You must output exactly one bare JSON object.\n"
        "Your entire stdout must start with { and end with }.\n"
        "Do not use Markdown. Do not use code fences. Do not include explanations.\n"
        "The workspace already has:\n"
        "- screening/idea_screening_results.json\n"
        "- screening/screening_diagnostics.json\n"
        "- screening/idea_screening_results.md\n"
        "- ideas/candidate_ideas.json\n"
        "- ideas/idea_generation_diagnostics.json\n"
        "- ideas/candidate_ideas.md\n"
        "- gaps/gap_map.json\n"
        "- gaps/gap_coverage_diagnostics.json\n"
        "- gaps/gap_map.md\n"
        "- landscape/literature_landscape.json\n"
        "- landscape/landscape_coverage_diagnostics.json\n"
        "- landscape/literature_landscape.md\n"
        "- evidence/evidence_cards.enriched.json\n"
        "- ranked_evidence/evidence_selection.json\n"
        "- ranked_evidence/coverage_diagnostics.json\n"
        "- reports/minimal_topic_to_evidence_report.json\n"
        "The explicit experiment matrix plan requires the next skill: create_experiment_matrix.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = create_experiment_matrix.\n"
        "Do not execute the skill.\n"
        "Do not generate experiment matrix content.\n"
        "Do not generate wet-lab protocol.\n"
        "Do not generate step-by-step procedure.\n"
        "Do not generate synthesis recipe.\n"
        "Do not generate safety protocol.\n"
        "Do not generate claim ledger.\n"
        "Do not generate manuscript content.\n"
        "Do not generate final claims.\n"
        "Do not claim feasibility is proven.\n"
        "Do not claim performance will improve.\n"
        "Do not modify files. Do not run shell commands. Do not access or mutate database.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not request build_claim_ledger, draft_manuscript_section, or any P2-M13+ skill.\n"
        "Return only a cli_controller_contract_v1 envelope matching this exact intended shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI experiment matrix decision smoke test is opt-in only",
)
def test_real_claude_cli_experiment_matrix_decision_contract_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")
    registry = _experiment_matrix_registry()
    contract = registry.get_skill("create_experiment_matrix")
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _experiment_matrix_decision_prompt,
    )
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(
            enabled=True,
            allow_real_invocation=True,
            working_directory=str(Path.cwd()),
            timeout_seconds=int(os.getenv("REAL_CLAUDE_CLI_TIMEOUT_SECONDS", "60")),
            max_output_chars=20000,
        ),
        registry=registry,
    )

    response = backend.invoke(_snapshot(workspace_root))
    parse_result = parse_cli_output(response.raw_output, registry=registry, policy=_policy(workspace_root))

    decision_type = None
    skill_name = None
    input_artifacts = []
    output_artifacts = []
    parameters = {}
    if parse_result.decision is not None:
        decision_type = parse_result.decision.decision_type.value
        if parse_result.decision.skill_request is not None:
            request = parse_result.decision.skill_request
            skill_name = request.skill_name
            input_artifacts = request.input_artifacts
            output_artifacts = request.output_artifacts
            parameters = request.parameters

    format_issue = detect_cli_output_format_issue(response.raw_output or "")
    retrieval_input_present = any(path.startswith("retrieval/") for path in input_artifacts)
    screening_results_json_present = "screening/idea_screening_results.json" in input_artifacts
    experiment_matrix_input_errors = validate_experiment_matrix_input_artifacts(input_artifacts)
    p2_m13_plus_requested = skill_name in P2_M13_PLUS_SKILLS
    skill_registered_available = contract.status == SkillStatus.AVAILABLE
    result = (
        "passed"
        if (
            format_issue == "none"
            and parse_result.accepted
            and decision_type == "CALL_TOOL"
            and skill_name == "create_experiment_matrix"
            and input_artifacts == INPUT_ARTIFACTS
            and output_artifacts == OUTPUT_ARTIFACTS
            and not retrieval_input_present
            and screening_results_json_present
            and not experiment_matrix_input_errors
            and not p2_m13_plus_requested
            and skill_registered_available
        )
        else "failed_expectation"
    )
    summary = {
        "real_cli_invoked": response.metadata.get("backend_error") != "real_invocation_disabled",
        "exit_code": response.exit_code,
        "timed_out": response.timed_out,
        "stdout_chars": len(response.stdout or ""),
        "stderr_chars": len(response.stderr or ""),
        "format_issue": format_issue,
        "parse_success": parse_result.decision is not None,
        "validation_success": parse_result.accepted,
        "decision_type": decision_type,
        "expected_decision_type": "CALL_TOOL",
        "skill_name": skill_name,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "parameters": parameters,
        "retrieval_input_present": retrieval_input_present,
        "screening_results_json_present": screening_results_json_present,
        "experiment_matrix_input_errors": experiment_matrix_input_errors,
        "p2_m13_plus_requested": p2_m13_plus_requested,
        "skill_registered_available": skill_registered_available,
        "violations": [violation.violation_type.value for violation in parse_result.violations],
        "result": result,
        "raw_output_preview": _preview(response.raw_output or ""),
    }
    print("REAL_CLAUDE_CLI_EXPERIMENT_MATRIX_DECISION_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert response.raw_output
    assert format_issue == "none"
    assert parse_result.accepted is True
    assert decision_type == "CALL_TOOL"
    assert skill_name == "create_experiment_matrix"
    assert input_artifacts == INPUT_ARTIFACTS
    assert output_artifacts == OUTPUT_ARTIFACTS
    assert retrieval_input_present is False
    assert screening_results_json_present is True
    assert experiment_matrix_input_errors == []
    assert p2_m13_plus_requested is False
    assert skill_registered_available is True
    assert (workspace_root / "state.json").read_text(encoding="utf-8") == before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") == before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()
    assert not (workspace_root / "experiments/experiment_matrix.md").exists()
    assert not (workspace_root / "experiments/experiment_matrix_diagnostics.json").exists()
