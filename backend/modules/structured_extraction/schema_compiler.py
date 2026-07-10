from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from .schema_contract import (
    CompilationResult,
    PAPER_METADATA_REGISTRY,
    SCHEMA_COMPILER_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from .schema_coverage import coverage_report, derive_requirement_mappings
from .schema_normalizer import field_tree_hash, normalize_field_tree, normalize_record_schema, remove_record_identity_nodes
from .schema_source_parser import ParsedSource, parse_schema_source
from .schema_validator import validate_compilation

StructuredGenerator = Callable[[list[dict[str, Any]], dict[str, Any], str], Awaitable[dict[str, Any]]]
ProgressCallback = Callable[[dict[str, Any]], None]


COMPILATION_PHASES = {
    "source_parsing": {"progress": 10, "indeterminate": False},
    "requirement_graph": {"progress": 20, "indeterminate": False},
    "semantic_compile": {"progress": 35, "indeterminate": True},
    "normalization": {"progress": 60, "indeterminate": False},
    "validation": {"progress": 72, "indeterminate": False},
    "targeted_repair": {"progress": 78, "indeterminate": True},
    "final_validation": {"progress": 90, "indeterminate": False},
    "completed": {"progress": 100, "indeterminate": False},
}


async def compile_schema_definition(
    *,
    instruction: str,
    source_format: str,
    draft: dict[str, Any] | None,
    task: dict[str, Any],
    generate_structured: StructuredGenerator | None,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    _emit_progress(on_progress, "source_parsing")
    parsed = parse_schema_source(instruction, source_format)
    _emit_progress(on_progress, "requirement_graph", requirement_count=len(parsed.requirements))
    deterministic_tree = parsed.field_tree
    model_attempts: list[dict[str, Any]] = []
    model_result: dict[str, Any] = {}
    llm_available = generate_structured is not None
    if generate_structured is not None:
        _emit_progress(on_progress, "semantic_compile", attempt=1)
        model_result = await _run_model(
            generate_structured,
            parsed=parsed,
            task=task,
            draft=draft or {},
            errors=[],
            attempt=1,
            attempts=model_attempts,
        )
    _emit_progress(on_progress, "normalization")
    result = _assemble_result(parsed, deterministic_tree, model_result, model_attempts=model_attempts, llm_available=llm_available)
    _emit_progress(on_progress, "validation", unresolved=result["coverage"]["unresolved"], error_count=len(result["validation_errors"]))
    model_failed = bool(model_attempts and model_attempts[-1].get("status") == "failed")
    if generate_structured is not None and (result["validation_errors"] or result["coverage"]["unresolved"] or model_failed):
        repair_errors = list(result["validation_errors"])
        if model_failed:
            repair_errors.append({"code": "llm_structured_output_failed", "message": model_attempts[-1].get("error") or "structured output failed"})
        _emit_progress(on_progress, "targeted_repair", attempt=2)
        repaired = await _run_model(
            generate_structured,
            parsed=parsed,
            task=task,
            draft=draft or {},
            errors=repair_errors + [
                {"code": "unresolved_requirement", "requirement_id": req_id}
                for req_id in result["coverage"]["unresolved_requirement_ids"]
            ],
            attempt=2,
            attempts=model_attempts,
            current=result,
        )
        _emit_progress(on_progress, "final_validation")
        result = _assemble_result(parsed, deterministic_tree, repaired, model_attempts=model_attempts, llm_available=True)
    validated = CompilationResult.model_validate(result).model_dump(mode="json")
    _emit_progress(on_progress, "completed", status=validated["status"])
    return validated


def _emit_progress(callback: ProgressCallback | None, phase: str, **details: Any) -> None:
    if callback is None:
        return
    callback({"phase": phase, **COMPILATION_PHASES[phase], **details})


def _assemble_result(
    parsed: ParsedSource,
    deterministic_tree: list[dict[str, Any]],
    model_result: dict[str, Any],
    *,
    model_attempts: list[dict[str, Any]],
    llm_available: bool,
) -> dict[str, Any]:
    model_tree, model_changes = normalize_field_tree(model_result)
    field_tree = model_tree or deterministic_tree
    if deterministic_tree:
        field_tree = _preserve_source_requirements(field_tree, deterministic_tree)
    record_schema, record_changes = normalize_record_schema(model_result.get("record_schema") or model_result.get("recordSchema") or {})
    field_tree, identity_changes = remove_record_identity_nodes(field_tree, record_schema)
    model_mappings = model_result.get("requirement_mappings") or model_result.get("requirementMappings") or []
    mappings = derive_requirement_mappings(parsed.requirements, field_tree, record_schema, model_mappings)
    global_instructions = _global_instructions(parsed.requirements, mappings, model_result)
    coverage = coverage_report(parsed.requirements, mappings)
    errors = validate_compilation(record_schema, field_tree, parsed.requirements, mappings, global_instructions)
    warnings: list[dict[str, Any]] = []
    if not llm_available:
        warnings.append({"code": "llm_unavailable", "message": "LLM semantic enrichment was unavailable"})
    failed_attempts = [item for item in model_attempts if item.get("status") == "failed"]
    if failed_attempts:
        recovered = bool(model_attempts and model_attempts[-1].get("status") == "completed")
        warnings.append({
            "code": "llm_structured_output_recovered" if recovered else "llm_structured_output_failed",
            "message": failed_attempts[-1].get("error") or "LLM structured output failed",
            "attempt_count": len(model_attempts),
        })
    if coverage["unresolved"]:
        warnings.append({"code": "unresolved_requirements", "count": coverage["unresolved"]})
    if errors:
        status = "needs_review" if field_tree else "failed"
    elif coverage["unresolved"]:
        status = "needs_review"
    elif warnings or model_changes or record_changes:
        status = "valid_with_warnings"
    else:
        status = "valid"
    if not llm_available and not field_tree:
        status = "llm_unavailable"
    metadata_fields = sorted({item.get("target_path", "").split(".", 1)[1] for item in mappings if item.get("disposition") == "system_metadata" and "." in item.get("target_path", "")})
    return {
        "status": status,
        "source_format": parsed.source_format,
        "schema_mode": "nested_record",
        "compiler_version": SCHEMA_COMPILER_VERSION,
        "contract_version": SCHEMA_CONTRACT_VERSION,
        "record_schema": record_schema,
        "field_tree": field_tree,
        "paper_metadata_fields": metadata_fields,
        "system_metadata_contract": {key: dict(value) for key, value in PAPER_METADATA_REGISTRY.items()},
        "global_instructions": global_instructions,
        "requirements": parsed.requirements,
        "requirement_mappings": mappings,
        "coverage": coverage,
        "validation_errors": errors,
        "warnings": warnings,
        "normalization_changes": record_changes + model_changes + identity_changes,
        "model_attempts": list(model_attempts),
        "field_tree_hash": field_tree_hash(field_tree),
    }


async def _run_model(
    generator: StructuredGenerator,
    *,
    parsed: ParsedSource,
    task: dict[str, Any],
    draft: dict[str, Any],
    errors: list[dict[str, Any]],
    attempt: int,
    attempts: list[dict[str, Any]],
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "task": {"task_id": task.get("task_id"), "name": task.get("name")},
        "source_format": parsed.source_format,
        "source_text": parsed.source_text,
        "requirements": parsed.requirements,
        "deterministic_field_tree": parsed.field_tree,
        "current_draft": draft,
        "system_metadata_registry": PAPER_METADATA_REGISTRY,
        "validation_errors": errors,
        "current_compilation": current or {},
        "rules": [
            "Return one mapping for every requirement_id.",
            "Never remove source-declared requirements.",
            "Map platform-provided publication fields to system_metadata.",
            "Put selection and grouping behavior in global_instructions.",
            "Use nested_record and the allowed field types only.",
        ],
    }
    messages = [{"role": "user", "content": "Compile this requirement graph into a validated structured extraction schema.\n\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
    try:
        result = await generator(messages, _structured_output_schema(), "submit_schema_compilation")
        attempts.append({"attempt": attempt, "status": "completed", "result_keys": sorted(result.keys())})
        return result
    except Exception as exc:  # noqa: BLE001
        attempts.append({"attempt": attempt, "status": "failed", "error": str(exc)})
        return {}


def _preserve_source_requirements(model_tree: list[dict[str, Any]], source_tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_by_path: dict[str, list[str]] = {}
    def collect(nodes: list[dict[str, Any]], prefix: str = "") -> None:
        for node in nodes:
            path = f"{prefix}.{node['key']}" if prefix else node["key"]
            source_by_path[path] = list(node.get("source_requirement_ids") or [])
            collect(node.get("children") or [], path)
    def apply(nodes: list[dict[str, Any]], prefix: str = "") -> None:
        for node in nodes:
            path = f"{prefix}.{node['key']}" if prefix else node["key"]
            if not node.get("source_requirement_ids") and path in source_by_path:
                node["source_requirement_ids"] = source_by_path[path]
            apply(node.get("children") or [], path)
    collect(source_tree)
    apply(model_tree)
    return model_tree


def _global_instructions(requirements: list[dict[str, Any]], mappings: list[dict[str, Any]], model_result: dict[str, Any]) -> list[dict[str, Any]]:
    requirement_by_id = {item["requirement_id"]: item for item in requirements}
    out = []
    for mapping in mappings:
        if mapping.get("disposition") != "global_instruction":
            continue
        requirement = requirement_by_id.get(mapping.get("requirement_id"))
        if requirement:
            kind = requirement.get("kind")
            category = "selection" if kind == "selection_rule" else "grouping" if kind == "grouping_rule" else "extraction"
            out.append({"requirement_id": requirement["requirement_id"], "category": category, "text": requirement.get("source_text") or ""})
    for item in model_result.get("global_instructions") or model_result.get("globalInstructions") or []:
        if isinstance(item, dict) and item.get("requirement_id") and item.get("text") and not any(existing["requirement_id"] == item["requirement_id"] for existing in out):
            out.append({"requirement_id": item["requirement_id"], "category": item.get("category") or "extraction", "text": item["text"]})
    return out


def _structured_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "record_schema": {"type": "object"},
            "field_tree": {"type": "array", "items": {"type": "object"}},
            "requirement_mappings": {"type": "array", "items": {"type": "object"}},
            "global_instructions": {"type": "array", "items": {"type": "object"}},
            "warnings": {"type": "array"},
        },
        "required": ["record_schema", "field_tree", "requirement_mappings"],
    }
