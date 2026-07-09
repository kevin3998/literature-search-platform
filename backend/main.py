from __future__ import annotations

import time

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from core.registry import registry
from core.session_store import session_store
from core.user_context import DEFAULT_USER_ID, UserContext
from core.workspace_paths import user_data_root, user_workspace_root
from modules import register_builtin_modules
from api import (
    chat_router,
    corpus_router,
    library_router,
    literature_search_router,
    modules_router,
    settings_router,
    structured_extraction_router,
    workflow_router,
)

API_VERSION = "0.1.0"
READINESS_CONTRACT_VERSION = "platform_readiness_v2_2026_07_07"
READINESS_CAPABILITIES = [
    "literature_search_reliability_batch",
    "session_stale_turn_recovery",
    "workflow_artifact_insights",
]

app = FastAPI(title="文献智能体平台 API", version=API_VERSION)
register_builtin_modules()

# 团队内部部署：开发环境下放开本机几个常见端口，正式部署时按需收紧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


def _check_memory_db():
    row = session_store.conn.execute("pragma quick_check").fetchone()
    quick_check = row[0] if row else "missing_result"
    return {
        "status": "ok" if quick_check == "ok" else "error",
        "quick_check": quick_check,
    }


def _check_sessions_read():
    sessions = session_store.list_sessions("literature_search", user_id=DEFAULT_USER_ID)
    return {"status": "ok", "module_id": "literature_search", "count": len(sessions)}


def _check_user_workspace():
    root = user_data_root()
    default_workspace = user_workspace_root(UserContext(DEFAULT_USER_ID, DEFAULT_USER_ID))
    default_workspace.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "user_workspace_root": str(root),
        "default_user_id": DEFAULT_USER_ID,
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
        _readiness_check("memory.db", "Memory database", _check_memory_db),
        _readiness_check("sessions.read", "Session read contract", _check_sessions_read),
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
