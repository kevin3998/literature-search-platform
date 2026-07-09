from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import core.auth_store as auth_store_module
from core.csrf import require_csrf
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminUserPatchRequest(BaseModel):
    role: str | None = None
    status: str | None = None
    display_name: str | None = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


def require_admin(user: UserContext = Depends(current_user)) -> UserContext:
    if user.role != "admin" or user.status != "active":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


@router.get("/users")
def list_users(query: str = "", limit: int = 100, offset: int = 0, user: UserContext = Depends(require_admin)):
    return {"users": auth_store_module.auth_store.list_users(query=query, limit=limit, offset=offset)}


@router.patch("/users/{user_id}", dependencies=[Depends(require_csrf)])
def update_user(user_id: str, payload: AdminUserPatchRequest, user: UserContext = Depends(require_admin)):
    try:
        return auth_store_module.auth_store.update_user_admin(
            user.user_id,
            user_id,
            role=payload.role,
            status=payload.status,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(require_csrf)])
def reset_password(user_id: str, payload: AdminResetPasswordRequest, user: UserContext = Depends(require_admin)):
    try:
        auth_store_module.auth_store.reset_password_admin(user.user_id, user_id, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/users/{user_id}/revoke-sessions", dependencies=[Depends(require_csrf)])
def revoke_sessions(user_id: str, user: UserContext = Depends(require_admin)):
    try:
        return {"revoked": auth_store_module.auth_store.revoke_user_sessions_admin(user.user_id, user_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/users/{user_id}/revoke-api-tokens", dependencies=[Depends(require_csrf)])
def revoke_api_tokens(user_id: str, user: UserContext = Depends(require_admin)):
    try:
        return {"revoked": auth_store_module.auth_store.revoke_user_api_tokens_admin(user.user_id, user_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit-events")
def audit_events(limit: int = 100, offset: int = 0, user: UserContext = Depends(require_admin)):
    return {"audit_events": auth_store_module.auth_store.list_audit_events(limit=limit, offset=offset)}


__all__ = ["router"]
