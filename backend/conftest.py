"""Pytest bootstrap: isolate the memory database before any test imports run.

Several modules (``core.settings_store``, ``core.session_store``) create a
module-level singleton bound to ``LITERATURE_MEMORY_DB_PATH`` at import time.
pytest imports the test modules — and their import chains — during collection,
which happens before any test fixture runs. Without this, the singletons would
bind to (and read/write) the developer's real ``platform_memory.sqlite``,
leaking real data into assertions and vice versa.

Setting the env var here, at conftest import (which pytest loads before
collecting tests), guarantees every singleton binds to a throwaway path.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.gettempdir())
_MEMORY_DB = _TMP / "literature_agent_test_memory.sqlite"
_SECRET_KEY = _TMP / "literature_agent_test_secret.key"
_SECRET_STORE = _TMP / "literature_agent_test_secrets.enc"

# Module-level singletons bind these paths at import; per-test monkeypatching of
# the env can't rebind them, so state written through the singletons persists in
# these shared files across runs. Clear them at session start for a clean slate.
for _stale in (_MEMORY_DB, _SECRET_KEY, _SECRET_STORE):
    for _suffix in ("", "-wal", "-shm"):
        try:
            Path(str(_stale) + _suffix).unlink()
        except FileNotFoundError:
            pass

# setdefault so an explicit override in the environment still wins.
os.environ.setdefault("LITERATURE_MEMORY_DB_PATH", str(_MEMORY_DB))
# Keep the encrypted secret store out of the developer's real ~/.literature-agent.
os.environ.setdefault("LITERATURE_SECRET_KEY_PATH", str(_SECRET_KEY))
os.environ.setdefault("LITERATURE_SECRET_STORE_PATH", str(_SECRET_STORE))
