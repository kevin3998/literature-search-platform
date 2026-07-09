from __future__ import annotations

import os
import re
from dataclasses import dataclass

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


def auth_mode() -> str:
    return (os.getenv("AUTH_MODE") or "dev-header").strip().lower()


def trusted_user_header_name() -> str:
    return (os.getenv("TRUSTED_USER_HEADER") or "X-Forwarded-User").strip()


def trusted_display_name_header_name() -> str:
    return (os.getenv("TRUSTED_DISPLAY_NAME_HEADER") or "X-Forwarded-User-Name").strip()


def validate_auth_runtime() -> None:
    mode = auth_mode()
    if mode not in {"dev-header", "trusted-header"}:
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
            subject_header = trusted_user_header_name()
            subject_raw = request.headers.get(subject_header)
            if not subject_raw:
                raise HTTPException(status_code=401, detail="trusted user header required")
            subject = validate_subject(subject_raw)
            display_name = request.headers.get(trusted_display_name_header_name()) or subject
            from core.user_store import TRUSTED_HEADER_PROVIDER, user_store

            user = user_store.get_or_create_user_for_subject(
                provider=TRUSTED_HEADER_PROVIDER,
                subject=subject,
                display_name=display_name.strip() or subject,
            )
        else:
            subject = validate_subject(x_user_id)
            from core.user_store import DEV_HEADER_PROVIDER, user_store

            user = user_store.get_or_create_user_for_subject(provider=DEV_HEADER_PROVIDER, subject=subject)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid user id") from exc
    except DatabaseConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return UserContext(
        user_id=user["user_id"],
        workspace_slug=subject,
        subject=subject,
        display_name=user["display_name"],
        auth_mode=auth_mode(),
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
