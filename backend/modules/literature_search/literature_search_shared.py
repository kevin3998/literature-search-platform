"""Process-wide singletons for the literature-search subsystem.

The API process only enqueues jobs. A separate PostgreSQL worker process claims
and executes them, so importing routers must not reap or mutate active jobs.
"""
from __future__ import annotations

from modules.literature_search.job_runner import JobRunner
from modules.literature_search.job_store import JobStore
from modules.literature_search.service import LiteratureResearchService

service = LiteratureResearchService()
job_store = JobStore()
job_runner = JobRunner(job_store, service)
