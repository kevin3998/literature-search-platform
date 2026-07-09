"""Artifact-first storage for evidence workflow cards.

M2 persists Evidence Cards as workflow-scoped JSON artifacts only. It does not
reconstruct dataclasses, emit job events, or touch database-backed state.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ARTIFACT_FILENAME = "evidence_cards.json"
_MINIMAL_REPORT_MD = "minimal_topic_to_evidence_report.md"
_MINIMAL_REPORT_JSON = "minimal_topic_to_evidence_report.json"
_EVIDENCE_SELECTION_JSON = "evidence_selection.json"


class EvidenceCardStore:
    """Save and read Evidence Card artifacts under a workflow directory."""

    def __init__(self, data_dir: str | Path, root_rel: str = "research_agent/evidence_workflows"):
        self.data_dir = Path(data_dir)
        self.root_rel = _normalize_root_rel(root_rel)
        self.root = self.data_dir / self.root_rel

    def save_cards(
        self,
        workflow_id: str,
        cards: list[Any],
        schema_version: str = "m1",
        extraction_version: str = "not_started",
        source: str = "m2_store",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        artifact_path = self._artifact_path(safe_workflow_id)
        card_dicts = [self._card_to_dict(card) for card in cards]
        now = time.time()
        created_at = now

        if artifact_path.exists():
            try:
                created_at = self.load_cards(safe_workflow_id).get("created_at", now)
            except (FileNotFoundError, json.JSONDecodeError):
                created_at = now

        manifest: dict[str, Any] = {
            "artifact_type": "evidence_cards",
            "schema_version": schema_version,
            "extraction_version": extraction_version,
            "workflow_id": safe_workflow_id,
            "card_count": len(card_dicts),
            "cards": card_dicts,
            "source": source,
            "metadata": dict(metadata or {}),
            "created_at": created_at,
            "updated_at": now,
        }

        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = artifact_path.with_name(f"{artifact_path.name}.tmp")
        tmp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(artifact_path)
        return manifest

    def load_cards(self, workflow_id: str) -> dict[str, Any]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        artifact_path = self._artifact_path(safe_workflow_id)
        if not artifact_path.exists():
            raise FileNotFoundError(str(artifact_path))
        return json.loads(artifact_path.read_text(encoding="utf-8"))

    def list_card_artifacts(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        if workflow_id is not None:
            safe_workflow_id = self._validate_workflow_id(workflow_id)
            artifact_path = self._artifact_path(safe_workflow_id)
            return [self._summary_from_path(artifact_path)] if artifact_path.exists() else []

        if not self.root.exists():
            return []

        summaries = [
            self._summary_from_path(path)
            for path in self.root.glob(f"*/{_ARTIFACT_FILENAME}")
            if self._is_safe_existing_workflow_dir(path.parent.name)
        ]
        return sorted(summaries, key=lambda item: (item.get("workflow_id") or ""))

    def artifact_event(self, workflow_id: str, label: str = "Evidence Cards") -> dict[str, str]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        rel_path = self._rel_artifact_path(safe_workflow_id)
        return {
            "type": "artifact",
            "artifact_type": "evidence_cards",
            "artifact_id": rel_path,
            "path": rel_path,
            "label": label,
        }

    def save_minimal_report(
        self,
        workflow_id: str,
        markdown: str,
        manifest: dict[str, Any],
        label: str = "Minimal Topic-to-Evidence Report",
    ) -> dict[str, Any]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        md_path = self._minimal_report_md_path(safe_workflow_id)
        json_path = self._minimal_report_json_path(safe_workflow_id)
        now = time.time()
        created_at = now
        if json_path.exists():
            try:
                created_at = self.load_minimal_report(safe_workflow_id)["manifest"].get("created_at", now)
            except (FileNotFoundError, json.JSONDecodeError):
                created_at = now

        report_manifest = dict(manifest or {})
        report_manifest.update(
            {
                "artifact_type": "minimal_topic_to_evidence_report",
                "workflow_id": safe_workflow_id,
                "label": label,
                "md_path": self._rel_minimal_report_md_path(safe_workflow_id),
                "json_path": self._rel_minimal_report_json_path(safe_workflow_id),
                "evidence_card_ids": [
                    card.get("evidence_id")
                    for card in report_manifest.get("evidence_cards", [])
                    if card.get("evidence_id")
                ],
                "created_at": created_at,
                "updated_at": now,
            }
        )

        md_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_md = md_path.with_name(f"{md_path.name}.tmp")
        tmp_json = json_path.with_name(f"{json_path.name}.tmp")
        tmp_md.write_text(str(markdown or ""), encoding="utf-8")
        tmp_json.write_text(
            json.dumps(report_manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_md.replace(md_path)
        tmp_json.replace(json_path)
        return report_manifest

    def load_minimal_report(self, workflow_id: str) -> dict[str, Any]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        md_path = self._minimal_report_md_path(safe_workflow_id)
        json_path = self._minimal_report_json_path(safe_workflow_id)
        if not md_path.exists():
            raise FileNotFoundError(str(md_path))
        if not json_path.exists():
            raise FileNotFoundError(str(json_path))
        return {
            "markdown": md_path.read_text(encoding="utf-8"),
            "manifest": json.loads(json_path.read_text(encoding="utf-8")),
        }

    def minimal_report_event(
        self,
        workflow_id: str,
        label: str = "Minimal Topic-to-Evidence Report",
    ) -> dict[str, str]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        rel_path = self._rel_minimal_report_md_path(safe_workflow_id)
        return {
            "type": "artifact",
            "artifact_type": "minimal_topic_to_evidence_report",
            "artifact_id": rel_path,
            "path": rel_path,
            "label": label,
        }

    def save_evidence_selection(
        self,
        workflow_id: str,
        result_dict: dict[str, Any],
        label: str = "Evidence Selection",
    ) -> dict[str, Any]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        json_path = self._evidence_selection_path(safe_workflow_id)
        now = time.time()
        created_at = now
        if json_path.exists():
            try:
                created_at = self.load_evidence_selection(safe_workflow_id).get("created_at", now)
            except (FileNotFoundError, json.JSONDecodeError):
                created_at = now

        manifest = dict(result_dict or {})
        manifest.update(
            {
                "artifact_type": "evidence_selection",
                "workflow_id": safe_workflow_id,
                "label": label,
                "json_path": self._rel_evidence_selection_path(safe_workflow_id),
                "created_at": created_at,
                "updated_at": now,
            }
        )

        json_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_json = json_path.with_name(f"{json_path.name}.tmp")
        tmp_json.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_json.replace(json_path)
        return manifest

    def load_evidence_selection(self, workflow_id: str) -> dict[str, Any]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        json_path = self._evidence_selection_path(safe_workflow_id)
        if not json_path.exists():
            raise FileNotFoundError(str(json_path))
        return json.loads(json_path.read_text(encoding="utf-8"))

    def evidence_selection_event(
        self,
        workflow_id: str,
        label: str = "Evidence Selection",
    ) -> dict[str, str]:
        safe_workflow_id = self._validate_workflow_id(workflow_id)
        rel_path = self._rel_evidence_selection_path(safe_workflow_id)
        return {
            "type": "artifact",
            "artifact_type": "evidence_selection",
            "artifact_id": rel_path,
            "path": rel_path,
            "label": label,
        }

    def _summary_from_path(self, artifact_path: Path) -> dict[str, Any]:
        manifest = json.loads(artifact_path.read_text(encoding="utf-8"))
        workflow_id = self._validate_workflow_id(artifact_path.parent.name)
        rel_path = self._rel_artifact_path(workflow_id)
        return {
            "artifact_type": "evidence_cards",
            "artifact_id": rel_path,
            "path": rel_path,
            "json_path": rel_path,
            "workflow_id": workflow_id,
            "schema_version": manifest.get("schema_version"),
            "extraction_version": manifest.get("extraction_version"),
            "card_count": manifest.get("card_count", 0),
            "created_at": manifest.get("created_at"),
            "updated_at": manifest.get("updated_at"),
        }

    def _artifact_path(self, workflow_id: str) -> Path:
        return self.root / workflow_id / _ARTIFACT_FILENAME

    def _rel_artifact_path(self, workflow_id: str) -> str:
        return f"{self.root_rel}/{workflow_id}/{_ARTIFACT_FILENAME}"

    def _minimal_report_md_path(self, workflow_id: str) -> Path:
        return self.root / workflow_id / _MINIMAL_REPORT_MD

    def _minimal_report_json_path(self, workflow_id: str) -> Path:
        return self.root / workflow_id / _MINIMAL_REPORT_JSON

    def _rel_minimal_report_md_path(self, workflow_id: str) -> str:
        return f"{self.root_rel}/{workflow_id}/{_MINIMAL_REPORT_MD}"

    def _rel_minimal_report_json_path(self, workflow_id: str) -> str:
        return f"{self.root_rel}/{workflow_id}/{_MINIMAL_REPORT_JSON}"

    def _evidence_selection_path(self, workflow_id: str) -> Path:
        return self.root / workflow_id / _EVIDENCE_SELECTION_JSON

    def _rel_evidence_selection_path(self, workflow_id: str) -> str:
        return f"{self.root_rel}/{workflow_id}/{_EVIDENCE_SELECTION_JSON}"

    def _validate_workflow_id(self, workflow_id: str) -> str:
        if not isinstance(workflow_id, str):
            raise ValueError("workflow_id must be a string")
        workflow_id = workflow_id.strip()
        if (
            not workflow_id
            or workflow_id == ".."
            or ".." in workflow_id
            or "/" in workflow_id
            or "\\" in workflow_id
            or not _WORKFLOW_ID_RE.match(workflow_id)
        ):
            raise ValueError(f"invalid workflow_id: {workflow_id!r}")
        return workflow_id

    def _is_safe_existing_workflow_dir(self, workflow_id: str) -> bool:
        try:
            self._validate_workflow_id(workflow_id)
        except ValueError:
            return False
        return True

    @staticmethod
    def _card_to_dict(card: Any) -> dict[str, Any]:
        if hasattr(card, "as_dict"):
            card = card.as_dict()
        if not isinstance(card, dict):
            raise TypeError("cards must be dicts or objects with as_dict()")
        return card


def _normalize_root_rel(root_rel: str) -> str:
    normalized = root_rel.strip().strip("/")
    if not normalized or Path(normalized).is_absolute() or ".." in Path(normalized).parts:
        raise ValueError(f"invalid root_rel: {root_rel!r}")
    return normalized


__all__ = ["EvidenceCardStore"]
