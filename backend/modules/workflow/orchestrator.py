"""WorkflowOrchestrator — sequences steps over runners on a daemon thread.

One "workflow" job (in the shared JobStore) carries the unified event stream:
``step`` / ``stage`` / ``artifact`` markers plus the usual ``result`` / ``done``
/ ``error``. The SSE endpoint tails that job. P1 templates are a single
corpus-stage step, but the loop is written for the multi-step (agent-step) future.

Pause is cooperative and takes effect BETWEEN steps — a single corpus-stage step
cannot be interrupted mid-run (the underlying run is a blocking call); the real
control for P1 is resume-from-failed-stage, which the underlying engine supports.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from core.db.types import to_unix_seconds, utc_now
from core.workspace_paths import user_workspace_root
from modules.research_agent_controller.skills.screening_tools import render_screening_summary_markdown

_LOG_STATUS = {"running": "执行中", "done": "完成", "failed": "失败", "blocked": "已阻塞", "unavailable": "敬请期待", "skipped": "已跳过"}

_CONTROLLER_MARKDOWN_PRIORITY = (
    "screening/idea_screening_results.md",
    "ideas/candidate_ideas.md",
    "gaps/gap_map.md",
    "landscape/literature_landscape.md",
    "reports/minimal_topic_to_evidence_report.md",
)

_ARTIFACT_META_BY_SUFFIX = {
    "retrieval/source_candidate_packet.json": ("retrieve_sources", "检索候选源"),
    "retrieval/retrieval_warnings.json": ("retrieve_sources", "检索警告"),
    "evidence/evidence_card_seeds.json": ("create_evidence_seeds", "证据种子"),
    "evidence/evidence_cards.initial.json": ("extract_evidence_cards", "初始证据卡片"),
    "evidence/evidence_cards.enriched.json": ("enrich_evidence_cards", "富集证据卡片"),
    "ranked_evidence/evidence_selection.json": ("rank_evidence", "代表性证据选择"),
    "ranked_evidence/coverage_diagnostics.json": ("rank_evidence", "证据覆盖诊断"),
    "reports/minimal_topic_to_evidence_report.md": ("build_minimal_topic_to_evidence_report", "最小证据报告"),
    "reports/minimal_topic_to_evidence_report.json": ("build_minimal_topic_to_evidence_report", "最小证据报告数据"),
    "landscape/literature_landscape.md": ("build_landscape", "文献图景"),
    "landscape/literature_landscape.json": ("build_landscape", "文献图景数据"),
    "landscape/landscape_coverage_diagnostics.json": ("build_landscape", "文献图景覆盖诊断"),
    "gaps/gap_map.md": ("map_gaps", "研究空白图"),
    "gaps/gap_map.json": ("map_gaps", "研究空白图数据"),
    "gaps/gap_coverage_diagnostics.json": ("map_gaps", "研究空白覆盖诊断"),
    "ideas/candidate_ideas.md": ("generate_candidate_ideas", "候选想法"),
    "ideas/candidate_ideas.json": ("generate_candidate_ideas", "候选想法数据"),
    "ideas/idea_generation_diagnostics.json": ("generate_candidate_ideas", "候选想法诊断"),
    "screening/idea_screening_results.md": ("screen_novelty_feasibility_risk", "新颖性 / 可行性 / 风险筛选"),
    "screening/idea_screening_results.json": ("screen_novelty_feasibility_risk", "筛选结果数据"),
    "screening/screening_diagnostics.json": ("screen_novelty_feasibility_risk", "筛选诊断"),
}

_DIAGNOSTIC_ARTIFACTS_BY_SUFFIX = {
    "retrieval/retrieval_warnings.json": ("retrieve_sources", "检索警告", "retrieval_warnings"),
    "ranked_evidence/coverage_diagnostics.json": ("rank_evidence", "证据覆盖诊断", "coverage_diagnostics"),
    "landscape/landscape_coverage_diagnostics.json": ("build_landscape", "文献图景覆盖诊断", "landscape_coverage_diagnostics"),
    "gaps/gap_coverage_diagnostics.json": ("map_gaps", "研究空白覆盖诊断", "gap_coverage_diagnostics"),
    "ideas/idea_generation_diagnostics.json": ("generate_candidate_ideas", "候选想法诊断", "idea_generation_diagnostics"),
    "screening/screening_diagnostics.json": ("screen_novelty_feasibility_risk", "筛选诊断", "screening_diagnostics"),
}


def _now() -> float:
    return to_unix_seconds(utc_now()) or 0.0

from .runners.base import RunnerContext, StepFailed
from .runners.corpus_stage import CorpusStageRunner
from .runners.agent_step import AgentStepRunner
from .runners.research_controller import ResearchControllerRunner
from .runners.base import stages_for_step


def _default_runners() -> dict[str, Any]:
    return {
        CorpusStageRunner.name: CorpusStageRunner(),
        AgentStepRunner.name: AgentStepRunner(),
        ResearchControllerRunner.name: ResearchControllerRunner(),
    }


class WorkflowOrchestrator:
    def __init__(self, store, job_runner, job_store, service, *, runners=None) -> None:
        self.store = store
        self.job_runner = job_runner
        self.job_store = job_store
        self.service = service
        # Injectable so tests can supply an agent-step runner backed by a
        # ScriptedLLM (real client otherwise).
        self.runners = runners or _default_runners()
        self._pause_flags: dict[str, bool] = {}

    # ---- control ------------------------------------------------------------
    def start(self, workflow_id: str, *, resume: bool = False, user_id: str | None = None) -> dict[str, Any]:
        wf = self.store.get(workflow_id, user_id=user_id)
        if wf["status"] == "running":
            raise ValueError("workflow already running")
        self._pause_flags.pop(workflow_id, None)
        orch_job = self.job_store.create(
            "workflow.run",
            {"workflow_id": workflow_id, "user_id": wf.get("user_id"), "resume": bool(resume)},
            user_id=wf.get("user_id"),
            queue="workflow",
        )
        orch_job_id = orch_job["job_id"]
        self.store.set_engine_ref(workflow_id, orchestrator_job_id=orch_job_id)
        self.store.update_status(workflow_id, "running", started_at=wf.get("started_at") or _now())
        return {
            "job_id": orch_job_id,
            "status": "running",
            "stream_url": f"/api/workflows/{workflow_id}/stream",
        }

    def request_pause(self, workflow_id: str) -> None:
        self._pause_flags[workflow_id] = True
        self.store.set_engine_ref(workflow_id, pause_requested=True)

    def execute_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = job.get("payload") or {}
        workflow_id = payload["workflow_id"]
        resume = bool(payload.get("resume"))
        user_id = payload.get("user_id") or job.get("user_id")
        return self._run(workflow_id, job["job_id"], resume, user_id)

    # ---- execution ----------------------------------------------------------
    def _run(self, workflow_id: str, orch_job_id: str, resume: bool, user_id: str | None) -> dict[str, Any]:
        ctx = RunnerContext(self.store, self.job_store, self.job_runner, self.service)
        try:
            wf = self.store.get(workflow_id, user_id=user_id)
            steps = wf["manifest"].get("steps", [])
            ran_any = False
            for step in steps:
                persisted = self._step_status(workflow_id, step["step_index"])
                # Resume only re-runs from the first not-done step.
                if resume and persisted == "done":
                    continue
                # Capability boundary: stop at the first not-yet-built step. The
                # rest stay 'unavailable' (敬请期待). This is not a failure.
                runner = self.runners.get(step["runner"])
                if not step.get("available") or runner is None:
                    self.job_store.add_event(
                        orch_job_id,
                        {
                            "type": "step",
                            "step_index": step["step_index"],
                            "step_key": step["step_key"],
                            "label": step.get("label"),
                            "status": "unavailable",
                        },
                    )
                    break
                wf_ref = self.store.get(workflow_id, user_id=user_id).get("engine_ref") or {}
                if self._pause_flags.get(workflow_id) or wf_ref.get("pause_requested"):
                    self.job_store.add_event(orch_job_id, {"type": "workflow_status", "status": "paused"})
                    self.store.update_status(workflow_id, "paused")
                    self.store.set_engine_ref(workflow_id, pause_requested=False)
                    return {"workflow_id": workflow_id, "status": "paused", "paused": True}
                runner.execute(workflow_id, step, orch_job_id, resume=resume, ctx=ctx)
                ran_any = True
            final = self._final_status(workflow_id)
            self.job_store.add_event(orch_job_id, {"type": "workflow_status", "status": final})
            self.store.update_status(workflow_id, final, ended_at=_now())
            return {"workflow_id": workflow_id, "status": final}
        except StepFailed as exc:
            self.job_store.add_event(orch_job_id, {"type": "workflow_status", "status": "failed"})
            self.store.update_status(workflow_id, "failed", error=str(exc), ended_at=_now())
            raise
        except Exception as exc:  # noqa: BLE001 - never leak; record on the run
            self.store.update_status(workflow_id, "failed", error=str(exc), ended_at=_now())
            raise

    def _step_status(self, workflow_id: str, step_index: int) -> str:
        for step in self.store.get(workflow_id)["steps"]:
            if step["step_index"] == step_index:
                return step["status"]
        return "pending"

    def _final_status(self, workflow_id: str) -> str:
        steps = self.store.get(workflow_id)["steps"]
        statuses = [s["status"] for s in steps]
        if any(s == "failed" for s in statuses):
            return "failed"
        done = [s for s in statuses if s == "done"]
        remaining = [s for s in statuses if s not in ("done",)]
        if not remaining:
            return "completed"
        # Some steps are still unavailable/pending (敬请期待).
        if done:
            return "partial"
        return "blocked"  # nothing could run (first step not yet built)

    # ---- read model ---------------------------------------------------------
    def detail(self, workflow_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        """Workflow + per-step timeline, corpus-stage steps enriched with the
        underlying run's sub-stages (live or planned).

        Also rehydrates the HISTORY so re-entering a finished run isn't blank:
        agent-step产物的生成内容 (read back from the .md) + a run log rebuilt from
        the persisted orchestrator job events (token events excluded)."""
        wf = self.store.get(workflow_id, user_id=user_id)
        engine_ref = wf.get("engine_ref") or {}
        artifacts: list[dict[str, Any]] = []
        for step in wf["steps"]:
            step["stages"] = stages_for_step(step, engine_ref, self.service)
            if step.get("runner") in {"agent-step", "research-controller"}:
                step["output_text"] = self._read_step_output(step)
            for aid in step.get("artifact_ids", []):
                artifacts.append({"artifact_id": aid, "step_index": step["step_index"], **_artifact_meta(aid)})
        wf["artifacts"] = artifacts
        wf["history_log"] = self._history_log(engine_ref.get("orchestrator_job_id"), user_id=wf.get("user_id"))
        wf["next_event_index"] = self._next_event_index(engine_ref.get("orchestrator_job_id"), user_id=wf.get("user_id"))
        return wf

    def artifact_preview(self, workflow_id: str, artifact_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        """Read a registered workflow artifact for UI preview.

        The artifact must already be present in detail()["artifacts"], which is
        derived from persisted step artifact ids. This prevents the preview API
        from becoming a generic file reader.
        """
        wf = self.detail(workflow_id, user_id=user_id)
        artifacts = {
            item.get("artifact_id"): item
            for item in wf.get("artifacts", [])
            if item.get("artifact_id")
        }
        meta = artifacts.get(artifact_id)
        if not meta:
            raise KeyError("artifact not found")

        text = self._read_artifact_text(artifact_id)
        content_type = _artifact_content_type(artifact_id)
        json_payload = None
        if content_type == "json":
            try:
                json_payload = json.loads(text)
                text = json.dumps(json_payload, ensure_ascii=False, indent=2, sort_keys=True)
            except json.JSONDecodeError:
                content_type = "text"

        return {
            "workflow_id": workflow_id,
            "artifact_id": artifact_id,
            "artifact_type": meta.get("artifact_type") or "workflow_artifact",
            "label": meta.get("label") or artifact_id.rsplit("/", 1)[-1],
            "content_type": content_type,
            "text": text,
            "json": json_payload,
        }

    def workflow_insights(self, workflow_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        """Return read-only, UI-ready summaries derived from registered artifacts."""
        wf = self.detail(workflow_id, user_id=user_id)
        artifacts = list(wf.get("artifacts") or [])
        by_id = {
            item.get("artifact_id"): item
            for item in artifacts
            if item.get("artifact_id")
        }
        enriched_id = _find_artifact_id(artifacts, "evidence/evidence_cards.enriched.json")
        selection_id = _find_artifact_id(artifacts, "ranked_evidence/evidence_selection.json")

        cards_payload = _safe_json_from_registered(self, by_id, enriched_id)
        selection_payload = _safe_json_from_registered(self, by_id, selection_id)
        evidence = _build_evidence_insights(cards_payload, selection_payload, enriched_id)
        diagnostics = _build_diagnostic_insights(self, artifacts, by_id)
        return {
            "workflow_id": workflow_id,
            "evidence": evidence,
            "diagnostics": diagnostics,
        }

    def _read_step_output(self, step: dict[str, Any]) -> str:
        """Read back a step's preferred markdown output."""
        artifact_ids = list(step.get("artifact_ids") or [])
        if step.get("runner") == "research-controller":
            display = self._read_controller_display_output(artifact_ids)
            if display:
                return display
        ordered = _preferred_markdown_artifacts(artifact_ids) if step.get("runner") == "research-controller" else artifact_ids
        for aid in ordered:
            if isinstance(aid, str) and aid.endswith(".md"):
                try:
                    return self._read_artifact_text(aid)
                except Exception:  # noqa: BLE001 - missing file -> no history text
                    return ""
        return ""

    def _read_controller_display_output(self, artifact_ids: list[str]) -> str:
        for aid in artifact_ids:
            if isinstance(aid, str) and aid.endswith("screening/idea_screening_results.json"):
                try:
                    payload = self._read_artifact_json(aid)
                except Exception:  # noqa: BLE001 - fall back to markdown output
                    return ""
                return render_screening_summary_markdown(payload)
        return ""

    def _read_artifact_text(self, artifact_id: str) -> str:
        if artifact_id.startswith("users/"):
            _prefix, user_id, rel = artifact_id.split("/", 2)
            return (user_workspace_root(user_id) / rel).read_text(encoding="utf-8")
        return (Path(self.service.paths.data_dir) / artifact_id).read_text(encoding="utf-8")

    def _read_artifact_json(self, artifact_id: str) -> dict[str, Any]:
        import json

        return json.loads(self._read_artifact_text(artifact_id))

    def _history_log(self, orch_job_id: str | None, *, user_id: str | None = None) -> list[dict[str, Any]]:
        """Rebuild the run log from persisted job events (skip token spam)."""
        if not orch_job_id:
            return []
        try:
            events = self.job_store.events(orch_job_id, user_id=user_id)
        except Exception:  # noqa: BLE001
            return []
        log: list[dict[str, Any]] = []
        for e in events:
            t = e.get("type")
            at = int((e.get("ts") or 0) * 1000)
            status = _LOG_STATUS.get(e.get("status"), e.get("status"))
            if t == "step":
                err = f"：{e['error']}" if e.get("error") else ""
                log.append({"at": at, "line": f"步骤「{e.get('label') or e.get('step_key')}」{status}{err}"})
            elif t == "stage" and e.get("stage") and e.get("stage") != "job":
                log.append({"at": at, "line": f"阶段「{e.get('label') or e.get('stage')}」{status}"})
            elif t == "artifact":
                log.append({"at": at, "line": f"产出：{e.get('label') or e.get('artifact_type') or e.get('artifact_id')}"})
        return log

    def _next_event_index(self, orch_job_id: str | None, *, user_id: str | None = None) -> int:
        if not orch_job_id:
            return 0
        try:
            events = self.job_store.events(orch_job_id, user_id=user_id)
        except Exception:  # noqa: BLE001
            return 0
        if not events:
            return 0
        return max(int(e.get("_event_index", idx)) for idx, e in enumerate(events)) + 1


