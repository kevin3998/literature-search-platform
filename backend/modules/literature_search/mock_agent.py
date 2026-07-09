"""
演示用的假数据 / 假延迟，让前端在真实 agent 接入前也能跑通完整交互链路。
一旦 adapter.py 里的 REAL_AGENT_AVAILABLE 为 True，这里就不会再被调用。
"""
from __future__ import annotations

import asyncio
import random

_MOCK_LIBRARY = [
    dict(
        title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        authors=["P. Lewis", "E. Perez", "A. Piktus"],
        year=2020,
        venue="NeurIPS",
        citation_count=4821,
        abstract="提出将参数化语言模型与非参数化检索记忆相结合的 RAG 框架，在开放域问答等知识密集型任务上显著提升事实准确性。",
        tags=["RAG", "检索增强"],
    ),
    dict(
        title="A Survey of Large Language Models for Scientific Literature Mining",
        authors=["Y. Zhang", "S. Chen"],
        year=2023,
        venue="ACL Findings",
        citation_count=312,
        abstract="系统综述了 LLM 在文献挖掘、实体抽取、跨文献综合等场景中的方法与局限，并指出本地化部署在数据隐私上的优势。",
        tags=["综述", "文献挖掘"],
    ),
    dict(
        title="Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        authors=["A. Asai", "Z. Wu", "Y. Wang"],
        year=2023,
        venue="ICLR",
        citation_count=587,
        abstract="引入反思 token 让模型自主判断何时检索、检索什么、以及对生成内容进行自我批判，减少幻觉。",
        tags=["RAG", "自我反思"],
    ),
    dict(
        title="From Literature Review to Hypothesis: An Agent-based Pipeline for Scientific Discovery",
        authors=["L. Romero", "K. Tanaka"],
        year=2024,
        venue="arXiv preprint",
        citation_count=41,
        abstract="构建了一条从文献综述自动生成可验证科学假设的 agent 流水线，强调检索结果的可追溯性与人工复核环节。",
        tags=["Idea Discovery", "假设生成"],
    ),
    dict(
        title="Towards Reproducible Experiment Design with LLM-assisted Protocol Generation",
        authors=["M. Okafor", "H. Lindqvist"],
        year=2024,
        venue="Nature Methods (Correspondence)",
        citation_count=18,
        abstract="探讨利用 LLM 辅助生成可复现实验方案的方法，并讨论与现有实验室信息管理系统（LIMS）对接的挑战。",
        tags=["实验设计", "Experiment Bridge"],
    ),
]


def _score(query: str, paper: dict) -> float:
    q = query.lower()
    hay = (paper["title"] + " " + paper["abstract"] + " ".join(paper["tags"])).lower()
    overlap = sum(1 for w in q.split() if w in hay)
    base = min(0.5 + overlap * 0.12, 0.97)
    return round(base + random.uniform(-0.03, 0.03), 2)


async def mock_search(query: str, top_k: int = 5) -> list[dict]:
    await asyncio.sleep(0.5)
    ranked = sorted(_MOCK_LIBRARY, key=lambda p: _score(query, p), reverse=True)
    results = []
    for i, p in enumerate(ranked[:top_k]):
        item = dict(p)
        item["id"] = f"mock-{i}"
        item["relevance_score"] = _score(query, p)
        item["snippet"] = p["abstract"][:60] + "…"
        item["source_path"] = f"/library/{p['title'][:24].replace(' ', '_')}.pdf"
        results.append(item)
    return results


async def mock_answer(query: str, papers: list[dict]):
    titles = "、".join(f"《{p['title'][:38]}》" for p in papers[:3])
    text = (
        f"基于本地文献库中检索到的 {len(papers)} 篇相关文献，与「{query}」最相关的是 {titles} 等。\n\n"
        "这些文献的共同结论是：检索增强（RAG）类方法能有效降低生成内容的事实性错误，"
        "而将其用于科研场景时，关键挑战在于检索结果的可追溯性与跨文献观点的一致性核验。\n\n"
        "（提示：当前为演示数据。将 backend/modules/literature_search/adapter.py 中的 "
        "REAL_AGENT_AVAILABLE 接入你的真实 agent 后，这里会替换为真实分析结果。）"
    )
    for chunk in text.split(" "):
        await asyncio.sleep(0.02)
        yield chunk + " "
