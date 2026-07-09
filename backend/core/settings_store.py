from __future__ import annotations

import os
import sqlite3
import time
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from core.memory_db import connect, dumps, loads, memory_db_path, now


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
        "max_tokens": 0,  # 0 = no explicit cap → use the model's maximum output
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
        "max_tool_iterations": 6,
        "tool_budget": 12,
        "enforce_citations": True,
        "answer_mode": "quick",
        "grounding_mode": "audit",
    },
    "retrieval": {
        "default_retrieval": "hybrid",
        "default_scope": "library",
        "default_profile": "default",
        "default_limit": 10,
        "default_evidence_per_article_limit": 3,
        "default_expand_assets": False,
        "default_year_from": None,
        "default_year_to": None,
    },
    "memory": {
        "context_message_limit": 8,
        "context_search_limit": 8,
        "evidence_limit_multiplier": 3,
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
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path
        self.conn = connect(db_path)

    def get_settings(self) -> dict[str, dict[str, Any]]:
        grouped = {scope: dict(values) for scope, values in DEFAULTS.items()}
        for row in self.conn.execute("select scope, key, value_json from settings").fetchall():
            grouped.setdefault(row["scope"], {})
            grouped[row["scope"]][row["key"]] = loads(row["value_json"], None)
        self._hydrate_runtime(grouped)
        return grouped

    def patch(self, payload: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        ts = now()
        for scope, values in payload.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                if key == "api_key" or key.endswith("_api_key"):
                    continue
                if scope not in DEFAULTS or key not in DEFAULTS.get(scope, {}):
                    continue
                self.conn.execute(
                    """
                    insert into settings(scope, key, value_json, updated_at)
                    values(?, ?, ?, ?)
                    on conflict(scope, key) do update set
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (scope, key, dumps(value), ts),
                )
        self.conn.commit()
        return self.get_settings()

    def reset(self, scope: str | None = None) -> dict[str, dict[str, Any]]:
        if scope:
            self.conn.execute("delete from settings where scope = ?", (scope,))
        else:
            self.conn.execute("delete from settings")
        self.conn.commit()
        return self.get_settings()

    def effective(self) -> dict[str, dict[str, Any]]:
        rows = {
            (row["scope"], row["key"]): loads(row["value_json"], None)
            for row in self.conn.execute("select scope, key, value_json from settings").fetchall()
        }
        effective: dict[str, dict[str, Any]] = {}
        for scope, defaults in DEFAULTS.items():
            for key, default in defaults.items():
                value, source = self._resolve(scope, key, default, rows)
                effective[f"{scope}.{key}"] = {"value": value, "source": source}
        active = self._active_model_profile()
        if active:
            effective["models.provider"] = {"value": active.get("provider") or "none", "source": "profile"}
            effective["models.base_url"] = {"value": active.get("base_url") or "", "source": "profile"}
            effective["models.chat_model"] = {"value": active.get("model") or "", "source": "profile"}
        provider = self.get_model_provider()
        effective["models.api_key_configured"] = {
            "value": self.api_key_configured(provider),
            "source": "env",
        }
        effective["models.api_key_source"] = {
            "value": self.api_key_source(provider),
            "source": "env",
        }
        for key, value in self.research_agent_status().items():
            effective[f"research_agent.{key}"] = value
        for source in ["semantic_scholar", "exa"]:
            effective[f"external_sources.{source}_key_configured"] = {
                "value": self.external_source_key_configured(source),
                "source": self.external_source_key_source(source) or "none",
            }
        return effective

    def value(self, scope: str, key: str) -> Any:
        row = self.conn.execute(
            "select value_json from settings where scope = ? and key = ?",
            (scope, key),
        ).fetchone()
        if row:
            return loads(row["value_json"], DEFAULTS[scope][key])
        env_name = ENV_MAP.get((scope, key))
        if env_name and os.getenv(env_name) not in (None, ""):
            return _cast(os.getenv(env_name), DEFAULTS[scope][key])
        return DEFAULTS[scope][key]

    def retrieval_defaults(self) -> dict[str, Any]:
        return {
            "retrieval": self.value("retrieval", "default_retrieval"),
            "scope": self.value("retrieval", "default_scope"),
            "profile": self.value("retrieval", "default_profile"),
            "limit": self.value("retrieval", "default_limit"),
            "evidence_per_article_limit": self.value("retrieval", "default_evidence_per_article_limit"),
            "expand_assets": self.value("retrieval", "default_expand_assets"),
            "year_from": self.value("retrieval", "default_year_from"),
            "year_to": self.value("retrieval", "default_year_to"),
        }

    def external_sources_config(self) -> dict[str, Any]:
        values = {
            key: self.value("external_sources", key)
            for key in DEFAULTS["external_sources"]
        }
        values["semantic_scholar_key_configured"] = self.external_source_key_configured("semantic_scholar")
        values["semantic_scholar_key_source"] = self.external_source_key_source("semantic_scholar")
        values["exa_key_configured"] = self.external_source_key_configured("exa")
        values["exa_key_source"] = self.external_source_key_source("exa")
        return values

    def agent_config(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.value("agent", "enabled")),
            "max_tool_iterations": _positive_int(self.value("agent", "max_tool_iterations"), 6),
            "tool_budget": _positive_int(self.value("agent", "tool_budget"), 12),
            "enforce_citations": bool(self.value("agent", "enforce_citations")),
            "answer_mode": str(self.value("agent", "answer_mode") or "quick"),
            "grounding_mode": _grounding_mode(self.value("agent", "grounding_mode")),
        }

    def model_config(self) -> dict[str, Any]:
        active = self._active_model_profile()
        if active:
            provider = str(active.get("provider") or "none")
            return {
                "provider": provider,
                "base_url": str(active.get("base_url") or ""),
                "chat_model": str(active.get("model") or ""),
                "strong_model": str(self.value("models", "strong_model") or ""),
                "temperature": self.value("models", "temperature"),
                "max_tokens": self.value("models", "max_tokens"),
                "timeout_seconds": self.value("models", "timeout_seconds"),
                "retry_count": self.value("models", "retry_count"),
            }
        return {
            "provider": self.get_model_provider(),
            "base_url": str(self.value("models", "base_url") or ""),
            "chat_model": str(self.value("models", "chat_model") or ""),
            "strong_model": str(self.value("models", "strong_model") or ""),
            "temperature": self.value("models", "temperature"),
            "max_tokens": self.value("models", "max_tokens"),
            "timeout_seconds": self.value("models", "timeout_seconds"),
            "retry_count": self.value("models", "retry_count"),
        }

    def llm_enabled(self) -> bool:
        """True when an agentic LLM chat path can actually run."""
        provider = self.get_model_provider()
        if provider == "none":
            return False
        if not bool(self.value("agent", "enabled")):
            return False
        if provider == "ollama":
            return True
        return self.api_key_configured(provider)

    def supported_agent_providers(self) -> list[str]:
        """Providers the agent LLM path can actually drive (mirrors llm.client.build_llm_client)."""
        return ["openai", "openai_compatible", "deepseek", "ollama"]

    def readiness(self) -> dict[str, Any]:
        """Structured runtime-readiness contract for the agent chat path.

        Unlike :meth:`llm_enabled` (a bare bool), this explains *why* the agent is
        Ready / Not Ready and what it falls back to, so the UI can surface concrete
        reasons. Reason codes: ``provider_none``, ``agent_disabled``,
        ``provider_unsupported``, ``missing_chat_model``, ``missing_base_url``,
        ``missing_api_key``, ``research_agent_unavailable``.
        """
        config = self.model_config()
        provider = config["provider"]
        base_url = str(config.get("base_url") or "") or _DEFAULT_BASE_URLS.get(provider, "")
        chat_model = str(config.get("chat_model") or "")
        source = self.api_key_source(provider)
        active_model = {
            "provider": provider,
            "model": chat_model,
            "base_url": base_url,
            "api_key_source": source,
        }

        reasons: list[str] = []
        warnings: list[str] = []
        if provider == "none":
            reasons.append("provider_none")
        else:
            if not bool(self.value("agent", "enabled")):
                reasons.append("agent_disabled")
            if provider not in self.supported_agent_providers():
                reasons.append("provider_unsupported")
            if not chat_model:
                reasons.append("missing_chat_model")
            if provider == "openai_compatible" and not str(self.value("models", "base_url") or ""):
                reasons.append("missing_base_url")
            if provider != "ollama" and provider in self.supported_agent_providers():
                try:
                    from core.llm.client import resolve_api_key

                    if not resolve_api_key(provider):
                        reasons.append("missing_api_key")
                except Exception:  # noqa: BLE001 - key resolution must never break readiness
                    reasons.append("missing_api_key")
            if provider == "ollama" and chat_model and not self._ollama_model_available(chat_model, base_url):
                reasons.append("ollama_model_unavailable")
            if not self._research_agent_importable():
                reasons.append("research_agent_unavailable")

        if source == "env" and self._active_profile_has_key(provider):
            warnings.append("env_overrides_profile")

        ready = not reasons
        return {
            "ready": ready,
            "mode": "agent" if ready else "blocked",
            "active_model": active_model,
            "reasons": reasons,
            "warnings": warnings,
            "fallback_mode": None if ready else "blocked_requires_llm",
        }

    def _active_profile_has_key(self, provider: str) -> bool:
        try:
            from core.model_profiles import model_profile_store

            active = model_profile_store.active()
            return bool(active and active.get("provider") == provider and active.get("has_key"))
        except Exception:  # noqa: BLE001
            return False

    def _research_agent_importable(self) -> bool:
        try:
            from modules.literature_search.service import LiteratureResearchService

            LiteratureResearchService()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _ollama_model_available(self, model: str, base_url: str, *, timeout: float = 1.5) -> bool:
        root = _ollama_root_url(base_url)
        try:
            with urllib.request.urlopen(f"{root}/api/tags", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return False
        wanted = _normalize_ollama_model(model)
        for item in payload.get("models") or []:
            name = _normalize_ollama_model(item.get("name") or item.get("model") or "")
            if name == wanted:
                return True
        return False

    def memory_context_limits(self) -> dict[str, int]:
        message_limit = _positive_int(self.value("memory", "context_message_limit"), 8)
        search_limit = _positive_int(self.value("memory", "context_search_limit"), 8)
        multiplier = _positive_int(self.value("memory", "evidence_limit_multiplier"), 3)
        return {
            "message_limit": message_limit,
            "search_limit": search_limit,
            "evidence_limit": search_limit * multiplier,
        }

    def diagnostics(self) -> dict[str, Any]:
        checks = [
            self._check_backend(),
            self._check_settings_db(),
            self._check_memory_db(),
            self._check_research_paths(),
            self._check_research_import(),
            self._check_selfcheck(),
            self._check_index_status(),
            self._check_vector_status(),
            self._check_llm_config(),
            self._check_external_sources(),
            self._check_artifact_root(),
            self._check_recent_failed_jobs(),
        ]
        statuses = [check["status"] for check in checks]
        overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
        return {"overall": overall, "checks": checks}

    def test_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        from core.llm.client import resolve_api_key, test_chat_completion

        provider = payload.get("provider") or self.get_model_provider()
        if provider == "none":
            return {
                "available": False,
                "provider": provider,
                "message": "Provider 为 none：未启用 LLM，文献检索问答无法生成证据接地回答。",
            }

        base_url = payload.get("base_url") or self.value("models", "base_url") or None
        model = payload.get("model") or self.value("models", "chat_model")
        if not model:
            return {
                "available": False,
                "provider": provider,
                "message": "未配置 Chat Model，无法测试。",
            }
        api_key = resolve_api_key(provider)
        if not api_key:
            return {
                "available": False,
                "provider": provider,
                "message": "缺少 API key：请在此保存密钥或设置环境变量。",
                "api_key_configured": False,
            }
        if not base_url:
            base_url = _DEFAULT_BASE_URLS.get(provider)
        return test_chat_completion(provider=provider, model=model, base_url=base_url, api_key=api_key)

    def get_model_provider(self) -> str:
        active = self._active_model_profile()
        if active:
            return str(active.get("provider") or "none")
        return str(self.value("models", "provider") or "none")

    def _active_model_profile(self) -> dict[str, Any] | None:
        try:
            from core.model_profiles import model_profile_store

            active = model_profile_store.active()
            if active and active.get("provider"):
                return active
        except Exception:  # noqa: BLE001
            return None
        return None

    def platform_role(self) -> str:
        """Maintenance role for the current (single-user) session.

        Block 0 reserves the admin/viewer boundary for future multi-user auth.
        Today it is env-driven: ``LITERATURE_PLATFORM_ROLE=viewer`` makes the
        Research Index Health page read-only; the default ``admin`` may trigger
        maintenance jobs. ``viewer`` is the only value that disables maintenance.
        """
        role = (os.getenv("LITERATURE_PLATFORM_ROLE") or "admin").strip().lower()
        return "viewer" if role == "viewer" else "admin"

    def api_key_configured(self, provider: str) -> bool:
        return self.api_key_source(provider) is not None

    def api_key_source(self, provider: str) -> str | None:
        """Where the API key for `provider` comes from: 'env', 'profile', 'stored', or None.

        Precedence mirrors `llm.client.resolve_api_key`: env wins (keeps `export`
        workflows working), then the active model profile, then a legacy
        per-provider stored key. Never returns the key itself.
        """
        from core.secret_store import secret_store

        if provider == "none":
            names = {name for values in SECRET_ENV_BY_PROVIDER.values() for name in values}
            if any(os.getenv(name) for name in names):
                return "env"
            return "stored" if secret_store.providers() else None
        env_names = SECRET_ENV_BY_PROVIDER.get(provider, ["LITERATURE_LLM_API_KEY"])
        if any(os.getenv(name) for name in env_names):
            return "env"
        from core.model_profiles import model_profile_store

        active = model_profile_store.active()
        if active and active.get("provider") == provider and active.get("has_key"):
            return "profile"
        if secret_store.has(provider):
            return "stored"
        return None

    def external_source_key_configured(self, source: str) -> bool:
        return self.external_source_key_source(source) is not None

    def external_source_key_source(self, source: str) -> str | None:
        from core.secret_store import secret_store

        env_names = {
            "semantic_scholar": ["SEMANTIC_SCHOLAR_API_KEY"],
            "exa": ["EXA_API_KEY"],
            "openalex": ["OPENALEX_API_KEY"],
        }.get(source, [])
        if any(os.getenv(name) for name in env_names):
            return "env"
        if secret_store.has(f"external:{source}"):
            return "stored"
        return None

    def research_agent_status(self) -> dict[str, dict[str, Any]]:
        code_dir = os.getenv("LITERATURE_RESEARCH_CODE_DIR") or "/Users/chenlintao/paper-crawler-ops/literature_research"
        data_dir = os.getenv("LITERATURE_DATA_DIR") or "/Users/chenlintao/paper-crawler-ops/literature_data"
        memory_path = str(memory_db_path(self.db_path))
        artifact_root = str(Path(data_dir) / "research_agent")
        return {
            "code_dir": {"value": code_dir, "source": "env" if os.getenv("LITERATURE_RESEARCH_CODE_DIR") else "default"},
            "data_dir": {"value": data_dir, "source": "env" if os.getenv("LITERATURE_DATA_DIR") else "default"},
            "memory_db_path": {"value": memory_path, "source": "env" if os.getenv("LITERATURE_MEMORY_DB_PATH") else "default"},
            "artifact_root": {"value": artifact_root, "source": "derived"},
        }

    def _resolve(self, scope: str, key: str, default: Any, rows: dict[tuple[str, str], Any]):
        if (scope, key) in rows:
            return rows[(scope, key)], "sqlite"
        env_name = ENV_MAP.get((scope, key))
        if env_name and os.getenv(env_name) not in (None, ""):
            return _cast(os.getenv(env_name), default), "env"
        return default, "default"

    def _hydrate_runtime(self, grouped: dict[str, dict[str, Any]]) -> None:
        active = self._active_model_profile()
        if active:
            grouped["models"]["provider"] = active.get("provider") or grouped["models"].get("provider")
            grouped["models"]["base_url"] = active.get("base_url") or ""
            grouped["models"]["chat_model"] = active.get("model") or ""
            grouped["models"]["active_profile_id"] = active.get("id")
            grouped["models"]["active_profile_name"] = active.get("name")
        provider = str(grouped["models"].get("provider") or "none")
        grouped["models"]["api_key_configured"] = self.api_key_configured(provider)
        grouped["models"]["api_key_source"] = self.api_key_source(provider)
        grouped["models"]["llm_enabled"] = self.llm_enabled()
        grouped.setdefault("agent", {})["agent_chat_ready"] = self.llm_enabled()
        grouped["research_agent"] = {
            key: value["value"] for key, value in self.research_agent_status().items()
        }
        grouped["memory"]["db_path"] = str(memory_db_path(self.db_path))
        grouped["memory"]["stats"] = self.memory_stats()
        grouped["external_sources"].update({
            "semantic_scholar_key_configured": self.external_source_key_configured("semantic_scholar"),
            "semantic_scholar_key_source": self.external_source_key_source("semantic_scholar"),
            "exa_key_configured": self.external_source_key_configured("exa"),
            "exa_key_source": self.external_source_key_source("exa"),
            "openalex_key_configured": self.external_source_key_configured("openalex"),
            "openalex_key_source": self.external_source_key_source("openalex"),
        })
        grouped["diagnostics"] = {"last_run": None}

    def memory_stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}
        for table in [
            "sessions",
            "messages",
            "turns",
            "search_results",
            "evidence_items",
            "jobs",
            "conversation_artifact_links",
        ]:
            try:
                stats[table] = self.conn.execute(f"select count(*) as n from {table}").fetchone()["n"]
            except sqlite3.Error:
                stats[table] = 0
        path = memory_db_path(self.db_path)
        stats["db_exists"] = path.exists()
        stats["db_size_bytes"] = path.stat().st_size if path.exists() else 0
        stats["db_modified_at"] = path.stat().st_mtime if path.exists() else None
        return stats

    def _check(self, check_id: str, label: str, func):
        checked_at = time.time()
        try:
            detail = func()
            status = "ok"
            if isinstance(detail, dict) and detail.get("status") in {"warning", "error"}:
                status = detail["status"]
            return {"id": check_id, "status": status, "label": label, "detail": detail, "checked_at": checked_at}
        except Exception as exc:  # noqa: BLE001
            return {"id": check_id, "status": "error", "label": label, "detail": {"error": str(exc)}, "checked_at": checked_at}

    def _check_backend(self):
        return self._check("backend.health", "Backend health", lambda: {"status": "ok"})

    def _check_settings_db(self):
        return self._check("settings.db", "Settings database", lambda: {"path": str(memory_db_path(self.db_path)), "status": "ok"})

    def _check_memory_db(self):
        return self._check("memory.db", "Memory database", lambda: self.memory_stats())

    def _check_research_paths(self):
        def run():
            status = self.research_agent_status()
            code_dir = Path(status["code_dir"]["value"])
            data_dir = Path(status["data_dir"]["value"])
            return {
                "status": "ok" if code_dir.exists() and data_dir.exists() else "error",
                "code_dir_exists": code_dir.exists(),
                "data_dir_exists": data_dir.exists(),
            }

        return self._check("research_agent.paths", "Research Agent paths", run)

    def _check_research_import(self):
        def run():
            from modules.literature_search.service import LiteratureResearchService

            LiteratureResearchService()
            return {"status": "ok"}

        return self._check("research_agent.import", "Research Agent import", run)

    def _check_selfcheck(self):
        def run():
            from modules.literature_search.service import LiteratureResearchService

            return LiteratureResearchService().selfcheck()

        return self._check("research_agent.selfcheck", "Research Agent selfcheck", run)

    def _check_index_status(self):
        def run():
            from modules.literature_search.service import LiteratureResearchService

            return LiteratureResearchService().index_status()

        return self._check("research_agent.index", "Index status", run)

    def _check_vector_status(self):
        def run():
            from modules.literature_search.service import LiteratureResearchService

            return LiteratureResearchService().vector_status()

        return self._check("research_agent.vector", "Vector status", run)

    def _check_llm_config(self):
        def run():
            provider = self.get_model_provider()
            if provider == "none":
                return {"status": "warning", "provider": provider, "message": "未启用 LLM；文献检索问答需要可用模型。"}
            configured = self.api_key_configured(provider)
            has_model = bool(self.value("models", "chat_model"))
            ok = configured and has_model
            return {
                "status": "ok" if ok else "warning",
                "provider": provider,
                "api_key_configured": configured,
                "api_key_source": self.api_key_source(provider),
                "chat_model_configured": has_model,
                "agent_chat_ready": self.llm_enabled() and has_model,
            }

        return self._check("models.llm", "LLM configuration", run)

    def _check_external_sources(self):
        def run():
            detail = {
                "arxiv": {
                    "status": "ok",
                    "api_key_required": False,
                    "contact_email_configured": bool(os.getenv("ARIS_VERIFY_EMAIL")),
                },
                "semantic_scholar": {
                    "status": "ok",
                    "api_key_required": False,
                    "api_key_configured": self.external_source_key_configured("semantic_scholar"),
                    "api_key_source": self.external_source_key_source("semantic_scholar"),
                    "enabled": bool(self.value("external_sources", "semantic_scholar_enabled")),
                },
                "openalex": {
                    "status": "ok",
                    "api_key_required": False,
                    "api_key_configured": self.external_source_key_configured("openalex"),
                    "api_key_source": self.external_source_key_source("openalex"),
                    "email_configured": bool(os.getenv("OPENALEX_EMAIL") or self.value("external_sources", "openalex_email")),
                    "enabled": bool(self.value("external_sources", "openalex_enabled")),
                },
                "exa": {
                    "status": "ok" if self.external_source_key_configured("exa") else "skipped_no_api_key",
                    "api_key_required": True,
                    "api_key_configured": self.external_source_key_configured("exa"),
                    "api_key_source": self.external_source_key_source("exa"),
                    "enabled": bool(self.value("external_sources", "exa_enabled")),
                },
                "crossref": {
                    "status": "ok",
                    "api_key_required": False,
                    "role": "doi_verification",
                    "enabled": bool(self.value("external_sources", "crossref_enabled")),
                },
            }
            overall = "warning" if detail["exa"]["status"] != "ok" else "ok"
            return {"status": overall, **detail}

        return self._check("external_sources.scholarly", "External scholarly sources", run)

    def _check_artifact_root(self):
        def run():
            artifact_root = Path(self.research_agent_status()["artifact_root"]["value"])
            return {"status": "ok" if artifact_root.exists() else "warning", "path": str(artifact_root), "exists": artifact_root.exists()}

        return self._check("artifacts.root", "Artifact root", run)

    def _check_recent_failed_jobs(self):
        def run():
            failed = self.conn.execute("select count(*) as n from jobs where status = 'failed'").fetchone()["n"]
            return {"status": "warning" if failed else "ok", "failed_jobs": failed}

        return self._check("jobs.failed", "Recent failed jobs", run)

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
    # "audit" (default): deterministic floor only — no per-claim LLM grounding pass.
    # Fabricated-citation flagging + no-evidence not_answerable still apply; the
    # answer is never silently rewritten/deleted by an LLM judge.
    # "strict"/"warn": additionally run the LLM grounding pass (opt-in).
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
