"""PostgreSQL encrypted at-rest store for per-user secrets.

M2 stores ciphertext in ``user_secrets`` and reuses the existing Fernet file-key
mechanism for local development. There is no plaintext reveal in normal API
responses; backend code may call ``get`` to construct provider clients.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.config import DatabaseConfigError, app_env
from core.db.engine import create_engine_from_env
from core.db.types import new_uuid, utc_now, uuid_value
from core.runtime_config import secret_key_path

def _key_path() -> Path:
    return secret_key_path()


class SecretStore:
    def __init__(self, key_path: str | Path | None = None, store_path: str | Path | None = None, engine: Engine | None = None) -> None:
        self.key_path = Path(key_path).expanduser() if key_path else _key_path()
        self.store_path = Path(store_path).expanduser() if store_path else None
        self.engine = engine or create_engine_from_env()

    def set(self, secret_type: str, api_key: str, *, user_id: str | None = None) -> str:
        if not secret_type or not api_key:
            raise ValueError("secret_type and api_key are required")
        owner = _user_id(user_id)
        secret_id = new_uuid()
        encrypted = self._fernet().encrypt(api_key.encode("utf-8")).decode("utf-8")
        preview = _mask(api_key)
        ts = utc_now()
        with self.engine.begin() as conn:
            existing = conn.execute(
                text("select secret_id from user_secrets where user_id = :user_id and secret_type = :secret_type order by updated_at desc limit 1"),
                {"user_id": uuid_value(owner), "secret_type": secret_type},
            ).scalar_one_or_none()
            if existing:
                conn.execute(
                    text(
                        """
                        update user_secrets
                        set encrypted_value = :encrypted_value,
                            masked_preview = :masked_preview,
                            encryption_version = 'fernet-v1',
                            key_id = 'default',
                            updated_at = :ts
                        where secret_id = :secret_id
                        """
                    ),
                    {
                        "secret_id": existing,
                        "encrypted_value": encrypted,
                        "masked_preview": preview,
                        "ts": ts,
                    },
                )
                return str(existing)
            conn.execute(
                text(
                    """
                    insert into user_secrets(
                        secret_id, user_id, secret_type, encrypted_value, masked_preview,
                        encryption_version, key_id, metadata_json, created_at, updated_at
                    ) values(
                        :secret_id, :user_id, :secret_type, :encrypted_value, :masked_preview,
                        'fernet-v1', 'default', '{}'::jsonb, :ts, :ts
                    )
                    """
                ),
                {
                    "secret_id": uuid_value(secret_id),
                    "user_id": uuid_value(owner),
                    "secret_type": secret_type,
                    "encrypted_value": encrypted,
                    "masked_preview": preview,
                    "ts": ts,
                },
            )
        return secret_id

    def get(self, secret_type: str, *, user_id: str | None = None) -> str | None:
        owner = _user_id(user_id)
        with self.engine.connect() as conn:
            encrypted = conn.execute(
                text(
                    """
                    select encrypted_value
                    from user_secrets
                    where user_id = :user_id and secret_type = :secret_type
                    order by updated_at desc
                    limit 1
                    """
                ),
                {"user_id": uuid_value(owner), "secret_type": secret_type},
            ).scalar_one_or_none()
        if not encrypted:
            return None
        try:
            return self._fernet().decrypt(str(encrypted).encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return None

    def preview(self, secret_type: str, *, user_id: str | None = None) -> str:
        owner = _user_id(user_id)
        with self.engine.connect() as conn:
            value = conn.execute(
                text(
                    """
                    select masked_preview
                    from user_secrets
                    where user_id = :user_id and secret_type = :secret_type
                    order by updated_at desc
                    limit 1
                    """
                ),
                {"user_id": uuid_value(owner), "secret_type": secret_type},
            ).scalar_one_or_none()
        return str(value or "")

    def delete(self, secret_type: str, *, user_id: str | None = None) -> bool:
        owner = _user_id(user_id)
        with self.engine.begin() as conn:
            result = conn.execute(
                text("delete from user_secrets where user_id = :user_id and secret_type = :secret_type"),
                {"user_id": uuid_value(owner), "secret_type": secret_type},
            )
        return bool(result.rowcount)

    def has(self, secret_type: str, *, user_id: str | None = None) -> bool:
        return self.status(secret_type, user_id=user_id) == "readable"

    def status(self, secret_type: str, *, user_id: str | None = None) -> str:
        owner = _user_id(user_id)
        with self.engine.connect() as conn:
            encrypted = conn.execute(
                text(
                    """
                    select encrypted_value
                    from user_secrets
                    where user_id = :user_id and secret_type = :secret_type
                    order by updated_at desc
                    limit 1
                    """
                ),
                {"user_id": uuid_value(owner), "secret_type": secret_type},
            ).scalar_one_or_none()
        if not encrypted:
            return "missing"
        try:
            self._fernet().decrypt(str(encrypted).encode("utf-8"))
        except InvalidToken:
            return "unreadable"
        return "readable"

    def providers(self, *, user_id: str | None = None) -> list[str]:
        owner = _user_id(user_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select secret_type from user_secrets where user_id = :user_id order by secret_type"),
                {"user_id": uuid_value(owner)},
            ).scalars().all()
        return [str(row) for row in rows if self.status(str(row), user_id=owner) == "readable"]

    def _fernet(self) -> Fernet:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
        else:
            if app_env() == "production":
                raise DatabaseConfigError("LITERATURE_SECRET_KEY_PATH must exist before decrypting secrets when APP_ENV=production")
            key = Fernet.generate_key()
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(key)
            _chmod_600(self.key_path)
        return Fernet(key)


def _user_id(user_id: str | None) -> str:
    if user_id:
        return user_id
    from core.user_store import user_store

    return user_store.ensure_local_user()["user_id"]


def _mask(key: str | None) -> str:
    if not key:
        return ""
    if len(key) >= 12:
        return f"{key[:6]}...{key[-4:]}"
    if len(key) > 4:
        return f"{key[:2]}...{key[-2:]}"
    return "****"


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


secret_store = SecretStore()
