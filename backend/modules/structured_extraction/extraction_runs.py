from __future__ import annotations

import asyncio
from typing import Any

from core.llm import LLMUnavailable
from core.user_context import UserContext
from core.worker.queue import JobQueue

from .artifacts import write_extraction_run
from .artifacts import write_task_manifest
from . import llm_extraction
from .schemas import DEFAULT_TASK_STATS, ExtractionRunResumeRequest, ExtractionRunStartRequest
from .schema_contract import is_nested_schema_mode
from .store import StructuredExtractionStore, dumps, loads, new_uuid, now

TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "cancelled", "interrupted"}
ACTIVE_STATUSES = {"queued", "running", "cancelling"}


class StructuredExtractionRunService:
    def __init__(self, store: StructuredExtractionStore) -> None:
        self.store = store
        self.job_queue = JobQueue(self.store.engine)

    def start(self, task_id: str, payload: ExtractionRunStartRequest, *, user: UserContext) -> dict[str, Any]:
        task = self.store.get_task(task_id, user_id=user.user_id)
        collection_version = payload.collection_version or task.get("current_collection_version")
        schema_version = payload.schema_version or task.get("current_schema_version")
        if not collection_version:
            raise ValueError("collection_version_required")
        if not schema_version:
            raise ValueError("schema_version_required")
        prompt_contract = self._resolve_prompt_contract(task_id, user=user, collection_version=collection_version, schema_version=schema_version, prompt_contract_version=payload.prompt_contract_version)
        packet = self._resolve_packet(task_id, user=user, collection_version=collection_version, schema_version=schema_version, prompt_contract_version=prompt_contract["prompt_contract_version"], packet_version=payload.packet_version)
        packet_items = self._packet_items(task_id, packet["packet_version"], user=user)
        packet_items = _sort_packet_items(packet_items, prompt_contract)
        if not packet_items:
            raise ValueError("evidence_packet_empty")
        run_id = new_uuid()
        ts = now()
        stats = {
            "packet_item_count": len(packet_items),
            "completed_item_count": 0,
            "failed_item_count": 0,
            "record_count": 0,
        }
        self.store.conn.execute(
            """
            insert into structured_extraction_runs(
                run_id, task_id, user_id, status, collection_version, schema_version,
                prompt_contract_version, packet_version, model_snapshot_json, stats_json,
                previous_task_status, created_at
            ) values(?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                task_id,
                user.user_id,
                collection_version,
                schema_version,
                prompt_contract["prompt_contract_version"],
                packet["packet_version"],
                dumps(llm_extraction.model_snapshot(user_id=user.user_id)),
                dumps(stats),
                task.get("status"),
                ts,
            ),
        )
        for index, item in enumerate(packet_items):
            self.store.conn.execute(
                """
                insert into structured_extraction_run_items(
                    run_item_id, run_id, task_id, user_id, packet_item_id, paper_id, field_group, status, created_at
                ) values(?, ?, ?, ?, ?, ?, ?, 'queued', ?)
                """,
                (
                    new_uuid(),
                    run_id,
                    task_id,
                    user.user_id,
                    item["packet_item_id"],
                    item["paper_id"],
                    item["field_group"],
                    ts + (index * 0.000001),
                ),
            )
        self._event(run_id, task_id, user.user_id, "queued", {"packet_item_count": len(packet_items)}, ts=ts)
        self.store.conn.commit()
        core_job = self.job_queue.enqueue(
            "structured.extraction_run",
            {"task_id": task_id, "run_id": run_id, "user_id": user.user_id},
            user_id=user.user_id,
            queue="structured-extraction",
        )
        self.store.conn.execute("update structured_extraction_runs set core_job_id = ? where run_id = ?", (core_job["job_id"], run_id))
        self.store.conn.commit()
        run = self.get(task_id, run_id, user=user)
        return run

    def list_runs(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_runs
            where task_id = ? and user_id = ?
            order by created_at desc
            """,
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "runs": [self._row_to_run(row) for row in rows]}

    def get(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            "select * from structured_extraction_runs where task_id = ? and user_id = ? and run_id = ?",
            (task_id, user.user_id, run_id),
        ).fetchone()
        if not row:
            raise KeyError(f"run not found: {run_id}")
        return self._row_to_run(row)

    def list_items(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        self.get(task_id, run_id, user=user)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_run_items
            where task_id = ? and user_id = ? and run_id = ?
            order by created_at asc, run_item_id asc
            """,
            (task_id, user.user_id, run_id),
        ).fetchall()
        return {"task_id": task_id, "run_id": run_id, "items": [self._row_to_item(row) for row in rows]}

    def list_records(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        run = self.get(task_id, run_id, user=user)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_records
            where task_id = ? and user_id = ? and run_id = ?
            order by paper_id asc, record_index asc, record_id asc
            """,
            (task_id, user.user_id, run_id),
        ).fetchall()
        paper_map = self._paper_metadata_map(task_id, run["collection_version"])
        records = []
        for row in rows:
            record = self._row_to_record(row)
            metadata = paper_map.get(record["paper_id"], {"paper_id": record["paper_id"]})
            record["paper_metadata"] = metadata
            record["paper"] = metadata
            records.append(record)
        return {"task_id": task_id, "run_id": run_id, "records": records}

    def _paper_metadata_map(self, task_id: str, collection_version: str) -> dict[str, dict[str, Any]]:
        rows = self.store.conn.execute(
            "select paper_id, paper_ref_json from structured_extraction_collection_papers where task_id = ? and collection_version = ?",
            (task_id, collection_version),
        ).fetchall()
        out = {}
        for row in rows:
            ref = loads(row["paper_ref_json"], {}) or {}
            out[row["paper_id"]] = {
                "paper_id": row["paper_id"],
                "title": ref.get("title") or "",
                "doi": ref.get("doi") or "",
                "year": ref.get("year"),
                "journal": ref.get("journal") or "",
                "authors": ref.get("authors") or [],
                "source_path": ref.get("source_path") or "",
                "index_version": ref.get("index_version"),
            }
        return out

    def cancel(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        run = self.get(task_id, run_id, user=user)
        if run["status"] in TERMINAL_STATUSES:
            return run
        if run["status"] == "queued":
            if run.get("core_job_id"):
                self.job_queue.cancel(run["core_job_id"])
            self._finalize_cancelled(task_id, run_id, user.user_id)
            return self.get(task_id, run_id, user=user)
        ts = now()
        self.store.conn.execute(
            "update structured_extraction_runs set status = 'cancelling' where task_id = ? and user_id = ? and run_id = ?",
            (task_id, user.user_id, run_id),
        )
        self._event(run_id, task_id, user.user_id, "cancelling", {}, ts=ts)
        self.store.conn.commit()
        if run.get("core_job_id"):
            self.job_queue.cancel(run["core_job_id"])
        return self.get(task_id, run_id, user=user)

    def recovery_status(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        run = self.get(task_id, run_id, user=user)
        return self._recovery_status_from_run(task_id, run, user=user)

    def resume(self, task_id: str, run_id: str, payload: ExtractionRunResumeRequest, *, user: UserContext) -> dict[str, Any]:
        run = self.get(task_id, run_id, user=user)
        recovery = self._recovery_status_from_run(task_id, run, user=user, retry_failed_items=payload.retry_failed_items)
        if "run_locked_by_review_or_export" in recovery["blockers"]:
            raise PermissionError("run_locked_by_review_or_export")
        if not recovery["resumable"]:
            raise ValueError("run_not_resumable")
        ts = now()
        retry_statuses = ["queued", "running", "interrupted"]
        if payload.retry_failed_items:
            retry_statuses.append("failed")
        placeholders = ",".join("?" for _ in retry_statuses)
        self.store.conn.execute(
            f"""
            update structured_extraction_run_items
            set status = 'queued', error_json = null, started_at = null, completed_at = null
            where task_id = ? and user_id = ? and run_id = ? and status in ({placeholders})
            """,
            (task_id, user.user_id, run_id, *retry_statuses),
        )
        self.store.conn.execute(
            """
            update structured_extraction_runs
            set status = 'queued', error_json = null, completed_at = null, interrupted_at = null,
                recovery_json = ?, resume_count = resume_count + 1
            where task_id = ? and user_id = ? and run_id = ?
            """,
            (dumps({"reason": payload.reason, "resumed_at": ts, "retry_failed_items": payload.retry_failed_items}), task_id, user.user_id, run_id),
        )
        self._event(run_id, task_id, user.user_id, "resumed", {"reason": payload.reason, "retry_failed_items": payload.retry_failed_items}, ts=ts)
        self.store.conn.commit()
        core_job = self.job_queue.enqueue(
            "structured.extraction_run",
            {"task_id": task_id, "run_id": run_id, "user_id": user.user_id, "resume": True},
            user_id=user.user_id,
            queue="structured-extraction",
        )
        self.store.conn.execute("update structured_extraction_runs set core_job_id = ? where run_id = ?", (core_job["job_id"], run_id))
        self.store.conn.commit()
        return self.get(task_id, run_id, user=user)

    def reap_orphaned_runs(self) -> list[str]:
        rows = self.store.conn.execute(
            "select * from structured_extraction_runs where status in ('queued', 'running', 'cancelling')"
        ).fetchall()
        reaped: list[str] = []
        for row in rows:
            ts = now()
            error = {"reason": "process_restarted"}
            self.store.conn.execute(
                """
                update structured_extraction_runs
                set status = 'interrupted', error_json = ?, interrupted_at = ?, completed_at = ?,
                    recovery_json = ?
                where run_id = ?
                """,
                (dumps(error), ts, ts, dumps(error), row["run_id"]),
            )
            self.store.conn.execute(
                """
                update structured_extraction_run_items
                set status = 'interrupted', error_json = ?, completed_at = ?
                where run_id = ? and status in ('queued', 'running')
                """,
                (dumps(error), ts, row["run_id"]),
            )
            self._event(row["run_id"], row["task_id"], row["user_id"], "interrupted", error, ts=ts)
            reaped.append(row["run_id"])
        self.store.conn.commit()
        return reaped

    def _worker_entry(self, task_id: str, run_id: str, user_id: str) -> None:
        asyncio.run(self._run_worker(task_id, run_id, user_id))

    async def _run_worker(self, task_id: str, run_id: str, user_id: str) -> None:
        user = UserContext(user_id, user_id)
        task = self.store.get_task(task_id, user_id=user_id)
        run = self.get(task_id, run_id, user=user)
        ts = now()
        self.store.conn.execute(
            "update structured_extraction_runs set status = 'running', started_at = coalesce(started_at, ?), last_heartbeat_at = ? where run_id = ?",
            (ts, ts, run_id),
        )
        self._set_task_status(task_id, user_id, "extracting")
        self._event(run_id, task_id, user_id, "started", {}, ts=ts)
        self.store.conn.commit()
        try:
            contract = self._prompt_contract(task_id, run["prompt_contract_version"], user=user)
            packet_items = {item["packet_item_id"]: item for item in self._packet_items(task_id, run["packet_version"], user=user)}
            item_rows = self.store.conn.execute(
                """
                select * from structured_extraction_run_items
                where run_id = ? and user_id = ? and status != 'completed'
                order by created_at asc, run_item_id asc
                """,
                (run_id, user_id),
            ).fetchall()
            for row in item_rows:
                self.store.conn.execute("update structured_extraction_runs set last_heartbeat_at = ? where run_id = ?", (now(), run_id))
                self.store.conn.commit()
                if self._run_status(run_id) == "cancelling":
                    self._finalize_cancelled(task_id, run_id, user_id)
                    return
                packet_item = packet_items[row["packet_item_id"]]
                await self._process_item(task, run_id, row["run_item_id"], packet_item, contract, user)
                if self._run_status(run_id) == "cancelling":
                    self._finalize_cancelled(task_id, run_id, user_id)
                    return
            self._merge_records(task_id, run_id, contract, user=user)
            self._finalize_run(task_id, run_id, user_id)
        except LLMUnavailable:
            self._fail_run(task_id, run_id, user_id, {"reason": "llm_unavailable"})
        except Exception as exc:  # noqa: BLE001
            self._fail_run(task_id, run_id, user_id, {"reason": "run_failed", "detail": str(exc)})

    async def _process_item(self, task: dict[str, Any], run_id: str, run_item_id: str, packet_item: dict[str, Any], contract: dict[str, Any], user: UserContext) -> None:
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_run_items
            set status = 'running', started_at = ?, last_attempt_at = ?, attempt_count = attempt_count + 1
            where run_item_id = ?
            """,
            (ts, ts, run_item_id),
        )
        self.store.conn.commit()
        try:
            prompt, raw, parsed = await llm_extraction.extract_packet_item(
                task=task,
                contract=contract,
                packet_item=packet_item,
                user_id=user.user_id,
            )
            normalized = _normalize_item_records(parsed, packet_item, contract)
            self.store.conn.execute(
                """
                update structured_extraction_run_items
                set status = 'completed', prompt_json = ?, raw_output = ?, parsed_json = ?, completed_at = ?
                where run_item_id = ?
                """,
                (dumps(prompt), raw, dumps(normalized), now(), run_item_id),
            )
            self._event(run_id, task["task_id"], user.user_id, "item_completed", {"run_item_id": run_item_id, "packet_item_id": packet_item["packet_item_id"]})
        except LLMUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            error = {"reason": "llm_output_invalid", "detail": str(exc)}
            self.store.conn.execute(
                """
                update structured_extraction_run_items
                set status = 'failed', raw_output = coalesce(raw_output, ''), error_json = ?, completed_at = ?
                where run_item_id = ?
                """,
                (dumps(error), now(), run_item_id),
            )
            self._event(run_id, task["task_id"], user.user_id, "item_failed", {"run_item_id": run_item_id, "error": error})
        self.store.conn.commit()

    def _merge_records(self, task_id: str, run_id: str, contract: dict[str, Any], *, user: UserContext) -> None:
        self.store.conn.execute("delete from structured_extraction_records where run_id = ?", (run_id,))
        rows = self.store.conn.execute(
            "select * from structured_extraction_run_items where run_id = ? and status = 'completed' order by created_at asc, run_item_id asc",
            (run_id,),
        ).fetchall()
        identity_fields = (contract.get("record_contract") or {}).get("record_identity_fields") or ["paper_id"]
        record_type = (contract.get("record_contract") or {}).get("record_type")
        schema_mode = contract.get("schema_mode") or "flat_fields"
        merged: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            parsed = loads(row["parsed_json"], {}) or {}
            for record in parsed.get("records") or []:
                identity = record.get("record_identity") or {}
                flags = list(record.get("quality_flags") or [])
                if not isinstance(identity, dict):
                    identity = {"paper_id": record.get("paper_id") or row["paper_id"]}
                    flags.append("invalid_record_identity_shape")
                key_values = [record.get("paper_id") or row["paper_id"]]
                missing_identity = False
                for field in identity_fields:
                    if field == "paper_id":
                        continue
                    value = identity.get(field)
                    if value in (None, ""):
                        missing_identity = True
                    key_values.append(value)
                if missing_identity:
                    flags.append("missing_record_identity")
                    key_values.append(row["run_item_id"])
                key = tuple(key_values)
                target = merged.setdefault(
                    key,
                    {
                        "paper_id": record.get("paper_id") or row["paper_id"],
                        "record_type": record.get("record_type") or record_type,
                        "record_identity": identity,
                        "data": {},
                        "fields": {},
                        "source_packet_item_ids": [],
                        "quality_flags": [],
                    },
                )
                target["record_identity"].update(identity)
                if is_nested_schema_mode(schema_mode):
                    _deep_merge(target["data"], record.get("data") or {})
                    target["fields"].update(_top_level_fields(record.get("data") or {}))
                else:
                    target["data"].update(record.get("data") or {})
                    target["fields"].update(record.get("fields") or {})
                target["source_packet_item_ids"].append(row["packet_item_id"])
                target["quality_flags"] = sorted(set(target["quality_flags"] + flags))
        per_paper: dict[str, int] = {}
        ts = now()
        for record in merged.values():
            paper_id = record["paper_id"]
            per_paper[paper_id] = per_paper.get(paper_id, 0) + 1
            record_index = per_paper[paper_id]
            record_id = new_uuid()
            out = {
                "record_id": record_id,
                "run_id": run_id,
                "paper_id": paper_id,
                "record_type": record["record_type"],
                "record_index": record_index,
                "record_identity": record["record_identity"],
                "data": record["data"],
                "fields": record["fields"],
                "source_packet_item_ids": sorted(set(record["source_packet_item_ids"])),
                "quality_flags": record["quality_flags"],
                "created_at": ts,
            }
            self.store.conn.execute(
                """
                insert into structured_extraction_records(
                    record_id, run_id, task_id, user_id, paper_id, record_type, record_index,
                    record_identity_json, data_json, fields_json, source_packet_item_ids_json, quality_flags_json,
                    record_json, created_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    run_id,
                    task_id,
                    user.user_id,
                    paper_id,
                    record["record_type"],
                    record_index,
                    dumps(out["record_identity"]),
                    dumps(out["data"]),
                    dumps(out["fields"]),
                    dumps(out["source_packet_item_ids"]),
                    dumps(out["quality_flags"]),
                    dumps(out),
                    ts,
                ),
            )
        self.store.conn.commit()

    def _finalize_run(self, task_id: str, run_id: str, user_id: str) -> None:
        item_counts = self._item_counts(run_id)
        record_count = self.store.conn.execute("select count(*) from structured_extraction_records where run_id = ?", (run_id,)).fetchone()[0]
        if record_count == 0 and item_counts["failed"] > 0 and item_counts["completed"] == 0:
            status = "failed"
            error = {"reason": "all_items_failed"}
            task_status = "failed"
        else:
            status = "completed_with_errors" if item_counts["failed"] else "completed"
            error = None
            task_status = "review_required"
        stats = self._run_stats(run_id, record_count=record_count)
        ts = now()
        should_count = self._should_count_run(run_id)
        self.store.conn.execute(
            "update structured_extraction_runs set status = ?, stats_json = ?, error_json = ?, completed_at = ?, counted_at = coalesce(counted_at, ?) where run_id = ?",
            (status, dumps(stats), dumps(error) if error else None, ts, ts, run_id),
        )
        self._set_task_status(task_id, user_id, task_status, increment_run=should_count, last_run_at=ts)
        self._event(run_id, task_id, user_id, status, {"stats": stats, "error": error}, ts=ts)
        self.store.conn.commit()
        self._write_artifacts(task_id, run_id, user_id)

    def _fail_run(self, task_id: str, run_id: str, user_id: str, error: dict[str, Any]) -> None:
        ts = now()
        stats = self._run_stats(run_id, record_count=0)
        should_count = self._should_count_run(run_id)
        self.store.conn.execute(
            "update structured_extraction_runs set status = 'failed', stats_json = ?, error_json = ?, completed_at = ?, counted_at = coalesce(counted_at, ?) where run_id = ?",
            (dumps(stats), dumps(error), ts, ts, run_id),
        )
        self._set_task_status(task_id, user_id, "failed", increment_run=should_count, last_run_at=ts)
        self._event(run_id, task_id, user_id, "failed", {"error": error}, ts=ts)
        self.store.conn.commit()
        self._write_artifacts(task_id, run_id, user_id)

    def _finalize_cancelled(self, task_id: str, run_id: str, user_id: str) -> None:
        run = self.get(task_id, run_id, user=UserContext(user_id, user_id))
        ts = now()
        self.store.conn.execute(
            "update structured_extraction_runs set status = 'cancelled', completed_at = ? where run_id = ?",
            (ts, run_id),
        )
        self._set_task_status(task_id, user_id, run.get("previous_task_status") or "schema_ready")
        self._event(run_id, task_id, user_id, "cancelled", {}, ts=ts)
        self.store.conn.commit()
        self._write_artifacts(task_id, run_id, user_id)

    def _set_task_status(self, task_id: str, user_id: str, status: str, *, increment_run: bool = False, last_run_at: float | None = None) -> None:
        task = self.store.get_task(task_id, user_id=user_id)
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(task.get("stats") or {})
        if increment_run:
            stats["run_count"] = int(stats.get("run_count") or 0) + 1
        self.store.conn.execute(
            "update structured_extraction_tasks set status = ?, stats_json = ?, last_run_at = coalesce(?, last_run_at), updated_at = ? where task_id = ? and user_id = ?",
            (status, dumps(stats), last_run_at, now(), task_id, user_id),
        )
        updated = dict(task)
        updated["status"] = status
        updated["stats"] = stats
        updated["last_run_at"] = last_run_at if last_run_at is not None else task.get("last_run_at")
        updated["updated_at"] = now()
        write_task_manifest(UserContext(user_id, user_id), updated)

    def _write_artifacts(self, task_id: str, run_id: str, user_id: str) -> None:
        user = UserContext(user_id, user_id)
        run = self.get(task_id, run_id, user=user)
        items = self.list_items(task_id, run_id, user=user)["items"]
        records = self.list_records(task_id, run_id, user=user)["records"]
        write_extraction_run(user, task_id, run, items, records)

    def _resolve_prompt_contract(self, task_id: str, *, user: UserContext, collection_version: str, schema_version: str, prompt_contract_version: str | None) -> dict[str, Any]:
        if prompt_contract_version:
            contract = self._prompt_contract(task_id, prompt_contract_version, user=user)
            if contract.get("collection_version") != collection_version or contract.get("schema_version") != schema_version:
                raise ValueError("prompt_contract_incompatible")
            return contract
        row = self.store.conn.execute(
            """
            select * from structured_extraction_prompt_contracts
            where task_id = ? and user_id = ? and collection_version = ? and schema_version = ?
            order by created_at desc limit 1
            """,
            (task_id, user.user_id, collection_version, schema_version),
        ).fetchone()
        if not row:
            raise ValueError("prompt_contract_required")
        return loads(row["contract_json"], {}) or {}

    def _resolve_packet(self, task_id: str, *, user: UserContext, collection_version: str, schema_version: str, prompt_contract_version: str, packet_version: str | None) -> dict[str, Any]:
        params = [task_id, user.user_id, collection_version, schema_version, prompt_contract_version]
        where = "task_id = ? and user_id = ? and collection_version = ? and schema_version = ? and prompt_contract_version = ?"
        if packet_version:
            where += " and packet_version = ?"
            params.append(packet_version)
        row = self.store.conn.execute(
            f"select * from structured_extraction_evidence_packet_versions where {where} order by created_at desc limit 1",
            params,
        ).fetchone()
        if not row:
            raise ValueError("evidence_packet_not_found" if packet_version else "evidence_packet_required")
        return {"packet_version": row["packet_version"]}

    def _prompt_contract(self, task_id: str, prompt_contract_version: str, *, user: UserContext) -> dict[str, Any]:
        row = self.store.conn.execute(
            "select * from structured_extraction_prompt_contracts where task_id = ? and user_id = ? and prompt_contract_version = ?",
            (task_id, user.user_id, prompt_contract_version),
        ).fetchone()
        if not row:
            raise ValueError("prompt_contract_not_found")
        return loads(row["contract_json"], {}) or {}

    def _packet_items(self, task_id: str, packet_version: str, *, user: UserContext) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            "select * from structured_extraction_evidence_packet_items where task_id = ? and packet_version = ? order by paper_id asc, field_group asc",
            (task_id, packet_version),
        ).fetchall()
        return [_packet_item_from_row(row) for row in rows]

    def _item_counts(self, run_id: str) -> dict[str, int]:
        rows = self.store.conn.execute("select status, count(*) as n from structured_extraction_run_items where run_id = ? group by status", (run_id,)).fetchall()
        out = {"completed": 0, "failed": 0}
        for row in rows:
            if row["status"] in out:
                out[row["status"]] = int(row["n"])
        return out

    def _run_stats(self, run_id: str, *, record_count: int) -> dict[str, int]:
        total = self.store.conn.execute("select count(*) from structured_extraction_run_items where run_id = ?", (run_id,)).fetchone()[0]
        counts = self._item_counts(run_id)
        return {
            "packet_item_count": int(total),
            "completed_item_count": counts["completed"],
            "failed_item_count": counts["failed"],
            "record_count": int(record_count),
        }

    def _run_status(self, run_id: str) -> str:
        row = self.store.conn.execute("select status from structured_extraction_runs where run_id = ?", (run_id,)).fetchone()
        return row["status"] if row else "failed"

    def _should_count_run(self, run_id: str) -> bool:
        row = self.store.conn.execute("select counted_at from structured_extraction_runs where run_id = ?", (run_id,)).fetchone()
        return bool(row and row["counted_at"] is None)

    def _run_is_locked(self, task_id: str, run_id: str, user_id: str) -> bool:
        review_count = self.store.conn.execute(
            "select count(*) from structured_extraction_review_events where task_id = ? and run_id = ? and user_id = ?",
            (task_id, run_id, user_id),
        ).fetchone()[0]
        export_count = self.store.conn.execute(
            "select count(*) from structured_extraction_exports where task_id = ? and run_id = ? and user_id = ?",
            (task_id, run_id, user_id),
        ).fetchone()[0]
        return bool(review_count or export_count)

    def _recovery_status_from_run(self, task_id: str, run: dict[str, Any], *, user: UserContext, retry_failed_items: bool = True) -> dict[str, Any]:
        rows = self.store.conn.execute(
            """
            select status, count(*) as n from structured_extraction_run_items
            where task_id = ? and user_id = ? and run_id = ?
            group by status
            """,
            (task_id, user.user_id, run["run_id"]),
        ).fetchall()
        counts = {"completed": 0, "failed": 0, "interrupted": 0, "queued": 0, "running": 0}
        for row in rows:
            if row["status"] in counts:
                counts[row["status"]] = int(row["n"])
        retryable = counts["queued"] + counts["running"] + counts["interrupted"] + (counts["failed"] if retry_failed_items else 0)
        record_count = self.store.conn.execute(
            "select count(*) from structured_extraction_records where task_id = ? and user_id = ? and run_id = ?",
            (task_id, user.user_id, run["run_id"]),
        ).fetchone()[0]
        blockers = []
        if self._run_is_locked(task_id, run["run_id"], user.user_id):
            blockers.append("run_locked_by_review_or_export")
        if run["status"] == "completed":
            blockers.append("run_already_completed")
        if run["status"] in {"failed", "interrupted", "cancelled", "completed_with_errors"} and retryable <= 0:
            blockers.append("no_remaining_items")
        if run["status"] not in {"failed", "interrupted", "cancelled", "completed_with_errors", "queued"} and run["status"] != "completed":
            blockers.append("run_status_not_resumable")
        return {
            "run_id": run["run_id"],
            "task_id": task_id,
            "resumable": not blockers and retryable > 0,
            "status": run["status"],
            "completed_item_count": counts["completed"],
            "failed_item_count": counts["failed"],
            "interrupted_item_count": counts["interrupted"] + counts["running"],
            "queued_item_count": counts["queued"],
            "remaining_item_count": retryable,
            "record_count": int(record_count),
            "blockers": blockers,
            "last_error": run.get("error"),
        }

    def _event(self, run_id: str, task_id: str, user_id: str, event_type: str, payload: dict[str, Any], *, ts: float | None = None) -> None:
        self.store.conn.execute(
            "insert into structured_extraction_run_events(run_id, task_id, user_id, event_type, payload_json, created_at) values(?, ?, ?, ?, ?, ?)",
            (run_id, task_id, user_id, event_type, dumps(payload), ts or now()),
        )

    @staticmethod
    def _row_to_run(row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "status": row["status"],
            "collection_version": row["collection_version"],
            "schema_version": row["schema_version"],
            "prompt_contract_version": row["prompt_contract_version"],
            "packet_version": row["packet_version"],
            "model_snapshot": loads(row["model_snapshot_json"], {}) or {},
            "stats": loads(row["stats_json"], {}) or {},
            "error": loads(row["error_json"], None) if row["error_json"] else None,
            "previous_task_status": row["previous_task_status"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "resume_count": row["resume_count"],
            "last_heartbeat_at": row["last_heartbeat_at"],
            "interrupted_at": row["interrupted_at"],
            "counted_at": row["counted_at"],
            "recovery": loads(row["recovery_json"], {}) or {},
            "core_job_id": row["core_job_id"] if "core_job_id" in row.keys() else None,
        }

    @staticmethod
    def _row_to_item(row) -> dict[str, Any]:
        return {
            "run_item_id": row["run_item_id"],
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "packet_item_id": row["packet_item_id"],
            "paper_id": row["paper_id"],
            "field_group": row["field_group"],
            "status": row["status"],
            "prompt": loads(row["prompt_json"], {}) or {},
            "raw_output": row["raw_output"],
            "parsed": loads(row["parsed_json"], None) if row["parsed_json"] else None,
            "error": loads(row["error_json"], None) if row["error_json"] else None,
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "attempt_count": row["attempt_count"],
            "last_attempt_at": row["last_attempt_at"],
        }

    @staticmethod
    def _row_to_record(row) -> dict[str, Any]:
        record = loads(row["record_json"], {}) or {}
        if record:
            return record
        return {
            "record_id": row["record_id"],
            "run_id": row["run_id"],
            "paper_id": row["paper_id"],
            "record_type": row["record_type"],
            "record_index": row["record_index"],
            "record_identity": loads(row["record_identity_json"], {}) or {},
            "data": loads(row["data_json"], {}) if "data_json" in row.keys() else {},
            "fields": loads(row["fields_json"], {}) or {},
            "source_packet_item_ids": loads(row["source_packet_item_ids_json"], []) or [],
            "quality_flags": loads(row["quality_flags_json"], []) or [],
            "created_at": row["created_at"],
        }


def _packet_item_from_row(row) -> dict[str, Any]:
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


def _sort_packet_items(items: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    if not is_nested_schema_mode(contract.get("schema_mode") or "flat_fields"):
        return items
    section_order = {
        section.get("section_key"): idx
        for idx, section in enumerate(contract.get("section_contracts") or [])
        if section.get("section_key")
    }
    return sorted(items, key=lambda item: (item.get("paper_id") or "", section_order.get(item.get("field_group"), 9999), item.get("packet_item_id") or ""))


def _normalize_item_records(parsed: dict[str, Any], packet_item: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = set(packet_item.get("field_keys") or [])
    field_contracts = {field.get("key"): field for field in (contract.get("field_contracts") or [])}
    identity_fields = (contract.get("record_contract") or {}).get("record_identity_fields") or ["paper_id"]
    schema_mode = contract.get("schema_mode") or "flat_fields"
    records = []
    for record in parsed.get("records") or []:
        paper_id = record.get("paper_id") or packet_item["paper_id"]
        identity_source = record.get("record_identity")
        if schema_mode == "nested_material":
            material_name = record.get("material_name") or (record.get("data") or {}).get("material_name")
            if isinstance(identity_source, dict):
                identity_source = {**identity_source, "material_name": identity_source.get("material_name") or material_name}
            elif material_name:
                identity_source = {"paper_id": paper_id, "material_name": material_name}
        identity, identity_flags = _normalize_record_identity(identity_source, identity_fields, paper_id)
        quality_flags = record.get("quality_flags") or []
        if not isinstance(quality_flags, list):
            quality_flags = [str(quality_flags)]
        data = {}
        fields = {}
        if is_nested_schema_mode(schema_mode):
            data = _normalize_nested_data(
                record.get("data") or record.get("fields") or {},
                packet_item.get("field_group"),
                identity_fields,
            )
            if any(not identity.get(field) for field in identity_fields if field != "paper_id"):
                quality_flags.append("missing_record_identity")
            fields = _top_level_fields(data)
        else:
            for key, value in (record.get("fields") or {}).items():
                if key not in allowed_keys:
                    continue
                fields[key] = _normalize_field_value(value, field_contracts.get(key) or {})
        records.append(
            {
                "paper_id": paper_id,
                "record_id": record.get("record_id"),
                "record_type": record.get("record_type") or (contract.get("record_contract") or {}).get("record_type"),
                "record_identity": identity,
                "data": data,
                "fields": fields,
                "source_packet_item_id": packet_item["packet_item_id"],
                "quality_flags": sorted(set(quality_flags + identity_flags)),
            }
        )
    return {"records": records}


def _normalize_nested_data(value: Any, section_key: str | None, identity_fields: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    excluded = {"paper_id", "paper_metadata", *identity_fields}
    data = {key: val for key, val in value.items() if key not in excluded}
    if section_key and section_key not in data and section_key not in excluded:
        section_value = dict(data)
        data = {section_key: section_value}
    return {key: val for key, val in data.items() if val is not None}


def _top_level_fields(data: dict[str, Any]) -> dict[str, Any]:
    return dict(data or {})


def _deep_merge(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in (incoming or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def _normalize_record_identity(value: Any, identity_fields: list[str], paper_id: str) -> tuple[dict[str, Any], list[str]]:
    if isinstance(value, dict):
        identity = dict(value)
        identity.setdefault("paper_id", paper_id)
        return identity, []
    if isinstance(value, list):
        identity = {"paper_id": paper_id}
        for field, item in zip(identity_fields, value):
            identity[field] = item
        identity.setdefault("paper_id", paper_id)
        return identity, ["invalid_record_identity_shape"]
    if value in (None, ""):
        return {"paper_id": paper_id}, []
    return {"paper_id": paper_id}, ["invalid_record_identity_shape"]


def _normalize_field_value(value: Any, field_contract: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        out = dict(value)
    else:
        out = {"raw_value": value}
    return {
        "raw_value": out.get("raw_value"),
        "normalized_value": out.get("normalized_value"),
        "unit": out.get("unit") or field_contract.get("unit") or "",
        "condition_context": out.get("condition_context"),
        "evidence_text": out.get("evidence_text"),
        "evidence_location": out.get("evidence_location"),
        "extraction_note": out.get("extraction_note"),
    }
