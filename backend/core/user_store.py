from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, new_uuid, utc_now, uuid_value

LOCAL_SUBJECT = "local_user"
DEV_HEADER_PROVIDER = "dev-header"
TRUSTED_HEADER_PROVIDER = "trusted-header"


class UserStore:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or create_engine_from_env()

    def get_or_create_user_for_subject(
        self,
        *,
        provider: str,
        subject: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    select u.user_id, u.display_name, u.status, i.provider, i.subject
                    from user_identities i
                    join users u on u.user_id = i.user_id
                    where i.provider = :provider and i.subject = :subject
                    """
                ),
                {"provider": provider, "subject": subject},
            ).mappings().first()
            if row:
                conn.execute(
                    text("update user_identities set last_seen_at = :ts where provider = :provider and subject = :subject"),
                    {"ts": utc_now(), "provider": provider, "subject": subject},
                )
                return _user_row(row)

            user_id = uuid_value(new_uuid())
            identity_id = uuid_value(new_uuid())
            ts = utc_now()
            label = display_name or subject
            conn.execute(
                text(
                    """
                    insert into users(user_id, display_name, status, metadata_json, created_at, updated_at)
                    values(:user_id, :display_name, 'active', '{}'::jsonb, :ts, :ts)
                    """
                ),
                {"user_id": user_id, "display_name": label, "ts": ts},
            )
            conn.execute(
                text(
                    """
                    insert into user_identities(identity_id, user_id, provider, subject, metadata_json, created_at, last_seen_at)
                    values(:identity_id, :user_id, :provider, :subject, '{}'::jsonb, :ts, :ts)
                    """
                ),
                {"identity_id": identity_id, "user_id": user_id, "provider": provider, "subject": subject, "ts": ts},
            )
            conn.execute(
                text(
                    """
                    insert into audit_events(event_id, actor_user_id, event_type, resource_type, resource_id, outcome, metadata_json, created_at)
                    values(:event_id, :actor_user_id, 'identity.auto_created', 'user', :resource_id, 'ok', cast(:metadata_json as jsonb), :ts)
                    """
                ),
                {
                    "event_id": uuid_value(new_uuid()),
                    "actor_user_id": user_id,
                    "resource_id": str(user_id),
                    "metadata_json": json_dumps({"provider": provider, "subject": subject}),
                    "ts": ts,
                },
            )
            return {
                "user_id": str(user_id),
                "display_name": label,
                "status": "active",
                "provider": provider,
                "subject": subject,
            }

    def ensure_local_user(self) -> dict[str, Any]:
        return self.get_or_create_user_for_subject(provider=DEV_HEADER_PROVIDER, subject=LOCAL_SUBJECT)

    def get_user(self, user_id: str | uuid.UUID) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("select user_id, display_name, status from users where user_id = :user_id"),
                {"user_id": uuid_value(user_id)},
            ).mappings().first()
        if not row:
            raise KeyError(f"user not found: {user_id}")
        return _user_row(row)


def _user_row(row) -> dict[str, Any]:
    return {
        "user_id": str(row["user_id"]),
        "display_name": row["display_name"],
        "status": row.get("status", "active") if hasattr(row, "get") else row["status"],
        "provider": row.get("provider") if hasattr(row, "get") else None,
        "subject": row.get("subject") if hasattr(row, "get") else None,
    }


user_store = UserStore()
