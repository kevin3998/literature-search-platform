from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.user_context import UserContext, current_user
from modules.structured_extraction.schemas import (
    BulkCandidateDecisionRequest,
    CandidateDecisionRequest,
    CollectionSearchRequest,
    EvidencePacketBuildRequest,
    ExportCreateRequest,
    ExtractionRunResumeRequest,
    ExtractionRunStartRequest,
    LLMScreenRequest,
    MultimodalReviewJobCreateRequest,
    PromptContractCompileRequest,
    QuestionExpansionRequest,
    ReviewBulkRequest,
    ReviewFieldActionRequest,
    ReviewFieldEditRequest,
    ReviewSuggestionActionRequest,
    ReviewSuggestionBulkRequest,
    SchemaAssistRequest,
    SchemaDraftSaveRequest,
    TaskArchiveRequest,
    TaskCreateRequest,
    TaskDuplicateRequest,
    TaskUpdateRequest,
)
from modules.structured_extraction.llm_collection import expand_question, screen_candidates
from modules.structured_extraction.llm_schema import assist_schema
from modules.structured_extraction.shared import (
    structured_extraction_collection_service,
    structured_extraction_evidence_packet_service,
    structured_extraction_export_service,
    structured_extraction_multimodal_review_service,
    structured_extraction_prompt_contract_service,
    structured_extraction_review_service,
    structured_extraction_run_service,
    structured_extraction_schema_designer,
    structured_extraction_store,
)

router = APIRouter(prefix="/api/structured-extraction", tags=["structured-extraction"])


