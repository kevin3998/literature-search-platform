from __future__ import annotations

import os
from pathlib import Path
import uuid

from alembic import command
from sqlalchemy import create_engine, inspect, text

from postgres_test_utils import alembic_config, migrated_postgres_schema, test_database_url


CORE_TABLES = {
    "users",
    "user_identities",
    "audit_events",
    "settings",
    "model_profiles",
    "user_secrets",
    "sessions",
    "messages",
    "turns",
    "search_results",
    "evidence_items",
    "research_state",
    "paper_states",
    "evidence_states",
    "research_state_events",
    "session_attachments",
    "tool_traces",
    "artifacts",
    "conversation_artifact_links",
    "jobs",
    "job_events",
    "worker_heartbeats",
    "workflow_runs",
    "workflow_steps",
    "structured_extraction_tasks",
    "structured_extraction_runs",
    "structured_extraction_multimodal_review_jobs",
}


def test_initial_migration_creates_core_tables_in_dedicated_schema_only():
    from core.db.engine import engine_for_url

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            inspector = inspect(engine)
            tables = set(inspector.get_table_names(schema=schema))
            public_tables = set(inspector.get_table_names(schema="public"))
        finally:
            engine.dispose()

    assert CORE_TABLES.issubset(tables)
    assert not (CORE_TABLES & public_tables)


