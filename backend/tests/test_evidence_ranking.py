from pathlib import Path

from modules.evidence_workflow.ranking import (
    EVIDENCE_SELECTION_VERSION,
    EvidenceRankingConfig,
    EvidenceSelectionResult,
    compute_selection_coverage,
    rank_evidence_cards,
    save_selection_result,
    select_representative_evidence,
)
from modules.evidence_workflow.schemas import (
    EvidenceCard,
    EvidenceEntities,
    EvidenceRelation,
    EvidenceRelevance,
    EvidenceSource,
    EvidenceSupport,
)
from modules.evidence_workflow.store import EvidenceCardStore
from modules.evidence_workflow.task_profiles import resolve_task_profile


def _card(
    evidence_id: str,
    *,
    paper_id: str = "P1",
    primary_role: str = "performance",
    secondary_roles: list[str] | None = None,
    asset_type: str = "text",
    relevance: float | None = 0.8,
    support_strength: str = "direct",
    confidence: float | None = 0.8,
    with_entities: bool = True,
    with_relation: bool = True,
) -> EvidenceCard:
    return EvidenceCard(
        evidence_id=evidence_id,
        seed_id=f"seed_{evidence_id}",
        source_evidence_id=f"src_{evidence_id}",
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        source=EvidenceSource(
            source_path=f"papers/{paper_id}/{asset_type}.md",
            asset_type=asset_type,
            locator={"section": "Results"} if asset_type != "abstract" else {},
        ),
        primary_role=primary_role,
        secondary_roles=list(secondary_roles or []),
        normalized_statement=f"Statement for {evidence_id}.",
        entities=EvidenceEntities(materials=["sample"] if with_entities else []),
        relations=[
            EvidenceRelation(subject="sample", predicate="has", object="property", confidence=0.8)
        ]
        if with_relation
        else [],
        relevance=EvidenceRelevance(topic="ranking topic", relevance_score=relevance),
        support=EvidenceSupport(support_strength=support_strength, extraction_confidence=confidence),
    )


def test_ranking_score_order_is_deterministic_and_explainable() -> None:
    profile = resolve_task_profile("topic-to-report")
    cards = [
        _card("ecard_weak", relevance=0.8, support_strength="weak", confidence=0.8),
        _card("ecard_indirect", relevance=0.8, support_strength="indirect", confidence=0.8),
        _card("ecard_direct", relevance=0.8, support_strength="direct", confidence=0.8),
        _card("ecard_high_relevance", relevance=0.95, support_strength="direct", confidence=0.8),
        _card("ecard_a_tie", relevance=0.7, support_strength="direct", confidence=0.7),
        _card("ecard_b_tie", relevance=0.7, support_strength="direct", confidence=0.7),
    ]

    ranked = rank_evidence_cards(cards, task_profile=profile)
    ids = [item.evidence_id for item in ranked]

    assert ids.index("ecard_high_relevance") < ids.index("ecard_direct")
    assert ids.index("ecard_direct") < ids.index("ecard_indirect")
    assert ids.index("ecard_indirect") < ids.index("ecard_weak")
    assert ids.index("ecard_a_tie") < ids.index("ecard_b_tie")
    assert ranked[0].score_components["relevance"] == 0.95
    assert ranked[0].score_components["support"] == 1.0
    assert ranked[0].score_components["role"] == 1.0
    assert ranked[0].rank == 1


def test_selection_preserves_required_roles_including_secondary_role_matches() -> None:
    profile = resolve_task_profile("topic-to-report")
    cards = [
        _card("ecard_perf", paper_id="P1", primary_role="performance", relevance=0.95),
        _card("ecard_method", paper_id="P2", primary_role="background", secondary_roles=["method"], relevance=0.62),
        _card("ecard_limit", paper_id="P3", primary_role="limitation", relevance=0.61),
        _card("ecard_extra", paper_id="P4", primary_role="background", relevance=0.9),
    ]

    result = select_representative_evidence(
        cards,
        task_profile=profile,
        config=EvidenceRankingConfig(selection_limit=3),
    )
    selected_ids = [card["evidence_id"] for card in result.selected_cards]

    assert "ecard_perf" in selected_ids
    assert "ecard_method" in selected_ids
    assert "ecard_limit" in selected_ids
    assert result.coverage["role_coverage"]["by_role"]["method"] == 1
    method_ranked = next(item for item in result.ranked_cards if item.evidence_id == "ecard_method")
    assert "required_role:method" in method_ranked.selection_reasons


def test_selection_limits_single_paper_dominance_when_alternatives_exist() -> None:
    cards = [
        _card(f"ecard_p1_{idx}", paper_id="P1", primary_role="performance", relevance=0.99 - idx * 0.01)
        for idx in range(5)
    ]
    cards.extend(
        [
            _card("ecard_p2", paper_id="P2", primary_role="method", relevance=0.7),
            _card("ecard_p3", paper_id="P3", primary_role="limitation", relevance=0.69),
            _card("ecard_p4", paper_id="P4", primary_role="condition", relevance=0.68),
        ]
    )

    result = select_representative_evidence(
        cards,
        task_profile=resolve_task_profile("topic-to-report"),
        config=EvidenceRankingConfig(selection_limit=5),
    )
    selected_papers = [card["paper_id"] for card in result.selected_cards]

    assert selected_papers.count("P1") <= 2
    assert {"P2", "P3", "P4"}.issubset(set(selected_papers))
    assert "dominant_paper_warning" not in result.warnings


