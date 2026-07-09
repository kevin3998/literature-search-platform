"""Initial Evidence Card draft extraction for M5."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .schemas import (
    EvidenceCard,
    EvidenceCardSeed,
    EvidenceEntities,
    EvidenceRelevance,
    EvidenceSource,
    EvidenceSupport,
    deterministic_card_id,
    validate_evidence_card,
)

INITIAL_EXTRACTION_VERSION = "m5_initial_v1"
MAX_VERBATIM_CHARS = 1200
SUPPORT_STRENGTHS = {"direct", "indirect", "weak"}
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

InitialExtractor = Callable[[EvidenceCardSeed, str, Any | None], dict[str, Any]]


@dataclass
class EvidenceExtractionResult:
    cards: list[EvidenceCard] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_seed_ids: list[str] = field(default_factory=list)
    extraction_version: str = INITIAL_EXTRACTION_VERSION

    @property
    def card_count(self) -> int:
        return len(self.cards)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cards": [card.as_dict() for card in self.cards],
            "warnings": list(self.warnings),
            "skipped_seed_ids": list(self.skipped_seed_ids),
            "extraction_version": self.extraction_version,
            "card_count": self.card_count,
        }


def extract_initial_cards(
    seeds: list[EvidenceCardSeed],
    *,
    topic: str,
    task_profile: Any | None = None,
    extractor: InitialExtractor | None = None,
    extraction_version: str = INITIAL_EXTRACTION_VERSION,
) -> EvidenceExtractionResult:
    result = EvidenceExtractionResult(extraction_version=extraction_version)
    for seed in seeds:
        card, warnings = _extract_card_with_warnings(
            seed,
            topic=topic,
            task_profile=task_profile,
            extractor=extractor,
            extraction_version=extraction_version,
        )
        result.warnings.extend(warnings)
        if card is None:
            result.skipped_seed_ids.append(seed.seed_id)
        else:
            result.cards.append(card)
    result.warnings = _dedupe(result.warnings)
    return result


def extract_initial_card(
    seed: EvidenceCardSeed,
    *,
    topic: str,
    task_profile: Any | None = None,
    extractor: InitialExtractor | None = None,
    extraction_version: str = INITIAL_EXTRACTION_VERSION,
) -> EvidenceCard:
    card, warnings = _extract_card_with_warnings(
        seed,
        topic=topic,
        task_profile=task_profile,
        extractor=extractor,
        extraction_version=extraction_version,
    )
    if card is None:
        message = "; ".join(warnings) or f"could not extract seed: {seed.seed_id}"
        raise ValueError(message)
    return card


def save_initial_extraction_result(store: Any, workflow_id: str, result: EvidenceExtractionResult) -> dict[str, Any]:
    return store.save_cards(
        workflow_id,
        result.cards,
        schema_version="m1",
        extraction_version=result.extraction_version,
        source="m5_initial_extraction",
        metadata={
            "warnings": list(result.warnings),
            "skipped_seed_ids": list(result.skipped_seed_ids),
            "card_count": result.card_count,
        },
    )


def _extract_card_with_warnings(
    seed: EvidenceCardSeed,
    *,
    topic: str,
    task_profile: Any | None,
    extractor: InitialExtractor | None,
    extraction_version: str,
) -> tuple[EvidenceCard | None, list[str]]:
    warnings: list[str] = []
    raw = _source_text(seed)
    if not raw:
        return None, [f"missing_raw_text_or_caption:{seed.seed_id}"]

    extractor_data: dict[str, Any] = {}
    if extractor is not None:
        try:
            raw_output = extractor(seed, topic, task_profile)
        except Exception:  # noqa: BLE001 - per-seed failure should not block extraction
            warnings.append(f"extractor_failed:{seed.seed_id}")
        else:
            extractor_data, invalid = _normalize_extractor_output(raw_output)
            if invalid:
                warnings.append(f"extractor_invalid_output:{seed.seed_id}")
                extractor_data = {}
            warnings.extend(extractor_data.get("warnings") or [])

    support_strength = extractor_data.get("support_strength") or "weak"
    if support_strength not in SUPPORT_STRENGTHS:
        warnings.append(f"invalid_support_strength:{seed.seed_id}")
        support_strength = "weak"

    primary_role = _provisional_primary_role(seed)
    unsupported_parts = list(extractor_data.get("unsupported_parts") or [])
    if primary_role == "background":
        unsupported_parts.append("primary_role_provisional_pending_m6")

    card = EvidenceCard(
        evidence_id=deterministic_card_id(seed, extraction_version=extraction_version),
        seed_id=seed.seed_id,
        source_evidence_id=seed.source_evidence_id,
        paper_id=seed.paper_id,
        title=seed.title,
        doi=seed.doi,
        year=seed.year,
        journal=seed.journal,
        source=EvidenceSource(
            source_path=seed.source_path,
            asset_type=seed.asset_type,
            section_id=seed.section_id,
            chunk_id=seed.chunk_id,
            asset_id=seed.asset_id,
            locator=dict(seed.locator or {}),
        ),
        primary_role=primary_role,
        secondary_roles=[],
        verbatim_snippet=_clip_verbatim(raw),
        normalized_statement=extractor_data.get("normalized_statement") or _normalize_statement(raw),
        entities=EvidenceEntities(),
        relations=[],
        relevance=EvidenceRelevance(
            topic=topic,
            relevance_reason=extractor_data.get("relevance_reason"),
            relevance_score=seed.retrieval_score,
        ),
        support=EvidenceSupport(
            support_strength=support_strength,
            extraction_confidence=extractor_data.get("extraction_confidence"),
            uncertainty=None,
            unsupported_parts=_dedupe(unsupported_parts),
        ),
    )

    errors = validate_evidence_card(card)
    if errors:
        warnings.append(f"card_validation_failed:{seed.seed_id}:{'|'.join(errors)}")
        return None, warnings
    return card, warnings


def _normalize_extractor_output(value: Any) -> tuple[dict[str, Any], bool]:
    if not isinstance(value, dict):
        return {}, True
    out: dict[str, Any] = {}
    invalid = False

    for key in ("normalized_statement", "relevance_reason", "support_strength"):
        if value.get(key) is not None:
            if not isinstance(value[key], str):
                invalid = True
                continue
            out[key] = value[key].strip()
    if out.get("support_strength"):
        out["support_strength"] = _normalize_support_strength(out["support_strength"])

    if value.get("extraction_confidence") is not None:
        confidence = _normalize_confidence(value["extraction_confidence"])
        if confidence is None:
            invalid = True
        else:
            out["extraction_confidence"] = confidence

    for key in ("unsupported_parts", "warnings"):
        if value.get(key) is not None:
            normalized_list = _normalize_string_list(value[key])
            if normalized_list is None:
                invalid = True
                continue
            out[key] = normalized_list

    return out, invalid


def _normalize_support_strength(value: str) -> str:
    normalized = value.strip().lower()
    return SUPPORT_STRENGTH_ALIASES.get(normalized, normalized)


def _normalize_confidence(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        confidence = float(value)
        return confidence if 0 <= confidence <= 1 else None
    if isinstance(value, str):
        return CONFIDENCE_ALIASES.get(value.strip().lower())
    return None


def _normalize_string_list(value: Any) -> list[str] | None:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item for item in value if item]
    return None


def _source_text(seed: EvidenceCardSeed) -> str:
    return _clean_text(seed.raw_text or seed.raw_caption or "")


def _clip_verbatim(text: str) -> str:
    text = text.strip()
    return text[:MAX_VERBATIM_CHARS]


def _normalize_statement(text: str) -> str:
    return " ".join(text.split())


def _clean_text(text: str) -> str:
    return str(text or "").strip()


def _provisional_primary_role(seed: EvidenceCardSeed) -> str:
    if seed.asset_type == "figure":
        return "figure_evidence"
    if seed.asset_type == "table":
        return "table_evidence"
    return "background"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "INITIAL_EXTRACTION_VERSION",
    "EvidenceExtractionResult",
    "extract_initial_card",
    "extract_initial_cards",
    "save_initial_extraction_result",
]
