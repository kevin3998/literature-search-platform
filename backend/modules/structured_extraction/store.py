from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from core.memory_db import connect, dumps, loads, memory_db_path, now
from core.user_context import DEFAULT_USER_ID, UserContext

from .artifacts import ensure_task_workspace, task_workspace_rel_path, write_task_manifest
from .schemas import DEFAULT_TASK_STATS, ExtractionTask, TaskStatus

_HIDDEN_STATUSES = ("deleted",)


class StructuredExtractionStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path
        self._local = threading.local()

    @property
    def conn(self):
        conn = getattr(self._local, "conn", None)
        current_path = str(memory_db_path(self.db_path))
        conn_path = getattr(self._local, "conn_path", None)
        if conn is None or conn_path != current_path:
            if conn is not None:
                conn.close()
            conn = connect(self.db_path)
            self._local.conn = conn
            self._local.conn_path = current_path
        return conn

    def create_task(
        self,
        *,
        name: str,
        description: str = "",
        user: UserContext | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = user or UserContext(DEFAULT_USER_ID, DEFAULT_USER_ID)
        task_id = f"ext_{uuid.uuid4().hex[:12]}"
        ts = now()
        stats = dict(DEFAULT_TASK_STATS)
        self.conn.execute(
            """
            insert into structured_extraction_tasks(
                task_id, user_id, name, description, status, workspace_rel_path,
                model_settings_json, stats_json, archived, created_at, updated_at
            ) values(?, ?, ?, ?, 'draft', ?, ?, ?, 0, ?, ?)
            """,
            (
                task_id,
                ctx.user_id,
                _clean_name(name),
                description or "",
                task_workspace_rel_path(task_id),
                dumps(model_settings or {}),
                dumps(stats),
                ts,
                ts,
            ),
        )
        self._insert_event(task_id, ctx.user_id, "created", {"name": name})
        self.conn.commit()
        task = self.get_task(task_id, user_id=ctx.user_id)
        ensure_task_workspace(ctx, task)
        return task

    def list_tasks(self, *, include_archived: bool = False, limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ["status not in (?)"]
        params.extend(_HIDDEN_STATUSES)
        if not include_archived:
            where.append("archived = 0")
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        params.append(max(1, min(int(limit or 100), 500)))
        rows = self.conn.execute(
            f"select * from structured_extraction_tasks where {' and '.join(where)} order by updated_at desc limit ?",
            params,
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            row = self.conn.execute("select * from structured_extraction_tasks where task_id = ?", (task_id,)).fetchone()
        else:
            row = self.conn.execute(
                "select * from structured_extraction_tasks where task_id = ? and user_id = ?",
                (task_id, user_id),
            ).fetchone()
        if not row or row["status"] == "deleted":
            raise KeyError(f"structured extraction task not found: {task_id}")
        return self._row_to_task(row)

    def update_task(
        self,
        task_id: str,
        *,
        user: UserContext,
        name: str | None = None,
        description: str | None = None,
        status: TaskStatus | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_task(task_id, user_id=user.user_id)
        changes: dict[str, Any] = {}
        event_payload: dict[str, Any] = {}
        if name is not None:
            changes["name"] = _clean_name(name)
            event_payload["name"] = changes["name"]
        if description is not None:
            changes["description"] = description
            event_payload["description"] = description
        if status is not None:
            changes["status"] = status
            event_payload["status"] = status
        if model_settings is not None:
            changes["model_settings_json"] = dumps(model_settings)
            event_payload["model_settings"] = model_settings
        if changes:
            changes["updated_at"] = now()
            assignments = ", ".join(f"{key} = ?" for key in changes)
            self.conn.execute(
                f"update structured_extraction_tasks set {assignments} where task_id = ? and user_id = ?",
                [*changes.values(), task_id, user.user_id],
            )
            self._insert_event(task_id, user.user_id, "updated", event_payload)
            self.conn.commit()
        task = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, task)
        return task

    def set_archived(self, task_id: str, archived: bool, *, user: UserContext) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        ts = now()
        status = "archived" if archived else ("draft" if task["status"] == "archived" else task["status"])
        self.conn.execute(
            "update structured_extraction_tasks set archived = ?, status = ?, updated_at = ? where task_id = ? and user_id = ?",
            (1 if archived else 0, status, ts, task_id, user.user_id),
        )
        self._insert_event(task_id, user.user_id, "archived" if archived else "unarchived", {"archived": archived})
        self.conn.commit()
        out = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, out)
        return out

    def soft_delete(self, task_id: str, *, user: UserContext) -> None:
        self.get_task(task_id, user_id=user.user_id)
        ts = now()
        self.conn.execute(
            "update structured_extraction_tasks set status = 'deleted', deleted_at = ?, updated_at = ? where task_id = ? and user_id = ?",
            (ts, ts, task_id, user.user_id),
        )
        self._insert_event(task_id, user.user_id, "deleted", {})
        self.conn.commit()

    def duplicate_task(self, task_id: str, *, user: UserContext, name: str, copy_model_settings: bool = True) -> dict[str, Any]:
        source = self.get_task(task_id, user_id=user.user_id)
        return self.create_task(
            name=name,
            description=source.get("description") or "",
            user=user,
            model_settings=source.get("model_settings") if copy_model_settings else {},
        )

    def mark_collecting(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        if task["status"] == "draft":
            self.conn.execute(
                "update structured_extraction_tasks set status = 'collecting', updated_at = ? where task_id = ? and user_id = ?",
                (now(), task_id, user.user_id),
            )
            self._insert_event(task_id, user.user_id, "collecting", {})
            self.conn.commit()
            task = self.get_task(task_id, user_id=user.user_id)
            write_task_manifest(user, task)
        return task

    def update_collection_state(self, task_id: str, *, user: UserContext, collection_version: str, paper_count: int) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(task.get("stats") or {})
        stats["paper_count"] = int(paper_count)
        ts = now()
        self.conn.execute(
            """
            update structured_extraction_tasks
            set status = 'collection_ready',
                current_collection_version = ?,
                stats_json = ?,
                updated_at = ?
            where task_id = ? and user_id = ?
            """,
            (collection_version, dumps(stats), ts, task_id, user.user_id),
        )
        self._insert_event(task_id, user.user_id, "collection_frozen", {"collection_version": collection_version, "paper_count": paper_count})
        self.conn.commit()
        out = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, out)
        return out

    def update_schema_state(self, task_id: str, *, user: UserContext, schema_version: str, field_count: int) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(task.get("stats") or {})
        stats["field_count"] = int(field_count)
        ts = now()
        self.conn.execute(
            """
            update structured_extraction_tasks
            set status = 'schema_ready',
                current_schema_version = ?,
                stats_json = ?,
                updated_at = ?
            where task_id = ? and user_id = ?
            """,
            (schema_version, dumps(stats), ts, task_id, user.user_id),
        )
        self._insert_event(task_id, user.user_id, "schema_frozen", {"schema_version": schema_version, "field_count": field_count})
        self.conn.commit()
        out = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, out)
        return out

    def events_for_task(self, task_id: str, *, user_id: str) -> list[dict[str, Any]]:
        self.get_task(task_id, user_id=user_id)
        rows = self.conn.execute(
            "select * from structured_extraction_task_events where task_id = ? and user_id = ? order by created_at",
            (task_id, user_id),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "task_id": row["task_id"],
                "user_id": row["user_id"],
                "event_type": row["event_type"],
                "payload": loads(row["payload_json"], {}) or {},
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _insert_event(self, task_id: str, user_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            """
            insert into structured_extraction_task_events(task_id, user_id, event_type, payload_json, created_at)
            values(?, ?, ?, ?, ?)
            """,
            (task_id, user_id, event_type, dumps(payload), now()),
        )

    @staticmethod
    def _row_to_task(row) -> dict[str, Any]:
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(loads(row["stats_json"], {}) or {})
        return ExtractionTask(
            task_id=row["task_id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"] or "",
            status=row["status"],
            workspace_rel_path=row["workspace_rel_path"],
            current_collection_version=row["current_collection_version"],
            current_schema_version=row["current_schema_version"],
            model_settings=loads(row["model_settings_json"], {}) or {},
            stats=stats,
            archived=bool(row["archived"]),
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_run_at=row["last_run_at"],
        ).model_dump()


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("task name is required")
    return cleaned[:160]
