from __future__ import annotations

import time

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from core.registry import registry
from core.db.engine import create_engine_from_env
from core.db.readiness import check_alembic_at_head, check_postgres_connection
from core.db.config import app_env
from core.runtime_config import check_secret_key_policy, cors_allow_origins
from core.session_store import session_store
from core.user_context import DEFAULT_SUBJECT, auth_mode, validate_auth_runtime
from core.user_store import user_store
from core.worker.readiness import check_worker_heartbeat
from core.workspace_paths import user_data_root, user_workspace_root
from modules import register_builtin_modules

API_VERSION = "0.1.0"
READINESS_CONTRACT_VERSION = "platform_readiness_m6_2026_07_09"
READINESS_CAPABILITIES = [
    "literature_search_reliability_batch",
    "session_stale_turn_recovery",
    "workflow_artifact_insights",
    "postgres_core_runtime",
    "postgres_workflow_runtime",
    "postgres_structured_extraction_runtime",
    "postgres_worker_queue_runtime",
    "postgres_operations_m6",
]

validate_auth_runtime()
check_secret_key_policy()
postgres_engine = create_engine_from_env()
if app_env() == "production":
    migration_status = check_alembic_at_head(postgres_engine)
    if migration_status.get("status") != "ok":
        raise RuntimeError(f"PostgreSQL schema is not at Alembic head: {migration_status}")
app = FastAPI(title="文献智能体平台 API", version=API_VERSION)
register_builtin_modules()

# 团队内部部署：开发环境下放开本机几个常见端口，正式部署时按需收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api import (  # noqa: E402 - auth/database safety checks must run before router imports.
    chat_router,
    corpus_router,
    library_router,
    literature_search_router,
    modules_router,
    settings_router,
    structured_extraction_router,
    workflow_router,
)

app.include_router(modules_router.router)
app.include_router(chat_router.router)
app.include_router(library_router.router)
app.include_router(literature_search_router.router)
app.include_router(corpus_router.router)
app.include_router(settings_router.router)
app.include_router(workflow_router.router)
app.include_router(structured_extraction_router.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


def _readiness_check(check_id: str, label: str, func):
    checked_at = time.time()
    try:
        detail = func()
        status = detail.get("status", "ok") if isinstance(detail, dict) else "ok"
        if status not in {"ok", "warning", "error"}:
            status = "ok"
        return {"id": check_id, "status": status, "label": label, "detail": detail, "checked_at": checked_at}
    except Exception as exc:  # noqa: BLE001 - readiness must report failed dependency boundaries.
        return {"id": check_id, "status": "error", "label": label, "detail": {"error": str(exc)}, "checked_at": checked_at}


def _check_registry():
    modules = registry.list()
    module_ids = [module.id for module in modules]
    return {
        "status": "ok" if "literature_search" in module_ids else "error",
        "module_ids": module_ids,
    }


def _check_postgres_connection():
    return check_postgres_connection(postgres_engine)


def _check_migrations():
    return check_alembic_at_head(postgres_engine)


def _check_auth_safety():
    validate_auth_runtime()
    return {"status": "ok", "auth_mode": auth_mode()}


def _check_secret_key():
    return check_secret_key_policy()


def _check_default_user():
    user = user_store.ensure_local_user()
    return {"status": "ok", "user_id": user["user_id"], "display_name": user["display_name"]}


def _check_sessions_read():
    user = user_store.ensure_local_user()
    sessions = session_store.list_sessions("literature_search", user_id=user["user_id"])
    return {"status": "ok", "module_id": "literature_search", "count": len(sessions)}


def _check_workflows_read():
    from modules.workflow.shared import workflow_store
    from modules.workflow.templates import list_templates

    user = user_store.ensure_local_user()
    workflows = workflow_store.list(user_id=user["user_id"], limit=1)
    templates = list_templates()
    return {
        "status": "ok" if templates is not None else "error",
        "count": len(workflows),
        "template_count": len(templates),
    }


def _check_structured_extraction_read():
    from modules.structured_extraction.shared import structured_extraction_store

    user = user_store.ensure_local_user()
    tasks = structured_extraction_store.list_tasks(user_id=user["user_id"], limit=1)
    return {"status": "ok", "count": len(tasks)}


def _check_worker_heartbeat():
    return check_worker_heartbeat(postgres_engine)


def _check_user_workspace():
    root = user_data_root()
    default_workspace = user_workspace_root(DEFAULT_SUBJECT)
    default_workspace.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "user_workspace_root": str(root),
        "default_user_id": DEFAULT_SUBJECT,
        "default_user_workspace": str(default_workspace),
    }


@app.get("/api/readiness")
def readiness(response: Response):
    """Deep development/operations readiness for the chat-facing API boundary.

    Liveness (`/api/health`) only proves the process is up. Readiness proves the
    core chat dependencies used by the frontend can be reached without mutating
    data, so dev tooling does not reuse a half-broken backend.
    """
    checks = [
        _readiness_check("backend.health", "Backend process", lambda: {"status": "ok"}),
        _readiness_check("modules.registry", "Module registry", _check_registry),
        _readiness_check("postgres.connection", "PostgreSQL connection", _check_postgres_connection),
        _readiness_check("postgres.migrations", "Alembic migration head", _check_migrations),
        _readiness_check("auth.safety", "Authentication safety", _check_auth_safety),
        _readiness_check("secrets.encryption_key", "Secret encryption key", _check_secret_key),
        _readiness_check("users.default", "Default development user", _check_default_user),
        _readiness_check("sessions.read", "Session read contract", _check_sessions_read),
        _readiness_check("workflows.read", "Workflow read contract", _check_workflows_read),
        _readiness_check("structured_extraction.read", "Structured extraction read contract", _check_structured_extraction_read),
        _readiness_check("workers.heartbeat", "Worker heartbeat", _check_worker_heartbeat),
        _readiness_check("user_workspace.root", "User workspace root", _check_user_workspace),
    ]
    statuses = [check["status"] for check in checks]
    overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    if overall == "error":
        response.status_code = 503
    return {
        "ready": overall != "error",
        "overall": overall,
        "build": {
            "api_version": API_VERSION,
            "readiness_contract_version": READINESS_CONTRACT_VERSION,
            "capabilities": READINESS_CAPABILITIES,
        },
        "checks": checks,
    }
