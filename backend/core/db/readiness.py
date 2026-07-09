from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine


def check_postgres_connection(engine: Engine) -> dict:
    with engine.connect() as conn:
        value = conn.execute(text("select 1")).scalar_one()
    return {"status": "ok" if value == 1 else "error", "select_1": value}


def _default_alembic_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "alembic.ini"


def check_alembic_at_head(engine: Engine, *, config_path: str | Path | None = None) -> dict:
    config_path = config_path or _default_alembic_config_path()
    cfg = Config(str(config_path))
    script = ScriptDirectory.from_config(cfg)
    heads = set(script.get_heads())
    with engine.connect() as conn:
        schema = conn.execute(text("select current_schema()")).scalar_one()
        context = MigrationContext.configure(conn, opts={"version_table_schema": schema})
        current = set(context.get_current_heads())
    missing = sorted(heads - current)
    return {
        "status": "ok" if not missing else "error",
        "current": sorted(current),
        "head": sorted(heads),
        "missing": missing,
    }
