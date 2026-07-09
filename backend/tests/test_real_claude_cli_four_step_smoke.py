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
    build_default_skill_registry,
    detect_cli_output_format_issue,
    read_jsonl_events,
)
from modules.research_workspace import ResearchWorkspaceStore


TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"
TASK_ID = "smoke_real_cli_four_step_task"


def _workspace(tmp_path: Path) -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(
        TASK_ID,
        task_markdown=(
            "# Task\n\n"
            f"Topic: {TOPIC}\n"
            "Task profile: topic-to-report\n"
            "Retrieval budget: 5\n\n"
            "This is a four-step real Claude CLI smoke test. The only permitted platform actions are:\n"
            "1. retrieve_sources\n"
            "2. create_evidence_seeds\n"
            "3. extract_evidence_cards\n"
            "4. enrich_evidence_cards\n\n"
            "Do not request ranking, reports, landscape, gaps, ideas, experiments, claim ledger, or manuscript skills.\n"
        ),
        plan_markdown=(
            "# Plan\n\n"
            "- step_retrieve_sources: pending\n"
            "- step_create_evidence_seeds: pending\n"
            "- step_extract_evidence_cards: pending\n"
            "- step_enrich_evidence_cards: pending\n\n"
            "The smoke test will call run_once exactly four times. It must not call run_until_stop.\n"
        ),
    )
    return tmp_path / "research_agent/research_tasks" / TASK_ID


def _registry_for(*names: str) -> SkillRegistry:
    default = build_default_skill_registry()
    registry = SkillRegistry()
    for name in names:
        registry.register_skill(default.get_skill(name))
    return registry


