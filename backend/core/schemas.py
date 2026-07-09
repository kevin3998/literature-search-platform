"""
全平台共用的数据结构。前端和后端通过这些结构"对话"，
新增模块时优先复用这里的结构，保证前端组件可以直接复用。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: float = Field(default_factory=time.time)


class PaperResult(BaseModel):
    """检索 / 分析返回的单篇文献结构。字段尽量贴合常见文献检索 agent 的输出，
    缺失字段前端会自动留空展示，不需要每个字段都有值。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str
    authors: list[str] = []
    year: Optional[int] = None
    venue: Optional[str] = None
    citation_count: Optional[int] = None
    relevance_score: Optional[float] = None  # 0~1
    abstract: Optional[str] = None
    snippet: Optional[str] = None  # 命中的关键片段（用于高亮展示）
    source_path: Optional[str] = None  # 本地文献库中的文件路径
    url: Optional[str] = None
    tags: list[str] = []
    doi: Optional[str] = None
    article_id: Optional[int] = None
    evidence: list[dict[str, Any]] = []
    evidence_summary: Optional[dict[str, Any]] = None
    matched_terms: list[str] = []
    retrieval_sources: list[str] = []


class ModuleInfo(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    status: Literal["active", "beta", "coming_soon"]
    accent: Optional[str] = None


class ChatRequest(BaseModel):
    module_id: str
    session_id: str
    message: str
    history: list[ChatMessage] = []
    options: dict[str, Any] = {}


class LibraryFile(BaseModel):
    name: str
    path: str
    size_kb: Optional[float] = None
    modified: Optional[float] = None
