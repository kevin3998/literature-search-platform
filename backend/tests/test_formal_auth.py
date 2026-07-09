from __future__ import annotations

import pytest

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


def test_signup_rejects_duplicate_email():
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        store = AuthStore()
        store.signup(email="duplicate@example.com", display_name="Original", password="password123")

        with pytest.raises(ValueError, match="email already registered"):
            store.signup(email=" DUPLICATE@example.com ", display_name="Duplicate", password="password123")
