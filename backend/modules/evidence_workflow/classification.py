"""M6 Evidence Card role, entity, and relation enrichment.

This module enriches M5 Evidence Card drafts. It is deliberately isolated from
workflow execution, APIs, retrieval services, and database-backed state.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from .schemas import (
    EVIDENCE_ROLES,
    SUPPORT_STRENGTHS,
    EvidenceCard,
    EvidenceEntities,
    EvidenceRelation,
    validate_evidence_card,
)

ROLE_ENRICHMENT_VERSION = "m6_role_entity_relation_v1"
FALLBACK_UNCERTAINTY = "M6 fallback did not perform semantic role classification."
PROVISIONAL_MARKER = "primary_role_provisional_pending_m6"
SUPPORT_STRENGTH_ALIASES = {
    "high": "direct",
    "strong": "direct",
    "moderate": "indirect",
    "medium": "indirect",
    "partial": "indirect",
    "low": "weak",
    "limited": "weak",
}
CONFIDENCE_ALIASES = {"high": 0.85, "medium": 0.6, "moderate": 0.6, "low": 0.35}
ENTITY_TYPE_FIELD_ALIASES = {
    "material": "materials",
    "materials": "materials",
    "compound": "materials",
    "model": "methods",
    "method": "methods",
    "technology": "methods",
    "tool": "methods",
    "algorithm": "methods",
    "property": "properties",
    "metric": "metrics",
    "value": "values",
    "unit": "units",
    "condition": "conditions",
    "characterization": "characterization_tools",
    "characterization_tool": "characterization_tools",
    "mechanism": "mechanisms",
    "application": "applications",
    "task": "applications",
    "domain": "applications",
}

Classifier = Callable[[EvidenceCard, str, Any | None], dict[str, Any]]

_ENTITY_FIELDS = tuple(EvidenceEntities().__dict__.keys())


@dataclass
class EvidenceEnrichmentResult:
    cards: list[EvidenceCard] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_card_ids: list[str] = field(default_factory=list)
    role_coverage: dict[str, Any] = field(default_factory=dict)
    enrichment_version: str = ROLE_ENRICHMENT_VERSION

    @property
    def card_count(self) -> int:
        return len(self.cards)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cards": [card.as_dict() for card in self.cards],
            "warnings": list(self.warnings),
            "skipped_card_ids": list(self.skipped_card_ids),
            "role_coverage": dict(self.role_coverage),
            "enrichment_version": self.enrichment_version,
            "card_count": self.card_count,
        }


def enrich_evidence_cards(
    cards: list[EvidenceCard],
    *,
    topic: str,
    task_profile: Any | None = None,
    classifier: Classifier | None = None,
    enrichment_version: str = ROLE_ENRICHMENT_VERSION,
) -> EvidenceEnrichmentResult:
    result = EvidenceEnrichmentResult(enrichment_version=enrichment_version)
    for card in cards:
        enriched, warnings = _enrich_card_with_warnings(
            card,
            topic=topic,
            task_profile=task_profile,
            classifier=classifier,
        )
        result.warnings.extend(warnings)
        if enriched is None:
            result.skipped_card_ids.append(card.evidence_id)
        else:
            result.cards.append(enriched)
    result.warnings = _dedupe(result.warnings)
    result.role_coverage = compute_role_coverage(result.cards, task_profile)
    return result


def enrich_evidence_card(
    card: EvidenceCard,
    *,
    topic: str,
    task_profile: Any | None = None,
    classifier: Classifier | None = None,
    enrichment_version: str = ROLE_ENRICHMENT_VERSION,
) -> EvidenceCard:
    enriched, warnings = _enrich_card_with_warnings(
        card,
        topic=topic,
        task_profile=task_profile,
        classifier=classifier,
    )
    if enriched is None:
        message = "; ".join(warnings) or f"could not enrich card: {card.evidence_id}"
        raise ValueError(message)
    return enriched


def save_enrichment_result(store: Any, workflow_id: str, result: EvidenceEnrichmentResult) -> dict[str, Any]:
    return store.save_cards(
        workflow_id,
        result.cards,
        schema_version="m1",
        extraction_version=result.enrichment_version,
        source="m6_role_entity_relation_enrichment",
        metadata={
            "warnings": list(result.warnings),
            "skipped_card_ids": list(result.skipped_card_ids),
            "card_count": result.card_count,
            "role_coverage": result.role_coverage,
        },
    )


def compute_role_coverage(cards: list[EvidenceCard], task_profile: Any | None = None) -> dict[str, Any]:
    primary_role_counts: dict[str, int] = {}
    secondary_role_counts: dict[str, int] = {}
    by_role: dict[str, int] = {}

    for card in cards:
        _increment(primary_role_counts, card.primary_role)
        _increment(by_role, card.primary_role)
        for role in card.secondary_roles:
            _increment(secondary_role_counts, role)
            _increment(by_role, role)

    required_roles = _task_profile_roles(task_profile, "required_evidence_roles")
    optional_roles = _task_profile_roles(task_profile, "optional_evidence_roles")
    missing_required_roles = [role for role in required_roles if by_role.get(role, 0) == 0]

    return {
        "by_role": by_role,
        "primary_role_counts": primary_role_counts,
        "secondary_role_counts": secondary_role_counts,
        "required_roles": required_roles,
        "optional_roles": optional_roles,
        "missing_required_roles": missing_required_roles,
    }


def _enrich_card_with_warnings(
    card: EvidenceCard,
    *,
    topic: str,
    task_profile: Any | None,
    classifier: Classifier | None,
) -> tuple[EvidenceCard | None, list[str]]:
    warnings: list[str] = []
    enriched = deepcopy(card)
    _set_topic_if_missing(enriched, topic)

    if classifier is None:
        _apply_fallback(enriched)
        warnings.append(f"role_enrichment_fallback:{card.evidence_id}")
        return _validated_or_none(enriched, warnings)

    try:
        raw_output = classifier(deepcopy(card), topic, task_profile)
    except Exception:  # noqa: BLE001 - classifier failure should not block batch enrichment
        _apply_fallback(enriched)
        warnings.extend([f"classifier_failed:{card.evidence_id}", f"role_enrichment_fallback:{card.evidence_id}"])
        return _validated_or_none(enriched, warnings)

    if not isinstance(raw_output, dict):
        _apply_fallback(enriched)
        warnings.extend([f"classifier_invalid_output:{card.evidence_id}", f"role_enrichment_fallback:{card.evidence_id}"])
        return _validated_or_none(enriched, warnings)

    warnings.extend(_clean_warning_list(raw_output.get("warnings")))

    _apply_roles(enriched, raw_output, warnings)
    _apply_entities(enriched, raw_output.get("entities"), warnings)
    _apply_relations(enriched, raw_output.get("relations"), warnings)
    _apply_support(enriched, raw_output, warnings)

    return _validated_or_none(enriched, warnings)


def _apply_roles(card: EvidenceCard, data: dict[str, Any], warnings: list[str]) -> None:
    primary = data.get("primary_role")
    if isinstance(primary, str) and primary in EVIDENCE_ROLES:
        card.primary_role = primary
    elif primary is not None:
        warnings.append(f"invalid_primary_role:{primary}:{card.evidence_id}")

    secondary = data.get("secondary_roles")
    if secondary is not None and not isinstance(secondary, list):
        warnings.append(f"invalid_secondary_roles:{card.evidence_id}")
        secondary = []

    valid_secondary: list[str] = []
    for role in secondary or []:
        if not isinstance(role, str) or role not in EVIDENCE_ROLES:
            warnings.append(f"invalid_secondary_role:{role}:{card.evidence_id}")
            continue
        if role == card.primary_role:
            continue
        valid_secondary.append(role)
    card.secondary_roles = _dedupe(valid_secondary)


def _apply_entities(card: EvidenceCard, value: Any, warnings: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, list):
        value = _entity_dict_from_typed_list(value, warnings, card.evidence_id)
    if not isinstance(value, dict):
        warnings.append(f"invalid_entities:{card.evidence_id}")
        return

    entities = EvidenceEntities()
    for field_name, field_value in value.items():
        if field_name not in _ENTITY_FIELDS:
            warnings.append(f"unknown_entity_field:{field_name}:{card.evidence_id}")
            continue
        if not isinstance(field_value, list) or not all(isinstance(item, str) for item in field_value):
            warnings.append(f"invalid_entity_field:{field_name}:{card.evidence_id}")
            continue
        setattr(entities, field_name, _dedupe([item.strip() for item in field_value if item.strip()]))
    card.entities = entities


def _apply_relations(card: EvidenceCard, value: Any, warnings: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        warnings.append(f"invalid_relations:{card.evidence_id}")
        return

    relations: list[EvidenceRelation] = []
    seen: set[tuple[str, str, str, str | None]] = set()
    for item in value:
        if not isinstance(item, dict):
            warnings.append(f"invalid_relation:{card.evidence_id}")
            continue
        subject = _clean_str(item.get("subject"))
        predicate = _clean_str(item.get("predicate"))
        object_value = _clean_str(item.get("object"))
        if not (subject and predicate and object_value):
            warnings.append(f"incomplete_relation:{card.evidence_id}")
            continue

        condition = _clean_optional_str(item.get("condition"))
        key = (subject, predicate, object_value, condition)
        if key in seen:
            continue
        seen.add(key)

        qualifiers = item.get("qualifiers") or {}
        if not isinstance(qualifiers, dict):
            warnings.append(f"invalid_relation_qualifiers:{card.evidence_id}")
            qualifiers = {}

        confidence = _confidence_or_none(item.get("confidence"))
        if item.get("confidence") is not None and confidence is None:
            warnings.append(f"invalid_relation_confidence:{card.evidence_id}")

        relations.append(
            EvidenceRelation(
                subject=subject,
                predicate=predicate,
                object=object_value,
                qualifiers=dict(qualifiers),
                condition=condition,
                confidence=confidence,
            )
        )
    card.relations = relations


def _apply_support(card: EvidenceCard, data: dict[str, Any], warnings: list[str]) -> None:
    support_strength = data.get("support_strength")
    if support_strength is not None:
        normalized_support = _normalize_support_strength(support_strength)
        if normalized_support in SUPPORT_STRENGTHS:
            card.support.support_strength = normalized_support
        else:
            warnings.append(f"invalid_support_strength:{card.evidence_id}")
            card.support.support_strength = "weak"

    if "extraction_confidence" in data:
        confidence = _confidence_or_none(data.get("extraction_confidence"))
        if data.get("extraction_confidence") is not None and confidence is None:
            warnings.append(f"invalid_extraction_confidence:{card.evidence_id}")
        card.support.extraction_confidence = confidence

    if data.get("uncertainty") is not None:
        card.support.uncertainty = _clean_optional_str(data.get("uncertainty"))

    if data.get("unsupported_parts") is not None:
        unsupported_parts = _normalize_string_list(data["unsupported_parts"])
        if unsupported_parts is not None:
            card.support.unsupported_parts = _dedupe(
                [item.strip() for item in unsupported_parts if item.strip() and item != PROVISIONAL_MARKER]
            )
        else:
            warnings.append(f"invalid_unsupported_parts:{card.evidence_id}")

    card.support.unsupported_parts = [item for item in card.support.unsupported_parts if item != PROVISIONAL_MARKER]


def _apply_fallback(card: EvidenceCard) -> None:
    if card.source.asset_type == "figure":
        card.primary_role = "figure_evidence"
    elif card.source.asset_type == "table":
        card.primary_role = "table_evidence"
    card.secondary_roles = _dedupe([role for role in card.secondary_roles if role != card.primary_role])
    card.support.unsupported_parts = [item for item in card.support.unsupported_parts if item != PROVISIONAL_MARKER]
    card.support.uncertainty = _append_uncertainty(card.support.uncertainty, FALLBACK_UNCERTAINTY)


def _validated_or_none(card: EvidenceCard, warnings: list[str]) -> tuple[EvidenceCard | None, list[str]]:
    errors = validate_evidence_card(card)
    if errors:
        warnings.append(f"card_validation_failed:{card.evidence_id}:{'|'.join(errors)}")
        return None, warnings
    return card, warnings


def _set_topic_if_missing(card: EvidenceCard, topic: str) -> None:
    if not card.relevance.topic:
        card.relevance.topic = topic


def _task_profile_roles(task_profile: Any | None, key: str) -> list[str]:
    if task_profile is None:
        return []
    if hasattr(task_profile, key):
        value = getattr(task_profile, key)
    elif isinstance(task_profile, dict):
        value = task_profile.get(key)
    else:
        value = None
    if not isinstance(value, list):
        return []
    return [role for role in value if isinstance(role, str)]


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _clean_warning_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _entity_dict_from_typed_list(value: list[Any], warnings: list[str], evidence_id: str) -> dict[str, list[str]]:
    entities: dict[str, list[str]] = {}
    for item in value:
        if not isinstance(item, dict):
            warnings.append(f"invalid_entity_item:{evidence_id}")
            continue
        name = _clean_optional_str(item.get("name") or item.get("text") or item.get("value"))
        raw_type = _clean_optional_str(item.get("type") or item.get("field") or item.get("category"))
        if not name or not raw_type:
            warnings.append(f"invalid_entity_item:{evidence_id}")
            continue
        field_name = ENTITY_TYPE_FIELD_ALIASES.get(raw_type.strip().lower())
        if not field_name:
            warnings.append(f"unknown_entity_type:{raw_type}:{evidence_id}")
            continue
        entities.setdefault(field_name, []).append(name)
    return entities


def _normalize_support_strength(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return SUPPORT_STRENGTH_ALIASES.get(normalized, normalized)


def _confidence_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if isinstance(value, str):
            return CONFIDENCE_ALIASES.get(value.strip().lower())
        return None
    confidence = float(value)
    if confidence < 0 or confidence > 1:
        return None
    return confidence


def _normalize_string_list(value: Any) -> list[str] | None:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item]
    return None


def _clean_str(value: Any) -> str:
    return str(value or "").strip()


def _clean_optional_str(value: Any) -> str | None:
    text = _clean_str(value)
    return text or None


def _append_uncertainty(existing: str | None, addition: str) -> str:
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing} {addition}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "ROLE_ENRICHMENT_VERSION",
    "EvidenceEnrichmentResult",
    "compute_role_coverage",
    "enrich_evidence_card",
    "enrich_evidence_cards",
    "save_enrichment_result",
]
