from __future__ import annotations

from core.module_base import AgentModule


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, AgentModule] = {}

    def register(self, module: AgentModule) -> AgentModule:
        if module.id in self._modules:
            raise ValueError(f"模块 id 重复: {module.id}")
        self._modules[module.id] = module
        return module

    def get(self, module_id: str) -> AgentModule | None:
        return self._modules.get(module_id)

    def list(self):
        return [m.info() for m in self._modules.values()]


registry = ModuleRegistry()
