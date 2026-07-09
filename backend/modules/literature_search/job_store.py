from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, json_loads, new_uuid, to_unix_seconds, utc_now, uuid_value
from core.worker.queue import JobQueue


class JobStore:
    def __init__(self, db_path: str | None = None, engine: Engine | None = None) -> None:
        self.db_path = db_path
        self.engine = engine or create_engine_from_env()
        self.queue = JobQueue(self.engine)

    def create(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        user_id: str | None = None,
        queue: str = "default",
        priority: int = 0,
        max_attempts: int = 1,
    ) -> dict[str, Any]:
        return self.queue.enqueue(
            job_type,
            payload,
            session_id=session_id,
            turn_id=turn_id,
            user_id=user_id,
            queue=queue,
            priority=priority,
            max_attempts=max_attempts,
        )

    def start(self, job_id: str) -> None:
        self._update(job_id, status="running", started_at=utc_now())
        self.add_event(job_id, {"type": "stage", "stage": "job", "status": "running", "label": "任务开始执行"})

    def add_event(self, job_id: str, event: dict[str, Any]) -> None:
        self.queue.append_event(job_id, event)

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        self.queue.complete(job_id, result)

    def fail(self, job_id: str, message: str) -> None:
        self.queue.fail(job_id, message, retry=False)

    def get(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        row = self._job_row_for_user(job_id, user_id)
        if not row:
            raise KeyError(f"job not found: {job_id}")
        return _job_row(row)

    def events(self, job_id: str, *, after: int = 0, user_id: str | None = None) -> list[dict[str, Any]]:
        return self.queue.events(job_id, after=after, user_id=user_id)

    def reap_orphaned_jobs(self, *, note: str = "中断：后端进程重启，任务线程已终止") -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("select job_id from jobs where status in ('queued', 'running')")).scalars().all()
        job_ids = [str(row) for row in rows]
        for job_id in job_ids:
            self._update(job_id, status="interrupted", error=note, completed_at=utc_now())
            self.add_event(job_id, {"type": "stage", "stage": "job", "status": "interrupted", "label": note})
            self.add_event(job_id, {"type": "error", "message": note})
            self.add_event(job_id, {"type": "done"})
        return job_ids

    def list_jobs(self, *, job_types: list[str] | None = None, limit: int = 20, user_id: str | None = None) -> list[dict[str, Any]]:
        clauses = []
        params: dict[str, Any] = {"limit": limit}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = uuid_value(user_id)
        if job_types:
            clauses.append("job_type = any(:job_types)")
            params["job_types"] = job_types
        where = f"where {' and '.join(clauses)}" if clauses else ""
        with self.engine.connect() as conn:
            rows = conn.execute(text(f"select * from jobs {where} order by created_at desc limit :limit"), params).mappings().all()
        return [_job_row(row) for row in rows]

    def latest_event(self, job_id: str, event_type: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("select event_json from job_events where job_id = :job_id and event_type = :event_type order by event_index desc limit 1"),
                {"job_id": uuid_value(job_id), "event_type": event_type},
            ).mappings().first()
        return json_loads(row["event_json"], None) if row else None

    def event_count(self, job_id: str) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text("select count(*) from job_events where job_id = :job_id"), {"job_id": uuid_value(job_id)}).scalar_one())

    def _update(self, job_id: str, **changes) -> None:
        self._ensure_job(job_id)
        assignments = []
        params: dict[str, Any] = {"job_id": uuid_value(job_id), "updated_at": utc_now()}
        for key, value in changes.items():
            if key in {"result_json"}:
                assignments.append(f"{key} = cast(:{key} as jsonb)")
            else:
                assignments.append(f"{key} = :{key}")
            params[key] = value
        assignments.append("updated_at = :updated_at")
        with self.engine.begin() as conn:
            conn.execute(text(f"update jobs set {', '.join(assignments)} where job_id = :job_id"), params)

    def _ensure_job(self, job_id: str, *, user_id: str | None = None) -> None:
        row = self._job_row_for_user(job_id, user_id)
        if not row:
            raise KeyError(f"job not found: {job_id}")

    def _job_row_for_user(self, job_id: str, user_id: str | None):
        with self.engine.connect() as conn:
            if user_id is None:
                return conn.execute(text("select * from jobs where job_id = :job_id"), {"job_id": uuid_value(job_id)}).mappings().first()
            return conn.execute(
                text("select * from jobs where job_id = :job_id and user_id = :user_id"),
                {"job_id": uuid_value(job_id), "user_id": uuid_value(user_id)},
            ).mappings().first()


def _job_row(row) -> dict[str, Any]:
    return {
        "job_id": str(row["job_id"]),
        "user_id": str(row["user_id"]) if row["user_id"] else None,
        "session_id": str(row["session_id"]) if row["session_id"] else None,
        "turn_id": str(row["turn_id"]) if row["turn_id"] else None,
        "job_type": row["job_type"],
        "payload": json_loads(row["payload_json"], {}),
        "status": row["status"],
        "created_at": to_unix_seconds(row["created_at"]),
        "updated_at": to_unix_seconds(row["updated_at"]),
        "started_at": to_unix_seconds(row["started_at"]),
        "completed_at": to_unix_seconds(row["completed_at"]),
        "result": json_loads(row["result_json"], None),
        "error": row["error"],
    }
