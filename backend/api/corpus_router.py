"""Block 0 API: canonical corpus identity + Research Index Health.

Exposes the read-only identity/health surface (dashboard, paper_id resolution,
on-disk path checks) plus role-gated maintenance jobs (health check, index
refresh, vector build). Shares the literature-search job store/runner so
maintenance jobs stream through the same SSE machinery.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.permissions import require_admin
from core.user_context import UserContext, current_user
from modules.literature_search.corpus import (
    MAINTENANCE_ACTIONS,
    CorpusService,
    PaperNotFound,
)
from modules.literature_search.literature_search_shared import job_runner, job_store, service

router = APIRouter(prefix="/api/corpus", tags=["corpus"])

_corpus: CorpusService | None = None


def corpus() -> CorpusService:
    global _corpus
    if _corpus is None:
        _corpus = CorpusService(service)
    return _corpus


_MAINTENANCE_JOB_TYPES = list(MAINTENANCE_ACTIONS)


class ResolveRequest(BaseModel):
    doi: str | None = None
    paper_id: str | None = None
    article_id: int | None = None
    source_path: str | None = None


class PaperPathsRequest(BaseModel):
    doi: str | None = None
    paper_id: str | None = None
    article_id: int | None = None


def _handle_error(exc: Exception):
    if isinstance(exc, (PaperNotFound, KeyError)):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, sqlite3.Error):
        message = str(exc)
        if "locked" in message or "malformed" in message:
            raise HTTPException(status_code=503, detail=f"research index is busy: {message}") from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard")
def dashboard(user: UserContext = Depends(current_user)):
    try:
        role = "admin" if user.role == "admin" and user.status == "active" else "viewer"
        recent_jobs = job_store.list_jobs(job_types=_MAINTENANCE_JOB_TYPES, limit=10) if role == "admin" else []
        payload = corpus().dashboard(role=role, recent_jobs=recent_jobs)
        # Attach the latest streamed progress so a reloaded page (with no live
        # SSE stream) can still render a determinate bar for a running refresh.
        running = payload.get("running_maintenance")
        if role == "admin" and running and running.get("job_id"):
            progress = job_store.latest_event(running["job_id"], "progress")
            if progress:
                running["progress"] = progress
        return payload if role == "admin" else _viewer_dashboard(payload)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/quick-stats")
def quick_stats():
    try:
        return corpus().quick_stats()
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/resolve")
def resolve(payload: ResolveRequest):
    if not any([payload.doi, payload.paper_id, payload.article_id is not None, payload.source_path]):
        raise HTTPException(status_code=400, detail="doi, paper_id, article_id, or source_path is required")
    try:
        return corpus().resolve(**payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/paper-paths")
def paper_paths(payload: PaperPathsRequest):
    if not any([payload.doi, payload.paper_id, payload.article_id is not None]):
        raise HTTPException(status_code=400, detail="doi, paper_id, or article_id is required")
    try:
        return corpus().check_paths(**payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/maintenance/jobs")
def maintenance_jobs(limit: int = 20, user: UserContext = Depends(require_admin)):
    del user
    try:
        return job_store.list_jobs(job_types=_MAINTENANCE_JOB_TYPES, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/maintenance/{action}")
def run_maintenance(action: str, user: UserContext = Depends(require_admin)):
    if action not in MAINTENANCE_ACTIONS:
        raise HTTPException(status_code=404, detail=f"unknown maintenance action: {action}")
    running = [
        job for job in job_store.list_jobs(job_types=_MAINTENANCE_JOB_TYPES, limit=20)
        if job.get("status") in {"queued", "running"}
    ]
    if running:
        current = running[0]
        raise HTTPException(
            status_code=409,
            detail=f"maintenance job already running: {current.get('job_type')} ({current.get('job_id')})",
        )
    job = job_runner.submit(action, {"triggered_by": "admin", "user_id": user.user_id})
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "action": action,
        "stream_url": f"/api/literature-search/jobs/{job['job_id']}/stream",
    }


def _viewer_dashboard(payload: dict) -> dict:
    coverage = payload.get("coverage") or {}
    summary = payload.get("summary") or {}
    vector = payload.get("vector") or {}
    capabilities = payload.get("capabilities") or {}
    return {
        "index_available": bool(payload.get("index_available")),
        "overall_status": _viewer_status(payload),
        "role": "viewer",
        "capabilities": {
            **capabilities,
            "role": "viewer",
            "can_view": True,
            "can_maintain": False,
            "maintenance_actions": [],
        },
        "coverage": coverage,
        "summary": {
            "papers": summary.get("papers") or coverage.get("papers"),
            "documents": summary.get("documents"),
            "sections": summary.get("sections") or coverage.get("sections"),
            "chunks": summary.get("chunks") or coverage.get("chunks"),
        },
        "vector": {"built": bool(vector.get("built"))},
        "warnings": [],
        "failures": list(payload.get("failures") or []),
    }


def _viewer_status(payload: dict) -> str:
    if payload.get("overall_status") == "failed":
        return "failed"
    if payload.get("running_maintenance"):
        return "updating"
    return "healthy" if payload.get("index_available") else "failed"
