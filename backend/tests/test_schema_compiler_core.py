from __future__ import annotations

import asyncio
import json
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:5432/test")
os.environ.setdefault("DB_SCHEMA", "literature_agent_test")

from modules.structured_extraction.schema_compiler import compile_schema_definition
from modules.structured_extraction.schema_contract import CompilationResult
from modules.structured_extraction.schema_source_parser import detect_source_format, parse_schema_source
from modules.structured_extraction.llm_extraction import build_item_prompt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"field_tree":[{"key":"metric","type":"number"}]}', "json"),
        ("# Fields\n- `metric`: measured value", "markdown"),
        ("Extract the intervention and the primary endpoint from each study.", "natural_language"),
    ],
)
def test_detect_source_format(text, expected):
    assert detect_source_format(text) == expected


def test_json_schema_and_example_json_infer_supported_field_shapes():
    json_schema = parse_schema_source(
        """{
          "type": "object",
          "properties": {
            "measured_at": {"type": "string", "format": "date"},
            "labels": {"type": "array", "items": {"type": "string"}},
            "phases": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}}}},
            "attributes": {"type": "object", "additionalProperties": {"type": "string"}},
            "categories": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}}
          }
        }""",
        "json",
    )
    types = {node["key"]: node["type"] for node in json_schema.field_tree}
    assert types == {
        "measured_at": "date",
        "labels": "list_string",
        "phases": "list_object",
        "attributes": "dict",
        "categories": "multi_enum",
    }
    categories = next(node for node in json_schema.field_tree if node["key"] == "categories")
    assert categories["allowed_values"] == ["a", "b"]

    example = parse_schema_source('{"active": true, "score": 1.2, "tags": ["x"], "details": {"method": "m"}}', "json")
    assert {node["key"]: node["type"] for node in example.field_tree} == {
        "active": "boolean",
        "score": "number",
        "tags": "list_string",
        "details": "object",
    }


def test_markdown_parser_builds_domain_neutral_requirement_graph():
    parsed = parse_schema_source(
        """
# Extraction
1. **Experiment**:
    * `temperature`: Reaction temperature.
    * `catalysts`: A list of objects.
        * `name`: Catalyst name.
2. **PUBLICATION METADATA**:
    * `journal`: Publication journal.
    * `year`: Publication year.
""",
        "auto",
    )

    names = {item["raw_name"] for item in parsed.requirements if item["kind"] == "field"}
    assert {"Experiment", "temperature", "catalysts", "name", "journal", "year"}.issubset(names)
    assert parsed.source_format == "markdown"
    assert parsed.field_tree[0]["key"] == "experiment"


def test_markdown_parser_captures_inline_fields_and_keeps_commands_out_of_field_tree():
    parsed = parse_schema_source(
        """
- **Avoid Sparse Entries**: Do not create records without measured results.
- **Independent Entries**: Only create separate records when results are independently reported.
- **Consolidate Records**: Group referenced values under `Design` and `Fabrication`.
- **Surface characteristics**: `roughness`, **surface_energy**, **surface_area**.
- `transport_metrics`: {{`flux`, `permeability`, `rejection`}}
- `pressure`, `temperature`, `duration`.
""",
        "markdown",
    )

    by_name = {item["raw_name"]: item for item in parsed.requirements}
    assert by_name["Avoid Sparse Entries"]["kind"] == "selection_rule"
    assert by_name["Independent Entries"]["kind"] == "selection_rule"
    assert by_name["Consolidate Records"]["kind"] == "grouping_rule"
    assert {"roughness", "surface_energy", "surface_area", "flux", "permeability", "rejection", "pressure", "temperature", "duration"}.issubset(by_name)
    top_level = {node["key"] for node in parsed.field_tree}
    assert "avoid_sparse_entries" not in top_level
    assert "design" not in top_level
    assert "fabrication" not in top_level
    assert {"pressure", "temperature", "duration"}.issubset(top_level)


