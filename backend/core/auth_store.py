from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from core.db.engine import create_engine_from_env
from core.db.types import json_dumps, json_loads, new_uuid, utc_now, uuid_value
from core.passwords import hash_password, validate_password_strength, verify_password
from core.runtime_config import enable_signup, session_ttl_days

LOCAL_PASSWORD_PROVIDER = "local-password"
ADMIN_BOOTSTRAP_ADVISORY_LOCK_ID = 7_157_555_001_001
VALID_ROLES = {"user", "admin"}
VALID_STATUSES = {"active", "disabled"}


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

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    select user_id, display_name, status, email, role, avatar_url, last_login_at, created_at, updated_at
                    from users
                    where user_id = :user_id
                    """
                ),
                {"user_id": uuid_value(user_id)},
            ).mappings().first()
        return _user_row(row) if row else None

    def update_profile(self, user_id: str, display_name: str | None = None, avatar_url: str | None = None) -> dict[str, Any]:
        ts = utc_now()
        fields: dict[str, Any] = {"user_id": uuid_value(user_id), "ts": ts}
        assignments = ["updated_at = :ts"]
        if display_name is not None:
            label = display_name.strip()
            if not label:
                raise ValueError("display_name required")
            fields["display_name"] = label
            assignments.append("display_name = :display_name")
        if avatar_url is not None:
            fields["avatar_url"] = avatar_url.strip() or None
            assignments.append("avatar_url = :avatar_url")
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    f"""
                    update users
                    set {", ".join(assignments)}
                    where user_id = :user_id and status = 'active'
                    returning user_id, display_name, status, email, role, avatar_url, last_login_at, created_at, updated_at
                    """
                ),
                fields,
            ).mappings().first()
            if not row:
                raise ValueError("user not found")
            _insert_audit_event(
                conn,
                actor_user_id=uuid_value(user_id),
                event_type="account.update_profile",
                resource_type="user",
                resource_id=str(user_id),
                metadata={"fields": [key for key in ("display_name", "avatar_url") if key in fields]},
                ts=ts,
            )
        return _user_row(row)

    def change_password(self, user_id: str, current_password: str, new_password: str) -> bool:
        validate_password_strength(new_password)
        ts = utc_now()
        user_uuid = uuid_value(user_id)
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    select c.credential_id, c.password_hash
                    from user_credentials c
                    join users u on u.user_id = c.user_id
                    where c.user_id = :user_id
                        and c.credential_type = 'password'
                        and c.active = true
                        and u.status = 'active'
                    """
                ),
                {"user_id": user_uuid},
            ).mappings().first()
            if not row or not verify_password(current_password, row["password_hash"]):
                raise ValueError("invalid current password")
            password_hash = hash_password(new_password)
            conn.execute(
                text(
                    """
                    update user_credentials
                    set password_hash = :password_hash, password_algorithm = :password_algorithm, updated_at = :ts
                    where credential_id = :credential_id
                    """
                ),
                {
                    "credential_id": row["credential_id"],
                    "password_hash": password_hash,
                    "password_algorithm": _password_algorithm(password_hash),
                    "ts": ts,
                },
            )
            _insert_audit_event(
                conn,
                actor_user_id=user_uuid,
                event_type="account.change_password",
                resource_type="user",
                resource_id=str(user_id),
                metadata={},
                ts=ts,
            )
        return True

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select session_id, user_agent, created_at, last_seen_at, expires_at, revoked_at, revoked_reason
                    from auth_sessions
                    where user_id = :user_id
                    order by created_at desc
                    """
                ),
                {"user_id": uuid_value(user_id)},
            ).mappings().all()
        return [_session_row(row) for row in rows]

    def revoke_session(self, user_id: str, session_id: str, reason: str = "user_revoked") -> bool:
        ts = utc_now()
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    update auth_sessions
                    set revoked_at = :ts, revoked_reason = :reason
                    where user_id = :user_id and session_id = :session_id and revoked_at is null
                    """
                ),
                {"user_id": uuid_value(user_id), "session_id": uuid_value(session_id), "ts": ts, "reason": reason},
            )
            if result.rowcount:
                _insert_audit_event(
                    conn,
                    actor_user_id=uuid_value(user_id),
                    event_type="account.revoke_session",
                    resource_type="auth_session",
                    resource_id=str(session_id),
                    metadata={"reason": reason},
                    ts=ts,
                )
        return bool(result.rowcount)

    def create_api_token(self, user_id: str, name: str) -> dict[str, Any]:
        label = name.strip()
        if not label:
            raise ValueError("token name required")
        raw_token = _new_token("lap")
        token_id = uuid_value(new_uuid())
        user_uuid = uuid_value(user_id)
        ts = utc_now()
        with self.engine.begin() as conn:
            user_exists = conn.execute(
                text("select exists(select 1 from users where user_id = :user_id and status = 'active')"),
                {"user_id": user_uuid},
            ).scalar_one()
            if not user_exists:
                raise ValueError("user not found")
            row = conn.execute(
                text(
                    """
                    insert into api_tokens(
                        token_id, user_id, name, token_hash, token_preview, scopes_json, created_at
                    )
                    values(:token_id, :user_id, :name, :token_hash, :token_preview, '[]'::jsonb, :ts)
                    returning token_id, user_id, name, token_preview, scopes_json, created_at, last_used_at, expires_at, revoked_at
                    """
                ),
                {
                    "token_id": token_id,
                    "user_id": user_uuid,
                    "name": label,
                    "token_hash": _hash_token(raw_token),
                    "token_preview": _token_preview(raw_token),
                    "ts": ts,
                },
            ).mappings().one()
            _insert_audit_event(
                conn,
                actor_user_id=user_uuid,
                event_type="account.create_api_token",
                resource_type="api_token",
                resource_id=str(token_id),
                metadata={"name": label},
                ts=ts,
            )
        token = _api_token_row(row)
        token["api_token"] = raw_token
        return token

    def list_api_tokens(self, user_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select token_id, user_id, name, token_preview, scopes_json, created_at, last_used_at, expires_at, revoked_at
                    from api_tokens
                    where user_id = :user_id
                    order by created_at desc
                    """
                ),
                {"user_id": uuid_value(user_id)},
            ).mappings().all()
        return [_api_token_row(row) for row in rows]

    def revoke_api_token(self, user_id: str, token_id: str) -> bool:
        ts = utc_now()
        with self.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    update api_tokens
                    set revoked_at = :ts
                    where user_id = :user_id and token_id = :token_id and revoked_at is null
                    """
                ),
                {"user_id": uuid_value(user_id), "token_id": uuid_value(token_id), "ts": ts},
            )
            if result.rowcount:
                _insert_audit_event(
                    conn,
                    actor_user_id=uuid_value(user_id),
                    event_type="account.revoke_api_token",
                    resource_type="api_token",
                    resource_id=str(token_id),
                    metadata={},
                    ts=ts,
                )
        return bool(result.rowcount)

    def user_for_api_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        ts = utc_now()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    select
                        u.user_id, u.display_name, u.status, u.email, u.role, u.avatar_url, u.last_login_at,
                        t.token_id
                    from api_tokens t
                    join users u on u.user_id = t.user_id
                    where t.token_hash = :token_hash
                        and t.revoked_at is null
                        and (t.expires_at is null or t.expires_at > :ts)
                        and u.status = 'active'
                    """
                ),
                {"token_hash": _hash_token(token), "ts": ts},
            ).mappings().first()
            if not row:
                return None
            conn.execute(text("update api_tokens set last_used_at = :ts where token_id = :token_id"), {"ts": ts, "token_id": row["token_id"]})
        user = _user_row(row)
        user["api_token_id"] = str(row["token_id"])
        return user

    def list_users(self, query: str = "", limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        pattern = f"%{query.strip().lower()}%"
        where = "where lower(coalesce(email, '') || ' ' || display_name) like :pattern" if query.strip() else ""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    select user_id, display_name, status, email, role, avatar_url, last_login_at, created_at, updated_at
                    from users
                    {where}
                    order by created_at desc
                    limit :limit offset :offset
                    """
                ),
                {"pattern": pattern, "limit": limit, "offset": offset},
            ).mappings().all()
        return [_user_row(row) for row in rows]

    def update_user_admin(
        self,
        actor_user_id: str,
        target_user_id: str,
        role: str | None = None,
        status: str | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        if role is not None:
            _validate_role(role)
        if status is not None:
            _validate_status(status)
        ts = utc_now()
        actor_uuid = uuid_value(actor_user_id)
        target_uuid = uuid_value(target_user_id)
        with self.engine.begin() as conn:
            target = _select_user_for_update(conn, target_uuid)
            if not target:
                raise ValueError("user not found")
            new_role = role if role is not None else target["role"]
            new_status = status if status is not None else target["status"]
            if _would_remove_last_active_admin(conn, target, new_role=new_role, new_status=new_status):
                raise ValueError("cannot remove last active admin")
            fields: dict[str, Any] = {"user_id": target_uuid, "ts": ts}
            assignments = ["updated_at = :ts"]
            if role is not None:
                fields["role"] = role
                assignments.append("role = :role")
            if status is not None:
                fields["status"] = status
                assignments.append("status = :status")
            if display_name is not None:
                label = display_name.strip()
                if not label:
                    raise ValueError("display_name required")
                fields["display_name"] = label
                assignments.append("display_name = :display_name")
            row = conn.execute(
                text(
                    f"""
                    update users
                    set {", ".join(assignments)}
                    where user_id = :user_id
                    returning user_id, display_name, status, email, role, avatar_url, last_login_at, created_at, updated_at
                    """
                ),
                fields,
            ).mappings().one()
            if status == "disabled":
                _revoke_sessions_for_user(conn, target_uuid, ts=ts, reason="user_disabled")
                _revoke_api_tokens_for_user(conn, target_uuid, ts=ts)
            _insert_audit_event(
                conn,
                actor_user_id=actor_uuid,
                event_type="admin.update_user",
                resource_type="user",
                resource_id=str(target_user_id),
                metadata={"role": role, "status": status, "display_name": display_name},
                ts=ts,
            )
        return _user_row(row)

    def reset_password_admin(self, actor_user_id: str, target_user_id: str, new_password: str) -> bool:
        validate_password_strength(new_password)
        password_hash = hash_password(new_password)
        ts = utc_now()
        actor_uuid = uuid_value(actor_user_id)
        target_uuid = uuid_value(target_user_id)
        with self.engine.begin() as conn:
            target = _select_user_for_update(conn, target_uuid)
            if not target:
                raise ValueError("user not found")
            row = conn.execute(
                text(
                    """
                    update user_credentials
                    set password_hash = :password_hash, password_algorithm = :password_algorithm, updated_at = :ts
                    where user_id = :user_id and credential_type = 'password' and active = true
                    returning credential_id
                    """
                ),
                {
                    "user_id": target_uuid,
                    "password_hash": password_hash,
                    "password_algorithm": _password_algorithm(password_hash),
                    "ts": ts,
                },
            ).first()
            if not row:
                raise ValueError("password credential not found")
            _insert_audit_event(
                conn,
                actor_user_id=actor_uuid,
                event_type="admin.reset_password",
                resource_type="user",
                resource_id=str(target_user_id),
                metadata={},
                ts=ts,
            )
        return True

    def revoke_user_sessions_admin(self, actor_user_id: str, target_user_id: str, reason: str = "admin_revoked") -> int:
        ts = utc_now()
        with self.engine.begin() as conn:
            revoked = _revoke_sessions_for_user(conn, uuid_value(target_user_id), ts=ts, reason=reason)
            _insert_audit_event(
                conn,
                actor_user_id=uuid_value(actor_user_id),
                event_type="admin.revoke_sessions",
                resource_type="user",
                resource_id=str(target_user_id),
                metadata={"revoked": revoked, "reason": reason},
                ts=ts,
            )
        return revoked

    def revoke_user_api_tokens_admin(self, actor_user_id: str, target_user_id: str) -> int:
        ts = utc_now()
        with self.engine.begin() as conn:
            revoked = _revoke_api_tokens_for_user(conn, uuid_value(target_user_id), ts=ts)
            _insert_audit_event(
                conn,
                actor_user_id=uuid_value(actor_user_id),
                event_type="admin.revoke_api_tokens",
                resource_type="user",
                resource_id=str(target_user_id),
                metadata={"revoked": revoked},
                ts=ts,
            )
        return revoked

    def list_audit_events(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    select event_id, actor_user_id, event_type, resource_type, resource_id, outcome, metadata_json, created_at
                    from audit_events
                    order by created_at desc
                    limit :limit offset :offset
                    """
                ),
                {"limit": limit, "offset": offset},
            ).mappings().all()
        return [_audit_event_row(row) for row in rows]


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


def _session_row(row: Any) -> dict[str, Any]:
    return {
        "session_id": str(row["session_id"]),
        "user_agent": row["user_agent"],
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
        "revoked_reason": row["revoked_reason"],
    }


def _api_token_row(row: Any) -> dict[str, Any]:
    return {
        "token_id": str(row["token_id"]),
        "user_id": str(row["user_id"]),
        "name": row["name"],
        "token_preview": row["token_preview"],
        "scopes": json_loads(row["scopes_json"], []),
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
    }


def _audit_event_row(row: Any) -> dict[str, Any]:
    return {
        "event_id": str(row["event_id"]),
        "actor_user_id": str(row["actor_user_id"]) if row["actor_user_id"] else None,
        "event_type": row["event_type"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "outcome": row["outcome"],
        "metadata": json_loads(row["metadata_json"], {}),
        "created_at": row["created_at"],
    }


def _token_preview(token: str) -> str:
    return f"{token[:8]}...{token[-4:]}"


def _validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError("invalid role")


def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError("invalid status")


def _select_user_for_update(conn: Any, user_id: Any) -> Any:
    return conn.execute(
        text(
            """
            select user_id, display_name, status, email, role, avatar_url, last_login_at, created_at, updated_at
            from users
            where user_id = :user_id
            for update
            """
        ),
        {"user_id": user_id},
    ).mappings().first()


def _would_remove_last_active_admin(conn: Any, target: Any, *, new_role: str, new_status: str) -> bool:
    if target["role"] != "admin" or target["status"] != "active":
        return False
    if new_role == "admin" and new_status == "active":
        return False
    other_admin_count = conn.execute(
        text(
            """
            select count(*)
            from users
            where role = 'admin' and status = 'active' and user_id != :user_id
            """
        ),
        {"user_id": target["user_id"]},
    ).scalar_one()
    return int(other_admin_count) == 0


def _revoke_sessions_for_user(conn: Any, user_id: Any, *, ts: Any, reason: str) -> int:
    result = conn.execute(
        text(
            """
            update auth_sessions
            set revoked_at = :ts, revoked_reason = :reason
            where user_id = :user_id and revoked_at is null
            """
        ),
        {"user_id": user_id, "ts": ts, "reason": reason},
    )
    return int(result.rowcount or 0)


def _revoke_api_tokens_for_user(conn: Any, user_id: Any, *, ts: Any) -> int:
    result = conn.execute(
        text(
            """
            update api_tokens
            set revoked_at = :ts
            where user_id = :user_id and revoked_at is null
            """
        ),
        {"user_id": user_id, "ts": ts},
    )
    return int(result.rowcount or 0)


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
