"""Per-user PostgreSQL model credential profiles."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_loads, new_uuid, to_unix_seconds, utc_now, uuid_value

_CRED_PREFIX = "cred:"


class ModelProfileStore:
    def __init__(self, db_path: str | None = None, secret_store=None, engine: Engine | None = None) -> None:
        self.db_path = db_path
        self.engine = engine or create_engine_from_env()
        if secret_store is None:
            from core.secret_store import secret_store as default_store

            secret_store = default_store
        self.secrets = secret_store

    def list(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        owner = _user_id(user_id)
        with self.engine.connect() as conn:
            rows = conn.execute(
                text("select * from model_profiles where user_id = :user_id order by created_at"),
                {"user_id": uuid_value(owner)},
            ).mappings().all()
        return [self._row(row, user_id=owner) for row in rows]

    def get(self, profile_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        owner = _user_id(user_id)
        with self.engine.connect() as conn:
            row = conn.execute(
                text("select * from model_profiles where profile_id = :profile_id and user_id = :user_id"),
                {"profile_id": uuid_value(profile_id), "user_id": uuid_value(owner)},
            ).mappings().first()
        if not row:
            raise KeyError(f"model profile not found: {profile_id}")
        return self._row(row, user_id=owner)

    def active(self, *, user_id: str | None = None) -> dict[str, Any] | None:
        owner = _user_id(user_id)
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    select * from model_profiles
                    where user_id = :user_id and active = true
                    order by updated_at desc
                    limit 1
                    """
                ),
                {"user_id": uuid_value(owner)},
            ).mappings().first()
        return self._row(row, user_id=owner) if row else None

    def active_api_key(self, *, user_id: str | None = None) -> str | None:
        current = self.active(user_id=user_id)
        if not current:
            return None
        return self.secrets.get(_CRED_PREFIX + current["id"], user_id=_user_id(user_id))

    def reveal(self, profile_id: str, *, user_id: str | None = None) -> str | None:
        self.get(profile_id, user_id=user_id)
        return self.secrets.get(_CRED_PREFIX + profile_id, user_id=_user_id(user_id))

    def create(
        self,
        *,
        name: str,
        provider: str,
        base_url: str = "",
        model: str = "",
        api_key: str = "",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        owner = _user_id(user_id)
        profile_id = new_uuid()
        secret_id = self.secrets.set(_CRED_PREFIX + profile_id, api_key, user_id=owner) if api_key else None
        ts = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into model_profiles(
                        profile_id, user_id, secret_id, name, provider, base_url, model,
                        config_json, active, created_at, updated_at
                    ) values(
                        :profile_id, :user_id, :secret_id, :name, :provider, :base_url, :model,
                        '{}'::jsonb, false, :ts, :ts
                    )
                    """
                ),
                {
                    "profile_id": uuid_value(profile_id),
                    "user_id": uuid_value(owner),
                    "secret_id": uuid_value(secret_id) if secret_id else None,
                    "name": name or provider,
                    "provider": provider,
                    "base_url": base_url or "",
                    "model": model or "",
                    "ts": ts,
                },
            )
        return self.get(profile_id, user_id=owner)

    def update(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        owner = _user_id(user_id)
        current = self.get(profile_id, user_id=owner)
        secret_id = current.get("secret_id")
        if api_key:
            secret_id = self.secrets.set(_CRED_PREFIX + profile_id, api_key, user_id=owner)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    update model_profiles
                    set secret_id = :secret_id,
                        name = :name,
                        provider = :provider,
                        base_url = :base_url,
                        model = :model,
                        updated_at = :updated_at
                    where profile_id = :profile_id and user_id = :user_id
                    """
                ),
                {
                    "secret_id": uuid_value(secret_id) if secret_id else None,
                    "name": name if name is not None else current["name"],
                    "provider": provider if provider is not None else current["provider"],
                    "base_url": base_url if base_url is not None else current["base_url"],
                    "model": model if model is not None else current["model"],
                    "updated_at": utc_now(),
                    "profile_id": uuid_value(profile_id),
                    "user_id": uuid_value(owner),
                },
            )
        return self.get(profile_id, user_id=owner)

    def delete(self, profile_id: str, *, user_id: str | None = None) -> None:
        owner = _user_id(user_id)
        self.get(profile_id, user_id=owner)
        with self.engine.begin() as conn:
            conn.execute(
                text("delete from model_profiles where profile_id = :profile_id and user_id = :user_id"),
                {"profile_id": uuid_value(profile_id), "user_id": uuid_value(owner)},
            )
        self.secrets.delete(_CRED_PREFIX + profile_id, user_id=owner)

    def activate(self, profile_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        owner = _user_id(user_id)
        self.get(profile_id, user_id=owner)
        with self.engine.begin() as conn:
            conn.execute(text("update model_profiles set active = false where user_id = :user_id"), {"user_id": uuid_value(owner)})
            conn.execute(
                text("update model_profiles set active = true, updated_at = :ts where profile_id = :profile_id and user_id = :user_id"),
                {"ts": utc_now(), "profile_id": uuid_value(profile_id), "user_id": uuid_value(owner)},
            )
        return self.get(profile_id, user_id=owner)

    def _row(self, row, *, user_id: str) -> dict[str, Any]:
        secret_type = _CRED_PREFIX + str(row["profile_id"])
        has_key = self.secrets.has(secret_type, user_id=user_id)
        return {
            "id": str(row["profile_id"]),
            "profile_id": str(row["profile_id"]),
            "secret_id": str(row["secret_id"]) if row["secret_id"] else None,
            "name": row["name"],
            "provider": row["provider"],
            "base_url": row["base_url"],
            "model": row["model"],
            "config": json_loads(row["config_json"], {}),
            "key_masked": self.secrets.preview(secret_type, user_id=user_id) if has_key else "",
            "has_key": has_key,
            "active": bool(row["active"]),
            "created_at": to_unix_seconds(row["created_at"]),
            "updated_at": to_unix_seconds(row["updated_at"]),
        }


def _user_id(user_id: str | None) -> str:
    if user_id:
        return user_id
    from core.user_store import user_store

    return user_store.ensure_local_user()["user_id"]


model_profile_store = ModelProfileStore()
