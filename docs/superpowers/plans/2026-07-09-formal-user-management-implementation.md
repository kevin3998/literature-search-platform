# Formal User Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete local email/password user management system on top of existing `users` + `user_identities` + `UserContext`, with opaque database session cookies, API tokens, admin user management, and frontend login/account/admin surfaces.

**Architecture:** Extend the current PostgreSQL business schema and preserve internal UUID `users.user_id` as the only ownership key used by sessions, settings, workflows, jobs, and extraction tasks. Add focused auth modules for password credentials, browser sessions, API tokens, CSRF, and role checks; keep all protected business routers behind the existing `Depends(current_user)` boundary. The frontend gates the app on `/api/auth/me`, uses cookie credentials for browser auth, and keeps the existing development `X-User-Id` adapter only for `AUTH_MODE=dev-header`.

**Tech Stack:** FastAPI, SQLAlchemy Core, Alembic, PostgreSQL, cryptography/bcrypt or stdlib PBKDF2 fallback, React, Zustand, Vite, Node test runner, pytest.

---

## File Structure

### Backend Files

- Modify `backend/migrations/versions/0001_initial_postgres_schema.py`
  - Add user columns and auth tables to fresh schema creation.
  - This repo currently has one initial migration plus later runtime migrations; fresh test schemas run all heads, so the initial schema should include the new baseline tables.
- Create `backend/migrations/versions/0004_formal_user_management.py`
  - Upgrade existing deployments by adding user columns, auth tables, indexes, and constraints.
- Modify `backend/core/runtime_config.py`
  - Add auth/session config helpers: signup enabled, session TTL, cookie names, password minimum length, secure-cookie behavior.
- Create `backend/core/passwords.py`
  - Hash and verify local passwords.
  - Prefer bcrypt if available; otherwise use PBKDF2-SHA256 with per-password salt and constant-time comparison.
- Create `backend/core/auth_store.py`
  - Own local signup/login credential records, browser session records, CSRF validation, API token records, and user admin operations.
- Modify `backend/core/user_store.py`
  - Extend returned user rows with `email`, `role`, `status`, `avatar_url`, `last_login_at`.
  - Add helpers for first-admin bootstrap and trusted/dev identity creation with role/status defaults.
- Modify `backend/core/user_context.py`
  - Add `role`, `status`, and `email` to `UserContext`.
  - Resolve auth modes: `dev-header`, `trusted-header`, `local-password`, `hybrid`.
  - Resolve browser session cookie and API token through `auth_store`.
- Create `backend/api/auth_router.py`
  - Expose `/api/auth/signup`, `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/csrf`.
- Create `backend/api/account_router.py`
  - Expose account profile, password, session, and API token endpoints.
- Create `backend/api/admin_router.py`
  - Expose admin user management and audit-event read APIs.
- Modify `backend/api/modules_router.py`
  - Keep `/api/me` as compatibility alias that delegates to current `UserContext`.
- Modify `backend/api/__init__.py`
  - Export new routers.
- Modify `backend/main.py`
  - Include new routers.
  - Add readiness checks for local-password auth configuration and auth table availability.

### Backend Tests

- Modify `backend/tests/test_postgres_migrations.py`
  - Assert auth tables and user columns exist.
- Create `backend/tests/test_passwords.py`
  - Verify password hash/verify behavior and minimum length boundary.
- Create `backend/tests/test_formal_auth.py`
  - Cover signup/login/logout/session cookie/current user/disabled user/CSRF.
- Create `backend/tests/test_account_api.py`
  - Cover profile update, password change, session listing/revocation, API tokens.
- Create `backend/tests/test_admin_users_api.py`
  - Cover admin user list/update/disable/enable/reset/revoke and last-admin protection.
- Modify `backend/tests/test_auth_config.py`
  - Cover new `AUTH_MODE` values and production safety.
- Modify `backend/tests/test_postgres_m2_core_runtime.py`
  - Ensure existing `/api/me`, settings isolation, and sessions still work in `dev-header`.

### Frontend Files

- Modify `frontend/src/api/client.js`
  - Add `authApi`, `accountApi`, `adminApi`.
  - Add `credentials: "include"` and CSRF header handling for cookie-authenticated state changes.
  - Preserve `setApiUserId` behavior for development tests.
- Modify `frontend/src/store/useAppStore.js`
  - Add auth state, bootstrap flow, login/signup/logout actions, account actions, admin users actions.
  - Gate module loading until auth bootstrap succeeds or login is required.
- Modify `frontend/src/App.jsx`
  - Render auth screen when unauthenticated.
- Create `frontend/src/components/AuthScreen.jsx`
  - Login/register forms.
- Modify `frontend/src/components/TopBar.jsx`
  - User menu with Account, Admin Users for admins, Logout.
- Modify `frontend/src/components/SettingsModal.jsx`
  - Replace static Account placeholder with real profile, password, sessions, and API tokens.
- Create `frontend/src/components/AdminUsersModal.jsx`
  - Admin user-management surface.

### Frontend Tests

- Modify `frontend/tests/api_client_contract.test.mjs`
  - Auth/account/admin API calls, credentials, CSRF headers.
- Modify `frontend/tests/literature_search_store_contract.test.mjs`
  - Auth bootstrap, login-required state, logout state.
- Create `frontend/tests/auth_ui_contract.test.mjs`
  - Static source contract for auth screen, Account tab, admin-only user UI.

---

## Task 1: PostgreSQL Schema For Formal Auth

**Files:**
- Modify: `backend/migrations/versions/0001_initial_postgres_schema.py`
- Create: `backend/migrations/versions/0004_formal_user_management.py`
- Modify: `backend/tests/test_postgres_migrations.py`

- [ ] **Step 1: Write migration contract tests**

Add to `backend/tests/test_postgres_migrations.py`:

```python
def test_formal_user_management_schema_is_present():
    from core.db.engine import engine_for_url

    with migrated_postgres_schema() as (url, schema):
        engine = engine_for_url(url, schema=schema)
        try:
            with engine.connect() as conn:
                user_columns = set(
                    conn.execute(
                        text(
                            """
                            select column_name
                            from information_schema.columns
                            where table_schema = :schema
                              and table_name = 'users'
                            """
                        ),
                        {"schema": schema},
                    ).scalars()
                )
                auth_tables = set(
                    conn.execute(
                        text(
                            """
                            select table_name
                            from information_schema.tables
                            where table_schema = :schema
                              and table_name in ('user_credentials', 'auth_sessions', 'api_tokens')
                            """
                        ),
                        {"schema": schema},
                    ).scalars()
                )
                session_indexes = {
                    row["indexname"]
                    for row in conn.execute(
                        text(
                            """
                            select indexname
                            from pg_indexes
                            where schemaname = :schema
                              and tablename = 'auth_sessions'
                            """
                        ),
                        {"schema": schema},
                    ).mappings()
                }
        finally:
            engine.dispose()

    assert {"email", "role", "status", "avatar_url", "last_login_at"}.issubset(user_columns)
    assert auth_tables == {"user_credentials", "auth_sessions", "api_tokens"}
    assert "uq_auth_sessions_token_hash" in session_indexes
```

