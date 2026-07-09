from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient

from postgres_test_utils import migrated_postgres_schema


def _reload_main():
    modules = [
        "main",
        "api.modules_router",
        "api.workflow_router",
        "modules.workflow.shared",
        "modules.workflow.store",
        "modules.workflow.orchestrator",
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
    return importlib.import_module("main")


def _template_id(client: TestClient) -> str:
    templates = client.get("/api/workflows/templates").json()["templates"]
    return templates[0]["id"]


def test_workflows_are_scoped_by_header_user() -> None:
    with migrated_postgres_schema():
        client = TestClient(_reload_main().app)
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
        bob_get_alice = client.get(f"/api/workflows/{alice['workflow_id']}", headers={"X-User-Id": "bob"})

    assert [item["workflow_id"] for item in alice_list] == [alice["workflow_id"]]
    assert [item["workflow_id"] for item in bob_list] == [bob["workflow_id"]]
    assert bob_get_alice.status_code == 404


def test_workflow_create_rejects_cross_user_session() -> None:
    with migrated_postgres_schema():
        client = TestClient(_reload_main().app)
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


def test_workflow_stream_requires_workflow_owner() -> None:
    with migrated_postgres_schema():
        main = _reload_main()
        client = TestClient(main.app)
        template_id = _template_id(client)
        alice = client.post(
            "/api/workflows",
            headers={"X-User-Id": "alice"},
            json={"template_id": template_id, "topic": "A"},
        ).json()
        main.workflow_router.workflow_store.set_engine_ref(alice["workflow_id"], orchestrator_job_id=None)

        response = client.get(f"/api/workflows/{alice['workflow_id']}/stream", headers={"X-User-Id": "bob"})

    assert response.status_code == 404
