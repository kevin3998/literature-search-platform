from __future__ import annotations

import sys
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core.user_context import UserContext, current_user, validate_subject


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: UserContext = Depends(current_user)):
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

    return app


def test_current_user_defaults_to_local_user(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    response = TestClient(_app()).get("/whoami")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "00000000-0000-4000-8000-000000000001",
        "workspace_slug": "local_user",
        "subject": "local_user",
        "display_name": "local_user",
        "auth_mode": "dev-header",
        "role": "user",
        "status": "active",
        "email": None,
    }


def test_current_user_accepts_valid_header_user(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    response = TestClient(_app()).get("/whoami", headers={"X-User-Id": "alice.01"})

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "00000000-0000-4000-8000-000000000002",
        "workspace_slug": "alice.01",
        "subject": "alice.01",
        "display_name": "alice.01",
        "auth_mode": "dev-header",
        "role": "user",
        "status": "active",
        "email": None,
    }


def test_current_user_rejects_path_like_or_invalid_ids() -> None:
    client = TestClient(_app())

    for value in ["../alice", "alice/bob", "alice bob", "", "." * 65]:
        response = client.get("/whoami", headers={"X-User-Id": value})

        assert response.status_code == 400
        assert response.json()["detail"] == "invalid user id"


def test_trusted_header_requires_proxy_user_header(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "trusted-header")
    monkeypatch.setenv("APP_ENV", "production")

    response = TestClient(_app()).get("/whoami")

    assert response.status_code == 401
    assert response.json()["detail"] == "trusted user header required"


def test_trusted_header_creates_user_from_proxy_headers(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "trusted-header")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TRUSTED_USER_HEADER", "X-Auth-User")
    monkeypatch.setenv("TRUSTED_DISPLAY_NAME_HEADER", "X-Auth-Name")

    response = TestClient(_app()).get(
        "/whoami",
        headers={"X-Auth-User": "alice.01", "X-Auth-Name": "Alice Chen"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "00000000-0000-4000-8000-000000000002",
        "workspace_slug": "alice.01",
        "subject": "alice.01",
        "display_name": "Alice Chen",
        "auth_mode": "trusted-header",
        "role": "user",
        "status": "active",
        "email": None,
    }


def test_local_password_session_cookie_resolves_current_user(monkeypatch) -> None:
    _install_fake_auth_store(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local-password")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COOKIE_NAME", "lap_test")

    client = TestClient(_app())
    client.cookies.set("lap_test", "valid-session")
    response = client.get("/whoami")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "00000000-0000-4000-8000-000000000003",
        "workspace_slug": "00000000-0000-4000-8000-000000000003",
        "subject": "local@example.com",
        "display_name": "Local User",
        "auth_mode": "local-password",
        "role": "admin",
        "status": "active",
        "email": "local@example.com",
    }


def test_local_password_session_cookie_is_required(monkeypatch) -> None:
    _install_fake_auth_store(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "local-password")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COOKIE_NAME", "lap_test")

    client = TestClient(_app())
    client.cookies.set("lap_test", "invalid-session")
    response = client.get("/whoami")

    assert response.status_code == 401
    assert response.json()["detail"] == "valid session required"


def test_hybrid_uses_trusted_header_before_session_cookie(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    _install_fake_auth_store(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "hybrid")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COOKIE_NAME", "lap_test")
    monkeypatch.setenv("TRUSTED_USER_HEADER", "X-Auth-User")
    monkeypatch.setenv("TRUSTED_DISPLAY_NAME_HEADER", "X-Auth-Name")

    client = TestClient(_app())
    client.cookies.set("lap_test", "valid-session")
    response = client.get(
        "/whoami",
        headers={"X-Auth-User": "alice.01", "X-Auth-Name": "Alice Chen"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "00000000-0000-4000-8000-000000000002",
        "workspace_slug": "alice.01",
        "subject": "alice.01",
        "display_name": "Alice Chen",
        "auth_mode": "hybrid",
        "role": "user",
        "status": "active",
        "email": None,
    }


def test_hybrid_falls_back_to_session_cookie_without_trusted_header(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    _install_fake_auth_store(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "hybrid")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COOKIE_NAME", "lap_test")
    monkeypatch.setenv("TRUSTED_USER_HEADER", "X-Auth-User")

    client = TestClient(_app())
    client.cookies.set("lap_test", "valid-session")
    response = client.get("/whoami", headers={"X-User-Id": "alice.01"})

    assert response.status_code == 200
    assert response.json()["user_id"] == "00000000-0000-4000-8000-000000000003"
    assert response.json()["subject"] == "local@example.com"


def test_validate_subject_defaults_and_rejects_unsafe_values() -> None:
    assert validate_subject(None) == "local_user"
    assert validate_subject(" alice.01 ") == "alice.01"

    for value in ["../alice", "alice/bob", "alice bob", "", "." * 65]:
        try:
            validate_subject(value)
        except ValueError as exc:
            assert str(exc) == "invalid user id"
        else:  # pragma: no cover - keeps the assertion message direct.
            raise AssertionError(f"expected invalid subject: {value!r}")


def _install_fake_user_store(monkeypatch) -> None:
    class FakeUserStore:
        def get_or_create_user_for_subject(self, *, provider: str, subject: str, display_name: str | None = None):
            suffix = "2" if subject == "alice.01" else "1"
            return {
                "user_id": f"00000000-0000-4000-8000-00000000000{suffix}",
                "subject": subject,
                "display_name": display_name or subject,
                "role": "user",
                "status": "active",
                "email": None,
            }

    monkeypatch.setitem(
        sys.modules,
        "core.user_store",
        SimpleNamespace(DEV_HEADER_PROVIDER="dev-header", TRUSTED_HEADER_PROVIDER="trusted-header", user_store=FakeUserStore()),
    )


def _install_fake_auth_store(monkeypatch) -> None:
    class FakeAuthStore:
        def user_for_session_token(self, token: str):
            if token != "valid-session":
                return None
            return {
                "user_id": "00000000-0000-4000-8000-000000000003",
                "display_name": "Local User",
                "role": "admin",
                "status": "active",
                "email": "local@example.com",
                "avatar_url": None,
            }

    monkeypatch.setitem(sys.modules, "core.auth_store", SimpleNamespace(auth_store=FakeAuthStore()))
