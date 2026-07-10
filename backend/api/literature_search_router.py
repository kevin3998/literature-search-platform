from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from modules.literature_search.artifact_store import ArtifactStore
from modules.literature_search.literature_search_shared import job_runner, job_store, service
from modules.literature_search.schemas import (
    AnalysisBundleRequest,
    CompareRequest,
    EvidenceExpandRequest,
    ExtractRequest,
    NotesRequest,
    PackRequest,
    PaperLookupRequest,
    QualityRequest,
    RunRequest,
    SearchRequest,
    SynthesizeRequest,
    TaskRequest,
    VectorBuildRequest,
    VerifyAnswerRequest,
)
from core.permissions import require_admin
from core.session_store import session_store
from core.settings_store import settings_store
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api/literature-search", tags=["literature-search"])


def _job_response(job: dict) -> dict:
    job_id = job["job_id"]
    return {
        "job_id": job_id,
        "status": job["status"],
        "stream_url": f"/api/literature-search/jobs/{job_id}/stream",
    }


def _handle_error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/selfcheck")
def selfcheck():
    try:
        return service.selfcheck()
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/index/status")
def index_status():
    try:
        return service.index_status()
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/index/health")
def index_health():
    try:
        return service.index_health()
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/search")
def search(payload: SearchRequest, user: UserContext = Depends(current_user)):
    try:
        data = payload.model_dump(exclude={"query"})
        defaults = settings_store.retrieval_defaults(user_id=user.user_id)
        for request_key, default_value in defaults.items():
            if request_key not in payload.model_fields_set:
                data[request_key] = default_value
        data = {key: value for key, value in data.items() if value is not None}
        return service.search(payload.query, **data)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/acquire-evidence")
def acquire_evidence(payload: SearchRequest, user: UserContext = Depends(current_user)):
    """Block 2: auditable evidence acquisition packet wrapping raw search.

    Additive endpoint — ``/search`` keeps returning the legacy shape for existing
    consumers; this returns query_intent / query_plan / evidence_candidates /
    coverage / fallback_reason on top of the same underlying retrieval.
    """
    try:
        data = payload.model_dump(exclude={"query"})
        defaults = settings_store.retrieval_defaults(user_id=user.user_id)
        for request_key, default_value in defaults.items():
            if request_key not in payload.model_fields_set:
                data[request_key] = default_value
        data = {key: value for key, value in data.items() if value is not None}
        return service.acquire_evidence(payload.query, **data)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/papers/{article_id}")
def paper_by_article_id(article_id: int):
    try:
        return service.paper_show(article_id=article_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/papers/show")
def paper_show(payload: PaperLookupRequest):
    try:
        return service.paper_show(**payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/papers/sections")
def paper_sections(payload: PaperLookupRequest):
    try:
        return service.paper_sections(**payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/papers/chunks")
def paper_chunks(payload: PaperLookupRequest):
    try:
        return service.paper_chunks(**payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/evidence/expand")
def evidence_expand(payload: EvidenceExpandRequest):
    try:
        return service.evidence_expand(**payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/pack")
def pack(payload: PackRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("pack", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.post("/task/plan")
def task_plan(payload: TaskRequest):
    try:
        return service.task_plan(payload.question, budget=payload.budget, scope=payload.scope)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/task/run")
def task_run(payload: TaskRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("task_run", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.post("/run")
def run(payload: RunRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("run", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.get("/runs")
def runs(limit: int = 20):
    try:
        return service.run_list(limit=limit)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/runs/{run_id}")
def run_show(run_id: str):
    try:
        return service.run_show(run_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/runs/{run_id}/resume")
def run_resume(run_id: str, user: UserContext = Depends(current_user)):
    job = job_runner.submit("run_resume", {"run_id": run_id, "user_id": user.user_id})
    return _job_response(job)


@router.post("/extract")
def extract(payload: ExtractRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("extract", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.post("/compare")
def compare(payload: CompareRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("compare", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.post("/analysis/bundle")
def analysis_bundle(payload: AnalysisBundleRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("analysis_bundle", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.get("/analysis/{bundle_id}")
def analysis_show(bundle_id: str):
    try:
        return service.analysis_show(bundle_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/verify-answer")
def verify_answer(payload: VerifyAnswerRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("verify_answer", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.post("/notes/build")
def notes_build(payload: NotesRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("notes_build", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.post("/synthesize")
def synthesize(payload: SynthesizeRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("synthesize", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.post("/quality")
def quality(payload: QualityRequest, user: UserContext = Depends(current_user)):
    job = job_runner.submit("quality", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.get("/vector/status")
def vector_status():
    try:
        return service.vector_status()
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/vector/build")
def vector_build(payload: VectorBuildRequest, user: UserContext = Depends(require_admin)):
    job = job_runner.submit("vector_build", {**payload.model_dump(), "user_id": user.user_id})
    return _job_response(job)


@router.get("/artifacts")
def artifacts(user: UserContext = Depends(current_user)):
    try:
        items = [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in ArtifactStore(service.data_dir).list_artifacts()
        ]
        for item in items:
            session_store.record_artifact(item, user_id=user.user_id)
        return items
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/artifacts/{artifact_id}")
def artifact(artifact_id: str, user: UserContext = Depends(current_user)):
    try:
        item = ArtifactStore(service.data_dir).read_artifact(artifact_id)
        session_store.record_artifact(item, user_id=user.user_id)
        return item
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/jobs/{job_id}")
def job(job_id: str, user: UserContext = Depends(current_user)):
    try:
        return job_store.get(job_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str, user: UserContext = Depends(current_user)):
    try:
        job_store.get(job_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)

    async def events():
        index = 0
        while True:
            emitted = job_store.events(job_id, after=index, user_id=user.user_id)
            for event in emitted:
                index += 1
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    return
            await asyncio.sleep(0.2)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
