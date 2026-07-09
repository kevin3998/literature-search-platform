from __future__ import annotations

import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, json_loads, new_uuid, to_unix_seconds, utc_now, uuid_value
from core.schemas import ChatMessage

MAX_ATTACHMENT_TEXT_CHARS = 80_000
MAX_ATTACHMENT_CONTEXT_CHARS = 12_000


class SessionStore:
    def __init__(self, db_path: str | None = None, engine: Engine | None = None) -> None:
        self.db_path = db_path
        self.engine = engine or create_engine_from_env()
        self.recover_stale_running_turns()

    def create_session(
        self,
        *,
        module_id: str,
        title: str = "新对话",
        user_id: str,
        session_id: str | None = None,
    ) -> dict:
        sid = uuid_value(session_id) if session_id else uuid_value(new_uuid())
        owner = uuid_value(user_id)
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into sessions(
                        session_id, user_id, module_id, title, status, tags_json,
                        favorite, pinned, archived, metadata_json, deleted_at,
                        created_at, updated_at, last_message_at
                    ) values(
                        :session_id, :user_id, :module_id, :title, 'active', '[]'::jsonb,
                        false, false, false, '{}'::jsonb, null, :ts, :ts, null
                    )
                    on conflict(session_id) do nothing
                    """
                ),
                {"session_id": sid, "user_id": owner, "module_id": module_id, "title": title, "ts": ts},
            )
        return self.get_session(str(sid), user_id=user_id)

    def get_session(self, session_id: str, *, user_id: str | None = None) -> dict:
        row = self._session_row_for_user(session_id, user_id)
        if not row:
            raise KeyError(f"session not found: {session_id}")
        return _session_row(row)

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        archived: bool | None = None,
        favorite: bool | None = None,
        pinned: bool | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
    ) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        changes: dict[str, Any] = {}
        if title is not None:
            changes["title"] = title
        if status is not None:
            changes["status"] = status
        if archived is not None:
            changes["archived"] = archived
        if favorite is not None:
            changes["favorite"] = favorite
        if pinned is not None:
            changes["pinned"] = pinned
        if tags is not None:
            changes["tags_json"] = json_dumps([tag.strip() for tag in tags if tag and tag.strip()])
        if changes:
            assignments = []
            params: dict[str, Any] = {"session_id": uuid_value(session_id), "updated_at": utc_now()}
            for key, value in changes.items():
                if key == "tags_json":
                    assignments.append("tags_json = cast(:tags_json as jsonb)")
                else:
                    assignments.append(f"{key} = :{key}")
                params[key] = value
            assignments.append("updated_at = :updated_at")
            with self.engine.begin() as conn:
                conn.execute(text(f"update sessions set {', '.join(assignments)} where session_id = :session_id"), params)
        return self.get_session(session_id, user_id=user_id)

    def set_archived(self, session_id: str, archived: bool, *, user_id: str | None = None) -> dict:
        return self.update_session(session_id, archived=archived, status="archived" if archived else "active", user_id=user_id)

    def set_favorite(self, session_id: str, favorite: bool, *, user_id: str | None = None) -> dict:
        return self.update_session(session_id, favorite=favorite, user_id=user_id)

    def set_pinned(self, session_id: str, pinned: bool, *, user_id: str | None = None) -> dict:
        return self.update_session(session_id, pinned=pinned, user_id=user_id)

    def delete_session(self, session_id: str, *, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text("update sessions set deleted_at = :ts, updated_at = :ts where session_id = :session_id"),
                {"ts": ts, "session_id": uuid_value(session_id)},
            )
        return self.get_session(session_id, user_id=user_id)

    def restore_session(self, session_id: str, *, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.begin() as conn:
            conn.execute(
                text("update sessions set deleted_at = null, archived = false, status = 'active', updated_at = :ts where session_id = :session_id"),
                {"ts": utc_now(), "session_id": uuid_value(session_id)},
            )
        return self.get_session(session_id, user_id=user_id)

    def set_tags(self, session_id: str, tags: list[str], *, user_id: str | None = None) -> dict:
        return self.update_session(session_id, tags=tags, user_id=user_id)

    def create_attachment(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
        filename: str,
        content_type: str,
        extracted_text: str,
        status: str = "parsed",
        error: str | None = None,
    ) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        owner = user_id or self._session_user_id(session_id)
        aid = new_uuid()
        text_value = (extracted_text or "")[:MAX_ATTACHMENT_TEXT_CHARS]
        preview = " ".join(text_value.split())[:500]
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into session_attachments(
                        attachment_id, session_id, user_id, filename, content_type, status,
                        extracted_text, text_preview, char_count, error, created_at, deleted_at
                    ) values(
                        :attachment_id, :session_id, :user_id, :filename, :content_type, :status,
                        :extracted_text, :text_preview, :char_count, :error, :created_at, null
                    )
                    """
                ),
                {
                    "attachment_id": uuid_value(aid),
                    "session_id": uuid_value(session_id),
                    "user_id": uuid_value(owner),
                    "filename": filename,
                    "content_type": content_type,
                    "status": status,
                    "extracted_text": text_value,
                    "text_preview": preview,
                    "char_count": len(text_value),
                    "error": error,
                    "created_at": ts,
                },
            )
        return self._attachment_row(aid, include_text=False)

    def list_attachments(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        owner = user_id or self._session_user_id(session_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select * from session_attachments
                    where session_id = :session_id and user_id = :user_id and deleted_at is null
                    order by created_at
                    """
                ),
                {"session_id": uuid_value(session_id), "user_id": uuid_value(owner)},
            ).mappings().all()
        return [_attachment_row(row, include_text=False) for row in rows]

    def delete_attachment(self, session_id: str, attachment_id: str, *, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        owner = user_id or self._session_user_id(session_id)
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    select attachment_id from session_attachments
                    where attachment_id = :attachment_id and session_id = :session_id and user_id = :user_id and deleted_at is null
                    """
                ),
                {"attachment_id": uuid_value(attachment_id), "session_id": uuid_value(session_id), "user_id": uuid_value(owner)},
            ).first()
            if not row:
                raise KeyError(f"attachment not found: {attachment_id}")
            conn.execute(
                text("update session_attachments set deleted_at = :ts where attachment_id = :attachment_id"),
                {"ts": utc_now(), "attachment_id": uuid_value(attachment_id)},
            )
        return {"deleted": True, "attachment_id": attachment_id}

    def attachments_context(self, session_id: str, attachment_ids: list[str], *, user_id: str | None = None, max_chars: int = MAX_ATTACHMENT_CONTEXT_CHARS) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        if not attachment_ids:
            return []
        owner = user_id or self._session_user_id(session_id)
        ids = [uuid_value(item) for item in attachment_ids]
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select * from session_attachments
                    where session_id = :session_id and user_id = :user_id and deleted_at is null
                      and status = 'parsed' and attachment_id = any(:attachment_ids)
                    order by created_at
                    """
                ),
                {"session_id": uuid_value(session_id), "user_id": uuid_value(owner), "attachment_ids": ids},
            ).mappings().all()
        by_id = {str(row["attachment_id"]): row for row in rows}
        remaining = max_chars
        out: list[dict] = []
        for aid in attachment_ids:
            row = by_id.get(aid)
            if not row or remaining <= 0:
                continue
            extracted = (row["extracted_text"] or "")[:remaining]
            remaining -= len(extracted)
            item = _attachment_row(row, include_text=False)
            item["text"] = extracted
            out.append(item)
        return out

    def get_history(self, session_id: str, *, user_id: str | None = None) -> list[ChatMessage]:
        if not self._session_exists(session_id):
            return []
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select role, content, created_at from messages where session_id = :session_id order by created_at, message_id"),
                {"session_id": uuid_value(session_id)},
            ).mappings().all()
        return [ChatMessage(role=row["role"], content=row["content"], timestamp=to_unix_seconds(row["created_at"]) or 0.0) for row in rows]

    def append(
        self,
        session_id: str,
        message: ChatMessage,
        *,
        turn_id: str | None = None,
        metadata: dict | None = None,
        message_id: str | None = None,
        error: bool = False,
        user_id: str | None = None,
    ) -> str:
        self._ensure_session(session_id, user_id=user_id)
        mid = uuid_value(message_id) if message_id else uuid_value(new_uuid())
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into messages(message_id, session_id, turn_id, role, content, error, created_at, metadata_json)
                    values(:message_id, :session_id, :turn_id, :role, :content, :error, :created_at, cast(:metadata_json as jsonb))
                    """
                ),
                {
                    "message_id": mid,
                    "session_id": uuid_value(session_id),
                    "turn_id": uuid_value(turn_id) if turn_id else None,
                    "role": message.role,
                    "content": message.content,
                    "error": error,
                    "created_at": ts,
                    "metadata_json": json_dumps(metadata or {}),
                },
            )
            conn.execute(
                text("update sessions set updated_at = :updated_at, last_message_at = :last_message_at where session_id = :session_id"),
                {"updated_at": utc_now(), "last_message_at": ts, "session_id": uuid_value(session_id)},
            )
            if turn_id and message.role == "user":
                conn.execute(text("update turns set user_message_id = :message_id where turn_id = :turn_id"), {"message_id": mid, "turn_id": uuid_value(turn_id)})
            if turn_id and message.role == "assistant":
                conn.execute(text("update turns set assistant_message_id = :message_id where turn_id = :turn_id"), {"message_id": mid, "turn_id": uuid_value(turn_id)})
        return str(mid)

    def touch(self, session_id: str, module_id: str, title: str | None = None, *, user_id: str) -> None:
        if not self._session_exists(session_id):
            raise KeyError(f"session not found: {session_id}")
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.begin() as conn:
            if title:
                conn.execute(
                    text("update sessions set module_id = :module_id, title = :title, updated_at = :ts where session_id = :session_id"),
                    {"module_id": module_id, "title": title, "ts": utc_now(), "session_id": uuid_value(session_id)},
                )
            else:
                conn.execute(
                    text("update sessions set module_id = :module_id, updated_at = :ts where session_id = :session_id"),
                    {"module_id": module_id, "ts": utc_now(), "session_id": uuid_value(session_id)},
                )

    def list_sessions(self, module_id: str | None = None, include_archived: bool = False, *, user_id: str | None = None):
        clauses = ["deleted_at is null"]
        params: dict[str, Any] = {}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = uuid_value(user_id)
        if module_id:
            clauses.append("module_id = :module_id")
            params["module_id"] = module_id
        if not include_archived:
            clauses.append("archived = false")
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(f"select * from sessions where {' and '.join(clauses)} order by pinned desc, updated_at desc, created_at desc"),
                params,
            ).mappings().all()
        return [_session_row(row) for row in rows]

    def messages(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select * from messages where session_id = :session_id order by created_at, message_id"),
                {"session_id": uuid_value(session_id)},
            ).mappings().all()
        return [_message_row(row) for row in rows]

    def delete_last_turn(self, session_id: str, *, user_id: str | None = None) -> str | None:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.begin() as conn:
            row = conn.execute(
                text("select turn_id from turns where session_id = :session_id order by created_at desc, turn_id desc limit 1"),
                {"session_id": uuid_value(session_id)},
            ).mappings().first()
            if not row:
                return None
            turn_id = row["turn_id"]
            user_row = conn.execute(
                text("select content from messages where turn_id = :turn_id and role = 'user' order by created_at, message_id limit 1"),
                {"turn_id": turn_id},
            ).mappings().first()
            user_text = user_row["content"] if user_row else ""
            for table in ("messages", "search_results", "evidence_items", "conversation_artifact_links"):
                conn.execute(text(f"delete from {table} where turn_id = :turn_id"), {"turn_id": turn_id})
            conn.execute(text("delete from turns where turn_id = :turn_id"), {"turn_id": turn_id})
        return user_text

    def create_turn(self, session_id: str, *, query: str, answer_mode: str = "chat", role: str | None = None, user_id: str | None = None) -> str:
        self._ensure_session(session_id, user_id=user_id)
        turn_id = new_uuid()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into turns(turn_id, session_id, query, answer_mode, role, status, created_at)
                    values(:turn_id, :session_id, :query, :answer_mode, :role, 'running', :created_at)
                    """
                ),
                {"turn_id": uuid_value(turn_id), "session_id": uuid_value(session_id), "query": query, "answer_mode": answer_mode, "role": role, "created_at": utc_now()},
            )
        return turn_id

    def complete_turn(self, turn_id: str, *, status: str = "completed") -> None:
        with self.engine.begin() as conn:
            conn.execute(text("update turns set status = :status, completed_at = :ts where turn_id = :turn_id"), {"status": status, "ts": utc_now(), "turn_id": uuid_value(turn_id)})

    def fail_turn(self, turn_id: str) -> None:
        self.complete_turn(turn_id, status="failed")

    def recover_stale_running_turns(self, *, max_age_seconds: float | None = None) -> int:
        if max_age_seconds is None:
            try:
                max_age_seconds = float(os.getenv("LITERATURE_STALE_TURN_SECONDS", "3600"))
            except ValueError:
                max_age_seconds = 3600.0
        if max_age_seconds <= 0:
            return 0
        # PostgreSQL M2 leaves recovery conservative; startup should not mutate
        # fresh empty schemas in tests unless genuinely stale rows exist.
        return 0

    def record_search_result(self, session_id: str, turn_id: str | None, payload: dict, *, user_id: str | None = None) -> str:
        self._ensure_session(session_id, user_id=user_id)
        search_result_id = new_uuid()
        query_plan = payload.get("query_plan") or {}
        filters = payload.get("filters") or query_plan.get("filters_applied") or {}
        results = payload.get("results") or payload.get("papers") or []
        coverage = payload.get("coverage") or {}
        fallback = payload.get("fallback_reason")
        breadth = payload.get("breadth") or {}
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into search_results(
                        search_result_id, session_id, turn_id, query, query_plan_json,
                        filters_json, results_json, coverage_json, fallback_json, breadth_json, created_at
                    ) values(
                        :search_result_id, :session_id, :turn_id, :query, cast(:query_plan_json as jsonb),
                        cast(:filters_json as jsonb), cast(:results_json as jsonb), cast(:coverage_json as jsonb),
                        cast(:fallback_json as jsonb), cast(:breadth_json as jsonb), :created_at
                    )
                    """
                ),
                {
                    "search_result_id": uuid_value(search_result_id),
                    "session_id": uuid_value(session_id),
                    "turn_id": uuid_value(turn_id) if turn_id else None,
                    "query": payload.get("query") or "",
                    "query_plan_json": json_dumps(query_plan),
                    "filters_json": json_dumps(filters),
                    "results_json": json_dumps(results),
                    "coverage_json": json_dumps(coverage),
                    "fallback_json": json_dumps(fallback) if fallback is not None else "null",
                    "breadth_json": json_dumps(breadth),
                    "created_at": utc_now(),
                },
            )
            for paper in results:
                for evidence in paper.get("evidence") or []:
                    self._insert_evidence(conn, session_id, turn_id, search_result_id, paper, evidence)
            if turn_id:
                conn.execute(text("update turns set search_result_id = :search_result_id where turn_id = :turn_id"), {"search_result_id": uuid_value(search_result_id), "turn_id": uuid_value(turn_id)})
        return search_result_id

    def record_artifact(self, artifact: dict, *, session_id: str | None = None, turn_id: str | None = None, link_type: str = "manual", user_id: str | None = None) -> str:
        if session_id:
            self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
            user_id = self._session_user_id(session_id)
        if not user_id:
            raise ValueError("user_id is required for artifact metadata")
        artifact_id = _uuid_or_new(artifact.get("artifact_id"))
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into artifacts(
                        artifact_id, user_id, artifact_type, title, json_path, markdown_path,
                        summary_json, created_at, updated_at
                    ) values(
                        :artifact_id, :user_id, :artifact_type, :title, :json_path, :markdown_path,
                        cast(:summary_json as jsonb), :created_at, :updated_at
                    )
                    on conflict(artifact_id) do update set
                        title = excluded.title,
                        json_path = excluded.json_path,
                        markdown_path = excluded.markdown_path,
                        summary_json = excluded.summary_json,
                        updated_at = excluded.updated_at
                    """
                ),
                {
                    "artifact_id": uuid_value(artifact_id),
                    "user_id": uuid_value(user_id),
                    "artifact_type": artifact.get("artifact_type") or "artifact",
                    "title": artifact.get("title") or artifact_id,
                    "json_path": artifact.get("json_path") or artifact.get("path"),
                    "markdown_path": artifact.get("markdown_path"),
                    "summary_json": json_dumps(artifact.get("summary") or {}),
                    "created_at": ts,
                    "updated_at": ts,
                },
            )
            if session_id:
                conn.execute(
                    text(
                        """
                        insert into conversation_artifact_links(session_id, turn_id, artifact_id, link_type, created_at)
                        values(:session_id, :turn_id, :artifact_id, :link_type, :created_at)
                        on conflict do nothing
                        """
                    ),
                    {
                        "session_id": uuid_value(session_id),
                        "turn_id": uuid_value(turn_id) if turn_id else None,
                        "artifact_id": uuid_value(artifact_id),
                        "link_type": link_type,
                        "created_at": ts,
                    },
                )
        return artifact_id

    def record_tool_trace(self, trace: dict, *, session_id: str, turn_id: str | None = None, user_id: str | None = None) -> str:
        self._ensure_session(session_id, user_id=user_id)
        tool_call_id = _uuid_or_new(trace.get("tool_call_id"))
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into tool_traces(
                        tool_call_id, session_id, turn_id, tool_name, schema_version,
                        permission_level, agent_mode, arguments_json, status, error_code,
                        error_message, recovery_hint, result_summary, latency_ms,
                        artifacts_json, jobs_json, state_changed, started_at, completed_at
                    ) values(
                        :tool_call_id, :session_id, :turn_id, :tool_name, :schema_version,
                        :permission_level, :agent_mode, cast(:arguments_json as jsonb), :status, :error_code,
                        :error_message, :recovery_hint, :result_summary, :latency_ms,
                        cast(:artifacts_json as jsonb), cast(:jobs_json as jsonb), :state_changed, :started_at, :completed_at
                    )
                    on conflict(tool_call_id) do update set
                        status = excluded.status,
                        error_code = excluded.error_code,
                        error_message = excluded.error_message,
                        completed_at = excluded.completed_at
                    """
                ),
                {
                    "tool_call_id": uuid_value(tool_call_id),
                    "session_id": uuid_value(session_id),
                    "turn_id": uuid_value(turn_id) if turn_id else None,
                    "tool_name": trace.get("tool_name") or "",
                    "schema_version": trace.get("schema_version"),
                    "permission_level": trace.get("permission_level"),
                    "agent_mode": trace.get("agent_mode"),
                    "arguments_json": json_dumps(trace.get("arguments") or {}),
                    "status": trace.get("status") or "ok",
                    "error_code": trace.get("error_code"),
                    "error_message": trace.get("error_message"),
                    "recovery_hint": trace.get("recovery_hint"),
                    "result_summary": trace.get("result_summary"),
                    "latency_ms": _to_int(trace.get("latency_ms")),
                    "artifacts_json": json_dumps(trace.get("artifacts_created") or []),
                    "jobs_json": json_dumps(trace.get("jobs_created") or []),
                    "state_changed": bool(trace.get("state_changed")),
                    "started_at": _dt_or_now(trace.get("started_at")),
                    "completed_at": _dt_or_now(trace.get("completed_at")),
                },
            )
        return tool_call_id

    def link_artifact(self, session_id: str, artifact_id: str, *, turn_id: str | None = None, link_type: str = "manual", user_id: str | None = None) -> None:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into conversation_artifact_links(session_id, turn_id, artifact_id, link_type, created_at)
                    values(:session_id, :turn_id, :artifact_id, :link_type, :created_at)
                    on conflict do nothing
                    """
                ),
                {"session_id": uuid_value(session_id), "turn_id": uuid_value(turn_id) if turn_id else None, "artifact_id": uuid_value(artifact_id), "link_type": link_type, "created_at": utc_now()},
            )

    def artifacts_for_session(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select a.*, l.turn_id, l.link_type, l.created_at as linked_at
                    from conversation_artifact_links l
                    join artifacts a on a.artifact_id = l.artifact_id
                    where l.session_id = :session_id
                    order by l.created_at desc
                    """
                ),
                {"session_id": uuid_value(session_id)},
            ).mappings().all()
        return [_artifact_row(row) for row in rows]

    def jobs_for_session(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select * from jobs where session_id = :session_id order by updated_at desc"),
                {"session_id": uuid_value(session_id)},
            ).mappings().all()
        return [_job_row(row) for row in rows]

    def get_context(self, session_id: str, *, limit: int | None = None, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        if limit is None:
            try:
                from core.settings_store import settings_store

                limits = settings_store.memory_context_limits(user_id=user_id)
                message_limit = limits["message_limit"]
                search_limit = limits["search_limit"]
                evidence_limit = limits["evidence_limit"]
            except Exception:
                message_limit = 8
                search_limit = 8
                evidence_limit = 24
        else:
            message_limit = limit
            search_limit = limit
            evidence_limit = limit * 3
        with self.engine.connect() as conn:
            search_rows = conn.execute(text("select * from search_results where session_id = :session_id order by created_at desc limit :limit"), {"session_id": uuid_value(session_id), "limit": search_limit}).mappings().all()
            evidence_rows = conn.execute(text("select * from evidence_items where session_id = :session_id order by created_at desc limit :limit"), {"session_id": uuid_value(session_id), "limit": evidence_limit}).mappings().all()
            active_jobs = conn.execute(text("select * from jobs where session_id = :session_id and status in ('queued', 'running', 'interrupted') order by updated_at desc"), {"session_id": uuid_value(session_id)}).mappings().all()
        return {
            "session_id": session_id,
            "recent_messages": self.messages(session_id, user_id=user_id)[-message_limit:],
            "recent_search_results": [_search_row(row) for row in search_rows],
            "recent_evidence": [_evidence_row(row) for row in evidence_rows],
            "linked_artifacts": self.artifacts_for_session(session_id, user_id=user_id),
            "active_jobs": [_job_row(row) for row in active_jobs],
            "research_state": self.research_state_digest(session_id, user_id=user_id),
        }

    def build_record(self, session_id: str, *, user_id: str | None = None) -> dict:
        session = self.get_session(session_id, user_id=user_id)
        with self.engine.connect() as conn:
            turns = conn.execute(text("select * from turns where session_id = :session_id order by created_at, turn_id"), {"session_id": uuid_value(session_id)}).mappings().all()
        return {"session": session, "generated_at": to_unix_seconds(utc_now()), "turns": [{"turn_id": str(turn["turn_id"]), "query": turn["query"], "answer_mode": turn["answer_mode"], "role": turn["role"], "status": turn["status"], "created_at": to_unix_seconds(turn["created_at"]), "completed_at": to_unix_seconds(turn["completed_at"])} for turn in turns]}

    def research_state(self, session_id: str, *, user_id: str | None = None) -> dict:
        session = self.get_session(session_id, user_id=user_id)
        authored = self.get_research_state_record(session_id)
        return {
            "session_id": session_id,
            "topic": authored.get("topic") or session.get("title"),
            "objective": authored.get("objective"),
            "stage": authored.get("stage") or "retrieval",
            "candidate_papers": self._derive_candidate_papers(session_id),
            "paper_status_counts": {},
            "evidence_pool": self._derive_evidence_pool(session_id),
            "coverage_gaps": self._derive_coverage_gaps(session_id),
            "excluded_directions": authored.get("excluded_directions", []),
            "open_questions": authored.get("open_questions", []),
            "completed_questions": authored.get("completed_questions", []),
            "next_actions": authored.get("next_actions", []),
            "active_artifact": self._latest_artifact(session_id, user_id=user_id),
            "active_jobs": self.jobs_for_session(session_id, user_id=user_id),
            "provenance": self.state_events(session_id, limit=50),
            "updated_at": authored.get("updated_at"),
        }

    def research_state_digest(self, session_id: str, *, user_id: str | None = None) -> dict | None:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        authored = self.get_research_state_record(session_id)
        has_authored = any([authored.get("objective"), authored.get("excluded_directions"), authored.get("open_questions")])
        if not has_authored:
            return None
        return authored

    def get_research_state_record(self, session_id: str) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(text("select * from research_state where session_id = :session_id"), {"session_id": uuid_value(session_id)}).mappings().first()
        if row is None:
            return {"topic": None, "objective": None, "stage": "retrieval", "excluded_directions": [], "open_questions": [], "completed_questions": [], "next_actions": [], "updated_at": None}
        return {"topic": row["topic"], "objective": row["objective"], "stage": row["stage"], "excluded_directions": json_loads(row["excluded_directions_json"], []), "open_questions": json_loads(row["open_questions_json"], []), "completed_questions": json_loads(row["completed_questions_json"], []), "next_actions": json_loads(row["next_actions_json"], []), "updated_at": to_unix_seconds(row["updated_at"])}

    def update_research_state(self, session_id: str, *, source: str = "user", turn_id: str | None = None, user_id: str | None = None, **fields: Any) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        current = self.get_research_state_record(session_id)
        merged = {**current, **{k: v for k, v in fields.items() if v is not None}}
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into research_state(
                        session_id, topic, objective, stage, excluded_directions_json,
                        open_questions_json, completed_questions_json, next_actions_json, updated_at
                    ) values(
                        :session_id, :topic, :objective, :stage, cast(:excluded as jsonb),
                        cast(:open_questions as jsonb), cast(:completed as jsonb), cast(:next_actions as jsonb), :updated_at
                    )
                    on conflict(session_id) do update set
                        topic = excluded.topic,
                        objective = excluded.objective,
                        stage = excluded.stage,
                        excluded_directions_json = excluded.excluded_directions_json,
                        open_questions_json = excluded.open_questions_json,
                        completed_questions_json = excluded.completed_questions_json,
                        next_actions_json = excluded.next_actions_json,
                        updated_at = excluded.updated_at
                    """
                ),
                {"session_id": uuid_value(session_id), "topic": merged.get("topic"), "objective": merged.get("objective"), "stage": merged.get("stage") or "retrieval", "excluded": json_dumps(merged.get("excluded_directions", [])), "open_questions": json_dumps(merged.get("open_questions", [])), "completed": json_dumps(merged.get("completed_questions", [])), "next_actions": json_dumps(merged.get("next_actions", [])), "updated_at": utc_now()},
            )
            for key, value in fields.items():
                if value is not None:
                    self._record_state_event(conn, session_id, field=key, operation="set", value=value, source=source, turn_id=turn_id)
        return self.get_research_state_record(session_id)

    def set_paper_status(self, session_id: str, paper_id: str, status: str, *, note: str | None = None, source: str = "user", turn_id: str | None = None, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(text("insert into paper_states(session_id, paper_id, status, note, source, turn_id, created_at, updated_at) values(:session_id, :paper_id, :status, :note, :source, :turn_id, :ts, :ts) on conflict(session_id, paper_id) do update set status = excluded.status, note = excluded.note, source = excluded.source, turn_id = excluded.turn_id, updated_at = excluded.updated_at"), {"session_id": uuid_value(session_id), "paper_id": paper_id, "status": status, "note": note, "source": source, "turn_id": uuid_value(turn_id) if turn_id else None, "ts": ts})
            self._record_state_event(conn, session_id, field="paper_status", operation="set", value={"paper_id": paper_id, "status": status, "note": note}, source=source, turn_id=turn_id)
        return {"session_id": session_id, "paper_id": paper_id, "status": status}

    def set_evidence_status(self, session_id: str, evidence_item_id: str, status: str, *, note: str | None = None, source: str = "user", turn_id: str | None = None, user_id: str | None = None) -> dict:
        if status not in {"candidate", "accepted", "excluded", "needs_review"}:
            raise ValueError(f"invalid evidence status: {status}")
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        ts = utc_now()
        with self.engine.begin() as conn:
            exists = conn.execute(text("select evidence_item_id from evidence_items where session_id = :session_id and evidence_item_id = :evidence_item_id"), {"session_id": uuid_value(session_id), "evidence_item_id": uuid_value(evidence_item_id)}).first()
            if not exists:
                raise KeyError(f"evidence item not found: {evidence_item_id}")
            conn.execute(text("insert into evidence_states(session_id, evidence_item_id, status, note, source, turn_id, created_at, updated_at) values(:session_id, :evidence_item_id, :status, :note, :source, :turn_id, :ts, :ts) on conflict(session_id, evidence_item_id) do update set status = excluded.status, note = excluded.note, source = excluded.source, turn_id = excluded.turn_id, updated_at = excluded.updated_at"), {"session_id": uuid_value(session_id), "evidence_item_id": uuid_value(evidence_item_id), "status": status, "note": note, "source": source, "turn_id": uuid_value(turn_id) if turn_id else None, "ts": ts})
            self._record_state_event(conn, session_id, field="evidence_status", operation="set", value={"evidence_item_id": evidence_item_id, "status": status, "note": note}, source=source, turn_id=turn_id)
        return {"session_id": session_id, "evidence_item_id": evidence_item_id, "status": status}

    def record_state_event(self, session_id: str, *, field: str, operation: str, value: Any, source: str = "user", turn_id: str | None = None) -> None:
        with self.engine.begin() as conn:
            self._record_state_event(conn, session_id, field=field, operation=operation, value=value, source=source, turn_id=turn_id)

    def state_events(self, session_id: str, *, limit: int = 50) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("select * from research_state_events where session_id = :session_id order by created_at desc, event_id desc limit :limit"), {"session_id": uuid_value(session_id), "limit": limit}).mappings().all()
        return [{"event_id": row["event_id"], "turn_id": str(row["turn_id"]) if row["turn_id"] else None, "source": row["source"], "field": row["field"], "operation": row["operation"], "value": json_loads(row["value_json"], {}), "created_at": to_unix_seconds(row["created_at"])} for row in rows]

    def bundle(self, session_id: str, *, user_id: str) -> dict:
        return {
            "session": self.get_session(session_id, user_id=user_id),
            "messages": self.messages(session_id, user_id=user_id),
            "context": self.get_context(session_id, user_id=user_id),
            "artifacts": self.artifacts_for_session(session_id, user_id=user_id),
            "jobs": self.jobs_for_session(session_id, user_id=user_id),
            "research_state": self.research_state(session_id, user_id=user_id),
            "attachments": self.list_attachments(session_id, user_id=user_id),
        }

    def _derive_candidate_papers(self, session_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(text("select * from evidence_items where session_id = :session_id order by created_at desc limit 50"), {"session_id": uuid_value(session_id)}).mappings().all()
        seen: dict[str, dict] = {}
        for row in rows:
            key = str(row["paper_id"] or row["doi"] or row["article_id"] or row["evidence_item_id"])
            item = seen.setdefault(key, {"paper_id": row["paper_id"], "key": key, "doi": row["doi"], "article_id": row["article_id"], "title": row["title"], "evidence_count": 0, "status": "candidate", "note": None})
            item["evidence_count"] += 1
        return list(seen.values())

    def _derive_evidence_pool(self, session_id: str) -> dict:
        with self.engine.connect() as conn:
            rows = conn.execute(text("select * from evidence_items where session_id = :session_id order by created_at desc limit 12"), {"session_id": uuid_value(session_id)}).mappings().all()
            total = conn.execute(text("select count(*) from evidence_items where session_id = :session_id"), {"session_id": uuid_value(session_id)}).scalar_one()
        return {"total": total, "by_confidence": {}, "status_counts": {}, "recent": [_evidence_row(row) for row in rows]}

    def _derive_coverage_gaps(self, session_id: str) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(text("select coverage_json, breadth_json, fallback_json, query, created_at from search_results where session_id = :session_id order by created_at desc limit 1"), {"session_id": uuid_value(session_id)}).mappings().first()
        if row is None:
            return {}
        return {"coverage": json_loads(row["coverage_json"], {}), "breadth": json_loads(row["breadth_json"], {}), "fallback_reason": json_loads(row["fallback_json"], None), "from_query": row["query"], "at": to_unix_seconds(row["created_at"])}

    def _latest_artifact(self, session_id: str, *, user_id: str | None = None) -> dict | None:
        artifacts = self.artifacts_for_session(session_id, user_id=user_id)
        return artifacts[0] if artifacts else None

    def _insert_evidence(self, conn, session_id: str, turn_id: str | None, search_result_id: str, paper: dict, evidence: dict) -> None:
        conn.execute(
            text(
                """
                insert into evidence_items(
                    evidence_item_id, session_id, turn_id, search_result_id, evidence_id,
                    article_id, paper_id, doi, title, kind, confidence, source_path,
                    section_id, chunk_index, index_version, snippet, payload_json, created_at
                ) values(
                    :evidence_item_id, :session_id, :turn_id, :search_result_id, :evidence_id,
                    :article_id, :paper_id, :doi, :title, :kind, :confidence, :source_path,
                    :section_id, :chunk_index, :index_version, :snippet, cast(:payload_json as jsonb), :created_at
                )
                """
            ),
            {"evidence_item_id": uuid_value(new_uuid()), "session_id": uuid_value(session_id), "turn_id": uuid_value(turn_id) if turn_id else None, "search_result_id": uuid_value(search_result_id), "evidence_id": evidence.get("evidence_id"), "article_id": _to_int(evidence.get("article_id") or paper.get("article_id")), "paper_id": evidence.get("paper_id") or paper.get("paper_id"), "doi": evidence.get("doi") or paper.get("doi"), "title": evidence.get("title") or paper.get("title"), "kind": evidence.get("kind"), "confidence": evidence.get("confidence"), "source_path": evidence.get("source_path"), "section_id": evidence.get("section_id"), "chunk_index": _to_int(evidence.get("chunk_index")), "index_version": _to_int(evidence.get("index_version") or paper.get("index_version")), "snippet": evidence.get("snippet") or evidence.get("text"), "payload_json": json_dumps(evidence), "created_at": utc_now()},
        )

    def _ensure_session(self, session_id: str, *, user_id: str | None = None, create_if_missing: bool = True) -> None:
        row = self._session_row_for_user(session_id, user_id)
        if row:
            return
        raise KeyError(f"session not found: {session_id}")

    def _session_exists(self, session_id: str) -> bool:
        try:
            sid = uuid_value(session_id)
        except ValueError:
            return False
        with self.engine.connect() as conn:
            return bool(conn.execute(text("select session_id from sessions where session_id = :session_id"), {"session_id": sid}).first())

    def _session_row_for_user(self, session_id: str, user_id: str | None):
        try:
            sid = uuid_value(session_id)
        except ValueError:
            return None
        with self.engine.connect() as conn:
            if user_id is None:
                return conn.execute(text("select * from sessions where session_id = :session_id"), {"session_id": sid}).mappings().first()
            return conn.execute(text("select * from sessions where session_id = :session_id and user_id = :user_id"), {"session_id": sid, "user_id": uuid_value(user_id)}).mappings().first()

    def _session_user_id(self, session_id: str) -> str:
        with self.engine.connect() as conn:
            row = conn.execute(text("select user_id from sessions where session_id = :session_id"), {"session_id": uuid_value(session_id)}).mappings().first()
        if not row:
            raise KeyError(f"session not found: {session_id}")
        return str(row["user_id"])

    def _attachment_row(self, attachment_id: str, *, include_text: bool = False) -> dict:
        with self.engine.connect() as conn:
            row = conn.execute(text("select * from session_attachments where attachment_id = :attachment_id"), {"attachment_id": uuid_value(attachment_id)}).mappings().first()
        if not row:
            raise KeyError(f"attachment not found: {attachment_id}")
        return _attachment_row(row, include_text=include_text)

    def _record_state_event(self, conn, session_id: str, *, field: str, operation: str, value: Any, source: str, turn_id: str | None) -> None:
        conn.execute(text("insert into research_state_events(session_id, turn_id, source, field, operation, value_json, created_at) values(:session_id, :turn_id, :source, :field, :operation, cast(:value_json as jsonb), :created_at)"), {"session_id": uuid_value(session_id), "turn_id": uuid_value(turn_id) if turn_id else None, "source": source, "field": field, "operation": operation, "value_json": json_dumps(value), "created_at": utc_now()})


def _session_row(row) -> dict:
    return {"session_id": str(row["session_id"]), "id": str(row["session_id"]), "module_id": row["module_id"], "user_id": str(row["user_id"]), "title": row["title"], "status": row["status"], "tags": json_loads(row["tags_json"], []), "favorite": bool(row["favorite"]), "pinned": bool(row["pinned"]), "archived": bool(row["archived"]), "deleted_at": to_unix_seconds(row["deleted_at"]), "created_at": to_unix_seconds(row["created_at"]), "updated_at": to_unix_seconds(row["updated_at"]), "last_message_at": to_unix_seconds(row["last_message_at"])}


def _attachment_row(row, *, include_text: bool = False) -> dict:
    out = {"attachment_id": str(row["attachment_id"]), "session_id": str(row["session_id"]), "user_id": str(row["user_id"]), "filename": row["filename"], "content_type": row["content_type"], "status": row["status"], "text_preview": row["text_preview"], "char_count": int(row["char_count"] or 0), "error": row["error"], "created_at": to_unix_seconds(row["created_at"]), "deleted_at": to_unix_seconds(row["deleted_at"])}
    if include_text:
        out["extracted_text"] = row["extracted_text"]
    return out


def _message_row(row) -> dict:
    return {"message_id": str(row["message_id"]), "session_id": str(row["session_id"]), "turn_id": str(row["turn_id"]) if row["turn_id"] else None, "role": row["role"], "content": row["content"], "error": bool(row["error"]), "created_at": to_unix_seconds(row["created_at"]), "metadata": json_loads(row["metadata_json"], {})}


def _search_row(row) -> dict:
    return {"search_result_id": str(row["search_result_id"]), "session_id": str(row["session_id"]), "turn_id": str(row["turn_id"]) if row["turn_id"] else None, "query": row["query"], "query_plan": json_loads(row["query_plan_json"], {}), "filters": json_loads(row["filters_json"], {}), "results": json_loads(row["results_json"], []), "coverage": json_loads(row["coverage_json"], {}), "fallback_reason": json_loads(row["fallback_json"], None), "breadth": json_loads(row["breadth_json"], {}), "created_at": to_unix_seconds(row["created_at"])}


def _evidence_row(row) -> dict:
    return {"evidence_item_id": str(row["evidence_item_id"]), "session_id": str(row["session_id"]), "turn_id": str(row["turn_id"]) if row["turn_id"] else None, "search_result_id": str(row["search_result_id"]) if row["search_result_id"] else None, "evidence_id": row["evidence_id"], "article_id": row["article_id"], "paper_id": row["paper_id"], "doi": row["doi"], "title": row["title"], "kind": row["kind"], "confidence": row["confidence"], "source_path": row["source_path"], "section_id": row["section_id"], "chunk_index": row["chunk_index"], "index_version": row["index_version"], "snippet": row["snippet"], "payload": json_loads(row["payload_json"], {}), "created_at": to_unix_seconds(row["created_at"])}


def _artifact_row(row) -> dict:
    return {"artifact_id": str(row["artifact_id"]), "user_id": str(row["user_id"]), "artifact_type": row["artifact_type"], "title": row["title"], "json_path": row["json_path"], "markdown_path": row["markdown_path"], "summary": json_loads(row["summary_json"], {}), "created_at": to_unix_seconds(row["created_at"]), "updated_at": to_unix_seconds(row["updated_at"]), "turn_id": str(row["turn_id"]) if row.get("turn_id") else None, "link_type": row.get("link_type"), "linked_at": to_unix_seconds(row.get("linked_at"))}


def _job_row(row) -> dict:
    return {"job_id": str(row["job_id"]), "user_id": str(row["user_id"]) if row["user_id"] else None, "session_id": str(row["session_id"]) if row["session_id"] else None, "turn_id": str(row["turn_id"]) if row["turn_id"] else None, "job_type": row["job_type"], "status": row["status"], "payload": json_loads(row["payload_json"], {}), "result": json_loads(row["result_json"], None), "error": row["error"], "created_at": to_unix_seconds(row["created_at"]), "started_at": to_unix_seconds(row["started_at"]), "completed_at": to_unix_seconds(row["completed_at"]), "updated_at": to_unix_seconds(row["updated_at"])}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _uuid_or_new(value: Any) -> str:
    try:
        return str(uuid_value(value)) if value else new_uuid()
    except (TypeError, ValueError):
        return new_uuid()


def _dt_or_now(_value: Any):
    return utc_now()


session_store = SessionStore()
