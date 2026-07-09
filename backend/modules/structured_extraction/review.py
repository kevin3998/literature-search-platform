from __future__ import annotations

from typing import Any

from core.memory_db import dumps, loads, now
from core.user_context import UserContext

from .artifacts import write_review_artifacts
from .schemas import ReviewBulkRequest, ReviewFieldActionRequest, ReviewFieldEditRequest
from .store import StructuredExtractionStore

FIELD_STATUSES = {"unreviewed", "accepted", "edited", "rejected", "rerun_required", "locked", "multimodal_pending"}
EVENT_TYPES = {
    "accept_field",
    "edit_field",
    "reject_field",
    "lock_field",
    "unlock_field",
    "mark_rerun_required",
    "revert_event",
    "multimodal_suggested",
    "accept_multimodal_suggestion",
    "reject_multimodal_suggestion",
    "bulk_accept_multimodal",
}
PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2}


class StructuredExtractionReviewService:
    def __init__(self, store: StructuredExtractionStore) -> None:
        self.store = store

    def list_runs(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select r.*
            from structured_extraction_runs r
            where r.task_id = ?
              and r.user_id = ?
              and r.status in ('completed', 'completed_with_errors')
              and exists(select 1 from structured_extraction_records rec where rec.run_id = r.run_id)
            order by r.completed_at desc, r.created_at desc
            """,
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "runs": [_row_to_run(row) for row in rows]}

    def table(
        self,
        task_id: str,
        *,
        user: UserContext,
        run_id: str | None = None,
        q: str | None = None,
        field_key: str | None = None,
        status: str | None = None,
        review_priority: str | None = None,
        quality_flag: str | None = None,
        missing: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        run = self._resolve_run(task_id, user=user, run_id=run_id)
        self._ensure_states(task_id, run["run_id"], user=user)
        rows = self._review_rows(task_id, run["run_id"], user=user)
        rows = [
            row
            for row in rows
            if _matches_filters(
                row,
                q=q,
                field_key=field_key,
                status=status,
                review_priority=review_priority,
                quality_flag=quality_flag,
                missing=missing,
            )
        ]
        total = len(rows)
        bounded_limit = max(1, min(int(limit or 100), 500))
        bounded_offset = max(0, int(offset or 0))
        page = rows[bounded_offset : bounded_offset + bounded_limit]
        self._write_artifacts(task_id, run["run_id"], user=user)
        return {
            "task_id": task_id,
            "run_id": run["run_id"],
            "total": total,
            "limit": bounded_limit,
            "offset": bounded_offset,
            "field_keys": [field["key"] for field in self._schema_fields(task_id, run["schema_version"], user=user)],
            "rows": page,
        }

    def record(self, task_id: str, record_id: str, *, user: UserContext, run_id: str | None = None) -> dict[str, Any]:
        run = self._resolve_run(task_id, user=user, run_id=run_id, record_id=record_id)
        self._ensure_states(task_id, run["run_id"], user=user)
        for row in self._review_rows(task_id, run["run_id"], user=user):
            if row["record_id"] == record_id:
                return row
        raise KeyError(f"review record not found: {record_id}")

    def events(self, task_id: str, record_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_review_events
            where task_id = ? and user_id = ? and record_id = ?
            order by created_at asc, event_id asc
            """,
            (task_id, user.user_id, record_id),
        ).fetchall()
        return {"task_id": task_id, "record_id": record_id, "events": [_row_to_event(row) for row in rows]}

    def accept_field(self, task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest, *, user: UserContext) -> dict[str, Any]:
        return self._apply_field_action(task_id, record_id, field_key, "accept_field", reason=payload.reason, user=user)

    def edit_field(self, task_id: str, record_id: str, field_key: str, payload: ReviewFieldEditRequest, *, user: UserContext) -> dict[str, Any]:
        value = _normalize_review_value(payload.value)
        return self._apply_field_action(task_id, record_id, field_key, "edit_field", value=value, reason=payload.reason, locked=payload.locked, user=user)

    def reject_field(self, task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest, *, user: UserContext) -> dict[str, Any]:
        return self._apply_field_action(task_id, record_id, field_key, "reject_field", value=None, reason=payload.reason, user=user)

    def lock_field(self, task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest, *, user: UserContext) -> dict[str, Any]:
        return self._apply_field_action(task_id, record_id, field_key, "lock_field", reason=payload.reason, locked=True, user=user)

    def unlock_field(self, task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest, *, user: UserContext) -> dict[str, Any]:
        return self._apply_field_action(task_id, record_id, field_key, "unlock_field", reason=payload.reason, locked=False, user=user)

    def revert_event(self, task_id: str, event_id: int, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        event = self.store.conn.execute(
            "select * from structured_extraction_review_events where task_id = ? and user_id = ? and event_id = ?",
            (task_id, user.user_id, event_id),
        ).fetchone()
        if not event:
            raise KeyError(f"review event not found: {event_id}")
        payload = loads(event["payload_json"], {}) or {}
        old_state = payload.get("old_state")
        if not old_state:
            raise ValueError("review_event_not_revertible")
        state = self._state_row(task_id, event["record_id"], event["field_key"], user=user)
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_review_field_states
            set effective_value_json = ?, status = ?, locked = ?, quality_flags_json = ?,
                review_priority = ?, last_event_id = null, updated_at = ?
            where task_id = ? and user_id = ? and run_id = ? and record_id = ? and field_key = ?
            """,
            (
                dumps(old_state.get("effective_value")) if old_state.get("effective_value") is not None else None,
                old_state.get("status") or "unreviewed",
                1 if old_state.get("locked") else 0,
                dumps(old_state.get("quality_flags") or []),
                old_state.get("review_priority") or "low",
                ts,
                task_id,
                user.user_id,
                event["run_id"],
                event["record_id"],
                event["field_key"],
            ),
        )
        cursor = self.store.conn.execute(
            """
            insert into structured_extraction_review_events(
                task_id, run_id, record_id, field_key, user_id, event_type, old_value_json,
                new_value_json, reason, locked, target_event_id, payload_json, created_at
            ) values(?, ?, ?, ?, ?, 'revert_event', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                event["run_id"],
                event["record_id"],
                event["field_key"],
                user.user_id,
                state["effective_value_json"],
                dumps(old_state.get("effective_value")) if old_state.get("effective_value") is not None else None,
                f"revert event {event_id}",
                1 if old_state.get("locked") else 0,
                event_id,
                dumps({"old_state": _state_snapshot(state), "restored_state": old_state}),
                ts,
            ),
        )
        new_event_id = cursor.lastrowid
        self.store.conn.execute(
            """
            update structured_extraction_review_field_states
            set last_event_id = ?
            where task_id = ? and user_id = ? and run_id = ? and record_id = ? and field_key = ?
            """,
            (new_event_id, task_id, user.user_id, event["run_id"], event["record_id"], event["field_key"]),
        )
        self.store.conn.commit()
        self._write_artifacts(task_id, event["run_id"], user=user)
        return self.record(task_id, event["record_id"], user=user, run_id=event["run_id"])

    def bulk(self, task_id: str, payload: ReviewBulkRequest, *, user: UserContext) -> dict[str, Any]:
        if payload.action not in {"accept_field", "reject_field", "lock_field", "unlock_field", "mark_rerun_required"}:
            raise ValueError("unsupported_review_bulk_action")
        updated = 0
        run_id: str | None = None
        for item in payload.items:
            record_id = item.get("record_id")
            field_key = item.get("field_key")
            if not record_id or not field_key:
                continue
            row = self._apply_field_action(task_id, record_id, field_key, payload.action, reason=payload.reason, user=user, commit=False)
            run_id = row["run_id"]
            updated += 1
        self.store.conn.commit()
        if run_id:
            self._write_artifacts(task_id, run_id, user=user)
        rows = self.table(task_id, user=user, run_id=run_id)["rows"] if run_id else []
        return {"task_id": task_id, "updated": updated, "rows": rows}

    def _apply_field_action(
        self,
        task_id: str,
        record_id: str,
        field_key: str,
        event_type: str,
        *,
        user: UserContext,
        value: dict[str, Any] | None = None,
        reason: str = "",
        locked: bool | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError("unsupported_review_event_type")
        state = self._state_row(task_id, record_id, field_key, user=user)
        old_snapshot = _state_snapshot(state)
        base_value = loads(state["base_value_json"], None)
        if event_type == "accept_field":
            next_value = base_value
            next_status = "accepted"
            next_locked = True
        elif event_type == "edit_field":
            next_value = value
            next_status = "edited"
            next_locked = True if locked is None else bool(locked)
        elif event_type == "reject_field":
            next_value = None
            next_status = "rejected"
            next_locked = True
        elif event_type == "lock_field":
            next_value = loads(state["effective_value_json"], None)
            next_status = "locked" if state["status"] == "unreviewed" else state["status"]
            next_locked = True
        elif event_type == "unlock_field":
            next_value = loads(state["effective_value_json"], None)
            next_status = "unreviewed" if state["status"] == "locked" else state["status"]
            next_locked = False
        else:
            next_value = loads(state["effective_value_json"], None)
            next_status = "rerun_required"
            next_locked = False
        ts = now()
        cursor = self.store.conn.execute(
            """
            insert into structured_extraction_review_events(
                task_id, run_id, record_id, field_key, user_id, event_type, old_value_json,
                new_value_json, reason, locked, payload_json, created_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                state["run_id"],
                record_id,
                field_key,
                user.user_id,
                event_type,
                state["effective_value_json"],
                dumps(next_value) if next_value is not None else None,
                reason or "",
                1 if next_locked else 0,
                dumps({"old_state": old_snapshot, "new_state": {"effective_value": next_value, "status": next_status, "locked": next_locked}}),
                ts,
            ),
        )
        event_id = cursor.lastrowid
        self.store.conn.execute(
            """
            update structured_extraction_review_field_states
            set effective_value_json = ?, status = ?, locked = ?, last_event_id = ?, updated_at = ?
            where task_id = ? and user_id = ? and run_id = ? and record_id = ? and field_key = ?
            """,
            (
                dumps(next_value) if next_value is not None else None,
                next_status,
                1 if next_locked else 0,
                event_id,
                ts,
                task_id,
                user.user_id,
                state["run_id"],
                record_id,
                field_key,
            ),
        )
        if commit:
            self.store.conn.commit()
            self._write_artifacts(task_id, state["run_id"], user=user)
        return self.record(task_id, record_id, user=user, run_id=state["run_id"])

    def _resolve_run(self, task_id: str, *, user: UserContext, run_id: str | None = None, record_id: str | None = None) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        params: list[Any] = [task_id, user.user_id]
        where = ["r.task_id = ?", "r.user_id = ?", "r.status in ('completed', 'completed_with_errors')"]
        if run_id:
            where.append("r.run_id = ?")
            params.append(run_id)
        if record_id:
            where.append("exists(select 1 from structured_extraction_records rec where rec.run_id = r.run_id and rec.record_id = ?)")
            params.append(record_id)
        else:
            where.append("exists(select 1 from structured_extraction_records rec where rec.run_id = r.run_id)")
        row = self.store.conn.execute(
            f"""
            select r.*
            from structured_extraction_runs r
            where {' and '.join(where)}
            order by r.completed_at desc, r.created_at desc
            limit 1
            """,
            params,
        ).fetchone()
        if not row:
            raise ValueError("review_run_required")
        return _row_to_run(row)

    def _ensure_states(self, task_id: str, run_id: str, *, user: UserContext) -> None:
        run = self._resolve_run(task_id, user=user, run_id=run_id)
        fields = self._schema_fields(task_id, run["schema_version"], user=user)
        records = self._base_records(task_id, run_id, user=user)
        ts = now()
        for record in records:
            base_fields = record.get("fields") or {}
            for field in fields:
                field_key = field["key"]
                exists = self.store.conn.execute(
                    """
                    select 1 from structured_extraction_review_field_states
                    where task_id = ? and user_id = ? and run_id = ? and record_id = ? and field_key = ?
                    """,
                    (task_id, user.user_id, run_id, record["record_id"], field_key),
                ).fetchone()
                if exists:
                    continue
                base_value = base_fields.get(field_key)
                flags, priority = _initial_quality(field, base_value)
                self.store.conn.execute(
                    """
                    insert into structured_extraction_review_field_states(
                        task_id, run_id, record_id, field_key, user_id, base_value_json, effective_value_json,
                        status, locked, quality_flags_json, review_priority, updated_at
                    ) values(?, ?, ?, ?, ?, ?, ?, 'unreviewed', 0, ?, ?, ?)
                    """,
                    (
                        task_id,
                        run_id,
                        record["record_id"],
                        field_key,
                        user.user_id,
                        dumps(base_value) if base_value is not None else None,
                        dumps(base_value) if base_value is not None else None,
                        dumps(flags),
                        priority,
                        ts,
                    ),
                )
        self.store.conn.commit()

    def _review_rows(self, task_id: str, run_id: str, *, user: UserContext) -> list[dict[str, Any]]:
        run = self._resolve_run(task_id, user=user, run_id=run_id)
        field_defs = {field["key"]: field for field in self._schema_fields(task_id, run["schema_version"], user=user)}
        paper_map = self._paper_map(task_id, run["collection_version"], user=user)
        records = self._base_records(task_id, run_id, user=user)
        states = self._states(task_id, run_id, user=user)
        by_record: dict[str, list[dict[str, Any]]] = {}
        for state in states:
            by_record.setdefault(state["record_id"], []).append(state)
        rows: list[dict[str, Any]] = []
        for record in records:
            fields: dict[str, Any] = {}
            field_priorities: list[str] = []
            statuses: list[str] = []
            for state in sorted(by_record.get(record["record_id"], []), key=lambda item: field_defs.get(item["field_key"], {}).get("order", 9999)):
                field = field_defs.get(state["field_key"], {"label": state["field_key"]})
                flags = loads(state["quality_flags_json"], []) or []
                priority = state["review_priority"] or "low"
                field_priorities.append(priority)
                statuses.append(state["status"])
                fields[state["field_key"]] = {
                    "field_key": state["field_key"],
                    "label": field.get("label") or state["field_key"],
                    "base_value": loads(state["base_value_json"], None),
                    "effective_value": loads(state["effective_value_json"], None),
                    "status": state["status"],
                    "locked": bool(state["locked"]),
                    "quality_flags": flags,
                    "review_priority": priority,
                    "provenance": loads(state["provenance_json"], {}) or {},
                    "last_event_id": state["last_event_id"],
                }
            record_flags = record.get("quality_flags") or []
            priority = _max_priority(field_priorities + [_priority_from_record_flags(record_flags)])
            rows.append(
                {
                    "record_id": record["record_id"],
                    "run_id": run_id,
                    "paper_id": record["paper_id"],
                    "paper": paper_map.get(record["paper_id"], {"paper_id": record["paper_id"]}),
                    "record_type": record.get("record_type"),
                    "record_index": record.get("record_index"),
                    "record_identity": record.get("record_identity") or {},
                    "data": _effective_data(fields, record.get("data") or {}),
                    "base_data": record.get("data") or {},
                    "fields": fields,
                    "record_quality_flags": record_flags,
                    "review_priority": priority,
                    "review_status": _review_status(statuses),
                }
            )
        return rows

    def _schema_fields(self, task_id: str, schema_version: str, *, user: UserContext) -> list[dict[str, Any]]:
        row = self.store.conn.execute(
            "select fields_json from structured_extraction_schema_versions where task_id = ? and user_id = ? and schema_version = ?",
            (task_id, user.user_id, schema_version),
        ).fetchone()
        if not row:
            raise ValueError("schema_version_not_found")
        return loads(row["fields_json"], []) or []

    def _paper_map(self, task_id: str, collection_version: str, *, user: UserContext) -> dict[str, dict[str, Any]]:
        rows = self.store.conn.execute(
            """
            select paper_id, paper_ref_json
            from structured_extraction_collection_papers
            where task_id = ? and collection_version = ?
            """,
            (task_id, collection_version),
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            ref = loads(row["paper_ref_json"], {}) or {}
            out[row["paper_id"]] = {
                "paper_id": row["paper_id"],
                "title": ref.get("title") or "",
                "year": ref.get("year"),
                "journal": ref.get("journal") or "",
                "doi": ref.get("doi") or "",
                **ref,
            }
        return out

    def _base_records(self, task_id: str, run_id: str, *, user: UserContext) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_records
            where task_id = ? and user_id = ? and run_id = ?
            order by paper_id asc, record_index asc, record_id asc
            """,
            (task_id, user.user_id, run_id),
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def _states(self, task_id: str, run_id: str, *, user: UserContext) -> list[Any]:
        return self.store.conn.execute(
            """
            select * from structured_extraction_review_field_states
            where task_id = ? and user_id = ? and run_id = ?
            order by record_id asc, field_key asc
            """,
            (task_id, user.user_id, run_id),
        ).fetchall()

    def _state_row(self, task_id: str, record_id: str, field_key: str, *, user: UserContext) -> Any:
        run = self._resolve_run(task_id, user=user, record_id=record_id)
        self._ensure_states(task_id, run["run_id"], user=user)
        row = self.store.conn.execute(
            """
            select * from structured_extraction_review_field_states
            where task_id = ? and user_id = ? and run_id = ? and record_id = ? and field_key = ?
            """,
            (task_id, user.user_id, run["run_id"], record_id, field_key),
        ).fetchone()
        if not row:
            raise KeyError(f"review field not found: {record_id}/{field_key}")
        return row

    def _write_artifacts(self, task_id: str, run_id: str, *, user: UserContext) -> None:
        events = self.events_for_run(task_id, run_id, user=user)
        states = [_row_to_state(row) for row in self._states(task_id, run_id, user=user)]
        effective_records = self.effective_records(task_id, run_id, user=user)
        write_review_artifacts(user, task_id, run_id, events, states, effective_records)

    def events_for_run(self, task_id: str, run_id: str, *, user: UserContext) -> list[dict[str, Any]]:
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_review_events
            where task_id = ? and user_id = ? and run_id = ?
            order by created_at asc, event_id asc
            """,
            (task_id, user.user_id, run_id),
        ).fetchall()
        return [_row_to_event(row) for row in rows]

    def effective_records(self, task_id: str, run_id: str, *, user: UserContext) -> list[dict[str, Any]]:
        rows = self._review_rows(task_id, run_id, user=user)
        out = []
        for row in rows:
            out.append(
                {
                    "record_id": row["record_id"],
                    "run_id": row["run_id"],
                    "paper_id": row["paper_id"],
                    "record_type": row["record_type"],
                    "record_index": row["record_index"],
                    "record_identity": row["record_identity"],
                    "data": _effective_data(row["fields"], {}),
                    "fields": {key: value.get("effective_value") for key, value in row["fields"].items() if value.get("status") != "rejected"},
                    "review_priority": row["review_priority"],
                    "review_status": row["review_status"],
                    "record_quality_flags": row["record_quality_flags"],
                }
            )
        return out


def _initial_quality(field: dict[str, Any], value: Any) -> tuple[list[str], str]:
    flags: list[str] = []
    priority = "low"
    missing = _is_missing_value(value)
    if field.get("required") and missing:
        flags.append("missing_required_field")
        priority = "high"
    if field.get("evidence_required") and not missing:
        evidence_text = value.get("evidence_text") if isinstance(value, dict) else None
        evidence_location = value.get("evidence_location") if isinstance(value, dict) else None
        if not evidence_text and not evidence_location:
            flags.append("no_evidence")
            priority = _max_priority([priority, "medium"])
        else:
            flags.append("evidence_found")
    return flags, priority


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        if any(key in value for key in ("raw_value", "rawValue", "normalized_value", "normalizedValue")):
            raw = value.get("raw_value") if "raw_value" in value else value.get("rawValue")
            normalized = value.get("normalized_value") if "normalized_value" in value else value.get("normalizedValue")
            return raw in (None, "") and normalized in (None, "")
        return not bool(value)
    if isinstance(value, list):
        return not bool(value)
    return value == ""


def _effective_data(fields: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    data = dict(fallback or {})
    for key, field in (fields or {}).items():
        if field.get("status") == "rejected":
            data.pop(key, None)
        else:
            data[key] = field.get("effective_value")
    return data


def _matches_filters(
    row: dict[str, Any],
    *,
    q: str | None,
    field_key: str | None,
    status: str | None,
    review_priority: str | None,
    quality_flag: str | None,
    missing: bool | None,
) -> bool:
    if q:
        needle = q.strip().lower()
        haystack = " ".join(
            [
                str(row.get("paper_id") or ""),
                str((row.get("paper") or {}).get("title") or ""),
                str((row.get("paper") or {}).get("doi") or ""),
                str(row.get("record_identity") or ""),
            ]
        ).lower()
        if needle not in haystack:
            return False
    fields = row.get("fields") or {}
    selected = {field_key: fields.get(field_key)} if field_key else fields
    selected = {key: value for key, value in selected.items() if value}
    if status and not any(value.get("status") == status for value in selected.values()):
        return False
    if review_priority and not any(value.get("review_priority") == review_priority for value in selected.values()):
        return False
    if quality_flag and not any(quality_flag in (value.get("quality_flags") or []) for value in selected.values()):
        return False
    if missing is not None:
        has_missing = any(_is_missing_value(value.get("effective_value")) for value in selected.values())
        if bool(missing) != has_missing:
            return False
    return True


def _max_priority(values: list[str]) -> str:
    best = "low"
    for value in values:
        if PRIORITY_RANK.get(value or "low", 0) > PRIORITY_RANK[best]:
            best = value
    return best


def _priority_from_record_flags(flags: list[str]) -> str:
    if any(flag in {"missing_required_field", "value_conflict_detected", "extraction_error", "invalid_json"} for flag in flags):
        return "high"
    if any(flag in {"no_evidence", "ambiguous_value", "condition_context_missing"} for flag in flags):
        return "medium"
    return "low"


def _review_status(statuses: list[str]) -> str:
    if not statuses or all(status == "unreviewed" for status in statuses):
        return "unreviewed"
    if any(status == "multimodal_pending" for status in statuses):
        return "multimodal_pending"
    if all(status in {"accepted", "edited", "rejected", "locked"} for status in statuses):
        return "reviewed"
    return "partially_reviewed"


def _state_snapshot(row) -> dict[str, Any]:
    return {
        "base_value": loads(row["base_value_json"], None),
        "effective_value": loads(row["effective_value_json"], None),
        "status": row["status"],
        "locked": bool(row["locked"]),
        "quality_flags": loads(row["quality_flags_json"], []) or [],
        "review_priority": row["review_priority"],
        "provenance": loads(row["provenance_json"], {}) or {},
        "last_event_id": row["last_event_id"],
    }


def _normalize_review_value(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"raw_value": value}
    value_shape_keys = {"raw_value", "rawValue", "normalized_value", "normalizedValue", "unit", "condition_context", "conditionContext", "evidence_text", "evidenceText", "evidence_location", "evidenceLocation", "extraction_note", "extractionNote"}
    if not any(key in value for key in value_shape_keys):
        return value
    return {
        "raw_value": value.get("raw_value"),
        "normalized_value": value.get("normalized_value"),
        "unit": value.get("unit") or "",
        "condition_context": value.get("condition_context"),
        "evidence_text": value.get("evidence_text"),
        "evidence_location": value.get("evidence_location"),
        "extraction_note": value.get("extraction_note"),
    }


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
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


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
        "fields": loads(row["fields_json"], {}) or {},
        "source_packet_item_ids": loads(row["source_packet_item_ids_json"], []) or [],
        "quality_flags": loads(row["quality_flags_json"], []) or [],
        "created_at": row["created_at"],
    }


def _row_to_event(row) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "task_id": row["task_id"],
        "run_id": row["run_id"],
        "record_id": row["record_id"],
        "field_key": row["field_key"],
        "event_type": row["event_type"],
        "old_value": loads(row["old_value_json"], None),
        "new_value": loads(row["new_value_json"], None),
        "reason": row["reason"],
        "locked": bool(row["locked"]),
        "target_event_id": row["target_event_id"],
        "payload": loads(row["payload_json"], {}) or {},
        "created_at": row["created_at"],
    }


def _row_to_state(row) -> dict[str, Any]:
    return {
        "task_id": row["task_id"],
        "run_id": row["run_id"],
        "record_id": row["record_id"],
        "field_key": row["field_key"],
        **_state_snapshot(row),
        "updated_at": row["updated_at"],
    }
