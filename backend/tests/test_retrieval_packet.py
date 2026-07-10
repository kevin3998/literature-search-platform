"""Block 2 retrieval / evidence acquisition regression set.

Covers the acceptance matrix from
``docs/capability-blocks/block-02-retrieval-evidence-acquisition.md``:
intent detection, deterministic rewrite, no-hit recovery, candidate
normalization, single-paper dominance, table boost, and coverage judgment.
"""
from __future__ import annotations

from modules.literature_search.retrieval import build_packet
from modules.literature_search.retrieval.intent import detect_intent
from modules.literature_search.retrieval.rewrite import normalize_doi, relax_query, rewrite_query
from modules.literature_search.retrieval.schemas import EvidenceCandidate, QueryIntent
from modules.literature_search.retrieval.selector import select_evidence


# --- fixtures -------------------------------------------------------------------

def _evidence(eid, paper, *, kind="section_chunk", section="Results", score=10.0, conf=0.7, year=2023):
    return {
        "evidence_id": eid,
        "paper_id": paper,
        "doi": paper,
        "article_id": int(eid[1:]),
        "title": f"Paper {paper}",
        "kind": kind,
        "section": section,
        "snippet": f"snippet for {eid}",
        "source_path": f"articles/{paper}/parsed/fulltext.md",
        "confidence": conf,
        "score": score,
    }


def _result(paper, evidence, *, year=2023):
    return {
        "paper_id": paper,
        "doi": paper,
        "article_id": int(evidence[0]["evidence_id"][1:]),
        "title": f"Paper {paper}",
        "year": year,
        "journal": "J. Test",
        "evidence": evidence,
    }


def _make_search(results, *, retrieval_used="fts", vector_reason="vector index not built"):
    """Return a search_fn that yields `results` and records the queries it saw."""
    calls: list[dict] = []

    def search_fn(query, **options):
        calls.append({"query": query, **options})
        return {
            "query": query,
            "retrieval": retrieval_used,
            "query_plan": {
                "retrieval_requested": options.get("retrieval", "hybrid"),
                "retrieval_used": retrieval_used,
                "vector_unavailable_reason": vector_reason,
                "filters_applied": {"scope": "library"},
            },
            "filters": {"year_from": options.get("year_from")},
            "results": results,
        }

    search_fn.calls = calls  # type: ignore[attr-defined]
    return search_fn


# --- intent detection -----------------------------------------------------------

def test_intent_doi():
    intent = detect_intent("what does 10.1234/abcd.5678 say about flux")
    assert intent.type == "doi"
    assert intent.detected_entities["doi"].startswith("10.1234/")


def test_intent_title_quoted():
    intent = detect_intent('find the paper titled "Attention Is All You Need"')
    assert intent.type == "title"
    assert "Attention" in intent.detected_entities["title"]


def test_intent_recent_review_beats_mechanism():
    # mentions both "mechanism" and "recent" -> recency wins (review-shaped)
    intent = detect_intent("recent advances in the mechanism of RAG")
    assert intent.type == "recent_review"


def test_intent_metric_compare():
    assert detect_intent("compare power density across MXene papers").type == "metric_compare"


def test_intent_mechanism():
    assert detect_intent("how does the SEI layer form").type == "mechanism"


def test_intent_topic_default():
    assert detect_intent("graphene oxide membranes for desalination").type == "topic"


def test_intent_followup_needs_history():
    assert detect_intent("还有别的吗", has_history=False).type != "followup"
    assert detect_intent("还有别的吗", has_history=True).type == "followup"


# --- rewrite --------------------------------------------------------------------

def test_normalize_doi_strips_url_and_case():
    assert normalize_doi("https://doi.org/10.1234/ABCD.5678.") == "10.1234/abcd.5678"


def test_rewrite_expands_abbreviations():
    intent = QueryIntent(type="topic")
    queries = [rw.query for rw in rewrite_query("RAG for science", intent)]
    assert any("retrieval augmented generation" in q for q in queries)