- [ ] **Step 2: Run migration test and verify it fails**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_postgres_migrations.py::test_formal_user_management_schema_is_present -q
```

Expected: FAIL because `user_credentials`, `auth_sessions`, `api_tokens`, or new `users` columns do not exist.

- [ ] **Step 3: Add Alembic migration**

Create `backend/migrations/versions/0004_formal_user_management.py`:

```python
"""Formal user management schema.

Revision ID: 0004_formal_user_management
Revises: 0003_worker_runtime_alignment
Create Date: 2026-07-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_formal_user_management"
down_revision = "0003_worker_runtime_alignment"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("role", sa.Text(), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True, postgresql_where=sa.text("email is not null"))
    op.create_index("idx_users_role_status", "users", ["role", "status"])

    op.create_table(
        "user_credentials",
        sa.Column("credential_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("credential_type", sa.Text(), nullable=False, server_default="password"),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_algorithm", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_user_credentials_active_password", "user_credentials", ["user_id"], unique=True, postgresql_where=sa.text("credential_type = 'password' and active = true"))

    op.create_table(
        "auth_sessions",
        sa.Column("session_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token_hash", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
    )
    op.create_index("uq_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("idx_auth_sessions_user_active", "auth_sessions", ["user_id", "expires_at"], postgresql_where=sa.text("revoked_at is null"))

    op.create_table(
        "api_tokens",
        sa.Column("token_id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("token_preview", sa.Text(), nullable=False),
        sa.Column("scopes_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_api_tokens_token_hash", "api_tokens", ["token_hash"], unique=True)
    op.create_index("idx_api_tokens_user_active", "api_tokens", ["user_id", "created_at"], postgresql_where=sa.text("revoked_at is null"))


def downgrade() -> None:
    op.drop_table("api_tokens")
    op.drop_table("auth_sessions")
    op.drop_table("user_credentials")
    op.drop_index("idx_users_role_status", table_name="users")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "role")
    op.drop_column("users", "email")
```

- [ ] **Step 4: Update fresh initial schema**

Mirror the same `users` columns and auth tables in `backend/migrations/versions/0001_initial_postgres_schema.py`. Place new auth tables immediately after `user_identities` and before `audit_events`, so ownership tables are grouped together.

Use the same column definitions and index names from Step 3. In the downgrade table list, add these tables before `user_identities`:

```python
"api_tokens", "auth_sessions", "user_credentials",
```

- [ ] **Step 5: Run migration tests**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_postgres_migrations.py -q
```

Expected: PASS or SKIP if `TEST_DATABASE_URL` is not configured. If SKIP, run at least:

```bash
PYTHONPATH=backend python -m compileall backend/migrations/versions
```

Expected: no syntax errors.

- [ ] **Step 6: Commit schema task**

```bash
git add backend/migrations/versions/0001_initial_postgres_schema.py backend/migrations/versions/0004_formal_user_management.py backend/tests/test_postgres_migrations.py
git commit -m "feat: add formal auth schema"
```

---

## Task 2: Password Hashing And Auth Store Core

**Files:**
- Create: `backend/core/passwords.py`
- Create: `backend/core/auth_store.py`
- Modify: `backend/core/runtime_config.py`
- Create: `backend/tests/test_passwords.py`
- Create: `backend/tests/test_formal_auth.py`

- [ ] **Step 1: Write password tests**

Create `backend/tests/test_passwords.py`:

```python
from __future__ import annotations

import pytest


def test_password_hash_round_trip():
    from core.passwords import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_minimum_length(monkeypatch):
    from core.passwords import validate_password_strength

    monkeypatch.setenv("PASSWORD_MIN_LENGTH", "8")

    with pytest.raises(ValueError, match="at least 8"):
        validate_password_strength("short")

    validate_password_strength("12345678")
```

- [ ] **Step 2: Run password tests and verify they fail**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_passwords.py -q
```

Expected: FAIL because `core.passwords` does not exist.

- [ ] **Step 3: Implement password helpers**

Create `backend/core/passwords.py`:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from core.runtime_config import password_min_length

PBKDF2_ITERATIONS = 260_000


def validate_password_strength(password: str) -> None:
    minimum = password_min_length()
    if len(password or "") < minimum:
        raise ValueError(f"password must be at least {minimum} characters")


def hash_password(password: str) -> str:
    validate_password_strength(password)
    try:
        import bcrypt  # type: ignore

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        return f"bcrypt${hashed}"
    except Exception:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        return "pbkdf2_sha256${iterations}${salt}${digest}".format(
            iterations=PBKDF2_ITERATIONS,
            salt=base64.urlsafe_b64encode(salt).decode("ascii"),
            digest=base64.urlsafe_b64encode(digest).decode("ascii"),
        )


def verify_password(password: str, stored_hash: str) -> bool:
    if not password or not stored_hash:
        return False
    if stored_hash.startswith("bcrypt$"):
        try:
            import bcrypt  # type: ignore

            return bool(bcrypt.checkpw(password.encode("utf-8"), stored_hash.removeprefix("bcrypt$").encode("utf-8")))
        except Exception:
            return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _algorithm, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
            salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_raw))
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False
    return False
```

- [ ] **Step 4: Add runtime config helpers**

Append to `backend/core/runtime_config.py`:

```python
def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def enable_signup() -> bool:
    return bool_env("ENABLE_SIGNUP", True)


def session_ttl_days() -> int:
    raw = os.getenv("SESSION_TTL_DAYS") or "30"
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigError("SESSION_TTL_DAYS must be an integer") from exc
    if value <= 0:
        raise DatabaseConfigError("SESSION_TTL_DAYS must be positive")
    return value


def password_min_length() -> int:
    raw = os.getenv("PASSWORD_MIN_LENGTH") or "8"
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigError("PASSWORD_MIN_LENGTH must be an integer") from exc
    if value < 8:
        raise DatabaseConfigError("PASSWORD_MIN_LENGTH must be at least 8")
    return value


def session_cookie_name() -> str:
    return os.getenv("COOKIE_NAME") or "lap_session"


def csrf_cookie_name() -> str:
    return os.getenv("CSRF_COOKIE_NAME") or "lap_csrf"


def cookie_secure() -> bool:
    return bool_env("COOKIE_SECURE", app_env() == "production")
```

- [ ] **Step 5: Write auth store signup/login tests**

Add to `backend/tests/test_formal_auth.py`:

```python
from __future__ import annotations

from postgres_test_utils import migrated_postgres_schema


def test_signup_bootstraps_first_admin_and_later_user():
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        store = AuthStore()
        admin = store.signup(email="Admin@Example.com", display_name="Admin", password="password123")
        user = store.signup(email="user@example.com", display_name="User", password="password456")

    assert admin["email"] == "admin@example.com"
    assert admin["role"] == "admin"
    assert admin["status"] == "active"
    assert user["role"] == "user"
    assert user["status"] == "active"


def test_login_creates_session_and_validates_cookie_token():
    from core.auth_store import AuthStore

    with migrated_postgres_schema():
        store = AuthStore()
        created = store.signup(email="alice@example.com", display_name="Alice", password="password123")
        login = store.login(email="alice@example.com", password="password123", user_agent="test-agent", ip_address="127.0.0.1")
        resolved = store.user_for_session_token(login["session_token"])

    assert login["user"]["user_id"] == created["user_id"]
    assert login["session_token"]
    assert login["csrf_token"]
    assert resolved["email"] == "alice@example.com"
```

- [ ] **Step 6: Implement auth store core**

Create `backend/core/auth_store.py` with these public methods:

```python
class AuthStore:
    def signup(self, *, email: str, display_name: str, password: str) -> dict: ...
    def login(self, *, email: str, password: str, user_agent: str = "", ip_address: str = "") -> dict: ...
    def logout(self, session_token: str, *, reason: str = "logout") -> bool: ...
    def user_for_session_token(self, session_token: str) -> dict | None: ...
    def validate_csrf(self, session_token: str, csrf_token: str) -> bool: ...
```

Use these implementation details:

```python
LOCAL_PASSWORD_PROVIDER = "local-password"

def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("invalid email")
    return value
```

For token generation and hashing:

```python
import hashlib
import secrets

def _new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

For first-admin bootstrap:

```sql
select count(*) from users
```

If count is `0`, role is `admin`; otherwise role is `user`. Insert into `users`, `user_identities`, `user_credentials`, and `audit_events` in one transaction. On duplicate email or identity, raise `ValueError("email already registered")`.

For login, find `users` through `user_identities(provider='local-password', subject=email_lower)`, verify active password, require `users.status='active'`, create `auth_sessions`, update `users.last_login_at`, update `user_identities.last_seen_at`, and insert `audit_events`.

- [ ] **Step 7: Run core auth tests**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_passwords.py backend/tests/test_formal_auth.py -q
```

Expected: PASS or PostgreSQL tests SKIP if `TEST_DATABASE_URL` is absent. If PostgreSQL tests skip, run:

```bash
PYTHONPATH=backend python -m compileall backend/core/passwords.py backend/core/auth_store.py
```

Expected: no syntax errors.

- [ ] **Step 8: Commit core auth task**

```bash
git add backend/core/passwords.py backend/core/auth_store.py backend/core/runtime_config.py backend/tests/test_passwords.py backend/tests/test_formal_auth.py
git commit -m "feat: add local auth store"
```

---

## Task 3: UserContext Resolver For Session Cookies And API Tokens

**Files:**
- Modify: `backend/core/user_context.py`
- Modify: `backend/core/user_store.py`
- Modify: `backend/tests/test_auth_config.py`
- Modify: `backend/tests/test_user_context.py`
- Modify: `backend/tests/test_postgres_m2_core_runtime.py`

- [ ] **Step 1: Write auth mode tests**

Add to `backend/tests/test_auth_config.py`:

```python
def test_local_password_and_hybrid_auth_modes_are_supported(monkeypatch):
    from core.user_context import auth_mode, validate_auth_runtime

    monkeypatch.setenv("APP_ENV", "production")

    monkeypatch.setenv("AUTH_MODE", "local-password")
    assert auth_mode() == "local-password"
    validate_auth_runtime()

    monkeypatch.setenv("AUTH_MODE", "hybrid")
    assert auth_mode() == "hybrid"
    validate_auth_runtime()
```

- [ ] **Step 2: Write resolver integration test**

Add to `backend/tests/test_formal_auth.py`:

```python
def test_current_user_resolves_local_password_session_cookie(monkeypatch):
    import importlib
    import sys
    from fastapi.testclient import TestClient

    from postgres_test_utils import migrated_postgres_schema

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        for name in ["main", "api.modules_router", "api.auth_router", "core.user_context", "core.auth_store", "core.user_store"]:
            sys.modules.pop(name, None)
        main = importlib.import_module("main")
        client = TestClient(main.app)

        signup = client.post("/api/auth/signup", json={"email": "alice@example.com", "display_name": "Alice", "password": "password123"})
        me = client.get("/api/auth/me")
        legacy_me = client.get("/api/me")

    assert signup.status_code == 200, signup.text
    assert me.status_code == 200, me.text
    assert legacy_me.status_code == 200, legacy_me.text
    assert me.json()["email"] == "alice@example.com"
    assert legacy_me.json()["role"] == "admin"
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_auth_config.py::test_local_password_and_hybrid_auth_modes_are_supported backend/tests/test_formal_auth.py::test_current_user_resolves_local_password_session_cookie -q
```

Expected: FAIL because modes/routes/resolver are not wired yet.

- [ ] **Step 4: Extend UserContext**

Modify `backend/core/user_context.py`:

```python
@dataclass(frozen=True)
class UserContext:
    user_id: str
    workspace_slug: str
    subject: str = DEFAULT_SUBJECT
    display_name: str = DEFAULT_SUBJECT
    auth_mode: str = "dev-header"
    role: str = "user"
    status: str = "active"
    email: str | None = None
```

Update `validate_auth_runtime()` allowed modes:

```python
if mode not in {"dev-header", "trusted-header", "local-password", "hybrid"}:
    raise DatabaseConfigError(f"Unsupported AUTH_MODE: {mode}")
```

Keep production rejection for `dev-header`.

- [ ] **Step 5: Extend user store row shape**

Modify `backend/core/user_store.py` `_user_row()` to include:

```python
"email": row.get("email") if hasattr(row, "get") else None,
"role": row.get("role", "user") if hasattr(row, "get") else "user",
"status": row.get("status", "active") if hasattr(row, "get") else row["status"],
"avatar_url": row.get("avatar_url") if hasattr(row, "get") else None,
```

Update `get_or_create_user_for_subject()` select list to include:

```sql
u.email, u.role, u.avatar_url
```

When auto-creating dev/trusted users, insert `role='user'` and `status='active'`.

- [ ] **Step 6: Implement local-password resolver**

In `backend/core/user_context.py`, add helper:

```python
def _context_from_user_row(user: dict, *, subject: str, mode: str) -> UserContext:
    return UserContext(
        user_id=user["user_id"],
        workspace_slug=subject,
        subject=subject,
        display_name=user.get("display_name") or subject,
        auth_mode=mode,
        role=user.get("role") or "user",
        status=user.get("status") or "active",
        email=user.get("email"),
    )
```

For `mode in {"local-password", "hybrid"}`, read session cookie:

```python
from core.runtime_config import session_cookie_name
from core.auth_store import auth_store

token = request.cookies.get(session_cookie_name())
if token:
    user = auth_store.user_for_session_token(token)
    if user:
        return _context_from_user_row(user, subject=user.get("email") or user["user_id"], mode=mode)
```

If no cookie and an `Authorization: Bearer lap_...` API token exists, resolve it in Task 6. For now, return 401 when no session exists in local-password mode.

For hybrid mode, try trusted header first, then session cookie.

- [ ] **Step 7: Run resolver tests**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_auth_config.py backend/tests/test_user_context.py backend/tests/test_formal_auth.py::test_current_user_resolves_local_password_session_cookie -q
```

Expected: PASS or PostgreSQL tests SKIP when `TEST_DATABASE_URL` is absent.

- [ ] **Step 8: Commit resolver task**

```bash
git add backend/core/user_context.py backend/core/user_store.py backend/tests/test_auth_config.py backend/tests/test_user_context.py backend/tests/test_formal_auth.py
git commit -m "feat: resolve users from auth sessions"
```

---

## Task 4: Auth, Account, And Admin API Routers

**Files:**
- Create: `backend/api/auth_router.py`
- Create: `backend/api/account_router.py`
- Create: `backend/api/admin_router.py`
- Modify: `backend/api/__init__.py`
- Modify: `backend/main.py`
- Modify: `backend/api/modules_router.py`
- Extend: `backend/core/auth_store.py`
- Extend: `backend/tests/test_formal_auth.py`
- Create: `backend/tests/test_account_api.py`
- Create: `backend/tests/test_admin_users_api.py`

- [ ] **Step 1: Write API tests**

Create `backend/tests/test_account_api.py`:

```python
from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient
from postgres_test_utils import migrated_postgres_schema


def _client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local-password")
    for name in ["main", "api.auth_router", "api.account_router", "api.admin_router", "core.user_context", "core.auth_store"]:
        sys.modules.pop(name, None)
    return TestClient(importlib.import_module("main").app)


def test_account_profile_password_sessions_and_api_tokens(monkeypatch):
    with migrated_postgres_schema():
        client = _client(monkeypatch)
        client.post("/api/auth/signup", json={"email": "alice@example.com", "display_name": "Alice", "password": "password123"})
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]

        profile = client.patch("/api/account/profile", json={"display_name": "Alice Chen", "avatar_url": "https://example.com/a.png"}, headers={"X-CSRF-Token": csrf})
        sessions = client.get("/api/account/sessions")
        token = client.post("/api/account/api-tokens", json={"name": "CLI"}, headers={"X-CSRF-Token": csrf})
        tokens = client.get("/api/account/api-tokens")

    assert profile.status_code == 200, profile.text
    assert profile.json()["display_name"] == "Alice Chen"
    assert sessions.status_code == 200
    assert token.status_code == 200, token.text
    assert token.json()["api_token"].startswith("lap_")
    assert tokens.json()["tokens"][0]["token_preview"]
```

Create `backend/tests/test_admin_users_api.py`:

```python
from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient
from postgres_test_utils import migrated_postgres_schema


def _client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local-password")
    for name in ["main", "api.auth_router", "api.account_router", "api.admin_router", "core.user_context", "core.auth_store"]:
        sys.modules.pop(name, None)
    return TestClient(importlib.import_module("main").app)


def test_admin_can_disable_enable_and_cannot_demote_last_admin(monkeypatch):
    with migrated_postgres_schema():
        client = _client(monkeypatch)
        client.post("/api/auth/signup", json={"email": "admin@example.com", "display_name": "Admin", "password": "password123"})
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        client.post("/api/auth/signup", json={"email": "bob@example.com", "display_name": "Bob", "password": "password456"})
        users = client.get("/api/admin/users").json()["users"]
        admin = next(item for item in users if item["email"] == "admin@example.com")
        bob = next(item for item in users if item["email"] == "bob@example.com")

        demote = client.patch(f"/api/admin/users/{admin['user_id']}", json={"role": "user"}, headers={"X-CSRF-Token": csrf})
        disabled = client.patch(f"/api/admin/users/{bob['user_id']}", json={"status": "disabled"}, headers={"X-CSRF-Token": csrf})
        enabled = client.patch(f"/api/admin/users/{bob['user_id']}", json={"status": "active"}, headers={"X-CSRF-Token": csrf})

    assert demote.status_code == 400
    assert "last admin" in demote.text.lower()
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"
```

- [ ] **Step 2: Run API tests and verify they fail**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_account_api.py backend/tests/test_admin_users_api.py -q
```

Expected: FAIL because routers and store methods are not complete.

- [ ] **Step 3: Implement auth router**

Create `backend/api/auth_router.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from core.auth_store import auth_store
from core.runtime_config import cookie_secure, csrf_cookie_name, session_cookie_name, session_ttl_days
from core.user_context import UserContext, current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _set_auth_cookies(response: Response, login: dict) -> None:
    max_age = session_ttl_days() * 24 * 60 * 60
    response.set_cookie(session_cookie_name(), login["session_token"], httponly=True, samesite="lax", secure=cookie_secure(), max_age=max_age, path="/")
    response.set_cookie(csrf_cookie_name(), login["csrf_token"], httponly=False, samesite="lax", secure=cookie_secure(), max_age=max_age, path="/")


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(session_cookie_name(), path="/")
    response.delete_cookie(csrf_cookie_name(), path="/")


@router.post("/signup")
def signup(payload: SignupRequest, request: Request, response: Response):
    try:
        auth_store.signup(email=payload.email, display_name=payload.display_name, password=payload.password)
        login_result = auth_store.login(email=payload.email, password=payload.password, user_agent=request.headers.get("user-agent", ""), ip_address=request.client.host if request.client else "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_auth_cookies(response, login_result)
    return login_result["user"]


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    try:
        login_result = auth_store.login(email=payload.email, password=payload.password, user_agent=request.headers.get("user-agent", ""), ip_address=request.client.host if request.client else "")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_auth_cookies(response, login_result)
    return login_result["user"]


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(session_cookie_name())
    if token:
        auth_store.logout(token)
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(user: UserContext = Depends(current_user)):
    return user.__dict__


@router.get("/csrf")
def csrf(request: Request, user: UserContext = Depends(current_user)):
    token = request.cookies.get(csrf_cookie_name()) or ""
    return {"csrf_token": token}
```

- [ ] **Step 4: Implement account and admin routers**

Create `backend/api/account_router.py` with:

```python
router = APIRouter(prefix="/api/account", tags=["account"])
```

Endpoints:

```text
GET /profile                 -> current user profile
PATCH /profile               -> auth_store.update_profile
POST /password               -> auth_store.change_password
GET /sessions                -> auth_store.list_sessions
DELETE /sessions/{id}        -> auth_store.revoke_session
GET /api-tokens              -> auth_store.list_api_tokens
POST /api-tokens             -> auth_store.create_api_token
DELETE /api-tokens/{id}      -> auth_store.revoke_api_token
```

Create `backend/api/admin_router.py` with:

```python
router = APIRouter(prefix="/api/admin", tags=["admin"])
```

Add dependency:

```python
def require_admin(user: UserContext = Depends(current_user)) -> UserContext:
    if user.role != "admin" or user.status != "active":
        raise HTTPException(status_code=403, detail="admin required")
    return user
```

Endpoints:

```text
GET /users
PATCH /users/{user_id}
POST /users/{user_id}/reset-password
POST /users/{user_id}/revoke-sessions
POST /users/{user_id}/revoke-api-tokens
GET /audit-events
```

- [ ] **Step 5: Add auth store methods**

Extend `backend/core/auth_store.py` with:

```python
def update_profile(self, user_id: str, *, display_name: str | None = None, avatar_url: str | None = None) -> dict: ...
def change_password(self, user_id: str, *, current_password: str, new_password: str) -> bool: ...
def list_sessions(self, user_id: str) -> list[dict]: ...
def revoke_session(self, user_id: str, session_id: str, *, reason: str = "user_revoked") -> bool: ...
def create_api_token(self, user_id: str, *, name: str) -> dict: ...
def list_api_tokens(self, user_id: str) -> list[dict]: ...
def revoke_api_token(self, user_id: str, token_id: str) -> bool: ...
def user_for_api_token(self, token: str) -> dict | None: ...
def list_users(self, *, query: str = "", limit: int = 100, offset: int = 0) -> list[dict]: ...
def update_user_admin(self, actor_user_id: str, target_user_id: str, *, role: str | None = None, status: str | None = None, display_name: str | None = None) -> dict: ...
def reset_password_admin(self, actor_user_id: str, target_user_id: str, *, new_password: str) -> bool: ...
```

Enforce:

```text
role in {'user', 'admin'}
status in {'active', 'disabled'}
last active admin cannot be demoted or disabled
disabled users have all sessions and API tokens revoked
```

- [ ] **Step 6: Include routers**

Modify `backend/api/__init__.py` to import:

```python
from . import account_router, admin_router, auth_router
```

Modify `backend/main.py` to include:

```python
app.include_router(auth_router.router)
app.include_router(account_router.router)
app.include_router(admin_router.router)
```

Keep `/api/me` in `backend/api/modules_router.py`, but include `role`, `status`, and `email`:

```python
return {
    "user_id": user.user_id,
    "subject": user.subject,
    "display_name": user.display_name,
    "auth_mode": user.auth_mode,
    "role": user.role,
    "status": user.status,
    "email": user.email,
}
```

- [ ] **Step 7: Run backend API tests**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_formal_auth.py backend/tests/test_account_api.py backend/tests/test_admin_users_api.py -q
```

Expected: PASS or PostgreSQL tests SKIP if `TEST_DATABASE_URL` is absent.

- [ ] **Step 8: Commit API task**

```bash
git add backend/api/auth_router.py backend/api/account_router.py backend/api/admin_router.py backend/api/__init__.py backend/main.py backend/api/modules_router.py backend/core/auth_store.py backend/tests/test_formal_auth.py backend/tests/test_account_api.py backend/tests/test_admin_users_api.py
git commit -m "feat: add auth account and admin APIs"
```

---

## Task 5: CSRF Enforcement For Cookie Auth

**Files:**
- Modify: `backend/api/auth_router.py`
- Create: `backend/core/csrf.py`
- Modify: `backend/api/account_router.py`
- Modify: `backend/api/admin_router.py`
- Extend: `backend/tests/test_formal_auth.py`

- [ ] **Step 1: Write CSRF failure test**

Add to `backend/tests/test_formal_auth.py`:

```python
def test_cookie_state_change_requires_csrf(monkeypatch):
    import importlib
    import sys
    from fastapi.testclient import TestClient
    from postgres_test_utils import migrated_postgres_schema

    with migrated_postgres_schema():
        monkeypatch.setenv("AUTH_MODE", "local-password")
        for name in ["main", "api.auth_router", "api.account_router", "core.user_context", "core.auth_store"]:
            sys.modules.pop(name, None)
        client = TestClient(importlib.import_module("main").app)
        client.post("/api/auth/signup", json={"email": "alice@example.com", "display_name": "Alice", "password": "password123"})

        missing = client.patch("/api/account/profile", json={"display_name": "No CSRF"})
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        accepted = client.patch("/api/account/profile", json={"display_name": "With CSRF"}, headers={"X-CSRF-Token": csrf})

    assert missing.status_code == 403
    assert accepted.status_code == 200
```

- [ ] **Step 2: Run CSRF test and verify it fails**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_formal_auth.py::test_cookie_state_change_requires_csrf -q
```

Expected: FAIL because account router does not enforce CSRF yet.

- [ ] **Step 3: Implement CSRF dependency**

Create `backend/core/csrf.py`:

```python
from __future__ import annotations

from fastapi import Header, HTTPException, Request

from core.auth_store import auth_store
from core.runtime_config import session_cookie_name


def require_csrf(request: Request, x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token")) -> None:
    session_token = request.cookies.get(session_cookie_name())
    if not session_token or not x_csrf_token or not auth_store.validate_csrf(session_token, x_csrf_token):
        raise HTTPException(status_code=403, detail="csrf failed")
```

Use `Depends(require_csrf)` on every account/admin state-changing endpoint and `/api/auth/logout`.

- [ ] **Step 4: Run CSRF tests**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_formal_auth.py::test_cookie_state_change_requires_csrf backend/tests/test_account_api.py backend/tests/test_admin_users_api.py -q
```

Expected: PASS or SKIP if PostgreSQL is unavailable.

- [ ] **Step 5: Commit CSRF task**

```bash
git add backend/core/csrf.py backend/api/auth_router.py backend/api/account_router.py backend/api/admin_router.py backend/tests/test_formal_auth.py
git commit -m "feat: enforce csrf for cookie auth"
```

---

## Task 6: API Token Authentication

**Files:**
- Modify: `backend/core/user_context.py`
- Extend: `backend/core/auth_store.py`
- Extend: `backend/tests/test_account_api.py`

- [ ] **Step 1: Write API token auth test**

Add to `backend/tests/test_account_api.py`:

```python
def test_api_token_authenticates_as_user(monkeypatch):
    with migrated_postgres_schema():
        client = _client(monkeypatch)
        client.post("/api/auth/signup", json={"email": "alice@example.com", "display_name": "Alice", "password": "password123"})
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        token = client.post("/api/account/api-tokens", json={"name": "CLI"}, headers={"X-CSRF-Token": csrf}).json()["api_token"]

        client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200, me.text
    assert me.json()["email"] == "alice@example.com"
```

- [ ] **Step 2: Run API token test and verify it fails**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_account_api.py::test_api_token_authenticates_as_user -q
```

Expected: FAIL because `current_user()` does not resolve API tokens.

- [ ] **Step 3: Add API token resolver**

In `backend/core/user_context.py`, parse Authorization:

```python
def _bearer_token(request: Request) -> str | None:
    raw = request.headers.get("authorization") or ""
    if not raw.lower().startswith("bearer "):
        return None
    return raw.split(" ", 1)[1].strip() or None
```

For `local-password` and `hybrid`, after cookie resolution:

```python
api_token = _bearer_token(request)
if api_token:
    user = auth_store.user_for_api_token(api_token)
    if user:
        return _context_from_user_row(user, subject=user.get("email") or user["user_id"], mode=mode)
```

Reject disabled users inside `auth_store.user_for_api_token()`.

- [ ] **Step 4: Run API token tests**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_account_api.py::test_api_token_authenticates_as_user backend/tests/test_formal_auth.py -q
```

Expected: PASS or SKIP if PostgreSQL is unavailable.

- [ ] **Step 5: Commit API token auth task**

```bash
git add backend/core/user_context.py backend/core/auth_store.py backend/tests/test_account_api.py
git commit -m "feat: authenticate api tokens"
```

---

## Task 7: Frontend API Client Auth Contracts

**Files:**
- Modify: `frontend/src/api/client.js`
- Modify: `frontend/tests/api_client_contract.test.mjs`

- [x] **Step 1: Write frontend API tests**

Add to `frontend/tests/api_client_contract.test.mjs`:

```js
test("authApi uses cookie credentials and account mutations include csrf", async () => {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET", credentials: options.credentials, headers: options.headers || {}, body: options.body });
    if (url === "/api/auth/csrf") return jsonResponse({ csrf_token: "csrf-1" });
    if (url === "/api/auth/me") return jsonResponse({ user_id: "u1", email: "alice@example.com", display_name: "Alice", role: "admin", status: "active" });
    return jsonResponse({ ok: true });
  };

  const { authApi, accountApi } = await import(`../src/api/client.js?auth=${Date.now()}`);

  await authApi.me();
  await accountApi.updateProfile({ display_name: "Alice Chen" });

  assert.equal(calls[0].url, "/api/auth/me");
  assert.equal(calls[0].credentials, "include");
  assert.equal(calls[1].url, "/api/auth/csrf");
  assert.equal(calls[2].url, "/api/account/profile");
  assert.equal(calls[2].headers["X-CSRF-Token"], "csrf-1");
  assert.equal(calls[2].credentials, "include");
});
```

- [x] **Step 2: Run frontend API test and verify it fails**

Run:

```bash
cd frontend && node --test tests/api_client_contract.test.mjs
```

Expected: FAIL because `authApi` and `accountApi` do not exist.

- [x] **Step 3: Update frontend API client**

In `frontend/src/api/client.js`:

```js
let csrfToken = null;

async function csrfHeader() {
  if (!csrfToken) {
    const res = await fetch(`${BASE}/auth/csrf`, { credentials: "include" });
    if (res.ok) {
      const body = await res.json();
      csrfToken = body.csrf_token || null;
    }
  }
  return csrfToken ? { "X-CSRF-Token": csrfToken } : {};
}

async function authedRequest(path, options = {}) {
  const headers = apiHeaders({
    ...(options.method && options.method !== "GET" ? await csrfHeader() : {}),
    ...(options.headers || {}),
  });
  const res = await fetch(`${BASE}${path}`, { ...options, credentials: "include", headers });
  if (!res.ok) throw new Error(await responseErrorMessage(res));
  return res.json();
}
```

Add exports:

```js
export const authApi = {
  me: () => authedRequest("/auth/me"),
  signup: (payload) => authedRequest("/auth/signup", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload) => authedRequest("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  logout: () => authedRequest("/auth/logout", { method: "POST" }).finally(() => { csrfToken = null; }),
};

export const accountApi = {
  profile: () => authedRequest("/account/profile"),
  updateProfile: (payload) => authedRequest("/account/profile", { method: "PATCH", body: JSON.stringify(payload) }),
  changePassword: (payload) => authedRequest("/account/password", { method: "POST", body: JSON.stringify(payload) }),
  sessions: () => authedRequest("/account/sessions"),
  revokeSession: (id) => authedRequest(`/account/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }),
  apiTokens: () => authedRequest("/account/api-tokens"),
  createApiToken: (payload) => authedRequest("/account/api-tokens", { method: "POST", body: JSON.stringify(payload) }),
  revokeApiToken: (id) => authedRequest(`/account/api-tokens/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

export const adminApi = {
  users: (params = {}) => authedRequest(`/admin/users${new URLSearchParams(params).toString() ? `?${new URLSearchParams(params)}` : ""}`),
  updateUser: (id, payload) => authedRequest(`/admin/users/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  resetPassword: (id, payload) => authedRequest(`/admin/users/${encodeURIComponent(id)}/reset-password`, { method: "POST", body: JSON.stringify(payload) }),
  revokeSessions: (id) => authedRequest(`/admin/users/${encodeURIComponent(id)}/revoke-sessions`, { method: "POST" }),
  revokeApiTokens: (id) => authedRequest(`/admin/users/${encodeURIComponent(id)}/revoke-api-tokens`, { method: "POST" }),
  auditEvents: () => authedRequest("/admin/audit-events"),
};
```

Update existing `apiRequest()` and `multipartRequest()` to pass `credentials: "include"` so cookie auth works for all existing APIs.

- [x] **Step 4: Run frontend API tests**

Run:

```bash
cd frontend && node --test tests/api_client_contract.test.mjs
```

Expected: PASS.

- [x] **Step 5: Commit frontend API task**

```bash
git add frontend/src/api/client.js frontend/tests/api_client_contract.test.mjs
git commit -m "feat: add frontend auth api client"
```

---

## Task 8: Frontend Auth Bootstrap And Login Screen

**Files:**
- Modify: `frontend/src/store/useAppStore.js`
- Modify: `frontend/src/App.jsx`
- Create: `frontend/src/components/AuthScreen.jsx`
- Modify: `frontend/tests/literature_search_store_contract.test.mjs`
- Create: `frontend/tests/auth_ui_contract.test.mjs`

- [x] **Step 1: Write store bootstrap tests**

Add to `frontend/tests/literature_search_store_contract.test.mjs`:

```js
test("auth bootstrap shows login required when me returns 401", async () => {
  installWindowStub();
  globalThis.fetch = async (url) => {
    if (url === "/api/auth/me") return new Response(JSON.stringify({ detail: "not authenticated" }), { status: 401, headers: { "Content-Type": "application/json" } });
    throw new Error(`unexpected fetch: ${url}`);
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?auth401=${Date.now()}`);
  await useAppStore.getState().bootstrapAuth();

  assert.equal(useAppStore.getState().auth.status, "login_required");
  assert.equal(useAppStore.getState().currentUser, null);
});

test("auth bootstrap loads modules when user is authenticated", async () => {
  installWindowStub();
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url === "/api/auth/me") return new Response(JSON.stringify({ user_id: "u1", email: "alice@example.com", display_name: "Alice", role: "admin", status: "active" }), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url === "/api/modules") return new Response(JSON.stringify([{ id: "literature_search", name: "文献检索分析", status: "active" }]), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/settings/effective")) return new Response(JSON.stringify({ general.default_module: { value: "literature_search" } }), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/corpus/quick-stats")) return new Response(JSON.stringify({ status: "ok" }), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/sessions")) return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
  };

  const { useAppStore } = await import(`../src/store/useAppStore.js?auth200=${Date.now()}`);
  await useAppStore.getState().bootstrapAuth();

  assert.equal(useAppStore.getState().auth.status, "authenticated");
  assert.equal(useAppStore.getState().currentUser.email, "alice@example.com");
  assert.ok(calls.includes("/api/modules"));
});
```

- [x] **Step 2: Write UI source contract test**

Create `frontend/tests/auth_ui_contract.test.mjs`:

```js
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("auth screen contains login and registration forms", async () => {
  const source = await readFile(new URL("../src/components/AuthScreen.jsx", import.meta.url), "utf8");

  assert.match(source, /authLogin/);
  assert.match(source, /authSignup/);
  assert.match(source, /email/);
  assert.match(source, /password/);
  assert.match(source, /display_name|displayName/);
});
```

- [x] **Step 3: Run tests and verify they fail**

Run:

```bash
cd frontend && node --test tests/literature_search_store_contract.test.mjs tests/auth_ui_contract.test.mjs
```

Expected: FAIL because auth store and `AuthScreen.jsx` do not exist.

- [x] **Step 4: Add auth state and actions**

Modify import in `frontend/src/store/useAppStore.js`:

```js
import { accountApi, adminApi, authApi, corpusApi, fetchModules, fetchLibrary, literatureSearchApi, modelProfilesApi, sessionApi, settingsApi, streamChat, streamLiteratureSearchJob, structuredExtractionApi, workflowApi, streamWorkflow } from "../api/client.js";
```

Add state:

```js
currentUser: null,
auth: {
  status: "checking",
  mode: "login",
  error: null,
  loading: false,
},
```

Add actions:

```js
async bootstrapAuth() {
  set((state) => ({ auth: { ...state.auth, status: "checking", error: null } }));
  try {
    const user = await authApi.me();
    set((state) => ({ currentUser: user, auth: { ...state.auth, status: "authenticated", error: null } }));
    await get().loadModules();
  } catch (e) {
    set((state) => ({ currentUser: null, modulesLoaded: true, auth: { ...state.auth, status: "login_required", error: null } }));
  }
},
setAuthMode(mode) {
  set((state) => ({ auth: { ...state.auth, mode, error: null } }));
},
async authLogin(payload) {
  set((state) => ({ auth: { ...state.auth, loading: true, error: null } }));
  try {
    const user = await authApi.login(payload);
    set((state) => ({ currentUser: user, auth: { ...state.auth, status: "authenticated", loading: false } }));
    await get().loadModules();
  } catch (e) {
    set((state) => ({ auth: { ...state.auth, loading: false, error: e.message } }));
  }
},
async authSignup(payload) {
  set((state) => ({ auth: { ...state.auth, loading: true, error: null } }));
  try {
    const user = await authApi.signup(payload);
    set((state) => ({ currentUser: user, auth: { ...state.auth, status: "authenticated", loading: false } }));
    await get().loadModules();
  } catch (e) {
    set((state) => ({ auth: { ...state.auth, loading: false, error: e.message } }));
  }
},
async authLogout() {
  await authApi.logout().catch(() => {});
  set({
    currentUser: null,
    modules: [],
    modulesLoaded: true,
    activeModuleId: null,
    sessionsById: {},
    sessionOrderByModule: {},
    activeSessionByModule: {},
    auth: { status: "login_required", mode: "login", error: null, loading: false },
  });
},
```

- [x] **Step 5: Add AuthScreen component**

Create `frontend/src/components/AuthScreen.jsx`:

```jsx
import React, { useState } from "react";
import { LogIn, UserPlus } from "lucide-react";
import { useAppStore } from "../store/useAppStore";

export default function AuthScreen() {
  const mode = useAppStore((s) => s.auth.mode);
  const loading = useAppStore((s) => s.auth.loading);
  const error = useAppStore((s) => s.auth.error);
  const setAuthMode = useAppStore((s) => s.setAuthMode);
  const authLogin = useAppStore((s) => s.authLogin);
  const authSignup = useAppStore((s) => s.authSignup);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");

  const submit = (event) => {
    event.preventDefault();
    if (mode === "signup") {
      authSignup({ email, display_name: displayName, password });
    } else {
      authLogin({ email, password });
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-paper-50 px-4">
      <form onSubmit={submit} className="w-full max-w-[360px] rounded-lg border border-line bg-paper-0 p-5 shadow-xl">
        <div className="mb-4 flex items-center gap-2">
          {mode === "signup" ? <UserPlus size={18} /> : <LogIn size={18} />}
          <h1 className="font-serif text-[18px] text-ink-900">{mode === "signup" ? "注册账号" : "登录"}</h1>
        </div>
        {error && <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700">{error}</div>}
        <label className="mb-3 block text-[12.5px] text-ink-700">
          邮箱
          <input className="form-input mt-1" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        {mode === "signup" && (
          <label className="mb-3 block text-[12.5px] text-ink-700">
            显示名
            <input className="form-input mt-1" value={displayName} onChange={(e) => setDisplayName(e.target.value)} required />
          </label>
        )}
        <label className="mb-4 block text-[12.5px] text-ink-700">
          密码
          <input className="form-input mt-1" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        </label>
        <button className="btn-primary w-full justify-center" type="submit" disabled={loading}>{loading ? "处理中..." : mode === "signup" ? "注册并进入" : "登录"}</button>
        <button className="mt-3 w-full text-[12.5px] text-ink-500 hover:text-ink-900" type="button" onClick={() => setAuthMode(mode === "signup" ? "login" : "signup")}>
          {mode === "signup" ? "已有账号，去登录" : "没有账号，注册一个"}
        </button>
      </form>
    </div>
  );
}
```

- [x] **Step 6: Gate App by auth**

Modify `frontend/src/App.jsx`:

```jsx
import AuthScreen from "./components/AuthScreen";
```

Change startup effect:

```jsx
const bootstrapAuth = useAppStore((s) => s.bootstrapAuth);
const authStatus = useAppStore((s) => s.auth.status);

useEffect(() => {
  bootstrapAuth();
}, [bootstrapAuth]);

if (authStatus === "checking") {
  return <div className="h-screen flex items-center justify-center bg-paper-50 text-ink-500 text-[13px] font-mono">正在检查登录状态...</div>;
}

if (authStatus === "login_required") {
  return <AuthScreen />;
}
```

Remove the old `loadModules()` startup call from `App.jsx`; `bootstrapAuth()` now calls it after auth succeeds.

- [x] **Step 7: Run frontend tests and build**

Run:

```bash
cd frontend && node --test tests/literature_search_store_contract.test.mjs tests/auth_ui_contract.test.mjs
cd frontend && npm run build
```

Expected: tests PASS and build succeeds.

- [x] **Step 8: Commit auth bootstrap task**

```bash
git add frontend/src/store/useAppStore.js frontend/src/App.jsx frontend/src/components/AuthScreen.jsx frontend/tests/literature_search_store_contract.test.mjs frontend/tests/auth_ui_contract.test.mjs
git commit -m "feat: add frontend auth bootstrap"
```

---

## Task 9: Account Settings And Admin Users UI

**Files:**
- Modify: `frontend/src/components/SettingsModal.jsx`
- Modify: `frontend/src/components/TopBar.jsx`
- Create: `frontend/src/components/AdminUsersModal.jsx`
- Modify: `frontend/src/store/useAppStore.js`
- Modify: `frontend/tests/auth_ui_contract.test.mjs`

- [ ] **Step 1: Write UI contract tests**

Extend `frontend/tests/auth_ui_contract.test.mjs`:

```js
test("account settings uses real current user and exposes api tokens", async () => {
  const source = await readFile(new URL("../src/components/SettingsModal.jsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /ACCOUNT_PLACEHOLDER/);
  assert.match(source, /currentUser/);
  assert.match(source, /apiTokens|API token|API Token/);
  assert.match(source, /changePassword|修改密码/);
});

test("admin users modal contains role status and reset actions", async () => {
  const source = await readFile(new URL("../src/components/AdminUsersModal.jsx", import.meta.url), "utf8");

  assert.match(source, /adminUsers/);
  assert.match(source, /role/);
  assert.match(source, /status/);
  assert.match(source, /resetPassword|重置密码/);
  assert.match(source, /disabled|禁用/);
});
```

- [ ] **Step 2: Run UI tests and verify they fail**

Run:

```bash
cd frontend && node --test tests/auth_ui_contract.test.mjs
```

Expected: FAIL because Account is still placeholder and AdminUsersModal does not exist.

- [ ] **Step 3: Add store state/actions**

In `frontend/src/store/useAppStore.js`, add:

```js
adminUsersOpen: false,
account: {
  sessions: [],
  apiTokens: [],
  lastCreatedToken: null,
  loading: false,
  error: null,
},
adminUsers: {
  items: [],
  loading: false,
  error: null,
},
```

Add actions:

```js
async loadAccountSecurity() { ...accountApi.sessions() and accountApi.apiTokens()... }
async updateAccountProfile(payload) { ...accountApi.updateProfile(payload); refresh currentUser... }
async changeAccountPassword(payload) { ...accountApi.changePassword(payload)... }
async createAccountApiToken(payload) { ...accountApi.createApiToken(payload)... }
async revokeAccountApiToken(id) { ...accountApi.revokeApiToken(id)... }
openAdminUsers() { set({ adminUsersOpen: true }); get().loadAdminUsers(); }
closeAdminUsers() { set({ adminUsersOpen: false }); }
async loadAdminUsers() { ...adminApi.users()... }
async updateAdminUser(id, payload) { ...adminApi.updateUser(id, payload); reload... }
async resetAdminUserPassword(id, newPassword) { ...adminApi.resetPassword(id, { new_password: newPassword })... }
```

- [ ] **Step 4: Replace Account placeholder**

In `frontend/src/components/SettingsModal.jsx`, delete `ACCOUNT_PLACEHOLDER`. Make `AccountCategory()` read:

```jsx
const account = useAppStore((s) => s.currentUser);
const updateAccountProfile = useAppStore((s) => s.updateAccountProfile);
const loadAccountSecurity = useAppStore((s) => s.loadAccountSecurity);
const apiTokens = useAppStore((s) => s.account.apiTokens);
const sessions = useAppStore((s) => s.account.sessions);
```

Render:

```text
email
display_name
role
status
auth_mode
avatar_url input
change password form
active sessions list
API token list and create form
```

Keep styling consistent with existing settings groups and avoid nested cards.

- [ ] **Step 5: Add TopBar user menu**

Modify `frontend/src/components/TopBar.jsx`:

```jsx
const currentUser = useAppStore((s) => s.currentUser);
const openSettings = useAppStore((s) => s.openSettings);
const openAdminUsers = useAppStore((s) => s.openAdminUsers);
const authLogout = useAppStore((s) => s.authLogout);
```

Add compact controls on the right:

```text
display_name
Account button
Admin Users button when role === admin
Logout button
```

Use lucide icons: `UserRound`, `Users`, `LogOut`.

- [ ] **Step 6: Create AdminUsersModal**

Create `frontend/src/components/AdminUsersModal.jsx` with:

```jsx
export default function AdminUsersModal() { ... }
```

Read `adminUsersOpen`, `adminUsers.items`, and actions from store. Render a modal table with:

```text
email
display name
role select
status select
last login
reset password button
```

Protect UI:

```jsx
if (!open) return null;
```

- [ ] **Step 7: Mount AdminUsersModal**

In `frontend/src/App.jsx`:

```jsx
import AdminUsersModal from "./components/AdminUsersModal";
...
<AdminUsersModal />
```

- [ ] **Step 8: Run frontend UI tests and build**

Run:

```bash
cd frontend && node --test tests/auth_ui_contract.test.mjs tests/literature_search_store_contract.test.mjs
cd frontend && npm run build
```

Expected: PASS and build succeeds.

- [ ] **Step 9: Commit UI task**

```bash
git add frontend/src/components/SettingsModal.jsx frontend/src/components/TopBar.jsx frontend/src/components/AdminUsersModal.jsx frontend/src/store/useAppStore.js frontend/src/App.jsx frontend/tests/auth_ui_contract.test.mjs
git commit -m "feat: add account and admin user UI"
```

---

## Task 10: End-To-End Verification And Documentation

**Files:**
- Modify: `.env.example`
- Modify: `docs/deployment.md`
- Modify: `README.md`
- Possibly modify: `backend/tests/test_platform_readiness.py`

- [ ] **Step 1: Update environment docs**

Add to `.env.example`:

```bash
AUTH_MODE=local-password
ENABLE_SIGNUP=true
SESSION_TTL_DAYS=30
PASSWORD_MIN_LENGTH=8
COOKIE_NAME=lap_session
CSRF_COOKIE_NAME=lap_csrf
```

If preserving dev default is preferred for current local workflows, keep `AUTH_MODE=dev-header` in `.env.example` and add the new variables commented below it:

```bash
# For formal local login:
# AUTH_MODE=local-password
```

- [ ] **Step 2: Update deployment guide**

In `docs/deployment.md`, add a "Formal Local Login" section:

```markdown
## Formal Local Login

Set:

```bash
APP_ENV=production
AUTH_MODE=local-password
ENABLE_SIGNUP=true
SESSION_TTL_DAYS=30
LITERATURE_SECRET_KEY_PATH=/srv/literature-agent/secret.key
```

The first registered account becomes admin. Later accounts are normal users. Browser login uses an opaque httpOnly database session cookie named `lap_session`.
```
```

- [ ] **Step 3: Update README deployment hints**

In `README.md` team deployment notes, replace the current auth bullets with:

```markdown
- 开发/测试可用 `AUTH_MODE=dev-header` 和 `X-User-Id` 模拟用户。
- 正式本地账号登录使用 `AUTH_MODE=local-password`，浏览器登录态为 httpOnly DB session cookie。
- 可信反向代理/SSO 过渡可用 `AUTH_MODE=trusted-header`。
- 生产必须禁止裸露后端可信头入口，且不得使用 `AUTH_MODE=dev-header`。
```

- [ ] **Step 4: Run backend verification**

Run:

```bash
PYTHONPATH=backend pytest backend/tests/test_auth_config.py backend/tests/test_passwords.py backend/tests/test_formal_auth.py backend/tests/test_account_api.py backend/tests/test_admin_users_api.py backend/tests/test_postgres_migrations.py -q
```

Expected: PASS or PostgreSQL-dependent tests SKIP if `TEST_DATABASE_URL` is not configured.

Run broader compatibility:

```bash
PYTHONPATH=backend pytest backend/tests/test_postgres_m2_core_runtime.py backend/tests/test_user_context.py backend/tests/test_api_contract_sessions_chat.py backend/tests/test_api_contract_settings_workflow.py -q
```

Expected: PASS or PostgreSQL-dependent tests SKIP if `TEST_DATABASE_URL` is not configured.

- [ ] **Step 5: Run frontend verification**

Run:

```bash
cd frontend && node --test tests/api_client_contract.test.mjs tests/literature_search_store_contract.test.mjs tests/auth_ui_contract.test.mjs
cd frontend && npm run build
```

Expected: tests PASS and build succeeds.

- [ ] **Step 6: Manual smoke with dev server**

Start services in a local auth mode that does not disturb production services:

```bash
AUTH_MODE=local-password START_WORKER=0 bash dev.sh
```

Manual checks:

```text
1. Open frontend.
2. Register first account.
3. Confirm user menu shows admin.
4. Create a literature session and send a simple agent message.
5. Register second account in a separate browser profile or after logout.
6. Confirm second account is role=user and can use agent.
7. Login as admin and disable second user.
8. Confirm second user can no longer access API after refresh.
9. Create an API token and call GET /api/auth/me with Authorization: Bearer <token>.
```

- [ ] **Step 7: Commit docs and verification updates**

```bash
git add .env.example README.md docs/deployment.md backend/tests/test_platform_readiness.py
git commit -m "docs: document formal user management"
```

If `backend/tests/test_platform_readiness.py` was not modified, omit it from `git add`.

---

## Self-Review Checklist

- [ ] Spec coverage: schema, local password auth, DB session cookie, CSRF, API token, admin users, account settings, frontend login, no pending flow, self-service registration, first admin bootstrap, existing auth mode compatibility.
- [ ] Placeholder scan: no unresolved placeholder markers or vague implementation notes remain in this plan.
- [ ] Type consistency: backend uses `user_id`, `email`, `display_name`, `role`, `status`, `avatar_url`; frontend uses camelCase only after normalization where existing patterns require it.
- [ ] Safety: no raw password, raw session token, raw CSRF token, or raw API token is logged or stored.
- [ ] Compatibility: `dev-header` tests and current user-scoped stores remain protected by `current_user()`.

## Execution Notes

Implement tasks in order. Tasks 1-6 are backend prerequisites for Tasks 7-9. Task 10 is the final verification and documentation pass.
