"""Named model credential profiles.

Each profile bundles a display name + provider/base_url/model + an API key, so a
user can manage several models (e.g. multiple relay keys) in one table and pick
which one drives the agent via `activate()`. Non-secret fields live in the
otherwise-unused `settings_profiles` table; the API key is encrypted in
`secret_store` under the id `cred:<profile_id>`.

Security: `list()` only ever returns a masked preview (`sk-abc...wxyz`). The
plaintext key is returned solely by `reveal()`, which the dedicated reveal
endpoint calls on an explicit user action.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from core.memory_db import connect, dumps, loads, now

_CRED_PREFIX = "cred:"
# Provider/base_url get mirrored into the `models` settings scope on activate so
# the existing LLM/diagnostics wiring keeps reading one source of truth.
_MIRRORED_KEYS = {"provider": "provider", "base_url": "base_url", "model": "chat_model"}


class ModelProfileStore:
    def __init__(self, db_path: str | Path | None = None, secret_store=None) -> None:
        self.conn = connect(db_path)
        if secret_store is None:
            from core.secret_store import secret_store as default_store

            secret_store = default_store
        self.secrets = secret_store

    # --- queries ----------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from settings_profiles order by created_at",
        ).fetchall()
        return [self._row(row) for row in rows]

    def get(self, profile_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from settings_profiles where profile_id = ?", (profile_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"model profile not found: {profile_id}")
        return self._row(row)

    def active(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "select * from settings_profiles where active = 1 order by updated_at desc limit 1"
        ).fetchone()
        return self._row(row) if row else None

    def active_api_key(self) -> str | None:
        current = self.active()
        if not current:
            return None
        return self.secrets.get(_CRED_PREFIX + current["id"])

    def reveal(self, profile_id: str) -> str | None:
        self.get(profile_id)  # existence check
        return self.secrets.get(_CRED_PREFIX + profile_id)

    # --- mutations --------------------------------------------------------------

    def create(
        self,
        *,
        name: str,
        provider: str,
        base_url: str = "",
        model: str = "",
        api_key: str = "",
    ) -> dict[str, Any]:
        profile_id = f"mp_{uuid.uuid4().hex[:12]}"
        ts = now()
        config = {
            "provider": provider,
            "base_url": base_url or "",
            "model": model or "",
            "key_masked": _mask(api_key),
            "has_key": bool(api_key),
        }
        self.conn.execute(
            """
            insert into settings_profiles(profile_id, name, config_json, active, created_at, updated_at)
            values(?, ?, ?, 0, ?, ?)
            """,
            (profile_id, name or provider, dumps(config), ts, ts),
        )
        self.conn.commit()
        if api_key:
            self.secrets.set(_CRED_PREFIX + profile_id, api_key)
        return self.get(profile_id)

    def update(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        current = self.get(profile_id)
        config = {
            "provider": provider if provider is not None else current["provider"],
            "base_url": base_url if base_url is not None else current["base_url"],
            "model": model if model is not None else current["model"],
            "key_masked": current["key_masked"],
            "has_key": current["has_key"],
        }
        if api_key:  # empty string / None => keep existing key
            self.secrets.set(_CRED_PREFIX + profile_id, api_key)
            config["key_masked"] = _mask(api_key)
            config["has_key"] = True
        self.conn.execute(
            "update settings_profiles set name = ?, config_json = ?, updated_at = ? where profile_id = ?",
            (name if name is not None else current["name"], dumps(config), now(), profile_id),
        )
        self.conn.commit()
        if current["active"]:
            self._mirror_to_models(self.get(profile_id))
        return self.get(profile_id)

    def delete(self, profile_id: str) -> None:
        self.get(profile_id)  # existence check
        self.conn.execute("delete from settings_profiles where profile_id = ?", (profile_id,))
        self.conn.commit()
        self.secrets.delete(_CRED_PREFIX + profile_id)

    def activate(self, profile_id: str) -> dict[str, Any]:
        profile = self.get(profile_id)
        self.conn.execute("update settings_profiles set active = 0")
        self.conn.execute(
            "update settings_profiles set active = 1, updated_at = ? where profile_id = ?",
            (now(), profile_id),
        )
        self.conn.commit()
        profile = self.get(profile_id)
        self._mirror_to_models(profile)
        return profile

    # --- internals --------------------------------------------------------------

    def _mirror_to_models(self, profile: dict[str, Any]) -> None:
        ts = now()
        for source_key, settings_key in _MIRRORED_KEYS.items():
            self.conn.execute(
                """
                insert into settings(scope, key, value_json, updated_at)
                values('models', ?, ?, ?)
                on conflict(scope, key) do update set
                    value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (settings_key, dumps(profile.get(source_key) or ""), ts),
            )
        self.conn.commit()

    def _row(self, row) -> dict[str, Any]:
        config = loads(row["config_json"], {})
        has_key = bool(config.get("has_key")) and self.secrets.has(_CRED_PREFIX + row["profile_id"])
        return {
            "id": row["profile_id"],
            "name": row["name"],
            "provider": config.get("provider") or "",
            "base_url": config.get("base_url") or "",
            "model": config.get("model") or "",
            "key_masked": (config.get("key_masked") or "") if has_key else "",
            "has_key": has_key,
            "active": bool(row["active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def _mask(key: str | None) -> str:
    if not key:
        return ""
    if len(key) >= 12:
        return f"{key[:6]}...{key[-4:]}"
    if len(key) > 4:
        return f"{key[:2]}...{key[-2:]}"
    return "****"


model_profile_store = ModelProfileStore()
