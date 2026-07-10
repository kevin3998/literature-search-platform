from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest
from sqlalchemy import text

from core.llm.client import LLMClient, LLMUnavailable, build_llm_client
from modules.literature_search.agent.loop import AgentLoop
from modules.literature_search.agent import tool_errors as te
from modules.literature_search.agent.tools import ToolResult
from modules.literature_search.agent.tools import ToolRegistry

TEST_USER_ID = "00000000-0000-4000-8000-000000000101"


@pytest.fixture(autouse=True)
def _isolate_memory_db(tmp_path, monkeypatch):
    # Pin the shared memory-db singletons to a throwaway path so these tests never
    # bind (and read) the developer's real platform_memory.sqlite, which would
    # also leak stale state into later test files.
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "singleton.sqlite"))


def _ensure_test_user(store) -> str:
    with store.engine.begin() as conn:
        conn.execute(
            text(
                """
                insert into users(user_id, display_name, status, metadata_json, created_at, updated_at, role)
                values(:user_id, 'Agent Test User', 'active', '{}'::jsonb, now(), now(), 'admin')
                on conflict(user_id) do update
                set status = 'active', role = 'admin', updated_at = now()
                """
            ),
            {"user_id": TEST_USER_ID},
        )
    return TEST_USER_ID


class ScriptedLLM(LLMClient):
    """Returns a pre-scripted sequence of stream_chat responses (no network)."""

    def __init__(self, scripts: list[list[dict[str, Any]]]) -> None:
        self.scripts = scripts
        self.calls = 0

    async def stream_chat(self, messages, tools=None) -> AsyncIterator[dict[str, Any]]:
        script = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        for delta in script:
            yield delta


class TimeoutRegistry:
    """Minimal registry for loop-level timeout policy tests."""

    answer_mode = "quick"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search test tool",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                },
            }
        ]

    async def execute(self, name: str, arguments: dict[str, Any], *, tool_call_id: str | None = None) -> ToolResult:
        self.calls.append({"name": name, "arguments": arguments, "tool_call_id": tool_call_id})
        err = te.make_error(te.TIMEOUT, "search timed out in test")
        return ToolResult(
            summary="search 执行失败",
            content=err.as_dict(),
            events=[
                {
                    "type": "tool_trace",
                    "tool_call_id": tool_call_id or "tc_test",
                    "tool_name": name,
                    "permission_level": "read_only",
                    "agent_mode": "quick",
                    "status": "error",
                    "error_code": te.TIMEOUT,
                    "error_message": err.message,
                    "recovery_hint": err.recovery_hint or "",
                    "result_summary": "search 执行失败",
                    "latency_ms": 1,
                    "artifacts_created": [],
                    "jobs_created": [],
                    "state_changed": False,
                }
            ],
        )


class FakeService:
    """Minimal stand-in for LiteratureResearchService used by the search tool."""

    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, query: str, **options):
        self.search_calls += 1
        return {
            "query_plan": {"retrieval_used": "fts", "filters_applied": {"scope": "library"}},
            "results": [
                {
                    "doi": "10.1/a",
                    "paper_id": "10.1/a",
                    "article_id": 1,
                    "title": "Membrane Paper",
                    "year": 2021,
                    "journal": "J. Membr.",
                    "evidence": [
                        {
                            "evidence_id": "E1",
                            "paper_id": "10.1/a",
                            "doi": "10.1/a",
                            "title": "Membrane Paper",
                            "kind": "section_chunk",
                            "section": "Results",
                            "snippet": "water flux 30 L/m2h",
                            "source_path": "articles/a/parsed/fulltext.md",
                            "confidence": 0.8,
                            "score": 12.0,
                        }
                    ],
                }
            ],
        }

    def acquire_evidence(self, query: str, *, has_history: bool = False, **options):
        from modules.literature_search.retrieval import build_packet

        return build_packet(self.search, query, has_history=has_history, options=options).as_dict()

    def to_chat_papers(self, payload):
        return [
            {
                "title": "Membrane Paper",
                "doi": "10.1/a",
                "year": 2021,
                "venue": "J. Membr.",
                "evidence": [
                    {
                        "evidence_id": "E1",
                        "snippet": "water flux 30 L/m2h",
                        "source_path": "articles/a/parsed/fulltext.md",
                        "section": "Results",
                        "confidence": "high",
                    }
                ],
            }
        ]


