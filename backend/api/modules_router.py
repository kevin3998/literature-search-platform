from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi import File, UploadFile
from pydantic import BaseModel

from core.registry import registry
from core.session_store import session_store
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api", tags=["modules"])

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ACTIVE_ATTACHMENTS = 5


@router.get("/modules")
def list_modules():
    return registry.list()


@router.get("/me")
def me(user: UserContext = Depends(current_user)):
    return {
        "user_id": user.user_id,
        "subject": user.subject,
        "display_name": user.display_name,
        "auth_mode": user.auth_mode,
        "role": user.role,
        "status": user.status,
        "email": user.email,
    }


@router.get("/sessions")
def list_sessions(module_id: str | None = None, include_archived: bool = False, user: UserContext = Depends(current_user)):
    return session_store.list_sessions(module_id, include_archived=include_archived, user_id=user.user_id)


class SessionCreateRequest(BaseModel):
    module_id: str
    title: str = "新对话"


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    status: str | None = None
    archived: bool | None = None
    favorite: bool | None = None
    pinned: bool | None = None
    tags: list[str] | None = None


class FavoriteRequest(BaseModel):
    favorite: bool = True


class ArchiveRequest(BaseModel):
    archived: bool = True


class PinRequest(BaseModel):
    pinned: bool = True


class TagsRequest(BaseModel):
    tags: list[str] = []


class PaperStatusRequest(BaseModel):
    paper_id: str
    status: str  # candidate | accepted | excluded | needs_review
    note: str | None = None
    turn_id: str | None = None


class EvidenceStatusRequest(BaseModel):
    evidence_item_id: str
    status: str  # candidate | accepted | excluded | needs_review
    note: str | None = None
    turn_id: str | None = None


class ResearchStateUpdateRequest(BaseModel):
    topic: str | None = None
    objective: str | None = None
    stage: str | None = None
    excluded_directions: list[str] | None = None
    open_questions: list[str] | None = None
    completed_questions: list[str] | None = None
    next_actions: list[str] | None = None
    turn_id: str | None = None


@router.post("/sessions")
def create_session(payload: SessionCreateRequest, user: UserContext = Depends(current_user)):
    return session_store.create_session(module_id=payload.module_id, title=payload.title, user_id=user.user_id)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.get_session(session_id, user_id=user.user_id))


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: SessionUpdateRequest, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.update_session(session_id, user_id=user.user_id, **payload.model_dump(exclude_none=True)))


@router.post("/sessions/{session_id}/archive")
def archive_session(session_id: str, payload: ArchiveRequest, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.set_archived(session_id, payload.archived, user_id=user.user_id))


@router.post("/sessions/{session_id}/favorite")
def favorite_session(session_id: str, payload: FavoriteRequest, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.set_favorite(session_id, payload.favorite, user_id=user.user_id))


@router.post("/sessions/{session_id}/pin")
def pin_session(session_id: str, payload: PinRequest, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.set_pinned(session_id, payload.pinned, user_id=user.user_id))


@router.post("/sessions/{session_id}/tags")
def tag_session(session_id: str, payload: TagsRequest, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.set_tags(session_id, payload.tags, user_id=user.user_id))


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.delete_session(session_id, user_id=user.user_id))


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.messages(session_id, user_id=user.user_id))


@router.get("/sessions/{session_id}/bundle")
def session_bundle(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.bundle(session_id, user_id=user.user_id))


@router.get("/sessions/{session_id}/attachments")
def session_attachments(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.list_attachments(session_id, user_id=user.user_id))