def _preferred_markdown_artifacts(artifact_ids: list[str]) -> list[str]:
    markdown_ids = [aid for aid in artifact_ids if isinstance(aid, str) and aid.endswith(".md")]
    ordered: list[str] = []
    for suffix in _CONTROLLER_MARKDOWN_PRIORITY:
        ordered.extend([aid for aid in markdown_ids if aid.endswith(suffix)])
    ordered.extend([aid for aid in markdown_ids if aid not in ordered])
    return ordered


def _artifact_meta(artifact_id: str) -> dict[str, str]:
    for suffix, (artifact_type, label) in _ARTIFACT_META_BY_SUFFIX.items():
        if artifact_id.endswith(suffix):
            return {"artifact_type": artifact_type, "label": label}
    name = artifact_id.rsplit("/", 1)[-1]
    return {"artifact_type": "workflow_artifact", "label": name or "产物"}


def _artifact_content_type(artifact_id: str) -> str:
    if artifact_id.endswith(".json"):
        return "json"
    if artifact_id.endswith(".md") or artifact_id.endswith(".markdown"):
        return "markdown"
    return "text"


def _find_artifact_id(artifacts: list[dict[str, Any]], suffix: str) -> str | None:
    for artifact in artifacts:
        artifact_id = str(artifact.get("artifact_id") or "")
        if artifact_id.endswith(suffix):
            return artifact_id
    return None


