from __future__ import annotations

from postgres_test_utils import migrated_postgres_schema


def test_postgres_readiness_checks_connection_and_migration_head():
    from core.db.engine import engine_for_url
    from core.db.readiness import check_alembic_at_head, check_postgres_connection

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            connection = check_postgres_connection(engine)
            migration = check_alembic_at_head(engine)
        finally:
            engine.dispose()

    assert connection["status"] == "ok"
    assert migration["status"] == "ok"
    assert migration["current"] == migration["head"]
