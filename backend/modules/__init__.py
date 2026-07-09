"""Platform module registration helpers.

Importing the ``modules`` package must stay side-effect free so subpackage
imports such as ``modules.research_agent_controller`` do not initialize the
SQLite-backed chat/session runtime. The FastAPI app calls
``register_builtin_modules()`` explicitly during startup.
"""
from __future__ import annotations

from core.registry import registry


def register_builtin_modules() -> None:
    """Register chat/workbench modules for the API runtime.

    Imports are intentionally inside this function because the literature
    module imports the session store, which initializes SQLite. Controller
    schema and smoke-test imports should not trigger that runtime path.

    Research Workflows are now exposed through ``/api/workflows`` and the
    ``research_agent_controller`` execution layer, not as chat modules.
    """
    from modules.literature_search.module import LiteratureSearchModule

    _register_once(LiteratureSearchModule())


def _register_once(module) -> None:
    if registry.get(module.id) is None:
        registry.register(module)


__all__ = ["register_builtin_modules"]

# 未来新增模块示例：
# from modules.your_new_module.module import YourNewModule
# _register_once(YourNewModule())
