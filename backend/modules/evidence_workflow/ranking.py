"""M7 deterministic Evidence Card ranking and diversity selection."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .classification import compute_role_coverage
from .schemas import EvidenceCard

EVIDENCE_SELECTION_VERSION = "m7_evidence_ranking_selection_v1"
_SUPPORT_COMPONENTS = {"direct": 1.0, "indirect": 0.65, "weak": 0.35}
_SOURCE_TYPES = ("text", "abstract", "figure", "table", "caption")


@dataclass
class EvidenceRankingConfig:
    selection_limit: int | None = None
    max_per_paper: int | None = None
    max_per_source_type: int | None = None
    preserve_required_roles: bool = True
    relevance_weight: float = 0.40
    support_weight: float = 0.25
    confidence_weight: float = 0.15
    role_weight: float = 0.15
    evidence_richness_weight: float = 0.05

    def resolved(self, card_count: int, retrieval_budget: int | None = None) -> "EvidenceRankingConfig":
        limit = self.selection_limit
        if limit is None:
            limit = retrieval_budget or 12
        limit = max(0, min(int(limit), int(card_count)))
        max_per_paper = self.max_per_paper if self.max_per_paper is not None else max(1, math.ceil(limit * 0.40))
        max_per_source_type = (
            self.max_per_source_type
            if self.max_per_source_type is not None
            else max(1, math.ceil(limit * 0.60))
        )
        return EvidenceRankingConfig(
            selection_limit=limit,
            max_per_paper=max(1, int(max_per_paper)) if limit else 0,
            max_per_source_type=max(1, int(max_per_source_type)) if limit else 0,
            preserve_required_roles=self.preserve_required_roles,
            relevance_weight=self.relevance_weight,
            support_weight=self.support_weight,
            confidence_weight=self.confidence_weight,
            role_weight=self.role_weight,
            evidence_richness_weight=self.evidence_richness_weight,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RankedEvidenceCard:
    rank: int
    evidence_id: str
    score: float
    score_components: dict[str, float]
    selected: bool
    selection_reasons: list[str]
    card: EvidenceCard

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "evidence_id": self.evidence_id,
            "score": self.score,
            "score_components": dict(self.score_components),
            "selected": self.selected,
            "selection_reasons": list(self.selection_reasons),
            "card": self.card.as_dict(),
        }


@dataclass
class EvidenceSelectionResult:
    ranked_cards: list[RankedEvidenceCard]
    selected_card_objects: list[EvidenceCard]
    coverage: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    ranking_config: dict[str, Any] = field(default_factory=dict)
    selection_version: str = EVIDENCE_SELECTION_VERSION

    @property
    def card_count(self) -> int:
        return len(self.ranked_cards)

    @property
    def selected_count(self) -> int:
        return len(self.selected_card_objects)

    @property
    def selected_cards(self) -> list[dict[str, Any]]:
        return [card.as_dict() for card in self.selected_card_objects]

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "evidence_selection",
            "selection_version": self.selection_version,
            "card_count": self.card_count,
            "selected_count": self.selected_count,
            "ranking_config": dict(self.ranking_config),
            "ranked_cards": [item.as_dict() for item in self.ranked_cards],
            "selected_cards": self.selected_cards,
            "coverage": self.coverage,
            "warnings": list(self.warnings),
        }


def rank_evidence_cards(
    cards: list[EvidenceCard],
    *,
    task_profile: Any | None = None,
    config: EvidenceRankingConfig | None = None,
) -> list[RankedEvidenceCard]:
    cfg = config or EvidenceRankingConfig()
    required_roles = set(_task_profile_roles(task_profile, "required_evidence_roles"))
    optional_roles = set(_task_profile_roles(task_profile, "optional_evidence_roles"))

    scored: list[tuple[float, float, float, str, EvidenceCard, dict[str, float]]] = []
    for card in cards:
        components = _score_components(card, required_roles, optional_roles)
        score = (
            components["relevance"] * cfg.relevance_weight
            + components["support"] * cfg.support_weight
            + components["confidence"] * cfg.confidence_weight
            + components["role"] * cfg.role_weight
            + components["evidence_richness"] * cfg.evidence_richness_weight
        )
        scored.append(
            (
                round(score, 8),
                components["relevance"],
                components["support"],
                card.evidence_id,
                card,
                components,
            )
        )

    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return [
        RankedEvidenceCard(
            rank=index,
            evidence_id=card.evidence_id,
            score=score,
            score_components=components,
            selected=False,
            selection_reasons=[],
            card=card,
        )
        for index, (score, _relevance, _support, _evidence_id, card, components) in enumerate(scored, 1)
    ]


def select_representative_evidence(
    cards: list[EvidenceCard],
    *,
    task_profile: Any | None = None,
    retrieval_budget: int | None = None,
    config: EvidenceRankingConfig | None = None,
) -> EvidenceSelectionResult:
    base_config = config or EvidenceRankingConfig()
    cfg = base_config.resolved(len(cards), retrieval_budget)
    ranked = rank_evidence_cards(cards, task_profile=task_profile, config=cfg)
    by_id = {item.evidence_id: item for item in ranked}
    selected_ids: list[str] = []
    warnings: list[str] = []
    caps_relaxed = False

    required_roles = _task_profile_roles(task_profile, "required_evidence_roles")
    available_required = _available_required_roles(cards, required_roles)
    missing_required_roles = [role for role in required_roles if role not in available_required]
    if missing_required_roles:
        warnings.append("missing_required_roles")

    if cfg.preserve_required_roles:
        for role in _selection_required_role_order(required_roles):
            if role in missing_required_roles or len(selected_ids) >= int(cfg.selection_limit or 0):
                continue
            candidate = _best_for_role(ranked, role, selected_ids, cfg, enforce_caps=True)
            if candidate is None:
                candidate = _best_for_role(ranked, role, selected_ids, cfg, enforce_caps=False)
                caps_relaxed = True
            if candidate is not None:
                _select(candidate, selected_ids, f"required_role:{role}")

    for item in ranked:
        if len(selected_ids) >= int(cfg.selection_limit or 0):
            break
        if item.evidence_id in selected_ids:
            continue
        if _within_caps(item.card, selected_ids, by_id, cfg, check_paper=True, check_source=True):
            _select(item, selected_ids, "high_score")

    if len(selected_ids) < int(cfg.selection_limit or 0):
        for item in ranked:
            if len(selected_ids) >= int(cfg.selection_limit or 0):
                break
            if item.evidence_id in selected_ids:
                continue
            if _within_caps(item.card, selected_ids, by_id, cfg, check_paper=True, check_source=False):
                caps_relaxed = True
                _select(item, selected_ids, "high_score")

    if len(selected_ids) < int(cfg.selection_limit or 0):
        for item in ranked:
            if len(selected_ids) >= int(cfg.selection_limit or 0):
                break
            if item.evidence_id in selected_ids:
                continue
            caps_relaxed = True
            _select(item, selected_ids, "high_score")

    selected_cards = [by_id[evidence_id].card for evidence_id in selected_ids]
    if caps_relaxed:
        warnings.append("selection_caps_relaxed_to_fill_budget")
    coverage = compute_selection_coverage(selected_cards, cards, task_profile)
    warnings.extend(_coverage_warnings(coverage, selected_cards, all_cards=cards))
    warnings = _dedupe(warnings)
    for item in ranked:
        if item.evidence_id in selected_ids:
            item.selected = True
    return EvidenceSelectionResult(
        ranked_cards=ranked,
        selected_card_objects=selected_cards,
        coverage=coverage,
        warnings=warnings,
        ranking_config=cfg.as_dict(),
    )


def compute_selection_coverage(
    selected_cards: list[EvidenceCard],
    all_cards: list[EvidenceCard],
    task_profile: Any | None = None,
) -> dict[str, Any]:
    return {
        "role_coverage": compute_role_coverage(selected_cards, task_profile),
        "source_type_coverage": {
            "selected": _count_by_source_type(selected_cards),
            "available": _count_by_source_type(all_cards),
        },
        "paper_coverage": {
            "selected": _count_by_paper(selected_cards),
            "available": _count_by_paper(all_cards),
        },
        "missing_required_roles": compute_role_coverage(selected_cards, task_profile).get("missing_required_roles", []),
    }


def save_selection_result(store: Any, workflow_id: str, result: EvidenceSelectionResult) -> dict[str, Any]:
    return store.save_evidence_selection(workflow_id, result.as_dict())


def _score_components(card: EvidenceCard, required_roles: set[str], optional_roles: set[str]) -> dict[str, float]:
    relevance = _clamp(card.relevance.relevance_score, default=0.0)
    support = _SUPPORT_COMPONENTS.get(card.support.support_strength, 0.35)
    confidence = _clamp(card.support.extraction_confidence, default=0.5)
    role = _role_component(card, required_roles, optional_roles)
    richness = _richness_component(card)
    return {
        "relevance": relevance,
        "support": support,
        "confidence": confidence,
        "role": role,
        "evidence_richness": richness,
    }


def _role_component(card: EvidenceCard, required_roles: set[str], optional_roles: set[str]) -> float:
    if card.primary_role in required_roles:
        return 1.0
    if card.primary_role in optional_roles:
        return 0.75
    if any(role in required_roles or role in optional_roles for role in card.secondary_roles):
        return 0.65
    return 0.4


def _richness_component(card: EvidenceCard) -> float:
    score = 0.0
    if card.relations:
        score += 0.4
    if any(getattr(card.entities, field_name) for field_name in card.entities.__dict__):
        score += 0.4
    if card.source.locator:
        score += 0.2
    return min(score, 1.0)


def _best_for_role(
    ranked: list[RankedEvidenceCard],
    role: str,
    selected_ids: list[str],
    cfg: EvidenceRankingConfig,
    *,
    enforce_caps: bool,
) -> RankedEvidenceCard | None:
    primary_matches = [item for item in ranked if item.card.primary_role == role]
    secondary_matches = [item for item in ranked if role in item.card.secondary_roles and item.card.primary_role != role]
    for item in [*primary_matches, *secondary_matches]:
        if item.evidence_id in selected_ids:
            continue
        if not enforce_caps or _within_caps(item.card, selected_ids, {ranked_item.evidence_id: ranked_item for ranked_item in ranked}, cfg):
            return item
    return None


def _select(item: RankedEvidenceCard, selected_ids: list[str], reason: str) -> None:
    selected_ids.append(item.evidence_id)
    item.selected = True
    item.selection_reasons = _dedupe([*item.selection_reasons, reason])


def _within_caps(
    card: EvidenceCard,
    selected_ids: list[str],
    by_id: dict[str, RankedEvidenceCard],
    cfg: EvidenceRankingConfig,
    *,
    check_paper: bool = True,
    check_source: bool = True,
) -> bool:
    selected = [by_id[evidence_id].card for evidence_id in selected_ids]
    if check_paper and _count_matching(selected, lambda item: item.paper_id == card.paper_id) >= int(cfg.max_per_paper or 0):
        return False
    if check_source and _count_matching(selected, lambda item: item.source.asset_type == card.source.asset_type) >= int(cfg.max_per_source_type or 0):
        return False
    return True


def _available_required_roles(cards: list[EvidenceCard], required_roles: list[str]) -> set[str]:
    available: set[str] = set()
    required = set(required_roles)
    for card in cards:
        if card.primary_role in required:
            available.add(card.primary_role)
        for role in card.secondary_roles:
            if role in required:
                available.add(role)
    return available


def _selection_required_role_order(required_roles: list[str]) -> list[str]:
    return [role for role in required_roles if role != "background"] + [
        role for role in required_roles if role == "background"
    ]


def _coverage_warnings(coverage: dict[str, Any], selected_cards: list[EvidenceCard], *, all_cards: list[EvidenceCard]) -> list[str]:
    warnings: list[str] = []
    paper_counts = coverage["paper_coverage"]["selected"]
    if selected_cards and max(paper_counts.values() or [0]) / len(selected_cards) > 0.5:
        warnings.append("dominant_paper_warning")
    selected_source_counts = coverage["source_type_coverage"]["selected"]
    if len([count for count in selected_source_counts.values() if count]) == 1 and len(selected_cards) > 1:
        warnings.append("single_source_type_warning")
    available_source_counts = coverage["source_type_coverage"]["available"]
    for source_type in ("figure", "table", "caption"):
        if available_source_counts.get(source_type, 0) == 0:
            warnings.append(f"missing_{source_type}_source_type")
    return warnings


def _count_by_source_type(cards: list[EvidenceCard]) -> dict[str, int]:
    counts = {source_type: 0 for source_type in _SOURCE_TYPES}
    for card in cards:
        counts[card.source.asset_type] = counts.get(card.source.asset_type, 0) + 1
    return counts


def _count_by_paper(cards: list[EvidenceCard]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.paper_id] = counts.get(card.paper_id, 0) + 1
    return counts


def _count_matching(cards: list[EvidenceCard], predicate) -> int:
    return sum(1 for card in cards if predicate(card))


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


def _clamp(value: Any, *, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(float(value), 1.0))


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "EVIDENCE_SELECTION_VERSION",
    "EvidenceRankingConfig",
    "RankedEvidenceCard",
    "EvidenceSelectionResult",
    "compute_selection_coverage",
    "rank_evidence_cards",
    "save_selection_result",
    "select_representative_evidence",
]
