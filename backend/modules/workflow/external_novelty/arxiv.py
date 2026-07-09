from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .models import PaperCandidate

ATOM_NS = "http://www.w3.org/2005/Atom"
API_BASE = "http://export.arxiv.org/api/query"
NEW_STYLE_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
OLD_STYLE_ID_RE = re.compile(r"^[A-Za-z.-]+/\d{7}(v\d+)?$")


def normalize_arxiv_id(value: str) -> str:
    raw = (value or "").strip()
    if "/abs/" in raw:
        raw = raw.split("/abs/", 1)[1]
    if raw.startswith("id:"):
        raw = raw[3:]
    return re.sub(r"v\d+$", "", raw)


def looks_like_arxiv_id(value: str) -> bool:
    value = (value or "").strip()
    return bool(NEW_STYLE_ID_RE.match(value) or OLD_STYLE_ID_RE.match(value))


def search(query: str, year_from: int, year_to: int, limit: int, *, timeout: int = 30, retries: int = 2) -> list[PaperCandidate]:
    params = {"start": 0, "max_results": limit, "sortBy": "relevance", "sortOrder": "descending"}
    if looks_like_arxiv_id(query) or str(query).startswith("id:"):
        params["id_list"] = normalize_arxiv_id(query)
    else:
        params["search_query"] = query
    root = fetch_atom(API_BASE + "?" + urllib.parse.urlencode(params), timeout=timeout, retries=retries)
    return [p for p in parse_atom(ET.tostring(root, encoding="unicode"), query=query) if not p.year or year_from <= p.year <= year_to]


def fetch_atom(url: str, *, timeout: int = 30, retries: int = 2) -> ET.Element:
    req = urllib.request.Request(url, headers={"User-Agent": arxiv_user_agent()})
    for attempt in range(1, max(1, retries) + 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt <= retries:
                time.sleep(5 * attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt <= retries:
                time.sleep(2 * attempt)
                continue
            raise
        if body.strip() == b"Rate exceeded.":
            if attempt <= retries:
                time.sleep(5 * attempt)
                continue
            raise RuntimeError("arXiv API rate-limited")
        return ET.fromstring(body)
    raise RuntimeError("arXiv API fetch failed")


def parse_atom(raw_xml: str, *, query: str | None = None) -> list[PaperCandidate]:
    root = ET.fromstring(raw_xml)
    out: list[PaperCandidate] = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        raw_id = entry.findtext(f"{{{ATOM_NS}}}id", "") or ""
        arxiv_id = normalize_arxiv_id(raw_id)
        title = _clean(entry.findtext(f"{{{ATOM_NS}}}title", "") or "")
        abstract = _clean(entry.findtext(f"{{{ATOM_NS}}}summary", "") or "")
        published = (entry.findtext(f"{{{ATOM_NS}}}published", "") or "")[:4]
        year = _to_int(published)
        categories = [c.get("term", "") for c in entry.findall(f"{{{ATOM_NS}}}category") if c.get("term")]
        out.append(PaperCandidate(
            id=f"arxiv:{arxiv_id}",
            title=title,
            source="arxiv",
            year=year,
            arxiv_id=arxiv_id,
            url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else raw_id,
            abstract=abstract,
            verification="verify_pending",
            query=query,
            metadata={"categories": categories},
        ))
    return out


def arxiv_user_agent() -> str:
    contact = os.getenv("ARIS_VERIFY_EMAIL", "").strip()
    base = "literature-agent-platform-arxiv/1.0"
    return f"{base} (mailto:{contact})" if contact else base


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
