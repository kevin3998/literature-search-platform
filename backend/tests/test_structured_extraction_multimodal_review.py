from __future__ import annotations

import json
import time

from test_structured_extraction_review import _client_with_completed_run
from test_structured_extraction_runs import _run_structured_worker_once


def _wait_for_mm_job(client, task_id: str, job_id: str, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _run_structured_worker_once()
        response = client.get(
            f"/api/structured-extraction/tasks/{task_id}/review/multimodal-jobs/{job_id}",
            headers={"X-User-Id": "alice"},
        )
        assert response.status_code == 200
        body = response.json()
        if body["status"] in {"completed", "failed", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError("multimodal review job did not finish")


def test_multimodal_review_requires_enabled_model(monkeypatch, tmp_path):
    client, task_id, run_id, _root = _client_with_completed_run(monkeypatch, tmp_path)

    response = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/runs/{run_id}/multimodal-jobs",
        json={"scan_mode": "related_pages_assets"},
        headers={"X-User-Id": "alice"},
    )

    assert response.status_code == 400
    assert "multimodal_model_not_configured" in response.json()["detail"]


def test_multimodal_review_job_suggestions_summary_accept_and_artifacts(monkeypatch, tmp_path):
    client, task_id, run_id, root = _client_with_completed_run(monkeypatch, tmp_path)
    settings = client.patch(
        "/api/settings",
        json={"models": {"multimodal_enabled": True, "multimodal_model": "gpt-4o", "multimodal_scan_default": "related_pages_assets"}},
        headers={"X-User-Id": "alice"},
    )
    assert settings.status_code == 200

    started = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/runs/{run_id}/multimodal-jobs",
        json={"scan_mode": "related_pages_assets", "reason": "run level review"},
        headers={"X-User-Id": "alice"},
    )
    assert started.status_code == 200
    assert started.json()["scan_mode"] == "related_pages_assets"
    assert started.json()["total_item_count"] >= 1
    job = _wait_for_mm_job(client, task_id, started.json()["job_id"])
    assert job["status"] == "completed"
    assert job["suggestion_count"] >= 1
    assert job["suggestions"][0]["provenance"]["source"] == "multimodal"

    duplicate = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/runs/{run_id}/multimodal-jobs",
        json={"scan_mode": "full_document"},
        headers={"X-User-Id": "alice"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["job_id"] != job["job_id"]

    summary = client.get(
        f"/api/structured-extraction/tasks/{task_id}/review/summary?run_id={run_id}",
        headers={"X-User-Id": "alice"},
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["risk_counts"]
    assert body["coverage_counts"]
    assert body["pending_suggestion_count"] >= 1
    assert body["bulk_accept_eligible_count"] == 0

    queue = client.get(
        f"/api/structured-extraction/tasks/{task_id}/review/queue?run_id={run_id}&queue=multimodal_pending",
        headers={"X-User-Id": "alice"},
    )
    assert queue.status_code == 200
    assert queue.json()["total"] >= 1
    suggestion = queue.json()["rows"][0]["suggestions"][0]

    accepted = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/suggestions/{suggestion['suggestion_id']}/accept",
        json={"reason": "accepted multimodal check"},
        headers={"X-User-Id": "alice"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["suggestion"]["status"] == "accepted"
    record_id = accepted.json()["record"]["record_id"]
    field_key = suggestion["field_key"]
    assert accepted.json()["record"]["fields"][field_key]["status"] == "multimodal_pending"
    assert accepted.json()["record"]["fields"][field_key]["provenance"]["source"] == "multimodal"

    events = client.get(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/events",
        headers={"X-User-Id": "alice"},
    ).json()["events"]
    assert events[-1]["event_type"] == "accept_multimodal_suggestion"
    assert events[-1]["payload"]["provenance"]["job_id"] == job["job_id"]

    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    audit = root / "users" / task["user_id"] / task["workspace_rel_path"] / "audit"
    assert (audit / f"multimodal_jobs_{run_id}.jsonl").exists()
    assert (audit / f"multimodal_suggestions_{run_id}.jsonl").exists()
    assert (audit / f"review_summary_{run_id}.json").exists()


def test_multimodal_review_reject_bulk_and_export_provenance(monkeypatch, tmp_path):
    client, task_id, run_id, root = _client_with_completed_run(monkeypatch, tmp_path)
    client.patch(
        "/api/settings",
        json={"models": {"multimodal_enabled": True, "multimodal_model": "gpt-4o"}},
        headers={"X-User-Id": "alice"},
    )
    started = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/runs/{run_id}/multimodal-jobs",
        json={"scan_mode": "evidence_only"},
        headers={"X-User-Id": "alice"},
    ).json()
    job = _wait_for_mm_job(client, task_id, started["job_id"])
    suggestion_ids = [item["suggestion_id"] for item in job["suggestions"]]
    assert suggestion_ids

    rejected = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/suggestions/{suggestion_ids[0]}/reject",
        json={"reason": "not useful"},
        headers={"X-User-Id": "alice"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["suggestion"]["status"] == "rejected"

    if len(suggestion_ids) > 1:
        bulk = client.post(
            f"/api/structured-extraction/tasks/{task_id}/review/suggestions/bulk",
            json={"suggestion_ids": suggestion_ids[1:], "action": "accept", "reason": "batch multimodal"},
            headers={"X-User-Id": "alice"},
        )
        assert bulk.status_code == 200
        assert bulk.json()["updated"] == len(suggestion_ids) - 1

    created = client.post(
        f"/api/structured-extraction/tasks/{task_id}/exports",
        json={"run_id": run_id, "formats": ["json"], "include_review_metadata": True},
        headers={"X-User-Id": "alice"},
    )
    assert created.status_code == 200
    export_id = created.json()["export_id"]
    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    manifest_path = root / "users" / task["user_id"] / task["workspace_rel_path"] / "exports" / export_id / f"export_{export_id}_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "multimodal_provenance" in manifest
    assert manifest["multimodal_provenance"]["job_count"] >= 1
