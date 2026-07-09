from __future__ import annotations

from sqlalchemy.engine import Engine

from core.worker.handlers import HandlerRegistry


def build_workflow_registry(*, orchestrator=None, engine: Engine | None = None) -> HandlerRegistry:
    registry = HandlerRegistry()
    register_workflow_handlers(registry, orchestrator=orchestrator, engine=engine)
    return registry


def register_workflow_handlers(registry: HandlerRegistry, *, orchestrator=None, engine: Engine | None = None) -> None:
    if orchestrator is None:
        from .shared import workflow_orchestrator

        orchestrator = workflow_orchestrator
    registry.register("workflow.run", lambda job, _context: orchestrator.execute_job(job))
