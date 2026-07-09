from __future__ import annotations

import inspect
import os
import re
from collections.abc import Callable
from typing import Any

from . import arxiv, exa, openalex, semantic_scholar
from .models import NoveltySearchPacket, PaperCandidate, VerificationSummary
from .query_builder import build_query_packet
from .verifier import verify_candidates

SourceFn = Callable[[str, int, int, int], list[PaperCandidate]]


class ExternalNoveltySearchService:
    def __init__(
        self,
        *,
        sources: dict[str, SourceFn] | None = None,
        settings_store=None,
        secret_store=None,
        arxiv_lookup=None,
        doi_lookup=None,
        title_lookup=None,
    ) -> None:
        self.settings_store = settings_store
        self.secret_store = secret_store
        self.sources = sources or {
            "arxiv": arxiv.search,
            "semantic_scholar": semantic_scholar.search,
            "openalex": openalex.search,
        }
        self.arxiv_lookup = arxiv_lookup
        self.doi_lookup = doi_lookup
        self.title_lookup = title_lookup

    def search(
        self,
        topic: str,
        idea_text: str,
        *,
        current_year: int = 2026,
        per_source_limit: int = 2,
    ) -> NoveltySearchPacket:
        config = self._config()
        year_window = _positive_int(config.get("default_year_window"), 3)
        per_source_limit = _positive_int(config.get("per_source_limit"), per_source_limit)
        query_packet = build_query_packet(topic, idea_text, current_year=current_year)
        query_packet.year_from = current_year - year_window
        source_status: dict[str, Any] = {
            "year_from": query_packet.year_from,
            "year_to": query_packet.year_to,
            "query_plan": query_packet.flat_queries,
        }
        candidates: list[PaperCandidate] = []
        queries = query_packet.flat_queries[: max(2, min(6, len(query_packet.flat_queries)))]

        for source_name, source_fn in self._enabled_sources().items():
            source_items: list[PaperCandidate] = []
            errors: list[str] = []
            per_query_counts: dict[str, int] = {}
            for query in queries:
                try:
                    found = self._call_source(source_name, source_fn, query, query_packet.year_from, query_packet.year_to, per_source_limit)
                    for item in found:
                        item.query = item.query or query
                    source_items.extend(found)
                    per_query_counts[query] = len(found)
                except Exception as exc:  # noqa: BLE001 - degraded status is part of the artifact contract
                    errors.append(str(exc))
            source_status[source_name] = _source_status(source_items, errors, per_query_counts)
            if source_name in {"semantic_scholar", "exa", "openalex"}:
                source_status[source_name]["api_key_configured"] = bool(self._secret(source_name))
            candidates.extend(source_items)

        if "exa" not in self.sources and config.get("exa_enabled"):
            exa_key = self._secret("exa")
            if exa.available(exa_key):
                source_items, errors = _run_optional_exa(queries, query_packet.year_from, query_packet.year_to, per_source_limit, exa_key)
                source_status["exa"] = _source_status(source_items, errors, {"exa": len(source_items)})
                source_status["exa"]["api_key_configured"] = True
                candidates.extend(source_items)
            else:
                source_status["exa"] = {"status": "skipped_no_api_key", "count": 0, "api_key_configured": False}
        elif "exa" not in source_status:
            source_status["exa"] = {"status": "disabled", "count": 0, "api_key_configured": bool(self._secret("exa"))}

        deduped = _dedupe(candidates)
        verification = verify_candidates(
            deduped,
            arxiv_lookup=self.arxiv_lookup,
            doi_lookup=self.doi_lookup,
            title_lookup=self.title_lookup,
        )
        summary = verification.summary()
        if summary.hallucination_rate > 0.2:
            source_status["high_hallucination_rate"] = True
        query_quality = {
            "dropped_template_terms": query_packet.dropped_template_terms,
            "queries_by_idea": query_packet.queries_by_idea,
        }
        return NoveltySearchPacket(
            candidates=verification.papers[:24],
            source_status=source_status,
            verification_summary=summary,
            query_quality=query_quality,
        )

    def _config(self) -> dict[str, Any]:
        if self.settings_store is not None:
            try:
                return self.settings_store.external_sources_config()
            except Exception:  # noqa: BLE001
                return {}
        try:
            from core.settings_store import settings_store

            return settings_store.external_sources_config()
        except Exception:  # noqa: BLE001
            return {}

    def _enabled_sources(self) -> dict[str, SourceFn]:
        config = self._config()
        out: dict[str, SourceFn] = {}
        for name, fn in self.sources.items():
            if config.get(f"{name}_enabled", True):
                out[name] = fn
        return out

    def _secret(self, source_name: str) -> str | None:
        env_names = {
            "semantic_scholar": ["SEMANTIC_SCHOLAR_API_KEY"],
            "exa": ["EXA_API_KEY"],
            "openalex": ["OPENALEX_API_KEY"],
        }.get(source_name, [])
        for env_name in env_names:
            value = os.getenv(env_name, "").strip()
            if value:
                return value
        store = self.secret_store
        if store is None:
            try:
                from core.secret_store import secret_store

                store = secret_store
            except Exception:  # noqa: BLE001
                return None
        try:
            return store.get(f"external:{source_name}")
        except Exception:  # noqa: BLE001
            return None

    def _call_source(self, source_name: str, source_fn: SourceFn, query: str, year_from: int, year_to: int, limit: int) -> list[PaperCandidate]:
        config = self._config()
        params = set(inspect.signature(source_fn).parameters)
        extra = {}
        if "timeout" in params:
            extra["timeout"] = _positive_int(config.get("timeout_seconds"), 30)
        if "retries" in params:
            extra["retries"] = _positive_int(config.get("retry_count"), 2)
        if source_name == "semantic_scholar" and "api_key" in params:
            return source_fn(query, year_from, year_to, limit, api_key=self._secret("semantic_scholar"), **extra)
        if source_name == "openalex" and {"email", "api_key"} <= params:
            return source_fn(query, year_from, year_to, limit, email=config.get("openalex_email"), api_key=self._secret("openalex"), **extra)
        if source_name == "exa" and "api_key" in params:
            return source_fn(query, year_from, year_to, limit, api_key=self._secret("exa"), **extra)
        if extra:
            return source_fn(query, year_from, year_to, limit, **extra)
        return source_fn(query, year_from, year_to, limit)


