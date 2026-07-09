from __future__ import annotations

from fastapi.testclient import TestClient

from core.session_store import SessionStore
from modules.literature_search.job_store import JobStore
from modules.workflow.store import WorkflowStore


def _client(monkeypatch, tmp_path):
    import api.modules_router as modules_router
    import api.workflow_router as workflow_router
    import main
    import modules.workflow.shared as workflow_shared

    db_path = tmp_path / "memory.sqlite"
    session_store = SessionStore(db_path=db_path)
    workflow_store = WorkflowStore(db_path=db_path)
    job_store = JobStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", session_store)
    monkeypatch.setattr(main, "session_store", session_store)
    monkeypatch.setattr(workflow_router, "workflow_store", workflow_store)
    monkeypatch.setattr(workflow_router, "job_store", job_store)
    monkeypatch.setattr(workflow_shared, "workflow_store", workflow_store)
    return TestClient(main.app), session_store, workflow_store


def _template_id(client: TestClient) -> str:
    templates = client.get("/api/workflows/templates").json()["templates"]
    return templates[0]["id"]


def test_workflows_are_scoped_by_header_user(monkeypatch, tmp_path) -> None:
    client, _sessions, _workflows = _client(monkeypatch, tmp_path)
    template_id = _template_id(client)

    alice = client.post(
        "/api/workflows",
        headers={"X-User-Id": "alice"},
        json={"template_id": template_id, "topic": "A", "title": "Alice workflow"},
    ).json()
    bob = client.post(
        "/api/workflows",
        headers={"X-User-Id": "bob"},
        json={"template_id": template_id, "topic": "B", "title": "Bob workflow"},
    ).json()

    alice_list = client.get("/api/workflows", headers={"X-User-Id": "alice"}).json()["workflows"]
    bob_list = client.get("/api/workflows", headers={"X-User-Id": "bob"}).json()["workflows"]

    assert [item["workflow_id"] for item in alice_list] == [alice["workflow_id"]]
    assert [item["workflow_id"] for item in bob_list] == [bob["workflow_id"]]
    assert client.get(f"/api/workflows/{alice['workflow_id']}", headers={"X-User-Id": "bob"}).status_code == 404


def test_workflow_create_rejects_cross_user_session(monkeypatch, tmp_path) -> None:
    client, _sessions, _workflows = _client(monkeypatch, tmp_path)
    template_id = _template_id(client)
    alice_session = client.post(
        "/api/sessions",
        headers={"X-User-Id": "alice"},
        json={"module_id": "literature_search", "title": "Alice"},
    ).json()

    response = client.post(
        "/api/workflows",
        headers={"X-User-Id": "bob"},
        json={"template_id": template_id, "topic": "B", "session_id": alice_session["session_id"]},
    )

    assert response.status_code == 404


def test_workflow_stream_requires_workflow_owner(monkeypatch, tmp_path) -> None:
    client, _sessions, workflow_store = _client(monkeypatch, tmp_path)
    template_id = _template_id(client)
    alice = client.post(
        "/api/workflows",
        headers={"X-User-Id": "alice"},
        json={"template_id": template_id, "topic": "A"},
    ).json()
    workflow_store.set_engine_ref(alice["workflow_id"], orchestrator_job_id="job_missing")

    response = client.get(f"/api/workflows/{alice['workflow_id']}/stream", headers={"X-User-Id": "bob"})

    assert response.status_code == 404
