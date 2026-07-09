from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, new_uuid, utc_now, uuid_value
from core.passwords import hash_password, validate_password_strength, verify_password
from core.runtime_config import enable_signup, session_ttl_days

LOCAL_PASSWORD_PROVIDER = "local-password"
ADMIN_BOOTSTRAP_ADVISORY_LOCK_ID = 7_157_555_001_001


class AuthStore:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or create_engine_from_env()

    def signup(self, *, email: str, display_name: str, password: str) -> dict[str, Any]:
        if not enable_signup():
            raise ValueError("signup disabled")
        normalized_email = normalize_email(email)
        validate_password_strength(password)
        password_hash = hash_password(password)
        user_id = uuid_value(new_uuid())
        identity_id = uuid_value(new_uuid())
        credential_id = uuid_value(new_uuid())
        ts = utc_now()
        label = display_name.strip() or normalized_email
        algorithm = _password_algorithm(password_hash)

        try:
            with self.engine.begin() as conn:
                conn.execute(text("select pg_advisory_xact_lock(:lock_id)"), {"lock_id": ADMIN_BOOTSTRAP_ADVISORY_LOCK_ID})
                has_admin = conn.execute(text("select exists(select 1 from users where role = 'admin')")).scalar_one()
                role = "user" if has_admin else "admin"
                conn.execute(
                    text(
                        """
                        insert into users(user_id, display_name, status, metadata_json, created_at, updated_at, email, role)
                        values(:user_id, :display_name, 'active', '{}'::jsonb, :ts, :ts, :email, :role)
                        """
                    ),
                    {
                        "user_id": user_id,
                        "display_name": label,
                        "ts": ts,
                        "email": normalized_email,
                        "role": role,
                    },
                )
                conn.execute(
                    text(
                        """
                        insert into user_identities(identity_id, user_id, provider, subject, metadata_json, created_at, last_seen_at)
                        values(:identity_id, :user_id, :provider, :subject, '{}'::jsonb, :ts, :ts)
                        """
                    ),
                    {
                        "identity_id": identity_id,
                        "user_id": user_id,
                        "provider": LOCAL_PASSWORD_PROVIDER,
                        "subject": normalized_email,
                        "ts": ts,
                    },
                )
                conn.execute(
                    text(
                        """
                        insert into user_credentials(
                            credential_id, user_id, credential_type, password_hash, password_algorithm, active, created_at, updated_at
                        )
                        values(:credential_id, :user_id, 'password', :password_hash, :password_algorithm, true, :ts, :ts)
                        """
                    ),
                    {
                        "credential_id": credential_id,
                        "user_id": user_id,
                        "password_hash": password_hash,
                        "password_algorithm": algorithm,
                        "ts": ts,
                    },
                )
                _insert_audit_event(
                    conn,
                    actor_user_id=user_id,
                    event_type="auth.signup",
                    resource_type="user",
                    resource_id=str(user_id),
                    metadata={"provider": LOCAL_PASSWORD_PROVIDER, "email": normalized_email, "role": role},
                    ts=ts,
                )
        except IntegrityError as exc:
            raise ValueError("email already registered") from exc

        return {
            "user_id": str(user_id),
            "display_name": label,
            "status": "active",
            "email": normalized_email,
            "role": role,
            "avatar_url": None,
            "last_login_at": None,
        }

    def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str = "",
        ip_address: str = "",
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        ts = utc_now()
        session_token = _new_token("sess")
        csrf_token = _new_token("csrf")
        expires_at = ts + timedelta(days=session_ttl_days())

        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    select
                        u.user_id, u.display_name, u.status, u.email, u.role, u.avatar_url, u.last_login_at,
                        c.password_hash
                    from user_identities i
                    join users u on u.user_id = i.user_id
                    join user_credentials c
                        on c.user_id = u.user_id
                        and c.credential_type = 'password'
                        and c.active = true
                    where i.provider = :provider and i.subject = :subject
                    """
                ),
                {"provider": LOCAL_PASSWORD_PROVIDER, "subject": normalized_email},
            ).mappings().first()
            if not row or row["status"] != "active" or not verify_password(password, row["password_hash"]):
                raise ValueError("invalid email or password")

            session_id = uuid_value(new_uuid())
            user_id = row["user_id"]
            conn.execute(
                text(
                    """
                    insert into auth_sessions(
                        session_id, user_id, token_hash, csrf_token_hash, user_agent, ip_hash,
                        created_at, last_seen_at, expires_at
                    )
                    values(
                        :session_id, :user_id, :token_hash, :csrf_token_hash, :user_agent, :ip_hash,
                        :ts, :ts, :expires_at
                    )
                    """
                ),
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "token_hash": _hash_token(session_token),
                    "csrf_token_hash": _hash_token(csrf_token),
                    "user_agent": user_agent or None,
                    "ip_hash": _hash_ip(ip_address),
                    "ts": ts,
                    "expires_at": expires_at,
                },
            )
            conn.execute(
                text("update users set last_login_at = :ts, updated_at = :ts where user_id = :user_id"),
                {"ts": ts, "user_id": user_id},
            )
            conn.execute(
                text(
                    """
                    update user_identities
                    set last_seen_at = :ts
                    where provider = :provider and subject = :subject
                    """
                ),
                {"ts": ts, "provider": LOCAL_PASSWORD_PROVIDER, "subject": normalized_email},
            )
            _insert_audit_event(
                conn,
                actor_user_id=user_id,
                event_type="auth.login",
                resource_type="auth_session",
                resource_id=str(session_id),
                metadata={"provider": LOCAL_PASSWORD_PROVIDER},
                ts=ts,
            )

        user = _user_row(row)
        user["last_login_at"] = ts
        return {
            "user": user,
            "session_token": session_token,
            "csrf_token": csrf_token,
            "expires_at": expires_at,
        }

    def logout(self, session_token: str, *, reason: str = "logout") -> bool:
        if not session_token:
            return False
        ts = utc_now()
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    update auth_sessions
                    set revoked_at = :ts, revoked_reason = :reason
                    where token_hash = :token_hash
                        and revoked_at is null
                        and expires_at > :ts
                    """
                ),
                {"ts": ts, "reason": reason, "token_hash": _hash_token(session_token)},
            )
        return bool(result.rowcount)

    def user_for_session_token(self, session_token: str) -> dict[str, Any] | None:
        if not session_token:
            return None
        ts = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    select
                        u.user_id, u.display_name, u.status, u.email, u.role, u.avatar_url, u.last_login_at,
                        s.session_id, s.expires_at
                    from auth_sessions s
                    join users u on u.user_id = s.user_id
                    where s.token_hash = :token_hash
                        and s.revoked_at is null
                        and s.expires_at > :ts
                        and u.status = 'active'
                    """
                ),
                {"token_hash": _hash_token(session_token), "ts": ts},
            ).mappings().first()
            if not row:
                return None
            conn.execute(
                text("update auth_sessions set last_seen_at = :ts where session_id = :session_id"),
                {"ts": ts, "session_id": row["session_id"]},
            )
        user = _user_row(row)
        user["session_id"] = str(row["session_id"])
        user["session_expires_at"] = row["expires_at"]
        return user

    def validate_csrf(self, session_token: str, csrf_token: str) -> bool:
        if not session_token or not csrf_token:
            return False
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    select 1
                    from auth_sessions s
                    join users u on u.user_id = s.user_id
                    where s.token_hash = :token_hash
                        and s.csrf_token_hash = :csrf_token_hash
                        and s.revoked_at is null
                        and s.expires_at > :ts
                        and u.status = 'active'
                    """
                ),
                {
                    "token_hash": _hash_token(session_token),
                    "csrf_token_hash": _hash_token(csrf_token),
                    "ts": utc_now(),
                },
            ).first()
        return row is not None


