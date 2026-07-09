from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from core.memory_db import connect, dumps, loads, now
from core.schemas import ChatMessage
from core.user_context import DEFAULT_USER_ID


MAX_ATTACHMENT_TEXT_CHARS = 80_000
MAX_ATTACHMENT_CONTEXT_CHARS = 12_000


class SessionStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path
        self.conn = connect(db_path)
        self.recover_stale_running_turns()

    def create_session(
        self,
        *,
        module_id: str,
        title: str = "新对话",
        user_id: str = DEFAULT_USER_ID,
        session_id: str | None = None,
    ) -> dict:
        sid = session_id or f"s_{uuid.uuid4().hex[:12]}"
        ts = now()
        self.conn.execute(
            """
            insert or ignore into sessions(
                session_id, module_id, user_id, title, status, tags_json,
                favorite, pinned, archived, deleted_at, created_at, updated_at, last_message_at
            ) values(?, ?, ?, ?, 'active', '[]', 0, 0, 0, null, ?, ?, null)
            """,
            (sid, module_id, user_id, title, ts, ts),
        )
        self.conn.commit()
        return self.get_session(sid, user_id=user_id)

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
        changes = []
        params: list[Any] = []
        if title is not None:
            changes.append("title = ?")
            params.append(title)
        if status is not None:
            changes.append("status = ?")
            params.append(status)
        if archived is not None:
            changes.append("archived = ?")
            params.append(1 if archived else 0)
        if favorite is not None:
            changes.append("favorite = ?")
            params.append(1 if favorite else 0)
        if pinned is not None:
            changes.append("pinned = ?")
            params.append(1 if pinned else 0)
        if tags is not None:
            changes.append("tags_json = ?")
            params.append(dumps(tags))
        if changes:
            changes.append("updated_at = ?")
            params.append(now())
            params.append(session_id)
            self.conn.execute(f"update sessions set {', '.join(changes)} where session_id = ?", params)
            self.conn.commit()
        return self.get_session(session_id, user_id=user_id)

    def set_archived(self, session_id: str, archived: bool, *, user_id: str | None = None) -> dict:
        return self.update_session(session_id, archived=archived, status="archived" if archived else "active", user_id=user_id)

    def set_favorite(self, session_id: str, favorite: bool, *, user_id: str | None = None) -> dict:
        return self.update_session(session_id, favorite=favorite, user_id=user_id)

    def set_pinned(self, session_id: str, pinned: bool, *, user_id: str | None = None) -> dict:
        return self.update_session(session_id, pinned=pinned, user_id=user_id)

    def delete_session(self, session_id: str, *, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        self.conn.execute(
            "update sessions set deleted_at = ?, updated_at = ? where session_id = ?",
            (now(), now(), session_id),
        )
        self.conn.commit()
        return self.get_session(session_id, user_id=user_id)

    def restore_session(self, session_id: str, *, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        self.conn.execute(
            "update sessions set deleted_at = null, archived = 0, status = 'active', updated_at = ? where session_id = ?",
            (now(), session_id),
        )
        self.conn.commit()
        return self.get_session(session_id, user_id=user_id)

    def set_tags(self, session_id: str, tags: list[str], *, user_id: str | None = None) -> dict:
        clean = [tag.strip() for tag in tags if tag and tag.strip()]
        return self.update_session(session_id, tags=clean, user_id=user_id)

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
        aid = f"att_{uuid.uuid4().hex[:12]}"
        text = (extracted_text or "")[:MAX_ATTACHMENT_TEXT_CHARS]
        preview = " ".join(text.split())[:500]
        ts = now()
        self.conn.execute(
            """
            insert into session_attachments(
                attachment_id, session_id, user_id, filename, content_type, status,
                extracted_text, text_preview, char_count, error, created_at, deleted_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null)
            """,
            (aid, session_id, owner, filename, content_type, status, text, preview, len(text), error, ts),
        )
        self.conn.commit()
        return self._attachment_row(aid, include_text=False)

    def list_attachments(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        owner = user_id or self._session_user_id(session_id)
        rows = self.conn.execute(
            """
            select * from session_attachments
            where session_id = ? and user_id = ? and deleted_at is null
            order by created_at
            """,
            (session_id, owner),
        ).fetchall()
        return [_attachment_row(row, include_text=False) for row in rows]

    def delete_attachment(self, session_id: str, attachment_id: str, *, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        owner = user_id or self._session_user_id(session_id)
        row = self.conn.execute(
            """
            select * from session_attachments
            where attachment_id = ? and session_id = ? and user_id = ? and deleted_at is null
            """,
            (attachment_id, session_id, owner),
        ).fetchone()
        if not row:
            raise KeyError(f"attachment not found: {attachment_id}")
        self.conn.execute(
            "update session_attachments set deleted_at = ? where attachment_id = ?",
            (now(), attachment_id),
        )
        self.conn.commit()
        return {"deleted": True, "attachment_id": attachment_id}

    def attachments_context(
        self,
        session_id: str,
        attachment_ids: list[str],
        *,
        user_id: str | None = None,
        max_chars: int = MAX_ATTACHMENT_CONTEXT_CHARS,
    ) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        if not attachment_ids:
            return []
        owner = user_id or self._session_user_id(session_id)
        placeholders = ",".join("?" for _ in attachment_ids)
        rows = self.conn.execute(
            f"""
            select * from session_attachments
            where session_id = ? and user_id = ? and deleted_at is null
              and status = 'parsed' and attachment_id in ({placeholders})
            order by created_at
            """,
            [session_id, owner, *attachment_ids],
        ).fetchall()
        by_id = {row["attachment_id"]: row for row in rows}
        remaining = max_chars
        out: list[dict] = []
        for aid in attachment_ids:
            row = by_id.get(aid)
            if not row or remaining <= 0:
                continue
            text = (row["extracted_text"] or "")[:remaining]
            remaining -= len(text)
            item = _attachment_row(row, include_text=False)
            item["text"] = text
            out.append(item)
        return out

    def get_history(self, session_id: str, *, user_id: str | None = None) -> list[ChatMessage]:
        if not self._session_exists(session_id):
            return []
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        rows = self.conn.execute(
            "select role, content, created_at from messages where session_id = ? order by created_at, rowid",
            (session_id,),
        ).fetchall()
        return [ChatMessage(role=row["role"], content=row["content"], timestamp=float(row["created_at"])) for row in rows]

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
        mid = message_id or f"m_{uuid.uuid4().hex[:12]}"
        ts = message.timestamp or now()
        self.conn.execute(
            """
            insert into messages(message_id, session_id, turn_id, role, content, error, created_at, metadata_json)
            values(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (mid, session_id, turn_id, message.role, message.content, 1 if error else 0, ts, dumps(metadata or {})),
        )
        self.conn.execute(
            "update sessions set updated_at = ?, last_message_at = ? where session_id = ?",
            (now(), ts, session_id),
        )
        if turn_id and message.role == "user":
            self.conn.execute("update turns set user_message_id = ? where turn_id = ?", (mid, turn_id))
        if turn_id and message.role == "assistant":
            self.conn.execute("update turns set assistant_message_id = ? where turn_id = ?", (mid, turn_id))
        self.conn.commit()
        return mid

    def touch(self, session_id: str, module_id: str, title: str | None = None, *, user_id: str = DEFAULT_USER_ID) -> None:
        row = self.conn.execute("select session_id from sessions where session_id = ?", (session_id,)).fetchone()
        if not row:
            self.create_session(module_id=module_id, title=title or "新对话", session_id=session_id, user_id=user_id)
            return
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        if title:
            self.conn.execute(
                "update sessions set module_id = ?, title = ?, updated_at = ? where session_id = ?",
                (module_id, title, now(), session_id),
            )
        else:
            self.conn.execute(
                "update sessions set module_id = ?, updated_at = ? where session_id = ?",
                (module_id, now(), session_id),
            )
        self.conn.commit()

    def list_sessions(self, module_id: str | None = None, include_archived: bool = False, *, user_id: str | None = None):
        clauses = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if module_id:
            clauses.append("module_id = ?")
            params.append(module_id)
        if not include_archived:
            clauses.append("archived = 0")
        clauses.append("deleted_at is null")
        where = f"where {' and '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"select * from sessions {where} order by pinned desc, updated_at desc, created_at desc",
            params,
        ).fetchall()
        return [_session_row(row) for row in rows]

    def messages(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        rows = self.conn.execute(
            "select * from messages where session_id = ? order by created_at, rowid",
            (session_id,),
        ).fetchall()
        return [_message_row(row) for row in rows]

    def delete_last_turn(self, session_id: str, *, user_id: str | None = None) -> str | None:
        """Delete the most recent turn (its messages + search_results + evidence +
        artifact links) so the user can re-edit and resend the last question.
        Returns the deleted user message text, or None if there was no turn."""
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        row = self.conn.execute(
            "select turn_id from turns where session_id = ? order by created_at desc, rowid desc limit 1",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        turn_id = row["turn_id"]
        user_row = self.conn.execute(
            "select content from messages where turn_id = ? and role = 'user' order by created_at, rowid limit 1",
            (turn_id,),
        ).fetchone()
        user_text = user_row["content"] if user_row else ""
        for table in ("messages", "search_results", "evidence_items", "conversation_artifact_links"):
            self.conn.execute(f"delete from {table} where turn_id = ?", (turn_id,))
        self.conn.execute("delete from turns where turn_id = ?", (turn_id,))
        self.conn.commit()
        return user_text

    def create_turn(
        self, session_id: str, *, query: str, answer_mode: str = "chat", role: str | None = None, user_id: str | None = None
    ) -> str:
        self._ensure_session(session_id, user_id=user_id)
        turn_id = f"t_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            insert into turns(turn_id, session_id, query, answer_mode, role, status, created_at)
            values(?, ?, ?, ?, ?, 'running', ?)
            """,
            (turn_id, session_id, query, answer_mode, role, now()),
        )
        self.conn.commit()
        return turn_id

    def complete_turn(self, turn_id: str, *, status: str = "completed") -> None:
        self.conn.execute(
            "update turns set status = ?, completed_at = ? where turn_id = ?",
            (status, now(), turn_id),
        )
        self.conn.commit()

    def fail_turn(self, turn_id: str) -> None:
        self.complete_turn(turn_id, status="failed")

    def recover_stale_running_turns(self, *, max_age_seconds: float | None = None) -> int:
        """Mark abandoned streaming turns as failed with a readable assistant note.

        A normally active SSE turn is fresh and must be left alone. Recovery only
        touches old running turns that never wrote an assistant message, which is
        the state left behind by browser disconnects or killed dev servers.
        """
        if max_age_seconds is None:
            raw = os.getenv("LITERATURE_STALE_TURN_SECONDS", "3600")
            try:
                max_age_seconds = float(raw)
            except ValueError:
                max_age_seconds = 3600.0
        if max_age_seconds <= 0:
            return 0
        cutoff = now() - max_age_seconds
        rows = self.conn.execute(
            """
            select t.turn_id, t.session_id, s.user_id
            from turns t
            join sessions s on s.session_id = t.session_id
            where t.status = 'running'
              and t.assistant_message_id is null
              and t.created_at < ?
              and s.deleted_at is null
            """,
            (cutoff,),
        ).fetchall()
        recovered = 0
        for row in rows:
            message_id = f"m_{uuid.uuid4().hex[:12]}"
            ts = now()
            content = "上一次回答中断，未生成完整结果。请重新发送问题或缩小检索范围后重试。"
            self.conn.execute(
                """
                insert into messages(message_id, session_id, turn_id, role, content, error, created_at, metadata_json)
                values(?, ?, ?, 'assistant', ?, 1, ?, ?)
                """,
                (
                    message_id,
                    row["session_id"],
                    row["turn_id"],
                    content,
                    ts,
                    dumps({"failure_code": "stream_abandoned", "failure_message": content}),
                ),
            )
            self.conn.execute(
                "update turns set status = 'failed', assistant_message_id = ?, completed_at = ? where turn_id = ?",
                (message_id, ts, row["turn_id"]),
            )
            self.conn.execute(
                "update sessions set updated_at = ?, last_message_at = ? where session_id = ?",
                (ts, ts, row["session_id"]),
            )
            recovered += 1
        if recovered:
            self.conn.commit()
        return recovered

    def record_search_result(self, session_id: str, turn_id: str | None, payload: dict, *, user_id: str | None = None) -> str:
        self._ensure_session(session_id, user_id=user_id)
        search_result_id = f"sr_{uuid.uuid4().hex[:12]}"
        query_plan = payload.get("query_plan") or {}
        filters = payload.get("filters") or query_plan.get("filters_applied") or {}
        results = payload.get("results") or payload.get("papers") or []
        coverage = payload.get("coverage") or {}
        fallback = payload.get("fallback_reason")
        breadth = payload.get("breadth") or {}
        self.conn.execute(
            """
            insert into search_results(
                search_result_id, session_id, turn_id, query, query_plan_json,
                filters_json, results_json, coverage_json, fallback_json, breadth_json, created_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                search_result_id,
                session_id,
                turn_id,
                payload.get("query") or "",
                dumps(query_plan),
                dumps(filters),
                dumps(results),
                dumps(coverage),
                dumps(fallback) if fallback else None,
                dumps(breadth),
                now(),
            ),
        )
        for paper in results:
            for evidence in paper.get("evidence") or []:
                self._insert_evidence(session_id, turn_id, search_result_id, paper, evidence)
        if turn_id:
            self.conn.execute(
                "update turns set search_result_id = ? where turn_id = ?",
                (search_result_id, turn_id),
            )
        self.conn.commit()
        return search_result_id

    def record_artifact(
        self,
        artifact: dict,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        link_type: str = "manual",
        user_id: str | None = None,
    ) -> str:
        if session_id:
            self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
            user_id = self._session_user_id(session_id)
        owner = user_id or DEFAULT_USER_ID
        artifact_id = artifact.get("artifact_id") or artifact.get("path") or f"a_{uuid.uuid4().hex[:12]}"
        ts = now()
        self.conn.execute(
            """
            insert into artifacts(
                artifact_id, user_id, artifact_type, title, json_path, markdown_path, summary_json, created_at, updated_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(artifact_id) do update set
                user_id = excluded.user_id,
                artifact_type = excluded.artifact_type,
                title = excluded.title,
                json_path = excluded.json_path,
                markdown_path = excluded.markdown_path,
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (
                artifact_id,
                owner,
                artifact.get("artifact_type") or "artifact",
                artifact.get("title") or artifact_id,
                artifact.get("json_path") or artifact.get("path"),
                artifact.get("markdown_path"),
                dumps(artifact.get("summary") or {}),
                artifact.get("created_at") or ts,
                ts,
            ),
        )
        if session_id:
            self.link_artifact(session_id, artifact_id, turn_id=turn_id, link_type=link_type, user_id=owner)
        self.conn.commit()
        return artifact_id

    def record_tool_trace(self, trace: dict, *, session_id: str, turn_id: str | None = None, user_id: str | None = None) -> str:
        """Persist one tool-call trace (Block 4).

        A thin record that REFERENCES the artifacts/jobs already written by the
        tool/JobRunner (it stores their ids, not a second copy of their payloads).
        ``arguments`` must already be redacted by the caller.
        """
        self._ensure_session(session_id, user_id=user_id)
        tool_call_id = trace.get("tool_call_id") or f"tc_{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            """
            insert into tool_traces(
                tool_call_id, session_id, turn_id, tool_name, schema_version,
                permission_level, agent_mode, arguments_json, status, error_code,
                error_message, recovery_hint, result_summary, latency_ms,
                artifacts_json, jobs_json, state_changed, started_at, completed_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(tool_call_id) do update set
                status = excluded.status, error_code = excluded.error_code,
                error_message = excluded.error_message, recovery_hint = excluded.recovery_hint,
                result_summary = excluded.result_summary, latency_ms = excluded.latency_ms,
                artifacts_json = excluded.artifacts_json, jobs_json = excluded.jobs_json,
                state_changed = excluded.state_changed, completed_at = excluded.completed_at
            """,
            (
                tool_call_id,
                session_id,
                turn_id,
                trace.get("tool_name") or "",
                trace.get("schema_version"),
                trace.get("permission_level"),
                trace.get("agent_mode"),
                dumps(trace.get("arguments") or {}),
                trace.get("status") or "ok",
                trace.get("error_code"),
                trace.get("error_message"),
                trace.get("recovery_hint"),
                trace.get("result_summary"),
                _to_int(trace.get("latency_ms")),
                dumps(trace.get("artifacts_created") or []),
                dumps(trace.get("jobs_created") or []),
                1 if trace.get("state_changed") else 0,
                trace.get("started_at") or now(),
                trace.get("completed_at") or now(),
            ),
        )
        self.conn.commit()
        return tool_call_id

    def link_artifact(self, session_id: str, artifact_id: str, *, turn_id: str | None = None, link_type: str = "manual", user_id: str | None = None) -> None:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        self.conn.execute(
            """
            insert or ignore into conversation_artifact_links(session_id, turn_id, artifact_id, link_type, created_at)
            values(?, ?, ?, ?, ?)
            """,
            (session_id, turn_id, artifact_id, link_type, now()),
        )
        self.conn.commit()

    def artifacts_for_session(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        rows = self.conn.execute(
            """
            select a.*, l.turn_id, l.link_type, l.created_at as linked_at
            from conversation_artifact_links l
            join artifacts a on a.artifact_id = l.artifact_id
            where l.session_id = ?
            order by l.created_at desc
            """,
            (session_id,),
        ).fetchall()
        return [_artifact_row(row) for row in rows]

    def jobs_for_session(self, session_id: str, *, user_id: str | None = None) -> list[dict]:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        rows = self.conn.execute(
            "select * from jobs where session_id = ? order by updated_at desc",
            (session_id,),
        ).fetchall()
        return [_job_row(row) for row in rows]

    def get_context(self, session_id: str, *, limit: int | None = None, user_id: str | None = None) -> dict:
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        if limit is None:
            try:
                from core.settings_store import settings_store

                limits = settings_store.memory_context_limits()
                message_limit = limits["message_limit"]
                search_limit = limits["search_limit"]
                evidence_limit = limits["evidence_limit"]
            except Exception:  # noqa: BLE001 - settings must not break memory context
                message_limit = 8
                search_limit = 8
                evidence_limit = 24
        else:
            message_limit = limit
            search_limit = limit
            evidence_limit = limit * 3
        messages = self.messages(session_id, user_id=user_id)[-message_limit:]
        search_rows = self.conn.execute(
            "select * from search_results where session_id = ? order by created_at desc limit ?",
            (session_id, search_limit),
        ).fetchall()
        evidence_rows = self.conn.execute(
            "select * from evidence_items where session_id = ? order by created_at desc limit ?",
            (session_id, evidence_limit),
        ).fetchall()
        active_jobs = self.conn.execute(
            "select * from jobs where session_id = ? and status in ('queued', 'running', 'interrupted') order by updated_at desc",
            (session_id,),
        ).fetchall()
        return {
            "session_id": session_id,
            "recent_messages": messages,
            "recent_search_results": [_search_row(row) for row in search_rows],
            "recent_evidence": [_evidence_row(row) for row in evidence_rows],
            "linked_artifacts": self.artifacts_for_session(session_id, user_id=user_id),
            "active_jobs": [_job_row(row) for row in active_jobs],
            # Block 6b: authored research state steers the next turn ("继续",
            # retained/excluded papers, excluded directions). None until curated.
            "research_state": self.research_state_digest(session_id, user_id=user_id),
        }

    def build_record(self, session_id: str, *, user_id: str | None = None) -> dict:
        """Assemble the full per-turn audit chain for a session.

        Each turn binds: the question, the answer + citation audit, the retrieval
        calls, the evidence located, and any artifacts produced — all already
        persisted with `turn_id`, so this is a pure read/assemble.
        """
        session = self.get_session(session_id, user_id=user_id)
        turn_rows = self.conn.execute(
            "select * from turns where session_id = ? order by created_at, rowid",
            (session_id,),
        ).fetchall()
        turns: list[dict] = []
        for turn in turn_rows:
            turn_id = turn["turn_id"]
            answer_row = self.conn.execute(
                """
                select content, metadata_json from messages
                where turn_id = ? and role = 'assistant'
                order by created_at desc, rowid desc limit 1
                """,
                (turn_id,),
            ).fetchone()
            answer = answer_row["content"] if answer_row else ""
            citation = (loads(answer_row["metadata_json"], {}) if answer_row else {}).get("citation")
            search_rows = self.conn.execute(
                "select * from search_results where turn_id = ? order by created_at",
                (turn_id,),
            ).fetchall()
            searches = [
                {
                    "query": row["query"],
                    "retrieval_used": (loads(row["query_plan_json"], {}) or {}).get("retrieval_used"),
                    "result_count": len(loads(row["results_json"], []) or []),
                    "coverage": loads(_row_value(row, "coverage_json") or "{}", {}),
                    "fallback_reason": loads(_row_value(row, "fallback_json") or "null", None),
                    "breadth": loads(_row_value(row, "breadth_json") or "{}", {}),
                }
                for row in search_rows
            ]
            evidence_rows = self.conn.execute(
                "select * from evidence_items where turn_id = ? order by created_at",
                (turn_id,),
            ).fetchall()
            artifact_rows = self.conn.execute(
                """
                select a.*, l.link_type from conversation_artifact_links l
                join artifacts a on a.artifact_id = l.artifact_id
                where l.turn_id = ? order by l.created_at
                """,
                (turn_id,),
            ).fetchall()
            trace_rows = self.conn.execute(
                "select * from tool_traces where turn_id = ? order by started_at, rowid",
                (turn_id,),
            ).fetchall()
            turns.append(
                {
                    "turn_id": turn_id,
                    "query": turn["query"],
                    "answer_mode": turn["answer_mode"],
                    "role": _row_value(turn, "role"),
                    "status": turn["status"],
                    "created_at": turn["created_at"],
                    "completed_at": turn["completed_at"],
                    "answer": answer,
                    "citation": citation,
                    "searches": searches,
                    "evidence": [_evidence_row(row) for row in evidence_rows],
                    "artifacts": [_artifact_row(row) for row in artifact_rows],
                    "tool_trace": [_tool_trace_row(row) for row in trace_rows],
                }
            )
        return {"session": session, "generated_at": now(), "turns": turns}

    # ------------------------------------------------------------------
    # Block 6a: Shared Research State
    #
    # Split into DERIVED projections (candidate papers / evidence pool /
    # coverage gaps — recomputed from already-persisted rows, never a second
    # copy) and AUTHORED facts (objective / stage / paper status / excluded
    # directions / open questions — written only via explicit mutations, each
    # logged in research_state_events for provenance). 6a populates the derived
    # half and restores both; 6b adds the user/agent write paths.
    # ------------------------------------------------------------------
    def research_state(self, session_id: str, *, user_id: str | None = None) -> dict:
        """Assemble the full Shared Research State for a 课题 (read + derive)."""
        session = self.get_session(session_id, user_id=user_id)
        authored = self.get_research_state_record(session_id)
        candidate_papers = self._derive_candidate_papers(session_id)
        status_counts: dict[str, int] = {}
        for paper in candidate_papers:
            status_counts[paper["status"]] = status_counts.get(paper["status"], 0) + 1
        return {
            "session_id": session_id,
            "topic": authored.get("topic") or session.get("title"),
            "objective": authored.get("objective"),
            "stage": authored.get("stage") or "retrieval",
            "candidate_papers": candidate_papers,
            "paper_status_counts": status_counts,
            "evidence_pool": self._derive_evidence_pool(session_id),
            "coverage_gaps": self._derive_coverage_gaps(session_id),
            "excluded_directions": authored.get("excluded_directions", []),
            "open_questions": authored.get("open_questions", []),
            "completed_questions": authored.get("completed_questions", []),
            "next_actions": authored.get("next_actions", []),
            "active_artifact": self._latest_artifact(session_id, user_id=user_id),
            "active_jobs": [
                _job_row(row)
                for row in self.conn.execute(
                    "select * from jobs where session_id = ? and status in "
                    "('queued', 'running', 'interrupted') order by updated_at desc",
                    (session_id,),
                ).fetchall()
            ],
            "provenance": self.state_events(session_id, limit=50),
            "updated_at": authored.get("updated_at"),
        }

    def research_state_digest(self, session_id: str, *, user_id: str | None = None) -> dict | None:
        """Lean authored-state slice for prompt injection (Block 6b).

        Returns only the curation that should steer the next turn — objective /
        stage / excluded directions / open questions / accepted+excluded papers.
        ``None`` when nothing has been authored yet, so the prompt stays clean for
        brand-new 课题 (no noise before the user has curated anything)."""
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        authored = self.get_research_state_record(session_id)
        papers = self._derive_candidate_papers(session_id)
        accepted = [p for p in papers if p["status"] == "accepted"]
        excluded = [p for p in papers if p["status"] == "excluded"]
        needs_review = [p for p in papers if p["status"] == "needs_review"]
        evidence_pool = self._derive_evidence_pool(session_id)
        evidence = evidence_pool.get("recent") or []
        accepted_evidence = [e for e in evidence if e.get("status") == "accepted"]
        excluded_evidence = [e for e in evidence if e.get("status") == "excluded"]
        needs_review_evidence = [e for e in evidence if e.get("status") == "needs_review"]
        has_authored = any(
            [
                authored.get("objective"),
                authored.get("excluded_directions"),
                authored.get("open_questions"),
                accepted,
                excluded,
                needs_review,
                accepted_evidence,
                excluded_evidence,
                needs_review_evidence,
            ]
        )
        if not has_authored:
            return None
        return {
            "objective": authored.get("objective"),
            "stage": authored.get("stage"),
            "excluded_directions": authored.get("excluded_directions", []),
            "open_questions": authored.get("open_questions", []),
            "accepted_papers": accepted,
            "excluded_papers": excluded,
            "needs_review_papers": needs_review,
            "accepted_evidence": accepted_evidence[:8],
            "excluded_evidence": excluded_evidence[:8],
            "needs_review_evidence": needs_review_evidence[:8],
        }

    def get_research_state_record(self, session_id: str) -> dict:
        """The authored (non-derivable) facts only. Empty defaults if never set."""
        row = self.conn.execute(
            "select * from research_state where session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return {
                "topic": None,
                "objective": None,
                "stage": "retrieval",
                "excluded_directions": [],
                "open_questions": [],
                "completed_questions": [],
                "next_actions": [],
                "updated_at": None,
            }
        return {
            "topic": row["topic"],
            "objective": row["objective"],
            "stage": row["stage"],
            "excluded_directions": loads(row["excluded_directions_json"], []),
            "open_questions": loads(row["open_questions_json"], []),
            "completed_questions": loads(row["completed_questions_json"], []),
            "next_actions": loads(row["next_actions_json"], []),
            "updated_at": row["updated_at"],
        }

    _STATE_LIST_FIELDS = {
        "excluded_directions": "excluded_directions_json",
        "open_questions": "open_questions_json",
        "completed_questions": "completed_questions_json",
        "next_actions": "next_actions_json",
    }
    _STATE_SCALAR_FIELDS = {"topic", "objective", "stage"}

    def update_research_state(
        self,
        session_id: str,
        *,
        source: str = "user",
        turn_id: str | None = None,
        user_id: str | None = None,
        **fields: Any,
    ) -> dict:
        """Set authored research-state fields (6b write path). Logs each change.

        Accepts the scalar fields (topic/objective/stage) and the list fields
        (excluded_directions/open_questions/completed_questions/next_actions).
        Unknown keys are ignored. Each changed field is appended to
        research_state_events with its source/turn so §10 stays auditable.
        """
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        current = self.get_research_state_record(session_id)
        ts = now()
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key in self._STATE_SCALAR_FIELDS or key in self._STATE_LIST_FIELDS:
                if value is None:
                    continue
                updates[key] = value
        if not updates:
            return self.get_research_state_record(session_id)
        merged = {**current, **updates}
        self.conn.execute(
            """
            insert into research_state(
                session_id, topic, objective, stage, excluded_directions_json,
                open_questions_json, completed_questions_json, next_actions_json, updated_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(session_id) do update set
                topic = excluded.topic, objective = excluded.objective,
                stage = excluded.stage,
                excluded_directions_json = excluded.excluded_directions_json,
                open_questions_json = excluded.open_questions_json,
                completed_questions_json = excluded.completed_questions_json,
                next_actions_json = excluded.next_actions_json,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                merged.get("topic"),
                merged.get("objective"),
                merged.get("stage") or "retrieval",
                dumps(merged.get("excluded_directions", [])),
                dumps(merged.get("open_questions", [])),
                dumps(merged.get("completed_questions", [])),
                dumps(merged.get("next_actions", [])),
                ts,
            ),
        )
        for key, value in updates.items():
            self.record_state_event(
                session_id,
                field=key,
                operation="set",
                value=value,
                source=source,
                turn_id=turn_id,
            )
        self.conn.commit()
        return self.get_research_state_record(session_id)

    def set_paper_status(
        self,
        session_id: str,
        paper_id: str,
        status: str,
        *,
        note: str | None = None,
        source: str = "user",
        turn_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        """Curate one candidate paper's status (6b write path). Logs provenance."""
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        ts = now()
        self.conn.execute(
            """
            insert into paper_states(
                session_id, paper_id, status, note, source, turn_id, created_at, updated_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(session_id, paper_id) do update set
                status = excluded.status, note = excluded.note,
                source = excluded.source, turn_id = excluded.turn_id,
                updated_at = excluded.updated_at
            """,
            (session_id, paper_id, status, note, source, turn_id, ts, ts),
        )
        self.record_state_event(
            session_id,
            field="paper_status",
            operation="set",
            value={"paper_id": paper_id, "status": status, "note": note},
            source=source,
            turn_id=turn_id,
        )
        self.conn.commit()
        return {"session_id": session_id, "paper_id": paper_id, "status": status}

    def set_evidence_status(
        self,
        session_id: str,
        evidence_item_id: str,
        status: str,
        *,
        note: str | None = None,
        source: str = "user",
        turn_id: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        """Curate one session-local evidence item's status. This never writes to corpus/index data."""
        if status not in {"candidate", "accepted", "excluded", "needs_review"}:
            raise ValueError(f"invalid evidence status: {status}")
        self._ensure_session(session_id, user_id=user_id, create_if_missing=False)
        row = self.conn.execute(
            "select evidence_item_id from evidence_items where session_id = ? and evidence_item_id = ?",
            (session_id, evidence_item_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"evidence item not found: {evidence_item_id}")
        ts = now()
        self.conn.execute(
            """
            insert into evidence_states(
                session_id, evidence_item_id, status, note, source, turn_id, created_at, updated_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(session_id, evidence_item_id) do update set
                status = excluded.status, note = excluded.note,
                source = excluded.source, turn_id = excluded.turn_id,
                updated_at = excluded.updated_at
            """,
            (session_id, evidence_item_id, status, note, source, turn_id, ts, ts),
        )
        self.record_state_event(
            session_id,
            field="evidence_status",
            operation="set",
            value={"evidence_item_id": evidence_item_id, "status": status, "note": note},
            source=source,
            turn_id=turn_id,
        )
        self.conn.commit()
        return {"session_id": session_id, "evidence_item_id": evidence_item_id, "status": status}

    def record_state_event(
        self,
        session_id: str,
        *,
        field: str,
        operation: str,
        value: Any,
        source: str = "user",
        turn_id: str | None = None,
    ) -> None:
        """Append a provenance row. Caller commits (batched with the mutation)."""
        self.conn.execute(
            """
            insert into research_state_events(
                session_id, turn_id, source, field, operation, value_json, created_at
            ) values(?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, turn_id, source, field, operation, dumps(value), now()),
        )

    def state_events(self, session_id: str, *, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "select * from research_state_events where session_id = ? "
            "order by created_at desc, event_id desc limit ?",
            (session_id, limit),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "turn_id": row["turn_id"],
                "source": row["source"],
                "field": row["field"],
                "operation": row["operation"],
                "value": loads(row["value_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _derive_candidate_papers(self, session_id: str) -> list[dict]:
        """Aggregate evidence_items into a per-paper candidate set, then overlay
        any authored paper_states status (no row → 'candidate')."""
        rows = self.conn.execute(
            """
            select paper_id, doi, article_id, title,
                   count(*) as evidence_count,
                   max(created_at) as last_seen_at,
                   min(turn_id) as first_turn_id
            from evidence_items
            where session_id = ?
            group by coalesce(paper_id, doi, 'article:' || article_id)
            order by evidence_count desc, last_seen_at desc
            """,
            (session_id,),
        ).fetchall()
        status_rows = {
            row["paper_id"]: row
            for row in self.conn.execute(
                "select * from paper_states where session_id = ?", (session_id,)
            ).fetchall()
        }
        papers: list[dict] = []
        for row in rows:
            key = row["paper_id"] or row["doi"] or (
                f"article:{row['article_id']}" if row["article_id"] is not None else None
            )
            override = status_rows.get(key) if key else None
            papers.append(
                {
                    "paper_id": row["paper_id"],
                    "key": key,
                    "doi": row["doi"],
                    "article_id": row["article_id"],
                    "title": row["title"],
                    "evidence_count": row["evidence_count"],
                    "last_seen_at": row["last_seen_at"],
                    "first_turn_id": row["first_turn_id"],
                    "status": override["status"] if override else "candidate",
                    "note": override["note"] if override else None,
                    "status_source": override["source"] if override else None,
                }
            )
        return papers

    def _derive_evidence_pool(self, session_id: str) -> dict:
        total = self.conn.execute(
            "select count(*) from evidence_items where session_id = ?", (session_id,)
        ).fetchone()[0]
        status_rows = {
            row["evidence_item_id"]: row
            for row in self.conn.execute(
                "select * from evidence_states where session_id = ?", (session_id,)
            ).fetchall()
        }
        status_counts: dict[str, int] = {}
        for row in self.conn.execute(
            "select evidence_item_id from evidence_items where session_id = ?", (session_id,)
        ).fetchall():
            override = status_rows.get(row["evidence_item_id"])
            status = override["status"] if override else "candidate"
            status_counts[status] = status_counts.get(status, 0) + 1
        by_confidence: dict[str, int] = {}
        for row in self.conn.execute(
            "select confidence, count(*) as n from evidence_items "
            "where session_id = ? group by confidence",
            (session_id,),
        ).fetchall():
            by_confidence[row["confidence"] or "unknown"] = row["n"]
        recent = self.conn.execute(
            "select * from evidence_items where session_id = ? "
            "order by created_at desc limit 12",
            (session_id,),
        ).fetchall()
        recent_rows = []
        for row in recent:
            item = _evidence_row(row)
            override = status_rows.get(item["evidence_item_id"])
            item["status"] = override["status"] if override else "candidate"
            item["note"] = override["note"] if override else None
            item["status_source"] = override["source"] if override else None
            recent_rows.append(item)
        return {
            "total": total,
            "by_confidence": by_confidence,
            "status_counts": status_counts,
            "recent": recent_rows,
        }

    def _derive_coverage_gaps(self, session_id: str) -> dict:
        """Latest turn's coverage judgment is the current gap picture."""
        row = self.conn.execute(
            "select coverage_json, breadth_json, fallback_json, query, created_at "
            "from search_results where session_id = ? order by created_at desc limit 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return {}
        return {
            "coverage": loads(_row_value(row, "coverage_json") or "{}", {}),
            "breadth": loads(_row_value(row, "breadth_json") or "{}", {}),
            "fallback_reason": loads(_row_value(row, "fallback_json") or "null", None),
            "from_query": row["query"],
            "at": row["created_at"],
        }

    def _latest_artifact(self, session_id: str, *, user_id: str | None = None) -> dict | None:
        artifacts = self.artifacts_for_session(session_id, user_id=user_id)
        return artifacts[0] if artifacts else None

    def _insert_evidence(self, session_id: str, turn_id: str | None, search_result_id: str, paper: dict, evidence: dict) -> None:
        self.conn.execute(
            """
            insert into evidence_items(
                evidence_item_id, session_id, turn_id, search_result_id, evidence_id,
                article_id, paper_id, doi, title, kind, confidence, source_path,
                section_id, chunk_index, index_version, snippet, payload_json, created_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ei_{uuid.uuid4().hex[:12]}",
                session_id,
                turn_id,
                search_result_id,
                evidence.get("evidence_id"),
                _to_int(evidence.get("article_id") or paper.get("article_id")),
                evidence.get("paper_id") or paper.get("paper_id"),
                evidence.get("doi") or paper.get("doi"),
                evidence.get("title") or paper.get("title"),
                evidence.get("kind"),
                evidence.get("confidence"),
                evidence.get("source_path"),
                evidence.get("section_id"),
                _to_int(evidence.get("chunk_index")),
                _to_int(evidence.get("index_version") or paper.get("index_version")),
                evidence.get("snippet") or evidence.get("text"),
                dumps(evidence),
                now(),
            ),
        )

    def _ensure_session(self, session_id: str, *, user_id: str | None = None, create_if_missing: bool = True) -> None:
        row = self._session_row_for_user(session_id, user_id)
        if row:
            return
        if user_id is not None or not create_if_missing:
            raise KeyError(f"session not found: {session_id}")
        self.create_session(module_id="literature_search", session_id=session_id)

    def _session_exists(self, session_id: str) -> bool:
        return bool(self.conn.execute("select session_id from sessions where session_id = ?", (session_id,)).fetchone())

    def _session_row_for_user(self, session_id: str, user_id: str | None):
        if user_id is None:
            return self.conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
        return self.conn.execute(
            "select * from sessions where session_id = ? and user_id = ?",
            (session_id, user_id),
        ).fetchone()

    def _session_user_id(self, session_id: str) -> str:
        row = self.conn.execute("select user_id from sessions where session_id = ?", (session_id,)).fetchone()
        if not row:
            raise KeyError(f"session not found: {session_id}")
        return row["user_id"]

    def _attachment_row(self, attachment_id: str, *, include_text: bool = False) -> dict:
        row = self.conn.execute("select * from session_attachments where attachment_id = ?", (attachment_id,)).fetchone()
        if not row:
            raise KeyError(f"attachment not found: {attachment_id}")
        return _attachment_row(row, include_text=include_text)


def _session_row(row) -> dict:
    return {
        "session_id": row["session_id"],
        "id": row["session_id"],
        "module_id": row["module_id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "status": row["status"],
        "tags": loads(row["tags_json"], []),
        "favorite": bool(row["favorite"]),
        "pinned": bool(row["pinned"]),
        "archived": bool(row["archived"]),
        "deleted_at": row["deleted_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_message_at": row["last_message_at"],
    }


def _attachment_row(row, *, include_text: bool = False) -> dict:
    out = {
        "attachment_id": row["attachment_id"],
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "status": row["status"],
        "text_preview": row["text_preview"],
        "char_count": int(row["char_count"] or 0),
        "error": row["error"],
        "created_at": row["created_at"],
        "deleted_at": row["deleted_at"],
    }
    if include_text:
        out["extracted_text"] = row["extracted_text"]
    return out


def _message_row(row) -> dict:
    return {
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "role": row["role"],
        "content": row["content"],
        "error": bool(row["error"]),
        "created_at": row["created_at"],
        "metadata": loads(row["metadata_json"], {}),
    }


def _search_row(row) -> dict:
    return {
        "search_result_id": row["search_result_id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "query": row["query"],
        "query_plan": loads(row["query_plan_json"], {}),
        "filters": loads(row["filters_json"], {}),
        "results": loads(row["results_json"], []),
        "coverage": loads(_row_value(row, "coverage_json") or "{}", {}),
        "fallback_reason": loads(_row_value(row, "fallback_json") or "null", None),
        "breadth": loads(_row_value(row, "breadth_json") or "{}", {}),
        "created_at": row["created_at"],
    }


def _evidence_row(row) -> dict:
    return {
        "evidence_item_id": row["evidence_item_id"],
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "search_result_id": row["search_result_id"],
        "evidence_id": row["evidence_id"],
        "article_id": row["article_id"],
        "paper_id": _row_value(row, "paper_id"),
        "doi": row["doi"],
        "title": row["title"],
        "kind": row["kind"],
        "confidence": row["confidence"],
        "source_path": row["source_path"],
        "section_id": _row_value(row, "section_id"),
        "chunk_index": _row_value(row, "chunk_index"),
        "index_version": _row_value(row, "index_version"),
        "snippet": row["snippet"],
        "payload": loads(row["payload_json"], {}),
        "created_at": row["created_at"],
    }


def _artifact_row(row) -> dict:
    return {
        "artifact_id": row["artifact_id"],
        "user_id": _row_value(row, "user_id"),
        "artifact_type": row["artifact_type"],
        "title": row["title"],
        "json_path": row["json_path"],
        "markdown_path": row["markdown_path"],
        "summary": loads(row["summary_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "turn_id": row["turn_id"] if "turn_id" in row.keys() else None,
        "link_type": row["link_type"] if "link_type" in row.keys() else None,
        "linked_at": row["linked_at"] if "linked_at" in row.keys() else None,
    }


def _tool_trace_row(row) -> dict:
    return {
        "tool_call_id": row["tool_call_id"],
        "tool_name": row["tool_name"],
        "schema_version": _row_value(row, "schema_version"),
        "permission_level": _row_value(row, "permission_level"),
        "agent_mode": _row_value(row, "agent_mode"),
        "arguments": loads(row["arguments_json"], {}),
        "status": row["status"],
        "error_code": _row_value(row, "error_code"),
        "error_message": _row_value(row, "error_message"),
        "recovery_hint": _row_value(row, "recovery_hint"),
        "result_summary": _row_value(row, "result_summary"),
        "latency_ms": _row_value(row, "latency_ms"),
        "artifacts_created": loads(_row_value(row, "artifacts_json") or "[]", []),
        "jobs_created": loads(_row_value(row, "jobs_json") or "[]", []),
        "state_changed": bool(_row_value(row, "state_changed")),
        "started_at": row["started_at"],
        "completed_at": _row_value(row, "completed_at"),
    }


def _job_row(row) -> dict:
    return {
        "job_id": row["job_id"],
        "user_id": _row_value(row, "user_id"),
        "session_id": row["session_id"],
        "turn_id": row["turn_id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "payload": loads(row["payload_json"], {}),
        "result": loads(row["result_json"], None),
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_value(row, key, default=None):
    """Tolerant column read so older DBs (pre-migration) don't blow up."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


session_store = SessionStore()
