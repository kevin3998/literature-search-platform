from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from core.db.config import database_schema, validate_postgres_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _url() -> str:
    configured = os.getenv("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    return validate_postgres_url(configured)


def _schema() -> str:
    configured = config.get_main_option("db_schema")
    if configured:
        os.environ["DB_SCHEMA"] = configured
    return database_schema()


def run_migrations_offline() -> None:
    schema = _schema()
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=schema,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.execute(f'create schema if not exists "{schema}"')
        context.execute(f'set search_path to "{schema}", public')
        context.run_migrations()


def run_migrations_online() -> None:
    schema = _schema()
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        connection.execute(text(f'create schema if not exists "{schema}"'))
        connection.execute(text(f'set search_path to "{schema}", public'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=schema,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
