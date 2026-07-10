"""Product schema compiler persistence.

Revision ID: 0005_schema_compiler
Revises: 0004_formal_user_management
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_schema_compiler"
down_revision = "0004_formal_user_management"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "structured_extraction_schema_compilations",
        sa.Column("compilation_id", UUID, primary_key=True),
        sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_format", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("schema_mode", sa.Text(), nullable=False, server_default="nested_record"),
        sa.Column("compiler_version", sa.Text(), nullable=False),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("requirements_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mappings_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("record_schema_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("field_tree_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("global_instructions_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("coverage_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation_errors_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warnings_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("normalization_changes_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model_attempts_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("field_tree_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_structured_schema_compilations_task",
        "structured_extraction_schema_compilations",
        ["task_id", "user_id", "created_at"],
    )
    for table_name in ("structured_extraction_schema_drafts", "structured_extraction_schema_versions"):
        op.add_column(table_name, sa.Column("source_compilation_id", UUID, nullable=True))
        op.add_column(table_name, sa.Column("source_compilation_modified", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        op.add_column(table_name, sa.Column("global_instructions_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
        op.create_foreign_key(
            f"fk_{table_name}_source_compilation",
            table_name,
            "structured_extraction_schema_compilations",
            ["source_compilation_id"],
            ["compilation_id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table_name in ("structured_extraction_schema_versions", "structured_extraction_schema_drafts"):
        op.drop_constraint(f"fk_{table_name}_source_compilation", table_name, type_="foreignkey")
        op.drop_column(table_name, "global_instructions_json")
        op.drop_column(table_name, "source_compilation_modified")
        op.drop_column(table_name, "source_compilation_id")
    op.drop_index("idx_structured_schema_compilations_task", table_name="structured_extraction_schema_compilations")
    op.drop_table("structured_extraction_schema_compilations")
