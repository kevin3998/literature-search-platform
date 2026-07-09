from pathlib import Path

import pytest

from modules.evidence_workflow.schemas import EVIDENCE_ROLES
from modules.evidence_workflow.task_profiles import (
    DEFAULT_TASK_PROFILE_ID,
    build_scope_lock,
    get_task_profile,
    list_task_profiles,
    resolve_task_profile,
)


DOMAIN_PROFILE_TERMS = {
    "HER",
    "membrane",
    "electrolyte",
    "TCO",
    "alloy",
    "catalyst",
    "thermoelectric",
    "perovskite",
}


def test_topic_to_report_is_only_runnable_task_profile() -> None:
    profiles = list_task_profiles(include_stubs=True)
    by_id = {profile["profile_id"]: profile for profile in profiles}

    assert DEFAULT_TASK_PROFILE_ID == "topic-to-report"
    assert by_id["topic-to-report"]["runnable"] is True
    assert by_id["topic-to-report"]["status"] == "active"
    assert by_id["topic-to-report"]["required_evidence_roles"] == [
        "background",
        "material_system",
        "method",
        "property",
        "performance",
        "mechanism",
        "comparison",
        "limitation",
        "condition",
        "figure_evidence",
        "table_evidence",
    ]
    assert {profile["profile_id"] for profile in profiles if profile["runnable"]} == {"topic-to-report"}


def test_stub_profiles_are_defined_but_not_runnable() -> None:
    profiles = {profile["profile_id"]: profile for profile in list_task_profiles(include_stubs=True)}

    for profile_id in ["literature-landscape", "experiment-plan", "manuscript-writing"]:
        assert profiles[profile_id]["runnable"] is False
        assert profiles[profile_id]["status"] == "stub"
        assert profiles[profile_id]["stub_reason"]

    assert [profile["profile_id"] for profile in list_task_profiles(include_stubs=False)] == ["topic-to-report"]


def test_resolve_task_profile_defaults_and_rejects_stubs() -> None:
    assert resolve_task_profile(None).profile_id == "topic-to-report"
    assert resolve_task_profile("topic-to-report").runnable is True
    assert get_task_profile("missing-profile") is None

    with pytest.raises(ValueError, match="not runnable"):
        resolve_task_profile("experiment-plan")
    with pytest.raises(ValueError, match="unknown task profile"):
        resolve_task_profile("missing-profile")


def test_all_task_profile_roles_are_general_evidence_roles() -> None:
    for profile in list_task_profiles(include_stubs=True):
        roles = set(profile["required_evidence_roles"]) | set(profile["optional_evidence_roles"])
        assert roles <= EVIDENCE_ROLES


def test_task_profile_registry_avoids_domain_profile_terms() -> None:
    source = Path("backend/modules/evidence_workflow/task_profiles.py").read_text(encoding="utf-8")
    lowered = source.lower()

    for term in DOMAIN_PROFILE_TERMS:
        assert term.lower() not in lowered


def test_build_scope_lock_preserves_topic_scope_options_and_timestamp() -> None:
    lock = build_scope_lock(
        topic="solid-state battery interfaces",
        scope="library",
        scope_options={"year_from": 2020, "journal": ["Nature Energy"]},
        task_profile_id="topic-to-report",
        created_at=123.45,
    )

    assert lock == {
        "topic": "solid-state battery interfaces",
        "scope": "library",
        "scope_options": {"year_from": 2020, "journal": ["Nature Energy"]},
        "task_profile_id": "topic-to-report",
        "locked_at": 123.45,
    }
