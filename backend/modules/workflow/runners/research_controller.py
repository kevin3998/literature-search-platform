"""Workflow runner that delegates structured tasks to research_agent_controller."""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any, Callable

from core.llm import LLMUnavailable, build_llm_client
from core.memory_db import now
from core.settings_store import settings_store
from core.workspace_paths import user_data_rel_prefix, user_workspace_root
from modules.research_agent_controller import (
    NativeFallbackStepStatus,
    PlatformNativeFallbackController,
    build_explicit_gap_mapping_plan,
    build_explicit_idea_generation_plan,
    build_explicit_landscape_plan,
    build_explicit_screening_plan,
    build_minimal_topic_to_evidence_plan,
)
from modules.research_workspace import ResearchWorkspaceStore

from .base import RunnerContext, StepFailed

EMPTY_EVIDENCE_BLOCKED_MESSAGE = (
    "未找到可用的本地证据，无法继续执行需要证据引用的受控研究步骤。"
    "请先扩大检索范围、换用英文关键词，或完成索引/向量索引后重试。"
)
DEFAULT_ACQUIRE_EVIDENCE_TIMEOUT_SECONDS = 300.0


class ResearchControllerRunner:
    """Run one explicit controller plan inside a workflow step."""

    name = "research-controller"

    _PLAN_BUILDERS: dict[str, Callable[..., Any]] = {
        "minimal": build_minimal_topic_to_evidence_plan,
        "landscape": build_explicit_landscape_plan,
        "gap_mapping": build_explicit_gap_mapping_plan,
        "idea_generation": build_explicit_idea_generation_plan,
        "screening": build_explicit_screening_plan,
    }

    _MAX_STEPS = {
        "minimal": 10,
        "landscape": 11,
        "gap_mapping": 12,
        "idea_generation": 13,
        "screening": 14,
    }

    def execute(
        self,
        workflow_id: str,
        step: dict[str, Any],
        orch_job_id: str,
        *,
        resume: bool,
        ctx: RunnerContext,
    ) -> list[str]:
        store, job_store, service = ctx.store, ctx.job_store, ctx.service
        si = step["step_index"]
        params = dict(step.get("params") or {})
        plan_kind = str(params.get("controller_plan_kind") or step.get("step_key") or "").strip()
        task_id = str(params.get("task_id") or f"{workflow_id}_{plan_kind}")
        if plan_kind not in self._PLAN_BUILDERS:
            return self._fail(store, job_store, orch_job_id, workflow_id, step, f"unknown controller plan kind: {plan_kind}")

        wf = store.get(workflow_id)
        topic = wf.get("topic") or wf.get("title") or ""
        user_id = wf.get("user_id") or params.get("user_id") or "local_user"
        scope_lock = dict(wf.get("scope_lock") or {})
        retrieval_budget = _retrieval_budget_from_scope_lock(scope_lock)
        data_dir = user_workspace_root(user_id)
        workspace_store = ResearchWorkspaceStore(data_dir)
        workspace_root = data_dir / "research_agent/research_tasks" / task_id
        plan = self._PLAN_BUILDERS[plan_kind](task_id, topic)

        if not resume or not workspace_root.exists():
            workspace_store.create_workspace(
                task_id,
                task_markdown=self._task_markdown(wf, plan_kind),
                plan_markdown=json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            )
        elif not (workspace_root / "plan.md").exists():
            workspace_store.write_plan(task_id, json.dumps(plan.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))

        store.set_engine_ref(
            workflow_id,
            controller_task_id=task_id,
            controller_plan_kind=plan_kind,
            controller_workspace_rel_path=f"{user_data_rel_prefix(user_id)}/research_agent/research_tasks/{task_id}",
        )
        store.update_step(workflow_id, si, status="running", started_at=now())
        self._emit_step(job_store, orch_job_id, step, "running")

        controller = PlatformNativeFallbackController(
            workspace_root,
            task_id,
            topic=topic,
            acquire_evidence_fn=self._acquire_evidence_fn(service),
            llm_client=self._llm_client(service),
            max_steps=self._MAX_STEPS.get(plan_kind, 14),
            scope_lock=scope_lock,
            retrieval_budget=retrieval_budget,
            task_profile_id=wf.get("task_profile_id") or "topic-to-report",
        )

        artifact_ids: list[str] = []
        terminal_failure: tuple[str, str] | None = None
        terminal_blocked: str | None = None
        terminal_statuses = {
            NativeFallbackStepStatus.BLOCKED,
            NativeFallbackStepStatus.FAILED,
            NativeFallbackStepStatus.VALIDATION_FAILED,
            NativeFallbackStepStatus.STOP_SUCCESS,
            NativeFallbackStepStatus.BUDGET_EXCEEDED,
        }

        while True:
            result = controller.run_once()
            if result.next_skill:
                self._emit_stage(job_store, orch_job_id, step, result.next_skill, "running")
                if result.status == NativeFallbackStepStatus.SUCCESS:
                    artifact_ids.extend(self._emit_artifacts(service, job_store, orch_job_id, user_id, task_id, result))
                    self._emit_stage(job_store, orch_job_id, step, result.next_skill, "done")
                    if self._should_block_for_empty_evidence(plan_kind, result):
                        terminal_blocked = EMPTY_EVIDENCE_BLOCKED_MESSAGE
                elif result.status == NativeFallbackStepStatus.BLOCKED:
                    terminal_blocked = self._message(result) or "controller_blocked"
                    self._emit_stage(job_store, orch_job_id, step, result.next_skill, "failed", label=result.next_skill)
                elif result.status == NativeFallbackStepStatus.VALIDATION_FAILED:
                    terminal_failure = ("validation_failed", self._message(result) or "controller_validation_failed")
                    self._emit_stage(job_store, orch_job_id, step, result.next_skill, "failed", label=result.next_skill)
                elif result.status == NativeFallbackStepStatus.FAILED:
                    terminal_failure = ("failed", self._message(result) or "controller_failed")
                    self._emit_stage(job_store, orch_job_id, step, result.next_skill, "failed", label=result.next_skill)

            if result.status == NativeFallbackStepStatus.BUDGET_EXCEEDED:
                terminal_failure = ("failed", self._message(result) or "controller_budget_exceeded")

            if terminal_blocked:
                break
            if result.status in terminal_statuses:
                break

        artifact_ids = list(dict.fromkeys(artifact_ids))
        if terminal_failure:
            _kind, message = terminal_failure
            store.update_step(workflow_id, si, status="failed", ended_at=now(), error=message, artifact_ids=artifact_ids)
            self._emit_step(job_store, orch_job_id, step, "failed", error=message)
            raise StepFailed(message)
        if terminal_blocked:
            store.update_step(workflow_id, si, status="blocked", ended_at=now(), error=terminal_blocked, artifact_ids=artifact_ids)
            self._emit_step(job_store, orch_job_id, step, "blocked", error=terminal_blocked)
            return artifact_ids

        store.update_step(workflow_id, si, status="done", ended_at=now(), artifact_ids=artifact_ids)
        self._mark_all_stages(job_store, orch_job_id, step, "done")
        self._emit_step(job_store, orch_job_id, step, "done")
        return artifact_ids

    @staticmethod
    def _task_markdown(wf: dict[str, Any], plan_kind: str) -> str:
        topic = wf.get("topic") or wf.get("title") or ""
        return "\n".join(
            [
                "# 研究工作流任务",
                "",
                f"- 工作流 ID: {wf.get('workflow_id')}",
                f"- 模板 ID: {wf.get('template_id')}",
                f"- 受控计划类型: {plan_kind}",
                f"- 研究主题: {topic}",
                "",
                "该任务由 research_agent_controller 通过工作流外壳受控执行。",
            ]
        )

    @staticmethod
    def _acquire_evidence_fn(service) -> Callable[..., dict[str, Any]]:
        def acquire(query: str, has_history: bool = False, **options: Any) -> dict[str, Any]:
            timeout = _acquire_timeout_seconds(service)
            result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

            def run() -> None:
                try:
                    result_queue.put(("ok", service.acquire_evidence(query, has_history=has_history, **options)))
                except Exception as exc:  # noqa: BLE001 - surfaced through structured retrieval packet
                    result_queue.put(("error", exc))

            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                status, payload = result_queue.get(timeout=timeout)
            except queue.Empty:
                return _retrieval_timeout_packet(query, timeout, options)
            if status == "error":
                raise payload
            return payload

        return acquire

    @staticmethod
    def _message(result) -> str:
        return "; ".join([*getattr(result, "errors", []), *getattr(result, "warnings", [])])

    @staticmethod
    def _emit_step(job_store, orch_job_id, step, status, *, error=None) -> None:
        event = {
            "type": "step",
            "step_index": step["step_index"],
            "step_key": step["step_key"],
            "label": step.get("label"),
            "status": status,
        }
        if error:
            event["error"] = error
        job_store.add_event(orch_job_id, event)

    @staticmethod
    def _emit_stage(job_store, orch_job_id, step, stage, status, label=None) -> None:
        key = f"agent-{step.get('step_index')}-{stage}"
        job_store.add_event(
            orch_job_id,
            {"type": "stage", "stage": key, "status": status, "label": label or _stage_label(step, stage)},
        )

    def _mark_all_stages(self, job_store, orch_job_id, step, status) -> None:
        for item in (step.get("params") or {}).get("stages") or []:
            stage = item.get("stage") if isinstance(item, dict) else item[0]
            if stage:
                self._emit_stage(job_store, orch_job_id, step, stage, status)

    def _emit_artifacts(self, service, job_store, orch_job_id, user_id: str, task_id: str, result) -> list[str]:
        skill_result = getattr(result, "skill_result", None)
        if skill_result is None:
            return []
        artifact_ids: list[str] = []
        for rel in skill_result.output_artifacts:
            artifact_id = f"{user_data_rel_prefix(user_id)}/research_agent/research_tasks/{task_id}/{rel}"
            _mirror_controller_artifact(service, user_id, task_id, rel, artifact_id)
            artifact_ids.append(artifact_id)
            job_store.add_event(
                orch_job_id,
                {
                    "type": "artifact",
                    "artifact_type": skill_result.skill_name,
                    "artifact_id": artifact_id,
                    "path": artifact_id,
                    "label": _artifact_label(skill_result.skill_name, rel),
                },
            )
        return artifact_ids

    @staticmethod
    def _should_block_for_empty_evidence(plan_kind: str, result) -> bool:
        if plan_kind == "minimal" or result.next_skill != "retrieve_sources":
            return False
        skill_result = getattr(result, "skill_result", None)
        metadata = getattr(skill_result, "metadata", {}) if skill_result is not None else {}
        return int(metadata.get("source_candidate_count") or 0) == 0 and int(metadata.get("seed_count") or 0) == 0

    def _fail(self, store, job_store, orch_job_id, workflow_id, step, err) -> list[str]:
        store.update_step(workflow_id, step["step_index"], status="failed", ended_at=now(), error=err)
        self._emit_step(job_store, orch_job_id, step, "failed", error=err)
        raise StepFailed(err)

    def _llm_client(self, service):
        scripted = getattr(service, "_screening_llm", None)
        if scripted is not None:
            return scripted
        scripted = getattr(service, "_scripted", None)
        if scripted is not None and getattr(scripted, "supports_screening", False):
            return scripted
        try:
            return build_llm_client(settings_store, strong=True)
        except LLMUnavailable:
            return None


