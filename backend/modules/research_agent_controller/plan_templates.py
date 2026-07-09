"""Controller plan templates for literature-research-agent workflows.

These plan templates are workflow profiles for the literature-research-agent
runtime. They are not default chat behavior. They must be selected explicitly by
the chat router, a workflow product surface, or a user workflow selection.
"""
from __future__ import annotations

from .schemas import AgentPlan, AgentStep, StopCondition


def build_minimal_topic_to_evidence_plan(
    task_id: str,
    topic: str,
    *,
    include_ranking: bool = True,
) -> AgentPlan:
    steps = [
        AgentStep(
            step_id="retrieve_sources",
            name="Retrieve source candidates",
            description=f"Retrieve topic-scoped source candidates for: {topic}",
            skill_name="retrieve_sources",
            produced_artifacts=["retrieval/source_candidate_packet.json"],
        ),
        AgentStep(
            step_id="create_evidence_seeds",
            name="Create evidence seeds",
            description="Normalize source candidates into Evidence Card seeds.",
            skill_name="create_evidence_seeds",
            required_artifacts=["retrieval/source_candidate_packet.json"],
            produced_artifacts=["evidence/evidence_card_seeds.json"],
        ),
        AgentStep(
            step_id="extract_evidence_cards",
            name="Extract initial evidence cards",
            description="Create initial Evidence Card drafts from seeds.",
            skill_name="extract_evidence_cards",
            required_artifacts=["evidence/evidence_card_seeds.json"],
            produced_artifacts=["evidence/evidence_cards.initial.json"],
        ),
        AgentStep(
            step_id="enrich_evidence_cards",
            name="Enrich evidence cards",
            description="Add evidence roles, entities, and relations.",
            skill_name="enrich_evidence_cards",
            required_artifacts=["evidence/evidence_cards.initial.json"],
            produced_artifacts=["evidence/evidence_cards.enriched.json"],
        ),
    ]
    if include_ranking:
        steps.append(
            AgentStep(
                step_id="rank_evidence",
                name="Rank representative evidence",
                description="Select representative evidence with coverage diagnostics.",
                skill_name="rank_evidence",
                required_artifacts=["evidence/evidence_cards.enriched.json"],
                produced_artifacts=["ranked_evidence/evidence_selection.json"],
            )
        )
    steps.append(
        AgentStep(
            step_id="build_minimal_topic_to_evidence_report",
            name="Build minimal topic-to-evidence report",
            description="Generate the minimal report from validated Evidence Cards or selected evidence.",
            skill_name="build_minimal_topic_to_evidence_report",
            required_artifacts=["evidence/evidence_cards.enriched.json"],
            produced_artifacts=[
                "reports/minimal_topic_to_evidence_report.md",
                "reports/minimal_topic_to_evidence_report.json",
            ],
        )
    )
    return AgentPlan(
        plan_id=f"{task_id}:minimal_topic_to_evidence",
        task_id=task_id,
        title="Minimal Topic-to-Evidence Plan",
        goal=f"Build a minimal evidence-grounded report for: {topic}",
        steps=steps,
        current_step_id=steps[0].step_id if steps else None,
        stop_conditions=[
            StopCondition.ALL_STEPS_COMPLETED,
            StopCondition.VALIDATION_FAILED,
            StopCondition.TOOL_FAILED,
            StopCondition.BUDGET_EXCEEDED,
        ],
    )


