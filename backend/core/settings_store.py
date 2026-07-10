from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_loads, utc_now, uuid_value

DEFAULTS: dict[str, dict[str, Any]] = {
    "general": {
        "platform_name": "文献智能体平台",
        "default_module": "literature_search",
        "default_literature_tab": "chat",
        "show_debug_json": False,
        "compact_mode": False,
        "theme": "light",
    },
    "models": {
        "provider": "none",
        "base_url": "",
        "chat_model": "",
        "strong_model": "",
        "embedding_provider": "local",
        "embedding_model": "",
        "rerank_provider": "",
        "rerank_model": "",
        "temperature": 0.2,
        "max_tokens": 0,
        "timeout_seconds": 60,
        "retry_count": 2,
        "multimodal_enabled": False,
        "multimodal_profile_id": "",
        "multimodal_model": "",
        "multimodal_scan_default": "related_pages_assets",
    },
    "research_agent": {},
    "agent": {
        "enabled": True,
        "max_tool_iterations": 10,
        "tool_budget": 24,
        "max_search_calls_per_turn": 8,
        "enforce_citations": True,
        "answer_mode": "quick",
        "grounding_mode": "audit",
    },
    "retrieval": {
        "default_retrieval": "hybrid",
        "default_scope": "library",
        "default_profile": "default",
        "default_limit": 20,
        "default_evidence_per_article_limit": 5,
        "default_expand_assets": False,
        "default_year_from": None,
        "default_year_to": None,
    },
    "memory": {
        "context_message_limit": 8,
        "context_search_limit": 16,
        "evidence_limit_multiplier": 4,
        "auto_use_previous_evidence": True,
        "auto_link_artifacts": True,
        "auto_generate_session_title": True,
        "show_archived_sessions": False,
    },
    "external_sources": {
        "arxiv_enabled": True,
        "semantic_scholar_enabled": True,
        "openalex_enabled": True,
        "exa_enabled": False,
        "crossref_enabled": True,
        "default_year_window": 3,
        "per_source_limit": 2,
        "timeout_seconds": 30,
        "retry_count": 2,
        "allow_unverified_candidates": True,
        "mark_concurrent_work_from_year": 2025,
        "openalex_email": "",
    },
    "diagnostics": {},
}

ENV_MAP = {
    ("retrieval", "default_retrieval"): "LITERATURE_SEARCH_DEFAULT_RETRIEVAL",
    ("retrieval", "default_scope"): "LITERATURE_SEARCH_DEFAULT_SCOPE",
}

_DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}

SECRET_ENV_BY_PROVIDER = {
    "openai": ["OPENAI_API_KEY", "LITERATURE_LLM_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "LITERATURE_LLM_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "LITERATURE_LLM_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY", "LITERATURE_LLM_API_KEY"],
    "openai_compatible": ["LITERATURE_LLM_API_KEY", "OPENAI_API_KEY"],
}


