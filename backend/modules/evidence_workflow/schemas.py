"""Core Evidence Card contracts for the evidence workflow.

These are internal dataclass schemas, matching the style of the retrieval
packet contracts. They are intentionally free of persistence, extraction, LLM,
or database behavior.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

EVIDENCE_ROLES = {
    "background",
    "material_system",
    "method",
    "structure",
    "property",
    "performance",
    "mechanism",
    "characterization",
    "comparison",
    "limitation",
    "condition",
    "calculation",
    "hypothesis",
    "figure_evidence",
    "table_evidence",
}

SOURCE_ASSET_TYPES = {"text", "abstract", "figure", "table", "caption"}
SUPPORT_STRENGTHS = {"direct", "indirect", "weak"}


@dataclass
class EvidenceSource:
    source_path: str
    asset_type: str
    section_id: str | None = None
    chunk_id: int | str | None = None
    asset_id: str | None = None
    locator: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRelation:
    subject: str
    predicate: str
    object: str
    qualifiers: dict[str, Any] = field(default_factory=dict)
    condition: str | None = None
    confidence: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceEntities:
    materials: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    characterization_tools: list[str] = field(default_factory=list)
    mechanisms: list[str] = field(default_factory=list)
    applications: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRelevance:
    topic: str | None = None
    relevance_reason: str | None = None
    relevance_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceSupport:
    support_strength: str = "weak"
    extraction_confidence: float | None = None
    uncertainty: str | None = None
    unsupported_parts: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCardSeed:
    seed_id: str
    source_evidence_id: str | None
    paper_id: str
    doi: str | None = None
    title: str | None = None
    year: int | str | None = None
    journal: str | None = None
    source_path: str = ""
    section_id: str | None = None
    chunk_id: int | str | None = None
    asset_id: str | None = None
    asset_type: str = "text"
    locator: dict[str, Any] = field(default_factory=dict)
    raw_text: str | None = None
    raw_caption: str | None = None
    candidate_kind: str | None = None
    retrieval_score: float | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCard:
    evidence_id: str
    seed_id: str
    source_evidence_id: str | None
    paper_id: str
    source: EvidenceSource
    primary_role: str
    title: str | None = None
    doi: str | None = None
    year: int | str | None = None
    journal: str | None = None
    secondary_roles: list[str] = field(default_factory=list)
    verbatim_snippet: str | None = None
    normalized_statement: str | None = None
    entities: EvidenceEntities = field(default_factory=EvidenceEntities)
    relations: list[EvidenceRelation] = field(default_factory=list)
    relevance: EvidenceRelevance = field(default_factory=EvidenceRelevance)
    support: EvidenceSupport = field(default_factory=EvidenceSupport)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evidence_card_seed_from_candidate(candidate: dict[str, Any], *, topic: str | None = None) -> EvidenceCardSeed:
    """Convert a retrieval EvidenceCandidate-like dict into an EvidenceCardSeed."""
    locator = _locator_from_candidate(candidate)
    raw_text = candidate.get("snippet") or candidate.get("expanded_context") or candidate.get("text")
    raw_caption = candidate.get("caption")
    asset_type = _asset_type_from_candidate(candidate)
    warnings: list[str] = []
    if topic:
        locator.setdefault("topic", topic)
    if not raw_text and not raw_caption:
        warnings.append("missing_raw_text_or_caption")

    seed = EvidenceCardSeed(
        seed_id=deterministic_seed_id(candidate),
        source_evidence_id=_clean_str(candidate.get("evidence_id")),
        paper_id=_clean_str(candidate.get("paper_id")) or "",
        doi=_clean_str(candidate.get("doi")),
        title=_clean_str(candidate.get("title")),
        year=candidate.get("year"),
        journal=_clean_str(candidate.get("journal")),
        source_path=_clean_str(candidate.get("source_path")) or "",
        section_id=_clean_str(candidate.get("section_id")),
        chunk_id=candidate.get("chunk_index") if candidate.get("chunk_index") is not None else candidate.get("chunk_id"),
        asset_id=_clean_str(candidate.get("asset_id")),
        asset_type=asset_type,
        locator=locator,
        raw_text=_clean_str(raw_text),
        raw_caption=_clean_str(raw_caption),
        candidate_kind=_clean_str(candidate.get("kind")),
        retrieval_score=_to_float(candidate.get("relevance_score", candidate.get("score"))),
        warnings=warnings,
    )
    seed.warnings.extend(validate_evidence_card_seed(seed))
    # Preserve deterministic order and avoid duplicate warning strings.
    seed.warnings = list(dict.fromkeys(seed.warnings))
    return seed


def deterministic_seed_id(candidate: dict[str, Any]) -> str:
    payload = {
        "source_evidence_id": candidate.get("evidence_id"),
        "paper_id": candidate.get("paper_id"),
        "source_path": candidate.get("source_path"),
        "section_id": candidate.get("section_id"),
        "chunk_index": candidate.get("chunk_index", candidate.get("chunk_id")),
        "asset_id": candidate.get("asset_id"),
        "asset_label": candidate.get("asset_label") or candidate.get("label"),
        "kind": candidate.get("kind"),
    }
    return "seed_" + _stable_hash(payload)


def deterministic_card_id(seed: EvidenceCardSeed, *, extraction_version: str = "v1") -> str:
    payload = {
        "seed_id": seed.seed_id,
        "source_evidence_id": seed.source_evidence_id,
        "paper_id": seed.paper_id,
        "source_path": seed.source_path,
        "section_id": seed.section_id,
        "chunk_id": seed.chunk_id,
        "asset_id": seed.asset_id,
        "asset_type": seed.asset_type,
        "extraction_version": extraction_version,
    }
    return "ecard_" + _stable_hash(payload)


def validate_evidence_card_seed(seed: EvidenceCardSeed) -> list[str]:
    errors: list[str] = []
    if not seed.seed_id:
        errors.append("seed_id is required")
    if not seed.paper_id:
        errors.append("paper_id is required")
    if not seed.source_path:
        errors.append("source_path is required")
    if seed.asset_type not in SOURCE_ASSET_TYPES:
        errors.append(f"asset_type is invalid: {seed.asset_type}")
    if not (seed.raw_text or seed.raw_caption):
        errors.append("raw_text or raw_caption is required")
    return errors


def validate_evidence_card(card: EvidenceCard) -> list[str]:
    errors: list[str] = []
    if not card.evidence_id:
        errors.append("evidence_id is required")
    if not card.seed_id:
        errors.append("seed_id is required")
    if not card.paper_id:
        errors.append("paper_id is required")
    if not card.source.source_path:
        errors.append("source.source_path is required")
    if card.source.asset_type not in SOURCE_ASSET_TYPES:
        errors.append(f"source.asset_type is invalid: {card.source.asset_type}")
    if card.primary_role not in EVIDENCE_ROLES:
        errors.append(f"primary_role is invalid: {card.primary_role}")
    for role in card.secondary_roles:
        if role not in EVIDENCE_ROLES:
            errors.append(f"secondary_roles contains invalid role: {role}")
    if not (card.verbatim_snippet or card.normalized_statement):
        errors.append("verbatim_snippet or normalized_statement is required")
    if card.support.support_strength not in SUPPORT_STRENGTHS:
        errors.append(f"support.support_strength is invalid: {card.support.support_strength}")
    if card.support.extraction_confidence is not None and not _valid_confidence(card.support.extraction_confidence):
        errors.append(f"support.extraction_confidence is invalid: {card.support.extraction_confidence}")
    for index, relation in enumerate(card.relations):
        if not relation.subject:
            errors.append(f"relations[{index}].subject is required")
        if not relation.predicate:
            errors.append(f"relations[{index}].predicate is required")
        if not relation.object:
            errors.append(f"relations[{index}].object is required")
        if relation.confidence is not None and not _valid_confidence(relation.confidence):
            errors.append(f"relations[{index}].confidence is invalid: {relation.confidence}")
    return errors


def _asset_type_from_candidate(candidate: dict[str, Any]) -> str:
    explicit = _clean_str(candidate.get("asset_type"))
    if explicit in SOURCE_ASSET_TYPES:
        return explicit
    kind = (_clean_str(candidate.get("kind")) or "").lower()
    if "abstract" in kind:
        return "abstract"
    if "figure" in kind:
        return "figure" if not candidate.get("caption") else "caption"
    if "table" in kind:
        return "table" if not candidate.get("caption") else "caption"
    if "caption" in kind:
        return "caption"
    return "text"


def _locator_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    locator: dict[str, Any] = {}
    raw_locator = candidate.get("source_locator")
    if isinstance(raw_locator, dict):
        locator.update(raw_locator)
    asset_label = candidate.get("asset_label") or candidate.get("label")
    if asset_label:
        locator["asset_label"] = asset_label
    if candidate.get("section"):
        locator.setdefault("section", candidate.get("section"))
    if candidate.get("chunk_index") is not None:
        locator.setdefault("chunk_index", candidate.get("chunk_index"))
    return locator


def _stable_hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _valid_confidence(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0 <= float(value) <= 1
