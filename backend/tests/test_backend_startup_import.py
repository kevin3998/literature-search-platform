from __future__ import annotations

import os
import subprocess
import sys

from postgres_test_utils import migrated_postgres_schema


def _reload_main():
    import importlib

    import main

    return importlib.reload(main)


def test_backend_app_imports_with_attachment_routes() -> None:
    with migrated_postgres_schema():
        import multipart  # noqa: F401

        main = _reload_main()

    routes = {getattr(route, "path", "") for route in main.app.routes}
    assert "/api/sessions/{session_id}/attachments" in routes


def test_backend_import_fails_without_database_url() -> None:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("TEST_DATABASE_URL", None)
    env["PYTHONPATH"] = "backend"
    result = subprocess.run(
        [sys.executable, "-c", "import main"],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "DATABASE_URL is required" in result.stderr
