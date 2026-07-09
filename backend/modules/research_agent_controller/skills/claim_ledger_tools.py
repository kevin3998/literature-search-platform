"""Deterministic P2-M13 claim ledger skill wrapper.

The wrapper assembles conservative, traceable claim ledger artifacts from
experiment matrix and upstream structured artifacts. It does not draft
manuscripts, generate final claims, call external services, or interpret
experimental results.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from modules.research_workspace import ResearchWorkspaceStore

from ..skill_registry import SkillExecutionInput, SkillExecutionResult, SkillExecutionStatus
from .claim_ledger_contract import (
    CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS,
    CLAIM_LEDGER_OUTPUT_ARTIFACTS,
    CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
    CLAIM_LEDGER_SCHEMA_VERSION,
    ClaimLedgerArtifact,
    ClaimRecord,
    UpstreamDependencies,
    validate_claim_ledger_input_artifacts,
)
from .screening_adapter import normalize_screening_for_downstream, validate_screening_v2_for_downstream

FORBIDDEN_CLAIM_LEDGER_PHRASES = [
    "final claim",
    "manuscript-ready",
    "we conclude",
    "we demonstrate",
    "we prove",
    "proves that",
    "confirms that",
    "experimentally validated",
    "is feasible",
    "is novel",
    "will improve",
    "will enhance",
    "significantly improves",
    "ready for publication",
    "results show",
    "our results show",
]


def build_claim_ledger(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    input_artifacts = list(execution.input_artifacts or CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS)
    input_errors = validate_claim_ledger_input_artifacts(input_artifacts)
    forbidden_errors = [
        error
        for error in input_errors
        if "not_allowed_for_claim_ledger" in error
        or error == "raw_retrieval_candidates_not_allowed_for_claim_ledger"
    ]
    if forbidden_errors:
        return _result(execution, SkillExecutionStatus.VALIDATION_FAILED, errors=forbidden_errors)

    missing_result = _missing_required_input_result(execution)
    if missing_result is not None:
        return missing_result

    payloads: dict[str, Any] = {}
    for artifact_path in CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS:
        try:
            payloads[artifact_path] = _read_json(execution, artifact_path)
        except json.JSONDecodeError:
            return _result(
                execution,
                SkillExecutionStatus.VALIDATION_FAILED,
                input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
                errors=[f"artifact_not_parseable:{artifact_path}"],
            )

    schema_errors = _validate_input_schema_versions(payloads)
    if schema_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
            errors=schema_errors,
        )

    screening_errors = validate_screening_v2_for_downstream(payloads["screening/idea_screening_results.json"])
    if screening_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
            errors=screening_errors,
        )
    screening = normalize_screening_for_downstream(payloads["screening/idea_screening_results.json"])

    basis_errors = _validate_experiment_matrix_for_claim_ledger(payloads["experiments/experiment_matrix.json"])
    if basis_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
            errors=basis_errors,
        )

    forbidden_matches = _forbidden_claim_matches(_input_claim_text(payloads["experiments/experiment_matrix.json"]), "")
    if forbidden_matches:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
            errors=["claim_ledger_rejects_validated_result_claim"],
            metadata={"forbidden_claim_matches": forbidden_matches},
        )

    topic = str(
        execution.parameters.get("topic")
        or payloads["experiments/experiment_matrix.json"].get("topic")
        or payloads["screening/idea_screening_results.json"].get("topic")
        or ""
    ).strip()
    artifact, diagnostics = _build_claim_ledger_artifact(
        task_id=execution.task_id,
        topic=topic or "unspecified topic",
        experiment_matrix=payloads["experiments/experiment_matrix.json"],
        experiment_diagnostics=payloads["experiments/experiment_matrix_diagnostics.json"],
        screening=screening,
        screening_diagnostics=payloads["screening/screening_diagnostics.json"],
        candidate_ideas=payloads["ideas/candidate_ideas.json"],
        idea_diagnostics=payloads["ideas/idea_generation_diagnostics.json"],
        gap_map=payloads["gaps/gap_map.json"],
        gap_diagnostics=payloads["gaps/gap_coverage_diagnostics.json"],
        landscape=payloads["landscape/literature_landscape.json"],
        landscape_diagnostics=payloads["landscape/landscape_coverage_diagnostics.json"],
        enriched_cards=payloads["evidence/evidence_cards.enriched.json"],
        selection=payloads["ranked_evidence/evidence_selection.json"],
        ranking_diagnostics=payloads["ranked_evidence/coverage_diagnostics.json"],
        input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
    )
    markdown = _render_claim_ledger_markdown(artifact)
    validation_errors = validate_claim_ledger_artifact(artifact.as_dict(), markdown)
    if validation_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
            errors=validation_errors,
            warnings=artifact.warnings,
        )

    _write_json(execution, "claims/claim_ledger.json", artifact.as_dict())
    _write_text(execution, "claims/claim_ledger.md", markdown)
    _write_json(execution, "claims/claim_ledger_diagnostics.json", diagnostics)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=CLAIM_LEDGER_OUTPUT_ARTIFACTS,
        warnings=artifact.warnings,
        metadata={
            "claim_count": len(artifact.claims),
            "llm_called": False,
            "manuscript_drafting_performed": False,
            "final_claims_generated": False,
            "experimental_result_interpretation_performed": False,
        },
    )


def validate_claim_ledger_artifact(claim_ledger: dict[str, Any], markdown: str) -> list[str]:
    errors: list[str] = []
    if claim_ledger.get("schema_version") != CLAIM_LEDGER_SCHEMA_VERSION:
        errors.append("invalid_claim_ledger_schema_version")
    for field_name in ("claim_ledger_id", "experiment_matrix_id", "screening_id", "idea_set_id", "gap_map_id", "landscape_id"):
        if not claim_ledger.get(field_name):
            errors.append(f"missing_{field_name}")
    if not claim_ledger.get("evidence_ids"):
        errors.append("claim_ledger_requires_evidence_references")
    claims = claim_ledger.get("claims") or []
    if not claims:
        errors.append("claim_ledger_requires_claims")

    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claim_record_is_not_object:{index}")
            continue
        if not claim.get("claim_id"):
            errors.append(f"claim_record_requires_claim_id:{index}")
        if not claim.get("claim_type"):
            errors.append(f"claim_record_requires_claim_type:{index}")
        if not claim.get("claim_status"):
            errors.append(f"claim_record_requires_claim_status:{index}")
        if not claim.get("source_artifacts"):
            errors.append(f"claim_record_requires_source_artifacts:{index}")
        if claim.get("claim_status") not in {"insufficient_support", "rejected_overclaim"} and not claim.get("evidence_ids"):
            errors.append(f"claim_record_requires_evidence_ids:{index}")
        if claim.get("not_a_final_claim") is not True:
            errors.append(f"claim_record_must_not_be_final_claim:{index}")
        if claim.get("not_experimentally_validated") is not True:
            errors.append(f"claim_record_must_not_be_experimentally_validated:{index}")
        if claim.get("requires_human_review") is not True:
            errors.append(f"claim_record_requires_human_review:{index}")

    if "## Evidence References" not in markdown:
        errors.append("markdown_missing_evidence_references")
    for section in CLAIM_LEDGER_FORBIDDEN_MARKDOWN_SECTIONS:
        if f"## {section}" in markdown:
            errors.append(f"forbidden_claim_ledger_markdown_section:{section}")
    if _forbidden_claim_matches(_claim_text_for_validation(claim_ledger), markdown):
        errors.append("claim_ledger_rejects_validated_result_claim")
    return _dedupe(errors)


def _missing_required_input_result(execution: SkillExecutionInput) -> SkillExecutionResult | None:
    named_missing = [
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
                input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
                errors=[error],
            )
    missing = [artifact_path for artifact_path in CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS if not _path(execution, artifact_path).exists()]
    if missing:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=CLAIM_LEDGER_REQUIRED_INPUT_ARTIFACTS,
            errors=[f"missing_input_artifact:{artifact_path}" for artifact_path in missing],
        )
    return None


def _validate_input_schema_versions(payloads: dict[str, Any]) -> list[str]:
    errors: list[str] = []
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


def _validate_experiment_matrix_for_claim_ledger(experiment_matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    candidates = [candidate for candidate in experiment_matrix.get("experiment_candidates") or [] if isinstance(candidate, dict)]
    if not candidates:
        errors.append("claim_ledger_requires_experiment_matrix")
    for candidate in candidates:
        if not candidate.get("source_idea_id") or not candidate.get("gap_ids") or not candidate.get("evidence_ids"):
            errors.append("claim_ledger_requires_traceable_evidence_basis")
        if candidate.get("not_a_validated_claim") is not True or candidate.get("not_a_protocol") is not True:
            errors.append("claim_ledger_requires_non_final_claim_status")
    return _dedupe(errors)


def _build_claim_ledger_artifact(
    *,
    task_id: str,
    topic: str,
    experiment_matrix: dict[str, Any],
    experiment_diagnostics: dict[str, Any],
    screening: dict[str, Any],
    screening_diagnostics: dict[str, Any],
    candidate_ideas: dict[str, Any],
    idea_diagnostics: dict[str, Any],
    gap_map: dict[str, Any],
    gap_diagnostics: dict[str, Any],
    landscape: dict[str, Any],
    landscape_diagnostics: dict[str, Any],
    enriched_cards: dict[str, Any],
    selection: dict[str, Any],
    ranking_diagnostics: dict[str, Any],
    input_artifacts: list[str],
) -> tuple[ClaimLedgerArtifact, dict[str, Any]]:
    warnings = _collect_warnings(
        experiment_matrix,
        experiment_diagnostics,
        screening,
        screening_diagnostics,
        candidate_ideas,
        idea_diagnostics,
        gap_map,
        gap_diagnostics,
        landscape,
        landscape_diagnostics,
        enriched_cards,
        selection,
        ranking_diagnostics,
    )
    evidence_ids = _dedupe(
        list(experiment_matrix.get("evidence_ids") or [])
        + list(screening.get("evidence_ids") or [])
        + list(candidate_ideas.get("evidence_ids") or [])
        + list(gap_map.get("evidence_ids") or [])
        + list(landscape.get("evidence_ids") or [])
    )
    source_paper_ids = _dedupe(
        list(experiment_matrix.get("source_paper_ids") or [])
        + list(screening.get("source_paper_ids") or [])
        + list(candidate_ideas.get("source_paper_ids") or [])
        + list(gap_map.get("source_paper_ids") or [])
        + list(landscape.get("source_paper_ids") or [])
    )
    evidence_by_id = _evidence_by_id(enriched_cards, selection)
    claims: list[ClaimRecord] = []
    claims.extend(_literature_claims(evidence_by_id, experiment_matrix, screening, candidate_ideas, gap_map, landscape))
    claims.extend(_gap_claims(gap_map, experiment_matrix, screening, candidate_ideas, landscape))
    claims.extend(_candidate_hypothesis_claims(experiment_matrix, screening))
    claims.extend(_screening_claims(screening, experiment_matrix, candidate_ideas, gap_map, landscape))
    claims.extend(_experiment_matrix_claims(experiment_matrix, screening))
    claims.extend(_limitation_claims(experiment_matrix, screening, gap_map, landscape, warnings))

    artifact = ClaimLedgerArtifact(
        task_id=task_id,
        topic=topic,
        claim_ledger_id=f"claim_ledger_{task_id}",
        input_artifacts=input_artifacts,
        experiment_matrix_id=str(experiment_matrix.get("experiment_matrix_id") or ""),
        screening_id=str(experiment_matrix.get("screening_id") or screening.get("screening_id") or ""),
        idea_set_id=str(experiment_matrix.get("idea_set_id") or candidate_ideas.get("idea_set_id") or ""),
        gap_map_id=str(experiment_matrix.get("gap_map_id") or gap_map.get("gap_map_id") or ""),
        landscape_id=str(experiment_matrix.get("landscape_id") or landscape.get("landscape_id") or ""),
        evidence_ids=evidence_ids,
        source_paper_ids=source_paper_ids,
        claims=claims,
        ledger_scope={
            "source": "experiment_matrix_and_upstream_artifacts",
            "real_experiments_interpreted": False,
            "manuscript_drafting_performed": False,
        },
        claim_policy={
            "not_a_final_claim": True,
            "not_experimentally_validated": True,
            "requires_human_review": True,
            "forbid_manuscript_ready_conclusions": True,
        },
        limitations=[
            "Claim ledger is deterministic and limited to existing structured artifacts.",
            "Experiment matrix entries are planning scaffolds, not experimental results.",
            "Human review is required before any downstream manuscript use.",
        ],
        warnings=warnings,
    )
    forbidden_matches = _forbidden_claim_matches(_claim_text_for_validation(artifact.as_dict()), "")
    diagnostics = {
        "artifact_type": "claim_ledger_diagnostics",
        "task_id": task_id,
        "claim_ledger_id": artifact.claim_ledger_id,
        "experiment_matrix_id": artifact.experiment_matrix_id,
        "claim_count": len(artifact.claims),
        "claim_type_counts": _claim_type_counts(artifact.claims),
        "llm_called": False,
        "manuscript_drafting_performed": False,
        "final_claims_generated": False,
        "forbidden_claim_checks": {"passed": not forbidden_matches, "matches": forbidden_matches},
        "warnings": artifact.warnings,
        "created_at": time.time(),
        "schema_version": CLAIM_LEDGER_SCHEMA_VERSION,
    }
    return artifact, diagnostics


def _literature_claims(
    evidence_by_id: dict[str, dict[str, Any]],
    experiment_matrix: dict[str, Any],
    screening: dict[str, Any],
    candidate_ideas: dict[str, Any],
    gap_map: dict[str, Any],
    landscape: dict[str, Any],
) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for index, evidence_id in enumerate(list(evidence_by_id)[:3]):
        card = evidence_by_id[evidence_id]
        paper_id = str(card.get("paper_id") or "")
        statement = str(card.get("normalized_statement") or card.get("verbatim_snippet") or "Evidence card statement is available.")
        claims.append(
            _claim(
                claim_id=f"claim_literature_observation_{index + 1}",
                claim_text=f"Literature evidence records that {statement}",
                claim_type="literature_observation",
                claim_status="evidence_supported_literature_claim",
                source_artifacts=["evidence/evidence_cards.enriched.json", "ranked_evidence/evidence_selection.json"],
                evidence_ids=[evidence_id],
                source_paper_ids=[paper_id] if paper_id else [],
                supporting_evidence=[{"evidence_id": evidence_id, "paper_id": paper_id}],
                support_level="medium",
                allowed_downstream_use="background_context",
                upstream_dependencies=_deps(experiment_matrix, screening, candidate_ideas, landscape),
            )
        )
    return claims


def _gap_claims(
    gap_map: dict[str, Any],
    experiment_matrix: dict[str, Any],
    screening: dict[str, Any],
    candidate_ideas: dict[str, Any],
    landscape: dict[str, Any],
) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for index, gap in enumerate([item for item in gap_map.get("gaps") or [] if isinstance(item, dict)]):
        basis = gap.get("basis") if isinstance(gap.get("basis"), dict) else {}
        evidence_ids = _dedupe(list(basis.get("evidence_ids") or []) + list(gap.get("evidence_ids") or []))
        claims.append(
            _claim(
                claim_id=f"claim_gap_statement_{index + 1}",
                claim_text=f"Gap record {gap.get('gap_id') or index + 1} describes limited evidence coverage: {gap.get('title') or 'coverage gap'}.",
                claim_type="gap_statement",
                claim_status="evidence_grounded_candidate" if evidence_ids else "insufficient_support",
                source_artifacts=["gaps/gap_map.json", "gaps/gap_coverage_diagnostics.json"],
                gap_ids=[str(gap.get("gap_id") or "")],
                evidence_ids=evidence_ids,
                support_level="low" if evidence_ids else "none",
                allowed_downstream_use="gap_framing" if evidence_ids else "limitation_only",
                upstream_dependencies=_deps(experiment_matrix, screening, candidate_ideas, landscape, diagnostic_refs=basis.get("diagnostic_refs") or []),
                warnings=list(gap.get("warnings") or []),
            )
        )
    return claims


def _candidate_hypothesis_claims(experiment_matrix: dict[str, Any], screening: dict[str, Any]) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for index, candidate in enumerate([item for item in experiment_matrix.get("experiment_candidates") or [] if isinstance(item, dict)]):
        claims.append(
            _claim(
                claim_id=f"claim_candidate_hypothesis_{index + 1}",
                claim_text=(
                    f"Candidate hypothesis from {candidate.get('experiment_id') or index + 1}: "
                    f"{candidate.get('hypothesis_under_test') or 'hypothesis requires downstream checking.'}"
                ),
                claim_type="candidate_hypothesis",
                claim_status="hypothesis_requires_validation",
                source_artifacts=["experiments/experiment_matrix.json", "ideas/candidate_ideas.json"],
                source_idea_ids=[str(candidate.get("source_idea_id") or "")],
                source_experiment_ids=[str(candidate.get("experiment_id") or "")],
                gap_ids=list(candidate.get("gap_ids") or []),
                evidence_ids=list(candidate.get("evidence_ids") or []),
                support_level="low",
                allowed_downstream_use="hypothesis_framing",
                upstream_dependencies=_deps(experiment_matrix, screening, {}, {}, experiment_ids=[str(candidate.get("experiment_id") or "")]),
                limitations=list(candidate.get("limitations") or []),
                warnings=list(candidate.get("warnings") or []),
            )
        )
    return claims


def _screening_claims(
    screening: dict[str, Any],
    experiment_matrix: dict[str, Any],
    candidate_ideas: dict[str, Any],
    gap_map: dict[str, Any],
    landscape: dict[str, Any],
) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for index, idea in enumerate([item for item in screening.get("screened_ideas") or [] if isinstance(item, dict)]):
        novelty = str(idea.get("novelty_status") or "unknown")
        feasibility = str(idea.get("feasibility_status") or "unknown")
        risk = str(idea.get("risk_status") or "unknown")
        claims.append(
            _claim(
                claim_id=f"claim_screening_assessment_{index + 1}",
                claim_text=(
                    f"Screening for idea {idea.get('idea_id') or index + 1} remains preliminary: "
                    f"novelty={novelty}, feasibility={feasibility}, risk={risk}."
                ),
                claim_type="screening_assessment",
                claim_status="screening_preliminary",
                source_artifacts=["screening/idea_screening_results.json", "screening/screening_diagnostics.json"],
                source_idea_ids=[str(idea.get("idea_id") or "")],
                gap_ids=list(idea.get("gap_ids") or []),
                evidence_ids=list(idea.get("evidence_ids") or []),
                source_paper_ids=list(screening.get("source_paper_ids") or []),
                support_level="low",
                allowed_downstream_use="limitation_only",
                upstream_dependencies=_deps(experiment_matrix, screening, candidate_ideas, landscape),
                limitations=list(idea.get("limitations") or []),
                warnings=list(idea.get("warnings") or []),
            )
        )
    return claims


def _experiment_matrix_claims(experiment_matrix: dict[str, Any], screening: dict[str, Any]) -> list[ClaimRecord]:
    claims: list[ClaimRecord] = []
    for index, candidate in enumerate([item for item in experiment_matrix.get("experiment_candidates") or [] if isinstance(item, dict)]):
        claims.append(
            _claim(
                claim_id=f"claim_experiment_matrix_rationale_{index + 1}",
                claim_text=(
                    f"Experiment matrix entry {candidate.get('experiment_id') or index + 1} is a planning scaffold "
                    f"for objective: {candidate.get('objective') or 'bounded comparison objective'}."
                ),
                claim_type="experiment_matrix_rationale",
                claim_status="matrix_planning_scaffold",
                source_artifacts=["experiments/experiment_matrix.json", "experiments/experiment_matrix_diagnostics.json"],
                source_idea_ids=[str(candidate.get("source_idea_id") or "")],
                source_experiment_ids=[str(candidate.get("experiment_id") or "")],
                gap_ids=list(candidate.get("gap_ids") or []),
                evidence_ids=list(candidate.get("evidence_ids") or []),
                source_paper_ids=list(experiment_matrix.get("source_paper_ids") or []),
                support_level="low",
                allowed_downstream_use="planning_rationale",
                upstream_dependencies=_deps(experiment_matrix, screening, {}, {}, experiment_ids=[str(candidate.get("experiment_id") or "")]),
                limitations=list(candidate.get("limitations") or []) + ["This entry is not an experimental result."],
                warnings=list(candidate.get("warnings") or []),
            )
        )
    return claims


def _limitation_claims(
    experiment_matrix: dict[str, Any],
    screening: dict[str, Any],
    gap_map: dict[str, Any],
    landscape: dict[str, Any],
    warnings: list[str],
) -> list[ClaimRecord]:
    text = "Current artifacts contain limitations and warnings that require human review before downstream use."
    return [
        _claim(
            claim_id="claim_limitation_1",
            claim_text=text,
            claim_type="limitation_statement",
            claim_status="insufficient_support",
            source_artifacts=[
                "experiments/experiment_matrix_diagnostics.json",
                "screening/screening_diagnostics.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            evidence_ids=[],
            support_level="none",
            allowed_downstream_use="limitation_only",
            upstream_dependencies=_deps(experiment_matrix, screening, {}, landscape, diagnostic_refs=[f"warning:{warning}" for warning in warnings]),
            limitations=list(experiment_matrix.get("limitations") or []) + list(screening.get("limitations") or []),
            warnings=warnings,
        )
    ]


def _claim(
    *,
    claim_id: str,
    claim_text: str,
    claim_type: str,
    claim_status: str,
    source_artifacts: list[str],
    source_idea_ids: list[str] | None = None,
    source_experiment_ids: list[str] | None = None,
    gap_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    source_paper_ids: list[str] | None = None,
    supporting_evidence: list[dict[str, Any]] | None = None,
    upstream_dependencies: UpstreamDependencies | None = None,
    support_level: str = "none",
    allowed_downstream_use: str = "not_for_manuscript_claim",
    prohibited_uses: list[str] | None = None,
    limitations: list[str] | None = None,
    warnings: list[str] | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        claim_text=claim_text,
        claim_type=claim_type,
        claim_status=claim_status,
        source_artifacts=source_artifacts,
        source_idea_ids=_dedupe(source_idea_ids or []),
        source_experiment_ids=_dedupe(source_experiment_ids or []),
        gap_ids=_dedupe(gap_ids or []),
        evidence_ids=_dedupe(evidence_ids or []),
        source_paper_ids=_dedupe(source_paper_ids or []),
        supporting_evidence=list(supporting_evidence or []),
        upstream_dependencies=upstream_dependencies or UpstreamDependencies(),
        support_level=support_level,
        allowed_downstream_use=allowed_downstream_use,
        prohibited_uses=_dedupe(prohibited_uses or ["final_claim", "manuscript_conclusion", "experimental_result_interpretation"]),
        limitations=_dedupe(limitations or []),
        not_a_final_claim=True,
        not_experimentally_validated=True,
        requires_human_review=True,
        warnings=_dedupe(warnings or []),
    )


def _render_claim_ledger_markdown(artifact: ClaimLedgerArtifact) -> str:
    lines = [
        "# Claim Ledger",
        "",
        "## Scope",
        "",
        f"- claim_ledger_id: {artifact.claim_ledger_id}",
        "- scope: deterministic traceability ledger from existing structured artifacts",
        "- manuscript drafting performed: false",
        "",
        "## Upstream Evidence And Artifact Base",
        "",
        f"- experiment_matrix_id: {artifact.experiment_matrix_id}",
        f"- screening_id: {artifact.screening_id}",
        f"- idea_set_id: {artifact.idea_set_id}",
        f"- gap_map_id: {artifact.gap_map_id}",
        f"- landscape_id: {artifact.landscape_id}",
        "",
        "## Claim Records",
        "",
    ]
    for claim in artifact.claims:
        data = claim.as_dict()
        lines.extend(
            [
                f"### {data['claim_id']}",
                "",
                f"- type: {data['claim_type']}",
                f"- status: {data['claim_status']}",
                f"- text: {data['claim_text']}",
                f"- evidence_ids: {', '.join(data['evidence_ids']) if data['evidence_ids'] else 'none'}",
                f"- allowed_downstream_use: {data['allowed_downstream_use']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Claim Status Summary",
            "",
        ]
    )
    for status, count in _status_counts(artifact.claims).items():
        lines.append(f"- {status}: {count}")
    lines.extend(
        [
            "",
            "## Claims Not Suitable For Manuscript Use",
            "",
            "- Claim records require human review before any writing workflow.",
            "- Experiment matrix rationale entries are planning scaffolds only.",
            "",
            "## Limitations",
            "",
        ]
    )
    for limitation in artifact.limitations:
        lines.append(f"- {limitation}")
    lines.extend(
        [
            "",
            "## Required Human Review",
            "",
            "- Review evidence traceability, screening status, and claim wording before downstream use.",
            "",
            "## Evidence References",
            "",
        ]
    )
    for claim in artifact.claims:
        data = claim.as_dict()
        deps = data["upstream_dependencies"]
        lines.append(
            "- "
            f"claim_id={data['claim_id']}; "
            f"experiment_id={','.join(data['source_experiment_ids']) or 'none'}; "
            f"idea_id={','.join(data['source_idea_ids']) or 'none'}; "
            f"screening_id={','.join(deps['screening_ids']) or artifact.screening_id}; "
            f"gap_id={','.join(data['gap_ids']) or 'none'}; "
            f"evidence_id={','.join(data['evidence_ids']) or 'none'}; "
            f"paper_id={','.join(data['source_paper_ids']) or 'none'}; "
            f"landscape_cluster_id={','.join(deps['landscape_cluster_ids']) or 'none'}; "
            f"diagnostic reference={','.join(deps['diagnostic_refs']) or 'none'}"
        )
    return "\n".join(lines) + "\n"


def _deps(
    experiment_matrix: dict[str, Any],
    screening: dict[str, Any],
    candidate_ideas: dict[str, Any],
    landscape: dict[str, Any],
    *,
    experiment_ids: list[str] | None = None,
    diagnostic_refs: list[str] | None = None,
) -> UpstreamDependencies:
    cluster_ids = [
        str(cluster.get("cluster_id"))
        for cluster in landscape.get("clusters") or []
        if isinstance(cluster, dict) and cluster.get("cluster_id")
    ]
    return UpstreamDependencies(
        experiment_matrix_ids=[str(experiment_matrix.get("experiment_matrix_id") or "")] + list(experiment_ids or []),
        screening_ids=[str(screening.get("screening_id") or experiment_matrix.get("screening_id") or "")],
        idea_set_ids=[str(candidate_ideas.get("idea_set_id") or experiment_matrix.get("idea_set_id") or "")],
        landscape_cluster_ids=cluster_ids,
        diagnostic_refs=list(diagnostic_refs or []),
    )


def _evidence_by_id(enriched_cards: dict[str, Any], selection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    for card in enriched_cards.get("cards") or []:
        if isinstance(card, dict) and card.get("evidence_id"):
            cards[str(card["evidence_id"])] = card
    for ranked in selection.get("ranked_cards") or []:
        if isinstance(ranked, dict):
            card = ranked.get("card") if isinstance(ranked.get("card"), dict) else ranked
            if isinstance(card, dict) and card.get("evidence_id"):
                cards.setdefault(str(card["evidence_id"]), card)
    for card in selection.get("selected_cards") or []:
        if isinstance(card, dict) and card.get("evidence_id"):
            cards.setdefault(str(card["evidence_id"]), card)
    return cards


def _status(idea: dict[str, Any], field_name: str) -> str:
    value = idea.get(field_name)
    if isinstance(value, dict):
        return str(value.get("status") or "unknown")
    return "unknown"


def _screening_limitations(idea: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    for field_name in ("novelty", "feasibility", "risk"):
        value = idea.get(field_name)
        if isinstance(value, dict):
            limitations.extend(str(item) for item in value.get("limitations") or [])
    return _dedupe(limitations)


def _collect_warnings(*payloads: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for payload in payloads:
        warnings.extend(str(warning) for warning in payload.get("warnings") or [])
    return _dedupe(warnings)


def _input_claim_text(experiment_matrix: dict[str, Any]) -> str:
    values: list[str] = []
    for candidate in experiment_matrix.get("experiment_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        for key in ("objective", "hypothesis_under_test"):
            if candidate.get(key):
                values.append(str(candidate[key]))
        values.extend(str(item) for item in candidate.get("expected_observations") or [])
        values.extend(str(item) for item in candidate.get("decision_criteria") or [])
        values.extend(str(item) for item in candidate.get("limitations") or [])
    return "\n".join(values)


def _claim_text_for_validation(claim_ledger: dict[str, Any]) -> str:
    values: list[str] = []
    for claim in claim_ledger.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        values.append(str(claim.get("claim_text") or ""))
        values.extend(str(item) for item in claim.get("limitations") or [])
        values.extend(str(item) for item in claim.get("warnings") or [])
    return "\n".join(values)


def _forbidden_claim_matches(text: str, markdown: str) -> list[str]:
    haystack = "\n".join([text, markdown]).lower()
    return [phrase for phrase in FORBIDDEN_CLAIM_LEDGER_PHRASES if phrase in haystack]


def _claim_type_counts(claims: list[ClaimRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for claim in claims:
        counts[claim.claim_type] = counts.get(claim.claim_type, 0) + 1
    return counts


def _status_counts(claims: list[ClaimRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for claim in claims:
        counts[claim.claim_status] = counts.get(claim.claim_status, 0) + 1
    return counts


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


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(str(value) for value in values if value))


__all__ = [
    "FORBIDDEN_CLAIM_LEDGER_PHRASES",
    "build_claim_ledger",
    "validate_claim_ledger_artifact",
]
