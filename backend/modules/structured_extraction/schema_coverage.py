from __future__ import annotations

from typing import Any

from .schema_contract import paper_metadata_aliases
from .schema_normalizer import slugify_key


def derive_requirement_mappings(
    requirements: list[dict[str, Any]],
    field_tree: list[dict[str, Any]],
    record_schema: dict[str, Any],
    model_mappings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    model_by_id = {str(item.get("requirement_id")): dict(item) for item in (model_mappings or []) if item.get("requirement_id")}
    field_paths = _field_requirement_paths(field_tree)
    identities = set(record_schema.get("record_identity_fields") or [])
    metadata_aliases = paper_metadata_aliases()
    mappings: list[dict[str, Any]] = []
    for requirement in requirements:
        req_id = requirement["requirement_id"]
        proposed = model_by_id.get(req_id)
        if proposed and proposed.get("disposition") in {
            "user_schema", "system_metadata", "record_identity", "constraint", "global_instruction", "ignored_with_reason", "unresolved"
        }:
            mappings.append(_clean_mapping(proposed, requirement))
            continue
        raw_key = slugify_key(requirement.get("raw_name"), fallback="")
        kind = requirement.get("kind")
        if raw_key in metadata_aliases:
            mappings.append({"requirement_id": req_id, "disposition": "system_metadata", "target_path": f"paper_metadata.{metadata_aliases[raw_key]}", "reason": "provided_by_platform"})
        elif raw_key in identities:
            mappings.append({"requirement_id": req_id, "disposition": "record_identity", "target_path": f"record_identity.{raw_key}", "reason": "record_identity_field"})
        elif req_id in field_paths:
            mappings.append({"requirement_id": req_id, "disposition": "user_schema", "target_path": f"data.{field_paths[req_id]}", "reason": "source_declared_field"})
        elif kind in {"global_instruction", "selection_rule", "grouping_rule"}:
            mappings.append({"requirement_id": req_id, "disposition": "global_instruction", "target_path": "global_instructions", "reason": "instruction_requirement"})
        elif kind == "constraint":
            mappings.append({"requirement_id": req_id, "disposition": "constraint", "target_path": requirement.get("source_path") or "", "reason": "constraint_requirement"})
        else:
            mappings.append({"requirement_id": req_id, "disposition": "unresolved", "target_path": "", "reason": "no_deterministic_mapping"})
    return mappings


def coverage_report(requirements: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> dict[str, Any]:
    mapping_by_id = {item.get("requirement_id"): item for item in mappings}
    unresolved = []
    resolved = 0
    for requirement in requirements:
        mapping = mapping_by_id.get(requirement["requirement_id"])
        if not mapping or mapping.get("disposition") == "unresolved":
            unresolved.append(requirement["requirement_id"])
        else:
            resolved += 1
    total = len(requirements)
    return {
        "total": total,
        "resolved": resolved,
        "unresolved": len(unresolved),
        "ratio": round(resolved / total, 6) if total else 1.0,
        "unresolved_requirement_ids": unresolved,
    }


def _field_requirement_paths(field_tree: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    def visit(nodes: list[dict[str, Any]], prefix: str = "") -> None:
        for node in nodes or []:
            path = f"{prefix}.{node['key']}" if prefix else node["key"]
            for req_id in node.get("source_requirement_ids") or []:
                out[str(req_id)] = path
            visit(node.get("children") or [], path)
    visit(field_tree)
    return out


def _clean_mapping(mapping: dict[str, Any], requirement: dict[str, Any]) -> dict[str, Any]:
    disposition = mapping.get("disposition") or "unresolved"
    reason = str(mapping.get("reason") or "model_mapping")
    if disposition == "ignored_with_reason" and not reason.strip():
        disposition = "unresolved"
        reason = "ignore_reason_required"
    return {
        "requirement_id": requirement["requirement_id"],
        "disposition": disposition,
        "target_path": str(mapping.get("target_path") or ""),
        "reason": reason,
    }
