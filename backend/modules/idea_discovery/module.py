"""
这是一个"占位/即将上线"模块的示例。它说明了新增模块的完整套路：
继承 AgentModule -> 实现 handle_chat -> 在 modules/__init__.py 注册。
等真正开发该环节时，把 handle_chat 里的内容换成真实逻辑即可，
status 改成 "active"，前端会自动从"即将上线"变为可正常使用。
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from core.module_base import AgentModule
from core.schemas import ChatMessage


class IdeaDiscoveryModule(AgentModule):
    id = "idea_discovery"
    name = "Idea Discovery"
    description = "从已检索文献中挖掘研究空白、生成可验证的研究假设"
    icon = "lightbulb"
    status = "coming_soon"
    accent = "teal"

    async def handle_chat(
        self,
        session_id: str,
        message: str,
        history: list[ChatMessage],
        options: dict,
    ) -> AsyncIterator[dict]:
        yield {"type": "step", "status": "running", "label": "规划中的能力"}
        await asyncio.sleep(0.3)
        yield {"type": "step", "status": "done", "label": "规划中的能力"}
        text = (
            "Idea Discovery 模块尚未上线，规划中的能力包括：\n\n"
            "· 基于「文献检索分析」沉淀的文献集合，自动识别研究空白\n"
            "· 对同主题的多篇文献进行立场/方法对比，找出尚未被验证的方向\n"
            "· 生成可追溯到具体文献依据的候选研究假设\n\n"
            "开发完成后，只需把本模块状态从 coming_soon 改为 active 即可正式启用。"
        )
        for chunk in text.split(" "):
            await asyncio.sleep(0.01)
            yield {"type": "token", "text": chunk + " "}
        yield {"type": "done"}
