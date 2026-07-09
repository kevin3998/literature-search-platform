import json
import os
from pathlib import Path

import pytest

from modules.research_agent_controller import (
    ClaudeCodeBackedMinimalController,
    ClaudeCodeCliBackendConfig,
    ControllerStepStatus,
    RealClaudeCodeCliBackend,
    SkillExecutionStatus,
    SkillRegistry,
    ValidationStatus,
    build_default_skill_registry,
    detect_cli_output_format_issue,
    read_jsonl_events,
    validate_report_inputs,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_minimal_report_task"


def _workspace(tmp_path: Path, task_id: str = TASK_ID) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        task_id,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: topic-to-report\n"
            "Retrieval budget: 5\n"
            "Selection budget: 5\n\n"
            "This is a minimal report real Claude CLI smoke test. The only permitted platform actions are:\n"
            "1. retrieve_sources\n"
            "2. create_evidence_seeds\n"
            "3. extract_evidence_cards\n"
            "4. enrich_evidence_cards\n"
            "5. rank_evidence\n"
            "6. build_minimal_topic_to_evidence_report\n\n"
            "Do not request landscape, gaps, ideas, novelty screening, experiments, full reports, claim ledger, "
            "or manuscript skills.\n"
        ),
        plan_markdown=(
            "# Plan\n\n"
            "- step_retrieve_sources: pending\n"
            "- step_create_evidence_seeds: pending\n"
            "- step_extract_evidence_cards: pending\n"
            "- step_enrich_evidence_cards: pending\n"
            "- step_rank_evidence: pending\n"
            "- step_build_minimal_report: pending\n\n"
            "The smoke test will call run_once exactly six times. It must not call run_until_stop.\n"
        ),
    )
    return tmp_path / "research_agent/research_tasks" / task_id


def _registry_for(*names: str) -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    for name in names:
        registry.register_skill(default.get_skill(name))
    return registry


def _minimal_report_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
    artifact_paths = {
        artifact.get("path")
        for artifact in snapshot.get("artifact_manifest", {}).get("artifacts", [])
        if isinstance(artifact, dict)
    }
    allowed_skills = [skill.name for skill in registry.list_available_skills()] if registry else []
    if "ranked_evidence/evidence_selection.json" in artifact_paths:
        expected = _minimal_report_envelope()
        instruction = (
            "Enriched Evidence Cards and ranked evidence already exist. The only valid next action in this "
            "minimal report smoke test is CALL_TOOL build_minimal_topic_to_evidence_report. The input_artifacts "
            "array must include evidence/evidence_cards.enriched.json, ranked_evidence/evidence_selection.json, "
            "and ranked_evidence/coverage_diagnostics.json. The input_artifacts array must not include any "
            "retrieval/... path."
        )
    elif "evidence/evidence_cards.enriched.json" in artifact_paths:
        expected = _rank_evidence_envelope()
        instruction = (
            "Enriched Evidence Cards already exist. The only valid next action in this minimal report smoke test "
            "is CALL_TOOL rank_evidence."
        )
    elif "evidence/evidence_cards.initial.json" in artifact_paths:
        expected = _enrich_cards_envelope()
        instruction = (
            "Initial Evidence Cards already exist. The only valid next action in this minimal report smoke test "
            "is CALL_TOOL enrich_evidence_cards."
        )
    elif "evidence/evidence_card_seeds.json" in artifact_paths:
        expected = _extract_cards_envelope()
        instruction = (
            "EvidenceCardSeed artifacts already exist. The only valid next action in this minimal report smoke "
            "test is CALL_TOOL extract_evidence_cards."
        )
    elif "retrieval/source_candidate_packet.json" in artifact_paths:
        expected = _create_seeds_envelope()
        instruction = (
            "Retrieval artifacts already exist. The only valid next action in this minimal report smoke test is "
            "CALL_TOOL create_evidence_seeds."
        )
    else:
        expected = _retrieve_sources_envelope()
        instruction = (
            "No retrieval artifacts exist yet. The only valid next action in this minimal report smoke test is "
            "CALL_TOOL retrieve_sources."
        )

    return (
        "You are inside a minimal report research controller run_once smoke test.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "Do not execute skills yourself. Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Do not request landscape, gaps, ideas, novelty screening, experiments, full reports, claim ledger, "
        "manuscript, validation-only, or any future skill.\n"
        "For the minimal report step, never use retrieval/source_candidate_packet.json or any retrieval/... path "
        "as report input.\n"
        f"Allowed skill_name values for this invocation: {', '.join(allowed_skills)}.\n"
        f"{instruction}\n"
        "Return only a cli_controller_contract_v1 envelope matching this exact intended shape:\n"
        f"{json.dumps(expected, ensure_ascii=False, sort_keys=True)}\n"
        "Workspace snapshot JSON:\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


def _retrieve_sources_envelope() -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_retrieve_sources",
            "skill_request": {
                "skill_name": "retrieve_sources",
                "input_artifacts": [],
                "output_artifacts": [
                    "retrieval/source_candidate_packet.json",
                    "retrieval/retrieval_warnings.json",
                ],
                "parameters": {
                    "topic": TOPIC,
                    "task_profile_id": "topic-to-report",
                    "retrieval_budget": 5,
                },
                "reason": "The workspace has no retrieval artifacts, so request topic-scoped source retrieval.",
            },
            "artifact_refs": [],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The first step in the minimal report smoke test is retrieving source candidates.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }


