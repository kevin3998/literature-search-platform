from __future__ import annotations

import asyncio

from core.schemas import ChatMessage


def _collect(module, message: str, *, attachments=None):
    options = {}
    if attachments:
        options["_attachments_context"] = attachments
    return asyncio.run(_collect_async(module.handle_chat("s1", message, [], options)))


async def _collect_async(stream):
    events = []
    async for event in stream:
        events.append(event)
    return events


def _text(events):
    return "".join(event.get("text", "") for event in events if event.get("type") == "token")


def _event(events, event_type: str):
    return next((event for event in events if event.get("type") == event_type), None)


def test_library_count_answer_uses_quick_stats(monkeypatch) -> None:
    from modules.literature_search.module import LiteratureSearchModule

    monkeypatch.setattr(
        "modules.literature_search.module._quick_stats",
        lambda: {
            "index_available": True,
            "paper_count": 147371,
            "article_index_count": 147372,
            "section_count": 2911107,
            "chunk_count": 4979646,
            "year_range": [2010, 2026],
            "top_years": [],
            "top_journals": [],
            "recent_imports": [],
            "vector_built": False,
        },
    )

    events = _collect(LiteratureSearchModule(), "当前文献库中一共有多少文献？")
    answer = _text(events)

    assert "147,371" in answer or "147371" in answer
    assert "本地文献库统计" in answer
    assert not any(event.get("type") == "citation" for event in events)
    assert not any(event.get("type") == "papers" for event in events)


def test_plain_help_does_not_emit_citation() -> None:
    from modules.literature_search.module import LiteratureSearchModule

    events = _collect(LiteratureSearchModule(), "What can you do?")
    answer = _text(events)

    assert _event(events, "intent_route") == {"type": "intent_route", "route": "plain_help", "label": "能力说明"}
    assert "literature" in answer.lower() or "文献" in answer
    assert "证据不足" not in answer
    assert not any(event.get("type") == "citation" for event in events)


def test_plain_chat_emits_route_metadata_without_retrieval(monkeypatch) -> None:
    from modules.literature_search.module import LiteratureSearchModule

    monkeypatch.setattr("modules.literature_search.module.settings_store.llm_enabled", lambda: False)

    events = _collect(LiteratureSearchModule(), "你好")
    answer = _text(events)

    assert _event(events, "intent_route") == {"type": "intent_route", "route": "plain_chat", "label": "普通对话"}
    assert "你好" in answer
    assert not any(event.get("type") == "papers" for event in events)
    assert not any(event.get("type") == "citation" for event in events)


def test_attachment_only_answer_uses_uploaded_material(monkeypatch) -> None:
    from modules.literature_search.module import LiteratureSearchModule

    class _LLM:
        async def stream_chat(self, messages, tools):
            yield {"type": "content", "text": "来自上传附件《note.txt》：附件讨论了钙钛矿稳定性。"}

    monkeypatch.setattr("modules.literature_search.module.build_llm_client", lambda settings: _LLM())
    attachments = [{"filename": "note.txt", "text": "主题：钙钛矿稳定性。"}]

    events = _collect(LiteratureSearchModule(), "请总结我上传的附件，不需要检索外部文献。", attachments=attachments)
    answer = _text(events)

    assert "来自上传附件《note.txt》" in answer
    assert "[E" not in answer
    assert not any(event.get("type") == "citation" for event in events)


def test_attachment_missing_returns_readable_message() -> None:
    from modules.literature_search.module import LiteratureSearchModule

    events = _collect(LiteratureSearchModule(), "请总结我上传的附件，不需要检索外部文献。")
    answer = _text(events)

    assert "当前会话没有可用附件" in answer
    assert not any(event.get("type") == "citation" for event in events)


def test_no_evidence_message_distinguishes_query_miss_from_empty_library() -> None:
    from modules.literature_search.agent.grounding import NOT_ANSWERABLE_MESSAGE

    assert "不表示文献库为空" in NOT_ANSWERABLE_MESSAGE
    assert "没有可用的文献记录" not in NOT_ANSWERABLE_MESSAGE


