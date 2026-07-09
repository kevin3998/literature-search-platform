"""Callable wrappers for registered evidence workflow skills.

A4 keeps these wrappers thin: they read/write workspace artifacts and call
existing evidence workflow functions. They do not choose controller actions,
update state, or perform audit-gate orchestration.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from modules.evidence_workflow.classification import enrich_evidence_cards
from modules.evidence_workflow.extraction import extract_initial_cards
from modules.evidence_workflow.minimal_report import build_minimal_topic_to_evidence_report
from modules.evidence_workflow.ranking import select_representative_evidence
from modules.evidence_workflow.retrieval import retrieve_source_candidates
from modules.evidence_workflow.schemas import (
    EvidenceCard,
    EvidenceCardSeed,
    EvidenceEntities,
    EvidenceRelation,
    EvidenceRelevance,
    EvidenceSource,
    EvidenceSupport,
    validate_evidence_card,
)
from modules.evidence_workflow.task_profiles import resolve_task_profile
from modules.research_agent_controller.skill_registry import (
    SkillExecutionInput,
    SkillExecutionResult,
    SkillExecutionStatus,
    SkillStatus,
    build_default_skill_registry,
)
from modules.research_workspace import ResearchWorkspaceStore
from .gap_tools import map_gaps
from .idea_tools import generate_candidate_ideas
from .landscape_tools import build_landscape
from .screening_tools import screen_novelty_feasibility_risk
from .experiment_matrix_tools import create_experiment_matrix
from .claim_ledger_tools import build_claim_ledger
from .manuscript_tools import draft_manuscript_section

WrapperFn = Callable[..., SkillExecutionResult]

SOURCE_PACKET_PATH = "retrieval/source_candidate_packet.json"
RETRIEVAL_WARNINGS_PATH = "retrieval/retrieval_warnings.json"
SEEDS_PATH = "evidence/evidence_card_seeds.json"
INITIAL_CARDS_PATH = "evidence/evidence_cards.initial.json"
ENRICHED_CARDS_PATH = "evidence/evidence_cards.enriched.json"
SELECTION_PATH = "ranked_evidence/evidence_selection.json"
COVERAGE_DIAGNOSTICS_PATH = "ranked_evidence/coverage_diagnostics.json"
REPORT_MD_PATH = "reports/minimal_topic_to_evidence_report.md"
REPORT_JSON_PATH = "reports/minimal_topic_to_evidence_report.json"
EVIDENCE_VALIDATION_PATH = "evidence/evidence_validation.json"
ARTIFACT_MANIFEST_PATH = "audit/artifact_manifest.json"
ARTIFACT_MANIFEST_VALIDATION_PATH = "audit/artifact_manifest_validation.json"


def execute_evidence_skill(
    execution_input: SkillExecutionInput | dict[str, Any],
    *,
    registry: Any | None = None,
    acquire_evidence_fn: Callable[..., dict[str, Any]] | None = None,
    extractor: Callable[..., dict[str, Any]] | None = None,
    classifier: Callable[..., dict[str, Any]] | None = None,
    llm_client: Any | None = None,
) -> SkillExecutionResult:
    execution = _execution_input(execution_input)
    active_registry = registry or build_default_skill_registry()
    try:
        contract = active_registry.get_skill(execution.skill_name)
    except KeyError as exc:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=[str(exc)])

    wrapper = EVIDENCE_SKILL_WRAPPERS.get(execution.skill_name)
    if wrapper is None:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=[f"no executable wrapper: {execution.skill_name}"])
    if contract.status != SkillStatus.AVAILABLE:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=[f"skill is not available: {execution.skill_name}"])

    try:
        return wrapper(
            execution,
            acquire_evidence_fn=acquire_evidence_fn,
            extractor=extractor,
            classifier=classifier,
            llm_client=llm_client,
        )
    except Exception as exc:  # noqa: BLE001 - wrappers should return structured failures
        return _result(execution, SkillExecutionStatus.FAILED, errors=[f"skill_execution_failed:{exc}"])


def get_evidence_skill_wrapper(skill_name: str) -> WrapperFn:
    if skill_name not in EVIDENCE_SKILL_WRAPPERS:
        raise KeyError(f"no executable wrapper: {skill_name!r}")
    return EVIDENCE_SKILL_WRAPPERS[skill_name]


def _retrieve_sources(
    execution: SkillExecutionInput,
    *,
    acquire_evidence_fn: Callable[..., dict[str, Any]] | None = None,
    **_: Any,
) -> SkillExecutionResult:
    topic = _topic(execution)
    if not topic:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=["missing_topic"])
    if acquire_evidence_fn is None:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=["missing_acquire_evidence_fn"])

    packet = retrieve_source_candidates(
        acquire_evidence_fn,
        topic=topic,
        task_profile_id=execution.parameters.get("task_profile_id"),
        scope_lock=execution.parameters.get("scope_lock"),
        retrieval_budget=execution.parameters.get("retrieval_budget"),
    )
    packet_data = packet.as_dict()
    warnings_data = {
        "artifact_type": "retrieval_warnings",
        "task_id": execution.task_id,
        "skill_name": execution.skill_name,
        "warnings": packet_data.get("warnings") or [],
        "coverage_notes": packet_data.get("coverage_notes") or [],
        "created_at": time.time(),
    }
    _write_json(execution, SOURCE_PACKET_PATH, packet_data)
    _write_json(execution, RETRIEVAL_WARNINGS_PATH, warnings_data)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        output_artifacts=[SOURCE_PACKET_PATH, RETRIEVAL_WARNINGS_PATH],
        warnings=packet_data.get("warnings") or [],
        metadata={
            "source_candidate_count": len(packet_data.get("source_candidates") or []),
            "seed_count": len(packet_data.get("evidence_card_seeds") or []),
        },
    )


def _create_evidence_seeds(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    packet, missing = _read_json_or_missing(execution, SOURCE_PACKET_PATH)
    if missing:
        return missing
    seeds = list(packet.get("evidence_card_seeds") or [])
    artifact = {
        "artifact_type": "evidence_card_seeds",
        "task_id": execution.task_id,
        "source_packet_path": SOURCE_PACKET_PATH,
        "seed_count": len(seeds),
        "seeds": seeds,
        "warnings": _dedupe([warning for seed in seeds for warning in seed.get("warnings", [])]),
        "created_at": time.time(),
    }
    _write_json(execution, SEEDS_PATH, artifact)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=[SOURCE_PACKET_PATH],
        output_artifacts=[SEEDS_PATH],
        warnings=artifact["warnings"],
        metadata={"seed_count": len(seeds)},
    )


def _extract_evidence_cards(
    execution: SkillExecutionInput,
    *,
    extractor: Callable[..., dict[str, Any]] | None = None,
    **_: Any,
) -> SkillExecutionResult:
    artifact, missing = _read_json_or_missing(execution, SEEDS_PATH)
    if missing:
        return missing
    topic = _topic(execution)
    if not topic:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=["missing_topic"])
    seeds = [_seed_from_dict(seed) for seed in artifact.get("seeds") or []]
    extraction = extract_initial_cards(seeds, topic=topic, extractor=extractor)
    payload = {
        "artifact_type": "evidence_cards",
        "stage": "initial",
        "task_id": execution.task_id,
        **extraction.as_dict(),
        "created_at": time.time(),
    }
    _write_json(execution, INITIAL_CARDS_PATH, payload)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=[SEEDS_PATH],
        output_artifacts=[INITIAL_CARDS_PATH],
        warnings=extraction.warnings,
        metadata={"card_count": extraction.card_count, "skipped_seed_ids": extraction.skipped_seed_ids},
    )


def _enrich_evidence_cards(
    execution: SkillExecutionInput,
    *,
    classifier: Callable[..., dict[str, Any]] | None = None,
    **_: Any,
) -> SkillExecutionResult:
    artifact, missing = _read_json_or_missing(execution, INITIAL_CARDS_PATH)
    if missing:
        return missing
    topic = _topic(execution)
    if not topic:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=["missing_topic"])
    profile = _task_profile(execution)
    cards = [_card_from_dict(card) for card in artifact.get("cards") or []]
    enrichment = enrich_evidence_cards(cards, topic=topic, task_profile=profile, classifier=classifier)
    payload = {
        "artifact_type": "evidence_cards",
        "stage": "enriched",
        "task_id": execution.task_id,
        **enrichment.as_dict(),
        "created_at": time.time(),
    }
    _write_json(execution, ENRICHED_CARDS_PATH, payload)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=[INITIAL_CARDS_PATH],
        output_artifacts=[ENRICHED_CARDS_PATH],
        warnings=enrichment.warnings,
        metadata={"card_count": enrichment.card_count, "role_coverage": enrichment.role_coverage},
    )


def _rank_evidence(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    artifact, missing = _read_json_or_missing(execution, ENRICHED_CARDS_PATH)
    if missing:
        return missing
    cards = [_card_from_dict(card) for card in artifact.get("cards") or []]
    selection = select_representative_evidence(
        cards,
        task_profile=_task_profile(execution),
        retrieval_budget=execution.parameters.get("retrieval_budget"),
    )
    selection_data = selection.as_dict()
    coverage_data = {
        "artifact_type": "coverage_diagnostics",
        "task_id": execution.task_id,
        "coverage": selection_data.get("coverage") or {},
        "warnings": selection_data.get("warnings") or [],
        "created_at": time.time(),
    }
    _write_json(execution, SELECTION_PATH, selection_data)
    _write_json(execution, COVERAGE_DIAGNOSTICS_PATH, coverage_data)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=[ENRICHED_CARDS_PATH],
        output_artifacts=[SELECTION_PATH, COVERAGE_DIAGNOSTICS_PATH],
        warnings=selection.warnings,
        metadata={"selected_count": selection.selected_count, "card_count": selection.card_count},
    )


def _build_minimal_report(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    if any(path == SOURCE_PACKET_PATH or path.startswith("retrieval/") for path in execution.input_artifacts):
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            errors=["raw_retrieval_candidates_not_allowed_for_report"],
        )
    topic = _topic(execution)
    if not topic:
        return _result(execution, SkillExecutionStatus.BLOCKED, errors=["missing_topic"])

    cards, input_path, missing = _report_cards(execution)
    if missing:
        return missing
    profile = _task_profile(execution)
    enrichment_data = {
        "cards": cards,
        "warnings": [],
        "skipped_card_ids": [],
        "role_coverage": {},
        "card_count": len(cards),
    }
    report = build_minimal_topic_to_evidence_report(
        workflow_id=execution.task_id,
        topic=topic,
        task_profile=profile.as_dict() if hasattr(profile, "as_dict") else profile,
        scope_lock={"topic": topic, "scope": "workspace", "task_profile_id": profile.profile_id},
        source_packet={
            "retrieval_budget": None,
            "retrieval_options": {},
            "source_candidates": [],
            "evidence_card_seeds": [],
            "source_type_coverage": {},
            "warnings": [],
            "coverage_notes": [],
        },
        extraction_result={"cards": cards, "warnings": [], "skipped_seed_ids": [], "card_count": len(cards)},
        enrichment_result=enrichment_data,
    )
    _write_text(execution, REPORT_MD_PATH, report.markdown)
    _write_json(execution, REPORT_JSON_PATH, report.as_dict())
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=[input_path],
        output_artifacts=[REPORT_MD_PATH, REPORT_JSON_PATH],
        warnings=report.warnings,
        metadata={"evidence_card_count": len(cards)},
    )


def _validate_evidence_cards(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    input_path = str(execution.parameters.get("input_path") or "")
    if not input_path:
        input_path = ENRICHED_CARDS_PATH if _exists(execution, ENRICHED_CARDS_PATH) else INITIAL_CARDS_PATH
    artifact, missing = _read_json_or_missing(execution, input_path)
    if missing:
        return missing
    cards = [_card_from_dict(card) for card in artifact.get("cards") or []]
    errors_by_card = {
        card.evidence_id: validate_evidence_card(card)
        for card in cards
        if validate_evidence_card(card)
    }
    payload = {
        "artifact_type": "evidence_validation",
        "task_id": execution.task_id,
        "input_path": input_path,
        "valid": not errors_by_card,
        "card_count": len(cards),
        "errors_by_card": errors_by_card,
        "created_at": time.time(),
    }
    _write_json(execution, EVIDENCE_VALIDATION_PATH, payload)
    status = SkillExecutionStatus.SUCCESS if payload["valid"] else SkillExecutionStatus.VALIDATION_FAILED
    return _result(
        execution,
        status,
        input_artifacts=[input_path],
        output_artifacts=[EVIDENCE_VALIDATION_PATH],
        errors=["evidence_card_validation_failed"] if errors_by_card else [],
        metadata={"valid": payload["valid"], "card_count": len(cards)},
    )


def _validate_artifact_manifest(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    manifest, missing = _read_json_or_missing(execution, ARTIFACT_MANIFEST_PATH)
    if missing:
        return missing
    errors: list[str] = []
    if not isinstance(manifest, dict):
        errors.append("manifest_is_not_object")
        artifacts = []
    else:
        artifacts = manifest.get("artifacts")
        if manifest.get("task_id") != execution.task_id:
            errors.append("task_id_mismatch")
        if not isinstance(artifacts, list):
            errors.append("artifacts_is_not_list")
            artifacts = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("artifact_record_is_not_object")
            continue
        path = artifact.get("path") or artifact.get("path_hint")
        if path:
            try:
                _store(execution).resolve_workspace_path(execution.task_id, path)
            except ValueError:
                errors.append(f"artifact_path_escapes_workspace:{path}")
    payload = {
        "artifact_type": "artifact_manifest_validation",
        "task_id": execution.task_id,
        "valid": not errors,
        "errors": errors,
        "artifact_count": len(artifacts),
        "created_at": time.time(),
    }
    _write_json(execution, ARTIFACT_MANIFEST_VALIDATION_PATH, payload)
    status = SkillExecutionStatus.SUCCESS if payload["valid"] else SkillExecutionStatus.VALIDATION_FAILED
    return _result(
        execution,
        status,
        input_artifacts=[ARTIFACT_MANIFEST_PATH],
        output_artifacts=[ARTIFACT_MANIFEST_VALIDATION_PATH],
        errors=errors,
        metadata={"valid": payload["valid"], "artifact_count": len(artifacts)},
    )


EVIDENCE_SKILL_WRAPPERS: dict[str, WrapperFn] = {
    "retrieve_sources": _retrieve_sources,
    "create_evidence_seeds": _create_evidence_seeds,
    "extract_evidence_cards": _extract_evidence_cards,
    "enrich_evidence_cards": _enrich_evidence_cards,
    "rank_evidence": _rank_evidence,
    "build_minimal_topic_to_evidence_report": _build_minimal_report,
    "build_landscape": build_landscape,
    "map_gaps": map_gaps,
    "generate_candidate_ideas": generate_candidate_ideas,
    "screen_novelty_feasibility_risk": screen_novelty_feasibility_risk,
    "create_experiment_matrix": create_experiment_matrix,
    "build_claim_ledger": build_claim_ledger,
    "draft_manuscript_section": draft_manuscript_section,
    "validate_evidence_cards": _validate_evidence_cards,
    "validate_artifact_manifest": _validate_artifact_manifest,
}


def _execution_input(value: SkillExecutionInput | dict[str, Any]) -> SkillExecutionInput:
    if isinstance(value, SkillExecutionInput):
        return value
    return SkillExecutionInput.from_dict(value)


def _result(
    execution: SkillExecutionInput,
    status: SkillExecutionStatus | str,
    *,
    input_artifacts: list[str] | None = None,
    output_artifacts: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SkillExecutionResult:
    return SkillExecutionResult(
        task_id=execution.task_id,
        skill_name=execution.skill_name,
        status=status,
        input_artifacts=list(input_artifacts or execution.input_artifacts),
        output_artifacts=list(output_artifacts or []),
        warnings=list(warnings or []),
        errors=list(errors or []),
        metadata=dict(metadata or {}),
    )


def _store(execution: SkillExecutionInput) -> ResearchWorkspaceStore:
    root = Path(execution.workspace_root)
    if root.name != execution.task_id:
        raise ValueError("workspace_root must point at the task workspace directory")
    return ResearchWorkspaceStore(root.parents[2])


def _path(execution: SkillExecutionInput, relative_path: str) -> Path:
    return _store(execution).resolve_workspace_path(execution.task_id, relative_path)


def _exists(execution: SkillExecutionInput, relative_path: str) -> bool:
    return _path(execution, relative_path).exists()


def _read_json_or_missing(
    execution: SkillExecutionInput,
    relative_path: str,
) -> tuple[dict[str, Any], SkillExecutionResult | None]:
    path = _path(execution, relative_path)
    if not path.exists():
        return {}, _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=[relative_path],
            errors=[f"missing_input_artifact:{relative_path}"],
        )
    return json.loads(path.read_text(encoding="utf-8")), None


def _write_json(execution: SkillExecutionInput, relative_path: str, payload: dict[str, Any]) -> None:
    path = _path(execution, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _write_text(execution: SkillExecutionInput, relative_path: str, text: str) -> None:
    path = _path(execution, relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def _topic(execution: SkillExecutionInput) -> str:
    return str(execution.parameters.get("topic") or "").strip()


def _task_profile(execution: SkillExecutionInput) -> Any:
    return resolve_task_profile(execution.parameters.get("task_profile_id"))


def _seed_from_dict(data: dict[str, Any]) -> EvidenceCardSeed:
    return EvidenceCardSeed(
        seed_id=data["seed_id"],
        source_evidence_id=data.get("source_evidence_id"),
        paper_id=data["paper_id"],
        doi=data.get("doi"),
        title=data.get("title"),
        year=data.get("year"),
        journal=data.get("journal"),
        source_path=data.get("source_path", ""),
        section_id=data.get("section_id"),
        chunk_id=data.get("chunk_id"),
        asset_id=data.get("asset_id"),
        asset_type=data.get("asset_type", "text"),
        locator=dict(data.get("locator") or {}),
        raw_text=data.get("raw_text"),
        raw_caption=data.get("raw_caption"),
        candidate_kind=data.get("candidate_kind"),
        retrieval_score=data.get("retrieval_score"),
        warnings=list(data.get("warnings") or []),
    )


def _card_from_dict(data: dict[str, Any]) -> EvidenceCard:
    source = data.get("source") or {}
    entities = data.get("entities") or {}
    relevance = data.get("relevance") or {}
    support = data.get("support") or {}
    return EvidenceCard(
        evidence_id=data["evidence_id"],
        seed_id=data["seed_id"],
        source_evidence_id=data.get("source_evidence_id"),
        paper_id=data["paper_id"],
        source=EvidenceSource(
            source_path=source.get("source_path", ""),
            asset_type=source.get("asset_type", "text"),
            section_id=source.get("section_id"),
            chunk_id=source.get("chunk_id"),
            asset_id=source.get("asset_id"),
            locator=dict(source.get("locator") or {}),
        ),
        primary_role=data.get("primary_role", "background"),
        title=data.get("title"),
        doi=data.get("doi"),
        year=data.get("year"),
        journal=data.get("journal"),
        secondary_roles=list(data.get("secondary_roles") or []),
        verbatim_snippet=data.get("verbatim_snippet"),
        normalized_statement=data.get("normalized_statement"),
        entities=EvidenceEntities(**{key: list(value or []) for key, value in entities.items()}),
        relations=[
            EvidenceRelation(
                subject=relation.get("subject", ""),
                predicate=relation.get("predicate", ""),
                object=relation.get("object", ""),
                qualifiers=dict(relation.get("qualifiers") or {}),
                condition=relation.get("condition"),
                confidence=relation.get("confidence"),
            )
            for relation in data.get("relations") or []
        ],
        relevance=EvidenceRelevance(
            topic=relevance.get("topic"),
            relevance_reason=relevance.get("relevance_reason"),
            relevance_score=relevance.get("relevance_score"),
        ),
        support=EvidenceSupport(
            support_strength=support.get("support_strength", "weak"),
            extraction_confidence=support.get("extraction_confidence"),
            uncertainty=support.get("uncertainty"),
            unsupported_parts=list(support.get("unsupported_parts") or []),
        ),
    )


def _report_cards(
    execution: SkillExecutionInput,
) -> tuple[list[dict[str, Any]], str, SkillExecutionResult | None]:
    if _exists(execution, SELECTION_PATH):
        selection, missing = _read_json_or_missing(execution, SELECTION_PATH)
        if missing:
            return [], SELECTION_PATH, missing
        return list(selection.get("selected_cards") or []), SELECTION_PATH, None
    artifact, missing = _read_json_or_missing(execution, ENRICHED_CARDS_PATH)
    if missing:
        return [], ENRICHED_CARDS_PATH, missing
    return list(artifact.get("cards") or []), ENRICHED_CARDS_PATH, None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "EVIDENCE_SKILL_WRAPPERS",
    "execute_evidence_skill",
    "get_evidence_skill_wrapper",
]
