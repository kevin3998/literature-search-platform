from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from core.schemas import ChatMessage
from core.settings_store import DEFAULTS

if not os.getenv("DATABASE_URL"):
    pytest.skip(
        "M2 settings store tests require DATABASE_URL; see test_postgres_m2_core_runtime.py for migrated coverage.",
        allow_module_level=True,
    )


def test_settings_api_defaults_save_effective_and_secret_redaction(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    monkeypatch.setenv("LITERATURE_SEARCH_DEFAULT_RETRIEVAL", "vector")

    import main

    client = TestClient(main.app)

    defaults = client.get("/api/settings").json()
    assert set(defaults) >= {"general", "models", "research_agent", "retrieval", "memory", "diagnostics"}
    assert defaults["general"]["platform_name"] == "文献智能体平台"
    assert defaults["models"]["api_key_configured"] is True
    assert "sk-secret-value" not in str(defaults)

    response = client.patch(
        "/api/settings",
        json={
            "general": {"platform_name": "Research Desk"},
            "retrieval": {"default_retrieval": "fts", "default_limit": 5},
            "memory": {"context_message_limit": 2},
            "models": {"provider": "openai", "chat_model": "gpt-test"},
        },
    )
    assert response.status_code == 200
    assert response.json()["general"]["platform_name"] == "Research Desk"

    effective = client.get("/api/settings/effective").json()
    assert effective["general.platform_name"] == {"value": "Research Desk", "source": "sqlite"}
    assert effective["retrieval.default_retrieval"] == {"value": "fts", "source": "sqlite"}
    assert effective["models.provider"] == {"value": "openai", "source": "sqlite"}
    assert effective["models.api_key_configured"]["value"] is True
    assert "sk-secret-value" not in str(effective)

    model_test = client.post("/api/settings/models/test", json={"provider": "none"}).json()
    assert model_test["available"] is False


def test_default_limits_are_expanded_for_product_research_turns():
    assert DEFAULTS["agent"]["max_tool_iterations"] == 10
    assert DEFAULTS["agent"]["tool_budget"] == 24
    assert DEFAULTS["agent"]["max_search_calls_per_turn"] == 8
    assert DEFAULTS["retrieval"]["default_limit"] == 20
    assert DEFAULTS["retrieval"]["default_evidence_per_article_limit"] == 5
    assert DEFAULTS["memory"]["context_search_limit"] == 16
    assert DEFAULTS["memory"]["evidence_limit_multiplier"] == 4


def test_readiness_reports_unreadable_active_profile_credential(monkeypatch):
    from core.settings_store import SettingsStore

    store = object.__new__(SettingsStore)
    monkeypatch.setattr(store, "model_config", lambda user_id=None: {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "chat_model": "deepseek-chat",
    })
    monkeypatch.setattr(store, "value", lambda scope, key, user_id=None: True if (scope, key) == ("agent", "enabled") else "")
    monkeypatch.setattr(store, "api_key_source", lambda provider, user_id=None: None)
    monkeypatch.setattr(store, "api_key_configured", lambda provider, user_id=None: False)
    monkeypatch.setattr(store, "_active_model_profile", lambda user_id=None: {"provider": "deepseek", "key_status": "unreadable"})

    result = store.readiness(user_id="00000000-0000-4000-8000-000000000001")

    assert result["ready"] is False
    assert result["reasons"] == ["credential_unreadable"]


def test_settings_diagnostics_report_external_source_status(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "s2-key")
    monkeypatch.setenv("OPENALEX_EMAIL", "lab@example.com")
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    import main

    client = TestClient(main.app)
    checks = client.get("/api/settings/diagnostics").json()["checks"]
    external = next(c for c in checks if c["id"] == "external_sources.scholarly")
    assert external["status"] == "warning"
    assert external["detail"]["semantic_scholar"]["api_key_configured"] is True
    assert external["detail"]["openalex"]["email_configured"] is True
    assert external["detail"]["exa"]["status"] == "skipped_no_api_key"


def test_external_sources_settings_and_secrets_do_not_leak(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    import core.secret_store as secret_module

    isolated = secret_module.SecretStore(key_path=tmp_path / "k.key", store_path=tmp_path / "s.enc")
    monkeypatch.setattr(secret_module, "secret_store", isolated)

    import main

    client = TestClient(main.app)
    response = client.patch(
        "/api/settings",
        json={
            "external_sources": {
                "semantic_scholar_enabled": True,
                "exa_enabled": True,
                "default_year_window": 5,
                "per_source_limit": 4,
                "timeout_seconds": 11,
                "retry_count": 1,
            }
        },
    )
    assert response.status_code == 200
    settings = response.json()
    assert settings["external_sources"]["default_year_window"] == 5
    assert settings["external_sources"]["semantic_scholar_key_configured"] is False

    saved = client.post("/api/settings/external-sources/secret", json={"source": "semantic_scholar", "api_key": "s2-secret"}).json()
    assert saved["configured"] is True
    assert saved["source"] == "semantic_scholar"

    settings = client.get("/api/settings").json()
    assert settings["external_sources"]["semantic_scholar_key_configured"] is True
    assert "s2-secret" not in str(settings)

    effective = client.get("/api/settings/effective").json()
    assert effective["external_sources.default_year_window"] == {"value": 5, "source": "sqlite"}
    assert effective["external_sources.semantic_scholar_key_configured"]["value"] is True
    assert "s2-secret" not in str(effective)


def test_model_secret_stored_encrypted_and_never_leaked(monkeypatch, tmp_path):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    # Ensure no env key for openai so a stored key is the only source.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LITERATURE_LLM_API_KEY", raising=False)

    import core.secret_store as secret_module

    isolated = secret_module.SecretStore(key_path=tmp_path / "k.key", store_path=tmp_path / "s.enc")
    monkeypatch.setattr(secret_module, "secret_store", isolated)

    import main

    client = TestClient(main.app)
    client.patch("/api/settings", json={"models": {"provider": "openai", "chat_model": "gpt-test"}})

    # Before saving: not configured.
    before = client.get("/api/settings").json()
    assert before["models"]["api_key_configured"] is False

    # Save the key via the dedicated endpoint.
    saved = client.post("/api/settings/models/secret", json={"provider": "openai", "api_key": "sk-stored-XYZ"}).json()
    assert saved["configured"] is True
    assert saved["source"] == "stored"

    settings = client.get("/api/settings").json()
    assert settings["models"]["api_key_configured"] is True
    assert settings["models"]["api_key_source"] == "stored"
    assert "sk-stored-XYZ" not in str(settings)

    effective = client.get("/api/settings/effective").json()
    assert effective["models.api_key_configured"]["value"] is True
    assert effective["models.api_key_source"]["value"] == "stored"
    assert "sk-stored-XYZ" not in str(effective)

    # Ciphertext on disk must not contain the plaintext key.
    assert b"sk-stored-XYZ" not in (tmp_path / "s.enc").read_bytes()

    # Delete clears it.
    client.request("DELETE", "/api/settings/models/secret", json={"provider": "openai"})
    assert client.get("/api/settings").json()["models"]["api_key_configured"] is False


def test_settings_retrieval_defaults_feed_literature_search_but_explicit_payload_wins(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.literature_search_router as literature_router
    import main

    calls = []

    class FakeService:
        def search(self, query, **options):
            calls.append(options)
            return {"query": query, "results": [], "query_plan": {"retrieval_used": options["retrieval"]}}

    monkeypatch.setattr(literature_router, "service", FakeService())
    client = TestClient(main.app)

    client.patch(
        "/api/settings",
        json={"retrieval": {"default_retrieval": "fts", "default_limit": 4, "default_scope": "library"}},
    )

    response = client.post("/api/literature-search/search", json={"query": "battery"})
    assert response.status_code == 200
    assert calls[-1]["retrieval"] == "fts"
    assert calls[-1]["limit"] == 4

    response = client.post(
        "/api/literature-search/search",
        json={"query": "battery", "retrieval": "hybrid", "limit": 9},
    )
    assert response.status_code == 200
    assert calls[-1]["retrieval"] == "hybrid"
    assert calls[-1]["limit"] == 9


def test_memory_context_limit_uses_settings(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.modules_router as modules_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", store)
    client = TestClient(main.app)

    client.patch("/api/settings", json={"memory": {"context_message_limit": 2}})
    session = store.create_session(module_id="literature_search", title="Memory")
    for index in range(5):
        store.append(session["session_id"], ChatMessage(role="user", content=f"m{index}"))

    context = client.get(f"/api/sessions/{session['session_id']}/context").json()
    assert [item["content"] for item in context["recent_messages"]] == ["m3", "m4"]


def _ready_env(monkeypatch):
    """Make readiness depend only on model config: research import OK, no stray env keys."""
    from core.settings_store import settings_store as singleton

    monkeypatch.setattr(singleton, "_research_agent_importable", lambda: True)
    for name in ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "LITERATURE_LLM_API_KEY"]:
        monkeypatch.delenv(name, raising=False)


def test_readiness_provider_none_not_ready(monkeypatch):
    _ready_env(monkeypatch)
    import main

    client = TestClient(main.app)
    client.patch("/api/settings", json={"models": {"provider": "none", "chat_model": ""}})

    body = client.get("/api/settings/readiness").json()
    assert set(body) >= {"ready", "mode", "active_model", "reasons", "warnings", "fallback_mode"}
    assert body["ready"] is False
    assert body["mode"] == "blocked"
    assert body["fallback_mode"] == "blocked_requires_llm"
    assert body["reasons"] == ["provider_none"]


def test_readiness_missing_chat_model(monkeypatch):
    _ready_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    import main

    client = TestClient(main.app)
    client.patch("/api/settings", json={"agent": {"enabled": True}, "models": {"provider": "openai", "chat_model": ""}})

    body = client.get("/api/settings/readiness").json()
    assert body["ready"] is False
    assert "missing_chat_model" in body["reasons"]


def test_readiness_openai_compatible_requires_base_url(monkeypatch):
    _ready_env(monkeypatch)
    monkeypatch.setenv("LITERATURE_LLM_API_KEY", "sk-x")
    import main

    client = TestClient(main.app)
    client.patch(
        "/api/settings",
        json={"agent": {"enabled": True}, "models": {"provider": "openai_compatible", "chat_model": "m", "base_url": ""}},
    )

    body = client.get("/api/settings/readiness").json()
    assert body["ready"] is False
    assert "missing_base_url" in body["reasons"]


def test_readiness_deepseek_ready(monkeypatch):
    _ready_env(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deep")
    import main

    client = TestClient(main.app)
    client.patch(
        "/api/settings",
        json={"agent": {"enabled": True}, "models": {"provider": "deepseek", "chat_model": "deepseek-chat", "base_url": ""}},
    )

    body = client.get("/api/settings/readiness").json()
    assert body["ready"] is True, body["reasons"]
    assert body["mode"] == "agent"
    assert body["active_model"]["provider"] == "deepseek"


def test_readiness_ollama_ready_without_key(monkeypatch):
    _ready_env(monkeypatch)
    import main
    from core.settings_store import settings_store as singleton

    monkeypatch.setattr(singleton, "_ollama_model_available", lambda model, base_url: True)

    client = TestClient(main.app)
    client.patch(
        "/api/settings",
        json={"agent": {"enabled": True}, "models": {"provider": "ollama", "chat_model": "llama3.1", "base_url": ""}},
    )

    body = client.get("/api/settings/readiness").json()
    assert body["ready"] is True, body["reasons"]
    assert body["mode"] == "agent"


def test_readiness_ollama_model_must_exist(monkeypatch):
    _ready_env(monkeypatch)
    import main
    from core.settings_store import settings_store as singleton

    monkeypatch.setattr(singleton, "_ollama_model_available", lambda model, base_url: False)

    client = TestClient(main.app)
    client.patch(
        "/api/settings",
        json={"agent": {"enabled": True}, "models": {"provider": "ollama", "chat_model": "llama3.1", "base_url": ""}},
    )

    body = client.get("/api/settings/readiness").json()
    assert body["ready"] is False
    assert body["mode"] == "blocked"
    assert body["fallback_mode"] == "blocked_requires_llm"
    assert "ollama_model_unavailable" in body["reasons"]


def test_active_model_profile_overrides_stale_models_settings(monkeypatch):
    _ready_env(monkeypatch)
    import main
    from core.settings_store import settings_store as singleton

    client = TestClient(main.app)
    created = client.post(
        "/api/settings/model-profiles",
        json={
            "name": "DeepSeek API",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-profile-secret",
        },
    ).json()
    client.post(f"/api/settings/model-profiles/{created['id']}/activate")

    # Simulate stale legacy settings left behind by an older local-model config.
    client.patch("/api/settings", json={"models": {"provider": "ollama", "chat_model": "llama3.1", "base_url": ""}})

    body = client.get("/api/settings/readiness").json()
    assert body["ready"] is True
    assert body["mode"] == "agent"
    assert body["active_model"]["provider"] == "deepseek"
    assert body["active_model"]["model"] == "deepseek-chat"
    assert body["active_model"]["api_key_source"] == "profile"
    assert "ollama_model_unavailable" not in body["reasons"]

    config = singleton.model_config()
    assert config["provider"] == "deepseek"
    assert config["chat_model"] == "deepseek-chat"
    assert config["base_url"] == "https://api.deepseek.com/v1"

    settings = client.get("/api/settings").json()
    assert settings["models"]["provider"] == "deepseek"
    assert settings["models"]["chat_model"] == "deepseek-chat"
    assert settings["models"]["base_url"] == "https://api.deepseek.com/v1"
    assert settings["models"]["api_key_source"] == "profile"

    effective = client.get("/api/settings/effective").json()
    assert effective["models.provider"] == {"value": "deepseek", "source": "profile"}
    assert effective["models.chat_model"] == {"value": "deepseek-chat", "source": "profile"}
    assert effective["models.base_url"] == {"value": "https://api.deepseek.com/v1", "source": "profile"}


def test_settings_diagnostics_return_structured_errors(monkeypatch, tmp_path):
    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("LITERATURE_RESEARCH_CODE_DIR", str(tmp_path / "missing-code"))
    monkeypatch.setenv("LITERATURE_DATA_DIR", str(tmp_path / "missing-data"))

    import main

    client = TestClient(main.app)
    response = client.get("/api/settings/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] in {"warning", "error"}
    assert any(check["status"] == "error" for check in body["checks"])
