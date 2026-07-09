from __future__ import annotations

from sqlalchemy.engine import Engine

from core.worker.handlers import HandlerRegistry

from .job_runner import JobRunner
from .job_store import JobStore
from .service import LiteratureResearchService

LITERATURE_JOB_TYPES = (
    "task_run",
    "run",
    "run_resume",
    "pack",
    "extract",
    "compare",
    "analysis_bundle",
    "verify_answer",
    "notes_build",
    "synthesize",
    "quality",
    "vector_build",
    "health_check",
    "index_refresh",
)


def build_literature_registry(*, store: JobStore | None = None, service: LiteratureResearchService | None = None, engine: Engine | None = None) -> HandlerRegistry:
    registry = HandlerRegistry()
    register_literature_handlers(registry, store=store, service=service, engine=engine)
    return registry


def register_literature_handlers(
    registry: HandlerRegistry,
    *,
    store: JobStore | None = None,
    service: LiteratureResearchService | None = None,
    engine: Engine | None = None,
) -> None:
    job_store = store or JobStore(engine=engine)
    runner = JobRunner(job_store, service or LiteratureResearchService())
    for job_type in LITERATURE_JOB_TYPES:
        registry.register(job_type, lambda job, _context, _runner=runner: _runner.execute_job(job))
