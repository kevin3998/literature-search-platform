from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_STRUCTURED_EXTRACTION_ACCEPTANCE") != "1",
    reason="Real structured extraction acceptance is opt-in only",
)


def _wait_for_run(client: TestClient, task_id: str, run_id: str, *, timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(
            f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}",
            headers={"X-User-Id": "m8_acceptance"},
        ).json()
        if run["status"] in {"completed", "completed_with_errors", "failed", "cancelled", "interrupted"}:
            return run
        time.sleep(2)
    raise AssertionError(f"real extraction run did not finish in time: {run}")


def _paper_level_schema() -> dict:
    return {
        "record_schema": {
            "record_type": "paper_summary",
            "record_unit": "paper_level",
            "primary_entity": "paper",
            "one_paper_may_have_multiple_records": False,
            "record_identity_fields": ["paper_id"],
            "deduplication_keys": ["paper_id"],
            "parent_record_type": None,
        },
        "field_groups": [
            {"group_key": "paper_summary", "label": "论文概要", "description": "paper topic, method or material, and key finding", "order": 1},
        ],
        "fields": [
            {
                "key": "paper_topic",
                "label": "研究主题",
                "type": "string",
                "group_key": "paper_summary",
                "description": "Main research topic of the paper.",
                "extraction_instruction": "Extract a concise topic grounded in the provided evidence.",
                "required": True,
                "missing_policy": "missing",
                "evidence_required": True,
                "allowed_values": [],
                "unit": "",
                "validation_rule": "",
                "example_values": ["antifouling membrane performance"],
                "notes": "",
                "order": 1,
            },
            {
                "key": "main_method_or_material",
                "label": "主要方法或材料",
                "type": "string",
                "group_key": "paper_summary",
                "description": "Main method, material, or system studied.",
                "extraction_instruction": "Extract the most specific method or material supported by evidence.",
                "required": False,
                "missing_policy": "missing",
                "evidence_required": True,
                "allowed_values": [],
                "unit": "",
                "validation_rule": "",
                "example_values": [],
                "notes": "",
                "order": 2,
            },
            {
                "key": "key_finding",
                "label": "关键发现",
                "type": "string",
                "group_key": "paper_summary",
                "description": "Key finding reported by the paper.",
                "extraction_instruction": "Extract one compact finding; use missing if unsupported.",
                "required": False,
                "missing_policy": "missing",
                "evidence_required": True,
                "allowed_values": [],
                "unit": "",
                "validation_rule": "",
                "example_values": [],
                "notes": "",
                "order": 3,
            },
        ],
    }


def test_real_structured_extraction_task_acceptance(tmp_path: Path) -> None:
    real_memory_db = os.getenv(
        "STRUCTURED_EXTRACTION_ACCEPTANCE_MEMORY_DB",
        "/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/platform_memory.sqlite",
    )
    os.environ["LITERATURE_MEMORY_DB_PATH"] = real_memory_db
    data_dir = Path(os.getenv("LITERATURE_DATA_DIR", "/Users/chenlintao/paper-crawler-ops/literature_data"))
    index_path = data_dir / "research_agent" / "research_index.sqlite"
    if not index_path.exists():
        pytest.fail(f"real Research Index not found: {index_path}")

    from core.llm import LLMUnavailable, build_llm_client
    from core.memory_db import memory_db_path
    from core.settings_store import settings_store

    try:
        build_llm_client(settings_store, strong=True)
    except LLMUnavailable as exc:
        pytest.fail(
            "real LLM is not configured for structured extraction acceptance: "
            f"{exc}; db={memory_db_path()}; config={settings_store.model_config()}; readiness={settings_store.readiness()}"
        )

    import main
    from modules.literature_search import literature_search_shared

    literature_search_shared.service.data_dir = data_dir
    client = TestClient(main.app)
    headers = {"X-User-Id": "m8_acceptance"}
    query = os.getenv("STRUCTURED_EXTRACTION_ACCEPTANCE_QUERY", "membrane")

    task = client.post("/api/structured-extraction/tasks", json={"name": "M8 real acceptance"}, headers=headers)
    assert task.status_code == 200
    task_id = task.json()["task_id"]

    search = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/search",
        json={"query": query, "limit": 10},
        headers=headers,
    )
    assert search.status_code == 200
    candidates = search.json()["candidates"]
    assert candidates, f"no local Research Index candidates for query: {query}"
    include = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/{candidates[0]['candidate_id']}/decision",
        json={"decision": "include"},
        headers=headers,
    )
    assert include.status_code == 200
    frozen = client.post(f"/api/structured-extraction/tasks/{task_id}/collection/freeze", headers=headers)
    assert frozen.status_code == 200
    assert frozen.json()["paper_count"] == 1

    draft = client.put(f"/api/structured-extraction/tasks/{task_id}/schema/draft", json=_paper_level_schema(), headers=headers)
    assert draft.status_code == 200
    schema = client.post(f"/api/structured-extraction/tasks/{task_id}/schema/freeze", headers=headers)
    assert schema.status_code == 200

    contract = client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers=headers)
    assert contract.status_code == 200
    packet = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build",
        json={"max_chunks_per_group": 4, "max_chars_per_chunk": 1200, "include_assets": True},
        headers=headers,
    )
    assert packet.status_code == 200
    assert packet.json()["item_count"] >= 1

    started = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers=headers)
    assert started.status_code == 200
    final = _wait_for_run(client, task_id, started.json()["run_id"])
    assert final["status"] in {"completed", "completed_with_errors"}
    assert final["stats"]["record_count"] >= 1

    table = client.get(f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={final['run_id']}", headers=headers)
    assert table.status_code == 200
    rows = table.json()["rows"]
    assert rows
    record_id = rows[0]["record_id"]
    field_key = next(iter(rows[0]["fields"].keys()))
    accepted = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/{field_key}/accept",
        json={"reason": "M8 real acceptance"},
        headers=headers,
    )
    assert accepted.status_code == 200

    exported = client.post(
        f"/api/structured-extraction/tasks/{task_id}/exports",
        json={"run_id": final["run_id"], "formats": ["json", "csv"]},
        headers=headers,
    )
    assert exported.status_code == 200
    export_body = exported.json()
    assert export_body["export_id"] == "exp_v1"
    assert set(export_body["formats"]) == {"json", "csv"}

    from modules.structured_extraction.artifacts import task_workspace_path
    from core.user_context import UserContext

    workspace = task_workspace_path(UserContext("m8_acceptance", "m8_acceptance"), task_id)
    json_path = workspace / "exports" / "exp_v1" / "records_exp_v1.json"
    csv_path = workspace / "exports" / "exp_v1" / "records_exp_v1.csv"
    assert json_path.exists()
    assert csv_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["records"]

    print(
        "STRUCTURED_EXTRACTION_REAL_ACCEPTANCE "
        + json.dumps(
            {
                "task_id": task_id,
                "query": query,
                "run_id": final["run_id"],
                "status": final["status"],
                "record_count": final["stats"]["record_count"],
                "export_id": export_body["export_id"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
