from __future__ import annotations

import importlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from postgres_test_utils import migrated_postgres_schema

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _reload_runtime_modules():
    for name in list(sys.modules):
        if name == "main" or name.startswith("api.structured_extraction_router") or name.startswith("modules.structured_extraction"):
            sys.modules.pop(name, None)
            if "." in name:
                package_name, attribute = name.rsplit(".", 1)
                package = sys.modules.get(package_name)
                if package is not None and hasattr(package, attribute):
                    delattr(package, attribute)
    modules = [
        "main",
        "api.structured_extraction_router",
        "modules.structured_extraction.shared",
        "modules.structured_extraction.store",
        "core.user_store",
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


def _run_worker_once(modules, *, queues: list[str] | None = None, max_jobs: int = 10) -> int:
    from core.worker.queue import JobQueue
    from core.worker.registry import build_handler_registry
    from core.worker.runtime import WorkerRuntime

    engine = modules["main"].postgres_engine
    runtime = WorkerRuntime(
        JobQueue(engine),
        build_handler_registry(engine=engine),
        worker_id="test-worker",
        queues=queues or ["structured-extraction"],
        max_jobs_per_tick=max_jobs,
    )
    return runtime.run_once()


def test_structured_extraction_tasks_use_postgres_uuid_ids_and_user_boundaries():
    with migrated_postgres_schema() as (url, schema):
        modules = _reload_runtime_modules()
        client = TestClient(modules["main"].app)

        alice = client.post(
            "/api/structured-extraction/tasks",
            headers={"X-User-Id": "alice"},
            json={"name": "Alice extraction", "description": "pg"},
        )
        bob = client.post(
            "/api/structured-extraction/tasks",
            headers={"X-User-Id": "bob"},
            json={"name": "Bob extraction"},
        )
        alice_body = alice.json()
        bob_body = bob.json()
        bob_get_alice = client.get(
            f"/api/structured-extraction/tasks/{alice_body['task_id']}",
            headers={"X-User-Id": "bob"},
        )
        alice_list = client.get("/api/structured-extraction/tasks", headers={"X-User-Id": "alice"}).json()["tasks"]
        bob_list = client.get("/api/structured-extraction/tasks", headers={"X-User-Id": "bob"}).json()["tasks"]

        engine = create_engine(url, future=True)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(f'select task_id, user_id from "{schema}".structured_extraction_tasks order by name')
                ).all()
                public_rows = conn.execute(
                    text(
                        """
                        select count(*)
                        from information_schema.tables
                        where table_schema = 'public'
                          and table_name = 'structured_extraction_tasks'
                        """
                    )
                ).scalar_one()
        finally:
            engine.dispose()

    assert alice.status_code == 200
    assert bob.status_code == 200
    assert UUID_RE.match(alice_body["task_id"])
    assert UUID_RE.match(bob_body["task_id"])
    assert UUID_RE.match(alice_body["user_id"])
    assert alice_body["user_id"] != "alice"
    assert [item["task_id"] for item in alice_list] == [alice_body["task_id"]]
    assert [item["task_id"] for item in bob_list] == [bob_body["task_id"]]
    assert bob_get_alice.status_code == 404
    assert len(rows) == 2
    assert public_rows == 0


