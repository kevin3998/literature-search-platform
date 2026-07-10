from __future__ import annotations

import re
from typing import Any

from core.user_context import UserContext

from .artifacts import append_schema_event, write_schema_draft, write_schema_version
from .schemas import SchemaDraftSaveRequest
from .schema_contract import is_nested_schema_mode
from .store import StructuredExtractionStore, dumps, loads, now

ALLOWED_RECORD_UNITS = {"paper_level", "material_level", "sample_level", "experiment_level", "condition_level"}
ALLOWED_FIELD_TYPES = {
    "string", "number", "boolean", "enum", "multi_enum", "date", "object",
    "list_object", "list_string", "dict", "evidence_text", "list",
}
ALLOWED_SCHEMA_MODES = {"flat_fields", "nested_material", "nested_record"}
ALLOWED_TREE_TYPES = {"string", "number", "boolean", "enum", "multi_enum", "date", "object", "list_object", "list_string", "dict", "evidence_text"}
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class StructuredExtractionSchemaDesigner:
    def __init__(self, store: StructuredExtractionStore) -> None:
        self.store = store

    def get_draft(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        task = self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            "select * from structured_extraction_schema_drafts where task_id = ? and user_id = ?",
            (task_id, user.user_id),
        ).fetchone()
        if row:
            return self._draft_row_to_dict(row)
        ts = now()
        return {
            "task_id": task_id,
            "schema_version": None,
            "base_collection_version": task.get("current_collection_version"),
            "schema_mode": "nested_material",
            "record_schema": _nested_material_record_schema(),
            "field_groups": [],
            "field_tree": [],
            "fields": [],
            "global_instructions": [],
            "source_compilation_id": None,
            "source_compilation_modified": False,
            "status": "draft",
            "validation_errors": [],
            "created_at": ts,
            "updated_at": ts,
            "frozen_at": None,
        }

    def save_draft(
        self,
        task_id: str,
        payload: SchemaDraftSaveRequest,
        *,
        user: UserContext,
        provenance_modified: bool | None = None,
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id, user_id=user.user_id)
        base_collection_version = task.get("current_collection_version")
        if not base_collection_version:
            raise ValueError("collection_required")
        schema_mode = payload.schema_mode if payload.schema_mode in ALLOWED_SCHEMA_MODES else "flat_fields"
        record_schema = _normalize_record_schema(payload.record_schema or {}, schema_mode=schema_mode)
        field_tree = _normalize_field_tree(payload.field_tree or []) if is_nested_schema_mode(schema_mode) else []
        field_groups = _field_groups_from_tree(field_tree) if is_nested_schema_mode(schema_mode) else _normalize_field_groups(payload.field_groups or [])
        fields = _fields_from_tree(field_tree) if is_nested_schema_mode(schema_mode) else _normalize_fields(payload.fields or [])
        global_instructions = _normalize_global_instructions(payload.global_instructions or [])
        if payload.source_compilation_id:
            source = self.store.conn.execute(
                "select compilation_id from structured_extraction_schema_compilations where compilation_id = ? and task_id = ? and user_id = ?",
                (payload.source_compilation_id, task_id, user.user_id),
            ).fetchone()
            if not source:
                raise ValueError("source_compilation_not_found")
        errors = validate_schema(record_schema, field_groups, fields, schema_mode=schema_mode, field_tree=field_tree)
        if errors:
            raise ValueError(",".join(errors))
        existing = self.store.conn.execute(
            "select * from structured_extraction_schema_drafts where task_id = ? and user_id = ?",
            (task_id, user.user_id),
        ).fetchone()
        source_compilation_modified = _source_compilation_modified(
            existing,
            source_compilation_id=payload.source_compilation_id,
            schema_mode=schema_mode,
            record_schema=record_schema,
            field_tree=field_tree,
            global_instructions=global_instructions,
            override=provenance_modified,
        )
        ts = now()
        created_at = existing["created_at"] if existing else ts
        self.store.conn.execute(
            """
            insert into structured_extraction_schema_drafts(
                task_id, user_id, base_collection_version, schema_mode, record_schema_json, field_groups_json,
                field_tree_json, fields_json, global_instructions_json, source_compilation_id, source_compilation_modified,
                validation_errors_json, created_at, updated_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(task_id) do update set
                user_id = excluded.user_id,
                base_collection_version = excluded.base_collection_version,
                schema_mode = excluded.schema_mode,
                record_schema_json = excluded.record_schema_json,
                field_groups_json = excluded.field_groups_json,
                field_tree_json = excluded.field_tree_json,
                fields_json = excluded.fields_json,
                global_instructions_json = excluded.global_instructions_json,
                source_compilation_id = excluded.source_compilation_id,
                source_compilation_modified = excluded.source_compilation_modified,
                validation_errors_json = excluded.validation_errors_json,
                updated_at = excluded.updated_at
            """,
            (
                task_id,
                user.user_id,
                base_collection_version,
                schema_mode,
                dumps(record_schema),
                dumps(field_groups),
                dumps(field_tree),
                dumps(fields),
                dumps(global_instructions),
                payload.source_compilation_id,
                source_compilation_modified,
                dumps([]),
                created_at,
                ts,
            ),
        )
        self._insert_event(task_id, None, user.user_id, "draft_saved", {"field_count": len(fields)}, ts=ts)
        self.store.conn.commit()
        draft = self.get_draft(task_id, user=user)
        write_schema_draft(user, task_id, draft)
        append_schema_event(user, task_id, _event_payload(task_id, None, "draft_saved", {"field_count": len(fields)}, ts))
        return draft

    def freeze(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            "select * from structured_extraction_schema_drafts where task_id = ? and user_id = ?",
            (task_id, user.user_id),
        ).fetchone()
        if not row:
            raise ValueError("schema_draft_required")
        draft = self._draft_row_to_dict(row)
        errors = validate_schema(draft["record_schema"], draft["field_groups"], draft["fields"], schema_mode=draft.get("schema_mode") or "flat_fields", field_tree=draft.get("field_tree") or [])
        if errors:
            raise ValueError(",".join(errors))
        if not draft["fields"]:
            raise ValueError("schema_fields_required")
        schema_version = self._next_schema_version(task_id)
        ts = now()
        field_count = len(draft["fields"])
        self.store.conn.execute(
            """
            insert into structured_extraction_schema_versions(
                task_id, schema_version, user_id, base_collection_version, schema_mode, record_schema_json,
                field_groups_json, field_tree_json, fields_json, global_instructions_json, source_compilation_id, source_compilation_modified,
                field_count, change_summary_json, created_at, frozen_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                schema_version,
                user.user_id,
                draft["base_collection_version"],
                draft.get("schema_mode") or "flat_fields",
                dumps(draft["record_schema"]),
                dumps(draft["field_groups"]),
                dumps(draft.get("field_tree") or []),
                dumps(draft["fields"]),
                dumps(draft.get("global_instructions") or []),
                draft.get("source_compilation_id"),
                bool(draft.get("source_compilation_modified")),
                field_count,
                dumps({
                    "source": "draft",
                    "field_count": field_count,
                    "source_compilation_id": draft.get("source_compilation_id"),
                    "source_compilation_modified": bool(draft.get("source_compilation_modified")),
                }),
                ts,
                ts,
            ),
        )
        self._insert_event(task_id, schema_version, user.user_id, "schema_frozen", {"field_count": field_count}, ts=ts)
        self.store.conn.commit()
        version = self.get_version(task_id, schema_version, user=user)
        write_schema_version(user, task_id, version)
        append_schema_event(user, task_id, _event_payload(task_id, schema_version, "schema_frozen", {"field_count": field_count}, ts))
        self.store.update_schema_state(task_id, user=user, schema_version=schema_version, field_count=field_count)
        return version

    def list_versions(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_schema_versions
            where task_id = ? and user_id = ?
            order by created_at desc
            """,
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "versions": [self._version_row_to_dict(row) for row in rows]}

    def get_version(self, task_id: str, schema_version: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            """
            select * from structured_extraction_schema_versions
            where task_id = ? and user_id = ? and schema_version = ?
            """,
            (task_id, user.user_id, schema_version),
        ).fetchone()
        if not row:
            raise KeyError(f"schema version not found: {schema_version}")
        return self._version_row_to_dict(row)

    def duplicate_to_draft(self, task_id: str, schema_version: str, *, user: UserContext) -> dict[str, Any]:
        version = self.get_version(task_id, schema_version, user=user)
        payload = SchemaDraftSaveRequest(
            schema_mode=version.get("schema_mode") or "flat_fields",
            record_schema=version["record_schema"],
            field_groups=version["field_groups"],
            field_tree=version.get("field_tree") or [],
            fields=version["fields"],
            global_instructions=version.get("global_instructions") or [],
            source_compilation_id=version.get("source_compilation_id"),
        )
        draft = self.save_draft(
            task_id,
            payload,
            user=user,
            provenance_modified=bool(version.get("source_compilation_modified")),
        )
        ts = now()
        self._insert_event(task_id, schema_version, user.user_id, "version_duplicated_to_draft", {}, ts=ts)
        self.store.conn.commit()
        append_schema_event(user, task_id, _event_payload(task_id, schema_version, "version_duplicated_to_draft", {}, ts))
        return draft

    def _next_schema_version(self, task_id: str) -> str:
        rows = self.store.conn.execute(
            "select schema_version from structured_extraction_schema_versions where task_id = ?",
            (task_id,),
        ).fetchall()
        max_n = 0
        for row in rows:
            match = re.match(r"^schema_v(\d+)$", row["schema_version"] or "")
            if match:
                max_n = max(max_n, int(match.group(1)))
        return f"schema_v{max_n + 1}"

    def _insert_event(
        self,
        task_id: str,
        schema_version: str | None,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        ts: float | None = None,
    ) -> None:
        self.store.conn.execute(
            """
            insert into structured_extraction_schema_events(task_id, schema_version, user_id, event_type, payload_json, created_at)
            values(?, ?, ?, ?, ?, ?)
            """,
            (task_id, schema_version, user_id, event_type, dumps(payload), ts or now()),
        )

    @staticmethod
    def _draft_row_to_dict(row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "schema_version": None,
            "base_collection_version": row["base_collection_version"],
            "schema_mode": row["schema_mode"] if "schema_mode" in row.keys() else "flat_fields",
            "record_schema": loads(row["record_schema_json"], {}) or {},
            "field_groups": loads(row["field_groups_json"], []) or [],
            "field_tree": loads(row["field_tree_json"], []) if "field_tree_json" in row.keys() else [],
            "fields": loads(row["fields_json"], []) or [],
            "global_instructions": loads(row["global_instructions_json"], []) if "global_instructions_json" in row.keys() else [],
            "source_compilation_id": str(row["source_compilation_id"]) if "source_compilation_id" in row.keys() and row["source_compilation_id"] else None,
            "source_compilation_modified": bool(row["source_compilation_modified"]) if "source_compilation_modified" in row.keys() else False,
            "status": "draft",
            "validation_errors": loads(row["validation_errors_json"], []) or [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "frozen_at": None,
        }

    @staticmethod
    def _version_row_to_dict(row) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "schema_version": row["schema_version"],
            "base_collection_version": row["base_collection_version"],
            "schema_mode": row["schema_mode"] if "schema_mode" in row.keys() else "flat_fields",
            "record_schema": loads(row["record_schema_json"], {}) or {},
            "field_groups": loads(row["field_groups_json"], []) or [],
            "field_tree": loads(row["field_tree_json"], []) if "field_tree_json" in row.keys() else [],
            "fields": loads(row["fields_json"], []) or [],
            "global_instructions": loads(row["global_instructions_json"], []) if "global_instructions_json" in row.keys() else [],
            "source_compilation_id": str(row["source_compilation_id"]) if "source_compilation_id" in row.keys() and row["source_compilation_id"] else None,
            "source_compilation_modified": bool(row["source_compilation_modified"]) if "source_compilation_modified" in row.keys() else False,
            "field_count": row["field_count"],
            "change_summary": loads(row["change_summary_json"], {}) or {},
            "status": "frozen",
            "validation_errors": [],
            "created_at": row["created_at"],
            "updated_at": row["frozen_at"],
            "frozen_at": row["frozen_at"],
        }


