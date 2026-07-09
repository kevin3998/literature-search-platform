from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from core.user_context import UserContext
from core.worker.queue import JobQueue
from modules.literature_search import literature_search_shared

from .artifacts import write_evidence_packet_version
from .prompt_contract import StructuredExtractionPromptContractService
from .schemas import EvidencePacketBuildRequest
from .store import StructuredExtractionStore, dumps, loads, new_uuid, now

ACTIVE_BUILD_STATUSES = {"queued", "running", "cancelling"}
TERMINAL_BUILD_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


class _BuildCancelled(Exception):
    pass


class StructuredExtractionEvidencePacketService:
    def __init__(self, store: StructuredExtractionStore, prompt_contracts: StructuredExtractionPromptContractService) -> None:
        self.store = store
        self.prompt_contracts = prompt_contracts
        self.job_queue = JobQueue(self.store.engine)

    def build(self, task_id: str, payload: EvidencePacketBuildRequest, *, user: UserContext) -> dict[str, Any]:
        ctx = self._build_context(task_id, payload, user=user)
        packet_version = self._next_version(task_id)
        items = []
        warnings = []
        for item, item_warnings in self._iter_packet_items(ctx, packet_version):
            items.append(item)
            warnings.extend(item_warnings)
        return self._finalize_packet_version(task_id, packet_version, ctx, items, warnings, user=user)

    def start_build_job(self, task_id: str, payload: EvidencePacketBuildRequest, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        active = self._active_build_job(task_id, user.user_id)
        if active:
            return self._row_to_build_job(active)
        ctx = self._build_context(task_id, payload, user=user)
        build_job_id = new_uuid()
        target_packet_version = self._next_version(task_id)
        ts = now()
        self.store.conn.execute(
            """
            insert into structured_extraction_evidence_packet_build_jobs(
                build_job_id, task_id, user_id, status, phase, collection_version, schema_version,
                prompt_contract_version, target_packet_version, paper_count, field_group_count,
                total_item_count, settings_json, created_at, updated_at
            ) values(?, ?, ?, 'queued', 'resolving_inputs', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                build_job_id,
                task_id,
                user.user_id,
                ctx["collection_version"],
                ctx["schema_version"],
                ctx["prompt_contract_version"],
                target_packet_version,
                len(ctx["papers"]),
                len(ctx["groups"]),
                len(ctx["papers"]) * len(ctx["groups"]),
                dumps(ctx["settings"]),
                ts,
                ts,
            ),
        )
        self.store.conn.commit()
        core_job = self.job_queue.enqueue(
            "structured.evidence_packet_build",
            {"task_id": task_id, "build_job_id": build_job_id, "user_id": user.user_id},
            user_id=user.user_id,
            queue="structured-extraction",
        )
        self.store.conn.execute(
            "update structured_extraction_evidence_packet_build_jobs set core_job_id = ? where build_job_id = ?",
            (core_job["job_id"], build_job_id),
        )
        self.store.conn.commit()
        return self.get_build_job(task_id, build_job_id, user=user)

    def list_build_jobs(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_evidence_packet_build_jobs
            where task_id = ? and user_id = ?
            order by created_at desc
            """,
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "jobs": [self._row_to_build_job(row) for row in rows]}

    def get_build_job(self, task_id: str, build_job_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            """
            select * from structured_extraction_evidence_packet_build_jobs
            where task_id = ? and user_id = ? and build_job_id = ?
            """,
            (task_id, user.user_id, build_job_id),
        ).fetchone()
        if not row:
            raise KeyError(f"evidence packet build job not found: {build_job_id}")
        return self._row_to_build_job(row)

    def cancel_build_job(self, task_id: str, build_job_id: str, *, user: UserContext) -> dict[str, Any]:
        job = self.get_build_job(task_id, build_job_id, user=user)
        if job["status"] in TERMINAL_BUILD_STATUSES:
            return job
        if job["status"] == "queued":
            self._finish_cancelled(build_job_id)
            if job.get("core_job_id"):
                self.job_queue.cancel(job["core_job_id"])
            return self.get_build_job(task_id, build_job_id, user=user)
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_evidence_packet_build_jobs
            set status = 'cancelling', phase = 'building_items', updated_at = ?
            where task_id = ? and user_id = ? and build_job_id = ?
            """,
            (ts, task_id, user.user_id, build_job_id),
        )
        self.store.conn.commit()
        if job.get("core_job_id"):
            self.job_queue.cancel(job["core_job_id"])
        return self.get_build_job(task_id, build_job_id, user=user)

    def reap_orphaned_build_jobs(self) -> list[str]:
        ts = now()
        rows = self.store.conn.execute(
            """
            select build_job_id from structured_extraction_evidence_packet_build_jobs
            where status in ('queued', 'running', 'cancelling')
            """
        ).fetchall()
        ids = [row["build_job_id"] for row in rows]
        for build_job_id in ids:
            self.store.conn.execute(
                """
                update structured_extraction_evidence_packet_build_jobs
                set status = 'interrupted', phase = 'interrupted',
                    error_json = ?, updated_at = ?, completed_at = ?
                where build_job_id = ?
                """,
                (dumps({"reason": "process_restarted"}), ts, ts, build_job_id),
            )
        self.store.conn.commit()
        return ids

    def _build_context(self, task_id: str, payload: EvidencePacketBuildRequest, *, user: UserContext) -> dict[str, Any]:
        task = self.store.get_task(task_id, user_id=user.user_id)
        collection_version = payload.collection_version or task.get("current_collection_version")
        schema_version = payload.schema_version or task.get("current_schema_version")
        if not collection_version:
            raise ValueError("collection_version_required")
        if not schema_version:
            raise ValueError("schema_version_required")
        prompt_contract_version = payload.prompt_contract_version
        if prompt_contract_version:
            contract = self.prompt_contracts.get_version(task_id, prompt_contract_version, user=user)
            if contract.get("collection_version") != collection_version or contract.get("schema_version") != schema_version:
                raise ValueError("prompt_contract_incompatible")
        else:
            contract = self.prompt_contracts.latest_compatible(
                task_id,
                user=user,
                collection_version=collection_version,
                schema_version=schema_version,
            )
            if not contract:
                raise ValueError("prompt_contract_required")
            prompt_contract_version = contract["prompt_contract_version"]
        papers = self._collection_papers(task_id, collection_version, user=user)
        schema = self._schema_version(task_id, schema_version, user=user)
        groups = schema["field_groups"] or [{"group_key": "default", "label": "Default", "description": "", "order": 1}]
        fields_by_group = _fields_by_group(schema["fields"], groups)
        settings = {
            "max_chunks_per_group": _bounded_int(payload.max_chunks_per_group, 1, 20, 6),
            "max_chars_per_chunk": _bounded_int(payload.max_chars_per_chunk, 200, 6000, 1800),
            "include_assets": bool(payload.include_assets),
        }
        return {
            "collection_version": collection_version,
            "schema_version": schema_version,
            "prompt_contract_version": prompt_contract_version,
            "papers": papers,
            "schema": schema,
            "groups": groups,
            "fields_by_group": fields_by_group,
            "settings": settings,
        }

    def _iter_packet_items(self, ctx: dict[str, Any], packet_version: str, *, should_cancel=None, before_item=None):
        ts = now()
        with _open_index() as conn:
            for paper in ctx["papers"]:
                for group in ctx["groups"]:
                    if should_cancel and should_cancel():
                        raise _BuildCancelled()
                    if before_item:
                        before_item(paper, group)
                    group_key = group["group_key"]
                    group_fields = ctx["fields_by_group"].get(group_key, [])
                    started = time.perf_counter()
                    item, item_warnings = self._build_one_item(
                        conn,
                        packet_version,
                        paper,
                        group,
                        group_fields,
                        ctx["schema"],
                        ctx["settings"],
                        ts,
                        should_cancel=should_cancel,
                    )
                    item["_build_seconds"] = round(time.perf_counter() - started, 4)
                    yield item, item_warnings

    def _build_one_item(
        self,
        conn: sqlite3.Connection,
        packet_version: str,
        paper: dict[str, Any],
        group: dict[str, Any],
        group_fields: list[dict[str, Any]],
        schema: dict[str, Any],
        settings: dict[str, Any],
        ts: float,
        should_cancel=None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if should_cancel and should_cancel():
            raise _BuildCancelled()
        paper_id = paper["paper_id"]
        article_id = paper.get("article_id")
        group_key = group["group_key"]
        query = _construction_query(group, group_fields, schema["record_schema"])
        item_warnings: list[str] = []
        chunks = _ranked_chunks(
            conn,
            paper_id,
            query,
            limit=settings["max_chunks_per_group"],
            max_chars=settings["max_chars_per_chunk"],
            article_id=article_id,
            should_cancel=should_cancel,
        )
        if chunks and chunks[0].get("query_mode") == "paper_id_fallback":
            if article_id:
                item_warnings.append("article_id_no_chunks_fallback_to_paper_id")
            else:
                item_warnings.append("article_id_missing_fallback_to_paper_id")
        if should_cancel and should_cancel():
            raise _BuildCancelled()
        if not chunks:
            fallback = _metadata_fallback(paper, query, max_chars=settings["max_chars_per_chunk"])
            if fallback:
                chunks = [fallback]
                item_warnings.append("metadata_fallback_used")
            else:
                item_warnings.append("no_chunks_found")
        assets = _assets(conn, paper_id) if settings["include_assets"] else {"tables": [], "figures": []}
        if should_cancel and should_cancel():
            raise _BuildCancelled()
        source_paths = sorted(
            {
                *(chunk.get("source_path") for chunk in chunks if chunk.get("source_path")),
                *(asset.get("source_path") for asset in assets["tables"] + assets["figures"] if asset.get("source_path")),
            }
        )
        item = {
            "packet_item_id": new_uuid(),
            "packet_version": packet_version,
            "task_id": "",
            "paper_id": paper_id,
            "field_group": group_key,
            "field_keys": [field["key"] for field in group_fields],
            "construction_query": query,
            "retrieved_sections": _sections_from_chunks(chunks),
            "chunks": chunks,
            "tables": assets["tables"],
            "figures": assets["figures"],
            "source_paths": source_paths,
            "warnings": item_warnings,
            "query_mode": chunks[0].get("query_mode") if chunks else "metadata_fallback",
            "article_id": article_id,
            "created_at": ts,
        }
        warnings = [{"paper_id": paper_id, "field_group": group_key, "warning": warning} for warning in item_warnings]
        return item, warnings

    def _finalize_packet_version(
        self,
        task_id: str,
        packet_version: str,
        ctx: dict[str, Any],
        items: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        *,
        user: UserContext,
    ) -> dict[str, Any]:
        ts = now()
        for item in items:
            item["task_id"] = task_id
            item["packet_version"] = packet_version
            item.setdefault("created_at", ts)
        summary = {
            "packet_version": packet_version,
            "task_id": task_id,
            "collection_version": ctx["collection_version"],
            "schema_version": ctx["schema_version"],
            "prompt_contract_version": ctx["prompt_contract_version"],
            "paper_count": len(ctx["papers"]),
            "field_group_count": len(ctx["groups"]),
            "item_count": len(items),
            "created_at": ts,
            "settings": ctx["settings"],
            "warnings": warnings,
        }
        self._insert_packet_version(summary, items, user=user)
        return summary

    def _insert_packet_version(self, summary: dict[str, Any], items: list[dict[str, Any]], *, user: UserContext) -> None:
        task_id = summary["task_id"]
        packet_version = summary["packet_version"]
        self.store.conn.execute(
            """
            insert into structured_extraction_evidence_packet_versions(
                task_id, packet_version, user_id, collection_version, schema_version, prompt_contract_version,
                paper_count, field_group_count, item_count, settings_json, warnings_json, created_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                packet_version,
                user.user_id,
                summary["collection_version"],
                summary["schema_version"],
                summary["prompt_contract_version"],
                summary["paper_count"],
                summary["field_group_count"],
                summary["item_count"],
                dumps(summary["settings"]),
                dumps(summary["warnings"]),
                summary["created_at"],
            ),
        )
        for item in items:
            self.store.conn.execute(
                """
                insert into structured_extraction_evidence_packet_items(
                    packet_item_id, task_id, packet_version, paper_id, field_group, field_keys_json,
                    construction_query, retrieved_sections_json, chunks_json, tables_json, figures_json,
                    source_paths_json, warnings_json, created_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["packet_item_id"],
                    task_id,
                    packet_version,
                    item["paper_id"],
                    item["field_group"],
                    dumps(item["field_keys"]),
                    item["construction_query"],
                    dumps(item["retrieved_sections"]),
                    dumps(item["chunks"]),
                    dumps(item["tables"]),
                    dumps(item["figures"]),
                    dumps(item["source_paths"]),
                    dumps(item["warnings"]),
                    item["created_at"],
                ),
            )
        self.store.conn.commit()
        write_evidence_packet_version(user, task_id, summary, items)

    def _worker_entry(self, task_id: str, build_job_id: str, user_id: str) -> None:
        user = UserContext(user_id=user_id, workspace_slug=user_id)
        try:
            row = self.store.conn.execute(
                "select * from structured_extraction_evidence_packet_build_jobs where build_job_id = ?",
                (build_job_id,),
            ).fetchone()
            if not row:
                return
            settings = loads(row["settings_json"], {}) or {}
            payload = EvidencePacketBuildRequest(
                collection_version=row["collection_version"],
                schema_version=row["schema_version"],
                prompt_contract_version=row["prompt_contract_version"],
                max_chunks_per_group=settings.get("max_chunks_per_group", 6),
                max_chars_per_chunk=settings.get("max_chars_per_chunk", 1800),
                include_assets=bool(settings.get("include_assets", True)),
            )
            ctx = self._build_context(task_id, payload, user=user)
            ts = now()
            self.store.conn.execute(
                """
                update structured_extraction_evidence_packet_build_jobs
                set status = 'running', phase = 'building_items', started_at = ?, updated_at = ?
                where build_job_id = ?
                """,
                (ts, ts, build_job_id),
            )
            self.store.conn.execute(
                "delete from structured_extraction_evidence_packet_build_items where build_job_id = ?",
                (build_job_id,),
            )
            self.store.conn.commit()

            warning_count = 0
            warnings_preview: list[dict[str, Any]] = []
            processed = 0
            total_chunk_count = 0
            slow_item_count = 0
            packet_version = row["target_packet_version"]
            def should_cancel() -> bool:
                return self._job_status(build_job_id) == "cancelling"

            def before_item(paper: dict[str, Any], group: dict[str, Any]) -> None:
                ts = now()
                self.store.conn.execute(
                    """
                    update structured_extraction_evidence_packet_build_jobs
                    set current_paper_id = ?, current_field_group = ?, updated_at = ?
                    where build_job_id = ?
                    """,
                    (paper.get("paper_id"), group.get("group_key"), ts, build_job_id),
                )
                self.store.conn.commit()

            try:
                iterator = self._iter_packet_items(ctx, packet_version, should_cancel=should_cancel, before_item=before_item)
                for index, (item, item_warnings) in enumerate(iterator):
                    if should_cancel():
                        raise _BuildCancelled()
                    item_seconds = float(item.pop("_build_seconds", 0) or 0)
                    item["task_id"] = task_id
                    self.store.conn.execute(
                        """
                        insert into structured_extraction_evidence_packet_build_items(
                            build_job_id, item_index, packet_item_json, warnings_json, created_at
                        ) values(?, ?, ?, ?, ?)
                        """,
                        (build_job_id, index, dumps(item), dumps(item_warnings), item["created_at"]),
                    )
                    processed += 1
                    total_chunk_count += len(item.get("chunks") or [])
                    if item_seconds >= 3.0:
                        slow_item_count += 1
                    warning_count += len(item_warnings)
                    if item_warnings:
                        warnings_preview.extend(item_warnings)
                        warnings_preview = warnings_preview[-20:]
                    ts = now()
                    self.store.conn.execute(
                        """
                        update structured_extraction_evidence_packet_build_jobs
                        set processed_item_count = ?, warning_count = ?, current_paper_id = ?,
                            current_field_group = ?, current_query_mode = ?, total_chunk_count = ?,
                            slow_item_count = ?, last_item_seconds = ?, warnings_preview_json = ?, updated_at = ?
                        where build_job_id = ?
                        """,
                        (
                            processed,
                            warning_count,
                            item["paper_id"],
                            item["field_group"],
                            item.get("query_mode"),
                            total_chunk_count,
                            slow_item_count,
                            round(item_seconds, 4),
                            dumps(warnings_preview),
                            ts,
                            build_job_id,
                        ),
                    )
                    self.store.conn.commit()
            except _BuildCancelled:
                self._finish_cancelled(build_job_id)
                return

            if self._job_status(build_job_id) == "cancelling":
                self._finish_cancelled(build_job_id)
                return
            ts = now()
            self.store.conn.execute(
                """
                update structured_extraction_evidence_packet_build_jobs
                set phase = 'finalizing', current_paper_id = null, current_field_group = null, updated_at = ?
                where build_job_id = ?
                """,
                (ts, build_job_id),
            )
            self.store.conn.commit()

            staged = self.store.conn.execute(
                """
                select packet_item_json, warnings_json from structured_extraction_evidence_packet_build_items
                where build_job_id = ?
                order by item_index asc
                """,
                (build_job_id,),
            ).fetchall()
            items = [loads(item_row["packet_item_json"], {}) or {} for item_row in staged]
            warnings: list[dict[str, Any]] = []
            for item_row in staged:
                warnings.extend(loads(item_row["warnings_json"], []) or [])
            summary = self._finalize_packet_version(task_id, packet_version, ctx, items, warnings, user=user)
            ts = now()
            self.store.conn.execute(
                """
                update structured_extraction_evidence_packet_build_jobs
                set status = 'completed', phase = 'completed', result_packet_version = ?,
                    processed_item_count = ?, warning_count = ?, warnings_preview_json = ?,
                    total_chunk_count = ?, slow_item_count = ?, updated_at = ?, completed_at = ?
                where build_job_id = ?
                """,
                (
                    summary["packet_version"],
                    summary["item_count"],
                    len(warnings),
                    dumps(warnings[-20:]),
                    total_chunk_count,
                    slow_item_count,
                    ts,
                    ts,
                    build_job_id,
                ),
            )
            self.store.conn.execute(
                "delete from structured_extraction_evidence_packet_build_items where build_job_id = ?",
                (build_job_id,),
            )
            self.store.conn.commit()
        except Exception as exc:  # noqa: BLE001
            ts = now()
            self.store.conn.execute(
                """
                update structured_extraction_evidence_packet_build_jobs
                set status = 'failed', phase = 'failed', error_json = ?, updated_at = ?, completed_at = ?
                where build_job_id = ?
                """,
                (dumps({"reason": str(exc)}), ts, ts, build_job_id),
            )
            self.store.conn.commit()

    def _job_status(self, build_job_id: str) -> str | None:
        row = self.store.conn.execute(
            "select status from structured_extraction_evidence_packet_build_jobs where build_job_id = ?",
            (build_job_id,),
        ).fetchone()
        return row["status"] if row else None

    def _finish_cancelled(self, build_job_id: str) -> None:
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_evidence_packet_build_jobs
            set status = 'cancelled', phase = 'cancelled', current_paper_id = null,
                current_field_group = null, updated_at = ?, completed_at = ?
            where build_job_id = ?
            """,
            (ts, ts, build_job_id),
        )
        self.store.conn.execute(
            "delete from structured_extraction_evidence_packet_build_items where build_job_id = ?",
            (build_job_id,),
        )
        self.store.conn.commit()

    def _active_build_job(self, task_id: str, user_id: str):
        return self.store.conn.execute(
            """
            select * from structured_extraction_evidence_packet_build_jobs
            where task_id = ? and user_id = ? and status in ('queued', 'running', 'cancelling')
            order by created_at desc
            limit 1
            """,
            (task_id, user_id),
        ).fetchone()

    def list_versions(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_evidence_packet_versions
            where task_id = ? and user_id = ?
            order by created_at desc
            """,
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "versions": [self._row_to_version(row) for row in rows]}

    def get_version(self, task_id: str, packet_version: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            """
            select * from structured_extraction_evidence_packet_versions
            where task_id = ? and user_id = ? and packet_version = ?
            """,
            (task_id, user.user_id, packet_version),
        ).fetchone()
        if not row:
            raise KeyError(f"evidence packet not found: {packet_version}")
        return self._row_to_version(row)

    def list_items(self, task_id: str, packet_version: str, *, user: UserContext, limit: int | None = None, offset: int | None = None) -> dict[str, Any]:
        self.get_version(task_id, packet_version, user=user)
        if limit is None and offset is None:
            rows = self.store.conn.execute(
                """
                select * from structured_extraction_evidence_packet_items
                where task_id = ? and packet_version = ?
                order by paper_id asc, field_group asc
                """,
                (task_id, packet_version),
            ).fetchall()
            return {"task_id": task_id, "packet_version": packet_version, "items": [self._row_to_item(row) for row in rows]}
        safe_limit = _bounded_int(limit, 1, 1000, 200)
        safe_offset = max(0, int(offset or 0))
        total = self.store.conn.execute(
            "select count(*) from structured_extraction_evidence_packet_items where task_id = ? and packet_version = ?",
            (task_id, packet_version),
        ).fetchone()[0]
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_evidence_packet_items
            where task_id = ? and packet_version = ?
            order by paper_id asc, field_group asc
            limit ? offset ?
            """,
            (task_id, packet_version, safe_limit, safe_offset),
        ).fetchall()
        return {
            "task_id": task_id,
            "packet_version": packet_version,
            "items": [self._row_to_item(row) for row in rows],
            "limit": safe_limit,
            "offset": safe_offset,
            "total": total,
        }

    def _collection_papers(self, task_id: str, collection_version: str, *, user: UserContext) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_collection_papers
            where task_id = ? and collection_version = ?
            order by created_at asc, candidate_id asc
            """,
            (task_id, collection_version),
        ).fetchall()
        if not rows:
            raise ValueError("collection_version_not_found")
        return [loads(row["paper_ref_json"], {}) or {} for row in rows]

    def _schema_version(self, task_id: str, schema_version: str, *, user: UserContext) -> dict[str, Any]:
        row = self.store.conn.execute(
            """
            select * from structured_extraction_schema_versions
            where task_id = ? and user_id = ? and schema_version = ?
            """,
            (task_id, user.user_id, schema_version),
        ).fetchone()
        if not row:
            raise ValueError("schema_version_not_found")
        return {
            "record_schema": loads(row["record_schema_json"], {}) or {},
            "field_groups": loads(row["field_groups_json"], []) or [],
            "fields": loads(row["fields_json"], []) or [],
        }

    def _next_version(self, task_id: str) -> str:
        rows = list(self.store.conn.execute(
            "select packet_version from structured_extraction_evidence_packet_versions where task_id = ?",
            (task_id,),
        ).fetchall())
        rows.extend(
            self.store.conn.execute(
                """
                select target_packet_version as packet_version
                from structured_extraction_evidence_packet_build_jobs
                where task_id = ?
                union all
                select result_packet_version as packet_version
                from structured_extraction_evidence_packet_build_jobs
                where task_id = ? and result_packet_version is not null
                """,
                (task_id, task_id),
            ).fetchall()
        )
        max_n = 0
        for row in rows:
            match = re.match(r"^ep_v(\d+)$", row["packet_version"] or "")
            if match:
                max_n = max(max_n, int(match.group(1)))
        return f"ep_v{max_n + 1}"

    @staticmethod
    def _row_to_build_job(row) -> dict[str, Any]:
        return {
            "build_job_id": row["build_job_id"],
            "task_id": row["task_id"],
            "status": row["status"],
            "phase": row["phase"],
            "collection_version": row["collection_version"],
            "schema_version": row["schema_version"],
            "prompt_contract_version": row["prompt_contract_version"],
            "target_packet_version": row["target_packet_version"],
            "result_packet_version": row["result_packet_version"],
            "paper_count": row["paper_count"],
            "field_group_count": row["field_group_count"],
            "total_item_count": row["total_item_count"],
            "processed_item_count": row["processed_item_count"],
            "warning_count": row["warning_count"],
            "current_paper_id": row["current_paper_id"],
            "current_field_group": row["current_field_group"],
            "current_query_mode": row["current_query_mode"] if "current_query_mode" in row.keys() else None,
            "avg_chunks_per_item": (
                round((row["total_chunk_count"] or 0) / row["processed_item_count"], 4)
                if "total_chunk_count" in row.keys() and row["processed_item_count"]
                else 0
            ),
            "slow_item_count": row["slow_item_count"] if "slow_item_count" in row.keys() else 0,
            "last_item_seconds": row["last_item_seconds"] if "last_item_seconds" in row.keys() else None,
            "settings": loads(row["settings_json"], {}) or {},
            "warnings_preview": loads(row["warnings_preview_json"], []) or [],
            "error": loads(row["error_json"], {}) if row["error_json"] else None,
            "core_job_id": row["core_job_id"] if "core_job_id" in row.keys() else None,
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    @staticmethod
    def _row_to_version(row) -> dict[str, Any]:
        return {
            "packet_version": row["packet_version"],
            "task_id": row["task_id"],
            "collection_version": row["collection_version"],
            "schema_version": row["schema_version"],
            "prompt_contract_version": row["prompt_contract_version"],
            "paper_count": row["paper_count"],
            "field_group_count": row["field_group_count"],
            "item_count": row["item_count"],
            "settings": loads(row["settings_json"], {}) or {},
            "warnings": loads(row["warnings_json"], []) or [],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _row_to_item(row) -> dict[str, Any]:
        return {
            "packet_item_id": row["packet_item_id"],
            "packet_version": row["packet_version"],
            "paper_id": row["paper_id"],
            "field_group": row["field_group"],
            "field_keys": loads(row["field_keys_json"], []) or [],
            "construction_query": row["construction_query"],
            "retrieved_sections": loads(row["retrieved_sections_json"], []) or [],
            "chunks": loads(row["chunks_json"], []) or [],
            "tables": loads(row["tables_json"], []) or [],
            "figures": loads(row["figures_json"], []) or [],
            "source_paths": loads(row["source_paths_json"], []) or [],
            "warnings": loads(row["warnings_json"], []) or [],
            "created_at": row["created_at"],
        }


def _open_index() -> sqlite3.Connection:
    index_path = Path(literature_search_shared.service.paths.index_db)
    if not index_path.exists():
        raise ValueError(f"research index not found: {index_path}")
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    return conn


def _fields_by_group(fields: list[dict[str, Any]], groups: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out = {group["group_key"]: [] for group in groups}
    for field in fields:
        group_key = field.get("group_key") or groups[0]["group_key"]
        out.setdefault(group_key, []).append(field)
    return out


def _construction_query(group: dict[str, Any], fields: list[dict[str, Any]], record_schema: dict[str, Any]) -> str:
    pieces = [
        group.get("group_key"),
        group.get("label"),
        group.get("description"),
        record_schema.get("primary_entity"),
    ]
    for field in fields:
        pieces.extend([field.get("key"), field.get("label"), field.get("description"), field.get("extraction_instruction"), field.get("unit")])
    terms = []
    seen = set()
    for term in _terms(" ".join(str(piece or "") for piece in pieces)):
        if term not in seen:
            terms.append(term)
            seen.add(term)
    return " ".join(terms[:32])


def _ranked_chunks(
    conn: sqlite3.Connection,
    paper_id: str,
    query: str,
    *,
    limit: int,
    max_chars: int,
    article_id: int | str | None = None,
    should_cancel=None,
) -> list[dict[str, Any]]:
    if article_id not in (None, ""):
        chunks = _ranked_chunks_for_key(
            conn,
            "article_id",
            article_id,
            query,
            limit=limit,
            max_chars=max_chars,
            query_mode="article_id",
            should_cancel=should_cancel,
        )
        if chunks:
            return chunks
    return _ranked_chunks_for_key(
        conn,
        "paper_id",
        paper_id,
        query,
        limit=limit,
        max_chars=max_chars,
        query_mode="paper_id_fallback",
        article_id=article_id,
        should_cancel=should_cancel,
    )


def _ranked_chunks_for_key(
    conn: sqlite3.Connection,
    key_column: str,
    key_value,
    query: str,
    *,
    limit: int,
    max_chars: int,
    query_mode: str,
    article_id=None,
    should_cancel=None,
) -> list[dict[str, Any]]:
    if key_column not in {"paper_id", "article_id"}:
        return []
    try:
        rows = conn.execute(
            f"""
            select id, paper_id, kind, section, heading_norm, section_id, chunk_index, source_path, text
            from documents
            where {key_column} = ? and coalesce(text, '') != ''
            """,
            (key_value,),
        )
    except sqlite3.Error:
        return []
    query_terms = set(_terms(query))
    out = []
    for row in rows:
        if should_cancel and should_cancel():
            raise _BuildCancelled()
        text = row["text"] or ""
        score = _score_text(text, query_terms)
        if score <= 0:
            score = 0.01
        out.append(
            {
                "evidence_id": f"E{row['id']}",
                "source_path": row["source_path"] or "",
                "section": row["section"] or row["heading_norm"] or "",
                "section_id": row["section_id"],
                "chunk_index": row["chunk_index"],
                "text": text[:max_chars],
                "score": round(score, 4),
                "query_mode": query_mode,
                "article_id": article_id if article_id not in (None, "") else (key_value if key_column == "article_id" else None),
            }
        )
    out.sort(key=lambda item: (-item["score"], item.get("section") or "", item.get("chunk_index") or 0))
    return out[:limit]


def _metadata_fallback(paper: dict[str, Any], query: str, *, max_chars: int) -> dict[str, Any] | None:
    metadata = paper.get("metadata") or {}
    text = metadata.get("abstract") or paper.get("title") or ""
    if not text:
        return None
    return {
        "evidence_id": f"meta:{paper.get('paper_id')}",
        "source_path": paper.get("abstract_path") or paper.get("md_path") or paper.get("article_dir") or "",
        "section": "metadata",
        "section_id": None,
        "chunk_index": None,
        "text": text[:max_chars],
        "score": round(_score_text(text, set(_terms(query))) or 0.01, 4),
    }


def _assets(conn: sqlite3.Connection, paper_id: str) -> dict[str, list[dict[str, Any]]]:
    try:
        rows = conn.execute(
            "select kind, source_path, label, caption from paper_assets where paper_id = ? order by kind, source_path",
            (paper_id,),
        ).fetchall()
    except sqlite3.Error:
        return {"tables": [], "figures": []}
    tables = []
    figures = []
    for row in rows:
        item = {
            "kind": row["kind"],
            "source_path": row["source_path"] or "",
            "label": row["label"],
            "caption": row["caption"],
        }
        if row["kind"] == "table":
            tables.append(item)
        elif row["kind"] == "figure":
            figures.append(item)
    return {"tables": tables, "figures": figures}


def _sections_from_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    sections = []
    for chunk in chunks:
        key = chunk.get("section") or chunk.get("section_id") or ""
        if not key or key in seen:
            continue
        seen.add(key)
        sections.append({"section": chunk.get("section"), "section_id": chunk.get("section_id"), "source_path": chunk.get("source_path")})
    return sections


def _terms(text: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[\w.-]+", text or "") if len(term) > 1]


def _score_text(text: str, query_terms: set[str]) -> float:
    if not query_terms:
        return 0.01
    text_terms = set(_terms(text))
    if not text_terms:
        return 0.0
    overlap = len(text_terms & query_terms)
    return overlap / max(len(query_terms), 1)


def _bounded_int(raw: int | None, lo: int, hi: int, default: int) -> int:
    try:
        value = int(raw if raw is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))
