from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from core.memory_db import connect, dumps, loads, now


class JobStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path
        # A sqlite3.Connection is NOT safe for concurrent use across threads
        # (raises "bad parameter or other API misuse"). This store is hit by the
        # workflow orchestrator thread, job-runner worker threads AND the SSE
        # reader concurrently, so give each thread its own connection — WAL mode
        # (set in connect()) handles multi-connection concurrency.
        self._local = threading.local()

    @property
    def conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.db_path)
            self._local.conn = conn
        return conn

    def create(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        ts = now()
        self.conn.execute(
            """
            insert into jobs(
                job_id, user_id, session_id, turn_id, job_type, status, payload_json, created_at, updated_at
            ) values(?, ?, ?, ?, ?, 'queued', ?, ?, ?)
            """,
            (job_id, user_id, session_id, turn_id, job_type, dumps(payload), ts, ts),
        )
        self.conn.commit()
        self.add_event(job_id, {"type": "queued", "job_id": job_id})
        return self.get(job_id)

    def start(self, job_id: str) -> None:
        self._update(job_id, status="running", started_at=now())
        self.add_event(job_id, {"type": "stage", "stage": "job", "status": "running", "label": "任务开始执行"})

    def add_event(self, job_id: str, event: dict[str, Any]) -> None:
        self._ensure_job(job_id)
        row = self.conn.execute(
            "select coalesce(max(event_index), -1) + 1 as next_index from job_events where job_id = ?",
            (job_id,),
        ).fetchone()
        event_index = int(row["next_index"])
        event_type = str(event.get("type") or "event")
        payload = {**event, "ts": event.get("ts") or now()}
        self.conn.execute(
            """
            insert into job_events(job_id, event_index, event_type, event_json, created_at)
            values(?, ?, ?, ?, ?)
            """,
            (job_id, event_index, event_type, dumps(payload), payload["ts"]),
        )
        self.conn.execute("update jobs set updated_at = ? where job_id = ?", (now(), job_id))
        self.conn.commit()

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        self._update(job_id, status="completed", result_json=dumps(result), completed_at=now())
        self.add_event(job_id, {"type": "result", "data": result})
        self.add_event(job_id, {"type": "done"})

    def fail(self, job_id: str, message: str) -> None:
        self._update(job_id, status="failed", error=message, completed_at=now())
        self.add_event(job_id, {"type": "error", "message": message})
        self.add_event(job_id, {"type": "done"})

    def get(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        row = self._job_row_for_user(job_id, user_id)
        if not row:
            raise KeyError(f"job not found: {job_id}")
        return _job_row(row)

    def events(self, job_id: str, *, after: int = 0, user_id: str | None = None) -> list[dict[str, Any]]:
        self._ensure_job(job_id, user_id=user_id)
        rows = self.conn.execute(
            "select event_index, event_json from job_events where job_id = ? and event_index >= ? order by event_index",
            (job_id, after),
        ).fetchall()
        events = []
        for row in rows:
            payload = loads(row["event_json"], {}) or {}
            payload["_event_index"] = row["event_index"]
            events.append(payload)
        return events

    def reap_orphaned_jobs(self, *, note: str = "中断：后端进程重启，任务线程已终止") -> list[str]:
        """Mark non-terminal jobs as ``interrupted`` — call once at process start.

        Jobs run as daemon threads inside the backend process; a restart (e.g.
        uvicorn ``--reload`` on a code edit) kills those threads without running
        ``complete``/``fail``, leaving rows stuck at ``queued``/``running``. A
        fresh process therefore can't have any live job thread, so every such row
        is orphaned. Reaping them unblocks the home dashboard (no false
        "updating") and the maintenance mutex, and ends any reconnecting stream.
        """
        rows = self.conn.execute(
            "select job_id from jobs where status in ('queued', 'running')"
        ).fetchall()
        job_ids = [row["job_id"] for row in rows]
        if not job_ids:
            return []
        ts = now()
        for job_id in job_ids:
            self.conn.execute(
                "update jobs set status = 'interrupted', error = coalesce(error, ?), completed_at = ?, updated_at = ? where job_id = ?",
                (note, ts, ts, job_id),
            )
        self.conn.commit()
        # Terminal events so any client still tailing the SSE stream stops cleanly.
        for job_id in job_ids:
            self.add_event(job_id, {"type": "stage", "stage": "job", "status": "interrupted", "label": note})
            self.add_event(job_id, {"type": "error", "message": note})
            self.add_event(job_id, {"type": "done"})
        return job_ids

    def list_jobs(self, *, job_types: list[str] | None = None, limit: int = 20, user_id: str | None = None) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if job_types:
            placeholders = ",".join("?" for _ in job_types)
            clauses.append(f"job_type in ({placeholders})")
            params.extend(job_types)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self.conn.execute(
            f"select * from jobs {where} order by created_at desc limit ?",
            params,
        ).fetchall()
        return [_job_row(row) for row in rows]

    def latest_event(self, job_id: str, event_type: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "select event_json from job_events where job_id = ? and event_type = ? order by event_index desc limit 1",
            (job_id, event_type),
        ).fetchone()
        return loads(row["event_json"], None) if row else None

    def event_count(self, job_id: str) -> int:
        row = self.conn.execute("select count(*) as count from job_events where job_id = ?", (job_id,)).fetchone()
        return int(row["count"] if row else 0)

    def _update(self, job_id: str, **changes) -> None:
        self._ensure_job(job_id)
        assignments = []
        params: list[Any] = []
        for key, value in changes.items():
            assignments.append(f"{key} = ?")
            params.append(value)
        assignments.append("updated_at = ?")
        params.append(now())
        params.append(job_id)
        self.conn.execute(f"update jobs set {', '.join(assignments)} where job_id = ?", params)
        self.conn.commit()

    def _ensure_job(self, job_id: str, *, user_id: str | None = None) -> None:
        row = self._job_row_for_user(job_id, user_id)
        if not row:
            raise KeyError(f"job not found: {job_id}")

    def _job_row_for_user(self, job_id: str, user_id: str | None):
        if user_id is None:
            return self.conn.execute("select * from jobs where job_id = ?", (job_id,)).fetchone()
        return self.conn.execute(
            "select * from jobs where job_id = ? and user_id = ?",
            (job_id, user_id),
        ).fetchone()


def _job_row(row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "job_type": row["job_type"],
        "payload": loads(row["payload_json"], {}),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "result": loads(row["result_json"], None),
        "error": row["error"],
    }
