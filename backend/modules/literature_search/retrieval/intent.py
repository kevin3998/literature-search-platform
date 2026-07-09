"""Deterministic query intent detection (Block 2, §1).

This sits *above* the underlying ``classify_query`` (which only knows
doi/data_metric/figure/topic). It produces the richer platform intent that
drives rewrite, retrieval strategy, and intent-aware coverage thresholds.

Detection is intentionally conservative and rule-based: ambiguous signals
(a bare integer, a DOI-shaped paper_id) are only treated as ``article_id`` /
``paper_id`` when explicitly prefixed. Chinese->English / semantic rewriting is
*not* done here — the Agent LLM already supplies English queries.
"""
from __future__ import annotations

import re

from modules.literature_search.retrieval.schemas import QueryIntent

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", re.IGNORECASE)
_ARTICLE_ID_RE = re.compile(r"\barticle[_ ]?id\s*[:=]?\s*(\d+)", re.IGNORECASE)
_PAPER_ID_RE = re.compile(r"\bpaper[_ ]?id\s*[:=]?\s*(\S+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_QUOTED_RE = re.compile(r"[\"“”『「]([^\"”』」]{8,})[\"“”』」]")

_RECENT_TERMS = (
    "latest", "recent", "recently", "sota", "state-of-the-art", "state of the art",
    "progress", "advances", "advancement", "survey", "review", "新进展", "最新",
    "进展", "综述", "近年来", "前沿",
)
_MECHANISM_TERMS = (
    "mechanism", "how does", "how do", "principle", "method", "approach",
    "机制", "原理", "方法", "如何", "怎样", "怎么",
)
_METRIC_TERMS = (
    "compare", "comparison", "versus", " vs ", "efficiency", "accuracy",
    "performance", "power density", "current density", "voltage", "flux",
    "rejection", "selectivity", "capacity", "evaporation rate", "table",
    "对比", "比较", "指标", "数据", "性能",
)
_AUTHOR_TERMS = ("et al", "et al.", "等人", "等,", "等，", "课题组")
_FOLLOWUP_TERMS = (
    "它", "他们", "这些", "这个", "那个", "上面", "前面", "刚才", "上述", "继续",
    "还有", "再", "more", "also", "additionally", "what about", "and the",
)


def detect_intent(query: str, *, has_history: bool = False) -> QueryIntent:
    text = (query or "").strip()
    if not text:
        return QueryIntent(type="unknown", confidence=0.0)
    lowered = text.lower()

    doi_match = _DOI_RE.search(text)
    if doi_match:
        return QueryIntent(
            type="doi",
            confidence=0.99,
            detected_entities={"doi": doi_match.group(1)},
            suggested_retrieval="metadata_lookup",
        )

    article_match = _ARTICLE_ID_RE.search(text)
    if article_match:
        return QueryIntent(
            type="article_id",
            confidence=0.95,
            detected_entities={"article_id": int(article_match.group(1))},
            suggested_retrieval="metadata_lookup",
        )

    paper_match = _PAPER_ID_RE.search(text)
    if paper_match:
        return QueryIntent(
            type="paper_id",
            confidence=0.9,
            detected_entities={"paper_id": paper_match.group(1)},
            suggested_retrieval="metadata_lookup",
        )

    quoted = _QUOTED_RE.search(text)
    if quoted or lowered.startswith("title:") or text.startswith("标题"):
        title = quoted.group(1) if quoted else re.sub(r"^(title:|标题[:：]?)", "", text, flags=re.IGNORECASE).strip()
        return QueryIntent(
            type="title",
            confidence=0.85 if quoted else 0.7,
            detected_entities={"title": title},
            suggested_retrieval="fts",
        )

    year_match = _YEAR_RE.search(text)
    has_author = any(term in lowered for term in _AUTHOR_TERMS)
    if year_match and has_author:
        return QueryIntent(
            type="author_year_journal",
            confidence=0.7,
            detected_entities={"year": int(year_match.group(0))},
            suggested_filters={"year_from": int(year_match.group(0)), "year_to": int(year_match.group(0))},
            suggested_retrieval="fts",
        )

    # Order matters: a "recent progress" question is review-shaped even if it
    # also mentions a method. Recency wins over mechanism/metric.
    if any(term in lowered for term in _RECENT_TERMS):
        return QueryIntent(
            type="recent_review",
            confidence=0.75,
            detected_entities={"year": int(year_match.group(0))} if year_match else {},
            suggested_retrieval="hybrid",
        )

    if any(term in lowered for term in _METRIC_TERMS):
        return QueryIntent(
            type="metric_compare",
            confidence=0.7,
            suggested_filters={"kind_boost": "table_row"},
            suggested_retrieval="hybrid",
        )

    if any(term in lowered for term in _MECHANISM_TERMS):
        return QueryIntent(
            type="mechanism",
            confidence=0.65,
            suggested_filters={"section_boost": "method"},
            suggested_retrieval="hybrid",
        )

    if has_history and any(term in lowered for term in _FOLLOWUP_TERMS):
        return QueryIntent(type="followup", confidence=0.6, suggested_retrieval="hybrid")

    if len(lowered.split()) <= 1 and len(text) <= 3:
        return QueryIntent(type="unknown", confidence=0.3, suggested_retrieval="hybrid")

    return QueryIntent(type="topic", confidence=0.55, suggested_retrieval="hybrid")
