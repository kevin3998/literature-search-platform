import json
import os
from pathlib import Path

import pytest

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
from modules.research_agent_controller.skills.claim_ledger_contract import (
    CLAIM_LEDGER_OUTPUT_ARTIFACTS,
    CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
    validate_claim_ledger_input_artifacts,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_claim_ledger_decision_task"
OPTIONAL_INPUT_ARTIFACTS = [
    "experiments/experiment_matrix.md",
    "screening/idea_screening_results.md",
    "ideas/candidate_ideas.md",
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.json",
]
INPUT_ARTIFACTS = CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS + OPTIONAL_INPUT_ARTIFACTS
OUTPUT_ARTIFACTS = CLAIM_LEDGER_OUTPUT_ARTIFACTS
P2_M14_PLUS_SKILLS = {"draft_manuscript_section"}


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n\n"
            "This is a bounded claim ledger decision smoke test. The workspace already has "
            "experiment matrix artifacts, screening results, candidate ideas, gap map, landscape, "
            "enriched Evidence Cards, ranked evidence, diagnostics, and a minimal report. "
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
            "- map_gaps: completed\n"
            "- generate_candidate_ideas: completed\n"
            "- screen_novelty_feasibility_risk: completed\n"
            "- create_experiment_matrix: completed\n"
            "- build_claim_ledger: pending\n\n"
            "The next valid explicit step is build_claim_ledger.\n"
        ),
    )
    workspace_root = tmp_path / "research_agent/research_tasks" / TASK_ID
    for relative_path in INPUT_ARTIFACTS:
        if relative_path.endswith(".md"):
            _write_text(workspace_root, relative_path, f"# Smoke Artifact\n\n{relative_path}\n")
        else:
            _write_json(
                workspace_root,
                relative_path,
                {
                    "artifact_type": "smoke_input",
                    "path": relative_path,
                    "task_id": TASK_ID,
                    "topic": TOPIC,
                    "evidence_ids": ["ecard_001"],
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


def _claim_ledger_registry() -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    registry.register_skill(default.get_skill("build_claim_ledger"))
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
            "experiments/",
            "screening/",
            "ideas/",
            "gaps/",
            "landscape/",
            "evidence/",
            "ranked_evidence/",
            "reports/",
        ],
        allowed_write_paths=["claims/"],
        forbidden_paths=["state.json", "plan.md", "audit/artifact_manifest.json"],
    )


def _preview(value: str, limit: int = 500) -> str:
    return value.replace("\n", "\\n")[:limit]


def _claim_ledger_decision_prompt(
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
            "target_step_id": "step_build_claim_ledger",
            "skill_request": {
                "skill_name": "build_claim_ledger",
                "input_artifacts": INPUT_ARTIFACTS,
                "output_artifacts": OUTPUT_ARTIFACTS,
                "parameters": {
                    "claim_ledger_scope": "explicit_experiment_matrix_grounded_claim_ledger",
                    "require_traceable_evidence_basis": True,
                    "require_non_final_claim_status": True,
                    "forbid_manuscript_drafting": True,
                    "forbid_final_claims": True,
                    "forbid_validated_result_claims": True,
                },
                "reason": (
                    "The explicit claim ledger plan has the required experiment matrix, screening results, "
                    "candidate ideas, gap map, landscape, enriched evidence, ranked evidence, and diagnostics "
                    "artifacts, so the next bounded action is to build a claim ledger."
                ),
            },
            "artifact_refs": [
                "experiments/experiment_matrix.json",
                "screening/idea_screening_results.json",
                "ideas/candidate_ideas.json",
                "gaps/gap_map.json",
                "landscape/literature_landscape.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The explicit claim ledger step should run after validated experiment matrix artifacts exist.",
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
        "- experiments/experiment_matrix.json\n"
        "- experiments/experiment_matrix_diagnostics.json\n"
        "- experiments/experiment_matrix.md\n"
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
        "The explicit claim ledger plan requires the next skill: build_claim_ledger.\n"
        "You must output decision_type = CALL_TOOL.\n"
        "You must output skill_name = build_claim_ledger.\n"
        "Do not execute the skill.\n"
        "Do not generate claim ledger content.\n"
        "Do not generate manuscript content.\n"
        "Do not generate abstract.\n"
        "Do not generate results or discussion.\n"
        "Do not generate conclusion.\n"
        "Do not generate final claims.\n"
        "Do not claim experimental validation.\n"
        "Do not claim candidate hypotheses are proven.\n"
        "Do not claim performance will improve.\n"
        "Do not modify files. Do not run shell commands. Do not access or mutate database.\n"
        "Do not use retrieval/... as an input artifact.\n"
        "Do not request draft_manuscript_section or any P2-M14+ skill.\n"
        "Return only a cli_controller_contract_v1 envelope matching this exact intended shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI claim ledger decision smoke test is opt-in only",
)
def test_real_claude_cli_claim_ledger_decision_contract_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    before_state = (workspace_root / "state.json").read_text(encoding="utf-8")
    before_plan = (workspace_root / "plan.md").read_text(encoding="utf-8")
    before_manifest = (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8")
    registry = _claim_ledger_registry()
    contract = registry.get_skill("build_claim_ledger")
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _claim_ledger_decision_prompt,
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
    experiment_matrix_json_present = "experiments/experiment_matrix.json" in input_artifacts
    claim_ledger_input_errors = validate_claim_ledger_input_artifacts(input_artifacts)
    p2_m14_plus_requested = skill_name in P2_M14_PLUS_SKILLS
    skill_registered_available = contract.status == SkillStatus.AVAILABLE
    result = (
        "passed"
        if (
            format_issue == "none"
            and parse_result.accepted
            and decision_type == "CALL_TOOL"
            and skill_name == "build_claim_ledger"
            and input_artifacts == INPUT_ARTIFACTS
            and output_artifacts == OUTPUT_ARTIFACTS
            and not retrieval_input_present
            and experiment_matrix_json_present
            and not claim_ledger_input_errors
            and not p2_m14_plus_requested
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
        "experiment_matrix_json_present": experiment_matrix_json_present,
        "claim_ledger_input_errors": claim_ledger_input_errors,
        "p2_m14_plus_requested": p2_m14_plus_requested,
        "skill_registered_available": skill_registered_available,
        "violations": [violation.violation_type.value for violation in parse_result.violations],
        "result": result,
        "raw_output_preview": _preview(response.raw_output or ""),
    }
    print("REAL_CLAUDE_CLI_CLAIM_LEDGER_DECISION_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert response.raw_output
    assert format_issue == "none"
    assert parse_result.accepted is True
    assert decision_type == "CALL_TOOL"
    assert skill_name == "build_claim_ledger"
    assert input_artifacts == INPUT_ARTIFACTS
    assert output_artifacts == OUTPUT_ARTIFACTS
    assert retrieval_input_present is False
    assert experiment_matrix_json_present is True
    assert claim_ledger_input_errors == []
    assert p2_m14_plus_requested is False
    assert skill_registered_available is True
    assert (workspace_root / "state.json").read_text(encoding="utf-8") == before_state
    assert (workspace_root / "plan.md").read_text(encoding="utf-8") == before_plan
    assert (workspace_root / "audit/artifact_manifest.json").read_text(encoding="utf-8") == before_manifest
    assert not (workspace_root / "logs/tool_calls.jsonl").exists()
    assert not (workspace_root / "claims/claim_ledger.json").exists()
    assert not (workspace_root / "claims/claim_ledger.md").exists()
    assert not (workspace_root / "claims/claim_ledger_diagnostics.json").exists()
