from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any


def new_uuid() -> str:
    return str(uuid.uuid4())


def uuid_value(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_unix_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return None


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def json_loads(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, bool, int, float)):
        return value
    if value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return value if isinstance(value, str) else default
