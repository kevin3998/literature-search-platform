from __future__ import annotations

import asyncio
import json

import pytest

from modules.literature_search.agent import grounding as g
from modules.literature_search.agent.loop import AgentLoop
from tests.test_agent_loop import FakeService, ScriptedLLM, _drain, _reconstruct_answer


@pytest.fixture(autouse=True)
def _isolate_memory_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(tmp_path / "singleton.sqlite"))


def _registry(tmp_path, answer_mode="quick"):
    from core.session_store import SessionStore
    from modules.literature_search.agent.tools import ToolRegistry

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    session = store.create_session(module_id="literature_search", title="t")
    turn_id = store.create_turn(session["session_id"], query="flux")
    registry = ToolRegistry(
        FakeService(), store, session_id=session["session_id"], turn_id=turn_id, answer_mode=answer_mode
    )
    return registry, store, session["session_id"]


def _grounding_script(payload: dict) -> list[dict]:
    return [{"type": "content", "text": json.dumps(payload, ensure_ascii=False)}]


# --- unit: run_grounding ----------------------------------------------------


def test_no_evidence_short_circuits_to_not_answerable():
    # No citable evidence → deterministic not_answerable, no LLM call needed.
    class BoomLLM:
        async def stream_chat(self, messages, tools=None):  # pragma: no cover - must not run
            raise AssertionError("grounding must not call the LLM when there is no evidence")
            yield {}

    out = asyncio.run(g.run_grounding(BoomLLM(), "膜通量约 30。", {}, mode="strict"))
    assert out["answer_permission"] == "not_answerable"
    assert out["rewritten_answer"] is None


def test_off_mode_returns_none():
    out = asyncio.run(g.run_grounding(ScriptedLLM([[]]), "x", {"E1": {"snippet": "s"}}, mode="off"))
    assert out is None


def test_malformed_json_degrades_to_none():
    llm = ScriptedLLM([[{"type": "content", "text": "sorry, not json"}]])
    out = asyncio.run(g.run_grounding(llm, "x [E1]", {"E1": {"snippet": "s"}}, mode="strict"))
    assert out is None


def test_normalize_drops_unavailable_ids():
    payload = {
        "claims": [
            {"claim": "c", "support_status": "supported", "evidence_ids": ["E1", "E999"], "rewrite_action": "keep"}
        ],
        "answer_permission": "grounded",
        "rewritten_answer": None,
    }
    llm = ScriptedLLM([_grounding_script(payload)])
    out = asyncio.run(g.run_grounding(llm, "x [E1]", {"E1": {"snippet": "s"}}, mode="strict"))
    assert out["claims"][0]["evidence_ids"] == ["E1"]  # fabricated E999 stripped


# --- end to end through the loop -------------------------------------------


def test_supported_answer_kept_with_permission(tmp_path):
    registry, _store, _sid = _registry(tmp_path)
    payload = {
        "claims": [{"claim": "膜通量约 30", "support_status": "supported", "evidence_ids": ["E1"],
                    "rewrite_action": "keep"}],
        "answer_permission": "grounded",
        "rewritten_answer": None,
    }
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
        [{"type": "content", "text": "膜通量约 30 L/m2h [E1]。"}],
        _grounding_script(payload),
    ])
    loop = AgentLoop(llm, registry, grounding_mode="strict")
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))

    answer = _reconstruct_answer(events)
    assert answer == "膜通量约 30 L/m2h [E1]。"  # unchanged
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["answer_permission"] == "grounded"
    assert citation["status"] == "ok"
    assert citation["grounding_summary"]["supported"] == 1


def test_overclaim_is_rewritten_and_flagged(tmp_path):
    registry, _store, _sid = _registry(tmp_path)
    payload = {
        "claims": [{"claim": "该领域普遍认为通量为 30", "support_status": "partially_supported",
                    "evidence_ids": ["E1"], "scope_notes": "单篇结果不可推广", "rewrite_action": "downgrade"}],
        "answer_permission": "partially_grounded",
        "warnings": ["将单篇结果写成了领域级结论。"],
        "rewritten_answer": "在本轮检索到的某研究中，膜通量约为 30 L/m2h [E1]，该结果范围有限。",
    }
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
        [{"type": "content", "text": "该领域普遍认为膜通量为 30 L/m2h [E1]。"}],
        _grounding_script(payload),
    ])
    loop = AgentLoop(llm, registry, grounding_mode="strict")
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))

    # the overclaiming draft was reset and replaced by the downgraded rewrite
    assert any(e["type"] == "answer_reset" for e in events)
    answer = _reconstruct_answer(events)
    assert answer == payload["rewritten_answer"]
    assert "普遍认为" not in answer
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["answer_permission"] == "partially_grounded"
    # A gated, safe answer is NOT a warning — it's verified with a neutral footer.
    assert citation["audit_status"] == "verified"
    assert citation["status"] == "ok"
    assert citation["cited_ids"] == ["E1"] and citation["missing_ids"] == []
    assert citation["grounding_summary"]["limited"] == 1
    assert citation["grounding_summary"]["unsupported"] == 0  # final answer has none