class EmptySearchService(FakeService):
    def search(self, query: str, **options):
        self.search_calls += 1
        return {
            "query_plan": {"retrieval_used": "fts", "filters_applied": {"scope": "library"}},
            "results": [],
        }

    def to_chat_papers(self, payload):
        return []


class MultiEvidenceService:
    """A single paper with many evidence rows — exercises the selector's
    per-paper cap so we can assert it becomes the citation/record boundary."""

    def search(self, query: str, **options):
        evidence = [
            {
                "evidence_id": f"E{i}",
                "paper_id": "P1",
                "doi": "10.1/a",
                "title": "Solo Paper",
                "kind": "section_chunk",
                "section": "Results",
                "snippet": f"snippet {i}",
                "source_path": "articles/a/parsed/fulltext.md",
                "confidence": "high",
                "score": 10.0 - i,
            }
            for i in range(6)
        ]
        return {
            "query_plan": {"retrieval_used": "fts", "vector_unavailable_reason": ""},
            "results": [
                {
                    "paper_id": "P1",
                    "doi": "10.1/a",
                    "article_id": 1,
                    "title": "Solo Paper",
                    "year": 2023,
                    "journal": "J. Test",
                    "evidence": evidence,
                }
            ],
        }

    def acquire_evidence(self, query: str, *, has_history: bool = False, **options):
        from modules.literature_search.retrieval import build_packet

        return build_packet(self.search, query, has_history=has_history, options=options).as_dict()

    def to_chat_papers(self, payload):
        out = []
        for item in payload.get("results") or []:
            out.append(
                {
                    "title": item["title"],
                    "doi": item["doi"],
                    "paper_id": item["paper_id"],
                    "year": item.get("year"),
                    "venue": item.get("journal"),
                    "evidence": item["evidence"],
                }
            )
        return out


def test_search_tool_restricts_to_selected_candidates(tmp_path):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "m.sqlite")
    user_id = _ensure_test_user(store)
    session = store.create_session(module_id="literature_search", title="t", user_id=user_id)
    turn_id = store.create_turn(session["session_id"], query="q", user_id=user_id)
    registry = ToolRegistry(
        MultiEvidenceService(), store, session_id=session["session_id"], turn_id=turn_id
    )

    result = asyncio.run(registry.execute("search", {"query": "membranes"}))

    # `topic` budget caps a single paper at 2/article -> only 2 evidence cross the
    # citation boundary (the rest are dropped, never citable).
    boundary = {e["evidence_id"] for e in result.evidence}
    assert len(result.evidence) == 2
    assert "E5" not in boundary  # dropped overflow is not citable

    # Gap 4 + §8: coverage AND breadth are persisted; the record keeps the
    # selection pool (here == the 2 kept evidence).
    ctx = store.get_context(session["session_id"])
    sr = ctx["recent_search_results"][0]
    assert sr["coverage"]["status"] in {"sufficient", "partial", "weak", "none"}
    assert "breadth" in sr and "candidate_paper_count" in sr["breadth"]
    assert len(ctx["recent_evidence"]) == 2


def test_search_tool_persists_fallback_on_no_results(tmp_path):
    from core.session_store import SessionStore

    class EmptyService(MultiEvidenceService):
        def search(self, query: str, **options):
            return {"query_plan": {"retrieval_used": "fts", "vector_unavailable_reason": ""}, "results": []}

    store = SessionStore(db_path=tmp_path / "m.sqlite")
    user_id = _ensure_test_user(store)
    session = store.create_session(module_id="literature_search", title="t", user_id=user_id)
    turn_id = store.create_turn(session["session_id"], query="q", user_id=user_id)
    registry = ToolRegistry(EmptyService(), store, session_id=session["session_id"], turn_id=turn_id)

    result = asyncio.run(registry.execute("search", {"query": "xyzzy"}))
    assert result.evidence == []  # no fabricated evidence

    search = store.get_context(session["session_id"], user_id=user_id)["recent_search_results"][0]
    assert search["coverage"]["status"] == "none"
    assert search["fallback_reason"]["code"] == "no_results"


def _registry_with(tmp_path, service):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "m.sqlite")
    user_id = _ensure_test_user(store)
    session = store.create_session(module_id="literature_search", title="t", user_id=user_id)
    turn_id = store.create_turn(session["session_id"], query="q", user_id=user_id)
    return ToolRegistry(service, store, session_id=session["session_id"], turn_id=turn_id)


