"""Process-wide singletons for the workflow subsystem.

Reuses the literature-search shared service / JobStore / JobRunner so workflow
sub-jobs run through the SAME in-process runner + event stream (and the same
orphaned-job reaper) as chat tool jobs.
"""
from __future__ import annotations

from modules.literature_search.literature_search_shared import job_runner, job_store, service

from .orchestrator import WorkflowOrchestrator
from .store import WorkflowStore

workflow_store = WorkflowStore()
workflow_orchestrator = WorkflowOrchestrator(workflow_store, job_runner, job_store, service)
