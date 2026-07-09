from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class HandlerContext:
    events: list[dict[str, Any]] = field(default_factory=list)


JobHandler = Callable[[dict[str, Any], HandlerContext], dict[str, Any] | None]


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> JobHandler:
        try:
            return self._handlers[job_type]
        except KeyError:
            raise KeyError(f"unknown job type: {job_type}") from None

    def job_types(self) -> list[str]:
        return sorted(self._handlers)