def _handle_error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail="structured extraction task not found") from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/tasks")
def list_tasks(include_archived: bool = False, limit: int = 100, user: UserContext = Depends(current_user)):
    try:
        return {
            "tasks": structured_extraction_store.list_tasks(
                include_archived=include_archived,
                limit=limit,
                user_id=user.user_id,
            )
        }
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks")
def create_task(payload: TaskCreateRequest, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_store.create_task(
            name=payload.name,
            description=payload.description,
            user=user,
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_store.get_task(task_id, user_id=user.user_id)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdateRequest, user: UserContext = Depends(current_user)):
    try:
        fields = payload.model_dump(exclude_none=True)
        return structured_extraction_store.update_task(task_id, user=user, **fields)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/duplicate")
def duplicate_task(task_id: str, payload: TaskDuplicateRequest, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_store.duplicate_task(
            task_id,
            user=user,
            name=payload.name,
            copy_model_settings=payload.copy_model_settings,
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/archive")
def archive_task(task_id: str, payload: TaskArchiveRequest, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_store.set_archived(task_id, payload.archived, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.soft_delete(task_id, user=user)
        return {"task_id": task_id, "deleted": True}
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/collection/search")
def search_collection(task_id: str, payload: CollectionSearchRequest, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.search(task_id, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/collection/filter-options")
def collection_filter_options(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.filter_options(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/collection/candidates")
def list_collection_candidates(
    task_id: str,
    decision: str | None = None,
    source: str | None = None,
    q: str | None = None,
    limit: int = 100,
    user: UserContext = Depends(current_user),
):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.list_candidates(
            task_id,
            user=user,
            decision=decision,
            source=source,
            q=q,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/collection/candidates/{candidate_id}/decision")
def set_candidate_decision(
    task_id: str,
    candidate_id: str,
    payload: CandidateDecisionRequest,
    user: UserContext = Depends(current_user),
):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.set_decision(task_id, candidate_id, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/collection/candidates/bulk-decision")
def bulk_candidate_decision(task_id: str, payload: BulkCandidateDecisionRequest, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.bulk_decision(task_id, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/collection/question-expansion")
async def question_expansion(task_id: str, payload: QuestionExpansionRequest, user: UserContext = Depends(current_user)):
    try:
        task = structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return await expand_question(payload, task=task)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/collection/llm-screen")
async def llm_screen(task_id: str, payload: LLMScreenRequest, user: UserContext = Depends(current_user)):
    try:
        task = structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return await screen_candidates(
            structured_extraction_collection_service,
            task_id,
            payload,
            task=task,
            user=user,
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/collection/freeze")
def freeze_collection(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.freeze(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/collection/versions")
def list_collection_versions(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.list_versions(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/collection/versions/{collection_version}")
def get_collection_version(task_id: str, collection_version: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_collection_service.get_version(task_id, collection_version, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/schema/draft")
def get_schema_draft(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_schema_designer.get_draft(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.put("/tasks/{task_id}/schema/draft")
def save_schema_draft(task_id: str, payload: SchemaDraftSaveRequest, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_schema_designer.save_draft(task_id, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/schema/assist")
async def schema_assist(task_id: str, payload: SchemaAssistRequest, user: UserContext = Depends(current_user)):
    try:
        task = structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return await assist_schema(payload, task=task)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/schema/freeze")
def freeze_schema(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_schema_designer.freeze(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/schema/versions")
def list_schema_versions(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_schema_designer.list_versions(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/schema/versions/{schema_version}")
def get_schema_version(task_id: str, schema_version: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_schema_designer.get_version(task_id, schema_version, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/schema/versions/{schema_version}/duplicate-to-draft")
def duplicate_schema_to_draft(task_id: str, schema_version: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_schema_designer.duplicate_to_draft(task_id, schema_version, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/prompt-contract/compile")
def compile_prompt_contract(
    task_id: str,
    payload: PromptContractCompileRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_prompt_contract_service.compile(task_id, payload or PromptContractCompileRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/prompt-contract/versions")
def list_prompt_contracts(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_prompt_contract_service.list_versions(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/prompt-contract/versions/{prompt_contract_version}")
def get_prompt_contract(task_id: str, prompt_contract_version: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_prompt_contract_service.get_version(task_id, prompt_contract_version, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/evidence-packets/build")
def build_evidence_packet(
    task_id: str,
    payload: EvidencePacketBuildRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.build(task_id, payload or EvidencePacketBuildRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/evidence-packets/build-jobs")
def start_evidence_packet_build_job(
    task_id: str,
    payload: EvidencePacketBuildRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.start_build_job(task_id, payload or EvidencePacketBuildRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/evidence-packets/build-jobs")
def list_evidence_packet_build_jobs(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.list_build_jobs(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/evidence-packets/build-jobs/{build_job_id}")
def get_evidence_packet_build_job(task_id: str, build_job_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.get_build_job(task_id, build_job_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/evidence-packets/build-jobs/{build_job_id}/cancel")
def cancel_evidence_packet_build_job(task_id: str, build_job_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.cancel_build_job(task_id, build_job_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/evidence-packets/versions")
def list_evidence_packets(task_id: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.list_versions(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/evidence-packets/versions/{packet_version}")
def get_evidence_packet(task_id: str, packet_version: str, user: UserContext = Depends(current_user)):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.get_version(task_id, packet_version, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/evidence-packets/versions/{packet_version}/items")
def list_evidence_packet_items(
    task_id: str,
    packet_version: str,
    limit: int | None = None,
    offset: int | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        structured_extraction_store.get_task(task_id, user_id=user.user_id)
        return structured_extraction_evidence_packet_service.list_items(task_id, packet_version, user=user, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/runs")
def start_extraction_run(
    task_id: str,
    payload: ExtractionRunStartRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        return structured_extraction_run_service.start(task_id, payload or ExtractionRunStartRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/runs")
def list_extraction_runs(task_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_run_service.list_runs(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/runs/{run_id}")
def get_extraction_run(task_id: str, run_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_run_service.get(task_id, run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/runs/{run_id}/items")
def list_extraction_run_items(task_id: str, run_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_run_service.list_items(task_id, run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/runs/{run_id}/records")
def list_extraction_run_records(task_id: str, run_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_run_service.list_records(task_id, run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/runs/{run_id}/recovery")
def get_extraction_run_recovery(task_id: str, run_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_run_service.recovery_status(task_id, run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/runs/{run_id}/resume")
def resume_extraction_run(
    task_id: str,
    run_id: str,
    payload: ExtractionRunResumeRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        return structured_extraction_run_service.resume(task_id, run_id, payload or ExtractionRunResumeRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/runs/{run_id}/cancel")
def cancel_extraction_run(task_id: str, run_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_run_service.cancel(task_id, run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/runs")
def list_review_runs(task_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.list_runs(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/table")
def list_review_table(
    task_id: str,
    run_id: str | None = None,
    q: str | None = None,
    field_key: str | None = None,
    status: str | None = None,
    review_priority: str | None = None,
    quality_flag: str | None = None,
    missing: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    user: UserContext = Depends(current_user),
):
    try:
        return structured_extraction_review_service.table(
            task_id,
            user=user,
            run_id=run_id,
            q=q,
            field_key=field_key,
            status=status,
            review_priority=review_priority,
            quality_flag=quality_flag,
            missing=missing,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/summary")
def get_review_summary(task_id: str, run_id: str | None = None, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_multimodal_review_service.summary(task_id, run_id=run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/queue")
def list_review_queue(
    task_id: str,
    run_id: str | None = None,
    queue: str = "all",
    limit: int = 100,
    offset: int = 0,
    user: UserContext = Depends(current_user),
):
    try:
        return structured_extraction_multimodal_review_service.queue(
            task_id,
            run_id=run_id,
            queue=queue,
            limit=limit,
            offset=offset,
            user=user,
        )
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/records/{record_id}")
def get_review_record(task_id: str, record_id: str, run_id: str | None = None, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.record(task_id, record_id, run_id=run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/records/{record_id}/events")
def list_review_events(task_id: str, record_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.events(task_id, record_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/records/{record_id}/fields/{field_key}/accept")
def accept_review_field(task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest | None = None, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.accept_field(task_id, record_id, field_key, payload or ReviewFieldActionRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/records/{record_id}/fields/{field_key}/edit")
def edit_review_field(task_id: str, record_id: str, field_key: str, payload: ReviewFieldEditRequest, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.edit_field(task_id, record_id, field_key, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/records/{record_id}/fields/{field_key}/reject")
def reject_review_field(task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest | None = None, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.reject_field(task_id, record_id, field_key, payload or ReviewFieldActionRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/records/{record_id}/fields/{field_key}/lock")
def lock_review_field(task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest | None = None, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.lock_field(task_id, record_id, field_key, payload or ReviewFieldActionRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/records/{record_id}/fields/{field_key}/unlock")
def unlock_review_field(task_id: str, record_id: str, field_key: str, payload: ReviewFieldActionRequest | None = None, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.unlock_field(task_id, record_id, field_key, payload or ReviewFieldActionRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/events/{event_id}/revert")
def revert_review_event(task_id: str, event_id: int, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.revert_event(task_id, event_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/bulk")
def bulk_review_action(task_id: str, payload: ReviewBulkRequest, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_review_service.bulk(task_id, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/runs/{run_id}/multimodal-jobs")
def start_multimodal_review_job(
    task_id: str,
    run_id: str,
    payload: MultimodalReviewJobCreateRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        return structured_extraction_multimodal_review_service.start_job(task_id, run_id, payload or MultimodalReviewJobCreateRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/runs/{run_id}/multimodal-jobs")
def list_multimodal_review_jobs(task_id: str, run_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_multimodal_review_service.list_jobs(task_id, run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/review/multimodal-jobs/{job_id}")
def get_multimodal_review_job(task_id: str, job_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_multimodal_review_service.get_job(task_id, job_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/multimodal-jobs/{job_id}/cancel")
def cancel_multimodal_review_job(task_id: str, job_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_multimodal_review_service.cancel_job(task_id, job_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/suggestions/{suggestion_id}/accept")
def accept_review_suggestion(
    task_id: str,
    suggestion_id: str,
    payload: ReviewSuggestionActionRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        return structured_extraction_multimodal_review_service.accept_suggestion(task_id, suggestion_id, payload or ReviewSuggestionActionRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/suggestions/{suggestion_id}/reject")
def reject_review_suggestion(
    task_id: str,
    suggestion_id: str,
    payload: ReviewSuggestionActionRequest | None = None,
    user: UserContext = Depends(current_user),
):
    try:
        return structured_extraction_multimodal_review_service.reject_suggestion(task_id, suggestion_id, payload or ReviewSuggestionActionRequest(), user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/review/suggestions/bulk")
def bulk_review_suggestions(task_id: str, payload: ReviewSuggestionBulkRequest, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_multimodal_review_service.bulk_suggestions(task_id, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/exports/preview")
def preview_export(task_id: str, run_id: str | None = None, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_export_service.preview(task_id, run_id=run_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.post("/tasks/{task_id}/exports")
def create_export(task_id: str, payload: ExportCreateRequest, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_export_service.create(task_id, payload, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/exports")
def list_exports(task_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_export_service.list_exports(task_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/exports/{export_id}")
def get_export(task_id: str, export_id: str, user: UserContext = Depends(current_user)):
    try:
        return structured_extraction_export_service.get(task_id, export_id, user=user)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)


@router.get("/tasks/{task_id}/exports/{export_id}/download")
def download_export(task_id: str, export_id: str, format: str, user: UserContext = Depends(current_user)):  # noqa: A002
    try:
        path, media_type = structured_extraction_export_service.download_path(task_id, export_id, format, user=user)
        return FileResponse(path, media_type=media_type, filename=path.name)
    except Exception as exc:  # noqa: BLE001
        _handle_error(exc)
