from __future__ import annotations

import csv
import io
import json
import zipfile
from html import escape as xml_escape
from pathlib import Path
from typing import Any

from core.user_context import UserContext

from .artifacts import task_workspace_path, write_export_artifacts
from .review import StructuredExtractionReviewService
from .schemas import DEFAULT_TASK_STATS, ExportCreateRequest
from .store import StructuredExtractionStore, dumps, loads, new_uuid, now

EXPORT_FORMATS = {"csv", "json", "xlsx", "markdown"}
MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "markdown": "text/markdown; charset=utf-8",
}


class StructuredExtractionExportService:
    def __init__(self, store: StructuredExtractionStore, review: StructuredExtractionReviewService, multimodal_review: Any | None = None) -> None:
        self.store = store
        self.review = review
        self.multimodal_review = multimodal_review

    def preview(self, task_id: str, *, user: UserContext, run_id: str | None = None) -> dict[str, Any]:
        task = self.store.get_task(task_id, user_id=user.user_id)
        run = self._resolve_run(task_id, user=user, run_id=run_id)
        rows = self._review_rows(task_id, run["run_id"], user=user)
        fields = self._schema_fields(task_id, run["schema_version"], user=user)
        summary = _summary(task, run, rows, fields)
        return {"task_id": task_id, "run_id": run["run_id"], **summary}

    def create(self, task_id: str, payload: ExportCreateRequest, *, user: UserContext) -> dict[str, Any]:
        task = self.store.get_task(task_id, user_id=user.user_id)
        formats = _validate_formats(payload.formats)
        run = self._resolve_run(task_id, user=user, run_id=payload.run_id)
        rows = self._review_rows(task_id, run["run_id"], user=user)
        fields = self._schema_fields(task_id, run["schema_version"], user=user)
        if not rows:
            raise ValueError("export_records_required")
        export_id = new_uuid()
        ts = now()
        settings = {
            "include_rejected": payload.include_rejected,
            "include_base_values": payload.include_base_values,
            "include_review_metadata": payload.include_review_metadata,
        }
        summary = _summary(task, run, rows, fields)
        multimodal_provenance = self._multimodal_provenance(task_id, run["run_id"], user=user)
        export_records = _export_records(rows, fields, settings)
        manifest = {
            "export_id": export_id,
            "task_id": task_id,
            "run_id": run["run_id"],
            "collection_version": run["collection_version"],
            "schema_version": run["schema_version"],
            "formats": formats,
            "settings": settings,
            "record_count": summary["record_count"],
            "field_count": summary["field_count"],
            "review_status_counts": summary["review_status_counts"],
            "multimodal_provenance": multimodal_provenance,
            "warnings": summary["warnings"],
            "created_at": ts,
        }
        flat_rows, long_rows = _flat_rows(export_records, fields)
        json_doc = {"manifest": manifest, "records": export_records}
        files: dict[str, bytes | str] = {}
        if "json" in formats:
            files[f"records_{export_id}.json"] = json.dumps(json_doc, ensure_ascii=False, indent=2, sort_keys=True)
        if "csv" in formats:
            files[f"records_{export_id}.csv"] = _csv_text(flat_rows)
        if "xlsx" in formats:
            files[f"records_{export_id}.xlsx"] = _xlsx_bytes(flat_rows, long_rows, manifest)
        if "markdown" in formats:
            files[f"records_{export_id}.md"] = _markdown_text(export_id, task, run, export_records, manifest)
        paths = write_export_artifacts(user, task_id, export_id, files, manifest)
        row = {
            "export_id": export_id,
            "task_id": task_id,
            "run_id": run["run_id"],
            "collection_version": run["collection_version"],
            "schema_version": run["schema_version"],
            "record_count": summary["record_count"],
            "field_count": summary["field_count"],
            "formats": formats,
            "files": paths,
            "review_status_counts": summary["review_status_counts"],
            "multimodal_provenance": multimodal_provenance,
            "top_level_section_count": summary.get("top_level_section_count", 0),
            "leaf_path_count": summary.get("leaf_path_count", 0),
            "warnings": summary["warnings"],
            "created_at": ts,
        }
        self.store.conn.execute(
            """
            insert into structured_extraction_exports(
                task_id, export_id, user_id, run_id, collection_version, schema_version,
                formats_json, files_json, settings_json, summary_json, record_count, field_count, created_at
            ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                export_id,
                user.user_id,
                run["run_id"],
                run["collection_version"],
                run["schema_version"],
                dumps(formats),
                dumps(paths),
                dumps(settings),
                dumps({
                    "review_status_counts": summary["review_status_counts"],
                    "multimodal_provenance": multimodal_provenance,
                    "warnings": summary["warnings"],
                    "top_level_section_count": summary.get("top_level_section_count", 0),
                    "leaf_path_count": summary.get("leaf_path_count", 0),
                }),
                summary["record_count"],
                summary["field_count"],
                ts,
            ),
        )
        self._mark_exported(task_id, user=user)
        self.store.conn.commit()
        return row

    def list_exports(self, task_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        rows = self.store.conn.execute(
            "select * from structured_extraction_exports where task_id = ? and user_id = ? order by created_at desc",
            (task_id, user.user_id),
        ).fetchall()
        return {"task_id": task_id, "exports": [_row_to_export(row) for row in rows]}

    def get(self, task_id: str, export_id: str, *, user: UserContext) -> dict[str, Any]:
        self.store.get_task(task_id, user_id=user.user_id)
        row = self.store.conn.execute(
            "select * from structured_extraction_exports where task_id = ? and user_id = ? and export_id = ?",
            (task_id, user.user_id, export_id),
        ).fetchone()
        if not row:
            raise KeyError(f"export not found: {export_id}")
        return _row_to_export(row)

    def download_path(self, task_id: str, export_id: str, export_format: str, *, user: UserContext) -> tuple[Path, str]:
        if export_format not in EXPORT_FORMATS:
            raise ValueError("unsupported_export_format")
        export = self.get(task_id, export_id, user=user)
        rel_path = (export.get("files") or {}).get(export_format)
        if not rel_path:
            raise KeyError(f"export file not found: {export_format}")
        root = task_workspace_path(user, task_id)
        path = root / "exports" / export_id / Path(rel_path).name
        if not path.exists():
            raise KeyError(f"export file not found: {export_format}")
        return path, MEDIA_TYPES[export_format]

    def _resolve_run(self, task_id: str, *, user: UserContext, run_id: str | None) -> dict[str, Any]:
        return self.review._resolve_run(task_id, user=user, run_id=run_id)  # noqa: SLF001

    def _review_rows(self, task_id: str, run_id: str, *, user: UserContext) -> list[dict[str, Any]]:
        self.review._ensure_states(task_id, run_id, user=user)  # noqa: SLF001
        return self.review._review_rows(task_id, run_id, user=user)  # noqa: SLF001

    def _schema_fields(self, task_id: str, schema_version: str, *, user: UserContext) -> list[dict[str, Any]]:
        return self.review._schema_fields(task_id, schema_version, user=user)  # noqa: SLF001

    def _mark_exported(self, task_id: str, *, user: UserContext) -> None:
        task = self.store.get_task(task_id, user_id=user.user_id)
        stats = dict(DEFAULT_TASK_STATS)
        stats.update(task.get("stats") or {})
        stats["export_count"] = int(stats.get("export_count") or 0) + 1
        ts = now()
        self.store.conn.execute(
            """
            update structured_extraction_tasks
            set status = 'exported', stats_json = ?, updated_at = ?
            where task_id = ? and user_id = ?
            """,
            (dumps(stats), ts, task_id, user.user_id),
        )
        self.store._insert_event(task_id, user.user_id, "exported", {"export_count": stats["export_count"]})  # noqa: SLF001

    def _multimodal_provenance(self, task_id: str, run_id: str, *, user: UserContext) -> dict[str, Any]:
        if not self.multimodal_review:
            return {"job_count": 0, "suggestion_status_counts": {}}
        return self.multimodal_review.provenance_summary(task_id, run_id, user=user)


def _validate_formats(formats: list[str]) -> list[str]:
    out = []
    for item in formats or ["csv", "json", "xlsx", "markdown"]:
        if item not in EXPORT_FORMATS:
            raise ValueError("unsupported_export_format")
        if item not in out:
            out.append(item)
    return out


def _summary(task: dict[str, Any], run: dict[str, Any], rows: list[dict[str, Any]], fields: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status = row.get("review_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    warnings = []
    if any(status in {"unreviewed", "partially_reviewed"} for status in status_counts):
        warnings.append("unreviewed_fields_present")
    top_level_keys = set()
    leaf_paths = set()
    for row in rows:
        data = row.get("data") or {}
        if data:
            top_level_keys.update(data.keys())
            leaf_paths.update(_flatten_json(data).keys())
    if any(isinstance(value, (list, dict)) for row in rows for value in _flatten_json(row.get("data") or {}).values()):
        warnings.append("nested_values_serialized_as_json_cells")
    return {
        "record_count": len(rows),
        "field_count": len(fields),
        "top_level_section_count": len(top_level_keys),
        "leaf_path_count": len(leaf_paths),
        "review_status_counts": status_counts,
        "warnings": warnings,
        "collection_version": run.get("collection_version"),
        "schema_version": run.get("schema_version"),
        "task_status": task.get("status"),
    }


def _export_records(rows: list[dict[str, Any]], fields: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    field_order = [field["key"] for field in fields]
    records = []
    for row in rows:
        values = {}
        field_details = {}
        for key in field_order:
            field = (row.get("fields") or {}).get(key) or {}
            if field.get("status") == "rejected" and not settings.get("include_rejected"):
                continue
            values[key] = field.get("effective_value")
            detail = {
                "status": field.get("status"),
                "locked": bool(field.get("locked")),
                "quality_flags": field.get("quality_flags") or [],
                "review_priority": field.get("review_priority"),
                "provenance": field.get("provenance") or {},
            }
            if settings.get("include_base_values"):
                detail["base_value"] = field.get("base_value")
            field_details[key] = detail
        records.append(
            {
                "record_id": row.get("record_id"),
                "run_id": row.get("run_id"),
                "paper_id": row.get("paper_id"),
                "paper_metadata": row.get("paper_metadata") or row.get("paper") or {},
                "paper": row.get("paper_metadata") or row.get("paper") or {},
                "record_type": row.get("record_type"),
                "record_index": row.get("record_index"),
                "record_identity": row.get("record_identity") or {},
                "data": row.get("data") or {},
                "fields": values,
                "field_details": field_details if settings.get("include_review_metadata") else {},
                "review_status": row.get("review_status"),
                "review_priority": row.get("review_priority"),
                "record_quality_flags": row.get("record_quality_flags") or [],
            }
        )
    return records


def _flat_rows(records: list[dict[str, Any]], fields: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    field_order = [field["key"] for field in fields]
    flat = []
    long = []
    for record in records:
        paper = record.get("paper_metadata") or record.get("paper") or {}
        row = {
            "record_id": record.get("record_id"),
            "run_id": record.get("run_id"),
            "paper_id": record.get("paper_id"),
            "title": paper.get("title") or "",
            "year": paper.get("year") or "",
            "journal": paper.get("journal") or "",
            "doi": paper.get("doi") or "",
            "authors_json": _json_cell(paper.get("authors") or []),
            "record_type": record.get("record_type") or "",
            "record_index": record.get("record_index") or "",
            "record_identity_json": _json_cell(record.get("record_identity") or {}),
            "review_status": record.get("review_status") or "",
            "review_priority": record.get("review_priority") or "",
            "record_quality_flags": ", ".join(record.get("record_quality_flags") or []),
        }
        for key in field_order:
            value = (record.get("fields") or {}).get(key)
            details = (record.get("field_details") or {}).get(key) or {}
            cells = _value_cells(value)
            for suffix, cell_value in cells.items():
                row[f"{key}.{suffix}"] = cell_value
            row[f"{key}.json"] = _json_cell(value)
            long.append(
                {
                    "record_id": record.get("record_id"),
                    "paper_id": record.get("paper_id"),
                    "field_key": key,
                    **cells,
                    "value_json": _json_cell(value),
                    "status": details.get("status") or "",
                    "review_priority": details.get("review_priority") or "",
                    "quality_flags": ", ".join(details.get("quality_flags") or []),
                }
            )
        data = record.get("data") or {}
        if data:
            for path, value in _flatten_json(data).items():
                row[path] = _json_cell(value) if isinstance(value, (dict, list)) else (value if value is not None else "")
        flat.append(row)
    return flat, long


def _flatten_json(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value} if prefix else {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            nested = _flatten_json(item, path)
            if nested:
                out.update(nested)
            else:
                out[path] = {}
        elif isinstance(item, list):
            out[path] = item
        else:
            out[path] = item
    return out


def _value_cells(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "raw": value.get("raw_value") or value.get("rawValue") or "",
            "normalized": value.get("normalized_value") if value.get("normalized_value") is not None else value.get("normalizedValue") or "",
            "unit": value.get("unit") or "",
            "evidence_text": value.get("evidence_text") or value.get("evidenceText") or "",
            "evidence_location": value.get("evidence_location") or value.get("evidenceLocation") or "",
            "note": value.get("extraction_note") or value.get("extractionNote") or "",
        }
    return {"raw": value if value is not None else "", "normalized": "", "unit": "", "evidence_text": "", "evidence_location": "", "note": ""}


def _csv_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + output.getvalue()


def _xlsx_bytes(flat_rows: list[dict[str, Any]], long_rows: list[dict[str, Any]], manifest: dict[str, Any]) -> bytes:
    sheets = [
        ("records_flat", flat_rows),
        ("field_values_long", long_rows),
        ("manifest", [{"key": key, "value": _json_cell(value) if isinstance(value, (dict, list)) else value} for key, value in manifest.items()]),
    ]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels_xml())
        archive.writestr("xl/workbook.xml", _workbook_xml([name for name, _rows in sheets]))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheets)))
        archive.writestr("xl/styles.xml", "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><fonts count=\"1\"><font/></fonts><fills count=\"1\"><fill/></fills><borders count=\"1\"><border/></borders><cellStyleXfs count=\"1\"><xf/></cellStyleXfs><cellXfs count=\"1\"><xf/></cellXfs></styleSheet>")
        for index, (_name, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _sheet_xml(rows))
    return out.getvalue()


def _sheet_xml(rows: list[dict[str, Any]]) -> str:
    headers = list(rows[0].keys()) if rows else []
    matrix = [headers] + [[row.get(header, "") for header in headers] for row in rows]
    body = []
    for r_idx, row in enumerate(matrix, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            ref = f"{_column_name(c_idx)}{r_idx}"
            cells.append(f"<c r=\"{ref}\" t=\"inlineStr\"><is><t>{xml_escape(str(value if value is not None else ''))}</t></is></c>")
        body.append(f"<row r=\"{r_idx}\">{''.join(cells)}</row>")
    return f"<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>{''.join(body)}</sheetData></worksheet>"


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml(sheet_count: int) -> str:
    sheets = "".join(f"<Override PartName=\"/xl/worksheets/sheet{i}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>" for i in range(1, sheet_count + 1))
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/><Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>{sheets}</Types>"


def _root_rels_xml() -> str:
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>"


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(f"<sheet name=\"{xml_escape(name)}\" sheetId=\"{idx}\" r:id=\"rId{idx}\"/>" for idx, name in enumerate(sheet_names, start=1))
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets>{sheets}</sheets></workbook>"


def _workbook_rels_xml(sheet_count: int) -> str:
    rels = "".join(f"<Relationship Id=\"rId{i}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet{i}.xml\"/>" for i in range(1, sheet_count + 1))
    rels += f"<Relationship Id=\"rId{sheet_count + 1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
    return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">{rels}</Relationships>"


def _markdown_text(export_id: str, task: dict[str, Any], run: dict[str, Any], records: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    lines = [
        f"# 结构化抽取导出 {export_id}",
        "",
        f"- 任务：{task.get('name') or task.get('task_id')}",
        f"- Run：{run.get('run_id')}",
        f"- Collection：{run.get('collection_version')}",
        f"- Schema：{run.get('schema_version')}",
        f"- 记录数：{manifest.get('record_count')}",
        "",
    ]
    for record in records:
        paper = record.get("paper_metadata") or record.get("paper") or {}
        lines.extend(
            [
                f"## {paper.get('title') or record.get('paper_id')}",
                "",
                f"- 文献 ID：{record.get('paper_id')}",
                f"- 记录 ID：{record.get('record_id')}",
                f"- 审阅状态：{record.get('review_status')}",
                "",
                "| 字段 | 原始值 | 标准化值 | 单位 | 证据 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for key, value in (record.get("fields") or {}).items():
            cells = _value_cells(value)
            lines.append(f"| {key} | {cells['raw']} | {cells['normalized']} | {cells['unit']} | {cells['evidence_location'] or cells['evidence_text']} |")
        if record.get("data"):
            lines.extend(["", "```json", json.dumps(record.get("data"), ensure_ascii=False, indent=2, sort_keys=True), "```"])
        lines.append("")
    return "\n".join(lines)


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _row_to_export(row) -> dict[str, Any]:
    summary = loads(row["summary_json"], {}) or {}
    return {
        "export_id": row["export_id"],
        "task_id": row["task_id"],
        "run_id": row["run_id"],
        "collection_version": row["collection_version"],
        "schema_version": row["schema_version"],
        "record_count": row["record_count"],
        "field_count": row["field_count"],
        "formats": loads(row["formats_json"], []) or [],
        "files": loads(row["files_json"], {}) or {},
        "review_status_counts": summary.get("review_status_counts") or {},
        "multimodal_provenance": summary.get("multimodal_provenance") or {"job_count": 0, "suggestion_status_counts": {}},
        "top_level_section_count": summary.get("top_level_section_count") or 0,
        "leaf_path_count": summary.get("leaf_path_count") or 0,
        "warnings": summary.get("warnings") or [],
        "created_at": row["created_at"],
    }