def test_markdown_parser_preserves_top_level_record_instructions_for_llm_and_coverage():
    source = """
# Extraction
For each experimental trial, return one record with `TrialId` and `Details`.

- `outcome`: Measured endpoint.
"""
    parsed = parse_schema_source(source, "markdown")

    prose = next(item for item in parsed.requirements if item["source_text"].startswith("For each experimental trial"))
    assert prose["kind"] == "record_identity"
    assert prose["raw_name"] == "TrialId"
    assert prose["constraints"][0] == {
        "type": "identity_candidates",
        "values": ["TrialId", "Details"],
        "text": "",
    }
    assert parsed.source_text == source

    seen_source = None

    async def generator(messages, _schema, _name):
        nonlocal seen_source
        payload = json.loads(messages[0]["content"].split("\n\n", 1)[1])
        seen_source = payload["source_text"]
        return {"record_schema": {}, "field_tree": [{"key": "outcome", "type": "string"}], "requirement_mappings": []}

    asyncio.run(compile_schema_definition(
        instruction=source,
        source_format="markdown",
        draft={},
        task={"task_id": "task-prose", "name": "prose"},
        generate_structured=generator,
    ))
    assert seen_source == source

    deterministic = asyncio.run(compile_schema_definition(
        instruction=source,
        source_format="markdown",
        draft={},
        task={"task_id": "task-prose-offline", "name": "prose"},
        generate_structured=None,
    ))
    assert deterministic["status"] == "needs_review"
    assert prose["requirement_id"] in deterministic["coverage"]["unresolved_requirement_ids"]


def test_record_identity_candidate_ranking_avoids_generic_wrappers():
    parsed = parse_schema_source(
        'For each primary entity, return a JSON object with "MaterialName" and "Details".',
        "natural_language",
    )
    requirement = parsed.requirements[0]
    assert requirement["kind"] == "record_identity"
    assert requirement["raw_name"] == "MaterialName"
    assert requirement["constraints"][0]["values"] == ["MaterialName", "Details"]


@pytest.mark.parametrize(
    ("source", "expected_fields"),
    [
        ("- `membrane_type`: Type\n- `water_flux`: Flux", {"membrane_type", "water_flux"}),
        ("- `catalyst`: Catalyst\n- `reaction_temperature`: Temperature", {"catalyst", "reaction_temperature"}),
        ("- `cell_id`: Cell\n- `cycle_life`: Cycles", {"cell_id", "cycle_life"}),
        ("- `intervention`: Treatment\n- `primary_endpoint`: Endpoint", {"intervention", "primary_endpoint"}),
        ("- `repository`: Repository\n- `latency`: Runtime metric", {"repository", "latency"}),
        ("- `样品编号`: sample id\n- `测试温度`: temperature", {"field_1", "field_2"}),
        ("- `entity_token`: Unknown entity\n- `observed_signal`: Unknown signal", {"entity_token", "observed_signal"}),
    ],
)
def test_markdown_parser_is_domain_neutral(source, expected_fields):
    parsed = parse_schema_source(source, "markdown")
    keys = {node["key"] for node in parsed.field_tree}
    assert expected_fields.issubset(keys)


def test_compiler_maps_system_metadata_and_preserves_requirements():
    source = """
# Record
- `trial_name`: Unique trial name.
- `journal`: Journal name.
- `year`: Publication year.
- **SELECTION RULE**: Only include controlled studies.
"""

    async def generator(_messages, _schema, _name):
        return {
            "record_schema": {
                "record_type": "trial_record",
                "record_unit": "experiment_level",
                "primary_entity": "trial",
                "record_identity_fields": ["paper_id", "trial_name"],
                "deduplication_keys": ["paper_id", "trial_name"],
                "one_paper_may_have_multiple_records": True,
            },
            "field_tree": [{"key": "trial_name", "label": "Trial name", "type": "string", "source_requirement_ids": ["req_0001"]}],
            "requirement_mappings": [],
        }

    result = asyncio.run(
        compile_schema_definition(
            instruction=source,
            source_format="auto",
            draft={},
            task={"task_id": "task-1", "name": "trial extraction"},
            generate_structured=generator,
        )
    )

    targets = {item["target_path"] for item in result["requirement_mappings"]}
    assert "paper_metadata.journal" in targets
    assert "paper_metadata.year" in targets
    assert result["record_schema"]["record_unit"] == "experiment_level"
    assert result["coverage"]["unresolved"] == 0


def test_compiler_blocks_unresolved_after_one_repair():
    calls = 0

    async def generator(_messages, _schema, _name):
        nonlocal calls
        calls += 1
        return {
            "record_schema": {},
            "field_tree": [],
            "requirement_mappings": [
                {"requirement_id": "req_0001", "disposition": "unresolved", "reason": "ambiguous request"}
            ],
        }

    result = asyncio.run(
        compile_schema_definition(
            instruction="Extract the clinically meaningful outcome without a predefined field name.",
            source_format="natural_language",
            draft={},
            task={"task_id": "task-2", "name": "unknown domain"},
            generate_structured=generator,
        )
    )

    assert calls == 2
    assert result["status"] == "needs_review"
    assert result["coverage"]["unresolved"] == 1


