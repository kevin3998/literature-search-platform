from __future__ import annotations

from fastapi import Depends, HTTPException

from core.user_context import UserContext, current_user


def require_admin(user: UserContext = Depends(current_user)) -> UserContext:
    if user.role != "admin" or user.status != "active":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


__all__ = ["require_admin"]
