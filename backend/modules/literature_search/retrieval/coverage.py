"""Coverage judgment (Block 2, §8).

Translates the selected evidence into a coarse trust signal the Agent can act
on. Thresholds are intent-dependent: a DOI/title lookup is satisfied by a single
hit, while a review/topic question needs several distinct papers.

The vector index is not built on this corpus, so FTS-only is the steady state —
it is reported as a calm note/warning, never as a reason to downgrade to weak.
"""
from __future__ import annotations

import re

from modules.literature_search.retrieval.schemas import Coverage, EvidenceCandidate, QueryIntent

# Minimum distinct papers for a "sufficient" verdict, per intent.
_MIN_PAPERS = {
    "doi": 1,
    "article_id": 1,
    "paper_id": 1,
    "title": 1,
    "author_year_journal": 1,
    "mechanism": 2,
    "metric_compare": 2,
    "topic": 3,
    "recent_review": 3,
    "followup": 1,
    "unknown": 2,
}


def judge_coverage(
    candidates: list[EvidenceCandidate],
    intent: QueryIntent,
    *,
    vector_unavailable: bool = False,
    candidate_paper_count: int = 0,
    query: str = "",
) -> Coverage:
    cov = Coverage()
    cov.evidence_count = len(candidates)
    cov.selected_evidence_count = len(candidates)
    cov.candidate_paper_count = candidate_paper_count
    if not candidates:
        cov.status = "none"
        cov.coverage_notes = ["No usable local evidence was found."]
        return cov

    papers = {c.paper_id or c.doi or c.article_id for c in candidates if (c.paper_id or c.doi or c.article_id)}
    cov.distinct_paper_count = len(papers)

    years = sorted({c.year for c in candidates if c.year})
    cov.year_range = [years[0], years[-1]] if years else [None, None]
    cov.sections_covered = sorted({(c.section or "").lower() for c in candidates if c.section})
    cov.evidence_kinds = sorted({(c.kind or "").lower() for c in candidates if c.kind})

    # Dominant-paper ratio: share of evidence from the single most-cited paper.
    counts: dict = {}
    for c in candidates:
        key = c.paper_id or c.doi or c.article_id
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    cov.dominant_paper_ratio = round(max(counts.values()) / len(candidates), 3) if counts else 0.0

    needed = _MIN_PAPERS.get(intent.type, 2)
    notes: list[str] = []
    missing: list[str] = []

    # Base status from distinct-paper coverage.
    if cov.distinct_paper_count >= needed:
        status = "sufficient"
    elif cov.distinct_paper_count >= max(1, needed - 1):
        status = "partial"
    else:
        status = "weak"

    # Single-paper dominance on a multi-paper question caps at partial.
    if needed >= 3 and cov.distinct_paper_count < 3:
        notes.append(f"Only {cov.distinct_paper_count} paper(s) found; not enough for a review-style answer.")
        missing.append("multiple_papers")

    # Evidence type / section gaps for analytical questions.
    if intent.type in {"mechanism", "metric_compare"}:
        has_support = any(k in cov.evidence_kinds for k in ("table_row", "table")) or any(
            s in cov.sections_covered for s in ("result", "results", "method", "methods", "discussion")
        )
        if not has_support:
            notes.append("Most evidence comes from abstracts, lacking method/result/table support.")
            missing.append("method_result_table")
            if status == "sufficient":
                status = "partial"

    if intent.type == "metric_compare" and not any(
        k in cov.evidence_kinds for k in ("table_row", "table")
    ):
        notes.append("No table/result-row evidence found for a data/metric question.")

    if intent.type == "recent_review" and cov.year_range[1] and cov.year_range[1] < 2022:
        notes.append("Recent-progress query has no evidence after 2022.")
        missing.append("recent_years")
        if status == "sufficient":
            status = "partial"

    if vector_unavailable:
        notes.append("Vector retrieval unavailable; results are FTS-only.")

    if status == "sufficient" and _is_direct_existence_query(query):
        direct = _direct_topic_match(query, candidates)
        if not direct["matched"]:
            notes.append(
                "Results appear adjacent to the requested topic but do not cover the direct topic terms."
            )
            missing.append("direct_topic_match")
            status = "partial" if cov.distinct_paper_count >= 2 else "weak"

    cov.status = status
    cov.missing_aspects = missing
    cov.coverage_notes = notes
    return cov


