from __future__ import annotations

import asyncio
import json
import re
import time

from test_structured_extraction_preparation import _client_with_schema

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class FakeLLM:
    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls: list[list[dict]] = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append(messages)
        text = self.outputs.pop(0) if self.outputs else '{"records":[]}'
        yield {"type": "content", "text": text}


def _prepare_inputs(client, task_id: str) -> None:
    compiled = client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers={"X-User-Id": "alice"})
    assert compiled.status_code == 200
    built = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build",
        json={"max_chunks_per_group": 1, "max_chars_per_chunk": 300, "include_assets": True},
        headers={"X-User-Id": "alice"},
    )
    assert built.status_code == 200


def _run_structured_worker_once(max_jobs: int = 10) -> None:
    import main
    from core.worker.queue import JobQueue
    from core.worker.registry import build_handler_registry
    from core.worker.runtime import WorkerRuntime

    engine = main.postgres_engine
    runtime = WorkerRuntime(
        JobQueue(engine),
        build_handler_registry(engine=engine),
        worker_id="test-structured-worker",
        queues=["structured-extraction"],
        max_jobs_per_tick=max_jobs,
    )
    runtime.run_once()


def _wait_for_terminal(client, task_id: str, run_id: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _run_structured_worker_once()
        run = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}", headers={"X-User-Id": "alice"}).json()
        if run["status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run did not finish in time: {run}")


def _record_json(paper_id: str, membrane_name: str, fields: dict) -> str:
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


def test_extraction_run_success_merges_records_and_writes_artifacts(monkeypatch, tmp_path):
    client, task_id, root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)

    outputs = [
        _record_json(
            "p_prep_1",
            "PES-ZW",
            {
                "membrane_name": {
                    "raw_value": "PES-ZW",
                    "normalized_value": "PES-ZW",
                    "unit": "",
                    "condition_context": None,
                    "evidence_text": "The membrane name PES-ZW was prepared",
                    "evidence_location": "Methods",
                    "extraction_note": "",
                }
            },
        ),
        _record_json(
            "p_prep_1",
            "PES-ZW",
            {
                "water_flux": {
                    "raw_value": "120 LMH",
                    "normalized_value": 120,
                    "unit": "LMH",
                    "condition_context": None,
                    "evidence_text": "water flux of 120 LMH",
                    "evidence_location": "Results",
                    "extraction_note": "",
                }
            },
        ),
        '{"records":[]}',
        '{"records":[]}',
    ]
    fake = FakeLLM(outputs)

    import modules.structured_extraction.llm_extraction as llm_extraction

    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False, user_id=None: fake)
    monkeypatch.setattr(llm_extraction.settings_store, "model_config", lambda user_id=None: {"provider": "fake", "chat_model": "weak", "strong_model": "strong"})

    missing = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", json={"packet_version": "missing"}, headers={"X-User-Id": "alice"})
    assert missing.status_code == 400
    assert "evidence_packet_not_found" in missing.json()["detail"]

    started = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"})
    assert started.status_code == 200
    run = started.json()
    assert UUID_RE.match(run["run_id"])
    assert run["status"] in {"queued", "running"}
    assert run["packet_version"] == "ep_v1"
    assert run["model_snapshot"]["model"] == "strong"
    assert run["stats"]["packet_item_count"] == 4

    final = _wait_for_terminal(client, task_id, run["run_id"])
    assert final["status"] == "completed"
    assert final["stats"]["completed_item_count"] == 4
    assert final["stats"]["failed_item_count"] == 0
    assert final["stats"]["record_count"] == 1

    items = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/items", headers={"X-User-Id": "alice"}).json()["items"]
    assert len(items) == 4
    assert all(item["status"] == "completed" for item in items)
    assert all(item["prompt"] for item in items)

    records = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/records", headers={"X-User-Id": "alice"}).json()["records"]
    assert len(records) == 1
    assert records[0]["record_identity"]["membrane_name"] == "PES-ZW"
    assert records[0]["fields"]["membrane_name"]["raw_value"] == "PES-ZW"
    assert records[0]["fields"]["water_flux"]["normalized_value"] == 120
    assert len(records[0]["source_packet_item_ids"]) == 2

    listed = client.get(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()["runs"]
    assert listed[0]["run_id"] == run["run_id"]

    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    assert task["status"] == "review_required"
    assert task["stats"]["run_count"] == 1
    assert task["last_run_at"] is not None
    workspace = root / "users" / task["user_id"] / task["workspace_rel_path"] / "runs"
    assert (workspace / f"run_{run['run_id']}.json").exists()
    assert (workspace / f"run_{run['run_id']}_items.jsonl").exists()
    assert (workspace / f"run_{run['run_id']}_records.jsonl").exists()
    assert (workspace / f"run_{run['run_id']}_prompts.jsonl").exists()

    bob = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}", headers={"X-User-Id": "bob"})
    assert bob.status_code == 404


