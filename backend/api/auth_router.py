from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

import core.auth_store as auth_store_module
from core.csrf import require_csrf
from core.runtime_config import cookie_secure, csrf_cookie_name, session_cookie_name, session_ttl_days
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/signup")
def signup(payload: SignupRequest, request: Request, response: Response):
    try:
        auth_store_module.auth_store.signup(email=payload.email, display_name=payload.display_name, password=payload.password)
        login_result = auth_store_module.auth_store.login(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=request.client.host if request.client else "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_auth_cookies(response, login_result)
    return login_result["user"]


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    try:
        login_result = auth_store_module.auth_store.login(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent", ""),
            ip_address=request.client.host if request.client else "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_auth_cookies(response, login_result)
    return login_result["user"]


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response):
    token = request.cookies.get(session_cookie_name())
    if token:
        auth_store_module.auth_store.logout(token)
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(user: UserContext = Depends(current_user)):
    return _context_dict(user)


@router.get("/csrf")
def csrf(request: Request, user: UserContext = Depends(current_user)):
    token = request.cookies.get(csrf_cookie_name())
    if not token:
        raise HTTPException(status_code=404, detail="csrf token not found")
    return {"csrf_token": token}


def _set_auth_cookies(response: Response, login_result: dict) -> None:
    max_age = session_ttl_days() * 24 * 60 * 60
    expires_at = login_result.get("expires_at")
    expires = expires_at if isinstance(expires_at, datetime) else None
    response.set_cookie(
        session_cookie_name(),
        login_result["session_token"],
        max_age=max_age,
        expires=expires,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        csrf_cookie_name(),
        login_result["csrf_token"],
        max_age=max_age,
        expires=expires,
        path="/",
        secure=cookie_secure(),
        httponly=False,
        samesite="lax",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(session_cookie_name(), path="/", secure=cookie_secure(), httponly=True, samesite="lax")
    response.delete_cookie(csrf_cookie_name(), path="/", secure=cookie_secure(), httponly=False, samesite="lax")


def _context_dict(user: UserContext) -> dict:
    return {
        "user_id": user.user_id,
        "workspace_slug": user.workspace_slug,
        "subject": user.subject,
        "display_name": user.display_name,
        "auth_mode": user.auth_mode,
        "role": user.role,
        "status": user.status,
        "email": user.email,
    }


__all__ = ["router"]
