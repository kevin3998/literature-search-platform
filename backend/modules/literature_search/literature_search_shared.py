"""Process-wide singletons for the literature-search subsystem.

The literature-search router and the corpus router both submit/stream jobs.
Sharing one ``service`` / ``JobStore`` / ``JobRunner`` here (rather than each
router building its own) keeps maintenance jobs and research jobs running
through the same in-process runner and event stream.
"""
from __future__ import annotations

from modules.literature_search.job_runner import JobRunner
from modules.literature_search.job_store import JobStore
from modules.literature_search.service import LiteratureResearchService

service = LiteratureResearchService()
job_store = JobStore()
# A fresh process can't own any live job thread, so any job still marked
# queued/running was orphaned by the previous process (e.g. uvicorn --reload
# restarting on a code edit). Reap them so the home dashboard and maintenance
# mutex don't wedge on a job that is no longer actually running.
try:
    _reaped = job_store.reap_orphaned_jobs()
    if _reaped:
        print(f"[literature_search] reaped {len(_reaped)} orphaned job(s) on startup: {_reaped}")
except Exception as _exc:  # noqa: BLE001 - reaping must never block startup
    print(f"[literature_search] orphaned-job reaping skipped: {_exc}")
job_runner = JobRunner(job_store, service)