def _stage_label(step: dict[str, Any], stage: str) -> str:
    for item in (step.get("params") or {}).get("stages") or []:
        if isinstance(item, dict) and item.get("stage") == stage:
            return item.get("label") or stage
    return stage


def _artifact_label(skill_name: str, rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if skill_name == "screen_novelty_feasibility_risk":
        return f"筛选 · {name}"
    return name


def _mirror_controller_artifact(service, user_id: str, task_id: str, rel: str, artifact_id: str) -> None:
    try:
        source = user_workspace_root(user_id) / "research_agent/research_tasks" / task_id / rel
        if not source.exists():
            return
        target = Path(service.paths.data_dir) / artifact_id
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".json":
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:  # noqa: BLE001 - compatibility mirror must not fail the workflow.
        return


def _retrieval_budget_from_scope_lock(scope_lock: dict[str, Any]) -> int | None:
    options = scope_lock.get("scope_options") if isinstance(scope_lock, dict) else None
    if not isinstance(options, dict):
        return None
    value = options.get("limit")
    if value is None:
        return None
    try:
        budget = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, budget)


def _acquire_timeout_seconds(service) -> float:
    raw = getattr(service, "workflow_acquire_evidence_timeout_seconds", None)
    if raw is None:
        raw = DEFAULT_ACQUIRE_EVIDENCE_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_ACQUIRE_EVIDENCE_TIMEOUT_SECONDS
    return max(0.1, value)


