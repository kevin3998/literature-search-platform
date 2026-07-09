from pathlib import Path

import pytest

from modules.evidence_workflow.retrieval import (
    EvidenceSourceCandidatePacket,
    retrieve_source_candidates,
    source_candidate_packet_from_acquisition,
)
from modules.evidence_workflow.task_profiles import resolve_task_profile


def _acquisition_packet(*, evidence_candidates=None, expanded_assets=None, warnings=None, coverage_notes=None):
    return {
        "query": "battery interface stability",
        "query_plan": {"final_retrieval_used": "fts", "filters_applied": {"scope": "library"}},
        "coverage": {"status": "partial", "evidence_count": len(evidence_candidates or [])},
        "breadth": {"candidate_evidence_count": len(evidence_candidates or [])},
        "evidence_candidates": evidence_candidates or [],
        "expanded_assets": expanded_assets or [],
        "warnings": warnings or [],
        "coverage_notes": coverage_notes or [],
    }


def _text_candidate(evidence_id="E1", kind="section_chunk", snippet="The interface remained stable.") -> dict:
    return {
        "evidence_id": evidence_id,
        "paper_id": "P1",
        "doi": "10.1000/p1",
        "title": "Interface Paper",
        "year": 2024,
        "journal": "Journal of Interfaces",
        "kind": kind,
        "section_id": "results",
        "chunk_index": 2,
        "snippet": snippet,
        "source_path": "papers/P1/fulltext.md",
        "source_locator": {"section": "Results", "chunk_index": 2},
        "relevance_score": 0.91,
    }


def test_retrieve_source_candidates_calls_acquire_evidence_with_scope_and_budget() -> None:
    calls = []

    def acquire_evidence(query, *, has_history=False, **options):
        calls.append({"query": query, "has_history": has_history, "options": options})
        return _acquisition_packet(evidence_candidates=[_text_candidate()])

    packet = retrieve_source_candidates(
        acquire_evidence,
        topic="battery interface stability",
        scope_lock={
            "topic": "battery interface stability",
            "scope": "collection",
            "scope_options": {"year_from": 2020, "journal": "Journal of Interfaces"},
            "task_profile_id": "topic-to-report",
            "locked_at": 123.0,
        },
        retrieval_budget=7,
    )

    assert isinstance(packet, EvidenceSourceCandidatePacket)
    assert calls == [
        {
            "query": "battery interface stability",
            "has_history": False,
            "options": {
                "scope": "collection",
                "year_from": 2020,
                "journal": "Journal of Interfaces",
                "limit": 7,
                "expand_assets": True,
            },
        }
    ]
    assert packet.retrieval_budget == 7
    assert packet.retrieval_options["scope"] == "collection"
    assert packet.retrieval_options["expand_assets"] is True


def test_text_and_abstract_candidates_generate_seed_dicts_with_provenance() -> None:
    candidates = [
        _text_candidate("E1", kind="section_chunk", snippet="Full text evidence."),
        _text_candidate("E2", kind="abstract", snippet="Abstract evidence."),
    ]

    packet = source_candidate_packet_from_acquisition(
        _acquisition_packet(evidence_candidates=candidates),
        topic="battery interface stability",
        task_profile=resolve_task_profile("topic-to-report"),
        scope_lock={"topic": "battery interface stability", "scope": "library", "scope_options": {}, "task_profile_id": "topic-to-report", "locked_at": 1.0},
        retrieval_budget=24,
    ).as_dict()

    assert [seed["source_evidence_id"] for seed in packet["evidence_card_seeds"]] == ["E1", "E2"]
    assert packet["evidence_card_seeds"][0]["paper_id"] == "P1"
    assert packet["evidence_card_seeds"][0]["source_path"] == "papers/P1/fulltext.md"
    assert packet["evidence_card_seeds"][0]["locator"]["section"] == "Results"
    assert packet["evidence_card_seeds"][0]["raw_text"] == "Full text evidence."
    assert packet["evidence_card_seeds"][1]["asset_type"] == "abstract"
    assert packet["source_type_coverage"]["text"]["seed_count"] == 1
    assert packet["source_type_coverage"]["abstract"]["seed_count"] == 1


def test_mixed_source_types_are_counted_without_guessing_missing_assets() -> None:
    candidates = [
        _text_candidate("E1", kind="section_chunk"),
        _text_candidate("E2", kind="figure", snippet="Figure-linked evidence."),
        _text_candidate("E3", kind="table_row", snippet="Table row evidence."),
        {
            **_text_candidate("E4", kind="figure_caption", snippet=None),
            "caption": "Caption evidence.",
        },
    ]

    packet = source_candidate_packet_from_acquisition(
        _acquisition_packet(evidence_candidates=candidates, expanded_assets=[{"evidence_id": "E2", "asset_type": "figure", "asset_id": "fig2", "asset_path": "assets/fig2.png", "caption": "Figure 2 caption"}]),
        topic="battery interface stability",
        task_profile=resolve_task_profile("topic-to-report"),
        scope_lock={"topic": "battery interface stability", "scope": "library", "scope_options": {}, "task_profile_id": "topic-to-report", "locked_at": 1.0},
        retrieval_budget=24,
    ).as_dict()

    coverage = packet["source_type_coverage"]
    assert coverage["text"]["candidate_count"] == 1
    assert coverage["figure"]["candidate_count"] == 2
    assert coverage["table"]["candidate_count"] == 1
    assert coverage["caption"]["candidate_count"] == 1
    assert "missing_figure_candidates_best_effort" not in packet["warnings"]
    assert "missing_table_candidates_best_effort" not in packet["warnings"]
    assert "missing_caption_candidates_best_effort" not in packet["warnings"]


