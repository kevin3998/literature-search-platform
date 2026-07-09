from __future__ import annotations

import os
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

if not os.getenv("DATABASE_URL"):
    pytest.skip(
        "M2 PostgreSQL runtime API contract tests require DATABASE_URL; see test_postgres_m2_core_runtime.py for migrated coverage.",
        allow_module_level=True,
    )

from core.module_base import AgentModule
from core.registry import registry
from core.schemas import ChatMessage
from core.session_store import SessionStore


class FakeChatModule(AgentModule):
    id = "literature_search"
    name = "Literature Search"
    description = "Fake contract module"
    icon = "book"
    status = "active"

    async def handle_chat(
        self,
        session_id: str,
        message: str,
        history: list[ChatMessage],
        options: dict,
    ) -> AsyncIterator[dict]:
        yield {"type": "token", "text": f"echo:{message}"}
        yield {"type": "citation", "status": "warning", "audit_status": "uncited"}
        yield {"type": "done"}


def _client_with_isolated_store(monkeypatch, tmp_path):
    import api.chat_router as chat_router
    import api.modules_router as modules_router
    import main

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    monkeypatch.setattr(modules_router, "session_store", store)
    monkeypatch.setattr(chat_router, "session_store", store)
    monkeypatch.setattr(main, "session_store", store)

    monkeypatch.setattr(registry, "_modules", {"literature_search": FakeChatModule()})
    return TestClient(main.app), store


def test_modules_and_sessions_contract_use_backend_snake_case(monkeypatch, tmp_path):
    client, _store = _client_with_isolated_store(monkeypatch, tmp_path)

    modules = client.get("/api/modules").json()
    assert modules[0]["id"] == "literature_search"
    assert {"name", "description", "icon", "status"}.issubset(modules[0])

    created_response = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Contract"})
    assert created_response.status_code == 200
    created = created_response.json()
    assert {"session_id", "module_id", "user_id", "created_at", "updated_at", "last_message_at"}.issubset(created)
    assert "sessionId" not in created
    assert created["module_id"] == "literature_search"

    listed = client.get("/api/sessions", params={"module_id": "literature_search"}).json()
    assert listed[0]["session_id"] == created["session_id"]
    assert listed[0]["module_id"] == "literature_search"

    fetched = client.get(f"/api/sessions/{created['session_id']}").json()
    assert fetched["session_id"] == created["session_id"]


def test_messages_context_and_chat_stream_contract(monkeypatch, tmp_path):
    client, _store = _client_with_isolated_store(monkeypatch, tmp_path)
    session = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Chat"}).json()
    sid = session["session_id"]

    response = client.post(
        "/api/chat/stream",
        json={
            "module_id": "literature_search",
            "session_id": sid,
            "message": "hello",
            "history": [],
            "options": {"role": "general"},
        },
    )
    assert response.status_code == 200
    assert 'data: {"type": "token", "text": "echo:hello"}' in response.text
    assert 'data: {"type": "done"}' in response.text

    messages = client.get(f"/api/sessions/{sid}/messages").json()
    assert messages[0]["session_id"] == sid
    assert messages[0]["turn_id"].startswith("t_")
    assert {"message_id", "role", "content", "error", "created_at", "metadata"}.issubset(messages[0])
    assert "messageId" not in messages[0]

    context = client.get(f"/api/sessions/{sid}/context").json()
    assert {"session_id", "recent_messages", "recent_search_results", "recent_evidence", "linked_artifacts", "active_jobs"}.issubset(context)
    assert context["recent_messages"][0]["content"] == "hello"


def test_chat_stream_rejects_camel_case_request_body(monkeypatch, tmp_path):
    client, _store = _client_with_isolated_store(monkeypatch, tmp_path)

    response = client.post(
        "/api/chat/stream",
        json={"moduleId": "literature_search", "sessionId": "s1", "message": "hello"},
    )

    assert response.status_code == 422


def test_chat_stream_persists_lightweight_route_metadata(monkeypatch, tmp_path):
    import api.chat_router as chat_router
    import api.modules_router as modules_router
    import main

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    monkeypatch.setattr(modules_router, "session_store", store)
    monkeypatch.setattr(chat_router, "session_store", store)
    monkeypatch.setattr(main, "session_store", store)

    class RouteModule(AgentModule):
        id = "literature_search"
        name = "Literature Search"
        description = "Route contract module"
        icon = "book"
        status = "active"

        async def handle_chat(self, session_id, message, history, options):
            yield {"type": "intent_route", "route": "library_count", "label": "文献库状态"}
            yield {"type": "library_status", "stats": {"paper_count": 3}}
            yield {"type": "token", "text": "当前本地文献库中共有 3 篇文献。"}
            yield {"type": "done"}

    monkeypatch.setattr(registry, "_modules", {"literature_search": RouteModule()})
    client = TestClient(main.app)
    session = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Chat"}).json()

    response = client.post(
        "/api/chat/stream",
        json={
            "module_id": "literature_search",
            "session_id": session["session_id"],
            "message": "当前文献库中一共有多少文献？",
            "history": [],
            "options": {"role": "general"},
        },
    )

    assert response.status_code == 200
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["metadata"]["route"] == "library_count"
    assert assistant["metadata"]["used_library_stats"] is True
    assert assistant["metadata"]["stats"]["paper_count"] == 3


def test_chat_stream_persists_failure_explanation_metadata(monkeypatch, tmp_path):
    import api.chat_router as chat_router
    import api.modules_router as modules_router
    import main

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    monkeypatch.setattr(modules_router, "session_store", store)
    monkeypatch.setattr(chat_router, "session_store", store)
    monkeypatch.setattr(main, "session_store", store)

    class FailureRouteModule(AgentModule):
        id = "literature_search"
        name = "Literature Search"
        description = "Failure route contract module"
        icon = "book"
        status = "active"

        async def handle_chat(self, session_id, message, history, options):
            yield {"type": "intent_route", "route": "research", "label": "文献检索"}
            yield {
                "type": "failure_explanation",
                "code": "library_not_empty_but_no_query_hit",
                "message": "当前本地文献库不是空的，但本轮检索没有命中该主题。",
            }
            yield {"type": "token", "text": "当前本地文献库没有命中该主题。"}
            yield {"type": "done"}

    monkeypatch.setattr(registry, "_modules", {"literature_search": FailureRouteModule()})
    client = TestClient(main.app)
    session = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Chat"}).json()

    response = client.post(
        "/api/chat/stream",
        json={
            "module_id": "literature_search",
            "session_id": session["session_id"],
            "message": "文献库里有没有关于量子香蕉电池的论文？",
            "history": [],
            "options": {"role": "general"},
        },
    )

    assert response.status_code == 200
    messages = client.get(f"/api/sessions/{session['session_id']}/messages").json()
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["metadata"]["route"] == "research"
    assert assistant["metadata"]["failure_code"] == "library_not_empty_but_no_query_hit"
    assert "不是空的" in assistant["metadata"]["failure_message"]
