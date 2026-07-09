from __future__ import annotations

import re

from .models import QueryPacket

TEMPLATE_TERMS = {
    "prior_work", "so_what", "unverified", "verify_pending", "risk", "medium",
    "low", "high", "local", "evidence", "idea", "verdict", "score", "recommendation",
    "effort_note", "contribution", "summary", "hypothesis",
}

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "using", "based",
    "study", "research", "paper", "candidate", "core", "claim", "claims",
}

DOMAIN_MAP = {
    "材料": ["materials science", "materials informatics"],
    "材料科学": ["materials science", "materials informatics"],
    "大语言模型": ["large language models", "LLM"],
    "语言模型": ["large language models", "LLM"],
    "显微": ["microscopy"],
    "表征": ["materials characterization"],
    "智能体": ["autonomous materials discovery", "LLM agents"],
}

DOMAIN_ANCHORS = [
    "materials science",
    "large language models",
    "materials informatics",
]


def build_query_packet(topic: str, idea_text: str, *, current_year: int = 2026, max_queries_per_idea: int = 3) -> QueryPacket:
    year_from = current_year - 3
    ideas = _split_ideas(idea_text)
    dropped: list[str] = []
    queries_by_idea: dict[str, list[str]] = {}
    topic_terms, topic_dropped = _terms(topic)
    dropped.extend(topic_dropped)
    anchors = _domain_anchors(topic, idea_text)
    for idx, idea in enumerate(ideas, 1):
        idea_terms, idea_dropped = _terms(idea)
        dropped.extend(idea_dropped)
        title = _title(idea)
        title_terms, title_dropped = _terms(title)
        dropped.extend(title_dropped)
        base_terms = _uniq([*anchors, *topic_terms, *title_terms, *idea_terms])
        queries = [
            " ".join(_uniq([*anchors[:2], *title_terms[:4], *idea_terms[:4]])),
            " ".join(_uniq([*anchors, *idea_terms[:6]])),
            " ".join(_uniq([*topic_terms[:4], *title_terms[:4], *anchors[:2]])),
        ]
        cleaned = []
        for q in queries:
            q = _clean_query(q)
            if q and q not in cleaned:
                cleaned.append(q)
        if not cleaned:
            cleaned = [" ".join(base_terms[:8]) or "materials science large language models"]
        queries_by_idea[f"idea_{idx}"] = cleaned[:max_queries_per_idea]
    return QueryPacket(queries_by_idea, sorted(set(dropped)), year_from, current_year)


def _split_ideas(text: str) -> list[str]:
    chunks = re.split(r"\n(?=###\s+Idea\s+\d+[:：])", text or "")
    ideas = [c.strip() for c in chunks if re.search(r"^###\s+Idea\s+\d+", c.strip(), re.M)]
    if ideas:
        return ideas[:12]
    return [(text or "").strip()]


def _title(text: str) -> str:
    m = re.search(r"Idea\s+\d+[:：]\s*(.+)", text or "")
    return m.group(1).strip() if m else ""


def _domain_anchors(*texts: str) -> list[str]:
    joined = " ".join(texts)
    anchors: list[str] = []
    for needle, values in DOMAIN_MAP.items():
        if needle in joined:
            anchors.extend(values)
    if re.search(r"\b(llm|gpt|claude|large language model)", joined, re.I):
        anchors.extend(["large language models", "LLM"])
    if re.search(r"\b(xrd|sem|microscopy|materials)", joined, re.I):
        anchors.extend(["materials science"])
    anchors.extend(DOMAIN_ANCHORS)
    return _uniq(anchors)


def _terms(text: str) -> tuple[list[str], list[str]]:
    raw = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", text or "")
    terms: list[str] = []
    dropped: list[str] = []
    for token in raw:
        lower = token.lower()
        if lower in TEMPLATE_TERMS:
            dropped.append(lower)
            continue
        if lower in STOPWORDS:
            continue
        if len(lower) <= 2 and lower not in {"llm", "xrd", "sem"}:
            continue
        terms.append(lower)
    return _uniq(terms), _uniq(dropped)


def _clean_query(query: str) -> str:
    words = []
    for token in query.split():
        lower = token.lower()
        if lower in TEMPLATE_TERMS or lower in STOPWORDS:
            continue
        words.append(token)
    return " ".join(_uniq(words[:12])).strip()


def _uniq(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out
