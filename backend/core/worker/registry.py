from __future__ import annotations

from sqlalchemy.engine import Engine

from .handlers import HandlerRegistry


def build_handler_registry(*, engine: Engine | None = None) -> HandlerRegistry:
    registry = HandlerRegistry()

    from modules.literature_search.worker_handlers import register_literature_handlers
    from modules.structured_extraction.worker_handlers import register_structured_extraction_handlers
    from modules.workflow.worker_handlers import register_workflow_handlers

    register_literature_handlers(registry, engine=engine)
    register_workflow_handlers(registry, engine=engine)
    register_structured_extraction_handlers(registry, engine=engine)
    return registry
