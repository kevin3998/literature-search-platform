"""Corpus-stage runner — wraps the underlying ResearchRunManager.

A single corpus-stage step carries an entire checkpointed run (selfcheck → … →
quality). We pre-generate the run_id, submit the existing ``run`` / ``run_resume``
job through the shared JobRunner, then poll the sub-job + run_show to translate
the run's incremental manifest/checkpoint into ``stage`` / ``artifact`` events on
the workflow's own stream. Resume restarts the underlying run from its failed
stage (the agent already skips completed stages on resume).
"""
from __future__ import annotations

import time
from typing import Any

from core.db.types import to_unix_seconds, utc_now

from ..query_lang import needs_translation, to_search_query
from .base import RunnerContext, StepFailed, gen_run_id, stages_from_run_show

_POLL_SECONDS = 0.6
_TERMINAL = {"completed", "failed", "interrupted"}


def _now() -> float:
    return to_unix_seconds(utc_now()) or 0.0


class CorpusStageRunner:
    name = "corpus-stage"

    def __init__(self, llm_factory=None) -> None:
        # Used only to translate a non-ASCII direction into an English search
        # query before retrieval (the corpus is English). Injectable for tests.
        self._llm_factory = llm_factory

    def execute(
        self,
        workflow_id: str,
        step: dict[str, Any],
        orch_job_id: str,
        *,
        resume: bool,
        ctx: RunnerContext,
    ) -> list[str]:
        store, job_store, job_runner, service = ctx.store, ctx.job_store, ctx.job_runner, ctx.service
        si = step["step_index"]
        store.update_step(workflow_id, si, status="running", started_at=_now())
        self._emit_step(job_store, orch_job_id, step, "running")

        wf = store.get(workflow_id)
        user_id = wf.get("user_id") or (step.get("params") or {}).get("user_id")
        engine_ref = wf.get("engine_ref") or {}
        # run_id is keyed per step so a pipeline with multiple corpus steps
        # doesn't collide; underlying_run_id mirrors the latest for convenience.
        run_id = engine_ref.get(f"run_id_{si}")

        if resume and run_id:
            sub = job_runner.submit("run_resume", {"run_id": run_id, "user_id": user_id})
        else:
            # English-only corpus: translate a non-ASCII direction into an English
            # search query so FTS actually hits (ASCII passes through unchanged).
            topic = wf.get("topic")
            if needs_translation(topic):
                # Make the (otherwise invisible) translation a visible sub-step so
                # the console doesn't look frozen during the LLM call.
                job_store.add_event(orch_job_id, {"type": "stage", "stage": "translate", "status": "running", "label": "翻译检索词"})
                search_query = to_search_query(topic, self._llm_factory, user_id=user_id)
                job_store.add_event(orch_job_id, {"type": "stage", "stage": "translate", "status": "done", "label": f"翻译检索词 → {search_query[:48]}"})
            else:
                search_query = topic or ""
            run_id = gen_run_id(search_query)
            store.set_engine_ref(
                workflow_id,
                **{f"run_id_{si}": run_id, "underlying_run_id": run_id, "search_query": search_query},
            )
            payload = {
                "question": search_query or wf.get("topic") or "",
                "scope": wf.get("scope") or "library",
                "run_id": run_id,
                "user_id": user_id,
                **(step.get("params") or {}),
            }
            sub = job_runner.submit("run", payload)

        sub_job_id = sub["job_id"]
        store.update_step(workflow_id, si, job_id=sub_job_id)
        if hasattr(job_runner, "run_inline"):
            job_runner.run_inline(sub)

        artifact_ids = self._pump(job_store, service, orch_job_id, sub_job_id, run_id)

        # Finalize from the authoritative manifest + sub-job status.
        try:
            show = service.run_show(run_id)
        except Exception:  # noqa: BLE001
            show = {}
        manifest = show.get("manifest") or {}
        checkpoint = show.get("checkpoint") or {}
        sub_status = job_store.get(sub_job_id)["status"]
        run_status = manifest.get("status")

        ok = sub_status == "completed" and run_status in ("completed", "partial")
        if ok:
            store.update_step(
                workflow_id, si, status="done", ended_at=_now(), artifact_ids=artifact_ids
            )
            self._emit_step(job_store, orch_job_id, step, "done")
            return artifact_ids

        error = (
            checkpoint.get("error")
            or job_store.get(sub_job_id).get("error")
            or f"run status={run_status or sub_status}"
        )
        failed_stage = checkpoint.get("failed_stage")
        store.update_step(workflow_id, si, status="failed", ended_at=_now(), error=str(error), artifact_ids=artifact_ids)
        self._emit_step(job_store, orch_job_id, step, "failed", error=str(error), failed_stage=failed_stage)
        raise StepFailed(str(error))

    def _pump(self, job_store, service, orch_job_id, sub_job_id, run_id) -> list[str]:
        """Forward the sub-job's artifact events and emit stage transitions until
        the sub-job is terminal. Returns collected artifact ids."""
        cursor = 0
        last_status: dict[str, str] = {}
        artifact_ids: list[str] = []
        while True:
            for ev in job_store.events(sub_job_id, after=cursor):
                cursor += 1
                if ev.get("type") == "artifact":
                    job_store.add_event(orch_job_id, ev)
                    aid = ev.get("artifact_id")
                    if aid and aid not in artifact_ids:
                        artifact_ids.append(aid)
            self._emit_stage_changes(job_store, service, orch_job_id, run_id, last_status)
            if job_store.get(sub_job_id)["status"] in _TERMINAL:
                # one final sweep so the closing stage transition is captured
                self._emit_stage_changes(job_store, service, orch_job_id, run_id, last_status)
                break
            time.sleep(_POLL_SECONDS)
        return artifact_ids

    def _emit_stage_changes(self, job_store, service, orch_job_id, run_id, last_status: dict[str, str]) -> None:
        try:
            stages = stages_from_run_show(service.run_show(run_id))
        except Exception:  # noqa: BLE001 - run dir may not exist yet
            return
        for stage in stages:
            key, status = stage["stage"], stage["status"]
            if last_status.get(key) != status:
                last_status[key] = status
                job_store.add_event(
                    orch_job_id,
                    {"type": "stage", "stage": key, "status": status, "label": stage["label"]},
                )

    @staticmethod
    def _emit_step(job_store, orch_job_id, step, status, *, error=None, failed_stage=None) -> None:
        event = {
            "type": "step",
            "step_index": step["step_index"],
            "step_key": step["step_key"],
            "label": step.get("label"),
            "status": status,
        }
        if error:
            event["error"] = error
        if failed_stage:
            event["failed_stage"] = failed_stage
        job_store.add_event(orch_job_id, event)