def test_paper_chunks_returns_real_citable_ids(tmp_path):
    """L1: full-text chunks read via paper_chunks carry their real E{document_id}
    and become citable, so the model never needs to fabricate an id for a detail."""

    class ChunkService(MultiEvidenceService):
        def paper_text_documents(self, *, limit=30, **kw):
            return [
                {"evidence_id": "E4759959", "paper_id": "P1", "doi": "10.1/a", "title": "Paper",
                 "section": "Results", "kind": "section_chunk", "snippet": "RMSE 19.14 mS measured", "source_path": "a.md", "confidence": "medium"},
                {"evidence_id": "E4759960", "paper_id": "P1", "doi": "10.1/a", "title": "Paper",
                 "section": "Methods", "kind": "section_chunk", "snippet": "response within 234 s", "source_path": "a.md", "confidence": "medium"},
            ]

    registry = _registry_with(tmp_path, ChunkService())
    result = asyncio.run(registry.execute("paper_chunks", {"doi": "10.1/a"}))
    assert {e["evidence_id"] for e in result.evidence} == {"E4759959", "E4759960"}


def test_grounding_enrichment_realigns_via_index(tmp_path):
    """L2: before grounding, the real index chunk that contains the answer's
    distinctive number is pulled into the citable set (scoped to papers in play)."""

    class IndexService(MultiEvidenceService):
        def find_supporting_evidence(self, paper_ids, terms, *, limit=12):
            assert "P1" in paper_ids and "13666" in terms  # number located post-paraphrase
            return [{"evidence_id": "E999", "paper_id": "P1", "title": "Paper",
                     "section": "Results", "kind": "section_chunk", "snippet": "ion count 13666 measured"}]

    registry = _registry_with(tmp_path, IndexService())
    loop = AgentLoop(ScriptedLLM([[{"type": "content", "text": "x"}]]), registry)
    loop._available_evidence = {"E1": {"evidence_id": "E1", "paper_id": "P1"}}

    asyncio.run(loop._enrich_available_evidence("测得离子计数为 13,666，RMSE 较低"))
    assert "E999" in loop._available_evidence  # real supporting chunk now citable


def test_distinctive_terms_extracts_numbers_and_acronyms():
    from modules.literature_search.agent.loop import _distinctive_terms

    terms = _distinctive_terms("RMSE 19.14 mS，响应 234 s，离子数 13,666")
    assert "13666" in terms  # comma stripped
    assert "19.14" in terms
    assert "234" in terms
    assert "RMSE" in terms


def test_dedupe_used_evidence_collapses_same_locus():
    from modules.literature_search.agent.loop import _dedupe_used_evidence

    available = {
        # search id + pack id for the SAME physical evidence (same locus)
        "E6766876": {"evidence_id": "E6766876", "paper_id": "10.1/a", "source_path": "a.md",
                     "section_id": "s1", "chunk_index": 3, "title": "Bio"},
        "E10": {"evidence_id": "E10", "paper_id": "10.1/a", "source_path": "a.md",
                "section_id": "s1", "chunk_index": 3, "title": "Bio"},
        # a genuinely different evidence
        "E20": {"evidence_id": "E20", "paper_id": "10.1/b", "source_path": "b.md",
                "section_id": "s2", "chunk_index": 1, "title": "Other"},
    }
    used = _dedupe_used_evidence(["E6766876", "E10", "E20"], available)
    assert len(used) == 2  # the two same-locus ids collapsed into one
    first = used[0]
    assert first["evidence_ids"] == ["E6766876", "E10"]
    assert used[1]["evidence_ids"] == ["E20"]


def test_dedupe_used_evidence_keeps_locusless_separate():
    from modules.literature_search.agent.loop import _dedupe_used_evidence

    available = {
        "E1": {"evidence_id": "E1", "paper_id": None, "source_path": None, "section_id": None, "chunk_index": None},
        "E2": {"evidence_id": "E2", "paper_id": None, "source_path": None, "section_id": None, "chunk_index": None},
    }
    used = _dedupe_used_evidence(["E1", "E2"], available)
    assert len(used) == 2  # empty locus must NOT merge unrelated evidence


