from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .models import PaperCandidate

API_BASE = "https://api.exa.ai/search"


def available(api_key: str | None = None) -> bool:
    return bool((api_key or os.getenv("EXA_API_KEY", "")).strip())


def search(query: str, year_from: int, year_to: int, limit: int, *, api_key: str | None = None, timeout: int = 30, retries: int = 2) -> list[PaperCandidate]:
    api_key = (api_key or os.getenv("EXA_API_KEY", "")).strip()
    if not api_key:
        return []
    payload = {
        "query": f"{query} scholarly paper {year_from}..{year_to}",
        "numResults": limit,
        "type": "neural",
        "contents": {"text": {"maxCharacters": 900}},
    }
    data = request_json(payload, api_key=api_key, retries=retries, timeout=timeout)
    out: list[PaperCandidate] = []
    for item in data.get("results") or []:
        title = item.get("title") or item.get("url") or "Untitled Exa result"
        out.append(
            PaperCandidate(
                id=f"exa:{item.get('id') or item.get('url') or title}",
                title=title,
                source="exa",
                year=_extract_year(item),
                url=item.get("url"),
                abstract=((item.get("text") or item.get("snippet") or "")[:1200] or None),
                verification="verify_pending",
                query=query,
                metadata={"publishedDate": item.get("publishedDate"), "score": item.get("score")},
            )
        )
    return out


def request_json(payload: dict[str, Any], *, api_key: str, retries: int = 2, timeout: int = 30) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_BASE,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": api_key,
            "User-Agent": "literature-agent-platform-exa/1.0",
        },
    )
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


def _extract_year(item: dict[str, Any]) -> int | None:
    value = item.get("publishedDate") or ""
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None
