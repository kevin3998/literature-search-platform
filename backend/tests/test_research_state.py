from __future__ import annotations

from core.schemas import ChatMessage


def _seed_search(store, session_id, *, turn_query, papers, coverage=None, breadth=None):
    turn_id = store.create_turn(session_id, query=turn_query)
    store.append(session_id, ChatMessage(role="user", content=turn_query), turn_id=turn_id)
    store.record_search_result(
        session_id,
        turn_id,
        {
            "query": turn_query,
            "query_plan": {"retrieval_used": "fts"},
            "results": papers,
            "coverage": coverage or {},
            "breadth": breadth or {},
        },
    )
    store.complete_turn(turn_id)
    return turn_id


def _paper(doi, title, evidence_ids, confidence="high"):
    return {
        "doi": doi,
        "title": title,
        "evidence": [
            {
                "evidence_id": eid,
                "snippet": f"snippet for {eid}",
                "source_path": f"articles/{doi}/parsed/fulltext.md",
                "section": "Results",
                "confidence": confidence,
            }
            for eid in evidence_ids
        ],
    }


def _store(tmp_path):
    from core.session_store import SessionStore

    return SessionStore(db_path=tmp_path / "memory.sqlite")


def test_candidate_papers_derived_from_evidence(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="LLM review agents")["session_id"]
    _seed_search(
        store,
        sid,
        turn_query="claim-level citation",
        papers=[_paper("10.1/a", "Paper A", ["E1", "E2"]), _paper("10.1/b", "Paper B", ["E3"])],
    )

    state = store.research_state(sid)
    papers = {p["doi"]: p for p in state["candidate_papers"]}
    assert set(papers) == {"10.1/a", "10.1/b"}
    # derived counts + default status, no authored override yet
    assert papers["10.1/a"]["evidence_count"] == 2
    assert papers["10.1/b"]["evidence_count"] == 1
    assert papers["10.1/a"]["status"] == "candidate"
    assert state["paper_status_counts"] == {"candidate": 2}
    assert state["evidence_pool"]["total"] == 3
    assert state["evidence_pool"]["by_confidence"]["high"] == 3


