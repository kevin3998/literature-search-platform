from __future__ import annotations

from typing import AsyncIterator

from core.module_base import AgentModule
from core.schemas import ChatMessage
from core.session_store import session_store
from core.settings_store import settings_store
from core.llm.client import LLMUnavailable, build_llm_client
from modules.literature_search.adapter import REAL_AGENT_AVAILABLE, real_adapter
from modules.literature_search.agent import orchestration as orch
from modules.literature_search.agent.loop import AgentLoop
from modules.literature_search.agent.roles import get_role
from modules.literature_search.agent.tools import ToolRegistry
from modules.literature_search.corpus import CorpusService
from modules.literature_search.failure_messages import failure_message
from modules.literature_search.lightweight_routes import classify_lightweight_route
from modules.literature_search.literature_search_shared import service as shared_service


_FALLBACK_REASON_LABELS = {
    "provider_none": "未配置模型 provider",
    "agent_disabled": "Agent 已在设置中关闭",
    "provider_unsupported": "当前 provider 暂不支持 Agent",
    "missing_chat_model": "未配置 Chat Model",
    "missing_base_url": "缺少 Base URL",
    "missing_api_key": "缺少 API Key",
    "ollama_model_unavailable": "Ollama 中未找到该模型",
    "research_agent_unavailable": "Research Agent 不可用",
}


def _fallback_reason() -> str:
    """Human-readable reason the agent path was skipped, derived from the readiness contract."""
    try:
        reasons = settings_store.readiness().get("reasons") or []
    except Exception:  # noqa: BLE001 - never let diagnostics break the chat path
        return ""
    labels = [_FALLBACK_REASON_LABELS.get(code, code) for code in reasons]
    return "、".join(labels)


