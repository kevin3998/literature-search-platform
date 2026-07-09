from modules import register_builtin_modules
from core.registry import registry


def test_builtin_modules_register_only_literature_search_by_default() -> None:
    original = dict(registry._modules)
    registry._modules.clear()
    try:
        register_builtin_modules()
        modules = registry.list()
    finally:
        registry._modules.clear()
        registry._modules.update(original)

    assert [module.id for module in modules] == ["literature_search"]
