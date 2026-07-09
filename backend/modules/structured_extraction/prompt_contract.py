from __future__ import annotations

import re
from typing import Any

from core.memory_db import dumps, loads, now
from core.user_context import UserContext

from .artifacts import write_prompt_contract
from .schemas import PromptContractCompileRequest
from .store import StructuredExtractionStore

EXTRACTION_RULES = [
    "Do not guess or infer values from general knowledge.",
    "Return missing when evidence does not support a field value.",
    "Do not mix composition, preparation conditions, or performance values across different samples.",
    "Do not merge measurements from different test conditions.",
    "Preserve raw_value, normalized_value, unit, condition_context, evidence_text, evidence_location, and extraction_note.",
    "Mark ambiguous_value when sample or condition alignment cannot be confirmed.",
]

NESTED_EXTRACTION_RULES = [
    "Do not guess or infer values from general knowledge.",
    "Return missing or omit values when evidence does not support a user-defined JSON path.",
    "Return native JSON values exactly under data; do not wrap leaf values in raw_value/evidence/unit objects.",
    "Do not normalize units or rewrite ranges unless the user-defined schema explicitly asks for that field.",
    "Do not put evidence metadata inside data unless the user-defined schema contains that evidence field.",
    "Do not mix composition, preparation conditions, or performance values across different materials.",
]


class StructuredExtractionPromptContractService:
    def __init__(self, store: StructuredExtractionStore) -> None:
        self.store = store

    def compile(self, task_id: str, payload: PromptContractCompileRequest, *, user: UserContext) -> dict[str, Any]:
        task = self.store.get_task(task_id, user_id=user.user_id)
        collection_version = payload.collection_version or task.get("current_collection_version")
        schema_version = payload.schema_version or task.get("current_schema_version")
        if not collection_version:
            raise ValueError("collection_version_required")
        if not schema_version:
            raise ValueError("schema_version_required")
        self._collection_version(task_id, collection_version, user=user)
        schema = self._schema_version(task_id, schema_version, user=user)
        version = self._next_version(task_id)
        contract = _compile_contract(
            task_id=task_id,
            prompt_contract_version=version,
            collection_version=collection_version,
            schema=schema,
            created_at=now(),
        )
        self.store.conn.execute(
            """
            insert into structured_extraction_prompt_contracts(
                task_id, prompt_contract_version, user_id, collection_version, schema_version,
                contract_json, field_count, created_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                version,
                user.user_id,
                collection_version,
                schema_version,
                dumps(contract),
                len(contract["field_contracts"]),
                contract["created_at"],
            ),
        )
        self.store.conn.commit()
        write_prompt_contract(user, task_id, contract)
        return contract

    def list_versions(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_prompt_contracts
            where task_id = ? and user_id = ?
            order by created_at desc
            """,
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "versions": [self._row_to_contract(row) for row in rows]}

    def get_version(self, task_id: str, prompt_contract_version: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            """
            select * from structured_extraction_prompt_contracts
            where task_id = ? and user_id = ? and prompt_contract_version = ?
            """,
            (task_id, user.user_id, prompt_contract_version),
        ).fetchone()
        if not row:
            raise KeyError(f"prompt contract not found: {prompt_contract_version}")
        return self._row_to_contract(row)

    def latest_compatible(self, task_id: str, *, user: UserContext, collection_version: str, schema_version: str) -> dict[str, Any] | None:
        row = self.store.conn.execute(
            """
            select * from structured_extraction_prompt_contracts
            where task_id = ? and user_id = ? and collection_version = ? and schema_version = ?
            order by created_at desc limit 1
            """,
            (task_id, user.user_id, collection_version, schema_version),
        ).fetchone()
        return self._row_to_contract(row) if row else None

    def _collection_version(self, task_id: str, collection_version: str, *, user: UserContext) -> dict[str, Any]:
        row = self.store.conn.execute(
            """
            select * from structured_extraction_collection_versions
            where task_id = ? and user_id = ? and collection_version = ?
            """,
            (task_id, user.user_id, collection_version),
        ).fetchone()
        if not row:
            raise ValueError("collection_version_not_found")
        return {"collection_version": row["collection_version"], "paper_count": row["paper_count"]}

    def _schema_version(self, task_id: str, schema_version: str, *, user: UserContext) -> dict[str, Any]:
        row = self.store.conn.execute(
            """
            select * from structured_extraction_schema_versions
            where task_id = ? and user_id = ? and schema_version = ?
            """,
            (task_id, user.user_id, schema_version),
        ).fetchone()
        if not row:
            raise ValueError("schema_version_not_found")
        return {
            "task_id": task_id,
            "schema_version": row["schema_version"],
            "base_collection_version": row["base_collection_version"],
            "schema_mode": row["schema_mode"] if "schema_mode" in row.keys() else "flat_fields",
            "record_schema": loads(row["record_schema_json"], {}) or {},
            "field_groups": loads(row["field_groups_json"], []) or [],
            "field_tree": loads(row["field_tree_json"], []) if "field_tree_json" in row.keys() else [],
            "fields": loads(row["fields_json"], []) or [],
            "field_count": row["field_count"],
            "created_at": row["created_at"],
            "frozen_at": row["frozen_at"],
        }

    def _next_version(self, task_id: str) -> str:
        rows = self.store.conn.execute(
            "select prompt_contract_version from structured_extraction_prompt_contracts where task_id = ?",
            (task_id,),
        ).fetchall()
        max_n = 0
        for row in rows:
            match = re.match(r"^pc_v(\d+)$", row["prompt_contract_version"] or "")
            if match:
                max_n = max(max_n, int(match.group(1)))
        return f"pc_v{max_n + 1}"

    @staticmethod
    def _row_to_contract(row) -> dict[str, Any]:
        return loads(row["contract_json"], {}) or {}


