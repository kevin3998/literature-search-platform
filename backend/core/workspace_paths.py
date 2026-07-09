from __future__ import annotations

import os
from pathlib import Path

from core.user_context import DEFAULT_USER_ID, UserContext, validate_user_id

USER_DATA_ROOT_ENV = "LITERATURE_USER_DATA_ROOT"


def user_data_root() -> Path:
    return Path(os.getenv(USER_DATA_ROOT_ENV) or ".runtime/users").expanduser().resolve()


def _coerce_user(user: UserContext | str | None) -> UserContext:
    if isinstance(user, UserContext):
        return user
    user_id = validate_user_id(user or DEFAULT_USER_ID)
    return UserContext(user_id=user_id, workspace_slug=user_id)


def user_workspace_root(user: UserContext | str | None) -> Path:
    ctx = _coerce_user(user)
    return user_data_root() / ctx.workspace_slug


def user_data_rel_prefix(user: UserContext | str | None) -> str:
    ctx = _coerce_user(user)
    return f"users/{ctx.workspace_slug}"


def resolve_user_workspace_path(user: UserContext | str | None, relative_path: str | Path = "") -> Path:
    rel_path = Path(relative_path)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise ValueError(f"invalid user workspace relative path: {relative_path!r}")
    root = user_workspace_root(user)
    candidate = root / rel_path
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"path escapes user workspace: {relative_path!r}") from exc
    return candidate


__all__ = [
    "USER_DATA_ROOT_ENV",
    "resolve_user_workspace_path",
    "user_data_rel_prefix",
    "user_data_root",
    "user_workspace_root",
]