@router.post("/sessions/{session_id}/attachments")
async def upload_session_attachment(
    session_id: str,
    file: UploadFile = File(...),
    user: UserContext = Depends(current_user),
):
    _session_or_404(lambda: session_store.get_session(session_id, user_id=user.user_id))
    active = session_store.list_attachments(session_id, user_id=user.user_id)
    if len(active) >= MAX_ACTIVE_ATTACHMENTS:
        raise HTTPException(status_code=400, detail=f"当前会话最多保留 {MAX_ACTIVE_ATTACHMENTS} 个附件，请先移除旧附件。")
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="附件超过 20MB 限制，请压缩或拆分后再上传。")
    filename = file.filename or "attachment"
    try:
        text = _extract_attachment_text(filename, file.content_type or "", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - return a user-readable parse failure
        raise HTTPException(status_code=400, detail=f"附件解析失败：{exc}") from exc
    if not text.strip():
        raise HTTPException(status_code=400, detail="附件未解析出可用文本。")
    return session_store.create_attachment(
        session_id,
        user_id=user.user_id,
        filename=filename,
        content_type=file.content_type or _content_type_for_filename(filename),
        extracted_text=text,
    )


@router.delete("/sessions/{session_id}/attachments/{attachment_id}")
def delete_session_attachment(session_id: str, attachment_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.delete_attachment(session_id, attachment_id, user_id=user.user_id))


@router.delete("/sessions/{session_id}/last-turn")
def delete_last_turn(session_id: str, user: UserContext = Depends(current_user)):
    """Remove the most recent turn so the last question can be re-edited and resent."""
    user_text = _session_or_404(lambda: session_store.delete_last_turn(session_id, user_id=user.user_id))
    return {"deleted": user_text is not None, "user_text": user_text or ""}


@router.get("/sessions/{session_id}/context")
def session_context(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.get_context(session_id, user_id=user.user_id))


@router.get("/sessions/{session_id}/research-state")
def session_research_state(session_id: str, user: UserContext = Depends(current_user)):
    """Block 6a: Shared Research State for a 课题 — authored facts + derived
    candidate papers / evidence pool / coverage gaps, for the workspace panel."""
    return _session_or_404(lambda: session_store.research_state(session_id, user_id=user.user_id))


@router.patch("/sessions/{session_id}/research-state")
def update_research_state(session_id: str, payload: ResearchStateUpdateRequest, user: UserContext = Depends(current_user)):
    """Block 6b: author the non-derivable research-state facts (objective / stage /
    excluded directions / open+completed questions / next actions). Logs provenance."""
    fields = payload.model_dump(exclude_none=True)
    turn_id = fields.pop("turn_id", None)
    _session_or_404(lambda: session_store.update_research_state(session_id, source="user", turn_id=turn_id, user_id=user.user_id, **fields))
    return _session_or_404(lambda: session_store.research_state(session_id, user_id=user.user_id))


@router.post("/sessions/{session_id}/paper-status")
def set_paper_status(session_id: str, payload: PaperStatusRequest, user: UserContext = Depends(current_user)):
    """Block 6b: curate one candidate paper (accept / exclude / needs_review).
    Returns the refreshed research state so the panel re-renders in one round-trip."""
    _session_or_404(
        lambda: session_store.set_paper_status(
            session_id,
            payload.paper_id,
            payload.status,
            note=payload.note,
            source="user",
            turn_id=payload.turn_id,
            user_id=user.user_id,
        )
    )
    return _session_or_404(lambda: session_store.research_state(session_id, user_id=user.user_id))


@router.post("/sessions/{session_id}/evidence-status")
def set_evidence_status(session_id: str, payload: EvidenceStatusRequest, user: UserContext = Depends(current_user)):
    """Literature Search phase 3: curate one session-local evidence item."""
    try:
        _session_or_404(
            lambda: session_store.set_evidence_status(
                session_id,
                payload.evidence_item_id,
                payload.status,
                note=payload.note,
                source="user",
                turn_id=payload.turn_id,
                user_id=user.user_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_or_404(lambda: session_store.research_state(session_id, user_id=user.user_id))


@router.get("/sessions/{session_id}/artifacts")
def session_artifacts(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.artifacts_for_session(session_id, user_id=user.user_id))


@router.get("/sessions/{session_id}/jobs")
def session_jobs(session_id: str, user: UserContext = Depends(current_user)):
    return _session_or_404(lambda: session_store.jobs_for_session(session_id, user_id=user.user_id))


def _enriched_record(session_id: str, *, user_id: str) -> dict:
    """Build the audit record, backfilling canonical paper_id / index_version."""
    record = session_store.build_record(session_id, user_id=user_id)
    try:
        from modules.literature_search.corpus import CorpusService, enrich_record_identity
        from modules.literature_search.literature_search_shared import service

        enrich_record_identity(record, CorpusService(service))
    except Exception:  # noqa: BLE001 - identity enrichment is best-effort
        pass
    return record


@router.get("/sessions/{session_id}/record")
def session_record(session_id: str, user: UserContext = Depends(current_user)):
    """Structured per-turn audit chain: question ↔ retrieval ↔ evidence ↔ artifacts."""
    return _session_or_404(lambda: _enriched_record(session_id, user_id=user.user_id))


@router.get("/sessions/{session_id}/export")
def session_export(session_id: str, user: UserContext = Depends(current_user)):
    """Citable Markdown report of the whole session (answer + evidence + sources)."""
    from core.report import render_markdown_report, report_filename

    record = _session_or_404(lambda: _enriched_record(session_id, user_id=user.user_id))
    return {
        "filename": report_filename(record),
        "format": "markdown",
        "content": render_markdown_report(record),
    }


def _session_or_404(func):
    try:
        return func()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


def _content_type_for_filename(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"


def _extract_attachment_text(filename: str, content_type: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".txt") or content_type.startswith("text/plain"):
        return _decode_text(data)
    if lower.endswith(".pdf") or content_type == "application/pdf":
        return _extract_pdf_text(data)
    raise ValueError("仅支持上传 .txt 或 .pdf 文件。")


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    parts: list[str] = []
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            parts.append(f"\n\n[PDF 第 {index + 1} 页]\n{text.strip()}")
    return "\n".join(parts).strip()
