from pathlib import Path

from modules.research_agent_controller.plan_templates import (
    build_explicit_claim_ledger_plan,
    build_explicit_experiment_matrix_plan,
    build_explicit_gap_mapping_plan,
    build_explicit_idea_generation_plan,
    build_explicit_landscape_plan,
    build_explicit_manuscript_scaffold_plan,
    build_explicit_screening_plan,
    build_minimal_topic_to_evidence_plan,
)
from modules.workflow.templates import get_template, list_templates


TASK_ID = "workflow_profile_boundary_task"
TOPIC = "oxygen vacancy engineering for alkaline HER catalysts"


def _skill_names(plan) -> list[str]:
    return [step.skill_name for step in plan.steps]


def test_workflow_profile_boundary_doc_declares_chat_workflow_runtime_semantics() -> None:
    text = Path("docs/workflow_profile_boundary.md").read_text(encoding="utf-8")

    required_phrases = [
        "Chat Layer vs Workflow Layer vs Agent Runtime Layer",
        "literature-research-agent Responsibility",
        "Explicit Invocation Rule",
        "Default Chat Boundary",
        "No Auto-Advance Rule",
        "Skill wrapper availability does not imply ordinary chat availability",
        "workflow_manuscript_scaffold",
        "workflow_full_research_discovery",
        "ordinary chat must not default to this workflow",
        "available through explicit manuscript scaffold workflow",
        "available only as explicit workflow, not default chat behavior",
    ]
    for phrase in required_phrases:
        assert phrase in text


def test_controller_plan_templates_stop_at_their_explicit_terminal_step() -> None:
    profiles = [
        (
            "workflow_minimal_report",
            build_minimal_topic_to_evidence_plan(TASK_ID, TOPIC),
            "build_minimal_topic_to_evidence_report",
            [
                "build_landscape",
                "map_gaps",
                "generate_candidate_ideas",
                "screen_novelty_feasibility_risk",
                "create_experiment_matrix",
                "build_claim_ledger",
                "draft_manuscript_section",
            ],
        ),
        (
            "workflow_literature_landscape",
            build_explicit_landscape_plan(TASK_ID, TOPIC),
            "build_landscape",
            [
                "map_gaps",
                "generate_candidate_ideas",
                "screen_novelty_feasibility_risk",
                "create_experiment_matrix",
                "build_claim_ledger",
                "draft_manuscript_section",
            ],
        ),
        (
            "workflow_gap_mapping",
            build_explicit_gap_mapping_plan(TASK_ID, TOPIC),
            "map_gaps",
            [
                "generate_candidate_ideas",
                "screen_novelty_feasibility_risk",
                "create_experiment_matrix",
                "build_claim_ledger",
                "draft_manuscript_section",
            ],
        ),
        (
            "workflow_idea_generation",
            build_explicit_idea_generation_plan(TASK_ID, TOPIC),
            "generate_candidate_ideas",
            [
                "screen_novelty_feasibility_risk",
                "create_experiment_matrix",
                "build_claim_ledger",
                "draft_manuscript_section",
            ],
        ),
        (
            "workflow_screening",
            build_explicit_screening_plan(TASK_ID, TOPIC),
            "screen_novelty_feasibility_risk",
            ["create_experiment_matrix", "build_claim_ledger", "draft_manuscript_section"],
        ),
        (
            "workflow_experiment_matrix",
            build_explicit_experiment_matrix_plan(TASK_ID, TOPIC),
            "create_experiment_matrix",
            ["build_claim_ledger", "draft_manuscript_section"],
        ),
        (
            "workflow_claim_ledger",
            build_explicit_claim_ledger_plan(TASK_ID, TOPIC),
            "build_claim_ledger",
            ["draft_manuscript_section"],
        ),
        (
            "workflow_manuscript_scaffold",
            build_explicit_manuscript_scaffold_plan(TASK_ID, TOPIC),
            "draft_manuscript_section",
            [],
        ),
    ]

    for profile_id, plan, terminal_step, forbidden_downstream_steps in profiles:
        skill_names = _skill_names(plan)
        assert skill_names[-1] == terminal_step, profile_id
        assert skill_names.count(terminal_step) == 1, profile_id
        for forbidden in forbidden_downstream_steps:
            assert forbidden not in skill_names, profile_id


def test_default_workflow_gallery_exposes_controlled_profiles_not_legacy_full_pipeline() -> None:
    template_ids = {template["id"] for template in list_templates()}

    assert "controlled-minimal-evidence" in template_ids
    assert "controlled-landscape" in template_ids
    assert "controlled-gap-mapping" in template_ids
    assert "controlled-idea-generation" in template_ids
    assert "controlled-screening" in template_ids
    assert "full-pipeline" not in template_ids

    # Historical templates remain readable by id for compatibility, but are not
    # part of the default new-run gallery or ordinary chat behavior.
    assert get_template("full-pipeline") is not None


def test_controlled_workflow_templates_do_not_imply_chat_default_full_research_chain() -> None:
    for template in list_templates():
        assert template["category"] == "controlled-research"
        assert len(template["steps"]) == 1
        step = template["steps"][0]
        assert step["runner"] == "research-controller"
        assert step["available"] is True
        assert step["params"]["controller_plan_kind"] in {
            "minimal",
            "landscape",
            "gap_mapping",
            "idea_generation",
            "screening",
        }
        stages = [item["stage"] for item in step["params"]["stages"]]
        assert "draft_manuscript_section" not in stages
        assert "build_claim_ledger" not in stages
        assert "create_experiment_matrix" not in stages


def test_manuscript_scaffold_is_only_in_explicit_manuscript_plan_template() -> None:
    non_manuscript_plans = [
        build_minimal_topic_to_evidence_plan(TASK_ID, TOPIC),
        build_explicit_landscape_plan(TASK_ID, TOPIC),
        build_explicit_gap_mapping_plan(TASK_ID, TOPIC),
        build_explicit_idea_generation_plan(TASK_ID, TOPIC),
        build_explicit_screening_plan(TASK_ID, TOPIC),
        build_explicit_experiment_matrix_plan(TASK_ID, TOPIC),
        build_explicit_claim_ledger_plan(TASK_ID, TOPIC),
    ]
    for plan in non_manuscript_plans:
        assert "draft_manuscript_section" not in _skill_names(plan)

    manuscript_plan = build_explicit_manuscript_scaffold_plan(TASK_ID, TOPIC)
    assert _skill_names(manuscript_plan)[-1] == "draft_manuscript_section"
    assert "workflow_full_research_discovery" not in manuscript_plan.plan_id
