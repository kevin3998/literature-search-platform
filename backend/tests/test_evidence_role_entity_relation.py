from pathlib import Path

from modules.evidence_workflow.classification import (
    ROLE_ENRICHMENT_VERSION,
    EvidenceEnrichmentResult,
    compute_role_coverage,
    enrich_evidence_card,
    enrich_evidence_cards,
    save_enrichment_result,
)
from modules.evidence_workflow.extraction import extract_initial_card
from modules.evidence_workflow.prompts import ROLE_ENTITY_RELATION_SYSTEM_PROMPT, build_role_entity_relation_messages
from modules.evidence_workflow.schemas import EvidenceCardSeed, validate_evidence_card
from modules.evidence_workflow.store import EvidenceCardStore
from modules.evidence_workflow.task_profiles import resolve_task_profile


def _seed(
    *,
    seed_id: str = "seed_perf",
    asset_type: str = "text",
    raw_text: str | None = "NiFe oxide delivered 42 mA cm-2 at 1.6 V in alkaline electrolyte.",
    raw_caption: str | None = None,
) -> EvidenceCardSeed:
    return EvidenceCardSeed(
        seed_id=seed_id,
        source_evidence_id="E1",
        paper_id="P1",
        doi="10.1000/p1",
        title="Evidence enrichment paper",
        year=2025,
        journal="Journal of Evidence",
        source_path="papers/P1/fulltext.md",
        section_id="results",
        chunk_id=2,
        asset_id="asset_1" if asset_type in {"figure", "table", "caption"} else None,
        asset_type=asset_type,
        locator={"section": "Results", "asset_label": "Figure 2"},
        raw_text=raw_text,
        raw_caption=raw_caption,
        candidate_kind=f"{asset_type}_seed",
        retrieval_score=0.91,
    )


def _initial_card(seed_id: str = "seed_perf", raw_text: str | None = None):
    return extract_initial_card(
        _seed(seed_id=seed_id, raw_text=raw_text or "NiFe oxide delivered 42 mA cm-2 at 1.6 V in alkaline electrolyte."),
        topic="oxide electrocatalyst performance",
    )


def test_scripted_classifier_enriches_performance_card_with_entities_and_relations() -> None:
    card = _initial_card()

    def classifier(card_arg, topic, task_profile):
        return {
            "primary_role": "performance",
            "secondary_roles": ["condition", "comparison", "condition"],
            "entities": {
                "materials": ["NiFe oxide"],
                "metrics": ["current density"],
                "values": ["42"],
                "units": ["mA cm-2"],
                "conditions": ["1.6 V", "alkaline electrolyte"],
            },
            "relations": [
                {
                    "subject": "NiFe oxide",
                    "predicate": "delivered current density",
                    "object": "42 mA cm-2",
                    "qualifiers": {"potential": "1.6 V"},
                    "condition": "alkaline electrolyte",
                    "confidence": 0.86,
                }
            ],
            "support_strength": "direct",
            "extraction_confidence": 0.88,
            "uncertainty": "single extracted sentence",
            "unsupported_parts": ["long-term stability"],
        }

    result = enrich_evidence_cards(
        [card],
        topic="oxide electrocatalyst performance",
        task_profile=resolve_task_profile("topic-to-report"),
        classifier=classifier,
    )
    enriched = result.cards[0]

    assert isinstance(result, EvidenceEnrichmentResult)
    assert enriched.primary_role == "performance"
    assert enriched.secondary_roles == ["condition", "comparison"]
    assert enriched.entities.materials == ["NiFe oxide"]
    assert enriched.entities.metrics == ["current density"]
    assert enriched.entities.values == ["42"]
    assert enriched.entities.units == ["mA cm-2"]
    assert enriched.entities.conditions == ["1.6 V", "alkaline electrolyte"]
    assert enriched.relations[0].predicate == "delivered current density"
    assert enriched.relations[0].confidence == 0.86
    assert enriched.support.support_strength == "direct"
    assert enriched.support.extraction_confidence == 0.88
    assert enriched.support.uncertainty == "single extracted sentence"
    assert enriched.support.unsupported_parts == ["long-term stability"]
    assert validate_evidence_card(enriched) == []


def test_mechanism_card_can_store_characterization_relation() -> None:
    card = _initial_card(
        seed_id="seed_mech",
        raw_text="XPS indicated electron transfer from Co to Mo, which optimized hydrogen adsorption.",
    )

    def classifier(card_arg, topic, task_profile):
        return {
            "primary_role": "mechanism",
            "secondary_roles": ["characterization"],
            "entities": {
                "materials": ["Co-Mo surface"],
                "characterization_tools": ["XPS"],
                "mechanisms": ["electron transfer", "optimized hydrogen adsorption"],
            },
            "relations": [
                {
                    "subject": "XPS",
                    "predicate": "supports mechanism",
                    "object": "electron transfer from Co to Mo",
                    "condition": "reported surface state",
                    "confidence": 0.79,
                }
            ],
        }

    enriched = enrich_evidence_card(card, topic="oxide electrocatalyst mechanism", classifier=classifier)

    assert enriched.primary_role == "mechanism"
    assert enriched.secondary_roles == ["characterization"]
    assert "XPS" in enriched.entities.characterization_tools
    assert "electron transfer" in enriched.entities.mechanisms
    assert enriched.relations[0].subject == "XPS"
    assert enriched.relations[0].object == "electron transfer from Co to Mo"
    assert validate_evidence_card(enriched) == []