def _compile_contract(
    *,
    task_id: str,
    prompt_contract_version: str,
    collection_version: str,
    schema: dict[str, Any],
    created_at: float,
) -> dict[str, Any]:
    record_schema = schema["record_schema"]
    fields = schema["fields"]
    field_groups = schema["field_groups"]
    schema_mode = schema.get("schema_mode") or "flat_fields"
    if schema_mode == "nested_material":
        field_tree = _sanitize_tree_for_prompt(schema.get("field_tree") or [])
        field_contracts = [_nested_field_contract(field) for field in fields]
        section_contracts = [{"section_key": node.get("key"), "node": node} for node in field_tree]
        output_contract = _nested_output_json_contract(record_schema, field_tree)
        extraction_rules = NESTED_EXTRACTION_RULES
    else:
        field_tree = schema.get("field_tree") or []
        field_contracts = [_field_contract(field) for field in fields]
        section_contracts = []
        output_contract = _output_json_contract(record_schema, field_contracts)
        extraction_rules = EXTRACTION_RULES
    return {
        "prompt_contract_version": prompt_contract_version,
        "task_id": task_id,
        "schema_version": schema["schema_version"],
        "collection_version": collection_version,
        "schema_mode": schema_mode,
        "record_contract": {
            "record_type": record_schema.get("record_type"),
            "record_unit": record_schema.get("record_unit"),
            "primary_entity": record_schema.get("primary_entity"),
            "one_paper_may_have_multiple_records": bool(record_schema.get("one_paper_may_have_multiple_records")),
            "record_identity_fields": record_schema.get("record_identity_fields") or [],
            "deduplication_keys": record_schema.get("deduplication_keys") or [],
            "parent_record_type": record_schema.get("parent_record_type"),
            "field_groups": field_groups,
        },
        "field_contracts": field_contracts,
        "schema_tree_contract": field_tree,
        "section_contracts": section_contracts,
        "output_json_contract": output_contract,
        "extraction_rules": extraction_rules,
        "created_at": created_at,
    }


