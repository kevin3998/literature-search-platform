from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .models import PaperCandidate

API_BASE = "https://api.openalex.org/works"


def search(query: str, year_from: int, year_to: int, limit: int, *, email: str | None = None, api_key: str | None = None, timeout: int = 30, retries: int = 2) -> list[PaperCandidate]:
    filters = f"from_publication_date:{year_from}-01-01,to_publication_date:{year_to}-12-31"
    params = {
        "search": query,
        "per-page": limit,
        "filter": filters,
        "sort": "relevance_score:desc",
    }
    email = (email or os.getenv("OPENALEX_EMAIL", "")).strip()
    api_key = (api_key or os.getenv("OPENALEX_API_KEY", "")).strip()
    if email:
        params["mailto"] = email
    if api_key:
        params["api_key"] = api_key
    payload = request_json(f"{API_BASE}?{urllib.parse.urlencode(params)}", retries=retries, timeout=timeout)
    return [parse_work(item, query=query) for item in payload.get("results") or []]


def request_json(url: str, *, retries: int = 2, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers())
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                last = exc
                continue
            raise RuntimeError(f"HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                last = exc
                continue
            raise RuntimeError(f"Network error: {exc}") from exc
    raise RuntimeError(f"Request failed after retries: {last}")


def parse_work(work: dict[str, Any], *, query: str | None = None) -> PaperCandidate:
    doi = _clean_doi(work.get("doi"))
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return PaperCandidate(
        id=f"openalex:{work.get('id') or doi or work.get('display_name')}",
        title=_clean(work.get("display_name") or work.get("title")),
        source="openalex",
        year=_to_int(work.get("publication_year")),
        doi=doi,
        url=work.get("id"),
        abstract=_abstract_from_inverted_index(work.get("abstract_inverted_index")),
        venue=_clean(source.get("display_name")),
        citation_count=_to_int(work.get("cited_by_count")),
        verification="verify_pending",
        query=query,
        metadata={
            "openalex_type": work.get("type"),
            "venue_type": source.get("type"),
            "is_oa": (work.get("open_access") or {}).get("is_oa"),
        },
    )


def headers() -> dict[str, str]:
    email = os.getenv("OPENALEX_EMAIL", "").strip()
    if email:
        return {"User-Agent": f"literature-agent-platform-openalex/1.0 (mailto:{email})", "Accept": "application/json"}
    return {"User-Agent": "literature-agent-platform-openalex/1.0", "Accept": "application/json"}


def _abstract_from_inverted_index(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, offsets in index.items():
        for offset in offsets or []:
            positions.append((int(offset), word))
    if not positions:
        return None
    return " ".join(word for _, word in sorted(positions))


def _clean_doi(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    return text or None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