def test_paper_status_override_and_provenance(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    tid = _seed_search(store, sid, turn_query="q", papers=[_paper("10.1/a", "A", ["E1"])])

    store.set_paper_status(sid, "10.1/a", "accepted", note="keep", source="user", turn_id=tid)
    state = store.research_state(sid)
    paper = state["candidate_papers"][0]
    assert paper["status"] == "accepted"
    assert paper["note"] == "keep"
    assert state["paper_status_counts"] == {"accepted": 1}

    # provenance: the curation is logged with its turn + source
    events = state["provenance"]
    assert any(
        e["field"] == "paper_status" and e["value"]["status"] == "accepted" and e["turn_id"] == tid
        for e in events
    )


def test_evidence_status_override_counts_provenance_and_digest(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    tid = _seed_search(store, sid, turn_query="q", papers=[_paper("10.1/a", "A", ["E1", "E2"])])
    state = store.research_state(sid)
    by_eid = {item["evidence_id"]: item for item in state["evidence_pool"]["recent"]}

    store.set_evidence_status(
        sid,
        by_eid["E1"]["evidence_item_id"],
        "accepted",
        note="关键机制证据",
        source="user",
        turn_id=tid,
    )
    store.set_evidence_status(sid, by_eid["E2"]["evidence_item_id"], "excluded", source="user")
    state = store.research_state(sid)
    by_eid = {item["evidence_id"]: item for item in state["evidence_pool"]["recent"]}

    assert by_eid["E1"]["status"] == "accepted"
    assert by_eid["E1"]["note"] == "关键机制证据"
    assert by_eid["E1"]["status_source"] == "user"
    assert by_eid["E2"]["status"] == "excluded"
    assert state["evidence_pool"]["status_counts"] == {"accepted": 1, "excluded": 1}
    assert any(
        e["field"] == "evidence_status" and e["value"]["status"] == "accepted" and e["turn_id"] == tid
        for e in state["provenance"]
    )

    digest = store.research_state_digest(sid)
    assert digest["accepted_evidence"][0]["evidence_id"] == "E1"
    assert digest["excluded_evidence"][0]["evidence_id"] == "E2"


def test_authored_state_set_get_and_restore(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    store.update_research_state(
        sid,
        objective="map claim-level citation benchmarks",
        stage="evidence curation",
        open_questions=["is there a claim-level benchmark?"],
        excluded_directions=["pure recommender systems"],
        source="user",
    )

    # a fresh store over the SAME db file = simulate refresh / reopen
    reopened = _store(tmp_path)
    state = reopened.research_state(sid)
    assert state["objective"] == "map claim-level citation benchmarks"
    assert state["stage"] == "evidence curation"
    assert state["open_questions"] == ["is there a claim-level benchmark?"]
    assert state["excluded_directions"] == ["pure recommender systems"]


def test_empty_session_has_safe_defaults(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="新对话")["session_id"]
    state = store.research_state(sid)
    assert state["candidate_papers"] == []
    assert state["evidence_pool"]["total"] == 0
    assert state["coverage_gaps"] == {}
    assert state["stage"] == "retrieval"
    assert state["open_questions"] == []
    # topic falls back to the session title when objective never authored
    assert state["topic"] == "新对话"


def test_coverage_gaps_track_latest_turn(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    _seed_search(store, sid, turn_query="first", papers=[_paper("10.1/a", "A", ["E1"])],
                 coverage={"sufficient": True})
    _seed_search(store, sid, turn_query="second", papers=[_paper("10.1/b", "B", ["E2"])],
                 coverage={"sufficient": False, "missing": ["benchmark"]})

    gaps = store.research_state(sid)["coverage_gaps"]
    assert gaps["from_query"] == "second"
    assert gaps["coverage"]["sufficient"] is False
    assert gaps["coverage"]["missing"] == ["benchmark"]


def test_research_state_endpoint(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.modules_router as modules_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", store)
    client = TestClient(main.app)

    sid = store.create_session(module_id="literature_search", title="endpoint")["session_id"]
    _seed_search(store, sid, turn_query="q", papers=[_paper("10.1/a", "A", ["E1"])])
    store.set_paper_status(sid, "10.1/a", "accepted")

    body = client.get(f"/api/sessions/{sid}/research-state").json()
    assert body["session_id"] == sid
    assert body["candidate_papers"][0]["status"] == "accepted"
    assert body["evidence_pool"]["total"] == 1


def test_digest_none_until_curated_then_steers(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    _seed_search(store, sid, turn_query="q", papers=[
        _paper("10.1/a", "Keep Me", ["E1"]), _paper("10.1/b", "Drop Me", ["E2"])
    ])
    # nothing authored yet → digest is None so brand-new 课题 prompts stay clean
    assert store.research_state_digest(sid) is None
    # the per-turn memory context also carries None
    assert store.get_context(sid)["research_state"] is None

    store.set_paper_status(sid, "10.1/a", "accepted")
    store.set_paper_status(sid, "10.1/b", "excluded")
    store.update_research_state(sid, objective="map benchmarks",
                                excluded_directions=["recommender systems"])

    digest = store.research_state_digest(sid)
    assert digest["objective"] == "map benchmarks"
    assert [p["title"] for p in digest["accepted_papers"]] == ["Keep Me"]
    assert [p["title"] for p in digest["excluded_papers"]] == ["Drop Me"]
    assert digest["excluded_directions"] == ["recommender systems"]


def test_memory_block_renders_authored_state(tmp_path):
    # the prompt block must surface retained/excluded papers + directions so the
    # agent honours curation on the next turn ("继续").
    from modules.literature_search.agent.loop import _memory_block

    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    _seed_search(store, sid, turn_query="q", papers=[
        _paper("10.1/a", "Keep Me", ["E1"]), _paper("10.1/b", "Drop Me", ["E2"])
    ])
    store.set_paper_status(sid, "10.1/a", "accepted")
    store.set_paper_status(sid, "10.1/b", "excluded")
    store.update_research_state(sid, objective="map benchmarks",
                                open_questions=["is there a benchmark?"])

    block = _memory_block(store.get_context(sid))
    assert "研究目标：map benchmarks" in block
    assert "Keep Me" in block        # retained → reuse
    assert "Drop Me" in block        # excluded → don't cite
    assert "is there a benchmark?" in block

    # an uncurated session injects no research-state header
    sid2 = store.create_session(module_id="literature_search", title="t2")["session_id"]
    assert "当前课题研究状态" not in _memory_block(store.get_context(sid2))


def test_curation_endpoints(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    db_path = tmp_path / "memory.sqlite"
    monkeypatch.setenv("LITERATURE_MEMORY_DB_PATH", str(db_path))

    import api.modules_router as modules_router
    import main
    from core.session_store import SessionStore

    store = SessionStore(db_path=db_path)
    monkeypatch.setattr(modules_router, "session_store", store)
    client = TestClient(main.app)

    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    _seed_search(store, sid, turn_query="q", papers=[_paper("10.1/a", "A", ["E1"])])

    r1 = client.post(f"/api/sessions/{sid}/paper-status",
                     json={"paper_id": "10.1/a", "status": "accepted"})
    assert r1.status_code == 200
    assert r1.json()["candidate_papers"][0]["status"] == "accepted"

    r2 = client.patch(f"/api/sessions/{sid}/research-state",
                      json={"objective": "obj", "open_questions": ["q1"]})
    assert r2.status_code == 200
    body = r2.json()
    assert body["objective"] == "obj"
    assert body["open_questions"] == ["q1"]

    evidence_item_id = body["evidence_pool"]["recent"][0]["evidence_item_id"]
    r3 = client.post(
        f"/api/sessions/{sid}/evidence-status",
        json={"evidence_item_id": evidence_item_id, "status": "needs_review", "note": "复核来源"},
    )
    assert r3.status_code == 200
    evidence = r3.json()["evidence_pool"]["recent"][0]
    assert evidence["status"] == "needs_review"
    assert evidence["note"] == "复核来源"


def test_state_survives_only_until_session_delete(tmp_path):
    store = _store(tmp_path)
    sid = store.create_session(module_id="literature_search", title="t")["session_id"]
    _seed_search(store, sid, turn_query="q", papers=[_paper("10.1/a", "A", ["E1"])])
    store.set_paper_status(sid, "10.1/a", "excluded")
    evidence_item_id = store.research_state(sid)["evidence_pool"]["recent"][0]["evidence_item_id"]
    store.set_evidence_status(sid, evidence_item_id, "accepted")
    # cascade: hard-deleting the session removes paper_states / research_state rows
    store.conn.execute("delete from sessions where session_id = ?", (sid,))
    store.conn.commit()
    remaining = store.conn.execute(
        "select count(*) from paper_states where session_id = ?", (sid,)
    ).fetchone()[0]
    assert remaining == 0
    remaining_evidence = store.conn.execute(
        "select count(*) from evidence_states where session_id = ?", (sid,)
    ).fetchone()[0]
    assert remaining_evidence == 0