def _source_compilation_modified(
    existing,
    *,
    source_compilation_id: str | None,
    schema_mode: str,
    record_schema: dict[str, Any],
    field_tree: list[dict[str, Any]],
    global_instructions: list[dict[str, Any]],
    override: bool | None,
) -> bool:
    if override is not None:
        return bool(override)
    if not source_compilation_id:
        return False
    if not existing or not existing["source_compilation_id"] or str(existing["source_compilation_id"]) != str(source_compilation_id):
        return True
    previous = (
        existing["schema_mode"],
        loads(existing["record_schema_json"], {}) or {},
        loads(existing["field_tree_json"], []) or [],
        loads(existing["global_instructions_json"], []) or [],
    )
    current = (schema_mode, record_schema, field_tree, global_instructions)
    already_modified = bool(existing["source_compilation_modified"]) if "source_compilation_modified" in existing.keys() else False
    return already_modified or previous != current


def validate_schema(record_schema: dict[str, Any], field_groups: list[dict[str, Any]], fields: list[dict[str, Any]], *, schema_mode: str = "flat_fields", field_tree: list[dict[str, Any]] | None = None) -> list[str]:
    errors: list[str] = []
    if schema_mode not in ALLOWED_SCHEMA_MODES:
        errors.append("invalid_schema_mode")
    record_type = record_schema.get("record_type") or ""
    if record_type and not _KEY_RE.match(record_type):
        errors.append("invalid_record_type")
    if record_schema.get("record_unit") not in ALLOWED_RECORD_UNITS:
        errors.append("invalid_record_unit")
    record_unit = record_schema.get("record_unit")
    identity_fields = set(record_schema.get("record_identity_fields") or [])
    deduplication_keys = set(record_schema.get("deduplication_keys") or [])
    primary_entity = (record_schema.get("primary_entity") or "").strip()
    if is_nested_schema_mode(schema_mode):
        tree_errors = _validate_field_tree(field_tree or [], reserved_keys=identity_fields | {"paper_id"})
        errors.extend(tree_errors)
    if schema_mode == "nested_material":
        if record_schema.get("record_type") != "material_record":
            errors.append("nested_material_record_type_required")
        if record_schema.get("record_unit") != "material_level":
            errors.append("nested_material_record_unit_required")
        if primary_entity != "material":
            errors.append("nested_material_primary_entity_required")
        if "material_name" not in identity_fields:
            errors.append("nested_material_identity_requires_material_name")
        if "material_name" not in deduplication_keys:
            errors.append("nested_material_deduplication_requires_material_name")
        if any(node.get("key") in {"paper_id", "material_name"} for node in (field_tree or [])):
            errors.append("nested_material_field_tree_must_not_include_identity_fields")
    if record_unit and record_unit != "paper_level":
        if not (identity_fields - {"paper_id"}):
            errors.append("record_identity_requires_non_paper_key")
        if not (deduplication_keys - {"paper_id"}):
            errors.append("deduplication_requires_non_paper_key")
        if primary_entity == "paper":
            errors.append("primary_entity_conflicts_with_record_unit")
        if not record_schema.get("one_paper_may_have_multiple_records"):
            errors.append("non_paper_record_requires_multiple_records_enabled")
    group_keys: set[str] = set()
    for group in field_groups:
        key = group.get("group_key") or ""
        if not _KEY_RE.match(key):
            errors.append(f"invalid_group_key:{key}")
        if key in group_keys:
            errors.append(f"duplicate_group_key:{key}")
        group_keys.add(key)
    field_keys: set[str] = set()
    for field in fields:
        key = field.get("key") or ""
        if not _KEY_RE.match(key):
            errors.append(f"invalid_field_key:{key}")
        if key in field_keys:
            errors.append(f"duplicate_field_key:{key}")
        field_keys.add(key)
        field_type = field.get("type") or ""
        if field_type not in ALLOWED_FIELD_TYPES:
            errors.append(f"invalid_field_type:{field_type}")
        group_key = field.get("group_key") or ""
        if group_key and group_key not in group_keys:
            errors.append(f"unknown_group_key:{group_key}")
    return errors


