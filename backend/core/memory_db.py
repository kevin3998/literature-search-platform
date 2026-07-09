from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_DB = "/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/platform_memory.sqlite"
SCHEMA_VERSION = 1
_SCHEMA_INIT_LOCK = threading.RLock()


def memory_db_path(db_path: str | Path | None = None) -> Path:
    configured = db_path or os.getenv("LITERATURE_MEMORY_DB_PATH") or DEFAULT_MEMORY_DB
    return Path(configured).expanduser()


def now() -> float:
    return time.time()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(raw: str | None, default=None):
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = memory_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # Set the timeout before WAL negotiation; concurrent imports may otherwise
    # fail at journal-mode setup before the later busy_timeout pragma is active.
    conn.execute("pragma busy_timeout = 30000")
    with _schema_initialization_lock(path):
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma foreign_keys = on")
        init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists memory_meta (
            key text primary key,
            value text not null
        );

        create table if not exists sessions (
            session_id text primary key,
            module_id text not null,
            user_id text not null default 'local_user',
            title text not null default '新对话',
            status text not null default 'active',
            tags_json text not null default '[]',
            favorite integer not null default 0,
            pinned integer not null default 0,
            archived integer not null default 0,
            deleted_at real,
            created_at real not null,
            updated_at real not null,
            last_message_at real
        );

        create table if not exists messages (
            message_id text primary key,
            session_id text not null,
            turn_id text,
            role text not null,
            content text not null,
            error integer not null default 0,
            created_at real not null,
            metadata_json text not null default '{}',
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists turns (
            turn_id text primary key,
            session_id text not null,
            user_message_id text,
            assistant_message_id text,
            query text,
            answer_mode text,
            status text not null default 'running',
            search_result_id text,
            job_id text,
            created_at real not null,
            completed_at real,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists search_results (
            search_result_id text primary key,
            session_id text not null,
            turn_id text,
            query text not null,
            query_plan_json text not null default '{}',
            filters_json text not null default '{}',
            results_json text not null default '[]',
            created_at real not null,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists evidence_items (
            evidence_item_id text primary key,
            session_id text not null,
            turn_id text,
            search_result_id text,
            evidence_id text,
            article_id integer,
            doi text,
            title text,
            kind text,
            confidence text,
            source_path text,
            snippet text,
            payload_json text not null default '{}',
            created_at real not null,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists artifacts (
            artifact_id text primary key,
            user_id text not null default 'local_user',
            artifact_type text not null,
            title text not null,
            json_path text,
            markdown_path text,
            summary_json text not null default '{}',
            created_at real,
            updated_at real
        );

        create table if not exists conversation_artifact_links (
            session_id text not null,
            turn_id text,
            artifact_id text not null,
            link_type text not null,
            created_at real not null,
            primary key(session_id, turn_id, artifact_id, link_type)
        );

        create table if not exists jobs (
            job_id text primary key,
            user_id text,
            session_id text,
            turn_id text,
            job_type text not null,
            status text not null,
            payload_json text not null default '{}',
            result_json text,
            error text,
            created_at real not null,
            started_at real,
            completed_at real,
            updated_at real not null
        );

        create table if not exists job_events (
            event_id integer primary key autoincrement,
            job_id text not null,
            event_index integer not null,
            event_type text not null,
            event_json text not null,
            created_at real not null,
            unique(job_id, event_index),
            foreign key(job_id) references jobs(job_id) on delete cascade
        );

        create table if not exists tool_traces (
            tool_call_id text primary key,
            session_id text not null,
            turn_id text,
            tool_name text not null,
            schema_version text,
            permission_level text,
            agent_mode text,
            arguments_json text not null default '{}',
            status text not null,
            error_code text,
            error_message text,
            recovery_hint text,
            result_summary text,
            latency_ms integer,
            artifacts_json text not null default '[]',
            jobs_json text not null default '[]',
            state_changed integer not null default 0,
            started_at real not null,
            completed_at real,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists session_annotations (
            annotation_id text primary key,
            session_id text not null,
            target_type text,
            target_id text,
            kind text not null,
            content text,
            created_at real not null,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists session_attachments (
            attachment_id text primary key,
            session_id text not null,
            user_id text not null default 'local_user',
            filename text not null,
            content_type text not null,
            status text not null,
            extracted_text text not null default '',
            text_preview text not null default '',
            char_count integer not null default 0,
            error text,
            created_at real not null,
            deleted_at real,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists settings (
            scope text not null,
            key text not null,
            value_json text not null,
            updated_at real not null,
            primary key(scope, key)
        );

        -- Block 6a: per-session authored research state (one row per 课题).
        -- Holds ONLY the non-derivable facts; candidate papers / evidence pool /
        -- coverage gaps are derived on read from evidence_items / search_results.
        create table if not exists research_state (
            session_id text primary key,
            topic text,
            objective text,
            stage text not null default 'retrieval',
            excluded_directions_json text not null default '[]',
            open_questions_json text not null default '[]',
            completed_questions_json text not null default '[]',
            next_actions_json text not null default '[]',
            updated_at real not null,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        -- Block 6a: per-(session, paper) curation status. A paper with no row is a
        -- plain 'candidate'; rows here are the authored overrides (accept/exclude/...).
        create table if not exists paper_states (
            session_id text not null,
            paper_id text not null,
            status text not null default 'candidate',
            note text,
            source text,
            turn_id text,
            created_at real not null,
            updated_at real not null,
            primary key(session_id, paper_id),
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        -- Literature Search phase 3: per-(session, evidence item) curation status.
        -- This is session-local research state only; it never mutates the corpus index.
        create table if not exists evidence_states (
            session_id text not null,
            evidence_item_id text not null,
            status text not null default 'candidate',
            note text,
            source text,
            turn_id text,
            created_at real not null,
            updated_at real not null,
            primary key(session_id, evidence_item_id),
            foreign key(session_id) references sessions(session_id) on delete cascade,
            foreign key(evidence_item_id) references evidence_items(evidence_item_id) on delete cascade
        );

        -- Block 6a: provenance log for every research-state mutation, so §10
        -- "this conclusion came from which turn / role / user" stays auditable.
        create table if not exists research_state_events (
            event_id integer primary key autoincrement,
            session_id text not null,
            turn_id text,
            source text,
            field text not null,
            operation text not null,
            value_json text not null default '{}',
            created_at real not null,
            foreign key(session_id) references sessions(session_id) on delete cascade
        );

        create table if not exists settings_profiles (
            profile_id text primary key,
            name text not null,
            config_json text not null default '{}',
            active integer not null default 0,
            created_at real not null,
            updated_at real not null
        );

        -- Block 7/10: a Deep Research Task Engine "workflow run" — a native entity
        -- (sibling to sessions, NOT a session sub-mode). One row per launched
        -- workflow; the ordered steps live in workflow_steps. Reuses jobs/artifacts
        -- and (P1) wraps the underlying ResearchRunManager via a corpus-stage runner.
        create table if not exists workflow_runs (
            workflow_id text primary key,
            user_id text not null default 'local_user',
            template_id text not null,
            title text not null default '研究工作流',
            topic text,
            scope text not null default 'library',
            status text not null default 'draft',
            manifest_json text not null default '{}',
            engine_ref_json text not null default '{}',
            session_id text,
            error text,
            deleted_at real,
            created_at real not null,
            updated_at real not null,
            started_at real,
            ended_at real
        );

        -- Block 7/10: per-step execution state — the persisted timeline source.
        -- For a corpus-stage step the underlying run's sub-stages are derived on
        -- read from run_show(manifest/checkpoint), not stored here.
        create table if not exists workflow_steps (
            workflow_id text not null,
            step_index integer not null,
            step_key text not null,
            runner text not null,
            label text not null,
            status text not null default 'pending',
            job_id text,
            artifact_ids_json text not null default '[]',
            error text,
            started_at real,
            ended_at real,
            primary key(workflow_id, step_index),
            foreign key(workflow_id) references workflow_runs(workflow_id) on delete cascade
        );

        create table if not exists structured_extraction_tasks (
            task_id text primary key,
            user_id text not null default 'local_user',
            name text not null,
            description text not null default '',
            status text not null default 'draft',
            workspace_rel_path text not null,
            current_collection_version text,
            current_schema_version text,
            model_settings_json text not null default '{}',
            stats_json text not null default '{}',
            archived integer not null default 0,
            deleted_at real,
            created_at real not null,
            updated_at real not null,
            last_run_at real
        );

        create table if not exists structured_extraction_task_events (
            event_id integer primary key autoincrement,
            task_id text not null,
            user_id text not null default 'local_user',
            event_type text not null,
            payload_json text not null default '{}',
            created_at real not null,
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_candidates (
            candidate_id text primary key,
            task_id text not null,
            user_id text not null default 'local_user',
            paper_id text not null,
            title text,
            authors_json text not null default '[]',
            year integer,
            journal text,
            doi text,
            source_path text,
            index_version integer,
            candidate_source text not null,
            source_query text not null default '',
            source_query_hash text not null,
            matched_fields_json text not null default '[]',
            metadata_score real not null default 0,
            llm_decision text,
            llm_relevance_score real,
            llm_reason text,
            user_decision text not null default 'candidate',
            exclude_reason text,
            duplicate_group_id text,
            canonical_paper_id text,
            duplicate_reason text,
            paper_ref_json text not null default '{}',
            created_at real not null,
            updated_at real not null,
            unique(task_id, paper_id, candidate_source, source_query_hash),
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_candidate_events (
            event_id integer primary key autoincrement,
            candidate_id text not null,
            task_id text not null,
            user_id text not null default 'local_user',
            event_type text not null,
            payload_json text not null default '{}',
            created_at real not null,
            foreign key(candidate_id) references structured_extraction_candidates(candidate_id) on delete cascade
        );

        create table if not exists structured_extraction_collection_versions (
            task_id text not null,
            collection_version text not null,
            user_id text not null default 'local_user',
            paper_count integer not null default 0,
            summary_json text not null default '{}',
            created_at real not null,
            primary key(task_id, collection_version),
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_collection_papers (
            task_id text not null,
            collection_version text not null,
            candidate_id text not null,
            paper_id text not null,
            paper_ref_json text not null default '{}',
            decision_payload_json text not null default '{}',
            created_at real not null,
            primary key(task_id, collection_version, candidate_id),
            foreign key(task_id, collection_version) references structured_extraction_collection_versions(task_id, collection_version) on delete cascade
        );

        create table if not exists structured_extraction_schema_drafts (
            task_id text primary key,
            user_id text not null default 'local_user',
            base_collection_version text not null,
            schema_mode text not null default 'flat_fields',
            record_schema_json text not null default '{}',
            field_groups_json text not null default '[]',
            field_tree_json text not null default '[]',
            fields_json text not null default '[]',
            validation_errors_json text not null default '[]',
            created_at real not null,
            updated_at real not null,
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_schema_versions (
            task_id text not null,
            schema_version text not null,
            user_id text not null default 'local_user',
            base_collection_version text not null,
            schema_mode text not null default 'flat_fields',
            record_schema_json text not null default '{}',
            field_groups_json text not null default '[]',
            field_tree_json text not null default '[]',
            fields_json text not null default '[]',
            field_count integer not null default 0,
            change_summary_json text not null default '{}',
            created_at real not null,
            frozen_at real not null,
            primary key(task_id, schema_version),
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_schema_events (
            event_id integer primary key autoincrement,
            task_id text not null,
            schema_version text,
            user_id text not null default 'local_user',
            event_type text not null,
            payload_json text not null default '{}',
            created_at real not null,
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_prompt_contracts (
            task_id text not null,
            prompt_contract_version text not null,
            user_id text not null default 'local_user',
            collection_version text not null,
            schema_version text not null,
            contract_json text not null default '{}',
            field_count integer not null default 0,
            created_at real not null,
            primary key(task_id, prompt_contract_version),
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_evidence_packet_versions (
            task_id text not null,
            packet_version text not null,
            user_id text not null default 'local_user',
            collection_version text not null,
            schema_version text not null,
            prompt_contract_version text not null,
            paper_count integer not null default 0,
            field_group_count integer not null default 0,
            item_count integer not null default 0,
            settings_json text not null default '{}',
            warnings_json text not null default '[]',
            created_at real not null,
            primary key(task_id, packet_version),
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_evidence_packet_items (
            packet_item_id text primary key,
            task_id text not null,
            packet_version text not null,
            paper_id text not null,
            field_group text not null,
            field_keys_json text not null default '[]',
            construction_query text not null default '',
            retrieved_sections_json text not null default '[]',
            chunks_json text not null default '[]',
            tables_json text not null default '[]',
            figures_json text not null default '[]',
            source_paths_json text not null default '[]',
            warnings_json text not null default '[]',
            created_at real not null,
            foreign key(task_id, packet_version) references structured_extraction_evidence_packet_versions(task_id, packet_version) on delete cascade
        );

        create table if not exists structured_extraction_evidence_packet_build_jobs (
            build_job_id text primary key,
            task_id text not null,
            user_id text not null default 'local_user',
            status text not null default 'queued',
            phase text not null default 'resolving_inputs',
            collection_version text not null,
            schema_version text not null,
            prompt_contract_version text not null,
            target_packet_version text not null,
            result_packet_version text,
            paper_count integer not null default 0,
            field_group_count integer not null default 0,
            total_item_count integer not null default 0,
            processed_item_count integer not null default 0,
            warning_count integer not null default 0,
            current_paper_id text,
            current_field_group text,
            current_query_mode text,
            total_chunk_count integer not null default 0,
            slow_item_count integer not null default 0,
            last_item_seconds real,
            settings_json text not null default '{}',
            warnings_preview_json text not null default '[]',
            error_json text,
            created_at real not null,
            started_at real,
            updated_at real not null,
            completed_at real,
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_evidence_packet_build_items (
            build_job_id text not null,
            item_index integer not null,
            packet_item_json text not null,
            warnings_json text not null default '[]',
            created_at real not null,
            primary key(build_job_id, item_index),
            foreign key(build_job_id) references structured_extraction_evidence_packet_build_jobs(build_job_id) on delete cascade
        );

        create table if not exists structured_extraction_runs (
            run_id text primary key,
            task_id text not null,
            user_id text not null default 'local_user',
            status text not null default 'queued',
            collection_version text not null,
            schema_version text not null,
            prompt_contract_version text not null,
            packet_version text not null,
            model_snapshot_json text not null default '{}',
            stats_json text not null default '{}',
            error_json text,
            previous_task_status text,
            created_at real not null,
            started_at real,
            completed_at real,
            resume_count integer not null default 0,
            last_heartbeat_at real,
            interrupted_at real,
            counted_at real,
            recovery_json text not null default '{}',
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_run_items (
            run_item_id text primary key,
            run_id text not null,
            task_id text not null,
            user_id text not null default 'local_user',
            packet_item_id text not null,
            paper_id text not null,
            field_group text not null,
            status text not null default 'queued',
            prompt_json text not null default '{}',
            raw_output text,
            parsed_json text,
            error_json text,
            created_at real not null,
            started_at real,
            completed_at real,
            attempt_count integer not null default 0,
            last_attempt_at real,
            foreign key(run_id) references structured_extraction_runs(run_id) on delete cascade
        );

        create table if not exists structured_extraction_records (
            record_id text primary key,
            run_id text not null,
            task_id text not null,
            user_id text not null default 'local_user',
            paper_id text not null,
            record_type text,
            record_index integer not null default 1,
            record_identity_json text not null default '{}',
            data_json text not null default '{}',
            fields_json text not null default '{}',
            source_packet_item_ids_json text not null default '[]',
            quality_flags_json text not null default '[]',
            record_json text not null default '{}',
            created_at real not null,
            foreign key(run_id) references structured_extraction_runs(run_id) on delete cascade
        );

        create table if not exists structured_extraction_run_events (
            event_id integer primary key autoincrement,
            run_id text not null,
            task_id text not null,
            user_id text not null default 'local_user',
            event_type text not null,
            payload_json text not null default '{}',
            created_at real not null,
            foreign key(run_id) references structured_extraction_runs(run_id) on delete cascade
        );

        create table if not exists structured_extraction_review_events (
            event_id integer primary key autoincrement,
            task_id text not null,
            run_id text not null,
            record_id text not null,
            field_key text not null,
            user_id text not null default 'local_user',
            event_type text not null,
            old_value_json text,
            new_value_json text,
            reason text not null default '',
            locked integer not null default 0,
            target_event_id integer,
            payload_json text not null default '{}',
            created_at real not null,
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_review_field_states (
            task_id text not null,
            run_id text not null,
            record_id text not null,
            field_key text not null,
            user_id text not null default 'local_user',
            base_value_json text,
            effective_value_json text,
            status text not null default 'unreviewed',
            locked integer not null default 0,
            quality_flags_json text not null default '[]',
            review_priority text not null default 'low',
            provenance_json text not null default '{}',
            last_event_id integer,
            updated_at real not null,
            primary key(task_id, run_id, record_id, field_key),
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_multimodal_review_jobs (
            job_id text primary key,
            task_id text not null,
            run_id text not null,
            user_id text not null default 'local_user',
            status text not null default 'queued',
            scan_mode text not null default 'related_pages_assets',
            reason text not null default '',
            model_snapshot_json text not null default '{}',
            total_item_count integer not null default 0,
            processed_item_count integer not null default 0,
            suggestion_count integer not null default 0,
            issue_count integer not null default 0,
            current_paper_id text,
            current_record_id text,
            current_section text,
            warnings_json text not null default '[]',
            error_json text,
            created_at real not null,
            started_at real,
            updated_at real not null,
            completed_at real,
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_multimodal_review_suggestions (
            suggestion_id text primary key,
            job_id text not null,
            task_id text not null,
            run_id text not null,
            record_id text not null,
            field_key text not null,
            user_id text not null default 'local_user',
            action text not null,
            status text not null default 'pending',
            risk_level text not null default 'medium',
            coverage_status text,
            issue_type text,
            suggested_value_json text,
            current_value_json text,
            evidence_json text not null default '{}',
            provenance_json text not null default '{}',
            reason text not null default '',
            created_at real not null,
            resolved_at real,
            foreign key(job_id) references structured_extraction_multimodal_review_jobs(job_id) on delete cascade,
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create table if not exists structured_extraction_exports (
            task_id text not null,
            export_id text not null,
            user_id text not null default 'local_user',
            run_id text not null,
            collection_version text not null,
            schema_version text not null,
            formats_json text not null default '[]',
            files_json text not null default '{}',
            settings_json text not null default '{}',
            summary_json text not null default '{}',
            record_count integer not null default 0,
            field_count integer not null default 0,
            created_at real not null,
            primary key(task_id, export_id),
            foreign key(task_id) references structured_extraction_tasks(task_id) on delete cascade
        );

        create index if not exists idx_messages_session_created on messages(session_id, created_at);
        create index if not exists idx_turns_session_created on turns(session_id, created_at);
        create index if not exists idx_search_session_created on search_results(session_id, created_at);
        create index if not exists idx_evidence_session_created on evidence_items(session_id, created_at);
        create index if not exists idx_jobs_session_updated on jobs(session_id, updated_at);
        create index if not exists idx_sessions_user_module_updated on sessions(user_id, module_id, updated_at);
        create index if not exists idx_job_events_job_index on job_events(job_id, event_index);
        create index if not exists idx_tool_traces_turn on tool_traces(turn_id, started_at);
        create index if not exists idx_paper_states_session on paper_states(session_id, status);
        create index if not exists idx_evidence_states_session on evidence_states(session_id, status);
        create index if not exists idx_state_events_session on research_state_events(session_id, created_at);
        create index if not exists idx_workflow_runs_updated on workflow_runs(updated_at);
        create index if not exists idx_workflow_steps_wf on workflow_steps(workflow_id, step_index);
        create index if not exists idx_structured_extraction_tasks_user_updated on structured_extraction_tasks(user_id, archived, updated_at);
        create index if not exists idx_structured_extraction_task_events_task on structured_extraction_task_events(task_id, created_at);
        create index if not exists idx_structured_extraction_candidates_task_decision on structured_extraction_candidates(task_id, user_decision, updated_at);
        create index if not exists idx_structured_extraction_candidates_task_source on structured_extraction_candidates(task_id, candidate_source, updated_at);
        create index if not exists idx_structured_extraction_versions_task on structured_extraction_collection_versions(task_id, created_at);
        create index if not exists idx_structured_extraction_schema_versions_task on structured_extraction_schema_versions(task_id, created_at);
        create index if not exists idx_structured_extraction_schema_events_task on structured_extraction_schema_events(task_id, created_at);
        create index if not exists idx_structured_extraction_prompt_contracts_task on structured_extraction_prompt_contracts(task_id, created_at);
        create index if not exists idx_structured_extraction_packet_versions_task on structured_extraction_evidence_packet_versions(task_id, created_at);
        create index if not exists idx_structured_extraction_packet_items_version on structured_extraction_evidence_packet_items(task_id, packet_version, paper_id);
        create index if not exists idx_structured_extraction_ep_build_jobs_task on structured_extraction_evidence_packet_build_jobs(task_id, user_id, created_at);
        create index if not exists idx_structured_extraction_ep_build_jobs_status on structured_extraction_evidence_packet_build_jobs(status, updated_at);
        create index if not exists idx_structured_extraction_ep_build_items_job on structured_extraction_evidence_packet_build_items(build_job_id, item_index);
        create index if not exists idx_structured_extraction_runs_task on structured_extraction_runs(task_id, created_at);
        create index if not exists idx_structured_extraction_run_items_run on structured_extraction_run_items(run_id, status, paper_id);
        create index if not exists idx_structured_extraction_records_run on structured_extraction_records(run_id, paper_id, record_index);
        create index if not exists idx_structured_extraction_run_events_run on structured_extraction_run_events(run_id, created_at);
        create index if not exists idx_structured_extraction_review_events_record on structured_extraction_review_events(task_id, record_id, created_at);
        create index if not exists idx_structured_extraction_review_states_run on structured_extraction_review_field_states(task_id, run_id, status, review_priority);
        create index if not exists idx_structured_extraction_mm_jobs_run on structured_extraction_multimodal_review_jobs(task_id, run_id, status, updated_at);
        create index if not exists idx_structured_extraction_mm_suggestions_run on structured_extraction_multimodal_review_suggestions(task_id, run_id, status, record_id);
        create index if not exists idx_structured_extraction_exports_task on structured_extraction_exports(task_id, created_at);
        """
    )
    _ensure_column(conn, "sessions", "pinned", "integer not null default 0")
    _ensure_column(conn, "sessions", "deleted_at", "real")
    _ensure_column(conn, "artifacts", "user_id", "text not null default 'local_user'")
    _ensure_column(conn, "jobs", "user_id", "text")
    _ensure_column(conn, "workflow_runs", "user_id", "text not null default 'local_user'")
    _ensure_column(conn, "structured_extraction_runs", "resume_count", "integer not null default 0")
    _ensure_column(conn, "structured_extraction_runs", "last_heartbeat_at", "real")
    _ensure_column(conn, "structured_extraction_runs", "interrupted_at", "real")
    _ensure_column(conn, "structured_extraction_runs", "counted_at", "real")
    _ensure_column(conn, "structured_extraction_runs", "recovery_json", "text not null default '{}'")
    _ensure_column(conn, "structured_extraction_run_items", "attempt_count", "integer not null default 0")
    _ensure_column(conn, "structured_extraction_run_items", "last_attempt_at", "real")
    _ensure_column(conn, "structured_extraction_evidence_packet_build_jobs", "current_query_mode", "text")
    _ensure_column(conn, "structured_extraction_evidence_packet_build_jobs", "total_chunk_count", "integer not null default 0")
    _ensure_column(conn, "structured_extraction_evidence_packet_build_jobs", "slow_item_count", "integer not null default 0")
    _ensure_column(conn, "structured_extraction_evidence_packet_build_jobs", "last_item_seconds", "real")
    _ensure_column(conn, "structured_extraction_schema_drafts", "schema_mode", "text not null default 'flat_fields'")
    _ensure_column(conn, "structured_extraction_schema_drafts", "field_tree_json", "text not null default '[]'")
    _ensure_column(conn, "structured_extraction_schema_versions", "schema_mode", "text not null default 'flat_fields'")
    _ensure_column(conn, "structured_extraction_schema_versions", "field_tree_json", "text not null default '[]'")
    _ensure_column(conn, "structured_extraction_records", "data_json", "text not null default '{}'")
    _ensure_column(conn, "structured_extraction_review_field_states", "provenance_json", "text not null default '{}'")
    # Block 0: bind persisted evidence to the canonical research-index identity.
    _ensure_column(conn, "evidence_items", "paper_id", "text")
    _ensure_column(conn, "evidence_items", "section_id", "text")
    _ensure_column(conn, "evidence_items", "chunk_index", "integer")
    _ensure_column(conn, "evidence_items", "index_version", "integer")
    # Block 2: persist the evidence-acquisition coverage judgment + fallback reason
    # so the research record / export can audit the full retrieval packet.
    _ensure_column(conn, "search_results", "coverage_json", "text not null default '{}'")
    _ensure_column(conn, "search_results", "fallback_json", "text")
    _ensure_column(conn, "search_results", "breadth_json", "text not null default '{}'")
    # Block 6c: which specialist role (subagent) handled the turn.
    _ensure_column(conn, "turns", "role", "text")
    conn.executescript(
        """
        create index if not exists idx_jobs_user_updated on jobs(user_id, updated_at);
        create index if not exists idx_artifacts_user_updated on artifacts(user_id, updated_at);
        create index if not exists idx_session_attachments_session on session_attachments(session_id, user_id, deleted_at, created_at);
        create index if not exists idx_workflow_runs_user_updated on workflow_runs(user_id, updated_at);
        create index if not exists idx_structured_extraction_tasks_user_updated on structured_extraction_tasks(user_id, archived, updated_at);
        create index if not exists idx_structured_extraction_candidates_task_decision on structured_extraction_candidates(task_id, user_decision, updated_at);
        create index if not exists idx_structured_extraction_schema_versions_task on structured_extraction_schema_versions(task_id, created_at);
        create index if not exists idx_structured_extraction_prompt_contracts_task on structured_extraction_prompt_contracts(task_id, created_at);
        create index if not exists idx_structured_extraction_packet_versions_task on structured_extraction_evidence_packet_versions(task_id, created_at);
        create index if not exists idx_structured_extraction_runs_task on structured_extraction_runs(task_id, created_at);
        create index if not exists idx_structured_extraction_exports_task on structured_extraction_exports(task_id, created_at);
        """
    )
    conn.execute(
        "insert or replace into memory_meta(key, value) values('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not _column_exists(conn, table, column):
        try:
            conn.execute(f"alter table {table} add column {column} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column" in str(exc).lower() and _column_exists(conn, table, column):
                return
            raise


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    columns = {row[1] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    return column in columns


@contextmanager
def _schema_initialization_lock(path: Path):
    with _SCHEMA_INIT_LOCK:
        lock_path = path.with_name(f"{path.name}.init.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a", encoding="utf-8") as lock_file:
            try:
                import fcntl
            except ImportError:
                yield
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