class SettingsStore:
    def __init__(self, db_path: str | None = None, engine: Engine | None = None) -> None:
        self.db_path = db_path
        self.engine = engine or create_engine_from_env()

    def get_settings(self, *, user_id: str | None = None) -> dict[str, dict[str, Any]]:
        owner = _user_id(user_id)
        grouped = {scope: dict(values) for scope, values in DEFAULTS.items()}
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select scope, key, value_json from settings where user_id = :user_id"),
                {"user_id": uuid_value(owner)},
            ).mappings().all()
        for row in rows:
            grouped.setdefault(row["scope"], {})
            grouped[row["scope"]][row["key"]] = json_loads(row["value_json"], None)
        self._hydrate_runtime(grouped, user_id=owner)
        return grouped

    def patch(self, payload: dict[str, dict[str, Any]], *, user_id: str | None = None) -> dict[str, dict[str, Any]]:
        owner = _user_id(user_id)
        ts = utc_now()
        with self.engine.begin() as conn:
            for scope, values in payload.items():
                if not isinstance(values, dict):
                    continue
                for key, value in values.items():
                    if key == "api_key" or key.endswith("_api_key"):
                        continue
                    if scope not in DEFAULTS or key not in DEFAULTS.get(scope, {}):
                        continue
                    conn.execute(
                        text(
                            """
                            insert into settings(user_id, scope, key, value_json, updated_at)
                            values(:user_id, :scope, :key, cast(:value_json as jsonb), :updated_at)
                            on conflict(user_id, scope, key) do update set
                                value_json = excluded.value_json,
                                updated_at = excluded.updated_at
                            """
                        ),
                        {
                            "user_id": uuid_value(owner),
                            "scope": scope,
                            "key": key,
                            "value_json": json.dumps(value, ensure_ascii=False),
                            "updated_at": ts,
                        },
                    )
        return self.get_settings(user_id=owner)

    def reset(self, scope: str | None = None, *, user_id: str | None = None) -> dict[str, dict[str, Any]]:
        owner = _user_id(user_id)
        with self.engine.begin() as conn:
            if scope:
                conn.execute(text("delete from settings where user_id = :user_id and scope = :scope"), {"user_id": uuid_value(owner), "scope": scope})
            else:
                conn.execute(text("delete from settings where user_id = :user_id"), {"user_id": uuid_value(owner)})
        return self.get_settings(user_id=owner)

    def effective(self, *, user_id: str | None = None) -> dict[str, dict[str, Any]]:
        owner = _user_id(user_id)
        rows = self._settings_rows(owner)
        effective: dict[str, dict[str, Any]] = {}
        for scope, defaults in DEFAULTS.items():
            for key, default in defaults.items():
                value, source = self._resolve(scope, key, default, rows)
                effective[f"{scope}.{key}"] = {"value": value, "source": source}
        active = self._active_model_profile(user_id=owner)
        if active:
            effective["models.provider"] = {"value": active.get("provider") or "none", "source": "profile"}
            effective["models.base_url"] = {"value": active.get("base_url") or "", "source": "profile"}
            effective["models.chat_model"] = {"value": active.get("model") or "", "source": "profile"}
        provider = self.get_model_provider(user_id=owner)
        effective["models.api_key_configured"] = {"value": self.api_key_configured(provider, user_id=owner), "source": self.api_key_source(provider, user_id=owner) or "none"}
        effective["models.api_key_source"] = {"value": self.api_key_source(provider, user_id=owner), "source": "runtime"}
        for key, value in self.research_agent_status().items():
            effective[f"research_agent.{key}"] = value
        return effective

    def value(self, scope: str, key: str, *, user_id: str | None = None) -> Any:
        owner = _user_id(user_id)
        rows = self._settings_rows(owner)
        default = DEFAULTS[scope][key]
        value, _source = self._resolve(scope, key, default, rows)
        return value

    def retrieval_defaults(self, *, user_id: str | None = None) -> dict[str, Any]:
        return {
            "retrieval": self.value("retrieval", "default_retrieval", user_id=user_id),
            "scope": self.value("retrieval", "default_scope", user_id=user_id),
            "profile": self.value("retrieval", "default_profile", user_id=user_id),
            "limit": self.value("retrieval", "default_limit", user_id=user_id),
            "evidence_per_article_limit": self.value("retrieval", "default_evidence_per_article_limit", user_id=user_id),
            "expand_assets": self.value("retrieval", "default_expand_assets", user_id=user_id),
            "year_from": self.value("retrieval", "default_year_from", user_id=user_id),
            "year_to": self.value("retrieval", "default_year_to", user_id=user_id),
        }

    def external_sources_config(self, *, user_id: str | None = None) -> dict[str, Any]:
        values = {key: self.value("external_sources", key, user_id=user_id) for key in DEFAULTS["external_sources"]}
        for source in ["semantic_scholar", "exa", "openalex"]:
            values[f"{source}_key_configured"] = self.external_source_key_configured(source, user_id=user_id)
            values[f"{source}_key_source"] = self.external_source_key_source(source, user_id=user_id)
        return values

    def agent_config(self, *, user_id: str | None = None) -> dict[str, Any]:
        return {
            "enabled": bool(self.value("agent", "enabled", user_id=user_id)),
            "max_tool_iterations": _positive_int(self.value("agent", "max_tool_iterations", user_id=user_id), 10),
            "tool_budget": _positive_int(self.value("agent", "tool_budget", user_id=user_id), 24),
            "max_search_calls_per_turn": _positive_int(self.value("agent", "max_search_calls_per_turn", user_id=user_id), 8),
            "enforce_citations": bool(self.value("agent", "enforce_citations", user_id=user_id)),
            "answer_mode": str(self.value("agent", "answer_mode", user_id=user_id) or "quick"),
            "grounding_mode": _grounding_mode(self.value("agent", "grounding_mode", user_id=user_id)),
        }

    def model_config(self, *, user_id: str | None = None) -> dict[str, Any]:
        owner = _user_id(user_id)
        active = self._active_model_profile(user_id=owner)
        if active:
            return {
                "provider": str(active.get("provider") or "none"),
                "base_url": str(active.get("base_url") or ""),
                "chat_model": str(active.get("model") or ""),
                "strong_model": str(self.value("models", "strong_model", user_id=owner) or ""),
                "temperature": self.value("models", "temperature", user_id=owner),
                "max_tokens": self.value("models", "max_tokens", user_id=owner),
                "timeout_seconds": self.value("models", "timeout_seconds", user_id=owner),
                "retry_count": self.value("models", "retry_count", user_id=owner),
            }
        return {
            "provider": self.get_model_provider(user_id=owner),
            "base_url": str(self.value("models", "base_url", user_id=owner) or ""),
            "chat_model": str(self.value("models", "chat_model", user_id=owner) or ""),
            "strong_model": str(self.value("models", "strong_model", user_id=owner) or ""),
            "temperature": self.value("models", "temperature", user_id=owner),
            "max_tokens": self.value("models", "max_tokens", user_id=owner),
            "timeout_seconds": self.value("models", "timeout_seconds", user_id=owner),
            "retry_count": self.value("models", "retry_count", user_id=owner),
        }

    def llm_enabled(self, *, user_id: str | None = None) -> bool:
        provider = self.get_model_provider(user_id=user_id)
        if provider == "none":
            return False
        if not bool(self.value("agent", "enabled", user_id=user_id)):
            return False
        if provider == "ollama":
            return True
        return self.api_key_configured(provider, user_id=user_id)

    def supported_agent_providers(self) -> list[str]:
        return ["openai", "openai_compatible", "deepseek", "ollama"]

    def readiness(self, *, user_id: str | None = None) -> dict[str, Any]:
        config = self.model_config(user_id=user_id)
        provider = config["provider"]
        base_url = str(config.get("base_url") or "") or _DEFAULT_BASE_URLS.get(provider, "")
        chat_model = str(config.get("chat_model") or "")
        source = self.api_key_source(provider, user_id=user_id)
        reasons: list[str] = []
        warnings: list[str] = []
        if provider == "none":
            reasons.append("provider_none")
        else:
            if not bool(self.value("agent", "enabled", user_id=user_id)):
                reasons.append("agent_disabled")
            if provider not in self.supported_agent_providers():
                reasons.append("provider_unsupported")
            if not chat_model:
                reasons.append("missing_chat_model")
            if provider == "openai_compatible" and not str(self.value("models", "base_url", user_id=user_id) or ""):
                reasons.append("missing_base_url")
            if provider != "ollama" and provider in self.supported_agent_providers() and not self.api_key_configured(provider, user_id=user_id):
                active = self._active_model_profile(user_id=user_id)
                if active and active.get("provider") == provider and active.get("key_status") == "unreadable":
                    reasons.append("credential_unreadable")
                else:
                    reasons.append("missing_api_key")
            if provider == "ollama" and chat_model and not self._ollama_model_available(chat_model, base_url):
                reasons.append("ollama_model_unavailable")
        ready = not reasons
        return {
            "ready": ready,
            "mode": "agent" if ready else "blocked",
            "active_model": {"provider": provider, "model": chat_model, "base_url": base_url, "api_key_source": source},
            "reasons": reasons,
            "warnings": warnings,
            "fallback_mode": None if ready else "blocked_requires_llm",
        }

    def memory_context_limits(self, *, user_id: str | None = None) -> dict[str, int]:
        message_limit = _positive_int(self.value("memory", "context_message_limit", user_id=user_id), 8)
        search_limit = _positive_int(self.value("memory", "context_search_limit", user_id=user_id), 8)
        multiplier = _positive_int(self.value("memory", "evidence_limit_multiplier", user_id=user_id), 3)
        return {"message_limit": message_limit, "search_limit": search_limit, "evidence_limit": search_limit * multiplier}

    def diagnostics(self, *, user_id: str | None = None) -> dict[str, Any]:
        return {
            "overall": "ok",
            "checks": [
                {"id": "settings.db", "status": "ok", "label": "PostgreSQL settings", "detail": {"backend": "postgres"}, "checked_at": time.time()},
                {"id": "models.llm", "status": "ok" if self.llm_enabled(user_id=user_id) else "warning", "label": "LLM configuration", "detail": self.readiness(user_id=user_id), "checked_at": time.time()},
            ],
        }

    def test_model(self, payload: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any]:
        from core.llm.client import resolve_api_key, test_chat_completion

        provider = payload.get("provider") or self.get_model_provider(user_id=user_id)
        if provider == "none":
            return {"available": False, "provider": provider, "message": "Provider 为 none：未启用 LLM。"}
        base_url = payload.get("base_url") or self.value("models", "base_url", user_id=user_id) or None
        model = payload.get("model") or self.value("models", "chat_model", user_id=user_id)
        if not model:
            return {"available": False, "provider": provider, "message": "未配置 Chat Model，无法测试。"}
        api_key = resolve_api_key(provider, user_id=user_id)
        if not api_key:
            return {"available": False, "provider": provider, "message": "缺少 API key。", "api_key_configured": False}
        if not base_url:
            base_url = _DEFAULT_BASE_URLS.get(provider)
        return test_chat_completion(provider=provider, model=model, base_url=base_url, api_key=api_key)

    def get_model_provider(self, *, user_id: str | None = None) -> str:
        active = self._active_model_profile(user_id=user_id)
        if active:
            return str(active.get("provider") or "none")
        return str(self.value("models", "provider", user_id=user_id) or "none")

    def platform_role(self) -> str:
        role = (os.getenv("LITERATURE_PLATFORM_ROLE") or "admin").strip().lower()
        return "viewer" if role == "viewer" else "admin"

    def api_key_configured(self, provider: str, *, user_id: str | None = None) -> bool:
        return self.api_key_source(provider, user_id=user_id) is not None

    def api_key_source(self, provider: str, *, user_id: str | None = None) -> str | None:
        from core.secret_store import secret_store

        owner = _user_id(user_id)
        if provider == "none":
            names = {name for values in SECRET_ENV_BY_PROVIDER.values() for name in values}
            if any(os.getenv(name) for name in names):
                return "env"
            return "stored" if secret_store.providers(user_id=owner) else None
        env_names = SECRET_ENV_BY_PROVIDER.get(provider, ["LITERATURE_LLM_API_KEY"])
        if any(os.getenv(name) for name in env_names):
            return "env"
        from core.model_profiles import model_profile_store

        active = model_profile_store.active(user_id=owner)
        if active and active.get("provider") == provider and active.get("has_key"):
            return "profile"
        if secret_store.has(provider, user_id=owner):
            return "stored"
        return None

    def external_source_key_configured(self, source: str, *, user_id: str | None = None) -> bool:
        return self.external_source_key_source(source, user_id=user_id) is not None

    def external_source_key_source(self, source: str, *, user_id: str | None = None) -> str | None:
        from core.secret_store import secret_store

        env_names = {"semantic_scholar": ["SEMANTIC_SCHOLAR_API_KEY"], "exa": ["EXA_API_KEY"], "openalex": ["OPENALEX_API_KEY"]}.get(source, [])
        if any(os.getenv(name) for name in env_names):
            return "env"
        if secret_store.has(f"external:{source}", user_id=user_id):
            return "stored"
        return None

    def research_agent_status(self) -> dict[str, dict[str, Any]]:
        code_dir = os.getenv("LITERATURE_RESEARCH_CODE_DIR") or "/Users/chenlintao/paper-crawler-ops/literature_research"
        data_dir = os.getenv("LITERATURE_DATA_DIR") or "/Users/chenlintao/paper-crawler-ops/literature_data"
        return {
            "code_dir": {"value": code_dir, "source": "env" if os.getenv("LITERATURE_RESEARCH_CODE_DIR") else "default"},
            "data_dir": {"value": data_dir, "source": "env" if os.getenv("LITERATURE_DATA_DIR") else "default"},
            "memory_db_path": {"value": os.getenv("LITERATURE_MEMORY_DB_PATH") or "legacy", "source": "legacy"},
            "artifact_root": {"value": os.path.join(data_dir, "research_agent"), "source": "derived"},
        }

    def _settings_rows(self, user_id: str) -> dict[tuple[str, str], Any]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select scope, key, value_json from settings where user_id = :user_id"),
                {"user_id": uuid_value(user_id)},
            ).mappings().all()
        return {(row["scope"], row["key"]): json_loads(row["value_json"], None) for row in rows}

    def _resolve(self, scope: str, key: str, default: Any, rows: dict[tuple[str, str], Any]):
        if (scope, key) in rows:
            return rows[(scope, key)], "postgres"
        env_name = ENV_MAP.get((scope, key))
        if env_name and os.getenv(env_name) not in (None, ""):
            return _cast(os.getenv(env_name), default), "env"
        return default, "default"

    def _hydrate_runtime(self, grouped: dict[str, dict[str, Any]], *, user_id: str) -> None:
        active = self._active_model_profile(user_id=user_id)
        if active:
            grouped["models"]["provider"] = active.get("provider") or grouped["models"].get("provider")
            grouped["models"]["base_url"] = active.get("base_url") or ""
            grouped["models"]["chat_model"] = active.get("model") or ""
            grouped["models"]["active_profile_id"] = active.get("id")
            grouped["models"]["active_profile_name"] = active.get("name")
        provider = str(grouped["models"].get("provider") or "none")
        grouped["models"]["api_key_configured"] = self.api_key_configured(provider, user_id=user_id)
        grouped["models"]["api_key_source"] = self.api_key_source(provider, user_id=user_id)
        grouped["models"]["llm_enabled"] = self.llm_enabled(user_id=user_id)
        grouped.setdefault("agent", {})["agent_chat_ready"] = self.llm_enabled(user_id=user_id)
        grouped["research_agent"] = {key: value["value"] for key, value in self.research_agent_status().items()}
        grouped["memory"]["db_path"] = "postgresql"
        grouped["memory"]["stats"] = {}
        grouped["diagnostics"] = {"last_run": None}

    def _active_model_profile(self, *, user_id: str | None = None) -> dict[str, Any] | None:
        try:
            from core.model_profiles import model_profile_store

            active = model_profile_store.active(user_id=_user_id(user_id))
            if active and active.get("provider"):
                return active
        except Exception:
            return None
        return None

    def _ollama_model_available(self, model: str, base_url: str, *, timeout: float = 1.5) -> bool:
        root = _ollama_root_url(base_url)
        try:
            with urllib.request.urlopen(f"{root}/api/tags", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return False
        wanted = _normalize_ollama_model(model)
        return any(_normalize_ollama_model(item.get("name") or item.get("model") or "") == wanted for item in payload.get("models") or [])


def _user_id(user_id: str | None) -> str:
    if user_id:
        return user_id
    from core.user_store import user_store

    return user_store.ensure_local_user()["user_id"]


def _cast(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        try:
            return int(raw)
        except ValueError:
            return default
    if default is None and raw == "":
        return None
    return raw


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _grounding_mode(value: Any) -> str:
    mode = str(value or "audit").lower()
    return mode if mode in {"audit", "strict", "warn", "off"} else "audit"


def _ollama_root_url(base_url: str | None) -> str:
    raw = (base_url or _DEFAULT_BASE_URLS["ollama"]).strip() or _DEFAULT_BASE_URLS["ollama"]
    parsed = urllib.parse.urlparse(raw)
    if parsed.path.rstrip("/") == "/v1":
        parsed = parsed._replace(path="")
    return urllib.parse.urlunparse(parsed).rstrip("/")


def _normalize_ollama_model(model: str) -> str:
    text = (model or "").strip()
    return text if not text or ":" in text else f"{text}:latest"


settings_store = SettingsStore()
