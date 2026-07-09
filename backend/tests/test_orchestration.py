"""Block 5 — deterministic orchestration shell: failure loop-guard, per-turn
search cap, and the quick-mode-only deep-research suggestion derivation."""
from __future__ import annotations

import asyncio

import pytest

from core.session_store import SessionStore
from modules.literature_search.agent import orchestration as orch
from modules.literature_search.agent.loop import AgentLoop
from modules.literature_search.agent.tools import ToolRegistry

from test_agent_loop import MultiEvidenceService, ScriptedLLM


@pytest.fixture(autouse=True)
def _isolate_memory_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "singleton.sqlite"))


# --- TurnGuard -----------------------------------------------------------------


def test_route_casual_greeting_skips_research():
    route = orch.route_chat_intent("你好", has_history=False, has_recent_evidence=False)
    assert route.kind == "casual"
    assert route.should_enter_research is False


def test_route_natural_greeting_variant_skips_research():
    route = orch.route_chat_intent("你好啊", has_history=False, has_recent_evidence=False)
    assert route.kind == "casual"
    assert route.should_enter_research is False


def test_route_casual_ack_skips_research():
    route = orch.route_chat_intent("谢谢", has_history=True, has_recent_evidence=True)
    assert route.kind == "casual"
    assert route.should_enter_research is False


def test_route_help_skips_research_and_hides_tool_names():
    route = orch.route_chat_intent("你能做什么？", has_history=False, has_recent_evidence=False)
    assert route.kind == "help"
    assert route.should_enter_research is False


def test_route_identity_question_is_help_not_research():
    route = orch.route_chat_intent("你是谁？", has_history=False, has_recent_evidence=False)
    assert route.kind == "help"
    assert route.should_enter_research is False


def test_route_vague_analysis_asks_clarification():
    route = orch.route_chat_intent("帮我分析一下", has_history=False, has_recent_evidence=False)
    assert route.kind == "clarification"
    assert route.should_enter_research is False


def test_route_research_enters_agent_loop():
    route = orch.route_chat_intent("帮我分析 Treg 在肿瘤免疫中的作用", has_history=False, has_recent_evidence=False)
    assert route.kind == "research"
    assert route.should_enter_research is True


def test_route_followup_with_recent_evidence_enters_agent_loop():
    route = orch.route_chat_intent("那这些论文的实验条件分别是什么？", has_history=True, has_recent_evidence=True)
    assert route.kind == "followup_research"
    assert route.should_enter_research is True


def test_search_cap_blocks_after_limit():
    g = orch.TurnGuard(max_searches=3)
    args = {"query": "x"}
    for _ in range(3):
        assert g.block_reason("search", args) is None
        g.record("search", args, is_error=False)
    reason = g.block_reason("search", {"query": "y"})
    assert reason and "上限" in reason


def test_non_search_tools_not_capped_by_search_limit():
    g = orch.TurnGuard(max_searches=1)
    g.record("search", {"query": "x"}, is_error=False)
    assert g.block_reason("search", {"query": "z"}) is not None
    # A different tool is unaffected by the search cap.
    assert g.block_reason("paper_sections", {"doi": "10.1/a"}) is None


def test_identical_failure_blocked_after_threshold():
    g = orch.TurnGuard(max_identical_failures=2)
    call = ("evidence_expand", {"doi": "missing"})
    assert g.block_reason(*call) is None
    g.record(*call, is_error=True)
    assert g.block_reason(*call) is None
    g.record(*call, is_error=True)
    # Third identical attempt is refused.
    assert g.block_reason(*call) is not None
    # A different argument set is still allowed.
    assert g.block_reason("evidence_expand", {"doi": "other"}) is None


def test_success_does_not_count_as_failure():
    g = orch.TurnGuard(max_identical_failures=1)
    call = ("search", {"query": "x"})
    g.record(*call, is_error=False)
    g.record(*call, is_error=False)
    assert g.block_reason(*call) is None  # only blocked by failures, not successes


def test_call_signature_is_argument_order_independent():
    a = orch.call_signature("search", {"query": "x", "limit": 8})
    b = orch.call_signature("search", {"limit": 8, "query": "x"})
    assert a == b
    assert a != orch.call_signature("search", {"query": "y"})


def test_blocked_payload_is_structured_error():
    p = orch.blocked_payload("nope")
    assert p["ok"] is False and p["error"]["code"] == "blocked_by_policy"
    assert p["error"]["recovery_hint"] == "nope"


# --- deep-research suggestion derivation --------------------------------------


def _coverage(**breadth):
    return {"type": "coverage", "status": "sufficient", "breadth": breadth, **breadth}


def test_suggest_deep_quick_mode_when_flagged():
    ev = _coverage(deep_research_suggested=True, candidate_paper_count=80)
    sug = orch.should_suggest_deep(ev, "quick")
    assert sug and sug["candidate_paper_count"] == 80


