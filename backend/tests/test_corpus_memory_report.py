"""Block 0: evidence memory + report source audit carry the canonical paper_id."""
from __future__ import annotations

from core.schemas import ChatMessage


def _seed(store, session_id):
    turn_id = store.create_turn(session_id, query="membrane flux?")
    store.append(session_id, ChatMessage(role="user", content="membrane flux?"), turn_id=turn_id)
    store.record_search_result(
        session_id,
        turn_id,
        {
            "query": "membrane water flux",
            "query_plan": {"retrieval_used": "fts"},
            "results": [
                {
                    "doi": "10.1/x",
                    "paper_id": "10.1/x",
                    "title": "Membrane Paper",
                    "evidence": [
                        {
                            "evidence_id": "E1",
                            "paper_id": "10.1/x",
                            "section_id": "results",
                            "chunk_index": 2,
                            "index_version": 3,
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
    store.append(
        session_id,
        ChatMessage(role="assistant", content="约 30 L/m2h [E1]。"),
        turn_id=turn_id,
        metadata={"citation": {"status": "ok", "cited_ids": ["E1"], "missing_ids": []}},
    )
    store.complete_turn(turn_id)
    return turn_id


def test_memory_persists_paper_id(tmp_path):
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    session = store.create_session(module_id="literature_search", title="t")
    _seed(store, session["session_id"])

    record = store.build_record(session["session_id"])
    evidence = record["turns"][0]["evidence"][0]
    assert evidence["paper_id"] == "10.1/x"
    assert evidence["section_id"] == "results"
    assert evidence["chunk_index"] == 2
    assert evidence["index_version"] == 3


def test_report_source_audit_outputs_paper_id_doi_index_version(tmp_path):
    from core.report import render_markdown_report
    from core.session_store import SessionStore

    store = SessionStore(db_path=tmp_path / "memory.sqlite")
    session = store.create_session(module_id="literature_search", title="膜分离")
    _seed(store, session["session_id"])

    md = render_markdown_report(store.build_record(session["session_id"]))
    assert "## 来源汇总" in md
    assert "paper_id: 10.1/x" in md
    assert "DOI: 10.1/x" in md
    assert "index_version: 3" in md
