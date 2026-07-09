"""Artifact-first storage for durable research task workspaces."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .schemas import (
    ARTIFACT_MANIFEST_REL_PATH,
    PLAN_FILENAME,
    STATE_FILENAME,
    STANDARD_WORKSPACE_DIRS,
    TASK_FILENAME,
    ArtifactManifest,
    ResearchTaskState,
    ResearchTaskWorkspace,
)

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class ResearchWorkspaceStore:
    """Create and read file-based research task workspaces."""

    def __init__(self, data_dir: str | Path, root_rel: str = "research_agent/research_tasks"):
        self.data_dir = Path(data_dir)
        self.root_rel = _normalize_root_rel(root_rel)
        self.root = self.data_dir / self.root_rel

    def create_workspace(
        self,
        task_id: str,
        task_markdown: str | None = None,
        plan_markdown: str | None = None,
        state: ResearchTaskState | dict[str, Any] | None = None,
    ) -> ResearchTaskWorkspace:
        safe_task_id = self._validate_task_id(task_id)
        workspace_path = self._workspace_path(safe_task_id)
        now = time.time()

        for dirname in STANDARD_WORKSPACE_DIRS:
            self.resolve_workspace_path(safe_task_id, dirname).mkdir(parents=True, exist_ok=True)

        self._write_text_atomic(workspace_path / TASK_FILENAME, task_markdown or "")
        self._write_text_atomic(workspace_path / PLAN_FILENAME, plan_markdown or "")

        state_dict = self._state_to_dict(state, safe_task_id, now)
        self._write_json_atomic(workspace_path / STATE_FILENAME, state_dict)

        artifact_manifest = ArtifactManifest(task_id=safe_task_id).as_dict()
        self._write_json_atomic(workspace_path / ARTIFACT_MANIFEST_REL_PATH, artifact_manifest)

        return ResearchTaskWorkspace(
            task_id=safe_task_id,
            root_rel=self.root_rel,
            workspace_rel_path=f"{self.root_rel}/{safe_task_id}",
            created_at=state_dict.get("created_at", now),
            updated_at=state_dict.get("updated_at", now),
        )

    def write_task(self, task_id: str, markdown: str) -> str:
        path = self.resolve_workspace_path(task_id, TASK_FILENAME)
        self._write_text_atomic(path, markdown)
        return markdown

    def read_task(self, task_id: str) -> str:
        path = self.resolve_workspace_path(task_id, TASK_FILENAME)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return path.read_text(encoding="utf-8")

    def write_plan(self, task_id: str, markdown: str) -> str:
        path = self.resolve_workspace_path(task_id, PLAN_FILENAME)
        self._write_text_atomic(path, markdown)
        return markdown

    def read_plan(self, task_id: str) -> str:
        path = self.resolve_workspace_path(task_id, PLAN_FILENAME)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return path.read_text(encoding="utf-8")

    def write_state(self, task_id: str, state: ResearchTaskState | dict[str, Any]) -> dict[str, Any]:
        safe_task_id = self._validate_task_id(task_id)
        state_dict = self._state_to_dict(state, safe_task_id, time.time())
        path = self.resolve_workspace_path(safe_task_id, STATE_FILENAME)
        self._write_json_atomic(path, state_dict)
        return state_dict

    def read_state(self, task_id: str) -> dict[str, Any]:
        path = self.resolve_workspace_path(task_id, STATE_FILENAME)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return json.loads(path.read_text(encoding="utf-8"))

    def read_artifact_manifest(self, task_id: str) -> dict[str, Any]:
        path = self.resolve_workspace_path(task_id, ARTIFACT_MANIFEST_REL_PATH)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return json.loads(path.read_text(encoding="utf-8"))

    def resolve_workspace_path(self, task_id: str, relative_path: str | Path = "") -> Path:
        safe_task_id = self._validate_task_id(task_id)
        rel_path = Path(relative_path)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"invalid workspace relative path: {relative_path!r}")

        workspace_root = self._workspace_path(safe_task_id)
        candidate = workspace_root / rel_path
        resolved_root = workspace_root.resolve()
        resolved_candidate = candidate.resolve()
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"path escapes workspace: {relative_path!r}") from exc
        return candidate

    def _workspace_path(self, task_id: str) -> Path:
        return self.root / task_id

    def _validate_task_id(self, task_id: str) -> str:
        if not isinstance(task_id, str):
            raise ValueError("task_id must be a string")
        task_id = task_id.strip()
        if (
            not task_id
            or task_id == ".."
            or ".." in task_id
            or "/" in task_id
            or "\\" in task_id
            or not _TASK_ID_RE.match(task_id)
        ):
            raise ValueError(f"invalid task_id: {task_id!r}")
        return task_id

    @staticmethod
    def _state_to_dict(
        state: ResearchTaskState | dict[str, Any] | None,
        task_id: str,
        now: float,
    ) -> dict[str, Any]:
        if state is None:
            state_dict = ResearchTaskState(task_id=task_id, created_at=now, updated_at=now).as_dict()
        elif hasattr(state, "as_dict"):
            state_dict = state.as_dict()
        elif isinstance(state, dict):
            state_dict = dict(state)
        else:
            raise TypeError("state must be a ResearchTaskState, dict, or None")

        if state_dict.get("task_id") != task_id:
            raise ValueError("state.task_id must match workspace task_id")

        state_dict.setdefault("status", "initialized")
        state_dict.setdefault("current_phase", "workspace")
        state_dict.setdefault("completed_steps", [])
        state_dict.setdefault("pending_steps", [])
        state_dict.setdefault("artifact_index", {})
        state_dict.setdefault("warnings", [])
        state_dict.setdefault("blockers", [])
        state_dict.setdefault("created_at", now)
        state_dict["updated_at"] = now
        return state_dict

    @staticmethod
    def _write_text_atomic(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(str(text or ""), encoding="utf-8")
        tmp_path.replace(path)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(path)


def _normalize_root_rel(root_rel: str) -> str:
    stripped = root_rel.strip()
    if Path(stripped).is_absolute():
        raise ValueError(f"invalid root_rel: {root_rel!r}")
    normalized = stripped.strip("/")
    if not normalized or ".." in Path(normalized).parts:
        raise ValueError(f"invalid root_rel: {root_rel!r}")
    return normalized


__all__ = ["ResearchWorkspaceStore"]
