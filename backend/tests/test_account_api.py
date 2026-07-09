from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.postgres_test_utils import migrated_postgres_schema


def test_account_signup_csrf_profile_sessions_and_api_tokens(monkeypatch):
    import core.auth_store as auth_store_module
    from api.account_router import router as account_router
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_account_session")
        monkeypatch.setenv("CSRF_COOKIE_NAME", "lap_account_csrf")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(account_router)
        client = TestClient(app)

        signup = client.post(
            "/api/auth/signup",
            json={"email": "account@example.com", "display_name": "Account User", "password": "password123"},
        )
        csrf = client.get("/api/auth/csrf")
        csrf_headers = {"X-CSRF-Token": csrf.json()["csrf_token"]}
        profile_before = client.get("/api/account/profile")
        profile_update = client.patch(
            "/api/account/profile",
            json={"display_name": "Updated User", "avatar_url": "https://example.com/avatar.png"},
            headers=csrf_headers,
        )
        sessions = client.get("/api/account/sessions")
        token_create = client.post("/api/account/api-tokens", json={"name": "CLI"}, headers=csrf_headers)
        token_list = client.get("/api/account/api-tokens")

    assert signup.status_code == 200
    assert csrf.status_code == 200
    assert csrf.json()["csrf_token"].startswith("csrf_")
    assert profile_before.status_code == 200
    assert profile_before.json()["email"] == "account@example.com"
    assert profile_update.status_code == 200
    assert profile_update.json()["display_name"] == "Updated User"
    assert profile_update.json()["avatar_url"] == "https://example.com/avatar.png"
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    assert sessions.json()[0]["session_id"]
    assert token_create.status_code == 200
    created = token_create.json()
    assert created["api_token"].startswith("lap_")
    assert created["name"] == "CLI"
    assert "token_hash" not in created
    assert token_list.status_code == 200
    listed = token_list.json()["tokens"]
    assert len(listed) == 1
    assert listed[0]["token_id"] == created["token_id"]
    assert listed[0]["token_preview"] == created["token_preview"]
    assert "api_token" not in listed[0]
    assert "token_hash" not in listed[0]


def test_account_password_change_and_revocations(monkeypatch):
    import core.auth_store as auth_store_module
    from api.account_router import router as account_router
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_account_revoke_session")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(account_router)
        client = TestClient(app)
        client.post(
            "/api/auth/signup",
            json={"email": "change@example.com", "display_name": "Change User", "password": "password123"},
        )
        csrf_headers = {"X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]}
        token_create = client.post("/api/account/api-tokens", json={"name": "Old token"}, headers=csrf_headers)
        token_id = token_create.json()["token_id"]
        revoke_token = client.delete(f"/api/account/api-tokens/{token_id}", headers=csrf_headers)
        password_change = client.post(
            "/api/account/password",
            json={"current_password": "password123", "new_password": "newpassword123"},
            headers=csrf_headers,
        )
        client.post("/api/auth/logout", headers=csrf_headers)
        old_login = client.post("/api/auth/login", json={"email": "change@example.com", "password": "password123"})
        new_login = client.post("/api/auth/login", json={"email": "change@example.com", "password": "newpassword123"})
        csrf_headers = {"X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]}
        session_id = client.get("/api/account/sessions").json()[0]["session_id"]
        revoke_session = client.delete(f"/api/account/sessions/{session_id}", headers=csrf_headers)
        after_revoke = client.get("/api/account/profile")

    assert revoke_token.status_code == 200
    assert revoke_token.json() == {"ok": True}
    assert password_change.status_code == 200
    assert password_change.json() == {"ok": True}
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert revoke_session.status_code == 200
    assert revoke_session.json() == {"ok": True}
    assert after_revoke.status_code == 401


def test_account_api_tokens_list_uses_wrapper_contract(monkeypatch):
    import core.auth_store as auth_store_module
    from api.account_router import router as account_router
    from core.user_context import UserContext, current_user

    class FakeAuthStore:
        def list_api_tokens(self, user_id: str):
            return [{"token_id": "token-1", "user_id": user_id, "name": "CLI"}]

    app = FastAPI()
    app.dependency_overrides[current_user] = lambda: UserContext(user_id="user-1", workspace_slug="user-1")
    app.include_router(account_router)
    monkeypatch.setattr(auth_store_module, "auth_store", FakeAuthStore(), raising=False)

    response = TestClient(app).get("/api/account/api-tokens")

    assert response.status_code == 200
    assert response.json() == {"tokens": [{"token_id": "token-1", "user_id": "user-1", "name": "CLI"}]}


def test_account_revoke_path_value_errors_return_400(monkeypatch):
    import core.auth_store as auth_store_module
    from api.account_router import router as account_router
    from core.user_context import UserContext, current_user

    class FakeAuthStore:
        def validate_csrf(self, session_token: str, csrf_token: str):
            return session_token == "session" and csrf_token == "csrf"

        def revoke_session(self, user_id: str, session_id: str):
            raise ValueError("bad session id")

        def revoke_api_token(self, user_id: str, token_id: str):
            raise ValueError("bad token id")

    app = FastAPI()
    app.dependency_overrides[current_user] = lambda: UserContext(user_id="user-1", workspace_slug="user-1")
    app.include_router(account_router)
    monkeypatch.setattr(auth_store_module, "auth_store", FakeAuthStore(), raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("lap_session", "session")
    csrf_headers = {"X-CSRF-Token": "csrf"}

    session_response = client.delete("/api/account/sessions/not-a-uuid", headers=csrf_headers)
    token_response = client.delete("/api/account/api-tokens/not-a-uuid", headers=csrf_headers)

    assert session_response.status_code == 400
    assert session_response.json()["detail"] == "bad session id"
    assert token_response.status_code == 400
    assert token_response.json()["detail"] == "bad token id"
