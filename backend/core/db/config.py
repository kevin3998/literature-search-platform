from __future__ import annotations

import os
import re
from dataclasses import dataclass

from sqlalchemy.engine import make_url

DEFAULT_DB_SCHEMA = "literature_agent"
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class DatabaseConfigError(RuntimeError):
    """Raised when the PostgreSQL runtime database is not configured safely."""


@dataclass(frozen=True)
class PoolSettings:
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle_seconds: int = 1800
    statement_timeout_ms: int = 30000


def app_env() -> str:
    return (os.getenv("APP_ENV") or "development").strip().lower()


def database_schema(default: str = DEFAULT_DB_SCHEMA) -> str:
    schema = (os.getenv("DB_SCHEMA") or default).strip()
    return validate_schema_name(schema)


def validate_schema_name(schema: str) -> str:
    if not _SCHEMA_RE.match(schema):
        raise DatabaseConfigError(f"Invalid DB_SCHEMA: {schema!r}")
    return schema


def validate_postgres_url(url: str | None) -> str:
    if not url:
        raise DatabaseConfigError("DATABASE_URL is required for PostgreSQL platform storage")
    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql"):
        raise DatabaseConfigError("DATABASE_URL must use a PostgreSQL driver")
    return url


def database_url() -> str:
    return validate_postgres_url(os.getenv("DATABASE_URL"))


def pool_settings() -> PoolSettings:
    return PoolSettings(
        pool_size=_int_env("WEB_DB_POOL_SIZE", 5),
        max_overflow=_int_env("WEB_DB_MAX_OVERFLOW", 10),
        pool_recycle_seconds=_int_env("DB_POOL_RECYCLE_SECONDS", 1800),
        statement_timeout_ms=_int_env("DB_STATEMENT_TIMEOUT_MS", 30000),
    )


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigError(f"{name} must be an integer") from exc
    if value < 0:
        raise DatabaseConfigError(f"{name} must be non-negative")
    return value