def test_collection_schema_prompt_and_evidence_packets_use_postgres_uuid_entities(monkeypatch, tmp_path):
    with migrated_postgres_schema() as (url, schema):
        monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
        data_dir = tmp_path / "literature_data"
        _make_index(data_dir)
        monkeypatch.setenv("LITERATURE_DATA_DIR", str(data_dir))
        modules = _reload_runtime_modules()
        from modules.literature_search import literature_search_shared

        literature_search_shared.service.data_dir = data_dir
        client = TestClient(modules["main"].app)

        task = client.post(
            "/api/structured-extraction/tasks",
            headers={"X-User-Id": "alice"},
            json={"name": "Preparation task"},
        )
        assert task.status_code == 200, task.text
        task = task.json()
        task_id = task["task_id"]
        assert UUID_RE.match(task_id)
        assert UUID_RE.match(task["user_id"])
        assert (tmp_path / "users" / task["user_id"] / task["workspace_rel_path"] / "task.json").exists()
        assert not (tmp_path / "users" / "alice").exists()

        search = client.post(
            f"/api/structured-extraction/tasks/{task_id}/collection/search",
            headers={"X-User-Id": "alice"},
            json={"query": "membrane", "limit": 10},
        )
        assert search.status_code == 200, search.text
        candidates = search.json()["candidates"]
        assert len(candidates) == 2
        assert all(UUID_RE.match(item["candidate_id"]) for item in candidates)

        bulk = client.post(
            f"/api/structured-extraction/tasks/{task_id}/collection/candidates/bulk-decision",
            headers={"X-User-Id": "alice"},
            json={"candidate_ids": [item["candidate_id"] for item in candidates], "decision": "include"},
        )
        assert bulk.status_code == 200, bulk.text

        frozen_collection = client.post(
            f"/api/structured-extraction/tasks/{task_id}/collection/freeze",
            headers={"X-User-Id": "alice"},
        )
        assert frozen_collection.status_code == 200, frozen_collection.text
        assert frozen_collection.json()["collection_version"] == "col_v1"

        saved_schema = client.put(
            f"/api/structured-extraction/tasks/{task_id}/schema/draft",
            headers={"X-User-Id": "alice"},
            json=_schema_payload(),
        )
        assert saved_schema.status_code == 200, saved_schema.text
        frozen_schema = client.post(
            f"/api/structured-extraction/tasks/{task_id}/schema/freeze",
            headers={"X-User-Id": "alice"},
        )
        assert frozen_schema.status_code == 200, frozen_schema.text
        assert frozen_schema.json()["schema_version"] == "schema_v1"

        compiled = client.post(
            f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile",
            headers={"X-User-Id": "alice"},
        )
        assert compiled.status_code == 200, compiled.text
        assert compiled.json()["prompt_contract_version"] == "pc_v1"

        packet = client.post(
            f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build",
            headers={"X-User-Id": "alice"},
            json={"max_chunks_per_group": 1, "max_chars_per_chunk": 160, "include_assets": True},
        )
        assert packet.status_code == 200, packet.text
        assert packet.json()["packet_version"] == "ep_v1"

        items = client.get(
            f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions/ep_v1/items",
            headers={"X-User-Id": "alice"},
        ).json()["items"]
        assert len(items) == 4
        assert all(UUID_RE.match(item["packet_item_id"]) for item in items)

        bob_packet = client.get(
            f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions/ep_v1",
            headers={"X-User-Id": "bob"},
        )
        assert bob_packet.status_code == 404

        engine = create_engine(url, future=True)
        try:
            with engine.connect() as conn:
                candidate_type = conn.execute(
                    text(
                        """
                        select data_type, udt_name
                        from information_schema.columns
                        where table_schema = :schema
                          and table_name = 'structured_extraction_candidates'
                          and column_name = 'candidate_id'
                        """
                    ),
                    {"schema": schema},
                ).mappings().one()
                schema_user_id = conn.execute(
                    text(f'select user_id from "{schema}".structured_extraction_schema_versions where task_id = :task_id'),
                    {"task_id": task_id},
                ).scalar_one()
        finally:
            engine.dispose()

    assert candidate_type["udt_name"] == "uuid"
    assert str(schema_user_id) == task["user_id"]


