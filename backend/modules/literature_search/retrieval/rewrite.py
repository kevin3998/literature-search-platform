"""Deterministic query rewrite / expansion (Block 2, §3).

Scope (confirmed): rule-based normalization and expansion only —
    DOI / title normalization, abbreviation + synonym expansion, recency /
    metric / section-aware hints, conservative bilingual domain aliases, and
    no-hit relaxation.

The bilingual aliases are intentionally tiny and phrase-based. They are a
retrieval recall aid for English-heavy local indexes, not semantic analysis.
``normalize_doi`` and ``relax_query`` are also used directly by the packet
builder's recovery loop.
"""
from __future__ import annotations

import re

from modules.literature_search.retrieval.schemas import QueryIntent, RewrittenQuery

# Small, real domain-abbreviation dictionary. Kept deliberately tiny — this is a
# recall aid, not a knowledge base.
_ABBREVIATIONS = {
    "rag": "retrieval augmented generation",
    "llm": "large language model",
    "llms": "large language models",
    "vlm": "vision language model",
    "moe": "mixture of experts",
    "rl": "reinforcement learning",
    "rlhf": "reinforcement learning from human feedback",
    "gan": "generative adversarial network",
    "cnn": "convolutional neural network",
    "sei": "solid electrolyte interphase",
    "orr": "oxygen reduction reaction",
    "her": "hydrogen evolution reaction",
    "pv": "photovoltaic",
}

_RECENT_HINTS = ("recent advances", "state of the art")
_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "with",
    "what", "is", "are", "how", "does", "do", "请", "的", "了", "在", "和",
    "最新", "进展", "综述", "关于",
}
_QUESTION_RETRIEVAL_STOPWORDS = _STOPWORDS | {
    "paper", "papers", "article", "articles", "study", "studies",
    "discuss", "discusses", "discussed", "about", "find", "show", "shows",
    "list", "tell", "me", "whether", "there", "any",
}
_ENGLISH_QUESTION_PREFIX_RE = re.compile(
    r"^\s*(what|which|who|when|where|why|how|does|do|did|is|are|can|could|find|show|list|tell)\b",
    re.IGNORECASE,
)

