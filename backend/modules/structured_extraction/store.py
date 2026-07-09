from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, json_loads, new_uuid, to_unix_seconds, utc_now, uuid_value
from core.user_context import DEFAULT_USER_ID, UserContext
from core.user_store import UserStore

from .artifacts import ensure_task_workspace, task_workspace_rel_path, write_task_manifest
from .schemas import DEFAULT_TASK_STATS, ExtractionTask, TaskStatus

_HIDDEN_STATUSES = ("deleted",)
_JSON_COLUMN_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*(?:_json|_jsonb)|error_json|parsed_json|packet_item_json)\s*=\s*\?$")
_TIMESTAMP_COLUMN_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*_at)\s*=\s*(?:coalesce\()?$")
_TIMESTAMP_COALESCE_RE = re.compile(r"coalesce\(\s*[a-zA-Z_][a-zA-Z0-9_]*_at\s*,\s*$")
_BOOLEAN_COLUMN_RE = re.compile(r"\b(archived|locked|cancel_requested)\s*=\s*$")
_INSERT_RE = re.compile(r"insert\s+into\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\((.*?)\)\s*values\s*\((.*?)\)", re.IGNORECASE | re.DOTALL)


class StructuredExtractionStore:
    def __init__(self, db_path: str | Path | None = None, engine: Engine | None = None) -> None:
        self.db_path = db_path
        self.engine = engine or create_engine_from_env()
        self.conn = _PostgresCompatConnection(self.engine)

    def create_task(
        self,
        *,
        name: str,
        description: str = "",
        user: UserContext | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = _resolve_user(user, self.engine)
        task_id = new_uuid()
        ts = utc_now()
        stats = dict(DEFAULT_TASK_STATS)
        with self.engine.begin() as conn:
            conn.execute(
                _json_text(
                    """
                    insert into structured_extraction_tasks(
                        task_id, user_id, name, description, status, workspace_rel_path,
                        model_settings_json, stats_json, archived, created_at, updated_at
                    ) values(
                        :task_id, :user_id, :name, :description, 'draft', :workspace_rel_path,
                        cast(:model_settings_json as jsonb), cast(:stats_json as jsonb), false, :ts, :ts
                    )
                    """
                ),
                {
                    "task_id": uuid_value(task_id),
                    "user_id": uuid_value(ctx.user_id),
                    "name": _clean_name(name),
                    "description": description or "",
                    "workspace_rel_path": task_workspace_rel_path(task_id),
                    "model_settings_json": json_dumps(model_settings or {}),
                    "stats_json": json_dumps(stats),
                    "ts": ts,
                },
            )
            self._insert_event(task_id, ctx.user_id, "created", {"name": name}, conn=conn)
        task = self.get_task(task_id, user_id=ctx.user_id)
        ensure_task_workspace(ctx, task)
        return task

    def list_tasks(self, *, include_archived: bool = False, limit: int = 100, user_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"hidden": list(_HIDDEN_STATUSES), "limit": max(1, min(int(limit or 100), 500))}
        where = ["status != all(:hidden)"]
        if not include_archived:
            where.append("archived = false")
        if user_id is not None:
            where.append("user_id = :user_id")
            params["user_id"] = uuid_value(user_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(f"select * from structured_extraction_tasks where {' and '.join(where)} order by updated_at desc limit :limit"),
                params,
            ).mappings().all()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        try:
            task_uuid = uuid_value(task_id)
            user_uuid = uuid_value(user_id) if user_id is not None else None
        except ValueError:
            raise KeyError(f"structured extraction task not found: {task_id}") from None
        with self.engine.connect() as conn:
            if user_uuid is None:
                row = conn.execute(
                    text("select * from structured_extraction_tasks where task_id = :task_id"),
                    {"task_id": task_uuid},
                ).mappings().first()
            else:
                row = conn.execute(
                    text("select * from structured_extraction_tasks where task_id = :task_id and user_id = :user_id"),
                    {"task_id": task_uuid, "user_id": user_uuid},
                ).mappings().first()
        if not row or row["status"] == "deleted":
            raise KeyError(f"structured extraction task not found: {task_id}")
        return self._row_to_task(row)

    def update_task(
        self,
        task_id: str,
        *,
        user: UserContext,
        name: str | None = None,
        description: str | None = None,
        status: TaskStatus | None = None,
        model_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_task(task_id, user_id=user.user_id)
        changes: dict[str, Any] = {}
        event_payload: dict[str, Any] = {}
        if name is not None:
            changes["name"] = _clean_name(name)
            event_payload["name"] = changes["name"]
        if description is not None:
            changes["description"] = description
            event_payload["description"] = description
        if status is not None:
            changes["status"] = status
            event_payload["status"] = status
        if model_settings is not None:
            changes["model_settings_json"] = json_dumps(model_settings)
            event_payload["model_settings"] = model_settings
        if changes:
            changes["updated_at"] = utc_now()
            params: dict[str, Any] = {"task_id": uuid_value(task_id), "user_id": uuid_value(user.user_id)}
            assignments = []
            for key, value in changes.items():
                assignments.append(f"{key} = cast(:{key} as jsonb)" if key.endswith("_json") else f"{key} = :{key}")
                params[key] = value
            with self.engine.begin() as conn:
                conn.execute(
                    text(f"update structured_extraction_tasks set {', '.join(assignments)} where task_id = :task_id and user_id = :user_id"),
                    params,
                )
                self._insert_event(task_id, user.user_id, "updated", event_payload, conn=conn)
        task = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, task)
        return task

    def set_archived(self, task_id: str, archived: bool, *, user: UserContext) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        ts = utc_now()
        status = "archived" if archived else ("draft" if task["status"] == "archived" else task["status"])
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    update structured_extraction_tasks
                    set archived = :archived, status = :status, updated_at = :ts
                    where task_id = :task_id and user_id = :user_id
                    """
                ),
                {"archived": archived, "status": status, "ts": ts, "task_id": uuid_value(task_id), "user_id": uuid_value(user.user_id)},
            )
            self._insert_event(task_id, user.user_id, "archived" if archived else "unarchived", {"archived": archived}, conn=conn)
        out = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, out)
        return out

    def soft_delete(self, task_id: str, *, user: UserContext) -> None:
        self.get_task(task_id, user_id=user.user_id)
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    update structured_extraction_tasks
                    set status = 'deleted', deleted_at = :ts, updated_at = :ts
                    where task_id = :task_id and user_id = :user_id
                    """
                ),
                {"ts": ts, "task_id": uuid_value(task_id), "user_id": uuid_value(user.user_id)},
            )
            self._insert_event(task_id, user.user_id, "deleted", {}, conn=conn)

    def duplicate_task(self, task_id: str, *, user: UserContext, name: str, copy_model_settings: bool = True) -> dict[str, Any]:
        source = self.get_task(task_id, user_id=user.user_id)
        return self.create_task(
            name=name,
            description=source.get("description") or "",
            user=user,
            model_settings=source.get("model_settings") if copy_model_settings else {},
        )

    def mark_collecting(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        if task["status"] == "draft":
            with self.engine.begin() as conn:
                conn.execute(
                    text("update structured_extraction_tasks set status = 'collecting', updated_at = :ts where task_id = :task_id and user_id = :user_id"),
                    {"ts": utc_now(), "task_id": uuid_value(task_id), "user_id": uuid_value(user.user_id)},
                )
                self._insert_event(task_id, user.user_id, "collecting", {}, conn=conn)
            task = self.get_task(task_id, user_id=user.user_id)
            write_task_manifest(user, task)
        return task

    def update_collection_state(self, task_id: str, *, user: UserContext, collection_version: str, paper_count: int) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(task.get("stats") or {})
        stats["paper_count"] = int(paper_count)
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    update structured_extraction_tasks
                    set status = 'collection_ready',
                        current_collection_version = :collection_version,
                        stats_json = cast(:stats_json as jsonb),
                        updated_at = :ts
                    where task_id = :task_id and user_id = :user_id
                    """
                ),
                {
                    "collection_version": collection_version,
                    "stats_json": json_dumps(stats),
                    "ts": ts,
                    "task_id": uuid_value(task_id),
                    "user_id": uuid_value(user.user_id),
                },
            )
            self._insert_event(task_id, user.user_id, "collection_frozen", {"collection_version": collection_version, "paper_count": paper_count}, conn=conn)
        out = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, out)
        return out

    def update_schema_state(self, task_id: str, *, user: UserContext, schema_version: str, field_count: int) -> dict[str, Any]:
        task = self.get_task(task_id, user_id=user.user_id)
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(task.get("stats") or {})
        stats["field_count"] = int(field_count)
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    update structured_extraction_tasks
                    set status = 'schema_ready',
                        current_schema_version = :schema_version,
                        stats_json = cast(:stats_json as jsonb),
                        updated_at = :ts
                    where task_id = :task_id and user_id = :user_id
                    """
                ),
                {
                    "schema_version": schema_version,
                    "stats_json": json_dumps(stats),
                    "ts": ts,
                    "task_id": uuid_value(task_id),
                    "user_id": uuid_value(user.user_id),
                },
            )
            self._insert_event(task_id, user.user_id, "schema_frozen", {"schema_version": schema_version, "field_count": field_count}, conn=conn)
        out = self.get_task(task_id, user_id=user.user_id)
        write_task_manifest(user, out)
        return out

    def events_for_task(self, task_id: str, *, user_id: str) -> list[dict[str, Any]]:
        self.get_task(task_id, user_id=user_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select * from structured_extraction_task_events
                    where task_id = :task_id and user_id = :user_id
                    order by created_at
                    """
                ),
                {"task_id": uuid_value(task_id), "user_id": uuid_value(user_id)},
            ).mappings().all()
        return [
            {
                "event_id": row["event_id"],
                "task_id": str(row["task_id"]),
                "user_id": str(row["user_id"]),
                "event_type": row["event_type"],
                "payload": json_loads(row["payload_json"], {}) or {},
                "created_at": to_unix_seconds(row["created_at"]),
            }
            for row in rows
        ]

    def _insert_event(self, task_id: str, user_id: str, event_type: str, payload: dict[str, Any], *, conn=None) -> None:
        params = {
            "task_id": uuid_value(task_id),
            "user_id": uuid_value(user_id),
            "event_type": event_type,
            "payload_json": json_dumps(payload),
            "created_at": utc_now(),
        }
        statement = text(
            """
            insert into structured_extraction_task_events(task_id, user_id, event_type, payload_json, created_at)
            values(:task_id, :user_id, :event_type, cast(:payload_json as jsonb), :created_at)
            """
        )
        if conn is not None:
            conn.execute(statement, params)
        else:
            with self.engine.begin() as owned:
                owned.execute(statement, params)

    @staticmethod
    def _row_to_task(row) -> dict[str, Any]:
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(json_loads(row["stats_json"], {}) or {})
        return ExtractionTask(
            task_id=str(row["task_id"]),
            user_id=str(row["user_id"]),
            name=row["name"],
            description=row["description"] or "",
            status=row["status"],
            workspace_rel_path=row["workspace_rel_path"],
            current_collection_version=row["current_collection_version"],
            current_schema_version=row["current_schema_version"],
            model_settings=json_loads(row["model_settings_json"], {}) or {},
            stats=stats,
            archived=bool(row["archived"]),
            deleted_at=to_unix_seconds(row["deleted_at"]),
            created_at=to_unix_seconds(row["created_at"]) or 0.0,
            updated_at=to_unix_seconds(row["updated_at"]) or 0.0,
            last_run_at=to_unix_seconds(row["last_run_at"]),
        ).model_dump()


class _PostgresCompatConnection:
    """Small SQLite-style facade while structured extraction services migrate.

    It intentionally supports only the subset used by this module: ``execute``,
    ``commit`` and row/result accessors. Each statement is committed
    independently, which matches the current in-process background-thread model
    closely enough for M4 while allowing services to be converted incrementally.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def execute(self, sql: str, params: Iterable[Any] | dict[str, Any] | None = None):
        statement, bound_params, json_param_names = _translate_sql(sql, params)
        bindparams = [bindparam(name, type_=JSONB) for name in json_param_names]
        if bindparams:
            statement = statement.bindparams(*bindparams)
        with self.engine.begin() as conn:
            result = conn.execute(statement, bound_params)
            if result.returns_rows:
                return _ResultAdapter(result.mappings().all())
            return _ResultAdapter([])

    def commit(self) -> None:
        return None


class _ResultAdapter:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = [_RowAdapter(row) for row in rows]
        self.lastrowid = self._rows[0].get("event_id") if self._rows else None

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _RowAdapter:
    def __init__(self, row) -> None:
        self._data = {key: _to_api_value(value) for key, value in dict(row).items()}
        self._values = list(self._data.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()


def _translate_sql(sql: str, params: Iterable[Any] | dict[str, Any] | None):
    normalized_sql = _normalize_sql(sql)
    if isinstance(params, dict):
        return text(normalized_sql), {key: _param_value(value) for key, value in params.items()}, []

    values = list(params or [])
    json_indexes = _json_placeholder_indexes(normalized_sql)
    timestamp_indexes = _timestamp_placeholder_indexes(normalized_sql)
    boolean_indexes = _boolean_placeholder_indexes(normalized_sql)
    out = []
    named: dict[str, Any] = {}
    json_names: list[str] = []
    index = 0
    for char in normalized_sql:
        if char == "?":
            name = f"p{index}"
            out.append(f":{name}")
            value = _param_value(values[index])
            if index in json_indexes:
                value = json_loads(value, value) if isinstance(value, str) else value
                json_names.append(name)
            elif index in timestamp_indexes:
                value = _datetime_value(value)
            elif index in boolean_indexes:
                value = _bool_value(value)
            named[name] = value
            index += 1
        else:
            out.append(char)
    return text("".join(out)), named, json_names


def _json_placeholder_indexes(sql: str) -> set[int]:
    indexes: set[int] = set()
    insert_match = _INSERT_RE.search(sql)
    if insert_match:
        columns = [col.strip().strip('"') for col in _split_sql_csv(insert_match.group(1))]
        values = [value.strip() for value in _split_sql_csv(insert_match.group(2))]
        placeholder_index = 0
        for column, value in zip(columns, values):
            if "?" not in value:
                continue
            if _is_json_column(column):
                indexes.add(placeholder_index)
            placeholder_index += value.count("?")
    placeholder_index = 0
    for match in re.finditer(r"\?", sql):
        prefix = sql[: match.start()]
        tail = prefix[-96:]
        if _JSON_COLUMN_RE.search(tail):
            indexes.add(placeholder_index)
        placeholder_index += 1
    return indexes


def _timestamp_placeholder_indexes(sql: str) -> set[int]:
    indexes: set[int] = set()
    insert_match = _INSERT_RE.search(sql)
    if insert_match:
        columns = [col.strip().strip('"') for col in _split_sql_csv(insert_match.group(1))]
        values = [value.strip() for value in _split_sql_csv(insert_match.group(2))]
        placeholder_index = 0
        for column, value in zip(columns, values):
            if "?" not in value:
                continue
            if _is_timestamp_column(column):
                indexes.add(placeholder_index)
            placeholder_index += value.count("?")
    placeholder_index = 0
    for match in re.finditer(r"\?", sql):
        prefix = sql[: match.start()]
        tail = prefix[-128:]
        if _TIMESTAMP_COLUMN_RE.search(tail) or _TIMESTAMP_COALESCE_RE.search(tail):
            indexes.add(placeholder_index)
        placeholder_index += 1
    return indexes


def _boolean_placeholder_indexes(sql: str) -> set[int]:
    indexes: set[int] = set()
    insert_match = _INSERT_RE.search(sql)
    if insert_match:
        columns = [col.strip().strip('"') for col in _split_sql_csv(insert_match.group(1))]
        values = [value.strip() for value in _split_sql_csv(insert_match.group(2))]
        placeholder_index = 0
        for column, value in zip(columns, values):
            if "?" not in value:
                continue
            if _is_boolean_column(column):
                indexes.add(placeholder_index)
            placeholder_index += value.count("?")
    placeholder_index = 0
    for match in re.finditer(r"\?", sql):
        prefix = sql[: match.start()]
        tail = prefix[-64:]
        if _BOOLEAN_COLUMN_RE.search(tail):
            indexes.add(placeholder_index)
        placeholder_index += 1
    return indexes


def _normalize_sql(sql: str) -> str:
    out = sql
    replacements = {
        "archived = 0": "archived = false",
        "archived = 1": "archived = true",
        "locked = 0": "locked = false",
        "locked = 1": "locked = true",
        "'unreviewed', 0,": "'unreviewed', false,",
        "'accept_multimodal_suggestion', ?, ?, ?, 0,": "'accept_multimodal_suggestion', ?, ?, ?, false,",
        "'[]'": "'[]'::jsonb",
        "'{}'": "'{}'::jsonb",
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
    if re.match(r"\s*insert\s+into\s+structured_extraction_review_events\s*\(", out, flags=re.IGNORECASE) and " returning " not in out.lower():
        out = f"{out.rstrip()} returning event_id"
    return out


def _split_sql_csv(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    depth = 0
    for char in value:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
            current.append(char)
            continue
        if char == ")":
            depth = max(0, depth - 1)
            current.append(char)
            continue
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def _is_json_column(column: str) -> bool:
    return column.endswith("_json") or column in {
        "error_json",
        "parsed_json",
        "packet_item_json",
        "base_value_json",
        "effective_value_json",
        "old_value_json",
        "new_value_json",
        "suggested_value_json",
        "current_value_json",
    }


def _is_timestamp_column(column: str) -> bool:
    return column.endswith("_at")


def _is_boolean_column(column: str) -> bool:
    return column in {"archived", "locked", "cancel_requested"}


def _json_text(sql: str):
    return text(sql)


def _param_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid_value(value)
        except ValueError:
            return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return value


def _datetime_value(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return value


def _bool_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _to_api_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return to_unix_seconds(value)
    return value


def _resolve_user(user: UserContext | None, engine: Engine) -> UserContext:
    if user and _is_uuid(user.user_id):
        return UserContext(
            user_id=user.user_id,
            subject=user.subject,
            display_name=user.display_name,
            workspace_slug=user.user_id,
            auth_mode=user.auth_mode,
        )
    if user and user.user_id and user.user_id != DEFAULT_USER_ID:
        created = UserStore(engine=engine).get_or_create_user_for_subject(provider="dev-header", subject=user.user_id, display_name=user.display_name)
        return UserContext(
            user_id=created["user_id"],
            subject=user.subject,
            display_name=created["display_name"],
            workspace_slug=created["user_id"],
        )
    created = UserStore(engine=engine).ensure_local_user()
    return UserContext(
        user_id=created["user_id"],
        subject=created.get("subject") or DEFAULT_USER_ID,
        display_name=created["display_name"],
        workspace_slug=created["user_id"],
    )


def _is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid_value(value)
        return True
    except ValueError:
        return False


def now() -> float:
    return to_unix_seconds(utc_now()) or 0.0


def dumps(value: Any) -> str:
    return json_dumps(value)


def loads(value: Any, default: Any = None) -> Any:
    return json_loads(value, default)


def _clean_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("task name is required")
    return cleaned[:160]
