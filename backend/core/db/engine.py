from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine

from .config import database_schema, database_url, pool_settings, validate_postgres_url, validate_schema_name


def create_engine_from_env() -> Engine:
    return engine_for_url(database_url(), schema=database_schema())


def engine_for_url(url: str, *, schema: str | None = None) -> Engine:
    validate_postgres_url(url)
    settings = pool_settings()
    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_recycle=settings.pool_recycle_seconds,
    )
    target_schema = validate_schema_name(schema) if schema is not None else database_schema()

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f'SET search_path TO "{target_schema}", public')
            cursor.execute(f"SET statement_timeout = {int(settings.statement_timeout_ms)}")
        finally:
            cursor.close()

    return engine


@contextmanager
def connect(engine: Engine | None = None) -> Iterator[Connection]:
    owned = engine is None
    db_engine = engine or create_engine_from_env()
    try:
        with db_engine.connect() as conn:
            yield conn
    finally:
        if owned:
            db_engine.dispose()
