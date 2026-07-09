"""Formal user management schema.

Revision ID: 0004_formal_user_management
Revises: 0003_worker_runtime_alignment
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_formal_user_management"
down_revision = "0003_worker_runtime_alignment"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def _schema() -> str:
    return op.get_bind().execute(sa.text("select current_schema()")).scalar_one()


def _column_exists(table_name: str, column_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                select 1
                from information_schema.columns
                where table_schema = :schema
                  and table_name = :table_name
                  and column_name = :column_name
                """
            ),
            {"schema": _schema(), "table_name": table_name, "column_name": column_name},
        )
        .first()
    )


def _table_exists(table_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                select 1
                from information_schema.tables
                where table_schema = :schema
                  and table_name = :table_name
                """
            ),
            {"schema": _schema(), "table_name": table_name},
        )
        .first()
    )


def _index_exists(index_name: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            sa.text(
                """
                select 1
                from pg_indexes
                where schemaname = :schema
                  and indexname = :index_name
                """
            ),
            {"schema": _schema(), "index_name": index_name},
        )
        .first()
    )


def upgrade() -> None:
    if not _column_exists("users", "email"):
        op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    if not _column_exists("users", "role"):
        op.add_column("users", sa.Column("role", sa.Text(), nullable=False, server_default="user"))
    if not _column_exists("users", "avatar_url"):
        op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    if not _column_exists("users", "last_login_at"):
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    if not _index_exists("uq_users_email_lower"):
        op.create_index(
            "uq_users_email_lower",
            "users",
            [sa.text("lower(email)")],
            unique=True,
            postgresql_where=sa.text("email is not null"),
        )
    if not _index_exists("idx_users_role_status"):
        op.create_index("idx_users_role_status", "users", ["role", "status"])

    if not _table_exists("user_credentials"):
        op.create_table(
            "user_credentials",
            sa.Column("credential_id", UUID, primary_key=True),
            sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
            sa.Column("credential_type", sa.Text(), nullable=False, server_default="password"),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("password_algorithm", sa.Text(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
    if not _index_exists("uq_user_credentials_active_password"):
        op.create_index(
            "uq_user_credentials_active_password",
            "user_credentials",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("credential_type = 'password' and active = true"),
        )

    if not _table_exists("auth_sessions"):
        op.create_table(
            "auth_sessions",
            sa.Column("session_id", UUID, primary_key=True),
            sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column("csrf_token_hash", sa.Text(), nullable=False),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("ip_hash", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.Text(), nullable=True),
        )
    if not _index_exists("uq_auth_sessions_token_hash"):
        op.create_index("uq_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    if not _index_exists("idx_auth_sessions_user_active"):
        op.create_index(
            "idx_auth_sessions_user_active",
            "auth_sessions",
            ["user_id", "expires_at"],
            postgresql_where=sa.text("revoked_at is null"),
        )

    if not _table_exists("api_tokens"):
        op.create_table(
            "api_tokens",
            sa.Column("token_id", UUID, primary_key=True),
            sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column("token_preview", sa.Text(), nullable=False),
            sa.Column("scopes_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _index_exists("uq_api_tokens_token_hash"):
        op.create_index("uq_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)
    if not _index_exists("idx_api_tokens_user_active"):
        op.create_index(
            "idx_api_tokens_user_active",
            "api_tokens",
            ["user_id", "created_at"],
            postgresql_where=sa.text("revoked_at is null"),
        )


def downgrade() -> None:
    op.drop_table("api_tokens", if_exists=True)
    op.drop_table("auth_sessions", if_exists=True)
    op.drop_table("user_credentials", if_exists=True)
    op.drop_index("idx_users_role_status", table_name="users", if_exists=True)
    op.drop_index("uq_users_email_lower", table_name="users", if_exists=True)
    if _column_exists("users", "last_login_at"):
        op.drop_column("users", "last_login_at")
    if _column_exists("users", "avatar_url"):
        op.drop_column("users", "avatar_url")
    if _column_exists("users", "role"):
        op.drop_column("users", "role")
    if _column_exists("users", "email"):
        op.drop_column("users", "email")
