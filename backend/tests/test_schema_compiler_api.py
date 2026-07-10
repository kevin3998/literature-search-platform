from __future__ import annotations

import uuid
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from postgres_test_utils import migrated_postgres_schema


def _reload_runtime():
    import importlib
    import sys

    prefixes = (
        "api.structured_extraction_router",
        "modules.structured_extraction",
        "core.user_context",
        "core.user_store",
        "core.settings_store",
        "core.secret_store",
        "core.model_profiles",
    )
    for name in list(sys.modules):
        if name == "main" or any(name.startswith(prefix) for prefix in prefixes):
            sys.modules.pop(name, None)
            if "." in name:
                package_name, attribute = name.rsplit(".", 1)
                package = sys.modules.get(package_name)
                if package is not None and hasattr(package, attribute):
                    delattr(package, attribute)
    return importlib.import_module("main")


def test_schema_compilation_create_list_apply_and_provenance(monkeypatch, tmp_path):
    with migrated_postgres_schema() as (url, schema):
        monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
        main = _reload_runtime()
        client = TestClient(main.app)
        headers = {"X-User-Id": "alice"}
        task = client.post("/api/structured-extraction/tasks", headers=headers, json={"name": "Compiler API"}).json()
        task_id = task["task_id"]

        engine = create_engine(url, future=True)
        with engine.begin() as conn:
            conn.execute(
                text(f'update "{schema}".structured_extraction_tasks set current_collection_version = :version where task_id = :task_id'),
                {"version": "col_v1", "task_id": uuid.UUID(task_id)},
            )

        assisted = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/assist",
            headers=headers,
            json={
                "action": "parse_field_definition",
                "source_format": "json",
                "instruction": '{"field_tree":[{"key":"title","type":"string"},{"key":"latency","label":"Latency","type":"number"}]}',
            },
        )
        assert assisted.status_code == 200, assisted.text
        compilation = assisted.json()["result"]
        compilation_id = compilation["compilation_id"]
        assert compilation["status"] == "valid_with_warnings"
        assert compilation["paper_metadata_fields"] == ["title"]
        assert compilation["system_metadata_contract"]["authors"]["type"] == "list_string"
        assert [node["key"] for node in compilation["field_tree"]] == ["latency"]

        listed = client.get(f"/api/structured-extraction/tasks/{task_id}/schema/compilations", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["compilations"][0]["compilation_id"] == compilation_id
        assert client.get(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{compilation_id}",
            headers={"X-User-Id": "bob"},
        ).status_code == 404

        applied = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{compilation_id}/apply",
            headers=headers,
            json={"mode": "replace"},
        )
        assert applied.status_code == 200, applied.text
        draft = applied.json()
        assert draft["source_compilation_id"] == compilation_id
        assert draft["source_compilation_modified"] is False

        leaked_draft = {**draft, "field_tree": [*draft["field_tree"], {"key": "req_9999", "label": "req_9999", "type": "string", "children": []}]}
        rejected_leaked_draft = client.put(
            f"/api/structured-extraction/tasks/{task_id}/schema/draft",
            headers=headers,
            json=leaked_draft,
        )
        assert rejected_leaked_draft.status_code == 400
        assert "internal_requirement_id_not_allowed:req_9999" in rejected_leaked_draft.json()["detail"]

        invalid_identity_draft = {**draft, "record_schema": {
            **draft["record_schema"],
            "record_unit": "experiment_level",
            "primary_entity": "trial",
            "one_paper_may_have_multiple_records": True,
            "record_identity_fields": ["paper_id", "trial_id"],
            "deduplication_keys": ["paper_id", "trial_id"],
        }, "field_tree": [*draft["field_tree"], {"key": "trial_id", "label": "Trial", "type": "string", "children": []}]}
        rejected_identity = client.put(
            f"/api/structured-extraction/tasks/{task_id}/schema/draft",
            headers=headers,
            json=invalid_identity_draft,
        )
        assert rejected_identity.status_code == 400
        assert "identity_field_not_allowed_in_tree:trial_id" in rejected_identity.json()["detail"]

        draft["field_tree"].append({"key": "throughput", "label": "Throughput", "type": "number", "children": []})
        changed = client.put(
            f"/api/structured-extraction/tasks/{task_id}/schema/draft",
            headers=headers,
            json=draft,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["source_compilation_modified"] is True

        frozen = client.post(f"/api/structured-extraction/tasks/{task_id}/schema/freeze", headers=headers)
        assert frozen.status_code == 200, frozen.text
        assert frozen.json()["source_compilation_id"] == compilation_id
        assert frozen.json()["source_compilation_modified"] is True
        engine.dispose()


def test_schema_compilation_non_applicable_status_is_blocked(monkeypatch, tmp_path):
    with migrated_postgres_schema() as (url, schema):
        monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
        main = _reload_runtime()
        client = TestClient(main.app)
        headers = {"X-User-Id": "alice"}
        task = client.post("/api/structured-extraction/tasks", headers=headers, json={"name": "Blocked compiler"}).json()
        task_id = task["task_id"]
        engine = create_engine(url, future=True)
        with engine.begin() as conn:
            conn.execute(
                text(f'update "{schema}".structured_extraction_tasks set current_collection_version = :version where task_id = :task_id'),
                {"version": "col_v1", "task_id": uuid.UUID(task_id)},
            )
        assisted_response = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/assist",
            headers=headers,
            json={"action": "parse_field_definition", "instruction": "Extract a meaningful outcome without defining a field."},
        )
        assert assisted_response.status_code == 200, assisted_response.text
        assisted = assisted_response.json()
        assert assisted["result"]["status"] in {"needs_review", "llm_unavailable", "failed"}
        blocked = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{assisted['result']['compilation_id']}/apply",
            headers=headers,
            json={"mode": "replace"},
        )
        assert blocked.status_code == 409
        assert "compilation_not_applicable" in blocked.json()["detail"]
        leaked_internal_field = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{assisted['result']['compilation_id']}/resolve",
            headers=headers,
            json={
                "resolutions": [{
                    "requirement_id": "req_0001",
                    "disposition": "user_schema",
                    "target_path": "data.req_0001",
                    "node": {"key": "req_0001", "label": "req_0001", "type": "string"},
                }]
            },
        )
        assert leaked_internal_field.status_code == 400
        assert "internal_requirement_id_cannot_be_field" in leaked_internal_field.json()["detail"]
        resolved = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{assisted['result']['compilation_id']}/resolve",
            headers=headers,
            json={
                "resolutions": [{
                    "requirement_id": "req_0001",
                    "disposition": "user_schema",
                    "target_path": "data.outcome",
                    "reason": "User chose an explicit field",
                    "node": {"key": "outcome", "label": "Outcome", "type": "string"},
                }]
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "valid_with_warnings"
        assert resolved.json()["field_tree"][0]["key"] == "outcome"
        assert resolved.json()["global_instructions"] == []
        assert not any(item.get("code") == "unresolved_requirements" for item in resolved.json()["warnings"])
        assert client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{assisted['result']['compilation_id']}/apply",
            headers=headers,
            json={"mode": "replace"},
        ).status_code == 200

        identity_assisted = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/assist",
            headers=headers,
            json={
                "action": "parse_field_definition",
                "instruction": 'For each sample, return a JSON object with "SampleName" and "Details".',
            },
        ).json()["result"]
        assert identity_assisted["coverage"]["unresolved"] == 1
        assert any(item.get("code") == "unresolved_requirements" for item in identity_assisted["warnings"])

        identity_resolved = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{identity_assisted['compilation_id']}/resolve",
            headers=headers,
            json={
                "resolutions": [{
                    "requirement_id": "req_0001",
                    "disposition": "record_identity",
                    "target_path": "record_identity.sample_name",
                    "reason": "User selected the record identity",
                }]
            },
        )
        assert identity_resolved.status_code == 200, identity_resolved.text
        assert identity_resolved.json()["coverage"]["unresolved"] == 0
        assert not any(item.get("code") == "unresolved_requirements" for item in identity_resolved.json()["warnings"])
        engine.dispose()


