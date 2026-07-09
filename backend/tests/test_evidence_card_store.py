from pathlib import Path

import pytest

from modules.evidence_workflow.schemas import (
    EvidenceCard,
    EvidenceEntities,
    EvidenceRelation,
    EvidenceRelevance,
    EvidenceSource,
    EvidenceSupport,
)
from modules.evidence_workflow.store import EvidenceCardStore


def _sample_card() -> EvidenceCard:
    return EvidenceCard(
        evidence_id="ecard_123",
        seed_id="seed_123",
        source_evidence_id="ev_123",
        paper_id="paper_123",
        doi="10.1000/example",
        title="Example materials paper",
        year=2025,
        journal="Journal of Evidence",
        source=EvidenceSource(
            source_path="literature-data/paper_123/full_text.json",
            asset_type="text",
            section_id="results",
            chunk_id=7,
            locator={"section": "Results", "paragraph": 3},
        ),
        primary_role="performance",
        secondary_roles=["material_system", "condition"],
        verbatim_snippet="The sample reached 42 mA cm-2 at 1.6 V.",
        normalized_statement="The sample showed measurable performance under stated test conditions.",
        entities=EvidenceEntities(
            materials=["NiFe LDH"],
            methods=["hydrothermal synthesis"],
            metrics=["current density"],
            values=["42"],
            units=["mA cm-2"],
            conditions=["1.6 V"],
        ),
        relations=[
            EvidenceRelation(
                subject="NiFe LDH",
                predicate="reached",
                object="42 mA cm-2",
                qualifiers={"voltage": "1.6 V"},
                condition="alkaline electrolyte",
                confidence=0.82,
            )
        ],
        relevance=EvidenceRelevance(
            topic="transition metal hydroxide electrocatalysts",
            relevance_reason="Reports performance under comparable conditions.",
            relevance_score=0.91,
        ),
        support=EvidenceSupport(
            support_strength="direct",
            extraction_confidence=0.88,
            uncertainty="single-paper observation",
            unsupported_parts=["long-term durability"],
        ),
    )


def test_save_and_load_cards_round_trip_preserves_schema_fields(tmp_path: Path) -> None:
    store = EvidenceCardStore(tmp_path)
    manifest = store.save_cards(
        "wf_123",
        [_sample_card()],
        schema_version="m1",
        extraction_version="not_started",
        source="test_suite",
    )

    artifact_path = tmp_path / "research_agent/evidence_workflows/wf_123/evidence_cards.json"
    assert artifact_path.exists()
    assert manifest["artifact_type"] == "evidence_cards"
    assert manifest["workflow_id"] == "wf_123"
    assert manifest["schema_version"] == "m1"
    assert manifest["extraction_version"] == "not_started"
    assert manifest["source"] == "test_suite"
    assert manifest["card_count"] == 1

    loaded = store.load_cards("wf_123")
    card = loaded["cards"][0]
    assert loaded["card_count"] == 1
    assert card["evidence_id"] == "ecard_123"
    assert card["source"]["source_path"] == "literature-data/paper_123/full_text.json"
    assert card["source"]["locator"] == {"section": "Results", "paragraph": 3}
    assert card["primary_role"] == "performance"
    assert card["secondary_roles"] == ["material_system", "condition"]
    assert card["entities"]["materials"] == ["NiFe LDH"]
    assert card["entities"]["conditions"] == ["1.6 V"]
    assert card["relations"][0]["qualifiers"] == {"voltage": "1.6 V"}
    assert card["relations"][0]["confidence"] == 0.82
    assert card["relevance"]["relevance_score"] == 0.91
    assert card["support"]["support_strength"] == "direct"
    assert card["support"]["unsupported_parts"] == ["long-term durability"]


def test_artifact_event_uses_existing_job_event_shape(tmp_path: Path) -> None:
    store = EvidenceCardStore(tmp_path)
    event = store.artifact_event("wf_123", label="Evidence Cards")

    expected_path = "research_agent/evidence_workflows/wf_123/evidence_cards.json"
    assert event == {
        "type": "artifact",
        "artifact_type": "evidence_cards",
        "artifact_id": expected_path,
        "path": expected_path,
        "label": "Evidence Cards",
    }


def test_list_card_artifacts_supports_all_and_single_workflow(tmp_path: Path) -> None:
    store = EvidenceCardStore(tmp_path)
    store.save_cards("wf_123", [_sample_card()])
    store.save_cards("wf_456", [_sample_card(), _sample_card()])

    all_artifacts = store.list_card_artifacts()
    assert {artifact["workflow_id"] for artifact in all_artifacts} == {"wf_123", "wf_456"}
    assert {
        artifact["artifact_id"] for artifact in all_artifacts
    } == {
        "research_agent/evidence_workflows/wf_123/evidence_cards.json",
        "research_agent/evidence_workflows/wf_456/evidence_cards.json",
    }

    wf_456 = store.list_card_artifacts("wf_456")
    assert len(wf_456) == 1
    assert wf_456[0]["workflow_id"] == "wf_456"
    assert wf_456[0]["card_count"] == 2
    assert wf_456[0]["schema_version"] == "m1"
    assert wf_456[0]["extraction_version"] == "not_started"


@pytest.mark.parametrize("workflow_id", ["", "../escape", "a/b", "a\\b", "..", "wf 123"])
def test_invalid_workflow_ids_are_rejected(tmp_path: Path, workflow_id: str) -> None:
    store = EvidenceCardStore(tmp_path)

    with pytest.raises(ValueError):
        store.save_cards(workflow_id, [_sample_card()])
    with pytest.raises(ValueError):
        store.load_cards(workflow_id)
    with pytest.raises(ValueError):
        store.artifact_event(workflow_id)


def test_store_module_does_not_import_sqlite_or_memory_db() -> None:
    store_source = Path("backend/modules/evidence_workflow/store.py").read_text(encoding="utf-8")

    assert "core.memory_db" not in store_source
    assert "sqlite" not in store_source.lower()