class _LazyAuthStore:
    def __init__(self) -> None:
        self._store: AuthStore | None = None

    def _get(self) -> AuthStore:
        if self._store is None:
            self._store = AuthStore()
        return self._store

    def user_for_session_token(self, session_token: str) -> dict[str, Any] | None:
        return self._get().user_for_session_token(session_token)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


def normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("invalid email")
    return normalized


def _new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_ip(ip_address: str) -> str | None:
    if not ip_address:
        return None
    return hashlib.sha256(ip_address.encode("utf-8")).hexdigest()


def _password_algorithm(password_hash: str) -> str:
    if password_hash.startswith("bcrypt$"):
        return "bcrypt"
    return password_hash.split("$", 1)[0]


def _user_row(row: Any) -> dict[str, Any]:
    return {
        "user_id": str(row["user_id"]),
        "display_name": row["display_name"],
        "status": row["status"],
        "email": row["email"],
        "role": row["role"],
        "avatar_url": row["avatar_url"],
        "last_login_at": row["last_login_at"],
    }


auth_store = _LazyAuthStore()


def _insert_audit_event(
    conn: Any,
    *,
    actor_user_id: Any,
    event_type: str,
    resource_type: str,
    resource_id: str,
    metadata: dict[str, Any],
    ts: Any,
) -> None:
    conn.execute(
        text(
            """
            insert into audit_events(event_id, actor_user_id, event_type, resource_type, resource_id, outcome, metadata_json, created_at)
            values(:event_id, :actor_user_id, :event_type, :resource_type, :resource_id, 'ok', cast(:metadata_json as jsonb), :ts)
            """
        ),
        {
            "event_id": uuid_value(new_uuid()),
            "actor_user_id": actor_user_id,
            "event_type": event_type,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "metadata_json": json_dumps(metadata),
            "ts": ts,
        },
    )
