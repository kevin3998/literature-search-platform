from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Header, HTTPException

DEFAULT_USER_ID = "local_user"
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class UserContext:
    user_id: str
    workspace_slug: str


def validate_user_id(value: str | None) -> str:
    if value is None:
        return DEFAULT_USER_ID
    user_id = value.strip()
    if (
        not user_id
        or user_id in {".", ".."}
        or ".." in user_id
        or "/" in user_id
        or "\\" in user_id
        or not _USER_ID_RE.match(user_id)
    ):
        raise ValueError("invalid user id")
    return user_id


def current_user(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> UserContext:
    try:
        user_id = validate_user_id(x_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid user id") from exc
    return UserContext(user_id=user_id, workspace_slug=user_id)


__all__ = ["DEFAULT_USER_ID", "UserContext", "current_user", "validate_user_id"]
