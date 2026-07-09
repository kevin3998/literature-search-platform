"""Block 7/10: workflow (Deep Research Task Engine) HTTP surface."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.session_store import session_store
from core.user_context import UserContext, current_user
from modules.literature_search.literature_search_shared import job_store
from modules.evidence_workflow.task_profiles import list_task_profiles
from modules.workflow.shared import workflow_orchestrator, workflow_store
from modules.workflow.templates import list_categories, list_templates

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class CreateWorkflowRequest(BaseModel):
    template_id: str
    topic: Optional[str] = None
    scope: str = "library"
    title: Optional[str] = None
    session_id: Optional[str] = None
    task_profile_id: Optional[str] = None
    scope_options: dict[str, Any] = Field(default_factory=dict)


def _handle_error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


# Templates route must precede /{workflow_id} so it isn't swallowed as an id.
@router.get("/templates")
def templates():
    return {
        "categories": list_categories(),
        "templates": list_templates(),
        "task_profiles": list_task_profiles(include_stubs=True),
    }


@router.post("")
def create(payload: CreateWorkflowRequest, user: UserContext = Depends(current_user)):
    try:
        if payload.session_id:
            session_store.get_session(payload.session_id, user_id=user.user_id)
        create_kwargs = {
            "topic": payload.topic,
            "scope": payload.scope,
            "title": payload.title,
            "session_id": payload.session_id,
            "task_profile_id": payload.task_profile_id,
            "scope_options": payload.scope_options,
            "user_id": user.user_id,
        }
        try:
            return workflow_store.create(payload.template_id, **create_kwargs)
        except TypeError as exc:
            if "user_id" not in str(exc):
                raise
            create_kwargs.pop("user_id", None)
            return workflow_store.create(payload.template_id, **create_kwargs)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("")
def list_workflows(limit: int = 50, user: UserContext = Depends(current_user)):
    try:
        return {"workflows": workflow_store.list(limit=limit, user_id=user.user_id)}
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/{workflow_id}/artifacts/{artifact_id:path}")
def get_workflow_artifact(workflow_id: str, artifact_id: str, user: UserContext = Depends(current_user)):
    try:
        workflow_store.get(workflow_id, user_id=user.user_id)
        return workflow_orchestrator.artifact_preview(workflow_id, artifact_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/{workflow_id}/insights")
def get_workflow_insights(workflow_id: str, user: UserContext = Depends(current_user)):
    try:
        workflow_store.get(workflow_id, user_id=user.user_id)
        return workflow_orchestrator.workflow_insights(workflow_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str, user: UserContext = Depends(current_user)):
    try:
        workflow_store.get(workflow_id, user_id=user.user_id)
        return workflow_orchestrator.detail(workflow_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/{workflow_id}/start")
def start_workflow(workflow_id: str, user: UserContext = Depends(current_user)):
    try:
        workflow_store.get(workflow_id, user_id=user.user_id)
        return workflow_orchestrator.start(workflow_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/{workflow_id}/resume")
def resume_workflow(workflow_id: str, user: UserContext = Depends(current_user)):
    try:
        workflow_store.get(workflow_id, user_id=user.user_id)
        return workflow_orchestrator.start(workflow_id, resume=True)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/{workflow_id}/pause")
def pause_workflow(workflow_id: str, user: UserContext = Depends(current_user)):
    try:
        workflow_store.get(workflow_id, user_id=user.user_id)
        workflow_orchestrator.request_pause(workflow_id)
        return {"workflow_id": workflow_id, "pause_requested": True}
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: str, user: UserContext = Depends(current_user)):
    try:
        workflow_store.soft_delete(workflow_id, user_id=user.user_id)
        return {"workflow_id": workflow_id, "deleted": True}
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/{workflow_id}/stream")
async def stream_workflow(workflow_id: str, after: int = 0, user: UserContext = Depends(current_user)):
    try:
        wf = workflow_store.get(workflow_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
    orch_job_id = (wf.get("engine_ref") or {}).get("orchestrator_job_id")
    if not orch_job_id:
        raise HTTPException(status_code=409, detail="workflow has not been started")

    async def events():
        index = max(0, after)
        while True:
            for event in job_store.events(orch_job_id, after=index, user_id=user.user_id):
                index = int(event.get("_event_index", index)) + 1
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    return
            await asyncio.sleep(0.2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
