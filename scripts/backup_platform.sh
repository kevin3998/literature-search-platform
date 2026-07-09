#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required for PostgreSQL backup." >&2
  exit 1
fi

BACKUP_DRY_RUN="${BACKUP_DRY_RUN:-0}"
if [[ "$BACKUP_DRY_RUN" == "1" || "$BACKUP_DRY_RUN" == "true" || "$BACKUP_DRY_RUN" == "yes" ]]; then
  BACKUP_DRY_RUN="1"
else
  BACKUP_DRY_RUN="0"
fi

if [[ "$BACKUP_DRY_RUN" != "1" ]] && ! command -v pg_dump >/dev/null 2>&1; then
  echo "pg_dump is required. Install PostgreSQL client tools first." >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/.runtime/backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
prefix="$BACKUP_DIR/platform-${timestamp}"
db_dump="${prefix}.pgdump"
files_archive="${prefix}-files.tar.gz"
secret_archive="${prefix}-secret-key.tar.gz"
manifest_path="${prefix}-manifest.json"

pg_dump_url="$(
  python - <<'PY'
import os
url = os.environ["DATABASE_URL"]
print(url.replace("postgresql+psycopg://", "postgresql://", 1))
PY
)"

safe_database_url="$(
  python - <<'PY'
import os
from urllib.parse import urlsplit

raw = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
parts = urlsplit(raw)
user = f"{parts.username}@" if parts.username else ""
port = f":{parts.port}" if parts.port else ""
print(f"{parts.scheme}://{user}{parts.hostname or ''}{port}{parts.path}")
PY
)"

if [[ "$BACKUP_DRY_RUN" == "1" ]]; then
  db_dump=""
else
  pg_dump --format=custom --file="$db_dump" "$pg_dump_url"
fi

missing_paths=()
archive_inputs=()
for path in "${LITERATURE_USER_DATA_ROOT:-$ROOT_DIR/.runtime/users}" "${LITERATURE_DATA_DIR:-}"; do
  if [[ -n "$path" && -e "$path" ]]; then
    archive_inputs+=("$path")
  elif [[ -n "$path" ]]; then
    missing_paths+=("$path")
  fi
done

if [[ "$BACKUP_DRY_RUN" == "1" ]]; then
  files_archive=""
elif [[ "${#archive_inputs[@]}" -gt 0 ]]; then
  tar -czf "$files_archive" "${archive_inputs[@]}"
else
  files_archive=""
fi

secret_key_path="${LITERATURE_SECRET_KEY_PATH:-$ROOT_DIR/.runtime/secret.key}"
if [[ "$BACKUP_DRY_RUN" == "1" ]]; then
  if [[ ! -f "$secret_key_path" ]]; then
    missing_paths+=("$secret_key_path")
  fi
  secret_archive=""
elif [[ -f "$secret_key_path" ]]; then
  tar -czf "$secret_archive" "$secret_key_path"
else
  missing_paths+=("$secret_key_path")
  secret_archive=""
fi

retention_deleted=0
while IFS= read -r old_file; do
  rm -f "$old_file"
  retention_deleted=$((retention_deleted + 1))
done < <(find "$BACKUP_DIR" -type f -name "platform-*" -mtime +"$BACKUP_KEEP_DAYS" -print)

if [[ "${#missing_paths[@]}" -gt 0 ]]; then
  missing_json="$(python -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "${missing_paths[@]}")"
else
  missing_json="[]"
fi

cat >"$manifest_path" <<JSON
{
  "manifest": "literature-agent-platform-backup-v1",
  "created_at_utc": "$timestamp",
  "dry_run": $([[ "$BACKUP_DRY_RUN" == "1" ]] && echo true || echo false),
  "safe_database_url": "$safe_database_url",
  "database_dump": "$db_dump",
  "file_archive": "$files_archive",
  "secret_key_archive": "$secret_archive",
  "missing_paths": $missing_json,
  "backup_keep_days": $BACKUP_KEEP_DAYS,
  "retention_deleted": $retention_deleted
}
JSON

if [[ "$BACKUP_DRY_RUN" == "1" ]]; then
  echo "Backup dry run complete:"
else
  echo "Backup complete:"
fi
echo "  manifest: $manifest_path"
if [[ -n "$db_dump" ]]; then
  echo "  database: $db_dump"
else
  echo "  database: dry-run only"
fi
if [[ -n "$files_archive" ]]; then
  echo "  files:    $files_archive"
fi
if [[ -n "$secret_archive" ]]; then
  echo "  key:      $secret_archive"
fi
