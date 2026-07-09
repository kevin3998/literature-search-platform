# Formal User Management Design

Date: 2026-07-09

## Purpose

This design adds a complete local user management and login system to the literature agent platform while preserving the existing `users` + `user_identities` + `UserContext` boundary.

Open WebUI is used as a product reference for the account lifecycle, first-admin bootstrap, local password login, user administration, API tokens, and trusted-header compatibility. The implementation will not copy Open WebUI code or schema directly. The platform already has internal UUID users, external identity mappings, per-user settings, per-user secrets, and user-scoped business data, so the new auth system should extend that architecture instead of replacing it.

## Scope

In scope:

- Local email/password signup, login, logout, and current-user APIs.
- Browser login backed by opaque database session cookies.
- Self-service registration.
- First registered user becomes `admin`; later users become `user`.
- Account status with `active` and `disabled`.
- Admin user management: list, search, update role, disable, enable, reset password, revoke sessions and API tokens.
- User account management: profile, password change, active session list, API token management.
- API tokens for script and external client access.
- Audit events for auth and user-management actions.
- Compatibility with the existing `dev-header` and `trusted-header` modes.
- Frontend login/register UI, account settings, user menu, and admin user management surface.

Out of scope for this design:

- Pending-user approval flow.
- Email verification or email-based password reset.
- Workspace, team, organization, sharing, or invitation systems.
- Full OAuth/OIDC UI flow.
- LDAP integration.
- Avatar file upload.
- Fine-grained API token scopes.
- Migration or modification of the Research Index or production indexing service.

## Reference Model

Open WebUI provides a useful reference shape:

- Separate user profile and credential records.
- Local password login with hashed passwords.
- First user bootstrap as admin.
- Admin-managed users.
- Trusted-header mode for deployments behind an authenticated proxy.
- API keys for non-browser access.

The platform will adapt these ideas to its existing model:

```text
users                  internal stable platform accounts
user_identities         external provider/subject mappings
user_credentials        local password credentials
auth_sessions           browser session cookies
api_tokens              machine/API credentials
audit_events            lifecycle and security event log
```

## User Types

The system has two roles:

```text
user   normal platform user
admin  administrator / developer
```

The system has two statuses:

```text
active    account can log in and use the platform
disabled  account cannot authenticate or call APIs
```

Registration rules:

```text
first registered user       -> role=admin, status=active
all later registered users  -> role=user, status=active
```

Protection rules:

- The last active admin cannot be disabled.
- The last active admin cannot be demoted to `user`.
- A disabled user cannot log in.
- Disabling a user revokes all of that user's browser sessions and API tokens.

## Data Model

### users

Extend the existing `users` table:

```text
users
- user_id uuid primary key
- email text nullable unique
- display_name text not null
- role text not null default 'user'
- status text not null default 'active'
- avatar_url text nullable
- metadata_json jsonb not null default '{}'
- created_at timestamptz not null
- updated_at timestamptz not null
- last_login_at timestamptz nullable
```

Existing deployments already have `user_id`, `display_name`, `status`, `metadata_json`, `created_at`, and `updated_at`. A migration should add missing columns and backfill:

- `role='admin'` for the existing `local_user`/first user when there are no local-password users yet.
- `email=null` for development and trusted-header users without a local email identity.
- `status='active'` for existing active users.

### user_identities

Keep `user_identities` as the canonical external identity mapping:

```text
user_identities
- identity_id uuid primary key
- user_id uuid references users(user_id)
- provider text not null
- subject text not null
- metadata_json jsonb not null default '{}'
- created_at timestamptz not null
- last_seen_at timestamptz not null
- unique(provider, subject)
```

Provider values:

```text
local-password
dev-header
trusted-header
api-token
```

Local password login uses email as the unique identity subject:

```text
provider='local-password'
subject=lower(email)
```

Display name is never used for login.

### user_credentials

Add a dedicated table for local password credentials:

```text
user_credentials
- credential_id uuid primary key
- user_id uuid not null references users(user_id)
- credential_type text not null default 'password'
- password_hash text not null
- password_algorithm text not null
- active boolean not null default true
- created_at timestamptz not null
- updated_at timestamptz not null
```

Rules:

- One active password credential per user in v1.
- Passwords are never stored or logged in plaintext.
- Password hash uses Argon2id if available; bcrypt is acceptable if Argon2id is not selected during implementation.
- Minimum password length is 8 characters.
- Users cannot change their own email in v1.

