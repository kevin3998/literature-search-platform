from __future__ import annotations

from modules.evidence_workflow.schemas import (
    EVIDENCE_ROLES,
    EvidenceCard,
    EvidenceEntities,
    EvidenceRelation,
    EvidenceRelevance,
    EvidenceSource,
    EvidenceSupport,
    deterministic_card_id,
    deterministic_seed_id,
    evidence_card_seed_from_candidate,
    validate_evidence_card,
    validate_evidence_card_seed,
)


def _candidate() -> dict:
    return {
        "evidence_id": "E42",
        "paper_id": "10.1000/test",
        "doi": "10.1000/test",
        "title": "A test paper",
        "year": 2025,
        "journal": "Journal of Tests",
        "kind": "section_chunk",
        "section_id": "results",
        "chunk_index": 3,
        "snippet": "Ni-Mo catalyst reached 58 mV dec-1 in 1.0 M KOH.",
        "expanded_context": "Expanded context should be retained only when snippet is absent.",
        "source_path": "articles/test/parsed/fulltext.md",
        "source_locator": {"section": "Results", "chunk_index": 3},
        "asset_label": "Figure 2",
        "relevance_score": 0.87,
    }


def _valid_card() -> EvidenceCard:
    seed = evidence_card_seed_from_candidate(_candidate(), topic="HER catalyst")
    return EvidenceCard(
        evidence_id=deterministic_card_id(seed),
        seed_id=seed.seed_id,
        source_evidence_id=seed.source_evidence_id,
        paper_id=seed.paper_id,
        title=seed.title,
        doi=seed.doi,
        year=seed.year,
        journal=seed.journal,
        source=EvidenceSource(
            source_path=seed.source_path,
            section_id=seed.section_id,
            chunk_id=seed.chunk_id,
            asset_id=seed.asset_id,
            asset_type=seed.asset_type,
            locator=seed.locator,
        ),
        primary_role="performance",
        secondary_roles=["condition", "table_evidence"],
        verbatim_snippet=seed.raw_text,
        normalized_statement="Ni-Mo catalyst showed a Tafel slope of 58 mV dec-1 in 1.0 M KOH.",
        entities=EvidenceEntities(
            materials=["Ni-Mo catalyst"],
            metrics=["Tafel slope"],
            values=["58"],
            units=["mV dec-1"],
            conditions=["1.0 M KOH"],
        ),
        relations=[
            EvidenceRelation(
                subject="Ni-Mo catalyst",
                predicate="has Tafel slope",
                object="58 mV dec-1",
                condition="1.0 M KOH",
                confidence=0.8,
            )
        ],
        relevance=EvidenceRelevance(
            topic="HER catalyst",
            relevance_reason="Reports performance under test conditions.",
            relevance_score=0.87,
        ),
        support=EvidenceSupport(
            support_strength="direct",
            extraction_confidence=0.82,
            uncertainty="metric extracted from snippet only",
            unsupported_parts=[],
        ),
    )


def test_seed_adapter_preserves_candidate_provenance():
    seed = evidence_card_seed_from_candidate(_candidate(), topic="HER catalyst")

    assert seed.source_evidence_id == "E42"
    assert seed.paper_id == "10.1000/test"
    assert seed.source_path == "articles/test/parsed/fulltext.md"
    assert seed.section_id == "results"
    assert seed.chunk_id == 3
    assert seed.asset_type == "text"
    assert seed.candidate_kind == "section_chunk"
    assert seed.raw_text == "Ni-Mo catalyst reached 58 mV dec-1 in 1.0 M KOH."
    assert seed.retrieval_score == 0.87
    assert seed.locator["asset_label"] == "Figure 2"
    assert validate_evidence_card_seed(seed) == []


def test_valid_card_serializes_to_json_safe_dict():
    card = _valid_card()

    data = card.as_dict()

    assert data["primary_role"] == "performance"
    assert data["secondary_roles"] == ["condition", "table_evidence"]
    assert data["source"]["asset_type"] == "text"
    assert data["entities"]["materials"] == ["Ni-Mo catalyst"]
    assert data["relations"][0]["predicate"] == "has Tafel slope"
    assert validate_evidence_card(card) == []


def test_missing_provenance_returns_validation_errors():
    card = _valid_card()
    card.paper_id = ""
    card.source.source_path = ""

    errors = validate_evidence_card(card)

    assert "paper_id is required" in errors
    assert "source.source_path is required" in errors


def test_invalid_roles_return_validation_errors():
    card = _valid_card()
    card.primary_role = "HER"
    card.secondary_roles = ["condition", "electrolyte"]

    errors = validate_evidence_card(card)

    assert "primary_role is invalid: HER" in errors
    assert "secondary_roles contains invalid role: electrolyte" in errors


def test_open_entities_and_relations_preserve_domain_content_without_domain_schema():
    card = _valid_card()
    card.entities.applications.append("alkaline hydrogen evolution")
    card.relations.append(
        EvidenceRelation(
            subject="PVDF composite membrane",
            predicate="has water flux",
            object="320 L m-2 h-1 bar-1",
            qualifiers={"rejection": "98.5%"},
            condition="0.1 MPa",
            confidence=0.75,
        )
    )

    data = card.as_dict()

    assert "alkaline hydrogen evolution" in data["entities"]["applications"]
    assert data["relations"][1]["subject"] == "PVDF composite membrane"
    assert data["relations"][1]["qualifiers"]["rejection"] == "98.5%"
    assert validate_evidence_card(card) == []


def test_deterministic_seed_and_card_ids_are_stable():
    candidate = _candidate()
    seed_a = evidence_card_seed_from_candidate(candidate)
    seed_b = evidence_card_seed_from_candidate(dict(candidate))

    assert seed_a.seed_id == seed_b.seed_id
    assert deterministic_seed_id(candidate) == seed_a.seed_id
    assert deterministic_card_id(seed_a) == deterministic_card_id(seed_b)
    assert deterministic_card_id(seed_a, extraction_version="v2") != deterministic_card_id(seed_a)


def test_domain_profile_terms_are_not_evidence_roles():
    forbidden = {"her", "membrane", "electrolyte", "tco", "alloy", "catalyst", "thermoelectric", "perovskite"}
    roles_lower = {role.lower() for role in EVIDENCE_ROLES}

    assert forbidden.isdisjoint(roles_lower)