def _validate_field_tree(nodes: list[dict[str, Any]], *, reserved_keys: set[str], path: str = "") -> list[str]:
    errors: list[str] = []
    keys: set[str] = set()
    for node in nodes:
        key = node.get("key") or ""
        node_path = f"{path}.{key}" if path else key
        if key in reserved_keys:
            errors.append(f"identity_field_not_allowed_in_tree:{node_path}")
        if re.fullmatch(r"req_\d+", key, flags=re.IGNORECASE):
            errors.append(f"internal_requirement_id_not_allowed:{node_path}")
        if not _KEY_RE.match(key):
            errors.append(f"invalid_tree_key:{node_path}")
        if key in keys:
            errors.append(f"duplicate_tree_key:{node_path}")
        keys.add(key)
        node_type = node.get("type") or ""
        if node_type not in ALLOWED_TREE_TYPES:
            errors.append(f"invalid_tree_type:{node_path}:{node_type}")
        children = node.get("children") or []
        if node_type in {"object", "list_object"} and not children:
            errors.append(f"tree_node_requires_children:{node_path}")
        if children:
            errors.extend(_validate_field_tree(children, reserved_keys=reserved_keys, path=node_path))
    return errors


def _default_record_schema() -> dict[str, Any]:
    return {
        "record_type": "paper_record",
        "record_unit": "paper_level",
        "primary_entity": "paper",
        "one_paper_may_have_multiple_records": False,
        "record_identity_fields": ["paper_id"],
        "deduplication_keys": ["paper_id"],
        "parent_record_type": None,
    }


