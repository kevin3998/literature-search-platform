from __future__ import annotations

from sqlalchemy import text

from core.schemas import ChatMessage
from postgres_test_utils import migrated_postgres_schema


def _evidence(**overrides):
    base = {
        "source_type": "literature_search",
        "evidence_id": "E6082756",
        "document_id": 6082756,
        "paper_id": "paper-1",
        "doi": "10.1000/example",
        "title": "Example Paper",
        "year": 2024,
        "journal": "Journal of Tests",
        "section": "Results",
        "section_id": "results",
        "chunk_index": 3,
        "index_version": 4,
        "snippet": "  Water flux increased to 30 L m-2 h-1.  ",
        "source_path": "articles/example/fulltext.md",
        "in_llm_context": True,
    }
    base.update(overrides)
    return base


def test_evidence_uid_is_stable_for_same_chunk_text():
    from modules.literature_search.agent.citations import build_evidence_uid

    first = build_evidence_uid(_evidence(snippet="Water   flux increased to 30."))
    second = build_evidence_uid(_evidence(snippet=" Water flux increased to 30. "))

    assert first == second
    assert first.startswith("ev_")


def test_evidence_uid_changes_when_chunk_text_changes():
    from modules.literature_search.agent.citations import build_evidence_uid

    first = build_evidence_uid(_evidence(snippet="Water flux increased to 30."))
    second = build_evidence_uid(_evidence(snippet="Water flux increased to 45."))

    assert first != second


def test_parse_numeric_citation_markers_dedupes_in_first_seen_order():
    from modules.literature_search.agent.citations import parse_citation_markers

    assert parse_citation_markers("A [2] B 【1】 C [2] D [99]") == ["2", "1", "99"]


def test_registry_only_aliases_prompt_visible_evidence_and_resolves_answer():
    from modules.literature_search.agent.citations import CitationRegistry

    registry = CitationRegistry()
    visible = registry.register_tool_evidence(
        [
            _evidence(evidence_id="E1", snippet="visible evidence", in_llm_context=True),
            _evidence(evidence_id="E2", snippet="hidden evidence", in_llm_context=False),
        ]
    )

    assert [item["alias"] for item in visible] == ["1"]

    resolved = registry.resolve_answer("Supported claim [1]. Missing claim [99].")

    assert resolved["cited_ids"] == ["1", "99"]
    assert resolved["missing_ids"] == ["99"]
    assert [item["alias"] for item in resolved["used_evidence"]] == ["1"]
    assert len(resolved["resolved_citations"]) == 1
    assert resolved["resolved_citations"][0]["chunk_snapshot_text"] == "visible evidence"


def test_registry_finalizes_sparse_current_turn_aliases():
    from modules.literature_search.agent.citations import CitationRegistry

    registry = CitationRegistry()
    # Simulate a long tool turn where many prompt-visible chunks were assigned
    # aliases, but the final answer only uses a sparse subset.
    registry.register_tool_evidence(
        [
            _evidence(evidence_id=f"E{i}", snippet=f"evidence {i}", chunk_index=i)
            for i in range(1, 7)
        ]
    )

    finalized = registry.finalize_answer("A claim [4]. Another claim 【6】. First again [4].")

    assert finalized["answer"] == "A claim [1]. Another claim [2]. First again [1]."
    assert finalized["cited_ids"] == ["1", "2"]
    assert finalized["missing_ids"] == []
    assert [row["alias"] for row in finalized["resolved_citations"]] == ["1", "2"]
    assert finalized["resolved_citations"][0]["source_locator"]["original_alias"] == "4"
    assert finalized["resolved_citations"][1]["source_locator"]["original_alias"] == "6"


def test_audit_mode_reports_verified_for_valid_deterministic_citations():
    from modules.literature_search.agent.loop import AgentLoop

    loop = object.__new__(AgentLoop)
    loop.grounding_mode = "audit"
    loop.enforce_citations = True
    loop._available_evidence = {"1": {"evidence_id": "1"}}

    assert loop._resolve_audit_status(None, ["1"], [], {"1"}) == ("verified", "ok")


def test_process_narration_strip_removes_tool_budget_and_pack_leaks():
    from modules.literature_search.agent.loop import _strip_process_narration

    answer = (
        "pack 没有返回额外内容，不过我已经从搜索中获得了足够的元数据信息。"
        "好的，检索次数已达上限。下面我基于本次新检索到的论文给出概览。\n\n"
        "本轮代表性结果如下 [1]。"
    )

    cleaned = _strip_process_narration(answer)

    assert cleaned == "本轮代表性结果如下 [1]。"


def test_turn_guard_blocks_repeated_paper_chunks_after_timeout():
    from modules.literature_search.agent import orchestration as orch

    guard = orch.TurnGuard()
    guard.record("paper_chunks", {"doi": "10.1/a"}, is_error=True)
    guard.record_error_code("paper_chunks", "timeout")

    reason = guard.block_reason("paper_chunks", {"doi": "10.1/b"})

    assert reason is not None
    assert "paper_chunks" in reason or "论文文本" in reason


def test_session_store_records_and_returns_message_citations(tmp_path):
    from core.db.engine import engine_for_url
    from modules.literature_search.agent.citations import CitationRegistry

    user_id = "00000000-0000-0000-0000-000000000001"

    with migrated_postgres_schema() as (url, schema):
        from core.session_store import SessionStore

        engine = engine_for_url(url, schema=schema)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        insert into users(user_id, display_name, status, metadata_json, created_at, updated_at)
                        values(:user_id, 'Test User', 'active', '{}'::jsonb, now(), now())
                        """
                    ),
                    {"user_id": user_id},
                )
            store = SessionStore(engine=engine)
            session = store.create_session(module_id="literature_search", title="t", user_id=user_id)
            turn_id = store.create_turn(session["session_id"], query="q", user_id=user_id)
            store.append(session["session_id"], ChatMessage(role="user", content="q"), turn_id=turn_id, user_id=user_id)
            message_id = store.append(
                session["session_id"],
                ChatMessage(role="assistant", content="answer [1]"),
                turn_id=turn_id,
                metadata={"citation": {"cited_ids": ["1"], "used_evidence": []}},
                user_id=user_id,
            )

            registry = CitationRegistry()
            registry.register_tool_evidence([_evidence(evidence_id="E1", snippet="Full evidence chunk")])
            resolved = registry.resolve_answer("answer [1]")
            rows = store.record_message_citations(message_id, resolved["resolved_citations"])

            assert rows[0]["alias"] == "1"
            assert rows[0]["chunk_snapshot_text"] == "Full evidence chunk"
            assert store.message_citations(message_id)[0]["paper_snapshot"]["title"] == "Example Paper"

            messages = store.messages(session["session_id"], user_id=user_id)
            assert messages[-1]["metadata"]["citation"]["used_evidence"][0]["alias"] == "1"

            context = store.get_context(session["session_id"], user_id=user_id)
            assert context["recent_citations"][0]["citations"][0]["alias"] == "1"
        finally:
            engine.dispose()
