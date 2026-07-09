from __future__ import annotations

import pytest
from sqlalchemy import text

from postgres_test_utils import migrated_postgres_schema


def test_engine_for_url_rejects_non_postgres_urls():
    from core.db.config import DatabaseConfigError
    from core.db.engine import engine_for_url

    with pytest.raises(DatabaseConfigError, match="PostgreSQL"):
        engine_for_url("sqlite:///tmp/platform.sqlite")

    with pytest.raises(DatabaseConfigError, match="Invalid DB_SCHEMA"):
        engine_for_url("postgresql+psycopg://u:p@localhost/db", schema="bad-schema")


def test_engine_sets_schema_search_path():
    from core.db.engine import engine_for_url

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            with engine.connect() as conn:
                current_schema = conn.execute(text("select current_schema()")).scalar_one()
                search_path = conn.execute(text("show search_path")).scalar_one()
            assert current_schema == schema
            assert schema in search_path
            assert "public" in search_path
        finally:
            engine.dispose()
