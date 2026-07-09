"""Artifact manifest and append-only audit utilities for research workspaces."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .schemas import ValidationStatus
from .skill_registry import SkillExecutionResult
from modules.research_workspace import ResearchWorkspaceStore

ArtifactValidationStatus = ValidationStatus

ARTIFACT_MANIFEST_PATH = "audit/artifact_manifest.json"
TOOL_CALLS_LOG = "logs/tool_calls.jsonl"
CONTROLLER_EVENTS_LOG = "logs/controller_events.jsonl"
VALIDATION_RESULTS_LOG = "logs/validation_results.jsonl"


class AuditEventType(str, Enum):
    TOOL_CALL = "tool_call"
    CONTROLLER_EVENT = "controller_event"
    VALIDATION_RESULT = "validation_result"


@dataclass
class ArtifactRecord:
    artifact_id: str
    artifact_type: str
    path: str
    created_by: str
    tool_version: str = ""
    input_artifacts: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    validation_status: ValidationStatus | str = ValidationStatus.NOT_VALIDATED
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validation_status = _coerce_validation_status(self.validation_status)
        self.input_artifacts = list(self.input_artifacts or [])
        self.warnings = list(self.warnings or [])
        self.metadata = dict(self.metadata or {})

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["validation_status"] = self.validation_status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRecord":
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            path=data["path"],
            created_by=data.get("created_by", ""),
            tool_version=data.get("tool_version", ""),
            input_artifacts=list(data.get("input_artifacts", [])),
            created_at=data.get("created_at", time.time()),
            validation_status=data.get("validation_status", ValidationStatus.NOT_VALIDATED.value),
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ArtifactManifest:
    task_id: str
    artifacts: list[ArtifactRecord | dict[str, Any]] = field(default_factory=list)
    cli_controller_ready: bool = False
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.artifacts = [
            artifact if isinstance(artifact, ArtifactRecord) else ArtifactRecord.from_dict(artifact)
            for artifact in self.artifacts
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "cli_controller_ready": self.cli_controller_ready,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactManifest":
        return cls(
            task_id=data["task_id"],
            artifacts=list(data.get("artifacts", [])),
            cli_controller_ready=bool(data.get("cli_controller_ready", False)),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class ToolCallAuditEvent:
    event_id: str
    task_id: str
    skill_name: str
    input_artifacts: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    status: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ControllerAuditEvent:
    event_id: str
    task_id: str
    event_type: AuditEventType | str
    decision_type: str | None = None
    target_step_id: str | None = None
    message: str = ""
    artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, AuditEventType):
            self.event_type = AuditEventType(self.event_type)
        self.artifacts = list(self.artifacts or [])
        self.warnings = list(self.warnings or [])
        self.errors = list(self.errors or [])
        self.metadata = dict(self.metadata or {})

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data


def load_artifact_manifest(workspace_root: str | Path, task_id: str) -> ArtifactManifest:
    path = _path(workspace_root, task_id, ARTIFACT_MANIFEST_PATH)
    if not path.exists():
        raise FileNotFoundError(str(path))
    return ArtifactManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_artifact_manifest(
    workspace_root: str | Path,
    manifest: ArtifactManifest | dict[str, Any],
    *,
    validate_paths: bool = True,
) -> ArtifactManifest:
    manifest_obj = manifest if isinstance(manifest, ArtifactManifest) else ArtifactManifest.from_dict(manifest)
    if validate_paths:
        for artifact in manifest_obj.artifacts:
            _validate_relative_artifact_path(workspace_root, manifest_obj.task_id, artifact.path)
    manifest_obj.updated_at = time.time()
    _write_json(_path(workspace_root, manifest_obj.task_id, ARTIFACT_MANIFEST_PATH), manifest_obj.as_dict())
    return manifest_obj


def register_artifact(
    workspace_root: str | Path,
    task_id: str,
    record: ArtifactRecord | dict[str, Any],
) -> ArtifactManifest:
    record_obj = record if isinstance(record, ArtifactRecord) else ArtifactRecord.from_dict(record)
    _validate_relative_artifact_path(workspace_root, task_id, record_obj.path)
    manifest = load_artifact_manifest(workspace_root, task_id)
    if find_artifact(manifest, record_obj.artifact_id) is not None:
        raise ValueError(f"duplicate artifact_id: {record_obj.artifact_id!r}")
    manifest.artifacts.append(record_obj)
    return save_artifact_manifest(workspace_root, manifest)


def update_artifact_validation_status(
    workspace_root: str | Path,
    task_id: str,
    artifact_id: str,
    validation_status: ValidationStatus | str,
    *,
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactManifest:
    manifest = load_artifact_manifest(workspace_root, task_id)
    record = find_artifact(manifest, artifact_id)
    if record is None:
        raise KeyError(f"unknown artifact_id: {artifact_id!r}")
    record.validation_status = _coerce_validation_status(validation_status)
    if warnings is not None:
        record.warnings = list(warnings)
    if metadata:
        record.metadata.update(metadata)
    return save_artifact_manifest(workspace_root, manifest)


def find_artifact(manifest: ArtifactManifest | dict[str, Any], artifact_id: str) -> ArtifactRecord | None:
    manifest_obj = manifest if isinstance(manifest, ArtifactManifest) else ArtifactManifest.from_dict(manifest)
    return next((artifact for artifact in manifest_obj.artifacts if artifact.artifact_id == artifact_id), None)


def list_artifacts_by_type(manifest: ArtifactManifest | dict[str, Any], artifact_type: str) -> list[ArtifactRecord]:
    manifest_obj = manifest if isinstance(manifest, ArtifactManifest) else ArtifactManifest.from_dict(manifest)
    return [artifact for artifact in manifest_obj.artifacts if artifact.artifact_type == artifact_type]


def append_tool_call_event(workspace_root: str | Path, event: ToolCallAuditEvent | dict[str, Any]) -> dict[str, Any]:
    data = event.as_dict() if hasattr(event, "as_dict") else dict(event)
    return _append_jsonl(workspace_root, data.get("task_id"), TOOL_CALLS_LOG, data)


def append_controller_event(workspace_root: str | Path, event: ControllerAuditEvent | dict[str, Any]) -> dict[str, Any]:
    data = event.as_dict() if hasattr(event, "as_dict") else dict(event)
    return _append_jsonl(workspace_root, data.get("task_id"), CONTROLLER_EVENTS_LOG, data)


def append_validation_result(workspace_root: str | Path, result: Any) -> dict[str, Any]:
    data = result.as_dict() if hasattr(result, "as_dict") else dict(result)
    task_id = data.get("task_id") or _task_id_from_workspace_root(workspace_root)
    return _append_jsonl(workspace_root, task_id, VALIDATION_RESULTS_LOG, data)


def read_jsonl_events(workspace_root: str | Path, relative_path: str) -> list[dict[str, Any]]:
    task_id = _task_id_from_workspace_root(workspace_root)
    path = _path(workspace_root, task_id, relative_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record_skill_execution_result(
    result: SkillExecutionResult | dict[str, Any],
    workspace_root: str | Path,
) -> ArtifactManifest:
    result_obj = result if isinstance(result, SkillExecutionResult) else SkillExecutionResult.from_dict(result)
    event = ToolCallAuditEvent(
        event_id=f"{result_obj.skill_name}:{time.time()}",
        task_id=result_obj.task_id,
        skill_name=result_obj.skill_name,
        input_artifacts=result_obj.input_artifacts,
        output_artifacts=result_obj.output_artifacts,
        status=result_obj.status.value,
        warnings=result_obj.warnings,
        errors=result_obj.errors,
        metadata=result_obj.metadata,
    )
    append_tool_call_event(workspace_root, event)
    manifest = load_artifact_manifest(workspace_root, result_obj.task_id)
    for output_path in result_obj.output_artifacts:
        artifact_id = f"{result_obj.skill_name}:{output_path}"
        if find_artifact(manifest, artifact_id) is not None:
            continue
        record = ArtifactRecord(
            artifact_id=artifact_id,
            artifact_type=Path(output_path).stem,
            path=output_path,
            created_by=result_obj.skill_name,
            input_artifacts=result_obj.input_artifacts,
            validation_status=ValidationStatus.NOT_VALIDATED,
            warnings=result_obj.warnings,
            metadata=result_obj.metadata,
        )
        _validate_relative_artifact_path(workspace_root, result_obj.task_id, output_path)
        manifest.artifacts.append(record)
    return save_artifact_manifest(workspace_root, manifest)


def _append_jsonl(workspace_root: str | Path, task_id: str, relative_path: str, data: dict[str, Any]) -> dict[str, Any]:
    path = _path(workspace_root, task_id, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _path(workspace_root: str | Path, task_id: str, relative_path: str) -> Path:
    return _store(workspace_root, task_id).resolve_workspace_path(task_id, relative_path)


def _store(workspace_root: str | Path, task_id: str) -> ResearchWorkspaceStore:
    root = Path(workspace_root)
    if root.name != task_id:
        raise ValueError("workspace_root must point at the task workspace directory")
    return ResearchWorkspaceStore(root.parents[2])


def _task_id_from_workspace_root(workspace_root: str | Path) -> str:
    return Path(workspace_root).name


def _validate_relative_artifact_path(workspace_root: str | Path, task_id: str, artifact_path: str) -> None:
    _path(workspace_root, task_id, artifact_path)


def _coerce_validation_status(value: ValidationStatus | str) -> ValidationStatus:
    if isinstance(value, ValidationStatus):
        return value
    return ValidationStatus(value)


__all__ = [
    "ARTIFACT_MANIFEST_PATH",
    "CONTROLLER_EVENTS_LOG",
    "TOOL_CALLS_LOG",
    "VALIDATION_RESULTS_LOG",
    "ArtifactManifest",
    "ArtifactRecord",
    "ArtifactValidationStatus",
    "AuditEventType",
    "ControllerAuditEvent",
    "ToolCallAuditEvent",
    "append_controller_event",
    "append_tool_call_event",
    "append_validation_result",
    "find_artifact",
    "list_artifacts_by_type",
    "load_artifact_manifest",
    "read_jsonl_events",
    "record_skill_execution_result",
    "register_artifact",
    "save_artifact_manifest",
    "update_artifact_validation_status",
]
