from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .schema_contract import MAX_KEY_LENGTH, PAPER_METADATA_REGISTRY

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_TYPE_ALIASES = {
    "array": "list_string",
    "array_string": "list_string",
    "array_object": "list_object",
    "list": "list_string",
    "list_of_strings": "list_string",
    "list_of_objects": "list_object",
    "map": "dict",
    "dictionary": "dict",
    "integer": "number",
    "float": "number",
}
_ALLOWED_TYPES = {
    "string", "number", "boolean", "enum", "multi_enum", "date", "object",
    "list_object", "list_string", "dict", "evidence_text",
}
_ALLOWED_RECORD_UNITS = {"paper_level", "material_level", "sample_level", "experiment_level", "condition_level"}


def slugify_key(value: Any, *, fallback: str = "field") -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*\d+[\).:-]?\s*", "", text)
    text = _CAMEL_BOUNDARY_RE.sub(r"\1_\2", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    if not text:
        text = fallback
    if not text:
        return ""
    if not text[0].isalpha():
        text = f"field_{text}"
    return text[:MAX_KEY_LENGTH] if _KEY_RE.match(text[:MAX_KEY_LENGTH]) else fallback


def normalize_record_schema(raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = dict(raw or {})
    changes: list[dict[str, Any]] = []
    record_unit = str(source.get("record_unit") or source.get("recordUnit") or "paper_level")
    if record_unit not in _ALLOWED_RECORD_UNITS:
        changes.append({"path": "record_schema.record_unit", "action": "normalized_record_unit", "before": record_unit, "after": "paper_level"})
        record_unit = "paper_level"
    primary_entity = slugify_key(source.get("primary_entity") or source.get("primaryEntity") or record_unit.removesuffix("_level"), fallback="paper")
    default_identity = ["paper_id"] if record_unit == "paper_level" else ["paper_id", f"{primary_entity}_name"]
    identity = [slugify_key(item, fallback="identity") for item in (source.get("record_identity_fields") or source.get("recordIdentityFields") or default_identity)]
    dedup = [slugify_key(item, fallback="identity") for item in (source.get("deduplication_keys") or source.get("deduplicationKeys") or identity)]
    out = {
        "record_type": slugify_key(source.get("record_type") or source.get("recordType") or f"{primary_entity}_record", fallback="record"),
        "record_unit": record_unit,
        "primary_entity": primary_entity,
        "one_paper_may_have_multiple_records": bool(source.get("one_paper_may_have_multiple_records", source.get("onePaperMayHaveMultipleRecords", record_unit != "paper_level"))),
        "record_identity_fields": list(dict.fromkeys(identity)),
        "deduplication_keys": list(dict.fromkeys(dedup)),
        "parent_record_type": source.get("parent_record_type") or source.get("parentRecordType") or None,
    }
    if source and out != source:
        changes.append({"path": "record_schema", "action": "normalized_record_schema"})
    return out, changes


def normalize_field_tree(raw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = extract_field_tree(raw)
    changes: list[dict[str, Any]] = []
    return _normalize_siblings(nodes, changes=changes, path=""), changes


def extract_field_tree(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []
    for key in ("field_tree", "fieldTree", "fields", "properties"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [{"key": name, **(spec if isinstance(spec, dict) else {"type": "string"})} for name, spec in value.items()]
    result = raw.get("result")
    return extract_field_tree(result) if result is not None else []


def _normalize_siblings(nodes: list[dict[str, Any]], *, changes: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, node in enumerate(nodes or [], start=1):
        before_key = node.get("key")
        base = slugify_key(before_key or node.get("name") or node.get("label"), fallback=f"field_{index}")
        key = base
        suffix = 2
        while key in used:
            key = f"{base[: max(1, MAX_KEY_LENGTH - len(str(suffix)) - 1)]}_{suffix}"
            suffix += 1
        used.add(key)
        node_path = f"{path}.{key}" if path else key
        if before_key != key:
            changes.append({"path": node_path, "action": "normalized_key", "before": before_key, "after": key})
        raw_children = node.get("children") or node.get("properties") or node.get("items") or []
        if isinstance(raw_children, dict):
            raw_children = [{"key": child_key, **(child if isinstance(child, dict) else {})} for child_key, child in raw_children.items()]
        children = _normalize_siblings([item for item in raw_children if isinstance(item, dict)], changes=changes, path=node_path)
        raw_type = str(node.get("type") or "").strip().lower().replace(" ", "_")
        node_type = _TYPE_ALIASES.get(raw_type, raw_type)
        if children and node_type not in {"object", "list_object"}:
            node_type = "object"
        if not node_type:
            node_type = "object" if children else "string"
        if node_type not in _ALLOWED_TYPES:
            changes.append({"path": node_path, "action": "normalized_type", "before": raw_type, "after": "string"})
            node_type = "string"
        allowed_values = node.get("allowed_values") or node.get("allowedValues") or node.get("enum") or []
        if not isinstance(allowed_values, list):
            allowed_values = []
        source_ids = node.get("source_requirement_ids") or node.get("sourceRequirementIds") or []
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        item = {
            "key": key,
            "label": str(node.get("label") or node.get("name") or key).strip(),
            "type": node_type,
            "description": str(node.get("description") or ""),
            "extraction_instruction": str(node.get("extraction_instruction") or node.get("extractionInstruction") or ""),
            "required": bool(node.get("required")),
            "evidence_required": bool(node.get("evidence_required", node.get("evidenceRequired", True))),
            "allowed_values": [str(value) for value in allowed_values],
            "notes": str(node.get("notes") or ""),
            "order": index,
            "children": children,
            "source_requirement_ids": [str(value) for value in source_ids if value],
            "origin": node.get("origin") if node.get("origin") in {"source_declared", "model_suggested", "manual"} else "source_declared",
            "confidence": node.get("confidence"),
        }
        out.append(item)
    return out


def remove_record_identity_nodes(
    field_tree: list[dict[str, Any]],
    record_schema: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reserved = set(record_schema.get("record_identity_fields") or []) | {"paper_id", *PAPER_METADATA_REGISTRY}
    changes: list[dict[str, Any]] = []

    def visit(nodes: list[dict[str, Any]], prefix: str = "") -> list[dict[str, Any]]:
        out = []
        for node in nodes or []:
            key = str(node.get("key") or "")
            path = f"{prefix}.{key}" if prefix else key
            if key in reserved:
                changes.append({"path": path, "action": "moved_to_record_identity", "before": key})
                continue
            item = dict(node)
            item["children"] = visit(item.get("children") or [], path)
            out.append(item)
        return out

    return visit(field_tree), changes


def field_tree_hash(field_tree: list[dict[str, Any]]) -> str:
    payload = json.dumps(field_tree, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
