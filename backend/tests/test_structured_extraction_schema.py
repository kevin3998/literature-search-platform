from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient


def _make_index(data_dir: Path) -> None:
    index_path = data_dir / "research_agent" / "research_index.sqlite"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_path)
    conn.execute(
        """
        create table papers (
            paper_id text primary key,
            article_id integer,
            doi text,
            title text,
            authors_json text,
            journal text,
            year integer,
            site text,
            article_dir text,
            md_path text,
            abstract_path text,
            indexed_at real,
            mtime real,
            index_version integer,
            metadata_json text
        )
        """
    )
    rows = [
        (
            "p_schema_1",
            1,
            "10.1000/schema1",
            "Antifouling membrane sample study",
            json.dumps(["Alice"]),
            "Journal of Membrane Science",
            2024,
            "elsevier",
            "articles/1",
            "articles/1/fulltext.md",
            "articles/1/abstract.md",
            1.0,
            2.0,
            3,
            json.dumps({"abstract": "membrane antifouling sample flux rejection"}),
        ),
        (
            "p_schema_2",
            2,
            "10.1000/schema2",
            "Graphene membrane performance",
            json.dumps(["Bob"]),
            "Water Research",
            2023,
            "elsevier",
            "articles/2",
            "articles/2/fulltext.md",
            "articles/2/abstract.md",
            1.0,
            2.0,
            3,
            json.dumps({"abstract": "membrane sample water flux"}),
        ),
    ]
    conn.executemany("insert into papers values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _schema_payload(field_key: str = "membrane_name") -> dict:
    return {
        "record_schema": {
            "record_type": "membrane_sample",
            "record_unit": "sample_level",
            "primary_entity": "membrane",
            "one_paper_may_have_multiple_records": True,
            "record_identity_fields": ["paper_id", field_key],
            "deduplication_keys": ["paper_id", field_key],
            "parent_record_type": None,
        },
        "field_groups": [
            {"group_key": "material_identity", "label": "材料身份", "description": "", "order": 1},
        ],
        "fields": [
            {
                "key": field_key,
                "label": "膜名称",
                "type": "string",
                "group_key": "material_identity",
                "description": "膜材料或样品名称",
                "extraction_instruction": "Extract the membrane or sample name exactly as reported.",
                "required": True,
                "missing_policy": "missing",
                "evidence_required": True,
                "allowed_values": [],
                "unit": "",
                "validation_rule": "",
                "example_values": ["PES-ZW"],
                "notes": "",
                "order": 1,
            }
        ],
    }


def _client_with_collection(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
    data_dir = tmp_path / "literature_data"
    _make_index(data_dir)
    monkeypatch.setenv("LITERATURE_DATA_DIR", str(data_dir))

    import main
    from modules.literature_search import literature_search_shared

    literature_search_shared.service.data_dir = data_dir
    client = TestClient(main.app)
    task = client.post(
        "/api/structured-extraction/tasks",
        json={"name": "Schema task"},
        headers={"X-User-Id": "alice"},
    ).json()
    task_id = task["task_id"]

    no_collection = client.put(
        f"/api/structured-extraction/tasks/{task_id}/schema/draft",
        json=_schema_payload(),
        headers={"X-User-Id": "alice"},
    )
    assert no_collection.status_code == 400
    assert "collection_required" in no_collection.json()["detail"]

    search = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/search",
        json={"query": "membrane", "limit": 10},
        headers={"X-User-Id": "alice"},
    ).json()
    candidate_ids = [item["candidate_id"] for item in search["candidates"][:2]]
    client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/bulk-decision",
        json={"candidate_ids": candidate_ids, "decision": "include"},
        headers={"X-User-Id": "alice"},
    )
    freeze = client.post(f"/api/structured-extraction/tasks/{task_id}/collection/freeze", headers={"X-User-Id": "alice"})
    assert freeze.status_code == 200
    return client, task_id, tmp_path


