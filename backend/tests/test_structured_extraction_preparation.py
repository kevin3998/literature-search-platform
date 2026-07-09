from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient


def _make_index(data_dir: Path) -> None:
    index_path = data_dir / "research_agent" / "research_index.sqlite"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_path)
    conn.executescript(
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
        );
        create table documents (
            id integer primary key,
            paper_id text,
            article_id integer,
            kind text,
            section text,
            heading_norm text,
            section_id text,
            chunk_index integer,
            source_path text,
            text text
        );
        create table paper_assets (
            paper_id text,
            kind text,
            source_path text,
            label text,
            caption text
        );
        """
    )
    papers = [
        (
            "p_prep_1",
            1,
            "10.1000/prep1",
            "Antifouling membrane performance",
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
            json.dumps({"abstract": "membrane sample water flux rejection"}),
        ),
        (
            "p_prep_2",
            2,
            "10.1000/prep2",
            "Graphene membrane sample",
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
            json.dumps({"abstract": "graphene membrane name support layer"}),
        ),
    ]
    documents = [
        (101, "p_prep_1", 1, "section_chunk", "Results", "results", "s1", 0, "articles/1/fulltext.md", "The PES-ZW membrane sample reached water flux of 120 LMH and rejection rate of 98%."),
        (102, "p_prep_1", 1, "section_chunk", "Methods", "methods", "s2", 0, "articles/1/fulltext.md", "The membrane name PES-ZW was prepared by coating a support layer."),
        (201, "p_prep_2", 2, "section_chunk", "Results", "results", "s1", 0, "articles/2/fulltext.md", "The GO membrane sample reported water flux around 80 LMH."),
    ]
    assets = [
        ("p_prep_1", "figure", "articles/1/figures/fig1.png", "Figure 1", "Flux and rejection comparison."),
        ("p_prep_1", "table", "articles/1/tables/table1.csv", "Table 1", "Membrane performance table."),
    ]
    conn.executemany("insert into papers values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", papers)
    conn.executemany("insert into documents values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", documents)
    conn.executemany("insert into paper_assets values(?, ?, ?, ?, ?)", assets)
    conn.commit()
    conn.close()


def _schema_payload() -> dict:
    return {
        "record_schema": {
            "record_type": "membrane_sample",
            "record_unit": "sample_level",
            "primary_entity": "membrane",
            "one_paper_may_have_multiple_records": True,
            "record_identity_fields": ["paper_id", "membrane_name"],
            "deduplication_keys": ["paper_id", "membrane_name"],
            "parent_record_type": None,
        },
        "field_groups": [
            {"group_key": "material_identity", "label": "材料身份", "description": "membrane sample identity", "order": 1},
            {"group_key": "performance", "label": "性能", "description": "water flux and rejection rate", "order": 2},
        ],
        "fields": [
            {
                "key": "membrane_name",
                "label": "膜名称",
                "type": "string",
                "group_key": "material_identity",
                "description": "membrane sample name",
                "extraction_instruction": "Extract exact membrane name.",
                "required": True,
                "missing_policy": "missing",
                "evidence_required": True,
                "allowed_values": [],
                "unit": "",
                "validation_rule": "",
                "example_values": ["PES-ZW"],
                "notes": "",
                "order": 1,
            },
            {
                "key": "water_flux",
                "label": "Water flux",
                "type": "number",
                "group_key": "performance",
                "description": "membrane water flux",
                "extraction_instruction": "Extract water flux and unit.",
                "required": False,
                "missing_policy": "missing",
                "evidence_required": True,
                "allowed_values": [],
                "unit": "LMH",
                "validation_rule": "",
                "example_values": ["120"],
                "notes": "",
                "order": 2,
            },
        ],
    }


def _client_with_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
    data_dir = tmp_path / "literature_data"
    _make_index(data_dir)
    monkeypatch.setenv("LITERATURE_DATA_DIR", str(data_dir))

    import main
    from modules.literature_search import literature_search_shared

    literature_search_shared.service.data_dir = data_dir
    client = TestClient(main.app)
    task = client.post("/api/structured-extraction/tasks", json={"name": "Preparation task"}, headers={"X-User-Id": "alice"}).json()
    task_id = task["task_id"]

    premature = client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers={"X-User-Id": "alice"})
    assert premature.status_code == 400
    assert "collection_version_required" in premature.json()["detail"]

    search = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/search",
        json={"query": "membrane", "limit": 10},
        headers={"X-User-Id": "alice"},
    ).json()
    candidate_ids = [item["candidate_id"] for item in search["candidates"]]
    client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/bulk-decision",
        json={"candidate_ids": candidate_ids, "decision": "include"},
        headers={"X-User-Id": "alice"},
    )
    client.post(f"/api/structured-extraction/tasks/{task_id}/collection/freeze", headers={"X-User-Id": "alice"})
    client.put(f"/api/structured-extraction/tasks/{task_id}/schema/draft", json=_schema_payload(), headers={"X-User-Id": "alice"})
    schema = client.post(f"/api/structured-extraction/tasks/{task_id}/schema/freeze", headers={"X-User-Id": "alice"}).json()
    assert schema["schema_version"] == "schema_v1"
    return client, task_id, tmp_path


def test_prompt_contract_and_evidence_packet_preparation(monkeypatch, tmp_path):
    client, task_id, root = _client_with_schema(monkeypatch, tmp_path)

    no_contract_packet = client.post(f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build", headers={"X-User-Id": "alice"})
    assert no_contract_packet.status_code == 400
    assert "prompt_contract_required" in no_contract_packet.json()["detail"]

    compiled = client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers={"X-User-Id": "alice"})
    assert compiled.status_code == 200
    contract = compiled.json()
    assert contract["prompt_contract_version"] == "pc_v1"
    assert contract["schema_version"] == "schema_v1"
    assert contract["collection_version"] == "col_v1"
    assert contract["record_contract"]["record_unit"] == "sample_level"
    assert [field["key"] for field in contract["field_contracts"]] == ["membrane_name", "water_flux"]
    assert contract["field_contracts"][1]["evidence_required"] is True
    assert contract["output_json_contract"]["record_unit"] == "sample_level"
    assert any("Do not guess" in rule for rule in contract["extraction_rules"])

    contract_list = client.get(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/versions", headers={"X-User-Id": "alice"}).json()
    assert [item["prompt_contract_version"] for item in contract_list["versions"]] == ["pc_v1"]

    built = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build",
        json={"max_chunks_per_group": 2, "max_chars_per_chunk": 120, "include_assets": True},
        headers={"X-User-Id": "alice"},
    )
    assert built.status_code == 200
    packet = built.json()
    assert packet["packet_version"] == "ep_v1"
    assert packet["prompt_contract_version"] == "pc_v1"
    assert packet["paper_count"] == 2
    assert packet["field_group_count"] == 2
    assert packet["item_count"] == 4

    items = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions/ep_v1/items",
        headers={"X-User-Id": "alice"},
    ).json()["items"]
    assert len(items) == 4
    perf_item = next(item for item in items if item["paper_id"] == "p_prep_1" and item["field_group"] == "performance")
    assert perf_item["field_keys"] == ["water_flux"]
    assert perf_item["chunks"]
    assert perf_item["chunks"][0]["evidence_id"] == "E101"
    assert perf_item["chunks"][0]["text"].startswith("The PES-ZW")
    assert len(perf_item["chunks"][0]["text"]) <= 120
    assert perf_item["figures"] or perf_item["tables"]

    version = client.get(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions/ep_v1",
        headers={"X-User-Id": "alice"},
    ).json()
    assert version["item_count"] == 4

    immutable_contract = client.get(
        f"/api/structured-extraction/tasks/{task_id}/prompt-contract/versions/pc_v1",
        headers={"X-User-Id": "alice"},
    ).json()
    assert immutable_contract["field_contracts"][0]["key"] == "membrane_name"

    task_after = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    assert task_after["status"] == "schema_ready"
    workspace = root / "users" / task_after["user_id"] / task_after["workspace_rel_path"]
    assert json.loads((workspace / "prompts" / "prompt_contract_pc_v1.json").read_text(encoding="utf-8"))["prompt_contract_version"] == "pc_v1"
    assert json.loads((workspace / "prompts" / "output_contract_pc_v1.json").read_text(encoding="utf-8"))["record_unit"] == "sample_level"
    assert json.loads((workspace / "evidence_packets" / "packet_ep_v1.json").read_text(encoding="utf-8"))["packet_version"] == "ep_v1"
    assert len((workspace / "evidence_packets" / "packet_ep_v1_items.jsonl").read_text(encoding="utf-8").strip().splitlines()) == 4
    assert (workspace / "evidence_packets" / "packet_ep_v1_warnings.jsonl").exists()

    bob = client.get(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/versions", headers={"X-User-Id": "bob"})
    assert bob.status_code == 404
