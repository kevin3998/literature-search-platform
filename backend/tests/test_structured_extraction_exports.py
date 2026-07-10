from __future__ import annotations

import csv
import json
import zipfile

from test_structured_extraction_review import _client_with_completed_run


def _first_review_record(client, task_id: str, run_id: str) -> dict:
    table = client.get(f"/api/structured-extraction/tasks/{task_id}/review/table?run_id={run_id}", headers={"X-User-Id": "alice"})
    assert table.status_code == 200
    return table.json()["rows"][0]


def test_export_preview_requires_completed_run(monkeypatch, tmp_path):
    from test_structured_extraction_preparation import _client_with_schema

    client, task_id, _root = _client_with_schema(monkeypatch, tmp_path)

    response = client.get(f"/api/structured-extraction/tasks/{task_id}/exports/preview", headers={"X-User-Id": "alice"})

    assert response.status_code == 400
    assert "review_run_required" in response.json()["detail"]


def test_export_creates_files_downloads_and_snapshots_effective_records(monkeypatch, tmp_path):
    client, task_id, run_id, root = _client_with_completed_run(monkeypatch, tmp_path)
    row = _first_review_record(client, task_id, run_id)
    record_id = row["record_id"]
    edit_value = {
        "raw_value": "121 LMH",
        "normalized_value": 121,
        "unit": "LMH",
        "condition_context": "25 C",
        "evidence_text": "manual correction from table",
        "evidence_location": "Table 1",
        "extraction_note": "export snapshot value",
    }
    edit = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/water_flux/edit",
        json={"value": edit_value, "reason": "ready for export"},
        headers={"X-User-Id": "alice"},
    )
    assert edit.status_code == 200

    preview = client.get(f"/api/structured-extraction/tasks/{task_id}/exports/preview?run_id={run_id}", headers={"X-User-Id": "alice"})
    assert preview.status_code == 200
    assert preview.json()["record_count"] == 1
    assert preview.json()["field_count"] == 2
    assert preview.json()["review_status_counts"]

    created = client.post(
        f"/api/structured-extraction/tasks/{task_id}/exports",
        json={"run_id": run_id, "formats": ["csv", "json", "xlsx", "markdown"], "include_base_values": True, "include_review_metadata": True},
        headers={"X-User-Id": "alice"},
    )
    assert created.status_code == 200
    body = created.json()
    export_id = body["export_id"]
    assert body["formats"] == ["csv", "json", "xlsx", "markdown"]
    assert body["record_count"] == 1
    assert body["field_count"] == 2

    task = client.get(f"/api/structured-extraction/tasks/{task_id}", headers={"X-User-Id": "alice"}).json()
    assert task["status"] == "exported"
    assert task["stats"]["export_count"] == 1
    export_dir = root / "users" / task["user_id"] / task["workspace_rel_path"] / "exports" / export_id
    manifest_path = export_dir / f"export_{export_id}_manifest.json"
    json_path = export_dir / f"records_{export_id}.json"
    csv_path = export_dir / f"records_{export_id}.csv"
    xlsx_path = export_dir / f"records_{export_id}.xlsx"
    md_path = export_dir / f"records_{export_id}.md"
    for path in [manifest_path, json_path, csv_path, xlsx_path, md_path]:
        assert path.exists(), path

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["export_id"] == export_id
    assert manifest["run_id"] == run_id

    exported_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert exported_json["records"][0]["fields"]["water_flux"]["normalized_value"] == 121
    assert exported_json["records"][0]["paper"]["title"] == "Antifouling membrane performance"
    assert exported_json["records"][0]["paper_metadata"] == exported_json["records"][0]["paper"]
    assert exported_json["records"][0]["paper_metadata"]["authors"] == ["Alice"]

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert rows[0]["title"] == "Antifouling membrane performance"
    assert json.loads(rows[0]["authors_json"]) == ["Alice"]
    assert rows[0]["water_flux.normalized"] == "121"
    assert rows[0]["water_flux.evidence_text"] == "manual correction from table"
    assert "membrane_name.raw" in rows[0]

    with zipfile.ZipFile(xlsx_path) as archive:
        names = set(archive.namelist())
    assert "xl/workbook.xml" in names
    assert "xl/worksheets/sheet1.xml" in names
    assert "xl/worksheets/sheet2.xml" in names
    assert "xl/worksheets/sheet3.xml" in names

    markdown = md_path.read_text(encoding="utf-8")
    assert f"# 结构化抽取导出 {export_id}" in markdown
    assert "Antifouling membrane performance" in markdown

    downloaded_csv = client.get(
        f"/api/structured-extraction/tasks/{task_id}/exports/{export_id}/download?format=csv",
        headers={"X-User-Id": "alice"},
    )
    assert downloaded_csv.status_code == 200
    assert "text/csv" in downloaded_csv.headers["content-type"]
    assert "water_flux.normalized" in downloaded_csv.text

    downloaded_xlsx = client.get(
        f"/api/structured-extraction/tasks/{task_id}/exports/{export_id}/download?format=xlsx",
        headers={"X-User-Id": "alice"},
    )
    assert downloaded_xlsx.status_code == 200
    assert "spreadsheetml.sheet" in downloaded_xlsx.headers["content-type"]
    assert downloaded_xlsx.content.startswith(b"PK")

    later_edit = client.post(
        f"/api/structured-extraction/tasks/{task_id}/review/records/{record_id}/fields/water_flux/edit",
        json={"value": {**edit_value, "normalized_value": 999, "raw_value": "999 LMH"}, "reason": "after export"},
        headers={"X-User-Id": "alice"},
    )
    assert later_edit.status_code == 200
    assert json.loads(json_path.read_text(encoding="utf-8"))["records"][0]["fields"]["water_flux"]["normalized_value"] == 121

    listed = client.get(f"/api/structured-extraction/tasks/{task_id}/exports", headers={"X-User-Id": "alice"})
    assert listed.status_code == 200
    assert listed.json()["exports"][0]["export_id"] == export_id
    detail = client.get(f"/api/structured-extraction/tasks/{task_id}/exports/{export_id}", headers={"X-User-Id": "alice"})
    assert detail.status_code == 200
    assert detail.json()["files"]["json"].endswith(f"records_{export_id}.json")

    bob = client.get(f"/api/structured-extraction/tasks/{task_id}/exports", headers={"X-User-Id": "bob"})
    assert bob.status_code == 404


def test_export_rejects_unsupported_format(monkeypatch, tmp_path):
    client, task_id, run_id, _root = _client_with_completed_run(monkeypatch, tmp_path)

    response = client.post(
        f"/api/structured-extraction/tasks/{task_id}/exports",
        json={"run_id": run_id, "formats": ["xml"]},
        headers={"X-User-Id": "alice"},
    )

    assert response.status_code in {400, 422}
