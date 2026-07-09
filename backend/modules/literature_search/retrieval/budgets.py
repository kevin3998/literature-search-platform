"""Intent-aware three-tier retrieval budgets (Block 2 §8).

Separates retrieval breadth from LLM context budget:

    candidate_pool   -> how many papers to retrieve (broad; underlying already
                        scans >=200 candidates, so a wide pool is near-free)
    selection_pool   -> how many evidence items the selector keeps (diverse,
                        cross-paper/year/cluster; powers the packet, record,
                        and browsing)
    llm_context      -> how many evidence items are actually inlined into the
                        model prompt and become the citation boundary

`per_article` caps evidence per paper to prevent single-paper dominance.
Defaults live here; callers may override any field (e.g. an explicit `limit`
the LLM passed, or a settings-derived ceiling).
"""
from __future__ import annotations

from typing import Any

# intent -> (candidate_pool, selection_pool, llm_context, per_article)
_BUDGETS: dict[str, tuple[int, int, int, int]] = {
    "doi": (5, 3, 3, 3),
    "article_id": (5, 3, 3, 3),
    "paper_id": (5, 3, 3, 3),
    "title": (10, 5, 5, 3),
    "author_year_journal": (15, 8, 6, 3),
    "followup": (20, 10, 8, 2),
    "mechanism": (40, 18, 12, 3),
    "metric_compare": (60, 24, 15, 3),
    "topic": (60, 24, 15, 2),
    "recent_review": (80, 30, 18, 2),
    "unknown": (40, 15, 10, 2),
}

_DEFAULT = (40, 15, 10, 2)

# Hard ceilings so an override / misconfiguration can't blow up the context.
_CONTEXT_HARD_CAP = 24
_POOL_HARD_CAP = 120


def budgets_for(intent_type: str, *, overrides: dict[str, Any] | None = None) -> dict[str, int]:
    pool, selection, context, per_article = _BUDGETS.get(intent_type, _DEFAULT)
    budget = {
        "candidate_pool": pool,
        "selection_pool": selection,
        "llm_context": context,
        "per_article": per_article,
    }
    for key, value in (overrides or {}).items():
        if key in budget and value is not None:
            try:
                budget[key] = int(value)
            except (TypeError, ValueError):
                continue
    # Keep the tiers monotonic and bounded: context <= selection <= pool.
    budget["llm_context"] = min(budget["llm_context"], _CONTEXT_HARD_CAP)
    budget["candidate_pool"] = min(budget["candidate_pool"], _POOL_HARD_CAP)
    budget["selection_pool"] = max(budget["llm_context"], min(budget["selection_pool"], budget["candidate_pool"]))
    budget["per_article"] = max(1, budget["per_article"])
    return budget