def _nested_material_record_schema() -> dict[str, Any]:
    return {
        "record_type": "material_record",
        "record_unit": "material_level",
        "primary_entity": "material",
        "one_paper_may_have_multiple_records": True,
        "record_identity_fields": ["paper_id", "material_name"],
        "deduplication_keys": ["paper_id", "material_name"],
        "parent_record_type": None,
    }


def _normalize_record_schema(raw: dict[str, Any], *, schema_mode: str = "flat_fields") -> dict[str, Any]:
    base = _nested_material_record_schema() if schema_mode == "nested_material" else _default_record_schema()
    base.update(raw or {})
    if schema_mode == "nested_material":
        base.update(_nested_material_record_schema())
    base["record_type"] = str(base.get("record_type") or "").strip()
    base["record_unit"] = str(base.get("record_unit") or "").strip()
    base["primary_entity"] = str(base.get("primary_entity") or "").strip()
    base["one_paper_may_have_multiple_records"] = bool(base.get("one_paper_may_have_multiple_records"))
    base["record_identity_fields"] = _string_list(base.get("record_identity_fields"))
    base["deduplication_keys"] = _string_list(base.get("deduplication_keys"))
    base["parent_record_type"] = str(base.get("parent_record_type") or "").strip() or None
    return base


def _normalize_global_instructions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for index, item in enumerate(items or [], start=1):
        text_value = str(item.get("text") or "").strip()
        if not text_value:
            continue
        requirement_id = str(item.get("requirement_id") or f"manual_instruction_{index}")
        if requirement_id in seen:
            continue
        seen.add(requirement_id)
        category = str(item.get("category") or "extraction")
        if category not in {"selection", "grouping", "extraction", "constraint", "other"}:
            category = "other"
        out.append({"requirement_id": requirement_id, "category": category, "text": text_value})
    return out


