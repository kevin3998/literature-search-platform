"""Artifact validation gates for research controller workspaces."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit import append_validation_result
from .schemas import ValidationStatus
from modules.research_workspace import ResearchWorkspaceStore

EVIDENCE_VALIDATION_PATH = "evidence/evidence_validation.json"
ARTIFACT_MANIFEST_VALIDATION_PATH = "audit/artifact_manifest_validation.json"
RANKING_SELECTION_VALIDATION_PATH = "ranked_evidence/evidence_selection_validation.json"


@dataclass
class ArtifactValidationResult:
    artifact_id: str
    artifact_type: str
    path: str
    validation_status: ValidationStatus | str
    validator_name: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    validated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not isinstance(self.validation_status, ValidationStatus):
            self.validation_status = ValidationStatus(self.validation_status)
        self.errors = list(self.errors or [])
        self.warnings = list(self.warnings or [])
        self.metadata = dict(self.metadata or {})

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["validation_status"] = self.validation_status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactValidationResult":
        return cls(
            artifact_id=data["artifact_id"],
            artifact_type=data["artifact_type"],
            path=data["path"],
            validation_status=data["validation_status"],
            validator_name=data["validator_name"],
            errors=list(data.get("errors", [])),
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
            validated_at=data.get("validated_at", time.time()),
        )


def validate_artifact_manifest(workspace_root: str | Path, task_id: str) -> ArtifactValidationResult:
    errors: list[str] = []
    manifest_path = "audit/artifact_manifest.json"
    try:
        manifest = _read_json(workspace_root, task_id, manifest_path)
    except FileNotFoundError:
        errors.append("manifest_missing")
        manifest = {}
    except json.JSONDecodeError:
        errors.append("manifest_not_parseable")
        manifest = {}

    artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict):
        errors.append("manifest_is_not_object")
        artifacts = []
    else:
        if manifest.get("task_id") != task_id:
            errors.append("task_id_mismatch")
        if not isinstance(artifacts, list):
            errors.append("artifacts_is_not_list")
            artifacts = []
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict):
                errors.append(f"artifact_record_is_not_object:{index}")
                continue
            path = artifact.get("path")
            if not path:
                errors.append(f"artifact_path_missing:{index}")
            else:
                try:
                    _path(workspace_root, task_id, path)
                except ValueError:
                    errors.append(f"artifact_path_escapes_workspace:{path}")
            status = artifact.get("validation_status", ValidationStatus.NOT_VALIDATED.value)
            try:
                ValidationStatus(status)
            except ValueError:
                errors.append(f"invalid_validation_status:{status}:{index}")

    result = ArtifactValidationResult(
        artifact_id="artifact_manifest",
        artifact_type="artifact_manifest",
        path=manifest_path,
        validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
        validator_name="artifact_manifest_gate",
        errors=errors,
        metadata={"artifact_count": len(artifacts or [])},
    )
    _write_validation(workspace_root, task_id, ARTIFACT_MANIFEST_VALIDATION_PATH, result)
    return result


def validate_evidence_card_artifact(
    workspace_root: str | Path,
    task_id: str,
    artifact_path: str,
    *,
    enriched: bool = False,
) -> ArtifactValidationResult:
    errors: list[str] = []
    try:
        payload = _read_json(workspace_root, task_id, artifact_path)
    except FileNotFoundError:
        payload = {}
        errors.append("artifact_missing")
    except json.JSONDecodeError:
        payload = {}
        errors.append("artifact_not_parseable")

    cards = _cards_from_payload(payload)
    if cards is None:
        cards = []
        errors.append("cards_list_missing")
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            errors.append(f"card_is_not_object:{index}")
            continue
        if not card.get("evidence_id"):
            errors.append(f"missing_evidence_id:{index}")
        if not (card.get("paper_id") or card.get("source_evidence_id")):
            errors.append(f"missing_provenance:{index}")
        source = card.get("source") or {}
        if not isinstance(source, dict) or not source.get("source_path"):
            errors.append(f"missing_source_path:{index}")
        if not isinstance(source, dict) or not source.get("asset_type"):
            errors.append(f"missing_source_asset_type:{index}")
        if not (card.get("verbatim_snippet") or card.get("normalized_statement")):
            errors.append(f"missing_statement:{index}")
        if enriched and not card.get("primary_role"):
            errors.append(f"missing_primary_role:{index}")

    result = ArtifactValidationResult(
        artifact_id=Path(artifact_path).stem,
        artifact_type="evidence_cards",
        path=artifact_path,
        validation_status=ValidationStatus.FAILED if errors else ValidationStatus.PASSED,
        validator_name="evidence_card_gate",
        errors=errors,
        metadata={"card_count": len(cards)},
    )
    _write_validation(workspace_root, task_id, EVIDENCE_VALIDATION_PATH, result)
    return result


def validate_ranking_selection_artifact(
    workspace_root: str | Path,
    task_id: str,
    artifact_path: str = "ranked_evidence/evidence_selection.json",
) -> ArtifactValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        payload = _read_json(workspace_root, task_id, artifact_path)
    except FileNotFoundError:
        payload = {}
        errors.append("artifact_missing")
    except json.JSONDecodeError:
        payload = {}
        errors.append("artifact_not_parseable")

    selected = payload.get("selected_cards") if isinstance(payload, dict) else None
    if not isinstance(selected, list):
        errors.append("selected_cards_missing")
        selected = []
    for index, item in enumerate(selected):
        if not isinstance(item, dict):
            errors.append(f"selected_item_is_not_object:{index}")
            continue
        if not item.get("evidence_id"):
            errors.append(f"missing_selected_evidence_id:{index}")

    ranked = payload.get("ranked_cards") if isinstance(payload, dict) else []
    if ranked:
        for index, item in enumerate(ranked):
            if not isinstance(item, dict):
                errors.append(f"ranked_item_is_not_object:{index}")
                continue
            if "score" not in item:
                errors.append(f"missing_rank_score:{index}")
            if "score_components" not in item:
                errors.append(f"missing_score_components:{index}")
    else:
        warnings.append("ranking_metadata_missing")

    warnings.extend(payload.get("warnings") or [] if isinstance(payload, dict) else [])
    status = ValidationStatus.FAILED if errors else (
        ValidationStatus.DEGRADED_WITH_WARNING if warnings else ValidationStatus.PASSED
    )
    result = ArtifactValidationResult(
        artifact_id=Path(artifact_path).stem,
        artifact_type="evidence_selection",
        path=artifact_path,
        validation_status=status,
        validator_name="ranking_selection_gate",
        errors=errors,
        warnings=list(dict.fromkeys(warnings)),
        metadata={"selected_count": len(selected), "ranked_count": len(ranked or [])},
    )
    _write_validation(workspace_root, task_id, RANKING_SELECTION_VALIDATION_PATH, result)
    return result


def validate_report_inputs(
    workspace_root: str | Path,
    task_id: str,
    input_artifacts: list[str],
) -> ArtifactValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    for artifact_path in input_artifacts:
        try:
            _path(workspace_root, task_id, artifact_path)
        except ValueError:
            errors.append(f"artifact_path_escapes_workspace:{artifact_path}")
            continue
        if artifact_path == "retrieval/source_candidate_packet.json" or artifact_path.startswith("retrieval/"):
            errors.append("raw_retrieval_candidates_not_allowed_for_report")

    if not input_artifacts:
        errors.append("report_inputs_missing")
    status = ValidationStatus.FAILED if errors else (
        ValidationStatus.DEGRADED_WITH_WARNING if warnings else ValidationStatus.PASSED
    )
    result = ArtifactValidationResult(
        artifact_id="report_inputs",
        artifact_type="report_inputs",
        path=",".join(input_artifacts),
        validation_status=status,
        validator_name="report_input_gate",
        errors=errors,
        warnings=warnings,
        metadata={"input_artifacts": list(input_artifacts)},
    )
    append_validation_result(workspace_root, result)
    return result


def _cards_from_payload(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("cards"), list):
        return payload["cards"]
    return None


def _write_validation(
    workspace_root: str | Path,
    task_id: str,
    relative_path: str,
    result: ArtifactValidationResult,
) -> None:
    path = _path(workspace_root, task_id, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)
    append_validation_result(workspace_root, result)


def _read_json(workspace_root: str | Path, task_id: str, relative_path: str) -> Any:
    return json.loads(_path(workspace_root, task_id, relative_path).read_text(encoding="utf-8"))


def _path(workspace_root: str | Path, task_id: str, relative_path: str) -> Path:
    return _store(workspace_root, task_id).resolve_workspace_path(task_id, relative_path)


def _store(workspace_root: str | Path, task_id: str) -> ResearchWorkspaceStore:
    root = Path(workspace_root)
    if root.name != task_id:
        raise ValueError("workspace_root must point at the task workspace directory")
    return ResearchWorkspaceStore(root.parents[2])


__all__ = [
    "ARTIFACT_MANIFEST_VALIDATION_PATH",
    "EVIDENCE_VALIDATION_PATH",
    "RANKING_SELECTION_VALIDATION_PATH",
    "ArtifactValidationResult",
    "validate_artifact_manifest",
    "validate_evidence_card_artifact",
    "validate_ranking_selection_artifact",
    "validate_report_inputs",
]
