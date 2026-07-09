from pathlib import Path

from modules.evidence_workflow.extraction import (
    INITIAL_EXTRACTION_VERSION,
    EvidenceExtractionResult,
    extract_initial_card,
    extract_initial_cards,
    save_initial_extraction_result,
)
from modules.evidence_workflow.prompts import INITIAL_EXTRACTION_SYSTEM_PROMPT, build_initial_extraction_messages
from modules.evidence_workflow.schemas import EvidenceCardSeed, validate_evidence_card
from modules.evidence_workflow.store import EvidenceCardStore
from modules.evidence_workflow.task_profiles import resolve_task_profile


def _seed(
    *,
    seed_id="seed_text",
    asset_type="text",
    raw_text="The coating improved stability during cycling.",
    raw_caption=None,
    source_path="papers/P1/fulltext.md",
) -> EvidenceCardSeed:
    return EvidenceCardSeed(
        seed_id=seed_id,
        source_evidence_id="E1",
        paper_id="P1",
        doi="10.1000/p1",
        title="Interface Paper",
        year=2025,
        journal="Journal of Interfaces",
        source_path=source_path,
        section_id="results",
        chunk_id=3,
        asset_id="asset_1" if asset_type in {"figure", "table", "caption"} else None,
        asset_type=asset_type,
        locator={"section": "Results", "asset_label": "Figure 1"},
        raw_text=raw_text,
        raw_caption=raw_caption,
        candidate_kind=f"{asset_type}_seed",
        retrieval_score=0.87,
    )


def test_text_seed_fallback_generates_valid_initial_card() -> None:
    seed = _seed(raw_text="  The coating improved   stability during cycling.  ")

    card = extract_initial_card(seed, topic="battery interface stability")

    assert card.evidence_id
    assert card.seed_id == seed.seed_id
    assert card.source_evidence_id == "E1"
    assert card.paper_id == "P1"
    assert card.source.source_path == "papers/P1/fulltext.md"
    assert card.source.asset_type == "text"
    assert card.source.locator == {"section": "Results", "asset_label": "Figure 1"}
    assert card.verbatim_snippet == "The coating improved   stability during cycling."
    assert card.normalized_statement == "The coating improved stability during cycling."
    assert card.primary_role == "background"
    assert card.secondary_roles == []
    assert card.entities.as_dict() == {
        "materials": [],
        "methods": [],
        "properties": [],
        "metrics": [],
        "values": [],
        "units": [],
        "conditions": [],
        "characterization_tools": [],
        "mechanisms": [],
        "applications": [],
    }
    assert card.relations == []
    assert card.relevance.topic == "battery interface stability"
    assert card.relevance.relevance_score == 0.87
    assert card.support.support_strength == "weak"
    assert "primary_role_provisional_pending_m6" in card.support.unsupported_parts
    assert validate_evidence_card(card) == []


def test_caption_figure_and_table_like_seeds_are_supported() -> None:
    caption = _seed(seed_id="seed_caption", asset_type="caption", raw_text=None, raw_caption="Figure caption describes stable cycling.")
    figure = _seed(seed_id="seed_figure", asset_type="figure", raw_text=None, raw_caption="Figure 2 shows morphology.")
    table = _seed(seed_id="seed_table", asset_type="table", raw_text="Table reports capacity retention.")

    result = extract_initial_cards([caption, figure, table], topic="battery interface stability")
    cards = {card.seed_id: card for card in result.cards}

    assert cards["seed_caption"].verbatim_snippet == "Figure caption describes stable cycling."
    assert cards["seed_caption"].primary_role == "background"
    assert cards["seed_figure"].primary_role == "figure_evidence"
    assert cards["seed_table"].primary_role == "table_evidence"
    assert result.card_count == 3
    assert validate_evidence_card(cards["seed_figure"]) == []
    assert validate_evidence_card(cards["seed_table"]) == []


def test_scripted_extractor_can_fill_initial_fields_but_not_m6_fields() -> None:
    seed = _seed()

    def extractor(seed_arg, topic, task_profile):
        return {
            "normalized_statement": "The coating improved cycling stability.",
            "relevance_reason": "Directly discusses the requested stability topic.",
            "support_strength": "direct",
            "extraction_confidence": 0.92,
            "unsupported_parts": ["long-term field behavior"],
            "warnings": ["scripted_warning"],
            "primary_role": "performance",
            "secondary_roles": ["condition"],
            "entities": {"materials": ["ignored"]},
            "relations": [{"subject": "ignored"}],
        }

    result = extract_initial_cards(
        [seed],
        topic="battery interface stability",
        task_profile=resolve_task_profile("topic-to-report"),
        extractor=extractor,
    )
    card = result.cards[0]

    assert card.normalized_statement == "The coating improved cycling stability."
    assert card.relevance.relevance_reason == "Directly discusses the requested stability topic."
    assert card.support.support_strength == "direct"
    assert card.support.extraction_confidence == 0.92
    assert card.support.unsupported_parts == ["long-term field behavior", "primary_role_provisional_pending_m6"]
    assert "scripted_warning" in result.warnings
    assert card.primary_role == "background"
    assert card.secondary_roles == []
    assert card.entities.materials == []
    assert card.relations == []


