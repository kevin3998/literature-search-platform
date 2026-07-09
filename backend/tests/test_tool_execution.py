"""Block 4 — tool execution layer: permission gate, input validation, timeout,
job-runner consistency, structured errors, and tool trace."""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import pytest

from core.session_store import SessionStore
from modules.literature_search.agent import tool_errors as te
from modules.literature_search.agent.tool_specs import get_spec, specs_for_mode
from modules.literature_search.agent.tools import ToolRegistry


@pytest.fixture(autouse=True)
def _isolate_memory_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "singleton.sqlite"))


# --- fakes ---------------------------------------------------------------------


class FakeService:
    """Just enough surface for the read-only/direct tools exercised here."""

    def __init__(self) -> None:
        self.search_calls = 0
        self.acquire_options: list[dict] = []

    def search(self, query: str, **options):
        self.search_calls += 1
        return {
            "query_plan": {"retrieval_used": "fts", "vector_unavailable_reason": ""},
            "results": [
                {
                    "doi": "10.1/a",
                    "paper_id": "10.1/a",
                    "article_id": 1,
                    "title": "Paper A",
                    "year": 2021,
                    "journal": "J",
                    "evidence": [
                        {
                            "evidence_id": "E1",
                            "paper_id": "10.1/a",
                            "doi": "10.1/a",
                            "title": "Paper A",
                            "kind": "section_chunk",
                            "section": "Results",
                            "snippet": "flux 30",
                            "source_path": "articles/a/parsed/fulltext.md",
                            "confidence": "high",
                            "score": 10.0,
                        }
                    ],
                }
            ],
        }

    def acquire_evidence(self, query: str, *, has_history: bool = False, **options):
        self.acquire_options.append(dict(options))
        from modules.literature_search.retrieval import build_packet

        return build_packet(self.search, query, has_history=has_history, options=options).as_dict()

    def to_chat_papers(self, payload):
        return [
            {
                "title": "Paper A",
                "doi": "10.1/a",
                "paper_id": "10.1/a",
                "year": 2021,
                "venue": "J",
                "evidence": [
                    {
                        "evidence_id": "E1",
                        "snippet": "flux 30",
                        "source_path": "articles/a/parsed/fulltext.md",
                        "section": "Results",
                        "confidence": "high",
                    }
                ],
            }
        ]

    def evidence_expand(self, **kwargs):
        return {"assets": []}


class SlowService(FakeService):
    def evidence_expand(self, **kwargs):
        time.sleep(0.5)
        return {"assets": []}