def test_rewrite_chinese_llm_materials_topic_uses_english_retrieval_alias_first():
    intent = QueryIntent(type="topic")
    queries = [rw.query for rw in rewrite_query("大语言模型在材料发现中的应用", intent)]

    assert queries[0] == "large language models materials discovery"
    assert "大语言模型在材料发现中的应用" in queries


def test_rewrite_english_research_question_uses_high_signal_terms_first():
    intent = QueryIntent(type="topic")
    queries = [rw.query for rw in rewrite_query("What papers discuss Martian soil simulants for building materials?", intent)]

    assert queries[0] == "Martian soil simulants building materials"
    assert "What papers discuss Martian soil simulants for building materials?" in queries


def test_rewrite_recent_adds_recency_hint():
    intent = QueryIntent(type="recent_review")
    reasons = [rw.reason for rw in rewrite_query("progress in solar cells", intent)]
    assert any("recency" in r for r in reasons)


def test_relax_query_keeps_high_signal_terms():
    relaxed = relax_query("what is the best method for the desalination membranes")
    assert "desalination" in relaxed
    assert "the" not in relaxed.split()


# --- selector -------------------------------------------------------------------

def test_selector_limits_single_paper_dominance():
    # one paper with 10 evidence rows, plus two other papers
    cands = [EvidenceCandidate(evidence_id=f"E{i}", paper_id="P1", relevance_score=10.0, confidence=0.9)
             for i in range(10)]
    cands += [EvidenceCandidate(evidence_id="E100", paper_id="P2", relevance_score=5.0, confidence=0.5)]
    cands += [EvidenceCandidate(evidence_id="E101", paper_id="P3", relevance_score=5.0, confidence=0.5)]
    selected = select_evidence(cands, QueryIntent(type="topic"), per_article_limit=3, total_limit=20)
    from collections import Counter
    counts = Counter(c.paper_id for c in selected)
    assert counts["P1"] <= 3
    assert {"P2", "P3"} <= set(counts)


def test_selector_boosts_table_for_metric_queries():
    table = EvidenceCandidate(evidence_id="E1", paper_id="P1", kind="table_row", relevance_score=1.0, confidence=0.1)
    para = EvidenceCandidate(evidence_id="E2", paper_id="P2", kind="paragraph", relevance_score=1.0, confidence=0.1)
    selected = select_evidence([para, table], QueryIntent(type="metric_compare"))
    assert selected[0].evidence_id == "E1"  # table_row ranked first


def test_selector_removes_equivalent_abstract_sources_before_context_budget():
    abstract = " ".join(["The abstract reports stable membrane performance under cyclic operation."] * 8)
    candidates = [
        EvidenceCandidate(
            evidence_id="E10",
            paper_id="P1",
            doi="10.1/example",
            kind="abstract",
            section="Abstract",
            source_path="articles/example/parsed/abstract.txt",
            snippet="opening search window from the dedicated abstract",
            expanded_context=abstract,
            relevance_score=1.0,
            confidence=0.8,
        ),
        EvidenceCandidate(
            evidence_id="E11",
            paper_id="P1",
            doi="10.1/example",
            kind="section_chunk",
            section="Abstract",
            section_id="s0002-abstract",
            chunk_index=1,
            source_path="articles/example/parsed/fulltext.md",
            snippet="different matched-sentence window from the full text",
            expanded_context=abstract,
            relevance_score=0.95,
            confidence=0.8,
        ),
        EvidenceCandidate(
            evidence_id="E12",
            paper_id="P1",
            doi="10.1/example",
            kind="section_chunk",
            section="Results",
            section_id="s0004-results",
            chunk_index=1,
            source_path="articles/example/parsed/fulltext.md",
            snippet="The measured flux remained stable for 100 cycles.",
            relevance_score=0.9,
            confidence=0.8,
        ),
    ]

    selected = select_evidence(candidates, QueryIntent(type="topic"), context_limit=3)

    assert len(selected) == 2
    assert "E12" in {candidate.evidence_id for candidate in selected}
    assert sum(candidate.section == "Abstract" for candidate in selected) == 1
    assert sum(candidate.in_llm_context for candidate in selected) == 2


