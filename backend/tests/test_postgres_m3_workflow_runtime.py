from __future__ import annotations

import importlib
import re
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from postgres_test_utils import migrated_postgres_schema

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _reload_runtime_modules():
    modules = [
        "main",
        "api.modules_router",
        "api.workflow_router",
        "modules.workflow.shared",
        "modules.workflow.store",
        "modules.workflow.orchestrator",
        "modules.workflow.runners.corpus_stage",
        "modules.workflow.runners.agent_step",
        "modules.workflow.runners.research_controller",
        "modules.literature_search.job_store",
        "modules.literature_search.literature_search_shared",
        "core.user_store",
        "core.user_context",
        "core.session_store",
    ]
    for name in modules:
        sys.modules.pop(name, None)
        if "." in name:
            package_name, attribute = name.rsplit(".", 1)
            package = sys.modules.get(package_name)
            if package is not None and hasattr(package, attribute):
                delattr(package, attribute)
    loaded = {}
    for name in reversed(modules):
        loaded[name] = importlib.import_module(name)
    return loaded


def _run_worker_once(modules, *, queues: list[str], max_jobs: int = 1) -> int:
    from core.worker.queue import JobQueue
    from core.worker.registry import build_handler_registry
    from core.worker.runtime import WorkerRuntime

    engine = modules["main"].postgres_engine
    runtime = WorkerRuntime(
        JobQueue(engine),
        build_handler_registry(engine=engine),
        worker_id="test-worker",
        queues=queues,
        max_jobs_per_tick=max_jobs,
    )
    return runtime.run_once()


def test_workflow_api_uses_postgres_uuid_ids_and_user_boundaries():
    with migrated_postgres_schema() as (url, schema):
        modules = _reload_runtime_modules()
        client = TestClient(modules["main"].app)
        template_id = client.get("/api/workflows/templates").json()["templates"][0]["id"]

        alice_session = client.post(
            "/api/sessions",
            headers={"X-User-Id": "alice"},
            json={"module_id": "literature_search", "title": "Alice source session"},
        ).json()
        alice = client.post(
            "/api/workflows",
            headers={"X-User-Id": "alice"},
            json={
                "template_id": template_id,
                "topic": "large language models materials discovery",
                "title": "Alice workflow",
                "session_id": alice_session["session_id"],
            },
        )
        bob_cross_session = client.post(
            "/api/workflows",
            headers={"X-User-Id": "bob"},
            json={"template_id": template_id, "topic": "bob", "session_id": alice_session["session_id"]},
        )
        bob = client.post(
            "/api/workflows",
            headers={"X-User-Id": "bob"},
            json={"template_id": template_id, "topic": "bob", "title": "Bob workflow"},
        )

        alice_body = alice.json()
        bob_body = bob.json()
        alice_list = client.get("/api/workflows", headers={"X-User-Id": "alice"}).json()["workflows"]
        bob_list = client.get("/api/workflows", headers={"X-User-Id": "bob"}).json()["workflows"]
        bob_get_alice = client.get(f"/api/workflows/{alice_body['workflow_id']}", headers={"X-User-Id": "bob"})
        alice_detail = client.get(f"/api/workflows/{alice_body['workflow_id']}", headers={"X-User-Id": "alice"}).json()

        engine = create_engine(url, future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(f'select workflow_id, user_id from "{schema}".workflow_runs order by title')).all()
        finally:
            engine.dispose()

    assert alice.status_code == 200
    assert bob.status_code == 200
    assert bob_cross_session.status_code == 404
    assert UUID_RE.match(alice_body["workflow_id"])
    assert UUID_RE.match(bob_body["workflow_id"])
    assert UUID_RE.match(alice_body["user_id"])
    assert alice_body["user_id"] != "alice"
    assert [item["workflow_id"] for item in alice_list] == [alice_body["workflow_id"]]
    assert [item["workflow_id"] for item in bob_list] == [bob_body["workflow_id"]]
    assert bob_get_alice.status_code == 404
    assert alice_detail["workflow_id"] == alice_body["workflow_id"]
    assert alice_detail["session_id"] == alice_session["session_id"]
    assert alice_detail["steps"]
    assert len(rows) == 2


def test_workflow_start_records_owner_job_and_stream_is_owner_scoped():
    with migrated_postgres_schema() as (url, schema):
        modules = _reload_runtime_modules()
        client = TestClient(modules["main"].app)
        template_id = client.get("/api/workflows/templates").json()["templates"][0]["id"]
        workflow = client.post(
            "/api/workflows",
            headers={"X-User-Id": "alice"},
            json={"template_id": template_id, "topic": "owner scoped start"},
        ).json()

        start = client.post(f"/api/workflows/{workflow['workflow_id']}/start", headers={"X-User-Id": "alice"})
        bob_start = client.post(f"/api/workflows/{workflow['workflow_id']}/start", headers={"X-User-Id": "bob"})
        bob_stream = client.get(f"/api/workflows/{workflow['workflow_id']}/stream", headers={"X-User-Id": "bob"})
        _run_worker_once(modules, queues=["workflow"], max_jobs=1)
        alice_stream = client.get(f"/api/workflows/{workflow['workflow_id']}/stream", headers={"X-User-Id": "alice"})
        detail = client.get(f"/api/workflows/{workflow['workflow_id']}", headers={"X-User-Id": "alice"}).json()

        engine = create_engine(url, future=True)
        try:
            with engine.connect() as conn:
                job_user_id = conn.execute(
                    text(f'select user_id from "{schema}".jobs where job_id = :job_id'),
                    {"job_id": detail["engine_ref"]["orchestrator_job_id"]},
                ).scalar_one()
        finally:
            engine.dispose()

    assert start.status_code == 200
    assert alice_stream.status_code == 200
    assert "done" in alice_stream.text
    assert UUID_RE.match(start.json()["job_id"])
    assert bob_start.status_code == 404
    assert bob_stream.status_code == 404
    assert detail["engine_ref"]["orchestrator_job_id"] == start.json()["job_id"]
    assert str(job_user_id) == workflow["user_id"]