def _safe_json_from_registered(orchestrator: WorkflowOrchestrator, registered: dict[str, dict[str, Any]], artifact_id: str | None) -> dict[str, Any]:
    if not artifact_id or artifact_id not in registered:
        return {}
    try:
        payload = orchestrator._read_artifact_json(artifact_id)
    except Exception:  # noqa: BLE001 - insights are optional UI summaries
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_evidence_insights(cards_payload: dict[str, Any], selection_payload: dict[str, Any], artifact_id: str | None) -> dict[str, Any]:
    raw_cards = cards_payload.get("cards") if isinstance(cards_payload, dict) else []
    cards = [card for card in (raw_cards or []) if isinstance(card, dict)]
    selected_ids = _selected_evidence_ids(selection_payload)
    normalized = [_normalize_evidence_card(card, selected_ids, artifact_id) for card in cards]
    role_counts = Counter(card.get("role") or "unspecified" for card in normalized)
    support_counts = Counter(card.get("support_strength") or "unspecified" for card in normalized)
    return {
        "available": bool(normalized),
        "card_count": len(normalized),
        "selected_count": len([card for card in normalized if card.get("selected")]),
        "role_counts": dict(role_counts),
        "support_counts": dict(support_counts),
        "cards": normalized,
    }


def _selected_evidence_ids(selection_payload: dict[str, Any]) -> set[str]:
    selected: set[str] = set()
    for item in selection_payload.get("selected_cards") or []:
        if not isinstance(item, dict):
            continue
        evidence_id = item.get("evidence_id") or (item.get("card") or {}).get("evidence_id")
        if evidence_id:
            selected.add(str(evidence_id))
    for item in selection_payload.get("ranked_cards") or []:
        if isinstance(item, dict) and item.get("selected") is True and item.get("evidence_id"):
            selected.add(str(item["evidence_id"]))
    return selected