### auth_sessions

Browser login uses opaque database sessions, not browser-visible JWTs.

```text
auth_sessions
- session_id uuid primary key
- user_id uuid not null references users(user_id)
- token_hash text not null unique
- csrf_token_hash text not null
- user_agent text nullable
- ip_hash text nullable
- created_at timestamptz not null
- last_seen_at timestamptz not null
- expires_at timestamptz not null
- revoked_at timestamptz nullable
- revoked_reason text nullable
```

The raw session token is only sent to the browser as a cookie and is never stored in the database. The database stores only a hash.

Default session lifetime:

```text
SESSION_TTL_DAYS=30
```

### api_tokens

API tokens are for scripts and external clients. They are separate from browser sessions.

```text
api_tokens
- token_id uuid primary key
- user_id uuid not null references users(user_id)
- name text not null
- token_hash text not null unique
- token_preview text not null
- scopes_json jsonb not null default '[]'
- created_at timestamptz not null
- last_used_at timestamptz nullable
- expires_at timestamptz nullable
- revoked_at timestamptz nullable
```

V1 scopes are intentionally simple:

```text
scopes_json=[]
```

An API token acts as the owning user. Fine-grained scopes can be added later without changing the authentication boundary.

## Authentication Modes

The existing modes stay valid:

```text
dev-header       development/test only, uses X-User-Id
trusted-header   trusted reverse proxy injects identity
```

New modes:

```text
local-password   email/password login with DB session cookie
hybrid           trusted-header plus local-password/API token fallback
```

Production safety:

- `APP_ENV=production` with `AUTH_MODE=dev-header` remains invalid.
- `local-password` requires a persistent session secret.
- `trusted-header` requires the backend to be reachable only behind the trusted proxy.
- `hybrid` must define deterministic precedence.

Recommended resolver order:

```text
dev-header:
  X-User-Id only

trusted-header:
  trusted proxy header only

local-password:
  browser session cookie, then API token

hybrid:
  trusted proxy header, then browser session cookie, then API token
```

## Browser Session Cookie

Login sets:

```text
lap_session=<opaque random token>
HttpOnly
SameSite=Lax
Path=/
Secure in production
Max-Age=30 days
```

CSRF protection uses a separate token:

```text
lap_csrf=<csrf token>
```

State-changing requests must send:

```text
X-CSRF-Token: <csrf token>
```

The backend hashes the submitted CSRF token and compares it with `auth_sessions.csrf_token_hash`.

Frontend fetch requests must include:

```js
credentials: "include"
```

The frontend must not store the browser session token in localStorage.

## UserContext

Extend `UserContext` while preserving existing call sites:

```python
@dataclass(frozen=True)
class UserContext:
    user_id: str
    workspace_slug: str
    subject: str
    display_name: str
    auth_mode: str
    role: str = "user"
    status: str = "active"
    email: str | None = None
```

The `current_user()` dependency becomes the single resolver for all modes:

```text
request -> auth resolver -> users row -> status check -> UserContext
```

Existing business routers continue using `Depends(current_user)`.

## API Design

### Auth

```text
POST /api/auth/signup
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/auth/csrf
```

Signup payload:

```json
{
  "email": "alice@example.com",
  "display_name": "Alice",
  "password": "********"
}
```

Login payload:

```json
{
  "email": "alice@example.com",
  "password": "********"
}
```

`/api/auth/me` returns:

```json
{
  "user_id": "uuid",
  "email": "alice@example.com",
  "display_name": "Alice",
  "role": "user",
  "status": "active",
  "auth_mode": "local-password"
}
```

### Account

```text
GET    /api/account/profile
PATCH  /api/account/profile
POST   /api/account/password
GET    /api/account/sessions
DELETE /api/account/sessions/{session_id}
```

V1 profile fields:

```text
display_name
avatar_url
```

Email is read-only in v1.

### API Tokens

```text
GET    /api/account/api-tokens
POST   /api/account/api-tokens
DELETE /api/account/api-tokens/{token_id}
```

Token creation returns the raw token once. Later reads only return metadata and `token_preview`.

### Admin

```text
GET   /api/admin/users
POST  /api/admin/users
GET   /api/admin/users/{user_id}
PATCH /api/admin/users/{user_id}
POST  /api/admin/users/{user_id}/reset-password
POST  /api/admin/users/{user_id}/revoke-sessions
POST  /api/admin/users/{user_id}/revoke-api-tokens
GET   /api/admin/audit-events
```

