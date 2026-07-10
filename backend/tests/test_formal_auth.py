from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from tests.postgres_test_utils import migrated_postgres_schema


def test_session_cookie_name_prefers_cookie_name(monkeypatch):
    from core.runtime_config import session_cookie_name

    monkeypatch.setenv("COOKIE_NAME", "primary_cookie")
    monkeypatch.setenv("SESSION_COOKIE_NAME", "legacy_cookie")

    assert session_cookie_name() == "primary_cookie"


def test_signup_bootstraps_first_admin_and_later_user():
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        store = AuthStore()

        first = store.signup(email=" First@Example.COM ", display_name="First", password="password123")
        second = store.signup(email="second@example.com", display_name="Second", password="password123")

    assert first["email"] == "first@example.com"
    assert first["role"] == "admin"
    assert first["status"] == "active"
    assert second["email"] == "second@example.com"
    assert second["role"] == "user"
    assert second["status"] == "active"


def test_signup_bootstraps_admin_when_legacy_non_admin_user_exists():
    from sqlalchemy import text

    from core.auth_store import AuthStore
    from core.db.types import new_uuid, utc_now, uuid_value

    with migrated_postgres_schema():
        store = AuthStore()
        ts = utc_now()
        with store.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into users(user_id, display_name, status, metadata_json, created_at, updated_at, role)
                    values(:user_id, 'Legacy User', 'active', '{}'::jsonb, :ts, :ts, 'user')
                    """
                ),
                {"user_id": uuid_value(new_uuid()), "ts": ts},
            )

        formal_user = store.signup(email="formal@example.com", display_name="Formal", password="password123")

    assert formal_user["role"] == "admin"


def test_signup_bootstraps_admin_when_only_disabled_admin_exists():
    from sqlalchemy import text

    from core.auth_store import AuthStore
    from core.db.types import new_uuid, utc_now, uuid_value

    with migrated_postgres_schema():
        store = AuthStore()
        ts = utc_now()
        with store.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into users(user_id, display_name, status, metadata_json, created_at, updated_at, role)
                    values(:user_id, 'Disabled Admin', 'disabled', '{}'::jsonb, :ts, :ts, 'admin')
                    """
                ),
                {"user_id": uuid_value(new_uuid()), "ts": ts},
            )

        formal_user = store.signup(email="replacement-admin@example.com", display_name="Replacement", password="password123")

    assert formal_user["role"] == "admin"


def test_login_creates_session_and_validates_cookie_token():
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        store = AuthStore()
        signed_up = store.signup(email="user@example.com", display_name="User", password="password123")

        login = store.login(
            email=" USER@example.com ",
            password="password123",
            user_agent="pytest",
            ip_address="127.0.0.1",
        )
        session_user = store.user_for_session_token(login["session_token"])

    assert login["user"]["user_id"] == signed_up["user_id"]
    assert login["user"]["email"] == "user@example.com"
    assert login["session_token"].startswith("sess_")
    assert login["csrf_token"].startswith("csrf_")
    assert session_user is not None
    assert session_user["email"] == "user@example.com"


def test_current_user_resolves_real_auth_session_cookie(monkeypatch):
    from core.auth_store import AuthStore
    import core.auth_store as auth_store_module
    from core.user_context import UserContext, current_user

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("COOKIE_NAME", "lap_test")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)
        signed_up = store.signup(email="session@example.com", display_name="Session User", password="password123")
        login = store.login(email="session@example.com", password="password123", user_agent="pytest", ip_address="127.0.0.1")

        app = FastAPI()

        @app.get("/session-whoami")
        def session_whoami(user: UserContext = Depends(current_user)):
            return {
                "user_id": user.user_id,
                "workspace_slug": user.workspace_slug,
                "subject": user.subject,
                "display_name": user.display_name,
                "auth_mode": user.auth_mode,
                "role": user.role,
                "status": user.status,
                "email": user.email,
            }

        client = TestClient(app)
        client.cookies.set("lap_test", login["session_token"])
        response = client.get("/session-whoami")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": signed_up["user_id"],
        "workspace_slug": signed_up["user_id"],
        "subject": "session@example.com",
        "display_name": "Session User",
        "auth_mode": "local-password",
        "role": "admin",
        "status": "active",
        "email": "session@example.com",
    }


def test_signup_rejects_duplicate_email():
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        store = AuthStore()
        store.signup(email="duplicate@example.com", display_name="Original", password="password123")

        with pytest.raises(ValueError, match="email already registered"):
            store.signup(email=" DUPLICATE@example.com ", display_name="Duplicate", password="password123")


