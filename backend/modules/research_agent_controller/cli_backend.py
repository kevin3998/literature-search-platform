"""Mockable controller backend interfaces for A7a."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .cli_contract import CLI_CONTROLLER_SCHEMA_VERSION


class CliControllerBackend(Protocol):
    """Backend that emits one raw controller-envelope string per step."""

    def next_output(self, snapshot: dict[str, Any]) -> str:
        ...


@dataclass
class ControllerWorkspaceSnapshot:
    task_id: str
    task_md: str
    plan_md: str
    state: dict[str, Any]
    artifact_manifest: dict[str, Any]
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    step_index: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class FakeCliControllerBackend:
    """Test backend that returns pre-scripted contract envelopes."""

    def __init__(self, outputs: list[str | dict[str, Any]]):
        self.outputs = list(outputs)
        self.index = 0
        self.snapshots: list[dict[str, Any]] = []

    def next_output(self, snapshot: dict[str, Any]) -> str:
        self.snapshots.append(dict(snapshot))
        if self.index >= len(self.outputs):
            return json.dumps(_stop_blocked(snapshot.get("task_id", "")), ensure_ascii=False, sort_keys=True)
        output = self.outputs[self.index]
        self.index += 1
        if isinstance(output, str):
            return output
        return json.dumps(output, ensure_ascii=False, sort_keys=True)


def _stop_blocked(task_id: str) -> dict[str, Any]:
    return {
        "schema_version": CLI_CONTROLLER_SCHEMA_VERSION,
        "task_id": task_id,
        "decision": {
            "decision_type": "STOP_BLOCKED",
            "reason": "Fake CLI backend has no remaining scripted outputs.",
        },
        "notes": [],
        "warnings": ["fake_cli_backend_outputs_exhausted"],
    }


__all__ = [
    "CliControllerBackend",
    "ControllerWorkspaceSnapshot",
    "FakeCliControllerBackend",
]
