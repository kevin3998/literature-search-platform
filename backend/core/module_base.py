"""
=========================================================================
 模块统一接口（核心扩展点）
=========================================================================
AgentModule 表示普通对话 / workbench 模块，例如 Literature Search。结构化
Research Workflows 不再作为 AgentModule 注册，而是通过 /api/workflows 和
research_agent_controller 受控执行。

新增一个模块的步骤（拿 idea_discovery 抄一份即可）：
  1. 在 backend/modules/ 下新建一个包，写一个类继承 AgentModule
  2. 实现 handle_chat()，按需 yield step / papers / token / done 事件
  3. 在 backend/modules/__init__.py 里 registry.register(YourModule())
完成后，GET /api/modules 会返回该模块；是否进入产品主导航由前端信息架构显式决定。
=========================================================================
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.schemas import ChatMessage, ModuleInfo


class AgentModule(ABC):
    id: str
    name: str
    description: str
    icon: str = "flask-conical"
    status: str = "active"  # active | beta | coming_soon
    accent: str | None = None

    def info(self) -> ModuleInfo:
        return ModuleInfo(
            id=self.id,
            name=self.name,
            description=self.description,
            icon=self.icon,
            status=self.status,  # type: ignore[arg-type]
            accent=self.accent,
        )

    @abstractmethod
    async def handle_chat(
        self,
        session_id: str,
        message: str,
        history: list[ChatMessage],
        options: dict,
    ) -> AsyncIterator[dict]:
        """处理一轮对话，以 async generator 形式逐步 yield 事件字典。

        约定的事件类型（type 字段）：
          - {"type": "step", "status": "running|done|error", "label": str, "detail"?: str}
                展示 agent 当前在做什么（检索中/重排序中/分析中…），
                会在前端渲染成一条条"日志"，让用户看到 agent 的中间过程。
          - {"type": "papers", "papers": [PaperResult.model_dump(), ...]}
                结构化的文献结果，前端会渲染成右侧的文献卡片列表。
          - {"type": "token", "text": str}
                最终回答的流式文本片段（实现打字机效果）。
          - {"type": "done"}
                本轮结束。
          - {"type": "error", "message": str}
                出错时使用，前端会用醒目样式展示。
        """
        raise NotImplementedError
