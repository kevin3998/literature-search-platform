from __future__ import annotations

from fastapi.testclient import TestClient


def test_platform_readiness_checks_core_chat_dependencies(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))

    import main

    client = TestClient(main.app)
    response = client.get("/api/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["overall"] == "ok"
    assert body["build"]["api_version"] == "0.1.0"
    assert body["build"]["readiness_contract_version"]
    assert "literature_search_reliability_batch" in body["build"]["capabilities"]
    check_ids = {check["id"] for check in body["checks"]}
    assert {
        "backend.health",
        "modules.registry",
        "memory.db",
        "sessions.read",
    }.issubset(check_ids)


def test_platform_readiness_fails_when_session_contract_is_broken(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))

    import main

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