class SlowSearchService(FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.acquire_calls = 0

    def acquire_evidence(self, query: str, *, has_history: bool = False, **options):
        self.acquire_calls += 1
        time.sleep(0.05)
        return super().acquire_evidence(query, has_history=has_history, **options)


class BoomService(FakeService):
    def evidence_expand(self, **kwargs):
        raise ValueError("no paper matched the provided DOI /Users/secret/corpus/x.pdf")


class _FakeJobStore:
    def __init__(self) -> None:
        self.jobs: dict = {}
        self.evs: dict = {}

    def get(self, job_id):
        return self.jobs[job_id]

    def events(self, job_id, *, after: int = 0):
        return self.evs.get(job_id, [])[after:]


class FakeJobRunner:
    """Synchronous stand-in: `submit` resolves the job immediately so the
    block-stream loop in `_execute_job` sees a terminal status on first poll."""

    def __init__(self, *, result=None, fail: str | None = None) -> None:
        self.store = _FakeJobStore()
        self.result = result or {}
        self.fail = fail
        self.submitted: list = []

    def submit(self, job_type, payload):
        self.submitted.append((job_type, dict(payload)))
        job_id = "job_test1"
        if self.fail:
            self.store.jobs[job_id] = {"job_id": job_id, "status": "failed", "error": self.fail, "result": None}
            self.store.evs[job_id] = [
                {"type": "stage", "stage": "job", "status": "running", "label": "start"},
                {"type": "error", "message": self.fail},
                {"type": "done"},
            ]
        else:
            artifact = {
                "type": "artifact",
                "artifact_type": "run",
                "artifact_id": "research_agent/runs/r1.json",
                "path": "research_agent/runs/r1.json",
            }
            self.store.jobs[job_id] = {"job_id": job_id, "status": "completed", "error": None, "result": self.result}
            self.store.evs[job_id] = [
                {"type": "stage", "stage": "job", "status": "running", "label": "start"},
                artifact,
                {"type": "result", "data": self.result},
                {"type": "done"},
            ]
        return {"job_id": job_id, "status": "queued"}


def _registry(tmp_path, service, *, answer_mode="quick", job_runner=None):
    store = SessionStore(db_path=tmp_path / "m.sqlite")
    session = store.create_session(module_id="literature_search", title="t")
    turn_id = store.create_turn(session["session_id"], query="q")
    reg = ToolRegistry(
        service,
        store,
        session_id=session["session_id"],
        turn_id=turn_id,
        answer_mode=answer_mode,
        job_runner=job_runner,
    )
    return reg, store, session["session_id"]


# --- gating / permissions ------------------------------------------------------


def test_quick_mode_excludes_long_state_creating_tools(tmp_path):
    reg, *_ = _registry(tmp_path, FakeService(), answer_mode="quick")
    names = {d["function"]["name"] for d in reg.definitions()}
    assert {"search", "paper_sections", "paper_chunks", "evidence_expand", "pack"} <= names
    assert names.isdisjoint({"task_run", "run", "extract", "compare", "verify_answer", "quality"})


def test_deep_mode_exposes_state_creating_tools(tmp_path):
    reg, *_ = _registry(tmp_path, FakeService(), answer_mode="deep")
    names = {d["function"]["name"] for d in reg.definitions()}
    assert {"task_run", "run", "extract", "compare", "verify_answer", "quality"} <= names


def test_admin_maintenance_tools_not_in_any_agent_mode():
    for mode in ("quick", "deep"):
        names = {s.name for s in specs_for_mode(mode)}
        assert names.isdisjoint({"index_refresh", "vector_build", "delete_artifact", "health_check"})
    assert get_spec("index_refresh") is None


def test_disabled_tool_returns_permission_denied(tmp_path):
    reg, *_ = _registry(tmp_path, FakeService(), answer_mode="quick")
    result = asyncio.run(reg.execute("run", {"question": "q"}))
    assert result.content["ok"] is False
    assert result.content["error"]["code"] == te.PERMISSION_DENIED


def test_unknown_tool_returns_permission_denied(tmp_path):
    reg, *_ = _registry(tmp_path, FakeService())
    result = asyncio.run(reg.execute("does_not_exist", {}))
    assert result.content["error"]["code"] == te.PERMISSION_DENIED


# --- input validation ----------------------------------------------------------


def test_missing_required_argument_is_validation_error(tmp_path):
    reg, *_ = _registry(tmp_path, FakeService())
    result = asyncio.run(reg.execute("search", {}))
    assert result.content["error"]["code"] == te.VALIDATION_ERROR


def test_wrong_argument_type_is_validation_error(tmp_path):
    reg, *_ = _registry(tmp_path, FakeService())
    result = asyncio.run(reg.execute("search", {"query": "x", "limit": "lots"}))
    assert result.content["error"]["code"] == te.VALIDATION_ERROR


# --- timeout / errors ----------------------------------------------------------


def test_direct_tool_timeout_produces_trace(tmp_path):
    reg, store, session_id = _registry(tmp_path, SlowService())
    reg.specs["evidence_expand"] = replace(reg.specs["evidence_expand"], timeout_seconds=0.05)
    result = asyncio.run(reg.execute("evidence_expand", {"doi": "10.1/a"}))
    assert result.content["error"]["code"] == te.TIMEOUT
    assert result.content["error"]["retryable"] is True
    trace = store.build_record(session_id)["turns"][0]["tool_trace"]
    assert trace and trace[-1]["error_code"] == te.TIMEOUT
    assert trace[-1]["status"] == "error"


def test_search_timeout_is_not_retried_inside_one_tool_call(tmp_path):
    service = SlowSearchService()
    reg, _store, _session_id = _registry(tmp_path, service)
    reg.specs["search"] = replace(reg.specs["search"], timeout_seconds=0.01)

    result = asyncio.run(reg.execute("search", {"query": "large language models materials discovery"}))
    time.sleep(0.08)

    assert result.content["error"]["code"] == te.TIMEOUT
    assert service.acquire_calls == 1


def test_search_tool_passes_original_question_to_packet(tmp_path):
    service = FakeService()
    reg, _store, _session_id = _registry(tmp_path, service)
    reg.original_question = "文献库里有没有关于火星土壤超导材料的论文？"

    result = asyncio.run(reg.execute("search", {"query": "火星土壤 超导材料 Martian soil superconducting"}))

    assert result.content["coverage"]["status"] != "sufficient"
    assert service.acquire_options[-1]["_original_user_query"] == "文献库里有没有关于火星土壤超导材料的论文？"


def test_tool_exception_is_classified_and_redacted(tmp_path):
    reg, store, session_id = _registry(tmp_path, BoomService())
    result = asyncio.run(reg.execute("evidence_expand", {"doi": "10.1/a"}))
    err = result.content["error"]
    assert err["code"] == te.PAPER_NOT_FOUND
    assert "/Users/secret/corpus" not in err["message"]  # absolute path redacted
    assert err["recovery_hint"]


def test_tool_failure_does_not_raise_into_loop(tmp_path):
    reg, *_ = _registry(tmp_path, BoomService())
    # Must return a ToolResult, never propagate the exception.
    result = asyncio.run(reg.execute("evidence_expand", {"doi": "x"}))
    assert te.is_tool_error(result.content)


# --- job runner consistency ----------------------------------------------------


def test_job_tool_submits_streams_and_records(tmp_path):
    runner = FakeJobRunner(result={"run_id": "r1", "report_path": "research_agent/runs/r1.md"})
    reg, store, session_id = _registry(tmp_path, FakeService(), answer_mode="deep", job_runner=runner)
    result = asyncio.run(reg.execute("run", {"question": "compare X"}))

    assert result.content == {"run_id": "r1", "report_path": "research_agent/runs/r1.md"}
    types = {e["type"] for e in result.events}
    assert {"job", "artifact", "tool_trace"} <= types
    # session_id / turn_id flowed into the submitted payload (job ↔ session link).
    job_type, payload = runner.submitted[0]
    assert job_type == "run" and payload["session_id"] == session_id and "turn_id" in payload

    trace = store.build_record(session_id)["turns"][0]["tool_trace"][-1]
    assert trace["status"] == "ok"
    assert "research_agent/runs/r1.json" in trace["artifacts_created"]
    assert trace["jobs_created"] == ["job_test1"]
    assert trace["state_changed"] is True


def test_job_tool_failure_returns_job_failed(tmp_path):
    runner = FakeJobRunner(fail="run crashed at stage synthesize")
    reg, store, session_id = _registry(tmp_path, FakeService(), answer_mode="deep", job_runner=runner)
    result = asyncio.run(reg.execute("run", {"question": "q"}))
    assert result.content["error"]["code"] == te.JOB_FAILED
    trace = store.build_record(session_id)["turns"][0]["tool_trace"][-1]
    assert trace["error_code"] == te.JOB_FAILED


# --- trace + schema regression -------------------------------------------------


def test_successful_read_only_tool_records_trace(tmp_path):
    reg, store, session_id = _registry(tmp_path, FakeService())
    asyncio.run(reg.execute("search", {"query": "membranes"}))
    trace = store.build_record(session_id)["turns"][0]["tool_trace"][-1]
    assert trace["tool_name"] == "search"
    assert trace["status"] == "ok"
    assert trace["permission_level"] == "read_only"
    assert trace["state_changed"] is False
    assert trace["latency_ms"] is not None


def test_definitions_schema_is_stable(tmp_path):
    reg, *_ = _registry(tmp_path, FakeService(), answer_mode="deep")
    by_name = {d["function"]["name"]: d["function"] for d in reg.definitions()}
    assert len(by_name) == 11
    assert by_name["search"]["parameters"]["required"] == ["query"]
    assert by_name["run"]["parameters"]["required"] == ["question"]


def test_redact_masks_secrets_and_paths():
    out = te.redact({"api_key": "sk-123", "path": "/Users/me/corpus/p.pdf", "q": "hello"})
    assert out["api_key"] == "[redacted]"
    assert "/Users/me/corpus" not in out["path"]
    assert out["q"] == "hello"


# --- 4b: per-turn answer_mode override -----------------------------------------


def _run_agent_capture(monkeypatch, *, options):
    """Drive module._run_agent with collaborators stubbed, capturing the
    answer_mode ToolRegistry is built with."""
    import modules.literature_search.module as mod

    captured = {}

    class FakeRegistry:
        def __init__(self, *a, **kw):
            captured["answer_mode"] = kw.get("answer_mode")

    class FakeLoop:
        def __init__(self, *a, **kw):
            pass

        async def run(self, *a, **kw):
            if False:
                yield {}

    monkeypatch.setattr(mod, "ToolRegistry", FakeRegistry)
    monkeypatch.setattr(mod, "AgentLoop", FakeLoop)
    monkeypatch.setattr(mod, "build_llm_client", lambda *_: object())
    monkeypatch.setattr(mod.settings_store, "agent_config", lambda: {
        "answer_mode": "quick", "max_tool_iterations": 3, "tool_budget": 5,
        "enforce_citations": False, "grounding_mode": "audit",
    })
    monkeypatch.setattr(mod.real_adapter, "service", object(), raising=False)

    async def drain():
        async for _ in mod.LiteratureSearchModule()._run_agent("s", "q", [], dict(options)):
            pass

    asyncio.run(drain())
    return captured["answer_mode"]


def test_per_turn_deep_overrides_quick_default(monkeypatch):
    assert _run_agent_capture(monkeypatch, options={"answer_mode": "deep"}) == "deep"


def test_per_turn_absent_falls_back_to_setting(monkeypatch):
    assert _run_agent_capture(monkeypatch, options={}) == "quick"


def test_per_turn_invalid_mode_ignored(monkeypatch):
    assert _run_agent_capture(monkeypatch, options={"answer_mode": "bogus"}) == "quick"


def _handle_chat_capture_non_research(monkeypatch, message, *, llm=None, llm_enabled=True):
    import modules.literature_search.module as mod

    class BoomRegistry:
        def __init__(self, *a, **kw):
            raise AssertionError("non-research chat must not construct ToolRegistry")

    class BoomLoop:
        def __init__(self, *a, **kw):
            raise AssertionError("non-research chat must not enter AgentLoop")

    monkeypatch.setattr(mod, "REAL_AGENT_AVAILABLE", True)
    monkeypatch.setattr(mod, "real_adapter", object())
    monkeypatch.setattr(mod.settings_store, "llm_enabled", lambda: llm_enabled)
    monkeypatch.setattr(mod, "ToolRegistry", BoomRegistry)
    monkeypatch.setattr(mod, "AgentLoop", BoomLoop)
    if llm is not None:
        monkeypatch.setattr(mod, "build_llm_client", lambda *_: llm)

    async def drain():
        return [
            event
            async for event in mod.LiteratureSearchModule().handle_chat(
                "s", message, [], {"_memory_context": {"recent_evidence": [{"evidence_id": "E1"}]}}
            )
        ]

    return asyncio.run(drain())


def test_handle_chat_greeting_short_circuits_before_agent(monkeypatch):
    class ChattyLLM:
        async def stream_chat(self, messages, tools=None):
            assert tools is None
            yield {"type": "content", "text": "自然回复"}

    events = _handle_chat_capture_non_research(monkeypatch, "你好", llm=ChattyLLM())
    assert [e["type"] for e in events] == ["intent_route", "token", "done"]
    assert events[0]["route"] == "plain_chat"
    assert events[1]["text"] == "自然回复"


def test_handle_chat_help_short_circuits_before_agent(monkeypatch):
    class ChattyLLM:
        async def stream_chat(self, messages, tools=None):
            assert tools is None
            yield {"type": "content", "text": "我是自然对话助手"}

    events = _handle_chat_capture_non_research(monkeypatch, "怎么用？", llm=ChattyLLM())
    assert [e["type"] for e in events] == ["intent_route", "token", "done"]
    assert events[0]["route"] == "plain_help"
    assert events[1]["text"] == "我是自然对话助手"


def test_handle_chat_vague_analysis_short_circuits_before_agent(monkeypatch):
    class ChattyLLM:
        async def stream_chat(self, messages, tools=None):
            assert tools is None
            yield {"type": "content", "text": "你想分析什么对象？"}

    events = _handle_chat_capture_non_research(monkeypatch, "帮我分析一下", llm=ChattyLLM())
    assert [e["type"] for e in events] == ["intent_route", "token", "done"]
    assert events[0]["route"] == "plain_chat"
    assert events[1]["text"] == "你想分析什么对象？"


def test_handle_chat_non_research_returns_deterministic_answer_when_llm_unavailable(monkeypatch):
    events = _handle_chat_capture_non_research(monkeypatch, "你好", llm_enabled=False)
    assert [e["type"] for e in events] == ["intent_route", "token", "done"]
    assert events[0]["route"] == "plain_chat"
    assert "你好" in events[1]["text"]


# --- breadth note must be mode-aware (deep ≠ "start deep research") ------------


def test_compact_search_note_quick_suggests_deep():
    from modules.literature_search.agent.tools import _compact_search

    note = _compact_search("q", [], {}, answer_mode="quick")["note"]
    assert "switching to deep research" in note


def test_compact_search_note_deep_does_not_suggest_starting_deep():
    from modules.literature_search.agent.tools import _compact_search

    note = _compact_search("q", [], {}, answer_mode="deep")["note"]
    assert "ALREADY in deep research mode" in note
    assert "Do NOT tell the user to start a deep research" in note