def test_extraction_run_partial_invalid_output_and_llm_unavailable(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)

    fake = FakeLLM([
        _record_json("p_prep_1", "PES-ZW", {"membrane_name": {"raw_value": "PES-ZW", "evidence_text": "PES-ZW"}}),
        "not json",
        '{"records":[]}',
        '{"records":[]}',
    ])

    import modules.structured_extraction.llm_extraction as llm_extraction

    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False, user_id=None: fake)
    monkeypatch.setattr(llm_extraction.settings_store, "model_config", lambda user_id=None: {"provider": "fake", "chat_model": "weak", "strong_model": "strong"})

    started = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()
    final = _wait_for_terminal(client, task_id, started["run_id"])
    assert final["status"] == "completed_with_errors"
    assert final["stats"]["failed_item_count"] == 1
    failed_items = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{started['run_id']}/items", headers={"X-User-Id": "alice"}).json()["items"]
    assert any(item["status"] == "failed" and item["error"]["reason"] == "llm_output_invalid" for item in failed_items)

    def unavailable(_settings_store, strong=False, user_id=None):
        from core.llm import LLMUnavailable

        raise LLMUnavailable("no model")

    monkeypatch.setattr(llm_extraction, "build_llm_client", unavailable)
    failed = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()
    final_failed = _wait_for_terminal(client, task_id, failed["run_id"])
    assert final_failed["status"] == "failed"
    assert final_failed["error"]["reason"] == "llm_unavailable"


def test_extraction_run_tolerates_non_object_record_identity(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)

    fake = FakeLLM(
        [
            json.dumps(
                {
                    "records": [
                        {
                            "paper_id": "p_prep_1",
                            "record_identity": ["p_prep_1"],
                            "fields": {
                                "membrane_name": {
                                    "raw_value": "PES-ZW",
                                    "normalized_value": "PES-ZW",
                                    "evidence_text": "The membrane name PES-ZW was prepared",
                                    "evidence_location": "Methods",
                                }
                            },
                        }
                    ]
                }
            ),
            _record_json(
                "p_prep_1",
                "PES-ZW",
                {
                    "water_flux": {
                        "raw_value": "120 LMH",
                        "normalized_value": 120,
                        "unit": "LMH",
                        "evidence_text": "water flux of 120 LMH",
                        "evidence_location": "Results",
                    }
                },
            ),
            '{"records":[]}',
            '{"records":[]}',
        ]
    )

    import modules.structured_extraction.llm_extraction as llm_extraction

    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False, user_id=None: fake)
    monkeypatch.setattr(llm_extraction.settings_store, "model_config", lambda user_id=None: {"provider": "fake", "chat_model": "weak", "strong_model": "strong"})

    started = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()
    final = _wait_for_terminal(client, task_id, started["run_id"])

    assert final["status"] == "completed"
    assert final["stats"]["record_count"] == 2

    records = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{started['run_id']}/records", headers={"X-User-Id": "alice"}).json()["records"]
    assert any("invalid_record_identity_shape" in record["quality_flags"] for record in records)


def test_extraction_run_cancel_and_orphan_reap(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)
    _prepare_inputs(client, task_id)

    class SlowLLM:
        async def stream_chat(self, messages, tools=None):
            await asyncio.sleep(0.2)
            yield {"type": "content", "text": '{"records":[]}'}

    import modules.structured_extraction.llm_extraction as llm_extraction
    from modules.structured_extraction.extraction_runs import StructuredExtractionRunService
    from modules.structured_extraction.shared import structured_extraction_run_service

    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False, user_id=None: SlowLLM())
    monkeypatch.setattr(llm_extraction.settings_store, "model_config", lambda user_id=None: {"provider": "fake", "chat_model": "weak", "strong_model": "strong"})

    run = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()
    cancelled = client.post(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/cancel", headers={"X-User-Id": "alice"})
    assert cancelled.status_code == 200
    terminal = _wait_for_terminal(client, task_id, run["run_id"], timeout=5.0)
    assert terminal["status"] == "cancelled"

    structured_extraction_run_service.store.conn.execute(
        "update structured_extraction_runs set status = 'running' where run_id = ?",
        (run["run_id"],),
    )
    structured_extraction_run_service.store.conn.commit()
    reaper = StructuredExtractionRunService(structured_extraction_run_service.store)
    reaped = reaper.reap_orphaned_runs()
    assert run["run_id"] in reaped
    interrupted = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}", headers={"X-User-Id": "alice"}).json()
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"]["reason"] == "process_restarted"
