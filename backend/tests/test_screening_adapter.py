from copy import deepcopy

from screening_v2_helpers import valid_screening_v2_artifact

from modules.research_agent_controller.skills.screening_adapter import (
    normalize_screening_for_downstream,
    validate_screening_v2_for_downstream,
)


def test_valid_v2_screening_normalizes_to_conservative_downstream_statuses() -> None:
    screening = valid_screening_v2_artifact()

    errors = validate_screening_v2_for_downstream(screening)
    normalized = normalize_screening_for_downstream(screening)

    assert errors == []
    assert normalized["schema_version"] == "normalized_screening_for_downstream_v1"
    assert normalized["source_schema_version"] == "idea_screening_v2"
    assert normalized["screening_id"] == screening["screening_id"]
    idea = normalized["screened_ideas"][0]
    assert idea["idea_id"] == "idea_gap_comparison_001"
    assert idea["novelty_status"] == "requires_external_search"
    assert idea["feasibility_status"] == "requires_expert_review"
    assert idea["risk_status"] == "requires_risk_review"
    assert idea["required_follow_up"] == ["external novelty search", "expert feasibility review", "risk review"]
    assert "Only local evidence artifacts were considered." in idea["limitations"]
    assert idea["triage_summary"] == {
        "local_novelty_judgment": "partial_overlap_with_local_evidence",
        "feasibility_judgment": "partially_supported",
        "risk_judgment": "evidence_gap_risk",
        "overall_judgment": "advance_to_external_novelty_search",
    }
    assert idea["not_an_experiment_plan"] is True
    assert idea["not_a_validated_claim"] is True


def test_v1_screening_is_rejected() -> None:
    screening = valid_screening_v2_artifact()
    screening["schema_version"] = "idea_screening_v1"

    errors = validate_screening_v2_for_downstream(screening)

    assert "invalid_screening_schema_version" in errors


def test_missing_analysis_mode_is_rejected() -> None:
    screening = valid_screening_v2_artifact()
    screening.pop("analysis_mode")

    errors = validate_screening_v2_for_downstream(screening)

    assert "invalid_screening_analysis_mode" in errors


def test_external_search_performed_or_status_not_performed_is_rejected() -> None:
    screening = valid_screening_v2_artifact()
    screening["llm_provenance"]["external_novelty_search_performed"] = True
    screening["screened_ideas"][0]["external_novelty_search"]["status"] = "performed"

    errors = validate_screening_v2_for_downstream(screening)

    assert "external_novelty_search_must_not_be_performed" in errors
    assert "external_novelty_search_status_must_be_not_performed:0" in errors


def test_missing_gap_or_evidence_basis_is_rejected() -> None:
    screening = valid_screening_v2_artifact()
    screening["screened_ideas"][0]["gap_ids"] = []
    screening["screened_ideas"][0]["evidence_ids"] = []

    errors = validate_screening_v2_for_downstream(screening)

    assert "screened_idea_requires_gap_ids:0" in errors
    assert "screened_idea_requires_evidence_ids:0" in errors


def test_boundary_flags_not_true_are_rejected() -> None:
    screening = valid_screening_v2_artifact()
    screening["screened_ideas"][0]["not_an_experiment_plan"] = False
    screening["screened_ideas"][0]["not_a_validated_claim"] = False

    errors = validate_screening_v2_for_downstream(screening)

    assert "screening_must_not_be_experiment_plan:0" in errors
    assert "screening_must_not_be_validated_claim:0" in errors


def test_normalization_does_not_mutate_source_screening() -> None:
    screening = valid_screening_v2_artifact()
    original = deepcopy(screening)

    normalize_screening_for_downstream(screening)

    assert screening == original
