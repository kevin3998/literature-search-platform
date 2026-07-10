from __future__ import annotations

import re
from typing import Any

from .schema_contract import MAX_FIELD_NODES, MAX_KEY_LENGTH, MAX_TREE_DEPTH, PAPER_METADATA_REGISTRY

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_RECORD_UNITS = {"paper_level", "material_level", "sample_level", "experiment_level", "condition_level"}
_ALLOWED_TYPES = {
    "string", "number", "boolean", "enum", "multi_enum", "date", "object",
    "list_object", "list_string", "dict", "evidence_text",
}


def validate_compilation(
    record_schema: dict[str, Any],
    field_tree: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    global_instructions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    unit = record_schema.get("record_unit")
    if unit not in _ALLOWED_RECORD_UNITS:
        errors.append(_error("record_schema.record_unit", "invalid_record_unit", str(unit)))
    identities = list(record_schema.get("record_identity_fields") or [])
    dedup = list(record_schema.get("deduplication_keys") or [])
    if "paper_id" not in identities:
        errors.append(_error("record_schema.record_identity_fields", "paper_id_required", "paper_id must be a record identity field"))
    if unit != "paper_level" and not (set(identities) - {"paper_id"}):
        errors.append(_error("record_schema.record_identity_fields", "non_paper_identity_required", "non-paper records require an entity identity field"))
    if unit == "paper_level" and (set(identities) - {"paper_id"}):
        errors.append(_error("record_schema.record_unit", "paper_level_identity_conflict", "paper-level records cannot declare a separate entity identity"))
    if unit != "paper_level" and record_schema.get("primary_entity") == "paper":
        errors.append(_error("record_schema.primary_entity", "primary_entity_conflicts_with_record_unit", "non-paper records require a non-paper primary entity"))
    if unit != "paper_level" and not record_schema.get("one_paper_may_have_multiple_records"):
        errors.append(_error("record_schema.one_paper_may_have_multiple_records", "multiple_records_required", "non-paper records must allow multiple records per paper"))
    if not set(dedup).issubset(set(identities)):
        errors.append(_error("record_schema.deduplication_keys", "deduplication_identity_mismatch", "deduplication keys must be record identity fields"))
    errors.extend(_validate_tree(field_tree, reserved_keys=set(identities) | {"paper_id"}))
    req_ids = {item.get("requirement_id") for item in requirements}
    mapping_ids = [item.get("requirement_id") for item in mappings]
    for req_id in sorted(req_ids - set(mapping_ids)):
        errors.append(_error(f"requirements.{req_id}", "requirement_mapping_missing", "requirement has no disposition"))
    duplicates = {req_id for req_id in mapping_ids if req_id and mapping_ids.count(req_id) > 1}
    for req_id in sorted(duplicates):
        errors.append(_error(f"requirements.{req_id}", "duplicate_requirement_mapping", "requirement has multiple dispositions"))
    instruction_ids = {item.get("requirement_id") for item in global_instructions}
    field_paths = _field_paths(field_tree)
    for mapping in mappings:
        disposition = mapping.get("disposition")
        target_path = str(mapping.get("target_path") or "")
        if disposition == "global_instruction" and mapping.get("requirement_id") not in instruction_ids:
            errors.append(_error(f"requirements.{mapping.get('requirement_id')}", "global_instruction_missing", "mapped global instruction was not preserved"))
        elif disposition == "system_metadata":
            metadata_key = target_path.removeprefix("paper_metadata.")
            if not target_path.startswith("paper_metadata.") or metadata_key not in PAPER_METADATA_REGISTRY:
                errors.append(_error(f"requirements.{mapping.get('requirement_id')}", "unknown_system_metadata_target", target_path))
        elif disposition == "record_identity":
            identity_key = target_path.removeprefix("record_identity.")
            if not target_path.startswith("record_identity.") or identity_key not in identities:
                errors.append(_error(f"requirements.{mapping.get('requirement_id')}", "unknown_record_identity_target", target_path))
        elif disposition == "user_schema":
            data_path = target_path.removeprefix("data.")
            if not target_path.startswith("data.") or data_path not in field_paths:
                errors.append(_error(f"requirements.{mapping.get('requirement_id')}", "unknown_user_schema_target", target_path))
        elif disposition == "ignored_with_reason" and not str(mapping.get("reason") or "").strip():
            errors.append(_error(f"requirements.{mapping.get('requirement_id')}", "ignore_reason_required", "ignored requirements require a reason"))
    return errors


def _validate_tree(field_tree: list[dict[str, Any]], *, reserved_keys: set[str]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    count = 0
    def visit(nodes: list[dict[str, Any]], prefix: str, depth: int) -> None:
        nonlocal count
        if depth > MAX_TREE_DEPTH:
            errors.append(_error(prefix, "tree_depth_exceeded", f"maximum depth is {MAX_TREE_DEPTH}"))
            return
        sibling_keys: set[str] = set()
        for node in nodes or []:
            count += 1
            key = str(node.get("key") or "")
            path = f"{prefix}.{key}" if prefix else key
            if not _KEY_RE.match(key) or len(key) > MAX_KEY_LENGTH:
                errors.append(_error(path, "invalid_field_key", key))
            if re.fullmatch(r"req_\d+", key, flags=re.IGNORECASE):
                errors.append(_error(path, "internal_requirement_id_not_allowed", key))
            if key in sibling_keys:
                errors.append(_error(path, "duplicate_field_key", key))
            sibling_keys.add(key)
            if key in PAPER_METADATA_REGISTRY or key in reserved_keys:
                errors.append(_error(path, "system_field_in_user_tree", key))
            node_type = node.get("type")
            if node_type not in _ALLOWED_TYPES:
                errors.append(_error(path, "invalid_field_type", str(node_type)))
            children = node.get("children") or []
            if node_type in {"object", "list_object"} and not children:
                errors.append(_error(path, "children_required", str(node_type)))
            if node_type not in {"object", "list_object"} and children:
                errors.append(_error(path, "children_not_allowed", str(node_type)))
            if node_type in {"enum", "multi_enum"} and not node.get("allowed_values"):
                errors.append(_error(path, "allowed_values_required", str(node_type)))
            visit(children, path, depth + 1)
    visit(field_tree, "", 1)
    if count > MAX_FIELD_NODES:
        errors.append(_error("field_tree", "field_node_limit_exceeded", f"maximum nodes is {MAX_FIELD_NODES}"))
    return errors


def _error(path: str, code: str, message: str) -> dict[str, str]:
    return {"path": path, "code": code, "message": message}


def _field_paths(field_tree: list[dict[str, Any]]) -> set[str]:
    paths: set[str] = set()

    def visit(nodes: list[dict[str, Any]], prefix: str = "") -> None:
        for node in nodes or []:
            key = str(node.get("key") or "")
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            visit(node.get("children") or [], path)

    visit(field_tree)
    return paths