def _create_seeds_envelope() -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_create_evidence_seeds",
            "skill_request": {
                "skill_name": "create_evidence_seeds",
                "input_artifacts": [
                    "retrieval/source_candidate_packet.json",
                ],
                "output_artifacts": [
                    "evidence/evidence_card_seeds.json",
                ],
                "parameters": {},
                "reason": (
                    "Retrieval artifacts already exist, so the next bounded action is to normalize source "
                    "candidates into EvidenceCardSeed artifacts."
                ),
            },
            "artifact_refs": [
                "retrieval/source_candidate_packet.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The second step in the minimal report smoke test is creating EvidenceCardSeed artifacts.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }


def _extract_cards_envelope() -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_extract_evidence_cards",
            "skill_request": {
                "skill_name": "extract_evidence_cards",
                "input_artifacts": [
                    "evidence/evidence_card_seeds.json",
                ],
                "output_artifacts": [
                    "evidence/evidence_cards.initial.json",
                ],
                "parameters": {
                    "topic": TOPIC,
                    "task_profile_id": "topic-to-report",
                },
                "reason": (
                    "EvidenceCardSeed artifacts already exist, so the next bounded action is to extract "
                    "initial Evidence Cards."
                ),
            },
            "artifact_refs": [
                "evidence/evidence_card_seeds.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The third step in the minimal report smoke test is creating initial Evidence Cards.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }


def _enrich_cards_envelope() -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_enrich_evidence_cards",
            "skill_request": {
                "skill_name": "enrich_evidence_cards",
                "input_artifacts": [
                    "evidence/evidence_cards.initial.json",
                ],
                "output_artifacts": [
                    "evidence/evidence_cards.enriched.json",
                ],
                "parameters": {
                    "topic": TOPIC,
                    "task_profile_id": "topic-to-report",
                },
                "reason": (
                    "Initial Evidence Cards already exist, so the next bounded action is to enrich Evidence "
                    "Cards with normalized roles and structured metadata."
                ),
            },
            "artifact_refs": [
                "evidence/evidence_cards.initial.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The fourth step in the minimal report smoke test is enriching initial Evidence Cards.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }


def _rank_evidence_envelope() -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_rank_evidence",
            "skill_request": {
                "skill_name": "rank_evidence",
                "input_artifacts": [
                    "evidence/evidence_cards.enriched.json",
                ],
                "output_artifacts": [
                    "ranked_evidence/evidence_selection.json",
                    "ranked_evidence/coverage_diagnostics.json",
                ],
                "parameters": {
                    "selection_budget": 5,
                    "task_profile_id": "topic-to-report",
                },
                "reason": (
                    "Enriched Evidence Cards already exist, so the next bounded action is to select "
                    "representative evidence and produce coverage diagnostics."
                ),
            },
            "artifact_refs": [
                "evidence/evidence_cards.enriched.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The fifth step in the minimal report smoke test is ranking and selecting representative evidence.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }


def _minimal_report_envelope() -> dict:
    return {
        "schema_version": "cli_controller_contract_v1",
        "task_id": TASK_ID,
        "decision": {
            "decision_type": "CALL_TOOL",
            "task_id": TASK_ID,
            "target_step_id": "step_build_minimal_report",
            "skill_request": {
                "skill_name": "build_minimal_topic_to_evidence_report",
                "input_artifacts": [
                    "evidence/evidence_cards.enriched.json",
                    "ranked_evidence/evidence_selection.json",
                    "ranked_evidence/coverage_diagnostics.json",
                ],
                "output_artifacts": [
                    "reports/minimal_topic_to_evidence_report.md",
                    "reports/minimal_topic_to_evidence_report.json",
                ],
                "parameters": {
                    "topic": TOPIC,
                    "task_profile_id": "topic-to-report",
                    "report_scope": "minimal_topic_to_evidence",
                    "require_evidence_ids": True,
                },
                "reason": (
                    "Enriched Evidence Cards and selected evidence already exist, so the next bounded action "
                    "is to build a minimal evidence-grounded report."
                ),
            },
            "artifact_refs": [
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            "state_update_intent": {},
            "plan_update_intent": {},
            "reason": "The final step in the minimal report smoke test is producing a minimal report grounded in selected Evidence Cards.",
            "warnings": [],
        },
        "notes": [],
        "warnings": [],
    }


def _fake_acquire_evidence(query: str, has_history: bool = False, **options: object) -> dict:
    _fake_acquire_evidence.calls.append(
        {
            "query": query,
            "has_history": has_history,
            "options": dict(options),
        }
    )
    return {
        "evidence_candidates": [
            {
                "evidence_id": "src_001",
                "source_evidence_id": "src_001",
                "paper_id": "paper_001",
                "title": "Oxygen vacancy engineering for alkaline HER catalysts",
                "doi": "10.0000/example",
                "year": 2024,
                "journal": "Example Journal",
                "kind": "text",
                "snippet": (
                    "Oxygen vacancies can modulate water dissociation and hydrogen adsorption in alkaline HER catalysts."
                ),
                "source_path": "paper_001/sections/results.md",
                "source_locator": {"section": "Results"},
                "section_id": "results",
                "chunk_index": 0,
                "asset_type": "text",
                "relevance_score": 0.91,
            }
        ],
        "expanded_assets": [],
        "query_plan": {"query": query},
        "coverage": {"limit": options.get("limit")},
        "breadth": {"has_history": has_history},
        "warnings": ["fake_acquire_evidence_used"],
    }


_fake_acquire_evidence.calls = []


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _decision_type(result) -> str | None:
    decision = result.parse_result.decision if result.parse_result else None
    return decision.decision_type.value if decision else None


def _skill_name(result) -> str | None:
    decision = result.parse_result.decision if result.parse_result else None
    if not decision or not decision.skill_request:
        return None
    return decision.skill_request.skill_name


def _skill_inputs(result) -> list[str]:
    decision = result.parse_result.decision if result.parse_result else None
    if not decision or not decision.skill_request:
        return []
    return list(decision.skill_request.input_artifacts)


def _parse_success(result) -> bool:
    return bool(result.parse_result and result.parse_result.decision is not None)


def _validation_success(result) -> bool:
    return bool(result.parse_result and result.parse_result.accepted)


def _violations(*results) -> list[str]:
    values: list[str] = []
    for result in results:
        if result and result.parse_result:
            values.extend(violation.violation_type.value for violation in result.parse_result.violations)
    return values


def _events(workspace_root: Path, relative_path: str) -> list[dict]:
    path = workspace_root / relative_path
    if not path.exists():
        return []
    return read_jsonl_events(workspace_root, relative_path)


def _latest_validation_status(events: list[dict], validator_name: str) -> str | None:
    for event in reversed(events):
        if event.get("validator_name") == validator_name:
            return event.get("validation_status")
    return None


def _report_scope_valid(markdown: str, report_data: dict) -> bool:
    forbidden = (
        "## Landscape",
        "## Gap",
        "## Candidate Ideas",
        "## Novelty",
        "## Experiment Plan",
        "## Manuscript",
    )
    combined = markdown + "\n" + json.dumps(report_data, ensure_ascii=False, sort_keys=True)
    return not any(marker in combined for marker in forbidden)


def _report_contains_evidence_references(markdown: str, report_data: dict) -> bool:
    combined = markdown + "\n" + json.dumps(report_data, ensure_ascii=False, sort_keys=True)
    return "evidence_id" in combined or "ecard_" in combined


def test_validate_report_inputs_rejects_raw_retrieval_artifacts(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path, task_id="smoke_report_gate_negative_task")

    result = validate_report_inputs(
        workspace_root,
        "smoke_report_gate_negative_task",
        ["retrieval/source_candidate_packet.json"],
    )
    nested_result = validate_report_inputs(
        workspace_root,
        "smoke_report_gate_negative_task",
        ["retrieval/other_raw_packet.json"],
    )

    assert result.validation_status == ValidationStatus.FAILED
    assert "raw_retrieval_candidates_not_allowed_for_report" in result.errors
    assert nested_result.validation_status == ValidationStatus.FAILED
    assert "raw_retrieval_candidates_not_allowed_for_report" in nested_result.errors


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI minimal report smoke test is opt-in only",
)
def test_real_claude_cli_minimal_report_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _fake_acquire_evidence.calls = []
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _minimal_report_prompt,
    )

    first_registry = _registry_for("retrieve_sources")
    backend = RealClaudeCodeCliBackend(
        ClaudeCodeCliBackendConfig(
            enabled=True,
            allow_real_invocation=True,
            working_directory=str(Path.cwd()),
            timeout_seconds=int(os.getenv("REAL_CLAUDE_CLI_TIMEOUT_SECONDS", "60")),
            max_output_chars=20000,
        ),
        registry=first_registry,
    )
    controller = ClaudeCodeBackedMinimalController(
        workspace_root=workspace_root,
        task_id=TASK_ID,
        cli_backend=backend,
        registry=first_registry,
        max_steps=6,
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    first = controller.run_once()
    first_response = backend.last_response
    assert first.status == ControllerStepStatus.SUCCESS
    assert _decision_type(first) == "CALL_TOOL"
    assert _skill_name(first) == "retrieve_sources"

    second_registry = _registry_for("create_evidence_seeds")
    controller.registry = second_registry
    backend.registry = second_registry
    second = controller.run_once()
    second_response = backend.last_response
    assert second.status == ControllerStepStatus.SUCCESS
    assert _decision_type(second) == "CALL_TOOL"
    assert _skill_name(second) == "create_evidence_seeds"

    third_registry = _registry_for("extract_evidence_cards")
    controller.registry = third_registry
    backend.registry = third_registry
    third = controller.run_once()
    third_response = backend.last_response
    assert third.status == ControllerStepStatus.SUCCESS
    assert _decision_type(third) == "CALL_TOOL"
    assert _skill_name(third) == "extract_evidence_cards"

    fourth_registry = _registry_for("enrich_evidence_cards")
    controller.registry = fourth_registry
    backend.registry = fourth_registry
    fourth = controller.run_once()
    fourth_response = backend.last_response
    assert fourth.status == ControllerStepStatus.SUCCESS
    assert _decision_type(fourth) == "CALL_TOOL"
    assert _skill_name(fourth) == "enrich_evidence_cards"

    fifth_registry = _registry_for("rank_evidence")
    controller.registry = fifth_registry
    backend.registry = fifth_registry
    fifth = controller.run_once()
    fifth_response = backend.last_response
    assert fifth.status == ControllerStepStatus.SUCCESS
    assert _decision_type(fifth) == "CALL_TOOL"
    assert _skill_name(fifth) == "rank_evidence"

    sixth_registry = _registry_for("build_minimal_topic_to_evidence_report")
    controller.registry = sixth_registry
    backend.registry = sixth_registry
    sixth = controller.run_once()
    sixth_response = backend.last_response

    assert sixth.status == ControllerStepStatus.SUCCESS
    assert _parse_success(sixth) is True
    assert _validation_success(sixth) is True
    assert _decision_type(sixth) == "CALL_TOOL"
    assert _skill_name(sixth) == "build_minimal_topic_to_evidence_report"
    assert not any(path.startswith("retrieval/") for path in _skill_inputs(sixth))
    assert sixth.skill_result is not None
    assert sixth.skill_result.status == SkillExecutionStatus.SUCCESS
    assert sixth.skill_result.output_artifacts == [
        "reports/minimal_topic_to_evidence_report.md",
        "reports/minimal_topic_to_evidence_report.json",
    ]

    executed_skills = [event.get("skill_name") for event in _events(workspace_root, "logs/tool_calls.jsonl")]
    validation_events = _events(workspace_root, "logs/validation_results.jsonl")
    ranking_validation_status = _latest_validation_status(validation_events, "ranking_selection_gate")
    report_input_gate_status = _latest_validation_status(validation_events, "report_input_gate")
    manifest_artifacts = [
        item["path"]
        for item in _read_json(workspace_root / "audit/artifact_manifest.json")["artifacts"]
    ]
    output_artifacts = []
    for result in (first, second, third, fourth, fifth, sixth):
        if result.skill_result:
            output_artifacts.extend(result.skill_result.output_artifacts)
    report_md = (workspace_root / "reports/minimal_topic_to_evidence_report.md").read_text(encoding="utf-8")
    report_json = _read_json(workspace_root / "reports/minimal_topic_to_evidence_report.json")
    report_contains_evidence_references = _report_contains_evidence_references(report_md, report_json)
    report_scope_valid = _report_scope_valid(report_md, report_json)
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    controller_events = _events(workspace_root, "logs/controller_events.jsonl")
    tool_calls = _events(workspace_root, "logs/tool_calls.jsonl")
    warnings = []
    for result in (first, second, third, fourth, fifth, sixth):
        warnings.extend(result.warnings)
        if result.skill_result:
            warnings.extend(result.skill_result.warnings)
    summary = {
        "real_cli_invoked": all(
            response.metadata.get("backend_error") != "real_invocation_disabled"
            for response in (first_response, second_response, third_response, fourth_response, fifth_response, sixth_response)
        ),
        "first_decision_type": _decision_type(first),
        "first_skill_name": _skill_name(first),
        "second_decision_type": _decision_type(second),
        "second_skill_name": _skill_name(second),
        "third_decision_type": _decision_type(third),
        "third_skill_name": _skill_name(third),
        "fourth_decision_type": _decision_type(fourth),
        "fourth_skill_name": _skill_name(fourth),
        "fifth_decision_type": _decision_type(fifth),
        "fifth_skill_name": _skill_name(fifth),
        "sixth_decision_type": _decision_type(sixth),
        "sixth_skill_name": _skill_name(sixth),
        "first_format_issue": detect_cli_output_format_issue(first_response.raw_output or ""),
        "second_format_issue": detect_cli_output_format_issue(second_response.raw_output or ""),
        "third_format_issue": detect_cli_output_format_issue(third_response.raw_output or ""),
        "fourth_format_issue": detect_cli_output_format_issue(fourth_response.raw_output or ""),
        "fifth_format_issue": detect_cli_output_format_issue(fifth_response.raw_output or ""),
        "sixth_format_issue": detect_cli_output_format_issue(sixth_response.raw_output or ""),
        "first_parse_success": _parse_success(first),
        "first_validation_success": _validation_success(first),
        "second_parse_success": _parse_success(second),
        "second_validation_success": _validation_success(second),
        "third_parse_success": _parse_success(third),
        "third_validation_success": _validation_success(third),
        "fourth_parse_success": _parse_success(fourth),
        "fourth_validation_success": _validation_success(fourth),
        "fifth_parse_success": _parse_success(fifth),
        "fifth_validation_success": _validation_success(fifth),
        "sixth_parse_success": _parse_success(sixth),
        "sixth_validation_success": _validation_success(sixth),
        "run_once_count": 6,
        "executed_skills": executed_skills,
        "fake_acquire_evidence_called": bool(_fake_acquire_evidence.calls),
        "report_input_gate_status": report_input_gate_status,
        "ranking_validation_status": ranking_validation_status,
        "report_result_status": sixth.skill_result.status.value if sixth.skill_result else None,
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(controller_events),
        "tool_calls_count": len(tool_calls),
        "validation_results_count": len(validation_events),
        "state_status": state.get("status"),
        "plan_step_statuses": {
            "retrieve_sources": "completed" if "retrieve_sources" in state.get("completed_steps", []) else "pending",
            "create_evidence_seeds": (
                "completed" if "create_evidence_seeds" in state.get("completed_steps", []) else "pending"
            ),
            "extract_evidence_cards": (
                "completed" if "extract_evidence_cards" in state.get("completed_steps", []) else "pending"
            ),
            "enrich_evidence_cards": (
                "completed" if "enrich_evidence_cards" in state.get("completed_steps", []) else "pending"
            ),
            "rank_evidence": "completed" if "rank_evidence" in state.get("completed_steps", []) else "pending",
            "build_minimal_topic_to_evidence_report": (
                "completed"
                if "build_minimal_topic_to_evidence_report" in state.get("completed_steps", [])
                else "pending"
            ),
        },
        "report_contains_evidence_references": report_contains_evidence_references,
        "report_scope_valid": report_scope_valid,
        "violations": _violations(first, second, third, fourth, fifth, sixth),
        "warnings": list(dict.fromkeys(warnings)),
    }
    print("REAL_CLAUDE_CLI_MINIMAL_REPORT_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert _skill_inputs(sixth) == [
        "evidence/evidence_cards.enriched.json",
        "ranked_evidence/evidence_selection.json",
        "ranked_evidence/coverage_diagnostics.json",
    ]
    assert executed_skills == [
        "retrieve_sources",
        "create_evidence_seeds",
        "extract_evidence_cards",
        "enrich_evidence_cards",
        "rank_evidence",
        "build_minimal_topic_to_evidence_report",
    ]
    assert ranking_validation_status in {ValidationStatus.PASSED.value, ValidationStatus.DEGRADED_WITH_WARNING.value}
    assert report_input_gate_status == ValidationStatus.PASSED.value
    assert (workspace_root / "reports/minimal_topic_to_evidence_report.md").exists()
    assert (workspace_root / "reports/minimal_topic_to_evidence_report.json").exists()
    assert report_contains_evidence_references is True
    assert report_scope_valid is True
    assert "reports/minimal_topic_to_evidence_report.md" in manifest_artifacts
    assert "reports/minimal_topic_to_evidence_report.json" in manifest_artifacts
    assert len(controller_events) >= 6
    assert len(tool_calls) >= 6
    assert len(validation_events) >= 6
    assert state["status"] == "running"
    assert "build_minimal_topic_to_evidence_report" in state["completed_steps"]
    assert "build_minimal_topic_to_evidence_report" in plan_md
    assert not (workspace_root / "landscape/landscape.json").exists()
    assert not (workspace_root / "gaps/gaps.json").exists()
    assert not (workspace_root / "ideas/candidate_ideas.json").exists()
    assert not (workspace_root / "screening/idea_screening.json").exists()
    assert not (workspace_root / "experiments/experiment_matrix.json").exists()
    assert not (workspace_root / "manuscript/section.md").exists()
