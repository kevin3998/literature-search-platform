from __future__ import annotations

import json

from test_structured_extraction_preparation import _client_with_schema
from test_structured_extraction_runs import FakeLLM, _prepare_inputs, _wait_for_terminal


def _review_record_json(paper_id: str, membrane_name: str, fields: dict) -> str:
    return json.dumps(
        {
            "records": [
                {
                    "paper_id": paper_id,
                    "record_identity": {"paper_id": paper_id, "membrane_name": membrane_name},
                    "fields": fields,
                }
            ]
        }
    )


def _client_with_completed_run(monkeypatch, tmp_path):
    client, task_id, root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)

    fake = FakeLLM(
        [
            _review_record_json("p_prep_1", "PES-ZW", {}),
            _review_record_json(
                "p_prep_1",
                "PES-ZW",
                {
                    "water_flux": {
                        "raw_value": "120 LMH",
                        "normalized_value": 120,
                        "unit": "LMH",
                        "condition_context": None,
                        "extraction_note": "",
                    }
                },
            ),
            '{"records":[]}',
            '{"records":[]}',
        ]
    )

    import modules.structured_extraction.llm_extraction as llm_extraction

    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False: fake)
    monkeypatch.setattr(llm_extraction.settings_store, "model_config", lambda: {"provider": "fake", "chat_model": "weak", "strong_model": "strong"})
    started = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()
    final = _wait_for_terminal(client, task_id, started["run_id"])
    assert final["status"] == "completed"
    return client, task_id, final["run_id"], root


def test_review_table_initializes_quality_flags_and_manual_overlay(monkeypatch, tmp_path):
    client, task_id, run_id, root = _client_with_completed_run(monkeypatch, tmp_path)

    runs = client.get(f"/api/structured-extraction/tasks/{task_id}/review/runs", headers={"X-User-Id": "alice"})
    assert runs.status_code == 200
    assert runs.json()["runs"][0]["run_id"] == run_id

    table = client.get(f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={run_id}", headers={"X-User-Id": "alice"})
    assert table.status_code == 200
    body = table.json()
    assert body["total"] == 1
    row = body["rows"][0]
    assert row["paper"]["title"] == "Antifouling membrane performance"
    assert row["review_priority"] == "high"
    assert row["review_status"] == "unreviewed"
    assert row["fields"]["membrane_name"]["status"] == "unreviewed"
    assert row["fields"]["membrane_name"]["review_priority"] == "high"
    assert "missing_required_field" in row["fields"]["membrane_name"]["quality_flags"]
    assert row["fields"]["water_flux"]["review_priority"] == "medium"
    assert "no_evidence" in row["fields"]["water_flux"]["quality_flags"]

    record_id = row["record_id"]
    accepted = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/membrane_name/accept",
        json={"reason": "identity checked"},
        headers={"X-User-Id": "alice"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["fields"]["membrane_name"]["status"] == "accepted"
    assert accepted.json()["fields"]["membrane_name"]["locked"] is True

    edited_value = {
        "raw_value": "121 LMH",
        "normalized_value": 121,
        "unit": "LMH",
        "condition_context": "25 C",
        "evidence_text": "manual correction from table",
        "evidence_location": "Table 1",
        "extraction_note": "Corrected after review",
    }
    edited = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/water_flux/edit",
        json={"value": edited_value, "reason": "manual correction"},
        headers={"X-User-Id": "alice"},
    )
    assert edited.status_code == 200
    assert edited.json()["fields"]["water_flux"]["status"] == "edited"
    assert edited.json()["fields"]["water_flux"]["effective_value"]["normalized_value"] == 121

    detail = client.get(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}?run_id={run_id}",
        headers={"X-User-Id": "alice"},
    )
    assert detail.status_code == 200
    assert detail.json()["fields"]["water_flux"]["effective_value"]["raw_value"] == "121 LMH"
    events = client.get(f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/events", headers={"X-User-Id": "alice"}).json()["events"]
    assert [event["event_type"] for event in events] == ["accept_field", "edit_field"]

    base_records = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}/records", headers={"X-User-Id": "alice"}).json()["records"]
    assert base_records[0]["fields"]["water_flux"]["normalized_value"] == 120

    reverted = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/events/{events[-1]['event_id']}/revert",
        headers={"X-User-Id": "alice"},
    )
    assert reverted.status_code == 200
    assert reverted.json()["fields"]["water_flux"]["effective_value"]["normalized_value"] == 120
    events_after_revert = client.get(f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/events", headers={"X-User-Id": "alice"}).json()["events"]
    assert events_after_revert[-1]["event_type"] == "revert_event"

    rejected = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/water_flux/reject",
        json={"reason": "not supported"},
        headers={"X-User-Id": "alice"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["fields"]["water_flux"]["status"] == "rejected"
    assert rejected.json()["fields"]["water_flux"]["effective_value"] is None
    assert rejected.json()["fields"]["water_flux"]["locked"] is True

    unlocked = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/water_flux/unlock",
        headers={"X-User-Id": "alice"},
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["fields"]["water_flux"]["locked"] is False

    bulk = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/bulk",
        json={"items": [{"record_id": record_id, "field_key": "water_flux"}], "action": "accept_field", "reason": "batch pass"},
        headers={"X-User-Id": "alice"},
    )
    assert bulk.status_code == 200
    assert bulk.json()["updated"] == 1
    assert bulk.json()["rows"][0]["fields"]["water_flux"]["status"] == "accepted"

    filtered = client.get(
        f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={run_id}&status=accepted&field_key=water_flux",
        headers={"X-User-Id": "alice"},
    )
    assert filtered.json()["total"] == 1
    missing = client.get(
        f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={run_id}&missing=true&field_key=membrane_name",
        headers={"X-User-Id": "alice"},
    )
    assert missing.json()["total"] == 1

    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    audit = root / "users" / "alice" / task["workspace_rel_path"] / "audit"
    assert (audit / "review_events.jsonl").exists()
    assert (audit / f"review_field_states_{run_id}.jsonl").exists()
    assert (audit / f"effective_records_{run_id}.jsonl").exists()

    bob = client.get(f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={run_id}", headers={"X-User-Id": "bob"})
    assert bob.status_code == 404


def test_review_table_requires_completed_run_with_records(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)

    response = client.get(f"/api/structured-extraction/tasks/{task_id}/review/table", headers={"X-User-Id": "alice"})

    assert response.status_code == 400
    assert "review_run_required" in response.json()["detail"]
