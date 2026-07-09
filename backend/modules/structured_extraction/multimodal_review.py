from __future__ import annotations

import threading
import uuid
from typing import Any

from core.memory_db import dumps, loads, now
from core.settings_store import settings_store
from core.user_context import UserContext

from .artifacts import write_multimodal_review_artifacts
from .review import StructuredExtractionReviewService, _is_missing_value, _priority_from_record_flags
from .schemas import MultimodalReviewJobCreateRequest, ReviewSuggestionActionRequest, ReviewSuggestionBulkRequest
from .store import StructuredExtractionStore

JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelling", "cancelled", "interrupted"}
ACTIVE_JOB_STATUSES = {"queued", "running", "cancelling"}
SCAN_MODES = {"evidence_only", "related_pages_assets", "full_document"}
SUGGESTION_ACTIONS = {"suggest_add", "suggest_edit", "flag_issue", "mark_coverage"}


class StructuredExtractionMultimodalReviewService:
    def __init__(self, store: StructuredExtractionStore, review: StructuredExtractionReviewService) -> None:
        self.store = store
        self.review = review

    def summary(self, task_id: str, *, user: UserContext, run_id: str | None = None) -> dict[str, Any]:
        run = self.review._resolve_run(task_id, user=user, run_id=run_id)  # noqa: SLF001
        rows = self._rows(task_id, run["run_id"], user=user)
        suggestions = self._suggestions(task_id, run["run_id"], user=user)
        summary = _summary_from_rows(task_id, run["run_id"], rows, suggestions, multimodal_ready=self._model_ready()["ready"])
        self._write_artifacts(task_id, run["run_id"], user=user, summary=summary)
        return summary

    def queue(
        self,
        task_id: str,
        *,
        user: UserContext,
        run_id: str | None = None,
        queue: str = "all",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        run = self.review._resolve_run(task_id, user=user, run_id=run_id)  # noqa: SLF001
        rows = self._decorated_rows(task_id, run["run_id"], user=user)
        filtered = [_row for _row in rows if _queue_match(_row, queue)]
        bounded_limit = max(1, min(int(limit or 100), 500))
        bounded_offset = max(0, int(offset or 0))
        return {
            "task_id": task_id,
            "run_id": run["run_id"],
            "queue": queue,
            "total": len(filtered),
            "limit": bounded_limit,
            "offset": bounded_offset,
            "rows": filtered[bounded_offset : bounded_offset + bounded_limit],
        }

    def start_job(self, task_id: str, run_id: str, payload: MultimodalReviewJobCreateRequest, *, user: UserContext) -> dict[str, Any]:
        ready = self._model_ready()
        if not ready["ready"]:
            raise ValueError("multimodal_model_not_configured")
        run = self.review._resolve_run(task_id, user=user, run_id=run_id)  # noqa: SLF001
        rows = self._rows(task_id, run["run_id"], user=user)
        if not rows:
            raise ValueError("review_records_required")
        active = self.store.conn.execute(
            """
            select * from structured_extraction_multimodal_review_jobs
            where task_id = ? and user_id = ? and run_id = ? and status in ('queued', 'running', 'cancelling')
            order by created_at desc
            limit 1
            """,
            (task_id, user.user_id, run["run_id"]),
        ).fetchone()
        if active:
            return self.get_job(task_id, active["job_id"], user=user)
        scan_mode = payload.scan_mode or ready["default_scan_mode"]
        if scan_mode not in SCAN_MODES:
            raise ValueError("unsupported_multimodal_scan_mode")
        ts = now()
        job_id = f"mmr_{uuid.uuid4().hex[:12]}"
        total = sum(max(1, len(row.get("fields") or {})) for row in rows)
        self.store.conn.execute(
            """
            insert into structured_extraction_multimodal_review_jobs(
                job_id, task_id, run_id, user_id, status, scan_mode, reason, model_snapshot_json,
                total_item_count, processed_item_count, suggestion_count, issue_count, warnings_json,
                created_at, updated_at
            ) values(?, ?, ?, ?, 'queued', ?, ?, ?, ?, 0, 0, 0, '[]', ?, ?)
            """,
            (job_id, task_id, run["run_id"], user.user_id, scan_mode, payload.reason or "", dumps(ready["model_snapshot"]), total, ts, ts),
        )
        self.store.conn.commit()
        thread = threading.Thread(target=self._run_job, args=(task_id, run["run_id"], job_id, user), daemon=True)
        thread.start()
        return self.get_job(task_id, job_id, user=user)

    def list_jobs(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        self.review._resolve_run(task_id, user=user, run_id=run_id)  # noqa: SLF001
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_multimodal_review_jobs
            where task_id = ? and user_id = ? and run_id = ?
            order by created_at desc
            """,
            (task_id, user.user_id, run_id),
        ).fetchall()
        return {"task_id": task_id, "run_id": run_id, "jobs": [_row_to_job(row) for row in rows]}

    def get_job(self, task_id: str, job_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            "select * from structured_extraction_multimodal_review_jobs where task_id = ? and user_id = ? and job_id = ?",
            (task_id, user.user_id, job_id),
        ).fetchone()
        if not row:
            raise KeyError(f"multimodal review job not found: {job_id}")
        job = _row_to_job(row)
        suggestions = self._suggestions(task_id, job["run_id"], user=user, job_id=job_id)
        job["suggestions"] = suggestions
        job["suggestions_preview"] = suggestions[:10]
        return job

    def cancel_job(self, task_id: str, job_id: str, *, user: UserContext) -> dict[str, Any]:
        job = self.get_job(task_id, job_id, user=user)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_multimodal_review_jobs
            set status = 'cancelling', updated_at = ?
            where task_id = ? and user_id = ? and job_id = ?
            """,
            (ts, task_id, user.user_id, job_id),
        )
        self.store.conn.commit()
        return self.get_job(task_id, job_id, user=user)

    def accept_suggestion(self, task_id: str, suggestion_id: str, payload: ReviewSuggestionActionRequest, *, user: UserContext) -> dict[str, Any]:
        suggestion = self._suggestion(task_id, suggestion_id, user=user)
        if suggestion["status"] != "pending":
            return {"suggestion": suggestion, "record": self.review.record(task_id, suggestion["record_id"], run_id=suggestion["run_id"], user=user)}
        state = self.review._state_row(task_id, suggestion["record_id"], suggestion["field_key"], user=user)  # noqa: SLF001
        old_value = loads(state["effective_value_json"], None)
        next_value = suggestion.get("suggested_value")
        if next_value is None:
            next_value = old_value
        provenance = suggestion.get("provenance") or {}
        ts = now()
        cursor = self.store.conn.execute(
            """
            insert into structured_extraction_review_events(
                task_id, run_id, record_id, field_key, user_id, event_type, old_value_json,
                new_value_json, reason, locked, payload_json, created_at
            ) values(?, ?, ?, ?, ?, 'accept_multimodal_suggestion', ?, ?, ?, 0, ?, ?)
            """,
            (
                task_id,
                suggestion["run_id"],
                suggestion["record_id"],
                suggestion["field_key"],
                user.user_id,
                state["effective_value_json"],
                dumps(next_value) if next_value is not None else None,
                payload.reason or "accept multimodal suggestion",
                dumps({"suggestion_id": suggestion_id, "provenance": provenance}),
                ts,
            ),
        )
        event_id = cursor.lastrowid
        self.store.conn.execute(
            """
            update structured_extraction_review_field_states
            set effective_value_json = ?, status = 'multimodal_pending', locked = 0,
                provenance_json = ?, last_event_id = ?, updated_at = ?
            where task_id = ? and user_id = ? and run_id = ? and record_id = ? and field_key = ?
            """,
            (
                dumps(next_value) if next_value is not None else None,
                dumps(provenance),
                event_id,
                ts,
                task_id,
                user.user_id,
                suggestion["run_id"],
                suggestion["record_id"],
                suggestion["field_key"],
            ),
        )
        self.store.conn.execute(
            "update structured_extraction_multimodal_review_suggestions set status = 'accepted', reason = ?, resolved_at = ? where suggestion_id = ?",
            (payload.reason or "", ts, suggestion_id),
        )
        self.store.conn.commit()
        self.review._write_artifacts(task_id, suggestion["run_id"], user=user)  # noqa: SLF001
        self._write_artifacts(task_id, suggestion["run_id"], user=user)
        return {
            "suggestion": self._suggestion(task_id, suggestion_id, user=user),
            "record": self.review.record(task_id, suggestion["record_id"], run_id=suggestion["run_id"], user=user),
        }

    def reject_suggestion(self, task_id: str, suggestion_id: str, payload: ReviewSuggestionActionRequest, *, user: UserContext) -> dict[str, Any]:
        suggestion = self._suggestion(task_id, suggestion_id, user=user)
        if suggestion["status"] == "pending":
            ts = now()
            self.store.conn.execute(
                """
                insert into structured_extraction_review_events(
                    task_id, run_id, record_id, field_key, user_id, event_type, reason, payload_json, created_at
                ) values(?, ?, ?, ?, ?, 'reject_multimodal_suggestion', ?, ?, ?)
                """,
                (
                    task_id,
                    suggestion["run_id"],
                    suggestion["record_id"],
                    suggestion["field_key"],
                    user.user_id,
                    payload.reason or "reject multimodal suggestion",
                    dumps({"suggestion_id": suggestion_id, "provenance": suggestion.get("provenance") or {}}),
                    ts,
                ),
            )
            self.store.conn.execute(
                "update structured_extraction_multimodal_review_suggestions set status = 'rejected', reason = ?, resolved_at = ? where suggestion_id = ?",
                (payload.reason or "", ts, suggestion_id),
            )
            self.store.conn.commit()
            self.review._write_artifacts(task_id, suggestion["run_id"], user=user)  # noqa: SLF001
            self._write_artifacts(task_id, suggestion["run_id"], user=user)
        return {"suggestion": self._suggestion(task_id, suggestion_id, user=user)}

    def bulk_suggestions(self, task_id: str, payload: ReviewSuggestionBulkRequest, *, user: UserContext) -> dict[str, Any]:
        updated = 0
        out = []
        for suggestion_id in payload.suggestion_ids:
            if payload.action == "accept":
                result = self.accept_suggestion(task_id, suggestion_id, ReviewSuggestionActionRequest(reason=payload.reason), user=user)
            else:
                result = self.reject_suggestion(task_id, suggestion_id, ReviewSuggestionActionRequest(reason=payload.reason), user=user)
            out.append(result["suggestion"])
            updated += 1
        return {"task_id": task_id, "updated": updated, "suggestions": out}

    def provenance_summary(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        job_count = self.store.conn.execute(
            "select count(*) as c from structured_extraction_multimodal_review_jobs where task_id = ? and user_id = ? and run_id = ?",
            (task_id, user.user_id, run_id),
        ).fetchone()["c"]
        rows = self.store.conn.execute(
            """
            select status, count(*) as c
            from structured_extraction_multimodal_review_suggestions
            where task_id = ? and user_id = ? and run_id = ?
            group by status
            """,
            (task_id, user.user_id, run_id),
        ).fetchall()
        return {"job_count": job_count, "suggestion_status_counts": {row["status"]: row["c"] for row in rows}}

    def _run_job(self, task_id: str, run_id: str, job_id: str, user: UserContext) -> None:
        ts = now()
        self.store.conn.execute(
            "update structured_extraction_multimodal_review_jobs set status = 'running', started_at = ?, updated_at = ? where job_id = ?",
            (ts, ts, job_id),
        )
        self.store.conn.commit()
        try:
            rows = self._rows(task_id, run_id, user=user)
            processed = 0
            suggestion_count = 0
            issue_count = 0
            for row in rows:
                for field_key, field in (row.get("fields") or {}).items():
                    current = self.store.conn.execute("select status from structured_extraction_multimodal_review_jobs where job_id = ?", (job_id,)).fetchone()
                    if current and current["status"] == "cancelling":
                        done = now()
                        self.store.conn.execute(
                            "update structured_extraction_multimodal_review_jobs set status = 'cancelled', updated_at = ?, completed_at = ? where job_id = ?",
                            (done, done, job_id),
                        )
                        self.store.conn.commit()
                        self._write_artifacts(task_id, run_id, user=user)
                        return
                    processed += 1
                    flags = field.get("quality_flags") or []
                    missing = _is_missing_value(field.get("effective_value"))
                    action = None
                    issue_type = None
                    risk = "medium"
                    coverage = "not_reported" if missing else "reported"
                    if "missing_required_field" in flags:
                        action = "flag_issue"
                        issue_type = "missing_required_field"
                        risk = "high"
                        coverage = "possibly_missed"
                    elif "no_evidence" in flags:
                        action = "suggest_edit"
                        issue_type = "evidence_alignment_unclear"
                    if action:
                        suggestion_count += 1
                        if action == "flag_issue":
                            issue_count += 1
                        self._insert_suggestion(job_id, task_id, run_id, user=user, row=row, field_key=field_key, field=field, action=action, risk=risk, coverage=coverage, issue_type=issue_type)
                    updated = now()
                    self.store.conn.execute(
                        """
                        update structured_extraction_multimodal_review_jobs
                        set processed_item_count = ?, suggestion_count = ?, issue_count = ?,
                            current_paper_id = ?, current_record_id = ?, current_section = ?, updated_at = ?
                        where job_id = ?
                        """,
                        (processed, suggestion_count, issue_count, row.get("paper_id"), row.get("record_id"), field_key, updated, job_id),
                    )
                    self.store.conn.commit()
            done = now()
            self.store.conn.execute(
                """
                update structured_extraction_multimodal_review_jobs
                set status = 'completed', processed_item_count = total_item_count,
                    suggestion_count = ?, issue_count = ?, updated_at = ?, completed_at = ?
                where job_id = ?
                """,
                (suggestion_count, issue_count, done, done, job_id),
            )
            self.store.conn.commit()
            self._write_artifacts(task_id, run_id, user=user)
        except Exception as exc:  # noqa: BLE001
            done = now()
            self.store.conn.execute(
                "update structured_extraction_multimodal_review_jobs set status = 'failed', error_json = ?, updated_at = ?, completed_at = ? where job_id = ?",
                (dumps({"detail": str(exc)}), done, done, job_id),
            )
            self.store.conn.commit()

    def _insert_suggestion(
        self,
        job_id: str,
        task_id: str,
        run_id: str,
        *,
        user: UserContext,
        row: dict[str, Any],
        field_key: str,
        field: dict[str, Any],
        action: str,
        risk: str,
        coverage: str,
        issue_type: str | None,
    ) -> None:
        suggestion_id = f"mms_{uuid.uuid4().hex[:12]}"
        current_value = field.get("effective_value")
        evidence = _evidence_from_value(current_value)
        provenance = {
            "source": "multimodal",
            "job_id": job_id,
            "model": self._model_ready()["model_snapshot"].get("model") or "",
            "evidence_type": evidence.get("evidence_type") or "text",
            "evidence_location": evidence.get("evidence_location") or "",
            "confidence": "medium",
        }
        self.store.conn.execute(
            """
            insert into structured_extraction_multimodal_review_suggestions(
                suggestion_id, job_id, task_id, run_id, record_id, field_key, user_id, action,
                status, risk_level, coverage_status, issue_type, suggested_value_json,
                current_value_json, evidence_json, provenance_json, created_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suggestion_id,
                job_id,
                task_id,
                run_id,
                row.get("record_id"),
                field_key,
                user.user_id,
                action,
                risk,
                coverage,
                issue_type,
                dumps(current_value) if current_value is not None else None,
                dumps(current_value) if current_value is not None else None,
                dumps(evidence),
                dumps(provenance),
                now(),
            ),
        )

    def _rows(self, task_id: str, run_id: str, *, user: UserContext) -> list[dict[str, Any]]:
        self.review._ensure_states(task_id, run_id, user=user)  # noqa: SLF001
        return self.review._review_rows(task_id, run_id, user=user)  # noqa: SLF001

    def _decorated_rows(self, task_id: str, run_id: str, *, user: UserContext) -> list[dict[str, Any]]:
        rows = self._rows(task_id, run_id, user=user)
        suggestions = self._suggestions(task_id, run_id, user=user)
        by_record: dict[str, list[dict[str, Any]]] = {}
        for suggestion in suggestions:
            by_record.setdefault(suggestion["record_id"], []).append(suggestion)
        out = []
        for row in rows:
            row_suggestions = by_record.get(row["record_id"], [])
            coverage = _coverage_for_row(row, row_suggestions)
            risk = _risk_for_row(row, row_suggestions)
            issues = [suggestion for suggestion in row_suggestions if suggestion.get("action") == "flag_issue"]
            out.append(
                {
                    **row,
                    "coverage": coverage,
                    "risk_level": risk,
                    "issues": issues,
                    "suggestions": row_suggestions,
                    "bulk_accept_eligible": risk == "low" and not any(s.get("status") == "pending" for s in row_suggestions),
                }
            )
        return out

    def _suggestions(self, task_id: str, run_id: str, *, user: UserContext, job_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [task_id, user.user_id, run_id]
        where = ["task_id = ?", "user_id = ?", "run_id = ?"]
        if job_id:
            where.append("job_id = ?")
            params.append(job_id)
        rows = self.store.conn.execute(
            f"select * from structured_extraction_multimodal_review_suggestions where {' and '.join(where)} order by created_at asc",
            params,
        ).fetchall()
        return [_row_to_suggestion(row) for row in rows]

    def _suggestion(self, task_id: str, suggestion_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            "select * from structured_extraction_multimodal_review_suggestions where task_id = ? and user_id = ? and suggestion_id = ?",
            (task_id, user.user_id, suggestion_id),
        ).fetchone()
        if not row:
            raise KeyError(f"multimodal suggestion not found: {suggestion_id}")
        return _row_to_suggestion(row)

    def _model_ready(self) -> dict[str, Any]:
        config = settings_store.model_config()
        enabled = bool(settings_store.value("models", "multimodal_enabled"))
        profile_id = str(settings_store.value("models", "multimodal_profile_id") or "")
        profile: dict[str, Any] | None = None
        if profile_id:
            try:
                from core.model_profiles import model_profile_store

                profile = model_profile_store.get(profile_id)
            except Exception:  # noqa: BLE001
                profile = None
        provider = (profile or {}).get("provider") or config.get("provider") or ""
        model = str(settings_store.value("models", "multimodal_model") or (profile or {}).get("model") or config.get("strong_model") or config.get("chat_model") or "")
        default_scan = str(settings_store.value("models", "multimodal_scan_default") or "related_pages_assets")
        return {
            "ready": bool(enabled and model),
            "default_scan_mode": default_scan if default_scan in SCAN_MODES else "related_pages_assets",
            "model_snapshot": {
                "provider": provider,
                "model": model,
                "base_url": (profile or {}).get("base_url") or config.get("base_url") or "",
                "multimodal_profile_id": profile_id,
            },
        }

    def _write_artifacts(self, task_id: str, run_id: str, *, user: UserContext, summary: dict[str, Any] | None = None) -> None:
        jobs = self.list_jobs(task_id, run_id, user=user)["jobs"]
        suggestions = self._suggestions(task_id, run_id, user=user)
        if summary is None:
            rows = self._rows(task_id, run_id, user=user)
            summary = _summary_from_rows(task_id, run_id, rows, suggestions, multimodal_ready=self._model_ready()["ready"])
        write_multimodal_review_artifacts(user, task_id, run_id, jobs, suggestions, summary)


def _summary_from_rows(task_id: str, run_id: str, rows: list[dict[str, Any]], suggestions: list[dict[str, Any]], *, multimodal_ready: bool) -> dict[str, Any]:
    decorated = []
    by_record: dict[str, list[dict[str, Any]]] = {}
    for suggestion in suggestions:
        by_record.setdefault(suggestion["record_id"], []).append(suggestion)
    risk_counts: dict[str, int] = {}
    coverage_counts: dict[str, int] = {}
    pending = 0
    eligible = 0
    for row in rows:
        row_suggestions = by_record.get(row["record_id"], [])
        coverage = _coverage_for_row(row, row_suggestions)
        risk = _risk_for_row(row, row_suggestions)
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
        for value in coverage.values():
            coverage_counts[value] = coverage_counts.get(value, 0) + 1
        if any(suggestion.get("status") == "pending" for suggestion in row_suggestions):
            pending += 1
        if risk == "low" and not any(suggestion.get("status") == "pending" for suggestion in row_suggestions):
            eligible += 1
        decorated.append({"record_id": row["record_id"], "risk_level": risk, "coverage": coverage})
    return {
        "task_id": task_id,
        "run_id": run_id,
        "record_count": len(rows),
        "risk_counts": risk_counts,
        "coverage_counts": coverage_counts,
        "pending_suggestion_count": pending,
        "bulk_accept_eligible_count": eligible,
        "multimodal_ready": multimodal_ready,
        "records": decorated,
    }


def _coverage_for_row(row: dict[str, Any], suggestions: list[dict[str, Any]]) -> dict[str, str]:
    coverage: dict[str, str] = {}
    for key, field in (row.get("fields") or {}).items():
        coverage[key] = "not_reported" if _is_missing_value(field.get("effective_value")) else "reported"
    for suggestion in suggestions:
        if suggestion.get("coverage_status"):
            coverage[suggestion["field_key"]] = suggestion["coverage_status"]
    return coverage


def _risk_for_row(row: dict[str, Any], suggestions: list[dict[str, Any]]) -> str:
    ranks = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    risk = _priority_from_record_flags(row.get("record_quality_flags") or [])
    if not _identity_valid(row.get("record_identity") or {}):
        risk = "high"
    for field in (row.get("fields") or {}).values():
        flags = field.get("quality_flags") or []
        if "missing_required_field" in flags:
            risk = "high"
        elif "no_evidence" in flags and ranks[risk] < ranks["medium"]:
            risk = "medium"
    for suggestion in suggestions:
        if suggestion.get("status") == "pending":
            level = suggestion.get("risk_level") or "medium"
            if ranks[level] > ranks[risk]:
                risk = level
    return risk


def _identity_valid(identity: dict[str, Any]) -> bool:
    non_paper = [value for key, value in identity.items() if key != "paper_id" and value not in (None, "")]
    return bool(non_paper)


def _queue_match(row: dict[str, Any], queue: str) -> bool:
    if queue in {"", "all", "全部材料"}:
        return True
    if queue == "high_risk":
        return row.get("risk_level") in {"high", "critical"}
    if queue == "multimodal_pending":
        return any(suggestion.get("status") == "pending" for suggestion in row.get("suggestions") or [])
    if queue == "possibly_missed":
        return any(value == "possibly_missed" for value in (row.get("coverage") or {}).values())
    if queue == "sample":
        return row.get("bulk_accept_eligible")
    if queue == "completed":
        return row.get("review_status") in {"reviewed", "completed"}
    return True


def _evidence_from_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        location = value.get("evidence_location") or value.get("evidenceLocation") or ""
        text = value.get("evidence_text") or value.get("evidenceText") or ""
        return {"evidence_type": "text", "evidence_location": location, "evidence_text": text}
    return {"evidence_type": "text"}


def _row_to_job(row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "task_id": row["task_id"],
        "run_id": row["run_id"],
        "status": row["status"],
        "scan_mode": row["scan_mode"],
        "reason": row["reason"],
        "model_snapshot": loads(row["model_snapshot_json"], {}) or {},
        "total_item_count": row["total_item_count"],
        "processed_item_count": row["processed_item_count"],
        "suggestion_count": row["suggestion_count"],
        "issue_count": row["issue_count"],
        "current_paper_id": row["current_paper_id"],
        "current_record_id": row["current_record_id"],
        "current_section": row["current_section"],
        "warnings": loads(row["warnings_json"], []) or [],
        "error": loads(row["error_json"], None) if row["error_json"] else None,
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def _row_to_suggestion(row) -> dict[str, Any]:
    return {
        "suggestion_id": row["suggestion_id"],
        "job_id": row["job_id"],
        "task_id": row["task_id"],
        "run_id": row["run_id"],
        "record_id": row["record_id"],
        "field_key": row["field_key"],
        "action": row["action"],
        "status": row["status"],
        "risk_level": row["risk_level"],
        "coverage_status": row["coverage_status"],
        "issue_type": row["issue_type"],
        "suggested_value": loads(row["suggested_value_json"], None),
        "current_value": loads(row["current_value_json"], None),
        "evidence": loads(row["evidence_json"], {}) or {},
        "provenance": loads(row["provenance_json"], {}) or {},
        "reason": row["reason"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }
