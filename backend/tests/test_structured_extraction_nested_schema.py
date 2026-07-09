from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from test_structured_extraction_preparation import _make_index
from test_structured_extraction_runs import _run_structured_worker_once


class FakeLLM:
    def __init__(self, outputs: list[str]):
        self.outputs = list(outputs)
        self.calls: list[list[dict]] = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append(messages)
        text = self.outputs.pop(0) if self.outputs else '{"records":[]}'
        yield {"type": "content", "text": text}


def _nested_tree() -> list[dict]:
    return [
        {
            "key": "classification",
            "label": "分类",
            "type": "object",
            "description": "Membrane classification.",
            "required": False,
            "evidence_required": True,
            "order": 2,
            "children": [
                {
                    "key": "membrane_type",
                    "label": "Membrane Type",
                    "type": "enum",
                    "allowed_values": ["UF", "NF", "RO", "Other"],
                    "unit": "should_not_be_prompted",
                    "example_values": ["NF"],
                    "description": "Specific separation process.",
                    "required": False,
                    "evidence_required": True,
                    "order": 1,
                }
            ],
        },
        {
            "key": "composition",
            "label": "组成",
            "type": "object",
            "description": "Material composition.",
            "required": False,
            "evidence_required": True,
            "order": 3,
            "children": [
                {
                    "key": "base_polymers",
                    "label": "Base Polymers",
                    "type": "list_object",
                    "description": "Primary polymers used.",
                    "required": False,
                    "evidence_required": True,
                    "order": 1,
                    "children": [
                        {"key": "name", "label": "Name", "type": "string", "order": 1},
                        {"key": "concentration_text", "label": "Concentration", "type": "string", "unit": "wt%", "example_values": ["15 wt%"], "order": 2},
                    ],
                },
                {"key": "additives", "label": "Additives", "type": "list_object", "order": 2, "children": [{"key": "name", "label": "Name", "type": "string", "order": 1}]},
            ],
        },
        {
            "key": "fabrication",
            "label": "制备",
            "type": "object",
            "description": "Preparation method and parameters.",
            "required": False,
            "evidence_required": True,
            "order": 4,
            "children": [
                {"key": "fabrication_method", "label": "Fabrication Method", "type": "string", "order": 1},
                {"key": "key_technical_parameters", "label": "Key Parameters", "type": "dict", "order": 2},
            ],
        },
        {
            "key": "performance",
            "label": "性能",
            "type": "object",
            "description": "Performance metrics.",
            "required": False,
            "evidence_required": True,
            "order": 5,
            "children": [
                {"key": "liquid_transport_properties", "label": "Liquid Transport", "type": "object", "order": 1, "children": [{"key": "water_flux", "label": "Water Flux", "type": "string", "order": 1}, {"key": "rejections", "label": "Rejections", "type": "dict", "order": 2}]}
            ],
        },
        {
            "key": "application",
            "label": "应用",
            "type": "object",
            "description": "Usage and test context.",
            "required": False,
            "evidence_required": True,
            "order": 6,
            "children": [
                {"key": "application_area", "label": "Application Area", "type": "string", "order": 1},
                {"key": "test_parameters", "label": "Test Parameters", "type": "dict", "order": 2},
            ],
        },
    ]


def _nested_payload() -> dict:
    return {
        "schema_mode": "nested_material",
        "record_schema": {
            "record_type": "material_record",
            "record_unit": "material_level",
            "primary_entity": "material",
            "one_paper_may_have_multiple_records": True,
            "record_identity_fields": ["paper_id", "material_name"],
            "deduplication_keys": ["paper_id", "material_name"],
            "parent_record_type": None,
        },
        "field_tree": _nested_tree(),
        "field_groups": [],
        "fields": [],
    }


def _client_with_nested_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setenv("LITERATURE_USER_DATA_ROOT", str(tmp_path / "users"))
    data_dir = tmp_path / "literature_data"
    _make_index(data_dir)
    monkeypatch.setenv("LITERATURE_DATA_DIR", str(data_dir))

    import main
    from modules.literature_search import literature_search_shared

    literature_search_shared.service.data_dir = data_dir
    client = TestClient(main.app)
    task = client.post("/api/structured-extraction/tasks", json={"name": "Nested material task"}, headers={"X-User-Id": "alice"}).json()
    task_id = task["task_id"]
    search = client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/search",
        json={"query": "membrane", "limit": 1},
        headers={"X-User-Id": "alice"},
    ).json()
    candidate_ids = [item["candidate_id"] for item in search["candidates"][:1]]
    client.post(
        f"/api/structured-extraction/tasks/{task_id}/collection/candidates/bulk-decision",
        json={"candidate_ids": candidate_ids, "decision": "include"},
        headers={"X-User-Id": "alice"},
    )
    client.post(f"/api/structured-extraction/tasks/{task_id}/collection/freeze", headers={"X-User-Id": "alice"})
    return client, task_id, tmp_path


