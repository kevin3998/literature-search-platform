from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from core.user_context import UserContext
from core.workspace_paths import user_workspace_root

TASK_ROOT_REL = "research_agent/structured_extraction/tasks"
TASK_DIRS = ("collection", "schemas", "evidence_packets", "prompts", "runs", "exports", "audit")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_task_id(task_id: str) -> str:
    if not isinstance(task_id, str):
        raise ValueError("task_id must be a string")
    value = task_id.strip()
    if (
        not value
        or value == ".."
        or ".." in value
        or "/" in value
        or "\\" in value
        or not _TASK_ID_RE.match(value)
    ):
        raise ValueError(f"invalid task_id: {task_id!r}")
    return value


def task_workspace_rel_path(task_id: str) -> str:
    return f"{TASK_ROOT_REL}/{validate_task_id(task_id)}"


def task_workspace_path(user: UserContext, task_id: str) -> Path:
    return user_workspace_root(user) / task_workspace_rel_path(task_id)


def ensure_task_workspace(user: UserContext, task: dict[str, Any]) -> Path:
    task_id = validate_task_id(task["task_id"])
    root = task_workspace_path(user, task_id)
    root.mkdir(parents=True, exist_ok=True)
    for dirname in TASK_DIRS:
        (root / dirname).mkdir(parents=True, exist_ok=True)
    write_task_manifest(user, task)
    return root


