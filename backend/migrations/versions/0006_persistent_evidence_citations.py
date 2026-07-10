"""Persistent evidence citations.

Revision ID: 0006_persistent_citations
Revises: 0005_schema_compiler
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_persistent_citations"
down_revision = "0005_schema_compiler"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "evidence_records",
        sa.Column("evidence_record_id", UUID, primary_key=True),
        sa.Column("evidence_uid", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("paper_id", sa.Text(), nullable=True),
        sa.Column("paper_stable_id", sa.Text(), nullable=True),
        sa.Column("doi", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("section_id", sa.Text(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("index_version", sa.Integer(), nullable=True),
        sa.Column("source_locator_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("latest_metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_evidence_records_uid", "evidence_records", ["evidence_uid"], unique=True)

    op.create_table(
        "message_citations",
        sa.Column("message_citation_id", UUID, primary_key=True),
        sa.Column("message_id", UUID, sa.ForeignKey("messages.message_id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", UUID, sa.ForeignKey("turns.turn_id", ondelete="SET NULL"), nullable=True),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("citation_marker", sa.Text(), nullable=False),
        sa.Column("evidence_uid", sa.Text(), nullable=False),
        sa.Column("evidence_record_id", UUID, sa.ForeignKey("evidence_records.evidence_record_id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_locator_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("paper_snapshot_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("chunk_snapshot_text", sa.Text(), nullable=False),
        sa.Column("chunk_snapshot_hash", sa.Text(), nullable=False),
        sa.Column("display_snippet", sa.Text(), nullable=True),
        sa.Column("citation_context", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", "alias", name="uq_message_citations_message_alias"),
    )
    op.create_index("idx_message_citations_message", "message_citations", ["message_id"])
    op.create_index("idx_message_citations_session_created", "message_citations", ["session_id", "created_at"])
    op.create_index("idx_message_citations_turn", "message_citations", ["turn_id"])
    op.create_index("idx_message_citations_evidence_uid", "message_citations", ["evidence_uid"])


def downgrade() -> None:
    op.drop_index("idx_message_citations_evidence_uid", table_name="message_citations")
    op.drop_index("idx_message_citations_turn", table_name="message_citations")
    op.drop_index("idx_message_citations_session_created", table_name="message_citations")
    op.drop_index("idx_message_citations_message", table_name="message_citations")
    op.drop_table("message_citations")
    op.drop_index("uq_evidence_records_uid", table_name="evidence_records")
    op.drop_table("evidence_records")
