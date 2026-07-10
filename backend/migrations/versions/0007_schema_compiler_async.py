"""Add durable worker execution state to schema compilations.

Revision ID: 0007_schema_compiler_async
Revises: 0006_persistent_citations
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_schema_compiler_async"
down_revision = "0006_persistent_citations"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    table = "structured_extraction_schema_compilations"
    op.add_column(table, sa.Column("execution_status", sa.Text(), nullable=False, server_default="completed"))
    op.add_column(table, sa.Column("phase", sa.Text(), nullable=False, server_default="completed"))
    op.add_column(table, sa.Column("progress", sa.Integer(), nullable=False, server_default="100"))
    op.add_column(table, sa.Column("core_job_id", UUID, nullable=True))
    op.add_column(table, sa.Column("request_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column(table, sa.Column("error_json", JSONB, nullable=True))
    op.add_column(table, sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(table, sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_structured_schema_compilations_core_job",
        table,
        "jobs",
        ["core_job_id"],
        ["job_id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_structured_schema_compilations_active",
        table,
        ["task_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("execution_status in ('queued', 'running')"),
    )


def downgrade() -> None:
    table = "structured_extraction_schema_compilations"
    op.drop_index("uq_structured_schema_compilations_active", table_name=table)
    op.drop_constraint("fk_structured_schema_compilations_core_job", table, type_="foreignkey")
    op.drop_column(table, "completed_at")
    op.drop_column(table, "started_at")
    op.drop_column(table, "error_json")
    op.drop_column(table, "request_json")
    op.drop_column(table, "core_job_id")
    op.drop_column(table, "progress")
    op.drop_column(table, "phase")
    op.drop_column(table, "execution_status")
