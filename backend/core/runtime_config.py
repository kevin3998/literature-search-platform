from __future__ import annotations

import os
from pathlib import Path

from core.db.config import DatabaseConfigError, app_env

DEFAULT_DEV_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
DEFAULT_SECRET_KEY_PATH = Path.home() / ".literature-agent" / "secret.key"


def csv_env(name: str) -> list[str]:
    raw = os.getenv(name) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def cors_allow_origins() -> list[str]:
    configured = csv_env("CORS_ALLOW_ORIGINS")
    if configured:
        origins = configured
    elif app_env() == "development":
        origins = list(DEFAULT_DEV_CORS_ORIGINS)
    else:
        origins = []
    if app_env() == "production" and "*" in origins:
        raise DatabaseConfigError("CORS_ALLOW_ORIGINS cannot include '*' when APP_ENV=production")
    return origins


def worker_required() -> bool:
    raw = os.getenv("WORKER_REQUIRED")
    if raw is None:
        return app_env() == "production"
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def secret_key_path() -> Path:
    return Path(os.getenv("LITERATURE_SECRET_KEY_PATH") or DEFAULT_SECRET_KEY_PATH).expanduser()


def check_secret_key_policy() -> dict:
    configured = os.getenv("LITERATURE_SECRET_KEY_PATH")
    path = secret_key_path()
    production = app_env() == "production"
    if production and not configured:
        raise DatabaseConfigError("LITERATURE_SECRET_KEY_PATH is required when APP_ENV=production")
    if production and not path.is_file():
        raise DatabaseConfigError("LITERATURE_SECRET_KEY_PATH must point to an existing readable key file when APP_ENV=production")
    if production and not os.access(path, os.R_OK):
        raise DatabaseConfigError("LITERATURE_SECRET_KEY_PATH must be readable when APP_ENV=production")
    return {
        "status": "ok",
        "path": str(path),
        "configured": bool(configured),
        "exists": path.exists(),
        "readable": os.access(path, os.R_OK) if path.exists() else False,
        "auto_create_allowed": not production,
    }
