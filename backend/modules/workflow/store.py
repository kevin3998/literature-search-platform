"""PostgreSQL-backed workflow persistence.

M3 moves the workflow runtime off the legacy SQLite memory DB. ``db_path`` is
kept only as a compatibility argument for older call sites; this store requires
the PostgreSQL ``DATABASE_URL`` configured by the M1/M2 runtime.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, json_loads, new_uuid, to_unix_seconds, utc_now, uuid_value
from core.user_context import DEFAULT_USER_ID
from core.workspace_paths import user_data_rel_prefix
from modules.evidence_workflow.task_profiles import build_scope_lock, resolve_task_profile

from .templates import get_template

_LIST_STATUS_HIDDEN = ("deleted",)


class WorkflowStore:
    def __init__(self, db_path: str | Path | None = None, engine: Engine | None = None) -> None:
        self.db_path = db_path
        self.engine = engine or create_engine_from_env()

    # ---- create -------------------------------------------------------------
    def create(
        self,
        template_id: str,
        *,
        topic: str | None,
        scope: str = "library",
        title: str | None = None,
        session_id: str | None = None,
        task_profile_id: str | None = None,
        scope_options: dict[str, Any] | None = None,
        user_id: str = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        template = get_template(template_id)
        if not template:
            raise ValueError(f"unknown template: {template_id}")

        workflow_id = new_uuid()
        user_id = _resolve_user_id(user_id, self.engine)
        owner = uuid_value(user_id)
        task_profile = resolve_task_profile(task_profile_id)
        ts = utc_now()
        steps = []
        for index, raw in enumerate(template["steps"]):
            params = dict(raw.get("params") or {})
            if raw["runner"] == "research-controller":
                plan_kind = params.get("controller_plan_kind") or raw["step_key"]
                task_id = f"wf_{workflow_id.replace('-', '')}_{plan_kind}"
                params.setdefault("controller_plan_kind", plan_kind)
                params.setdefault("controller_plan_id", f"{task_id}:workflow")
                params.setdefault("task_id", task_id)
                params.setdefault("user_id", user_id)
                params.setdefault("workspace_rel_path", f"{user_data_rel_prefix(user_id)}/research_agent/research_tasks/{task_id}")
            if raw["runner"] == "agent-step":
                params.setdefault("user_id", user_id)
                try:
                    from .step_defs import get_step_def

                    sdef = get_step_def(raw["step_key"])
                    if sdef and sdef.stages:
                        params.setdefault("stages", [{"stage": key, "label": label} for key, label in sdef.stages])
                except Exception:  # noqa: BLE001 - optional UI enrichment only
                    pass
            steps.append(
                {
                    "step_index": index,
                    "step_key": raw["step_key"],
                    "runner": raw["runner"],
                    "label": raw.get("label") or raw["step_key"],
                    "available": bool(raw.get("available")),
                    "note": raw.get("note") or "",
                    "params": params,
                }
            )

        manifest = {
            "template_id": template_id,
            "template_name": template["name"],
            "steps": steps,
            "task_profile_id": task_profile.profile_id,
            "task_profile": task_profile.as_dict(),
            "user_id": user_id,
            "scope_lock": build_scope_lock(topic, scope, scope_options, task_profile.profile_id, to_unix_seconds(ts) or 0.0),
        }
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into workflow_runs(
                        workflow_id, user_id, template_id, title, topic, scope, status,
                        manifest_json, engine_ref_json, session_id, created_at, updated_at
                    ) values(
                        :workflow_id, :user_id, :template_id, :title, :topic, :scope, 'draft',
                        cast(:manifest_json as jsonb), '{}'::jsonb, :session_id, :ts, :ts
                    )
                    """
                ),
                {
                    "workflow_id": uuid_value(workflow_id),
                    "user_id": owner,
                    "template_id": template_id,
                    "title": title or template["name"],
                    "topic": topic,
                    "scope": scope,
                    "manifest_json": json_dumps(manifest),
                    "session_id": uuid_value(session_id) if session_id else None,
                    "ts": ts,
                },
            )
            for step in steps:
                initial = "pending" if step["available"] else "unavailable"
                conn.execute(
                    text(
                        """
                        insert into workflow_steps(
                            workflow_id, step_index, step_key, runner, label, status, artifact_ids_json
                        ) values(
                            :workflow_id, :step_index, :step_key, :runner, :label, :status, '[]'::jsonb
                        )
                        """
                    ),
                    {
                        "workflow_id": uuid_value(workflow_id),
                        "step_index": step["step_index"],
                        "step_key": step["step_key"],
                        "runner": step["runner"],
                        "label": step["label"],
                        "status": initial,
                    },
                )
        return self.get(workflow_id, user_id=user_id)

    # ---- read ---------------------------------------------------------------
    def get(self, workflow_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        row = self._run_row_for_user(workflow_id, user_id)
        if not row:
            raise KeyError(f"workflow not found: {workflow_id}")
        return self._workflow_from_row(row)

    def list(self, *, limit: int = 50, user_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"hidden": list(_LIST_STATUS_HIDDEN), "limit": limit}
        clauses = ["status != all(:hidden)"]
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = uuid_value(user_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(f"select * from workflow_runs where {' and '.join(clauses)} order by updated_at desc limit :limit"),
                params,
            ).mappings().all()
        out = []
        for row in rows:
            manifest = json_loads(row["manifest_json"], {}) or {}
            out.append(
                {
                    "workflow_id": str(row["workflow_id"]),
                    "user_id": str(row["user_id"]),
                    "template_id": row["template_id"],
                    "template_name": manifest.get("template_name"),
                    "title": row["title"],
                    "topic": row["topic"],
                    "status": row["status"],
                    "task_profile_id": manifest.get("task_profile_id"),
                    "task_profile_name": (manifest.get("task_profile") or {}).get("name"),
                    "updated_at": to_unix_seconds(row["updated_at"]),
                    "created_at": to_unix_seconds(row["created_at"]),
                }
            )
        return out

    # ---- mutate -------------------------------------------------------------
    def update_status(
        self,
        workflow_id: str,
        status: str,
        *,
        error: str | None = None,
        started_at: Any | None = None,
        ended_at: Any | None = None,
    ) -> None:
        changes: dict[str, Any] = {"status": status}
        if error is not None:
            changes["error"] = error
        if started_at is not None:
            changes["started_at"] = _db_time(started_at)
        if ended_at is not None:
            changes["ended_at"] = _db_time(ended_at)
        self._update_run(workflow_id, **changes)

    def set_engine_ref(self, workflow_id: str, **values: Any) -> None:
        row = self._run_row_for_user(workflow_id, None)
        if not row:
            raise KeyError(f"workflow not found: {workflow_id}")
        ref = json_loads(row["engine_ref_json"], {}) or {}
        ref.update({k: v for k, v in values.items() if v is not None})
        self._update_run(workflow_id, engine_ref_json=json_dumps(ref))

    def update_step(self, workflow_id: str, step_index: int, **changes: Any) -> None:
        if "artifact_ids" in changes:
            changes["artifact_ids_json"] = json_dumps(changes.pop("artifact_ids"))
        for key in ("started_at", "ended_at"):
            if key in changes and changes[key] is not None:
                changes[key] = _db_time(changes[key])
        if "job_id" in changes and changes["job_id"]:
            changes["job_id"] = uuid_value(changes["job_id"])
        if not changes:
            return
        assignments = []
        params: dict[str, Any] = {
            "workflow_id": uuid_value(workflow_id),
            "step_index": step_index,
            "updated_at": utc_now(),
        }
        for key, value in changes.items():
            if key == "artifact_ids_json":
                assignments.append(f"{key} = cast(:{key} as jsonb)")
            else:
                assignments.append(f"{key} = :{key}")
            params[key] = value
        with self.engine.begin() as conn:
            cur = conn.execute(
                text(
                    f"""
                    update workflow_steps set {', '.join(assignments)}
                    where workflow_id = :workflow_id and step_index = :step_index
                    """
                ),
                params,
            )
            if cur.rowcount == 0:
                raise KeyError(f"workflow step not found: {workflow_id}:{step_index}")
            conn.execute(text("update workflow_runs set updated_at = :updated_at where workflow_id = :workflow_id"), params)

    def soft_delete(self, workflow_id: str, *, user_id: str | None = None) -> None:
        self.get(workflow_id, user_id=user_id)
        self._update_run(workflow_id, status="deleted", deleted_at=utc_now())

    def _update_run(self, workflow_id: str, **changes: Any) -> None:
        changes["updated_at"] = utc_now()
        params: dict[str, Any] = {"workflow_id": uuid_value(workflow_id)}
        assignments = []
        for key, value in changes.items():
            if key in {"manifest_json", "engine_ref_json"}:
                assignments.append(f"{key} = cast(:{key} as jsonb)")
            else:
                assignments.append(f"{key} = :{key}")
            params[key] = value
        with self.engine.begin() as conn:
            cur = conn.execute(text(f"update workflow_runs set {', '.join(assignments)} where workflow_id = :workflow_id"), params)
            if cur.rowcount == 0:
                raise KeyError(f"workflow not found: {workflow_id}")

    def _run_row_for_user(self, workflow_id: str, user_id: str | None):
        try:
            workflow_uuid = uuid_value(workflow_id)
            owner = uuid_value(user_id) if user_id is not None else None
        except ValueError:
            return None
        with self.engine.connect() as conn:
            if owner is None:
                return conn.execute(
                    text("select * from workflow_runs where workflow_id = :workflow_id"),
                    {"workflow_id": workflow_uuid},
                ).mappings().first()
            return conn.execute(
                text("select * from workflow_runs where workflow_id = :workflow_id and user_id = :user_id"),
                {"workflow_id": workflow_uuid, "user_id": owner},
            ).mappings().first()

    def _workflow_from_row(self, row) -> dict[str, Any]:
        manifest = json_loads(row["manifest_json"], {}) or {}
        by_index = {s.get("step_index"): s for s in manifest.get("steps", [])}
        with self.engine.connect() as conn:
            step_rows = conn.execute(
                text("select * from workflow_steps where workflow_id = :workflow_id order by step_index"),
                {"workflow_id": row["workflow_id"]},
            ).mappings().all()
        steps = []
        for s in step_rows:
            spec = by_index.get(s["step_index"], {})
            steps.append(
                {
                    "step_index": s["step_index"],
                    "step_key": s["step_key"],
                    "runner": s["runner"],
                    "label": s["label"],
                    "status": s["status"],
                    "available": bool(spec.get("available")),
                    "note": spec.get("note") or "",
                    "job_id": str(s["job_id"]) if s["job_id"] else None,
                    "artifact_ids": json_loads(s["artifact_ids_json"], []) or [],
                    "error": s["error"],
                    "params": spec.get("params") or {},
                    "started_at": to_unix_seconds(s["started_at"]),
                    "ended_at": to_unix_seconds(s["ended_at"]),
                }
            )
        return {
            "workflow_id": str(row["workflow_id"]),
            "user_id": str(row["user_id"]),
            "template_id": row["template_id"],
            "title": row["title"],
            "topic": row["topic"],
            "scope": row["scope"],
            "status": row["status"],
            "manifest": manifest,
            "task_profile_id": manifest.get("task_profile_id"),
            "task_profile": manifest.get("task_profile"),
            "scope_lock": manifest.get("scope_lock"),
            "engine_ref": json_loads(row["engine_ref_json"], {}) or {},
            "session_id": str(row["session_id"]) if row["session_id"] else None,
            "error": row["error"],
            "steps": steps,
            "created_at": to_unix_seconds(row["created_at"]),
            "updated_at": to_unix_seconds(row["updated_at"]),
            "started_at": to_unix_seconds(row["started_at"]),
            "ended_at": to_unix_seconds(row["ended_at"]),
        }


def _db_time(value: Any) -> Any:
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return value


def _resolve_user_id(user_id: str | None, engine: Engine) -> str:
    if user_id:
        try:
            return str(uuid_value(user_id))
        except ValueError:
            pass
    from core.user_store import UserStore

    return UserStore(engine=engine).ensure_local_user()["user_id"]
