from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from core.schemas import ChatMessage


def test_session_store_persists_sessions_messages_context_and_annotations(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    session = store.create_session(module_id="literature_search", title="Original")
    turn_id = store.create_turn(session["session_id"], query="perovskite")
    store.append(session["session_id"], ChatMessage(role="user", content="perovskite"), turn_id=turn_id)
    store.record_search_result(
        session["session_id"],
        turn_id,
        {
            "query": "perovskite",
            "query_plan": {"retrieval_used": "fts"},
            "filters": {"scope": "library"},
            "results": [
                {
                    "article_id": 1,
                    "doi": "10.1/example",
                    "title": "Example",
                    "evidence": [
                        {
                            "evidence_id": "E1",
                            "kind": "abstract",
                            "confidence": "medium",
                            "source_path": "articles/example/meta.json",
                            "snippet": "Evidence text",
                        }
                    ],
                }
            ],
        },
    )
    store.append(session["session_id"], ChatMessage(role="assistant", content="answer"), turn_id=turn_id)
    store.complete_turn(turn_id)
    store.set_tags(session["session_id"], ["solar", "review"])
    store.set_favorite(session["session_id"], True)

    reloaded = SessionStore(db_path=db_path)
    sessions = reloaded.list_sessions("literature_search")
    history = reloaded.get_history(session["session_id"])
    context = reloaded.get_context(session["session_id"])

    assert sessions[0]["title"] == "Original"
    assert sessions[0]["favorite"] is True
    assert sessions[0]["tags"] == ["solar", "review"]
    assert [m.content for m in history] == ["perovskite", "answer"]
    assert context["recent_search_results"][0]["query"] == "perovskite"
    assert context["recent_evidence"][0]["evidence_id"] == "E1"


def test_job_store_persists_events_across_instances(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    from modules.literature_search.job_store import JobStore

    store = JobStore(db_path=db_path)
    job = store.create("task_run", {"question": "q"}, session_id="s1", turn_id="t1")
    store.start(job["job_id"])
    store.add_event(job["job_id"], {"type": "artifact", "path": "research_agent/tasks/t.json"})
    store.complete(job["job_id"], {"ok": True})

    reloaded = JobStore(db_path=db_path)
    saved = reloaded.get(job["job_id"])
    events = reloaded.events(job["job_id"])

    assert saved["session_id"] == "s1"
    assert saved["turn_id"] == "t1"
    assert saved["status"] == "completed"
    assert [event["type"] for event in events] == ["queued", "stage", "artifact", "result", "done"]


def test_chat_stream_records_turn_search_and_assistant_message(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.chat_router as chat_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(chat_router, "session_store", store)

    class FakeModule:
        async def handle_chat(self, session_id, message, history, options):
            yield {"type": "search_meta", "query_plan": {"retrieval_used": "fts"}}
            yield {
                "type": "papers",
                "papers": [
                    {
                        "id": "p1",
                        "title": "Paper",
                        "doi": "10.1/example",
                        "article_id": 1,
                        "evidence": [{"evidence_id": "E1", "snippet": "Evidence"}],
                    }
                ],
            }
            yield {"type": "token", "text": "answer"}
            yield {"type": "done"}

    monkeypatch.setattr(chat_router.registry, "get", lambda module_id: FakeModule())
    client = TestClient(main.app)

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"module_id": "literature_search", "session_id": "s1", "message": "q", "history": [], "options": {}},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    history = store.get_history("s1")
    context = store.get_context("s1")

    assert [m.content for m in history] == ["q", "answer"]
    assert context["recent_search_results"][0]["query_plan"]["retrieval_used"] == "fts"
    assert context["recent_evidence"][0]["evidence_id"] == "E1"


def test_chat_stream_persists_error_event_as_assistant_message(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.chat_router as chat_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(chat_router, "session_store", store)

    class FakeModule:
        async def handle_chat(self, session_id, message, history, options):
            yield {"type": "error", "message": "普通对话失败：模型不可用"}
            yield {"type": "done"}

    monkeypatch.setattr(chat_router.registry, "get", lambda module_id: FakeModule())
    client = TestClient(main.app)

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"module_id": "literature_search", "session_id": "s1", "message": "你好", "history": [], "options": {}},
    ) as response:
        assert response.status_code == 200
        list(response.iter_text())

    messages = store.messages("s1")
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["error"] is True
    assert "普通对话失败" in messages[1]["content"]
    turn = store.conn.execute("select status from turns where session_id = ?", ("s1",)).fetchone()
    assert turn["status"] == "failed"


def test_session_store_recovers_stale_running_turns_with_readable_message(tmp_path):
    from core.memory_db import now
    from core.session_store import SessionStore
    from core.schemas import ChatMessage

    db_path = tmp_path / "memory.sqlite"
    store = SessionStore(db_path=db_path)
    session = store.create_session(module_id="literature_search", title="Stale")
    turn_id = store.create_turn(session["session_id"], query="q")
    store.append(session["session_id"], ChatMessage(role="user", content="q"), turn_id=turn_id)
    old = now() - 7200
    store.conn.execute(
        "update turns set created_at = ? where turn_id = ?",
        (old, turn_id),
    )
    store.conn.commit()

    recovered = SessionStore(db_path=db_path)
    turn = recovered.conn.execute("select status, assistant_message_id from turns where turn_id = ?", (turn_id,)).fetchone()
    messages = recovered.messages(session["session_id"])

    assert turn["status"] == "failed"
    assert turn["assistant_message_id"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["error"] is True
    assert "上一次回答中断" in messages[-1]["content"]


def test_session_api_exposes_persistent_sessions(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.modules_router as modules_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", store)
    client = TestClient(main.app)

    created = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Memory"}).json()
    client.post(f"/api/sessions/{created['session_id']}/tags", json={"tags": ["tag-a"]})
    client.post(f"/api/sessions/{created['session_id']}/favorite", json={"favorite": True})

    listed = client.get("/api/sessions", params={"module_id": "literature_search"}).json()
    detail = client.get(f"/api/sessions/{created['session_id']}").json()

    assert listed[0]["title"] == "Memory"
    assert listed[0]["tags"] == ["tag-a"]
    assert detail["favorite"] is True


def test_session_pin_and_soft_delete_api(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.modules_router as modules_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", store)
    client = TestClient(main.app)

    first = client.post("/api/sessions", json={"module_id": "literature_search", "title": "First"}).json()
    pinned = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Pinned"}).json()
    client.post(f"/api/sessions/{pinned['session_id']}/pin", json={"pinned": True})

    listed = client.get("/api/sessions", params={"module_id": "literature_search"}).json()
    assert listed[0]["session_id"] == pinned["session_id"]
    assert listed[0]["pinned"] is True

    deleted = client.delete(f"/api/sessions/{pinned['session_id']}").json()
    listed_after_delete = client.get("/api/sessions", params={"module_id": "literature_search"}).json()

    assert deleted["deleted_at"] is not None
    assert [item["session_id"] for item in listed_after_delete] == [first["session_id"]]


def test_memory_schema_migrates_legacy_session_columns(tmp_path):
    import sqlite3

    from core.memory_db import connect

    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        create table sessions (
            session_id text primary key,
            module_id text not null,
            user_id text not null default 'local_user',
            title text not null default '新对话',
            status text not null default 'active',
            tags_json text not null default '[]',
            favorite integer not null default 0,
            archived integer not null default 0,
            created_at real not null,
            updated_at real not null,
            last_message_at real
        )
        """
    )
    conn.commit()
    conn.close()

    migrated = connect(db_path)
    columns = {row[1] for row in migrated.execute("pragma table_info(sessions)").fetchall()}

    assert "pinned" in columns
    assert "deleted_at" in columns


def test_literature_job_endpoint_creates_session_linked_job(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.literature_search_router as literature_router
    import api.modules_router as modules_router
    import main
    from core.session_store import SessionStore
    from modules.literature_search.job_runner import JobRunner
    from modules.literature_search.job_store import JobStore

    class FakeService:
        data_dir = tmp_path

        def pack(self, query, **kwargs):
            return {"query": query, "pack_path": "research_agent/packs/test.json"}

    store = JobStore(db_path=db_path)
    session_store = SessionStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", session_store)
    monkeypatch.setattr(literature_router, "job_store", store)
    monkeypatch.setattr(literature_router, "job_runner", JobRunner(store, FakeService()))

    client = TestClient(main.app)
    session = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Job"}).json()
    response = client.post(
        "/api/literature-search/pack",
        json={"query": "q", "session_id": session["session_id"], "limit": 1},
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    jobs = client.get(f"/api/sessions/{session['session_id']}/jobs").json()
    assert jobs[0]["job_id"] == job_id