def write_task_manifest(user: UserContext, task: dict[str, Any]) -> None:
    task_id = validate_task_id(task["task_id"])
    root = task_workspace_path(user, task_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "task.json"
    tmp = path.with_name("task.json.tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_collection_candidates(user: UserContext, task_id: str, candidates: list[dict[str, Any]]) -> None:
    root = task_workspace_path(user, task_id) / "collection"
    write_jsonl(root / "candidates.jsonl", candidates)


def append_candidate_decision(user: UserContext, task_id: str, event: dict[str, Any]) -> None:
    root = task_workspace_path(user, task_id) / "collection"
    path = root / "candidate_decisions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def write_collection_version(user: UserContext, task_id: str, version: dict[str, Any]) -> None:
    root = task_workspace_path(user, task_id) / "collection"
    collection_version = version["collection_version"]
    suffix = collection_version.removeprefix("col_")
    json_path = root / f"collection_{suffix}.json"
    tmp = json_path.with_name(f"{json_path.name}.tmp")
    tmp.write_text(json.dumps(version, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(json_path)
    write_jsonl(root / f"paper_refs_{suffix}.jsonl", version.get("included_papers") or [])


def write_schema_draft(user: UserContext, task_id: str, draft: dict[str, Any]) -> None:
    root = task_workspace_path(user, task_id) / "schemas"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "draft.json"
    tmp = path.with_name("draft.json.tmp")
    tmp.write_text(json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_schema_version(user: UserContext, task_id: str, version: dict[str, Any]) -> None:
    root = task_workspace_path(user, task_id) / "schemas"
    root.mkdir(parents=True, exist_ok=True)
    schema_version = validate_task_id(version["schema_version"])
    path = root / f"{schema_version}.json"
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(version, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    write_jsonl(root / f"{schema_version}_fields.jsonl", version.get("fields") or [])


def append_schema_event(user: UserContext, task_id: str, event: dict[str, Any]) -> None:
    root = task_workspace_path(user, task_id) / "schemas"
    path = root / "schema_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def write_prompt_contract(user: UserContext, task_id: str, contract: dict[str, Any]) -> None:
    root = task_workspace_path(user, task_id) / "prompts"
    root.mkdir(parents=True, exist_ok=True)
    version = validate_task_id(contract["prompt_contract_version"])
    path = root / f"prompt_contract_{version}.json"
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    output_path = root / f"output_contract_{version}.json"
    output_tmp = output_path.with_name(f"{output_path.name}.tmp")
    output_tmp.write_text(
        json.dumps(contract.get("output_json_contract") or {}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    output_tmp.replace(output_path)


def write_evidence_packet_version(user: UserContext, task_id: str, packet: dict[str, Any], items: list[dict[str, Any]]) -> None:
    root = task_workspace_path(user, task_id) / "evidence_packets"
    root.mkdir(parents=True, exist_ok=True)
    version = validate_task_id(packet["packet_version"])
    path = root / f"packet_{version}.json"
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    write_jsonl(root / f"packet_{version}_items.jsonl", items)
    warnings = [{"warning": warning} if isinstance(warning, str) else warning for warning in (packet.get("warnings") or [])]
    write_jsonl(root / f"packet_{version}_warnings.jsonl", warnings)


def write_extraction_run(
    user: UserContext,
    task_id: str,
    run: dict[str, Any],
    items: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> None:
    root = task_workspace_path(user, task_id) / "runs"
    root.mkdir(parents=True, exist_ok=True)
    run_id = validate_task_id(run["run_id"])
    path = root / f"run_{run_id}.json"
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    write_jsonl(root / f"run_{run_id}_items.jsonl", items)
    write_jsonl(root / f"run_{run_id}_records.jsonl", records)
    errors = []
    prompts = []
    for item in items:
        if item.get("error"):
            errors.append(
                {
                    "run_item_id": item.get("run_item_id"),
                    "packet_item_id": item.get("packet_item_id"),
                    "paper_id": item.get("paper_id"),
                    "field_group": item.get("field_group"),
                    "error": item.get("error"),
                }
            )
        prompts.append(
            {
                "run_item_id": item.get("run_item_id"),
                "packet_item_id": item.get("packet_item_id"),
                "paper_id": item.get("paper_id"),
                "field_group": item.get("field_group"),
                "prompt": item.get("prompt") or {},
            }
        )
    write_jsonl(root / f"run_{run_id}_errors.jsonl", errors)
    write_jsonl(root / f"run_{run_id}_prompts.jsonl", prompts)


def write_review_artifacts(
    user: UserContext,
    task_id: str,
    run_id: str,
    events: list[dict[str, Any]],
    states: list[dict[str, Any]],
    effective_records: list[dict[str, Any]],
) -> None:
    root = task_workspace_path(user, task_id) / "audit"
    root.mkdir(parents=True, exist_ok=True)
    version = validate_task_id(run_id)
    write_jsonl(root / "review_events.jsonl", events)
    write_jsonl(root / f"review_field_states_{version}.jsonl", states)
    write_jsonl(root / f"effective_records_{version}.jsonl", effective_records)


def write_multimodal_review_artifacts(
    user: UserContext,
    task_id: str,
    run_id: str,
    jobs: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    root = task_workspace_path(user, task_id) / "audit"
    root.mkdir(parents=True, exist_ok=True)
    version = validate_task_id(run_id)
    write_jsonl(root / f"multimodal_jobs_{version}.jsonl", jobs)
    write_jsonl(root / f"multimodal_suggestions_{version}.jsonl", suggestions)
    path = root / f"review_summary_{version}.json"
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_export_artifacts(
    user: UserContext,
    task_id: str,
    export_id: str,
    files: dict[str, bytes | str],
    manifest: dict[str, Any],
) -> dict[str, str]:
    root = task_workspace_path(user, task_id)
    version = validate_task_id(export_id)
    export_root = root / "exports" / version
    export_root.mkdir(parents=True, exist_ok=True)
    manifest_name = f"export_{version}_manifest.json"
    manifest_path = export_root / manifest_name
    manifest_tmp = manifest_path.with_name(f"{manifest_path.name}.tmp")
    manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    manifest_tmp.replace(manifest_path)

    rel_root = f"{task_workspace_rel_path(task_id)}/exports/{version}"
    paths = {"manifest": f"{rel_root}/{manifest_name}"}
    for name, content in files.items():
        path = export_root / name
        tmp = path.with_name(f"{path.name}.tmp")
        if isinstance(content, bytes):
            tmp.write_bytes(content)
        else:
            tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        paths[_format_key_from_filename(name)] = f"{rel_root}/{name}"
    return paths


def _format_key_from_filename(name: str) -> str:
    suffix = Path(name).suffix.lower().lstrip(".")
    return "markdown" if suffix == "md" else suffix
