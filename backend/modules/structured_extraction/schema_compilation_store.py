from __future__ import annotations

import asyncio
import re
from typing import Any

from sqlalchemy.exc import IntegrityError

from core.db.types import new_uuid
from core.user_context import UserContext
from core.worker.queue import JobQueue

from .schema_contract import PAPER_METADATA_REGISTRY, SCHEMA_COMPILER_VERSION, SCHEMA_CONTRACT_VERSION
from .schema_coverage import coverage_report
from .schema_normalizer import field_tree_hash, normalize_field_tree
from .schema_validator import validate_compilation
from .schemas import SchemaCompilationApplyRequest, SchemaCompilationResolveRequest, SchemaDraftSaveRequest
from .store import StructuredExtractionStore, dumps, loads, now


class StructuredExtractionSchemaCompilationStore:
    def __init__(self, store: StructuredExtractionStore) -> None:
        self.store = store

    def create(self, task_id: str, source_text: str, result: dict[str, Any], *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        compilation_id = str(new_uuid())
        ts = now()
        self.store.conn.execute(
            """
            insert into structured_extraction_schema_compilations(
                compilation_id, task_id, user_id, source_text, source_format, status, schema_mode,
                execution_status, phase, progress,
                compiler_version, contract_version, requirements_json, mappings_json, record_schema_json,
                field_tree_json, global_instructions_json, coverage_json, validation_errors_json,
                warnings_json, normalization_changes_json, model_attempts_json, field_tree_hash,
                created_at, started_at, updated_at, completed_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                compilation_id, task_id, user.user_id, source_text, result.get("source_format") or "auto",
                result.get("status") or "failed", result.get("schema_mode") or "nested_record",
                "completed", "completed", 100,
                result.get("compiler_version") or "", result.get("contract_version") or "",
                dumps(result.get("requirements") or []), dumps(result.get("requirement_mappings") or []),
                dumps(result.get("record_schema") or {}), dumps(result.get("field_tree") or []),
                dumps(result.get("global_instructions") or []), dumps(result.get("coverage") or {}),
                dumps(result.get("validation_errors") or []), dumps(result.get("warnings") or []),
                dumps(result.get("normalization_changes") or []), dumps(result.get("model_attempts") or []),
                result.get("field_tree_hash") or field_tree_hash(result.get("field_tree") or []), ts, ts, ts, ts,
            ),
        )
        self.store.conn.commit()
        return self.get(task_id, compilation_id, user=user)

    def queue(self, task_id: str, request: dict[str, Any], *, user: UserContext) -> tuple[dict[str, Any], bool]:
        self.store.get_task(task_id, user_id=user.user_id)
        active = self.active(task_id, user=user)
        if active:
            return active, True
        compilation_id = str(new_uuid())
        ts = now()
        try:
            self.store.conn.execute(
                """
                insert into structured_extraction_schema_compilations(
                    compilation_id, task_id, user_id, source_text, source_format, status,
                    execution_status, phase, progress, request_json, schema_mode,
                    compiler_version, contract_version, requirements_json, mappings_json,
                    record_schema_json, field_tree_json, global_instructions_json, coverage_json,
                    validation_errors_json, warnings_json, normalization_changes_json,
                    model_attempts_json, field_tree_hash, created_at, updated_at
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    compilation_id, task_id, user.user_id, request.get("instruction") or "",
                    request.get("source_format") or "auto", "pending", "queued", "queued", 5,
                    dumps(request), "nested_record", SCHEMA_COMPILER_VERSION, SCHEMA_CONTRACT_VERSION,
                    dumps([]), dumps([]), dumps({}), dumps([]), dumps([]), dumps({}), dumps([]),
                    dumps([]), dumps([]), dumps([]), "", ts, ts,
                ),
            )
        except IntegrityError:
            active = self.active(task_id, user=user)
            if active:
                return active, True
            raise
        try:
            job = JobQueue(self.store.engine).enqueue(
                "structured.schema_compile",
                {"task_id": task_id, "compilation_id": compilation_id, "user_id": user.user_id},
                user_id=user.user_id,
                queue="structured-extraction",
            )
        except Exception as exc:
            self.fail(task_id, compilation_id, phase="queueing", error=exc, user=user)
            raise
        self.store.conn.execute(
            """
            update structured_extraction_schema_compilations set core_job_id = ?, updated_at = ?
            where task_id = ? and user_id = ? and compilation_id = ?
            """,
            (job["job_id"], now(), task_id, user.user_id, compilation_id),
        )
        return self.get(task_id, compilation_id, user=user), False

    def active(self, task_id: str, *, user: UserContext) -> dict[str, Any] | None:
        row = self.store.conn.execute(
            """
            select * from structured_extraction_schema_compilations
            where task_id = ? and user_id = ? and execution_status in ('queued', 'running')
            order by created_at desc limit 1
            """,
            (task_id, user.user_id),
        ).fetchone()
        return self._row(row) if row else None

    def update_progress(self, task_id: str, compilation_id: str, event: dict[str, Any], *, user: UserContext) -> dict[str, Any]:
        self.store.conn.execute(
            """
            update structured_extraction_schema_compilations
            set execution_status = 'running', phase = ?, progress = ?,
                started_at = coalesce(started_at, ?), updated_at = ?
            where task_id = ? and user_id = ? and compilation_id = ?
            """,
            (
                event["phase"], max(0, min(int(event.get("progress") or 0), 99)),
                now(), now(), task_id, user.user_id, compilation_id,
            ),
        )
        return self.get(task_id, compilation_id, user=user)

    def complete(self, task_id: str, compilation_id: str, result: dict[str, Any], *, user: UserContext) -> dict[str, Any]:
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_schema_compilations set
                status = ?, execution_status = 'completed', phase = 'completed', progress = 100,
                source_format = ?, schema_mode = ?, compiler_version = ?, contract_version = ?,
                requirements_json = ?, mappings_json = ?, record_schema_json = ?, field_tree_json = ?,
                global_instructions_json = ?, coverage_json = ?, validation_errors_json = ?,
                warnings_json = ?, normalization_changes_json = ?, model_attempts_json = ?,
                field_tree_hash = ?, error_json = null, completed_at = ?, updated_at = ?
            where task_id = ? and user_id = ? and compilation_id = ?
            """,
            (
                result.get("status") or "failed", result.get("source_format") or "auto",
                result.get("schema_mode") or "nested_record", result.get("compiler_version") or "",
                result.get("contract_version") or "", dumps(result.get("requirements") or []),
                dumps(result.get("requirement_mappings") or []), dumps(result.get("record_schema") or {}),
                dumps(result.get("field_tree") or []), dumps(result.get("global_instructions") or []),
                dumps(result.get("coverage") or {}), dumps(result.get("validation_errors") or []),
                dumps(result.get("warnings") or []), dumps(result.get("normalization_changes") or []),
                dumps(result.get("model_attempts") or []), result.get("field_tree_hash") or field_tree_hash(result.get("field_tree") or []),
                ts, ts, task_id, user.user_id, compilation_id,
            ),
        )
        return self.get(task_id, compilation_id, user=user)

    def fail(self, task_id: str, compilation_id: str, *, phase: str, error: Exception, user: UserContext) -> dict[str, Any]:
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_schema_compilations
            set status = 'failed', execution_status = 'failed', phase = ?, error_json = ?,
                completed_at = ?, updated_at = ?
            where task_id = ? and user_id = ? and compilation_id = ?
            """,
            (phase, dumps({"phase": phase, "message": str(error)}), ts, ts, task_id, user.user_id, compilation_id),
        )
        return self.get(task_id, compilation_id, user=user)

    def worker_entry(self, task_id: str, compilation_id: str, user_id: str) -> dict[str, Any]:
        return asyncio.run(self._run_worker(task_id, compilation_id, user_id))

    async def _run_worker(self, task_id: str, compilation_id: str, user_id: str) -> dict[str, Any]:
        from .llm_schema import assist_schema
        from .schemas import SchemaAssistRequest

        user = UserContext(user_id=user_id, workspace_slug=user_id)
        task = self.store.get_task(task_id, user_id=user_id)
        compilation = self.get(task_id, compilation_id, user=user)
        request = SchemaAssistRequest.model_validate(compilation["request"])
        queue = JobQueue(self.store.engine)
        current_phase = compilation["phase"]

        def on_progress(event: dict[str, Any]) -> None:
            nonlocal current_phase
            current_phase = event["phase"]
            self.update_progress(task_id, compilation_id, event, user=user)
            if compilation.get("core_job_id"):
                queue.append_event(compilation["core_job_id"], {"type": "schema_compilation_progress", **event})

        try:
            response = await assist_schema(request, task=task, user=user, on_progress=on_progress)
            result = response.get("result")
            if not isinstance(result, dict):
                raise ValueError(response.get("detail") or response.get("reason") or "schema_compilation_result_missing")
            return self.complete(task_id, compilation_id, result, user=user)
        except Exception as exc:
            self.fail(task_id, compilation_id, phase=current_phase, error=exc, user=user)
            raise

    def list(self, task_id: str, *, user: UserContext, limit: int = 20) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            """
            select * from structured_extraction_schema_compilations
            where task_id = ? and user_id = ? order by created_at desc limit ?
            """,
            (task_id, user.user_id, max(1, min(int(limit), 100))),
        ).fetchall()
        return {"task_id": task_id, "compilations": [self._row(row) for row in rows]}

    def get(self, task_id: str, compilation_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            """
            select * from structured_extraction_schema_compilations
            where task_id = ? and user_id = ? and compilation_id = ?
            """,
            (task_id, user.user_id, compilation_id),
        ).fetchone()
        if not row:
            raise KeyError(f"schema compilation not found: {compilation_id}")
        return self._row(row)

    def resolve(self, task_id: str, compilation_id: str, payload: SchemaCompilationResolveRequest, *, user: UserContext) -> dict[str, Any]:
        compilation = self.get(task_id, compilation_id, user=user)
        mappings = {item["requirement_id"]: dict(item) for item in compilation["requirement_mappings"]}
        field_tree = compilation["field_tree"]
        record_schema = compilation["record_schema"]
        global_instructions = compilation["global_instructions"]
        requirement_by_id = {item["requirement_id"]: item for item in compilation["requirements"]}
        for resolution in payload.resolutions:
            if resolution.requirement_id not in requirement_by_id:
                raise ValueError("requirement_not_found")
            previous = mappings.get(resolution.requirement_id) or {}
            if previous.get("disposition") == "global_instruction":
                global_instructions = [item for item in global_instructions if item.get("requirement_id") != resolution.requirement_id]
            if previous.get("disposition") == "user_schema":
                field_tree = _remove_requirement_nodes(field_tree, resolution.requirement_id)
            if resolution.disposition == "ignored_with_reason" and not resolution.reason.strip():
                raise ValueError("ignore_reason_required")
            if resolution.disposition == "system_metadata":
                key = resolution.target_path.removeprefix("paper_metadata.")
                if key not in PAPER_METADATA_REGISTRY:
                    raise ValueError("unknown_system_metadata_field")
            target_path = resolution.target_path
            if resolution.disposition == "user_schema" and resolution.node:
                nodes, _changes = normalize_field_tree([resolution.node])
                if not nodes:
                    raise ValueError("invalid_resolution_field")
                if re.fullmatch(r"req_\d+", nodes[0]["key"], flags=re.IGNORECASE) or nodes[0]["key"] == resolution.requirement_id:
                    raise ValueError("internal_requirement_id_cannot_be_field")
                nodes[0]["source_requirement_ids"] = [resolution.requirement_id]
                field_path = target_path.removeprefix("data.").strip(".")
                path_parts = [part for part in field_path.split(".") if part]
                if path_parts and path_parts[-1] == nodes[0]["key"]:
                    path_parts.pop()
                _insert_node(field_tree, ".".join(path_parts), nodes[0])
                target_path = f"data.{'.'.join([*path_parts, nodes[0]['key']])}"
            if resolution.disposition == "record_identity":
                key = resolution.target_path.removeprefix("record_identity.")
                if not key:
                    raise ValueError("record_identity_target_required")
                _apply_record_identity(record_schema, key)
            if resolution.disposition == "global_instruction":
                requirement = requirement_by_id[resolution.requirement_id]
                global_instructions = [item for item in global_instructions if item.get("requirement_id") != resolution.requirement_id]
                global_instructions.append({"requirement_id": resolution.requirement_id, "category": "extraction", "text": requirement.get("source_text") or ""})
            mappings[resolution.requirement_id] = {
                "requirement_id": resolution.requirement_id,
                "disposition": resolution.disposition,
                "target_path": target_path,
                "reason": resolution.reason or "user_resolution",
            }
        mapping_list = [mappings[item["requirement_id"]] for item in compilation["requirements"] if item["requirement_id"] in mappings]
        coverage = coverage_report(compilation["requirements"], mapping_list)
        errors = validate_compilation(record_schema, field_tree, compilation["requirements"], mapping_list, global_instructions)
        warnings = [item for item in compilation["warnings"] if item.get("code") != "unresolved_requirements"]
        if coverage["unresolved"]:
            warnings.append({"code": "unresolved_requirements", "count": coverage["unresolved"]})
        status = "needs_review" if coverage["unresolved"] or errors else ("valid_with_warnings" if warnings else "valid")
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_schema_compilations set status = ?, mappings_json = ?, record_schema_json = ?,
                field_tree_json = ?, global_instructions_json = ?, coverage_json = ?, validation_errors_json = ?,
                warnings_json = ?, field_tree_hash = ?, updated_at = ?
                where task_id = ? and user_id = ? and compilation_id = ?
            """,
            (status, dumps(mapping_list), dumps(record_schema), dumps(field_tree), dumps(global_instructions), dumps(coverage),
             dumps(errors), dumps(warnings), field_tree_hash(field_tree), ts, task_id, user.user_id, compilation_id),
        )
        self.store.conn.commit()
        return self.get(task_id, compilation_id, user=user)

    def apply(
        self,
        task_id: str,
        compilation_id: str,
        payload: SchemaCompilationApplyRequest,
        *,
        user: UserContext,
        schema_designer,
    ) -> dict[str, Any]:
        compilation = self.get(task_id, compilation_id, user=user)
        if compilation["status"] not in {"valid", "valid_with_warnings"}:
            raise PermissionError("schema_compilation_not_applicable")
        field_tree = compilation["field_tree"]
        global_instructions = compilation["global_instructions"]
        if payload.mode == "merge":
            draft = schema_designer.get_draft(task_id, user=user)
            field_tree = _merge_tree(draft.get("field_tree") or [], field_tree)
            global_instructions = _merge_instructions(draft.get("global_instructions") or [], global_instructions)
        return schema_designer.save_draft(
            task_id,
            SchemaDraftSaveRequest(
                schema_mode=compilation["schema_mode"],
                record_schema=compilation["record_schema"],
                field_tree=field_tree,
                global_instructions=global_instructions,
                source_compilation_id=compilation_id,
            ),
            user=user,
            provenance_modified=False,
        )

    @staticmethod
    def _row(row) -> dict[str, Any]:
        mappings = loads(row["mappings_json"], []) or []
        metadata_fields = sorted({
            str(item.get("target_path")).split(".", 1)[1]
            for item in mappings
            if item.get("disposition") == "system_metadata" and str(item.get("target_path") or "").startswith("paper_metadata.")
        })
        return {
            "compilation_id": str(row["compilation_id"]),
            "task_id": str(row["task_id"]),
            "user_id": str(row["user_id"]),
            "source_text": row["source_text"],
            "source_format": row["source_format"],
            "status": row["status"],
            "execution_status": row.get("execution_status") or "completed",
            "phase": row.get("phase") or "completed",
            "progress": int(row.get("progress") or 0),
            "core_job_id": str(row["core_job_id"]) if row.get("core_job_id") else None,
            "request": loads(row.get("request_json"), {}) or {},
            "error": loads(row.get("error_json"), None),
            "schema_mode": row["schema_mode"],
            "compiler_version": row["compiler_version"],
            "contract_version": row["contract_version"],
            "requirements": loads(row["requirements_json"], []) or [],
            "requirement_mappings": mappings,
            "record_schema": loads(row["record_schema_json"], {}) or {},
            "field_tree": loads(row["field_tree_json"], []) or [],
            "global_instructions": loads(row["global_instructions_json"], []) or [],
            "paper_metadata_fields": metadata_fields,
            "system_metadata_contract": {key: dict(value) for key, value in PAPER_METADATA_REGISTRY.items()},
            "coverage": loads(row["coverage_json"], {}) or {},
            "validation_errors": loads(row["validation_errors_json"], []) or [],
            "warnings": loads(row["warnings_json"], []) or [],
            "normalization_changes": loads(row["normalization_changes_json"], []) or [],
            "model_attempts": loads(row["model_attempts_json"], []) or [],
            "field_tree_hash": row["field_tree_hash"],
            "created_at": row["created_at"],
            "started_at": row.get("started_at"),
            "updated_at": row["updated_at"],
            "completed_at": row.get("completed_at"),
        }


def _insert_node(field_tree: list[dict[str, Any]], parent_path: str, node: dict[str, Any]) -> None:
    path = [part for part in parent_path.split(".") if part]
    if not path:
        field_tree.append(node)
        return
    nodes = field_tree
    for part in path:
        parent = next((item for item in nodes if item.get("key") == part), None)
        if not parent:
            raise ValueError("resolution_parent_not_found")
        parent["type"] = "object" if parent.get("type") not in {"object", "list_object"} else parent["type"]
        parent.setdefault("children", [])
        nodes = parent["children"]
    nodes.append(node)


def _remove_requirement_nodes(nodes: list[dict[str, Any]], requirement_id: str) -> list[dict[str, Any]]:
    out = []
    for node in nodes or []:
        item = dict(node)
        source_ids = [value for value in (item.get("source_requirement_ids") or []) if value != requirement_id]
        item["source_requirement_ids"] = source_ids
        item["children"] = _remove_requirement_nodes(item.get("children") or [], requirement_id)
        if requirement_id in (node.get("source_requirement_ids") or []) and not source_ids and not item["children"]:
            continue
        out.append(item)
    return out


def _apply_record_identity(record_schema: dict[str, Any], key: str) -> None:
    record_schema["record_identity_fields"] = list(dict.fromkeys([*(record_schema.get("record_identity_fields") or []), key]))
    record_schema["deduplication_keys"] = list(dict.fromkeys([*(record_schema.get("deduplication_keys") or []), key]))
    if key == "paper_id":
        return
    entity = re.sub(r"_(?:id|identifier|name|key|code|uuid)$", "", key).strip("_") or "entity"
    current_unit = record_schema.get("record_unit") or "paper_level"
    if current_unit != "paper_level" and record_schema.get("primary_entity") not in {None, "", "paper"}:
        record_schema["one_paper_may_have_multiple_records"] = True
        return
    candidate_unit = f"{entity}_level"
    allowed_units = {"material_level", "sample_level", "experiment_level", "condition_level"}
    record_schema["record_unit"] = candidate_unit if candidate_unit in allowed_units else "experiment_level"
    record_schema["primary_entity"] = entity
    record_schema["record_type"] = f"{entity}_record"
    record_schema["one_paper_may_have_multiple_records"] = True


def _merge_tree(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(item) for item in current]
    for node in incoming:
        existing = next((item for item in out if item.get("key") == node.get("key")), None)
        if not existing:
            out.append(dict(node))
            continue
        existing.update({key: value for key, value in node.items() if key != "children"})
        existing["children"] = _merge_tree(existing.get("children") or [], node.get("children") or [])
    for index, node in enumerate(out, start=1):
        node["order"] = index
    return out


def _merge_instructions(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = {item.get("requirement_id"): dict(item) for item in current if item.get("requirement_id")}
    for item in incoming:
        if item.get("requirement_id"):
            out[item["requirement_id"]] = dict(item)
    return list(out.values())
