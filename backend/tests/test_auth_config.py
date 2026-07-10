from __future__ import annotations

import pytest


def test_dev_header_auth_is_rejected_in_production(monkeypatch):
    from core.db.config import DatabaseConfigError
    from core.user_context import auth_mode, validate_auth_runtime

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "dev-header")

    assert auth_mode() == "dev-header"
    with pytest.raises(DatabaseConfigError, match="dev-header"):
        validate_auth_runtime()


def test_trusted_header_auth_is_allowed_in_production(monkeypatch):
    from core.user_context import auth_mode, trusted_user_header_name, validate_auth_runtime

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "trusted-header")
    monkeypatch.delenv("TRUSTED_USER_HEADER", raising=False)

    assert auth_mode() == "trusted-header"
    assert trusted_user_header_name() == "X-Forwarded-User"
    validate_auth_runtime()


def test_local_password_and_hybrid_auth_modes_are_supported(monkeypatch):
    from core.user_context import auth_mode, validate_auth_runtime

    monkeypatch.setenv("APP_ENV", "production")

    monkeypatch.setenv("AUTH_MODE", "local-password")
    assert auth_mode() == "local-password"
    validate_auth_runtime()

    monkeypatch.setenv("AUTH_MODE", "hybrid")
    assert auth_mode() == "hybrid"
    validate_auth_runtime()


def test_dev_subject_validation_keeps_filesystem_safe_boundary():
    from core.user_context import validate_subject

    assert validate_subject(None) == "local_user"
    assert validate_subject("alice.01") == "alice.01"
    for value in ["../alice", "alice/bob", "alice bob", "", "." * 65]:
        with pytest.raises(ValueError):
            validate_subject(value)
