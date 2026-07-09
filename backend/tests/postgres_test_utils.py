from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured; skipping PostgreSQL integration test")
    return url


def alembic_config(database_url: str, schema: str) -> Config:
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("db_schema", schema)
    return cfg


@contextmanager
def migrated_postgres_schema():
    url = test_database_url()
    schema = f"test_{uuid.uuid4().hex}"
    admin_engine = create_engine(url, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f'create schema "{schema}"'))
    try:
        previous_schema = os.environ.get("DB_SCHEMA")
        previous_database_url = os.environ.get("DATABASE_URL")
        previous_auth_mode = os.environ.get("AUTH_MODE")
        previous_app_env = os.environ.get("APP_ENV")
        os.environ["DB_SCHEMA"] = schema
        os.environ["DATABASE_URL"] = url
        os.environ["AUTH_MODE"] = "dev-header"
        os.environ["APP_ENV"] = "development"
        command.upgrade(alembic_config(url, schema), "head")
        yield url, schema
    finally:
        if previous_schema is None:
            os.environ.pop("DB_SCHEMA", None)
        else:
            os.environ["DB_SCHEMA"] = previous_schema
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        if previous_auth_mode is None:
            os.environ.pop("AUTH_MODE", None)
        else:
            os.environ["AUTH_MODE"] = previous_auth_mode
        if previous_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = previous_app_env
        with admin_engine.begin() as conn:
            conn.execute(text(f'drop schema if exists "{schema}" cascade'))
        admin_engine.dispose()