def test_pack_evidence_enters_citation_audit(tmp_path):
    """pack's numeric evidence aliases must be citable, else every
    pack-based citation is wrongly flagged "未找到证据"."""
    from core.session_store import SessionStore

    class PackService(MultiEvidenceService):
        def pack(self, query, **kwargs):
            return {
                "pack_path": "/tmp/pack.json",
                "evidence": [
                    {"evidence_id": "E1", "paper_id": "10.1/a", "doi": "10.1/a",
                     "title": "P", "section": "RAG", "source_path": "a.md",
                     "snippet": "rag helps", "confidence": "medium"},
                    {"evidence_id": "E2", "paper_id": "10.1/b", "doi": "10.1/b",
                     "title": "Q", "section": "Results", "source_path": "b.md",
                     "snippet": "18.5% gain", "confidence": "high"},
                ],
            }

    store = SessionStore(db_path=tmp_path / "m.sqlite")
    user_id = _ensure_test_user(store)
    session = store.create_session(module_id="literature_search", title="t", user_id=user_id)
    turn_id = store.create_turn(session["session_id"], query="q", user_id=user_id)
    registry = ToolRegistry(PackService(), store, session_id=session["session_id"], turn_id=turn_id)

    result = asyncio.run(registry.execute("pack", {"query": "rag"}))
    ids = {e["evidence_id"] for e in result.evidence}
    assert ids == {"E1", "E2"}

    # End-to-end: a pack id cited in the answer must NOT be flagged as missing.
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "pack", "arguments": {"query": "rag"}}],
            [{"type": "content", "text": "RAG 提升 18.5% [2]。"}],
        ]
    )
    loop = AgentLoop(llm, registry)
    events = asyncio.run(_drain(loop.run("rag 进展", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "ok"
    assert citation["missing_ids"] == []


def _make_registry(tmp_path, answer_mode="quick"):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    user_id = _ensure_test_user(store)
    session = store.create_session(module_id="literature_search", title="t", user_id=user_id)
    turn_id = store.create_turn(session["session_id"], query="flux", user_id=user_id)
    registry = ToolRegistry(
        FakeService(),
        store,
        session_id=session["session_id"],
        turn_id=turn_id,
        answer_mode=answer_mode,
    )
    return registry, store, session["session_id"]


async def _drain(agen) -> list[dict[str, Any]]:
    return [event async for event in agen]


def test_loop_runs_tool_then_answers_with_citation(tmp_path):
    registry, store, session_id = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "membrane flux"}}],
            [{"type": "content", "text": "检索路径 fts。膜通量约 30 L/m2h [1]。"}],
        ]
    )
    loop = AgentLoop(llm, registry)

    events = asyncio.run(_drain(loop.run("膜通量是多少", [], None)))
    types = [e["type"] for e in events]

    # tool executed and surfaced search results + step log
    assert registry.service.search_calls == 1
    assert "papers" in types
    assert "step" in types

    # final answer streamed as tokens
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "[1]" in answer

    # citation audit: cited a real evidence id, no hallucination
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "ok"
    assert citation["cited_ids"] == ["1"]
    assert citation["missing_ids"] == []

    # evidence persisted to the memory db for audit / follow-up reuse
    context = store.get_context(session_id)
    assert any(e["evidence_id"] == "E1" for e in context["recent_evidence"])


def _reconstruct_answer(events):
    """Mirror the store/chat_router: tokens accumulate, answer_reset clears."""
    out = ""
    for e in events:
        if e["type"] == "answer_reset":
            out = ""
        elif e["type"] == "token":
            out += e["text"]
    return out


def test_tool_turn_narration_excluded_from_answer(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            # model narrates AND calls a tool in the same turn (misbehaving model)
            [
                {"type": "content", "text": "我来搜索一下相关文献。"},
                {"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}},
            ],
            [{"type": "content", "text": "膜通量约 30 L/m2h [1]。"}],
        ]
    )
    loop = AgentLoop(llm, registry)
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))

    # The final answer must NOT contain the tool-turn narration.
    answer = _reconstruct_answer(events)
    assert answer == "膜通量约 30 L/m2h [1]。"
    assert "我来搜索" not in answer
    # narration surfaced as a process step instead
    assert any(e["type"] == "step" and "我来搜索" in (e.get("label") or "") for e in events)
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "ok"


