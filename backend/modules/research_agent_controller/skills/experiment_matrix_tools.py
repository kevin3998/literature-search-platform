"""Deterministic P2-M12 experiment matrix skill wrapper.

The wrapper assembles conservative, evidence-referenced experiment matrix
artifacts from screening results and upstream structured artifacts. It does not
perform experiment planning, generate protocols or recipes, call LLMs, or use
external services.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from modules.research_workspace import ResearchWorkspaceStore

from ..skill_registry import SkillExecutionInput, SkillExecutionResult, SkillExecutionStatus
from .experiment_matrix_contract import (
    EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS,
    EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS,
    EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
    EXPERIMENT_MATRIX_SCHEMA_VERSION,
    CharacterizationTarget,
    DesignVariable,
    ExperimentCandidate,
    ExperimentMatrixArtifact,
    ExperimentScreeningBasis,
    validate_experiment_matrix_input_artifacts,
)
from .screening_adapter import normalize_screening_for_downstream, validate_screening_v2_for_downstream

FORBIDDEN_EXPERIMENT_MATRIX_CLAIMS = [
    "step-by-step",
    "synthesis recipe",
    "safety protocol",
    "final claim",
    "is feasible",
    "experimentally feasible",
    "has been validated",
    "experimentally validated",
    "proves that",
    "confirms that",
    "will improve",
    "will enhance",
    "ready to synthesize",
    "ready to test",
    "guaranteed",
]

CONSERVATIVE_NOVELTY_STATUSES = {"requires_external_search", "insufficient_evidence", "unknown"}
CONSERVATIVE_FEASIBILITY_STATUSES = {"requires_expert_review", "insufficient_evidence", "unknown"}
CONSERVATIVE_RISK_STATUSES = {"requires_risk_review", "insufficient_evidence", "unknown"}


def create_experiment_matrix(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    input_artifacts = list(execution.input_artifacts or EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS)
    input_errors = validate_experiment_matrix_input_artifacts(input_artifacts)
    forbidden_errors = [
        error
        for error in input_errors
        if "not_allowed_for_experiment_matrix" in error
        or error == "raw_retrieval_candidates_not_allowed_for_experiment_matrix"
    ]
    if forbidden_errors:
        return _result(execution, SkillExecutionStatus.VALIDATION_FAILED, errors=forbidden_errors)

    missing_result = _missing_required_input_result(execution)
    if missing_result is not None:
        return missing_result

    payloads: dict[str, Any] = {}
    for artifact_path in EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS:
        try:
            payloads[artifact_path] = _read_json(execution, artifact_path)
        except json.JSONDecodeError:
            return _result(
                execution,
                SkillExecutionStatus.VALIDATION_FAILED,
                input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
                errors=[f"artifact_not_parseable:{artifact_path}"],
            )

    schema_errors = _validate_input_schema_versions(payloads)
    if schema_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=schema_errors,
        )

    raw_screening = payloads["screening/idea_screening_results.json"]
    adapter_errors = _screening_downstream_errors_for_experiment_matrix(raw_screening)
    if adapter_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=adapter_errors,
        )

    screening = normalize_screening_for_downstream(raw_screening)
    screening_errors = _validate_screening_for_experiment_matrix(screening)
    if screening_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=screening_errors,
        )

    topic = str(execution.parameters.get("topic") or screening.get("topic") or "").strip()
    artifact, diagnostics = _build_experiment_matrix_artifact(
        task_id=execution.task_id,
        topic=topic or "unspecified topic",
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
        input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
    )
    markdown = _render_experiment_matrix_markdown(
        artifact,
        payloads["gaps/gap_map.json"],
        payloads["landscape/literature_landscape.json"],
    )
    validation_errors = validate_experiment_matrix_artifact(artifact.as_dict(), markdown)
    if validation_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=validation_errors,
            warnings=artifact.warnings,
        )

    _write_json(execution, "experiments/experiment_matrix.json", artifact.as_dict())
    _write_text(execution, "experiments/experiment_matrix.md", markdown)
    _write_json(execution, "experiments/experiment_matrix_diagnostics.json", diagnostics)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=EXPERIMENT_MATRIX_OUTPUT_ARTIFACTS,
        warnings=artifact.warnings,
        metadata={
            "experiment_candidate_count": len(artifact.experiment_candidates),
            "real_experiment_planning_performed": False,
            "llm_called": False,
        },
    )


def validate_experiment_matrix_artifact(experiment_matrix: dict[str, Any], markdown: str) -> list[str]:
    errors: list[str] = []
    if experiment_matrix.get("schema_version") != EXPERIMENT_MATRIX_SCHEMA_VERSION:
        errors.append("invalid_experiment_matrix_schema_version")
    for field_name in ("experiment_matrix_id", "screening_id", "idea_set_id", "gap_map_id", "landscape_id"):
        if not experiment_matrix.get(field_name):
            errors.append(f"missing_{field_name}")
    if not experiment_matrix.get("evidence_ids"):
        errors.append("experiment_matrix_requires_evidence_references")
    if not experiment_matrix.get("experiment_candidates"):
        errors.append("experiment_matrix_requires_candidates")

    for index, candidate in enumerate(experiment_matrix.get("experiment_candidates") or []):
        if not isinstance(candidate, dict):
            errors.append(f"experiment_candidate_is_not_object:{index}")
            continue
        if not candidate.get("source_idea_id"):
            errors.append(f"experiment_candidate_requires_source_idea_id:{index}")
        if not candidate.get("screening_basis"):
            errors.append(f"experiment_candidate_requires_screening_basis:{index}")
        if not candidate.get("gap_ids"):
            errors.append(f"experiment_candidate_requires_gap_ids:{index}")
        if not candidate.get("evidence_ids"):
            errors.append(f"experiment_candidate_requires_evidence_ids:{index}")
        if candidate.get("not_a_protocol") is not True:
            errors.append(f"experiment_candidate_must_not_be_protocol:{index}")
        if candidate.get("not_a_validated_claim") is not True:
            errors.append(f"experiment_candidate_must_not_be_validated_claim:{index}")
        if candidate.get("requires_expert_review") is not True:
            errors.append(f"experiment_candidate_requires_expert_review:{index}")
        for variable_index, variable in enumerate(candidate.get("design_variables") or []):
            if isinstance(variable, dict) and variable.get("not_a_stepwise_instruction") is not True:
                errors.append(f"design_variable_must_not_be_stepwise_instruction:{index}:{variable_index}")

    if "## Evidence References" not in markdown:
        errors.append("markdown_missing_evidence_references")
    for section in EXPERIMENT_MATRIX_FORBIDDEN_MARKDOWN_SECTIONS:
        if f"## {section}" in markdown:
            errors.append(f"forbidden_experiment_matrix_markdown_section:{section}")
    if _forbidden_claim_matches(experiment_matrix, markdown):
        errors.append("unsupported_experiment_matrix_claim")
    return _dedupe(errors)


def _missing_required_input_result(execution: SkillExecutionInput) -> SkillExecutionResult | None:
    if not _path(execution, "screening/idea_screening_results.json").exists():
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=["missing_screening_results_artifact"],
        )
    if not _path(execution, "ideas/candidate_ideas.json").exists():
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=["missing_candidate_ideas_artifact"],
        )
    if not _path(execution, "gaps/gap_map.json").exists():
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=["missing_gap_map_artifact"],
        )
    if not _path(execution, "landscape/literature_landscape.json").exists():
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=["missing_landscape_artifact"],
        )
    missing = [
        artifact_path
        for artifact_path in EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS
        if not _path(execution, artifact_path).exists()
    ]
    if missing:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=EXPERIMENT_MATRIX_REQUIRED_INPUT_ARTIFACTS,
            errors=[f"missing_input_artifact:{artifact_path}" for artifact_path in missing],
        )
    return None


def _validate_input_schema_versions(payloads: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payloads["screening/idea_screening_results.json"].get("schema_version") != "idea_screening_v2":
        errors.append("invalid_screening_schema_version")
    if payloads["ideas/candidate_ideas.json"].get("schema_version") != "candidate_ideas_v1":
        errors.append("invalid_candidate_ideas_schema_version")
    if payloads["gaps/gap_map.json"].get("schema_version") != "gap_map_v1":
        errors.append("invalid_gap_map_schema_version")
    if payloads["landscape/literature_landscape.json"].get("schema_version") != "landscape_v1":
        errors.append("invalid_landscape_schema_version")
    return errors


def _screening_downstream_errors_for_experiment_matrix(screening: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for error in validate_screening_v2_for_downstream(screening):
        if error == "screening_requires_screened_ideas":
            errors.append("experiment_matrix_requires_screened_ideas")
        elif error.startswith("screened_idea_requires_gap_ids") or error.startswith("screened_idea_requires_evidence_ids"):
            errors.append("experiment_matrix_requires_gap_and_evidence_basis")
        elif error.startswith("screening_must_not_be_"):
            errors.append("experiment_matrix_requires_conservative_screening_status")
        else:
            errors.append(error)
    return _dedupe(errors)


def _validate_screening_for_experiment_matrix(screening: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    screened_ideas = [idea for idea in screening.get("screened_ideas") or [] if isinstance(idea, dict)]
    if not screened_ideas:
        errors.append("experiment_matrix_requires_screened_ideas")
    for idea in screened_ideas:
        if not idea.get("gap_ids") or not idea.get("evidence_ids"):
            errors.append("experiment_matrix_requires_gap_and_evidence_basis")
        if idea.get("not_an_experiment_plan") is not True or idea.get("not_a_validated_claim") is not True:
            errors.append("experiment_matrix_requires_conservative_screening_status")
        if not _screening_statuses_are_conservative(idea):
            errors.append("experiment_matrix_requires_conservative_screening_status")
    return _dedupe(errors)


def _screening_statuses_are_conservative(idea: dict[str, Any]) -> bool:
    return (
        str(idea.get("novelty_status") or "unknown") in CONSERVATIVE_NOVELTY_STATUSES
        and str(idea.get("feasibility_status") or "unknown") in CONSERVATIVE_FEASIBILITY_STATUSES
        and str(idea.get("risk_status") or "unknown") in CONSERVATIVE_RISK_STATUSES
    )


def _build_experiment_matrix_artifact(
    *,
    task_id: str,
    topic: str,
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
) -> tuple[ExperimentMatrixArtifact, dict[str, Any]]:
    warnings = _collect_warnings(
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
    ideas_by_id = {
        str(idea.get("idea_id") or ""): idea
        for idea in candidate_ideas.get("ideas") or []
        if isinstance(idea, dict) and idea.get("idea_id")
    }
    source_paper_ids = _dedupe(
        list(screening.get("source_paper_ids") or [])
        + list(candidate_ideas.get("source_paper_ids") or [])
        + list(gap_map.get("source_paper_ids") or [])
        + list(landscape.get("source_paper_ids") or [])
        + [str(card.get("paper_id") or "") for card in _cards_from_payload(enriched_cards)]
    )
    candidates: list[ExperimentCandidate] = []
    skipped_idea_ids: list[str] = []
    for screened_idea in [idea for idea in screening.get("screened_ideas") or [] if isinstance(idea, dict)][:10]:
        idea_id = str(screened_idea.get("idea_id") or "")
        if not idea_id or not screened_idea.get("gap_ids") or not screened_idea.get("evidence_ids"):
            if idea_id:
                skipped_idea_ids.append(idea_id)
                warnings.append(f"skipped_screened_idea_without_gap_or_evidence_basis:{idea_id}")
            continue
        candidates.append(_candidate_from_screened_idea(screened_idea, ideas_by_id.get(idea_id, {})))

    artifact = ExperimentMatrixArtifact(
        task_id=task_id,
        topic=topic,
        experiment_matrix_id=f"experiment_matrix_{task_id}",
        input_artifacts=input_artifacts,
        screening_id=str(screening.get("screening_id") or ""),
        idea_set_id=str(screening.get("idea_set_id") or candidate_ideas.get("idea_set_id") or ""),
        gap_map_id=str(screening.get("gap_map_id") or candidate_ideas.get("gap_map_id") or gap_map.get("gap_map_id") or ""),
        landscape_id=str(
            screening.get("landscape_id")
            or candidate_ideas.get("landscape_id")
            or gap_map.get("landscape_id")
            or landscape.get("landscape_id")
            or ""
        ),
        evidence_ids=_dedupe([evidence_id for candidate in candidates for evidence_id in candidate.evidence_ids]),
        source_paper_ids=source_paper_ids,
        experiment_candidates=candidates,
        matrix_scope={
            "source": "screened_ideas",
            "max_experiment_candidates": 10,
            "real_experiment_planning_performed": False,
        },
        design_policy={
            "one_candidate_per_valid_screened_idea": True,
            "requires_expert_review": True,
            "no_stepwise_instructions": True,
            "no_final_claims": True,
        },
        limitations=[
            "Experiment matrix is a deterministic assembly from screened ideas and evidence references.",
            "No expert-reviewed experimental design has been performed.",
            "No execution guidance or safety review is provided.",
        ],
        warnings=_dedupe(warnings),
    )
    diagnostics = {
        "artifact_type": "experiment_matrix_diagnostics",
        "task_id": task_id,
        "experiment_matrix_id": artifact.experiment_matrix_id,
        "screening_id": artifact.screening_id,
        "experiment_candidate_count": len(artifact.experiment_candidates),
        "skipped_idea_ids": skipped_idea_ids,
        "forbidden_claim_checks": {"passed": not _forbidden_claim_matches(artifact.as_dict(), ""), "matches": _forbidden_claim_matches(artifact.as_dict(), "")},
        "warnings": artifact.warnings,
        "created_at": time.time(),
        "schema_version": EXPERIMENT_MATRIX_SCHEMA_VERSION,
    }
    return artifact, diagnostics


def _candidate_from_screened_idea(screened_idea: dict[str, Any], source_idea: dict[str, Any]) -> ExperimentCandidate:
    idea_id = str(screened_idea.get("idea_id") or "")
    title = str(screened_idea.get("source_idea_title") or source_idea.get("title") or idea_id)
    gap_ids = _dedupe([str(value) for value in screened_idea.get("gap_ids") or []])
    evidence_ids = _dedupe([str(value) for value in screened_idea.get("evidence_ids") or []])
    screening_basis = ExperimentScreeningBasis(
        novelty_status=str(screened_idea.get("novelty_status") or "unknown"),
        feasibility_status=str(screened_idea.get("feasibility_status") or "unknown"),
        risk_status=str(screened_idea.get("risk_status") or "unknown"),
        required_follow_up=_dedupe([str(value) for value in screened_idea.get("required_follow_up") or []]),
        limitations=_dedupe([str(value) for value in screened_idea.get("limitations") or []]),
    )
    return ExperimentCandidate(
        experiment_id=f"exp_{idea_id}",
        source_idea_id=idea_id,
        screened_idea_ref=f"screening:{idea_id}",
        objective=f"Evaluate candidate idea {idea_id}: {title} under controlled comparison, subject to expert review.",
        hypothesis_under_test=(
            "The candidate idea suggests a possible relationship between the documented gap and evidence basis. "
            "This remains an unconfirmed hypothesis requiring expert-reviewed design."
        ),
        gap_ids=gap_ids,
        evidence_ids=evidence_ids,
        screening_basis=screening_basis,
        design_variables=_design_variables_for_idea(idea_id, evidence_ids, source_idea),
        control_groups=["baseline material or system from the evidence-grounded comparison context"],
        comparison_groups=["candidate variation group defined only at a high level"],
        characterization_targets=[
            CharacterizationTarget(
                target_id=f"target_{idea_id}_structure",
                target="structure and defect-related evidence",
                purpose="verify_structure",
                linked_gap_ids=gap_ids,
                linked_evidence_ids=evidence_ids,
                expected_evidence_type="characterization evidence",
                limitations=["Specific instrumentation parameters require expert review."],
            ),
            CharacterizationTarget(
                target_id=f"target_{idea_id}_comparison",
                target="control comparison evidence",
                purpose="compare_control",
                linked_gap_ids=gap_ids,
                linked_evidence_ids=evidence_ids,
                expected_evidence_type="comparison evidence",
                limitations=["Comparison design is not specified in P2-M12.2."],
            ),
        ],
        expected_observations=[
            "Record observations needed to evaluate whether evidence-grounded expectations align with controls."
        ],
        decision_criteria=[
            "Compare target observations against controls.",
            "Assess whether characterization evidence supports the proposed structure/property relationship.",
            "Check whether performance trends are consistent with evidence-grounded expectations.",
        ],
        data_to_record=[
            "composition descriptors",
            "structure descriptors",
            "defect indicators",
            "performance metrics",
            "control comparison data",
            "characterization evidence",
        ],
        constraints=_dedupe([str(value) for value in source_idea.get("constraints") or []] + ["Requires expert review before execution."]),
        risk_notes=[
            f"Risk status: {screening_basis.risk_status}.",
            "Risk remains under review.",
            "No safety review has been performed.",
        ],
        warnings=_dedupe(list(screened_idea.get("warnings") or []) + list(source_idea.get("warnings") or [])),
    )


def _design_variables_for_idea(idea_id: str, evidence_ids: list[str], source_idea: dict[str, Any]) -> list[DesignVariable]:
    title = str(source_idea.get("title") or "candidate idea")
    return [
        DesignVariable(
            variable_id=f"var_{idea_id}_comparison",
            name="control comparison factor",
            role="comparison_factor",
            allowed_level_description="high-level comparison categories only; no recipe, amounts, timings, or operating steps",
            rationale=f"Linked to screened candidate idea: {title}.",
            evidence_refs=evidence_ids,
            constraints=["Requires expert review before any operational design."],
        ),
        DesignVariable(
            variable_id=f"var_{idea_id}_defect",
            name="defect-related factor",
            role="defect",
            allowed_level_description="bounded qualitative levels only; no synthesis instructions",
            rationale="Oxygen-vacancy-related evidence motivates a high-level defect variable.",
            evidence_refs=evidence_ids,
            constraints=["Keep variable definition non-operational."],
        ),
    ]


def _render_experiment_matrix_markdown(
    artifact: ExperimentMatrixArtifact,
    gap_map: dict[str, Any],
    landscape: dict[str, Any],
) -> str:
    lines = [
        "# Experiment Matrix",
        "",
        "## Scope",
        "",
        f"Topic: {artifact.topic}",
        f"Experiment matrix ID: {artifact.experiment_matrix_id}",
        f"Screening ID: {artifact.screening_id}",
        "",
        "## Screening And Evidence Base",
        "",
        f"- idea_set_id: {artifact.idea_set_id}",
        f"- gap_map_id: {artifact.gap_map_id}",
        f"- landscape_id: {artifact.landscape_id}",
        f"- evidence_ids: {', '.join(artifact.evidence_ids)}",
        "",
        "## Candidate Experiment Matrix",
        "",
    ]
    for candidate in artifact.experiment_candidates:
        lines.extend(
            [
                f"### {candidate.experiment_id}",
                "",
                f"- idea_id: {candidate.source_idea_id}",
                f"- objective: {candidate.objective}",
                f"- hypothesis_under_test: {candidate.hypothesis_under_test}",
                f"- gap_ids: {', '.join(candidate.gap_ids)}",
                f"- evidence_ids: {', '.join(candidate.evidence_ids)}",
                "- review_required: true",
                "",
            ]
        )
    lines.extend(["## Variables And Controls", ""])
    for candidate in artifact.experiment_candidates:
        for variable in candidate.design_variables:
            lines.append(
                f"- experiment_id={candidate.experiment_id}; variable_id={variable.variable_id}; "
                f"role={variable.role}; evidence_refs={', '.join(variable.evidence_refs)}"
            )
        lines.append(f"- experiment_id={candidate.experiment_id}; control_groups={', '.join(candidate.control_groups)}")
        lines.append(f"- experiment_id={candidate.experiment_id}; comparison_groups={', '.join(candidate.comparison_groups)}")
    lines.extend(["", "## Characterization Targets", ""])
    for candidate in artifact.experiment_candidates:
        for target in candidate.characterization_targets:
            lines.append(
                f"- experiment_id={candidate.experiment_id}; target_id={target.target_id}; "
                f"purpose={target.purpose}; evidence_ids={', '.join(target.linked_evidence_ids)}"
            )
    lines.extend(["", "## Data To Record", ""])
    for candidate in artifact.experiment_candidates:
        lines.append(f"- experiment_id={candidate.experiment_id}; data={', '.join(candidate.data_to_record)}")
    lines.extend(["", "## Required Expert Review", ""])
    for candidate in artifact.experiment_candidates:
        for follow_up in candidate.screening_basis.required_follow_up:
            lines.append(f"- experiment_id={candidate.experiment_id}; follow_up={follow_up}")
    lines.extend(["", "## Limitations", ""])
    for limitation in artifact.limitations:
        lines.append(f"- {limitation}")
    if artifact.warnings:
        lines.append(f"- Warnings: {', '.join(artifact.warnings)}")
    lines.extend(["", "## Evidence References", ""])
    paper_by_evidence = _paper_by_evidence(artifact)
    for candidate in artifact.experiment_candidates:
        for gap_id in candidate.gap_ids:
            lines.append(f"- experiment_id={candidate.experiment_id}; idea_id={candidate.source_idea_id}; gap_id={gap_id}")
        for evidence_id in candidate.evidence_ids:
            lines.append(
                f"- experiment_id={candidate.experiment_id}; idea_id={candidate.source_idea_id}; "
                f"evidence_id={evidence_id}; paper_id={paper_by_evidence.get(evidence_id, '')}"
            )
        for cluster_id in _cluster_refs(candidate.gap_ids, gap_map, landscape):
            lines.append(
                f"- experiment_id={candidate.experiment_id}; idea_id={candidate.source_idea_id}; "
                f"landscape_cluster_id={cluster_id}"
            )
        for warning in candidate.warnings:
            lines.append(f"- experiment_id={candidate.experiment_id}; diagnostic reference={warning}")
    return "\n".join(lines).strip() + "\n"


def _cluster_refs(gap_ids: list[str], gap_map: dict[str, Any], landscape: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for gap in gap_map.get("gaps") or []:
        if not isinstance(gap, dict) or gap.get("gap_id") not in gap_ids:
            continue
        basis = gap.get("basis") if isinstance(gap.get("basis"), dict) else {}
        refs.extend(str(value) for value in basis.get("landscape_cluster_ids") or [])
    refs.extend(str(cluster.get("cluster_id")) for cluster in landscape.get("clusters") or [] if isinstance(cluster, dict))
    return _dedupe(refs)


def _paper_by_evidence(artifact: ExperimentMatrixArtifact) -> dict[str, str]:
    if len(artifact.evidence_ids) == len(artifact.source_paper_ids):
        return dict(zip(artifact.evidence_ids, artifact.source_paper_ids))
    fallback = artifact.source_paper_ids[0] if artifact.source_paper_ids else ""
    return {evidence_id: fallback for evidence_id in artifact.evidence_ids}


def _cards_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [card for card in payload.get("cards") or [] if isinstance(card, dict)]


def _forbidden_claim_matches(experiment_matrix: dict[str, Any], markdown: str) -> list[str]:
    text = f"{json.dumps(experiment_matrix, ensure_ascii=False)}\n{markdown}".lower()
    return [phrase for phrase in FORBIDDEN_EXPERIMENT_MATRIX_CLAIMS if phrase in text]


def _collect_warnings(*payloads: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for payload in payloads:
        warnings.extend(str(warning) for warning in payload.get("warnings") or [] if str(warning))
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        warnings.extend(str(warning) for warning in coverage.get("coverage_warnings") or [] if str(warning))
    return _dedupe(warnings)


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
    "FORBIDDEN_EXPERIMENT_MATRIX_CLAIMS",
    "create_experiment_matrix",
    "validate_experiment_matrix_artifact",
]
