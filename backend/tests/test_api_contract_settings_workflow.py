from __future__ import annotations

from fastapi.testclient import TestClient


def test_settings_readiness_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))

    import main

    client = TestClient(main.app)
    body = client.get("/api/settings/readiness").json()

    assert {"ready", "mode", "active_model", "reasons", "warnings", "fallback_mode"}.issubset(body)
    assert isinstance(body["reasons"], list)
    assert isinstance(body["warnings"], list)


def test_workflow_templates_contract_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))

    import main

    client = TestClient(main.app)
    response = client.get("/api/workflows/templates")

    assert response.status_code == 200
    body = response.json()
    assert {"categories", "templates", "task_profiles"}.issubset(body)
    assert isinstance(body["categories"], list)
    assert isinstance(body["templates"], list)
    assert body["templates"]
    first = body["templates"][0]
    assert {"id", "name", "desc", "steps"}.issubset(first)
