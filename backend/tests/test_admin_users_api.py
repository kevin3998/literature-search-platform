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
        admin_csrf_headers = {"X-CSRF-Token": admin_client.get("/api/auth/csrf").json()["csrf_token"]}

        users_before = admin_client.get("/api/admin/users")
        disable = admin_client.patch(
            f"/api/admin/users/{bob_id}",
            json={"status": "disabled", "display_name": "Disabled Bob"},
            headers=admin_csrf_headers,
        )
        disabled_login = user_client.post("/api/auth/login", json={"email": "bob@example.com", "password": "password123"})
        enable = admin_client.patch(f"/api/admin/users/{bob_id}", json={"status": "active", "role": "admin"}, headers=admin_csrf_headers)
        enabled_login = user_client.post("/api/auth/login", json={"email": "bob@example.com", "password": "password123"})

    assert admin_signup.status_code == 200
    assert admin_signup.json()["role"] == "admin"
    assert user_signup.status_code == 200
    assert user_signup.json()["role"] == "user"
    assert users_before.status_code == 200
    assert {user["email"] for user in users_before.json()["users"]} == {"admin@example.com", "bob@example.com"}
    assert disable.status_code == 200
    assert disable.json()["status"] == "disabled"
    assert disable.json()["display_name"] == "Disabled Bob"
    assert disabled_login.status_code == 401
    assert enable.status_code == 200
    assert enable.json()["status"] == "active"
    assert enable.json()["role"] == "admin"
    assert enabled_login.status_code == 200


def test_admin_users_default_hides_system_identities_and_can_include_them(monkeypatch):
    import core.auth_store as auth_store_module
    from api.admin_router import router as admin_router
    from api.auth_router import router as auth_router
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        from core.user_store import DEV_HEADER_PROVIDER, TRUSTED_HEADER_PROVIDER, UserStore

        monkeypatch.setenv("AUTH_MODE", "local-password")
        monkeypatch.setenv("COOKIE_NAME", "lap_admin_filter_session")
        store = AuthStore()
        monkeypatch.setattr(auth_store_module, "auth_store", store, raising=False)

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(admin_router)
        admin_client = TestClient(app)
        user_client = TestClient(app)

        admin_client.post(
            "/api/auth/signup",
            json={"email": "admin-filter@example.com", "display_name": "Admin Filter", "password": "password123"},
        )
        user_client.post(
            "/api/auth/signup",
            json={"email": "regular@example.com", "display_name": "Regular User", "password": "password123"},
        )
        user_store = UserStore(engine=store.engine)
        user_store.get_or_create_user_for_subject(provider=DEV_HEADER_PROVIDER, subject="local_user", display_name="local_user")
        user_store.get_or_create_user_for_subject(provider=TRUSTED_HEADER_PROVIDER, subject="chenlintao", display_name="chenlintao")

        default_response = admin_client.get("/api/admin/users")
        system_response = admin_client.get("/api/admin/users?include_system=true")
        search_response = admin_client.get("/api/admin/users?query=chenlintao")

    assert default_response.status_code == 200
    default_users = default_response.json()["users"]
    assert {user["email"] for user in default_users} == {"admin-filter@example.com", "regular@example.com"}
    assert all(user["account_type"] == "local-password" for user in default_users)
    assert all(user["providers"] == ["local-password"] for user in default_users)
    assert all(user["has_password"] is True for user in default_users)
    assert all(user["is_system_identity"] is False for user in default_users)

    assert system_response.status_code == 200
    system_users = system_response.json()["users"]
    by_name = {user["display_name"]: user for user in system_users}
    assert by_name["local_user"]["account_type"] == "system"
    assert by_name["local_user"]["providers"] == ["dev-header"]
    assert by_name["local_user"]["has_password"] is False
    assert by_name["local_user"]["is_system_identity"] is True
    assert by_name["chenlintao"]["account_type"] == "system"
    assert by_name["chenlintao"]["providers"] == ["trusted-header"]
    assert by_name["chenlintao"]["is_system_identity"] is True

    assert search_response.status_code == 200
    assert search_response.json()["users"] == []


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
        csrf_headers = {"X-CSRF-Token": client.get("/api/auth/csrf").json()["csrf_token"]}
        demote = client.patch(f"/api/admin/users/{user_id}", json={"role": "user"}, headers=csrf_headers)
        disable = client.patch(f"/api/admin/users/{user_id}", json={"status": "disabled"}, headers=csrf_headers)

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
        admin_csrf_headers = {"X-CSRF-Token": admin_client.get("/api/auth/csrf").json()["csrf_token"]}
        user_csrf_headers = {"X-CSRF-Token": user_client.get("/api/auth/csrf").json()["csrf_token"]}
        user_client.post("/api/account/api-tokens", json={"name": "Target token"}, headers=user_csrf_headers)

        reset = admin_client.post(
            f"/api/admin/users/{target_id}/reset-password",
            json={"new_password": "resetpassword123"},
            headers=admin_csrf_headers,
        )
        revoke_tokens = admin_client.post(f"/api/admin/users/{target_id}/revoke-api-tokens", headers=admin_csrf_headers)
        revoke_sessions = admin_client.post(f"/api/admin/users/{target_id}/revoke-sessions", headers=admin_csrf_headers)
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
    assert any(event["event_type"] == "admin.reset_password" for event in audit.json()["audit_events"])


