"""Block 2 §8 breadth-vs-context-budget regression set.

Covers: candidate-pool / context-evidence separation, intent-aware budgets,
breadth_limited + deep_research_suggested signals, and the lower-bound match
estimate.
"""
from __future__ import annotations

from modules.literature_search.retrieval import build_packet
from modules.literature_search.retrieval.budgets import budgets_for


def _evidence(eid, paper, *, kind="section_chunk", section="Results", score=10.0, conf="high", terms="graphene membrane"):
    return {
        "evidence_id": eid, "paper_id": paper, "doi": paper, "article_id": int(eid[1:]),
        "title": f"Paper {paper}", "kind": kind, "section": section,
        "snippet": f"snippet {eid}", "source_path": f"articles/{paper}/f.md",
        "confidence": conf, "score": score, "matched_terms": terms.split(),
    }


def _result(paper, n_ev=1, *, year=2023):
    ev = [_evidence(f"E{int(paper[1:])*100+i}", paper) for i in range(n_ev)]
    return {"paper_id": paper, "doi": paper, "article_id": int(paper[1:]),
            "title": f"Paper {paper}", "year": year, "journal": "J. Test", "evidence": ev}


def _make_search(results, *, fts_docs=50, retrieval_used="fts", vector_reason="vector_index_not_built"):
    calls = []

    def search_fn(query, **options):
        calls.append({"query": query, **options})
        return {
            "query": query, "retrieval": retrieval_used,
            "query_plan": {
                "retrieval_used": retrieval_used,
                "vector_unavailable_reason": vector_reason,
                "fts_candidate_documents": fts_docs,
                "filters_applied": {},
            },
            "filters": {}, "results": results,
        }

    search_fn.calls = calls  # type: ignore[attr-defined]
    return search_fn


def test_budgets_are_intent_aware():
    doi = budgets_for("doi")
    review = budgets_for("recent_review")
    assert doi["candidate_pool"] < review["candidate_pool"]
    assert doi["llm_context"] <= doi["selection_pool"] <= doi["candidate_pool"]
    # context is always bounded below the pool for broad intents
    assert review["llm_context"] < review["candidate_pool"]


def test_candidate_pool_drives_search_limit():
    search_fn = _make_search([_result(f"P{i}", 2) for i in range(1, 13)])
    build_packet(search_fn, "graphene oxide membranes for water", options={})
    # topic budget candidate_pool = 60 should be the limit passed down, NOT 8.
    assert search_fn.calls[0]["limit"] == budgets_for("topic")["candidate_pool"]


def test_context_evidence_bounded_below_candidate_pool():
    # 12 papers x 3 evidence = 36 candidates; topic context budget = 15.
    results = [_result(f"P{i}", 3) for i in range(1, 13)]
    packet = build_packet(_make_search(results, fts_docs=400), "graphene oxide membrane water desalination", options={}).as_dict()
    b = packet["breadth"]
    assert b["candidate_evidence_count"] > b["llm_context_evidence_count"]
    assert b["llm_context_evidence_count"] <= budgets_for("topic")["llm_context"]
    # evidence_candidates is the selection pool; in_llm_context marks the subset
    in_ctx = [c for c in packet["evidence_candidates"] if c["in_llm_context"]]
    assert len(in_ctx) == b["llm_context_evidence_count"]
    assert len(packet["evidence_candidates"]) >= len(in_ctx)


def test_breadth_limited_on_broad_saturated_query():
    results = [_result(f"P{i}", 3) for i in range(1, 13)]
    packet = build_packet(_make_search(results, fts_docs=400), "recent advances in solar evaporation", options={}).as_dict()
    b = packet["breadth"]
    assert b["estimate_is_lower_bound"] is True  # fts scan saturated
    assert b["breadth_limited"] is True
    assert packet["coverage"]["breadth_limited"] is True
    assert any("代表性" in n for n in b["breadth_notes"])


def test_deep_research_suggested_on_comprehensive_request():
    results = [_result(f"P{i}", 3) for i in range(1, 13)]
    packet = build_packet(
        _make_search(results, fts_docs=400), "写一篇关于太阳能蒸发的系统综述", options={}
    ).as_dict()
    assert packet["breadth"]["deep_research_suggested"] is True
    assert packet["coverage"]["deep_research_suggested"] is True


def test_narrow_lookup_not_breadth_limited():
    # a DOI lookup with a single hit must not be flagged as a representative sample
    packet = build_packet(_make_search([_result("P1", 1)], fts_docs=1), "10.1234/abcd.5678", options={}).as_dict()
    assert packet["breadth"]["breadth_limited"] is False
    assert packet["breadth"]["deep_research_suggested"] is False
