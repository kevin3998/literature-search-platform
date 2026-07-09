from __future__ import annotations

import uuid

from sqlalchemy import inspect, text

from postgres_test_utils import migrated_postgres_schema


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