def _wait_for_terminal(client, task_id: str, run_id: str, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _run_structured_worker_once()
        run = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run_id}", headers={"X-User-Id": "alice"}).json()
        if run["status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run did not finish in time: {run}")


def _section_output(section: str, value: dict, material_name: str = "PES-ZW") -> str:
    return json.dumps(
        {
            "records": [
                {
                    "paper_id": "p_prep_1",
                    "material_name": material_name,
                    "record_identity": {"paper_id": "p_prep_1", "material_name": material_name},
                    "data": {section: value},
                    "quality_flags": [],
                }
            ]
        }
    )


def test_nested_material_schema_draft_freeze_contract_and_packet(monkeypatch, tmp_path):
    client, task_id, _root = _client_with_nested_schema(monkeypatch, tmp_path)

    draft = client.get(f"/api/structured-extraction/tasks/{task_id}/schema/draft", headers={"X-User-Id": "alice"}).json()
    assert draft["schema_mode"] == "nested_material"
    assert draft["record_schema"]["record_identity_fields"] == ["paper_id", "material_name"]
    assert draft["field_tree"] == []
    assert draft["fields"] == []
    assert draft["field_groups"] == []

    saved = client.put(f"/api/structured-extraction/tasks/{task_id}/schema/draft", json=_nested_payload(), headers={"X-User-Id": "alice"})
    assert saved.status_code == 200
    assert saved.json()["schema_mode"] == "nested_material"
    assert [field["key"] for field in saved.json()["fields"]] == ["classification", "composition", "fabrication", "performance", "application"]

    frozen = client.post(f"/api/structured-extraction/tasks/{task_id}/schema/freeze", headers={"X-User-Id": "alice"}).json()
    assert frozen["schema_mode"] == "nested_material"
    assert frozen["field_tree"][1]["key"] == "composition"
    assert frozen["field_count"] == 5

    contract = client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers={"X-User-Id": "alice"}).json()
    assert contract["schema_mode"] == "nested_material"
    assert contract["schema_tree_contract"][0]["key"] == "classification"
    contract_text = json.dumps(contract, ensure_ascii=False)
    assert "should_not_be_prompted" not in contract_text
    assert "example_values" not in contract_text
    assert "unit" not in contract["schema_tree_contract"][0]["children"][0]
    assert [section["section_key"] for section in contract["section_contracts"]] == ["classification", "composition", "fabrication", "performance", "application"]
    assert contract["output_json_contract"]["records"][0]["material_name"] == "string"
    assert "material_name" not in contract["output_json_contract"]["records"][0]["data"]

    packet = client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build",
        json={"max_chunks_per_group": 1, "max_chars_per_chunk": 120, "include_assets": False},
        headers={"X-User-Id": "alice"},
    ).json()
    assert packet["field_group_count"] == 5
    assert packet["item_count"] == 5
    items = client.get(f"/api/structured-extraction/tasks/{task_id}/evidence-packets/versions/{packet['packet_version']}/items", headers={"X-User-Id": "alice"}).json()["items"]
    assert {item["field_group"] for item in items} == {"classification", "composition", "fabrication", "performance", "application"}