_DOI_URL_PREFIX_RE = re.compile(r"^\s*(https?://)?(dx\.)?doi\.org/", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_CJK_PHRASE_ALIASES = (
    ("大语言模型", "large language models"),
    ("大型语言模型", "large language models"),
    ("语言模型", "language models"),
    ("材料发现", "materials discovery"),
    ("材料设计", "materials design"),
    ("材料科学", "materials science"),
    ("机器学习", "machine learning"),
    ("深度学习", "deep learning"),
    ("人工智能", "artificial intelligence"),
    ("应用", "applications"),
)


def normalize_doi(raw: str) -> str:
    """Strip URL prefixes, lowercase, and drop trailing punctuation from a DOI."""
    value = _DOI_URL_PREFIX_RE.sub("", (raw or "").strip())
    value = value.strip().rstrip(".,;)]}>\"'")
    return value.lower()


def normalize_title(raw: str) -> str:
    """Lowercase, strip punctuation/quotes for fuzzy/FTS title matching."""
    value = re.sub(r"[\"“”『」「]", " ", raw or "")
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def _expand_abbreviations(query: str) -> str | None:
    tokens = re.findall(r"[A-Za-z]+", query)
    expansions = [_ABBREVIATIONS[t.lower()] for t in tokens if t.lower() in _ABBREVIATIONS]
    if not expansions:
        return None
    return (query + " " + " ".join(expansions)).strip()


def relax_query(query: str, *, keep: int = 4) -> str:
    """Drop stopwords and keep the highest-signal terms for a no-hit retry."""
    tokens = [t for t in re.findall(r"[\w]+", query or "") if t.lower() not in _STOPWORDS]
    if not tokens:
        return (query or "").strip()
    # Prefer longer tokens (more discriminative) but preserve original order.
    ranked = sorted(tokens, key=len, reverse=True)[:keep]
    kept = [t for t in tokens if t in ranked]
    return " ".join(dict.fromkeys(kept))


def _english_alias_for_cjk_query(query: str) -> str | None:
    if not _CJK_RE.search(query or ""):
        return None
    aliases: list[str] = []
    for phrase, alias in _CJK_PHRASE_ALIASES:
        if phrase == "语言模型" and ("大语言模型" in query or "大型语言模型" in query):
            continue
        if phrase in query and alias not in aliases:
            aliases.append(alias)
    if not aliases:
        return None
    # "applications" is too broad as a trailing standalone retrieval term for
    # local FTS; keep it only when it is the only useful alias.
    if len(aliases) > 1 and aliases[-1] == "applications":
        aliases = aliases[:-1]
    return " ".join(aliases)


def _english_question_retrieval_query(query: str) -> str | None:
    if _CJK_RE.search(query or ""):
        return None
    text = (query or "").strip()
    if not text or not (text.endswith("?") or _ENGLISH_QUESTION_PREFIX_RE.search(text)):
        return None
    tokens = re.findall(r"[A-Za-z0-9]+", text)
    kept = [token for token in tokens if token.lower() not in _QUESTION_RETRIEVAL_STOPWORDS]
    if len(kept) < 2 or len(kept) == len(tokens):
        return None
    normalized = " ".join(dict.fromkeys(kept))
    return normalized if normalized and normalized.lower() != text.rstrip("?").lower() else None


def rewrite_query(query: str, intent: QueryIntent) -> list[RewrittenQuery]:
    """Produce ordered retrieval expressions. The first is always the primary."""
    query = (query or "").strip()
    out: list[RewrittenQuery] = []
    seen: set[str] = set()

    def add(text: str, reason: str, *, retrieval_hint: str | None = None, filters_hint: dict | None = None) -> None:
        norm = (text or "").strip()
        key = norm.lower()
        if not norm or key in seen:
            return
        seen.add(key)
        out.append(RewrittenQuery(query=norm, reason=reason, retrieval_hint=retrieval_hint, filters_hint=filters_hint or {}))

    if intent.type == "doi":
        doi = normalize_doi(intent.detected_entities.get("doi") or query)
        add(doi, "doi normalization", retrieval_hint="metadata_lookup")
        return out

    if intent.type == "title":
        title = intent.detected_entities.get("title") or query
        add(title, "primary title query", retrieval_hint="fts")
        add(normalize_title(title), "title normalization (punctuation/case stripped)", retrieval_hint="fts")
        return out

    cjk_alias = _english_alias_for_cjk_query(query)
    if cjk_alias:
        add(cjk_alias, "conservative Chinese-to-English retrieval alias", retrieval_hint=intent.suggested_retrieval)

    english_question = _english_question_retrieval_query(query)
    if english_question:
        add(english_question, "English research-question retrieval normalization", retrieval_hint=intent.suggested_retrieval)

    # Keep the original wording in the rewrite list for auditability and for
    # indexes that actually contain Chinese text.
    add(query, "primary query", retrieval_hint=intent.suggested_retrieval)

    abbreviated = _expand_abbreviations(query)
    if abbreviated:
        add(abbreviated, "abbreviation expansion", retrieval_hint=intent.suggested_retrieval)

    if intent.type == "recent_review":
        for hint in _RECENT_HINTS:
            add(f"{query} {hint}", "recency expansion", retrieval_hint="hybrid")

    if intent.type == "metric_compare":
        add(f"{query} results table", "metric/table-oriented expansion",
            retrieval_hint="hybrid", filters_hint={"kind": "table_row"})

    if intent.type == "mechanism":
        add(f"{query} method", "method/result section-aware expansion",
            retrieval_hint="hybrid", filters_hint={"section": "method"})

    return out
