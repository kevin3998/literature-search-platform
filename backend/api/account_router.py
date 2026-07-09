from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import core.auth_store as auth_store_module
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api/account", tags=["account"])


class ProfilePatchRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ApiTokenCreateRequest(BaseModel):
    name: str


@router.get("/profile")
def profile(user: UserContext = Depends(current_user)):
    profile_row = auth_store_module.auth_store.get_user(user.user_id)
    if not profile_row:
        raise HTTPException(status_code=404, detail="user not found")
    return profile_row


@router.patch("/profile")
def update_profile(payload: ProfilePatchRequest, user: UserContext = Depends(current_user)):
    try:
        return auth_store_module.auth_store.update_profile(user.user_id, display_name=payload.display_name, avatar_url=payload.avatar_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/password")
def change_password(payload: PasswordChangeRequest, user: UserContext = Depends(current_user)):
    try:
        auth_store_module.auth_store.change_password(user.user_id, payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/sessions")
def list_sessions(user: UserContext = Depends(current_user)):
    return auth_store_module.auth_store.list_sessions(user.user_id)


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, user: UserContext = Depends(current_user)):
    return {"ok": auth_store_module.auth_store.revoke_session(user.user_id, session_id)}


@router.get("/api-tokens")
def list_api_tokens(user: UserContext = Depends(current_user)):
    return auth_store_module.auth_store.list_api_tokens(user.user_id)


@router.post("/api-tokens")
def create_api_token(payload: ApiTokenCreateRequest, user: UserContext = Depends(current_user)):
    try:
        return auth_store_module.auth_store.create_api_token(user.user_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api-tokens/{token_id}")
def revoke_api_token(token_id: str, user: UserContext = Depends(current_user)):
    return {"ok": auth_store_module.auth_store.revoke_api_token(user.user_id, token_id)}


__all__ = ["router"]
