"""Block 0: canonical corpus identity + Research Index Health.

This module is the platform's *consumer* of the identity layer the underlying
research index already maintains. It never mints a new paper id — the canonical
identity is ``research_index.sqlite.papers.paper_id`` — it only:

- resolves ``doi`` / ``article_id`` / ``source_path`` back to that ``paper_id``
  and assembles a stable :func:`paper_ref` snapshot,
- reports whether a paper's markdown / abstract / figure / table assets actually
  exist on disk (so missing files surface instead of failing silently),
- composes a Research Index Health dashboard (coverage, vector status, recent
  maintenance jobs, and the role-gated maintenance actions) for the home page.

All reads against ``research_index.sqlite`` are read-only.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
import time
from pathlib import Path
from typing import Any

from modules.literature_search.service import LiteratureResearchService


# Canonical PaperRef field order — the platform-wide identity contract (Block 0).
PAPER_REF_FIELDS = (
    "paper_id",
    "article_id",
    "doi",
    "title",
    "authors",
    "journal",
    "year",
    "site",
    "article_dir",
    "md_path",
    "abstract_path",
    "indexed_at",
    "mtime",
    "index_version",
)


class PaperNotFound(KeyError):
    """Raised when a lookup cannot be resolved to a canonical paper_id."""


@dataclass
class CorpusService:
    """Read-only identity + health facade over the underlying research index."""

    service: LiteratureResearchService
    index_db_path: Path | None = None
    data_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.index_db_path is None:
            self.index_db_path = Path(self.service.paths.index_db)
        if self.data_dir is None:
            self.data_dir = Path(self.service.data_dir)
        self.index_db_path = Path(self.index_db_path)
        self.data_dir = Path(self.data_dir)

    # --- low level ------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if not self.index_db_path.exists():
            raise FileNotFoundError(f"research index not found: {self.index_db_path}")
        uri = f"file:{self.index_db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        return conn

    # --- identity resolution --------------------------------------------------

    def resolve(
        self,
        *,
        doi: str | None = None,
        paper_id: str | None = None,
        article_id: int | None = None,
        source_path: str | None = None,
    ) -> dict[str, Any]:
        """Resolve any known handle to a canonical :func:`paper_ref` snapshot.

        Precedence: explicit ``paper_id`` → ``article_id`` → ``doi`` →
        ``source_path``. Returns the PaperRef with an extra ``matched_on`` key
        describing how the canonical id was found.
        """
        with self._connect() as conn:
            row, matched_on = self._resolve_row(
                conn, doi=doi, paper_id=paper_id, article_id=article_id, source_path=source_path
            )
            if row is None:
                handle = paper_id or article_id or doi or source_path
                raise PaperNotFound(f"no canonical paper for: {handle!r}")
            ref = paper_ref(row)
            ref["matched_on"] = matched_on
            return ref

    def _resolve_row(
        self,
        conn: sqlite3.Connection,
        *,
        doi: str | None,
        paper_id: str | None,
        article_id: int | None,
        source_path: str | None,
    ) -> tuple[sqlite3.Row | None, str | None]:
        if paper_id:
            row = conn.execute("select * from papers where paper_id = ? limit 1", (paper_id,)).fetchone()
            if row:
                return row, "paper_id"
        if article_id is not None:
            row = conn.execute("select * from papers where article_id = ? limit 1", (article_id,)).fetchone()
            if row:
                return row, "article_id"
        if doi:
            row = conn.execute(
                "select * from papers where lower(doi) = lower(?) limit 1", (doi.strip(),)
            ).fetchone()
            if row:
                return row, "doi"
        if source_path:
            resolved_pid, matched_on = self._paper_id_for_source_path(conn, source_path)
            if resolved_pid:
                row = conn.execute("select * from papers where paper_id = ? limit 1", (resolved_pid,)).fetchone()
                if row:
                    return row, matched_on
        return None, None

    def _paper_id_for_source_path(
        self, conn: sqlite3.Connection, source_path: str
    ) -> tuple[str | None, str | None]:
        """Find the canonical paper_id owning a markdown/section/chunk/asset path.

        Index paths are stored relative to ``data_dir`` (e.g.
        ``articles/.../parsed/fulltext.md``); an absolute path under the data dir
        is normalized to that relative form before matching.
        """
        candidates = self._path_candidates(source_path)
        placeholders = ",".join("?" for _ in candidates)
        # 1) direct paper-level paths
        row = conn.execute(
            f"select paper_id from papers where md_path in ({placeholders}) or abstract_path in ({placeholders}) limit 1",
            (*candidates, *candidates),
        ).fetchone()
        if row:
            return row["paper_id"], "md_path"
        # 2) section / chunk / asset evidence paths
        for table, label in (("paper_sections", "section_path"), ("paper_chunks", "chunk_path"), ("paper_assets", "asset_path")):
            row = conn.execute(
                f"select paper_id from {table} where source_path in ({placeholders}) limit 1",
                tuple(candidates),
            ).fetchone()
            if row:
                return row["paper_id"], label
        # 3) fall back to the article directory prefix
        for cand in candidates:
            row = conn.execute(
                "select paper_id from papers where ? like article_dir || '%' limit 1", (cand,)
            ).fetchone()
            if row:
                return row["paper_id"], "article_dir"
        return None, None

    def _path_candidates(self, source_path: str) -> list[str]:
        raw = source_path.strip()
        candidates = {raw}
        path = Path(raw)
        if path.is_absolute():
            try:
                candidates.add(str(path.resolve().relative_to(self.data_dir.resolve())))
            except (ValueError, OSError):
                pass
        else:
            candidates.add(str((self.data_dir / raw)))
        return [c for c in candidates if c]

    # --- on-disk integrity ----------------------------------------------------

    def check_paths(
        self,
        *,
        doi: str | None = None,
        paper_id: str | None = None,
        article_id: int | None = None,
    ) -> dict[str, Any]:
        """Report whether a paper's markdown/abstract/asset files exist on disk."""
        with self._connect() as conn:
            row, _ = self._resolve_row(
                conn, doi=doi, paper_id=paper_id, article_id=article_id, source_path=None
            )
            if row is None:
                raise PaperNotFound(f"no canonical paper for: {paper_id or article_id or doi!r}")
            pid = row["paper_id"]
            asset_rows = conn.execute(
                "select kind, source_path, label from paper_assets where paper_id = ? order by kind, source_path",
                (pid,),
            ).fetchall()

        files: list[dict[str, Any]] = []
        for role, rel in (("markdown", row["md_path"]), ("abstract", row["abstract_path"])):
            if rel:
                files.append(self._path_report(role, rel))
        for asset in asset_rows:
            files.append(self._path_report(asset["kind"], asset["source_path"], label=asset["label"]))

        missing = [f for f in files if not f["exists"]]
        return {
            "paper_id": pid,
            "article_id": row["article_id"],
            "doi": row["doi"],
            "index_version": row["index_version"],
            "files": files,
            "missing": missing,
            "missing_count": len(missing),
            "ok": not missing,
        }

    def _path_report(self, role: str, rel: str, *, label: str | None = None) -> dict[str, Any]:
        absolute = (self.data_dir / rel) if not Path(rel).is_absolute() else Path(rel)
        return {
            "role": role,
            "label": label,
            "source_path": rel,
            "abs_path": str(absolute),
            "exists": absolute.exists(),
        }

    # --- coverage + health ----------------------------------------------------

    def coverage_counts(self) -> dict[str, Any]:
        with self._connect() as conn:
            def scalar(sql: str) -> int:
                return int(conn.execute(sql).fetchone()[0])

            papers = scalar("select count(*) from papers")
            sections = scalar("select count(*) from paper_sections")
            chunks = scalar("select count(*) from paper_chunks")
            vector_records = scalar("select count(*) from vector_records")
            asset_kinds = {
                row["kind"]: int(row["n"])
                for row in conn.execute("select kind, count(*) as n from paper_assets group by kind").fetchall()
            }
            index_versions = {
                str(row["index_version"]): int(row["n"])
                for row in conn.execute(
                    "select index_version, count(*) as n from papers group by index_version order by index_version"
                ).fetchall()
            }
        return {
            "papers": papers,
            "sections": sections,
            "chunks": chunks,
            "assets": {
                "figure": asset_kinds.get("figure", 0),
                "table": asset_kinds.get("table", 0),
                "total": sum(asset_kinds.values()),
                "by_kind": asset_kinds,
            },
            "vector_records": vector_records,
            "index_versions": index_versions,
        }

    def quick_stats(self, *, limit: int = 8) -> dict[str, Any]:
        """Fast corpus metadata for chat-time library status answers."""
        base = {
            "index_available": self.index_db_path.exists(),
            "paper_count": 0,
            "article_index_count": 0,
            "section_count": 0,
            "chunk_count": 0,
            "year_range": [None, None],
            "top_years": [],
            "top_journals": [],
            "recent_imports": [],
            "vector_built": False,
            "generated_at": time.time(),
        }
        if not self.index_db_path.exists():
            return base

        def _has_table(conn: sqlite3.Connection, name: str) -> bool:
            row = conn.execute("select name from sqlite_master where type='table' and name=?", (name,)).fetchone()
            return row is not None

        def _count(conn: sqlite3.Connection, table: str) -> int:
            if not _has_table(conn, table):
                return 0
            return int(conn.execute(f"select count(*) from {table}").fetchone()[0])

        with self._connect() as conn:
            base["paper_count"] = _count(conn, "papers")
            base["article_index_count"] = _count(conn, "article_index")
            base["section_count"] = _count(conn, "paper_sections")
            base["chunk_count"] = _count(conn, "paper_chunks")
            base["vector_built"] = _count(conn, "vector_records") > 0

            years = [
                int(row["year_int"])
                for row in conn.execute(
                    """
                    select cast(year as integer) as year_int
                    from papers
                    where year is not null and trim(year) != ''
                      and cast(year as integer) between 1800 and 2200
                    """
                ).fetchall()
            ]
            if years:
                base["year_range"] = [min(years), max(years)]
            base["top_years"] = [
                {"year": int(row["year_int"]), "count": int(row["n"])}
                for row in conn.execute(
                    """
                    select cast(year as integer) as year_int, count(*) as n
                    from papers
                    where year is not null and trim(year) != ''
                      and cast(year as integer) between 1800 and 2200
                    group by cast(year as integer)
                    order by n desc, year_int desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            base["top_journals"] = [
                {"journal": row["journal"], "count": int(row["n"])}
                for row in conn.execute(
                    """
                    select trim(journal) as journal, count(*) as n
                    from papers
                    where journal is not null and trim(journal) != ''
                    group by trim(journal)
                    order by n desc, lower(trim(journal)) asc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            base["recent_imports"] = [
                {
                    "paper_id": row["paper_id"],
                    "doi": row["doi"],
                    "title": row["title"],
                    "year": row["year"],
                    "journal": row["journal"],
                    "indexed_at": row["indexed_at"],
                }
                for row in conn.execute(
                    """
                    select paper_id, doi, title, year, journal, indexed_at, mtime
                    from papers
                    order by coalesce(indexed_at, '') desc, coalesce(mtime, 0) desc
                    limit ?
                    """,
                    (limit,),
                ).fetchall()
            ]
        return base

    def integrity_sample(self, *, limit: int = 8) -> dict[str, Any]:
        """Spot-check a few papers' markdown files so broken paths surface early."""
        with self._connect() as conn:
            rows = conn.execute(
                "select paper_id, md_path from papers where md_path is not null and md_path != '' "
                "order by mtime desc limit ?",
                (limit,),
            ).fetchall()
        checked = 0
        broken: list[dict[str, Any]] = []
        for row in rows:
            checked += 1
            report = self._path_report("markdown", row["md_path"])
            if not report["exists"]:
                broken.append({"paper_id": row["paper_id"], **report})
        return {
            "sampled": checked,
            "broken": broken,
            "broken_count": len(broken),
            "status": "warning" if broken else "ok",
        }

    def dashboard(self, *, role: str = "admin", recent_jobs: list[dict] | None = None) -> dict[str, Any]:
        """Compose the Research Index Health home payload.

        Built only from *fast* signals (index counts, vector status, coverage,
        an on-disk integrity sample) so the home page loads quickly. The deep
        catalog/stale comparison is expensive (full ``index_health``) and is
        instead surfaced from the latest ``health_check`` maintenance job result.
        """
        recent_jobs = recent_jobs or []
        index_available = self.index_db_path.exists()
        running_maintenance = _running_job(recent_jobs, MAINTENANCE_ACTIONS)
        if not index_available:
            return {
                "index_available": False,
                "index_db_path": str(self.index_db_path),
                "overall_status": "failed",
                "role": role,
                "capabilities": _capabilities(role),
                "recent_jobs": recent_jobs,
                "warnings": ["index_db_missing"],
                "failures": ["index_db_missing"],
                "recommended_actions": [
                    {"label": "Build the research index", "command": "python -m research.cli index build"}
                ],
            }
        if running_maintenance:
            return {
                "index_available": True,
                "index_db_path": str(self.index_db_path),
                "data_dir": str(self.data_dir),
                "overall_status": "updating",
                "role": role,
                "capabilities": _capabilities(role),
                "coverage": {},
                "summary": {},
                "vector": {"status": "unknown", "reason": "maintenance_running"},
                "integrity": {"status": "unknown"},
                "warnings": [f"{running_maintenance.get('job_type')}_running"],
                "failures": [],
                "recommended_actions": [],
                "last_health_check": _latest_job(recent_jobs, "health_check"),
                "running_maintenance": running_maintenance,
                "recent_jobs": recent_jobs,
            }

        index_status = _safe(self.service.index_status, default={})
        vector_status = _safe(self.service.vector_status, default={})
        counts = _safe(self.coverage_counts, default={})
        integrity = _safe(lambda: self.integrity_sample(limit=8), default={"status": "ok", "broken_count": 0})

        papers = counts.get("papers") or index_status.get("papers") or 0
        vector_built = bool(vector_status.get("vector_index_exists"))
        index_warnings = int(index_status.get("warnings") or 0)
        index_errors = [e for e in (index_status.get("errors") or []) if e.get("severity") == "error"]

        warnings: list[str] = []
        failures: list[str] = []
        actions: list[dict] = []
        if not papers:
            failures.append("indexed_papers_empty")
            actions.append({"label": "Build the research index", "command": "python -m research.cli index build"})
        if index_errors:
            failures.append("index_errors_present")
        if not vector_built:
            warnings.append("vector_not_built")
            actions.append({"label": "Build the vector index", "command": "python -m research.cli vector build"})
        elif vector_status.get("missing_vectors") or vector_status.get("stale_vectors"):
            warnings.append("vector_incomplete")
            actions.append({"label": "Rebuild the vector index", "command": "python -m research.cli vector build"})
        if integrity.get("broken_count"):
            warnings.append("broken_source_paths")
        if index_warnings:
            warnings.append("index_warnings_present")

        overall = "failed" if failures else "warning" if warnings else "healthy"
        return {
            "index_available": True,
            "index_db_path": str(self.index_db_path),
            "data_dir": str(self.data_dir),
            "overall_status": overall,
            "role": role,
            "capabilities": _capabilities(role),
            "coverage": counts,
            "summary": {
                "papers": papers,
                "documents": index_status.get("documents"),
                "sections": counts.get("sections") or index_status.get("sections"),
                "chunks": counts.get("chunks") or index_status.get("chunks"),
                "index_warnings": index_warnings,
                "index_errors": len(index_errors),
            },
            "vector": {
                "built": vector_built,
                "target_documents": vector_status.get("target_documents"),
                "indexed_vectors": vector_status.get("indexed_vectors"),
                "missing_vectors": vector_status.get("missing_vectors"),
                "stale_vectors": vector_status.get("stale_vectors"),
                "embedding_model": vector_status.get("embedding_model"),
                "status": "ok" if vector_built else "warning",
                "reason": None if vector_built else "vector_index_not_built",
            },
            "integrity": integrity,
            "warnings": warnings,
            "failures": failures,
            "recommended_actions": actions,
            "last_health_check": _latest_job(recent_jobs, "health_check"),
            "recent_jobs": recent_jobs,
        }


def paper_ref(row: sqlite3.Row | dict) -> dict[str, Any]:
    """Build a canonical PaperRef snapshot from a ``papers`` row."""
    get = row.__getitem__ if isinstance(row, sqlite3.Row) else row.get
    import json

    def field(key, default=None):
        try:
            return get(key)
        except (KeyError, IndexError):
            return default

    authors_raw = field("authors_json") or "[]"
    metadata_raw = field("metadata_json") or "{}"
    try:
        authors = json.loads(authors_raw)
    except (TypeError, ValueError):
        authors = []
    try:
        metadata = json.loads(metadata_raw)
    except (TypeError, ValueError):
        metadata = {}
    return {
        "paper_id": field("paper_id"),
        "article_id": field("article_id"),
        "doi": field("doi"),
        "title": field("title"),
        "authors": authors,
        "journal": field("journal"),
        "year": field("year"),
        "site": field("site"),
        "article_dir": field("article_dir"),
        "md_path": field("md_path"),
        "abstract_path": field("abstract_path"),
        "indexed_at": field("indexed_at"),
        "mtime": field("mtime"),
        "index_version": field("index_version"),
        "metadata": metadata,
        "source": "research_index",
    }


# Maintenance actions, gated by role. The viewer role is read-only; admin may
# trigger the (reserved) state-changing maintenance jobs.
MAINTENANCE_ACTIONS = ("health_check", "index_refresh", "vector_build")


def enrich_record_identity(record: dict[str, Any], corpus: "CorpusService") -> dict[str, Any]:
    """Backfill canonical paper_id / index_version onto a session record's evidence.

    Persisted evidence already carries ``paper_id`` for hybrid/fts search, but
    ``index_version`` is not stamped per evidence by the underlying search. The
    report's source audit must show ``paper_id + doi + index_version``, so we
    resolve any gaps from the canonical index at export time. Degrades silently.
    """
    cache: dict[str, dict | None] = {}

    def lookup(paper_id, doi, article_id):
        key = paper_id or doi or (str(article_id) if article_id is not None else None)
        if not key:
            return None
        if key not in cache:
            try:
                cache[key] = corpus.resolve(paper_id=paper_id, doi=doi, article_id=article_id)
            except Exception:  # noqa: BLE001
                cache[key] = None
        return cache[key]

    for turn in record.get("turns") or []:
        for item in turn.get("evidence") or []:
            if item.get("paper_id") and item.get("index_version") is not None:
                continue
            ref = lookup(item.get("paper_id"), item.get("doi"), item.get("article_id"))
            if not ref:
                continue
            item.setdefault("paper_id", ref.get("paper_id"))
            if not item.get("paper_id"):
                item["paper_id"] = ref.get("paper_id")
            if item.get("index_version") is None:
                item["index_version"] = ref.get("index_version")
    return record


def _capabilities(role: str) -> dict[str, Any]:
    is_admin = role == "admin"
    return {
        "role": role,
        "can_view": True,
        "can_maintain": is_admin,
        "maintenance_actions": list(MAINTENANCE_ACTIONS) if is_admin else [],
    }


def _latest_job(jobs: list[dict], job_type: str) -> dict | None:
    for job in jobs:  # recent_jobs arrive newest-first
        if job.get("job_type") == job_type:
            return {
                "job_id": job.get("job_id"),
                "status": job.get("status"),
                "completed_at": job.get("completed_at"),
                "result_status": (job.get("result") or {}).get("status") if isinstance(job.get("result"), dict) else None,
            }
    return None


def _running_job(jobs: list[dict], job_types: tuple[str, ...]) -> dict | None:
    for job in jobs:
        if job.get("job_type") in job_types and job.get("status") in {"queued", "running"}:
            return job
    return None


def _safe(func, *, default):
    try:
        return func()
    except Exception:  # noqa: BLE001 - dashboard must degrade, never crash the home page
        return default