class LiteratureSearchModule(AgentModule):
    id = "literature_search"
    name = "文献检索分析"
    description = "基于本地文献库进行语义检索、追问与跨文献分析"
    icon = "library-big"
    status = "active"
    accent = "amber"

    async def handle_chat(
        self,
        session_id: str,
        message: str,
        history: list[ChatMessage],
        options: dict,
    ) -> AsyncIterator[dict]:
        memory_context = options.get("_memory_context") or {}
        attachments_context = options.get("_attachments_context") or []
        attachment_block = _attachments_prompt_block(attachments_context)
        light_route = classify_lightweight_route(message, has_attachments=bool(attachments_context))
        if light_route.kind != "research":
            if light_route.kind.startswith("library_"):
                yield {"type": "intent_route", "route": light_route.kind, "label": light_route.label}
                stats = _quick_stats()
                yield {"type": "library_status", "stats": stats}
                answer = _render_library_status_answer(light_route.kind, stats)
                yield {"type": "token", "text": answer}
                yield {"type": "done"}
                return
            if light_route.kind == "attachment_only":
                yield {"type": "intent_route", "route": light_route.kind, "label": light_route.label}
                yield {
                    "type": "attachment_context",
                    "attachment_count": len(attachments_context),
                    "filenames": [item.get("filename") or "附件" for item in attachments_context],
                }
                async for event in self._run_attachment_only_chat(message, attachments_context):
                    yield event
                yield {"type": "done"}
                return
            if light_route.kind == "attachment_missing":
                message_text = failure_message("attachment_missing")
                yield {"type": "intent_route", "route": light_route.kind, "label": light_route.label}
                yield {"type": "failure_explanation", "code": "attachment_missing", "message": message_text}
                yield {"type": "token", "text": message_text}
                yield {"type": "done"}
                return
            if light_route.kind == "plain_help":
                yield {"type": "intent_route", "route": light_route.kind, "label": light_route.label}
                if settings_store.llm_enabled():
                    try:
                        async for event in self._run_plain_chat(message, history, attachments_context):
                            yield event
                    except LLMUnavailable:
                        yield {"type": "token", "text": _plain_help_answer(message)}
                else:
                    yield {"type": "token", "text": _plain_help_answer(message)}
                yield {"type": "done"}
                return
            if light_route.kind == "plain_chat":
                yield {"type": "intent_route", "route": light_route.kind, "label": light_route.label}
                if settings_store.llm_enabled():
                    try:
                        async for event in self._run_plain_chat(message, history, attachments_context):
                            yield event
                    except LLMUnavailable:
                        yield {"type": "token", "text": _plain_chat_answer(message)}
                    except Exception as exc:  # noqa: BLE001 - keep the stream explicit
                        yield {"type": "error", "message": f"普通对话失败：{exc}"}
                else:
                    yield {"type": "token", "text": _plain_chat_answer(message)}
                yield {"type": "done"}
                return

        route = orch.route_chat_intent(
            message,
            has_history=bool(history),
            has_recent_evidence=bool(memory_context.get("recent_evidence")),
        )
        if not route.should_enter_research:
            yield {"type": "intent_route", "route": "plain_chat", "label": "普通对话"}
            try:
                async for event in self._run_plain_chat(message, history, attachments_context):
                    yield event
            except LLMUnavailable as exc:
                yield {"type": "error", "message": f"普通对话模型不可用：{exc}"}
            except Exception as exc:  # noqa: BLE001 - keep the stream explicit
                yield {"type": "error", "message": f"普通对话失败：{exc}"}
            yield {"type": "done"}
            return

        yield {"type": "intent_route", "route": "research", "label": "文献检索问答"}

        # Research QA is LLM-assisted by design. If the model/agent is unavailable,
        # block with a readable diagnostic instead of fabricating a local summary.
        if not REAL_AGENT_AVAILABLE or real_adapter is None or not settings_store.llm_enabled():
            message_text = failure_message("llm_required_for_research")
            reason = _fallback_reason()
            if reason:
                message_text = f"{message_text}\n\n当前阻塞原因：{reason}。"
            yield {"type": "failure_explanation", "code": "llm_required_for_research", "message": message_text}
            yield {"type": "token", "text": message_text}
            yield {"type": "done"}
            return

        try:
            async for event in self._run_agent(session_id, message, history, options):
                yield event
            yield {"type": "done"}
            return
        except LLMUnavailable as exc:
            message_text = f"{failure_message('llm_required_for_research')}\n\n当前阻塞原因：{exc}。"
            yield {"type": "failure_explanation", "code": "llm_required_for_research", "message": message_text}
            yield {"type": "token", "text": message_text}
            yield {"type": "done"}
            return
        except Exception as exc:  # noqa: BLE001 - keep stream readable
            message_text = f"{failure_message('llm_runtime_unavailable')}\n\n{_llm_runtime_detail(exc)}"
            yield {"type": "failure_explanation", "code": "llm_runtime_unavailable", "message": message_text}
            yield {"type": "token", "text": message_text}
            yield {"type": "done"}
            return

    async def _run_agent(
        self,
        session_id: str,
        message: str,
        history: list[ChatMessage],
        options: dict,
    ) -> AsyncIterator[dict]:
        # ToolRegistry persists search results itself; tell chat_router not to
        # record the forwarded `papers` events a second time.
        options["_agent_records_search"] = True
        agent_cfg = settings_store.agent_config()
        # Block 6c: a specialist role (explicit capability button) gates the tool
        # set + prepends a role prompt + can force deep tools. The general role
        # (free-form chat) leaves the pre-6c behaviour untouched.
        role = get_role(options.get("role"))
        # A per-turn research intent ("快速回答 / 深度研究") overrides the stored
        # default; deep mode is what exposes the job tools (run/task_run/...).
        # A role with a fixed mode (analysis/synthesis/report need deep) wins.
        requested_mode = options.get("answer_mode")
        answer_mode = requested_mode if requested_mode in {"quick", "deep"} else agent_cfg["answer_mode"]
        if role.mode in {"quick", "deep"}:
            answer_mode = role.mode
        llm = build_llm_client(settings_store)
        registry = ToolRegistry(
            real_adapter.service,
            session_store,
            session_id=session_id,
            turn_id=options.get("_turn_id"),
            answer_mode=answer_mode,
            has_history=bool(history),
            role_tools=role.tools,
            original_question=message,
        )
        loop = AgentLoop(
            llm,
            registry,
            max_iterations=agent_cfg["max_tool_iterations"],
            tool_budget=agent_cfg["tool_budget"],
            enforce_citations=agent_cfg["enforce_citations"],
            grounding_mode=agent_cfg["grounding_mode"],
            role_prompt=role.prompt,
        )
        hist = [h.model_dump() if hasattr(h, "model_dump") else dict(h) for h in history]
        async for event in loop.run(message, hist, options.get("_memory_context")):
            yield event

    async def _run_plain_chat(
        self,
        message: str,
        history: list[ChatMessage],
        attachments_context: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        llm = build_llm_client(settings_store)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是文献研究工作台中的普通对话助手。当前用户输入不是文献检索或证据分析任务，"
                    "因此不要调用工具、不要声称检索了本地文献、不要生成引用或证据审计。"
                    "自然、简洁地回应用户；如果用户在发泄或表达困惑，先承认问题并说明可以继续澄清。"
                ),
            }
        ]
        attachment_block = _attachments_prompt_block(attachments_context)
        if attachment_block:
            messages.append({"role": "system", "content": attachment_block})
        for turn in history[-8:]:
            data = turn.model_dump() if hasattr(turn, "model_dump") else dict(turn)
            role = data.get("role")
            content = data.get("content")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})
        async for delta in llm.stream_chat(messages, None):
            if delta.get("type") == "content" and delta.get("text"):
                yield {"type": "token", "text": delta["text"]}

    async def _run_attachment_only_chat(
        self,
        message: str,
        attachments_context: list[dict],
    ) -> AsyncIterator[dict]:
        attachment_block = _attachments_prompt_block(attachments_context)
        try:
            llm = build_llm_client(settings_store)
        except LLMUnavailable:
            yield {"type": "token", "text": "附件已解析，但当前模型不可用，无法生成总结。"}
            return
        messages = [
            {
                "role": "system",
                "content": (
                    "你正在回答会话级临时附件问题。只能基于用户上传附件内容回答；"
                    "不要检索文献库，不要生成 [E#] 引用。使用中文，并用“来自上传附件《文件名》”标明来源。"
                ),
            },
            {"role": "system", "content": attachment_block},
            {"role": "user", "content": message},
        ]
        async for delta in llm.stream_chat(messages, None):
            if delta.get("type") == "content" and delta.get("text"):
                yield {"type": "token", "text": delta["text"]}