def test_record_identity_resolution_updates_the_record_model(monkeypatch, tmp_path):
    with migrated_postgres_schema() as (url, schema):
        monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
        main = _reload_runtime()
        client = TestClient(main.app)
        headers = {"X-User-Id": "alice"}
        task = client.post("/api/structured-extraction/tasks", headers=headers, json={"name": "Identity compiler"}).json()
        task_id = task["task_id"]
        engine = create_engine(url, future=True)
        with engine.begin() as conn:
            conn.execute(
                text(f'update "{schema}".structured_extraction_tasks set current_collection_version = :version where task_id = :task_id'),
                {"version": "col_v1", "task_id": uuid.UUID(task_id)},
            )

        assisted = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/assist",
            headers=headers,
            json={
                "action": "parse_field_definition",
                "source_format": "natural_language",
                "instruction": 'For each primary entity, return one JSON object with "MaterialName" and "Details".',
            },
        ).json()["result"]
        requirement = assisted["requirements"][0]
        assert requirement["raw_name"] == "MaterialName"

        resolved = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{assisted['compilation_id']}/resolve",
            headers=headers,
            json={
                "resolutions": [{
                    "requirement_id": requirement["requirement_id"],
                    "disposition": "record_identity",
                    "target_path": "record_identity.material_name",
                }]
            },
        )
        assert resolved.status_code == 200, resolved.text
        record_schema = resolved.json()["record_schema"]
        assert record_schema["record_type"] == "material_record"
        assert record_schema["record_unit"] == "material_level"
        assert record_schema["primary_entity"] == "material"
        assert record_schema["one_paper_may_have_multiple_records"] is True
        assert record_schema["record_identity_fields"] == ["paper_id", "material_name"]
        assert all(node["key"] != requirement["requirement_id"] for node in resolved.json()["field_tree"])
        engine.dispose()


