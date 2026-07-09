from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from core.memory_db import dumps, loads, now
from core.user_context import UserContext
from modules.literature_search.corpus import paper_ref
from modules.literature_search import literature_search_shared

from .artifacts import (
    append_candidate_decision,
    write_collection_candidates,
    write_collection_version,
)
from .schemas import (
    BulkCandidateDecisionRequest,
    CandidateDecisionRequest,
    CollectionSearchRequest,
)
from .store import StructuredExtractionStore

DECISIONS = {"candidate", "include", "exclude", "uncertain"}
MAX_SEARCH_LIMIT = 200


class StructuredExtractionCollectionService:
    def __init__(self, store: StructuredExtractionStore) -> None:
        self.store = store

    def search(self, task_id: str, payload: CollectionSearchRequest, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        limit = _bounded_limit(payload.limit)
        query_hash = _source_query_hash(payload)
        rows = self._search_index(payload, limit=limit)
        created = 0
        touched_ids: list[str] = []
        ts = now()
        for row, matched_fields, score in rows:
            ref = paper_ref(row)
            candidate_id, was_created = self._upsert_candidate(
                task_id=task_id,
                user=user,
                row=row,
                ref=ref,
                payload=payload,
                query_hash=query_hash,
                matched_fields=matched_fields,
                metadata_score=score,
                ts=ts,
            )
            touched_ids.append(candidate_id)
            if was_created:
                created += 1
        if touched_ids:
            self._detect_duplicates(task_id, user=user)
            self.store.mark_collecting(task_id, user=user)
        candidates = self.list_candidates(
            task_id,
            user=user,
            source=payload.source,
            query_hash=query_hash,
            limit=limit,
        )["candidates"]
        all_candidates = self.list_candidates(task_id, user=user, limit=0)["candidates"]
        write_collection_candidates(user, task_id, all_candidates)
        return {
            "task_id": task_id,
            "created": created,
            "total_candidates": len(all_candidates),
            "candidates": candidates,
        }

    def list_candidates(
        self,
        task_id: str,
        *,
        user: UserContext,
        decision: str | None = None,
        source: str | None = None,
        q: str | None = None,
        query_hash: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        where = ["task_id = ?", "user_id = ?"]
        params: list[Any] = [task_id, user.user_id]
        if decision:
            where.append("user_decision = ?")
            params.append(decision)
        if source:
            where.append("candidate_source = ?")
            params.append(source)
        if query_hash:
            where.append("source_query_hash = ?")
            params.append(query_hash)
        if q:
            needle = f"%{q.strip().lower()}%"
            where.append("(lower(coalesce(title, '')) like ? or lower(coalesce(doi, '')) like ? or lower(coalesce(journal, '')) like ?)")
            params.extend([needle, needle, needle])
        bounded_limit = _bounded_limit(limit, default=100)
        limit_sql = ""
        if bounded_limit is not None:
            limit_sql = "limit ?"
            params.append(bounded_limit)
        rows = self.store.conn.execute(
            f"""
            select * from structured_extraction_candidates
            where {' and '.join(where)}
            order by metadata_score desc, coalesce(year, 0) desc, lower(coalesce(title, '')) asc, paper_id asc
            {limit_sql}
            """,
            params,
        ).fetchall()
        candidates = [self._row_to_candidate(row) for row in rows]
        return {"task_id": task_id, "candidates": candidates, "counts": self.counts(task_id, user=user)}

    def filter_options(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        index_path = Path(literature_search_shared.service.paths.index_db)
        if not index_path.exists():
            return {
                "task_id": task_id,
                "available": False,
                "reason": "research_index_not_found",
                "years": [],
                "journals": [],
                "sites": [],
            }
        with sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, timeout=3) as conn:
            conn.row_factory = sqlite3.Row
            year_values: set[int] = set()
            for row in conn.execute("select distinct year from papers where year is not null").fetchall():
                year = _coerce_year(row["year"])
                if year is not None:
                    year_values.add(year)
            years = sorted(year_values)
            journals = [
                row["journal"]
                for row in conn.execute(
                    """
                    select distinct trim(journal) as journal
                    from papers
                    where journal is not null and trim(journal) != ''
                    order by lower(trim(journal)) asc
                    limit 500
                    """
                ).fetchall()
            ]
            sites = [
                row["site"]
                for row in conn.execute(
                    """
                    select distinct trim(site) as site
                    from papers
                    where site is not null and trim(site) != ''
                    order by lower(trim(site)) asc
                    limit 200
                    """
                ).fetchall()
            ]
        return {
            "task_id": task_id,
            "available": True,
            "reason": None,
            "years": years,
            "journals": journals,
            "sites": sites,
        }

    def counts(self, task_id: str, *, user: UserContext) -> dict[str, int]:
        rows = self.store.conn.execute(
            """
            select user_decision, count(*) as n
            from structured_extraction_candidates
            where task_id = ? and user_id = ?
            group by user_decision
            """,
            (task_id, user.user_id),
        ).fetchall()
        out = {"candidate": 0, "include": 0, "exclude": 0, "uncertain": 0, "duplicate": 0, "total": 0}
        for row in rows:
            out[row["user_decision"]] = int(row["n"])
            out["total"] += int(row["n"])
        dup = self.store.conn.execute(
            """
            select count(*) from structured_extraction_candidates
            where task_id = ? and user_id = ? and duplicate_group_id is not null
            """,
            (task_id, user.user_id),
        ).fetchone()[0]
        out["duplicate"] = int(dup)
        return out

    def set_decision(
        self,
        task_id: str,
        candidate_id: str,
        payload: CandidateDecisionRequest,
        *,
        user: UserContext,
    ) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        candidate = self._candidate_row(task_id, candidate_id, user=user)
        decision, reason = _validated_decision(payload.decision, payload.exclude_reason)
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_candidates
            set user_decision = ?, exclude_reason = ?, updated_at = ?
            where candidate_id = ? and task_id = ? and user_id = ?
            """,
            (decision, reason, ts, candidate_id, task_id, user.user_id),
        )
        event = {
            "candidate_id": candidate_id,
            "task_id": task_id,
            "paper_id": candidate["paper_id"],
            "event_type": "decision_updated",
            "decision": decision,
            "exclude_reason": reason,
            "created_at": ts,
        }
        self._insert_candidate_event(candidate_id, task_id, user.user_id, "decision_updated", event, ts=ts)
        self.store.conn.commit()
        append_candidate_decision(user, task_id, event)
        self._rewrite_candidates_artifact(task_id, user=user)
        return self._row_to_candidate(self._candidate_row(task_id, candidate_id, user=user))

    def bulk_decision(self, task_id: str, payload: BulkCandidateDecisionRequest, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        decision, reason = _validated_decision(payload.decision, payload.exclude_reason)
        ids = [_clean_candidate_id(candidate_id) for candidate_id in payload.candidate_ids]
        if not ids:
            raise ValueError("candidate_ids is required")
        updated: list[dict[str, Any]] = []
        for candidate_id in ids:
            candidate = self._candidate_row(task_id, candidate_id, user=user)
            ts = now()
            self.store.conn.execute(
                """
                update structured_extraction_candidates
                set user_decision = ?, exclude_reason = ?, updated_at = ?
                where candidate_id = ? and task_id = ? and user_id = ?
                """,
                (decision, reason, ts, candidate_id, task_id, user.user_id),
            )
            event = {
                "candidate_id": candidate_id,
                "task_id": task_id,
                "paper_id": candidate["paper_id"],
                "event_type": "decision_updated",
                "decision": decision,
                "exclude_reason": reason,
                "created_at": ts,
            }
            self._insert_candidate_event(candidate_id, task_id, user.user_id, "decision_updated", event, ts=ts)
            append_candidate_decision(user, task_id, event)
            updated.append({"candidate_id": candidate_id, "paper_id": candidate["paper_id"]})
        self.store.conn.commit()
        self._rewrite_candidates_artifact(task_id, user=user)
        return {"task_id": task_id, "updated": len(updated), "candidates": updated}

    def update_llm_screening(
        self,
        task_id: str,
        results: list[dict[str, Any]],
        *,
        user: UserContext,
    ) -> list[dict[str, Any]]:
        self.store.get_task(task_id, user_id=user.user_id)
        out: list[dict[str, Any]] = []
        for item in results:
            candidate_id = _clean_candidate_id(str(item.get("candidate_id") or ""))
            self._candidate_row(task_id, candidate_id, user=user)
            decision = item.get("decision") if item.get("decision") in {"include", "exclude", "uncertain"} else "uncertain"
            score = item.get("relevance_score")
            try:
                score = None if score is None else float(score)
            except (TypeError, ValueError):
                score = None
            reason = str(item.get("reason") or "")[:1000]
            ts = now()
            self.store.conn.execute(
                """
                update structured_extraction_candidates
                set llm_decision = ?, llm_relevance_score = ?, llm_reason = ?, updated_at = ?
                where candidate_id = ? and task_id = ? and user_id = ?
                """,
                (decision, score, reason, ts, candidate_id, task_id, user.user_id),
            )
            self._insert_candidate_event(
                candidate_id,
                task_id,
                user.user_id,
                "llm_screened",
                {"candidate_id": candidate_id, "decision": decision, "relevance_score": score, "reason": reason},
                ts=ts,
            )
            out.append(self._row_to_candidate(self._candidate_row(task_id, candidate_id, user=user)))
        self.store.conn.commit()
        self._rewrite_candidates_artifact(task_id, user=user)
        return out

    def freeze(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        included = self.store.conn.execute(
            """
            select * from structured_extraction_candidates
            where task_id = ? and user_id = ? and user_decision = 'include'
            order by metadata_score desc, coalesce(year, 0) desc, lower(coalesce(title, '')) asc, paper_id asc
            """,
            (task_id, user.user_id),
        ).fetchall()
        if not included:
            raise ValueError("freeze requires at least one included candidate")
        version = self._next_collection_version(task_id)
        ts = now()
        papers = []
        for row in included:
            candidate = self._row_to_candidate(row)
            ref = loads(row["paper_ref_json"], {}) or {}
            snapshot = {
                **ref,
                "candidate_id": row["candidate_id"],
                "candidate_source": row["candidate_source"],
                "source_query": row["source_query"],
                "matched_fields": candidate["matched_fields"],
                "metadata_score": candidate["metadata_score"],
                "llm_decision": candidate["llm_decision"],
                "llm_relevance_score": candidate["llm_relevance_score"],
                "llm_reason": candidate["llm_reason"],
                "user_decision": candidate["user_decision"],
                "exclude_reason": candidate["exclude_reason"],
            }
            papers.append(snapshot)
        summary = {"included_candidate_ids": [paper["candidate_id"] for paper in papers]}
        self.store.conn.execute(
            """
            insert into structured_extraction_collection_versions(task_id, collection_version, user_id, paper_count, summary_json, created_at)
            values(?, ?, ?, ?, ?, ?)
            """,
            (task_id, version, user.user_id, len(papers), dumps(summary), ts),
        )
        for index, paper in enumerate(papers):
            paper_created_at = ts + (index * 0.000001)
            decision_payload = {
                "candidate_id": paper["candidate_id"],
                "user_decision": paper["user_decision"],
                "llm_decision": paper.get("llm_decision"),
                "llm_relevance_score": paper.get("llm_relevance_score"),
                "source_query": paper.get("source_query"),
                "created_at": paper_created_at,
            }
            self.store.conn.execute(
                """
                insert into structured_extraction_collection_papers(
                    task_id, collection_version, candidate_id, paper_id, paper_ref_json, decision_payload_json, created_at
                ) values(?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, version, paper["candidate_id"], paper["paper_id"], dumps(paper), dumps(decision_payload), paper_created_at),
            )
        self.store.conn.commit()
        out = {
            "collection_version": version,
            "task_id": task_id,
            "paper_count": len(papers),
            "created_at": ts,
            "included_papers": papers,
        }
        write_collection_version(user, task_id, out)
        self.store.update_collection_state(task_id, user=user, collection_version=version, paper_count=len(papers))
        return out

    def list_versions(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_collection_versions
            where task_id = ? and user_id = ?
            order by created_at desc
            """,
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "versions": [self._version_row_to_dict(row) for row in rows]}

    def get_version(self, task_id: str, collection_version: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            """
            select * from structured_extraction_collection_versions
            where task_id = ? and user_id = ? and collection_version = ?
            """,
            (task_id, user.user_id, collection_version),
        ).fetchone()
        if not row:
            raise KeyError(f"collection version not found: {collection_version}")
        return self._version_row_to_dict(row, include_papers=True)

    def _search_index(self, payload: CollectionSearchRequest, *, limit: int | None) -> list[tuple[sqlite3.Row, list[str], float]]:
        index_path = Path(literature_search_shared.service.paths.index_db)
        if not index_path.exists():
            raise ValueError(f"research index not found: {index_path}")
        params: list[Any] = []
        where: list[str] = []
        if payload.year_from is not None:
            where.append("year >= ?")
            params.append(int(payload.year_from))
        if payload.year_to is not None:
            where.append("year <= ?")
            params.append(int(payload.year_to))
        if payload.journal:
            where.append("lower(coalesce(journal, '')) like ?")
            params.append(f"%{payload.journal.strip().lower()}%")
        if payload.site:
            where.append("lower(coalesce(site, '')) like ?")
            params.append(f"%{payload.site.strip().lower()}%")
        query = (payload.query or "").strip()
        terms = _query_terms(query)
        if terms:
            term_clauses = []
            for term in terms:
                needle = f"%{term}%"
                term_clauses.append(
                    "(lower(coalesce(paper_id, '')) like ? or lower(coalesce(doi, '')) like ? or lower(coalesce(title, '')) like ? "
                    "or lower(coalesce(authors_json, '')) like ? or lower(coalesce(journal, '')) like ? "
                    "or lower(coalesce(site, '')) like ? or lower(coalesce(metadata_json, '')) like ?)"
                )
                params.extend([needle, needle, needle, needle, needle, needle, needle])
            where.append("(" + " or ".join(term_clauses) + ")")
        sql = "select * from papers"
        if where:
            sql += " where " + " and ".join(where)
        if limit is not None:
            sql += " limit ?"
            params.append(max(limit * 5, limit))
        with sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, timeout=3) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        scored: list[tuple[sqlite3.Row, list[str], float]] = []
        for row in rows:
            matched = _matched_fields(row, terms, query)
            score = _metadata_score(row, matched, terms, query, payload)
            if terms and score <= 0:
                continue
            scored.append((row, matched, score))
        scored.sort(key=lambda item: (-item[2], -(_coerce_year(item[0]["year"]) or 0), (item[0]["title"] or "").lower(), item[0]["paper_id"]))
        return scored if limit is None else scored[:limit]

    def _upsert_candidate(
        self,
        *,
        task_id: str,
        user: UserContext,
        row: sqlite3.Row,
        ref: dict[str, Any],
        payload: CollectionSearchRequest,
        query_hash: str,
        matched_fields: list[str],
        metadata_score: float,
        ts: float,
    ) -> tuple[str, bool]:
        paper_id = row["paper_id"]
        existing = self.store.conn.execute(
            """
            select candidate_id from structured_extraction_candidates
            where task_id = ? and paper_id = ? and candidate_source = ? and source_query_hash = ?
            """,
            (task_id, paper_id, payload.source, query_hash),
        ).fetchone()
        source_path = row["md_path"] or row["abstract_path"] or row["article_dir"] or ""
        if existing:
            candidate_id = existing["candidate_id"]
            self.store.conn.execute(
                """
                update structured_extraction_candidates
                set title = ?, authors_json = ?, year = ?, journal = ?, doi = ?, source_path = ?,
                    index_version = ?, matched_fields_json = ?, metadata_score = ?, paper_ref_json = ?, updated_at = ?
                where candidate_id = ?
                """,
                (
                    row["title"],
                    row["authors_json"] or "[]",
                    _coerce_year(row["year"]),
                    row["journal"],
                    row["doi"],
                    source_path,
                    row["index_version"],
                    dumps(matched_fields),
                    metadata_score,
                    dumps(ref),
                    ts,
                    candidate_id,
                ),
            )
            self.store.conn.commit()
            return candidate_id, False
        candidate_id = f"cand_{uuid.uuid4().hex[:12]}"
        self.store.conn.execute(
            """
            insert into structured_extraction_candidates(
                candidate_id, task_id, user_id, paper_id, title, authors_json, year, journal, doi, source_path,
                index_version, candidate_source, source_query, source_query_hash, matched_fields_json,
                metadata_score, user_decision, paper_ref_json, created_at, updated_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?)
            """,
            (
                candidate_id,
                task_id,
                user.user_id,
                paper_id,
                row["title"],
                row["authors_json"] or "[]",
                _coerce_year(row["year"]),
                row["journal"],
                row["doi"],
                source_path,
                row["index_version"],
                payload.source,
                payload.query or "",
                query_hash,
                dumps(matched_fields),
                metadata_score,
                dumps(ref),
                ts,
                ts,
            ),
        )
        self._insert_candidate_event(
            candidate_id,
            task_id,
            user.user_id,
            "candidate_created",
            {"paper_id": paper_id, "candidate_source": payload.source, "source_query": payload.query or ""},
            ts=ts,
        )
        self.store.conn.commit()
        return candidate_id, True

    def _detect_duplicates(self, task_id: str, *, user: UserContext) -> None:
        rows = self.store.conn.execute(
            "select candidate_id, paper_id, doi, title from structured_extraction_candidates where task_id = ? and user_id = ?",
            (task_id, user.user_id),
        ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            doi = (row["doi"] or "").strip().lower()
            title = _normalize_title(row["title"] or "")
            if doi:
                key = f"doi:{doi}"
            elif title:
                key = f"title:{title}"
            else:
                continue
            groups.setdefault(key, []).append(row)
        self.store.conn.execute(
            """
            update structured_extraction_candidates
            set duplicate_group_id = null, canonical_paper_id = null, duplicate_reason = null
            where task_id = ? and user_id = ?
            """,
            (task_id, user.user_id),
        )
        for key, group in groups.items():
            if len(group) < 2:
                continue
            canonical = sorted(group, key=lambda row: row["paper_id"])[0]["paper_id"]
            group_id = f"dup_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"
            reason = "same_doi" if key.startswith("doi:") else "same_normalized_title"
            for row in group:
                self.store.conn.execute(
                    """
                    update structured_extraction_candidates
                    set duplicate_group_id = ?, canonical_paper_id = ?, duplicate_reason = ?
                    where candidate_id = ?
                    """,
                    (group_id, canonical, reason, row["candidate_id"]),
                )
        self.store.conn.commit()

    def _candidate_row(self, task_id: str, candidate_id: str, *, user: UserContext) -> sqlite3.Row:
        row = self.store.conn.execute(
            """
            select * from structured_extraction_candidates
            where candidate_id = ? and task_id = ? and user_id = ?
            """,
            (_clean_candidate_id(candidate_id), task_id, user.user_id),
        ).fetchone()
        if not row:
            raise KeyError(f"candidate not found: {candidate_id}")
        return row

    def _next_collection_version(self, task_id: str) -> str:
        rows = self.store.conn.execute(
            "select collection_version from structured_extraction_collection_versions where task_id = ?",
            (task_id,),
        ).fetchall()
        max_n = 0
        for row in rows:
            match = re.match(r"^col_v(\d+)$", row["collection_version"] or "")
            if match:
                max_n = max(max_n, int(match.group(1)))
        return f"col_v{max_n + 1}"

    def _version_row_to_dict(self, row: sqlite3.Row, *, include_papers: bool = False) -> dict[str, Any]:
        out = {
            "collection_version": row["collection_version"],
            "task_id": row["task_id"],
            "paper_count": row["paper_count"],
            "summary": loads(row["summary_json"], {}) or {},
            "created_at": row["created_at"],
        }
        if include_papers:
            paper_rows = self.store.conn.execute(
                """
                select * from structured_extraction_collection_papers
                where task_id = ? and collection_version = ?
                order by created_at asc, candidate_id asc
                """,
                (row["task_id"], row["collection_version"]),
            ).fetchall()
            out["included_papers"] = [loads(paper["paper_ref_json"], {}) or {} for paper in paper_rows]
        return out

    def _insert_candidate_event(
        self,
        candidate_id: str,
        task_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        ts: float | None = None,
    ) -> None:
        self.store.conn.execute(
            """
            insert into structured_extraction_candidate_events(candidate_id, task_id, user_id, event_type, payload_json, created_at)
            values(?, ?, ?, ?, ?, ?)
            """,
            (candidate_id, task_id, user_id, event_type, dumps(payload), ts or now()),
        )

    def _rewrite_candidates_artifact(self, task_id: str, *, user: UserContext) -> None:
        candidates = self.list_candidates(task_id, user=user, limit=MAX_SEARCH_LIMIT)["candidates"]
        write_collection_candidates(user, task_id, candidates)

    @staticmethod
    def _row_to_candidate(row: sqlite3.Row) -> dict[str, Any]:
        paper_ref_snapshot = loads(row["paper_ref_json"], {}) or {}
        authors = loads(row["authors_json"], []) or []
        return {
            "candidate_id": row["candidate_id"],
            "task_id": row["task_id"],
            "paper_id": row["paper_id"],
            "title": row["title"] or "",
            "authors": authors,
            "year": _coerce_year(row["year"]),
            "journal": row["journal"] or "",
            "doi": row["doi"] or "",
            "source_path": row["source_path"] or "",
            "index_version": row["index_version"],
            "candidate_source": row["candidate_source"],
            "source_query": row["source_query"],
            "matched_fields": loads(row["matched_fields_json"], []) or [],
            "metadata_score": row["metadata_score"],
            "llm_decision": row["llm_decision"],
            "llm_relevance_score": row["llm_relevance_score"],
            "llm_reason": row["llm_reason"],
            "user_decision": row["user_decision"],
            "exclude_reason": row["exclude_reason"],
            "duplicate_group_id": row["duplicate_group_id"],
            "canonical_paper_id": row["canonical_paper_id"],
            "duplicate_reason": row["duplicate_reason"],
            "paper_ref": paper_ref_snapshot,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def _bounded_limit(raw: int | None, *, default: int = 50) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    if value <= 0:
        return None
    return max(1, min(value, MAX_SEARCH_LIMIT))


def _coerce_year(value: Any) -> int | None:
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if year > 0 else None


def _query_terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[\w.-]+", query or "") if term.strip()]


def _source_query_hash(payload: CollectionSearchRequest) -> str:
    normalized = {
        "query": (payload.query or "").strip().lower(),
        "year_from": payload.year_from,
        "year_to": payload.year_to,
        "journal": (payload.journal or "").strip().lower(),
        "site": (payload.site or "").strip().lower(),
        "source": payload.source or "metadata_search",
    }
    return hashlib.sha1(json.dumps(normalized, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _matched_fields(row: sqlite3.Row, terms: list[str], query: str) -> list[str]:
    fields = {
        "paper_id": row["paper_id"] or "",
        "doi": row["doi"] or "",
        "title": row["title"] or "",
        "authors": row["authors_json"] or "",
        "journal": row["journal"] or "",
        "site": row["site"] or "",
        "metadata": row["metadata_json"] or "",
    }
    matched: list[str] = []
    needles = terms or ([query.lower()] if query else [])
    for label, value in fields.items():
        text = value.lower()
        if needles and any(term in text for term in needles):
            matched.append("abstract" if label == "metadata" and "abstract" in text else label)
    return matched


def _metadata_score(row: sqlite3.Row, matched: list[str], terms: list[str], query: str, payload: CollectionSearchRequest) -> float:
    if not terms and not any([payload.year_from, payload.year_to, payload.journal, payload.site]):
        return 0.1
    score = 0.0
    exact = (query or "").strip().lower()
    if exact and exact in {(row["paper_id"] or "").lower(), (row["doi"] or "").lower()}:
        score += 1.0
    if "title" in matched:
        score += 0.35
    if "abstract" in matched or "metadata" in matched:
        score += 0.25
    if "journal" in matched or "site" in matched:
        score += 0.08
    if "authors" in matched:
        score += 0.06
    if "doi" in matched or "paper_id" in matched:
        score += 0.12
    if payload.year_from is not None or payload.year_to is not None:
        score += 0.03
    if payload.journal:
        score += 0.03
    if payload.site:
        score += 0.03
    return round(min(score, 1.0), 4)


def _validated_decision(decision: str, exclude_reason: str | None) -> tuple[str, str | None]:
    if decision not in DECISIONS:
        raise ValueError(f"invalid decision: {decision}")
    if decision == "exclude":
        return decision, exclude_reason or "other"
    return decision, None


def _clean_candidate_id(candidate_id: str) -> str:
    value = (candidate_id or "").strip()
    if not value or "/" in value or "\\" in value or ".." in value:
        raise ValueError("invalid candidate_id")
    return value


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
