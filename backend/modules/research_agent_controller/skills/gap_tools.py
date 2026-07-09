"""Deterministic P2-M9 gap mapping skill wrapper.

The wrapper maps coverage and diagnostic structure into bounded gap artifacts.
It does not perform semantic ideation or call external generation services.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from modules.research_workspace import ResearchWorkspaceStore

from ..skill_registry import SkillExecutionInput, SkillExecutionResult, SkillExecutionStatus
from .gap_contract import (
    GAP_FORBIDDEN_MARKDOWN_SECTIONS,
    GAP_INITIAL_AXES,
    GAP_MAP_SCHEMA_VERSION,
    GAP_OUTPUT_ARTIFACTS,
    GAP_REQUIRED_INPUT_ARTIFACTS,
    GapAxis,
    GapBasis,
    GapMapArtifact,
    GapRecord,
    SupportingEvidence,
    validate_gap_mapping_input_artifacts,
)


def map_gaps(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    input_artifacts = list(execution.input_artifacts or GAP_REQUIRED_INPUT_ARTIFACTS)
    input_errors = validate_gap_mapping_input_artifacts(input_artifacts)
    forbidden_errors = [error for error in input_errors if "not_allowed_for_gap_mapping" in error]
    if forbidden_errors:
        return _result(execution, SkillExecutionStatus.VALIDATION_FAILED, errors=forbidden_errors)

    if not _path(execution, "landscape/literature_landscape.json").exists():
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
            errors=["missing_landscape_artifact"],
        )

    missing = [path for path in GAP_REQUIRED_INPUT_ARTIFACTS if not _path(execution, path).exists()]
    if missing:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
            errors=[f"missing_input_artifact:{path}" for path in missing],
        )

    payloads: dict[str, Any] = {}
    for artifact_path in GAP_REQUIRED_INPUT_ARTIFACTS:
        try:
            payloads[artifact_path] = _read_json(execution, artifact_path)
        except json.JSONDecodeError:
            return _result(
                execution,
                SkillExecutionStatus.VALIDATION_FAILED,
                input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
                errors=[f"artifact_not_parseable:{artifact_path}"],
            )

    landscape = payloads["landscape/literature_landscape.json"]
    if landscape.get("schema_version") != "landscape_v1":
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
            errors=["invalid_landscape_schema_version"],
        )

    enriched = payloads["evidence/evidence_cards.enriched.json"]
    selection = payloads["ranked_evidence/evidence_selection.json"]
    landscape_diagnostics = payloads["landscape/landscape_coverage_diagnostics.json"]
    ranking_diagnostics = payloads["ranked_evidence/coverage_diagnostics.json"]
    cards = _cards_from_payload(enriched)
    selected_cards = _selected_cards(selection, cards)
    if not cards or not selected_cards:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
            errors=["gap_mapping_requires_evidence_references"],
        )

    topic = str(execution.parameters.get("topic") or landscape.get("topic") or enriched.get("topic") or "").strip()
    artifact = _build_gap_map_artifact(
        task_id=execution.task_id,
        topic=topic or "unspecified topic",
        landscape=landscape,
        landscape_diagnostics=landscape_diagnostics,
        cards=cards,
        selected_cards=selected_cards,
        selection=selection,
        ranking_diagnostics=ranking_diagnostics,
        input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
    )
    markdown = _render_gap_markdown(artifact)
    validation_errors = validate_gap_map_artifact(artifact.as_dict(), markdown)
    if validation_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
            errors=validation_errors,
            warnings=artifact.warnings,
        )

    diagnostics_payload = {
        "artifact_type": "gap_coverage_diagnostics",
        "task_id": execution.task_id,
        "gap_map_id": artifact.gap_map_id,
        "landscape_id": artifact.landscape_id,
        "gap_count": len(artifact.gaps),
        "coverage": artifact.coverage,
        "warnings": list(artifact.warnings),
        "created_at": time.time(),
        "schema_version": GAP_MAP_SCHEMA_VERSION,
    }
    _write_json(execution, "gaps/gap_map.json", artifact.as_dict())
    _write_text(execution, "gaps/gap_map.md", markdown)
    _write_json(execution, "gaps/gap_coverage_diagnostics.json", diagnostics_payload)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=GAP_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=GAP_OUTPUT_ARTIFACTS,
        warnings=artifact.warnings,
        metadata={
            "gap_count": len(artifact.gaps),
            "evidence_count": len(artifact.evidence_ids),
            "source_paper_count": len(artifact.source_paper_ids),
        },
    )


def validate_gap_map_artifact(gap_map: dict[str, Any], markdown: str) -> list[str]:
    errors: list[str] = []
    if gap_map.get("schema_version") != GAP_MAP_SCHEMA_VERSION:
        errors.append("invalid_gap_map_schema_version")
    if not gap_map.get("gap_map_id"):
        errors.append("missing_gap_map_id")
    if not gap_map.get("landscape_id"):
        errors.append("missing_landscape_id")
    if not gap_map.get("evidence_ids"):
        errors.append("gap_mapping_requires_evidence_references")

    gap_ids = set()
    for index, gap in enumerate(gap_map.get("gaps") or []):
        if not isinstance(gap, dict):
            errors.append(f"gap_is_not_object:{index}")
            continue
        if gap.get("gap_id"):
            gap_ids.add(gap["gap_id"])
        basis = gap.get("basis") if isinstance(gap.get("basis"), dict) else {}
        if not any(basis.get(key) for key in ["landscape_cluster_ids", "evidence_ids", "coverage_warnings", "diagnostic_refs"]):
            errors.append(f"gap_missing_basis:{index}")
        if gap.get("not_an_idea") is not True:
            errors.append(f"gap_must_not_be_candidate_idea:{index}")

    for index, item in enumerate(gap_map.get("supporting_evidence") or []):
        if not isinstance(item, dict):
            errors.append(f"supporting_evidence_is_not_object:{index}")
            continue
        item_gap_ids = set(item.get("gap_ids") or [])
        if not item_gap_ids:
            errors.append(f"supporting_evidence_missing_gap_ids:{index}")
        elif not item_gap_ids.issubset(gap_ids):
            errors.append(f"supporting_evidence_unknown_gap_id:{index}")

    if "## Evidence References" not in markdown:
        errors.append("markdown_missing_evidence_references")
    for section in GAP_FORBIDDEN_MARKDOWN_SECTIONS:
        if f"## {section}" in markdown:
            errors.append(f"forbidden_gap_markdown_section:{section}")
    return errors


def _build_gap_map_artifact(
    *,
    task_id: str,
    topic: str,
    landscape: dict[str, Any],
    landscape_diagnostics: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_cards: list[dict[str, Any]],
    selection: dict[str, Any],
    ranking_diagnostics: dict[str, Any],
    input_artifacts: list[str],
) -> GapMapArtifact:
    warnings = _collect_warnings(landscape, landscape_diagnostics, selection, ranking_diagnostics)
    coverage = _coverage(landscape, landscape_diagnostics, cards, selected_cards, ranking_diagnostics, warnings)
    evidence_ids = _dedupe([_evidence_id(card) for card in selected_cards])
    source_paper_ids = _dedupe([str(card.get("paper_id") or "") for card in selected_cards])
    axis_values = _axis_values(landscape, selected_cards, warnings)
    gap_axes = [
        GapAxis(
            axis_id=axis_id,
            name=axis_id.replace("_", " ").title(),
            description=f"Gap organization dimension: {axis_id}.",
            source="landscape_evidence_or_diagnostics",
        )
        for axis_id in GAP_INITIAL_AXES
    ]
    gaps = _generate_gaps(landscape, selected_cards, coverage, warnings, axis_values)
    supporting = _supporting_evidence(selected_cards, gaps)
    return GapMapArtifact(
        task_id=task_id,
        topic=topic,
        gap_map_id=f"gap_map_{task_id}",
        input_artifacts=input_artifacts,
        landscape_id=str(landscape.get("landscape_id") or ""),
        evidence_ids=evidence_ids,
        source_paper_ids=source_paper_ids,
        gap_axes=gap_axes,
        gaps=gaps,
        coverage=coverage,
        supporting_evidence=supporting,
        limitations=[
            "Gap map is generated by deterministic coverage and diagnostic rules.",
            "Gaps describe evidence structure and must not be read as candidate research ideas.",
        ],
        warnings=_dedupe(warnings),
    )


def _generate_gaps(
    landscape: dict[str, Any],
    selected_cards: list[dict[str, Any]],
    coverage: dict[str, Any],
    warnings: list[str],
    axis_values: dict[str, list[str]],
) -> list[GapRecord]:
    gaps: list[GapRecord] = []
    selected_ids = _dedupe([_evidence_id(card) for card in selected_cards])
    clusters = [cluster for cluster in landscape.get("clusters") or [] if isinstance(cluster, dict)]

    for role in coverage.get("missing_roles") or []:
        gaps.append(
            _gap(
                "missing_role",
                "role_gap",
                f"Missing evidence role: {role}",
                f"The coverage diagnostics identify {role} as absent from the selected evidence base.",
                {"evidence_role": role},
                GapBasis(
                    evidence_ids=selected_ids,
                    coverage_warnings=[f"missing_role:{role}"],
                    diagnostic_refs=["ranking_coverage:missing_roles"],
                ),
                "high",
                "high",
            )
        )

    if coverage.get("dominant_source_warning"):
        gaps.append(
            _gap(
                "dominant_source",
                "source_type_gap",
                "Selected evidence is concentrated in a narrow source base",
                "The selected evidence is dominated by a single source paper or source pattern.",
                {"source_paper_ids": coverage.get("source_paper_ids", [])},
                GapBasis(evidence_ids=selected_ids, coverage_warnings=["dominant_paper_warning"], diagnostic_refs=["selection:warnings"]),
                "high",
                "high",
            )
        )

    for warning in warnings:
        if warning.startswith("missing_") and warning.endswith("_source_type"):
            source_type = warning.removeprefix("missing_").removesuffix("_source_type")
            gaps.append(
                _gap(
                    warning,
                    "source_type_gap",
                    f"Limited {source_type} source-type coverage",
                    f"The diagnostics indicate limited {source_type} source-type evidence in the selected base.",
                    {"source_type": source_type},
                    GapBasis(evidence_ids=selected_ids, coverage_warnings=[warning], diagnostic_refs=["ranking_coverage:source_type_coverage"]),
                    "medium",
                    "high",
                )
            )

    for cluster in clusters:
        cluster_evidence_ids = _dedupe([str(value) for value in cluster.get("evidence_ids") or []])
        if 0 < len(cluster_evidence_ids) <= 1:
            cluster_id = str(cluster.get("cluster_id") or "")
            gaps.append(
                _gap(
                    f"sparse_cluster_{cluster_id}",
                    "coverage_gap",
                    f"Sparse landscape cluster: {cluster.get('title') or cluster_id}",
                    "The landscape cluster is represented by only one evidence card.",
                    dict(cluster.get("axis_values") or {}),
                    GapBasis(
                        landscape_cluster_ids=[cluster_id],
                        evidence_ids=cluster_evidence_ids,
                        diagnostic_refs=["landscape:cluster_evidence_count"],
                    ),
                    "medium",
                    "medium",
                )
            )

    for axis_name in ["material_system", "defect_type", "mechanistic_role", "application_condition"]:
        values = [value for value in axis_values.get(axis_name, []) if value != "unknown"]
        if selected_ids and len(_dedupe(values)) <= 1:
            gaps.append(
                _gap(
                    f"limited_axis_{axis_name}",
                    "comparison_gap",
                    f"Limited comparison coverage for {axis_name.replace('_', ' ')}",
                    f"The selected evidence covers one or fewer observed values for the {axis_name} axis.",
                    {axis_name: _dedupe(values) or ["unknown"]},
                    GapBasis(evidence_ids=selected_ids, diagnostic_refs=[f"axis_coverage:{axis_name}"]),
                    "low",
                    "medium",
                )
            )

    return _dedupe_gaps(gaps)


def _gap(
    suffix: str,
    gap_type: str,
    title: str,
    description: str,
    axis_values: dict[str, Any],
    basis: GapBasis,
    severity: str,
    confidence: str,
) -> GapRecord:
    return GapRecord(
        gap_id=f"gap_{_slug(suffix)}",
        gap_type=gap_type,
        title=title,
        description=description,
        axis_values=axis_values,
        basis=basis,
        severity=severity,
        confidence=confidence,
        not_an_idea=True,
        warnings=[],
    )


def _coverage(
    landscape: dict[str, Any],
    landscape_diagnostics: dict[str, Any],
    cards: list[dict[str, Any]],
    selected_cards: list[dict[str, Any]],
    ranking_diagnostics: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    landscape_coverage = landscape.get("coverage") if isinstance(landscape.get("coverage"), dict) else {}
    landscape_diag_coverage = landscape_diagnostics.get("coverage") if isinstance(landscape_diagnostics.get("coverage"), dict) else {}
    ranking_coverage = ranking_diagnostics.get("coverage") if isinstance(ranking_diagnostics.get("coverage"), dict) else {}
    source_types: dict[str, int] = {}
    roles: dict[str, int] = {}
    papers: set[str] = set()
    for card in cards:
        source_types[_source_type(card)] = source_types.get(_source_type(card), 0) + 1
        role = str(card.get("primary_role") or card.get("role") or "unknown")
        roles[role] = roles.get(role, 0) + 1
    for card in selected_cards:
        if card.get("paper_id"):
            papers.add(str(card["paper_id"]))
    missing_roles = _dedupe(
        list(landscape_coverage.get("missing_roles") or [])
        + list(landscape_diag_coverage.get("missing_roles") or [])
        + list(ranking_coverage.get("missing_required_roles") or ranking_coverage.get("missing_roles") or [])
    )
    coverage_warnings = _dedupe(
        list(landscape_coverage.get("coverage_warnings") or [])
        + list(landscape_diag_coverage.get("coverage_warnings") or [])
        + list(ranking_coverage.get("coverage_warnings") or [])
        + warnings
    )
    dominant_source = (
        bool(landscape_coverage.get("dominant_source_warning"))
        or bool(landscape_diag_coverage.get("dominant_source_warning"))
        or "dominant_paper_warning" in warnings
        or (len(papers) == 1 and len(selected_cards) > 1)
    )
    return {
        "num_landscape_clusters": len(landscape.get("clusters") or []),
        "num_evidence_cards": len(cards),
        "num_selected_evidence": len(selected_cards),
        "num_source_papers": len(papers),
        "source_paper_ids": sorted(papers),
        "source_type_distribution": source_types or dict(landscape_coverage.get("source_type_distribution") or {}),
        "role_distribution": roles or dict(landscape_coverage.get("role_distribution") or {}),
        "axis_coverage": {},
        "missing_roles": missing_roles,
        "dominant_source_warning": dominant_source,
        "coverage_warnings": coverage_warnings,
    }


def _axis_values(landscape: dict[str, Any], selected_cards: list[dict[str, Any]], warnings: list[str]) -> dict[str, list[str]]:
    axis_values: dict[str, list[str]] = {axis: [] for axis in GAP_INITIAL_AXES}
    for axis in landscape.get("landscape_axes") or []:
        if not isinstance(axis, dict):
            continue
        axis_id = axis.get("axis_id")
        values = axis.get("values")
        if axis_id in axis_values and isinstance(values, list):
            axis_values[axis_id].extend(str(value).strip() for value in values if str(value).strip())
    for card in selected_cards:
        evidence_id = _evidence_id(card) or "unknown"
        entities = card.get("entities") if isinstance(card.get("entities"), dict) else {}
        source_type = _source_type(card)
        role = str(card.get("primary_role") or card.get("role") or "unknown")
        card_values = {
            "material_system": _entity_values(entities, "materials"),
            "synthesis_strategy": _entity_values(entities, "methods"),
            "defect_type": _defect_values(card, entities),
            "mechanistic_role": _entity_values(entities, "mechanisms"),
            "performance_metric": _entity_values(entities, "metrics"),
            "characterization_method": _entity_values(entities, "characterization_tools"),
            "application_condition": _entity_values(entities, "conditions"),
            "source_type": [source_type],
            "evidence_role": [role],
        }
        for axis_name, values in card_values.items():
            axis_values[axis_name].extend(values)
            if values == ["unknown"]:
                warnings.append(f"missing_gap_axis_value:{axis_name}:{evidence_id}")
    return {axis: _dedupe(values) or ["unknown"] for axis, values in axis_values.items()}


def _supporting_evidence(selected_cards: list[dict[str, Any]], gaps: list[GapRecord]) -> list[SupportingEvidence]:
    result: list[SupportingEvidence] = []
    for card in selected_cards:
        evidence_id = _evidence_id(card)
        if not evidence_id:
            continue
        gap_ids = [
            gap.gap_id
            for gap in gaps
            if evidence_id in gap.basis.evidence_ids or gap.basis.coverage_warnings or gap.basis.diagnostic_refs
        ]
        if not gap_ids:
            continue
        result.append(
            SupportingEvidence(
                evidence_id=evidence_id,
                paper_id=str(card.get("paper_id") or ""),
                role=str(card.get("primary_role") or card.get("role") or "unknown"),
                source_type=_source_type(card),
                gap_ids=_dedupe(gap_ids),
                reason="Referenced because this evidence contributes to the coverage diagnostics associated with the gap.",
            )
        )
    return result


def _render_gap_markdown(artifact: GapMapArtifact) -> str:
    lines = [
        "# Gap Map",
        "",
        "## Scope",
        "",
        f"Topic: {artifact.topic}",
        "",
        "## Evidence And Landscape Base",
        "",
        f"- Landscape ID: {artifact.landscape_id}",
        f"- Evidence cards: {artifact.coverage.get('num_evidence_cards', 0)}",
        f"- Selected evidence: {artifact.coverage.get('num_selected_evidence', 0)}",
        f"- Source papers: {artifact.coverage.get('num_source_papers', 0)}",
        "",
        "## Gap Axes",
        "",
    ]
    for axis in artifact.gap_axes:
        lines.append(f"- {axis.axis_id}: {axis.source}")
    lines.extend(["", "## Identified Evidence Gaps", ""])
    for gap in artifact.gaps:
        basis = gap.basis.as_dict()
        lines.extend(
            [
                f"### {gap.title}",
                "",
                f"- gap_id: {gap.gap_id}",
                f"- gap_type: {gap.gap_type}",
                f"- description: {gap.description}",
                f"- severity: {gap.severity}",
                f"- confidence: {gap.confidence}",
                f"- basis: {basis}",
                "",
            ]
        )
    lines.extend(["## Coverage Diagnostics", ""])
    for key, value in artifact.coverage.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Limitations", ""])
    for limitation in artifact.limitations:
        lines.append(f"- {limitation}")
    if artifact.warnings:
        lines.append(f"- Warnings: {', '.join(artifact.warnings)}")
    lines.extend(["", "## Evidence References", ""])
    cluster_refs = _dedupe([cluster_id for gap in artifact.gaps for cluster_id in gap.basis.landscape_cluster_ids])
    if cluster_refs:
        for cluster_id in cluster_refs:
            lines.append(f"- landscape_cluster_id={cluster_id}")
    for item in artifact.supporting_evidence:
        lines.append(
            f"- evidence_id={item.evidence_id}; paper_id={item.paper_id}; role={item.role}; "
            f"source_type={item.source_type}; gap_ids={', '.join(item.gap_ids)}"
        )
    diagnostic_refs = _dedupe([ref for gap in artifact.gaps for ref in gap.basis.diagnostic_refs])
    for ref in diagnostic_refs:
        lines.append(f"- diagnostic reference={ref}")
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


def _collect_warnings(*payloads: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for payload in payloads:
        warnings.extend(str(warning) for warning in payload.get("warnings") or [] if str(warning))
        coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        warnings.extend(str(warning) for warning in coverage.get("coverage_warnings") or [] if str(warning))
    return _dedupe(warnings)


def _entity_values(entities: dict[str, Any], field: str) -> list[str]:
    values = entities.get(field)
    if isinstance(values, list):
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        return _dedupe(cleaned) or ["unknown"]
    return ["unknown"]


def _defect_values(card: dict[str, Any], entities: dict[str, Any]) -> list[str]:
    statement = str(card.get("normalized_statement") or card.get("verbatim_snippet") or "").lower()
    if "oxygen vacancy" in statement or "oxygen vacancies" in statement:
        return ["oxygen vacancy"]
    if "vacancy" in statement or "vacancies" in statement:
        return ["vacancy"]
    values = _entity_values(entities, "mechanisms")
    defects = [value for value in values if "defect" in value.lower() or "vacanc" in value.lower()]
    return defects or ["unknown"]


def _source_type(card: dict[str, Any]) -> str:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    return str(source.get("asset_type") or card.get("source_type") or card.get("asset_type") or "text")


def _evidence_id(card: dict[str, Any]) -> str:
    return str(card.get("evidence_id") or "").strip()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "unknown"


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_gaps(gaps: list[GapRecord]) -> list[GapRecord]:
    result: list[GapRecord] = []
    seen: set[str] = set()
    for gap in gaps:
        if gap.gap_id in seen:
            continue
        seen.add(gap.gap_id)
        result.append(gap)
    return result


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
    "map_gaps",
    "validate_gap_map_artifact",
]