def test_schema_compilation_runs_as_a_durable_worker_job_and_streams_progress(monkeypatch, tmp_path):
    with migrated_postgres_schema() as (url, schema):
        monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
        main = _reload_runtime()
        client = TestClient(main.app)
        headers = {"X-User-Id": "alice"}
        task = client.post("/api/structured-extraction/tasks", headers=headers, json={"name": "Async compiler"}).json()
        task_id = task["task_id"]
        payload = {
            "action": "parse_field_definition",
            "source_format": "json",
            "instruction": '{"metric": 1}',
            "draft": {"schema_mode": "nested_record", "field_tree": []},
        }

        queued = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations",
            headers=headers,
            json=payload,
        )
        assert queued.status_code == 202, queued.text
        submission = queued.json()
        assert submission["execution_status"] == "queued"
        assert submission["phase"] == "queued"
        assert submission["progress"] == 5
        assert submission["reused"] is False
        assert submission["stream_url"].endswith(f"/{submission['compilation_id']}/stream")

        reused = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations",
            headers=headers,
            json={**payload, "instruction": '{"other_metric": 2}'},
        )
        assert reused.status_code == 202, reused.text
        assert reused.json()["compilation_id"] == submission["compilation_id"]
        assert reused.json()["reused"] is True

        from core.worker.queue import JobQueue
        from core.worker.registry import build_handler_registry
        from core.worker.runtime import WorkerRuntime
        from core.db.engine import engine_for_url

        engine = engine_for_url(url, schema=schema)
        queue = JobQueue(engine)
        job = queue.get(submission["core_job_id"], user_id=task["user_id"])
        assert job["job_type"] == "structured.schema_compile"
        assert job["queue"] == "structured-extraction"
        runtime = WorkerRuntime(
            queue,
            build_handler_registry(engine=engine),
            worker_id="schema-compiler-test",
            queues=["structured-extraction"],
        )
        assert runtime.run_once() == 1

        completed = client.get(
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{submission['compilation_id']}",
            headers=headers,
        )
        assert completed.status_code == 200, completed.text
        compilation = completed.json()
        assert compilation["execution_status"] == "completed"
        assert compilation["phase"] == "completed"
        assert compilation["progress"] == 100
        assert compilation["status"] == "valid_with_warnings"
        assert compilation["field_tree"][0]["key"] == "metric"
        assert compilation["error"] is None

        events = queue.events(submission["core_job_id"], user_id=task["user_id"])
        phases = [event.get("phase") for event in events if event.get("type") == "schema_compilation_progress"]
        assert phases == ["source_parsing", "requirement_graph", "normalization", "validation", "completed"]

        with client.stream(
            "GET",
            f"/api/structured-extraction/tasks/{task_id}/schema/compilations/{submission['compilation_id']}/stream",
            headers=headers,
        ) as response:
            assert response.status_code == 200
            streamed = [
                json.loads(line.removeprefix("data: "))
                for line in response.iter_lines()
                if line.startswith("data: ")
            ]
        assert streamed[0]["type"] == "snapshot"
        assert streamed[0]["compilation"]["execution_status"] == "completed"
        assert streamed[-1]["type"] == "done"
        assert [event["type"] for event in streamed] == ["snapshot", "done"]
        engine.dispose()