def test_extractor_failure_falls_back_without_blocking_other_seeds() -> None:
    good = _seed(seed_id="seed_good", raw_text="Good seed text.")
    bad = _seed(seed_id="seed_bad", raw_text="Bad seed text.")

    def extractor(seed_arg, topic, task_profile):
        if seed_arg.seed_id == "seed_bad":
            raise RuntimeError("boom")
        return {"normalized_statement": "Scripted good statement.", "support_strength": "indirect"}

    result = extract_initial_cards([good, bad], topic="battery interface stability", extractor=extractor)
    cards = {card.seed_id: card for card in result.cards}

    assert result.card_count == 2
    assert cards["seed_good"].normalized_statement == "Scripted good statement."
    assert cards["seed_bad"].normalized_statement == "Bad seed text."
    assert "extractor_failed:seed_bad" in result.warnings


def test_live_llm_style_extractor_labels_are_coerced_without_losing_statement() -> None:
    seed = _seed(seed_id="seed_llm", raw_text="LLM-Prop predicts crystalline material properties using large language models.")

    def extractor(seed_arg, topic, task_profile):
        return {
            "normalized_statement": "LLM-Prop predicts crystalline material properties using large language models.",
            "relevance_reason": "Directly discusses large language models for materials discovery.",
            "support_strength": "moderate",
            "extraction_confidence": "high",
            "unsupported_parts": "specific benchmark performance is not provided",
        }

    result = extract_initial_cards([seed], topic="LLMs for materials discovery", extractor=extractor)
    card = result.cards[0]

    assert card.normalized_statement == "LLM-Prop predicts crystalline material properties using large language models."
    assert card.relevance.relevance_reason == "Directly discusses large language models for materials discovery."
    assert card.support.support_strength == "indirect"
    assert card.support.extraction_confidence == 0.85
    assert card.support.unsupported_parts == [
        "specific benchmark performance is not provided",
        "primary_role_provisional_pending_m6",
    ]
    assert "extractor_invalid_output:seed_llm" not in result.warnings
    assert validate_evidence_card(card) == []


def test_empty_seed_is_skipped_and_recorded() -> None:
    empty = _seed(seed_id="seed_empty", raw_text=None, raw_caption=None)

    result = extract_initial_cards([empty], topic="battery interface stability")

    assert result.cards == []
    assert result.card_count == 0
    assert result.skipped_seed_ids == ["seed_empty"]
    assert "missing_raw_text_or_caption:seed_empty" in result.warnings


def test_initial_extraction_result_round_trips_through_card_store(tmp_path: Path) -> None:
    result = extract_initial_cards([_seed()], topic="battery interface stability")
    store = EvidenceCardStore(tmp_path)

    manifest = save_initial_extraction_result(store, "wf_123", result)
    loaded = store.load_cards("wf_123")

    assert manifest["extraction_version"] == INITIAL_EXTRACTION_VERSION
    assert manifest["source"] == "m5_initial_extraction"
    assert manifest["metadata"]["card_count"] == 1
    assert manifest["metadata"]["warnings"] == result.warnings
    assert manifest["metadata"]["skipped_seed_ids"] == []
    assert loaded["cards"][0]["seed_id"] == "seed_text"
    assert loaded["metadata"]["card_count"] == 1


def test_prompt_guardrails_make_m5_boundary_explicit() -> None:
    seed = _seed()
    messages = build_initial_extraction_messages(seed, topic="battery interface stability")
    joined = "\n".join(message["content"] for message in messages)

    assert "JSON only" in INITIAL_EXTRACTION_SYSTEM_PROMPT
    assert "Do not add external knowledge" in joined
    assert "Do not perform final role classification" in joined
    assert "Do not extract entities or relations" in joined
    assert "unsupported_parts" in joined
    assert "The coating improved stability during cycling." in joined


def test_extraction_module_does_not_import_database_service_or_workflow_runner() -> None:
    source = Path("backend/modules/evidence_workflow/extraction.py").read_text(encoding="utf-8")

    assert "core.memory_db" not in source
    assert "sqlite" not in source.lower()
    assert "LiteratureResearchService" not in source
    assert "WorkflowOrchestrator" not in source
    assert "AgentStepRunner" not in source


def test_result_serializes_to_json_safe_dict() -> None:
    result = extract_initial_cards([_seed()], topic="battery interface stability")
    data = result.as_dict()

    assert isinstance(result, EvidenceExtractionResult)
    assert data["extraction_version"] == INITIAL_EXTRACTION_VERSION
    assert data["card_count"] == 1
    assert data["cards"][0]["seed_id"] == "seed_text"
