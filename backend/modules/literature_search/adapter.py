"""
=========================================================================
 把你已经实现的文献检索 / 分析 agent 接到这里
=========================================================================
这是整个项目里唯一"必须"由你来改的文件。把下面 import 的部分换成你自己
模块里真实的函数 / 类，上层 module.py 不需要再动。

两种典型接入方式，选你方便的一种即可：

【方式 A】你的 agent 拆成"检索"和"分析/问答"两个函数
    search(query, top_k, filters) -> list[dict]
    analyze(question, paper_ids, history) -> str | AsyncIterator[str]
    -> 实现 RealAgentAdapter.search / analyze 即可

【方式 B】你的 agent 是一个"自己决定先检索再回答"的单一入口
    run(query, history) -> str | AsyncIterator[str]
    -> 实现 RealAgentAdapter.chat 即可，module.py 会优先调用它

字段说明（PaperResult，全部可选，缺的字段前端会自动留空）：
    id, title, authors(list[str]), year(int), venue(str),
    citation_count(int), relevance_score(float 0~1),
    abstract(str), snippet(str, 命中片段), source_path(str, 本地文件路径), url(str)
=========================================================================
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

try:
    from modules.literature_search.service import LiteratureResearchService

    _service = LiteratureResearchService()
    REAL_AGENT_AVAILABLE = True
except Exception as exc:  # noqa: BLE001 - keep mock fallback usable if local agent is absent
    _service = None
    REAL_AGENT_AVAILABLE = False
    REAL_AGENT_IMPORT_ERROR = str(exc)


class RealAgentAdapter:
    """真实 agent 的适配器。把下面方法里的 TODO 换成真实调用即可。"""

    def __init__(self) -> None:
        if _service is None:
            raise RuntimeError(globals().get("REAL_AGENT_IMPORT_ERROR", "research agent is unavailable"))
        self.service = _service
        self.last_search_payload: dict | None = None

    async def search(
        self, query: str, top_k: int = 8, filters: Optional[dict] = None
    ) -> list[dict]:
        options = dict(filters or {})
        try:
            from core.settings_store import settings_store

            defaults = settings_store.retrieval_defaults()
            options = {**defaults, **{key: value for key, value in options.items() if value is not None}}
        except Exception:
            pass
        options["limit"] = options.get("limit") or top_k
        payload = await _to_thread(self.service.search, query, **options)
        self.last_search_payload = payload
        return self.service.to_chat_papers(payload)

    async def analyze(
        self, question: str, paper_ids: Optional[list[str]], history: list[dict]
    ) -> AsyncIterator[str]:
        papers = self.service.to_chat_papers(self.last_search_payload or {"results": []})
        answer = self.service.answer_from_search(question, papers, self.last_search_payload)
        for chunk in _chunk(answer):
            yield chunk

    async def chat(self, message: str, history: list[dict]) -> AsyncIterator[str]:
        papers = await self.search(message)
        async for chunk in self.analyze(message, [p.get("id") for p in papers], history):
            yield chunk


real_adapter: Optional[RealAgentAdapter] = RealAgentAdapter() if REAL_AGENT_AVAILABLE else None


async def _to_thread(func, *args, **kwargs):
    import asyncio

    return await asyncio.to_thread(func, *args, **kwargs)


def _chunk(text: str, size: int = 28):
    for index in range(0, len(text), size):
        yield text[index : index + size]
