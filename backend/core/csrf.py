from __future__ import annotations

from fastapi import Header, HTTPException, Request

import core.auth_store as auth_store_module
from core.runtime_config import session_cookie_name


def require_csrf(request: Request, x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token")) -> None:
    session_token = request.cookies.get(session_cookie_name())
    if not session_token:
        return
    if not auth_store_module.auth_store.validate_csrf(session_token, x_csrf_token or ""):
        raise HTTPException(status_code=403, detail="csrf failed")


__all__ = ["require_csrf"]
