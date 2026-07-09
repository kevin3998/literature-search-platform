from __future__ import annotations

from core.schemas import ChatMessage


def _seed_turn(store, session_id):
    turn_id = store.create_turn(session_id, query="膜通量是多少")
    store.append(session_id, ChatMessage(role="user", content="膜通量是多少"), turn_id=turn_id)
    store.record_search_result(
        session_id,
        turn_id,
        {
            "query": "membrane water flux",
            "query_plan": {"retrieval_used": "fts"},
            "results": [
                {
                    "doi": "10.1/x",
                    "title": "Membrane Paper",
                    "evidence": [
                        {
                            "evidence_id": "E1",
                            "snippet": "water flux 30 L/m2h",
                            "source_path": "articles/x/parsed/fulltext.md",
                            "section": "Results",
                            "confidence": "high",
                        }
                    ],
                }
            ],
        },
    )
    store.record_artifact(
        {"artifact_id": "research_agent/packs/pack-1.json", "artifact_type": "pack", "title": "pack-1", "path": "research_agent/packs/pack-1.json"},
        session_id=session_id,
        turn_id=turn_id,
        link_type="pack",
    )
    store.append(
        session_id,
        ChatMessage(role="assistant", content="膜通量约 30 L/m2h [E1]。"),
        turn_id=turn_id,
        metadata={"citation": {"status": "ok", "cited_ids": ["E1"], "missing_ids": []}},
    )
    store.complete_turn(turn_id)
    return turn_id


def test_build_record_assembles_full_chain(tmp_path):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    session = store.create_session(module_id="literature_search", title="膜分离调研")
    _seed_turn(store, session["session_id"])

    record = store.build_record(session["session_id"])
    assert record["session"]["title"] == "膜分离调研"
    assert len(record["turns"]) == 1
    turn = record["turns"][0]
    assert turn["query"] == "膜通量是多少"
    assert "[E1]" in turn["answer"]
    assert turn["citation"]["status"] == "ok"
    assert turn["searches"][0]["retrieval_used"] == "fts"
    assert turn["searches"][0]["result_count"] == 1
    assert any(e["evidence_id"] == "E1" for e in turn["evidence"])
    assert any(a["artifact_type"] == "pack" for a in turn["artifacts"])


def test_markdown_export_is_citable(tmp_path):
    from core.report import render_markdown_report, report_filename
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    session = store.create_session(module_id="literature_search", title="膜分离调研")
    _seed_turn(store, session["session_id"])

    record = store.build_record(session["session_id"])
    md = render_markdown_report(record)

    assert "# 膜分离调研" in md
    assert "膜通量是多少" in md
    assert "膜通量约 30 L/m2h [E1]" in md
    assert "## 来源汇总" in md
    assert "[E1]" in md
    assert "articles/x/parsed/fulltext.md" in md  # traceable to local file

    fname = report_filename(record)
    assert fname.endswith(".md")


def test_export_flags_citation_warning(tmp_path):
    from core.report import render_markdown_report
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    session = store.create_session(module_id="literature_search", title="t")
    turn_id = store.create_turn(session["session_id"], query="q")
    store.append(session["session_id"], ChatMessage(role="user", content="q"), turn_id=turn_id)
    store.append(
        session["session_id"],
        ChatMessage(role="assistant", content="答案 [E9]。"),
        turn_id=turn_id,
        metadata={"citation": {"status": "warning", "cited_ids": ["E9"], "missing_ids": ["E9"]}},
    )
    store.complete_turn(turn_id)

    md = render_markdown_report(store.build_record(session["session_id"]))
    assert "引用校验警告" in md


def test_delete_last_turn_removes_chain(tmp_path):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    session = store.create_session(module_id="literature_search", title="t")
    sid = session["session_id"]
    _seed_turn(store, sid)  # turn 1
    # second turn to delete
    t2 = store.create_turn(sid, query="第二个问题")
    store.append(sid, ChatMessage(role="user", content="第二个问题"), turn_id=t2)
    store.append(sid, ChatMessage(role="assistant", content="答复二"), turn_id=t2)
    store.complete_turn(t2)

    assert len(store.messages(sid)) == 4  # 2 turns x (user+assistant)

    deleted_text = store.delete_last_turn(sid)
    assert deleted_text == "第二个问题"

    msgs = store.messages(sid)
    assert len(msgs) == 2  # only the first turn remains
    assert all(m["content"] not in {"第二个问题", "答复二"} for m in msgs)
    # the first turn's record is intact
    record = store.build_record(sid)
    assert len(record["turns"]) == 1

    # deleting again removes the first turn; a third call returns None
    assert store.delete_last_turn(sid) == "膜通量是多少"
    assert store.delete_last_turn(sid) is None
