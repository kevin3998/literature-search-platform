from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient


def _make_index(data_dir: Path) -> Path:
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
            "p_membrane_1",
            1,
            "10.1000/mem1",
            "Antifouling membrane with zwitterionic coating",
            json.dumps(["Alice", "Bob"]),
            "Journal of Membrane Science",
            2024,
            "elsevier",
            "articles/1",
            "articles/1/fulltext.md",
            "articles/1/abstract.md",
            1.0,
            2.0,
            3,
            json.dumps({"abstract": "zwitterionic membrane antifouling flux rejection", "keywords": ["membrane", "antifouling"]}),
        ),
        (
            "p_membrane_2",
            2,
            "10.1000/mem2",
            "Graphene oxide mixed matrix membrane for water purification",
            json.dumps(["Chen"]),
            "Water Research",
            2022,
            "elsevier",
            "articles/2",
            "articles/2/fulltext.md",
            "articles/2/abstract.md",
            1.0,
            2.0,
            3,
            json.dumps({"abstract": "membrane antifouling water purification performance"}),
        ),
        (
            "p_dup_a",
            3,
            "10.1000/dup",
            "Duplicate membrane study",
            json.dumps(["Dora"]),
            "Materials Today",
            2023,
            "springer",
            "articles/3",
            "articles/3/fulltext.md",
            "articles/3/abstract.md",
            1.0,
            2.0,
            3,
            json.dumps({"abstract": "membrane antifouling duplicate"}),
        ),
        (
            "p_dup_b",
            4,
            "10.1000/dup",
            "Duplicate membrane study",
            json.dumps(["Dora"]),
            "Materials Today",
            2023,
            "springer",
            "articles/4",
            "articles/4/fulltext.md",
            "articles/4/abstract.md",
            1.0,
            2.0,
            3,
            json.dumps({"abstract": "membrane antifouling duplicate preprint"}),
        ),
        (
            "p_no_year",
            5,
            "10.1000/noyear",
            "Metadata row without a valid year",
            json.dumps(["No Year"]),
            "",
            "unknown",
            "",
            "articles/5",
            "articles/5/fulltext.md",
            "articles/5/abstract.md",
            1.0,
            2.0,
            3,
            json.dumps({"abstract": "metadata hygiene membrane row"}),
        ),
    ]
    conn.executemany("insert into papers values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return index_path


def test_collection_builder_metadata_search_decisions_and_freeze(monkeypatch, tmp_path):
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
        json={"name": "膜材料收集"},
        headers={"X-User-Id": "alice"},
    ).json()
    task_id = task["task_id"]

    options = client.get(
        f"/api/structured-extraction/tasks/{task_id}/collection/filter-options",
        headers={"X-User-Id": "alice"},
    )
    assert options.status_code == 200
    assert options.json()["years"] == [2022, 2023, 2024]
    assert options.json()["journals"] == ["Journal of Membrane Science", "Materials Today", "Water Research"]
    assert options.json()["sites"] == ["elsevier", "springer"]

    search = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/search",
        json={"query": "membrane antifouling", "year_from": 2022, "year_to": 2024, "limit": 10},
        headers={"X-User-Id": "alice"},
    )
    assert search.status_code == 200
    body = search.json()
    assert body["created"] == 4
    assert body["total_candidates"] == 4
    candidates = body["candidates"]
    assert {c["paper_id"] for c in candidates} == {"p_membrane_1", "p_membrane_2", "p_dup_a", "p_dup_b"}
    assert all(c["user_decision"] == "candidate" for c in candidates)
    assert any(c["duplicate_group_id"] and c["canonical_paper_id"] == "p_dup_a" for c in candidates)

    second = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/search",
        json={"query": "membrane antifouling", "year_from": 2022, "year_to": 2024, "limit": 10},
        headers={"X-User-Id": "alice"},
    ).json()
    assert second["created"] == 0
    assert second["total_candidates"] == 4

    listed = client.get(f"/api/structured-extraction/tasks/{task_id}/collection/candidates", headers={"X-User-Id": "alice"}).json()
    first_id = listed["candidates"][0]["candidate_id"]
    second_id = listed["candidates"][1]["candidate_id"]
    excluded_id = listed["candidates"][2]["candidate_id"]

    decision = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/{excluded_id}/decision",
        json={"decision": "exclude", "exclude_reason": "duplicate"},
        headers={"X-User-Id": "alice"},
    )
    assert decision.status_code == 200
    assert decision.json()["user_decision"] == "exclude"
    assert decision.json()["exclude_reason"] == "duplicate"

    bulk = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/bulk-decision",
        json={"candidate_ids": [first_id, second_id], "decision": "include"},
        headers={"X-User-Id": "alice"},
    )
    assert bulk.status_code == 200
    assert bulk.json()["updated"] == 2

    bob_list = client.get(f"/api/structured-extraction/tasks/{task_id}/collection/candidates", headers={"X-User-Id": "bob"})
    assert bob_list.status_code == 404

    freeze = client.post(f"/api/structured-extraction/tasks/{task_id}/collection/freeze", headers={"X-User-Id": "alice"})
    assert freeze.status_code == 200
    frozen = freeze.json()
    assert frozen["collection_version"] == "col_v1"
    assert frozen["paper_count"] == 2
    assert [paper["candidate_id"] for paper in frozen["included_papers"]] == [first_id, second_id]

    task_after = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    assert task_after["status"] == "collection_ready"
    assert task_after["current_collection_version"] == "col_v1"
    assert task_after["stats"]["paper_count"] == 2

    workspace = tmp_path / "users" / task_after["user_id"] / task_after["workspace_rel_path"] / "collection"
    assert (workspace / "candidates.jsonl").exists()
    assert (workspace / "candidate_decisions.jsonl").exists()
    assert json.loads((workspace / "collection_v1.json").read_text(encoding="utf-8"))["paper_count"] == 2
    assert len((workspace / "paper_refs_v1.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 2

    client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/{first_id}/decision",
        json={"decision": "exclude", "exclude_reason": "other"},
        headers={"X-User-Id": "alice"},
    )
    version = client.get(
        f"/api/structured-extraction/tasks/{task_id}/collection/versions/col_v1",
        headers={"X-User-Id": "alice"},
    ).json()
    assert [paper["candidate_id"] for paper in version["included_papers"]] == [first_id, second_id]

    expansion = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/question-expansion",
        json={"question": "membrane antifouling", "limit": 5},
        headers={"X-User-Id": "alice"},
    )
    assert expansion.status_code == 200
    assert expansion.json()["available"] is False
    assert expansion.json()["reason"] == "llm_unavailable"

    dirty_task = client.post(
        "/api/structured-extraction/tasks",
        json={"name": "脏年份检索"},
        headers={"X-User-Id": "alice"},
    ).json()
    dirty_search = client.post(
        f"/api/structured-extraction/tasks/{dirty_task['task_id']}/collection/search",
        json={"query": "metadata hygiene membrane", "limit": 10},
        headers={"X-User-Id": "alice"},
    )
    assert dirty_search.status_code == 200
    assert any(candidate["paper_id"] == "p_no_year" for candidate in dirty_search.json()["candidates"])

    unlimited_task = client.post(
        "/api/structured-extraction/tasks",
        json={"name": "无限制检索"},
        headers={"X-User-Id": "alice"},
    ).json()
    limited_search = client.post(
        f"/api/structured-extraction/tasks/{unlimited_task['task_id']}/collection/search",
        json={"query": "membrane", "limit": 1},
        headers={"X-User-Id": "alice"},
    )
    assert len(limited_search.json()["candidates"]) == 1
    unlimited_search = client.post(
        f"/api/structured-extraction/tasks/{unlimited_task['task_id']}/collection/search",
        json={"query": "membrane", "limit": 0},
        headers={"X-User-Id": "alice"},
    )
    assert unlimited_search.status_code == 200
    assert unlimited_search.json()["total_candidates"] == 5
    assert len(unlimited_search.json()["candidates"]) == 5
    unlimited_list = client.get(
        f"/api/structured-extraction/tasks/{unlimited_task['task_id']}/collection/candidates?limit=0",
        headers={"X-User-Id": "alice"},
    )
    assert len(unlimited_list.json()["candidates"]) == 5
