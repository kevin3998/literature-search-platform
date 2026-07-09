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
        profile_before = client.get("/api/account/profile")
        profile_update = client.patch(
            "/api/account/profile",
            json={"display_name": "Updated User", "avatar_url": "https://example.com/avatar.png"},
        )
        sessions = client.get("/api/account/sessions")
        token_create = client.post("/api/account/api-tokens", json={"name": "CLI"})
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
    listed = token_list.json()
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
        token_create = client.post("/api/account/api-tokens", json={"name": "Old token"})
        token_id = token_create.json()["token_id"]
        revoke_token = client.delete(f"/api/account/api-tokens/{token_id}")
        password_change = client.post(
            "/api/account/password",
            json={"current_password": "password123", "new_password": "newpassword123"},
        )
        client.post("/api/auth/logout")
        old_login = client.post("/api/auth/login", json={"email": "change@example.com", "password": "password123"})
        new_login = client.post("/api/auth/login", json={"email": "change@example.com", "password": "newpassword123"})
        session_id = client.get("/api/account/sessions").json()[0]["session_id"]
        revoke_session = client.delete(f"/api/account/sessions/{session_id}")
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
