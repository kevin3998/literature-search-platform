from __future__ import annotations

from modules.literature_search.evidence_identity import evidence_equivalent, physical_evidence_key


def _evidence(**overrides):
    base = {
        "source_namespace": "research_index",
        "evidence_id": "E42",
        "paper_id": "paper-1",
        "doi": "10.1000/example",
        "kind": "section_chunk",
        "section": "Results",
        "section_id": "s0004-results",
        "chunk_index": 1,
        "source_path": "articles/example/parsed/fulltext.md",
        "snippet": "The measured conversion reached 92 percent after ten hours.",
    }
    base.update(overrides)
    return base


def test_same_namespaced_physical_evidence_matches_despite_snippet_window():
    short = _evidence(snippet="conversion reached 92 percent")
    long = _evidence(snippet="The measured conversion reached 92 percent after ten hours under ambient conditions.")

    assert physical_evidence_key(short) == "research_index:E42"
    assert evidence_equivalent(short, long)


def test_pack_local_id_does_not_match_research_index_id():
    indexed = _evidence(evidence_id="E1", source_namespace="research_index")
    packed = _evidence(evidence_id="E1", source_namespace="evidence_pack")

    assert not evidence_equivalent(indexed, packed)


def test_identical_abstract_sources_from_same_paper_are_equivalent():
    text = " ".join(["This study reports a stable catalyst with high conversion under ambient conditions."] * 5)
    abstract_file = _evidence(
        evidence_id="E100",
        kind="abstract",
        section="Abstract",
        section_id=None,
        chunk_index=None,
        source_path="articles/example/parsed/abstract.txt",
        snippet="opening search window from the dedicated abstract",
        canonical_text=text,
    )
    fulltext_abstract = _evidence(
        evidence_id="E101",
        kind="section_chunk",
        section="Abstract",
        section_id="s0002-abstract",
        source_path="articles/example/parsed/fulltext.md",
        snippet="different matched-sentence window from the full text",
        canonical_text=text,
    )

    assert evidence_equivalent(abstract_file, fulltext_abstract)


def test_contained_but_materially_longer_abstract_is_not_equivalent():
    short = " ".join(["Core abstract reports thin-film performance and stability."] * 25)
    long = short + " " + " ".join(["A separate chapter discusses unrelated mechanisms and applications."] * 20)
    first = _evidence(evidence_id="E200", kind="abstract", section="Abstract", snippet=short)
    second = _evidence(evidence_id="E201", kind="section_chunk", section="Abstract", snippet=long)

    assert not evidence_equivalent(first, second)


def test_identical_abstract_text_from_different_papers_is_not_equivalent():
    text = " ".join(["Shared abstract wording used for a controlled identity test."] * 10)
    first = _evidence(evidence_id="E300", paper_id="paper-1", doi="10.1000/one", kind="abstract", section="Abstract", snippet=text)
    second = _evidence(evidence_id="E301", paper_id="paper-2", doi="10.1000/two", kind="abstract", section="Abstract", snippet=text)

    assert not evidence_equivalent(first, second)


def test_different_non_abstract_chunks_remain_distinct_even_with_same_text():
    text = "The same boilerplate sentence appears in more than one substantive section."
    methods = _evidence(evidence_id="E400", section="Methods", section_id="s0003-methods", snippet=text)
    results = _evidence(evidence_id="E401", section="Results", section_id="s0004-results", snippet=text)

    assert not evidence_equivalent(methods, results)