def test_compiler_separates_arbitrary_record_identity_from_user_data():
    async def generator(_messages, _schema, _name):
        return {
            "record_schema": {
                "record_type": "software_benchmark",
                "record_unit": "experiment_level",
                "primary_entity": "benchmark",
                "record_identity_fields": ["paper_id", "benchmark_id"],
                "deduplication_keys": ["paper_id", "benchmark_id"],
                "one_paper_may_have_multiple_records": True,
            },
            "field_tree": [
                {"key": "benchmark_id", "type": "string", "source_requirement_ids": ["req_0001"]},
                {"key": "latency", "type": "number", "source_requirement_ids": ["req_0002"]},
            ],
            "requirement_mappings": [],
        }

    result = asyncio.run(
        compile_schema_definition(
            instruction="- `benchmark_id`: Unique benchmark identifier.\n- `latency`: Runtime latency.",
            source_format="markdown",
            draft={},
            task={"task_id": "task-3", "name": "software metrics"},
            generate_structured=generator,
        )
    )

    assert [node["key"] for node in result["field_tree"]] == ["latency"]
    mapping = {item["requirement_id"]: item for item in result["requirement_mappings"]}
    assert mapping["req_0001"]["disposition"] == "record_identity"
    assert mapping["req_0001"]["target_path"] == "record_identity.benchmark_id"
    assert CompilationResult.model_validate(result).schema_mode == "nested_record"


def test_compiler_normalizes_invalid_model_types_without_breaking_the_contract():
    async def generator(_messages, _schema, _name):
        return {
            "record_schema": {"record_unit": "study", "record_identity_fields": ["paper_id"]},
            "field_tree": [{"key": "Primary Endpoint", "type": "decimal"}],
            "requirement_mappings": [],
        }

    result = asyncio.run(
        compile_schema_definition(
            instruction='{"Primary Endpoint": 2.5}',
            source_format="json",
            draft={},
            task={"task_id": "task-4", "name": "clinical endpoint"},
            generate_structured=generator,
        )
    )

    assert result["record_schema"]["record_unit"] == "paper_level"
    assert result["field_tree"][0]["key"] == "primary_endpoint"
    assert result["field_tree"][0]["type"] == "string"
    assert result["status"] == "valid_with_warnings"
    CompilationResult.model_validate(result)


def test_nested_record_prompt_uses_data_contract_and_platform_metadata_rules():
    prompt = build_item_prompt(
        task={"task_id": "task-5", "name": "generic records"},
        contract={
            "schema_mode": "nested_record",
            "record_contract": {"record_identity_fields": ["paper_id", "trial_id"]},
            "field_contracts": [{"key": "outcomes"}],
            "section_contracts": [{"section_key": "outcomes", "node": {"key": "outcomes"}}],
            "schema_tree_contract": [{"key": "outcomes"}],
            "output_json_contract": {"paper_metadata": "platform_injected_do_not_generate"},
            "extraction_rules": ["Use null when missing"],
            "user_extraction_rules": [{"text": "Only controlled trials"}],
            "system_metadata_contract": {"paper_metadata": {"title": {"type": "string"}}},
        },
        packet_item={"paper_id": "p1", "field_group": "outcomes", "field_keys": ["outcomes"]},
    )

    content = prompt["messages"][0]["content"]
    assert "record_identity, and data" in content
    assert "Do not generate paper_metadata" in content
    assert prompt["payload"]["user_extraction_rules"] == [{"text": "Only controlled trials"}]
    assert prompt["payload"]["system_metadata_contract"]["paper_metadata"]["title"]["type"] == "string"


def test_compiler_retries_one_model_failure_and_reports_both_attempts():
    calls = 0

    async def failing_generator(_messages, _schema, _name):
        nonlocal calls
        calls += 1
        raise ValueError("provider returned malformed structured output")

    result = asyncio.run(
        compile_schema_definition(
            instruction="- `metric`: Measured result.",
            source_format="markdown",
            draft={},
            task={"task_id": "task-6", "name": "failure handling"},
            generate_structured=failing_generator,
        )
    )

    assert calls == 2
    assert [attempt["status"] for attempt in result["model_attempts"]] == ["failed", "failed"]
    assert any(warning["code"] == "llm_structured_output_failed" for warning in result["warnings"])
    assert result["status"] == "valid_with_warnings"
    assert result["field_tree"][0]["key"] == "metric"


