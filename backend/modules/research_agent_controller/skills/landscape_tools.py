"""Deterministic P2-M8 landscape skill wrapper.

The wrapper aggregates validated evidence artifacts into a conservative
landscape artifact. It does not call LLMs, retrieval services, controllers, or
databases.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from modules.research_workspace import ResearchWorkspaceStore

from ..skill_registry import SkillExecutionInput, SkillExecutionResult, SkillExecutionStatus
from .landscape_contract import (
    LANDSCAPE_ALLOWED_MARKDOWN_SECTIONS,
    LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS,
    LANDSCAPE_OUTPUT_ARTIFACTS,
    LANDSCAPE_REQUIRED_INPUT_ARTIFACTS,
    LANDSCAPE_SCHEMA_VERSION,
    LandscapeArtifact,
    LandscapeAxis,
    LandscapeCluster,
    RepresentativeEvidence,
    validate_landscape_input_artifacts,
)


def build_landscape(execution: SkillExecutionInput, **_: Any) -> SkillExecutionResult:
    input_artifacts = list(execution.input_artifacts or LANDSCAPE_REQUIRED_INPUT_ARTIFACTS)
    input_errors = validate_landscape_input_artifacts(input_artifacts)
    raw_errors = [error for error in input_errors if "not_allowed_for_landscape" in error]
    if raw_errors:
        return _result(execution, SkillExecutionStatus.VALIDATION_FAILED, errors=raw_errors)

    missing = [path for path in LANDSCAPE_REQUIRED_INPUT_ARTIFACTS if not _path(execution, path).exists()]
    if missing:
        return _result(
            execution,
            SkillExecutionStatus.BLOCKED,
            input_artifacts=LANDSCAPE_REQUIRED_INPUT_ARTIFACTS,
            errors=[f"missing_input_artifact:{path}" for path in missing],
        )

    enriched = _read_json(execution, "evidence/evidence_cards.enriched.json")
    selection = _read_json(execution, "ranked_evidence/evidence_selection.json")
    diagnostics = _read_json(execution, "ranked_evidence/coverage_diagnostics.json")
    topic = str(execution.parameters.get("topic") or enriched.get("topic") or "").strip()
    if not topic:
        topic = "unspecified topic"

    cards = _cards_from_payload(enriched)
    selected_cards = _selected_cards(selection, cards)
    landscape = _build_landscape_artifact(
        execution.task_id,
        topic,
        cards,
        selected_cards,
        selection,
        diagnostics,
        input_artifacts,
    )
    markdown = _render_landscape_markdown(landscape)
    validation_errors = validate_landscape_artifact(landscape.as_dict(), markdown)
    if validation_errors:
        return _result(
            execution,
            SkillExecutionStatus.VALIDATION_FAILED,
            input_artifacts=input_artifacts,
            errors=validation_errors,
            warnings=landscape.warnings,
        )

    coverage_payload = {
        "artifact_type": "landscape_coverage_diagnostics",
        "task_id": execution.task_id,
        "landscape_id": landscape.landscape_id,
        "coverage": landscape.coverage,
        "warnings": list(landscape.warnings),
        "created_at": time.time(),
        "schema_version": LANDSCAPE_SCHEMA_VERSION,
    }
    _write_json(execution, "landscape/literature_landscape.json", landscape.as_dict())
    _write_text(execution, "landscape/literature_landscape.md", markdown)
    _write_json(execution, "landscape/landscape_coverage_diagnostics.json", coverage_payload)
    return _result(
        execution,
        SkillExecutionStatus.SUCCESS,
        input_artifacts=LANDSCAPE_REQUIRED_INPUT_ARTIFACTS,
        output_artifacts=LANDSCAPE_OUTPUT_ARTIFACTS,
        warnings=landscape.warnings,
        metadata={
            "evidence_count": len(landscape.evidence_ids),
            "cluster_count": len(landscape.clusters),
            "source_paper_count": len(landscape.source_paper_ids),
        },
    )


def validate_landscape_artifact(landscape: dict[str, Any], markdown: str) -> list[str]:
    errors: list[str] = []
    if landscape.get("schema_version") != LANDSCAPE_SCHEMA_VERSION:
        errors.append("invalid_landscape_schema_version")
    if not landscape.get("landscape_id"):
        errors.append("missing_landscape_id")
    for index, cluster in enumerate(landscape.get("clusters") or []):
        if not cluster.get("evidence_ids"):
            errors.append(f"cluster_missing_evidence_ids:{index}")
        for claim_index, claim in enumerate(cluster.get("representative_claims") or []):
            if not claim.get("evidence_ids"):
                errors.append(f"representative_claim_missing_evidence_ids:{index}:{claim_index}")
    if "## Evidence References" not in markdown:
        errors.append("markdown_missing_evidence_references")
    for section in LANDSCAPE_FORBIDDEN_MARKDOWN_SECTIONS:
        if f"## {section}" in markdown:
            errors.append(f"forbidden_landscape_markdown_section:{section}")
    return errors


def _build_landscape_artifact(
    task_id: str,
    topic: str,
    cards: list[dict[str, Any]],
    selected_cards: list[dict[str, Any]],
    selection: dict[str, Any],
    diagnostics: dict[str, Any],
    input_artifacts: list[str],
) -> LandscapeArtifact:
    evidence_base = selected_cards or cards
    warnings = _dedupe(list(diagnostics.get("warnings") or []) + list(selection.get("warnings") or []))
    axes_values: dict[str, list[str]] = {
        "material_system": [],
        "synthesis_strategy": [],
        "defect_type": [],
        "mechanistic_role": [],
        "performance_metric": [],
        "characterization_method": [],
        "application_condition": [],
    }
    clusters_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    representatives: list[RepresentativeEvidence] = []

    for card in evidence_base:
        evidence_id = str(card.get("evidence_id") or "").strip()
        if not evidence_id:
            warnings.append("missing_evidence_id_in_landscape_input")
            continue
        paper_id = str(card.get("paper_id") or card.get("source_evidence_id") or "").strip()
        entities = card.get("entities") if isinstance(card.get("entities"), dict) else {}
        statement = str(card.get("normalized_statement") or card.get("verbatim_snippet") or "").strip()
        axis_map = _axis_values(card, entities, statement, warnings)
        for axis_name, values in axis_map.items():
            axes_values[axis_name].extend(values)
            if values == ["unknown"]:
                warnings.append(f"missing_axis_value:{axis_name}:{evidence_id}")

        role = str(card.get("primary_role") or card.get("role") or "unknown_role")
        material = _first_known(axis_map["material_system"], "unknown_material")
        defect = _first_known(axis_map["defect_type"], "unknown_defect")
        cluster_key = (role or "unknown_role", material, defect)
        cluster = clusters_by_key.setdefault(
            cluster_key,
            {
                "cluster_id": f"cluster_{_slug(role)}_{_slug(material)}_{_slug(defect)}",
                "title": _cluster_title(role, material, defect),
                "description": "Deterministic grouping by role, material system, and defect type.",
                "axis_values": {
                    "primary_role": role or "unknown_role",
                    "material_system": material,
                    "defect_type": defect,
                },
                "evidence_ids": [],
                "source_paper_ids": [],
                "representative_claims": [],
                "confidence": "low",
                "warnings": [],
            },
        )
        cluster["evidence_ids"].append(evidence_id)
        if paper_id:
            cluster["source_paper_ids"].append(paper_id)
        if statement:
            cluster["representative_claims"].append({"claim": statement, "evidence_ids": [evidence_id]})
        else:
            cluster["warnings"].append(f"missing_representative_statement:{evidence_id}")
            warnings.append(f"missing_representative_statement:{evidence_id}")
        representatives.append(
            RepresentativeEvidence(
                evidence_id=evidence_id,
                paper_id=paper_id,
                role=role,
                source_type=_source_type(card),
                source_path=_source_path(card),
                cluster_ids=[cluster["cluster_id"]],
                reason="Selected as representative evidence in ranked evidence selection.",
            )
        )

    clusters = [_cluster_from_data(item) for item in clusters_by_key.values() if item["evidence_ids"]]
    for cluster in clusters:
        if len(cluster.evidence_ids) >= 3:
            cluster.confidence = "high"
        elif len(cluster.evidence_ids) >= 1:
            cluster.confidence = "medium"

    source_paper_ids = _dedupe([str(card.get("paper_id") or "") for card in evidence_base])
    evidence_ids = _dedupe([str(card.get("evidence_id") or "") for card in evidence_base])
    coverage = _coverage(cards, selected_cards, diagnostics, warnings)
    axes = [
        LandscapeAxis(
            axis_id=axis_id,
            name=axis_id.replace("_", " ").title(),
            description=f"Landscape organization dimension: {axis_id}.",
            values=_dedupe(values) or ["unknown"],
        )
        for axis_id, values in axes_values.items()
    ]

    return LandscapeArtifact(
        task_id=task_id,
        topic=topic,
        landscape_id=f"landscape_{task_id}",
        input_artifacts=input_artifacts,
        evidence_ids=evidence_ids,
        source_paper_ids=source_paper_ids,
        landscape_axes=axes,
        clusters=clusters,
        coverage=coverage,
        representative_evidence=representatives,
        limitations=[
            "Landscape is generated by deterministic grouping over available Evidence Cards.",
            "Missing axis values are marked as unknown rather than inferred.",
        ],
        warnings=_dedupe(warnings),
    )


def _axis_values(
    card: dict[str, Any],
    entities: dict[str, Any],
    statement: str,
    warnings: list[str],
) -> dict[str, list[str]]:
    return {
        "material_system": _entity_values(entities, "materials"),
        "synthesis_strategy": _entity_values(entities, "methods"),
        "defect_type": _defect_values(statement, entities),
        "mechanistic_role": _entity_values(entities, "mechanisms"),
        "performance_metric": _entity_values(entities, "metrics"),
        "characterization_method": _entity_values(entities, "characterization_tools"),
        "application_condition": _entity_values(entities, "conditions"),
    }


def _coverage(
    cards: list[dict[str, Any]],
    selected_cards: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    diagnostic_coverage = diagnostics.get("coverage") if isinstance(diagnostics.get("coverage"), dict) else {}
    source_types: dict[str, int] = {}
    roles: dict[str, int] = {}
    papers: set[str] = set()
    for card in cards:
        source_types[_source_type(card)] = source_types.get(_source_type(card), 0) + 1
        role = str(card.get("primary_role") or card.get("role") or "unknown")
        roles[role] = roles.get(role, 0) + 1
        if card.get("paper_id"):
            papers.add(str(card["paper_id"]))
    coverage_warnings = _dedupe(list(diagnostic_coverage.get("coverage_warnings") or []) + warnings)
    return {
        "num_evidence_cards": len(cards),
        "num_selected_evidence": len(selected_cards),
        "num_source_papers": len(papers),
        "source_type_distribution": source_types,
        "role_distribution": roles,
        "missing_roles": list(diagnostic_coverage.get("missing_required_roles") or diagnostic_coverage.get("missing_roles") or []),
        "dominant_source_warning": "dominant_paper_warning" in warnings,
        "coverage_warnings": coverage_warnings,
    }


def _render_landscape_markdown(artifact: LandscapeArtifact) -> str:
    lines = [
        "# Literature Landscape",
        "",
        "## Scope",
        "",
        f"Topic: {artifact.topic}",
        "",
        "## Evidence Base",
        "",
        f"- Evidence cards: {artifact.coverage.get('num_evidence_cards', 0)}",
        f"- Selected evidence: {artifact.coverage.get('num_selected_evidence', 0)}",
        f"- Source papers: {artifact.coverage.get('num_source_papers', 0)}",
        "",
        "## Landscape Axes",
        "",
    ]
    for axis in artifact.landscape_axes:
        lines.append(f"- {axis.name}: {', '.join(axis.values)}")
    lines.extend(["", "## Main Evidence Clusters", ""])
    for cluster in artifact.clusters:
        claims = "; ".join(claim.get("claim", "") for claim in cluster.representative_claims[:2] if claim.get("claim"))
        lines.extend(
            [
                f"### {cluster.title}",
                "",
                f"- Evidence IDs: {', '.join(cluster.evidence_ids)}",
                f"- Source papers: {', '.join(cluster.source_paper_ids) if cluster.source_paper_ids else 'unknown'}",
                f"- Confidence: {cluster.confidence}",
                f"- Representative claims: {claims if claims else 'No representative statement available.'}",
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
    for item in artifact.representative_evidence:
        lines.append(
            f"- evidence_id={item.evidence_id}; paper_id={item.paper_id}; role={item.role}; "
            f"source_type={item.source_type}; source_path={item.source_path}; clusters={', '.join(item.cluster_ids)}"
        )
    return "\n".join(lines).strip() + "\n"


def _cluster_from_data(data: dict[str, Any]) -> LandscapeCluster:
    data["evidence_ids"] = _dedupe(data["evidence_ids"])
    data["source_paper_ids"] = _dedupe(data["source_paper_ids"])
    data["representative_claims"] = _dedupe_claims(data["representative_claims"])
    data["warnings"] = _dedupe(data["warnings"])
    return LandscapeCluster(**data)


def _selected_cards(selection: dict[str, Any], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    card_by_id = {card.get("evidence_id"): card for card in cards}
    selected: list[dict[str, Any]] = []
    for item in selection.get("selected_cards") or []:
        if not isinstance(item, dict):
            continue
        evidence_id = item.get("evidence_id")
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


def _entity_values(entities: dict[str, Any], field: str) -> list[str]:
    values = entities.get(field)
    if isinstance(values, list):
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        return _dedupe(cleaned) or ["unknown"]
    return ["unknown"]


def _defect_values(statement: str, entities: dict[str, Any]) -> list[str]:
    text = statement.lower()
    if "oxygen vacancy" in text or "oxygen vacancies" in text:
        return ["oxygen vacancy"]
    if "vacancy" in text or "vacancies" in text:
        return ["vacancy"]
    values = _entity_values(entities, "mechanisms")
    defects = [value for value in values if "defect" in value.lower() or "vacanc" in value.lower()]
    return defects or ["unknown"]


def _source_type(card: dict[str, Any]) -> str:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    return str(source.get("asset_type") or card.get("source_type") or card.get("asset_type") or "text")


def _source_path(card: dict[str, Any]) -> str:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    return str(source.get("source_path") or card.get("source_path") or "")


def _first_known(values: list[str], default: str) -> str:
    return next((value for value in values if value and value != "unknown"), default)


def _cluster_title(role: str, material: str, defect: str) -> str:
    return f"{role or 'unknown role'} / {material} / {defect}".replace("_", " ").title()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return slug or "unknown"


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


def _dedupe_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    result: list[dict[str, Any]] = []
    for claim in claims:
        key = (str(claim.get("claim") or ""), tuple(claim.get("evidence_ids") or []))
        if key in seen:
            continue
        seen.add(key)
        result.append(claim)
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
    "build_landscape",
    "validate_landscape_artifact",
]
