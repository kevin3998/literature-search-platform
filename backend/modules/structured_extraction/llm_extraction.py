from __future__ import annotations

import json
import re
from typing import Any

from core.llm import LLMUnavailable, build_llm_client
from core.settings_store import settings_store


async def extract_packet_item(
    *,
    task: dict[str, Any],
    contract: dict[str, Any],
    packet_item: dict[str, Any],
    user_id: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    prompt = build_item_prompt(task=task, contract=contract, packet_item=packet_item)
    try:
        llm = build_llm_client(settings_store, strong=True, user_id=user_id)
    except LLMUnavailable as exc:
        raise LLMUnavailable("llm_unavailable") from exc
    raw = await _collect_text(llm, prompt["messages"])
    parsed = parse_extraction_json(raw)
    return prompt, raw, parsed


def model_snapshot(*, user_id: str | None = None) -> dict[str, Any]:
    try:
        config = settings_store.model_config(user_id=user_id)
    except Exception:  # noqa: BLE001
        config = {}
    strong_model = config.get("strong_model")
    chat_model = config.get("chat_model")
    return {
        "provider": config.get("provider") or "none",
        "model": strong_model or chat_model or "",
        "strong": bool(strong_model),
    }


def build_item_prompt(*, task: dict[str, Any], contract: dict[str, Any], packet_item: dict[str, Any]) -> dict[str, Any]:
    field_keys = set(packet_item.get("field_keys") or [])
    field_contracts = [field for field in (contract.get("field_contracts") or []) if field.get("key") in field_keys]
    schema_mode = contract.get("schema_mode") or "flat_fields"
    section_contract = None
    if schema_mode == "nested_material":
        section_contract = next((section for section in (contract.get("section_contracts") or []) if section.get("section_key") == packet_item.get("field_group")), None)
    payload = {
        "task": {"task_id": task.get("task_id"), "name": task.get("name")},
        "record_contract": contract.get("record_contract") or {},
        "field_contracts": field_contracts,
        "schema_mode": schema_mode,
        "section_contract": section_contract,
        "schema_tree_contract": contract.get("schema_tree_contract") or [],
        "output_json_contract": contract.get("output_json_contract") or {},
        "extraction_rules": contract.get("extraction_rules") or [],
        "evidence_packet_item": {
            "packet_item_id": packet_item.get("packet_item_id"),
            "paper_id": packet_item.get("paper_id"),
            "field_group": packet_item.get("field_group"),
            "chunks": packet_item.get("chunks") or [],
            "tables": packet_item.get("tables") or [],
            "figures": packet_item.get("figures") or [],
        },
    }
    if schema_mode == "nested_material":
        mode_rules = (
            "Return {\"records\":[...]} where each record is one material and includes paper_id, material_name, record_identity, and data. "
            "data must contain only the current user-defined top-level section for this evidence packet. "
            "Return user-defined data as native JSON. Do not wrap leaf values in raw_value/evidence/unit containers. "
            "Do not wrap leaf values. Do not normalize units. "
            "Do not add evidence fields inside data unless the user schema explicitly defines them. "
            "Do not put paper_id or material_name inside data; material_name belongs at the record top level and in record_identity. "
        )
    else:
        mode_rules = (
            "Return {\"records\":[...]} where each record includes paper_id, optional record_id, record_identity, and fields. "
            "For flat field values preserve raw_value, normalized_value, unit, condition_context, evidence_text, evidence_location, and extraction_note. "
        )
    content = (
        "You are extracting structured data from local literature evidence. "
        "Return strict JSON only. Do not include markdown or commentary. "
        f"{mode_rules}"
        "record_identity must be a JSON object, not an array. "
        "Use null or omit unsupported values; never guess.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )
    return {"messages": [{"role": "user", "content": content}], "payload": payload}


def parse_extraction_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty LLM output")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise ValueError("llm_output_invalid")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM output must be a JSON object")
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError("LLM output missing records")
    return {"records": [record for record in records if isinstance(record, dict)]}


async def _collect_text(llm, messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    async for event in llm.stream_chat(messages, tools=None):
        if event.get("type") == "content" and event.get("text"):
            chunks.append(event["text"])
    return "".join(chunks)
