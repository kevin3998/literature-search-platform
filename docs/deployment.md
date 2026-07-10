# PostgreSQL Deployment Guide

## Local Development

Use Docker Compose for PostgreSQL and run web/worker/frontend on the host:

```bash
cp .env.example .env
docker compose up -d postgres
bash dev.sh
```

`dev.sh` loads `.env`, runs `alembic upgrade head`, starts the worker, starts FastAPI, and then starts Vite. If `START_WORKER=0`, long jobs are queued but not executed.

## Required Runtime Settings

Development defaults:

```bash
APP_ENV=development
AUTH_MODE=dev-header
DATABASE_URL=postgresql+psycopg://literature_agent:literature_agent_dev@127.0.0.1:5432/literature_agent
DB_SCHEMA=literature_agent
LITERATURE_USER_DATA_ROOT=.runtime/users
LITERATURE_SECRET_KEY_PATH=.runtime/secret.key
WORKER_QUEUES=default,workflow,structured-extraction
```

Production requirements:

```bash
APP_ENV=production
AUTH_MODE=local-password
DATABASE_URL=postgresql+psycopg://...
DB_SCHEMA=literature_agent
ENABLE_SIGNUP=true
SESSION_TTL_DAYS=30
PASSWORD_MIN_LENGTH=8
COOKIE_NAME=lap_session
CSRF_COOKIE_NAME=lap_csrf
LITERATURE_USER_DATA_ROOT=/srv/literature-agent/users
LITERATURE_SECRET_KEY_PATH=/srv/literature-agent/secret.key
WORKER_REQUIRED=true
CORS_ALLOW_ORIGINS=
```

Production does not auto-run migrations at service startup. Run migration explicitly before restarting services:

```bash
cd /srv/literature-agent
PYTHONPATH=backend alembic -c backend/alembic.ini upgrade head
```

## Formal Local Login

For first-party browser login, use the local email/password auth mode:

```bash
APP_ENV=production
AUTH_MODE=local-password
ENABLE_SIGNUP=true
SESSION_TTL_DAYS=30
PASSWORD_MIN_LENGTH=8
COOKIE_NAME=lap_session
CSRF_COOKIE_NAME=lap_csrf
LITERATURE_SECRET_KEY_PATH=/srv/literature-agent/secret.key
```

The first registered active account becomes `admin`. Later self-service signups become ordinary `user` accounts and can use agent features immediately unless an admin disables them. Browser login uses an opaque httpOnly database session cookie named `lap_session`; browser state-changing requests use the `lap_csrf` CSRF cookie/header pair. API tokens are created from Settings -> Account and can authenticate with `Authorization: Bearer <token>`.

## Trusted Header Auth

`AUTH_MODE=trusted-header` is still available as a reverse-proxy / SSO bridge. A trusted reverse proxy injects:

```text
X-Forwarded-User: alice
X-Forwarded-User-Name: Alice Chen
```

The backend must bind only to `127.0.0.1` or a private network behind the proxy. Do not expose the backend directly to browsers, because clients could forge trusted headers. Do not use `AUTH_MODE=dev-header` in production.

Optional header names:

```bash
TRUSTED_USER_HEADER=X-Forwarded-User
TRUSTED_DISPLAY_NAME_HEADER=X-Forwarded-User-Name
```

## systemd Examples

Web service:

```ini
[Unit]
Description=Literature Agent API
After=network.target postgresql.service

[Service]
WorkingDirectory=/srv/literature-agent/backend
EnvironmentFile=/srv/literature-agent/.env
ExecStart=/srv/literature-agent/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Worker service:

```ini
[Unit]
Description=Literature Agent Worker
After=network.target postgresql.service

[Service]
WorkingDirectory=/srv/literature-agent
EnvironmentFile=/srv/literature-agent/.env
ExecStart=/srv/literature-agent/.venv/bin/python -m core.worker.main
Environment=PYTHONPATH=/srv/literature-agent/backend
Restart=always

[Install]
WantedBy=multi-user.target
```

## Reverse Proxy

Nginx should serve the built frontend and proxy `/api` to FastAPI. It must set trusted user headers from the real authentication layer:

```nginx
location /api/ {
  proxy_pass http://127.0.0.1:8000/api/;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-User $remote_user;
  proxy_set_header X-Forwarded-User-Name $remote_user;
}
```

If frontend and API are served from the same origin, leave `CORS_ALLOW_ORIGINS` empty in production.

## Backup And Restore

Create a backup:

```bash
DATABASE_URL=postgresql+psycopg://... \
LITERATURE_USER_DATA_ROOT=/srv/literature-agent/users \
LITERATURE_DATA_DIR=/srv/literature-agent/literature_data \
LITERATURE_SECRET_KEY_PATH=/srv/literature-agent/secret.key \
BACKUP_DIR=/srv/literature-agent/backups \
scripts/backup_platform.sh
```

For a non-destructive size/scope check before a full archive, run:

```bash
BACKUP_DRY_RUN=1 scripts/backup_platform.sh
```

The backup includes:

- PostgreSQL custom-format dump.
- User workspace and artifact/data directories when present.
- Fernet secret key archive.
- JSON manifest with safe database URL and missing paths.

Restore requires both the PostgreSQL dump and the same Fernet key. Without the key, encrypted API keys in PostgreSQL cannot be decrypted.

## Readiness

Check:

```bash
curl -fsS http://127.0.0.1:8000/api/readiness
```

Production readiness returns HTTP 503 if PostgreSQL is unavailable, migrations are not at head, auth is unsafe, the secret key is missing, or no worker heartbeat is fresh.

## Troubleshooting

- `DATABASE_URL is required`: copy `.env.example` to `.env` or export a PostgreSQL SQLAlchemy URL.
- `AUTH_MODE=dev-header is not allowed`: production must use `local-password`, `trusted-header`, or `hybrid`.
- `LITERATURE_SECRET_KEY_PATH is required`: create and persist a Fernet key file before production startup.
- `no live worker heartbeat`: start the worker service or set `WORKER_REQUIRED=false` only in development.
- Background jobs stay queued: worker is not running or is not listening to the required queue.
