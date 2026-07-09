import json
from pathlib import Path

import pytest

from modules.research_agent_controller import SkillExecutionResult, SkillExecutionStatus, ValidationStatus
from modules.research_agent_controller.audit import (
    ArtifactManifest,
    ArtifactRecord,
    AuditEventType,
    ControllerAuditEvent,
    ToolCallAuditEvent,
    append_controller_event,
    append_tool_call_event,
    append_validation_result,
    find_artifact,
    list_artifacts_by_type,
    load_artifact_manifest,
    read_jsonl_events,
    record_skill_execution_result,
    register_artifact,
    save_artifact_manifest,
    update_artifact_validation_status,
)
from modules.research_agent_controller.validators import (
    ArtifactValidationResult,
    validate_artifact_manifest,
    validate_evidence_card_artifact,
    validate_ranking_selection_artifact,
    validate_report_inputs,
)
from modules.research_workspace import ResearchWorkspaceStore


def _workspace(tmp_path: Path, task_id: str = "task_123") -> Path:
    store = ResearchWorkspaceStore(tmp_path)
    store.create_workspace(task_id)
    return tmp_path / "research_agent/research_tasks" / task_id


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _valid_card(evidence_id: str = "ecard_1") -> dict:
    return {
        "evidence_id": evidence_id,
        "seed_id": "seed_1",
        "source_evidence_id": "ev_1",
        "paper_id": "paper_1",
        "source": {
            "source_path": "literature-data/paper_1/full_text.json",
            "asset_type": "text",
            "locator": {"section": "Results"},
        },
        "primary_role": "background",
        "secondary_roles": [],
        "verbatim_snippet": "LLMs can extract materials synthesis facts from papers.",
        "normalized_statement": "LLMs can support extraction from materials papers.",
        "entities": {},
        "relations": [],
        "relevance": {"topic": "LLMs in materials discovery"},
        "support": {"support_strength": "weak", "unsupported_parts": []},
    }


