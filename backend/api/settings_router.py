from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.permissions import require_admin
from core.settings_store import settings_store
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api/settings", tags=["settings"])
USER_SETTING_SCOPES = {"models", "retrieval"}
USER_EFFECTIVE_KEYS = {"general.default_module", "general.default_literature_tab"}
USER_EFFECTIVE_PREFIXES = ("models.", "retrieval.")


class SettingsPatchRequest(BaseModel):
    general: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, Any] = Field(default_factory=dict)
    research_agent: dict[str, Any] = Field(default_factory=dict)
    agent: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    external_sources: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ModelTestRequest(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None


class ModelSecretRequest(BaseModel):
    provider: str
    api_key: str


class ModelSecretDeleteRequest(BaseModel):
    provider: str


class ExternalSourceSecretRequest(BaseModel):
    source: str
    api_key: str


class ExternalSourceSecretDeleteRequest(BaseModel):
    source: str


class ResetRequest(BaseModel):
    scope: str | None = None


class ModelProfileCreate(BaseModel):
    name: str
    provider: str
    base_url: str = ""
    model: str = ""
    api_key: str = ""


class ModelProfileUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


@router.get("")
def get_settings(user: UserContext = Depends(current_user)):
    settings = settings_store.get_settings(user_id=user.user_id)
    return settings if _is_admin(user) else _filter_user_settings(settings)


@router.patch("")
def patch_settings(payload: SettingsPatchRequest, user: UserContext = Depends(current_user)):
    data = _non_empty_settings_payload(payload.model_dump())
    _ensure_user_settings_scopes(user, data)
    settings = settings_store.patch(data, user_id=user.user_id)
    return settings if _is_admin(user) else _filter_user_settings(settings)


@router.get("/effective")
def effective_settings(user: UserContext = Depends(current_user)):
    effective = settings_store.effective(user_id=user.user_id)
    return effective if _is_admin(user) else _filter_user_effective(effective)


@router.get("/diagnostics")
def diagnostics(user: UserContext = Depends(require_admin)):
    return settings_store.diagnostics(user_id=user.user_id)


@router.get("/readiness")
def readiness(user: UserContext = Depends(require_admin)):
    """Structured agent runtime-readiness contract (why Ready / Not Ready + fallback)."""
    return settings_store.readiness(user_id=user.user_id)


@router.post("/models/test")
def test_model(payload: ModelTestRequest, user: UserContext = Depends(current_user)):
    return settings_store.test_model(payload.model_dump(exclude_none=True), user_id=user.user_id)


@router.post("/models/secret")
def set_model_secret(payload: ModelSecretRequest, user: UserContext = Depends(current_user)):
    """Store a provider API key, encrypted at rest. Never echoes the key back."""
    from core.secret_store import secret_store

    if payload.provider == "none":
        raise HTTPException(status_code=400, detail="选择一个具体的 provider 再保存密钥")
    secret_store.set(payload.provider, payload.api_key, user_id=user.user_id)
    return {
        "configured": True,
        "provider": payload.provider,
        "source": settings_store.api_key_source(payload.provider, user_id=user.user_id),
    }


@router.delete("/models/secret")
def delete_model_secret(payload: ModelSecretDeleteRequest, user: UserContext = Depends(current_user)):
    from core.secret_store import secret_store

    removed = secret_store.delete(payload.provider, user_id=user.user_id)
    return {
        "removed": removed,
        "provider": payload.provider,
        "source": settings_store.api_key_source(payload.provider, user_id=user.user_id),
    }


@router.post("/external-sources/secret")
def set_external_source_secret(payload: ExternalSourceSecretRequest, user: UserContext = Depends(require_admin)):
    from core.secret_store import secret_store

    allowed = {"semantic_scholar", "exa", "openalex"}
    if payload.source not in allowed:
        raise HTTPException(status_code=400, detail="不支持的外部源")
    secret_store.set(f"external:{payload.source}", payload.api_key, user_id=user.user_id)
    return {
        "configured": True,
        "source": payload.source,
        "key_source": settings_store.external_source_key_source(payload.source, user_id=user.user_id),
    }


@router.delete("/external-sources/secret")
def delete_external_source_secret(payload: ExternalSourceSecretDeleteRequest, user: UserContext = Depends(require_admin)):
    from core.secret_store import secret_store

    removed = secret_store.delete(f"external:{payload.source}", user_id=user.user_id)
    return {
        "removed": removed,
        "source": payload.source,
        "key_source": settings_store.external_source_key_source(payload.source, user_id=user.user_id),
    }


@router.post("/reset")
def reset_settings(payload: ResetRequest, user: UserContext = Depends(current_user)):
    if not _is_admin(user) and payload.scope not in USER_SETTING_SCOPES:
        raise HTTPException(status_code=403, detail="admin role required")
    settings = settings_store.reset(payload.scope, user_id=user.user_id)
    return settings if _is_admin(user) else _filter_user_settings(settings)


def _is_admin(user: UserContext) -> bool:
    return user.role == "admin" and user.status == "active"


def _ensure_user_settings_scopes(user: UserContext, payload: dict[str, dict[str, Any]]) -> None:
    if _is_admin(user):
        return
    blocked = [
        scope for scope, values in payload.items()
        if values and scope not in USER_SETTING_SCOPES
    ]
    if blocked:
        raise HTTPException(status_code=403, detail="admin role required")


def _non_empty_settings_payload(payload: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        scope: values
        for scope, values in payload.items()
        if isinstance(values, dict) and values
    }


def _filter_user_settings(settings: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {scope: values for scope, values in settings.items() if scope in USER_SETTING_SCOPES}


def _filter_user_effective(effective: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in effective.items()
        if key in USER_EFFECTIVE_KEYS or key.startswith(USER_EFFECTIVE_PREFIXES)
    }


# --- model credential profiles -------------------------------------------------


def _profiles():
    from core.model_profiles import model_profile_store

    return model_profile_store


@router.get("/model-profiles")
def list_model_profiles(user: UserContext = Depends(current_user)):
    return _profiles().list(user_id=user.user_id)


@router.post("/model-profiles")
def create_model_profile(payload: ModelProfileCreate, user: UserContext = Depends(current_user)):
    return _profiles().create(
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
        user_id=user.user_id,
    )


@router.patch("/model-profiles/{profile_id}")
def update_model_profile(profile_id: str, payload: ModelProfileUpdate, user: UserContext = Depends(current_user)):
    try:
        return _profiles().update(profile_id, user_id=user.user_id, **payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/model-profiles/{profile_id}")
def delete_model_profile(profile_id: str, user: UserContext = Depends(current_user)):
    try:
        _profiles().delete(profile_id, user_id=user.user_id)
        return {"removed": True, "id": profile_id}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/model-profiles/{profile_id}/activate")
def activate_model_profile(profile_id: str, user: UserContext = Depends(current_user)):
    try:
        return _profiles().activate(profile_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/model-profiles/{profile_id}/reveal")
def reveal_model_profile(profile_id: str, user: UserContext = Depends(current_user)):
    """Return only safe secret metadata; M2 does not expose stored plaintext keys via API."""
    try:
        profile = _profiles().get(profile_id, user_id=user.user_id)
        return {
            "id": profile_id,
            "configured": bool(profile["has_key"]),
            "key_masked": profile["key_masked"],
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/model-profiles/{profile_id}/test")
def test_model_profile(profile_id: str, user: UserContext = Depends(current_user)):
    from core.llm.client import test_chat_completion

    store = _profiles()
    try:
        profile = store.get(profile_id, user_id=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not profile["model"]:
        return {"available": False, "provider": profile["provider"], "message": "未配置模型，无法测试。"}
    api_key = store.reveal(profile_id, user_id=user.user_id)
    if not api_key:
        return {"available": False, "provider": profile["provider"], "message": "该配置未保存密钥。"}
    return test_chat_completion(
        provider=profile["provider"],
        model=profile["model"],
        base_url=profile["base_url"] or None,
        api_key=api_key,
    )