def test_no_suggestion_in_deep_mode():
    ev = _coverage(deep_research_suggested=True, candidate_paper_count=80)
    assert orch.should_suggest_deep(ev, "deep") is None


def test_no_suggestion_when_not_flagged():
    ev = _coverage(deep_research_suggested=False)
    assert orch.should_suggest_deep(ev, "quick") is None


# --- loop integration ----------------------------------------------------------


def _registry(tmp_path, service, *, answer_mode="quick"):
    store = SessionStore(db_path=tmp_path / "m.sqlite")
    session = store.create_session(module_id="literature_search", title="t")
    turn_id = store.create_turn(session["session_id"], query="q")
    return ToolRegistry(service, store, session_id=session["session_id"], turn_id=turn_id, answer_mode=answer_mode)


def test_loop_emits_deep_research_suggestion_when_policy_says_so(tmp_path, monkeypatch):
    # Decouple the loop wiring from breadth internals: the suggestion derivation is
    # unit-tested above; here we assert the loop emits ONE event carrying the
    # question when the (quick-mode) policy returns a payload on a coverage event.
    seen_modes = []

    def fake(event, mode):
        seen_modes.append(mode)
        return {"reason": "概览", "candidate_paper_count": 42} if mode == "quick" else None

    monkeypatch.setattr(orch, "should_suggest_deep", fake)
    registry = _registry(tmp_path, MultiEvidenceService(), answer_mode="quick")
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "review"}}],
        [{"type": "content", "text": "代表性概览 [E0]"}],
    ])
    loop = AgentLoop(llm, registry, grounding_mode="off")
    events = asyncio.run(_collect(loop.run("综述", [], None)))
    sugs = [e for e in events if e.get("type") == "deep_research_suggestion"]
    assert len(sugs) == 1 and sugs[0]["question"] == "综述" and sugs[0]["candidate_paper_count"] == 42
    assert "quick" in seen_modes


def test_loop_no_suggestion_in_deep(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "should_suggest_deep", lambda event, mode: None if mode == "deep" else {"reason": "x"})
    registry = _registry(tmp_path, MultiEvidenceService(), answer_mode="deep")
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "review"}}],
        [{"type": "content", "text": "代表性概览 [E0]"}],
    ])
    loop = AgentLoop(llm, registry, grounding_mode="off")
    events = asyncio.run(_collect(loop.run("综述", [], None)))
    assert not any(e.get("type") == "deep_research_suggestion" for e in events)


def test_reused_evidence_flag_when_no_search(tmp_path):
    # No tool call at all → answer straight from injected recent evidence.
    registry = _registry(tmp_path, MultiEvidenceService(), answer_mode="quick")
    llm = ScriptedLLM([[{"type": "content", "text": "复用上一轮 [E1]"}]])
    loop = AgentLoop(llm, registry, grounding_mode="off")
    memory = {"recent_evidence": [{"evidence_id": "E1", "title": "Prev", "snippet": "..."}]}
    events = asyncio.run(_collect(loop.run("追问", [], memory)))
    citation = next(e for e in events if e.get("type") == "citation")
    assert citation["reused_evidence"] is True
    assert citation["missing_ids"] == []
    assert citation["used_evidence"][0]["evidence_id"] == "E1"


def test_reused_evidence_false_when_searched(tmp_path):
    registry = _registry(tmp_path, MultiEvidenceService(), answer_mode="quick")
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "x"}}],
        [{"type": "content", "text": "新检索 [E0]"}],
    ])
    loop = AgentLoop(llm, registry, grounding_mode="off")
    memory = {"recent_evidence": [{"evidence_id": "E1", "title": "Prev"}]}
    events = asyncio.run(_collect(loop.run("新问题", [], memory)))
    citation = next(e for e in events if e.get("type") == "citation")
    assert citation["reused_evidence"] is False


def test_loop_stops_re_executing_a_repeatedly_failing_call(tmp_path):
    # The guard must stop the loop from re-running the SAME failing call forever.
    class BoomExpand(MultiEvidenceService):
        def __init__(self):
            self.calls = 0

        def evidence_expand(self, **kwargs):
            self.calls += 1
            raise ValueError("nope")

    service = BoomExpand()
    registry = _registry(tmp_path, service, answer_mode="quick")
    # ScriptedLLM clamps to its last script → every iteration re-issues the same
    # failing evidence_expand; the guard must cap real executions at 2.
    llm = ScriptedLLM([[{"type": "tool_call", "id": "c1", "name": "evidence_expand", "arguments": {"doi": "x"}}]])
    loop = AgentLoop(llm, registry, max_iterations=6, grounding_mode="off")
    asyncio.run(_collect(loop.run("q", [], None)))
    assert service.calls == orch.MAX_IDENTICAL_FAILURES  # blocked after the threshold


async def _collect(agen):
    out = []
    async for e in agen:
        out.append(e)
    return out
