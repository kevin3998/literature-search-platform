"""Deterministic evidence selection / rerank (Block 2, §7).

First-stage selector — no LLM. Goals: prefer relevant + confident evidence,
keep multi-paper and multi-kind coverage, prevent a single paper from
dominating, and cap total volume so the Agent context doesn't explode.

    score = relevance + confidence + section_weight + kind_weight
          + recency_weight + diversity_bonus - same_paper_penalty
"""
from __future__ import annotations

import datetime
from typing import Any

from modules.literature_search.retrieval.schemas import EvidenceCandidate, QueryIntent

EVIDENCE_PER_ARTICLE_LIMIT = 3
TOTAL_EVIDENCE_LIMIT = 20

_SECTION_WEIGHTS = {
    "result": 1.0,
    "results": 1.0,
    "method": 0.8,
    "methods": 0.8,
    "discussion": 0.6,
    "abstract": 0.3,
    "introduction": 0.1,
}
_KIND_WEIGHTS = {
    "table_row": 1.0,
    "table": 0.9,
    "figure": 0.6,
    "paragraph": 0.4,
    "abstract": 0.3,
}


_CONFIDENCE_LEVELS = {"high": 0.9, "medium": 0.6, "moderate": 0.6, "low": 0.3, "very_low": 0.1}


def _confidence_value(confidence: Any) -> float:
    """Confidence may be a float or a level string ('high'/'medium'/'low')."""
    if confidence is None:
        return 0.0
    if isinstance(confidence, (int, float)):
        return float(confidence)
    return _CONFIDENCE_LEVELS.get(str(confidence).strip().lower(), 0.0)


def _section_weight(section: str | None) -> float:
    if not section:
        return 0.0
    return _SECTION_WEIGHTS.get(section.strip().lower(), 0.0)


def _kind_weight(kind: str | None, intent: QueryIntent) -> float:
    base = _KIND_WEIGHTS.get((kind or "").strip().lower(), 0.0)
    # Data/metric questions promote table/result evidence further.
    if intent.type == "metric_compare" and (kind or "").lower().startswith("table"):
        base += 1.0
    return base


def _recency_weight(year: int | None, intent: QueryIntent) -> float:
    if intent.type not in {"recent_review", "author_year_journal"} or not year:
        return 0.0
    current = datetime.date.today().year
    age = max(0, current - int(year))
    # Linear decay over ~10 years, capped at 1.0.
    return max(0.0, 1.0 - age / 10.0)


def select_evidence(
    candidates: list[EvidenceCandidate],
    intent: QueryIntent,
    *,
    per_article_limit: int = EVIDENCE_PER_ARTICLE_LIMIT,
    total_limit: int = TOTAL_EVIDENCE_LIMIT,
    context_limit: int | None = None,
) -> list[EvidenceCandidate]:
    """Return the selection pool (size ``total_limit``), with the top
    ``context_limit`` items flagged ``in_llm_context=True`` — the bounded subset
    that enters the prompt and forms the citation boundary (Block 2 §8). When
    ``context_limit`` is None the whole pool is in-context (legacy behaviour)."""
    if not candidates:
        return []

    relevances = [c.relevance_score or 0.0 for c in candidates]
    max_rel = max(relevances) or 1.0

    scored: list[tuple[float, EvidenceCandidate]] = []
    for cand in candidates:
        relevance = (cand.relevance_score or 0.0) / max_rel
        confidence = _confidence_value(cand.confidence)
        score = (
            relevance
            + confidence
            + _section_weight(cand.section)
            + _kind_weight(cand.kind, intent)
            + _recency_weight(cand.year, intent)
        )
        scored.append((score, cand))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    # The per-article limit is a HARD cap — overflow evidence from a dominant
    # paper is dropped rather than backfilled, so one paper can never monopolize
    # the candidate set (Block 2 §7 "避免单篇论文垄断").
    selected: list[EvidenceCandidate] = []
    per_paper: dict[Any, int] = {}
    for score, cand in scored:
        key = cand.paper_id or cand.doi or cand.article_id or cand.evidence_id
        count = per_paper.get(key, 0)
        if count >= per_article_limit:
            continue
        # Diversity bonus: the first evidence from a fresh paper is worth more.
        bonus = 0.5 if count == 0 else 0.0
        penalty = 0.3 * count
        cand.selection_score = round(score + bonus - penalty, 4)
        per_paper[key] = count + 1
        selected.append(cand)
        if len(selected) >= total_limit:
            break

    selected.sort(key=lambda c: c.selection_score or 0.0, reverse=True)

    # Flag the bounded context subset. To keep the in-context evidence diverse
    # (not the top-K of one dominant paper), fill it cluster-aware-ish: walk the
    # ranked pool but cap how many from the same paper land in context first.
    limit = len(selected) if context_limit is None else max(1, context_limit)
    ctx_per_paper: dict[Any, int] = {}
    ctx_count = 0
    ctx_cap = max(1, per_article_limit - 1) if limit < len(selected) else per_article_limit
    for cand in selected:
        if ctx_count >= limit:
            break
        key = cand.paper_id or cand.doi or cand.article_id or cand.evidence_id
        if ctx_per_paper.get(key, 0) >= ctx_cap:
            continue
        cand.in_llm_context = True
        ctx_per_paper[key] = ctx_per_paper.get(key, 0) + 1
        ctx_count += 1
    # If diversity capping left context underfilled, top up by rank.
    if ctx_count < limit:
        for cand in selected:
            if ctx_count >= limit:
                break
            if not cand.in_llm_context:
                cand.in_llm_context = True
                ctx_count += 1
    return selected