def _tree_node(key: str, label: str, node_type: str, *, order: int, required: bool = False, description: str = "", instruction: str = "", allowed_values: list[str] | None = None, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": node_type,
        "description": description,
        "extraction_instruction": instruction,
        "required": required,
        "evidence_required": True,
        "allowed_values": allowed_values or [],
        "unit": "",
        "example_values": [],
        "notes": "",
        "order": order,
        "children": children or [],
    }


def _normalize_field_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [_normalize_tree_node(node, idx + 1) for idx, node in enumerate(nodes or [])]
    out = [node for node in out if node["key"] not in {"paper_id", "material_name"}]
    out = sorted(out, key=lambda item: item["order"])
    return _renumber(out)


def _normalize_tree_node(node: dict[str, Any], order: int) -> dict[str, Any]:
    node_type = str(node.get("type") or "string").strip()
    children = [
        child
        for child in (_normalize_tree_node(child, idx + 1) for idx, child in enumerate(node.get("children") or []))
        if child["key"] not in {"paper_id", "material_name"}
    ]
    return {
        "key": str(node.get("key") or "").strip(),
        "label": str(node.get("label") or node.get("key") or "").strip(),
        "type": node_type,
        "description": str(node.get("description") or ""),
        "extraction_instruction": str(node.get("extraction_instruction") or node.get("extractionInstruction") or ""),
        "required": bool(node.get("required")),
        "evidence_required": bool(node.get("evidence_required", node.get("evidenceRequired", True))),
        "allowed_values": _string_list(node.get("allowed_values") or node.get("allowedValues")),
        "unit": str(node.get("unit") or ""),
        "validation_rule": str(node.get("validation_rule") or node.get("validationRule") or ""),
        "example_values": _string_list(node.get("example_values") or node.get("exampleValues")),
        "notes": str(node.get("notes") or ""),
        "order": _int(node.get("order"), order),
        "children": sorted(children, key=lambda item: item["order"]),
        "source_requirement_ids": _string_list(node.get("source_requirement_ids") or node.get("sourceRequirementIds")),
        "origin": str(node.get("origin") or "manual"),
        "confidence": node.get("confidence"),
    }