# --- packet build ---------------------------------------------------------------

def test_packet_preserves_underlying_evidence_id():
    search_fn = _make_search([_result("P1", [_evidence("E5", "P1")])])
    packet = build_packet(search_fn, "graphene membranes", options={}).as_dict()
    ids = [c["evidence_id"] for c in packet["evidence_candidates"]]
    assert ids == ["E5"]  # E{document_id} kept verbatim, not re-minted


def test_packet_uses_chinese_topic_english_alias_against_english_index():
    def search_fn(query, **options):
        if query == "large language models materials discovery":
            results = [_result("P1", [_evidence("E1", "P1")])]
        else:
            results = []
        return {
            "query": query,
            "retrieval": options.get("retrieval", "hybrid"),
            "query_plan": {
                "retrieval_requested": options.get("retrieval", "hybrid"),
                "retrieval_used": "fts",
                "vector_unavailable_reason": "",
                "filters_applied": {"scope": "library"},
            },
            "results": results,
        }

    search_fn.calls = []
    original = search_fn

    def recording_search(query, **options):
        original.calls.append({"query": query, **options})
        return search_fn(query, **options)

    packet = build_packet(recording_search, "大语言模型在材料发现中的应用", options={}).as_dict()

    assert original.calls[0]["query"] == "large language models materials discovery"
    assert packet["query_plan"]["original_query"] == "大语言模型在材料发现中的应用"
    assert packet["evidence_candidates"]


def test_packet_coverage_sufficient_for_topic_with_three_papers():
    results = [_result(f"P{i}", [_evidence(f"E{i}", f"P{i}")]) for i in range(1, 4)]
    packet = build_packet(_make_search(results), "topic question about membranes", options={}).as_dict()
    assert packet["coverage"]["status"] == "sufficient"
    assert packet["coverage"]["distinct_paper_count"] == 3


def test_direct_existence_query_with_adjacent_results_is_not_sufficient():
    results = [
        _result(
            f"P{i}",
            [
                {
                    **_evidence(f"E{i}", f"P{i}"),
                    "title": "Martian soil construction material chemistry",
                    "snippet": "Evidence discusses Martian soil simulant and construction materials for habitats.",
                }
            ],
        )
        for i in range(1, 4)
    ]

    packet = build_packet(_make_search(results), "文献库里有没有关于火星土壤超导材料的论文？", options={}).as_dict()

    assert packet["coverage"]["status"] != "sufficient"
    assert "direct_topic_match" in packet["coverage"]["missing_aspects"]


def test_direct_existence_query_requires_terms_in_same_candidate():
    results = [
        _result(
            "P1",
            [
                {
                    **_evidence("E1", "P1"),
                    "title": "Martian soil construction materials",
                    "snippet": "Martian soil simulant is used for habitat construction materials.",
                }
            ],
        ),
        _result(
            "P2",
            [
                {
                    **_evidence("E2", "P2"),
                    "title": "Superconducting quantum materials",
                    "snippet": "Superconducting materials are discussed for laboratory quantum devices.",
                }
            ],
        ),
        _result(
            "P3",
            [
                {
                    **_evidence("E3", "P3"),
                    "title": "Regolith chemistry",
                    "snippet": "Soil chemistry and materials processing for planetary regolith.",
                }
            ],
        ),
    ]

    packet = build_packet(_make_search(results), "文献库里有没有关于火星土壤超导材料的论文？", options={}).as_dict()

    assert packet["coverage"]["status"] != "sufficient"
    assert "direct_topic_match" in packet["coverage"]["missing_aspects"]


