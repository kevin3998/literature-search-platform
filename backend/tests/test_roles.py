from __future__ import annotations

from modules.literature_search.agent.roles import get_role


class FakeService:
    pass


def _registry(answer_mode, role_tools):
    from core.session_store import SessionStore
    from modules.literature_search.agent.tools import ToolRegistry

    import tempfile, os

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    store = SessionStore(db_path=path)
    return ToolRegistry(
        FakeService(),
        store,
        session_id="s1",
        turn_id=None,
        answer_mode=answer_mode,
        role_tools=role_tools,
    )


def test_general_role_is_unrestricted():
    role = get_role(None)
    assert role.name == "general"
    assert role.tools is None
    assert role.mode is None
    # general in quick mode exposes the full quick tool set
    reg = _registry("quick", role.tools)
    assert set(reg.specs) == {"search", "paper_sections", "paper_chunks", "evidence_expand", "pack"}


def test_retrieval_role_cannot_analyse():
    role = get_role("retrieval")
    assert role.mode == "quick"
    reg = _registry("quick", role.tools)
    names = set(reg.specs)
    # has retrieval tools …
    assert {"search", "pack"} <= names
    # … but the analysis/synthesis/report tools are structurally absent
    assert names.isdisjoint({"extract", "compare", "run", "task_run", "verify_answer", "quality"})


def test_analysis_role_forces_deep_and_exposes_compare():
    role = get_role("analysis")
    assert role.mode == "deep"
    reg = _registry("deep", role.tools)
    names = set(reg.specs)
    assert {"extract", "compare"} <= names
    # but analysis is not a synthesis/report role
    assert names.isdisjoint({"run", "task_run", "verify_answer", "quality"})


def test_report_role_exposes_verify_quality_only():
    role = get_role("report")
    reg = _registry("deep", role.tools)
    names = set(reg.specs)
    assert {"verify_answer", "quality"} <= names
    assert "search" not in names  # report doesn't re-retrieve


def test_unknown_role_falls_back_to_general():
    assert get_role("nonsense").name == "general"


def test_role_recorded_on_turn(tmp_path):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    tid = store.create_turn(sid, query="q", role="analysis")
    record = store.build_record(sid)
    assert record["turns"][0]["role"] == "analysis"


def test_role_prompt_injected_into_messages(tmp_path):
    # the role's boundary statement must reach the system messages so the model
    # honours it; the general role injects nothing extra.
    from modules.literature_search.agent.loop import AgentLoop

    reg = _registry("deep", get_role("analysis").tools)
    loop = AgentLoop(object(), reg, role_prompt=get_role("analysis").prompt)
    sys_msgs = [m["content"] for m in loop._build_messages("q", [], None) if m["role"] == "system"]
    assert any("当前角色：分析" in c for c in sys_msgs)

    reg2 = _registry("quick", get_role("general").tools)
    loop2 = AgentLoop(object(), reg2, role_prompt=get_role("general").prompt)
    sys2 = [m["content"] for m in loop2._build_messages("q", [], None) if m["role"] == "system"]
    assert not any("当前角色" in c for c in sys2)
