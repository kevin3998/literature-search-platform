"""Shared runner contract + corpus stage-name helpers.

GOTCHA the timeline depends on: the underlying ResearchRunManager records
``requested_stages`` with BARE names (``pack``) but ``completed_stages`` /
``running_stage`` / ``failed_stage`` with PREFIXED names (``04-pack``). The
mapping below bridges the two so per-stage status is derivable from run_show.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# bare requested-stage name -> prefixed checkpoint/completed name
STAGE_PREFIX: dict[str, str] = {
    "selfcheck": "01-selfcheck",
    "plan": "02-plan",
    "task": "03-task",
    "pack": "04-pack",
    "extract": "05-extract",
    "compare": "06-compare",
    "verify": "07-verify",
    "notes": "08-notes",
    "synthesis": "09-synthesis",
    "quality": "10-quality",
}

STAGE_LABEL: dict[str, str] = {
    "selfcheck": "自检",
    "plan": "规划",
    "task": "任务规划",
    "pack": "整理证据包",
    "extract": "指标抽取",
    "compare": "对比",
    "verify": "核查引用",
    "notes": "研究笔记",
    "synthesis": "综合",
    "quality": "质量门",
}


class StepFailed(Exception):
    """Raised by a runner when its step ends in a failed state."""


@dataclass
class RunnerContext:
    """Collaborators handed to a runner (shared singletons, injected in tests)."""

    store: Any
    job_store: Any
    job_runner: Any
    service: Any


def gen_run_id(topic: str | None) -> str:
    """Pre-generate an underlying run_id (matches ResearchRunManager's format) so
    we can poll run_show for live per-stage status without touching the agent.

    Slug keeps ASCII word chars; if the topic is all non-ASCII (e.g. a Chinese
    direction that the old ``[^a-z0-9]`` regex erased to empty → every run became
    ``…-research-run``), fall back to a short content hash so run dirs stay
    distinct and traceable."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    text = topic or ""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:56]
    if not slug:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8] if text else "research-run"
        slug = digest
    return f"run-{stamp}-{slug}"


def expected_stages(params: dict[str, Any]) -> list[str]:
    """The bare stage names a corpus run will request given its flags — used to
    show the planned timeline before/without a live run."""
    stages = ["selfcheck", "plan", "task", "pack"]
    with_extract = bool(params.get("with_extract")) or bool(params.get("with_compare"))
    with_synthesis = bool(params.get("with_synthesis")) or bool(params.get("verify_synthesis"))
    if with_extract:
        stages.append("extract")
    if params.get("with_compare"):
        stages.append("compare")
    if params.get("verify_answer"):
        stages.append("verify")
    if params.get("with_notes"):
        stages.append("notes")
    if with_synthesis:
        stages.append("synthesis")
    if params.get("with_quality"):
        stages.append("quality")
    return stages


def _stage_view(bare: str, status: str) -> dict[str, str]:
    return {"stage": bare, "label": STAGE_LABEL.get(bare, bare), "status": status}


def agent_stages_for_step(step: dict[str, Any], status: str = "pending") -> list[dict[str, str]]:
    stages = ((step.get("params") or {}).get("stages") or [])
    out = []
    for item in stages:
        if isinstance(item, dict):
            key, label = item.get("stage"), item.get("label")
        else:
            key, label = item[0], item[1] if len(item) > 1 else item[0]
        if key:
            out.append({"stage": f"agent-{step.get('step_index')}-{key}", "label": label or key, "status": status})
    return out


def stages_from_run_show(show: dict[str, Any]) -> list[dict[str, str]]:
    """Derive per-stage timeline status from a run_show() payload."""
    manifest = show.get("manifest") or {}
    checkpoint = show.get("checkpoint") or {}
    requested = manifest.get("requested_stages") or []
    completed = set(manifest.get("completed_stages") or []) | set(checkpoint.get("completed_stages") or [])
    running = checkpoint.get("running_stage")
    failed = checkpoint.get("failed_stage")
    out: list[dict[str, str]] = []
    for bare in requested:
        prefixed = STAGE_PREFIX.get(bare, bare)
        if prefixed in completed:
            status = "done"
        elif prefixed == failed:
            status = "failed"
        elif prefixed == running:
            status = "running"
        else:
            status = "pending"
        out.append(_stage_view(bare, status))
    return out


def stages_for_step(step: dict[str, Any], engine_ref: dict[str, Any], service: Any) -> list[dict[str, str]]:
    """Timeline sub-stages for one step. Corpus-stage: from the live run if it
    exists, else the planned (pending) stages from the step's params."""
    if step.get("runner") != "corpus-stage":
        step_status = step.get("status")
        status = "done" if step_status == "done" else "failed" if step_status == "failed" else "pending"
        return agent_stages_for_step(step, status)
    ref = engine_ref or {}
    run_id = ref.get(f"run_id_{step.get('step_index')}") or ref.get("underlying_run_id")
    if run_id and service is not None:
        try:
            return stages_from_run_show(service.run_show(run_id))
        except Exception:  # noqa: BLE001 - fall back to planned stages
            pass
    params = step.get("params") or {}
    return [_stage_view(bare, "pending") for bare in expected_stages(params)]
