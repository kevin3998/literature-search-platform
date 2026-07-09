from __future__ import annotations

import core.secret_store as secret_module
from core.model_profiles import ModelProfileStore


def _store(tmp_path):
    secrets = secret_module.SecretStore(key_path=tmp_path / "k.key", store_path=tmp_path / "s.enc")
    return ModelProfileStore(db_path=tmp_path / "memory.sqlite", secret_store=secrets)


def test_create_lists_masked_and_never_plaintext(tmp_path):
    store = _store(tmp_path)
    profile = store.create(name="DeepSeek主力", provider="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key="sk-deepseek-PLAINTEXT-123")

    listed = store.list()
    assert len(listed) == 1
    row = listed[0]
    assert row["name"] == "DeepSeek主力"
    assert row["provider"] == "deepseek"
    assert row["has_key"] is True
    assert row["key_masked"] == "sk-dee...-123"
    assert "sk-deepseek-PLAINTEXT-123" not in str(listed)

    # ciphertext on disk has no plaintext
    assert b"sk-deepseek-PLAINTEXT-123" not in (tmp_path / "s.enc").read_bytes()

    # reveal returns plaintext on explicit demand
    assert store.reveal(profile["id"]) == "sk-deepseek-PLAINTEXT-123"


def test_activate_mirrors_models_scope_and_resolves_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LITERATURE_LLM_API_KEY", raising=False)

    secrets = secret_module.SecretStore(key_path=tmp_path / "k.key", store_path=tmp_path / "s.enc")
    monkeypatch.setattr(secret_module, "secret_store", secrets)
    store = ModelProfileStore(db_path=tmp_path / "memory.sqlite", secret_store=secrets)

    profile = store.create(name="ds", provider="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key="sk-active-KEY")
    store.activate(profile["id"])

    from core.settings_store import SettingsStore

    settings = SettingsStore(db_path=tmp_path / "memory.sqlite")
    # activate mirrored provider/base_url/model into the models scope
    assert settings.value("models", "provider") == "deepseek"
    assert settings.value("models", "chat_model") == "deepseek-chat"

    # key resolution + source reflect the active profile (need the same profile store)
    monkeypatch.setattr("core.model_profiles.model_profile_store", store)
    from core.llm.client import resolve_api_key

    assert resolve_api_key("deepseek") == "sk-active-KEY"
    assert settings.api_key_source("deepseek") == "profile"


def test_active_profile_key_source_requires_readable_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LITERATURE_LLM_API_KEY", raising=False)

    secrets = secret_module.SecretStore(key_path=tmp_path / "k.key", store_path=tmp_path / "s.enc")
    monkeypatch.setattr(secret_module, "secret_store", secrets)
    store = ModelProfileStore(db_path=tmp_path / "memory.sqlite", secret_store=secrets)

    profile = store.create(name="ds", provider="deepseek", base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key="sk-active-KEY")
    store.activate(profile["id"])
    secrets.delete("cred:" + profile["id"])

    from core.settings_store import SettingsStore

    monkeypatch.setattr("core.model_profiles.model_profile_store", store)
    settings = SettingsStore(db_path=tmp_path / "memory.sqlite")

    assert store.active()["has_key"] is False
    assert store.active_api_key() is None
    assert settings.api_key_source("deepseek") is None


def test_update_keeps_key_when_blank_and_delete_removes_secret(tmp_path):
    store = _store(tmp_path)
    profile = store.create(name="a", provider="openai", model="gpt-4o", api_key="sk-original")

    # update without api_key keeps the stored key
    store.update(profile["id"], name="renamed")
    assert store.reveal(profile["id"]) == "sk-original"
    assert store.get(profile["id"])["name"] == "renamed"

    # update with a new key replaces it and refreshes the mask
    store.update(profile["id"], api_key="sk-rotated-9999")
    assert store.reveal(profile["id"]) == "sk-rotated-9999"

    store.delete(profile["id"])
    assert store.list() == []
    assert store.secrets.get("cred:" + profile["id"]) is None


def test_only_one_active_at_a_time(tmp_path):
    store = _store(tmp_path)
    a = store.create(name="a", provider="openai", model="gpt-4o", api_key="sk-a")
    b = store.create(name="b", provider="deepseek", model="deepseek-chat", api_key="sk-b")

    store.activate(a["id"])
    store.activate(b["id"])
    active = store.active()
    assert active["id"] == b["id"]
    assert [p["active"] for p in store.list() if p["id"] == a["id"]] == [False]