def _retrieval_timeout_packet(query: str, timeout_seconds: float, options: dict[str, Any]) -> dict[str, Any]:
    timeout_label = f"{timeout_seconds:g}s"
    return {
        "query": query,
        "query_plan": {
            "original_query": query,
            "query_intent": "topic",
            "rewritten_queries": [query],
            "retrieval_requested": options.get("retrieval"),
            "retrieval_steps": [f"workflow acquire_evidence timed out after {timeout_label}"],
            "filters_requested": {key: value for key, value in options.items() if value is not None},
            "filters_applied": {},
            "fallback_steps": [],
            "final_retrieval_used": "timeout",
            "warnings": ["retrieval_timeout"],
        },
        "coverage": {
            "status": "none",
            "distinct_paper_count": 0,
            "evidence_count": 0,
            "year_range": [None, None],
            "sections_covered": [],
            "evidence_kinds": [],
            "dominant_paper_ratio": 0.0,
            "candidate_paper_count": 0,
            "selected_evidence_count": 0,
            "breadth_limited": False,
            "deep_research_suggested": False,
            "missing_aspects": [],
            "coverage_notes": [f"Retrieval timed out after {timeout_label}."],
        },
        "breadth": {
            "candidate_paper_count": 0,
            "candidate_evidence_count": 0,
            "selected_evidence_count": 0,
            "llm_context_evidence_count": 0,
            "cluster_count": 0,
            "clusters_covered": [],
            "missing_clusters": [],
            "breadth_limited": False,
            "deep_research_suggested": False,
            "estimate_is_lower_bound": False,
            "estimated_total_matches": 0,
            "breadth_notes": [],
        },
        "evidence_candidates": [],
        "expanded_assets": [],
        "warnings": ["retrieval_timeout"],
        "coverage_notes": [f"Retrieval timed out after {timeout_label}."],
    }


__all__ = ["ResearchControllerRunner"]