def test_admin_collection_routes_use_wrapper_contracts(monkeypatch):
    import core.auth_store as auth_store_module
    from api.admin_router import router as admin_router
    from core.user_context import UserContext, current_user

    class FakeAuthStore:
        def list_users(self, query: str = "", limit: int = 100, offset: int = 0, include_system: bool = False):
            assert include_system is True
            return [{"user_id": "user-1", "email": "admin@example.com"}]

        def list_audit_events(self, limit: int = 100, offset: int = 0):
            return [{"event_id": "event-1", "event_type": "auth.login"}]

    app = FastAPI()
    app.dependency_overrides[current_user] = lambda: UserContext(user_id="admin-1", workspace_slug="admin-1", role="admin")
    app.include_router(admin_router)
    monkeypatch.setattr(auth_store_module, "auth_store", FakeAuthStore(), raising=False)
    client = TestClient(app)

    users_response = client.get("/api/admin/users?include_system=true")
    audit_response = client.get("/api/admin/audit-events")

    assert users_response.status_code == 200
    assert users_response.json() == {"users": [{"user_id": "user-1", "email": "admin@example.com"}]}
    assert audit_response.status_code == 200
    assert audit_response.json() == {"audit_events": [{"event_id": "event-1", "event_type": "auth.login"}]}


def test_admin_write_without_session_cookie_skips_csrf_for_header_auth(monkeypatch):
    import core.auth_store as auth_store_module
    from api.admin_router import router as admin_router
    from core.user_context import UserContext, current_user

    class FakeAuthStore:
        validate_csrf_called = False

        def validate_csrf(self, session_token: str, csrf_token: str):
            self.validate_csrf_called = True
            return False

        def update_user_admin(self, actor_user_id: str, target_user_id: str, **kwargs):
            return {"user_id": target_user_id, "status": kwargs["status"]}

    fake_store = FakeAuthStore()
    app = FastAPI()
    app.dependency_overrides[current_user] = lambda: UserContext(
        user_id="admin-1",
        workspace_slug="admin-1",
        role="admin",
        auth_mode="dev-header",
    )
    app.include_router(admin_router)
    monkeypatch.setattr(auth_store_module, "auth_store", fake_store, raising=False)

    response = TestClient(app).patch("/api/admin/users/user-1", json={"status": "disabled"})

    assert response.status_code == 200
    assert response.json() == {"user_id": "user-1", "status": "disabled"}
    assert fake_store.validate_csrf_called is False


def test_admin_path_value_errors_return_400(monkeypatch):
    import core.auth_store as auth_store_module
    from api.admin_router import router as admin_router
    from core.user_context import UserContext, current_user

    class FakeAuthStore:
        def validate_csrf(self, session_token: str, csrf_token: str):
            return session_token == "session" and csrf_token == "csrf"

        def update_user_admin(self, actor_user_id: str, target_user_id: str, **kwargs):
            raise ValueError("bad user id")

        def reset_password_admin(self, actor_user_id: str, target_user_id: str, new_password: str):
            raise ValueError("bad reset id")

        def revoke_user_sessions_admin(self, actor_user_id: str, target_user_id: str):
            raise ValueError("bad sessions id")

        def revoke_user_api_tokens_admin(self, actor_user_id: str, target_user_id: str):
            raise ValueError("bad tokens id")

    app = FastAPI()
    app.dependency_overrides[current_user] = lambda: UserContext(user_id="admin-1", workspace_slug="admin-1", role="admin")
    app.include_router(admin_router)
    monkeypatch.setattr(auth_store_module, "auth_store", FakeAuthStore(), raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set("lap_session", "session")
    csrf_headers = {"X-CSRF-Token": "csrf"}

    update_response = client.patch("/api/admin/users/not-a-uuid", json={"status": "disabled"}, headers=csrf_headers)
    reset_response = client.post("/api/admin/users/not-a-uuid/reset-password", json={"new_password": "password123"}, headers=csrf_headers)
    sessions_response = client.post("/api/admin/users/not-a-uuid/revoke-sessions", headers=csrf_headers)
    tokens_response = client.post("/api/admin/users/not-a-uuid/revoke-api-tokens", headers=csrf_headers)

    assert update_response.status_code == 400
    assert update_response.json()["detail"] == "bad user id"
    assert reset_response.status_code == 400
    assert reset_response.json()["detail"] == "bad reset id"
    assert sessions_response.status_code == 400
    assert sessions_response.json()["detail"] == "bad sessions id"
    assert tokens_response.status_code == 400
    assert tokens_response.json()["detail"] == "bad tokens id"
