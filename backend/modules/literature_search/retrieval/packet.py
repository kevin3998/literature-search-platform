"""Evidence acquisition packet builder (Block 2, §2/§5/§9).

Wraps the raw ``ResearchSearch.search()`` output (passed in as ``search_fn`` so
this stays unit-testable) into an auditable :class:`EvidenceAcquisitionPacket`:

    intent -> rewrite -> search (+ bounded no-hit recovery) -> normalize
    -> select -> coverage -> packet

Recovery is intentionally shallow (``MAX_RECOVERY`` extra attempts): the Agent's
own loop handles semantic rewrites, so server-side retries only relax filters and
terms to avoid a double-retry latency explosion.
"""
from __future__ import annotations

from typing import Any, Callable

from modules.literature_search.retrieval.breadth import judge_breadth
from modules.literature_search.retrieval.budgets import budgets_for
from modules.literature_search.retrieval.coverage import judge_coverage
from modules.literature_search.retrieval.intent import detect_intent
from modules.literature_search.retrieval.rewrite import relax_query, rewrite_query
from modules.literature_search.retrieval.schemas import (
    EvidenceAcquisitionPacket,
    EvidenceCandidate,
    FallbackReason,
)
from modules.literature_search.retrieval.selector import select_evidence

MAX_RECOVERY = 2

SearchFn = Callable[..., dict[str, Any]]


