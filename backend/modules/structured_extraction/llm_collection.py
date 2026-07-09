from __future__ import annotations

import json
import re
from typing import Any

from core.llm import LLMUnavailable, build_llm_client
from core.settings_store import settings_store
from core.user_context import UserContext

from .collection import StructuredExtractionCollectionService
from .schemas import LLMScreenRequest, QuestionExpansionRequest


class EmptyLLMOutput(RuntimeError):
    pass


async def expand_question(payload: QuestionExpansionRequest, *, task: dict[str, Any]) -> dict[str, Any]:
    try:
        llm = build_llm_client(settings_store)
    except LLMUnavailable:
        return {"available": False, "reason": "llm_unavailable", "queries": []}
    limit = max(3, min(int(payload.limit or 5), 8))
    prompt = (
        "Convert the research question into local literature metadata search queries. "
        "Return strict JSON only with shape {\"queries\":[{\"query\":\"...\",\"year_from\":null,\"year_to\":null,"
        "\"journal\":\"\",\"site\":\"\"}]}. Keep queries short and metadata-search friendly.\n\n"
        f"Question: {payload.question}\nLimit: {limit}"
    )
    try:
        text = await _collect_text(llm, [{"role": "user", "content": prompt}])
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": "llm_unavailable", "queries": [], "detail": str(exc)}
    try:
        data = _parse_json(text)
        queries = data.get("queries") if isinstance(data, dict) else []
        if not isinstance(queries, list):
            queries = []
        normalized = []
        for item in queries[:limit]:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            normalized.append(
                {
                    "query": query[:240],
                    "limit": 50,
                    "year_from": _optional_int(item.get("year_from")),
                    "year_to": _optional_int(item.get("year_to")),
                    "journal": str(item.get("journal") or ""),
                    "site": str(item.get("site") or ""),
                    "source": "question_expansion",
                }
            )
        return {
            "available": True,
            "task_id": task["task_id"],
            "queries": normalized,
            "model_profile_id": (task.get("model_settings") or {}).get("schema_assist_profile_id"),
        }
    except EmptyLLMOutput as exc:
        return {"available": False, "reason": "llm_unavailable", "queries": [], "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": "llm_output_invalid", "queries": [], "detail": str(exc)}


async def screen_candidates(
    service: StructuredExtractionCollectionService,
    task_id: str,
    payload: LLMScreenRequest,
    *,
    task: dict[str, Any],
    user: UserContext,
) -> dict[str, Any]:
    try:
        llm = build_llm_client(settings_store)
    except LLMUnavailable:
        return {"available": False, "reason": "llm_unavailable", "updated": 0, "candidates": []}
    candidates = []
    for candidate_id in payload.candidate_ids:
        rows = service.list_candidates(task_id, user=user, limit=200)["candidates"]
        match = next((item for item in rows if item["candidate_id"] == candidate_id), None)
        if match:
            candidates.append(match)
    if not candidates:
        return {"available": True, "updated": 0, "candidates": []}
    prompt = (
        "Screen literature candidates for relevance. Return strict JSON only with shape "
        "{\"results\":[{\"candidate_id\":\"...\",\"decision\":\"include|exclude|uncertain\","
        "\"relevance_score\":0.0,\"reason\":\"...\"}]}. Do not decide user inclusion; this is only LLM advice.\n\n"
        f"Screening instruction: {payload.prompt or 'Assess relevance to the collection question.'}\n"
        f"Candidates: {json.dumps(_compact_candidates(candidates), ensure_ascii=False)}"
    )
    try:
        text = await _collect_text(llm, [{"role": "user", "content": prompt}])
        data = _parse_json(text)
        results = data.get("results") if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise ValueError("missing results")
    except Exception:
        results = [
            {
                "candidate_id": candidate["candidate_id"],
                "decision": "uncertain",
                "relevance_score": None,
                "reason": "llm_output_invalid",
            }
            for candidate in candidates
        ]
    updated = service.update_llm_screening(task_id, results, user=user)
    return {
        "available": True,
        "task_id": task_id,
        "updated": len(updated),
        "candidates": updated,
        "model_profile_id": (task.get("model_settings") or {}).get("schema_assist_profile_id"),
    }


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


def _compact_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": item["candidate_id"],
            "title": item.get("title"),
            "authors": item.get("authors") or [],
            "year": item.get("year"),
            "journal": item.get("journal"),
            "doi": item.get("doi"),
            "matched_fields": item.get("matched_fields") or [],
        }
        for item in candidates
    ]


def _optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
