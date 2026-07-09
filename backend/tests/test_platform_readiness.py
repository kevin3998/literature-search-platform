from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient

from postgres_test_utils import migrated_postgres_schema


def _reload_main():
    modules = [
        "main",
        "api.workflow_router",
        "api.structured_extraction_router",
        "modules.workflow.shared",
        "modules.workflow.store",
        "modules.structured_extraction.shared",
        "modules.structured_extraction.store",
        "modules.literature_search.job_store",
        "modules.literature_search.literature_search_shared",
        "core.user_store",
        "core.user_context",
        "core.session_store",
        "core.settings_store",
    ]
    for name in modules:
        sys.modules.pop(name, None)
        if "." in name:
            package_name, attribute = name.rsplit(".", 1)
            package = sys.modules.get(package_name)
            if package is not None and hasattr(package, attribute):
                delattr(package, attribute)
    return importlib.import_module("main")


def test_platform_readiness_checks_core_chat_dependencies():
    with migrated_postgres_schema():
        main = _reload_main()
        client = TestClient(main.app)
        response = client.get("/api/readiness")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is True
    assert body["overall"] in {"ok", "warning"}
    assert body["build"]["api_version"] == "0.1.0"
    assert body["build"]["readiness_contract_version"]
    assert "literature_search_reliability_batch" in body["build"]["capabilities"]
    assert "postgres_operations_m6" in body["build"]["capabilities"]
    check_ids = {check["id"] for check in body["checks"]}
    assert {
        "backend.health",
        "modules.registry",
        "postgres.connection",
        "postgres.migrations",
        "auth.safety",
        "secrets.encryption_key",
        "users.default",
        "sessions.read",
        "workflows.read",
        "structured_extraction.read",
        "workers.heartbeat",
    }.issubset(check_ids)


def test_platform_readiness_fails_when_session_contract_is_broken(monkeypatch):
    with migrated_postgres_schema():
        main = _reload_main()

        def broken_list_sessions(*args, **kwargs):
            raise RuntimeError("session contract broken")

        monkeypatch.setattr(main.session_store, "list_sessions", broken_list_sessions)
        client = TestClient(main.app)
        response = client.get("/api/readiness")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    sessions_check = next(check for check in body["checks"] if check["id"] == "sessions.read")
    assert sessions_check["status"] == "error"
    assert "session contract broken" in sessions_check["detail"]["error"]


def test_platform_readiness_fails_when_workflow_contract_is_broken(monkeypatch):
    with migrated_postgres_schema():
        main = _reload_main()

        def broken_list(*args, **kwargs):
            raise RuntimeError("workflow contract broken")

        monkeypatch.setattr(main.workflow_router.workflow_store, "list", broken_list)
        client = TestClient(main.app)
        response = client.get("/api/readiness")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    workflows_check = next(check for check in body["checks"] if check["id"] == "workflows.read")
    assert workflows_check["status"] == "error"
    assert "workflow contract broken" in workflows_check["detail"]["error"]


def test_platform_readiness_fails_when_structured_extraction_contract_is_broken(monkeypatch):
    with migrated_postgres_schema():
        main = _reload_main()
        from modules.structured_extraction import shared as structured_shared

        def broken_list_tasks(*args, **kwargs):
            raise RuntimeError("structured extraction contract broken")

        monkeypatch.setattr(structured_shared.structured_extraction_store, "list_tasks", broken_list_tasks)
        client = TestClient(main.app)
        response = client.get("/api/readiness")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    structured_check = next(check for check in body["checks"] if check["id"] == "structured_extraction.read")
    assert structured_check["status"] == "error"
    assert "structured extraction contract broken" in structured_check["detail"]["error"]
