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


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("role", sa.Text(), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email is not null"),
    )
    op.create_index("idx_users_role_status", "users", ["role", "status"])

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
    op.create_index(
        "uq_user_credentials_active_password",
        "user_credentials",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("credential_type = 'password' and active = true"),
    )

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
    op.create_index("uq_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index(
        "idx_auth_sessions_user_active",
        "auth_sessions",
        ["user_id", "expires_at"],
        postgresql_where=sa.text("revoked_at is null"),
    )

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
    op.create_index("uq_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)
    op.create_index(
        "idx_api_tokens_user_active",
        "api_tokens",
        ["user_id", "created_at"],
        postgresql_where=sa.text("revoked_at is null"),
    )


def downgrade() -> None:
    op.drop_table("api_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("user_credentials")
    op.drop_index("idx_users_role_status", table_name="users")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "role")
    op.drop_column("users", "email")
