from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LightweightRoute:
    kind: str
    label: str


_PUNCT_RE = re.compile(r"[\s。！？!?.,，；;：:、~～]+")


def _compact(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").strip().lower())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    compact = _compact(text)
    lowered = (text or "").lower()
    return any(term.lower() in lowered or _compact(term) in compact for term in terms)


_HELP_TERMS = (
    "你是谁",
    "你是什么",
    "你能做什么",
    "你可以做什么",
    "你会做什么",
    "怎么用",
    "如何使用",
    "使用方法",
    "help",
    "what can you do",
    "who are you",
)
_CASUAL_TERMS = ("你好", "您好", "hello", "hi", "谢谢", "thanks", "ok", "好的")
_ATTACHMENT_TERMS = ("附件", "上传", "pdf", "txt", "file", "document", "文档")
_ATTACHMENT_ACTION_TERMS = ("总结", "概括", "解释", "提取", "翻译", "summarize", "summary", "extract", "translate")
_LITERATURE_TERMS = ("文献", "论文", "检索", "证据", "本地库", "文献库", "literature", "paper", "papers", "evidence")


def classify_lightweight_route(message: str, *, has_attachments: bool = False) -> LightweightRoute:
    text = (message or "").strip()
    compact = _compact(text)
    if not compact:
        return LightweightRoute("plain_chat", "需要更多信息")

    if _contains_any(text, _HELP_TERMS):
        return LightweightRoute("plain_help", "能力说明")

    if compact in {_compact(term) for term in _CASUAL_TERMS}:
        return LightweightRoute("plain_chat", "普通对话")

    if _is_attachment_request(text):
        if _asks_for_literature_combination(text):
            return LightweightRoute("research", "文献检索")
        if has_attachments:
            return LightweightRoute("attachment_only", "读取上传附件")
        return LightweightRoute("attachment_missing", "缺少附件")

    library_kind = _library_status_kind(text)
    if library_kind:
        return LightweightRoute(library_kind, "文献库状态")

    return LightweightRoute("research", "文献检索")


def _is_attachment_request(text: str) -> bool:
    return _contains_any(text, _ATTACHMENT_TERMS) and _contains_any(text, _ATTACHMENT_ACTION_TERMS)


def _asks_for_literature_combination(text: str) -> bool:
    lowered = text.lower()
    combination_terms = ("结合", "补充", "对照", "compare", "with literature", "文献库补充")
    return _contains_any(text, combination_terms) and _contains_any(text, _LITERATURE_TERMS)


def _library_status_kind(text: str) -> str | None:
    if not _contains_any(text, ("文献库", "本地库", "库中", "索引", "导入")):
        return None
    if _contains_any(text, ("最近导入", "最近收录", "新导入", "最新导入")):
        return "library_recent_imports"
    if _contains_any(text, ("主要包含哪些期刊", "主要期刊", "哪些期刊", "期刊分布", "journal")):
        return "library_journal_distribution"
    if _contains_any(text, ("覆盖哪些年份", "年份覆盖", "覆盖年份", "year range", "years")):
        return "library_year_coverage"
    if _contains_any(text, ("完成索引", "已经索引", "索引数量", "索引了多少")):
        return "library_indexed_count"
    if _contains_any(text, ("多少文献", "多少篇文献", "文献总数", "一共有多少", "总共有多少")):
        return "library_count"
    return None
