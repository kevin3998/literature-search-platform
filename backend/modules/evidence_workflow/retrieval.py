"""Topic-scoped retrieval adapter for the evidence workflow."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .schemas import EvidenceCardSeed, SOURCE_ASSET_TYPES, evidence_card_seed_from_candidate
from .task_profiles import TaskProfile, build_scope_lock, resolve_task_profile

DEFAULT_RETRIEVAL_BUDGET = 24
ASSET_SOURCE_TYPES = {"figure", "table", "caption"}

AcquireEvidenceFn = Callable[..., dict[str, Any]]


@dataclass
class EvidenceSourceCandidatePacket:
    topic: str
    task_profile_id: str
    task_profile: dict[str, Any]
    scope_lock: dict[str, Any]
    retrieval_budget: int
    retrieval_options: dict[str, Any]
    source_candidates: list[dict[str, Any]] = field(default_factory=list)
    evidence_card_seeds: list[EvidenceCardSeed] = field(default_factory=list)
    source_type_coverage: dict[str, dict[str, int]] = field(default_factory=dict)
    coverage_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    underlying_packet: dict[str, Any] = field(default_factory=dict)
    query_plan: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    breadth: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def retrieve_source_candidates(
    acquire_evidence_fn: AcquireEvidenceFn,
    *,
    topic: str,
    task_profile_id: str | None = None,
    scope_lock: dict[str, Any] | None = None,
    retrieval_budget: int | None = None,
) -> EvidenceSourceCandidatePacket:
    profile = resolve_task_profile(task_profile_id or (scope_lock or {}).get("task_profile_id"))
    effective_scope_lock = _scope_lock(topic, profile.profile_id, scope_lock)
    budget = _retrieval_budget(retrieval_budget)
    retrieval_options = _retrieval_options(effective_scope_lock, budget)
    packet = acquire_evidence_fn(topic, has_history=False, **retrieval_options)
    return source_candidate_packet_from_acquisition(
        packet,
        topic=topic,
        task_profile=profile,
        scope_lock=effective_scope_lock,
        retrieval_budget=budget,
    )


def source_candidate_packet_from_acquisition(
    packet: dict[str, Any],
    *,
    topic: str,
    task_profile: TaskProfile | dict[str, Any],
    scope_lock: dict[str, Any],
    retrieval_budget: int | None,
) -> EvidenceSourceCandidatePacket:
    profile_dict = _task_profile_dict(task_profile)
    if not profile_dict.get("runnable", False):
        raise ValueError(f"task profile is not runnable: {profile_dict.get('profile_id')}")

    budget = _retrieval_budget(retrieval_budget)
    retrieval_options = _retrieval_options(scope_lock, budget)
    warnings = list(packet.get("warnings") or [])
    warnings_from_conversion: list[str] = []
    source_candidates: list[dict[str, Any]] = []
    seeds: list[EvidenceCardSeed] = []
    seen: set[tuple[Any, ...]] = set()

    for candidate in packet.get("evidence_candidates") or []:
        normalized = _normalize_candidate(candidate)
        _append_candidate(normalized, topic, seen, source_candidates, seeds)

    expanded_assets = packet.get("expanded_assets") or []
    if not expanded_assets:
        warnings_from_conversion.append("asset_retrieval_no_expanded_assets")
    for asset in expanded_assets:
        asset_candidate = _candidate_from_asset(asset, warnings_from_conversion)
        if asset_candidate is None:
            continue
        _append_candidate(asset_candidate, topic, seen, source_candidates, seeds)

    source_type_coverage = _source_type_coverage(source_candidates, seeds)
    if profile_dict.get("profile_id") == "topic-to-report":
        for asset_type in ("figure", "table", "caption"):
            if source_type_coverage[asset_type]["candidate_count"] == 0:
                warnings_from_conversion.append(f"missing_{asset_type}_candidates_best_effort")

    if any(seed.warnings for seed in seeds):
        warnings_from_conversion.append("seed_validation_warnings_present")

    warnings = _dedupe([*warnings, *warnings_from_conversion])
    coverage_notes = list(packet.get("coverage_notes") or [])

    return EvidenceSourceCandidatePacket(
        topic=topic,
        task_profile_id=str(profile_dict["profile_id"]),
        task_profile=profile_dict,
        scope_lock=dict(scope_lock),
        retrieval_budget=budget,
        retrieval_options=retrieval_options,
        source_candidates=source_candidates,
        evidence_card_seeds=seeds,
        source_type_coverage=source_type_coverage,
        coverage_notes=coverage_notes,
        warnings=warnings,
        underlying_packet=packet,
        query_plan=packet.get("query_plan") or {},
        coverage=packet.get("coverage") or {},
        breadth=packet.get("breadth") or {},
    )


def _append_candidate(
    candidate: dict[str, Any],
    topic: str,
    seen: set[tuple[Any, ...]],
    source_candidates: list[dict[str, Any]],
    seeds: list[EvidenceCardSeed],
) -> None:
    key = _provenance_key(candidate)
    if key in seen:
        return
    seen.add(key)
    source_candidates.append(candidate)
    seeds.append(evidence_card_seed_from_candidate(candidate, topic=topic))


def _candidate_from_asset(asset: dict[str, Any], warnings: list[str]) -> dict[str, Any] | None:
    asset_type = _asset_type_from_asset(asset)
    if asset_type not in ASSET_SOURCE_TYPES:
        warnings.append("unsupported_asset_candidate_type")
        return None

    asset_id = _first_present(asset, "asset_id", "id", "asset_label")
    asset_label = _first_present(asset, "asset_label", "label")
    source_path = _first_present(asset, "source_path", "asset_path") or ""
    locator = dict(asset.get("source_locator") or {})
    if asset_label:
        locator.setdefault("asset_label", asset_label)
    if asset.get("asset_path"):
        locator.setdefault("asset_path", asset.get("asset_path"))

    candidate = {
        "evidence_id": asset.get("evidence_id"),
        "paper_id": asset.get("paper_id"),
        "doi": asset.get("doi"),
        "title": asset.get("title"),
        "year": asset.get("year"),
        "journal": asset.get("journal"),
        "kind": asset.get("kind") or f"{asset_type}_asset",
        "section_id": asset.get("section_id"),
        "chunk_index": asset.get("chunk_index"),
        "snippet": asset.get("snippet") or asset.get("text"),
        "caption": asset.get("caption") or asset.get("raw_caption"),
        "source_path": source_path,
        "source_locator": locator,
        "asset_id": asset_id,
        "asset_label": asset_label,
        "asset_type": asset_type,
        "relevance_score": asset.get("relevance_score") or asset.get("score"),
    }
    return {key: value for key, value in candidate.items() if value is not None}


def _normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(candidate)
    normalized["asset_type"] = _asset_type_from_candidate(normalized)
    return normalized


def _source_type_coverage(
    source_candidates: list[dict[str, Any]],
    seeds: list[EvidenceCardSeed],
) -> dict[str, dict[str, int]]:
    coverage = {
        asset_type: {"candidate_count": 0, "seed_count": 0}
        for asset_type in sorted(SOURCE_ASSET_TYPES)
    }
    for candidate in source_candidates:
        asset_type = candidate.get("asset_type") or "text"
        if asset_type in coverage:
            coverage[asset_type]["candidate_count"] += 1
    for seed in seeds:
        if seed.asset_type in coverage:
            coverage[seed.asset_type]["seed_count"] += 1
    return coverage


def _asset_type_from_candidate(candidate: dict[str, Any]) -> str:
    explicit = _clean(candidate.get("asset_type"))
    if explicit in SOURCE_ASSET_TYPES:
        return explicit
    kind = (_clean(candidate.get("kind")) or "").lower()
    if "abstract" in kind:
        return "abstract"
    if "caption" in kind or candidate.get("caption") or candidate.get("raw_caption"):
        return "caption"
    if "figure" in kind:
        return "figure"
    if "table" in kind:
        return "table"
    return "text"


def _asset_type_from_asset(asset: dict[str, Any]) -> str | None:
    explicit = _clean(asset.get("asset_type"))
    if explicit in ASSET_SOURCE_TYPES:
        return explicit
    kind = (_clean(asset.get("kind")) or "").lower()
    if "caption" in kind or asset.get("caption") or asset.get("raw_caption"):
        return "caption"
    if "figure" in kind:
        return "figure"
    if "table" in kind:
        return "table"
    return None


def _scope_lock(topic: str, task_profile_id: str, scope_lock: dict[str, Any] | None) -> dict[str, Any]:
    if scope_lock:
        return dict(scope_lock)
    return build_scope_lock(topic, "library", {}, task_profile_id, time.time())


def _retrieval_options(scope_lock: dict[str, Any], retrieval_budget: int) -> dict[str, Any]:
    options = dict(scope_lock.get("scope_options") or {})
    options["scope"] = scope_lock.get("scope") or "library"
    options["limit"] = retrieval_budget
    options["expand_assets"] = True
    return options


def _retrieval_budget(value: int | None) -> int:
    try:
        budget = int(value or DEFAULT_RETRIEVAL_BUDGET)
    except (TypeError, ValueError):
        budget = DEFAULT_RETRIEVAL_BUDGET
    return max(1, budget)


def _task_profile_dict(task_profile: TaskProfile | dict[str, Any]) -> dict[str, Any]:
    if hasattr(task_profile, "as_dict"):
        return task_profile.as_dict()
    return dict(task_profile)


def _provenance_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        candidate.get("evidence_id"),
        candidate.get("paper_id"),
        candidate.get("source_path"),
        candidate.get("section_id"),
        candidate.get("chunk_index", candidate.get("chunk_id")),
        candidate.get("asset_id"),
        candidate.get("asset_label") or candidate.get("label"),
        candidate.get("kind"),
    )


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "EvidenceSourceCandidatePacket",
    "retrieve_source_candidates",
    "source_candidate_packet_from_acquisition",
]
