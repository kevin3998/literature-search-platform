from __future__ import annotations

import threading
import time
from typing import Any, Callable

from modules.literature_search.job_store import JobStore
from modules.literature_search.service import LiteratureResearchService
from core.session_store import session_store

# Job-bookkeeping keys that must not be forwarded as service call arguments.
_JOB_META = {"session_id", "turn_id", "user_id"}


def _service_kwargs(payload: dict) -> dict:
    """Drop job-association metadata so it is never forwarded as a service kwarg.

    The tool path (Block 4) puts ``session_id`` / ``turn_id`` in the submitted
    payload so the job links to the session, but the service methods don't accept
    them.
    """
    return {k: v for k, v in payload.items() if k not in _JOB_META}


class JobRunner:
    def __init__(self, store: JobStore, service: LiteratureResearchService) -> None:
        self.store = store
        self.service = service

    def submit(self, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = payload.get("user_id")
        if user_id is None and payload.get("session_id"):
            try:
                user_id = session_store.get_session(payload["session_id"]).get("user_id")
            except Exception:  # noqa: BLE001 - platform-level jobs may not have a session owner.
                user_id = None
        job = self.store.create(
            job_type,
            payload,
            session_id=payload.get("session_id"),
            turn_id=payload.get("turn_id"),
            user_id=user_id,
        )
        thread = threading.Thread(target=self._run_sync, args=(job["job_id"], job_type, payload), daemon=True)
        thread.start()
        return job

    def _run_sync(self, job_id: str, job_type: str, payload: dict[str, Any]) -> None:
        self.store.start(job_id)
        try:
            result = self._execute(job_id, job_type, payload)
            self.store.complete(job_id, result)
        except Exception as exc:  # noqa: BLE001 - convert to job event
            self.store.fail(job_id, str(exc))

    def _execute(self, job_id: str, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "task_run": self._task_run,
            "run": self._run_manager,
            "run_resume": self._run_resume,
            "pack": self._pack,
            "extract": self._extract,
            "compare": self._compare,
            "analysis_bundle": self._analysis_bundle,
            "verify_answer": self._verify_answer,
            "notes_build": self._notes_build,
            "synthesize": self._synthesize,
            "quality": self._quality,
            "vector_build": self._vector_build,
            "health_check": self._health_check,
            # index_refresh needs the job_id to stream per-article progress events.
            "index_refresh": lambda payload: self._index_refresh(job_id, payload),
        }
        if job_type not in handlers:
            raise ValueError(f"unknown job type: {job_type}")
        result = handlers[job_type](dict(payload))
        job = self.store.get(job_id)
        for artifact in _artifact_events(result):
            self.store.add_event(job_id, artifact)
            if job.get("session_id"):
                session_store.record_artifact(
                    artifact,
                    session_id=job.get("session_id"),
                    turn_id=job.get("turn_id"),
                    link_type=artifact.get("artifact_type") or job_type,
                )
        return result

    def _stage(self, job_id: str, stage: str, label: str, status: str = "running") -> None:
        self.store.add_event(job_id, {"type": "stage", "stage": stage, "status": status, "label": label})

    def _task_run(self, payload: dict) -> dict:
        return self.service.task_run(payload["question"], budget=payload.get("budget", 20000), scope=payload.get("scope", "library"))

    def _run_manager(self, payload: dict) -> dict:
        payload = _service_kwargs(payload)
        question = payload.pop("question")
        return self.service.run(question, **payload)

    def _run_resume(self, payload: dict) -> dict:
        return self.service.run_resume(payload["run_id"])

    def _pack(self, payload: dict) -> dict:
        payload = _service_kwargs(payload)
        query = payload.pop("query")
        return self.service.pack(query, **payload)

    def _extract(self, payload: dict) -> dict:
        payload = _service_kwargs(payload)
        query = payload.pop("query")
        return self.service.extract(query, **payload)

    def _compare(self, payload: dict) -> dict:
        payload = _service_kwargs(payload)
        query = payload.pop("query")
        return self.service.compare(query, **payload)

    def _analysis_bundle(self, payload: dict) -> dict:
        return self.service.analysis_bundle(**payload)

    def _verify_answer(self, payload: dict) -> dict:
        return self.service.verify_answer(**payload)

    def _notes_build(self, payload: dict) -> dict:
        return self.service.notes_build(payload["run_id"])

    def _synthesize(self, payload: dict) -> dict:
        return self.service.synthesize(**payload)

    def _quality(self, payload: dict) -> dict:
        return self.service.quality(**payload)

    def _vector_build(self, payload: dict) -> dict:
        return self.service.vector_build(**{k: v for k, v in payload.items() if k not in _JOB_META})

    def _health_check(self, payload: dict) -> dict:
        return self.service.index_health()

    def _index_refresh(self, job_id: str, payload: dict) -> dict:
        # Stream real per-article progress, throttled so we don't write an event
        # for every one of ~87k articles (emit ~once/0.7s or every 1000 articles,
        # always emitting the final one).
        state = {"last_ts": 0.0, "last_pos": 0}

        def on_progress(info: dict) -> None:
            current = int(info.get("current") or 0)
            total = int(info.get("total") or 0)
            now = time.monotonic()
            is_final = total and current >= total
            if not (is_final or now - state["last_ts"] >= 0.7 or current - state["last_pos"] >= 1000):
                return
            state["last_ts"] = now
            state["last_pos"] = current
            self.store.add_event(
                job_id,
                {
                    "type": "progress",
                    "current": current,
                    "total": total,
                    "indexed": info.get("indexed_articles"),
                    "documents": info.get("documents"),
                    "phase": f"扫描索引 {current}/{total}" if total else "扫描索引",
                },
            )

        return self.service.index_build(progress=on_progress)


def _artifact_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for key, value in _walk(result):
        if not isinstance(value, str):
            continue
        if not value.startswith("research_agent/"):
            continue
        if not (value.endswith(".json") or value.endswith(".md")):
            continue
        events.append(
            {
                "type": "artifact",
                "artifact_type": _artifact_type_from_path(value),
                "artifact_id": value,
                "path": value,
                "label": key,
            }
        )
    return events


def _walk(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{prefix}.{index}" if prefix else str(index))
    else:
        yield prefix, value


def _artifact_type_from_path(path: str) -> str:
    parts = path.split("/")
    if len(parts) >= 2:
        return parts[1].rstrip("s")
    return "artifact"