def test_search_timeout_stops_additional_searches_and_emits_failure():
    registry = TimeoutRegistry()
    llm = ScriptedLLM(
        [
            [
                {"type": "content", "text": "I'll search the local library."},
                {"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "large language models materials discovery"}},
            ],
            [
                {"type": "content", "text": "Let me try a narrower query."},
                {"type": "tool_call", "id": "c2", "name": "search", "arguments": {"query": "LLM materials discovery"}},
            ],
            [{"type": "content", "text": "没有获得可用的本地文献证据。"}],
        ]
    )
    loop = AgentLoop(llm, registry)
    events = asyncio.run(_drain(loop.run("What are the applications of LLMs in materials discovery?", [], None)))

    assert len(registry.calls) == 1
    assert any(
        event.get("type") == "failure_explanation" and event.get("code") == "tool_timeout_failed"
        for event in events
    )


def test_coverage_none_emits_failure_explanation(tmp_path):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    user_id = _ensure_test_user(store)
    session = store.create_session(module_id="literature_search", title="t", user_id=user_id)
    turn_id = store.create_turn(session["session_id"], query="q", user_id=user_id)
    registry = ToolRegistry(EmptySearchService(), store, session_id=session["session_id"], turn_id=turn_id)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "quantum banana battery"}}],
            [{"type": "content", "text": "没有获得可用的本地文献证据。"}],
        ]
    )
    loop = AgentLoop(llm, registry)

    events = asyncio.run(_drain(loop.run("文献库里有没有关于量子香蕉电池的论文？", [], None)))

    failure = next((event for event in events if event.get("type") == "failure_explanation"), None)
    assert failure is not None
    assert failure["code"] == "no_candidate_papers"
    assert "量子香蕉电池" in failure["message"]


def test_final_answer_process_narration_is_stripped_after_failed_search():
    registry = TimeoutRegistry()
    llm = ScriptedLLM(
        [
            [
                {"type": "content", "text": "I'll search the local library."},
                {"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "materials discovery"}},
            ],
            [
                {
                    "type": "content",
                    "text": "I'll search the local library. Let me try a narrower query. I could not retrieve reliable local evidence.",
                }
            ],
        ]
    )
    loop = AgentLoop(llm, registry)
    events = asyncio.run(_drain(loop.run("What are the applications of LLMs in materials discovery?", [], None)))
    answer = _reconstruct_answer(events)

    assert not answer.startswith("I'll search")
    assert "Let me try" not in answer
    assert "could not retrieve reliable local evidence" in answer


def test_final_answer_strips_sufficient_evidence_process_preface():
    from modules.literature_search.agent.loop import _strip_process_narration

    answer = (
        "I already have sufficient evidence from the earlier successful search. "
        "Let me compile the answer based on what I've retrieved.\n\n"
        "## 本地文献检索结果\n\nSulfur concrete uses Martian soil simulants [1]."
    )

    cleaned = _strip_process_narration(answer)

    assert cleaned.startswith("## 本地文献检索结果")
    assert "I already have sufficient evidence" not in cleaned
    assert "Let me compile" not in cleaned


def test_final_answer_strips_chinese_sufficient_evidence_process_preface():
    from modules.literature_search.agent.loop import _strip_process_narration

    answer = (
        "非常好，我已经获得了非常丰富的文献证据。现在来组织完整的回答。"
        "好的，现在我有充分的证据来整合回答。\n\n"
        "## 一、附件内容总结\n\n"
        "来自上传附件《note.txt》：附件讨论了 LLM 材料发现。"
    )

    cleaned = _strip_process_narration(answer)

    assert cleaned.startswith("## 一、附件内容总结")
    assert "非常好" not in cleaned
    assert "现在来组织完整的回答" not in cleaned
    assert "充分的证据来整合回答" not in cleaned

    variant = _strip_process_narration(
        "现在我有足够的证据来给出综合回答。\n\n## 综合回答\n\n材料发现可由 LLM 辅助。"
    )
    assert variant.startswith("## 综合回答")
    assert "足够的证据来给出综合回答" not in variant

    collected = _strip_process_narration(
        "现在我已经收集了充分的证据。让我整合所有信息来回答。\n\n## 一、附件内容总结\n\n材料发现可由 LLM 辅助。"
    )
    assert collected.startswith("## 一、附件内容总结")
    assert "收集了充分的证据" not in collected
    assert "让我整合" not in collected


def test_final_answer_adds_attachment_source_marker_when_context_was_used(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "LLM materials discovery"}}],
            [{"type": "content", "text": "附件总结：LLM 可用于材料文献摘要。\n\n文献也支持该方向 [1]。"}],
        ]
    )
    loop = AgentLoop(llm, registry)
    events = asyncio.run(
        _drain(
            loop.run(
                "请先总结附件内容，再结合文献库补充相关研究。",
                [],
                {"session_attachments": [{"filename": "note.txt", "text": "LLM 可用于材料文献摘要。"}]},
            )
        )
    )

    answer = _reconstruct_answer(events)

    assert answer.startswith("来自上传附件《note.txt》")
    assert "[1]" in answer