def _attachments_prompt_block(attachments_context: list[dict] | None) -> str:
    if not attachments_context:
        return ""
    lines = [
        "以下是用户上传的会话临时附件。它们不是本地文献库证据，也不能写成 [E#] 引用；",
        "如果回答使用其中内容，请用“来自上传附件《文件名》”这样的中文来源标记。",
    ]
    for item in attachments_context[:5]:
        filename = item.get("filename") or "附件"
        text = (item.get("text") or item.get("text_preview") or "")[:2400]
        lines.append(f"\n来自上传附件《{filename}》:\n{text}")
    return "\n".join(lines)


def _question_with_attachments(message: str, attachment_block: str) -> str:
    if not attachment_block:
        return message
    return f"{message}\n\n{attachment_block}"


def _quick_stats() -> dict:
    return CorpusService(shared_service).quick_stats()


def _no_candidate_failure(query: str) -> tuple[str, str]:
    try:
        stats = _quick_stats()
    except Exception:  # noqa: BLE001 - failure explanation must not break chat
        stats = {}
    if stats.get("index_available") and int(stats.get("paper_count") or 0) > 0:
        code = "library_not_empty_but_no_query_hit"
    elif stats.get("index_available") is False:
        code = "empty_or_unavailable_corpus"
    else:
        code = "no_candidate_papers"
    return code, failure_message(code, query=query)