def test_artifact_manifest_create_save_load_and_lookup(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    manifest = ArtifactManifest(task_id="task_123")
    record = ArtifactRecord(
        artifact_id="cards_enriched",
        artifact_type="evidence_cards",
        path="evidence/evidence_cards.enriched.json",
        created_by="enrich_evidence_cards",
        tool_version="a4",
        input_artifacts=["evidence/evidence_cards.initial.json"],
    )
    manifest.artifacts.append(record)

    saved = save_artifact_manifest(workspace_root, manifest)
    loaded = load_artifact_manifest(workspace_root, "task_123")

    assert saved.task_id == "task_123"
    assert loaded.task_id == "task_123"
    assert loaded.cli_controller_ready is False
    assert loaded.artifacts[0].artifact_id == "cards_enriched"
    assert find_artifact(loaded, "cards_enriched").path == "evidence/evidence_cards.enriched.json"
    assert list_artifacts_by_type(loaded, "evidence_cards")[0].artifact_id == "cards_enriched"
    assert isinstance(loaded.updated_at, float)


def test_register_artifact_rejects_duplicates_and_path_escape(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    record = ArtifactRecord(
        artifact_id="selection",
        artifact_type="evidence_selection",
        path="ranked_evidence/evidence_selection.json",
        created_by="rank_evidence",
    )

    manifest = register_artifact(workspace_root, "task_123", record)
    assert find_artifact(manifest, "selection").path == "ranked_evidence/evidence_selection.json"

    with pytest.raises(ValueError):
        register_artifact(workspace_root, "task_123", record)

    with pytest.raises(ValueError):
        register_artifact(
            workspace_root,
            "task_123",
            ArtifactRecord(
                artifact_id="escape",
                artifact_type="bad",
                path="../outside.json",
                created_by="test",
            ),
        )


def test_update_artifact_validation_status_requires_existing_artifact(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    register_artifact(
        workspace_root,
        "task_123",
        ArtifactRecord(
            artifact_id="cards",
            artifact_type="evidence_cards",
            path="evidence/evidence_cards.enriched.json",
            created_by="enrich_evidence_cards",
        ),
    )

    manifest = update_artifact_validation_status(
        workspace_root,
        "task_123",
        "cards",
        ValidationStatus.PASSED,
        warnings=["coverage warning"],
        metadata={"validator": "evidence_card_gate"},
    )

    record = find_artifact(manifest, "cards")
    assert record.validation_status == ValidationStatus.PASSED
    assert record.warnings == ["coverage warning"]
    assert record.metadata["validator"] == "evidence_card_gate"

    with pytest.raises(KeyError):
        update_artifact_validation_status(workspace_root, "task_123", "missing", ValidationStatus.FAILED)


def test_audit_jsonl_append_and_read_order(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    tool_event = ToolCallAuditEvent(
        event_id="tool_1",
        task_id="task_123",
        skill_name="rank_evidence",
        input_artifacts=["evidence/evidence_cards.enriched.json"],
        output_artifacts=["ranked_evidence/evidence_selection.json"],
        status="success",
    )
    controller_event = ControllerAuditEvent(
        event_id="controller_1",
        task_id="task_123",
        event_type=AuditEventType.CONTROLLER_EVENT,
        message="Controller observed validation result.",
        artifacts=["ranked_evidence/evidence_selection.json"],
    )
    validation_result = ArtifactValidationResult(
        artifact_id="selection",
        artifact_type="evidence_selection",
        path="ranked_evidence/evidence_selection.json",
        validation_status=ValidationStatus.PASSED,
        validator_name="ranking_selection_gate",
    )

    append_tool_call_event(workspace_root, tool_event)
    append_tool_call_event(workspace_root, tool_event)
    append_controller_event(workspace_root, controller_event)
    append_validation_result(workspace_root, validation_result)

    tool_events = read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")
    controller_events = read_jsonl_events(workspace_root, "logs/controller_events.jsonl")
    validation_events = read_jsonl_events(workspace_root, "logs/validation_results.jsonl")

    assert len(tool_events) == 2
    assert tool_events[0]["event_id"] == "tool_1"
    assert controller_events[0]["event_type"] == "controller_event"
    assert validation_events[0]["validation_status"] == "passed"


def test_validate_artifact_manifest_passes_and_rejects_illegal_paths(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    register_artifact(
        workspace_root,
        "task_123",
        ArtifactRecord(
            artifact_id="cards",
            artifact_type="evidence_cards",
            path="evidence/evidence_cards.enriched.json",
            created_by="enrich_evidence_cards",
        ),
    )

    passed = validate_artifact_manifest(workspace_root, "task_123")
    assert passed.validation_status == ValidationStatus.PASSED
    assert (workspace_root / "audit/artifact_manifest_validation.json").exists()

    bad_manifest = load_artifact_manifest(workspace_root, "task_123")
    bad_manifest.artifacts.append(
        ArtifactRecord(
            artifact_id="bad",
            artifact_type="bad",
            path="../escape.json",
            created_by="test",
        )
    )
    save_artifact_manifest(workspace_root, bad_manifest, validate_paths=False)

    failed = validate_artifact_manifest(workspace_root, "task_123")
    assert failed.validation_status == ValidationStatus.FAILED
    assert any("artifact_path_escapes_workspace" in error for error in failed.errors)


def test_validate_evidence_card_artifact_passes_valid_cards_and_fails_invalid_cards(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    valid_path = workspace_root / "evidence/evidence_cards.enriched.json"
    invalid_path = workspace_root / "evidence/evidence_cards.invalid.json"
    _write_json(valid_path, {"cards": [_valid_card()], "card_count": 1})
    invalid_card = _valid_card()
    invalid_card.pop("evidence_id")
    invalid_card.pop("normalized_statement")
    invalid_card.pop("verbatim_snippet")
    _write_json(invalid_path, {"cards": [invalid_card], "card_count": 1})

    before = valid_path.read_text(encoding="utf-8")
    passed = validate_evidence_card_artifact(
        workspace_root,
        "task_123",
        "evidence/evidence_cards.enriched.json",
        enriched=True,
    )
    after = valid_path.read_text(encoding="utf-8")
    failed = validate_evidence_card_artifact(
        workspace_root,
        "task_123",
        "evidence/evidence_cards.invalid.json",
        enriched=True,
    )

    assert passed.validation_status == ValidationStatus.PASSED
    assert before == after
    assert failed.validation_status == ValidationStatus.FAILED
    assert "missing_evidence_id:0" in failed.errors
    assert "missing_statement:0" in failed.errors


def test_validate_report_inputs_rejects_raw_retrieval_and_allows_evidence_cards(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)

    rejected = validate_report_inputs(
        workspace_root,
        "task_123",
        ["retrieval/source_candidate_packet.json"],
    )
    allowed = validate_report_inputs(
        workspace_root,
        "task_123",
        ["evidence/evidence_cards.enriched.json"],
    )

    assert rejected.validation_status == ValidationStatus.FAILED
    assert "raw_retrieval_candidates_not_allowed_for_report" in rejected.errors
    assert allowed.validation_status == ValidationStatus.PASSED


def test_validate_ranking_selection_artifact_accepts_current_selection_shape(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    selection_path = workspace_root / "ranked_evidence/evidence_selection.json"
    _write_json(
        selection_path,
        {
            "artifact_type": "evidence_selection",
            "selected_cards": [_valid_card("ecard_selected")],
            "ranked_cards": [
                {
                    "rank": 1,
                    "evidence_id": "ecard_selected",
                    "score": 0.83,
                    "score_components": {"relevance": 0.9},
                }
            ],
            "coverage": {"warnings": ["single_source_type_warning"]},
            "warnings": ["single_source_type_warning"],
        },
    )

    result = validate_ranking_selection_artifact(
        workspace_root,
        "task_123",
        "ranked_evidence/evidence_selection.json",
    )

    assert result.validation_status == ValidationStatus.DEGRADED_WITH_WARNING
    assert "single_source_type_warning" in result.warnings


def test_record_skill_execution_result_records_manifest_and_tool_log_only(tmp_path: Path) -> None:
    workspace_root = _workspace(tmp_path)
    result = SkillExecutionResult(
        task_id="task_123",
        skill_name="rank_evidence",
        status=SkillExecutionStatus.SUCCESS,
        input_artifacts=["evidence/evidence_cards.enriched.json"],
        output_artifacts=["ranked_evidence/evidence_selection.json"],
        warnings=["single_source_type_warning"],
        metadata={"selected_count": 1},
    )

    manifest = record_skill_execution_result(result, workspace_root)
    tool_events = read_jsonl_events(workspace_root, "logs/tool_calls.jsonl")

    assert find_artifact(manifest, "rank_evidence:ranked_evidence/evidence_selection.json")
    assert tool_events[0]["skill_name"] == "rank_evidence"
    assert not (workspace_root / "logs/controller_events.jsonl").exists()


def test_audit_and_validators_have_no_cli_database_frontend_or_workflow_dependencies() -> None:
    sources = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "backend/modules/research_agent_controller/audit.py",
            "backend/modules/research_agent_controller/validators.py",
        ]
    )

    forbidden = [
        "cli_backed_controller",
        "native_fallback_controller",
        "Claude Code CLI",
        "sqlite",
        "core.memory_db",
        "frontend",
        "modules.workflow",
        "LiteratureResearchService",
    ]
    for token in forbidden:
        assert token not in sources