def test_rewrite_with_fabricated_id_is_still_audited(tmp_path):
    registry, _store, _sid = _registry(tmp_path)
    # A misbehaving grounding rewrite that invents an id must still be caught by the
    # deterministic citation audit running on the FINAL answer.
    payload = {
        "claims": [{"claim": "c", "support_status": "partially_supported", "evidence_ids": ["E1"],
                    "rewrite_action": "downgrade"}],
        "answer_permission": "partially_grounded",
        "rewritten_answer": "据某研究膜通量约 30 [E1]，另有数据 [E999]。",
    }
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
        [{"type": "content", "text": "膜通量约 30 [E1]。"}],
        _grounding_script(payload),
    ])
    loop = AgentLoop(llm, registry, grounding_mode="strict")
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["status"] == "warning"
    assert citation["missing_ids"] == ["E999"]


def test_no_evidence_question_not_answerable(tmp_path):
    registry, _store, _sid = _registry(tmp_path)
    # Model answers WITHOUT searching → no citable evidence → deterministic not_answerable.
    llm = ScriptedLLM([[{"type": "content", "text": "膜通量大约是 30 左右。"}]])
    loop = AgentLoop(llm, registry, grounding_mode="strict")
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["answer_permission"] == "not_answerable"
    assert citation["available_count"] == 0
    # (d) the body itself is REPLACED by the honest non-answer, not labelled.
    answer = _reconstruct_answer(events)
    assert answer == g.NOT_ANSWERABLE_MESSAGE
    assert "30 左右" not in answer
    assert any(e["type"] == "answer_reset" for e in events)
    # not a warning: the body now openly states the limitation.
    assert citation["audit_status"] == "verified"
    assert citation["status"] == "ok"


def test_strict_rewrite_separates_removed_claims(tmp_path):
    registry, _store, _sid = _registry(tmp_path)
    # Draft mixes a supported claim and an unsupported one; the final record must
    # describe survivors (in the answer) and list the removed one separately for
    # transparency — never as "unsupported claims sitting in the answer".
    payload = {
        "claims": [
            {"claim": "通量约 30", "support_status": "supported", "evidence_ids": ["E1"], "rewrite_action": "keep"},
            {"claim": "该方法已被普遍证明", "support_status": "unsupported", "evidence_ids": [], "rewrite_action": "remove"},
        ],
        "answer_permission": "partially_grounded",
        "rewritten_answer": "膜通量约 30 L/m2h [E1]。",
    }
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
        [{"type": "content", "text": "膜通量约 30 [E1]，该方法已被普遍证明。"}],
        _grounding_script(payload),
    ])
    loop = AgentLoop(llm, registry, grounding_mode="strict")
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    gr = citation["grounding"]
    assert [c["claim"] for c in gr["claims"]] == ["通量约 30"]  # only the survivor
    assert [c["claim"] for c in gr["removed_claims"]] == ["该方法已被普遍证明"]
    s = citation["grounding_summary"]
    assert s["supported"] == 1 and s["unsupported"] == 0 and s["removed"] == 1
    assert "rewritten_answer" not in gr  # internal draft artifact not surfaced


def test_conflicting_evidence_surfaced(tmp_path):
    registry, _store, _sid = _registry(tmp_path)
    payload = {
        "claims": [{"claim": "通量为 30", "support_status": "conflicting", "evidence_ids": ["E1"],
                    "rewrite_action": "downgrade"}],
        "answer_permission": "conflicting",
        "conflicting_claims": ["一项研究报告 30，另一项报告 50。"],
        "rewritten_answer": "证据存在冲突：一项研究为 30，另一项为 50 [E1]。",
    }
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
        [{"type": "content", "text": "膜通量为 30 [E1]。"}],
        _grounding_script(payload),
    ])
    loop = AgentLoop(llm, registry, grounding_mode="strict")
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert citation["answer_permission"] == "conflicting"
    assert citation["grounding"]["conflicting_claims"]


def test_grounding_off_leaves_citation_unchanged(tmp_path):
    registry, _store, _sid = _registry(tmp_path)
    llm = ScriptedLLM([
        [{"type": "tool_call", "id": "c1", "name": "search", "arguments": {"query": "flux"}}],
        [{"type": "content", "text": "膜通量约 30 [E1]。"}],
    ])
    loop = AgentLoop(llm, registry)  # default grounding_mode="off"
    events = asyncio.run(_drain(loop.run("膜通量", [], None)))
    citation = next(e for e in events if e["type"] == "citation")
    assert "grounding" not in citation
    assert citation["status"] == "ok"