def test_schema_designer_draft_validation_freeze_and_versioning(monkeypatch, tmp_path):
    client, task_id, root = _client_with_collection(monkeypatch, tmp_path)

    invalid = _schema_payload()
    invalid["fields"].append({**invalid["fields"][0], "label": "Duplicate"})
    rejected = client.put(
        f"/api/structured-extraction/tasks/{task_id}/schema/draft",
        json=invalid,
        headers={"X-User-Id": "alice"},
    )
    assert rejected.status_code == 400
    assert "duplicate_field_key" in rejected.json()["detail"]

    saved = client.put(
        f"/api/structured-extraction/tasks/{task_id}/schema/draft",
        json=_schema_payload(),
        headers={"X-User-Id": "alice"},
    )
    assert saved.status_code == 200
    draft = saved.json()
    assert draft["schema_version"] is None
    assert draft["base_collection_version"] == "col_v1"
    assert draft["record_schema"]["record_unit"] == "sample_level"
    assert draft["fields"][0]["key"] == "membrane_name"
    assert draft["validation_errors"] == []

    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    workspace = root / "users" / task["user_id"] / task["workspace_rel_path"] / "schemas"
    assert json.loads((workspace / "draft.json").read_text(encoding="utf-8"))["fields"][0]["key"] == "membrane_name"

    listed_draft = client.get(f"/api/structured-extraction/tasks/{task_id}/schema/draft", headers={"X-User-Id": "alice"})
    assert listed_draft.status_code == 200
    assert listed_draft.json()["fields"][0]["key"] == "membrane_name"

    assist = client.post(
        f"/api/structured-extraction/tasks/{task_id}/schema/assist",
        json={"action": "suggest_fields", "instruction": "Suggest membrane fields", "draft": draft},
        headers={"X-User-Id": "alice"},
    )
    assert assist.status_code == 200
    assert assist.json()["available"] is False
    assert assist.json()["reason"] == "llm_unavailable"

    frozen = client.post(f"/api/structured-extraction/tasks/{task_id}/schema/freeze", headers={"X-User-Id": "alice"})
    assert frozen.status_code == 200
    version = frozen.json()
    assert version["schema_version"] == "schema_v1"
    assert version["field_count"] == 1
    assert version["fields"][0]["key"] == "membrane_name"

    task_after = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    assert task_after["status"] == "schema_ready"
    assert task_after["current_schema_version"] == "schema_v1"
    assert task_after["stats"]["field_count"] == 1
    assert json.loads((workspace / "schema_v1.json").read_text(encoding="utf-8"))["schema_version"] == "schema_v1"
    assert (workspace / "schema_v1_fields.jsonl").read_text(encoding="utf-8").strip()
    assert (workspace / "schema_events.jsonl").exists()

    changed = _schema_payload("support_layer")
    changed["fields"][0]["label"] = "支撑层"
    assert client.put(
        f"/api/structured-extraction/tasks/{task_id}/schema/draft",
        json=changed,
        headers={"X-User-Id": "alice"},
    ).status_code == 200

    immutable = client.get(
        f"/api/structured-extraction/tasks/{task_id}/schema/versions/schema_v1",
        headers={"X-User-Id": "alice"},
    ).json()
    assert immutable["fields"][0]["key"] == "membrane_name"

    copied = client.post(
        f"/api/structured-extraction/tasks/{task_id}/schema/versions/schema_v1/duplicate-to-draft",
        headers={"X-User-Id": "alice"},
    )
    assert copied.status_code == 200
    assert copied.json()["fields"][0]["key"] == "membrane_name"

    versions = client.get(f"/api/structured-extraction/tasks/{task_id}/schema/versions", headers={"X-User-Id": "alice"}).json()
    assert [item["schema_version"] for item in versions["versions"]] == ["schema_v1"]

    bob = client.get(f"/api/structured-extraction/tasks/{task_id}/schema/draft", headers={"X-User-Id": "bob"})
    assert bob.status_code == 404


def test_schema_rejects_material_level_without_material_identity(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_collection(monkeypatch, tmp_path)

    invalid = _schema_payload()
    invalid["record_schema"] = {
        "record_type": "paper_record",
        "record_unit": "material_level",
        "primary_entity": "paper",
        "one_paper_may_have_multiple_records": True,
        "record_identity_fields": ["paper_id"],
        "deduplication_keys": ["paper_id"],
        "parent_record_type": None,
    }
    rejected = client.put(
        f"/api/structured-extraction/tasks/{task_id}/schema/draft",
        json=invalid,
        headers={"X-User-Id": "alice"},
    )
    assert rejected.status_code == 400
    detail = rejected.json()["detail"]
    assert "record_identity_requires_non_paper_key" in detail
    assert "deduplication_requires_non_paper_key" in detail
    assert "primary_entity_conflicts_with_record_unit" in detail

    valid = _schema_payload("material_name")
    valid["record_schema"] = {
        "record_type": "material_record",
        "record_unit": "material_level",
        "primary_entity": "material",
        "one_paper_may_have_multiple_records": True,
        "record_identity_fields": ["paper_id", "material_name"],
        "deduplication_keys": ["paper_id", "material_name"],
        "parent_record_type": None,
    }
    accepted = client.put(
        f"/api/structured-extraction/tasks/{task_id}/schema/draft",
        json=valid,
        headers={"X-User-Id": "alice"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["record_schema"]["record_identity_fields"] == ["paper_id", "material_name"]
