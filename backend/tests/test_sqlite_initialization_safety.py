from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def test_research_agent_controller_import_does_not_create_memory_db(tmp_path: Path) -> None:
    db_path = tmp_path / "import_side_effect.sqlite"
    env = dict(os.environ)
    env["PYTHONPATH"] = "backend"
    env["LITERATURE_MEMORY_DB_PATH"] = str(db_path)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path\n"
                "import os\n"
                "import modules.research_agent_controller.schemas\n"
                "print('exists=' + str(Path(os.environ['LITERATURE_MEMORY_DB_PATH']).exists()))\n"
            ),
        ],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "exists=False" in completed.stdout
    assert not db_path.exists()


def test_memory_schema_repeated_connect_is_idempotent(tmp_path: Path) -> None:
    from core.memory_db import connect

    db_path = tmp_path / "repeated.sqlite"
    first = connect(db_path)
    first.close()

    second = connect(db_path)
    columns = {row[1] for row in second.execute("pragma table_info(evidence_items)").fetchall()}
    second.close()

    assert {"paper_id", "section_id", "chunk_index", "index_version"}.issubset(columns)


def test_memory_schema_upgrades_legacy_user_scoped_tables_before_indexing(
    tmp_path: Path,
) -> None:
    from core.memory_db import connect

    db_path = tmp_path / "legacy_user_scope.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        create table sessions (
            session_id text primary key,
            module_id text not null,
            user_id text not null default 'local_user',
            title text not null default '新对话',
            status text not null default 'active',
            tags_json text not null default '[]',
            favorite integer not null default 0,
            archived integer not null default 0,
            created_at real not null,
            updated_at real not null,
            last_message_at real
        );
        create table artifacts (
            artifact_id text primary key,
            artifact_type text not null,
            title text not null,
            json_path text,
            markdown_path text,
            summary_json text not null default '{}',
            created_at real,
            updated_at real
        );
        create table jobs (
            job_id text primary key,
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
        create table workflow_runs (
            workflow_id text primary key,
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
        """
    )
    conn.close()

    upgraded = connect(db_path)
    try:
        artifact_columns = {
            row[1] for row in upgraded.execute("pragma table_info(artifacts)").fetchall()
        }
        job_columns = {row[1] for row in upgraded.execute("pragma table_info(jobs)").fetchall()}
        workflow_columns = {
            row[1] for row in upgraded.execute("pragma table_info(workflow_runs)").fetchall()
        }
        indexes = {
            row[0]
            for row in upgraded.execute(
                "select name from sqlite_master where type = 'index'"
            ).fetchall()
        }
    finally:
        upgraded.close()

    assert "user_id" in artifact_columns
    assert "user_id" in job_columns
    assert "user_id" in workflow_columns
    assert "idx_artifacts_user_updated" in indexes
    assert "idx_jobs_user_updated" in indexes
    assert "idx_workflow_runs_user_updated" in indexes


def test_ensure_column_treats_duplicate_column_race_as_success() -> None:
    from core.memory_db import _ensure_column

    conn = _RaceConnection()

    _ensure_column(conn, "evidence_items", "paper_id", "text")

    assert conn.alter_attempts == 1
    assert conn.table_info_calls == 2


def test_ensure_column_does_not_swallow_non_duplicate_operational_errors() -> None:
    from core.memory_db import _ensure_column

    conn = _RaceConnection(error_message="database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        _ensure_column(conn, "evidence_items", "paper_id", "text")


def test_parallel_like_memory_schema_initialization_is_safe(tmp_path: Path) -> None:
    from core.memory_db import connect

    db_path = tmp_path / "parallel.sqlite"

    def initialize() -> set[str]:
        conn = connect(db_path)
        try:
            return {row[1] for row in conn.execute("pragma table_info(evidence_items)").fetchall()}
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: initialize(), range(8)))

    for columns in results:
        assert {"paper_id", "section_id", "chunk_index", "index_version"}.issubset(columns)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _RaceConnection:
    def __init__(self, error_message: str = "duplicate column name: paper_id") -> None:
        self.error_message = error_message
        self.table_info_calls = 0
        self.alter_attempts = 0

    def execute(self, sql: str):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("pragma table_info"):
            self.table_info_calls += 1
            if self.table_info_calls == 1:
                return _Rows([])
            return _Rows([(0, "paper_id", "text", 0, None, 0)])
        if normalized.startswith("alter table"):
            self.alter_attempts += 1
            raise sqlite3.OperationalError(self.error_message)
        return _Rows([])
