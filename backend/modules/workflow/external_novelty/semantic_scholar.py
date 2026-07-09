from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .models import PaperCandidate

API_BASE = "https://api.semanticscholar.org/graph/v1"
DEFAULT_FIELDS = (
    "paperId,title,abstract,year,venue,publicationVenue,publicationTypes,"
    "publicationDate,url,openAccessPdf,authors,externalIds,citationCount,"
    "referenceCount,fieldsOfStudy,s2FieldsOfStudy,tldr"
)


def search(query: str, year_from: int, year_to: int, limit: int, *, api_key: str | None = None, timeout: int = 30, retries: int = 2) -> list[PaperCandidate]:
    params = {
        "query": query,
        "limit": limit,
        "fields": DEFAULT_FIELDS,
        "year": f"{year_from}-{year_to}",
    }
    payload = request_json(f"{API_BASE}/paper/search?{urllib.parse.urlencode(params)}", api_key=api_key, retries=retries, timeout=timeout)
    return [parse_paper(item, query=query) for item in payload.get("data") or []]


def request_json(url: str, *, retries: int = 2, timeout: int = 30, api_key: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers(api_key=api_key))
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                last = exc
                continue
            msg = f"HTTP {exc.code}"
            if body:
                msg += f": {body}"
            raise RuntimeError(msg) from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                last = exc
                continue
            raise RuntimeError(f"Network error: {exc}") from exc
    raise RuntimeError(f"Request failed after retries: {last}")


def parse_paper(paper: dict[str, Any], *, query: str | None = None) -> PaperCandidate:
    ext = paper.get("externalIds") or {}
    venue = paper.get("venue") or ((paper.get("publicationVenue") or {}).get("name"))
    return PaperCandidate(
        id=f"s2:{paper.get('paperId') or ext.get('DOI') or paper.get('title')}",
        title=_clean(paper.get("title")),
        source="semantic_scholar",
        year=_to_int(paper.get("year")),
        doi=ext.get("DOI"),
        arxiv_id=ext.get("ArXiv"),
        url=paper.get("url"),
        abstract=_clean(paper.get("abstract")),
        venue=_clean(venue),
        citation_count=_to_int(paper.get("citationCount")),
        verification="verify_pending",
        query=query,
        metadata={
            "publicationTypes": paper.get("publicationTypes"),
            "fieldsOfStudy": paper.get("fieldsOfStudy"),
            "tldr": paper.get("tldr"),
        },
    )


def headers(*, api_key: str | None = None) -> dict[str, str]:
    out = {"User-Agent": "literature-agent-platform-s2/1.0", "Accept": "application/json"}
    resolved = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if resolved:
        out["x-api-key"] = resolved
    return out


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\n", " ")
    return text or None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
