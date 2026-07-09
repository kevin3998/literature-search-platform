from __future__ import annotations

from sqlalchemy.engine import Engine

from core.db.config import app_env

from .config import worker_config_from_env
from .queue import JobQueue


def check_worker_heartbeat(engine: Engine, *, max_age_seconds: int | None = None) -> dict:
    config = worker_config_from_env()
    age = max_age_seconds or max(1, config.job_lease_seconds * 2)
    workers = JobQueue(engine).active_workers(max_age_seconds=age)
    required = config.worker_required or app_env() == "production"
    if workers:
        status = "ok"
        detail = "worker heartbeat is fresh"
    elif required:
        status = "error"
        detail = "no live worker heartbeat"
    else:
        status = "warning"
        detail = "no live worker heartbeat; start `PYTHONPATH=backend python -m core.worker.main` for async jobs"
    return {
        "status": status,
        "detail": detail,
        "worker_required": required,
        "max_age_seconds": age,
        "queues": config.queues,
        "workers": workers,
    }
