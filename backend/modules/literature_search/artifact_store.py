from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ARTIFACT_DIRS = {
    "pack": "packs",
    "task": "tasks",
    "extraction": "extractions",
    "comparison": "comparisons",
    "analysis_bundle": "analysis_bundles",
    "verification": "verifications",
    "notes": "notes",
    "synthesis": "syntheses",
    "quality": "quality",
}


class ArtifactStore:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.agent_dir = self.data_dir / "research_agent"

    def list_artifacts(self) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for artifact_type, dirname in ARTIFACT_DIRS.items():
            directory = self.agent_dir / dirname
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                artifacts.append(self._summary(path, artifact_type))
        artifacts.extend(self._run_stage_artifacts())
        return sorted(artifacts, key=lambda item: item.get("_mtime", 0), reverse=True)

    def read_artifact(self, artifact_id: str) -> dict[str, Any]:
        for item in self.list_artifacts():
            if item["artifact_id"] != artifact_id:
                continue
            json_path = self._resolve_rel(item.get("json_path"))
            markdown_path = self._resolve_rel(item.get("markdown_path"))
            content = _read_json(json_path) if json_path and json_path.exists() else {}
            markdown = markdown_path.read_text(encoding="utf-8") if markdown_path and markdown_path.exists() else ""
            return {**{k: v for k, v in item.items() if not k.startswith("_")}, "content": content, "markdown": markdown}
        raise KeyError(f"artifact not found: {artifact_id}")

    def _summary(self, path: Path, artifact_type: str) -> dict[str, Any]:
        content = _read_json(path)
        markdown = path.with_suffix(".md")
        rel_json = self._rel(path)
        rel_markdown = self._rel(markdown) if markdown.exists() else None
        title = (
            content.get("question")
            or content.get("query")
            or content.get("title")
            or content.get("bundle_id")
            or content.get("task_id")
            or content.get("run_id")
            or path.stem
        )
        created_at = content.get("created_at") or content.get("updated_at")
        return {
            "artifact_id": f"{artifact_type}:{path.stem}",
            "artifact_type": artifact_type,
            "title": str(title)[:160],
            "json_path": rel_json,
            "markdown_path": rel_markdown,
            "created_at": created_at,
            "summary": _small_summary(content),
            "_mtime": path.stat().st_mtime,
        }

    def _run_stage_artifacts(self) -> list[dict[str, Any]]:
        runs = self.agent_dir / "runs"
        if not runs.exists():
            return []
        artifacts: list[dict[str, Any]] = []
        for run_dir in runs.glob("run-*"):
            stages = run_dir / "stages"
            if not stages.exists():
                continue
            for path in sorted(stages.glob("*.json")):
                content = _read_json(path)
                run_id = run_dir.name
                stage = path.stem
                artifacts.append(
                    {
                        "artifact_id": f"run_stage:{run_id}:{stage}",
                        "artifact_type": "run_stage",
                        "title": f"{run_id} / {stage}",
                        "json_path": self._rel(path),
                        "markdown_path": None,
                        "created_at": content.get("created_at") or content.get("updated_at"),
                        "summary": _small_summary(content),
                        "_mtime": path.stat().st_mtime,
                    }
                )
        return artifacts

    def _rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.data_dir.resolve()))

    def _resolve_rel(self, rel: str | None) -> Path | None:
        if not rel:
            return None
        path = self.data_dir / rel
        resolved = path.resolve()
        resolved.relative_to(self.data_dir.resolve())
        return resolved


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _small_summary(content: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "task_type",
        "scope",
        "run_id",
        "task_id",
        "bundle_id",
        "readiness",
        "evidence_assessment",
        "record_summary",
        "evidence_summary",
    )
    return {key: content[key] for key in keys if key in content}
