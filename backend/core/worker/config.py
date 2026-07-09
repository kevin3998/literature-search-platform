from __future__ import annotations

import os
import socket
import uuid
from dataclasses import dataclass

from core.runtime_config import worker_required


@dataclass(frozen=True)
class WorkerConfig:
    worker_id: str
    queues: list[str]
    poll_interval_ms: int
    job_lease_seconds: int
    heartbeat_interval_seconds: int
    max_jobs_per_tick: int
    worker_required: bool


def worker_config_from_env() -> WorkerConfig:
    return WorkerConfig(
        worker_id=os.getenv("WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}",
        queues=_csv(os.getenv("WORKER_QUEUES") or "default,workflow,structured-extraction"),
        poll_interval_ms=_int_env("WORKER_POLL_INTERVAL_MS", 500, minimum=50),
        job_lease_seconds=_int_env("WORKER_JOB_LEASE_SECONDS", 60, minimum=1),
        heartbeat_interval_seconds=_int_env("WORKER_HEARTBEAT_INTERVAL_SECONDS", 10, minimum=1),
        max_jobs_per_tick=_int_env("WORKER_MAX_JOBS_PER_TICK", 1, minimum=1),
        worker_required=worker_required(),
    )


def _csv(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or ["default"]


def _int_env(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
