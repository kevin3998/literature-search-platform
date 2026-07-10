"""Persistent citation helpers for literature-search answers.

The model sees short per-answer aliases such as ``[1]``. The platform keeps the
stable evidence identity and the full snapshot needed to audit that alias later.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from typing import Any

from modules.literature_search.evidence_identity import (
    evidence_equivalent,
    evidence_text,
    is_abstract_evidence,
    normalize_evidence_text,
    paper_stable_id as canonical_paper_stable_id,
    physical_evidence_key,
    source_namespace,
)

_NUMERIC_CITATION_RE = re.compile(r"[\[【]([0-9]+)[\]】]")


def normalize_chunk_text(text: Any) -> str:
    return " ".join(str(text or "").split())


def content_hash(text: Any) -> str:
    return hashlib.sha256(normalize_chunk_text(text).encode("utf-8")).hexdigest()


def paper_stable_id(evidence: dict[str, Any]) -> str:
    canonical = canonical_paper_stable_id(evidence)
    if canonical:
        return canonical
    source = _clean(evidence.get("source_path"))
    title = _clean(evidence.get("title"))
    if source:
        return f"source:{source}"
    if title:
        return f"title:{title.lower()}"
    article_id = evidence.get("article_id")
    if article_id is not None:
        return f"article:{article_id}"
    document_id = evidence.get("document_id") or _document_id_from_evidence_id(evidence.get("evidence_id"))
    if document_id is not None:
        return f"document:{document_id}"
    return "unknown"


def build_evidence_uid(evidence: dict[str, Any]) -> str:
    physical_key = physical_evidence_key(evidence)
    if physical_key:
        payload = {"physical_key": physical_key}
    else:
        text = _chunk_text(evidence)
        payload = {
            "source_type": evidence.get("source_type") or "literature_search",
            "paper_stable_id": paper_stable_id(evidence),
            "section_id": evidence.get("section_id") or evidence.get("section") or "",
            "chunk_index": evidence.get("chunk_index"),
            "content_hash": content_hash(text),
        }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_citation_markers(answer: str) -> list[str]:
    found: OrderedDict[str, None] = OrderedDict()
    for match in _NUMERIC_CITATION_RE.finditer(answer or ""):
        found.setdefault(match.group(1), None)
    return list(found)


class CitationRegistry:
    def __init__(self, historical_citations: list[dict[str, Any]] | None = None) -> None:
        self.current_manifest: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._by_source_key: dict[str, str] = {}
        self._by_physical_key: dict[str, str] = {}
        self._abstract_evidence_by_paper: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        self.historical_manifest: dict[str, dict[str, Any]] = {}
        for group in historical_citations or []:
            message_id = group.get("message_id")
            for item in group.get("citations") or []:
                alias = str(item.get("alias") or "")
                if message_id and alias:
                    self.historical_manifest[f"{message_id}:{alias}"] = {**item, "message_id": message_id}

    def register_tool_evidence(self, evidence_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        registered: list[dict[str, Any]] = []
        for item in evidence_items or []:
            snapshot = self.register_evidence(item)
            if snapshot is not None:
                registered.append(snapshot)
        return registered

    def register_evidence(self, evidence: dict[str, Any]) -> dict[str, Any] | None:
        if evidence.get("in_llm_context") is False:
            return None

        physical_key = physical_evidence_key(evidence)
        alias = self._by_physical_key.get(physical_key or "")
        matched_physical = bool(alias)
        source_key = _source_key(evidence)
        if not alias:
            alias = self._by_source_key.get(source_key)
        if not alias and is_abstract_evidence(evidence):
            paper_key = canonical_paper_stable_id(evidence)
            for candidate_alias, candidate in self._abstract_evidence_by_paper.get(paper_key or "", []):
                if evidence_equivalent(evidence, candidate):
                    alias = candidate_alias
                    break

        if alias:
            if matched_physical:
                self._merge_same_physical(alias, evidence)
            elif physical_key and physical_key != physical_evidence_key(self._primary_evidence(alias)):
                self._append_equivalent_source(alias, evidence)
            self._index_evidence(alias, evidence, source_key=source_key, physical_key=physical_key)
            return self.current_manifest[alias]

        alias = str(len(self.current_manifest) + 1)
        self.current_manifest[alias] = build_manifest_item(alias, evidence)
        self._index_evidence(alias, evidence, source_key=source_key, physical_key=physical_key)
        return self.current_manifest[alias]

    def _index_evidence(
        self,
        alias: str,
        evidence: dict[str, Any],
        *,
        source_key: str,
        physical_key: str | None,
    ) -> None:
        self._by_source_key[source_key] = alias
        if physical_key:
            self._by_physical_key[physical_key] = alias
        if is_abstract_evidence(evidence):
            paper_key = canonical_paper_stable_id(evidence)
            if paper_key:
                rows = self._abstract_evidence_by_paper.setdefault(paper_key, [])
                existing_index = next(
                    (index for index, (existing_alias, _) in enumerate(rows) if existing_alias == alias),
                    None,
                )
                if existing_index is None:
                    rows.append((alias, dict(evidence)))
                else:
                    _, representative = rows[existing_index]
                    same_physical = physical_key and physical_key == physical_evidence_key(representative)
                    if same_physical and len(normalize_evidence_text(evidence_text(evidence))) > len(
                        normalize_evidence_text(evidence_text(representative))
                    ):
                        rows[existing_index] = (alias, dict(evidence))

    def _merge_same_physical(self, alias: str, evidence: dict[str, Any]) -> None:
        current = self.current_manifest[alias]
        incoming = build_manifest_item(alias, evidence)
        current["paper"] = _fill_missing(current.get("paper") or {}, incoming.get("paper") or {})
        current["source_locator"] = _fill_missing(current.get("source_locator") or {}, incoming.get("source_locator") or {})
        for key in ("section", "section_id", "chunk_index", "index_version"):
            if current.get(key) in (None, "") and incoming.get(key) not in (None, ""):
                current[key] = incoming[key]
        if len(normalize_evidence_text(incoming.get("chunk_text"))) > len(normalize_evidence_text(current.get("chunk_text"))):
            current["chunk_text"] = incoming["chunk_text"]
            current["chunk_snapshot_hash"] = incoming["chunk_snapshot_hash"]
            current["display_snippet"] = incoming["display_snippet"]

    def _append_equivalent_source(self, alias: str, evidence: dict[str, Any]) -> None:
        locator = self.current_manifest[alias].setdefault("source_locator", {})
        incoming = _source_locator(evidence)
        primary_key = _locator_key(locator)
        existing = locator.setdefault("equivalent_sources", [])
        if _locator_key(incoming) != primary_key and all(_locator_key(item) != _locator_key(incoming) for item in existing):
            existing.append(incoming)

    def _primary_evidence(self, alias: str) -> dict[str, Any]:
        item = self.current_manifest[alias]
        paper = item.get("paper") or {}
        locator = item.get("source_locator") or {}
        return {
            **paper,
            **locator,
            "source_namespace": locator.get("source_namespace"),
            "source_type": locator.get("source_type"),
            "evidence_id": locator.get("evidence_id"),
            "section": item.get("section"),
            "section_id": item.get("section_id"),
            "chunk_index": item.get("chunk_index"),
            "snippet": item.get("chunk_text"),
        }

    def available_evidence(self) -> dict[str, dict[str, Any]]:
        return {alias: item_to_available_evidence(item) for alias, item in self.current_manifest.items()}

    def historical_available_evidence(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for item in self.historical_manifest.values():
            alias = str(item.get("alias") or "")
            if alias:
                out[alias] = item_to_available_evidence(item)
        return out

    def resolve_answer(self, answer: str) -> dict[str, Any]:
        cited = parse_citation_markers(answer)
        used: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for alias in cited:
            item = self.current_manifest.get(alias)
            if item is None:
                historical = _find_historical_by_alias(self.historical_manifest, alias)
                if historical is not None:
                    used.append(item_to_used_evidence(historical, scope="historical_message"))
                    continue
                missing.append(alias)
                continue
            used.append(item_to_used_evidence(item, scope="current_turn"))
            rows.append(item_to_message_citation(item))
        return {
            "cited_ids": cited,
            "missing_ids": missing,
            "used_evidence": used,
            "resolved_citations": rows,
            "available_count": len(self.current_manifest) + len(self.historical_manifest),
        }

    def finalize_answer(self, answer: str) -> dict[str, Any]:
        """Return the final user-visible answer plus citation audit payload.

        Aliases are allocated as evidence enters the prompt, so a final answer may
        cite a sparse subset such as ``[32] [36]``. For product UI, compact only
        current-turn citations into first-seen order inside this single assistant
        message. Historical citations keep their original aliases because they
        refer to already persisted previous-message context.
        """
        cited = parse_citation_markers(answer)
        if not cited:
            resolved = self.resolve_answer(answer)
            return {"answer": answer, **resolved}

        if any(alias not in self.current_manifest and _find_historical_by_alias(self.historical_manifest, alias) for alias in cited):
            resolved = self.resolve_answer(answer)
            return {"answer": answer, **resolved}

        alias_map: dict[str, str] = {}
        for alias in cited:
            if alias in self.current_manifest and alias not in alias_map:
                alias_map[alias] = str(len(alias_map) + 1)

        if not alias_map:
            resolved = self.resolve_answer(answer)
            return {"answer": answer, **resolved}

        finalized_answer = _rewrite_current_aliases(answer, alias_map)
        resolved = self._resolve_with_alias_map(finalized_answer, alias_map)
        return {"answer": finalized_answer, **resolved}

    def _resolve_with_alias_map(self, answer: str, alias_map: dict[str, str]) -> dict[str, Any]:
        reverse = {new: old for old, new in alias_map.items()}
        cited = parse_citation_markers(answer)
        used: list[dict[str, Any]] = []
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for alias in cited:
            original_alias = reverse.get(alias, alias)
            item = self.current_manifest.get(original_alias)
            if item is None:
                historical = _find_historical_by_alias(self.historical_manifest, alias)
                if historical is not None:
                    used.append(item_to_used_evidence(historical, scope="historical_message"))
                    continue
                missing.append(alias)
                continue
            remapped = _remap_item_alias(item, alias, original_alias=original_alias)
            used.append(item_to_used_evidence(remapped, scope="current_turn"))
            rows.append(item_to_message_citation(remapped))
        return {
            "cited_ids": cited,
            "missing_ids": missing,
            "used_evidence": used,
            "resolved_citations": rows,
            "available_count": len(self.current_manifest) + len(self.historical_manifest),
        }


def build_manifest_item(alias: str, evidence: dict[str, Any]) -> dict[str, Any]:
    chunk_text = normalize_chunk_text(_chunk_text(evidence))
    evidence_uid = build_evidence_uid({**evidence, "snippet": chunk_text})
    document_id = evidence.get("document_id") or _document_id_from_evidence_id(evidence.get("evidence_id"))
    return {
        "alias": str(alias),
        "citation_marker": f"[{alias}]",
        "evidence_uid": evidence_uid,
        "source_type": evidence.get("source_type") or "literature_search",
        "source_namespace": source_namespace(evidence),
        "source_locator": _source_locator({**evidence, "document_id": document_id}),
        "paper": {
            "paper_id": evidence.get("paper_id"),
            "paper_stable_id": paper_stable_id(evidence),
            "doi": evidence.get("doi"),
            "title": evidence.get("title"),
            "year": evidence.get("year"),
            "journal": evidence.get("journal") or evidence.get("venue"),
        },
        "section": evidence.get("section"),
        "section_id": evidence.get("section_id"),
        "chunk_index": evidence.get("chunk_index"),
        "index_version": evidence.get("index_version"),
        "chunk_text": chunk_text,
        "chunk_snapshot_hash": content_hash(chunk_text),
        "display_snippet": _display_snippet(evidence.get("display_snippet") or evidence.get("snippet") or chunk_text),
    }


def item_to_available_evidence(item: dict[str, Any]) -> dict[str, Any]:
    paper = item.get("paper") or {}
    locator = item.get("source_locator") or {}
    equivalent_sources = locator.get("equivalent_sources") or []
    return {
        "evidence_id": str(item.get("alias") or ""),
        "alias": str(item.get("alias") or ""),
        "evidence_uid": item.get("evidence_uid"),
        "source_namespace": item.get("source_namespace") or locator.get("source_namespace"),
        "source_evidence_id": locator.get("evidence_id"),
        "equivalent_source_evidence_ids": _dedupe_values(source.get("evidence_id") for source in equivalent_sources),
        "equivalent_source_locators": equivalent_sources,
        "paper_id": paper.get("paper_id"),
        "doi": paper.get("doi"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "journal": paper.get("journal"),
        "section": item.get("section") or item.get("section_id"),
        "section_id": item.get("section_id"),
        "chunk_index": item.get("chunk_index"),
        "index_version": item.get("index_version"),
        "source_path": locator.get("source_path"),
        "snippet": item.get("display_snippet") or item.get("chunk_text"),
    }


def item_to_used_evidence(item: dict[str, Any], *, scope: str) -> dict[str, Any]:
    available = item_to_available_evidence(item)
    return {
        **available,
        "alias": str(item.get("alias") or ""),
        "citation_alias": str(item.get("alias") or ""),
        "citation_marker": item.get("citation_marker") or f"[{item.get('alias')}]",
        "scope": scope,
    }


def item_to_message_citation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "alias": str(item.get("alias") or ""),
        "citation_marker": item.get("citation_marker") or f"[{item.get('alias')}]",
        "evidence_uid": item.get("evidence_uid"),
        "source_type": item.get("source_type") or "literature_search",
        "source_locator": item.get("source_locator") or {},
        "paper_snapshot": item.get("paper") or {},
        "chunk_snapshot_text": item.get("chunk_text") or "",
        "chunk_snapshot_hash": item.get("chunk_snapshot_hash") or content_hash(item.get("chunk_text")),
        "display_snippet": item.get("display_snippet"),
        "citation_context": item.get("citation_context"),
    }


def _rewrite_current_aliases(answer: str, alias_map: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        alias = match.group(1)
        if alias not in alias_map:
            return match.group(0)
        return f"[{alias_map[alias]}]"

    return _NUMERIC_CITATION_RE.sub(replace, answer or "")


def _remap_item_alias(item: dict[str, Any], alias: str, *, original_alias: str) -> dict[str, Any]:
    out = dict(item)
    out["alias"] = str(alias)
    out["citation_marker"] = f"[{alias}]"
    locator = dict(out.get("source_locator") or {})
    if str(original_alias) != str(alias):
        locator["original_alias"] = str(original_alias)
    out["source_locator"] = locator
    return out


def _find_historical_by_alias(items: dict[str, dict[str, Any]], alias: str) -> dict[str, Any] | None:
    for item in items.values():
        if str(item.get("alias") or "") == alias:
            return item
    return None


def _chunk_text(evidence: dict[str, Any]) -> str:
    return str(
        evidence.get("chunk_text")
        or evidence.get("text")
        or evidence.get("full_text")
        or evidence.get("snippet")
        or ""
    )


def _display_snippet(text: Any, limit: int = 500) -> str:
    value = normalize_chunk_text(text)
    return value if len(value) <= limit else value[:limit].rstrip() + "..."


def _source_key(evidence: dict[str, Any]) -> str:
    keys = [
        source_namespace(evidence),
        evidence.get("evidence_id"),
        evidence.get("paper_id") or evidence.get("doi"),
        evidence.get("section_id") or evidence.get("section"),
        evidence.get("chunk_index"),
        evidence.get("source_path"),
        content_hash(_chunk_text(evidence)),
    ]
    return "|".join("" if key is None else str(key) for key in keys)


def _source_locator(evidence: dict[str, Any]) -> dict[str, Any]:
    document_id = evidence.get("document_id") or _document_id_from_evidence_id(evidence.get("evidence_id"))
    return {
        "source_namespace": source_namespace(evidence),
        "source_type": evidence.get("source_type") or "literature_search",
        "evidence_id": evidence.get("evidence_id"),
        "document_id": document_id,
        "paper_id": evidence.get("paper_id"),
        "article_id": evidence.get("article_id"),
        "section": evidence.get("section"),
        "section_id": evidence.get("section_id"),
        "chunk_index": evidence.get("chunk_index"),
        "index_version": evidence.get("index_version"),
        "source_path": evidence.get("source_path"),
    }


def _locator_key(locator: dict[str, Any]) -> tuple[Any, ...]:
    return (
        locator.get("source_namespace"),
        locator.get("evidence_id"),
        locator.get("source_path"),
        locator.get("section_id"),
        locator.get("chunk_index"),
    )


def _fill_missing(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in incoming.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    return merged


def _dedupe_values(values) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _document_id_from_evidence_id(evidence_id: Any) -> int | None:
    text = str(evidence_id or "")
    if len(text) > 1 and text[0].upper() == "E" and text[1:].isdigit():
        return int(text[1:])
    return None


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
