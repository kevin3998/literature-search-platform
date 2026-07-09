from pathlib import Path

from modules.evidence_workflow.classification import enrich_evidence_cards
from modules.evidence_workflow.extraction import extract_initial_cards
from modules.evidence_workflow.minimal_report import (
    MINIMAL_REPORT_VERSION,
    MinimalTopicEvidenceReport,
    build_minimal_topic_to_evidence_report,
    run_minimal_topic_to_evidence_slice,
    save_minimal_topic_to_evidence_report,
)
from modules.evidence_workflow.retrieval import source_candidate_packet_from_acquisition
from modules.evidence_workflow.store import EvidenceCardStore
from modules.evidence_workflow.task_profiles import resolve_task_profile


def _candidate(
    evidence_id: str = "E1",
    *,
    snippet: str = "RAW_CHUNK_SHOULD_NOT_APPEAR",
    kind: str = "section_chunk",
) -> dict:
    return {
        "evidence_id": evidence_id,
        "paper_id": "P1",
        "doi": "10.1000/p1",
        "title": "Interface Evidence Paper",
        "year": 2025,
        "journal": "Journal of Evidence",
        "kind": kind,
        "section_id": "results",
        "chunk_index": 4,
        "snippet": snippet,
        "source_path": "papers/P1/fulltext.md",
        "source_locator": {"section": "Results", "chunk_index": 4},
        "relevance_score": 0.93,
    }


def _acquisition_packet(*, evidence_candidates=None, expanded_assets=None, warnings=None, coverage_notes=None) -> dict:
    candidates = evidence_candidates if evidence_candidates is not None else [_candidate()]
    return {
        "query": "battery interface stability",
        "query_plan": {"final_retrieval_used": "fts", "filters_applied": {"scope": "library"}},
        "coverage": {"status": "partial", "evidence_count": len(candidates), "distinct_paper_count": 1},
        "breadth": {"candidate_paper_count": 1, "llm_context_evidence_count": len(candidates)},
        "evidence_candidates": candidates,
        "expanded_assets": expanded_assets or [],
        "warnings": warnings or ["vector_index_not_built"],
        "coverage_notes": coverage_notes or ["FTS-only retrieval"],
    }


def _source_packet():
    profile = resolve_task_profile("topic-to-report")
    return source_candidate_packet_from_acquisition(
        _acquisition_packet(),
        topic="battery interface stability",
        task_profile=profile,
        scope_lock={
            "topic": "battery interface stability",
            "scope": "library",
            "scope_options": {},
            "task_profile_id": "topic-to-report",
            "locked_at": 1.0,
        },
        retrieval_budget=12,
    )


def _extractor(seed, topic, task_profile):
    return {
        "normalized_statement": "Interface coating improved cycling stability.",
        "support_strength": "direct",
        "extraction_confidence": 0.91,
    }


def _classifier(card, topic, task_profile):
    return {
        "primary_role": "performance",
        "secondary_roles": ["condition"],
        "entities": {
            "materials": ["interface coating"],
            "properties": ["cycling stability"],
            "conditions": ["reported cycling condition"],
        },
        "relations": [
            {
                "subject": "interface coating",
                "predicate": "improved",
                "object": "cycling stability",
                "confidence": 0.84,
            }
        ],
        "support_strength": "direct",
        "extraction_confidence": 0.88,
        "unsupported_parts": ["scale-up behavior"],
    }


def _enriched_cards_and_inputs():
    source_packet = _source_packet()
    profile = resolve_task_profile("topic-to-report")
    initial = extract_initial_cards(
        source_packet.evidence_card_seeds,
        topic="battery interface stability",
        task_profile=profile,
        extractor=_extractor,
    )
    enriched = enrich_evidence_cards(
        initial.cards,
        topic="battery interface stability",
        task_profile=profile,
        classifier=_classifier,
    )
    return source_packet, initial, enriched, profile


def test_build_minimal_report_from_evidence_workflow_objects() -> None:
    source_packet, initial, enriched, profile = _enriched_cards_and_inputs()

    report = build_minimal_topic_to_evidence_report(
        workflow_id="wf_123",
        topic="battery interface stability",
        task_profile=profile,
        scope_lock=source_packet.scope_lock,
        source_packet=source_packet,
        extraction_result=initial,
        enrichment_result=enriched,
    )

    assert isinstance(report, MinimalTopicEvidenceReport)
    assert report.report_version == MINIMAL_REPORT_VERSION
    assert report.workflow_id == "wf_123"
    assert report.topic == "battery interface stability"
    assert report.role_coverage["by_role"]["performance"] == 1
    assert report.source_type_coverage["text"]["seed_count"] == 1
    assert report.evidence_cards[0]["evidence_id"] == enriched.cards[0].evidence_id
    assert report.evidence_cards[0]["primary_role"] == "performance"
    assert report.evidence_cards[0]["secondary_roles"] == ["condition"]
    assert report.evidence_cards[0]["source"]["locator"]["section"] == "Results"
    assert "# Minimal Topic-to-Evidence Report" in report.markdown
    assert "## Scope Lock" in report.markdown
    assert "## Retrieval Summary" in report.markdown
    assert "## Source-Type Coverage" in report.markdown
    assert "## Role Coverage" in report.markdown
    assert "## Evidence Cards" in report.markdown
    assert "## Coverage Warnings" in report.markdown
    assert "## Manual Verification Checklist" in report.markdown
    assert "Interface coating improved cycling stability." in report.markdown
    assert "RAW_CHUNK_SHOULD_NOT_APPEAR" not in report.markdown