def _four_step_prompt(snapshot: dict, registry: SkillRegistry | None = None, contract: dict | None = None) -> str:
    artifact_paths = {
        artifact.get("path")
        for artifact in snapshot.get("artifact_manifest", {}).get("artifacts", [])
        if isinstance(artifact, dict)
    }
    allowed_skills = [skill.name for skill in registry.list_available_skills()] if registry else []
    if "evidence/evidence_cards.initial.json" in artifact_paths:
        expected = _enrich_cards_envelope()
        instruction = (
            "Initial Evidence Cards already exist. The only valid next action in this four-step smoke test is "
            "CALL_TOOL enrich_evidence_cards. The input_artifacts array must include "
            "evidence/evidence_cards.initial.json. The output_artifacts array must include "
            "evidence/evidence_cards.enriched.json."
        )
    elif "evidence/evidence_card_seeds.json" in artifact_paths:
        expected = _extract_cards_envelope()
        instruction = (
            "EvidenceCardSeed artifacts already exist. The only valid next action in this four-step smoke test is "
            "CALL_TOOL extract_evidence_cards."
        )
    elif "retrieval/source_candidate_packet.json" in artifact_paths:
        expected = _create_seeds_envelope()
        instruction = (
            "Retrieval artifacts already exist. The only valid next action in this four-step smoke test is "
            "CALL_TOOL create_evidence_seeds."
        )
    else:
        expected = _retrieve_sources_envelope()
        instruction = (
            "No retrieval artifacts exist yet. The only valid next action in this four-step smoke test is "
            "CALL_TOOL retrieve_sources."
        )

    return (
        "You are inside a four-step research controller run_once smoke test.\n"
        "You must output exactly one bare JSON object. Your stdout must start with { and end with }.\n"
        "Do not use Markdown, code fences, explanations, comments, or natural language outside JSON.\n"
        "Do not execute skills yourself. Do not run shell commands. Do not modify files. Do not access databases.\n"
        "Do not modify state.json, plan.md, or audit/artifact_manifest.json.\n"
        "Do not request rank_evidence, reports, landscape, gaps, ideas, experiments, claim ledger, manuscript, "
        "validation-only, or any future skill.\n"
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
            "reason": "The first step in the four-step smoke test is retrieving source candidates.",
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
            "reason": "The second step in the four-step smoke test is creating EvidenceCardSeed artifacts.",
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
            "reason": "The third step in the four-step smoke test is creating initial Evidence Cards.",
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
            "reason": "The fourth step in the four-step smoke test is enriching initial Evidence Cards.",
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


@pytest.mark.skipif(
    os.getenv("RUN_REAL_CLAUDE_CLI_TEST") != "1",
    reason="Real Claude Code CLI four-step smoke test is opt-in only",
)
def test_real_claude_cli_four_step_retrieve_seed_extract_enrich_smoke(monkeypatch, tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    _fake_acquire_evidence.calls = []
    monkeypatch.setattr(
        "modules.research_agent_controller.claude_cli_invocation.build_claude_cli_controller_prompt",
        _four_step_prompt,
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
        max_steps=4,
        acquire_evidence_fn=_fake_acquire_evidence,
    )

    first = controller.run_once()
    first_response = backend.last_response
    assert first.status == ControllerStepStatus.SUCCESS
    assert _parse_success(first) is True
    assert _validation_success(first) is True
    assert _decision_type(first) == "CALL_TOOL"
    assert _skill_name(first) == "retrieve_sources"
    assert first.skill_result is not None
    assert first.skill_result.output_artifacts == [
        "retrieval/source_candidate_packet.json",
        "retrieval/retrieval_warnings.json",
    ]
    assert bool(_fake_acquire_evidence.calls) is True

    second_registry = _registry_for("create_evidence_seeds")
    controller.registry = second_registry
    backend.registry = second_registry
    second = controller.run_once()
    second_response = backend.last_response
    assert second.status == ControllerStepStatus.SUCCESS
    assert _parse_success(second) is True
    assert _validation_success(second) is True
    assert _decision_type(second) == "CALL_TOOL"
    assert _skill_name(second) == "create_evidence_seeds"
    assert second.skill_result is not None
    assert second.skill_result.input_artifacts == ["retrieval/source_candidate_packet.json"]
    assert second.skill_result.output_artifacts == ["evidence/evidence_card_seeds.json"]

    third_registry = _registry_for("extract_evidence_cards")
    controller.registry = third_registry
    backend.registry = third_registry
    third = controller.run_once()
    third_response = backend.last_response
    assert third.status == ControllerStepStatus.SUCCESS
    assert _parse_success(third) is True
    assert _validation_success(third) is True
    assert _decision_type(third) == "CALL_TOOL"
    assert _skill_name(third) == "extract_evidence_cards"
    assert third.skill_result is not None
    assert third.skill_result.status == SkillExecutionStatus.SUCCESS
    assert third.skill_result.input_artifacts == ["evidence/evidence_card_seeds.json"]
    assert third.skill_result.output_artifacts == ["evidence/evidence_cards.initial.json"]

    fourth_registry = _registry_for("enrich_evidence_cards")
    controller.registry = fourth_registry
    backend.registry = fourth_registry
    fourth = controller.run_once()
    fourth_response = backend.last_response

    executed_skills = [event.get("skill_name") for event in _events(workspace_root, "logs/tool_calls.jsonl")]
    manifest_artifacts = [
        item["path"]
        for item in _read_json(workspace_root / "audit/artifact_manifest.json")["artifacts"]
    ]
    output_artifacts = []
    for result in (first, second, third, fourth):
        if result.skill_result:
            output_artifacts.extend(result.skill_result.output_artifacts)
    state = _read_json(workspace_root / "state.json")
    plan_md = (workspace_root / "plan.md").read_text(encoding="utf-8")
    controller_events = _events(workspace_root, "logs/controller_events.jsonl")
    tool_calls = _events(workspace_root, "logs/tool_calls.jsonl")
    validation_results = _events(workspace_root, "logs/validation_results.jsonl")
    warnings = list(first.warnings) + list(second.warnings) + list(third.warnings) + list(fourth.warnings)
    for result in (first, second, third, fourth):
        if result.skill_result:
            warnings.extend(result.skill_result.warnings)
    summary = {
        "real_cli_invoked": (
            first_response.metadata.get("backend_error") != "real_invocation_disabled"
            and second_response.metadata.get("backend_error") != "real_invocation_disabled"
            and third_response.metadata.get("backend_error") != "real_invocation_disabled"
            and fourth_response.metadata.get("backend_error") != "real_invocation_disabled"
        ),
        "first_exit_code": first_response.exit_code,
        "second_exit_code": second_response.exit_code,
        "third_exit_code": third_response.exit_code,
        "fourth_exit_code": fourth_response.exit_code,
        "first_timed_out": first_response.timed_out,
        "second_timed_out": second_response.timed_out,
        "third_timed_out": third_response.timed_out,
        "fourth_timed_out": fourth_response.timed_out,
        "first_format_issue": detect_cli_output_format_issue(first_response.raw_output or ""),
        "second_format_issue": detect_cli_output_format_issue(second_response.raw_output or ""),
        "third_format_issue": detect_cli_output_format_issue(third_response.raw_output or ""),
        "fourth_format_issue": detect_cli_output_format_issue(fourth_response.raw_output or ""),
        "first_decision_type": _decision_type(first),
        "first_skill_name": _skill_name(first),
        "second_decision_type": _decision_type(second),
        "second_skill_name": _skill_name(second),
        "third_decision_type": _decision_type(third),
        "third_skill_name": _skill_name(third),
        "fourth_decision_type": _decision_type(fourth),
        "fourth_skill_name": _skill_name(fourth),
        "first_parse_success": _parse_success(first),
        "first_validation_success": _validation_success(first),
        "second_parse_success": _parse_success(second),
        "second_validation_success": _validation_success(second),
        "third_parse_success": _parse_success(third),
        "third_validation_success": _validation_success(third),
        "fourth_parse_success": _parse_success(fourth),
        "fourth_validation_success": _validation_success(fourth),
        "run_once_count": 4,
        "executed_skills": executed_skills,
        "fake_acquire_evidence_called": bool(_fake_acquire_evidence.calls),
        "output_artifacts": output_artifacts,
        "manifest_artifacts": manifest_artifacts,
        "controller_events_count": len(controller_events),
        "tool_calls_count": len(tool_calls),
        "validation_results_count": len(validation_results),
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
        },
        "extract_result_status": third.skill_result.status.value if third.skill_result else None,
        "enrich_result_status": fourth.skill_result.status.value if fourth.skill_result else None,
        "violations": _violations(first, second, third, fourth),
        "warnings": list(dict.fromkeys(warnings)),
    }
    print("REAL_CLAUDE_CLI_FOUR_STEP_SMOKE " + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    assert fourth.status == ControllerStepStatus.SUCCESS
    assert _parse_success(fourth) is True
    assert _validation_success(fourth) is True
    assert _decision_type(fourth) == "CALL_TOOL"
    assert _skill_name(fourth) == "enrich_evidence_cards"
    assert fourth.skill_result is not None
    assert fourth.skill_result.status == SkillExecutionStatus.SUCCESS
    assert fourth.skill_result.input_artifacts == ["evidence/evidence_cards.initial.json"]
    assert fourth.skill_result.output_artifacts == ["evidence/evidence_cards.enriched.json"]
    assert executed_skills == [
        "retrieve_sources",
        "create_evidence_seeds",
        "extract_evidence_cards",
        "enrich_evidence_cards",
    ]
    assert (workspace_root / "retrieval/source_candidate_packet.json").exists()
    assert (workspace_root / "retrieval/retrieval_warnings.json").exists()
    assert (workspace_root / "evidence/evidence_card_seeds.json").exists()
    assert (workspace_root / "evidence/evidence_cards.initial.json").exists()
    assert (workspace_root / "evidence/evidence_cards.enriched.json").exists()
    assert "retrieval/source_candidate_packet.json" in manifest_artifacts
    assert "retrieval/retrieval_warnings.json" in manifest_artifacts
    assert "evidence/evidence_card_seeds.json" in manifest_artifacts
    assert "evidence/evidence_cards.initial.json" in manifest_artifacts
    assert "evidence/evidence_cards.enriched.json" in manifest_artifacts
    assert len(controller_events) >= 4
    assert len(tool_calls) >= 4
    assert len(validation_results) >= 4
    assert state["status"] == "running"
    assert "retrieve_sources" in state["completed_steps"]
    assert "create_evidence_seeds" in state["completed_steps"]
    assert "extract_evidence_cards" in state["completed_steps"]
    assert "enrich_evidence_cards" in state["completed_steps"]
    assert "retrieve_sources" in plan_md
    assert "create_evidence_seeds" in plan_md
    assert "extract_evidence_cards" in plan_md
    assert "enrich_evidence_cards" in plan_md
    assert not (workspace_root / "ranked_evidence/evidence_selection.json").exists()
    assert not (workspace_root / "reports/minimal_topic_to_evidence_report.md").exists()