def test_research_requires_llm_when_model_is_disabled(monkeypatch) -> None:
    from modules.literature_search import module as lit_module
    from modules.literature_search.module import LiteratureSearchModule

    class _Adapter:
        async def search(self, message, top_k=5, filters=None):
            raise AssertionError("research QA must not use local retrieval summary when LLM is disabled")

    monkeypatch.setattr(lit_module, "REAL_AGENT_AVAILABLE", True)
    monkeypatch.setattr(lit_module, "real_adapter", _Adapter())
    monkeypatch.setattr("modules.literature_search.module.settings_store.llm_enabled", lambda: False)

    events = _collect(LiteratureSearchModule(), "文献库里有没有关于量子香蕉电池的论文？")

    route = _event(events, "intent_route")
    assert route == {"type": "intent_route", "route": "research", "label": "文献检索问答"}
    failure = _event(events, "failure_explanation")
    assert failure is not None
    assert failure["code"] == "llm_required_for_research"
    assert "需要可用 LLM" in failure["message"]
    assert "需要可用 LLM" in _text(events)
    assert not any(event.get("type") == "papers" for event in events)
    assert not any(event.get("type") == "error" for event in events)


def test_attachment_plus_research_requires_llm_without_search_fallback(monkeypatch) -> None:
    from modules.literature_search import module as lit_module
    from modules.literature_search.module import LiteratureSearchModule

    class _Adapter:
        async def search(self, message, top_k=5, filters=None):
            raise AssertionError("attachment+literature turns must not use local retrieval summary when LLM is disabled")

    monkeypatch.setattr(lit_module, "REAL_AGENT_AVAILABLE", True)
    monkeypatch.setattr(lit_module, "real_adapter", _Adapter())
    monkeypatch.setattr("modules.literature_search.module.settings_store.llm_enabled", lambda: False)
    attachments = [{"filename": "note.txt", "text": "附件讨论了钙钛矿稳定性。"}]

    events = _collect(LiteratureSearchModule(), "请先总结附件内容，再结合文献库补充相关研究。", attachments=attachments)

    assert _event(events, "intent_route") == {"type": "intent_route", "route": "research", "label": "文献检索问答"}
    failure = _event(events, "failure_explanation")
    assert failure is not None
    assert failure["code"] == "llm_required_for_research"
    assert "需要可用 LLM" in _text(events)
    assert not any(event.get("type") == "papers" for event in events)
    assert not any(event.get("type") == "search_meta" for event in events)
    assert not any(event.get("type") == "citation" for event in events)


def test_research_agent_runtime_error_blocks_without_local_retrieval_summary(monkeypatch) -> None:
    from modules.literature_search import module as lit_module
    from modules.literature_search.module import LiteratureSearchModule

    class _Adapter:
        service = object()

    async def failing_agent(self, session_id, message, history, options):
        raise RuntimeError("model 'llama3.1' not found")
        yield  # pragma: no cover

    monkeypatch.setattr(lit_module, "REAL_AGENT_AVAILABLE", True)
    monkeypatch.setattr(lit_module, "real_adapter", _Adapter())
    monkeypatch.setattr("modules.literature_search.module.settings_store.llm_enabled", lambda: True)
    monkeypatch.setattr(LiteratureSearchModule, "_run_agent", failing_agent)

    events = _collect(LiteratureSearchModule(), "What papers discuss Martian soil simulants for building materials?")

    assert _event(events, "intent_route") == {"type": "intent_route", "route": "research", "label": "文献检索问答"}
    failure = _event(events, "failure_explanation")
    assert failure is not None
    assert failure["code"] == "llm_runtime_unavailable"
    assert "模型调用失败" in failure["message"]
    assert "llama3.1" in failure["message"]
    assert not any(event.get("type") == "papers" for event in events)
    assert "本地检索摘要" not in _text(events)
    assert not any(event.get("type") == "error" for event in events)
