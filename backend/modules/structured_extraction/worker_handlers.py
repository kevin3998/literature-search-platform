from __future__ import annotations

from sqlalchemy.engine import Engine

from core.user_context import UserContext
from core.worker.handlers import HandlerRegistry


def build_structured_extraction_registry(
    *,
    evidence_packet_service=None,
    run_service=None,
    multimodal_review_service=None,
    engine: Engine | None = None,
) -> HandlerRegistry:
    registry = HandlerRegistry()
    register_structured_extraction_handlers(
        registry,
        evidence_packet_service=evidence_packet_service,
        run_service=run_service,
        multimodal_review_service=multimodal_review_service,
        engine=engine,
    )
    return registry


def register_structured_extraction_handlers(
    registry: HandlerRegistry,
    *,
    evidence_packet_service=None,
    run_service=None,
    multimodal_review_service=None,
    engine: Engine | None = None,
) -> None:
    if evidence_packet_service is None or run_service is None or multimodal_review_service is None:
        from .shared import (
            structured_extraction_evidence_packet_service,
            structured_extraction_multimodal_review_service,
            structured_extraction_run_service,
        )

        evidence_packet_service = evidence_packet_service or structured_extraction_evidence_packet_service
        run_service = run_service or structured_extraction_run_service
        multimodal_review_service = multimodal_review_service or structured_extraction_multimodal_review_service

    registry.register(
        "structured.evidence_packet_build",
        lambda job, _context: _run_evidence_packet_build(evidence_packet_service, job),
    )
    registry.register(
        "structured.extraction_run",
        lambda job, _context: _run_extraction(run_service, job),
    )
    registry.register(
        "structured.multimodal_review",
        lambda job, _context: _run_multimodal_review(multimodal_review_service, job),
    )


def _run_evidence_packet_build(service, job) -> dict:
    payload = job.get("payload") or {}
    service._worker_entry(payload["task_id"], payload["build_job_id"], payload["user_id"])  # noqa: SLF001
    return {"task_id": payload["task_id"], "build_job_id": payload["build_job_id"]}


def _run_extraction(service, job) -> dict:
    payload = job.get("payload") or {}
    service._worker_entry(payload["task_id"], payload["run_id"], payload["user_id"])  # noqa: SLF001
    return {"task_id": payload["task_id"], "run_id": payload["run_id"]}


def _run_multimodal_review(service, job) -> dict:
    payload = job.get("payload") or {}
    user = UserContext(user_id=payload["user_id"], workspace_slug=payload["user_id"])
    service._run_job(payload["task_id"], payload["run_id"], payload["job_id"], user)  # noqa: SLF001
    return {"task_id": payload["task_id"], "run_id": payload["run_id"], "job_id": payload["job_id"]}