Admin-only operations require:

```text
UserContext.role == 'admin'
UserContext.status == 'active'
```

## Frontend Design

Startup flow:

```text
App loads
-> GET /api/auth/me
-> 200: enter platform
-> 401: show login/register screen
```

Login/register screen:

- Email login.
- Self-service registration.
- Error states for invalid credentials, disabled accounts, and server/auth configuration.

TopBar:

- Shows current display name and role.
- User menu: Account, API Tokens, Admin Users if admin, Logout.

Settings Account:

- Real account data from `/api/auth/me` or `/api/account/profile`.
- Edit display name and avatar URL.
- Change password.
- View active browser sessions.
- Manage API tokens.

Admin Users:

- List and search users.
- Show email, display name, role, status, created time, last login.
- Change `user`/`admin`.
- Disable/enable users.
- Reset password.
- Revoke sessions and API tokens.

Development-only user switching:

- Existing `X-User-Id` switching remains available only in `AUTH_MODE=dev-header`.
- It is hidden for `local-password`, `trusted-header`, and production.

## Audit Events

Write audit events for:

```text
auth.signup
auth.login
auth.logout
auth.login_failed
auth.password_changed
auth.session_revoked
api_token.created
api_token.revoked
user.created
user.updated
user.disabled
user.enabled
user.role_changed
user.password_reset
```

Audit metadata must not include plaintext passwords, raw session tokens, raw API tokens, or full secrets.

## Error Handling

Authentication errors:

```text
401 not_authenticated
401 invalid_credentials
403 account_disabled
403 admin_required
403 csrf_failed
409 email_taken
400 weak_password
```

Login failures should use a generic message where possible to avoid account enumeration.

## Configuration

Recommended defaults:

```text
AUTH_MODE=local-password
ENABLE_SIGNUP=true
SESSION_TTL_DAYS=30
PASSWORD_MIN_LENGTH=8
COOKIE_NAME=lap_session
CSRF_COOKIE_NAME=lap_csrf
```

Production requirements:

```text
APP_ENV=production
AUTH_MODE=local-password or trusted-header or hybrid
LITERATURE_SECRET_KEY_PATH or SESSION_SECRET_KEY configured persistently
COOKIE_SECURE=true
```

Signup behavior:

- Signup is enabled by default.
- `ENABLE_SIGNUP=false` disables self-service signup after the first user exists.
- First-user signup is always allowed if no users exist, so the system can bootstrap its first admin.

## Data And Runtime Effects

This design does not modify the shared Research Index or current indexing process.

Business data remains scoped by internal `users.user_id`:

- sessions
- settings
- model profiles
- secrets
- jobs
- workflows
- structured extraction tasks
- artifacts

Disabling a user does not delete data. Re-enabling a user restores access to their existing data.

## Testing

Backend tests:

- First signup creates `admin active`.
- Later signup creates `user active`.
- Duplicate email is rejected.
- Login sets session cookie and creates `auth_sessions`.
- Logout revokes the current session.
- Disabled user cannot log in.
- Disabling a user revokes sessions and API tokens.
- Last admin cannot be disabled or demoted.
- `current_user()` resolves local-password session.
- `current_user()` still resolves dev-header in development.
- Production still rejects `AUTH_MODE=dev-header`.
- Trusted-header behavior remains compatible.
- CSRF is required for state-changing cookie-authenticated requests.
- API token resolves the owning user.

Frontend tests:

- App shows login/register when `/api/auth/me` returns 401.
- App enters platform when `/api/auth/me` returns a user.
- Login/register forms call the expected APIs.
- Account page renders real user data.
- Admin Users UI is visible only for `admin`.
- Logout clears authenticated UI state.

Manual checks:

- Register first admin.
- Register second user.
- Login as both users and verify data isolation.
- Disable second user and verify immediate session invalidation.
- Create API token and call a protected endpoint.

## Acceptance Criteria

- Users can self-register and log in with email/password.
- The first registered user is admin; later users are normal users.
- Browser auth uses opaque DB session cookies, not localStorage tokens.
- Users can immediately use agent functionality after registration.
- Admins can manage users without touching business data manually.
- Disabled accounts cannot authenticate or use existing sessions/API tokens.
- Existing `dev-header` and `trusted-header` modes remain available and tested.
- Existing user-scoped sessions, settings, model profiles, workflows, and structured extraction flows continue to use internal `user_id`.