def build_explicit_landscape_plan(
    task_id: str,
    topic: str,
    *,
    include_minimal_report: bool = True,
) -> AgentPlan:
    plan = build_minimal_topic_to_evidence_plan(task_id, topic, include_ranking=True)
    if not include_minimal_report:
        plan.steps = [
            step for step in plan.steps
            if step.skill_name != "build_minimal_topic_to_evidence_report"
        ]
    plan.plan_id = f"{task_id}:explicit_landscape"
    plan.title = "Explicit Landscape Plan"
    plan.goal = f"Build an evidence-grounded literature landscape for: {topic}"
    plan.add_step(
        AgentStep(
            step_id="build_landscape",
            name="Build literature landscape",
            description="Build a deterministic landscape from enriched Evidence Cards and selected evidence.",
            skill_name="build_landscape",
            required_artifacts=[
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            produced_artifacts=[
                "landscape/literature_landscape.json",
                "landscape/literature_landscape.md",
                "landscape/landscape_coverage_diagnostics.json",
            ],
        )
    )
    if plan.steps:
        plan.current_step_id = plan.steps[0].step_id
    return plan


def build_explicit_gap_mapping_plan(
    task_id: str,
    topic: str,
    *,
    include_minimal_report: bool = True,
) -> AgentPlan:
    plan = build_explicit_landscape_plan(
        task_id,
        topic,
        include_minimal_report=include_minimal_report,
    )
    plan.plan_id = f"{task_id}:explicit_gap_mapping"
    plan.title = "Explicit Gap Mapping Plan"
    plan.goal = f"Build an evidence-grounded gap map for: {topic}"
    plan.add_step(
        AgentStep(
            step_id="map_gaps",
            name="Map evidence gaps",
            description="Build a deterministic gap map from landscape artifacts and selected evidence.",
            skill_name="map_gaps",
            required_artifacts=[
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            produced_artifacts=[
                "gaps/gap_map.json",
                "gaps/gap_map.md",
                "gaps/gap_coverage_diagnostics.json",
            ],
        )
    )
    if plan.steps:
        plan.current_step_id = plan.steps[0].step_id
    return plan


def build_explicit_idea_generation_plan(
    task_id: str,
    topic: str,
    *,
    include_minimal_report: bool = True,
) -> AgentPlan:
    plan = build_explicit_gap_mapping_plan(
        task_id,
        topic,
        include_minimal_report=include_minimal_report,
    )
    plan.plan_id = f"{task_id}:explicit_idea_generation"
    plan.title = "Explicit Idea Generation Plan"
    plan.goal = f"Build evidence-grounded candidate ideas for: {topic}"
    plan.add_step(
        AgentStep(
            step_id="generate_candidate_ideas",
            name="Generate candidate ideas",
            description="Build deterministic candidate ideas from gap map and selected evidence artifacts.",
            skill_name="generate_candidate_ideas",
            required_artifacts=[
                "gaps/gap_map.json",
                "gaps/gap_coverage_diagnostics.json",
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            produced_artifacts=[
                "ideas/candidate_ideas.json",
                "ideas/candidate_ideas.md",
                "ideas/idea_generation_diagnostics.json",
            ],
        )
    )
    if plan.steps:
        plan.current_step_id = plan.steps[0].step_id
    return plan


def build_explicit_screening_plan(
    task_id: str,
    topic: str,
    *,
    include_minimal_report: bool = True,
) -> AgentPlan:
    plan = build_explicit_idea_generation_plan(
        task_id,
        topic,
        include_minimal_report=include_minimal_report,
    )
    plan.plan_id = f"{task_id}:explicit_screening"
    plan.title = "Explicit Screening Plan"
    plan.goal = f"Build conservative screening results for candidate ideas on: {topic}"
    plan.add_step(
        AgentStep(
            step_id="screen_novelty_feasibility_risk",
            name="Screen novelty, feasibility, and risk",
            description=(
                "Build deterministic, conservative screening results from candidate ideas, "
                "gap map, landscape, enriched Evidence Cards, selected evidence, and diagnostics."
            ),
            skill_name="screen_novelty_feasibility_risk",
            required_artifacts=[
                "ideas/candidate_ideas.json",
                "ideas/idea_generation_diagnostics.json",
                "gaps/gap_map.json",
                "gaps/gap_coverage_diagnostics.json",
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            produced_artifacts=[
                "screening/idea_screening_results.json",
                "screening/idea_screening_results.md",
                "screening/screening_diagnostics.json",
            ],
        )
    )
    if plan.steps:
        plan.current_step_id = plan.steps[0].step_id
    return plan


def build_explicit_experiment_matrix_plan(
    task_id: str,
    topic: str,
    *,
    include_minimal_report: bool = True,
) -> AgentPlan:
    plan = build_explicit_screening_plan(
        task_id,
        topic,
        include_minimal_report=include_minimal_report,
    )
    plan.plan_id = f"{task_id}:explicit_experiment_matrix"
    plan.title = "Explicit Experiment Matrix Plan"
    plan.goal = f"Build a conservative experiment matrix for screened ideas on: {topic}"
    plan.add_step(
        AgentStep(
            step_id="create_experiment_matrix",
            name="Create experiment matrix",
            description=(
                "Build deterministic, conservative experiment matrix artifacts from screening results, "
                "candidate ideas, gap map, landscape, enriched Evidence Cards, selected evidence, and diagnostics."
            ),
            skill_name="create_experiment_matrix",
            required_artifacts=[
                "screening/idea_screening_results.json",
                "screening/screening_diagnostics.json",
                "ideas/candidate_ideas.json",
                "ideas/idea_generation_diagnostics.json",
                "gaps/gap_map.json",
                "gaps/gap_coverage_diagnostics.json",
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            produced_artifacts=[
                "experiments/experiment_matrix.json",
                "experiments/experiment_matrix.md",
                "experiments/experiment_matrix_diagnostics.json",
            ],
        )
    )
    if plan.steps:
        plan.current_step_id = plan.steps[0].step_id
    return plan


def build_explicit_claim_ledger_plan(
    task_id: str,
    topic: str,
    *,
    include_minimal_report: bool = True,
) -> AgentPlan:
    plan = build_explicit_experiment_matrix_plan(
        task_id,
        topic,
        include_minimal_report=include_minimal_report,
    )
    plan.plan_id = f"{task_id}:explicit_claim_ledger"
    plan.title = "Explicit Claim Ledger Plan"
    plan.goal = f"Build a conservative, traceable claim ledger for: {topic}"
    plan.add_step(
        AgentStep(
            step_id="build_claim_ledger",
            name="Build claim ledger",
            description=(
                "Build a deterministic claim ledger from experiment matrix artifacts, screening results, "
                "candidate ideas, gap map, landscape, enriched Evidence Cards, selected evidence, and diagnostics."
            ),
            skill_name="build_claim_ledger",
            required_artifacts=[
                "experiments/experiment_matrix.json",
                "experiments/experiment_matrix_diagnostics.json",
                "screening/idea_screening_results.json",
                "screening/screening_diagnostics.json",
                "ideas/candidate_ideas.json",
                "ideas/idea_generation_diagnostics.json",
                "gaps/gap_map.json",
                "gaps/gap_coverage_diagnostics.json",
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            produced_artifacts=[
                "claims/claim_ledger.json",
                "claims/claim_ledger.md",
                "claims/claim_ledger_diagnostics.json",
            ],
        )
    )
    if plan.steps:
        plan.current_step_id = plan.steps[0].step_id
    return plan


def build_explicit_manuscript_scaffold_plan(
    task_id: str,
    topic: str,
    *,
    include_minimal_report: bool = True,
) -> AgentPlan:
    """Build the explicit manuscript scaffold workflow profile.

    This plan is a workflow profile for literature-research-agent. It is not
    default chat behavior. It must be selected explicitly by chat router,
    workflow API, or user workflow selection.
    """
    plan = build_explicit_claim_ledger_plan(
        task_id,
        topic,
        include_minimal_report=include_minimal_report,
    )
    plan.plan_id = f"{task_id}:explicit_manuscript_scaffold"
    plan.title = "Explicit Manuscript Scaffold Plan"
    plan.goal = f"Build a conservative manuscript-adjacent scaffold for: {topic}"
    plan.add_step(
        AgentStep(
            step_id="draft_manuscript_section",
            name="Draft manuscript scaffold",
            description=(
                "Build deterministic manuscript-adjacent scaffold artifacts from claim ledger, "
                "experiment matrix, screening, candidate ideas, gap map, landscape, enriched Evidence Cards, "
                "selected evidence, and diagnostics."
            ),
            skill_name="draft_manuscript_section",
            required_artifacts=[
                "claims/claim_ledger.json",
                "claims/claim_ledger_diagnostics.json",
                "experiments/experiment_matrix.json",
                "experiments/experiment_matrix_diagnostics.json",
                "screening/idea_screening_results.json",
                "screening/screening_diagnostics.json",
                "ideas/candidate_ideas.json",
                "ideas/idea_generation_diagnostics.json",
                "gaps/gap_map.json",
                "gaps/gap_coverage_diagnostics.json",
                "landscape/literature_landscape.json",
                "landscape/landscape_coverage_diagnostics.json",
                "evidence/evidence_cards.enriched.json",
                "ranked_evidence/evidence_selection.json",
                "ranked_evidence/coverage_diagnostics.json",
            ],
            produced_artifacts=[
                "drafts/manuscript_section_draft.json",
                "drafts/manuscript_section_draft.md",
                "drafts/manuscript_section_diagnostics.json",
            ],
        )
    )
    if plan.steps:
        plan.current_step_id = plan.steps[0].step_id
    return plan


__all__ = [
    "build_explicit_claim_ledger_plan",
    "build_explicit_experiment_matrix_plan",
    "build_explicit_gap_mapping_plan",
    "build_explicit_idea_generation_plan",
    "build_explicit_landscape_plan",
    "build_explicit_manuscript_scaffold_plan",
    "build_explicit_screening_plan",
    "build_minimal_topic_to_evidence_plan",
]