def test_limitation_card_preserves_uncertainty() -> None:
    card = _initial_card(
        seed_id="seed_limit",
        raw_text="The authors noted that stability was only evaluated for 2 h.",
    )

    def classifier(card_arg, topic, task_profile):
        return {
            "primary_role": "limitation",
            "secondary_roles": ["condition"],
            "support_strength": "direct",
            "uncertainty": "Only a short test duration is reported.",
            "unsupported_parts": ["durability beyond 2 h"],
        }

    enriched = enrich_evidence_card(card, topic="oxide electrocatalyst durability", classifier=classifier)

    assert enriched.primary_role == "limitation"
    assert enriched.secondary_roles == ["condition"]
    assert enriched.support.uncertainty == "Only a short test duration is reported."
    assert enriched.support.unsupported_parts == ["durability beyond 2 h"]
    assert validate_evidence_card(enriched) == []


def test_classifier_output_is_bounded_to_roles_open_entities_and_relations() -> None:
    card = _initial_card()
    original = card.as_dict()

    def classifier(card_arg, topic, task_profile):
        return {
            "evidence_id": "mutated",
            "paper_id": "mutated",
            "source": {"source_path": "mutated"},
            "verbatim_snippet": "mutated",
            "primary_role": "HER",
            "secondary_roles": ["condition", "electrolyte", "condition", "background"],
            "entities": {
                "materials": ["NiFe oxide", "", "NiFe oxide"],
                "metrics": "current density",
                "domain_profile": ["forbidden"],
            },
            "relations": [
                {"subject": "NiFe oxide", "predicate": "delivered", "object": "42 mA cm-2", "confidence": 1.4},
                {"subject": "NiFe oxide", "predicate": "delivered", "object": "42 mA cm-2", "confidence": 0.7},
                {"subject": "missing object", "predicate": "has"},
                {"subject": "bad qualifiers", "predicate": "has", "object": "value", "qualifiers": "not a dict"},
            ],
            "support_strength": "certain",
            "extraction_confidence": 2.5,
            "warnings": ["classifier_warning"],
        }

    result = enrich_evidence_cards([card], topic="oxide electrocatalyst performance", classifier=classifier)
    enriched = result.cards[0]

    assert enriched.evidence_id == original["evidence_id"]
    assert enriched.paper_id == original["paper_id"]
    assert enriched.source.source_path == original["source"]["source_path"]
    assert enriched.verbatim_snippet == original["verbatim_snippet"]
    assert enriched.primary_role == "background"
    assert enriched.secondary_roles == ["condition"]
    assert enriched.entities.materials == ["NiFe oxide"]
    assert enriched.entities.metrics == []
    assert len(enriched.relations) == 2
    assert enriched.relations[0].confidence is None
    assert enriched.relations[1].qualifiers == {}
    assert enriched.support.support_strength == "weak"
    assert enriched.support.extraction_confidence is None
    assert "invalid_primary_role:HER:" + card.evidence_id in result.warnings
    assert "invalid_secondary_role:electrolyte:" + card.evidence_id in result.warnings
    assert "unknown_entity_field:domain_profile:" + card.evidence_id in result.warnings
    assert "invalid_entity_field:metrics:" + card.evidence_id in result.warnings
    assert "invalid_relation_confidence:" + card.evidence_id in result.warnings
    assert "classifier_warning" in result.warnings
    assert validate_evidence_card(enriched) == []


def test_live_llm_style_classifier_output_is_coerced_into_open_schema() -> None:
    card = _initial_card(
        seed_id="seed_llm_style",
        raw_text="LLM-Prop predicts properties of crystalline materials using large language models.",
    )

    def classifier(card_arg, topic, task_profile):
        return {
            "primary_role": "background",
            "secondary_roles": [],
            "entities": [
                {"name": "LLM-Prop", "type": "model"},
                {"name": "crystalline materials", "type": "material"},
                {"name": "large language models", "type": "technology"},
                {"name": "materials discovery", "type": "task"},
            ],
            "relations": [
                {"subject": "LLM-Prop", "predicate": "uses", "object": "large language models"},
                {"subject": "LLM-Prop", "predicate": "targets", "object": "crystalline materials"},
            ],
            "support_strength": "partial",
            "extraction_confidence": "medium",
            "uncertainty": "The snippet is title-like and lacks benchmark details.",
            "unsupported_parts": "benchmark performance",
        }

    result = enrich_evidence_cards([card], topic="LLMs for materials discovery", classifier=classifier)
    enriched = result.cards[0]

    assert enriched.entities.methods == ["LLM-Prop", "large language models"]
    assert enriched.entities.materials == ["crystalline materials"]
    assert enriched.entities.applications == ["materials discovery"]
    assert enriched.support.support_strength == "indirect"
    assert enriched.support.extraction_confidence == 0.6
    assert enriched.support.unsupported_parts == ["benchmark performance"]
    assert enriched.relations[0].subject == "LLM-Prop"
    assert "invalid_entities:" + card.evidence_id not in result.warnings
    assert "invalid_support_strength:" + card.evidence_id not in result.warnings
    assert "invalid_extraction_confidence:" + card.evidence_id not in result.warnings
    assert validate_evidence_card(enriched) == []


