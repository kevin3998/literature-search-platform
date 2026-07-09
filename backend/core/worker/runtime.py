from __future__ import annotations

import signal
import time
from typing import Any

from .handlers import HandlerContext, HandlerRegistry
from .queue import JobQueue


class WorkerRuntime:
    def __init__(
        self,
        queue: JobQueue,
        handlers: HandlerRegistry,
        *,
        worker_id: str,
        queues: list[str],
        poll_interval_ms: int = 500,
        lease_seconds: int = 60,
        heartbeat_interval_seconds: int = 10,
        max_jobs_per_tick: int = 1,
    ) -> None:
        self.queue = queue
        self.handlers = handlers
        self.worker_id = worker_id
        self.queues = queues
        self.poll_interval_ms = poll_interval_ms
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.max_jobs_per_tick = max_jobs_per_tick
        self._stopping = False
        self._last_heartbeat = 0.0

    def stop(self) -> None:
        self._stopping = True

    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_args: self.stop())
        signal.signal(signal.SIGINT, lambda *_args: self.stop())
        while not self._stopping:
            count = self.run_once()
            if count <= 0:
                time.sleep(self.poll_interval_ms / 1000)

    def run_once(self) -> int:
        self._heartbeat_if_needed(force=True)
        self.queue.recover_stale_jobs(lease_seconds=self.lease_seconds)
        completed = 0
        for _ in range(max(1, self.max_jobs_per_tick)):
            job = self.queue.claim(worker_id=self.worker_id, queues=self.queues, lease_seconds=self.lease_seconds)
            if not job:
                break
            self._execute(job)
            completed += 1
        return completed

    def _execute(self, job: dict[str, Any]) -> None:
        try:
            handler = self.handlers.get(job["job_type"])
            context = HandlerContext()
            result = handler(job, context) or {}
            for event in context.events:
                self.queue.append_event(job["job_id"], event)
            if self.queue.get(job["job_id"])["cancel_requested"]:
                self.queue.cancel(job["job_id"])
            else:
                self.queue.complete(job["job_id"], result)
        except Exception as exc:  # noqa: BLE001 - worker boundary records failures as job state.
            self.queue.fail(job["job_id"], str(exc))

    def _heartbeat_if_needed(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_heartbeat >= self.heartbeat_interval_seconds:
            self.queue.heartbeat(worker_id=self.worker_id, queues=self.queues)
            self._last_heartbeat = now
