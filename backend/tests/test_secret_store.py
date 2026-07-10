from __future__ import annotations

from core.secret_store import SecretStore


def _store(tmp_path):
    return SecretStore(
        key_path=tmp_path / "secret.key",
        store_path=tmp_path / "secrets.enc",
    )


def test_set_get_delete_has_roundtrip(tmp_path):
    store = _store(tmp_path)
    assert store.has("openai") is False
    assert store.get("openai") is None

    store.set("openai", "sk-roundtrip-123")
    assert store.has("openai") is True
    assert store.get("openai") == "sk-roundtrip-123"
    assert store.providers() == ["openai"]

    # reloading from disk (new instance, same paths) decrypts the same value
    reloaded = SecretStore(key_path=tmp_path / "secret.key", store_path=tmp_path / "secrets.enc")
    assert reloaded.get("openai") == "sk-roundtrip-123"

    assert store.delete("openai") is True
    assert store.has("openai") is False
    assert store.delete("openai") is False


def test_ciphertext_does_not_contain_plaintext(tmp_path):
    store = _store(tmp_path)
    store.set("openai", "sk-super-secret-value")
    raw = (tmp_path / "secrets.enc").read_bytes()
    assert b"sk-super-secret-value" not in raw
    assert b"openai" not in raw  # whole JSON payload is encrypted


def test_wrong_master_key_cannot_decrypt(tmp_path):
    store = _store(tmp_path)
    store.set("openai", "sk-isolated")

    # A different key file over the same ciphertext yields no plaintext (no crash).
    other = SecretStore(key_path=tmp_path / "other.key", store_path=tmp_path / "secrets.enc")
    assert other.get("openai") is None
    assert other.providers() == []


def test_has_requires_a_decryptable_secret(monkeypatch):
    store = object.__new__(SecretStore)
    monkeypatch.setattr(store, "status", lambda _secret_type, user_id=None: "unreadable")

    assert store.has("deepseek") is False
