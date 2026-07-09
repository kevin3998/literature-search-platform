"""Durable research workspace contracts.

A1 keeps these schemas internal and file-oriented. They intentionally do not
model controller execution, tool registries, retrieval, evidence extraction, or
database-backed state.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


STANDARD_WORKSPACE_DIRS = (
    "retrieval",
    "evidence",
    "ranked_evidence",
    "landscape",
    "gaps",
    "ideas",
    "screening",
    "reports",
    "experiments",
    "claim_ledger",
    "manuscript",
    "logs",
    "audit",
)

TASK_FILENAME = "task.md"
PLAN_FILENAME = "plan.md"
STATE_FILENAME = "state.json"
ARTIFACT_MANIFEST_REL_PATH = "audit/artifact_manifest.json"


@dataclass
class ResearchTaskWorkspace:
    task_id: str
    root_rel: str
    workspace_rel_path: str
    standard_dirs: list[str] = field(default_factory=lambda: list(STANDARD_WORKSPACE_DIRS))
    task_path: str = TASK_FILENAME
    plan_path: str = PLAN_FILENAME
    state_path: str = STATE_FILENAME
    artifact_manifest_path: str = ARTIFACT_MANIFEST_REL_PATH
    cli_controller_ready: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchTaskState:
    task_id: str
    status: str = "initialized"
    current_phase: str = "workspace"
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    artifact_index: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactRecord:
    artifact_id: str
    artifact_type: str
    path: str
    created_at: float = field(default_factory=time.time)
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactManifest:
    task_id: str
    artifacts: list[ArtifactRecord | dict[str, Any]] = field(default_factory=list)
    cli_controller_ready: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "artifacts": [
                artifact.as_dict() if hasattr(artifact, "as_dict") else dict(artifact)
                for artifact in self.artifacts
            ],
            "cli_controller_ready": self.cli_controller_ready,
        }


@dataclass
class ResearchWorkspaceManifest:
    task_id: str
    workspace_rel_path: str
    artifact_manifest_path: str = ARTIFACT_MANIFEST_REL_PATH
    cli_controller_ready: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
