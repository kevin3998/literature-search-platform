from __future__ import annotations

import pytest


def test_database_url_requires_postgresql(monkeypatch):
    from core.db.config import DatabaseConfigError, database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseConfigError, match="DATABASE_URL"):
        database_url()

    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/platform.sqlite")
    with pytest.raises(DatabaseConfigError, match="PostgreSQL"):
        database_url()

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")
    assert database_url() == "postgresql+psycopg://user:pass@localhost/db"


def test_database_schema_and_app_env_defaults(monkeypatch):
    from core.db.config import DatabaseConfigError, app_env, database_schema

    monkeypatch.delenv("DB_SCHEMA", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    assert database_schema() == "literature_agent"
    assert app_env() == "development"

    monkeypatch.setenv("DB_SCHEMA", "custom_schema")
    monkeypatch.setenv("APP_ENV", "production")
    assert database_schema() == "custom_schema"
    assert app_env() == "production"

    monkeypatch.setenv("DB_SCHEMA", "bad-schema")
    with pytest.raises(DatabaseConfigError, match="Invalid DB_SCHEMA"):
        database_schema()


def test_pool_defaults_and_overrides(monkeypatch):
    from core.db.config import pool_settings

    for key in (
        "WEB_DB_POOL_SIZE",
        "WEB_DB_MAX_OVERFLOW",
        "DB_POOL_RECYCLE_SECONDS",
        "DB_STATEMENT_TIMEOUT_MS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = pool_settings()
    assert settings.pool_size == 5
    assert settings.max_overflow == 10
    assert settings.pool_recycle_seconds == 1800
    assert settings.statement_timeout_ms == 30000

    monkeypatch.setenv("WEB_DB_POOL_SIZE", "2")
    monkeypatch.setenv("WEB_DB_MAX_OVERFLOW", "3")
    monkeypatch.setenv("DB_POOL_RECYCLE_SECONDS", "60")
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "1000")
    settings = pool_settings()
    assert settings.pool_size == 2
    assert settings.max_overflow == 3
    assert settings.pool_recycle_seconds == 60
    assert settings.statement_timeout_ms == 1000


def test_validate_postgres_url_accepts_supported_drivers():
    from core.db.config import validate_postgres_url

    assert validate_postgres_url("postgresql://u:p@localhost/db") == "postgresql://u:p@localhost/db"
    assert validate_postgres_url("postgresql+psycopg://u:p@localhost/db") == "postgresql+psycopg://u:p@localhost/db"