def search_external_sources(
    topic: str,
    idea_text: str,
    *,
    current_year: int = 2026,
    per_source_limit: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return ExternalNoveltySearchService().search(
        topic,
        idea_text,
        current_year=current_year,
        per_source_limit=per_source_limit,
    ).as_tuple()


def render_external_context(candidates: list[dict[str, Any]], status: dict[str, Any]) -> str:
    lines = [
        f"搜索年份窗口：{status.get('year_from')}-{status.get('year_to')}；2025-2026 结果视为 concurrent work 高风险区。",
        "",
        "查询质量：",
    ]
    quality = status.get("query_quality") or {}
    dropped = quality.get("dropped_template_terms") or []
    if dropped:
        lines.append(f"- 已过滤模板词：{', '.join(dropped[:20])}")
    for idea_id, queries in (quality.get("queries_by_idea") or {}).items():
        lines.append(f"- {idea_id}: {' | '.join(queries[:3])}")

    lines.extend(["", "外部源状态："])
    for key, value in status.items():
        if isinstance(value, dict) and key not in {"verification_summary", "query_quality"}:
            lines.append(f"- {key}: {value.get('status')} ({value.get('count', 0)} results)")

    summary = status.get("verification_summary") or {}
    if summary:
        lines.extend([
            "",
            "验证摘要：",
            f"- verdict: {summary.get('verdict')}",
            f"- hallucination_rate: {summary.get('hallucination_rate')}",
            f"- pending_rate: {summary.get('pending_rate')}",
        ])

    lines.extend(["", "候选 prior work："])
    if not candidates:
        lines.append("- 未返回外部候选；world novelty 必须标为 SEARCH_INCOMPLETE。")
    for i, candidate in enumerate(candidates, 1):
        tag = candidate.get("verification") or "verify_pending"
        if tag == "unverified":
            tag = "UNVERIFIED"
        elif tag == "verify_pending":
            tag = "VERIFY_PENDING"
        title = candidate.get("title") or "Untitled"
        year = candidate.get("year") or "?"
        ident = candidate.get("doi") or candidate.get("arxiv_id") or candidate.get("url") or ""
        lines.append(f"{i}. [{tag}] {title} ({year}) · {candidate.get('source')} · {ident}")
        abstract = (candidate.get("abstract") or "").strip()
        if abstract:
            lines.append(f"   摘要：{abstract[:300]}")
    return "\n".join(lines)


def _run_optional_exa(queries: list[str], year_from: int, year_to: int, limit: int, api_key: str | None = None) -> tuple[list[PaperCandidate], list[str]]:
    items: list[PaperCandidate] = []
    errors: list[str] = []
    for query in queries[:2]:
        try:
            items.extend(exa.search(query, year_from, year_to, limit, api_key=api_key))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    return items, errors


def _source_status(items: list[PaperCandidate], errors: list[str], per_query_counts: dict[str, int]) -> dict[str, Any]:
    if items:
        return {"status": "ok", "count": len(items), "per_query_counts": per_query_counts, "errors": errors[:3]}
    if errors:
        return {"status": _classify_errors(errors), "count": 0, "errors": errors[:3]}
    return {"status": "warning", "count": 0}


def _classify_errors(errors: list[str]) -> str:
    text = " ".join(errors).lower()
    if "429" in text or "rate" in text or "too many requests" in text:
        return "rate_limited"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    return "error"


def _dedupe(candidates: list[PaperCandidate]) -> list[PaperCandidate]:
    seen: set[str] = set()
    out: list[PaperCandidate] = []
    for candidate in candidates:
        key = _dedupe_key(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _dedupe_key(candidate: PaperCandidate) -> str:
    if candidate.doi:
        return f"doi:{candidate.doi.lower()}"
    if candidate.arxiv_id:
        return f"arxiv:{candidate.arxiv_id.lower()}"
    return f"title:{re.sub(r'\\W+', ' ', (candidate.title or '').lower()).strip()}"


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default