def test_cookie_state_change_requires_csrf(monkeypatch):
    import core.auth_store as auth_store_module
    from api.account_router import router as account_router
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_csrf_session")
        monkeypatch.setenv("CSRF_COOKIE_NAME", "lap_csrf_token")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(account_router)
        client = TestClient(app)

        signup_response = client.post(
            "/api/auth/signup",
            json={"email": "csrf@example.com", "display_name": "CSRF User", "password": "password123"},
        )
        missing_csrf_profile = client.patch("/api/account/profile", json={"display_name": "No Token"})
        csrf_response = client.get("/api/auth/csrf")
        csrf_headers = {"X-CSRF-Token": csrf_response.json()["csrf_token"]}
        profile_response = client.patch("/api/account/profile", json={"display_name": "With Token"}, headers=csrf_headers)
        missing_csrf_logout = client.post("/api/auth/logout")
        client.cookies.delete("lap_csrf_token")
        reissued_csrf_response = client.get("/api/auth/csrf")
        reissued_csrf_headers = {"X-CSRF-Token": reissued_csrf_response.json()["csrf_token"]}
        logout_response = client.post("/api/auth/logout", headers=reissued_csrf_headers)

    assert signup_response.status_code == 200
    assert missing_csrf_profile.status_code == 403
    assert missing_csrf_profile.json()["detail"] == "csrf failed"
    assert csrf_response.status_code == 200
    assert profile_response.status_code == 200
    assert profile_response.json()["display_name"] == "With Token"
    assert missing_csrf_logout.status_code == 403
    assert missing_csrf_logout.json()["detail"] == "csrf failed"
    assert reissued_csrf_response.status_code == 200
    assert reissued_csrf_response.json()["csrf_token"].startswith("csrf_")
    assert logout_response.status_code == 200
    assert logout_response.json() == {"ok": True}


def test_auth_csrf_reissues_missing_cookie_for_valid_session(monkeypatch):
    import core.auth_store as auth_store_module
    from api.auth_router import router as auth_router
    from core.runtime_config import csrf_cookie_name

    class FakeAuthStore:
        def user_for_session_token(self, session_token: str):
            if session_token != "session":
                return None
            return {
                "user_id": "user-1",
                "display_name": "Session User",
                "status": "active",
                "email": "session@example.com",
                "role": "user",
            }

        def reissue_csrf(self, session_token: str):
            if session_token == "session":
                return {"csrf_token": "csrf_reissued", "expires_at": datetime(2026, 8, 9, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai"))}
            return None

    monkeypatch.setenv("AUTH_MODE", "local-password")
    monkeypatch.setenv("COOKIE_NAME", "lap_reissue_session")
    monkeypatch.setenv("CSRF_COOKIE_NAME", "lap_reissue_csrf")
    monkeypatch.setattr(auth_store_module, "auth_store", FakeAuthStore(), raising=False)

    app = FastAPI()
    app.include_router(auth_router)
    client = TestClient(app)
    client.cookies.set("lap_reissue_session", "session")

    response = client.get("/api/auth/csrf")

    assert response.status_code == 200
    assert response.json() == {"csrf_token": "csrf_reissued"}
    assert response.cookies[csrf_cookie_name()] == "csrf_reissued"
    assert "GMT" in response.headers["set-cookie"]


def test_auth_api_signup_me_and_logout(monkeypatch):
    import core.auth_store as auth_store_module
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore
    from core.runtime_config import csrf_cookie_name, session_cookie_name

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_test_session")
        monkeypatch.setenv("CSRF_COOKIE_NAME", "lap_test_csrf")
        session_name = session_cookie_name()
        csrf_name = csrf_cookie_name()
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        client = TestClient(app)

        signup_response = client.post(
            "/api/auth/signup",
            json={"email": "ApiUser@example.com", "display_name": "API User", "password": "password123"},
        )
        me_response = client.get("/api/auth/me")
        csrf_response = client.get("/api/auth/csrf")
        logout_response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_response.json()["csrf_token"]})
        after_logout_response = client.get("/api/auth/me")

    assert signup_response.status_code == 200
    signed_up = signup_response.json()
    assert signed_up["email"] == "apiuser@example.com"
    assert signed_up["role"] == "admin"
    assert session_name in signup_response.cookies
    assert csrf_name in signup_response.cookies
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "apiuser@example.com"
    assert csrf_response.status_code == 200
    assert logout_response.status_code == 200
    assert logout_response.json() == {"ok": True}
    assert after_logout_response.status_code == 401


def test_auth_api_login_sets_fresh_session_cookie(monkeypatch):
    import core.auth_store as auth_store_module
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore
    from core.runtime_config import session_cookie_name

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_login_session")
        session_name = session_cookie_name()
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)
        store.signup(email="login@example.com", display_name="Login User", password="password123")

        app = FastAPI()
        app.include_router(auth_router)
        client = TestClient(app)

        failed_response = client.post("/api/auth/login", json={"email": "login@example.com", "password": "wrongpassword"})
        login_response = client.post("/api/auth/login", json={"email": "LOGIN@example.com", "password": "password123"})

    assert failed_response.status_code == 401
    assert login_response.status_code == 200
    assert login_response.json()["email"] == "login@example.com"
    assert session_name in login_response.cookies