def _field_contract(field: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": field.get("key"),
        "label": field.get("label"),
        "type": field.get("type"),
        "group_key": field.get("group_key"),
        "description": field.get("description") or "",
        "extraction_instruction": field.get("extraction_instruction") or "",
        "required": bool(field.get("required")),
        "missing_policy": field.get("missing_policy") or "missing",
        "evidence_required": bool(field.get("evidence_required")),
        "allowed_values": field.get("allowed_values") or [],
        "unit": field.get("unit") or "",
        "validation_rule": field.get("validation_rule") or "",
        "example_values": field.get("example_values") or [],
        "value_shape": {
            "raw_value": None,
            "normalized_value": None,
            "unit": field.get("unit") or "",
            "condition_context": None,
            "evidence_text": None,
            "evidence_location": None,
            "extraction_note": None,
        },
    }


def _nested_field_contract(field: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": field.get("key"),
        "label": field.get("label"),
        "type": field.get("type"),
        "group_key": field.get("group_key"),
        "description": field.get("description") or "",
        "extraction_instruction": field.get("extraction_instruction") or "",
        "required": bool(field.get("required")),
        "missing_policy": field.get("missing_policy") or "missing",
        "evidence_required": bool(field.get("evidence_required")),
        "allowed_values": field.get("allowed_values") or [],
    }


def _sanitize_tree_for_prompt(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for node in nodes or []:
        key = node.get("key")
        if key in {"paper_id", "material_name"}:
            continue
        item = {
            "key": key,
            "label": node.get("label") or key,
            "type": node.get("type") or "string",
            "description": node.get("description") or "",
            "extraction_instruction": node.get("extraction_instruction") or "",
            "required": bool(node.get("required")),
            "evidence_required": bool(node.get("evidence_required", True)),
            "allowed_values": node.get("allowed_values") or [],
            "notes": node.get("notes") or "",
            "order": node.get("order"),
            "children": _sanitize_tree_for_prompt(node.get("children") or []),
        }
        cleaned.append(item)
    return cleaned


def _output_json_contract(record_schema: dict[str, Any], field_contracts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_type": record_schema.get("record_type"),
        "record_unit": record_schema.get("record_unit"),
        "records": [
            {
                "paper_id": "string",
                "record_id": "string",
                "record_type": record_schema.get("record_type"),
                "parent_record_id": None,
                "fields": {
                    field["key"]: {
                        "raw_value": field["value_shape"]["raw_value"],
                        "normalized_value": field["value_shape"]["normalized_value"],
                        "unit": field["value_shape"]["unit"],
                        "condition_context": field["value_shape"]["condition_context"],
                        "evidence_text": field["value_shape"]["evidence_text"],
                        "evidence_location": field["value_shape"]["evidence_location"],
                        "extraction_note": field["value_shape"]["extraction_note"],
                    }
                    for field in field_contracts
                },
            }
        ],
    }


def _nested_output_json_contract(record_schema: dict[str, Any], field_tree: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_type": record_schema.get("record_type"),
        "record_unit": record_schema.get("record_unit"),
        "records": [
            {
                "paper_id": "string",
                "material_name": "string",
                "record_id": "string",
                "record_type": record_schema.get("record_type"),
                "record_identity": {"paper_id": "string", "material_name": "string"},
                "data": _sample_from_tree(field_tree),
            }
        ],
    }


def _sample_from_tree(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for node in nodes:
        key = node.get("key")
        if not key:
            continue
        out[key] = _sample_value(node)
    return out


def _sample_value(node: dict[str, Any]) -> Any:
    node_type = node.get("type")
    if node_type == "object":
        return _sample_from_tree(node.get("children") or [])
    if node_type == "list_object":
        return [_sample_from_tree(node.get("children") or [])]
    if node_type == "list_string":
        return ["string"]
    if node_type == "dict":
        return {"key": "value"}
    if node_type in {"number"}:
        return 0
    if node_type == "boolean":
        return False
    return "string"
