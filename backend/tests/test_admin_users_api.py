from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.postgres_test_utils import migrated_postgres_schema


def test_admin_can_list_update_disable_and_enable_users(monkeypatch):
    import core.auth_store as auth_store_module
    from api.admin_router import router as admin_router
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_admin_session")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(admin_router)
        admin_client = TestClient(app)
        user_client = TestClient(app)

        admin_signup = admin_client.post(
            "/api/auth/signup",
            json={"email": "admin@example.com", "display_name": "Admin", "password": "password123"},
        )
        user_signup = user_client.post(
            "/api/auth/signup",
            json={"email": "bob@example.com", "display_name": "Bob", "password": "password123"},
        )
        bob_id = user_signup.json()["user_id"]

        users_before = admin_client.get("/api/admin/users")
        disable = admin_client.patch(f"/api/admin/users/{bob_id}", json={"status": "disabled", "display_name": "Disabled Bob"})
        disabled_login = user_client.post("/api/auth/login", json={"email": "bob@example.com", "password": "password123"})
        enable = admin_client.patch(f"/api/admin/users/{bob_id}", json={"status": "active", "role": "admin"})
        enabled_login = user_client.post("/api/auth/login", json={"email": "bob@example.com", "password": "password123"})

    assert admin_signup.status_code == 200
    assert admin_signup.json()["role"] == "admin"
    assert user_signup.status_code == 200
    assert user_signup.json()["role"] == "user"
    assert users_before.status_code == 200
    assert {user["email"] for user in users_before.json()} == {"admin@example.com", "bob@example.com"}
    assert disable.status_code == 200
    assert disable.json()["status"] == "disabled"
    assert disable.json()["display_name"] == "Disabled Bob"
    assert disabled_login.status_code == 401
    assert enable.status_code == 200
    assert enable.json()["status"] == "active"
    assert enable.json()["role"] == "admin"
    assert enabled_login.status_code == 200


def test_admin_rejects_last_admin_demotion_and_disable(monkeypatch):
    import core.auth_store as auth_store_module
    from api.admin_router import router as admin_router
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_last_admin_session")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(admin_router)
        client = TestClient(app)

        signup = client.post(
            "/api/auth/signup",
            json={"email": "solo@example.com", "display_name": "Solo Admin", "password": "password123"},
        )
        user_id = signup.json()["user_id"]
        demote = client.patch(f"/api/admin/users/{user_id}", json={"role": "user"})
        disable = client.patch(f"/api/admin/users/{user_id}", json={"status": "disabled"})

    assert signup.status_code == 200
    assert demote.status_code == 400
    assert "last active admin" in demote.json()["detail"]
    assert disable.status_code == 400
    assert "last active admin" in disable.json()["detail"]


def test_admin_reset_password_revoke_targets_and_audit(monkeypatch):
    import core.auth_store as auth_store_module
    from api.account_router import router as account_router
    from api.admin_router import router as admin_router
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_admin_ops_session")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(account_router)
        app.include_router(admin_router)
        admin_client = TestClient(app)
        user_client = TestClient(app)

        admin_client.post(
            "/api/auth/signup",
            json={"email": "adminops@example.com", "display_name": "Admin Ops", "password": "password123"},
        )
        user_signup = user_client.post(
            "/api/auth/signup",
            json={"email": "target@example.com", "display_name": "Target", "password": "password123"},
        )
        target_id = user_signup.json()["user_id"]
        user_client.post("/api/account/api-tokens", json={"name": "Target token"})

        reset = admin_client.post(f"/api/admin/users/{target_id}/reset-password", json={"new_password": "resetpassword123"})
        revoke_tokens = admin_client.post(f"/api/admin/users/{target_id}/revoke-api-tokens")
        revoke_sessions = admin_client.post(f"/api/admin/users/{target_id}/revoke-sessions")
        old_login = user_client.post("/api/auth/login", json={"email": "target@example.com", "password": "password123"})
        new_login = user_client.post("/api/auth/login", json={"email": "target@example.com", "password": "resetpassword123"})
        audit = admin_client.get("/api/admin/audit-events")

    assert reset.status_code == 200
    assert reset.json() == {"ok": True}
    assert revoke_tokens.status_code == 200
    assert revoke_tokens.json()["revoked"] == 1
    assert revoke_sessions.status_code == 200
    assert revoke_sessions.json()["revoked"] >= 1
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert audit.status_code == 200
    assert any(event["event_type"] == "admin.reset_password" for event in audit.json())
