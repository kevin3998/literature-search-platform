from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, json_loads, new_uuid, to_unix_seconds, utc_now, uuid_value

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
BACKOFF_SECONDS = (5, 30, 120)


class JobQueue:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or create_engine_from_env()

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        queue: str = "default",
        priority: int = 0,
        max_attempts: int = 1,
        next_run_at: Any | None = None,
    ) -> dict[str, Any]:
        job_id = new_uuid()
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into jobs(
                        job_id, user_id, session_id, turn_id, queue, job_type, status,
                        payload_json, priority, attempt_count, max_attempts, next_run_at,
                        created_at, updated_at
                    ) values(
                        :job_id, :user_id, :session_id, :turn_id, :queue, :job_type, 'queued',
                        cast(:payload_json as jsonb), :priority, 0, :max_attempts,
                        coalesce(:next_run_at, :ts), :ts, :ts
                    )
                    """
                ),
                {
                    "job_id": uuid_value(job_id),
                    "user_id": uuid_value(user_id) if user_id else None,
                    "session_id": uuid_value(session_id) if session_id else None,
                    "turn_id": uuid_value(turn_id) if turn_id else None,
                    "queue": queue,
                    "job_type": job_type,
                    "payload_json": json_dumps(payload),
                    "priority": int(priority or 0),
                    "max_attempts": max(1, int(max_attempts or 1)),
                    "next_run_at": next_run_at,
                    "ts": ts,
                },
            )
        self.append_event(job_id, {"type": "queued", "job_id": job_id})
        return self.get(job_id)

    def claim(self, *, worker_id: str, queues: list[str], lease_seconds: int = 60) -> dict[str, Any] | None:
        del lease_seconds
        ts = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    select *
                    from jobs
                    where status = 'queued'
                      and queue = any(:queues)
                      and coalesce(next_run_at, now()) <= now()
                    order by priority desc, created_at asc
                    limit 1
                    for update skip locked
                    """
                ),
                {"queues": queues},
            ).mappings().first()
            if not row:
                return None
            conn.execute(
                text(
                    """
                    update jobs
                    set status = 'running',
                        locked_by = :worker_id,
                        locked_at = :ts,
                        started_at = coalesce(started_at, :ts),
                        attempt_count = attempt_count + 1,
                        updated_at = :ts
                    where job_id = :job_id
                    """
                ),
                {"worker_id": worker_id, "ts": ts, "job_id": row["job_id"]},
            )
        self.append_event(str(row["job_id"]), {"type": "stage", "stage": "job", "status": "running", "label": "任务开始执行"})
        return self.get(str(row["job_id"]))

    def heartbeat(self, *, worker_id: str, queues: list[str], metadata: dict[str, Any] | None = None) -> None:
        ts = utc_now()
        payload = {"queues": queues, **(metadata or {})}
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into worker_heartbeats(worker_id, metadata_json, started_at, last_seen_at, status)
                    values(:worker_id, cast(:metadata_json as jsonb), :ts, :ts, 'online')
                    on conflict(worker_id) do update
                    set metadata_json = excluded.metadata_json,
                        last_seen_at = excluded.last_seen_at,
                        status = 'online'
                    """
                ),
                {"worker_id": worker_id, "metadata_json": json_dumps(payload), "ts": ts},
            )

    def heartbeat_job(self, job_id: str, *, worker_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("update jobs set locked_at = :ts, updated_at = :ts where job_id = :job_id and locked_by = :worker_id and status = 'running'"),
                {"ts": utc_now(), "job_id": uuid_value(job_id), "worker_id": worker_id},
            )

    def complete(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    update jobs
                    set status = 'completed',
                        result_json = cast(:result_json as jsonb),
                        locked_by = null,
                        locked_at = null,
                        completed_at = :ts,
                        updated_at = :ts
                    where job_id = :job_id
                    """
                ),
                {"job_id": uuid_value(job_id), "result_json": json_dumps(result or {}), "ts": ts},
            )
        self.append_event(job_id, {"type": "result", "data": result or {}})
        self.append_event(job_id, {"type": "done"})

    def fail(self, job_id: str, message: str, *, retry: bool = True) -> dict[str, Any]:
        job = self.get(job_id)
        ts = utc_now()
        if retry and int(job["attempt_count"]) < int(job["max_attempts"]):
            next_run_at = ts + timedelta(seconds=_backoff_for_attempt(int(job["attempt_count"])))
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        update jobs
                        set status = 'queued',
                            error = :error,
                            locked_by = null,
                            locked_at = null,
                            next_run_at = :next_run_at,
                            updated_at = :ts
                        where job_id = :job_id
                        """
                    ),
                    {"job_id": uuid_value(job_id), "error": message, "next_run_at": next_run_at, "ts": ts},
                )
            self.append_event(job_id, {"type": "retry", "message": message, "next_run_at": to_unix_seconds(next_run_at)})
        else:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        update jobs
                        set status = 'failed',
                            error = :error,
                            locked_by = null,
                            locked_at = null,
                            completed_at = :ts,
                            updated_at = :ts
                        where job_id = :job_id
                        """
                    ),
                    {"job_id": uuid_value(job_id), "error": message, "ts": ts},
                )
            self.append_event(job_id, {"type": "error", "message": message})
            self.append_event(job_id, {"type": "done"})
        return self.get(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job["status"] in TERMINAL_STATUSES:
            return job
        ts = utc_now()
        if job["status"] == "queued":
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        update jobs
                        set status = 'cancelled',
                            cancel_requested = true,
                            completed_at = :ts,
                            updated_at = :ts
                        where job_id = :job_id
                        """
                    ),
                    {"job_id": uuid_value(job_id), "ts": ts},
                )
            self.append_event(job_id, {"type": "cancelled"})
            self.append_event(job_id, {"type": "done"})
        else:
            with self.engine.begin() as conn:
                conn.execute(
                    text("update jobs set cancel_requested = true, updated_at = :ts where job_id = :job_id"),
                    {"job_id": uuid_value(job_id), "ts": ts},
                )
            self.append_event(job_id, {"type": "cancel_requested"})
        return self.get(job_id)

    def recover_stale_jobs(self, *, lease_seconds: int) -> list[str]:
        cutoff = utc_now() - timedelta(seconds=max(1, int(lease_seconds)))
        recovered: list[str] = []
        with self.engine.connect() as conn:
            stale = conn.execute(
                text("select job_id from jobs where status = 'running' and locked_at < :cutoff"),
                {"cutoff": cutoff},
            ).scalars().all()
        for raw_id in stale:
            job_id = str(raw_id)
            job = self.get(job_id)
            if int(job["attempt_count"]) < int(job["max_attempts"]):
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            update jobs
                            set status = 'queued',
                                locked_by = null,
                                locked_at = null,
                                next_run_at = :ts,
                                updated_at = :ts
                            where job_id = :job_id
                            """
                        ),
                        {"job_id": uuid_value(job_id), "ts": utc_now()},
                    )
                self.append_event(job_id, {"type": "retry", "message": "worker lease expired"})
            else:
                self.fail(job_id, "worker lease expired")
            recovered.append(job_id)
        return recovered

    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("select job_id from jobs where job_id = :job_id for update"), {"job_id": uuid_value(job_id)}).scalar_one()
            event_index = conn.execute(
                text("select coalesce(max(event_index), -1) + 1 from job_events where job_id = :job_id"),
                {"job_id": uuid_value(job_id)},
            ).scalar_one()
            payload = {**event, "ts": event.get("ts") or to_unix_seconds(utc_now())}
            conn.execute(
                text(
                    """
                    insert into job_events(job_id, event_index, event_type, event_json, created_at)
                    values(:job_id, :event_index, :event_type, cast(:event_json as jsonb), :created_at)
                    """
                ),
                {
                    "job_id": uuid_value(job_id),
                    "event_index": int(event_index),
                    "event_type": str(payload.get("type") or "event"),
                    "event_json": json_dumps(payload),
                    "created_at": utc_now(),
                },
            )
            conn.execute(text("update jobs set updated_at = :ts where job_id = :job_id"), {"ts": utc_now(), "job_id": uuid_value(job_id)})

    def get(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        with self.engine.connect() as conn:
            if user_id is None:
                row = conn.execute(text("select * from jobs where job_id = :job_id"), {"job_id": uuid_value(job_id)}).mappings().first()
            else:
                row = conn.execute(
                    text("select * from jobs where job_id = :job_id and user_id = :user_id"),
                    {"job_id": uuid_value(job_id), "user_id": uuid_value(user_id)},
                ).mappings().first()
        if not row:
            raise KeyError(f"job not found: {job_id}")
        return _job_row(row)

    def events(self, job_id: str, *, after: int = 0, user_id: str | None = None) -> list[dict[str, Any]]:
        self.get(job_id, user_id=user_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select event_index, event_json from job_events where job_id = :job_id and event_index >= :after order by event_index"),
                {"job_id": uuid_value(job_id), "after": after},
            ).mappings().all()
        events = []
        for row in rows:
            payload = json_loads(row["event_json"], {}) or {}
            payload["_event_index"] = row["event_index"]
            events.append(payload)
        return events

    def active_workers(self, *, max_age_seconds: int) -> list[dict[str, Any]]:
        cutoff = utc_now() - timedelta(seconds=max(1, int(max_age_seconds)))
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select * from worker_heartbeats
                    where status = 'online' and last_seen_at >= :cutoff
                    order by last_seen_at desc
                    """
                ),
                {"cutoff": cutoff},
            ).mappings().all()
        return [
            {
                "worker_id": row["worker_id"],
                "metadata": json_loads(row["metadata_json"], {}) or {},
                "started_at": to_unix_seconds(row["started_at"]),
                "last_seen_at": to_unix_seconds(row["last_seen_at"]),
                "status": row["status"],
            }
            for row in rows
        ]


def _backoff_for_attempt(attempt_count: int) -> int:
    index = max(0, min(attempt_count - 1, len(BACKOFF_SECONDS) - 1))
    return BACKOFF_SECONDS[index]


def _job_row(row) -> dict[str, Any]:
    return {
        "job_id": str(row["job_id"]),
        "user_id": str(row["user_id"]) if row["user_id"] else None,
        "session_id": str(row["session_id"]) if row["session_id"] else None,
        "turn_id": str(row["turn_id"]) if row["turn_id"] else None,
        "queue": row["queue"],
        "job_type": row["job_type"],
        "payload": json_loads(row["payload_json"], {}) or {},
        "status": row["status"],
        "priority": row["priority"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "next_run_at": to_unix_seconds(row["next_run_at"]),
        "cancel_requested": bool(row["cancel_requested"]),
        "locked_by": row["locked_by"],
        "locked_at": to_unix_seconds(row["locked_at"]),
        "created_at": to_unix_seconds(row["created_at"]),
        "updated_at": to_unix_seconds(row["updated_at"]),
        "started_at": to_unix_seconds(row["started_at"]),
        "completed_at": to_unix_seconds(row["completed_at"]),
        "result": json_loads(row["result_json"], None),
        "error": row["error"],
    }
