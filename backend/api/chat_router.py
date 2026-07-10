from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from core.registry import registry
from core.schemas import ChatMessage, ChatRequest
from core.session_store import session_store
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api", tags=["chat"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, user: UserContext = Depends(current_user)):
    module = registry.get(payload.module_id)
    if module is None:
        raise HTTPException(status_code=404, detail=f"未找到模块: {payload.module_id}")

    try:
        history = payload.history or session_store.get_history(payload.session_id, user_id=user.user_id)
        session_store.touch(payload.session_id, payload.module_id, title=payload.message[:24], user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    options = dict(payload.options or {})
    attachment_ids = [str(item) for item in (options.get("attachment_ids") or []) if item]
    attachments_context = session_store.attachments_context(payload.session_id, attachment_ids, user_id=user.user_id)
    # Block 6c: which specialist role (subagent) is handling this turn — recorded
    # so the timeline / audit can show "由哪个 subagent 响应" and it restores.
    turn_role = options.get("role") or "general"
    turn_id = session_store.create_turn(
        payload.session_id, query=payload.message, answer_mode="chat", role=turn_role, user_id=user.user_id
    )
    user_msg = ChatMessage(role="user", content=payload.message)
    user_meta = {}
    if attachments_context:
        user_meta["attachments"] = [
            {
                "attachment_id": item.get("attachment_id"),
                "filename": item.get("filename"),
                "status": item.get("status"),
                "char_count": item.get("char_count"),
            }
            for item in attachments_context
        ]
    session_store.append(payload.session_id, user_msg, turn_id=turn_id, metadata=user_meta, user_id=user.user_id)
    memory_context = session_store.get_context(payload.session_id, user_id=user.user_id)
    if attachments_context:
        memory_context = {**memory_context, "session_attachments": attachments_context}
        options["_attachments_context"] = attachments_context
    options["_memory_context"] = memory_context
    options["_turn_id"] = turn_id
    options["_user_id"] = user.user_id
    options["_user_subject"] = user.subject

    async def event_generator():
        answer_parts: list[str] = []
        citation_meta: dict | None = None
        route_meta: dict | None = None
        failure_meta: dict | None = None
        attachment_meta: dict | None = (
            {
                "attachment_count": len(attachments_context),
                "filenames": [item.get("filename") or "附件" for item in attachments_context],
            }
            if attachments_context
            else None
        )
        library_status_meta: dict | None = None
        error_message: str | None = None
        search_payload: dict = {"query": payload.message, "query_plan": {}, "results": []}
        try:
            if attachment_meta:
                yield _sse({"type": "attachment_context", **attachment_meta})
            async for event in module.handle_chat(
                payload.session_id, payload.message, history, options
            ):
                if event.get("type") == "token":
                    answer_parts.append(event["text"])
                elif event.get("type") == "answer_reset":
                    # Discard tool-turn narration so the persisted answer is only
                    # the final synthesized text (mirrors the loop's answer_reset).
                    answer_parts.clear()
                elif event.get("type") == "search_meta":
                    search_payload["query_plan"] = event.get("query_plan") or {}
                    search_payload["filters"] = search_payload["query_plan"].get("filters_applied") or {}
                elif event.get("type") == "papers":
                    # The agent path already persists search results itself; only the
                    # legacy summary path relies on chat_router to record them.
                    if not options.get("_agent_records_search"):
                        search_payload["results"] = event.get("papers") or []
                        session_store.record_search_result(payload.session_id, turn_id, search_payload, user_id=user.user_id)
                elif event.get("type") == "citation":
                    citation_meta = event
                elif event.get("type") == "intent_route":
                    route_meta = {"route": event.get("route"), "label": event.get("label")}
                elif event.get("type") == "failure_explanation":
                    failure_meta = {"code": event.get("code"), "message": event.get("message")}
                elif event.get("type") == "attachment_context":
                    incoming_attachment_meta = {
                        "attachment_count": event.get("attachment_count"),
                        "filenames": event.get("filenames") or [],
                    }
                    already_emitted = incoming_attachment_meta == attachment_meta
                    attachment_meta = incoming_attachment_meta
                    if already_emitted:
                        continue
                elif event.get("type") == "library_status":
                    library_status_meta = {"used_library_stats": True, "stats": event.get("stats") or {}}
                elif event.get("type") == "artifact":
                    session_store.record_artifact(
                        event,
                        session_id=payload.session_id,
                        turn_id=turn_id,
                        link_type=event.get("artifact_type") or "artifact",
                        user_id=user.user_id,
                    )
                elif event.get("type") == "error":
                    error_message = event.get("message") or "请求失败"
                yield _sse(event)
        except Exception as exc:  # 防止单个模块异常导致整个连接挂死
            yield _sse({"type": "error", "message": str(exc)})
            yield _sse({"type": "done"})
            if answer_parts:
                session_store.append(
                    payload.session_id,
                    ChatMessage(role="assistant", content="".join(answer_parts)),
                    turn_id=turn_id,
                    error=True,
                    user_id=user.user_id,
                )
            session_store.fail_turn(turn_id)
            return

        if answer_parts or error_message:
            meta: dict = {"role_used": turn_role}
            if citation_meta:
                meta["citation"] = {k: v for k, v in citation_meta.items() if k != "resolved_citations"}
            if route_meta:
                meta.update(route_meta)
            if failure_meta:
                meta["failure_code"] = failure_meta.get("code")
                meta["failure_message"] = failure_meta.get("message")
            if attachment_meta:
                meta["used_attachments"] = attachment_meta
            if library_status_meta:
                meta.update(library_status_meta)
            assistant_message_id = session_store.append(
                payload.session_id,
                ChatMessage(
                    role="assistant",
                    content="".join(answer_parts) if answer_parts else f"⚠ {error_message}",
                ),
                turn_id=turn_id,
                metadata=meta,
                error=bool(error_message and not answer_parts),
                user_id=user.user_id,
            )
            if citation_meta and citation_meta.get("resolved_citations"):
                session_store.record_message_citations(assistant_message_id, citation_meta.get("resolved_citations") or [])
        if error_message:
            session_store.fail_turn(turn_id)
        else:
            session_store.complete_turn(turn_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
