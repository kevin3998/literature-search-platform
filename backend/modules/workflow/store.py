"""WorkflowStore — SQLite CRUD over workflow_runs / workflow_steps.

Pure persistence: no service/runner imports (the router/orchestrator enrich
corpus-stage steps with live sub-stages). Mirrors JobStore's connection style.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from core.memory_db import connect, dumps, loads, now
from core.user_context import DEFAULT_USER_ID
from core.workspace_paths import user_data_rel_prefix
from modules.evidence_workflow.task_profiles import build_scope_lock, resolve_task_profile

from .templates import get_template

_LIST_STATUS_HIDDEN = ("deleted",)


class WorkflowStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path
        # Per-thread connection: the orchestrator daemon thread and the API/SSE
        # threads both touch this store; sharing one sqlite3.Connection across
        # threads raises "bad parameter or other API misuse". WAL handles it.
        self._local = threading.local()

    @property
    def conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.db_path)
            self._local.conn = conn
        return conn

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
        task_profile = resolve_task_profile(task_profile_id)
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        ts = now()
        steps = []
        for index, raw in enumerate(template["steps"]):
            params = dict(raw.get("params") or {})
            if raw["runner"] == "research-controller":
                plan_kind = params.get("controller_plan_kind") or raw["step_key"]
                task_id = f"{workflow_id}_{plan_kind}"
                params.setdefault("controller_plan_kind", plan_kind)
                params.setdefault("controller_plan_id", f"{task_id}:workflow")
                params.setdefault("task_id", task_id)
                params.setdefault("user_id", user_id)
                params.setdefault("workspace_rel_path", f"{user_data_rel_prefix(user_id)}/research_agent/research_tasks/{task_id}")
            if raw["runner"] == "agent-step":
                params.setdefault("user_id", user_id)
            if raw["runner"] == "agent-step":
                try:
                    from .step_defs import get_step_def

                    sdef = get_step_def(raw["step_key"])
                    if sdef and sdef.stages:
                        params.setdefault("stages", [{"stage": key, "label": label} for key, label in sdef.stages])
                except Exception:  # noqa: BLE001 - step params are an optional UI enrichment
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
            "scope_lock": build_scope_lock(topic, scope, scope_options, task_profile.profile_id, ts),
        }
        self.conn.execute(
            """
            insert into workflow_runs(
                workflow_id, user_id, template_id, title, topic, scope, status,
                manifest_json, engine_ref_json, session_id, created_at, updated_at
            ) values(?, ?, ?, ?, ?, ?, 'draft', ?, '{}', ?, ?, ?)
            """,
            (
                workflow_id,
                user_id,
                template_id,
                title or template["name"],
                topic,
                scope,
                dumps(manifest),
                session_id,
                ts,
                ts,
            ),
        )
        for step in steps:
            # agent-step / not-yet-built steps start as 'unavailable' (敬请期待);
            # the orchestrator never executes them and stops the run at the first one.
            initial = "pending" if step["available"] else "unavailable"
            self.conn.execute(
                """
                insert into workflow_steps(
                    workflow_id, step_index, step_key, runner, label, status
                ) values(?, ?, ?, ?, ?, ?)
                """,
                (workflow_id, step["step_index"], step["step_key"], step["runner"], step["label"], initial),
            )
        self.conn.commit()
        return self.get(workflow_id, user_id=user_id)

    # ---- read ---------------------------------------------------------------
    def get(self, workflow_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        row = self._run_row_for_user(workflow_id, user_id)
        if not row:
            raise KeyError(f"workflow not found: {workflow_id}")
        manifest = loads(row["manifest_json"], {}) or {}
        by_index = {s.get("step_index"): s for s in manifest.get("steps", [])}
        step_rows = self.conn.execute(
            "select * from workflow_steps where workflow_id = ? order by step_index",
            (workflow_id,),
        ).fetchall()
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
                    "job_id": s["job_id"],
                    "artifact_ids": loads(s["artifact_ids_json"], []) or [],
                    "error": s["error"],
                    "params": spec.get("params") or {},
                    "started_at": s["started_at"],
                    "ended_at": s["ended_at"],
                }
            )
        return {
            "workflow_id": row["workflow_id"],
            "user_id": row["user_id"],
            "template_id": row["template_id"],
            "title": row["title"],
            "topic": row["topic"],
            "scope": row["scope"],
            "status": row["status"],
            "manifest": manifest,
            "task_profile_id": manifest.get("task_profile_id"),
            "task_profile": manifest.get("task_profile"),
            "scope_lock": manifest.get("scope_lock"),
            "engine_ref": loads(row["engine_ref_json"], {}) or {},
            "session_id": row["session_id"],
            "error": row["error"],
            "steps": steps,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
        }

    def list(self, *, limit: int = 50, user_id: str | None = None) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in _LIST_STATUS_HIDDEN)
        params: list[Any] = [*_LIST_STATUS_HIDDEN]
        where = [f"status not in ({placeholders})"]
        if user_id is not None:
            where.append("user_id = ?")
            params.append(user_id)
        params.append(limit)
        rows = self.conn.execute(
            f"select * from workflow_runs where {' and '.join(where)} "
            "order by updated_at desc limit ?",
            params,
        ).fetchall()
        out = []
        for row in rows:
            manifest = loads(row["manifest_json"], {}) or {}
            out.append(
                {
                    "workflow_id": row["workflow_id"],
                    "user_id": row["user_id"],
                    "template_id": row["template_id"],
                    "template_name": manifest.get("template_name"),
                    "title": row["title"],
                    "topic": row["topic"],
                    "status": row["status"],
                    "task_profile_id": manifest.get("task_profile_id"),
                    "task_profile_name": (manifest.get("task_profile") or {}).get("name"),
                    "updated_at": row["updated_at"],
                    "created_at": row["created_at"],
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
        started_at: float | None = None,
        ended_at: float | None = None,
    ) -> None:
        changes: dict[str, Any] = {"status": status}
        if error is not None:
            changes["error"] = error
        if started_at is not None:
            changes["started_at"] = started_at
        if ended_at is not None:
            changes["ended_at"] = ended_at
        self._update_run(workflow_id, **changes)

    def set_engine_ref(self, workflow_id: str, **values: Any) -> None:
        row = self.conn.execute(
            "select engine_ref_json from workflow_runs where workflow_id = ?", (workflow_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"workflow not found: {workflow_id}")
        ref = loads(row["engine_ref_json"], {}) or {}
        ref.update({k: v for k, v in values.items() if v is not None})
        self._update_run(workflow_id, engine_ref_json=dumps(ref))

    def update_step(self, workflow_id: str, step_index: int, **changes: Any) -> None:
        if "artifact_ids" in changes:
            changes["artifact_ids_json"] = dumps(changes.pop("artifact_ids"))
        if not changes:
            return
        assignments = ", ".join(f"{k} = ?" for k in changes)
        params = [*changes.values(), workflow_id, step_index]
        self.conn.execute(
            f"update workflow_steps set {assignments} where workflow_id = ? and step_index = ?",
            params,
        )
        self.conn.execute(
            "update workflow_runs set updated_at = ? where workflow_id = ?", (now(), workflow_id)
        )
        self.conn.commit()

    def soft_delete(self, workflow_id: str, *, user_id: str | None = None) -> None:
        self.get(workflow_id, user_id=user_id)
        self._update_run(workflow_id, status="deleted", deleted_at=now())

    def _update_run(self, workflow_id: str, **changes: Any) -> None:
        changes["updated_at"] = now()
        assignments = ", ".join(f"{k} = ?" for k in changes)
        params = [*changes.values(), workflow_id]
        cur = self.conn.execute(
            f"update workflow_runs set {assignments} where workflow_id = ?", params
        )
        if cur.rowcount == 0:
            raise KeyError(f"workflow not found: {workflow_id}")
        self.conn.commit()

    def _run_row_for_user(self, workflow_id: str, user_id: str | None):
        if user_id is None:
            return self.conn.execute(
                "select * from workflow_runs where workflow_id = ?", (workflow_id,)
            ).fetchone()
        return self.conn.execute(
            "select * from workflow_runs where workflow_id = ? and user_id = ?",
            (workflow_id, user_id),
        ).fetchone()