def test_dominant_paper_warning_is_emitted_when_dominance_cannot_be_avoided() -> None:
    cards = [
        _card(f"ecard_p1_{idx}", paper_id="P1", primary_role="performance", relevance=0.9 - idx * 0.01)
        for idx in range(4)
    ]

    result = select_representative_evidence(
        cards,
        task_profile=resolve_task_profile("topic-to-report"),
        config=EvidenceRankingConfig(selection_limit=4),
    )

    assert result.selected_count == 4
    assert "dominant_paper_warning" in result.warnings
    assert "selection_caps_relaxed_to_fill_budget" in result.warnings


def test_source_type_diversity_is_preserved_when_available_and_gaps_are_reported() -> None:
    cards = [
        _card("ecard_text", paper_id="P1", primary_role="performance", asset_type="text", relevance=0.95),
        _card("ecard_caption", paper_id="P2", primary_role="mechanism", asset_type="caption", relevance=0.72),
        _card("ecard_table", paper_id="P3", primary_role="table_evidence", asset_type="table", relevance=0.71),
        _card("ecard_figure", paper_id="P4", primary_role="figure_evidence", asset_type="figure", relevance=0.7),
    ]

    result = select_representative_evidence(
        cards,
        task_profile=resolve_task_profile("topic-to-report"),
        config=EvidenceRankingConfig(selection_limit=4),
    )
    selected_types = {card["source"]["asset_type"] for card in result.selected_cards}

    assert {"text", "caption", "table", "figure"}.issubset(selected_types)
    assert result.coverage["source_type_coverage"]["selected"]["figure"] == 1
    assert "missing_caption_source_type" not in result.warnings

    text_only = select_representative_evidence(
        [_card("ecard_text_only", paper_id="P1", asset_type="text")],
        task_profile=resolve_task_profile("topic-to-report"),
    )
    assert "missing_figure_source_type" in text_only.warnings
    assert "missing_table_source_type" in text_only.warnings
    assert "missing_caption_source_type" in text_only.warnings


def test_selection_limit_caps_relaxation_and_coverage_output() -> None:
    profile = resolve_task_profile("topic-to-report")
    cards = [
        _card("ecard_a", paper_id="P1", primary_role="performance", asset_type="text", relevance=0.9),
        _card("ecard_b", paper_id="P1", primary_role="method", asset_type="text", relevance=0.88),
        _card("ecard_c", paper_id="P1", primary_role="condition", asset_type="text", relevance=0.87),
    ]

    result = select_representative_evidence(cards, task_profile=profile, retrieval_budget=3)

    assert isinstance(result, EvidenceSelectionResult)
    assert result.selection_version == EVIDENCE_SELECTION_VERSION
    assert result.selected_count == 3
    assert result.coverage["paper_coverage"]["selected"]["P1"] == 3
    assert result.coverage["source_type_coverage"]["selected"]["text"] == 3
    assert "background" in result.coverage["missing_required_roles"]
    assert "selection_caps_relaxed_to_fill_budget" in result.warnings
    assert compute_selection_coverage(result.selected_card_objects, cards, profile) == result.coverage


def test_selection_result_serializes_and_round_trips_through_store(tmp_path: Path) -> None:
    cards = [
        _card("ecard_perf", paper_id="P1", primary_role="performance", relevance=0.9),
        _card("ecard_method", paper_id="P2", primary_role="method", relevance=0.8),
    ]
    result = select_representative_evidence(
        cards,
        task_profile=resolve_task_profile("topic-to-report"),
        config=EvidenceRankingConfig(selection_limit=2),
    )
    store = EvidenceCardStore(tmp_path)

    manifest = save_selection_result(store, "wf_123", result)
    loaded = store.load_evidence_selection("wf_123")
    event = store.evidence_selection_event("wf_123")

    assert manifest["artifact_type"] == "evidence_selection"
    assert manifest["selection_version"] == EVIDENCE_SELECTION_VERSION
    assert manifest["selected_count"] == 2
    assert loaded["selected_cards"][0]["evidence_id"] == result.selected_cards[0]["evidence_id"]
    assert event == {
        "type": "artifact",
        "artifact_type": "evidence_selection",
        "artifact_id": "research_agent/evidence_workflows/wf_123/evidence_selection.json",
        "path": "research_agent/evidence_workflows/wf_123/evidence_selection.json",
        "label": "Evidence Selection",
    }


def test_ranking_module_does_not_import_database_service_workflow_or_api() -> None:
    source = Path("backend/modules/evidence_workflow/ranking.py").read_text(encoding="utf-8")

    assert "core.memory_db" not in source
    assert "sqlite" not in source.lower()
    assert "LiteratureResearchService" not in source
    assert "WorkflowOrchestrator" not in source
    assert "AgentStepRunner" not in source
    assert "workflow_router" not in source