def build_packet(
    search_fn: SearchFn,
    query: str,
    *,
    has_history: bool = False,
    options: dict[str, Any] | None = None,
) -> EvidenceAcquisitionPacket:
    options = dict(options or {})
    original_user_query = options.pop("_original_user_query", None) or query
    intent = detect_intent(query, has_history=has_history)
    rewrites = rewrite_query(query, intent)
    primary = rewrites[0] if rewrites else None

    # Block 2 §8: intent-aware three-tier budgets. The candidate pool is broad
    # (the underlying scan already fetches >=200 rows, so this is near-free); the
    # selection pool and llm-context subset stay bounded downstream.
    budgets = budgets_for(
        intent.type, overrides={"candidate_pool": options.get("limit")} if options.get("limit") else None
    )

    # Merge intent-derived section/kind boosts into the requested filters unless
    # the caller already pinned them.
    merged = dict(options)
    merged["limit"] = budgets["candidate_pool"]
    merged.setdefault("evidence_per_article_limit", budgets["per_article"])
    if primary and primary.retrieval_hint and not merged.get("retrieval"):
        # metadata_lookup is a packet-level concept; the underlying search only
        # knows hybrid/fts/vector, so map it to fts for exact lookups.
        merged["retrieval"] = "fts" if primary.retrieval_hint == "metadata_lookup" else primary.retrieval_hint
    if primary and primary.filters_hint:
        for key, value in primary.filters_hint.items():
            merged.setdefault(key, value)

    retrieval_requested = merged.get("retrieval")
    attempted: list[str] = []
    warnings: list[str] = []

    search_query = primary.query if primary else query
    payload = search_fn(search_query, **merged)
    attempted.append(f"primary: '{search_query}' ({retrieval_requested or 'default'})")

    # --- bounded no-hit recovery -------------------------------------------------
    recovery_used = 0
    while not (payload.get("results") or []) and recovery_used < MAX_RECOVERY:
        recovery_used += 1
        if recovery_used == 1:
            # Attempt 2: drop restrictive filters (year/section/kind), keep query.
            relaxed = {k: v for k, v in merged.items()
                       if k not in {"year_from", "year_to", "section", "kind", "journal", "site"}}
            payload = search_fn(search_query, **relaxed)
            attempted.append("recovery: dropped year/section/kind/journal filters")
        else:
            # Attempt 3: relax the query itself to its highest-signal terms.
            relaxed_q = relax_query(search_query)
            relaxed = {k: v for k, v in merged.items()
                       if k not in {"year_from", "year_to", "section", "kind", "journal", "site"}}
            payload = search_fn(relaxed_q, **relaxed)
            attempted.append(f"recovery: relaxed query -> '{relaxed_q}'")

    results = payload.get("results") or []
    raw_plan = payload.get("query_plan") or {}
    retrieval_used = raw_plan.get("retrieval_used") or payload.get("retrieval")
    vector_reason = raw_plan.get("vector_unavailable_reason") or ""
    vector_unavailable = bool(vector_reason)

    # --- normalize evidence candidates ------------------------------------------
    # all_candidates = candidate pool (broad). selection pool = bounded, diverse;
    # within it, the top `llm_context` are flagged in_llm_context (citation bound).
    all_candidates = _flatten_candidates(results)
    selected = select_evidence(
        all_candidates,
        intent,
        per_article_limit=budgets["per_article"],
        total_limit=budgets["selection_pool"],
        context_limit=budgets["llm_context"],
    )

    coverage = judge_coverage(
        selected,
        intent,
        vector_unavailable=vector_unavailable,
        candidate_paper_count=len(results),
        query=original_user_query,
    )

    # --- breadth vs context budget (Block 2 §8) ---------------------------------
    breadth = judge_breadth(
        intent_type=intent.type,
        query=query,
        candidate_paper_count=len(results),
        candidate_evidence_count=len(all_candidates),
        selection_pool=selected,
        raw_query_plan=raw_plan,
    )
    coverage.breadth_limited = breadth.breadth_limited
    coverage.deep_research_suggested = breadth.deep_research_suggested
    if breadth.breadth_notes:
        coverage.coverage_notes = coverage.coverage_notes + breadth.breadth_notes

    # --- fallback reason ---------------------------------------------------------
    fallback: FallbackReason | None = None
    if not results:
        fallback = FallbackReason(
            code="no_results",
            message="No documents matched after recovery attempts.",
            triggered_by=search_query,
            attempted_recoveries=attempted[1:],
            final_status="none",
        )
    elif vector_unavailable:
        # The underlying search already emits a code-like reason
        # (e.g. "vector_index_not_built"); use it verbatim when recognized.
        normalized = vector_reason.strip().lower().replace(" ", "_")
        code = normalized if normalized in {"vector_index_not_built", "vector_query_failed"} else (
            "vector_index_not_built" if "not_built" in normalized else "vector_query_failed"
        )
        fallback = FallbackReason(
            code=code,
            message=vector_reason,
            triggered_by="hybrid/vector retrieval",
            attempted_recoveries=["fell back to FTS"],
            final_status="degraded",
        )
        warnings.append(code)
    elif coverage.status in {"weak", "none"}:
        fallback = FallbackReason(
            code="low_evidence_count",
            message=f"Only {coverage.distinct_paper_count} distinct paper(s) / {coverage.evidence_count} evidence item(s).",
            triggered_by=search_query,
            attempted_recoveries=attempted[1:],
            final_status=coverage.status,
        )

    if recovery_used:
        warnings.append("no_hit_recovery_used")

    # --- platform query_plan (superset of the underlying one) -------------------
    query_plan = {
        "original_query": query,
        "query_intent": intent.type,
        "rewritten_queries": [rw.query for rw in rewrites],
        "retrieval_requested": retrieval_requested or raw_plan.get("retrieval_requested"),
        "retrieval_steps": attempted,
        "filters_requested": {k: merged.get(k) for k in ("year_from", "year_to", "section", "kind", "journal", "site", "scope") if merged.get(k) is not None},
        "filters_applied": raw_plan.get("filters_applied") or {},
        "fallback_steps": attempted[1:],
        "final_retrieval_used": retrieval_used,
        "warnings": warnings,
        "underlying": raw_plan,
    }

    return EvidenceAcquisitionPacket(
        query=query,
        query_intent=_intent_dict(intent),
        query_plan=query_plan,
        rewritten_queries=[_rewrite_dict(rw) for rw in rewrites],
        retrieval_requested=retrieval_requested or raw_plan.get("retrieval_requested"),
        retrieval_used=retrieval_used,
        filters=payload.get("filters") or {},
        fallback_reason=_fallback_dict(fallback),
        results=results,
        evidence_candidates=[_candidate_dict(c) for c in selected],
        expanded_assets=_collect_assets(results),
        coverage=_coverage_dict(coverage),
        breadth=_breadth_dict(breadth),
        coverage_notes=coverage.coverage_notes,
        warnings=warnings,
        debug={
            "raw_query_plan": raw_plan,
            "budgets": budgets,
            "candidate_count_before_selection": len(all_candidates),
            "candidate_count_after_selection": len(selected),
            "llm_context_evidence_count": breadth.llm_context_evidence_count,
            "recovery_attempts": recovery_used,
        },
    )


# --- helpers --------------------------------------------------------------------