def test_nested_material_extraction_review_and_export_json(monkeypatch, tmp_path):
    client, task_id, root = _client_with_nested_schema(monkeypatch, tmp_path)
    client.put(f"/api/structured-extraction/tasks/{task_id}/schema/draft", json=_nested_payload(), headers={"X-User-Id": "alice"})
    client.post(f"/api/structured-extraction/tasks/{task_id}/schema/freeze", headers={"X-User-Id": "alice"})
    client.post(f"/api/structured-extraction/tasks/{task_id}/prompt-contract/compile", headers={"X-User-Id": "alice"})
    client.post(
        f"/api/structured-extraction/tasks/{task_id}/evidence-packets/build",
        json={"max_chunks_per_group": 1, "max_chars_per_chunk": 120, "include_assets": False},
        headers={"X-User-Id": "alice"},
    )

    fake = FakeLLM(
        [
            _section_output("classification", {"membrane_type": "NF"}),
            _section_output("composition", {"base_polymers": [{"name": "PES", "concentration_text": "15 wt%"}], "additives": [{"name": "ZW"}]}),
            _section_output("fabrication", {"fabrication_method": "coating", "key_technical_parameters": {"temperature": "25 C"}}),
            _section_output("performance", {"liquid_transport_properties": {"water_flux": "120 LMH", "rejections": {"Na2SO4": "98%"}}}),
            _section_output("application", {"application_area": "wastewater treatment", "test_parameters": {"pressure": "1 bar"}}),
        ]
    )

    import modules.structured_extraction.llm_extraction as llm_extraction

    monkeypatch.setattr(llm_extraction, "build_llm_client", lambda _settings_store, strong=False, user_id=None: fake)
    monkeypatch.setattr(llm_extraction.settings_store, "model_config", lambda user_id=None: {"provider": "fake", "chat_model": "weak", "strong_model": "strong"})

    run = client.post(f"/api/structured-extraction/tasks/{task_id}/runs", headers={"X-User-Id": "alice"}).json()
    final = _wait_for_terminal(client, task_id, run["run_id"])
    assert final["status"] == "completed"
    assert final["stats"]["record_count"] == 1
    first_prompt = fake.calls[0][0]["content"]
    assert "native JSON" in first_prompt
    assert "Do not wrap leaf values" in first_prompt
    assert "Do not normalize units" in first_prompt

    records = client.get(f"/api/structured-extraction/tasks/{task_id}/runs/{run['run_id']}/records", headers={"X-User-Id": "alice"}).json()["records"]
    assert records[0]["record_identity"]["material_name"] == "PES-ZW"
    assert records[0]["data"]["classification"]["membrane_type"] == "NF"
    assert records[0]["data"]["performance"]["liquid_transport_properties"]["water_flux"] == "120 LMH"
    assert records[0]["fields"]["composition"]["base_polymers"][0]["name"] == "PES"

    table = client.get(f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={run['run_id']}", headers={"X-User-Id": "alice"}).json()
    row = table["rows"][0]
    assert row["record_identity"]["material_name"] == "PES-ZW"
    assert row["data"]["composition"]["base_polymers"][0]["name"] == "PES"
    assert "composition" in row["fields"]

    edited_composition = {"base_polymers": [{"name": "PES", "concentration_text": "16 wt%"}], "additives": [{"name": "ZW"}]}
    edit = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{row['record_id']}/fields/composition/edit",
        json={"value": edited_composition, "reason": "nested correction"},
        headers={"X-User-Id": "alice"},
    )
    assert edit.status_code == 200
    assert edit.json()["data"]["composition"]["base_polymers"][0]["concentration_text"] == "16 wt%"

    exported = client.post(
        f"/api/structured-extraction/tasks/{task_id}/exports",
        json={"run_id": run["run_id"], "formats": ["json", "csv", "xlsx"], "include_base_values": True, "include_review_metadata": True},
        headers={"X-User-Id": "alice"},
    ).json()
    assert exported["record_count"] == 1
    assert exported["top_level_section_count"] == 5
    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    export_id = exported["export_id"]
    export_dir = root / "users" / task["user_id"] / task["workspace_rel_path"] / "exports" / export_id
    exported_json = json.loads((export_dir / f"records_{export_id}.json").read_text(encoding="utf-8"))
    assert exported_json["records"][0]["data"]["composition"]["base_polymers"][0]["concentration_text"] == "16 wt%"
    csv_text = (export_dir / f"records_{export_id}.csv").read_text(encoding="utf-8-sig")
    assert "classification.membrane_type" in csv_text


def test_nested_schema_assist_prompt_keeps_native_json_and_avoids_units():
    from modules.structured_extraction.llm_schema import _prompt
    from modules.structured_extraction.schemas import SchemaAssistRequest

    prompt = _prompt(
        SchemaAssistRequest(action="parse_field_definition", instruction="battery fields", draft={}),
        task={"name": "Battery extraction", "current_collection_version": "col_v1"},
    )

    assert "native JSON" in prompt
    assert "Do not add unit constraints" in prompt
    assert "Do not add example_values" in prompt
    assert "Do not include paper_id or material_name" in prompt
