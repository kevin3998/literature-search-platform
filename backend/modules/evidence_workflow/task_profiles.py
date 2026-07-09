"""Static Task Profile registry for evidence workflow inputs."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .schemas import EVIDENCE_ROLES

DEFAULT_TASK_PROFILE_ID = "topic-to-report"


@dataclass
class TaskProfile:
    profile_id: str
    name: str
    goal: str
    runnable: bool
    status: str
    required_evidence_roles: list[str] = field(default_factory=list)
    optional_evidence_roles: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    artifact_sequence: list[str] = field(default_factory=list)
    audit_rules: list[str] = field(default_factory=list)
    stub_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_TOPIC_TO_REPORT = TaskProfile(
    profile_id=DEFAULT_TASK_PROFILE_ID,
    name="Topic-to-Report",
    goal="Produce a traceable research report from a scoped topic.",
    runnable=True,
    status="active",
    required_evidence_roles=[
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
    ],
    optional_evidence_roles=[
        "structure",
        "characterization",
        "calculation",
        "hypothesis",
    ],
    input_schema={
        "required": ["topic"],
        "optional": ["scope", "scope_options", "retrieval_budget"],
    },
    artifact_sequence=[
        "source_candidates",
        "evidence_cards",
        "minimal_topic_to_evidence_report",
        "landscape",
        "gaps",
        "ideas",
        "screening",
        "report",
    ],
    audit_rules=[
        "every_report_claim_requires_evidence_cards",
        "every_gap_requires_evidence_or_missing_evidence",
        "every_idea_requires_gap_and_supporting_evidence",
        "unsupported_assumptions_must_be_listed",
    ],
)


_STUB_PROFILES = [
    TaskProfile(
        profile_id="literature-landscape",
        name="Literature Landscape",
        goal="Map a research area without creating ideas or reports.",
        runnable=False,
        status="stub",
        required_evidence_roles=["background", "material_system", "method", "property", "comparison"],
        optional_evidence_roles=["mechanism", "limitation", "condition", "figure_evidence", "table_evidence"],
        input_schema={"required": ["topic"], "optional": ["scope", "scope_options"]},
        artifact_sequence=["source_candidates", "evidence_cards", "landscape"],
        audit_rules=["landscape_units_require_evidence_cards"],
        stub_reason="Landscape aggregation is not implemented yet.",
    ),
    TaskProfile(
        profile_id="experiment-plan",
        name="Experiment Plan",
        goal="Convert supported research directions into a reviewable planning matrix.",
        runnable=False,
        status="stub",
        required_evidence_roles=["method", "condition", "performance", "limitation", "comparison"],
        optional_evidence_roles=["material_system", "characterization", "mechanism"],
        input_schema={"required": ["topic"], "optional": ["scope", "scope_options", "idea_id"]},
        artifact_sequence=["evidence_cards", "screening", "planning_matrix"],
        audit_rules=["planning_recommendations_require_supporting_evidence"],
        stub_reason="Planning matrix generation is not implemented yet.",
    ),
    TaskProfile(
        profile_id="manuscript-writing",
        name="Manuscript Writing",
        goal="Draft manuscript sections from verified claim records.",
        runnable=False,
        status="stub",
        required_evidence_roles=["background", "method", "property", "performance", "comparison", "limitation"],
        optional_evidence_roles=["mechanism", "figure_evidence", "table_evidence"],
        input_schema={"required": ["topic"], "optional": ["scope", "scope_options", "claim_record_id"]},
        artifact_sequence=["evidence_cards", "claim_records", "section_outline", "draft"],
        audit_rules=["draft_paragraphs_require_verified_claim_records"],
        stub_reason="Claim-record writing flow is not implemented yet.",
    ),
]

_PROFILES = [_TOPIC_TO_REPORT, *_STUB_PROFILES]
_BY_ID = {profile.profile_id: profile for profile in _PROFILES}


def list_task_profiles(include_stubs: bool = True) -> list[dict[str, Any]]:
    profiles = _PROFILES if include_stubs else [profile for profile in _PROFILES if profile.runnable]
    return [profile.as_dict() for profile in profiles]


def get_task_profile(profile_id: str) -> TaskProfile | None:
    return _BY_ID.get(profile_id)


def resolve_task_profile(profile_id: str | None, *, require_runnable: bool = True) -> TaskProfile:
    resolved_id = profile_id or DEFAULT_TASK_PROFILE_ID
    profile = get_task_profile(resolved_id)
    if profile is None:
        raise ValueError(f"unknown task profile: {resolved_id}")
    if require_runnable and not profile.runnable:
        raise ValueError(f"task profile is not runnable: {resolved_id}")
    _validate_profile_roles(profile)
    return profile


def build_scope_lock(
    topic: str | None,
    scope: str,
    scope_options: dict[str, Any] | None,
    task_profile_id: str,
    created_at: float,
) -> dict[str, Any]:
    return {
        "topic": topic,
        "scope": scope,
        "scope_options": dict(scope_options or {}),
        "task_profile_id": task_profile_id,
        "locked_at": created_at,
    }


def _validate_profile_roles(profile: TaskProfile) -> None:
    roles = [*profile.required_evidence_roles, *profile.optional_evidence_roles]
    invalid = [role for role in roles if role not in EVIDENCE_ROLES]
    if invalid:
        raise ValueError(f"task profile has invalid evidence roles: {', '.join(invalid)}")


__all__ = [
    "DEFAULT_TASK_PROFILE_ID",
    "TaskProfile",
    "build_scope_lock",
    "get_task_profile",
    "list_task_profiles",
    "resolve_task_profile",
]
