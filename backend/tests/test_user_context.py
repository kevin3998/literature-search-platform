from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core.user_context import UserContext, current_user


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: UserContext = Depends(current_user)):
        return {"user_id": user.user_id, "workspace_slug": user.workspace_slug}

    return app


def test_current_user_defaults_to_local_user() -> None:
    response = TestClient(_app()).get("/whoami")

    assert response.status_code == 200
    assert response.json() == {"user_id": "local_user", "workspace_slug": "local_user"}


def test_current_user_accepts_valid_header_user() -> None:
    response = TestClient(_app()).get("/whoami", headers={"X-User-Id": "alice.01"})

    assert response.status_code == 200
    assert response.json() == {"user_id": "alice.01", "workspace_slug": "alice.01"}


def test_current_user_rejects_path_like_or_invalid_ids() -> None:
    client = TestClient(_app())

    for value in ["../alice", "alice/bob", "alice bob", "", "." * 65]:
        response = client.get("/whoami", headers={"X-User-Id": value})

        assert response.status_code == 400
        assert response.json()["detail"] == "invalid user id"
