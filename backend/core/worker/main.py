from __future__ import annotations

from core.db.engine import create_engine_from_env
from core.worker.config import worker_config_from_env
from core.worker.queue import JobQueue
from core.worker.runtime import WorkerRuntime


def main() -> None:
    from core.worker.registry import build_handler_registry

    config = worker_config_from_env()
    engine = create_engine_from_env()
    runtime = WorkerRuntime(
        JobQueue(engine),
        build_handler_registry(engine=engine),
        worker_id=config.worker_id,
        queues=config.queues,
        poll_interval_ms=config.poll_interval_ms,
        lease_seconds=config.job_lease_seconds,
        heartbeat_interval_seconds=config.heartbeat_interval_seconds,
        max_jobs_per_tick=config.max_jobs_per_tick,
    )
    runtime.run_forever()


if __name__ == "__main__":
    main()
