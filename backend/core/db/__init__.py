"""PostgreSQL infrastructure for the platform business database.

M1 intentionally provides no SQLite fallback. The existing ``core.memory_db``
module is legacy until later milestones migrate the business stores.
"""

from .config import DatabaseConfigError, database_schema, database_url
from .engine import create_engine_from_env, engine_for_url

__all__ = [
    "DatabaseConfigError",
    "create_engine_from_env",
    "database_schema",
    "database_url",
    "engine_for_url",
]
