from __future__ import annotations

from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core.user_context import UserContext, current_user, validate_subject


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: UserContext = Depends(current_user)):
        return {"user_id": user.user_id, "workspace_slug": user.workspace_slug}

    return app


def test_current_user_defaults_to_local_user(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    response = TestClient(_app()).get("/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": "00000000-0000-4000-8000-000000000001", "workspace_slug": "local_user"}


def test_current_user_accepts_valid_header_user(monkeypatch) -> None:
    _install_fake_user_store(monkeypatch)
    response = TestClient(_app()).get("/whoami", headers={"X-User-Id": "alice.01"})

    assert response.status_code == 200
    assert response.json() == {"user_id": "00000000-0000-4000-8000-000000000002", "workspace_slug": "alice.01"}


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
    assert response.json() == {"user_id": "00000000-0000-4000-8000-000000000002", "workspace_slug": "alice.01"}


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
            }

    monkeypatch.setitem(
        __import__("sys").modules,
        "core.user_store",
        SimpleNamespace(DEV_HEADER_PROVIDER="dev-header", TRUSTED_HEADER_PROVIDER="trusted-header", user_store=FakeUserStore()),
    )
