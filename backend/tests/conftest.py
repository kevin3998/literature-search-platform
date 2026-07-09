from __future__ import annotations

import sys

import pytest

from postgres_test_utils import migrated_postgres_schema


STRUCTURED_EXTRACTION_LEGACY_TEST_PREFIX = "test_structured_extraction_"


@pytest.fixture(autouse=True)
def structured_extraction_postgres_schema(request):
    path = request.node.path.name
    if not path.startswith(STRUCTURED_EXTRACTION_LEGACY_TEST_PREFIX):
        yield
        return

    with migrated_postgres_schema():
        _purge_runtime_modules()
        yield
        _purge_runtime_modules()


def _purge_runtime_modules() -> None:
    prefixes = (
        "main",
        "api.settings_router",
        "api.structured_extraction_router",
        "modules.structured_extraction",
        "modules.literature_search.literature_search_shared",
        "modules.literature_search.job_store",
        "modules.literature_search.job_runner",
        "core.session_store",
        "core.secret_store",
        "core.settings_store",
        "core.model_profiles",
        "core.user_store",
    )
    for name in list(sys.modules):
        if name == "main" or any(name.startswith(prefix) for prefix in prefixes if prefix != "main"):
            sys.modules.pop(name, None)
            if "." in name:
                package_name, attribute = name.rsplit(".", 1)
                package = sys.modules.get(package_name)
                if package is not None and hasattr(package, attribute):
                    delattr(package, attribute)