def test_run_minimal_topic_to_evidence_slice_saves_cards_and_report_artifacts(tmp_path: Path) -> None:
    calls = []

    def acquire_evidence(query, *, has_history=False, **options):
        calls.append({"query": query, "has_history": has_history, "options": options})
        return _acquisition_packet()

    store = EvidenceCardStore(tmp_path)
    report = run_minimal_topic_to_evidence_slice(
        acquire_evidence,
        workflow_id="wf_123",
        topic="battery interface stability",
        store=store,
        retrieval_budget=6,
        extractor=_extractor,
        classifier=_classifier,
    )

    assert calls[0]["query"] == "battery interface stability"
    assert calls[0]["has_history"] is False
    assert calls[0]["options"]["limit"] == 6
    assert calls[0]["options"]["expand_assets"] is True
    assert report.workflow_id == "wf_123"

    cards_manifest = store.load_cards("wf_123")
    assert cards_manifest["extraction_version"] == "m6_role_entity_relation_v1"
    assert cards_manifest["cards"][0]["primary_role"] == "performance"

    loaded = store.load_minimal_report("wf_123")
    assert loaded["manifest"]["artifact_type"] == "minimal_topic_to_evidence_report"
    assert loaded["manifest"]["report_version"] == MINIMAL_REPORT_VERSION
    assert loaded["manifest"]["workflow_id"] == "wf_123"
    assert loaded["manifest"]["evidence_card_ids"] == [report.evidence_cards[0]["evidence_id"]]
    assert "# Minimal Topic-to-Evidence Report" in loaded["markdown"]


def test_coverage_warnings_are_visible_without_fake_asset_evidence() -> None:
    source_packet, initial, enriched, profile = _enriched_cards_and_inputs()
    report = build_minimal_topic_to_evidence_report(
        workflow_id="wf_123",
        topic="battery interface stability",
        task_profile=profile,
        scope_lock=source_packet.scope_lock,
        source_packet=source_packet,
        extraction_result=initial,
        enrichment_result=enriched,
    )

    assert "missing_figure_candidates_best_effort" in report.warnings
    assert "missing_table_candidates_best_effort" in report.warnings
    assert "missing_caption_candidates_best_effort" in report.warnings
    assert "missing_figure_candidates_best_effort" in report.markdown
    assert report.source_type_coverage["figure"]["candidate_count"] == 0
    assert all(card["source"]["asset_type"] == "text" for card in report.evidence_cards)


def test_minimal_report_does_not_include_downstream_research_sections() -> None:
    source_packet, initial, enriched, profile = _enriched_cards_and_inputs()
    report = build_minimal_topic_to_evidence_report(
        workflow_id="wf_123",
        topic="battery interface stability",
        task_profile=profile,
        scope_lock=source_packet.scope_lock,
        source_packet=source_packet,
        extraction_result=initial,
        enrichment_result=enriched,
    )

    forbidden = [
        "## Research Gap",
        "## Candidate Idea",
        "## Novelty",
        "## Experiment Plan",
        "## Manuscript",
        "## Landscape",
    ]
    for section in forbidden:
        assert section not in report.markdown


def test_minimal_report_artifact_round_trip_and_event_shape(tmp_path: Path) -> None:
    source_packet, initial, enriched, profile = _enriched_cards_and_inputs()
    report = build_minimal_topic_to_evidence_report(
        workflow_id="wf_123",
        topic="battery interface stability",
        task_profile=profile,
        scope_lock=source_packet.scope_lock,
        source_packet=source_packet,
        extraction_result=initial,
        enrichment_result=enriched,
    )
    store = EvidenceCardStore(tmp_path)

    manifest = save_minimal_topic_to_evidence_report(store, "wf_123", report)
    loaded = store.load_minimal_report("wf_123")
    event = store.minimal_report_event("wf_123")

    assert manifest["artifact_type"] == "minimal_topic_to_evidence_report"
    assert manifest["md_path"] == "research_agent/evidence_workflows/wf_123/minimal_topic_to_evidence_report.md"
    assert manifest["json_path"] == "research_agent/evidence_workflows/wf_123/minimal_topic_to_evidence_report.json"
    assert loaded["manifest"]["evidence_card_ids"] == [report.evidence_cards[0]["evidence_id"]]
    assert loaded["markdown"] == report.markdown
    assert event == {
        "type": "artifact",
        "artifact_type": "minimal_topic_to_evidence_report",
        "artifact_id": "research_agent/evidence_workflows/wf_123/minimal_topic_to_evidence_report.md",
        "path": "research_agent/evidence_workflows/wf_123/minimal_topic_to_evidence_report.md",
        "label": "Minimal Topic-to-Evidence Report",
    }


def test_minimal_report_module_does_not_import_database_service_workflow_or_api() -> None:
    source = Path("backend/modules/evidence_workflow/minimal_report.py").read_text(encoding="utf-8")

    assert "core.memory_db" not in source
    assert "sqlite" not in source.lower()
    assert "LiteratureResearchService" not in source
    assert "WorkflowOrchestrator" not in source
    assert "AgentStepRunner" not in source
    assert "workflow_router" not in source
