"""Encrypted at-rest store for provider API keys.

The platform deliberately keeps API keys out of the conversation memory DB
(`platform_memory.sqlite`, which the README recommends backing up) and never
returns them to the frontend. This store lets the user configure keys from the
UI without that tradeoff: keys are encrypted with Fernet and persisted to a
file kept *outside* the backed-up data dir.

Layout (both overridable by env, both created with 0600 perms):
    master key  ~/.literature-agent/secret.key   (LITERATURE_SECRET_KEY_PATH)
    ciphertext  ~/.literature-agent/secrets.enc  (LITERATURE_SECRET_STORE_PATH)

Only `get()` returns plaintext, and only the backend calls it (LLM client).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DEFAULT_DIR = Path.home() / ".literature-agent"
DEFAULT_KEY_PATH = DEFAULT_DIR / "secret.key"
DEFAULT_STORE_PATH = DEFAULT_DIR / "secrets.enc"


def _key_path() -> Path:
    return Path(os.getenv("LITERATURE_SECRET_KEY_PATH") or DEFAULT_KEY_PATH).expanduser()


def _store_path() -> Path:
    return Path(os.getenv("LITERATURE_SECRET_STORE_PATH") or DEFAULT_STORE_PATH).expanduser()


class SecretStore:
    """Per-provider API key store, encrypted at rest."""

    def __init__(self, key_path: str | Path | None = None, store_path: str | Path | None = None) -> None:
        self.key_path = Path(key_path).expanduser() if key_path else _key_path()
        self.store_path = Path(store_path).expanduser() if store_path else _store_path()

    # --- public API -------------------------------------------------------------

    def set(self, provider: str, api_key: str) -> None:
        if not provider or not api_key:
            raise ValueError("provider and api_key are required")
        data = self._load()
        data[provider] = api_key
        self._save(data)

    def get(self, provider: str) -> str | None:
        return self._load().get(provider)

    def delete(self, provider: str) -> bool:
        data = self._load()
        if provider in data:
            del data[provider]
            self._save(data)
            return True
        return False

    def has(self, provider: str) -> bool:
        value = self._load().get(provider)
        return bool(value)

    def providers(self) -> list[str]:
        return [provider for provider, value in self._load().items() if value]

    # --- internals --------------------------------------------------------------

    def _fernet(self) -> Fernet:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(key)
            _chmod_600(self.key_path)
        return Fernet(key)

    def _load(self) -> dict[str, str]:
        if not self.store_path.exists():
            return {}
        token = self.store_path.read_bytes()
        if not token:
            return {}
        try:
            plaintext = self._fernet().decrypt(token)
        except InvalidToken:
            # Wrong/rotated master key: treat as empty rather than crash the app.
            return {}
        try:
            data = json.loads(plaintext.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save(self, data: dict[str, str]) -> None:
        token = self._fernet().encrypt(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_bytes(token)
        _chmod_600(self.store_path)


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best-effort on platforms without POSIX perms


secret_store = SecretStore()
