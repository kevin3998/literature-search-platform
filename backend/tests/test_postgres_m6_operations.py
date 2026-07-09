from __future__ import annotations

import importlib
import sys

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from postgres_test_utils import migrated_postgres_schema


def _reload_main():
    for name in [
        "main",
        "api.modules_router",
        "core.user_context",
        "core.user_store",
        "core.secret_store",
        "core.runtime_config",
    ]:
        sys.modules.pop(name, None)
    return importlib.import_module("main")


def test_trusted_header_api_me_creates_internal_user(monkeypatch, tmp_path):
    key_path = tmp_path / "secret.key"
    key_path.write_bytes(Fernet.generate_key())
    with migrated_postgres_schema() as (url, schema):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("AUTH_MODE", "trusted-header")
        monkeypatch.setenv("LITERATURE_SECRET_KEY_PATH", str(key_path))
        monkeypatch.setenv("TRUSTED_USER_HEADER", "X-Auth-User")
        monkeypatch.setenv("TRUSTED_DISPLAY_NAME_HEADER", "X-Auth-Name")
        main = _reload_main()
        client = TestClient(main.app)

        missing = client.get("/api/me")
        response = client.get("/api/me", headers={"X-Auth-User": "alice.01", "X-Auth-Name": "Alice Chen"})

        engine = create_engine(url, future=True)
        with engine.connect() as conn:
            display_name = conn.execute(
                text(f'select display_name from "{schema}".users where user_id = :user_id'),
                {"user_id": response.json()["user_id"]},
            ).scalar_one()
        engine.dispose()

    assert missing.status_code == 401
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["subject"] == "alice.01"
    assert body["display_name"] == "Alice Chen"
    assert body["auth_mode"] == "trusted-header"
    assert display_name == "Alice Chen"
