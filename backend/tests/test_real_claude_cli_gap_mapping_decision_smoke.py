import json
import os
from pathlib import Path

import pytest

from modules.research_agent_controller import (
    ClaudeCodeCliBackendConfig,
    CliWorkspaceAccessPolicy,
    RealClaudeCodeCliBackend,
    SkillRegistry,
    build_default_skill_registry,
    detect_cli_output_format_issue,
    parse_cli_output,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_gap_mapping_decision_task"
INPUT_ARTIFACTS = [
    "landscape/literature_landscape.json",
    "landscape/landscape_coverage_diagnostics.json",
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]
REQUIRED_INPUT_ARTIFACTS = [
    "landscape/literature_landscape.json",
    "landscape/landscape_coverage_diagnostics.json",
    "evidence/evidence_cards.enriched.json",
    "ranked_evidence/evidence_selection.json",
    "ranked_evidence/coverage_diagnostics.json",
]
OUTPUT_ARTIFACTS = [
    "gaps/gap_map.json",
    "gaps/gap_map.md",
    "gaps/gap_coverage_diagnostics.json",
]
P2_M10_PLUS_SKILLS = {
    "generate_candidate_ideas",
    "screen_novelty_feasibility_risk",
    "draft_evidence_grounded_report",
    "create_experiment_matrix",
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
            "This is a bounded gap mapping decision smoke test. The workspace already has landscape, "
            "enriched Evidence Cards, ranked evidence, coverage diagnostics, and a minimal report. "
            "Do not execute tools or modify workspace files.\n"
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
            "- map_gaps: pending\n\n"
            "The next valid explicit step is map_gaps.\n"
        ),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    _write_json(
        workspace_root,
        "landscape/literature_landscape.json",
        {
            "task_id": TASK_ID,
            "topic": TOPIC,
            "landscape_id": "landscape_smoke_gap",
            "evidence_ids": ["ecard_001"],
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
            "coverage": {"missing_roles": ["figure_evidence"], "coverage_warnings": ["landscape_sparse_cluster"]},
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_json(
        workspace_root,
        "landscape/landscape_coverage_diagnostics.json",
        {
            "artifact_type": "landscape_coverage_diagnostics",
            "task_id": TASK_ID,
            "landscape_id": "landscape_smoke_gap",
            "coverage": {"missing_roles": ["figure_evidence"]},
            "warnings": ["landscape_sparse_cluster"],
            "schema_version": "landscape_v1",
        },
    )
    _write_text(
        workspace_root,
        "landscape/literature_landscape.md",
        "# Literature Landscape\n\n## Evidence References\n\n- evidence_id=ecard_001; paper_id=paper_001\n",
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
            "artifacts": [
                {"artifact_id": path, "artifact_type": "input", "path": path}
                for path in INPUT_ARTIFACTS
            ],
            "cli_controller_ready": False,
        },
        "recent_events": [],
        "step_index": 0,
    }


def _gap_mapping_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("map_gaps"))
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
            "landscape/",
            "evidence/",
            "ranked_evidence/",
            "reports/",
        ],
        allowed_write_paths=["gaps/"],
        forbidden_paths=["state.json", "plan.md", "audit/artifact_manifest.json"],
    )


def _preview(value: str, limit: int = 500) -> str:
    return value.replace("\n", "\\n")[:limit]


def _gap_mapping_decision_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
    expected = {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_map_gaps",
            "skill_request": {
                "skill_name": "map_gaps",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "gap_mapping_scope": "explicit_topic_gap_map",
                    "require_evidence_basis": True,
                    "forbid_candidate_ideas": True,
                },
                "reason": (
                    "The explicit gap mapping plan has the required landscape, enriched evidence, "
                    "ranked evidence, and diagnostics artifacts, so the next bounded action is to map evidence gaps."
                ),
            },
            "artifact_refs": REQUIRED_INPUT_ARTIFACTS,
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The explicit gap mapping step should run after landscape and evidence diagnostics artifacts exist.",
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
        "- landscape/literature_landscape.json\n"
        "- landscape/landscape_coverage_diagnostics.json\n"
        "- landscape/literature_landscape.md\n"
        "- evidence/evidence_cards.enriched.json\n"
        "- ranked_evidence/evidence_selection.json\n"
        "- ranked_evidence/coverage_diagnostics.json\n"
        "- reports/minimal_topic_to_evidence_report.json\n"
        "The explicit gap mapping plan requires the next skill: map_gaps.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = map_gaps.\n"
        "Do not execute the skill.\n"
        "Do not generate gap content.\n"
        "Do not generate candidate ideas.\n"
        "Do not generate novelty screening.\n"
        "Do not generate feasibility screening.\n"
        "Do not generate experiment plan.\n"
        "Do not generate manuscript content.\n"
        "Do not modify files. Do not run shell commands. Do not access or mutate database.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Return only a cli_controller_contract_v1 envelope matching this exact intended shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI gap mapping decision smoke test is opt-in only",
)
def test_real_claude_cli_gap_mapping_decision_contract_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")
    registry = _gap_mapping_registry()
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _gap_mapping_decision_prompt,
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

    retrieval_input_present = any(path.startswith("retrieval/") for path in input_artifacts)
    landscape_json_present = "landscape/literature_landscape.json" in input_artifacts
    p2_m10_requested = skill_name in P2_M10_PLUS_SKILLS
    result = (
        "passed"
        if (
            parse_result.accepted
            and decision_type == "CALL_TOOL"
            and skill_name == "map_gaps"
            and input_artifacts == INPUT_ARTIFACTS
            and output_artifacts == OUTPUT_ARTIFACTS
            and not retrieval_input_present
            and landscape_json_present
            and not p2_m10_requested
        )
        else "failed_expectation"
    )
    summary = {
        "real_cli_invoked": response.metadata.get("backend_error") != "real_invocation_disabled",
        "exit_code": response.exit_code,
        "timed_out": response.timed_out,
        "stdout_chars": len(response.stdout or ""),
        "stderr_chars": len(response.stderr or ""),
        "format_issue": detect_cli_output_format_issue(response.raw_output or ""),
        "parse_success": parse_result.decision is not None,
        "validation_success": parse_result.accepted,
        "decision_type": decision_type,
        "expected_decision_type": "CALL_TOOL",
        "skill_name": skill_name,
        "input_artifacts": input_artifacts,
        "output_artifacts": output_artifacts,
        "parameters": parameters,
        "retrieval_input_present": retrieval_input_present,
        "landscape_json_present": landscape_json_present,
        "p2_m10_requested": p2_m10_requested,
        "violations": [violation.violation_type.value for violation in parse_result.violations],
        "result": result,
        "raw_output_preview": _preview(response.raw_output or ""),
    }
    print("REAL_CLAUDE_CLI_GAP_MAPPING_DECISION_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert response.raw_output
    assert parse_result.accepted is True
    assert decision_type == "CALL_TOOL"
    assert skill_name == "map_gaps"
    assert input_artifacts == INPUT_ARTIFACTS
    assert output_artifacts == OUTPUT_ARTIFACTS
    assert retrieval_input_present is False
    assert landscape_json_present is True
    assert p2_m10_requested is False
    assert (workspace_root / "state.json").read_text(encoding="utf-8") == before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") == before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
    assert not (workspace_root / "gaps/gap_map.json").exists()
    assert not (workspace_root / "gaps/gap_map.md").exists()
    assert not (workspace_root / "gaps/gap_coverage_diagnostics.json").exists()
