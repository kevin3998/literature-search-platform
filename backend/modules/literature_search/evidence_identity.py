"""Canonical runtime identity for literature evidence.

Source assets remain independently auditable. These helpers only decide when
two runtime evidence records represent the same citable evidence.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

ABSTRACT_MIN_NEAR_MATCH_CHARS = 200
ABSTRACT_MIN_LENGTH_RATIO = 0.85
ABSTRACT_MIN_SIMILARITY = 0.92


def evidence_value(evidence: Any, key: str) -> Any:
    if isinstance(evidence, dict):
        return evidence.get(key)
    return getattr(evidence, key, None)


def source_namespace(evidence: Any) -> str:
    explicit = _clean(evidence_value(evidence, "source_namespace")).lower()
    if explicit:
        return explicit
    source_type = _clean(evidence_value(evidence, "source_type")).lower()
    if source_type in {"", "literature_search", "research_index", "search", "paper_chunks"}:
        return "research_index"
    if source_type in {"pack", "evidence_pack"}:
        return "evidence_pack"
    return source_type


def physical_evidence_key(evidence: Any) -> str | None:
    evidence_id = _clean(evidence_value(evidence, "evidence_id"))
    namespace = source_namespace(evidence)
    if not evidence_id or not namespace:
        return None
    return f"{namespace}:{evidence_id}"


def paper_stable_id(evidence: Any) -> str | None:
    doi = _clean(evidence_value(evidence, "doi"))
    if doi:
        return f"doi:{doi.lower()}"
    for key, prefix in (("pmid", "pmid"), ("arxiv_id", "arxiv"), ("paper_id", "paper")):
        value = _clean(evidence_value(evidence, key))
        if value:
            return f"{prefix}:{value.lower()}"
    article_id = evidence_value(evidence, "article_id")
    if article_id is not None and str(article_id).strip():
        return f"article:{article_id}"
    return None


def normalize_evidence_text(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"\s+", " ", value).strip()


def evidence_text(evidence: Any) -> str:
    # Prefer the stable document/context text used only for identity matching.
    # The shorter snippet remains the citation snapshot shown to the model/user.
    for key in ("canonical_text", "expanded_context", "chunk_text", "text", "full_text", "snippet"):
        value = evidence_value(evidence, key)
        if value:
            return str(value)
    return ""


def is_abstract_evidence(evidence: Any) -> bool:
    kind = _clean(evidence_value(evidence, "kind")).lower()
    if kind == "abstract":
        return True
    labels = " ".join(
        _clean(evidence_value(evidence, key)).lower()
        for key in ("section", "section_id", "heading_norm", "label")
    )
    path = _clean(evidence_value(evidence, "source_path")).lower()
    return "abstract" in labels or path.endswith("/abstract.txt") or path == "abstract.txt"


def evidence_equivalent(left: Any, right: Any) -> bool:
    left_physical = physical_evidence_key(left)
    right_physical = physical_evidence_key(right)
    if left_physical and left_physical == right_physical:
        return True

    left_paper = paper_stable_id(left)
    if not left_paper or left_paper != paper_stable_id(right):
        return False
    if not is_abstract_evidence(left) or not is_abstract_evidence(right):
        return False

    left_text = normalize_evidence_text(evidence_text(left))
    right_text = normalize_evidence_text(evidence_text(right))
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    shortest = min(len(left_text), len(right_text))
    longest = max(len(left_text), len(right_text))
    if shortest < ABSTRACT_MIN_NEAR_MATCH_CHARS or shortest / longest < ABSTRACT_MIN_LENGTH_RATIO:
        return False
    return SequenceMatcher(None, left_text, right_text, autojunk=False).ratio() >= ABSTRACT_MIN_SIMILARITY


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