def _llm_runtime_detail(exc: Exception) -> str:
    text = str(exc)
    import re

    model = re.search(r"model ['\"]([^'\"]+)['\"] not found", text, flags=re.IGNORECASE)
    if model:
        return f"当前配置的模型 `{model.group(1)}` 不可用或未安装。请在设置中切换到可用模型后重试。"
    if "404" in text and "not_found" in text.lower():
        return "当前模型服务返回未找到模型。请检查模型名称、服务商和 Base URL 配置。"
    return "请检查模型服务、模型名称、Base URL 和 API Key 配置。"


def _fmt_int(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _boundary_note() -> str:
    return "\n\n说明：这是当前本地文献库统计，不是外部全网文献统计。"


def _render_library_status_answer(kind: str, stats: dict) -> str:
    if not stats.get("index_available"):
        return failure_message("empty_or_unavailable_corpus")
    if kind == "library_count":
        return (
            f"当前本地文献库中共有 {_fmt_int(stats.get('paper_count'))} 篇文献。"
            f"同时，索引表中有 {_fmt_int(stats.get('article_index_count'))} 条 article index 记录，"
            f"已解析章节约 {_fmt_int(stats.get('section_count'))} 条，文本块约 {_fmt_int(stats.get('chunk_count'))} 条。"
            + _boundary_note()
        )
    if kind == "library_indexed_count":
        return (
            f"当前已完成索引的文献记录约为 {_fmt_int(stats.get('paper_count'))} 篇；"
            f"article_index 表中有 {_fmt_int(stats.get('article_index_count'))} 条记录。"
            "两者口径不同：papers 更接近可用于文献检索的规范化论文数，article_index 是底层索引条目数。"
            + _boundary_note()
        )
    if kind == "library_year_coverage":
        years = stats.get("year_range") or [None, None]
        top = "、".join(f"{item['year']} 年（{_fmt_int(item['count'])} 篇）" for item in (stats.get("top_years") or [])[:5])
        range_text = f"{years[0]}-{years[1]}" if years[0] and years[1] else "暂无可靠年份统计"
        return f"当前本地文献库的可统计年份覆盖范围是 {range_text}。主要年份分布：{top or '暂无'}。" + _boundary_note()
    if kind == "library_journal_distribution":
        journals = stats.get("top_journals") or []
        lines = [f"{i}. {item['journal']}：{_fmt_int(item['count'])} 篇" for i, item in enumerate(journals[:8], start=1)]
        return "当前本地文献库的主要期刊包括：\n\n" + "\n".join(lines or ["暂无可靠期刊统计。"]) + _boundary_note()
    if kind == "library_recent_imports":
        imports = stats.get("recent_imports") or []
        lines = []
        for item in imports[:8]:
            title = item.get("title") or item.get("doi") or item.get("paper_id")
            extra = "，".join(str(x) for x in (item.get("year"), item.get("journal"), item.get("indexed_at")) if x)
            lines.append(f"- {title}" + (f"（{extra}）" if extra else ""))
        return "最近导入或更新的文献包括：\n\n" + "\n".join(lines or ["暂无可靠导入时间记录。"]) + _boundary_note()
    return "当前文献库状态已读取。" + _boundary_note()


def _plain_help_answer(message: str) -> str:
    lowered = (message or "").lower()
    if any(ch in lowered for ch in ("what can you do", "who are you", "help")):
        return (
            "I can help with local literature search, library status questions, evidence-grounded Q&A, "
            "citation/audit review, and session-level attachment summaries. For research questions, I use the local library; "
            "for uploaded files, I treat them as temporary session context rather than library evidence."
        )
    return (
        "我是文献智能体平台里的文献检索助手。你可以让我查询本地文献库状态、检索论文、整理证据、检查引用，"
        "也可以上传 txt/pdf 附件让我基于当前会话材料做总结。附件只服务当前会话，不会写入文献库。"
    )


def _plain_chat_answer(message: str) -> str:
    compact = (message or "").strip().lower()
    if compact in {"hello", "hi"}:
        return "Hello! I can help with literature search, evidence review, and local library questions."
    if "thank" in compact:
        return "不客气。"
    return "你好！你可以直接问我文献检索、证据分析、文献库状态，或上传附件让我基于当前会话总结。"