def _normalize_evidence_card(card: dict[str, Any], selected_ids: set[str], artifact_id: str | None) -> dict[str, Any]:
    evidence_id = str(card.get("evidence_id") or "")
    relevance = card.get("relevance") if isinstance(card.get("relevance"), dict) else {}
    support = card.get("support") if isinstance(card.get("support"), dict) else {}
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    return {
        "evidence_id": evidence_id,
        "paper_id": str(card.get("paper_id") or ""),
        "title": str(card.get("title") or ""),
        "year": card.get("year"),
        "journal": str(card.get("journal") or ""),
        "role": str(card.get("primary_role") or ""),
        "normalized_statement": str(card.get("normalized_statement") or card.get("verbatim_snippet") or ""),
        "support_strength": str(support.get("support_strength") or ""),
        "relevance_score": relevance.get("relevance_score"),
        "selected": evidence_id in selected_ids,
        "source_locator": source.get("locator") if isinstance(source.get("locator"), dict) else {},
        "warnings": _evidence_card_warnings(card),
        "artifact_id": artifact_id or "",
    }


def _evidence_card_warnings(card: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    support = card.get("support") if isinstance(card.get("support"), dict) else {}
    if support.get("uncertainty"):
        warnings.append(str(support["uncertainty"]))
    for item in support.get("unsupported_parts") or []:
        if item:
            warnings.append(str(item))
    return list(dict.fromkeys(warnings))


def _build_diagnostic_insights(orchestrator: WorkflowOrchestrator, artifacts: list[dict[str, Any]], registered: dict[str, dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for artifact in artifacts:
        artifact_id = str(artifact.get("artifact_id") or "")
        matched = next((value for suffix, value in _DIAGNOSTIC_ARTIFACTS_BY_SUFFIX.items() if artifact_id.endswith(suffix)), None)
        if not matched:
            continue
        stage, label, diagnostic_id = matched
        payload = _safe_json_from_registered(orchestrator, registered, artifact_id)
        item = _diagnostic_item(diagnostic_id, stage, label, artifact_id, payload)
        items.append(item)
    counts = Counter(item["severity"] for item in items)
    return {
        "available": bool(items),
        "severity_counts": {
            "info": counts.get("info", 0),
            "warning": counts.get("warning", 0),
            "error": counts.get("error", 0),
        },
        "items": items,
    }


def _diagnostic_item(diagnostic_id: str, stage: str, label: str, artifact_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    warnings = _string_list(payload.get("warnings") or payload.get("coverage_warnings") or [])
    errors = _string_list(payload.get("errors") or payload.get("validation_errors") or [])
    severity = "error" if errors else "warning" if warnings else "info"
    return {
        "diagnostic_id": diagnostic_id,
        "stage": stage,
        "label": label,
        "severity": severity,
        "summary": _diagnostic_summary(label, payload, warnings, errors),
        "warnings": warnings,
        "errors": errors,
        "metrics": _diagnostic_metrics(payload),
        "artifact_id": artifact_id,
    }


def _diagnostic_summary(label: str, payload: dict[str, Any], warnings: list[str], errors: list[str]) -> str:
    if errors:
        return f"{label}发现 {len(errors)} 个错误。"
    if warnings:
        return f"{label}发现 {len(warnings)} 条警告。"
    if payload.get("valid") is True:
        return f"{label}通过校验。"
    if payload.get("coverage"):
        return f"{label}已生成覆盖摘要。"
    return f"{label}已生成。"


def _diagnostic_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"warnings", "errors", "validation_errors", "cards", "seeds", "ranked_cards", "selected_cards"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            metrics[key] = value
        elif isinstance(value, list):
            metrics[f"{key}_count"] = len(value)
        elif isinstance(value, dict):
            metrics[f"{key}_fields"] = len(value)
    return metrics


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item)]
