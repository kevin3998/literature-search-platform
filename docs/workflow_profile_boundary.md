# Workflow Profile Boundary

## Purpose

This document fixes the architecture semantics between ordinary chat, explicit workflow selection, and the literature-research-agent runtime.

P2-M8 through P2-M14 are workflow capabilities. They are not default chat behavior.

## Chat Layer vs Workflow Layer vs Agent Runtime Layer

The intended architecture is:

```text
Chat Interface
-> Intent / Workflow Router
-> Workflow Profile / Plan Template
-> literature-research-agent Controller
-> Skill Registry
-> Skill Wrappers
-> Artifacts / Validation / Audit
```

The chat layer is the user interaction surface. It may collect intent, ask clarifying questions, show progress, and request explicit workflow selection.

The workflow layer owns workflow profiles and plan templates. It decides which bounded plan is selected and where that plan must stop.

The Agent Runtime Layer is the literature-research-agent controller plus registry, wrappers, validation gates, artifact manifest, state, plan, and audit logs. It executes only the selected bounded workflow.

## literature-research-agent Responsibility

The literature-research-agent runtime is an evidence-grounded research workflow runtime. It is not ordinary chat and it is not a free-form autonomous research chain.

The runtime may execute registered skills only through controller-approved plans or explicit controller decisions. It must preserve artifact validation, audit logging, state updates, and plan boundaries.

## Workflow Profiles

Current workflow profiles:

- `workflow_minimal_report`
- `workflow_literature_landscape`
- `workflow_gap_mapping`
- `workflow_idea_generation`
- `workflow_screening`
- `workflow_experiment_matrix`
- `workflow_claim_ledger`
- `workflow_manuscript_scaffold`
- `workflow_full_research_discovery`

## Terminal Step For Each Workflow

Each profile has a terminal step. The selected workflow must stop there unless a later explicit workflow is selected.

| Workflow profile | Terminal step |
| --- | --- |
| `workflow_minimal_report` | `build_minimal_topic_to_evidence_report` |
| `workflow_literature_landscape` | `build_landscape` |
| `workflow_gap_mapping` | `map_gaps` |
| `workflow_idea_generation` | `generate_candidate_ideas` |
| `workflow_screening` | `screen_novelty_feasibility_risk` |
| `workflow_experiment_matrix` | `create_experiment_matrix` |
| `workflow_claim_ledger` | `build_claim_ledger` |
| `workflow_manuscript_scaffold` | `draft_manuscript_section` |
| `workflow_full_research_discovery` | `draft_manuscript_section` |

## Explicit Invocation Rule

Research workflows must be explicitly invoked by a chat router, workflow API, or user workflow selection. Ordinary chat must not default to this workflow family.

`workflow_full_research_discovery` must always be explicit. It is never the default chat behavior.

## Default Chat Boundary

Ordinary chat may answer questions, route intent, and propose workflow options. It must not automatically execute:

- landscape building
- gap mapping
- idea generation
- novelty / feasibility / risk screening
- experiment matrix construction
- claim ledger construction
- manuscript scaffold drafting
- full research discovery

## No Auto-Advance Rule

A workflow profile must not auto-advance past its terminal step.

Examples:

- `workflow_minimal_report` stops at `build_minimal_topic_to_evidence_report`.
- `workflow_literature_landscape` stops at `build_landscape`.
- `workflow_gap_mapping` stops at `map_gaps`.
- `workflow_idea_generation` stops at `generate_candidate_ideas`.
- `workflow_screening` stops at `screen_novelty_feasibility_risk`.
- `workflow_experiment_matrix` stops at `create_experiment_matrix`.
- `workflow_claim_ledger` stops at `build_claim_ledger`.

The explicit claim ledger workflow must not automatically continue into manuscript drafting.

## Relationship To P2-M8 Through P2-M14

P2-M8 through P2-M14 add bounded downstream workflow capabilities to the literature-research-agent runtime. They do not redefine ordinary chat.

`draft_manuscript_section` is part of the explicit manuscript scaffold workflow. It must not be triggered by ordinary chat or by the explicit claim ledger workflow unless a manuscript scaffold workflow is explicitly selected.

## Current Availability Matrix

Skill wrapper availability does not imply ordinary chat availability or workflow profile availability.

| Workflow profile | Current availability |
| --- | --- |
| `workflow_minimal_report` | available |
| `workflow_literature_landscape` | available |
| `workflow_gap_mapping` | available |
| `workflow_idea_generation` | available |
| `workflow_screening` | available |
| `workflow_experiment_matrix` | available |
| `workflow_claim_ledger` | available |
| `workflow_manuscript_scaffold` | available through explicit manuscript scaffold workflow |
| `workflow_full_research_discovery` | available only as explicit workflow, not default chat behavior |

Skill wrapper availability and workflow controller availability are different layers; neither makes ordinary chat or full research discovery available by default.

`workflow_full_research_discovery` is available only as explicit workflow, not default chat behavior.

ordinary chat must not default to this workflow.

## Future Chat Router Integration

A future chat router may map user intent to workflow profiles. That router should:

- keep ordinary chat separate from research workflow execution
- show available workflow profiles explicitly
- require explicit user or API selection before running a workflow
- display the terminal step of the selected workflow
- avoid auto-selecting `workflow_full_research_discovery`
- avoid auto-entering manuscript scaffold drafting from claim ledger output

## Phase 2 Final Closure

The final Phase 2 workflow profile set, availability matrix, terminal-step
rules, no-auto-advance guarantees, artifact families, controller integration
summary, real Claude CLI smoke coverage, and safety boundary are documented in:

```text
docs/phase2_final_closure.md
```
