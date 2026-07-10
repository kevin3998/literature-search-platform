from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_COMPILER_VERSION = "2.0"
SCHEMA_CONTRACT_VERSION = "nested_record_v1"
MAX_SOURCE_CHARS = 100_000
MAX_REQUIREMENTS = 500
MAX_FIELD_NODES = 500
MAX_TREE_DEPTH = 8
MAX_KEY_LENGTH = 64

SchemaMode = Literal["flat_fields", "nested_material", "nested_record"]
RecordUnit = Literal["paper_level", "material_level", "sample_level", "experiment_level", "condition_level"]
FieldType = Literal[
    "string",
    "number",
    "boolean",
    "enum",
    "multi_enum",
    "date",
    "object",
    "list_object",
    "list_string",
    "dict",
    "evidence_text",
]
RequirementKind = Literal["field", "constraint", "global_instruction", "record_identity", "grouping_rule", "selection_rule"]
RequirementDisposition = Literal[
    "user_schema",
    "system_metadata",
    "record_identity",
    "constraint",
    "global_instruction",
    "ignored_with_reason",
    "unresolved",
]
CompilationStatus = Literal["valid", "valid_with_warnings", "needs_review", "failed", "llm_unavailable"]


class SourceSpan(BaseModel):
    start: int = 0
    end: int = 0
    start_line: int = 1
    end_line: int = 1


class RequirementConstraint(BaseModel):
    type: str
    values: list[Any] = Field(default_factory=list)
    text: str = ""


class SchemaRequirement(BaseModel):
    requirement_id: str
    kind: RequirementKind = "field"
    raw_name: str = ""
    source_path: str = ""
    source_text: str
    source_span: SourceSpan = Field(default_factory=SourceSpan)
    shape_hint: str = ""
    parent_requirement_id: str | None = None
    constraints: list[RequirementConstraint] = Field(default_factory=list)


class RequirementMapping(BaseModel):
    requirement_id: str
    disposition: RequirementDisposition
    target_path: str = ""
    reason: str = ""


class RecordSchemaContract(BaseModel):
    record_type: str = "record"
    record_unit: RecordUnit = "paper_level"
    primary_entity: str = "paper"
    one_paper_may_have_multiple_records: bool = False
    record_identity_fields: list[str] = Field(default_factory=lambda: ["paper_id"])
    deduplication_keys: list[str] = Field(default_factory=lambda: ["paper_id"])
    parent_record_type: str | None = None


class SchemaFieldNode(BaseModel):
    key: str
    label: str = ""
    type: FieldType = "string"
    description: str = ""
    extraction_instruction: str = ""
    required: bool = False
    evidence_required: bool = True
    allowed_values: list[str] = Field(default_factory=list)
    notes: str = ""
    order: int = 1
    children: list["SchemaFieldNode"] = Field(default_factory=list)
    source_requirement_ids: list[str] = Field(default_factory=list)
    origin: Literal["source_declared", "model_suggested", "manual"] = "source_declared"
    confidence: float | None = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return max(0.0, min(1.0, float(value)))


class GlobalInstruction(BaseModel):
    requirement_id: str
    category: Literal["selection", "grouping", "extraction", "constraint", "other"] = "extraction"
    text: str


class CoverageReport(BaseModel):
    total: int = 0
    resolved: int = 0
    unresolved: int = 0
    ratio: float = 1.0
    unresolved_requirement_ids: list[str] = Field(default_factory=list)


class CompilationResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    compilation_id: str | None = None
    status: CompilationStatus
    source_format: str
    schema_mode: SchemaMode = "nested_record"
    compiler_version: str = SCHEMA_COMPILER_VERSION
    contract_version: str = SCHEMA_CONTRACT_VERSION
    record_schema: RecordSchemaContract
    field_tree: list[SchemaFieldNode] = Field(default_factory=list)
    paper_metadata_fields: list[str] = Field(default_factory=list)
    system_metadata_contract: dict[str, dict[str, Any]] = Field(default_factory=dict)
    global_instructions: list[GlobalInstruction] = Field(default_factory=list)
    requirements: list[SchemaRequirement] = Field(default_factory=list)
    requirement_mappings: list[RequirementMapping] = Field(default_factory=list)
    coverage: CoverageReport = Field(default_factory=CoverageReport)
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    normalization_changes: list[dict[str, Any]] = Field(default_factory=list)
    model_attempts: list[dict[str, Any]] = Field(default_factory=list)
    field_tree_hash: str = ""


PAPER_METADATA_REGISTRY: dict[str, dict[str, Any]] = {
    "title": {"type": "string", "aliases": ["paper_title", "publication_title", "article_title"]},
    "doi": {"type": "string", "aliases": ["digital_object_identifier"]},
    "year": {"type": "number", "aliases": ["publication_year", "published_year"]},
    "journal": {"type": "string", "aliases": ["venue", "publication_venue", "journal_name"]},
    "authors": {"type": "list_string", "aliases": ["author", "author_list"]},
    "source_path": {"type": "string", "aliases": ["document_path", "article_path"]},
    "index_version": {"type": "number", "aliases": ["research_index_version"]},
}


def paper_metadata_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, spec in PAPER_METADATA_REGISTRY.items():
        aliases[key] = key
        for alias in spec.get("aliases") or []:
            aliases[str(alias)] = key
    return aliases


NESTED_SCHEMA_MODES = {"nested_material", "nested_record"}


def is_nested_schema_mode(value: str | None) -> bool:
    return str(value or "") in NESTED_SCHEMA_MODES


SchemaFieldNode.model_rebuild()