def test_initial_migration_uses_postgres_types_and_constraints():
    from core.db.engine import engine_for_url

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        select column_name, data_type, udt_name
                        from information_schema.columns
                        where table_schema = :schema
                          and table_name = 'sessions'
                          and column_name in ('session_id', 'metadata_json', 'created_at')
                        """
                    ),
                    {"schema": schema},
                ).mappings().all()
                session_columns = {row["column_name"]: row for row in rows}
                settings_pk = conn.execute(
                    text(
                        """
                        select kcu.column_name
                        from information_schema.table_constraints tc
                        join information_schema.key_column_usage kcu
                          on tc.constraint_name = kcu.constraint_name
                         and tc.table_schema = kcu.table_schema
                        where tc.table_schema = :schema
                          and tc.table_name = 'settings'
                          and tc.constraint_type = 'PRIMARY KEY'
                        order by kcu.ordinal_position
                        """
                    ),
                    {"schema": schema},
                ).scalars().all()
                identity_uniques = conn.execute(
                    text(
                        """
                        select count(*)
                        from pg_constraint c
                        join pg_namespace n on n.oid = c.connamespace
                        join pg_class t on t.oid = c.conrelid
                        where n.nspname = :schema
                          and t.relname = 'user_identities'
                          and c.contype = 'u'
                        """
                    ),
                    {"schema": schema},
                ).scalar_one()
                job_columns = set(
                    conn.execute(
                        text(
                            """
                            select column_name
                            from information_schema.columns
                            where table_schema = :schema
                              and table_name = 'jobs'
                            """
                        ),
                        {"schema": schema},
                    ).scalars()
                )
                session_indexes = {
                    row["indexname"]
                    for row in conn.execute(
                        text(
                            """
                            select indexname
                            from pg_indexes
                            where schemaname = :schema
                              and tablename = 'sessions'
                            """
                        ),
                        {"schema": schema},
                    ).mappings()
                }
        finally:
            engine.dispose()

    assert session_columns["session_id"]["udt_name"] == "uuid"
    assert session_columns["metadata_json"]["udt_name"] == "jsonb"
    assert session_columns["created_at"]["data_type"] == "timestamp with time zone"
    assert settings_pk == ["user_id", "scope", "key"]
    assert identity_uniques >= 1
    assert "queue" in job_columns
    assert "idx_sessions_user_updated" in session_indexes


def test_partial_unique_active_model_profile_per_user_and_settings_key():
    from core.db.engine import engine_for_url

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            user_id = uuid.uuid4()
            profile_1 = uuid.uuid4()
            profile_2 = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(
                    text("insert into users(user_id, display_name) values(:user_id, 'Alice')"),
                    {"user_id": user_id},
                )
                conn.execute(
                    text(
                        """
                        insert into settings(user_id, scope, key, value_json)
                        values(:user_id, 'models', 'provider', '\"openai\"'::jsonb)
                        """
                    ),
                    {"user_id": user_id},
                )
                duplicate_settings_failed = False
                with conn.begin_nested() as nested:
                    try:
                        conn.execute(
                            text(
                                """
                                insert into settings(user_id, scope, key, value_json)
                                values(:user_id, 'models', 'provider', '\"anthropic\"'::jsonb)
                                """
                            ),
                            {"user_id": user_id},
                        )
                    except Exception:
                        duplicate_settings_failed = True
                        nested.rollback()
                conn.execute(
                    text(
                        """
                        insert into model_profiles(profile_id, user_id, name, provider, active)
                        values(:profile_id, :user_id, 'Default', 'openai', true)
                        """
                    ),
                    {"profile_id": profile_1, "user_id": user_id},
                )
                second_active_failed = False
                with conn.begin_nested() as nested:
                    try:
                        conn.execute(
                            text(
                                """
                                insert into model_profiles(profile_id, user_id, name, provider, active)
                                values(:profile_id, :user_id, 'Other', 'anthropic', true)
                                """
                            ),
                            {"profile_id": profile_2, "user_id": user_id},
                        )
                    except Exception:
                        second_active_failed = True
                        nested.rollback()
        finally:
            engine.dispose()

    assert duplicate_settings_failed
    assert second_active_failed


def test_session_hard_delete_cascades_children_but_audit_events_remain():
    from core.db.engine import engine_for_url

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            user_id = uuid.uuid4()
            session_id = uuid.uuid4()
            message_id = uuid.uuid4()
            event_id = uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(text("insert into users(user_id, display_name) values(:id, 'Alice')"), {"id": user_id})
                conn.execute(
                    text(
                        """
                        insert into sessions(session_id, user_id, module_id, title)
                        values(:session_id, :user_id, 'literature_search', 'T')
                        """
                    ),
                    {"session_id": session_id, "user_id": user_id},
                )
                conn.execute(
                    text(
                        """
                        insert into messages(message_id, session_id, role, content)
                        values(:message_id, :session_id, 'user', 'hello')
                        """
                    ),
                    {"message_id": message_id, "session_id": session_id},
                )
                conn.execute(
                    text(
                        """
                        insert into audit_events(event_id, actor_user_id, event_type, resource_type, resource_id, outcome)
                        values(:event_id, :user_id, 'session.deleted', 'session', :resource_id, 'ok')
                        """
                    ),
                    {"event_id": event_id, "user_id": user_id, "resource_id": str(session_id)},
                )
                conn.execute(text("delete from sessions where session_id = :session_id"), {"session_id": session_id})
                message_count = conn.execute(text("select count(*) from messages where session_id = :session_id"), {"session_id": session_id}).scalar_one()
                audit_count = conn.execute(text("select count(*) from audit_events where event_id = :event_id"), {"event_id": event_id}).scalar_one()
        finally:
            engine.dispose()

    assert message_count == 0
    assert audit_count == 1


def test_m5_structured_async_tables_link_to_core_jobs():
    from core.db.engine import engine_for_url

    expected_tables = {
        "structured_extraction_evidence_packet_build_jobs",
        "structured_extraction_runs",
        "structured_extraction_multimodal_review_jobs",
    }

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            with engine.connect() as conn:
                columns = {
                    row["table_name"]: row["column_name"]
                    for row in conn.execute(
                        text(
                            """
                            select table_name, column_name
                            from information_schema.columns
                            where table_schema = :schema
                              and table_name = any(:tables)
                              and column_name = 'core_job_id'
                            """
                        ),
                        {"schema": schema, "tables": list(expected_tables)},
                    ).mappings()
                }
                fk_count = conn.execute(
                    text(
                        """
                        select count(*)
                        from pg_constraint c
                        join pg_namespace n on n.oid = c.connamespace
                        join pg_class t on t.oid = c.conrelid
                        where n.nspname = :schema
                          and t.relname = any(:tables)
                          and c.contype = 'f'
                          and pg_get_constraintdef(c.oid) like '%core_job_id%'
                          and pg_get_constraintdef(c.oid) like '%jobs%'
                        """
                    ),
                    {"schema": schema, "tables": list(expected_tables)},
                ).scalar_one()
        finally:
            engine.dispose()

    assert set(columns) == expected_tables
    assert fk_count == 3


def test_formal_user_management_schema_is_present():
    from core.db.engine import engine_for_url

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            with engine.connect() as conn:
                user_columns = set(
                    conn.execute(
                        text(
                            """
                            select column_name
                            from information_schema.columns
                            where table_schema = :schema
                              and table_name = 'users'
                            """
                        ),
                        {"schema": schema},
                    ).scalars()
                )
                auth_tables = set(
                    conn.execute(
                        text(
                            """
                            select table_name
                            from information_schema.tables
                            where table_schema = :schema
                              and table_name in ('user_credentials', 'auth_sessions', 'api_tokens')
                            """
                        ),
                        {"schema": schema},
                    ).scalars()
                )
                session_indexes = {
                    row["indexname"]
                    for row in conn.execute(
                        text(
                            """
                            select indexname
                            from pg_indexes
                            where schemaname = :schema
                              and tablename = 'auth_sessions'
                            """
                        ),
                        {"schema": schema},
                    ).mappings()
                }
        finally:
            engine.dispose()

    assert {"email", "role", "status", "avatar_url", "last_login_at"}.issubset(user_columns)
    assert auth_tables == {"user_credentials", "auth_sessions", "api_tokens"}
    assert "uq_auth_sessions_token_hash" in session_indexes


def test_formal_user_management_schema_is_owned_by_0004_only():
    migration_dir = Path(__file__).parents[1] / "migrations" / "versions"
    initial_schema = (migration_dir / "0001_initial_postgres_schema.py").read_text()
    formal_auth_schema = (migration_dir / "0004_formal_user_management.py").read_text()

    auth_tokens = {
        '"email"',
        '"avatar_url"',
        '"last_login_at"',
        "user_credentials",
        "auth_sessions",
        "api_tokens",
        "uq_users_email_lower",
        "idx_users_role_status",
    }

    assert not any(token in initial_schema for token in auth_tokens)
    assert all(token in formal_auth_schema for token in auth_tokens)


def test_formal_user_management_revision_supports_offline_sql_generation(capsys):
    cfg = alembic_config("postgresql+psycopg://user:password@localhost/literature_agent", "public")

    command.upgrade(cfg, "0003_worker_runtime_alignment:0004_formal_user_management", sql=True)
    command.downgrade(cfg, "0004_formal_user_management:0003_worker_runtime_alignment", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TABLE user_credentials" in sql
    assert "CREATE TABLE auth_sessions" in sql
    assert "DROP TABLE user_credentials" in sql


def test_formal_user_management_migrates_legacy_0003_user_to_head():
    from core.db.engine import engine_for_url

    url = test_database_url()
    schema = f"test_{uuid.uuid4().hex}"
    admin_engine = create_engine(url, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f'create schema "{schema}"'))

    previous_schema = os.environ.get("DB_SCHEMA")
    previous_database_url = os.environ.get("DATABASE_URL")
    previous_auth_mode = os.environ.get("AUTH_MODE")
    previous_app_env = os.environ.get("APP_ENV")
    try:
        os.environ["DB_SCHEMA"] = schema
        os.environ["DATABASE_URL"] = url
        os.environ["AUTH_MODE"] = "dev-header"
        os.environ["APP_ENV"] = "development"
        cfg = alembic_config(url, schema)

        command.upgrade(cfg, "0003_worker_runtime_alignment")
        user_id = uuid.uuid4()
        engine = engine_for_url(url, schema=schema)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("insert into users(user_id, display_name) values(:user_id, 'Legacy User')"),
                    {"user_id": user_id},
                )
        finally:
            engine.dispose()

        command.upgrade(cfg, "head")
        engine = engine_for_url(url, schema=schema)
        try:
            with engine.connect() as conn:
                auth_tables = set(
                    conn.execute(
                        text(
                            """
                            select table_name
                            from information_schema.tables
                            where table_schema = :schema
                              and table_name in ('user_credentials', 'auth_sessions', 'api_tokens')
                            """
                        ),
                        {"schema": schema},
                    ).scalars()
                )
                migrated_user = conn.execute(
                    text("select role, status from users where user_id = :user_id"),
                    {"user_id": user_id},
                ).mappings().one()
        finally:
            engine.dispose()
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

    assert auth_tables == {"user_credentials", "auth_sessions", "api_tokens"}
    assert migrated_user["role"] == "user"
    assert migrated_user["status"] == "active"