_DIRECT_EXISTENCE_RE = re.compile(
    r"(有没有|是否有|有无|有没有关于|有没有.*论文|是否.*论文|any\s+(?:papers|literature|studies)|literature\s+about|papers?\s+about)",
    re.IGNORECASE,
)
_EN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
_CJK_KEY_TERMS = (
    "超导",
    "火星",
    "土壤",
    "材料",
    "电池",
    "催化",
    "钙钛矿",
    "石墨烯",
    "纳米",
    "大语言模型",
    "语言模型",
    "材料发现",
    "材料设计",
)
_TERM_ALIASES = {
    "超导": ("超导", "superconduct", "superconductivity"),
    "火星": ("火星", "martian", "mars"),
    "土壤": ("土壤", "soil"),
    "材料": ("材料", "material", "materials"),
    "电池": ("电池", "battery", "batteries"),
    "大语言模型": ("大语言模型", "large language model", "large language models", "llm", "llms"),
    "语言模型": ("语言模型", "language model", "language models"),
    "材料发现": ("材料发现", "materials discovery", "material discovery"),
    "材料设计": ("材料设计", "materials design", "material design"),
}
_STOP_TERMS = {
    "文献库",
    "有没有",
    "是否有",
    "关于",
    "论文",
    "文献",
    "研究",
    "paper",
    "papers",
    "literature",
    "about",
    "there",
    "current",
    "local",
}


def _is_direct_existence_query(query: str) -> bool:
    return bool(_DIRECT_EXISTENCE_RE.search(query or ""))


def _direct_topic_match(query: str, candidates: list[EvidenceCandidate]) -> dict[str, object]:
    terms = _direct_query_terms(query)
    if not terms:
        return {"matched": True, "missing_terms": []}
    per_candidate_missing: list[list[str]] = []
    for c in candidates:
        text = " ".join(
            str(value or "")
            for value in (c.title, c.snippet, c.section, c.journal)
        ).lower()
        missing = [term for term in terms if not _term_present(term, text)]
        if not missing:
            return {"matched": True, "missing_terms": []}
        per_candidate_missing.append(missing)
    combined_text = " ".join(
        str(value or "")
        for c in candidates
        for value in (c.title, c.snippet, c.section, c.journal)
    ).lower()
    missing = [term for term in terms if not _term_present(term, combined_text)]
    if not missing and per_candidate_missing:
        # Terms appear somewhere in the result set, but not together in one
        # evidence locus; this is adjacent coverage, not a direct topic hit.
        missing = sorted({term for terms_missing in per_candidate_missing for term in terms_missing})
    # Existence questions need a direct topic hit, not merely many adjacent
    # papers. A missing key term such as "超导" changes the requested topic.
    return {"matched": False, "missing_terms": missing}


def _direct_query_terms(query: str) -> list[str]:
    q = (query or "").lower()
    terms: list[str] = []
    for term in _CJK_KEY_TERMS:
        if term in query and term not in terms:
            terms.append(term)
    for raw in _EN_TOKEN_RE.findall(q):
        if raw in _STOP_TERMS or len(raw) < 4:
            continue
        if raw not in terms:
            terms.append(raw)
    # If no dictionary term was found, fall back to CJK bigrams from the topic
    # phrase; this keeps the rule useful without pretending to be a segmenter.
    if not terms:
        cjk = "".join(_CJK_RE.findall(query or ""))
        for index in range(max(0, len(cjk) - 1)):
            term = cjk[index:index + 2]
            if term and term not in _STOP_TERMS and term not in terms:
                terms.append(term)
    return terms[:8]


def _term_present(term: str, text: str) -> bool:
    aliases = _TERM_ALIASES.get(term, (term,))
    return any(alias.lower() in text for alias in aliases)