def test_fallback_keeps_card_valid_and_cleans_m5_provisional_marker() -> None:
    card = _initial_card()

    result = enrich_evidence_cards([card], topic="oxide electrocatalyst performance")
    enriched = result.cards[0]

    assert enriched.primary_role == "background"
    assert enriched.secondary_roles == []
    assert "primary_role_provisional_pending_m6" not in enriched.support.unsupported_parts
    assert "role_enrichment_fallback:" + card.evidence_id in result.warnings
    assert enriched.support.uncertainty == "M6 fallback did not perform semantic role classification."
    assert validate_evidence_card(enriched) == []


def test_role_coverage_reports_required_role_gaps_without_failing() -> None:
    profile = resolve_task_profile("topic-to-report")
    performance = _initial_card(seed_id="seed_perf")
    limitation = _initial_card(seed_id="seed_limit", raw_text="The test lacked long-term cycling evidence.")

    def classifier(card_arg, topic, task_profile):
        if card_arg.seed_id == "seed_limit":
            return {"primary_role": "limitation", "secondary_roles": ["condition"]}
        return {"primary_role": "performance", "secondary_roles": ["condition"]}

    result = enrich_evidence_cards(
        [performance, limitation],
        topic="oxide electrocatalyst performance",
        task_profile=profile,
        classifier=classifier,
    )

    assert result.role_coverage["by_role"]["performance"] == 1
    assert result.role_coverage["by_role"]["condition"] == 2
    assert result.role_coverage["by_role"]["limitation"] == 1
    assert result.role_coverage["primary_role_counts"] == {"performance": 1, "limitation": 1}
    assert result.role_coverage["secondary_role_counts"] == {"condition": 2}
    assert "background" in result.role_coverage["missing_required_roles"]
    assert "method" in result.role_coverage["missing_required_roles"]
    assert "performance" not in result.role_coverage["missing_required_roles"]
    assert result.skipped_card_ids == []
    assert compute_role_coverage(result.cards, profile) == result.role_coverage


def test_enrichment_result_round_trips_through_card_store(tmp_path: Path) -> None:
    card = _initial_card()

    def classifier(card_arg, topic, task_profile):
        return {
            "primary_role": "performance",
            "entities": {"metrics": ["current density"], "values": ["42"], "units": ["mA cm-2"]},
            "relations": [{"subject": "NiFe oxide", "predicate": "delivered", "object": "42 mA cm-2", "confidence": 0.82}],
        }

    result = enrich_evidence_cards([card], topic="oxide electrocatalyst performance", classifier=classifier)
    store = EvidenceCardStore(tmp_path)

    manifest = save_enrichment_result(store, "wf_123", result)
    loaded = store.load_cards("wf_123")

    assert manifest["extraction_version"] == ROLE_ENRICHMENT_VERSION
    assert manifest["source"] == "m6_role_entity_relation_enrichment"
    assert manifest["metadata"]["card_count"] == 1
    assert manifest["metadata"]["role_coverage"]["by_role"]["performance"] == 1
    assert loaded["cards"][0]["primary_role"] == "performance"
    assert loaded["cards"][0]["entities"]["metrics"] == ["current density"]
    assert loaded["cards"][0]["relations"][0]["confidence"] == 0.82


def test_role_entity_relation_prompt_guardrails() -> None:
    card = _initial_card()
    messages = build_role_entity_relation_messages(card, topic="oxide electrocatalyst performance")
    joined = "\n".join(message["content"] for message in messages)

    assert "JSON only" in ROLE_ENTITY_RELATION_SYSTEM_PROMPT
    assert "Do not add external knowledge" in joined
    assert "This is not a Claim Ledger" in joined
    assert "Do not generate ideas, novelty claims, reports, or experiment plans" in joined
    assert "role/entity/relation enrichment" in joined
    assert "domain profile schema" in joined
    assert card.normalized_statement in joined


def test_classification_module_does_not_import_database_service_workflow_or_api() -> None:
    source = Path("backend/modules/evidence_workflow/classification.py").read_text(encoding="utf-8")

    assert "core.memory_db" not in source
    assert "sqlite" not in source.lower()
    assert "LiteratureResearchService" not in source
    assert "WorkflowOrchestrator" not in source
    assert "AgentStepRunner" not in source
    assert "workflow_router" not in source
