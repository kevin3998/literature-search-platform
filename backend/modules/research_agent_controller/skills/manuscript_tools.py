"""Deterministic P2-M14 manuscript-adjacent draft wrapper.

The wrapper assembles a conservative draft scaffold from structured upstream
artifacts. It does not produce submission text, interpret experimental results,
call external services, or upgrade hypotheses into conclusions.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from modules.research_workspace import ResearchWorkspaceStore

from ..skill_registry import SkillExecutionInput, SkillExecutionResult, SkillExecutionStatus
from .manuscript_contract import (
    MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS,
    MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
    MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
    MANUSCRIPT_DRAFT_SCHEMA_VERSION,
    CitationMapRecord,
    DraftBlock,
    ManuscriptSectionDraftArtifact,
    UnsupportedClaimRecord,
    validate_manuscript_drafting_input_artifacts,
)
from .screening_adapter import normalize_screening_for_downstream, validate_screening_v2_for_downstream

FINAL_TEXT_MARKERS = [
    "final abstract",
    "final results",
    "final discussion",
    "final conclusion",
    "final claims",
    "submission-ready",
    "submission ready",
    "publication-ready",
    "publication ready",
    "accepted manuscript",
    "ready for publication",
    "we conclude",
]

UNVALIDATED_RESULT_MARKERS = [
    "we demonstrate",
    "we prove",
    "proves that",
    "confirms that",
    "validated",
    "experimentally validated",
    "is feasible",
    "is novel",
    "will improve",
    "will enhance",
    "significantly improves",
    "results show",
    "our results show",
]


def draft_manuscript_section(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    input_artifacts = list(execution.input_artifacts or MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS)
    input_errors = validate_manuscript_drafting_input_artifacts(input_artifacts)
    forbidden_errors = [
        error
        for error in input_errors
        if "not_allowed_for_manuscript_drafting" in error
        or error == "raw_retrieval_candidates_not_allowed_for_manuscript_drafting"
    ]
    if forbidden_errors:
        return _result(execution, SkillExecutionStatus.VALIDATION_FAILED, errors=forbidden_errors)

    missing_result = _missing_required_input_result(execution)
    if missing_result is not None:
        return missing_result

    payloads: dict[str, Any] = {}
    for artifact_path in MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS:
        try:
            payloads[artifact_path] = _read_json(execution, artifact_path)
        except json.JSONDecodeError:
            return _result(
                execution,
                SkillExecutionStatus.VALIDATION_FAILED,
                input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
                errors=[f"artifact_not_parseable:{artifact_path}"],
            )

    schema_errors = _validate_input_schema_versions(payloads)
    if schema_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
            errors=schema_errors,
        )

    screening_errors = validate_screening_v2_for_downstream(payloads["screening/idea_screening_results.json"])
    if screening_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
            errors=screening_errors,
        )
    screening = normalize_screening_for_downstream(payloads["screening/idea_screening_results.json"])

    claim_errors = _validate_claim_ledger_for_drafting(payloads["claims/claim_ledger.json"])
    if claim_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
            errors=claim_errors,
        )

    artifact, diagnostics = _build_manuscript_draft_artifact(
        task_id=execution.task_id,
        topic=str(execution.parameters.get("topic") or payloads["claims/claim_ledger.json"].get("topic") or "unspecified topic"),
        target_section=str(execution.parameters.get("target_section") or "discussion_scaffold"),
        claim_ledger=payloads["claims/claim_ledger.json"],
        experiment_matrix=payloads["experiments/experiment_matrix.json"],
        screening=screening,
        candidate_ideas=payloads["ideas/candidate_ideas.json"],
        gap_map=payloads["gaps/gap_map.json"],
        landscape=payloads["landscape/literature_landscape.json"],
        input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
        warnings=_collect_warnings(*payloads.values()),
    )
    markdown = _render_markdown(artifact)
    validation_errors = validate_manuscript_draft_artifact(artifact.as_dict(), markdown)
    if validation_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
            errors=validation_errors,
            warnings=artifact.warnings,
        )

    _write_json(execution, "drafts/manuscript_section_draft.json", artifact.as_dict())
    _write_text(execution, "drafts/manuscript_section_draft.md", markdown)
    _write_json(execution, "drafts/manuscript_section_diagnostics.json", diagnostics)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=MANUSCRIPT_DRAFT_OUTPUT_ARTIFACTS,
        warnings=artifact.warnings,
        metadata={
            "draft_block_count": len(artifact.draft_blocks),
            "unsupported_claim_count": len(artifact.unsupported_claims),
            "llm_called": False,
            "final_manuscript_generated": False,
            "final_claims_generated": False,
            "experimental_result_interpretation_performed": False,
        },
    )


def validate_manuscript_draft_artifact(draft: dict[str, Any], markdown: str) -> list[str]:
    errors: list[str] = []
    if draft.get("schema_version") != MANUSCRIPT_DRAFT_SCHEMA_VERSION:
        errors.append("invalid_manuscript_draft_schema_version")
    for field_name in ("draft_id", "claim_ledger_id", "experiment_matrix_id", "screening_id", "idea_set_id", "gap_map_id", "landscape_id"):
        if not draft.get(field_name):
            errors.append(f"missing_{field_name}")
    if not draft.get("evidence_ids"):
        errors.append("manuscript_draft_requires_evidence_ids")

    blocks = draft.get("draft_blocks") or []
    if not blocks:
        errors.append("manuscript_draft_requires_draft_blocks")
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"draft_block_is_not_object:{index}")
            continue
        if not block.get("block_id"):
            errors.append(f"draft_block_requires_block_id:{index}")
        if not block.get("block_type"):
            errors.append(f"draft_block_requires_block_type:{index}")
        if not block.get("text"):
            errors.append(f"draft_block_requires_text:{index}")
        if block.get("block_type") not in {"transition", "caution"} and not block.get("claim_ids"):
            errors.append(f"draft_block_requires_claim_ids:{index}")
        if block.get("requires_human_review") is not True:
            errors.append(f"draft_block_requires_human_review:{index}")
        if block.get("not_final_text") is not True:
            errors.append(f"draft_block_must_not_be_final_text:{index}")
        if block.get("not_peer_reviewed") is not True:
            errors.append(f"draft_block_must_not_be_peer_reviewed:{index}")
        if block.get("not_experimentally_validated") is not True:
            errors.append(f"draft_block_must_not_be_experimentally_validated:{index}")

    for index, citation in enumerate(draft.get("citation_map") or []):
        if not isinstance(citation, dict):
            errors.append(f"citation_map_record_is_not_object:{index}")
            continue
        if not citation.get("claim_id"):
            errors.append(f"citation_map_requires_claim_id:{index}")
        if not citation.get("evidence_ids"):
            errors.append(f"citation_map_requires_evidence_ids:{index}")
        if not citation.get("source_paper_ids"):
            errors.append(f"citation_map_requires_source_paper_ids:{index}")
        if not citation.get("source_artifacts"):
            errors.append(f"citation_map_requires_source_artifacts:{index}")

    if "## Evidence References" not in markdown:
        errors.append("markdown_missing_evidence_references")
    for section in MANUSCRIPT_DRAFT_FORBIDDEN_MARKDOWN_SECTIONS:
        if f"## {section}" in markdown:
            errors.append(f"forbidden_manuscript_draft_markdown_section:{section}")

    validation_text = "\n".join([str(block.get("text") or "") for block in blocks if isinstance(block, dict)] + [markdown])
    if _contains_any(validation_text, FINAL_TEXT_MARKERS):
        errors.append("manuscript_drafting_rejects_final_claim_overwrite")
    if _contains_any(validation_text, UNVALIDATED_RESULT_MARKERS):
        errors.append("manuscript_drafting_rejects_unvalidated_claims")
    return _dedupe(errors)


def _missing_required_input_result(execution: SkillExecutionInput) -> SkillExecutionResult | None:
    named_missing = [
        ("claims/claim_ledger.json", "missing_claim_ledger_artifact"),
        ("experiments/experiment_matrix.json", "missing_experiment_matrix_artifact"),
        ("screening/idea_screening_results.json", "missing_screening_results_artifact"),
        ("ideas/candidate_ideas.json", "missing_candidate_ideas_artifact"),
        ("gaps/gap_map.json", "missing_gap_map_artifact"),
        ("landscape/literature_landscape.json", "missing_landscape_artifact"),
    ]
    for artifact_path, error in named_missing:
        if not _path(execution, artifact_path).exists():
            return _result(
                execution,
                SkillExecutionStatus.BLOCKED,
                input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
                errors=[error],
            )
    missing = [artifact_path for artifact_path in MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS if not _path(execution, artifact_path).exists()]
    if missing:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=MANUSCRIPT_DRAFT_REQUIRED_INPUT_ARTIFACTS,
            errors=[f"missing_manuscript_drafting_input:{artifact_path}" for artifact_path in missing],
        )
    return None


def _validate_input_schema_versions(payloads: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payloads["claims/claim_ledger.json"].get("schema_version") != "claim_ledger_v1":
        errors.append("invalid_claim_ledger_schema_version")
    if payloads["experiments/experiment_matrix.json"].get("schema_version") != "experiment_matrix_v1":
        errors.append("invalid_experiment_matrix_schema_version")
    if payloads["screening/idea_screening_results.json"].get("schema_version") != "idea_screening_v2":
        errors.append("invalid_screening_schema_version")
    if payloads["ideas/candidate_ideas.json"].get("schema_version") != "candidate_ideas_v1":
        errors.append("invalid_candidate_ideas_schema_version")
    if payloads["gaps/gap_map.json"].get("schema_version") != "gap_map_v1":
        errors.append("invalid_gap_map_schema_version")
    if payloads["landscape/literature_landscape.json"].get("schema_version") != "landscape_v1":
        errors.append("invalid_landscape_schema_version")
    return errors


def _validate_claim_ledger_for_drafting(claim_ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    claims = [claim for claim in claim_ledger.get("claims") or [] if isinstance(claim, dict)]
    if not claims:
        errors.append("manuscript_drafting_requires_claim_ledger")
    for claim in claims:
        status = str(claim.get("claim_status") or "")
        if not claim.get("source_artifacts") or (status not in {"insufficient_support", "rejected_overclaim"} and not claim.get("evidence_ids")):
            errors.append("manuscript_drafting_requires_traceable_claims")
        if claim.get("not_a_final_claim") is not True:
            errors.append("manuscript_drafting_rejects_final_claim_overwrite")
        if claim.get("not_experimentally_validated") is not True or claim.get("requires_human_review") is not True:
            errors.append("manuscript_drafting_rejects_unvalidated_claims")
        claim_text = str(claim.get("claim_text") or "")
        if _contains_any(claim_text, FINAL_TEXT_MARKERS):
            errors.append("manuscript_drafting_rejects_final_claim_overwrite")
        if _contains_any(claim_text, UNVALIDATED_RESULT_MARKERS):
            errors.append("manuscript_drafting_rejects_unvalidated_claims")
    return _dedupe(errors)


def _build_manuscript_draft_artifact(
    *,
    task_id: str,
    topic: str,
    target_section: str,
    claim_ledger: dict[str, Any],
    experiment_matrix: dict[str, Any],
    screening: dict[str, Any],
    candidate_ideas: dict[str, Any],
    gap_map: dict[str, Any],
    landscape: dict[str, Any],
    input_artifacts: list[str],
    warnings: list[str],
) -> tuple[ManuscriptSectionDraftArtifact, dict[str, Any]]:
    blocks: list[DraftBlock] = []
    citations: list[CitationMapRecord] = []
    unsupported: list[UnsupportedClaimRecord] = []

    for index, claim in enumerate([item for item in claim_ledger.get("claims") or [] if isinstance(item, dict)], start=1):
        if _claim_is_unsupported(claim):
            unsupported.append(_unsupported_claim(claim, index))
            continue
        block = _draft_block_from_claim(claim, index)
        blocks.append(block)
        if block.evidence_ids and block.source_paper_ids:
            citations.append(
                CitationMapRecord(
                    citation_id=f"cite_{index:03d}",
                    claim_id=claim["claim_id"],
                    evidence_ids=block.evidence_ids,
                    source_paper_ids=block.source_paper_ids,
                    source_artifacts=list(claim.get("source_artifacts") or ["claims/claim_ledger.json"]),
                    citation_status="evidence_grounded" if claim.get("support_level") in {"medium", "high"} else "needs_manual_verification",
                )
            )

    artifact = ManuscriptSectionDraftArtifact(
        task_id=task_id,
        topic=topic,
        draft_id=f"manuscript_section_draft_{task_id}",
        draft_type="discussion_scaffold" if target_section == "discussion_scaffold" else "manuscript_section",
        target_section=target_section,
        input_artifacts=input_artifacts,
        claim_ledger_id=str(claim_ledger.get("claim_ledger_id") or f"claim_ledger_{task_id}"),
        experiment_matrix_id=str(experiment_matrix.get("experiment_matrix_id") or claim_ledger.get("experiment_matrix_id") or ""),
        screening_id=str(screening.get("screening_id") or claim_ledger.get("screening_id") or ""),
        idea_set_id=str(candidate_ideas.get("idea_set_id") or claim_ledger.get("idea_set_id") or ""),
        gap_map_id=str(gap_map.get("gap_map_id") or claim_ledger.get("gap_map_id") or ""),
        landscape_id=str(landscape.get("landscape_id") or claim_ledger.get("landscape_id") or ""),
        evidence_ids=_dedupe(list(claim_ledger.get("evidence_ids") or []) + [evidence_id for block in blocks for evidence_id in block.evidence_ids]),
        source_paper_ids=_dedupe(list(claim_ledger.get("source_paper_ids") or []) + [paper_id for block in blocks for paper_id in block.source_paper_ids]),
        draft_blocks=blocks,
        citation_map=citations,
        unsupported_claims=unsupported,
        draft_policy={
            "not_final_text": True,
            "requires_human_review": True,
            "not_peer_reviewed": True,
            "not_experimentally_validated": True,
            "not_submission_ready": True,
        },
        limitations=_dedupe(
            list(claim_ledger.get("limitations") or [])
            + ["Draft scaffold only; human review is required before any manuscript use."]
        ),
        warnings=_dedupe(warnings + list(claim_ledger.get("warnings") or [])),
    )
    diagnostics = {
        "artifact_type": "manuscript_section_diagnostics",
        "schema_version": MANUSCRIPT_DRAFT_SCHEMA_VERSION,
        "task_id": task_id,
        "draft_id": artifact.draft_id,
        "draft_block_count": len(blocks),
        "citation_count": len(citations),
        "unsupported_claim_count": len(unsupported),
        "warnings": artifact.warnings,
        "created_at": time.time(),
        "llm_called": False,
        "final_manuscript_generated": False,
        "final_claims_generated": False,
    }
    return artifact, diagnostics


def _claim_is_unsupported(claim: dict[str, Any]) -> bool:
    return (
        claim.get("claim_status") in {"rejected_overclaim", "insufficient_support"}
        or claim.get("allowed_downstream_use") == "not_for_manuscript_claim"
        or not claim.get("evidence_ids")
    )


def _unsupported_claim(claim: dict[str, Any], index: int) -> UnsupportedClaimRecord:
    reason = "overclaim" if claim.get("claim_status") == "rejected_overclaim" else "no_evidence_basis"
    action = "remove" if reason == "overclaim" else "move_to_limitations"
    return UnsupportedClaimRecord(
        unsupported_claim_id=str(claim.get("claim_id") or f"unsupported_claim_{index:03d}"),
        text=str(claim.get("claim_text") or "Unsupported claim omitted from draft scaffold."),
        reason=reason,
        source_artifacts=list(claim.get("source_artifacts") or ["claims/claim_ledger.json"]),
        recommended_action=action,
    )


def _draft_block_from_claim(claim: dict[str, Any], index: int) -> DraftBlock:
    claim_type = str(claim.get("claim_type") or "")
    block_type = "context"
    allowed_use = "draft_context"
    text = str(claim.get("claim_text") or "").strip()
    if claim_type in {"gap_statement"}:
        block_type = "gap_framing"
        allowed_use = "draft_gap_framing"
    elif claim_type in {"candidate_hypothesis"}:
        block_type = "hypothesis_framing"
        allowed_use = "draft_hypothesis_framing"
        text = f"The upstream claim ledger frames this point as a hypothesis requiring validation: {text}"
    elif claim_type in {"experiment_matrix_rationale"}:
        block_type = "rationale"
        allowed_use = "draft_hypothesis_framing"
        text = f"The experiment matrix records this item as a planning rationale rather than an experimental result: {text}"
    elif claim_type in {"screening_assessment", "limitation_statement"}:
        block_type = "limitation"
        allowed_use = "draft_limitation"
    elif claim_type in {"evidence_summary"}:
        block_type = "evidence_summary"

    return DraftBlock(
        block_id=f"draft_block_{index:03d}",
        block_type=block_type,
        text=text,
        claim_ids=[str(claim.get("claim_id"))],
        evidence_ids=list(claim.get("evidence_ids") or []),
        source_paper_ids=list(claim.get("source_paper_ids") or []),
        allowed_downstream_use=allowed_use,
        support_level=str(claim.get("support_level") or "low"),
        requires_human_review=True,
        not_final_text=True,
        not_peer_reviewed=True,
        not_experimentally_validated=True,
        warnings=list(claim.get("warnings") or []),
    )


def _render_markdown(artifact: ManuscriptSectionDraftArtifact) -> str:
    blocks = [block.as_dict() for block in artifact.draft_blocks]
    lines = [
        "# Manuscript Section Draft",
        "",
        "## Draft Scope",
        "",
        f"- task_id: {artifact.task_id}",
        f"- topic: {artifact.topic}",
        f"- target_section: {artifact.target_section}",
        "- scope: conservative draft scaffold requiring human review",
        "",
        "## Source Artifact Base",
        "",
        *[f"- {path}" for path in artifact.input_artifacts],
        "",
        "## Draft Blocks",
        "",
    ]
    for block in blocks:
        lines.extend(
            [
                f"### {block['block_id']} ({block['block_type']})",
                "",
                block["text"],
                "",
                f"- claim_ids: {', '.join(block['claim_ids'])}",
                f"- evidence_ids: {', '.join(block['evidence_ids']) or 'none'}",
                f"- support_level: {block['support_level']}",
                "- requires_human_review: true",
                "",
            ]
        )
    lines.extend(["## Citation Map", ""])
    for citation in artifact.citation_map:
        lines.append(f"- {citation.claim_id}: evidence_id={', '.join(citation.evidence_ids)}; source_paper_id={', '.join(citation.source_paper_ids)}")
    lines.extend(["", "## Unsupported Or Downgraded Claims", ""])
    for item in artifact.unsupported_claims:
        lines.append(f"- {item.unsupported_claim_id}: {item.reason}; recommended_action={item.recommended_action}")
    lines.extend(["", "## Limitations", ""])
    for limitation in artifact.limitations:
        lines.append(f"- {limitation}")
    lines.extend(["", "## Required Human Review", "", "- All draft blocks require human review before reuse.", ""])
    lines.extend(["## Evidence References", ""])
    for evidence_id in artifact.evidence_ids:
        lines.append(f"- evidence_id={evidence_id}")
    return "\n".join(lines) + "\n"


def _collect_warnings(*payloads: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for payload in payloads:
        warnings.extend(str(warning) for warning in payload.get("warnings") or [])
        for key in ("coverage_warnings", "diagnostic_warnings"):
            warnings.extend(str(warning) for warning in payload.get(key) or [])
    return _dedupe(warnings)


def _contains_any(text: str, markers: list[str]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _read_json(execution: SkillExecutionInput, relative_path: str) -> dict[str, Any]:
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
    root = Path(execution.workspace_root)
    if root.name != execution.task_id:
        raise ValueError("workspace_root must point at the task workspace directory")
    return ResearchWorkspaceStore(root.parents[2]).resolve_workspace_path(execution.task_id, relative_path)


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


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = ["draft_manuscript_section", "validate_manuscript_draft_artifact"]
