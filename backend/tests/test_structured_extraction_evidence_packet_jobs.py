from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid

from test_structured_extraction_preparation import _client_with_schema
from test_structured_extraction_runs import _run_structured_worker_once

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_ranked_chunks_checks_cancel_during_scan():
    from modules.structured_extraction import evidence_packets

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table documents (
            id integer primary key,
            paper_id text,
            kind text,
            section text,
            heading_norm text,
            section_id text,
            chunk_index integer,
            source_path text,
            text text
        )
        """
    )
    conn.executemany(
        "insert into documents values(?, 'p1', 'section_chunk', 'Results', 'results', 's1', ?, 'a.md', 'water flux membrane')",
        [(idx, idx) for idx in range(1, 10)],
    )
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] >= 2

    try:
        evidence_packets._ranked_chunks(conn, "p1", "water flux", limit=5, max_chars=120, should_cancel=should_cancel)
    except evidence_packets._BuildCancelled:
        pass
    else:
        raise AssertionError("expected ranked chunk scan to raise _BuildCancelled")


def test_ranked_chunks_prefers_article_id_and_marks_query_mode():
    from modules.structured_extraction import evidence_packets

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table documents (
            id integer primary key,
            paper_id text,
            article_id integer,
            kind text,
            section text,
            heading_norm text,
            section_id text,
            chunk_index integer,
            source_path text,
            text text
        )
        """
    )
    conn.execute("create index idx_documents_article_id on documents(article_id)")
    conn.executemany(
        "insert into documents values(?, ?, ?, 'section_chunk', 'Results', 'results', 's1', ?, 'a.md', ?)",
        [
            (1, "wrong_paper_id", 42, 0, "water flux membrane article match"),
            (2, "p1", 999, 0, "water flux membrane paper fallback should not be used"),
        ],
    )

    chunks = evidence_packets._ranked_chunks(conn, "p1", "water flux", limit=5, max_chars=120, article_id=42)

    assert len(chunks) == 1
    assert chunks[0]["evidence_id"] == "E1"
    assert chunks[0]["query_mode"] == "article_id"
    assert chunks[0]["article_id"] == 42


