"""Initial PostgreSQL platform schema.

Revision ID: 0001_initial_postgres_schema
Revises:
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_postgres_schema"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def _ts(name: str, *, nullable: bool = False, default_now: bool = True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=sa.text("now()") if default_now else None)


def _json_obj(name: str, *, nullable: bool = False):
    return sa.Column(name, JSONB, nullable=nullable, server_default=sa.text("'{}'::jsonb"))


def _json_arr(name: str, *, nullable: bool = False):
    return sa.Column(name, JSONB, nullable=nullable, server_default=sa.text("'[]'::jsonb"))


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", UUID, primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        _json_obj("metadata_json"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "user_identities",
        sa.Column("identity_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        _json_obj("metadata_json"),
        _ts("created_at"),
        _ts("last_seen_at"),
        sa.UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
    )
    op.create_index("idx_user_identities_user", "user_identities", ["user_id"])
    op.create_table(
        "audit_events",
        sa.Column("event_id", UUID, primary_key=True),
        sa.Column("actor_user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False, server_default="ok"),
        _json_obj("metadata_json"),
        _ts("created_at"),
    )
    op.create_index("idx_audit_events_actor_created", "audit_events", ["actor_user_id", "created_at"])

    op.create_table(
        "settings",
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value_json", JSONB, nullable=False),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("user_id", "scope", "key", name="pk_settings"),
    )
    op.create_table(
        "user_secrets",
        sa.Column("secret_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("secret_type", sa.Text(), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column("masked_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("encryption_version", sa.Text(), nullable=False, server_default="fernet-v1"),
        sa.Column("key_id", sa.Text(), nullable=False, server_default="default"),
        _json_obj("metadata_json"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("idx_user_secrets_user_type", "user_secrets", ["user_id", "secret_type"])
    op.create_table(
        "model_profiles",
        sa.Column("profile_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("secret_id", UUID, sa.ForeignKey("user_secrets.secret_id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("model", sa.Text(), nullable=False, server_default=""),
        _json_obj("config_json"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("user_id", "name", name="uq_model_profiles_user_name"),
    )
    op.create_index("uq_model_profiles_one_active_per_user", "model_profiles", ["user_id"], unique=True, postgresql_where=sa.text("active = true"))

    op.create_table(
        "sessions",
        sa.Column("session_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default="新对话"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        _json_arr("tags_json"),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _json_obj("metadata_json"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_sessions_user_updated", "sessions", ["user_id", "updated_at"])
    op.create_index("idx_sessions_user_module_updated", "sessions", ["user_id", "module_id", "updated_at"])

    op.create_table("messages", sa.Column("message_id", UUID, primary_key=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("turn_id", UUID, nullable=True), sa.Column("role", sa.Text(), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("error", sa.Boolean(), nullable=False, server_default=sa.text("false")), _ts("created_at"), _json_obj("metadata_json"))
    op.create_index("idx_messages_session_created", "messages", ["session_id", "created_at"])
    op.create_table("turns", sa.Column("turn_id", UUID, primary_key=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("user_message_id", UUID, nullable=True), sa.Column("assistant_message_id", UUID, nullable=True), sa.Column("query", sa.Text(), nullable=True), sa.Column("answer_mode", sa.Text(), nullable=True), sa.Column("role", sa.Text(), nullable=True), sa.Column("status", sa.Text(), nullable=False, server_default="running"), sa.Column("search_result_id", UUID, nullable=True), sa.Column("job_id", UUID, nullable=True), _ts("created_at"), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_turns_session_created", "turns", ["session_id", "created_at"])
    op.create_table("search_results", sa.Column("search_result_id", UUID, primary_key=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("turn_id", UUID, nullable=True), sa.Column("query", sa.Text(), nullable=False), _json_obj("query_plan_json"), _json_obj("filters_json"), _json_arr("results_json"), _json_obj("coverage_json"), sa.Column("fallback_json", JSONB, nullable=True), _json_obj("breadth_json"), _ts("created_at"))
    op.create_index("idx_search_session_created", "search_results", ["session_id", "created_at"])
    op.create_table("evidence_items", sa.Column("evidence_item_id", UUID, primary_key=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("turn_id", UUID, nullable=True), sa.Column("search_result_id", UUID, nullable=True), sa.Column("evidence_id", sa.Text(), nullable=True), sa.Column("article_id", sa.Integer(), nullable=True), sa.Column("paper_id", sa.Text(), nullable=True), sa.Column("doi", sa.Text(), nullable=True), sa.Column("title", sa.Text(), nullable=True), sa.Column("kind", sa.Text(), nullable=True), sa.Column("confidence", sa.Text(), nullable=True), sa.Column("source_path", sa.Text(), nullable=True), sa.Column("section_id", sa.Text(), nullable=True), sa.Column("chunk_index", sa.Integer(), nullable=True), sa.Column("index_version", sa.Integer(), nullable=True), sa.Column("snippet", sa.Text(), nullable=True), _json_obj("payload_json"), _ts("created_at"))
    op.create_index("idx_evidence_session_created", "evidence_items", ["session_id", "created_at"])
    op.create_table("research_state", sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), primary_key=True), sa.Column("topic", sa.Text(), nullable=True), sa.Column("objective", sa.Text(), nullable=True), sa.Column("stage", sa.Text(), nullable=False, server_default="retrieval"), _json_arr("excluded_directions_json"), _json_arr("open_questions_json"), _json_arr("completed_questions_json"), _json_arr("next_actions_json"), _ts("updated_at"))
    op.create_table("paper_states", sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("paper_id", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="candidate"), sa.Column("note", sa.Text(), nullable=True), sa.Column("source", sa.Text(), nullable=True), sa.Column("turn_id", UUID, nullable=True), _ts("created_at"), _ts("updated_at"), sa.PrimaryKeyConstraint("session_id", "paper_id", name="pk_paper_states"))
    op.create_index("idx_paper_states_session", "paper_states", ["session_id", "status"])
    op.create_table("evidence_states", sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("evidence_item_id", UUID, sa.ForeignKey("evidence_items.evidence_item_id", ondelete="CASCADE"), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="candidate"), sa.Column("note", sa.Text(), nullable=True), sa.Column("source", sa.Text(), nullable=True), sa.Column("turn_id", UUID, nullable=True), _ts("created_at"), _ts("updated_at"), sa.PrimaryKeyConstraint("session_id", "evidence_item_id", name="pk_evidence_states"))
    op.create_index("idx_evidence_states_session", "evidence_states", ["session_id", "status"])
    op.create_table("research_state_events", sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("turn_id", UUID, nullable=True), sa.Column("source", sa.Text(), nullable=True), sa.Column("field", sa.Text(), nullable=False), sa.Column("operation", sa.Text(), nullable=False), _json_obj("value_json"), _ts("created_at"))
    op.create_index("idx_state_events_session", "research_state_events", ["session_id", "created_at"])
    op.create_table("session_attachments", sa.Column("attachment_id", UUID, primary_key=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("filename", sa.Text(), nullable=False), sa.Column("content_type", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False), sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""), sa.Column("text_preview", sa.Text(), nullable=False, server_default=""), sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("error", sa.Text(), nullable=True), _ts("created_at"), sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_session_attachments_session", "session_attachments", ["session_id", "user_id", "deleted_at", "created_at"])
    op.create_table("session_annotations", sa.Column("annotation_id", UUID, primary_key=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("target_type", sa.Text(), nullable=True), sa.Column("target_id", sa.Text(), nullable=True), sa.Column("kind", sa.Text(), nullable=False), sa.Column("content", sa.Text(), nullable=True), _ts("created_at"))
    op.create_table("tool_traces", sa.Column("tool_call_id", UUID, primary_key=True), sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("turn_id", UUID, nullable=True), sa.Column("tool_name", sa.Text(), nullable=False), sa.Column("schema_version", sa.Text(), nullable=True), sa.Column("permission_level", sa.Text(), nullable=True), sa.Column("agent_mode", sa.Text(), nullable=True), _json_obj("arguments_json"), sa.Column("status", sa.Text(), nullable=False), sa.Column("error_code", sa.Text(), nullable=True), sa.Column("error_message", sa.Text(), nullable=True), sa.Column("recovery_hint", sa.Text(), nullable=True), sa.Column("result_summary", sa.Text(), nullable=True), sa.Column("latency_ms", sa.Integer(), nullable=True), _json_arr("artifacts_json"), _json_arr("jobs_json"), sa.Column("state_changed", sa.Boolean(), nullable=False, server_default=sa.text("false")), _ts("started_at"), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_tool_traces_turn", "tool_traces", ["turn_id", "started_at"])

    op.create_table("artifacts", sa.Column("artifact_id", UUID, primary_key=True), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("artifact_type", sa.Text(), nullable=False), sa.Column("title", sa.Text(), nullable=False), sa.Column("json_path", sa.Text(), nullable=True), sa.Column("markdown_path", sa.Text(), nullable=True), _json_obj("summary_json"), _ts("created_at", nullable=True, default_now=False), _ts("updated_at"))
    op.create_index("idx_artifacts_user_updated", "artifacts", ["user_id", "updated_at"])
    op.create_table("conversation_artifact_links", sa.Column("session_id", UUID, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("turn_id", UUID, nullable=True), sa.Column("artifact_id", UUID, sa.ForeignKey("artifacts.artifact_id", ondelete="CASCADE"), nullable=False), sa.Column("link_type", sa.Text(), nullable=False), _ts("created_at"), sa.PrimaryKeyConstraint("session_id", "turn_id", "artifact_id", "link_type", name="pk_conversation_artifact_links"))

    op.create_table("jobs", sa.Column("job_id", UUID, primary_key=True), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True), sa.Column("session_id", UUID, nullable=True), sa.Column("turn_id", UUID, nullable=True), sa.Column("queue", sa.Text(), nullable=False, server_default="default"), sa.Column("job_type", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False), _json_obj("payload_json"), sa.Column("result_json", JSONB, nullable=True), sa.Column("error", sa.Text(), nullable=True), sa.Column("priority", sa.Integer(), nullable=False, server_default="0"), sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"), sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("now()")), sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("locked_by", sa.Text(), nullable=True), sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True), _ts("created_at"), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), _ts("updated_at"))
    op.create_index("idx_jobs_session_updated", "jobs", ["session_id", "updated_at"])
    op.create_index("idx_jobs_user_updated", "jobs", ["user_id", "updated_at"])
    op.create_index("idx_jobs_queue_claim", "jobs", ["status", "next_run_at", "priority", "created_at"])
    op.create_table("job_events", sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("job_id", UUID, sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False), sa.Column("event_index", sa.Integer(), nullable=False), sa.Column("event_type", sa.Text(), nullable=False), sa.Column("event_json", JSONB, nullable=False), _ts("created_at"), sa.UniqueConstraint("job_id", "event_index", name="uq_job_events_job_index"))
    op.create_index("idx_job_events_job_index", "job_events", ["job_id", "event_index"])
    op.create_table("worker_heartbeats", sa.Column("worker_id", sa.Text(), primary_key=True), _json_obj("metadata_json"), _ts("started_at"), _ts("last_seen_at"), sa.Column("status", sa.Text(), nullable=False, server_default="online"))

    op.create_table("workflow_runs", sa.Column("workflow_id", UUID, primary_key=True), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("template_id", sa.Text(), nullable=False), sa.Column("title", sa.Text(), nullable=False, server_default="研究工作流"), sa.Column("topic", sa.Text(), nullable=True), sa.Column("scope", sa.Text(), nullable=False, server_default="library"), sa.Column("status", sa.Text(), nullable=False, server_default="draft"), _json_obj("manifest_json"), _json_obj("engine_ref_json"), sa.Column("session_id", UUID, nullable=True), sa.Column("error", sa.Text(), nullable=True), sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), _ts("created_at"), _ts("updated_at"), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_workflow_runs_user_updated", "workflow_runs", ["user_id", "updated_at"])
    op.create_table("workflow_steps", sa.Column("workflow_id", UUID, sa.ForeignKey("workflow_runs.workflow_id", ondelete="CASCADE"), nullable=False), sa.Column("step_index", sa.Integer(), nullable=False), sa.Column("step_key", sa.Text(), nullable=False), sa.Column("runner", sa.Text(), nullable=False), sa.Column("label", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="pending"), sa.Column("job_id", UUID, nullable=True), _json_arr("artifact_ids_json"), sa.Column("error", sa.Text(), nullable=True), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True), sa.PrimaryKeyConstraint("workflow_id", "step_index", name="pk_workflow_steps"))
    op.create_index("idx_workflow_steps_wf", "workflow_steps", ["workflow_id", "step_index"])

    _create_structured_extraction_tables()


def _create_structured_extraction_tables() -> None:
    op.create_table("structured_extraction_tasks", sa.Column("task_id", UUID, primary_key=True), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("name", sa.Text(), nullable=False), sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("status", sa.Text(), nullable=False, server_default="draft"), sa.Column("workspace_rel_path", sa.Text(), nullable=False), sa.Column("current_collection_version", sa.Text(), nullable=True), sa.Column("current_schema_version", sa.Text(), nullable=True), _json_obj("model_settings_json"), _json_obj("stats_json"), sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), _ts("created_at"), _ts("updated_at"), sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_structured_extraction_tasks_user_updated", "structured_extraction_tasks", ["user_id", "archived", "updated_at"])
    op.create_table("structured_extraction_task_events", sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("event_type", sa.Text(), nullable=False), _json_obj("payload_json"), _ts("created_at"))
    op.create_index("idx_structured_extraction_task_events_task", "structured_extraction_task_events", ["task_id", "created_at"])
    op.create_table("structured_extraction_candidates", sa.Column("candidate_id", UUID, primary_key=True), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("paper_id", sa.Text(), nullable=False), sa.Column("title", sa.Text(), nullable=True), _json_arr("authors_json"), sa.Column("year", sa.Integer(), nullable=True), sa.Column("journal", sa.Text(), nullable=True), sa.Column("doi", sa.Text(), nullable=True), sa.Column("source_path", sa.Text(), nullable=True), sa.Column("index_version", sa.Integer(), nullable=True), sa.Column("candidate_source", sa.Text(), nullable=False), sa.Column("source_query", sa.Text(), nullable=False, server_default=""), sa.Column("source_query_hash", sa.Text(), nullable=False), _json_arr("matched_fields_json"), sa.Column("metadata_score", sa.Float(), nullable=False, server_default="0"), sa.Column("llm_decision", sa.Text(), nullable=True), sa.Column("llm_relevance_score", sa.Float(), nullable=True), sa.Column("llm_reason", sa.Text(), nullable=True), sa.Column("user_decision", sa.Text(), nullable=False, server_default="candidate"), sa.Column("exclude_reason", sa.Text(), nullable=True), sa.Column("duplicate_group_id", sa.Text(), nullable=True), sa.Column("canonical_paper_id", sa.Text(), nullable=True), sa.Column("duplicate_reason", sa.Text(), nullable=True), _json_obj("paper_ref_json"), _ts("created_at"), _ts("updated_at"), sa.UniqueConstraint("task_id", "paper_id", "candidate_source", "source_query_hash", name="uq_structured_candidates_source"))
    op.create_index("idx_structured_extraction_candidates_task_decision", "structured_extraction_candidates", ["task_id", "user_decision", "updated_at"])
    op.create_index("idx_structured_extraction_candidates_task_source", "structured_extraction_candidates", ["task_id", "candidate_source", "updated_at"])
    op.create_table("structured_extraction_candidate_events", sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("candidate_id", UUID, sa.ForeignKey("structured_extraction_candidates.candidate_id", ondelete="CASCADE"), nullable=False), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("event_type", sa.Text(), nullable=False), _json_obj("payload_json"), _ts("created_at"))
    op.create_table("structured_extraction_collection_versions", sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("collection_version", sa.Text(), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("paper_count", sa.Integer(), nullable=False, server_default="0"), _json_obj("summary_json"), _ts("created_at"), sa.PrimaryKeyConstraint("task_id", "collection_version", name="pk_structured_collection_versions"))
    op.create_table("structured_extraction_collection_papers", sa.Column("task_id", UUID, nullable=False), sa.Column("collection_version", sa.Text(), nullable=False), sa.Column("candidate_id", UUID, nullable=False), sa.Column("paper_id", sa.Text(), nullable=False), _json_obj("paper_ref_json"), _json_obj("decision_payload_json"), _ts("created_at"), sa.PrimaryKeyConstraint("task_id", "collection_version", "candidate_id", name="pk_structured_collection_papers"), sa.ForeignKeyConstraint(["task_id", "collection_version"], ["structured_extraction_collection_versions.task_id", "structured_extraction_collection_versions.collection_version"], ondelete="CASCADE"))
    for table_name, pk_cols in [
        ("structured_extraction_schema_drafts", ["task_id"]),
        ("structured_extraction_schema_versions", ["task_id", "schema_version"]),
        ("structured_extraction_prompt_contracts", ["task_id", "prompt_contract_version"]),
        ("structured_extraction_evidence_packet_versions", ["task_id", "packet_version"]),
    ]:
        _create_version_like_table(table_name, pk_cols)
    op.create_table("structured_extraction_schema_events", sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("schema_version", sa.Text(), nullable=True), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("event_type", sa.Text(), nullable=False), _json_obj("payload_json"), _ts("created_at"))
    op.create_table("structured_extraction_evidence_packet_items", sa.Column("packet_item_id", UUID, primary_key=True), sa.Column("task_id", UUID, nullable=False), sa.Column("packet_version", sa.Text(), nullable=False), sa.Column("paper_id", sa.Text(), nullable=False), sa.Column("field_group", sa.Text(), nullable=False), _json_arr("field_keys_json"), sa.Column("construction_query", sa.Text(), nullable=False, server_default=""), _json_arr("retrieved_sections_json"), _json_arr("chunks_json"), _json_arr("tables_json"), _json_arr("figures_json"), _json_arr("source_paths_json"), _json_arr("warnings_json"), _ts("created_at"), sa.ForeignKeyConstraint(["task_id", "packet_version"], ["structured_extraction_evidence_packet_versions.task_id", "structured_extraction_evidence_packet_versions.packet_version"], ondelete="CASCADE"))
    op.create_index("idx_structured_extraction_packet_items_version", "structured_extraction_evidence_packet_items", ["task_id", "packet_version", "paper_id"])
    op.create_table("structured_extraction_evidence_packet_build_jobs", sa.Column("build_job_id", UUID, primary_key=True), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="queued"), sa.Column("phase", sa.Text(), nullable=False, server_default="resolving_inputs"), sa.Column("collection_version", sa.Text(), nullable=False), sa.Column("schema_version", sa.Text(), nullable=False), sa.Column("prompt_contract_version", sa.Text(), nullable=False), sa.Column("target_packet_version", sa.Text(), nullable=False), sa.Column("result_packet_version", sa.Text(), nullable=True), sa.Column("paper_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("field_group_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("total_item_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("processed_item_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("current_paper_id", sa.Text(), nullable=True), sa.Column("current_field_group", sa.Text(), nullable=True), sa.Column("current_query_mode", sa.Text(), nullable=True), sa.Column("total_chunk_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("slow_item_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_item_seconds", sa.Float(), nullable=True), _json_obj("settings_json"), _json_arr("warnings_preview_json"), sa.Column("error_json", JSONB, nullable=True), _ts("created_at"), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), _ts("updated_at"), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("structured_extraction_evidence_packet_build_items", sa.Column("build_job_id", UUID, sa.ForeignKey("structured_extraction_evidence_packet_build_jobs.build_job_id", ondelete="CASCADE"), nullable=False), sa.Column("item_index", sa.Integer(), nullable=False), sa.Column("packet_item_json", JSONB, nullable=False), _json_arr("warnings_json"), _ts("created_at"), sa.PrimaryKeyConstraint("build_job_id", "item_index", name="pk_structured_ep_build_items"))
    op.create_table("structured_extraction_runs", sa.Column("run_id", UUID, primary_key=True), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="queued"), sa.Column("collection_version", sa.Text(), nullable=False), sa.Column("schema_version", sa.Text(), nullable=False), sa.Column("prompt_contract_version", sa.Text(), nullable=False), sa.Column("packet_version", sa.Text(), nullable=False), _json_obj("model_snapshot_json"), _json_obj("stats_json"), sa.Column("error_json", JSONB, nullable=True), sa.Column("previous_task_status", sa.Text(), nullable=True), _ts("created_at"), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("resume_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True), sa.Column("interrupted_at", sa.DateTime(timezone=True), nullable=True), sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True), _json_obj("recovery_json"))
    op.create_index("idx_structured_extraction_runs_task", "structured_extraction_runs", ["task_id", "created_at"])
    _create_structured_extraction_children()


def _create_version_like_table(table_name: str, pk_cols: list[str]) -> None:
    cols = [sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False)]
    if "schema_version" in pk_cols:
        cols.extend([sa.Column("schema_version", sa.Text(), nullable=False), sa.Column("base_collection_version", sa.Text(), nullable=False), sa.Column("schema_mode", sa.Text(), nullable=False, server_default="flat_fields"), _json_obj("record_schema_json"), _json_arr("field_groups_json"), _json_arr("field_tree_json"), _json_arr("fields_json"), sa.Column("field_count", sa.Integer(), nullable=False, server_default="0"), _json_obj("change_summary_json"), _ts("created_at"), _ts("frozen_at")])
    elif "prompt_contract_version" in pk_cols:
        cols.extend([sa.Column("prompt_contract_version", sa.Text(), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("collection_version", sa.Text(), nullable=False), sa.Column("schema_version", sa.Text(), nullable=False), _json_obj("contract_json"), sa.Column("field_count", sa.Integer(), nullable=False, server_default="0"), _ts("created_at")])
    elif "packet_version" in pk_cols:
        cols.extend([sa.Column("packet_version", sa.Text(), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("collection_version", sa.Text(), nullable=False), sa.Column("schema_version", sa.Text(), nullable=False), sa.Column("prompt_contract_version", sa.Text(), nullable=False), sa.Column("paper_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("field_group_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"), _json_obj("settings_json"), _json_arr("warnings_json"), _ts("created_at")])
    else:
        cols.extend([sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("base_collection_version", sa.Text(), nullable=False), sa.Column("schema_mode", sa.Text(), nullable=False, server_default="flat_fields"), _json_obj("record_schema_json"), _json_arr("field_groups_json"), _json_arr("field_tree_json"), _json_arr("fields_json"), _json_arr("validation_errors_json"), _ts("created_at"), _ts("updated_at")])
    cols.append(sa.PrimaryKeyConstraint(*pk_cols, name=f"pk_{table_name}"))
    op.create_table(table_name, *cols)
    op.create_index(f"idx_{table_name}_task", table_name, ["task_id"])


def _create_structured_extraction_children() -> None:
    op.create_table("structured_extraction_run_items", sa.Column("run_item_id", UUID, primary_key=True), sa.Column("run_id", UUID, sa.ForeignKey("structured_extraction_runs.run_id", ondelete="CASCADE"), nullable=False), sa.Column("task_id", UUID, nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("packet_item_id", UUID, nullable=False), sa.Column("paper_id", sa.Text(), nullable=False), sa.Column("field_group", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="queued"), _json_obj("prompt_json"), sa.Column("raw_output", sa.Text(), nullable=True), sa.Column("parsed_json", JSONB, nullable=True), sa.Column("error_json", JSONB, nullable=True), _ts("created_at"), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_structured_extraction_run_items_run", "structured_extraction_run_items", ["run_id", "status", "paper_id"])
    op.create_table("structured_extraction_records", sa.Column("record_id", UUID, primary_key=True), sa.Column("run_id", UUID, sa.ForeignKey("structured_extraction_runs.run_id", ondelete="CASCADE"), nullable=False), sa.Column("task_id", UUID, nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("paper_id", sa.Text(), nullable=False), sa.Column("record_type", sa.Text(), nullable=True), sa.Column("record_index", sa.Integer(), nullable=False, server_default="1"), _json_obj("record_identity_json"), _json_obj("data_json"), _json_obj("fields_json"), _json_arr("source_packet_item_ids_json"), _json_arr("quality_flags_json"), _json_obj("record_json"), _ts("created_at"))
    op.create_table("structured_extraction_run_events", sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("run_id", UUID, sa.ForeignKey("structured_extraction_runs.run_id", ondelete="CASCADE"), nullable=False), sa.Column("task_id", UUID, nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("event_type", sa.Text(), nullable=False), _json_obj("payload_json"), _ts("created_at"))
    op.create_table("structured_extraction_review_events", sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("run_id", UUID, nullable=False), sa.Column("record_id", UUID, nullable=False), sa.Column("field_key", sa.Text(), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("event_type", sa.Text(), nullable=False), sa.Column("old_value_json", JSONB, nullable=True), sa.Column("new_value_json", JSONB, nullable=True), sa.Column("reason", sa.Text(), nullable=False, server_default=""), sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("target_event_id", sa.BigInteger(), nullable=True), _json_obj("payload_json"), _ts("created_at"))
    op.create_table("structured_extraction_review_field_states", sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("run_id", UUID, nullable=False), sa.Column("record_id", UUID, nullable=False), sa.Column("field_key", sa.Text(), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("base_value_json", JSONB, nullable=True), sa.Column("effective_value_json", JSONB, nullable=True), sa.Column("status", sa.Text(), nullable=False, server_default="unreviewed"), sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")), _json_arr("quality_flags_json"), sa.Column("review_priority", sa.Text(), nullable=False, server_default="low"), _json_obj("provenance_json"), sa.Column("last_event_id", sa.BigInteger(), nullable=True), _ts("updated_at"), sa.PrimaryKeyConstraint("task_id", "run_id", "record_id", "field_key", name="pk_structured_review_field_states"))
    op.create_table("structured_extraction_multimodal_review_jobs", sa.Column("job_id", UUID, primary_key=True), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("run_id", UUID, nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="queued"), sa.Column("scan_mode", sa.Text(), nullable=False, server_default="related_pages_assets"), sa.Column("reason", sa.Text(), nullable=False, server_default=""), _json_obj("model_snapshot_json"), sa.Column("total_item_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("processed_item_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("suggestion_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("issue_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("current_paper_id", sa.Text(), nullable=True), sa.Column("current_record_id", UUID, nullable=True), sa.Column("current_section", sa.Text(), nullable=True), _json_arr("warnings_json"), sa.Column("error_json", JSONB, nullable=True), _ts("created_at"), sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), _ts("updated_at"), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("structured_extraction_multimodal_review_suggestions", sa.Column("suggestion_id", UUID, primary_key=True), sa.Column("job_id", UUID, sa.ForeignKey("structured_extraction_multimodal_review_jobs.job_id", ondelete="CASCADE"), nullable=False), sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("run_id", UUID, nullable=False), sa.Column("record_id", UUID, nullable=False), sa.Column("field_key", sa.Text(), nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("action", sa.Text(), nullable=False), sa.Column("status", sa.Text(), nullable=False, server_default="pending"), sa.Column("risk_level", sa.Text(), nullable=False, server_default="medium"), sa.Column("coverage_status", sa.Text(), nullable=True), sa.Column("issue_type", sa.Text(), nullable=True), sa.Column("suggested_value_json", JSONB, nullable=True), sa.Column("current_value_json", JSONB, nullable=True), _json_obj("evidence_json"), _json_obj("provenance_json"), sa.Column("reason", sa.Text(), nullable=False, server_default=""), _ts("created_at"), sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("structured_extraction_exports", sa.Column("task_id", UUID, sa.ForeignKey("structured_extraction_tasks.task_id", ondelete="CASCADE"), nullable=False), sa.Column("export_id", UUID, nullable=False), sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False), sa.Column("run_id", UUID, nullable=False), sa.Column("collection_version", sa.Text(), nullable=False), sa.Column("schema_version", sa.Text(), nullable=False), _json_arr("formats_json"), _json_obj("files_json"), _json_obj("settings_json"), _json_obj("summary_json"), sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("field_count", sa.Integer(), nullable=False, server_default="0"), _ts("created_at"), sa.PrimaryKeyConstraint("task_id", "export_id", name="pk_structured_exports"))


def downgrade() -> None:
    for table in [
        "structured_extraction_exports", "structured_extraction_multimodal_review_suggestions", "structured_extraction_multimodal_review_jobs", "structured_extraction_review_field_states", "structured_extraction_review_events", "structured_extraction_run_events", "structured_extraction_records", "structured_extraction_run_items", "structured_extraction_runs", "structured_extraction_evidence_packet_build_items", "structured_extraction_evidence_packet_build_jobs", "structured_extraction_evidence_packet_items", "structured_extraction_evidence_packet_versions", "structured_extraction_prompt_contracts", "structured_extraction_schema_events", "structured_extraction_schema_versions", "structured_extraction_schema_drafts", "structured_extraction_collection_papers", "structured_extraction_collection_versions", "structured_extraction_candidate_events", "structured_extraction_candidates", "structured_extraction_task_events", "structured_extraction_tasks", "workflow_steps", "workflow_runs", "worker_heartbeats", "job_events", "jobs", "conversation_artifact_links", "artifacts", "tool_traces", "session_annotations", "session_attachments", "research_state_events", "evidence_states", "paper_states", "research_state", "evidence_items", "search_results", "turns", "messages", "sessions", "model_profiles", "user_secrets", "settings", "audit_events", "user_identities", "users",
    ]:
        op.drop_table(table)
