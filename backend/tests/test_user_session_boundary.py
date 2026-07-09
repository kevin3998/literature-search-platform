from __future__ import annotations

from fastapi.testclient import TestClient

from core.module_base import AgentModule
from core.registry import registry
from core.schemas import ChatMessage
from core.session_store import SessionStore


class FakeModule(AgentModule):
    id = "literature_search"
    name = "Literature Search"
    description = "Fake"
    icon = "book"
    status = "active"

    async def handle_chat(self, session_id: str, message: str, history: list[ChatMessage], options: dict):
        yield {"type": "token", "text": f"ok:{message}"}
        yield {"type": "done"}


def _client(monkeypatch, tmp_path):
    import api.chat_router as chat_router
    import api.modules_router as modules_router
    import main

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    monkeypatch.setattr(modules_router, "session_store", store)
    monkeypatch.setattr(chat_router, "session_store", store)
    monkeypatch.setattr(main, "session_store", store)
    monkeypatch.setattr(registry, "_modules", {"literature_search": FakeModule()})
    return TestClient(main.app), store


def test_sessions_are_scoped_by_header_user(monkeypatch, tmp_path) -> None:
    client, _store = _client(monkeypatch, tmp_path)

    alice = client.post(
        "/api/sessions",
        headers={"X-User-Id": "alice"},
        json={"module_id": "literature_search", "title": "Alice"},
    ).json()
    bob = client.post(
        "/api/sessions",
        headers={"X-User-Id": "bob"},
        json={"module_id": "literature_search", "title": "Bob"},
    ).json()

    alice_list = client.get("/api/sessions", headers={"X-User-Id": "alice"}, params={"module_id": "literature_search"}).json()
    bob_list = client.get("/api/sessions", headers={"X-User-Id": "bob"}, params={"module_id": "literature_search"}).json()

    assert [item["session_id"] for item in alice_list] == [alice["session_id"]]
    assert [item["session_id"] for item in bob_list] == [bob["session_id"]]
    assert client.get(f"/api/sessions/{alice['session_id']}", headers={"X-User-Id": "bob"}).status_code == 404


def test_session_children_are_scoped_by_owner(monkeypatch, tmp_path) -> None:
    client, store = _client(monkeypatch, tmp_path)
    alice = client.post(
        "/api/sessions",
        headers={"X-User-Id": "alice"},
        json={"module_id": "literature_search", "title": "Alice"},
    ).json()
    sid = alice["session_id"]
    store.record_artifact({"artifact_id": "a1", "artifact_type": "note", "title": "A1"}, session_id=sid, user_id="alice")

    ok = client.get(f"/api/sessions/{sid}/artifacts", headers={"X-User-Id": "alice"})
    blocked = client.get(f"/api/sessions/{sid}/artifacts", headers={"X-User-Id": "bob"})

    assert ok.status_code == 200
    assert ok.json()[0]["artifact_id"] == "a1"
    assert blocked.status_code == 404


def test_chat_stream_cannot_write_to_another_users_session(monkeypatch, tmp_path) -> None:
    client, _store = _client(monkeypatch, tmp_path)
    alice = client.post(
        "/api/sessions",
        headers={"X-User-Id": "alice"},
        json={"module_id": "literature_search", "title": "Alice"},
    ).json()

    response = client.post(
        "/api/chat/stream",
        headers={"X-User-Id": "bob"},
        json={
            "module_id": "literature_search",
            "session_id": alice["session_id"],
            "message": "hello",
            "history": [],
            "options": {},
        },
    )

    assert response.status_code == 404


def test_no_header_remains_local_user(monkeypatch, tmp_path) -> None:
    client, _store = _client(monkeypatch, tmp_path)

    created = client.post("/api/sessions", json={"module_id": "literature_search", "title": "Local"}).json()

    assert created["user_id"] == "local_user"
    assert client.get(f"/api/sessions/{created['session_id']}").status_code == 200