def test_build_one_item_falls_back_to_paper_id_when_article_id_missing():
    from modules.structured_extraction.evidence_packets import StructuredExtractionEvidencePacketService

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table documents (
            id integer primary key,
            paper_id text,
            article_id integer,
            kind text,
            section text,
            heading_norm text,
            section_id text,
            chunk_index integer,
            source_path text,
            text text
        )
        """
    )
    conn.execute("create table paper_assets (paper_id text, kind text, source_path text, label text, caption text)")
    conn.execute("insert into documents values(1, 'p1', null, 'section_chunk', 'Results', 'results', 's1', 0, 'a.md', 'water flux membrane fallback')")

    service = StructuredExtractionEvidencePacketService.__new__(StructuredExtractionEvidencePacketService)
    item, warnings = service._build_one_item(
        conn,
        "ep_v1",
        {"paper_id": "p1", "article_id": None, "metadata": {}},
        {"group_key": "performance", "label": "性能", "description": "water flux"},
        [{"key": "water_flux", "label": "Water flux", "description": "water flux"}],
        {"record_schema": {"primary_entity": "membrane"}},
        {"max_chunks_per_group": 3, "max_chars_per_chunk": 120, "include_assets": False},
        1.0,
    )

    assert item["chunks"][0]["query_mode"] == "paper_id_fallback"
    assert "article_id_missing_fallback_to_paper_id" in item["warnings"]
    assert warnings[0]["warning"] == "article_id_missing_fallback_to_paper_id"


def _compile_contract(client, task_id: str) -> None:
    compiled = client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers={"X-User-Id": "alice"})
    assert compiled.status_code == 200


def _wait_for_job(client, task_id: str, build_job_id: str, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        _run_structured_worker_once()
        job = client.get(
            f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs/{build_job_id}",
            headers={"X-User-Id": "alice"},
        ).json()
        if job["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"build job did not finish in time: {job}")


def test_evidence_packet_build_job_completes_and_paginates_items(monkeypatch, tmp_path):
    client, task_id, root = _client_with_schema(monkeypatch, tmp_path)
    _compile_contract(client, task_id)

    started = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs",
        json={"max_chunks_per_group": 1, "max_chars_per_chunk": 120, "include_assets": True},
        headers={"X-User-Id": "alice"},
    )
    assert started.status_code == 200
    job = started.json()
    assert UUID_RE.match(job["build_job_id"])
    assert job["status"] in {"queued", "running", "completed"}
    assert job["target_packet_version"] == "ep_v1"
    assert job["total_item_count"] == 4

    final = _wait_for_job(client, task_id, job["build_job_id"])
    assert final["status"] == "completed"
    assert final["phase"] == "completed"
    assert final["result_packet_version"] == "ep_v1"
    assert final["processed_item_count"] == 4
    assert final["warning_count"] >= 0

    version = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions/ep_v1",
        headers={"X-User-Id": "alice"},
    ).json()
    assert version["item_count"] == 4

    first_page = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions/ep_v1/items?limit=2&offset=1",
        headers={"X-User-Id": "alice"},
    ).json()
    assert first_page["limit"] == 2
    assert first_page["offset"] == 1
    assert first_page["total"] == 4
    assert len(first_page["items"]) == 2

    listed = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs",
        headers={"X-User-Id": "alice"},
    ).json()
    assert listed["jobs"][0]["build_job_id"] == job["build_job_id"]

    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    workspace = root / "users" / task["user_id"] / task["workspace_rel_path"] / "evidence_packets"
    assert json.loads((workspace / "packet_ep_v1.json").read_text(encoding="utf-8"))["packet_version"] == "ep_v1"
    assert len((workspace / "packet_ep_v1_items.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 4

    bob = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs/{job['build_job_id']}",
        headers={"X-User-Id": "bob"},
    )
    assert bob.status_code == 404


def test_evidence_packet_build_job_reuses_active_job_and_can_cancel(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _compile_contract(client, task_id)

    import modules.structured_extraction.evidence_packets as evidence_packets

    original = evidence_packets._ranked_chunks

    def slow_ranked_chunks(*args, **kwargs):
        time.sleep(0.2)
        return original(*args, **kwargs)

    monkeypatch.setattr(evidence_packets, "_ranked_chunks", slow_ranked_chunks)

    first = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs",
        json={"max_chunks_per_group": 1},
        headers={"X-User-Id": "alice"},
    ).json()
    second = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs",
        json={"max_chunks_per_group": 1},
        headers={"X-User-Id": "alice"},
    ).json()
    assert second["build_job_id"] == first["build_job_id"]

    cancelled = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs/{first['build_job_id']}/cancel",
        headers={"X-User-Id": "alice"},
    )
    assert cancelled.status_code == 200
    final = _wait_for_job(client, task_id, first["build_job_id"])
    assert final["status"] == "cancelled"
    assert final["result_packet_version"] is None

    versions = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions",
        headers={"X-User-Id": "alice"},
    ).json()
    assert versions["versions"] == []


def test_evidence_packet_build_job_reaper_marks_active_jobs_interrupted(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _compile_contract(client, task_id)

    from modules.structured_extraction.evidence_packets import StructuredExtractionEvidencePacketService
    from modules.structured_extraction.shared import (
        structured_extraction_evidence_packet_service,
        structured_extraction_prompt_contract_service,
    )

    from core.memory_db import dumps, now

    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    build_job_id = str(uuid.uuid4())
    ts = now()
    structured_extraction_evidence_packet_service.store.conn.execute(
        """
        insert into structured_extraction_evidence_packet_build_jobs(
            build_job_id, task_id, user_id, status, phase, collection_version, schema_version,
            prompt_contract_version, target_packet_version, settings_json, created_at, updated_at
        ) values(?, ?, ?, 'running', 'building_items', 'col_v1', 'schema_v1', 'pc_v1', 'ep_v1', ?, ?, ?)
        """,
        (build_job_id, task_id, task["user_id"], dumps({}), ts, ts),
    )
    structured_extraction_evidence_packet_service.store.conn.commit()

    reaper = StructuredExtractionEvidencePacketService(
        structured_extraction_evidence_packet_service.store,
        structured_extraction_prompt_contract_service,
    )
    reaped = reaper.reap_orphaned_build_jobs()
    assert build_job_id in reaped
    interrupted = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build-jobs/{build_job_id}",
        headers={"X-User-Id": "alice"},
    ).json()
    assert interrupted["status"] == "interrupted"
    assert interrupted["phase"] == "interrupted"
    assert interrupted["error"]["reason"] == "process_restarted"
