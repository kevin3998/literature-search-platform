from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_structured_extraction_task_lifecycle_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))

    import main

    client = TestClient(main.app)

    created = client.post(
        "/api/structured-extraction/tasks",
        json={"name": "AI 综述工具数据抽取", "description": "first pass"},
        headers={"X-User-Id": "alice"},
    )
    assert created.status_code == 200
    task = created.json()
    assert UUID_RE.match(task["task_id"])
    assert UUID_RE.match(task["user_id"])
    assert task["name"] == "AI 综述工具数据抽取"
    assert task["description"] == "first pass"
    assert task["status"] == "draft"
    assert task["current_collection_version"] is None
    assert task["current_schema_version"] is None
    assert task["model_settings"] == {}
    assert task["stats"] == {"paper_count": 0, "field_count": 0, "run_count": 0, "export_count": 0}
    assert task["archived"] is False
    assert task["deleted_at"] is None
    assert task["last_run_at"] is None

    workspace = tmp_path / "users" / task["user_id"] / task["workspace_rel_path"]
    assert workspace.exists()
    assert (workspace / "task.json").exists()
    for dirname in ["collection", "schemas", "evidence_packets", "prompts", "runs", "exports", "audit"]:
        assert (workspace / dirname).is_dir()
    manifest = json.loads((workspace / "task.json").read_text(encoding="utf-8"))
    assert manifest["task_id"] == task["task_id"]
    assert manifest["name"] == "AI 综述工具数据抽取"

    listed = client.get("/api/structured-extraction/tasks", headers={"X-User-Id": "alice"})
    assert listed.status_code == 200
    assert [row["task_id"] for row in listed.json()["tasks"]] == [task["task_id"]]

    bob_get = client.get(f"/api/structured-extraction/tasks/{task['task_id']}", headers={"X-User-Id": "bob"})
    assert bob_get.status_code == 404

    updated = client.patch(
        f"/api/structured-extraction/tasks/{task['task_id']}",
        json={"name": "updated", "description": "changed", "model_settings": {"extraction_profile_id": "cheap-json"}},
        headers={"X-User-Id": "alice"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "updated"
    assert updated.json()["model_settings"] == {"extraction_profile_id": "cheap-json"}

    archived = client.post(
        f"/api/structured-extraction/tasks/{task['task_id']}/archive",
        json={"archived": True},
        headers={"X-User-Id": "alice"},
    )
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get("/api/structured-extraction/tasks", headers={"X-User-Id": "alice"}).json()["tasks"] == []
    with_archived = client.get(
        "/api/structured-extraction/tasks?include_archived=true",
        headers={"X-User-Id": "alice"},
    ).json()["tasks"]
    assert [row["task_id"] for row in with_archived] == [task["task_id"]]

    duplicated = client.post(
        f"/api/structured-extraction/tasks/{task['task_id']}/duplicate",
        json={"name": "copy", "copy_model_settings": True},
        headers={"X-User-Id": "alice"},
    )
    assert duplicated.status_code == 200
    copy = duplicated.json()
    assert copy["task_id"] != task["task_id"]
    assert copy["name"] == "copy"
    assert copy["model_settings"] == {"extraction_profile_id": "cheap-json"}
    assert copy["stats"] == {"paper_count": 0, "field_count": 0, "run_count": 0, "export_count": 0}

    deleted = client.delete(f"/api/structured-extraction/tasks/{copy['task_id']}", headers={"X-User-Id": "alice"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    remaining = client.get(
        "/api/structured-extraction/tasks?include_archived=true",
        headers={"X-User-Id": "alice"},
    ).json()["tasks"]
    assert [row["task_id"] for row in remaining] == [task["task_id"]]
