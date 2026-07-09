from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.settings_store import settings_store

router = APIRouter(prefix="/api/settings", tags=["settings"])


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
def get_settings():
    return settings_store.get_settings()


@router.patch("")
def patch_settings(payload: SettingsPatchRequest):
    return settings_store.patch(payload.model_dump())


@router.get("/effective")
def effective_settings():
    return settings_store.effective()


@router.get("/diagnostics")
def diagnostics():
    return settings_store.diagnostics()


@router.get("/readiness")
def readiness():
    """Structured agent runtime-readiness contract (why Ready / Not Ready + fallback)."""
    return settings_store.readiness()


@router.post("/models/test")
def test_model(payload: ModelTestRequest):
    return settings_store.test_model(payload.model_dump(exclude_none=True))


@router.post("/models/secret")
def set_model_secret(payload: ModelSecretRequest):
    """Store a provider API key, encrypted at rest. Never echoes the key back."""
    from core.secret_store import secret_store

    if payload.provider == "none":
        raise HTTPException(status_code=400, detail="选择一个具体的 provider 再保存密钥")
    secret_store.set(payload.provider, payload.api_key)
    return {
        "configured": True,
        "provider": payload.provider,
        "source": settings_store.api_key_source(payload.provider),
    }


@router.delete("/models/secret")
def delete_model_secret(payload: ModelSecretDeleteRequest):
    from core.secret_store import secret_store

    removed = secret_store.delete(payload.provider)
    return {
        "removed": removed,
        "provider": payload.provider,
        "source": settings_store.api_key_source(payload.provider),
    }


@router.post("/external-sources/secret")
def set_external_source_secret(payload: ExternalSourceSecretRequest):
    from core.secret_store import secret_store

    allowed = {"semantic_scholar", "exa", "openalex"}
    if payload.source not in allowed:
        raise HTTPException(status_code=400, detail="不支持的外部源")
    secret_store.set(f"external:{payload.source}", payload.api_key)
    return {
        "configured": True,
        "source": payload.source,
        "key_source": settings_store.external_source_key_source(payload.source),
    }


@router.delete("/external-sources/secret")
def delete_external_source_secret(payload: ExternalSourceSecretDeleteRequest):
    from core.secret_store import secret_store

    removed = secret_store.delete(f"external:{payload.source}")
    return {
        "removed": removed,
        "source": payload.source,
        "key_source": settings_store.external_source_key_source(payload.source),
    }


@router.post("/reset")
def reset_settings(payload: ResetRequest):
    return settings_store.reset(payload.scope)


# --- model credential profiles -------------------------------------------------


def _profiles():
    from core.model_profiles import model_profile_store

    return model_profile_store


@router.get("/model-profiles")
def list_model_profiles():
    return _profiles().list()


@router.post("/model-profiles")
def create_model_profile(payload: ModelProfileCreate):
    return _profiles().create(
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
    )


@router.patch("/model-profiles/{profile_id}")
def update_model_profile(profile_id: str, payload: ModelProfileUpdate):
    try:
        return _profiles().update(profile_id, **payload.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/model-profiles/{profile_id}")
def delete_model_profile(profile_id: str):
    try:
        _profiles().delete(profile_id)
        return {"removed": True, "id": profile_id}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/model-profiles/{profile_id}/activate")
def activate_model_profile(profile_id: str):
    try:
        return _profiles().activate(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/model-profiles/{profile_id}/reveal")
def reveal_model_profile(profile_id: str):
    """The ONLY endpoint that returns a plaintext key — used for explicit view/copy."""
    try:
        return {"id": profile_id, "api_key": _profiles().reveal(profile_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/model-profiles/{profile_id}/test")
def test_model_profile(profile_id: str):
    from core.llm.client import test_chat_completion

    store = _profiles()
    try:
        profile = store.get(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not profile["model"]:
        return {"available": False, "provider": profile["provider"], "message": "未配置模型，无法测试。"}
    api_key = store.reveal(profile_id)
    if not api_key:
        return {"available": False, "provider": profile["provider"], "message": "该配置未保存密钥。"}
    return test_chat_completion(
        provider=profile["provider"],
        model=profile["model"],
        base_url=profile["base_url"] or None,
        api_key=api_key,
    )
