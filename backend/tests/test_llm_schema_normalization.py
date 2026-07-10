from __future__ import annotations


def test_schema_assist_normalizes_missing_keys_from_llm_names(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
    monkeypatch.setenv("DB_SCHEMA", "literature_agent_test")

    from modules.structured_extraction.llm_schema import _normalize_result

    result = _normalize_result(
        "parse_field_definition",
        {
            "field_tree": [
                {
                    "name": "Classification",
                    "type": "object",
                    "children": [
                        {"name": "MembraneType", "type": "string"},
                        {"label": "Application Area", "type": "string"},
                    ],
                },
                {
                    "label": "Performance",
                    "type": "object",
                    "children": [
                        {"name": "Water Flux", "type": "string"},
                        {"name": "Water Flux", "type": "string"},
                    ],
                },
            ]
        },
    )

    tree = result["field_tree"]
    assert [node["key"] for node in tree] == ["classification", "performance"]
    assert [node["key"] for node in tree[0]["children"]] == ["membrane_type", "application_area"]
    assert [node["key"] for node in tree[1]["children"]] == ["water_flux", "water_flux_2"]
    assert tree[0]["label"] == "Classification"
