"""Bounded CLI controller contract objects and validators.

A6 defines parseable controller decisions and policy checks only. It does not
run a controller loop, execute skills, write audit logs, or mutate workspace
state.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field as dataclass_field
from enum import Enum
from pathlib import Path
from typing import Any

from .audit import AuditEventType, ControllerAuditEvent
from .schemas import AgentDecisionType, ControllerDecision
from .skill_registry import SkillRegistry, SkillStatus, build_default_skill_registry

CLI_CONTROLLER_SCHEMA_VERSION = "cli_controller_contract_v1"


class CliViolationType(str, Enum):
    UNPARSEABLE_OUTPUT = "UNPARSEABLE_OUTPUT"
    UNKNOWN_DECISION_TYPE = "UNKNOWN_DECISION_TYPE"
    UNREGISTERED_SKILL = "UNREGISTERED_SKILL"
    DISALLOWED_READ_PATH = "DISALLOWED_READ_PATH"
    DISALLOWED_WRITE_PATH = "DISALLOWED_WRITE_PATH"
    RAW_RETRIEVAL_TO_REPORT = "RAW_RETRIEVAL_TO_REPORT"
    DATABASE_MUTATION_ATTEMPT = "DATABASE_MUTATION_ATTEMPT"
    SHELL_COMMAND_NOT_ALLOWED = "SHELL_COMMAND_NOT_ALLOWED"
    SCHEMA_MUTATION_ATTEMPT = "SCHEMA_MUTATION_ATTEMPT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_ARTIFACT_REFERENCE = "INVALID_ARTIFACT_REFERENCE"
    OUT_OF_SCOPE_SKILL = "OUT_OF_SCOPE_SKILL"


@dataclass
class CliContractViolation:
    violation_type: CliViolationType | str
    message: str
    field: str | None = None
    path: str | None = None
    skill_name: str | None = None
    metadata: dict[str, Any] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        self.violation_type = _coerce_enum(CliViolationType, self.violation_type, "violation_type")
        self.metadata = dict(self.metadata or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "violation_type": self.violation_type.value,
            "message": self.message,
            "field": self.field,
            "path": self.path,
            "skill_name": self.skill_name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliContractViolation":
        return cls(
            violation_type=data["violation_type"],
            message=data.get("message", ""),
            field=data.get("field"),
            path=data.get("path"),
            skill_name=data.get("skill_name"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class CliWriteIntent:
    path: str
    artifact_type: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliWriteIntent":
        return cls(
            path=data["path"],
            artifact_type=data.get("artifact_type", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class CliSkillRequest:
    skill_name: str
    input_artifacts: list[str] = dataclass_field(default_factory=list)
    output_artifacts: list[str] = dataclass_field(default_factory=list)
    parameters: dict[str, Any] = dataclass_field(default_factory=dict)
    reason: str = ""

    def __post_init__(self) -> None:
        self.input_artifacts = list(self.input_artifacts or [])
        self.output_artifacts = list(self.output_artifacts or [])
        self.parameters = dict(self.parameters or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "input_artifacts": list(self.input_artifacts),
            "output_artifacts": list(self.output_artifacts),
            "parameters": dict(self.parameters),
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliSkillRequest":
        return cls(
            skill_name=data["skill_name"],
            input_artifacts=list(data.get("input_artifacts", [])),
            output_artifacts=list(data.get("output_artifacts", [])),
            parameters=dict(data.get("parameters", {})),
            reason=data.get("reason", ""),
        )


@dataclass
class CliControllerDecision:
    decision_type: AgentDecisionType | str
    task_id: str
    target_step_id: str | None = None
    skill_request: CliSkillRequest | dict[str, Any] | None = None
    artifact_refs: list[str] = dataclass_field(default_factory=list)
    state_update_intent: dict[str, Any] = dataclass_field(default_factory=dict)
    plan_update_intent: dict[str, Any] = dataclass_field(default_factory=dict)
    reason: str = ""
    warnings: list[str] = dataclass_field(default_factory=list)

    def __post_init__(self) -> None:
        self.decision_type = _coerce_enum(AgentDecisionType, self.decision_type, "decision_type")
        if isinstance(self.skill_request, dict):
            self.skill_request = CliSkillRequest.from_dict(self.skill_request)
        self.artifact_refs = list(self.artifact_refs or [])
        self.state_update_intent = dict(self.state_update_intent or {})
        self.plan_update_intent = dict(self.plan_update_intent or {})
        self.warnings = list(self.warnings or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type.value,
            "task_id": self.task_id,
            "target_step_id": self.target_step_id,
            "skill_request": self.skill_request.as_dict() if self.skill_request else None,
            "artifact_refs": list(self.artifact_refs),
            "state_update_intent": dict(self.state_update_intent),
            "plan_update_intent": dict(self.plan_update_intent),
            "reason": self.reason,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, task_id: str | None = None) -> "CliControllerDecision":
        return cls(
            decision_type=data["decision_type"],
            task_id=data.get("task_id") or task_id,
            target_step_id=data.get("target_step_id"),
            skill_request=data.get("skill_request"),
            artifact_refs=list(data.get("artifact_refs", [])),
            state_update_intent=dict(data.get("state_update_intent", {})),
            plan_update_intent=dict(data.get("plan_update_intent", {})),
            reason=data.get("reason", ""),
            warnings=list(data.get("warnings", [])),
        )


@dataclass
class CliOutputEnvelope:
    task_id: str
    decision: CliControllerDecision | dict[str, Any]
    schema_version: str = CLI_CONTROLLER_SCHEMA_VERSION
    notes: list[str] = dataclass_field(default_factory=list)
    warnings: list[str] = dataclass_field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.decision, dict):
            self.decision = CliControllerDecision.from_dict(self.decision, task_id=self.task_id)
        self.notes = list(self.notes or [])
        self.warnings = list(self.warnings or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "decision": self.decision.as_dict(),
            "notes": list(self.notes),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliOutputEnvelope":
        return cls(
            schema_version=data.get("schema_version", CLI_CONTROLLER_SCHEMA_VERSION),
            task_id=data["task_id"],
            decision=data["decision"],
            notes=list(data.get("notes", [])),
            warnings=list(data.get("warnings", [])),
        )


@dataclass
class CliDecisionParseResult:
    accepted: bool
    envelope: CliOutputEnvelope | None = None
    decision: CliControllerDecision | None = None
    violations: list[CliContractViolation | dict[str, Any]] = dataclass_field(default_factory=list)
    raw_output: str = ""

    def __post_init__(self) -> None:
        self.violations = [
            violation if isinstance(violation, CliContractViolation) else CliContractViolation.from_dict(violation)
            for violation in self.violations
        ]
        if self.envelope and self.decision is None:
            self.decision = self.envelope.decision
        self.accepted = bool(self.accepted and not self.violations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "envelope": self.envelope.as_dict() if self.envelope else None,
            "decision": self.decision.as_dict() if self.decision else None,
            "violations": [violation.as_dict() for violation in self.violations],
            "raw_output": self.raw_output,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliDecisionParseResult":
        envelope_data = data.get("envelope")
        decision_data = data.get("decision")
        return cls(
            accepted=bool(data.get("accepted", False)),
            envelope=CliOutputEnvelope.from_dict(envelope_data) if envelope_data else None,
            decision=CliControllerDecision.from_dict(decision_data) if decision_data else None,
            violations=list(data.get("violations", [])),
            raw_output=data.get("raw_output", ""),
        )


@dataclass
class CliWorkspaceAccessPolicy:
    task_id: str
    workspace_root: str
    allowed_read_paths: list[str] = dataclass_field(default_factory=list)
    allowed_write_paths: list[str] = dataclass_field(default_factory=list)
    forbidden_paths: list[str] = dataclass_field(default_factory=list)
    allow_shell_commands: bool = False
    allow_database_mutation: bool = False
    allow_schema_mutation: bool = False

    def __post_init__(self) -> None:
        self.allowed_read_paths = list(self.allowed_read_paths or [])
        self.allowed_write_paths = list(self.allowed_write_paths or [])
        self.forbidden_paths = list(self.forbidden_paths or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workspace_root": self.workspace_root,
            "allowed_read_paths": list(self.allowed_read_paths),
            "allowed_write_paths": list(self.allowed_write_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "allow_shell_commands": self.allow_shell_commands,
            "allow_database_mutation": self.allow_database_mutation,
            "allow_schema_mutation": self.allow_schema_mutation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliWorkspaceAccessPolicy":
        return cls(
            task_id=data["task_id"],
            workspace_root=data["workspace_root"],
            allowed_read_paths=list(data.get("allowed_read_paths", [])),
            allowed_write_paths=list(data.get("allowed_write_paths", [])),
            forbidden_paths=list(data.get("forbidden_paths", [])),
            allow_shell_commands=bool(data.get("allow_shell_commands", False)),
            allow_database_mutation=bool(data.get("allow_database_mutation", False)),
            allow_schema_mutation=bool(data.get("allow_schema_mutation", False)),
        )

    def is_read_allowed(self, path: str) -> bool:
        return self._is_allowed(path, self.allowed_read_paths)

    def is_write_allowed(self, path: str) -> bool:
        return self._is_allowed(path, self.allowed_write_paths)

    def validate_artifact_ref(self, path: str) -> list[CliContractViolation]:
        if not self._is_safe_relative_path(path):
            return [
                CliContractViolation(
                    violation_type=CliViolationType.INVALID_ARTIFACT_REFERENCE,
                    message="Artifact reference must stay inside the task workspace.",
                    path=path,
                )
            ]
        return []

    def _is_allowed(self, path: str, allowed_paths: list[str]) -> bool:
        if not self._is_safe_relative_path(path) or self._matches_any(path, self.forbidden_paths):
            return False
        return self._matches_any(path, allowed_paths)

    def _is_safe_relative_path(self, path: str) -> bool:
        try:
            rel_path = Path(path)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                return False
            root = Path(self.workspace_root).resolve()
            candidate = (root / rel_path).resolve()
            candidate.relative_to(root)
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _matches_any(path: str, patterns: list[str]) -> bool:
        normalized = path.strip("/")
        for pattern in patterns:
            clean_pattern = pattern.strip("/")
            if not clean_pattern:
                continue
            if pattern.endswith("/"):
                if normalized == clean_pattern or normalized.startswith(f"{clean_pattern}/"):
                    return True
            elif normalized == clean_pattern:
                return True
        return False


@dataclass
class CliControllerContract:
    task_id: str
    workspace_policy: CliWorkspaceAccessPolicy
    schema_version: str = CLI_CONTROLLER_SCHEMA_VERSION
    decision_types: list[str] = dataclass_field(default_factory=lambda: [item.value for item in AgentDecisionType])
    notes: list[str] = dataclass_field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "workspace_policy": self.workspace_policy.as_dict(),
            "decision_types": list(self.decision_types),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CliControllerContract":
        return cls(
            task_id=data["task_id"],
            workspace_policy=CliWorkspaceAccessPolicy.from_dict(data["workspace_policy"]),
            schema_version=data.get("schema_version", CLI_CONTROLLER_SCHEMA_VERSION),
            decision_types=list(data.get("decision_types", [item.value for item in AgentDecisionType])),
            notes=list(data.get("notes", [])),
        )


def parse_cli_output(
    raw_output: str,
    *,
    registry: SkillRegistry | None = None,
    policy: CliWorkspaceAccessPolicy | None = None,
) -> CliDecisionParseResult:
    try:
        payload = json.loads(raw_output)
    except (TypeError, json.JSONDecodeError):
        return _parse_failure(
            raw_output,
            CliContractViolation(CliViolationType.UNPARSEABLE_OUTPUT, "CLI output is not parseable JSON."),
        )

    if not isinstance(payload, dict):
        return _parse_failure(
            raw_output,
            CliContractViolation(CliViolationType.UNPARSEABLE_OUTPUT, "CLI output must be a JSON object."),
        )

    missing = _missing_required_field(payload, ["schema_version", "task_id", "decision"])
    if missing:
        return _parse_failure(raw_output, missing)
    if payload.get("schema_version") != CLI_CONTROLLER_SCHEMA_VERSION:
        return _parse_failure(
            raw_output,
            CliContractViolation(
                CliViolationType.MISSING_REQUIRED_FIELD,
                "Unsupported or missing schema version.",
                field="schema_version",
                metadata={"expected": CLI_CONTROLLER_SCHEMA_VERSION},
            ),
        )

    decision_data = payload.get("decision")
    if not isinstance(decision_data, dict):
        return _parse_failure(
            raw_output,
            CliContractViolation(CliViolationType.MISSING_REQUIRED_FIELD, "decision must be an object.", field="decision"),
        )
    missing_decision = _missing_required_field(decision_data, ["decision_type", "reason"])
    if missing_decision:
        return _parse_failure(raw_output, missing_decision)
    try:
        decision_type = AgentDecisionType(decision_data.get("decision_type"))
    except ValueError:
        return _parse_failure(
            raw_output,
            CliContractViolation(
                CliViolationType.UNKNOWN_DECISION_TYPE,
                "Decision type is not in the bounded controller vocabulary.",
                field="decision.decision_type",
                metadata={"value": decision_data.get("decision_type")},
            ),
        )

    if decision_type == AgentDecisionType.CALL_TOOL and not isinstance(decision_data.get("skill_request"), dict):
        return _parse_failure(
            raw_output,
            CliContractViolation(
                CliViolationType.MISSING_REQUIRED_FIELD,
                "CALL_TOOL decisions require skill_request.",
                field="decision.skill_request",
            ),
        )

    if isinstance(decision_data.get("skill_request"), dict):
        missing_skill = _missing_required_field(decision_data["skill_request"], ["skill_name"])
        if missing_skill:
            return _parse_failure(raw_output, missing_skill)

    try:
        envelope = CliOutputEnvelope.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        return _parse_failure(
            raw_output,
            CliContractViolation(
                CliViolationType.MISSING_REQUIRED_FIELD,
                "CLI output does not match the contract schema.",
                metadata={"error": str(exc)},
            ),
        )

    violations: list[CliContractViolation] = []
    if envelope.decision.skill_request is not None and (registry is not None or policy is not None):
        violations.extend(validate_cli_skill_request(envelope.decision.skill_request, registry, policy))
    if policy is not None:
        for artifact_ref in envelope.decision.artifact_refs:
            violations.extend(policy.validate_artifact_ref(artifact_ref))
        violations.extend(_validate_intent_flags(envelope.decision.state_update_intent, policy))
        violations.extend(_validate_intent_flags(envelope.decision.plan_update_intent, policy))

    return CliDecisionParseResult(
        accepted=not violations,
        envelope=envelope,
        decision=envelope.decision,
        violations=violations,
        raw_output=raw_output,
    )


def validate_cli_skill_request(
    request: CliSkillRequest | dict[str, Any],
    registry: SkillRegistry | None = None,
    policy: CliWorkspaceAccessPolicy | None = None,
) -> list[CliContractViolation]:
    request_obj = request if isinstance(request, CliSkillRequest) else CliSkillRequest.from_dict(request)
    registry_obj = registry or build_default_skill_registry()
    violations: list[CliContractViolation] = []

    try:
        skill = registry_obj.get_skill(request_obj.skill_name)
    except KeyError:
        return [
            CliContractViolation(
                CliViolationType.UNREGISTERED_SKILL,
                "Requested skill is not registered.",
                skill_name=request_obj.skill_name,
            )
        ]

    if skill.status != SkillStatus.AVAILABLE:
        return [
            CliContractViolation(
                CliViolationType.OUT_OF_SCOPE_SKILL,
                "Requested skill is not available for executable controller requests.",
                skill_name=request_obj.skill_name,
                metadata={"status": skill.status.value},
            )
        ]

    if request_obj.skill_name == "build_minimal_topic_to_evidence_report":
        for path in request_obj.input_artifacts:
            if path == "retrieval/source_candidate_packet.json" or path.startswith("retrieval/"):
                violations.append(
                    CliContractViolation(
                        CliViolationType.RAW_RETRIEVAL_TO_REPORT,
                        "Report generation cannot consume raw retrieval artifacts directly.",
                        path=path,
                        skill_name=request_obj.skill_name,
                    )
                )

    if policy is not None:
        for path in request_obj.input_artifacts:
            violations.extend(policy.validate_artifact_ref(path))
            if not policy.is_read_allowed(path):
                violations.append(
                    CliContractViolation(
                        CliViolationType.DISALLOWED_READ_PATH,
                        "Input artifact is outside the CLI read policy.",
                        path=path,
                        skill_name=request_obj.skill_name,
                    )
                )
        for path in request_obj.output_artifacts:
            violations.extend(policy.validate_artifact_ref(path))
            if not policy.is_write_allowed(path):
                violations.append(
                    CliContractViolation(
                        CliViolationType.DISALLOWED_WRITE_PATH,
                        "Output artifact is outside the CLI write policy.",
                        path=path,
                        skill_name=request_obj.skill_name,
                    )
                )
        violations.extend(_validate_intent_flags(request_obj.parameters, policy))

    return _dedupe_violations(violations)


def cli_decision_to_controller_decision(decision: CliControllerDecision) -> ControllerDecision:
    skill_name = decision.skill_request.skill_name if decision.skill_request else None
    input_artifacts = decision.skill_request.input_artifacts if decision.skill_request else decision.artifact_refs
    output_artifacts = decision.skill_request.output_artifacts if decision.skill_request else []
    return ControllerDecision(
        decision_id=f"cli:{decision.task_id}:{time.time()}",
        task_id=decision.task_id,
        decision_type=decision.decision_type,
        reason=decision.reason,
        target_step_id=decision.target_step_id,
        skill_name=skill_name,
        input_artifacts=list(input_artifacts),
        output_artifacts=list(output_artifacts),
        warnings=decision.warnings,
    )


def cli_violation_to_controller_audit_event(
    violation: CliContractViolation | dict[str, Any],
    task_id: str,
) -> ControllerAuditEvent:
    violation_obj = violation if isinstance(violation, CliContractViolation) else CliContractViolation.from_dict(violation)
    return ControllerAuditEvent(
        event_id=f"cli_violation:{task_id}:{time.time()}",
        task_id=task_id,
        event_type=AuditEventType.CONTROLLER_EVENT,
        message=violation_obj.message,
        artifacts=[violation_obj.path] if violation_obj.path else [],
        errors=[violation_obj.violation_type.value],
        metadata=violation_obj.as_dict(),
    )


def cli_decision_to_controller_audit_event(decision: CliControllerDecision) -> ControllerAuditEvent:
    artifacts: list[str] = []
    if decision.skill_request is not None:
        artifacts.extend(decision.skill_request.input_artifacts)
        artifacts.extend(decision.skill_request.output_artifacts)
    artifacts.extend(decision.artifact_refs)
    return ControllerAuditEvent(
        event_id=f"cli_decision:{decision.task_id}:{time.time()}",
        task_id=decision.task_id,
        event_type=AuditEventType.CONTROLLER_EVENT,
        decision_type=decision.decision_type.value,
        target_step_id=decision.target_step_id,
        message=decision.reason,
        artifacts=list(dict.fromkeys(artifacts)),
        warnings=decision.warnings,
        metadata={"decision": decision.as_dict()},
    )


def _parse_failure(raw_output: str, violation: CliContractViolation) -> CliDecisionParseResult:
    return CliDecisionParseResult(accepted=False, violations=[violation], raw_output=raw_output)


def _missing_required_field(data: dict[str, Any], fields: list[str]) -> CliContractViolation | None:
    for field_name in fields:
        if field_name not in data or data[field_name] in (None, ""):
            return CliContractViolation(
                CliViolationType.MISSING_REQUIRED_FIELD,
                f"Missing required field: {field_name}",
                field=field_name,
            )
    return None


def _validate_intent_flags(payload: Any, policy: CliWorkspaceAccessPolicy) -> list[CliContractViolation]:
    violations: list[CliContractViolation] = []
    if not isinstance(payload, dict):
        return violations
    if not policy.allow_shell_commands and _contains_key(payload, {"shell_command", "shell_commands"}):
        violations.append(CliContractViolation(CliViolationType.SHELL_COMMAND_NOT_ALLOWED, "Shell commands are not allowed."))
    if not policy.allow_database_mutation and _contains_key(payload, {"database_mutation", "database_write"}):
        violations.append(
            CliContractViolation(CliViolationType.DATABASE_MUTATION_ATTEMPT, "Database mutation is not allowed.")
        )
    if not policy.allow_schema_mutation and _contains_key(payload, {"schema_mutation", "schema_write"}):
        violations.append(CliContractViolation(CliViolationType.SCHEMA_MUTATION_ATTEMPT, "Schema mutation is not allowed."))
    return violations


def _contains_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(key in keys or _contains_key(child, keys) for key, child in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, keys) for item in value)
    return False


def _dedupe_violations(violations: list[CliContractViolation]) -> list[CliContractViolation]:
    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    deduped: list[CliContractViolation] = []
    for violation in violations:
        key = (
            violation.violation_type.value,
            violation.field,
            violation.path,
            violation.skill_name,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(violation)
    return deduped


def _coerce_enum(enum_cls: type[Enum], value: Enum | str, field_name: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise ValueError(f"invalid {field_name}: {value!r}; expected one of: {allowed}") from exc


__all__ = [
    "CLI_CONTROLLER_SCHEMA_VERSION",
    "CliContractViolation",
    "CliControllerContract",
    "CliControllerDecision",
    "CliDecisionParseResult",
    "CliOutputEnvelope",
    "CliSkillRequest",
    "CliViolationType",
    "CliWorkspaceAccessPolicy",
    "CliWriteIntent",
    "cli_decision_to_controller_audit_event",
    "cli_decision_to_controller_decision",
    "cli_violation_to_controller_audit_event",
    "parse_cli_output",
    "validate_cli_skill_request",
]