def test_extraction_run_review_and_export_use_postgres_uuid_entities(monkeypatch, tmp_path):
    with migrated_postgres_schema() as (url, schema):
        monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
        data_dir = tmp_path / "literature_data"
        _make_index(data_dir)
        monkeypatch.setenv("LITERATURE_DATA_DIR", str(data_dir))
        modules = _reload_runtime_modules()
        from modules.literature_search import literature_search_shared
        import modules.structured_extraction.llm_extraction as llm_extraction

        literature_search_shared.service.data_dir = data_dir
        fake_llm = _FakeLLM(
            [
                _record_json(
                    "p_prep_1",
                    "PES-ZW",
                    {
                        "membrane_name": {
                            "raw_value": "PES-ZW",
                            "normalized_value": "PES-ZW",
                            "evidence_text": "The membrane name PES-ZW was prepared",
                            "evidence_location": "Methods",
                        }
                    },
                ),
                _record_json(
                    "p_prep_1",
                    "PES-ZW",
                    {
                        "water_flux": {
                            "raw_value": "120 LMH",
                            "normalized_value": 120,
                            "unit": "LMH",
                            "evidence_text": "water flux of 120 LMH",
                            "evidence_location": "Results",
                        }
                    },
                ),
                '{"records":[]}',
                '{"records":[]}',
            ]
        )
        monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False, user_id=None: fake_llm)
        client = TestClient(modules["main"].app)
        task = _prepare_ready_task(client)
        task_id = task["task_id"]

        started = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"})
        assert started.status_code == 200, started.text
        run = started.json()
        assert UUID_RE.match(run["run_id"])
        _run_worker_once(modules)
        final = _wait_for_terminal(client, task_id, run["run_id"])
        assert final["status"] == "completed"
        assert final["stats"]["record_count"] == 1

        items = client.get(
            f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/items",
            headers={"X-User-Id": "alice"},
        ).json()["items"]
        records = client.get(
            f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/records",
            headers={"X-User-Id": "alice"},
        ).json()["records"]
        assert all(UUID_RE.match(item["run_item_id"]) for item in items)
        assert all(UUID_RE.match(record["record_id"]) for record in records)
        record_id = records[0]["record_id"]

        accepted = client.post(
            f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/membrane_name/accept",
            headers={"X-User-Id": "alice"},
            json={"reason": "checked"},
        )
        assert accepted.status_code == 200, accepted.text
        events = client.get(
            f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/events",
            headers={"X-User-Id": "alice"},
        ).json()["events"]
        assert events[-1]["event_type"] == "accept_field"
        assert isinstance(events[-1]["event_id"], int)

        exported = client.post(
            f"/api/structured-extraction/tasks/{task_id}/exports",
            headers={"X-User-Id": "alice"},
            json={"formats": ["json", "csv"]},
        )
        assert exported.status_code == 200, exported.text
        export = exported.json()
        assert UUID_RE.match(export["export_id"])
        assert export["record_count"] == 1
        assert (tmp_path / "users" / task["user_id"] / task["workspace_rel_path"] / "exports" / export["export_id"]).exists()

        bob_run = client.get(
            f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}",
            headers={"X-User-Id": "bob"},
        )
        assert bob_run.status_code == 404

        engine = create_engine(url, future=True)
        try:
            with engine.connect() as conn:
                ids = conn.execute(
                    text(
                        f"""
                        select r.run_id, i.run_item_id, rec.record_id, e.export_id
                        from "{schema}".structured_extraction_runs r
                        join "{schema}".structured_extraction_run_items i on i.run_id = r.run_id
                        join "{schema}".structured_extraction_records rec on rec.run_id = r.run_id
                        join "{schema}".structured_extraction_exports e on e.run_id = r.run_id
                        where r.task_id = :task_id
                        limit 1
                        """
                    ),
                    {"task_id": task_id},
                ).mappings().one()
        finally:
            engine.dispose()

    assert UUID_RE.match(str(ids["run_id"]))
    assert UUID_RE.match(str(ids["run_item_id"]))
    assert UUID_RE.match(str(ids["record_id"]))
    assert UUID_RE.match(str(ids["export_id"]))


class _FakeLLM:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.user_ids: list[str | None] = []

    async def stream_chat(self, messages, tools=None):
        text = self.outputs.pop(0) if self.outputs else '{"records":[]}'
        yield {"type": "content", "text": text}


def _prepare_ready_task(client: TestClient) -> dict:
    task = client.post(
        "/api/structured-extraction/tasks",
        headers={"X-User-Id": "alice"},
        json={"name": "Run task"},
    ).json()
    task_id = task["task_id"]
    search = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/search",
        headers={"X-User-Id": "alice"},
        json={"query": "membrane", "limit": 10},
    ).json()
    candidate_ids = [item["candidate_id"] for item in search["candidates"]]
    client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/bulk-decision",
        headers={"X-User-Id": "alice"},
        json={"candidate_ids": candidate_ids, "decision": "include"},
    )
    client.post(f"/api/structured-extraction/tasks/{task_id}/collection/freeze", headers={"X-User-Id": "alice"})
    client.put(
        f"/api/structured-extraction/tasks/{task_id}/schema/draft",
        headers={"X-User-Id": "alice"},
        json=_schema_payload(),
    )
    client.post(f"/api/structured-extraction/tasks/{task_id}/schema/freeze", headers={"X-User-Id": "alice"})
    client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers={"X-User-Id": "alice"})
    client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build",
        headers={"X-User-Id": "alice"},
        json={"max_chunks_per_group": 1, "max_chars_per_chunk": 160, "include_assets": True},
    )
    return client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()


def _wait_for_terminal(client: TestClient, task_id: str, run_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}", headers={"X-User-Id": "alice"}).json()
        if run["status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run did not finish in time: {run}")


def _record_json(paper_id: str, membrane_name: str, fields: dict) -> str:
    return json.dumps(
        {
            "records": [
                {
                    "paper_id": paper_id,
                    "record_identity": {"paper_id": paper_id, "membrane_name": membrane_name},
                    "fields": fields,
                }
            ]
        }
    )


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
            {"group_key": "material_identity", "label": "Material identity", "description": "membrane sample identity", "order": 1},
            {"group_key": "performance", "label": "Performance", "description": "water flux and rejection rate", "order": 2},
        ],
        "fields": [
            {
                "key": "membrane_name",
                "label": "Membrane name",
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
