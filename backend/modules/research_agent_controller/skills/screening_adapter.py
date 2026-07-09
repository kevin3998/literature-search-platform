"""Normalize P2-M11 screening v2 artifacts for downstream deterministic skills."""
from __future__ import annotations

from typing import Any

SUPPORTED_SCREENING_SCHEMA_VERSION = "idea_screening_v2"
NORMALIZED_SCREENING_SCHEMA_VERSION = "normalized_screening_for_downstream_v1"
SUPPORTED_ANALYSIS_MODE = "llm_assisted_local_evidence_triage"


def validate_screening_v2_for_downstream(screening: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if screening.get("schema_version") != SUPPORTED_SCREENING_SCHEMA_VERSION:
        errors.append("invalid_screening_schema_version")
    if screening.get("analysis_mode") != SUPPORTED_ANALYSIS_MODE:
        errors.append("invalid_screening_analysis_mode")
    provenance = screening.get("llm_provenance") if isinstance(screening.get("llm_provenance"), dict) else {}
    if provenance.get("external_novelty_search_performed") is not False:
        errors.append("external_novelty_search_must_not_be_performed")
    for field in ("screening_id", "idea_set_id", "gap_map_id", "landscape_id"):
        if not screening.get(field):
            errors.append(f"missing_{field}")
    if not screening.get("evidence_ids"):
        errors.append("screening_requires_evidence_references")

    screened_ideas = [idea for idea in screening.get("screened_ideas") or [] if isinstance(idea, dict)]
    if not screened_ideas:
        errors.append("screening_requires_screened_ideas")
    for index, idea in enumerate(screened_ideas):
        if not idea.get("idea_id"):
            errors.append(f"screened_idea_requires_source_idea_id:{index}")
        if not idea.get("gap_ids"):
            errors.append(f"screened_idea_requires_gap_ids:{index}")
        if not idea.get("evidence_ids"):
            errors.append(f"screened_idea_requires_evidence_ids:{index}")
        novelty = idea.get("local_novelty_triage") if isinstance(idea.get("local_novelty_triage"), dict) else {}
        external = idea.get("external_novelty_search") if isinstance(idea.get("external_novelty_search"), dict) else {}
        feasibility = idea.get("feasibility_triage") if isinstance(idea.get("feasibility_triage"), dict) else {}
        risk = idea.get("risk_triage") if isinstance(idea.get("risk_triage"), dict) else {}
        overall = idea.get("overall_triage") if isinstance(idea.get("overall_triage"), dict) else {}
        if not novelty.get("judgment"):
            errors.append(f"local_novelty_triage_requires_judgment:{index}")
        if external.get("status") != "not_performed":
            errors.append(f"external_novelty_search_status_must_be_not_performed:{index}")
        if external.get("required") is not True:
            errors.append(f"external_novelty_search_required_must_be_true:{index}")
        if not feasibility.get("judgment"):
            errors.append(f"feasibility_triage_requires_judgment:{index}")
        if not risk.get("judgment"):
            errors.append(f"risk_triage_requires_judgment:{index}")
        if not overall.get("judgment"):
            errors.append(f"overall_triage_requires_judgment:{index}")
        if idea.get("not_an_experiment_plan") is not True:
            errors.append(f"screening_must_not_be_experiment_plan:{index}")
        if idea.get("not_a_validated_claim") is not True:
            errors.append(f"screening_must_not_be_validated_claim:{index}")
    return _dedupe(errors)


def normalize_screening_for_downstream(screening: dict[str, Any]) -> dict[str, Any]:
    errors = validate_screening_v2_for_downstream(screening)
    if errors:
        raise ValueError(",".join(errors))
    return {
        "schema_version": NORMALIZED_SCREENING_SCHEMA_VERSION,
        "source_schema_version": SUPPORTED_SCREENING_SCHEMA_VERSION,
        "screening_id": str(screening.get("screening_id") or ""),
        "idea_set_id": str(screening.get("idea_set_id") or ""),
        "gap_map_id": str(screening.get("gap_map_id") or ""),
        "landscape_id": str(screening.get("landscape_id") or ""),
        "evidence_ids": _string_list(screening.get("evidence_ids")),
        "source_paper_ids": _string_list(screening.get("source_paper_ids")),
        "screened_ideas": [
            normalize_screened_idea_for_downstream(idea)
            for idea in screening.get("screened_ideas") or []
            if isinstance(idea, dict)
        ],
        "warnings": _string_list(screening.get("warnings")),
        "limitations": _string_list(screening.get("limitations")),
    }


def normalize_screened_idea_for_downstream(idea: dict[str, Any]) -> dict[str, Any]:
    novelty = idea.get("local_novelty_triage") if isinstance(idea.get("local_novelty_triage"), dict) else {}
    feasibility = idea.get("feasibility_triage") if isinstance(idea.get("feasibility_triage"), dict) else {}
    risk = idea.get("risk_triage") if isinstance(idea.get("risk_triage"), dict) else {}
    overall = idea.get("overall_triage") if isinstance(idea.get("overall_triage"), dict) else {}
    limitations = _dedupe(
        _string_list(novelty.get("limitations"))
        + _string_list(feasibility.get("missing_requirements"))
        + _string_list(feasibility.get("constraints"))
        + _string_list(risk.get("risk_factors"))
    )
    return {
        "idea_id": str(idea.get("idea_id") or ""),
        "source_idea_title": str(idea.get("source_idea_title") or ""),
        "gap_ids": _string_list(idea.get("gap_ids")),
        "evidence_ids": _string_list(idea.get("evidence_ids")),
        "novelty_status": "requires_external_search",
        "feasibility_status": "requires_expert_review",
        "risk_status": "requires_risk_review",
        "required_follow_up": _string_list(overall.get("required_follow_up")),
        "limitations": limitations,
        "warnings": _string_list(idea.get("warnings")),
        "triage_summary": {
            "local_novelty_judgment": str(novelty.get("judgment") or ""),
            "feasibility_judgment": str(feasibility.get("judgment") or ""),
            "risk_judgment": str(risk.get("judgment") or ""),
            "overall_judgment": str(overall.get("judgment") or ""),
        },
        "not_an_experiment_plan": True,
        "not_a_validated_claim": True,
    }


def _string_list(values: Any) -> list[str]:
    return [str(value) for value in values or [] if str(value)]


def _dedupe(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "NORMALIZED_SCREENING_SCHEMA_VERSION",
    "SUPPORTED_SCREENING_SCHEMA_VERSION",
    "normalize_screened_idea_for_downstream",
    "normalize_screening_for_downstream",
    "validate_screening_v2_for_downstream",
]
