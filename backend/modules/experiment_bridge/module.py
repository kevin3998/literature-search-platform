from __future__ import annotations

import asyncio
from typing import AsyncIterator

from core.module_base import AgentModule
from core.schemas import ChatMessage


class ExperimentBridgeModule(AgentModule):
    id = "experiment_bridge"
    name = "Experiment Bridge"
    description = "把研究假设转化为可执行的实验方案与验证路径"
    icon = "flask-conical"
    status = "coming_soon"
    accent = "violet"

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
            "Experiment Bridge 模块尚未上线，规划中的能力包括：\n\n"
            "· 把 Idea Discovery 产出的研究假设拆解为可执行的实验步骤\n"
            "· 关联文献中报告过的实验方法与参数，给出可复现的实验方案草稿\n"
            "· 标注方案中依据较弱、需要人工复核的环节\n\n"
            "开发完成后，把本模块状态从 coming_soon 改为 active 即可正式启用。"
        )
        for chunk in text.split(" "):
            await asyncio.sleep(0.01)
            yield {"type": "token", "text": chunk + " "}
        yield {"type": "done"}
