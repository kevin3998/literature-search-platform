from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi import Header, HTTPException, Request

from core.db.config import DatabaseConfigError, app_env

DEFAULT_USER_ID = "local_user"
DEFAULT_SUBJECT = "local_user"
_SUBJECT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class UserContext:
    user_id: str
    workspace_slug: str
    subject: str = DEFAULT_SUBJECT
    display_name: str = DEFAULT_SUBJECT
    auth_mode: str = "dev-header"
    role: str = "user"
    status: str = "active"
    email: str | None = None


def auth_mode() -> str:
    return (os.getenv("AUTH_MODE") or "dev-header").strip().lower()


def trusted_user_header_name() -> str:
    return (os.getenv("TRUSTED_USER_HEADER") or "X-Forwarded-User").strip()


def trusted_display_name_header_name() -> str:
    return (os.getenv("TRUSTED_DISPLAY_NAME_HEADER") or "X-Forwarded-User-Name").strip()


def validate_auth_runtime() -> None:
    mode = auth_mode()
    if mode not in {"dev-header", "trusted-header", "local-password", "hybrid"}:
        raise DatabaseConfigError(f"Unsupported AUTH_MODE: {mode}")
    if mode == "dev-header" and app_env() == "production":
        raise DatabaseConfigError("AUTH_MODE=dev-header is not allowed when APP_ENV=production")


def validate_subject(value: str | None) -> str:
    if value is None:
        return DEFAULT_SUBJECT
    subject = value.strip()
    if (
        not subject
        or subject in {".", ".."}
        or ".." in subject
        or "/" in subject
        or "\\" in subject
        or not _SUBJECT_RE.match(subject)
    ):
        raise ValueError("invalid user id")
    return subject


def validate_user_id(value: str | None) -> str:
    """Legacy name retained for filesystem-safe external subjects."""
    return validate_subject(value)


def current_user(request: Request, x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> UserContext:
    try:
        validate_auth_runtime()
        mode = auth_mode()
        if mode == "trusted-header":
            return _trusted_header_user(request, required=True, mode=mode)
        if mode == "local-password":
            return _local_password_user(request, mode=mode)
        if mode == "hybrid":
            if request.headers.get(trusted_user_header_name()):
                return _trusted_header_user(request, required=True, mode=mode)
            return _local_password_user(request, mode=mode)
        return _dev_header_user(x_user_id, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid user id") from exc
    except DatabaseConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _trusted_header_user(request: Request, *, required: bool, mode: str) -> UserContext:
    subject_header = trusted_user_header_name()
    subject_raw = request.headers.get(subject_header)
    if not subject_raw:
        if required:
            raise HTTPException(status_code=401, detail="trusted user header required")
        raise HTTPException(status_code=401, detail="valid session required")
    subject = validate_subject(subject_raw)
    display_name = request.headers.get(trusted_display_name_header_name()) or subject
    from core.user_store import TRUSTED_HEADER_PROVIDER, user_store

    user = user_store.get_or_create_user_for_subject(
        provider=TRUSTED_HEADER_PROVIDER,
        subject=subject,
        display_name=display_name.strip() or subject,
    )
    return _context_from_user(user, subject=subject, workspace_slug=subject, mode=mode)


def _dev_header_user(x_user_id: str | None, *, mode: str) -> UserContext:
    subject = validate_subject(x_user_id)
    from core.user_store import DEV_HEADER_PROVIDER, user_store

    user = user_store.get_or_create_user_for_subject(provider=DEV_HEADER_PROVIDER, subject=subject)
    return _context_from_user(user, subject=subject, workspace_slug=subject, mode=mode)


def _local_password_user(request: Request, *, mode: str) -> UserContext:
    from core.auth_store import auth_store
    from core.runtime_config import session_cookie_name

    token = request.cookies.get(session_cookie_name())
    user = auth_store.user_for_session_token(token or "")
    if not user:
        raise HTTPException(status_code=401, detail="valid session required")
    email = user.get("email")
    subject = str(email or user["user_id"])
    workspace_slug = str(user["user_id"])
    return _context_from_user(user, subject=subject, workspace_slug=workspace_slug, mode=mode)


def _context_from_user(user: dict[str, Any], *, subject: str, workspace_slug: str, mode: str) -> UserContext:
    return UserContext(
        user_id=user["user_id"],
        workspace_slug=workspace_slug,
        subject=subject,
        display_name=user["display_name"],
        auth_mode=mode,
        role=user.get("role") or "user",
        status=user.get("status") or "active",
        email=user.get("email"),
    )


__all__ = [
    "DEFAULT_USER_ID",
    "DEFAULT_SUBJECT",
    "UserContext",
    "auth_mode",
    "current_user",
    "trusted_display_name_header_name",
    "trusted_user_header_name",
    "validate_auth_runtime",
    "validate_subject",
    "validate_user_id",
]