def _flatten_candidates(results: list[dict[str, Any]]) -> list[EvidenceCandidate]:
    candidates: list[EvidenceCandidate] = []
    for item in results:
        paper_id = item.get("paper_id")
        for ev in item.get("evidence") or []:
            evidence_id = ev.get("evidence_id")
            if not evidence_id:
                continue
            sources = ev.get("retrieval_sources") or item.get("ranking_features", {}).get("retrieval_sources") or []
            candidates.append(
                EvidenceCandidate(
                    evidence_id=evidence_id,
                    paper_id=ev.get("paper_id") or paper_id or None,
                    article_id=ev.get("article_id") or item.get("article_id"),
                    doi=ev.get("doi") or item.get("doi"),
                    title=ev.get("title") or item.get("title"),
                    year=_to_int(item.get("year")),
                    journal=item.get("journal"),
                    kind=ev.get("kind"),
                    section=ev.get("section") or ev.get("heading_norm"),
                    section_id=ev.get("section_id"),
                    chunk_index=ev.get("chunk_index"),
                    snippet=ev.get("snippet") or ev.get("text"),
                    confidence=ev.get("confidence"),
                    relevance_score=ev.get("score"),
                    source_path=ev.get("source_path"),
                    source_locator=ev.get("source_locator"),
                    asset_label=ev.get("label") or None,
                    retrieval_source=",".join(str(s) for s in sources) if sources else None,
                    query_match_reason=", ".join(ev.get("matched_terms") or []) or None,
                )
            )
    return candidates


def _collect_assets(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for item in results:
        for ev in item.get("evidence") or []:
            for asset in ev.get("linked_assets") or []:
                assets.append({"evidence_id": ev.get("evidence_id"), **asset})
    return assets


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _intent_dict(intent) -> dict[str, Any]:
    return {
        "type": intent.type,
        "confidence": intent.confidence,
        "detected_entities": intent.detected_entities,
        "suggested_filters": intent.suggested_filters,
        "suggested_retrieval": intent.suggested_retrieval,
    }


def _rewrite_dict(rw) -> dict[str, Any]:
    return {
        "query": rw.query,
        "reason": rw.reason,
        "retrieval_hint": rw.retrieval_hint,
        "filters_hint": rw.filters_hint,
    }


def _fallback_dict(fb) -> dict[str, Any] | None:
    if fb is None:
        return None
    return {
        "code": fb.code,
        "message": fb.message,
        "triggered_by": fb.triggered_by,
        "attempted_recoveries": fb.attempted_recoveries,
        "final_status": fb.final_status,
    }


def _coverage_dict(cov) -> dict[str, Any]:
    return {
        "status": cov.status,
        "distinct_paper_count": cov.distinct_paper_count,
        "evidence_count": cov.evidence_count,
        "year_range": cov.year_range,
        "sections_covered": cov.sections_covered,
        "evidence_kinds": cov.evidence_kinds,
        "dominant_paper_ratio": cov.dominant_paper_ratio,
        "candidate_paper_count": cov.candidate_paper_count,
        "selected_evidence_count": cov.selected_evidence_count,
        "breadth_limited": cov.breadth_limited,
        "deep_research_suggested": cov.deep_research_suggested,
        "missing_aspects": cov.missing_aspects,
        "coverage_notes": cov.coverage_notes,
    }


def _breadth_dict(b) -> dict[str, Any]:
    return {
        "candidate_paper_count": b.candidate_paper_count,
        "candidate_evidence_count": b.candidate_evidence_count,
        "selected_evidence_count": b.selected_evidence_count,
        "llm_context_evidence_count": b.llm_context_evidence_count,
        "estimated_total_matches": b.estimated_total_matches,
        "estimate_is_lower_bound": b.estimate_is_lower_bound,
        "cluster_count": b.cluster_count,
        "clusters_covered": b.clusters_covered,
        "missing_clusters": b.missing_clusters,
        "cluster_method": b.cluster_method,
        "breadth_limited": b.breadth_limited,
        "deep_research_suggested": b.deep_research_suggested,
        "breadth_notes": b.breadth_notes,
    }


def _candidate_dict(c: EvidenceCandidate) -> dict[str, Any]:
    return {
        "evidence_id": c.evidence_id,
        "paper_id": c.paper_id,
        "article_id": c.article_id,
        "doi": c.doi,
        "title": c.title,
        "year": c.year,
        "journal": c.journal,
        "kind": c.kind,
        "section": c.section,
        "section_id": c.section_id,
        "chunk_index": c.chunk_index,
        "snippet": c.snippet,
        "confidence": c.confidence,
        "relevance_score": c.relevance_score,
        "selection_score": c.selection_score,
        "source_path": c.source_path,
        "source_locator": c.source_locator,
        "asset_label": c.asset_label,
        "retrieval_source": c.retrieval_source,
        "query_match_reason": c.query_match_reason,
        "cluster": c.cluster,
        "in_llm_context": c.in_llm_context,
    }
