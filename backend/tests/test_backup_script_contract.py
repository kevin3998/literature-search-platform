from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def test_backup_script_contract_is_postgres_and_file_aware():
    script = Path("scripts/backup_platform.sh").read_text(encoding="utf-8")

    assert "DATABASE_URL" in script
    assert "pg_dump" in script
    assert "--format=custom" in script
    assert "LITERATURE_USER_DATA_ROOT" in script
    assert "LITERATURE_SECRET_KEY_PATH" in script
    assert "BACKUP_KEEP_DAYS" in script
    assert "manifest" in script
    assert "safe_database_url" in script
    assert "BACKUP_DRY_RUN" in script
    assert "password" not in script.lower()


def test_backup_script_dry_run_writes_manifest_without_dumping_or_archiving(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "BACKUP_DIR": str(tmp_path),
            "BACKUP_DRY_RUN": "1",
            "DATABASE_URL": "postgresql+psycopg://user:secret@127.0.0.1:5432/literature_agent",
            "LITERATURE_USER_DATA_ROOT": str(tmp_path / "users"),
            "LITERATURE_DATA_DIR": str(tmp_path / "large-literature-data"),
            "LITERATURE_SECRET_KEY_PATH": str(tmp_path / "secret.key"),
        }
    )
    (tmp_path / "users").mkdir()
    (tmp_path / "large-literature-data").mkdir()
    (tmp_path / "secret.key").write_text("not-a-real-fernet-key", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/backup_platform.sh"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifests = list(tmp_path.glob("*-manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["dry_run"] is True
    assert "secret" not in manifest["safe_database_url"]
    assert not list(tmp_path.glob("*.pgdump"))
    assert not list(tmp_path.glob("*.tar.gz"))