def test_expanded_assets_become_best_effort_asset_candidates_and_seeds() -> None:
    packet = source_candidate_packet_from_acquisition(
        _acquisition_packet(
            evidence_candidates=[_text_candidate("E1")],
            expanded_assets=[
                {
                    "evidence_id": "E1",
                    "paper_id": "P1",
                    "doi": "10.1000/p1",
                    "title": "Interface Paper",
                    "year": 2024,
                    "journal": "Journal of Interfaces",
                    "asset_type": "caption",
                    "asset_id": "fig1_caption",
                    "asset_label": "Figure 1",
                    "asset_path": "papers/P1/figures/fig1.png",
                    "caption": "Figure 1 shows a stable interface.",
                    "source_locator": {"figure": "Figure 1"},
                }
            ],
        ),
        topic="battery interface stability",
        task_profile=resolve_task_profile("topic-to-report"),
        scope_lock={"topic": "battery interface stability", "scope": "library", "scope_options": {}, "task_profile_id": "topic-to-report", "locked_at": 1.0},
        retrieval_budget=24,
    ).as_dict()

    asset_seed = next(seed for seed in packet["evidence_card_seeds"] if seed["asset_id"] == "fig1_caption")
    assert asset_seed["source_evidence_id"] == "E1"
    assert asset_seed["paper_id"] == "P1"
    assert asset_seed["source_path"] == "papers/P1/figures/fig1.png"
    assert asset_seed["asset_type"] == "caption"
    assert asset_seed["raw_caption"] == "Figure 1 shows a stable interface."
    assert asset_seed["locator"]["asset_label"] == "Figure 1"


def test_missing_asset_source_types_emit_coverage_warnings_without_fake_candidates() -> None:
    packet = source_candidate_packet_from_acquisition(
        _acquisition_packet(
            evidence_candidates=[_text_candidate("E1")],
            warnings=["vector_index_not_built"],
            coverage_notes=["FTS-only retrieval"],
        ),
        topic="battery interface stability",
        task_profile=resolve_task_profile("topic-to-report"),
        scope_lock={"topic": "battery interface stability", "scope": "library", "scope_options": {}, "task_profile_id": "topic-to-report", "locked_at": 1.0},
        retrieval_budget=24,
    ).as_dict()

    assert "vector_index_not_built" in packet["warnings"]
    assert "asset_retrieval_no_expanded_assets" in packet["warnings"]
    assert "missing_figure_candidates_best_effort" in packet["warnings"]
    assert "missing_table_candidates_best_effort" in packet["warnings"]
    assert "missing_caption_candidates_best_effort" in packet["warnings"]
    assert packet["coverage_notes"] == ["FTS-only retrieval"]
    assert packet["source_type_coverage"]["figure"]["candidate_count"] == 0
    assert all(candidate.get("asset_type") == "text" for candidate in packet["source_candidates"])


def test_stub_task_profiles_are_rejected_before_retrieval() -> None:
    def acquire_evidence(*args, **kwargs):
        raise AssertionError("stub profiles should not call retrieval")

    with pytest.raises(ValueError, match="not runnable"):
        retrieve_source_candidates(acquire_evidence, topic="x", task_profile_id="experiment-plan")


def test_underlying_packet_query_coverage_breadth_are_preserved() -> None:
    underlying = _acquisition_packet(
        evidence_candidates=[_text_candidate("E1")],
        warnings=["no_hit_recovery_used"],
        coverage_notes=["recovered after dropping filters"],
    )
    packet = source_candidate_packet_from_acquisition(
        underlying,
        topic="battery interface stability",
        task_profile=resolve_task_profile("topic-to-report"),
        scope_lock={"topic": "battery interface stability", "scope": "library", "scope_options": {}, "task_profile_id": "topic-to-report", "locked_at": 1.0},
        retrieval_budget=24,
    ).as_dict()

    assert packet["underlying_packet"] == underlying
    assert packet["query_plan"] == underlying["query_plan"]
    assert packet["coverage"] == underlying["coverage"]
    assert packet["breadth"] == underlying["breadth"]


def test_retrieval_module_does_not_import_database_or_real_index() -> None:
    source = Path("backend/modules/evidence_workflow/retrieval.py").read_text(encoding="utf-8")

    assert "core.memory_db" not in source
    assert "sqlite" not in source.lower()
    assert "LiteratureResearchService" not in source