def test_direct_existence_uses_original_user_query_after_llm_rewrite():
    results = [
        _result(
            "P1",
            [
                {
                    **_evidence("E1", "P1"),
                    "title": "Martian soil construction materials",
                    "snippet": "Martian soil simulant is used for habitat construction materials.",
                }
            ],
        ),
        _result(
            "P2",
            [
                {
                    **_evidence("E2", "P2"),
                    "title": "Superconducting tunnel junction detectors",
                    "snippet": "Superconducting detectors are discussed for X-ray absorption measurement.",
                }
            ],
        ),
        _result("P3", [_evidence("E3", "P3")]),
    ]

    packet = build_packet(
        _make_search(results),
        "火星土壤 超导材料 Martian soil superconducting",
        options={"_original_user_query": "文献库里有没有关于火星土壤超导材料的论文？"},
    ).as_dict()

    assert packet["coverage"]["status"] != "sufficient"
    assert "direct_topic_match" in packet["coverage"]["missing_aspects"]


def test_direct_existence_ignores_query_match_reason_as_content():
    candidate = {
        **_evidence("E1", "P1"),
        "title": "Superconducting tunnel junction detectors",
        "snippet": "Superconducting detectors are used for X-ray absorption measurements.",
        "matched_terms": ["martian", "soil", "materials", "superconducting"],
    }

    packet = build_packet(
        _make_search([_result("P1", [candidate]), _result("P2", [_evidence("E2", "P2")]), _result("P3", [_evidence("E3", "P3")])]),
        "火星土壤 超导材料 Martian soil superconducting",
        options={"_original_user_query": "文献库里有没有关于火星土壤超导材料的论文？"},
    ).as_dict()

    assert packet["coverage"]["status"] != "sufficient"
    assert "direct_topic_match" in packet["coverage"]["missing_aspects"]


def test_packet_coverage_weak_for_single_paper_topic():
    packet = build_packet(_make_search([_result("P1", [_evidence("E1", "P1")])]),
                          "broad survey of membranes", options={}).as_dict()
    assert packet["coverage"]["status"] in {"weak", "partial"}
    assert "multiple_papers" in packet["coverage"]["missing_aspects"]


def test_packet_no_hit_recovery_and_fallback_reason():
    search_fn = _make_search([])  # always empty -> exhausts recovery
    packet = build_packet(search_fn, "nonexistent xyzzy topic", options={"year_from": 2024}).as_dict()
    assert packet["coverage"]["status"] == "none"
    assert packet["evidence_candidates"] == []
    assert packet["fallback_reason"]["code"] == "no_results"
    # bounded: primary + MAX_RECOVERY attempts, never fabricates evidence
    assert len(search_fn.calls) == 3
    assert "no_hit_recovery_used" in packet["warnings"]


def test_packet_recovery_drops_filters_on_second_attempt():
    # empty with filters, hit once filters are dropped
    state = {"n": 0}

    def search_fn(query, **options):
        state["n"] += 1
        if options.get("year_from"):
            return {"results": [], "query_plan": {"retrieval_used": "fts", "vector_unavailable_reason": ""}}
        return {"results": [_result("P1", [_evidence("E1", "P1")])],
                "query_plan": {"retrieval_used": "fts", "vector_unavailable_reason": ""}}

    packet = build_packet(search_fn, "membranes 2024", options={"year_from": 2024}).as_dict()
    assert packet["evidence_candidates"]  # recovered after dropping the year filter
    assert "no_hit_recovery_used" in packet["warnings"]


def test_packet_vector_unavailable_is_explicit_but_not_alarming():
    results = [_result(f"P{i}", [_evidence(f"E{i}", f"P{i}")]) for i in range(1, 4)]
    packet = build_packet(_make_search(results), "topic about membranes", options={}).as_dict()
    # FTS-only is the steady state: a calm note, coverage still sufficient
    assert packet["coverage"]["status"] == "sufficient"
    assert any("FTS-only" in n for n in packet["coverage"]["coverage_notes"])
    assert packet["fallback_reason"]["code"] == "vector_index_not_built"


def test_packet_doi_intent_single_hit_is_sufficient():
    search_fn = _make_search([_result("10.1/a", [_evidence("E1", "10.1/a")])])
    packet = build_packet(search_fn, "10.1234/abcd.5678", options={}).as_dict()
    assert packet["query_intent"]["type"] == "doi"
    assert packet["coverage"]["status"] == "sufficient"  # one hit satisfies a DOI lookup
