"""Minimal topic-to-evidence report slice for M6.5.

This module assembles existing evidence-workflow outputs into a small audit
report. It does not perform landscape, gap, idea, novelty, or manuscript work.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .classification import EvidenceEnrichmentResult, compute_role_coverage, enrich_evidence_cards, save_enrichment_result
from .extraction import EvidenceExtractionResult, extract_initial_cards
from .retrieval import EvidenceSourceCandidatePacket, retrieve_source_candidates
from .schemas import EvidenceCard
from .store import EvidenceCardStore
from .task_profiles import TaskProfile, resolve_task_profile

MINIMAL_REPORT_VERSION = "m6_5_minimal_topic_to_evidence_v1"

_CHECKLIST = [
    "Verify evidence IDs and source locators.",
    "Inspect missing required roles.",
    "Inspect figure/table/caption coverage warnings.",
    "Verify unsupported parts and uncertainty fields.",
    "Do not treat this report as landscape, gap, idea, novelty, or manuscript conclusion.",
]


@dataclass
class MinimalTopicEvidenceReport:
    workflow_id: str
    topic: str
    task_profile: dict[str, Any]
    scope_lock: dict[str, Any]
    retrieval_summary: dict[str, Any]
    source_type_coverage: dict[str, Any]
    role_coverage: dict[str, Any]
    evidence_cards: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_verification_checklist: list[str] = field(default_factory=lambda: list(_CHECKLIST))
    markdown: str = ""
    report_version: str = MINIMAL_REPORT_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_minimal_topic_to_evidence_slice(
    acquire_evidence_fn: Callable[..., dict[str, Any]],
    *,
    workflow_id: str,
    topic: str,
    store: EvidenceCardStore,
    task_profile_id: str | None = None,
    scope_lock: dict[str, Any] | None = None,
    retrieval_budget: int | None = None,
    extractor: Callable[..., dict[str, Any]] | None = None,
    classifier: Callable[..., dict[str, Any]] | None = None,
) -> MinimalTopicEvidenceReport:
    profile = resolve_task_profile(task_profile_id or (scope_lock or {}).get("task_profile_id"))
    source_packet = retrieve_source_candidates(
        acquire_evidence_fn,
        topic=topic,
        task_profile_id=profile.profile_id,
        scope_lock=scope_lock,
        retrieval_budget=retrieval_budget,
    )
    extraction_result = extract_initial_cards(
        source_packet.evidence_card_seeds,
        topic=topic,
        task_profile=profile,
        extractor=extractor,
    )
    enrichment_result = enrich_evidence_cards(
        extraction_result.cards,
        topic=topic,
        task_profile=profile,
        classifier=classifier,
    )
    save_enrichment_result(store, workflow_id, enrichment_result)
    report = build_minimal_topic_to_evidence_report(
        workflow_id=workflow_id,
        topic=topic,
        task_profile=profile,
        scope_lock=source_packet.scope_lock,
        source_packet=source_packet,
        extraction_result=extraction_result,
        enrichment_result=enrichment_result,
    )
    save_minimal_topic_to_evidence_report(store, workflow_id, report)
    return report


def build_minimal_topic_to_evidence_report(
    *,
    workflow_id: str,
    topic: str,
    task_profile: TaskProfile | dict[str, Any],
    scope_lock: dict[str, Any],
    source_packet: EvidenceSourceCandidatePacket | dict[str, Any],
    extraction_result: EvidenceExtractionResult | dict[str, Any],
    enrichment_result: EvidenceEnrichmentResult | dict[str, Any],
) -> MinimalTopicEvidenceReport:
    profile_dict = _as_profile_dict(task_profile)
    source_data = _as_dict(source_packet)
    extraction_data = _as_result_dict(extraction_result)
    enrichment_data = _as_result_dict(enrichment_result)
    cards = _cards_from_enrichment(enrichment_result)
    role_coverage = enrichment_data.get("role_coverage") or compute_role_coverage(_card_objects(enrichment_result), profile_dict)
    warnings = _dedupe(
        [
            *(source_data.get("warnings") or []),
            *(source_data.get("coverage_notes") or []),
            *(extraction_data.get("warnings") or []),
            *(enrichment_data.get("warnings") or []),
        ]
    )
    retrieval_summary = {
        "retrieval_budget": source_data.get("retrieval_budget"),
        "retrieval_options": source_data.get("retrieval_options") or {},
        "query_plan": source_data.get("query_plan") or {},
        "coverage": source_data.get("coverage") or {},
        "breadth": source_data.get("breadth") or {},
        "source_candidate_count": len(source_data.get("source_candidates") or []),
        "seed_count": len(source_data.get("evidence_card_seeds") or []),
        "initial_card_count": extraction_data.get("card_count", 0),
        "enriched_card_count": enrichment_data.get("card_count", len(cards)),
    }
    report = MinimalTopicEvidenceReport(
        workflow_id=workflow_id,
        topic=topic,
        task_profile=profile_dict,
        scope_lock=dict(scope_lock),
        retrieval_summary=retrieval_summary,
        source_type_coverage=source_data.get("source_type_coverage") or {},
        role_coverage=role_coverage,
        evidence_cards=cards,
        warnings=warnings,
    )
    report.markdown = render_minimal_topic_to_evidence_markdown(report)
    return report


def render_minimal_topic_to_evidence_markdown(report: MinimalTopicEvidenceReport) -> str:
    lines = [
        "# Minimal Topic-to-Evidence Report",
        "",
        f"- Workflow ID: `{report.workflow_id}`",
        f"- Topic: {report.topic}",
        f"- Report version: `{report.report_version}`",
        "",
        "## Scope Lock",
        "",
        "```json",
        _json(report.scope_lock),
        "```",
        "",
        "## Retrieval Summary",
        "",
        "```json",
        _json(report.retrieval_summary),
        "```",
        "",
        "## Source-Type Coverage",
        "",
        "```json",
        _json(report.source_type_coverage),
        "```",
        "",
        "## Role Coverage",
        "",
        "```json",
        _json(report.role_coverage),
        "```",
        "",
        "## Evidence Cards",
        "",
        "| evidence_id | paper_id | title | primary_role | secondary_roles | source_type | source_path | locator | support_strength | statement |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for card in report.evidence_cards:
        source = card.get("source") or {}
        support = card.get("support") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(card.get("evidence_id")),
                    _cell(card.get("paper_id")),
                    _cell(card.get("title")),
                    _cell(card.get("primary_role")),
                    _cell(", ".join(card.get("secondary_roles") or [])),
                    _cell(source.get("asset_type")),
                    _cell(source.get("source_path")),
                    _cell(_json_inline(source.get("locator") or {})),
                    _cell(support.get("support_strength")),
                    _cell(card.get("normalized_statement")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Coverage Warnings", ""])
    if report.warnings:
        lines.extend([f"- `{warning}`" for warning in report.warnings])
    else:
        lines.append("- None")
    lines.extend(["", "## Manual Verification Checklist", ""])
    lines.extend([f"- [ ] {item}" for item in report.manual_verification_checklist])
    lines.append("")
    return "\n".join(lines)


def save_minimal_topic_to_evidence_report(
    store: EvidenceCardStore,
    workflow_id: str,
    report: MinimalTopicEvidenceReport,
) -> dict[str, Any]:
    return store.save_minimal_report(workflow_id, report.markdown, report.as_dict())


def _cards_from_enrichment(enrichment_result: EvidenceEnrichmentResult | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(enrichment_result, EvidenceEnrichmentResult):
        return [card.as_dict() for card in enrichment_result.cards]
    return [dict(card) for card in enrichment_result.get("cards") or []]


def _card_objects(enrichment_result: EvidenceEnrichmentResult | dict[str, Any]) -> list[EvidenceCard]:
    if isinstance(enrichment_result, EvidenceEnrichmentResult):
        return enrichment_result.cards
    return []


def _as_profile_dict(task_profile: TaskProfile | dict[str, Any]) -> dict[str, Any]:
    if hasattr(task_profile, "as_dict"):
        return task_profile.as_dict()
    return dict(task_profile)


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return dict(value or {})


def _as_result_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    return dict(value or {})


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _json_inline(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "\\|").strip()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "MINIMAL_REPORT_VERSION",
    "MinimalTopicEvidenceReport",
    "build_minimal_topic_to_evidence_report",
    "render_minimal_topic_to_evidence_markdown",
    "run_minimal_topic_to_evidence_slice",
    "save_minimal_topic_to_evidence_report",
]
