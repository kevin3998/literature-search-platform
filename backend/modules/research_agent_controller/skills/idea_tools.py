"""Deterministic P2-M10 idea generation skill wrapper.

The wrapper assembles conservative candidate idea artifacts from validated gap
records and evidence references. It does not perform free-form brainstorming,
call LLMs, or run external services.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from modules.research_workspace import ResearchWorkspaceStore

from ..skill_registry import SkillExecutionInput, SkillExecutionResult, SkillExecutionStatus
from .idea_contract import (
    CANDIDATE_IDEAS_SCHEMA_VERSION,
    IDEA_FORBIDDEN_MARKDOWN_SECTIONS,
    IDEA_OUTPUT_ARTIFACTS,
    IDEA_REQUIRED_INPUT_ARTIFACTS,
    CandidateIdeaArtifact,
    CandidateIdeaEvidenceBasis,
    CandidateIdeaGapBasis,
    CandidateIdeaRecord,
    validate_idea_generation_input_artifacts,
)

FORBIDDEN_CANDIDATE_IDEA_CLAIMS = [
    "is novel",
    "is feasible",
    "has been validated",
    "experimentally validated",
    "will improve",
    "will enhance",
    "proves that",
    "confirms that",
    "should be synthesized",
    "should be tested",
]


def generate_candidate_ideas(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    input_artifacts = list(execution.input_artifacts or IDEA_REQUIRED_INPUT_ARTIFACTS)
    input_errors = validate_idea_generation_input_artifacts(input_artifacts)
    forbidden_errors = [error for error in input_errors if "not_allowed_for_idea_generation" in error]
    if forbidden_errors:
        return _result(execution, SkillExecutionStatus.VALIDATION_FAILED, errors=forbidden_errors)

    if not _path(execution, "gaps/gap_map.json").exists():
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
            errors=["missing_gap_map_artifact"],
        )

    missing = [path for path in IDEA_REQUIRED_INPUT_ARTIFACTS if not _path(execution, path).exists()]
    if missing:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
            errors=[f"missing_input_artifact:{path}" for path in missing],
        )

    payloads: dict[str, Any] = {}
    for artifact_path in IDEA_REQUIRED_INPUT_ARTIFACTS:
        try:
            payloads[artifact_path] = _read_json(execution, artifact_path)
        except json.JSONDecodeError:
            return _result(
                execution,
                SkillExecutionStatus.VALIDATION_FAILED,
                input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
                errors=[f"artifact_not_parseable:{artifact_path}"],
            )

    gap_map = payloads["gaps/gap_map.json"]
    landscape = payloads["landscape/literature_landscape.json"]
    if gap_map.get("schema_version") != "gap_map_v1":
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
            errors=["invalid_gap_map_schema_version"],
        )
    if landscape.get("schema_version") != "landscape_v1":
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
            errors=["invalid_landscape_schema_version"],
        )

    enriched = payloads["evidence/evidence_cards.enriched.json"]
    selection = payloads["ranked_evidence/evidence_selection.json"]
    cards = _cards_from_payload(enriched)
    selected_cards = _selected_cards(selection, cards)
    if not cards or not selected_cards or not gap_map.get("evidence_ids"):
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
            errors=["idea_generation_requires_evidence_references"],
        )

    topic = str(execution.parameters.get("topic") or gap_map.get("topic") or landscape.get("topic") or "").strip()
    artifact, diagnostics = _build_candidate_idea_artifact(
        task_id=execution.task_id,
        topic=topic or "unspecified topic",
        gap_map=gap_map,
        gap_diagnostics=payloads["gaps/gap_coverage_diagnostics.json"],
        landscape=landscape,
        landscape_diagnostics=payloads["landscape/landscape_coverage_diagnostics.json"],
        cards=cards,
        selected_cards=selected_cards,
        selection=selection,
        ranking_diagnostics=payloads["ranked_evidence/coverage_diagnostics.json"],
        input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
    )
    markdown = _render_candidate_ideas_markdown(artifact)
    validation_errors = validate_candidate_ideas_artifact(artifact.as_dict(), markdown)
    if validation_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
            errors=validation_errors,
            warnings=artifact.warnings,
        )

    _write_json(execution, "ideas/candidate_ideas.json", artifact.as_dict())
    _write_text(execution, "ideas/candidate_ideas.md", markdown)
    _write_json(execution, "ideas/idea_generation_diagnostics.json", diagnostics)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=IDEA_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=IDEA_OUTPUT_ARTIFACTS,
        warnings=artifact.warnings,
        metadata={
            "idea_count": len(artifact.ideas),
            "valid_gap_count": diagnostics["num_valid_gaps"],
            "skipped_gap_ids": diagnostics["skipped_gap_ids"],
        },
    )


def validate_candidate_ideas_artifact(candidate_ideas: dict[str, Any], markdown: str) -> list[str]:
    errors: list[str] = []
    if candidate_ideas.get("schema_version") != CANDIDATE_IDEAS_SCHEMA_VERSION:
        errors.append("invalid_candidate_ideas_schema_version")
    if not candidate_ideas.get("idea_set_id"):
        errors.append("missing_idea_set_id")
    if not candidate_ideas.get("gap_map_id"):
        errors.append("missing_gap_map_id")
    if not candidate_ideas.get("landscape_id"):
        errors.append("missing_landscape_id")
    if not candidate_ideas.get("evidence_ids"):
        errors.append("idea_generation_requires_evidence_references")

    for index, idea in enumerate(candidate_ideas.get("ideas") or []):
        if not isinstance(idea, dict):
            errors.append(f"candidate_idea_is_not_object:{index}")
            continue
        gap_basis = idea.get("gap_basis") if isinstance(idea.get("gap_basis"), dict) else {}
        evidence_basis = idea.get("evidence_basis") if isinstance(idea.get("evidence_basis"), dict) else {}
        if not gap_basis.get("gap_ids"):
            errors.append(f"candidate_idea_requires_gap_basis:{index}")
        if not evidence_basis.get("supporting_evidence_ids"):
            errors.append(f"candidate_idea_requires_evidence_basis:{index}")
        if idea.get("not_yet_screened") is not True:
            errors.append(f"candidate_idea_must_remain_unscreened:{index}")
        if idea.get("requires_novelty_screening") is not True:
            errors.append(f"candidate_idea_requires_novelty_screening:{index}")
        if idea.get("requires_feasibility_screening") is not True:
            errors.append(f"candidate_idea_requires_feasibility_screening:{index}")

    if "## Evidence References" not in markdown:
        errors.append("markdown_missing_evidence_references")
    for section in IDEA_FORBIDDEN_MARKDOWN_SECTIONS:
        if f"## {section}" in markdown:
            errors.append(f"forbidden_candidate_ideas_markdown_section:{section}")

    forbidden = _forbidden_claim_matches(candidate_ideas, markdown)
    if forbidden:
        errors.append("unsupported_candidate_idea_claim")
    return errors


def _build_candidate_idea_artifact(
    *,
    task_id: str,
    topic: str,
    gap_map: dict[str, Any],
    gap_diagnostics: dict[str, Any],
    landscape: dict[str, Any],
    landscape_diagnostics: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_cards: list[dict[str, Any]],
    selection: dict[str, Any],
    ranking_diagnostics: dict[str, Any],
    input_artifacts: list[str],
) -> tuple[CandidateIdeaArtifact, dict[str, Any]]:
    warnings = _collect_warnings(gap_map, gap_diagnostics, landscape, landscape_diagnostics, selection, ranking_diagnostics)
    evidence_by_id = {_evidence_id(card): card for card in cards if _evidence_id(card)}
    selected_ids = _dedupe([_evidence_id(card) for card in selected_cards])
    source_paper_ids = _dedupe([str(card.get("paper_id") or "") for card in selected_cards])
    ideas: list[CandidateIdeaRecord] = []
    skipped_gap_ids: list[str] = []
    valid_gap_count = 0

    for gap in [item for item in gap_map.get("gaps") or [] if isinstance(item, dict)][:10]:
        gap_id = str(gap.get("gap_id") or "").strip()
        basis = gap.get("basis") if isinstance(gap.get("basis"), dict) else {}
        gap_evidence_ids = _dedupe([str(value) for value in basis.get("evidence_ids") or []])
        if not gap_evidence_ids:
            gap_evidence_ids = _supporting_evidence_ids_for_gap(gap_id, gap_map)
        gap_evidence_ids = [evidence_id for evidence_id in gap_evidence_ids if evidence_id in evidence_by_id or evidence_id in selected_ids]
        if not gap_id or not gap_evidence_ids:
            if gap_id:
                skipped_gap_ids.append(gap_id)
                warnings.append(f"skipped_gap_without_evidence_basis:{gap_id}")
            continue
        valid_gap_count += 1
        ideas.append(_idea_from_gap(gap, gap_evidence_ids, evidence_by_id, gap_map, landscape))

    artifact = CandidateIdeaArtifact(
        task_id=task_id,
        topic=topic,
        idea_set_id=f"candidate_ideas_{task_id}",
        input_artifacts=input_artifacts,
        gap_map_id=str(gap_map.get("gap_map_id") or ""),
        landscape_id=str(landscape.get("landscape_id") or gap_map.get("landscape_id") or ""),
        evidence_ids=_dedupe([evidence_id for idea in ideas for evidence_id in idea.evidence_basis.supporting_evidence_ids]),
        source_paper_ids=source_paper_ids,
        ideas=ideas,
        generation_scope={
            "max_ideas": 10,
            "source": "validated_gap_records",
            "default_ideas_per_gap": 1,
        },
        constraints={
            "not_yet_screened": True,
            "requires_novelty_screening": True,
            "requires_feasibility_screening": True,
            "forbidden_inputs": ["retrieval/...", "raw_chunks", "raw_papers"],
        },
        limitations=[
            "Candidate ideas are deterministic assemblies from gap records and evidence references.",
            "Candidate ideas are unscreened and must not be read as novel, feasible, or validated.",
        ],
        warnings=_dedupe(warnings),
    )
    diagnostics = {
        "artifact_type": "idea_generation_diagnostics",
        "task_id": task_id,
        "idea_set_id": artifact.idea_set_id,
        "gap_map_id": artifact.gap_map_id,
        "landscape_id": artifact.landscape_id,
        "num_input_gaps": len([item for item in gap_map.get("gaps") or [] if isinstance(item, dict)]),
        "num_valid_gaps": valid_gap_count,
        "num_generated_ideas": len(ideas),
        "skipped_gap_ids": skipped_gap_ids,
        "warnings": artifact.warnings,
        "forbidden_claim_checks": {"passed": True, "matches": []},
        "downstream_screening_required": True,
        "created_at": time.time(),
        "schema_version": CANDIDATE_IDEAS_SCHEMA_VERSION,
    }
    return artifact, diagnostics


def _idea_from_gap(
    gap: dict[str, Any],
    evidence_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
    gap_map: dict[str, Any],
    landscape: dict[str, Any],
) -> CandidateIdeaRecord:
    gap_id = str(gap.get("gap_id") or "")
    gap_type = str(gap.get("gap_type") or "coverage_gap")
    title = str(gap.get("title") or gap_id)
    description = str(gap.get("description") or "the selected evidence base contains a documented gap")
    basis = gap.get("basis") if isinstance(gap.get("basis"), dict) else {}
    source_paper_ids = _dedupe([str(evidence_by_id.get(evidence_id, {}).get("paper_id") or "") for evidence_id in evidence_ids])
    cluster_ids = _dedupe([str(value) for value in basis.get("landscape_cluster_ids") or []])
    coverage_warnings = _dedupe([str(value) for value in basis.get("coverage_warnings") or []])
    diagnostic_refs = _dedupe([str(value) for value in basis.get("diagnostic_refs") or []])
    return CandidateIdeaRecord(
        idea_id=f"idea_{_slug(gap_id)}",
        title=f"Candidate idea from {gap_type}: address {title}",
        summary=(
            f"This candidate idea is derived from a validated gap record indicating {description}. "
            "It remains an unscreened candidate direction requiring novelty and feasibility screening."
        ),
        idea_type=_idea_type_for_gap(gap_type),
        gap_basis=CandidateIdeaGapBasis(
            gap_ids=[gap_id],
            gap_types=[gap_type],
            landscape_cluster_ids=cluster_ids,
            evidence_ids=evidence_ids,
            coverage_warnings=coverage_warnings,
            diagnostic_refs=diagnostic_refs,
        ),
        evidence_basis=CandidateIdeaEvidenceBasis(
            supporting_evidence_ids=evidence_ids,
            source_paper_ids=source_paper_ids,
            representative_claim_refs=_representative_claim_refs(cluster_ids, landscape),
        ),
        rationale=(
            f"The idea is grounded in gap {gap_id} and supporting evidence {', '.join(evidence_ids)}. "
            f"The gap basis indicates {_basis_summary(basis)}."
        ),
        expected_contribution=(
            "May help address the documented evidence gap if later novelty and feasibility screening support it."
        ),
        assumptions=[
            "The input gap map and evidence artifacts are valid.",
            "The candidate direction remains unscreened.",
        ],
        constraints=[
            "No novelty, feasibility, risk, or experimental validation is claimed.",
            "Downstream screening is required before any research action.",
        ],
        not_yet_screened=True,
        requires_novelty_screening=True,
        requires_feasibility_screening=True,
        warnings=list(gap.get("warnings") or []),
    )


def _render_candidate_ideas_markdown(artifact: CandidateIdeaArtifact) -> str:
    lines = [
        "# Candidate Ideas",
        "",
        "## Scope",
        "",
        f"Topic: {artifact.topic}",
        f"Idea set ID: {artifact.idea_set_id}",
        "",
        "## Gap And Evidence Base",
        "",
        f"- Gap map ID: {artifact.gap_map_id}",
        f"- Landscape ID: {artifact.landscape_id}",
        f"- Evidence IDs: {', '.join(artifact.evidence_ids)}",
        "",
        "## Candidate Idea Set",
        "",
    ]
    for idea in artifact.ideas:
        lines.extend(
            [
                f"### {idea.title}",
                "",
                f"- idea_id: {idea.idea_id}",
                f"- idea_type: {idea.idea_type}",
                f"- summary: {idea.summary}",
                f"- gap_ids: {', '.join(idea.gap_basis.gap_ids)}",
                f"- evidence_ids: {', '.join(idea.evidence_basis.supporting_evidence_ids)}",
                f"- rationale: {idea.rationale}",
                f"- expected_contribution: {idea.expected_contribution}",
                "",
            ]
        )
    lines.extend(["## Assumptions And Constraints", ""])
    for idea in artifact.ideas:
        for assumption in idea.assumptions:
            lines.append(f"- idea_id={idea.idea_id}; assumption={assumption}")
        for constraint in idea.constraints:
            lines.append(f"- idea_id={idea.idea_id}; constraint={constraint}")
    lines.extend(["", "## Required Downstream Screening", ""])
    for idea in artifact.ideas:
        lines.append(
            f"- idea_id={idea.idea_id}; not_yet_screened={idea.not_yet_screened}; "
            f"requires_novelty_screening={idea.requires_novelty_screening}; "
            f"requires_feasibility_screening={idea.requires_feasibility_screening}"
        )
    lines.extend(["", "## Limitations", ""])
    for limitation in artifact.limitations:
        lines.append(f"- {limitation}")
    if artifact.warnings:
        lines.append(f"- Warnings: {', '.join(artifact.warnings)}")
    lines.extend(["", "## Evidence References", ""])
    for idea in artifact.ideas:
        for gap_id in idea.gap_basis.gap_ids:
            lines.append(f"- idea_id={idea.idea_id}; gap_id={gap_id}")
        for evidence_id in idea.evidence_basis.supporting_evidence_ids:
            paper_id = _paper_id_for_evidence(artifact, idea, evidence_id)
            lines.append(f"- idea_id={idea.idea_id}; evidence_id={evidence_id}; paper_id={paper_id}")
        for cluster_id in idea.gap_basis.landscape_cluster_ids:
            lines.append(f"- idea_id={idea.idea_id}; landscape_cluster_id={cluster_id}")
        for diagnostic_ref in idea.gap_basis.diagnostic_refs:
            lines.append(f"- idea_id={idea.idea_id}; diagnostic reference={diagnostic_ref}")
    return "\n".join(lines).strip() + "\n"


def _selected_cards(selection: dict[str, Any], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    card_by_id = {_evidence_id(card): card for card in cards}
    selected: list[dict[str, Any]] = []
    for item in selection.get("selected_cards") or []:
        if not isinstance(item, dict):
            continue
        evidence_id = _evidence_id(item)
        if evidence_id in card_by_id:
            selected.append(card_by_id[evidence_id])
        elif isinstance(item.get("card"), dict):
            selected.append(item["card"])
        else:
            selected.append(item)
    return selected


def _cards_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [card for card in payload if isinstance(card, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("cards"), list):
        return [card for card in payload["cards"] if isinstance(card, dict)]
    return []


def _supporting_evidence_ids_for_gap(gap_id: str, gap_map: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in gap_map.get("supporting_evidence") or []:
        if isinstance(item, dict) and gap_id in set(item.get("gap_ids") or []):
            ids.append(str(item.get("evidence_id") or ""))
    return _dedupe(ids)


def _representative_claim_refs(cluster_ids: list[str], landscape: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for cluster in landscape.get("clusters") or []:
        if not isinstance(cluster, dict):
            continue
        cluster_id = str(cluster.get("cluster_id") or "")
        if cluster_id not in cluster_ids:
            continue
        claims = [claim for claim in cluster.get("representative_claims") or [] if isinstance(claim, dict)]
        for index, _claim in enumerate(claims, start=1):
            refs.append(f"landscape:{cluster_id}:claim_{index}")
    return _dedupe(refs)


def _basis_summary(basis: dict[str, Any]) -> str:
    parts = []
    for key in ["landscape_cluster_ids", "evidence_ids", "coverage_warnings", "diagnostic_refs"]:
        values = _dedupe([str(value) for value in basis.get(key) or []])
        if values:
            parts.append(f"{key}={','.join(values)}")
    return "; ".join(parts) if parts else "documented diagnostic support"


def _idea_type_for_gap(gap_type: str) -> str:
    return {
        "coverage_gap": "data_integration",
        "comparison_gap": "comparative_study",
        "evidence_quality_gap": "characterization_strategy",
        "source_type_gap": "characterization_strategy",
        "role_gap": "mechanism_hypothesis",
        "condition_gap": "performance_validation",
    }.get(gap_type, "comparative_study")


def _forbidden_claim_matches(candidate_ideas: dict[str, Any], markdown: str) -> list[str]:
    text = f"{json.dumps(candidate_ideas, ensure_ascii=False)}\n{markdown}".lower()
    return [phrase for phrase in FORBIDDEN_CANDIDATE_IDEA_CLAIMS if phrase in text]


def _collect_warnings(*payloads: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for payload in payloads:
        warnings.extend(str(warning) for warning in payload.get("warnings") or [] if str(warning))
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        warnings.extend(str(warning) for warning in coverage.get("coverage_warnings") or [] if str(warning))
    return _dedupe(warnings)


def _paper_id_for_evidence(artifact: CandidateIdeaArtifact, idea: CandidateIdeaRecord, evidence_id: str) -> str:
    if len(idea.evidence_basis.supporting_evidence_ids) == len(idea.evidence_basis.source_paper_ids):
        index = idea.evidence_basis.supporting_evidence_ids.index(evidence_id)
        return idea.evidence_basis.source_paper_ids[index]
    return artifact.source_paper_ids[0] if artifact.source_paper_ids else ""


def _evidence_id(card: dict[str, Any]) -> str:
    return str(card.get("evidence_id") or "").strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "unknown"


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


def _read_json(execution: SkillExecutionInput, relative_path: str) -> Any:
    return json.loads(_path(execution, relative_path).read_text(encoding="utf-8"))


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


def _path(execution: SkillExecutionInput, relative_path: str) -> Path:
    return _store(execution).resolve_workspace_path(execution.task_id, relative_path)


def _store(execution: SkillExecutionInput) -> ResearchWorkspaceStore:
    root = Path(execution.workspace_root)
    if root.name != execution.task_id:
        raise ValueError("workspace_root must point at the task workspace directory")
    return ResearchWorkspaceStore(root.parents[2])


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


__all__ = [
    "FORBIDDEN_CANDIDATE_IDEA_CLAIMS",
    "generate_candidate_ideas",
    "validate_candidate_ideas_artifact",
]
