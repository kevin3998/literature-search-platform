"""Align async structured extraction jobs with core worker jobs.

Revision ID: 0003_worker_runtime_alignment
Revises: 0002_m4_structured_runtime
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_worker_runtime_alignment"
down_revision = "0002_m4_structured_runtime"
branch_labels = None
depends_on = None

_TABLES = {
    "structured_extraction_evidence_packet_build_jobs": "se_ep_build_jobs",
    "structured_extraction_runs": "se_runs",
    "structured_extraction_multimodal_review_jobs": "se_mm_review_jobs",
}


def upgrade() -> None:
    for table, short_name in _TABLES.items():
        op.add_column(table, sa.Column("core_job_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"fk_{short_name}_core_job",
            table,
            "jobs",
            ["core_job_id"],
            ["job_id"],
            ondelete="SET NULL",
        )
        op.create_index(f"idx_{short_name}_core_job", table, ["core_job_id"])


def downgrade() -> None:
    for table, short_name in reversed(_TABLES.items()):
        op.drop_index(f"idx_{short_name}_core_job", table_name=table)
        op.drop_constraint(f"fk_{short_name}_core_job", table, type_="foreignkey")
        op.drop_column(table, "core_job_id")
