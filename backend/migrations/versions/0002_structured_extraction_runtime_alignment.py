"""Align structured extraction runtime schema.

Revision ID: 0002_m4_structured_runtime
Revises: 0001_initial_postgres_schema
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_m4_structured_runtime"
down_revision = "0001_initial_postgres_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "structured_extraction_schema_versions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        update structured_extraction_schema_versions sv
        set user_id = t.user_id
        from structured_extraction_tasks t
        where sv.task_id = t.task_id
          and sv.user_id is null
        """
    )
    op.alter_column("structured_extraction_schema_versions", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_structured_schema_versions_user_id",
        "structured_extraction_schema_versions",
        "users",
        ["user_id"],
        ["user_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "idx_structured_schema_versions_task_user_version",
        "structured_extraction_schema_versions",
        ["task_id", "user_id", "schema_version"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_structured_schema_versions_task_user_version",
        table_name="structured_extraction_schema_versions",
    )
    op.drop_constraint(
        "fk_structured_schema_versions_user_id",
        "structured_extraction_schema_versions",
        type_="foreignkey",
    )
    op.drop_column("structured_extraction_schema_versions", "user_id")
