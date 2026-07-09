from __future__ import annotations

import json
import time

from test_structured_extraction_runs import FakeLLM, _prepare_inputs, _record_json, _wait_for_terminal
from test_structured_extraction_preparation import _client_with_schema


def _start_completed_with_errors(client, task_id: str, monkeypatch) -> dict:
    import modules.structured_extraction.llm_extraction as llm_extraction

    fake = FakeLLM(
        [
            _record_json("p_prep_1", "PES-ZW", {"membrane_name": {"raw_value": "PES-ZW", "evidence_text": "PES-ZW"}}),
            "not json",
            '{"records":[]}',
            '{"records":[]}',
        ]
    )
    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False: fake)
    monkeypatch.setattr(llm_extraction.settings_store, "model_config", lambda: {"provider": "fake", "chat_model": "weak", "strong_model": "strong"})
    run = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()
    final = _wait_for_terminal(client, task_id, run["run_id"])
    assert final["status"] == "completed_with_errors"
    return final


def test_reaper_marks_active_run_interrupted_and_recovery_status_is_resumable(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)
    run = _start_completed_with_errors(client, task_id, monkeypatch)

    from modules.structured_extraction.shared import structured_extraction_run_service

    structured_extraction_run_service.store.conn.execute(
        "update structured_extraction_runs set status = 'running', error_json = null where run_id = ?",
        (run["run_id"],),
    )
    structured_extraction_run_service.store.conn.execute(
        "update structured_extraction_run_items set status = 'running', error_json = null where run_id = ? and status = 'failed'",
        (run["run_id"],),
    )
    structured_extraction_run_service.store.conn.commit()

    reaped = structured_extraction_run_service.reap_orphaned_runs()

    assert run["run_id"] in reaped
    interrupted = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}", headers={"X-User-Id": "alice"}).json()
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"]["reason"] == "process_restarted"
    recovery = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/recovery", headers={"X-User-Id": "alice"})
    assert recovery.status_code == 200
    body = recovery.json()
    assert body["resumable"] is True
    assert body["interrupted_item_count"] == 1
    assert body["remaining_item_count"] == 1
    assert body["last_error"]["reason"] == "process_restarted"
    items = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/items", headers={"X-User-Id": "alice"}).json()["items"]
    assert any(item["status"] == "interrupted" and item["error"]["reason"] == "process_restarted" for item in items)


def test_resume_reuses_run_id_skips_completed_items_and_does_not_double_count(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)
    run = _start_completed_with_errors(client, task_id, monkeypatch)
    task_after_first = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    assert task_after_first["stats"]["run_count"] == 1

    before_items = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/items", headers={"X-User-Id": "alice"}).json()["items"]
    completed_before = [item for item in before_items if item["status"] == "completed"]
    failed_before = [item for item in before_items if item["status"] == "failed"]
    assert len(completed_before) == 3
    assert len(failed_before) == 1

    import modules.structured_extraction.llm_extraction as llm_extraction

    fake = FakeLLM(
        [
            _record_json(
                "p_prep_1",
                "PES-ZW",
                {"water_flux": {"raw_value": "120 LMH", "normalized_value": 120, "unit": "LMH", "evidence_text": "water flux of 120 LMH"}},
            )
        ]
    )
    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False: fake)

    resumed = client.post(
        f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/resume",
        json={"retry_failed_items": True, "reason": "test_resume"},
        headers={"X-User-Id": "alice"},
    )

    assert resumed.status_code == 200
    assert resumed.json()["run_id"] == run["run_id"]
    final = _wait_for_terminal(client, task_id, run["run_id"])
    assert final["status"] == "completed"
    assert final["stats"]["completed_item_count"] == 4
    assert final["stats"]["failed_item_count"] == 0
    assert final["resume_count"] == 1
    assert len(fake.calls) == 1

    records = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/records", headers={"X-User-Id": "alice"}).json()["records"]
    assert records[0]["fields"]["water_flux"]["normalized_value"] == 120
    assert len(records[0]["source_packet_item_ids"]) == len(set(records[0]["source_packet_item_ids"]))
    task_after_resume = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    assert task_after_resume["stats"]["run_count"] == 1


def test_resume_blocked_after_review_or_export(monkeypatch, tmp_path):
    from test_structured_extraction_review import _client_with_completed_run

    client, task_id, run_id, _root = _client_with_completed_run(monkeypatch, tmp_path)
    table = client.get(f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={run_id}", headers={"X-User-Id": "alice"}).json()
    record_id = table["rows"][0]["record_id"]
    accepted = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/membrane_name/accept",
        headers={"X-User-Id": "alice"},
    )
    assert accepted.status_code == 200

    response = client.post(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}/resume", headers={"X-User-Id": "alice"})

    assert response.status_code == 409
    assert "run_locked_by_review_or_export" in response.json()["detail"]


def test_resume_blocked_after_export_even_without_review_event(monkeypatch, tmp_path):
    from test_structured_extraction_review import _client_with_completed_run

    client, task_id, run_id, _root = _client_with_completed_run(monkeypatch, tmp_path)
    created = client.post(
        f"/api/structured-extraction/tasks/{task_id}/exports",
        json={"run_id": run_id, "formats": ["json"]},
        headers={"X-User-Id": "alice"},
    )
    assert created.status_code == 200

    response = client.post(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}/resume", headers={"X-User-Id": "alice"})

    assert response.status_code == 409
    assert "run_locked_by_review_or_export" in response.json()["detail"]


def test_completed_and_foreign_runs_are_not_resumable(monkeypatch, tmp_path):
    from test_structured_extraction_review import _client_with_completed_run

    client, task_id, run_id, _root = _client_with_completed_run(monkeypatch, tmp_path)

    recovery = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}/recovery", headers={"X-User-Id": "alice"})
    assert recovery.status_code == 200
    assert recovery.json()["resumable"] is False
    assert "run_already_completed" in recovery.json()["blockers"]

    resume = client.post(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}/resume", headers={"X-User-Id": "alice"})
    assert resume.status_code == 400
    assert "run_not_resumable" in resume.json()["detail"]

    bob = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}/recovery", headers={"X-User-Id": "bob"})
    assert bob.status_code == 404


def test_cancelled_run_with_remaining_items_can_resume(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)
    run = _start_completed_with_errors(client, task_id, monkeypatch)

    from modules.structured_extraction.shared import structured_extraction_run_service

    structured_extraction_run_service.store.conn.execute(
        "update structured_extraction_runs set status = 'cancelled' where run_id = ?",
        (run["run_id"],),
    )
    structured_extraction_run_service.store.conn.commit()
    recovery = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/recovery", headers={"X-User-Id": "alice"}).json()
    assert recovery["resumable"] is True

    import modules.structured_extraction.llm_extraction as llm_extraction

    fake = FakeLLM(['{"records":[]}'])
    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False: fake)
    response = client.post(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/resume", headers={"X-User-Id": "alice"})
    assert response.status_code == 200
    terminal = _wait_for_terminal(client, task_id, run["run_id"])
    assert terminal["status"] == "completed"
