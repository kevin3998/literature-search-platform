from __future__ import annotations

import pytest


def test_cors_defaults_to_localhost_in_development(monkeypatch):
    from core.runtime_config import cors_allow_origins

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)

    assert cors_allow_origins() == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_reads_csv_from_env(monkeypatch):
    from core.runtime_config import cors_allow_origins

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://agent.example.com, https://admin.example.com")

    assert cors_allow_origins() == ["https://agent.example.com", "https://admin.example.com"]


def test_cors_rejects_wildcard_in_production(monkeypatch):
    from core.db.config import DatabaseConfigError
    from core.runtime_config import cors_allow_origins

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")

    with pytest.raises(DatabaseConfigError, match="CORS_ALLOW_ORIGINS"):
        cors_allow_origins()


def test_secret_key_policy_allows_development_autocreate(monkeypatch, tmp_path):
    from core.runtime_config import check_secret_key_policy

    key_path = tmp_path / "dev-secret.key"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LITERATURE_SECRET_KEY_PATH", str(key_path))

    assert check_secret_key_policy()["status"] == "ok"
    assert check_secret_key_policy()["auto_create_allowed"] is True


def test_secret_key_policy_requires_existing_key_in_production(monkeypatch, tmp_path):
    from core.db.config import DatabaseConfigError
    from core.runtime_config import check_secret_key_policy

    key_path = tmp_path / "missing-secret.key"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LITERATURE_SECRET_KEY_PATH", str(key_path))

    with pytest.raises(DatabaseConfigError, match="LITERATURE_SECRET_KEY_PATH"):
        check_secret_key_policy()


def test_worker_required_defaults_to_true_in_production(monkeypatch):
    from core.runtime_config import worker_required

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("WORKER_REQUIRED", raising=False)

    assert worker_required() is True
