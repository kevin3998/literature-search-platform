"""Retrieval breadth estimation (Block 2 §8).

Decouples "how much the system considered" from "how much entered the answer",
and turns that gap into honest, user-readable trust signals. Everything here is
deterministic and cheap: the candidate-match estimate is read off the existing
query_plan counters, and clustering is a lightweight lexical/metadata
approximation (real semantic clustering waits for the vector index).
"""
from __future__ import annotations

import re
from typing import Any

from modules.literature_search.retrieval.schemas import Breadth, EvidenceCandidate

# Intents whose answers are inherently broad-coverage tasks.
_BROAD_INTENTS = {"topic", "recent_review", "metric_compare", "mechanism"}

# Phrases that signal the user wants exhaustive coverage, not a quick overview.
_COMPREHENSIVE_TERMS = (
    "综述", "系统综述", "系统回顾", "全面", "全领域", "所有方法", "逐一", "穷尽",
    "literature review", "systematic review", "survey", "comprehensive",
    "all methods", "every", "exhaustive", "full picture", "state of the field",
)

_STOP_TERMS = {"the", "a", "an", "of", "in", "on", "for", "and", "or", "with", "to"}


def estimate_total_matches(raw_query_plan: dict, candidate_paper_count: int) -> tuple[int, bool]:
    """Approximate corpus matches from query_plan counters (no exact COUNT exists).

    Returns (estimate, is_lower_bound). When the underlying candidate scan
    saturated its internal ceiling, the true total is unknown and larger — we
    report the paper count as a lower bound.
    """
    fts_docs = int(raw_query_plan.get("fts_candidate_documents") or 0)
    # Underlying _candidate_limit = max(limit*20, 200); we don't know `limit`
    # here, so treat a large doc scan as saturation evidence.
    saturated = fts_docs >= 200
    if saturated:
        return candidate_paper_count, True
    # Below saturation, the deduped paper count is a fair estimate.
    return max(candidate_paper_count, 0), False


def _cluster_key(cand: EvidenceCandidate) -> str:
    """Lightweight cluster label: most distinctive matched term, else journal,
    else year bucket. Marked approximate; replace with vector clustering later."""
    reason = (cand.query_match_reason or "").lower()
    terms = [t for t in re.split(r"[,\s]+", reason) if len(t) >= 4 and t not in _STOP_TERMS]
    if terms:
        return max(terms, key=len)
    if cand.journal:
        return f"journal:{cand.journal.strip().lower()}"
    if cand.year:
        return f"year:{(cand.year // 5) * 5}s"
    return "misc"


def cluster_candidates(candidates: list[EvidenceCandidate]) -> dict[str, list[str]]:
    """Group selection-pool candidates into approximate sub-themes (label -> eids)
    and stamp ``cand.cluster`` in place."""
    clusters: dict[str, list[str]] = {}
    for cand in candidates:
        label = _cluster_key(cand)
        cand.cluster = label
        clusters.setdefault(label, []).append(cand.evidence_id)
    return clusters


def judge_breadth(
    *,
    intent_type: str,
    query: str,
    candidate_paper_count: int,
    candidate_evidence_count: int,
    selection_pool: list[EvidenceCandidate],
    raw_query_plan: dict,
) -> Breadth:
    b = Breadth()
    b.candidate_paper_count = candidate_paper_count
    b.candidate_evidence_count = candidate_evidence_count
    b.selected_evidence_count = len(selection_pool)
    context = [c for c in selection_pool if c.in_llm_context]
    b.llm_context_evidence_count = len(context)

    b.estimated_total_matches, b.estimate_is_lower_bound = estimate_total_matches(
        raw_query_plan, candidate_paper_count
    )

    clusters = cluster_candidates(selection_pool)
    b.cluster_count = len(clusters)
    context_clusters = {c.cluster for c in context if c.cluster}
    b.clusters_covered = sorted(context_clusters)
    b.missing_clusters = sorted(set(clusters) - context_clusters)

    broad_intent = intent_type in _BROAD_INTENTS
    pool_exceeds_context = b.candidate_evidence_count > b.llm_context_evidence_count
    wants_comprehensive = any(term in query.lower() for term in _COMPREHENSIVE_TERMS)

    # breadth_limited: the answer can only carry a representative sample.
    b.breadth_limited = bool(
        broad_intent
        and pool_exceeds_context
        and (b.missing_clusters or b.estimate_is_lower_bound)
    )

    # deep_research_suggested: a single chat answer cannot claim completeness.
    b.deep_research_suggested = bool(
        wants_comprehensive
        or (broad_intent and b.estimate_is_lower_bound and b.missing_clusters)
    )

    notes: list[str] = []
    if b.breadth_limited:
        scope = f"约 {b.estimated_total_matches}+ 篇" if b.estimate_is_lower_bound else f"约 {b.candidate_paper_count} 篇"
        notes.append(
            f"本库命中{scope}相关文献；本次回答基于其中 {b.llm_context_evidence_count} 条代表性证据，"
            f"覆盖 {len(b.clusters_covered)}/{b.cluster_count} 个主要方向。"
        )
        notes.append("当前回答是代表性概览，不是完整系统综述。")
    if b.deep_research_suggested:
        notes.append("如需全面综述，建议启动深度研究 / 报告流程进行分批聚合。")
    b.breadth_notes = notes
    return b