def test_invalid_model_mapping_target_needs_review_after_one_repair():
    calls = 0

    async def generator(_messages, _schema, _name):
        nonlocal calls
        calls += 1
        return {
            "record_schema": {},
            "field_tree": [{"key": "metric", "type": "number"}],
            "requirement_mappings": [{
                "requirement_id": "req_0001",
                "disposition": "system_metadata",
                "target_path": "paper_metadata.nonexistent",
            }],
        }

    result = asyncio.run(
        compile_schema_definition(
            instruction="- `metric`: Measured result.",
            source_format="markdown",
            draft={},
            task={"task_id": "task-7", "name": "mapping validation"},
            generate_structured=generator,
        )
    )

    assert calls == 2
    assert result["status"] == "needs_review"
    assert any(error["code"] == "unknown_system_metadata_target" for error in result["validation_errors"])


def test_internal_requirement_id_from_model_never_becomes_a_field():
    async def generator(_messages, _schema, _name):
        return {
            "record_schema": {},
            "field_tree": [{"key": "req_0001", "type": "string", "source_requirement_ids": ["req_0001"]}],
            "requirement_mappings": [{
                "requirement_id": "req_0001",
                "disposition": "user_schema",
                "target_path": "data.req_0001",
            }],
        }

    result = asyncio.run(compile_schema_definition(
        instruction="Extract one meaningful result.",
        source_format="natural_language",
        draft={},
        task={"task_id": "task-internal-id", "name": "guard"},
        generate_structured=generator,
    ))

    assert result["status"] == "needs_review"
    assert any(error["code"] == "internal_requirement_id_not_allowed" for error in result["validation_errors"])


def test_compiler_enforces_source_requirement_and_tree_limits():
    with pytest.raises(ValueError, match="schema_source_too_large"):
        parse_schema_source("x" * 100_001, "natural_language")
    with pytest.raises(ValueError, match="schema_requirement_limit_exceeded"):
        parse_schema_source("\n".join(f"- `field_{index}`: value" for index in range(501)), "markdown")

    node = {"key": "level_9", "type": "string", "children": []}
    for depth in range(8, 0, -1):
        node = {"key": f"level_{depth}", "type": "object", "children": [node]}
    result = asyncio.run(
        compile_schema_definition(
            instruction='{"metric": 1}',
            source_format="json",
            draft={},
            task={"task_id": "task-8", "name": "limits"},
            generate_structured=lambda *_args: _async_result({
                "record_schema": {},
                "field_tree": [node],
                "requirement_mappings": [],
            }),
        )
    )
    assert result["status"] == "needs_review"
    assert any(error["code"] == "tree_depth_exceeded" for error in result["validation_errors"])


def test_compiler_reports_real_progress_phases_without_a_model():
    events = []

    result = asyncio.run(
        compile_schema_definition(
            instruction='{"metric": 1}',
            source_format="json",
            draft={},
            task={"task_id": "task-progress", "name": "progress"},
            generate_structured=None,
            on_progress=events.append,
        )
    )

    assert result["field_tree"][0]["key"] == "metric"
    assert [event["phase"] for event in events] == [
        "source_parsing",
        "requirement_graph",
        "normalization",
        "validation",
        "completed",
    ]
    assert [event["progress"] for event in events] == sorted(event["progress"] for event in events)
    assert events[-1]["progress"] == 100


def test_compiler_reports_model_and_targeted_repair_phases():
    events = []
    calls = 0

    async def generator(_messages, _schema, _name):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("malformed structured output")
        return {
            "record_schema": {},
            "field_tree": [{"key": "metric", "type": "number"}],
            "requirement_mappings": [{
                "requirement_id": "req_0001",
                "disposition": "user_schema",
                "target_path": "data.metric",
            }],
        }

    asyncio.run(
        compile_schema_definition(
            instruction="- `metric`: Measured result.",
            source_format="markdown",
            draft={},
            task={"task_id": "task-repair-progress", "name": "repair progress"},
            generate_structured=generator,
            on_progress=events.append,
        )
    )

    phases = [event["phase"] for event in events]
    assert phases == [
        "source_parsing",
        "requirement_graph",
        "semantic_compile",
        "normalization",
        "validation",
        "targeted_repair",
        "final_validation",
        "completed",
    ]
    assert next(event for event in events if event["phase"] == "semantic_compile")["indeterminate"] is True
    assert next(event for event in events if event["phase"] == "targeted_repair")["indeterminate"] is True


async def _async_result(value):
    return value
