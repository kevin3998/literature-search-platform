from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from typing import Callable, Iterable

from . import arxiv
from .models import PaperCandidate, VerificationResult

LookupArxiv = Callable[[list[str]], dict[str, str]]
LookupDoi = Callable[[str], str]
LookupTitle = Callable[[str], str]

TERMINAL_STATUSES = {"verified", "unverified"}
PENDING_STATUSES = {"verify_pending", "source_error"}


def verify_candidates(
    candidates: Iterable[PaperCandidate],
    *,
    arxiv_lookup: LookupArxiv | None = None,
    doi_lookup: LookupDoi | None = None,
    title_lookup: LookupTitle | None = None,
    warn_threshold: float = 0.2,
) -> VerificationResult:
    papers = list(candidates)
    arxiv_lookup = arxiv_lookup or _lookup_arxiv
    doi_lookup = doi_lookup or _lookup_crossref_doi
    title_lookup = title_lookup or _lookup_semantic_title

    arxiv_ids = sorted({p.arxiv_id for p in papers if p.arxiv_id})
    arxiv_status: dict[str, str] = {}
    if arxiv_ids:
        try:
            arxiv_status = arxiv_lookup(arxiv_ids)
        except Exception:  # noqa: BLE001 - one verifier source should not erase candidates
            arxiv_status = {aid: "verify_pending" for aid in arxiv_ids}

    for paper in papers:
        status = None
        if paper.arxiv_id:
            status = arxiv_status.get(paper.arxiv_id)
        if not status and paper.doi:
            try:
                status = doi_lookup(paper.doi)
            except Exception:  # noqa: BLE001
                status = "verify_pending"
        if not status and paper.title:
            try:
                status = title_lookup(paper.title)
            except Exception:  # noqa: BLE001
                status = "verify_pending"
        paper.verification = _normalize_status(status or "unverified")

    hallucination_rate, pending_rate = _rates(papers)
    warnings: list[str] = []
    if hallucination_rate > warn_threshold:
        warnings.append("high_hallucination_rate")
    if pending_rate > 0:
        warnings.append("verification_pending")
    verdict = "PASS" if not warnings else "WARN"
    return VerificationResult(
        papers=papers,
        verdict=verdict,
        hallucination_rate=hallucination_rate,
        pending_rate=pending_rate,
        warnings=warnings,
    )


def _lookup_arxiv(ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for aid in ids:
        try:
            found = arxiv.search(f"id:{aid}", 1900, 2100, 1)
            out[aid] = "verified" if any(p.arxiv_id == aid for p in found) else "unverified"
        except Exception:  # noqa: BLE001
            out[aid] = "verify_pending"
    return out


def _lookup_crossref_doi(doi: str) -> str:
    encoded = urllib.parse.quote((doi or "").strip(), safe="")
    if not encoded:
        return "unverified"
    req = urllib.request.Request(
        f"https://api.crossref.org/works/{encoded}",
        headers={"User-Agent": "literature-agent-platform-crossref/1.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                return "verified" if payload.get("message") else "unverified"
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 500, 502, 503, 504):
            return "verify_pending"
        return "unverified"
    except Exception:  # noqa: BLE001
        return "verify_pending"
    return "unverified"


def _lookup_semantic_title(title: str) -> str:
    if not title:
        return "unverified"
    fields = "title"
    params = urllib.parse.urlencode({"query": title, "limit": 5, "fields": fields})
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if not api_key:
        try:
            from core.secret_store import secret_store

            api_key = secret_store.get("external:semantic_scholar") or ""
        except Exception:  # noqa: BLE001
            api_key = ""
    headers = {"User-Agent": "literature-agent-platform-s2-verify/1.0", "Accept": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    req = urllib.request.Request(
        f"https://api.semanticscholar.org/graph/v1/paper/search?{params}",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (429, 500, 502, 503, 504):
            return "verify_pending"
        return "unverified"
    except Exception:  # noqa: BLE001
        return "verify_pending"
    needle = _norm_title(title)
    for paper in payload.get("data") or []:
        candidate = _norm_title(paper.get("title") or "")
        if candidate and SequenceMatcher(None, needle, candidate).ratio() >= 0.9:
            return "verified"
    return "unverified"


def _rates(papers: list[PaperCandidate]) -> tuple[float, float]:
    if not papers:
        return 0.0, 0.0
    total = len(papers)
    unverified = sum(1 for p in papers if p.verification == "unverified")
    pending = sum(1 for p in papers if p.verification in PENDING_STATUSES)
    return round(unverified / total, 4), round(pending / total, 4)


def _normalize_status(value) -> str:
    if isinstance(value, bool):
        return "verified" if value else "unverified"
    status = str(value or "").strip().lower()
    if status in {"verified", "unverified", "verify_pending", "source_error"}:
        return status
    if status in {"pending", "timeout", "rate_limited"}:
        return "verify_pending"
    return "unverified"


def _norm_title(title: str) -> str:
    return re.sub(r"\W+", " ", (title or "").lower()).strip()
