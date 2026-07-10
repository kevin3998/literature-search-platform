from __future__ import annotations

import json
import re
from typing import Any

from core.llm import LLMUnavailable, build_llm_client
from core.settings_store import settings_store
from core.user_context import UserContext

from .schemas import SchemaAssistRequest
from .schema_compiler import ProgressCallback, compile_schema_definition


class EmptyLLMOutput(RuntimeError):
    pass


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")


async def assist_schema(
    payload: SchemaAssistRequest,
    *,
    task: dict[str, Any],
    user: UserContext,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    try:
        llm = build_llm_client(settings_store, user_id=user.user_id)
    except LLMUnavailable:
        if payload.action == "parse_field_definition":
            result = await compile_schema_definition(
                instruction=payload.instruction,
                source_format=payload.source_format,
                draft=payload.draft,
                task=task,
                generate_structured=None,
                on_progress=on_progress,
            )
            return {
                "available": bool(result.get("field_tree")),
                "action": payload.action,
                "status": result["status"],
                "reason": "llm_unavailable",
                "result": result,
                "model_profile_id": None,
            }
        return {"available": False, "reason": "llm_unavailable"}
    if payload.action == "parse_field_definition":
        result = await compile_schema_definition(
            instruction=payload.instruction,
            source_format=payload.source_format,
            draft=payload.draft,
            task=task,
            generate_structured=llm.generate_structured,
            on_progress=on_progress,
        )
        return {
            "available": result["status"] != "llm_unavailable",
            "action": payload.action,
            "status": result["status"],
            "result": result,
            "model_profile_id": (task.get("model_settings") or {}).get("schema_assist_profile_id"),
        }
    prompt = _prompt(payload, task=task)
    try:
        text = await _collect_text(llm, [{"role": "user", "content": prompt}])
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": "llm_unavailable", "detail": str(exc)}
    try:
        data = _parse_json(text)
        return {
            "available": True,
            "action": payload.action,
            "result": _normalize_result(payload.action, data),
            "model_profile_id": (task.get("model_settings") or {}).get("schema_assist_profile_id"),
        }
    except EmptyLLMOutput as exc:
        return {"available": False, "reason": "llm_unavailable", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": "llm_output_invalid", "detail": str(exc)}


def _prompt(payload: SchemaAssistRequest, *, task: dict[str, Any]) -> str:
    return (
        "You are assisting a structured literature extraction schema designer. "
        "Return strict JSON only. Do not run extraction. Provide schema suggestions that a user can review before saving.\n\n"
        f"Task name: {task.get('name')}\n"
        f"Current collection version: {task.get('current_collection_version')}\n"
        f"Action: {payload.action}\n"
        f"Instruction: {payload.instruction or ''}\n"
        f"Draft: {json.dumps(payload.draft or {}, ensure_ascii=False)}\n"
        f"Field: {json.dumps(payload.field or {}, ensure_ascii=False)}\n"
        f"Fields: {json.dumps(payload.fields or [], ensure_ascii=False)}\n\n"
        "For suggest_fields, return {\"field_groups\": [...], \"fields\": [...]}.\n"
        "For rewrite_field, return {\"field\": {...}}.\n"
        "For split_field, return {\"fields\": [...], \"change_note\": \"...\"}.\n"
        "For merge_fields, return {\"field\": {...}, \"change_note\": \"...\"}.\n"
        "For generate_examples, return {\"examples\": [\"...\"]}.\n"
        "For parse_field_definition, convert the user's pasted field definition into nested_material schema JSON: "
        "{\"schema_mode\":\"nested_material\",\"field_tree\":[...],\"warnings\":[],\"summary\":{...}}. "
        "Use lower snake_case keys. Preserve nested semantics and keep leaf values as native JSON. "
        "Use object for grouped properties, list_object for repeated objects, "
        "list_string for repeated strings, and dict for dynamic key/value maps such as rejections, test_parameters, and key_technical_parameters. "
        "Do not wrap leaves in raw_value/evidence/unit containers. Do not normalize units or standardize values. "
        "Do not add unit constraints. Do not add example_values. "
        "Do not include paper_id or material_name in field_tree; they are fixed system identity fields outside user-defined data."
    )


def _normalize_result(action: str, data: dict[str, Any]) -> dict[str, Any]:
    if action != "parse_field_definition":
        return data
    field_tree = _normalize_field_tree(data.get("field_tree") or data.get("fieldTree") or [])
    return {
        "schema_mode": data.get("schema_mode") or data.get("schemaMode") or "nested_material",
        "field_tree": field_tree,
        "warnings": data.get("warnings") or [],
        "summary": data.get("summary") or _tree_summary(field_tree),
    }


def _normalize_field_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    used_keys: set[str] = set()
    for index, node in enumerate(nodes or [], start=1):
        if not isinstance(node, dict):
            continue
        key = _unique_key(_node_key(node, fallback=f"field_{index}"), used_keys)
        if key in {"paper_id", "material_name"}:
            continue
        item = dict(node)
        item["key"] = key
        item["label"] = str(item.get("label") or item.get("name") or key).strip()
        item.pop("unit", None)
        item.pop("example_values", None)
        item.pop("exampleValues", None)
        item["children"] = _normalize_field_tree(item.get("children") or [])
        out.append(item)
    return out


def _node_key(node: dict[str, Any], *, fallback: str) -> str:
    for field in ("key", "name", "label"):
        key = _slugify_key(node.get(field))
        if key:
            return key
    return fallback


def _slugify_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*\d+[\).:-]?\s*", "", text)
    text = _CAMEL_BOUNDARY_RE.sub(r"\1_\2", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    if not text:
        return ""
    if not text[0].isalpha():
        text = f"field_{text}"
    return text if _KEY_RE.match(text) else ""


def _unique_key(key: str, used_keys: set[str]) -> str:
    base = key or "field"
    candidate = base
    suffix = 2
    while candidate in used_keys:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_keys.add(candidate)
    return candidate


def _tree_summary(nodes: list[dict[str, Any]]) -> dict[str, int]:
    top = len(nodes or [])
    leaf = 0
    objects = 0
    list_objects = 0
    stack = list(nodes or [])
    while stack:
        node = stack.pop()
        children = node.get("children") or []
        node_type = node.get("type")
        if node_type == "object":
            objects += 1
        if node_type == "list_object":
            list_objects += 1
        if children:
            stack.extend(children)
        else:
            leaf += 1
    return {"top_level_sections": top, "leaf_count": leaf, "nested_object_count": objects, "list_object_count": list_objects}


async def _collect_text(llm, messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    async for event in llm.stream_chat(messages, tools=None):
        if event.get("type") == "content" and event.get("text"):
            chunks.append(event["text"])
    return "".join(chunks)


def _parse_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise EmptyLLMOutput("empty LLM output")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM output must be a JSON object")
    return value