def test_exhausted_budget_forces_final_answer(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path)
    # Always asks for a tool, never volunteers a final answer; the forced
    # tools-disabled synthesis (last script) must produce the cited answer.
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
            [{"type": "tool_call", "id": "c2", "name": "search", "arguments": {"query": "flux2"}}],
            [{"type": "content", "text": "基于已有证据：膜通量约 30 [1]。"}],
        ]
    )
    loop = AgentLoop(llm, registry, max_iterations=2)
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))

    answer = _reconstruct_answer(events)
    assert "[1]" in answer
    assert "已达到工具调用上限" not in answer  # no more leftover-narration wrap-up note
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "ok"
    assert citation["cited_ids"] == ["1"]


def test_loop_flags_hallucinated_citation(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
            [{"type": "content", "text": "膜通量约 30 [9]。"}],  # 9 was never retrieved
        ]
    )
    loop = AgentLoop(llm, registry)

    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "warning"
    assert citation["missing_ids"] == ["9"]


def test_english_successful_answer_flags_pseudo_citation(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "Martian soil simulants building materials"}}],
            [{"type": "content", "text": "Martian soil simulants can support construction material studies [99]."}],
        ]
    )
    loop = AgentLoop(llm, registry, enforce_citations=True)

    events = asyncio.run(_drain(loop.run("What papers discuss Martian soil simulants for building materials?", [], None)))

    assert any(event.get("type") == "papers" for event in events)
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "warning"
    assert citation["audit_status"] == "unverified"
    assert citation["cited_ids"] == ["99"]
    assert citation["missing_ids"] == ["99"]
    assert citation["used_evidence"] == []


def test_loop_accepts_fullwidth_bracket_citations(tmp_path):
    """Chinese-output models emit full-width numeric brackets. Those must count as real
    citations, not trip a false "had evidence but cited nothing" warning."""
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
            [{"type": "content", "text": "膜通量约 30 L/m2h【1】。"}],  # full-width brackets
        ]
    )
    loop = AgentLoop(llm, registry, enforce_citations=True)

    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "ok"
    assert citation["cited_ids"] == ["1"]
    assert citation["missing_ids"] == []
    assert len(citation["used_evidence"]) == 1  # popover has content


def test_audit_mode_flags_fabricated_id_without_llm_pass(tmp_path):
    """Default 'audit' floor: still flags a fabricated id (deterministic), but
    runs NO per-claim grounding LLM pass (efficiency / no over-deletion)."""
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
            [{"type": "content", "text": "膜通量约 30 [9]。"}],  # 9 never retrieved
        ]
    )
    loop = AgentLoop(llm, registry, grounding_mode="audit")
    events = asyncio.run(_drain(loop.run("flux", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "warning"
    assert citation["missing_ids"] == ["9"]
    assert llm.calls == 2  # no extra grounding call (tool turn + answer only)
    assert citation.get("grounding") is None  # no LLM grounding record in audit mode


def test_audit_mode_valid_citation_is_ok(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
            [{"type": "content", "text": "膜通量约 30 L/m2h [1]。"}],
        ]
    )
    loop = AgentLoop(llm, registry, grounding_mode="audit")
    events = asyncio.run(_drain(loop.run("flux", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "ok"
    assert llm.calls == 2  # deterministic floor adds no LLM latency


def test_loop_warns_when_evidence_uncited(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path)
    llm = ScriptedLLM(
        [
            [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
            [{"type": "content", "text": "膜通量大概是 30 左右。"}],  # evidence available but no citation
        ]
    )
    loop = AgentLoop(llm, registry, enforce_citations=True)

    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "warning"


def test_quick_mode_hides_deep_tools(tmp_path):
    registry, _store, _sid = _make_registry(tmp_path, answer_mode="quick")
    names = {d["function"]["name"] for d in registry.definitions()}
    assert "search" in names
    assert "run" not in names and "task_run" not in names

    deep_registry, _s, _i = _make_registry(tmp_path, answer_mode="deep")
    deep_names = {d["function"]["name"] for d in deep_registry.definitions()}
    assert {"run", "task_run", "extract", "compare"} <= deep_names


def test_build_llm_client_unavailable_when_provider_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "memory.sqlite"))
    from core.settings_store import SettingsStore

    store = SettingsStore(db_path=tmp_path / "memory.sqlite")  # provider defaults to "none"
    _ensure_test_user(store)
    assert store.llm_enabled(user_id=TEST_USER_ID) is False
    with pytest.raises(LLMUnavailable):
        build_llm_client(store, user_id=TEST_USER_ID)