def _renumber(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for idx, node in enumerate(nodes, start=1):
        item = dict(node)
        item["order"] = idx
        item["children"] = _renumber(item.get("children") or [])
        out.append(item)
    return out


def _field_groups_from_tree(field_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "group_key": node["key"],
            "label": node.get("label") or node["key"],
            "description": node.get("description") or "",
            "order": node.get("order") or idx + 1,
        }
        for idx, node in enumerate(field_tree)
    ]


def _fields_from_tree(field_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = []
    for idx, node in enumerate(field_tree, start=1):
        fields.append(
            {
                "key": node["key"],
                "label": node.get("label") or node["key"],
                "type": "object" if node.get("type") in {"object", "list_object", "dict"} else node.get("type", "string"),
                "group_key": node["key"],
                "description": node.get("description") or "",
                "extraction_instruction": node.get("extraction_instruction") or "",
                "required": bool(node.get("required")),
                "missing_policy": "missing",
                "evidence_required": bool(node.get("evidence_required", True)),
                "allowed_values": node.get("allowed_values") or [],
                "unit": node.get("unit") or "",
                "validation_rule": node.get("validation_rule") or "",
                "example_values": node.get("example_values") or [],
                "notes": node.get("notes") or "",
                "order": idx,
            }
        )
    return fields


def _normalize_field_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for idx, group in enumerate(groups):
        out.append(
            {
                "group_key": str(group.get("group_key") or "").strip(),
                "label": str(group.get("label") or "").strip(),
                "description": str(group.get("description") or ""),
                "order": _int(group.get("order"), idx + 1),
            }
        )
    return sorted(out, key=lambda item: item["order"])


def _normalize_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for idx, field in enumerate(fields):
        out.append(
            {
                "key": str(field.get("key") or "").strip(),
                "label": str(field.get("label") or "").strip(),
                "type": str(field.get("type") or "string").strip(),
                "group_key": str(field.get("group_key") or "").strip(),
                "description": str(field.get("description") or ""),
                "extraction_instruction": str(field.get("extraction_instruction") or ""),
                "required": bool(field.get("required")),
                "missing_policy": str(field.get("missing_policy") or "missing"),
                "evidence_required": bool(field.get("evidence_required", True)),
                "allowed_values": _string_list(field.get("allowed_values")),
                "unit": str(field.get("unit") or ""),
                "validation_rule": str(field.get("validation_rule") or ""),
                "example_values": _string_list(field.get("example_values")),
                "notes": str(field.get("notes") or ""),
                "order": _int(field.get("order"), idx + 1),
            }
        )
    return sorted(out, key=lambda item: item["order"])


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _event_payload(task_id: str, schema_version: str | None, event_type: str, payload: dict[str, Any], ts: float) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "schema_version": schema_version,
        "event_type": event_type,
        "payload": payload,
        "created_at": ts,
    }
