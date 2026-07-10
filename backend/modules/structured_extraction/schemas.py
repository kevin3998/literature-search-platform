from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal[
    "draft",
    "collecting",
    "collection_ready",
    "schema_ready",
    "extracting",
    "review_required",
    "completed",
    "exported",
    "failed",
    "archived",
    "deleted",
]

DEFAULT_TASK_STATS = {
    "paper_count": 0,
    "field_count": 0,
    "run_count": 0,
    "export_count": 0,
}


class ExtractionTask(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    task_id: str
    user_id: str
    name: str
    description: str = ""
    status: TaskStatus = "draft"
    workspace_rel_path: str
    current_collection_version: str | None = None
    current_schema_version: str | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_TASK_STATS))
    archived: bool = False
    deleted_at: float | None = None
    created_at: float
    updated_at: float
    last_run_at: float | None = None


class TaskCreateRequest(BaseModel):
    name: str
    description: str = ""


class TaskUpdateRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    model_settings: dict[str, Any] | None = None


class TaskDuplicateRequest(BaseModel):
    name: str
    copy_model_settings: bool = True


class TaskArchiveRequest(BaseModel):
    archived: bool = True


DecisionValue = Literal["candidate", "include", "exclude", "uncertain"]
ExcludeReason = Literal[
    "not_relevant",
    "review_article",
    "no_full_text",
    "not_target_material",
    "not_target_method",
    "not_target_application",
    "duplicate",
    "insufficient_data",
    "non_experimental",
    "non_english_or_non_chinese",
    "other",
]


class CollectionSearchRequest(BaseModel):
    query: str = ""
    limit: int | None = 50
    year_from: int | None = None
    year_to: int | None = None
    journal: str | None = None
    site: str | None = None
    source: str = "metadata_search"


class CandidateDecisionRequest(BaseModel):
    decision: DecisionValue
    exclude_reason: ExcludeReason | None = None


class BulkCandidateDecisionRequest(BaseModel):
    candidate_ids: list[str]
    decision: DecisionValue
    exclude_reason: ExcludeReason | None = None


class QuestionExpansionRequest(BaseModel):
    question: str
    limit: int = 5


class LLMScreenRequest(BaseModel):
    candidate_ids: list[str]
    prompt: str = ""


RecordUnit = Literal["paper_level", "material_level", "sample_level", "experiment_level", "condition_level"]
FieldType = Literal["string", "number", "boolean", "enum", "multi_enum", "date", "object", "list_object", "list_string", "dict", "evidence_text"]
SchemaAssistAction = Literal["suggest_fields", "rewrite_field", "split_field", "merge_fields", "generate_examples", "parse_field_definition"]


class SchemaDraftSaveRequest(BaseModel):
    schema_mode: str = "flat_fields"
    record_schema: dict[str, Any] = Field(default_factory=dict)
    field_groups: list[dict[str, Any]] = Field(default_factory=list)
    field_tree: list[dict[str, Any]] = Field(default_factory=list)
    fields: list[dict[str, Any]] = Field(default_factory=list)
    global_instructions: list[dict[str, Any]] = Field(default_factory=list)
    source_compilation_id: str | None = None


class SchemaAssistRequest(BaseModel):
    action: SchemaAssistAction
    instruction: str = ""
    draft: dict[str, Any] | None = None
    field: dict[str, Any] | None = None
    fields: list[dict[str, Any]] = Field(default_factory=list)
    source_format: Literal["auto", "json", "markdown", "natural_language"] = "auto"


class SchemaCompilationResolution(BaseModel):
    requirement_id: str
    disposition: Literal["user_schema", "system_metadata", "record_identity", "constraint", "global_instruction", "ignored_with_reason"]
    target_path: str = ""
    reason: str = ""
    node: dict[str, Any] | None = None


class SchemaCompilationResolveRequest(BaseModel):
    resolutions: list[SchemaCompilationResolution] = Field(default_factory=list)


class SchemaCompilationApplyRequest(BaseModel):
    mode: Literal["replace", "merge"] = "replace"


class PromptContractCompileRequest(BaseModel):
    collection_version: str | None = None
    schema_version: str | None = None


class EvidencePacketBuildRequest(BaseModel):
    collection_version: str | None = None
    schema_version: str | None = None
    prompt_contract_version: str | None = None
    max_chunks_per_group: int = 6
    max_chars_per_chunk: int = 1800
    include_assets: bool = True


class ExtractionRunStartRequest(BaseModel):
    collection_version: str | None = None
    schema_version: str | None = None
    prompt_contract_version: str | None = None
    packet_version: str | None = None


class ExtractionRunResumeRequest(BaseModel):
    retry_failed_items: bool = True
    reason: str = "manual_resume"


class ReviewFieldActionRequest(BaseModel):
    reason: str = ""


class ReviewFieldEditRequest(BaseModel):
    value: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    locked: bool = True


class ReviewBulkRequest(BaseModel):
    items: list[dict[str, str]]
    action: str
    reason: str = ""


ScanMode = Literal["evidence_only", "related_pages_assets", "full_document"]
SuggestionBulkAction = Literal["accept", "reject"]


class MultimodalReviewJobCreateRequest(BaseModel):
    scan_mode: ScanMode | None = None
    reason: str = ""


class ReviewSuggestionActionRequest(BaseModel):
    reason: str = ""


class ReviewSuggestionBulkRequest(BaseModel):
    suggestion_ids: list[str] = Field(default_factory=list)
    action: SuggestionBulkAction
    reason: str = ""


ExportFormat = Literal["csv", "json", "xlsx", "markdown"]


class ExportCreateRequest(BaseModel):
    run_id: str | None = None
    formats: list[ExportFormat] = Field(default_factory=lambda: ["csv", "json", "xlsx", "markdown"])
    include_rejected: bool = False
    include_base_values: bool = True
    include_review_metadata: bool = True
