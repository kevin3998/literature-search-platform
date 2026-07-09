# Phase 2 Final Closure / Workflow Profile Cleanup

## Purpose

This document closes Phase 2 after completion of P2-M8 through P2-M14. It fixes the final explicit literature-research-agent capability chain, workflow profile layer, terminal-step rules, chat / workflow / runtime boundary, no-auto-advance guarantees, availability matrix, real Claude CLI smoke coverage, and next-phase recommendation.

Phase 2 is now a complete explicit, evidence-grounded literature research workflow capability set.

Phase 2 is not default chat behavior. Phase 2 workflows must be invoked explicitly through workflow profiles, plan templates, a workflow API, or a future chat workflow router.

## Phase 2 Completion Summary

- P2-M8 Landscape Skill: completed
- P2-M9 Gap Mapping Skill: completed
- P2-M10 Idea Generation Skill: completed
- P2-M11 Novelty / Feasibility / Risk Screening Skill: completed
- P2-M12 Experiment Matrix Skill: completed
- P2-M13 Claim Ledger Skill: completed
- P2-M14 Report / Manuscript Drafting Skill: completed

Each downstream skill completed the same bounded pattern:

```text
contract / schema
-> deterministic stub-safe wrapper
-> explicit controller integration
-> real Claude CLI bounded decision smoke
-> real Claude CLI one-step run_once smoke
-> documentation closure
```

Closure documents:

- `docs/p2_m8_landscape_skill_closure.md`
- `docs/p2_m9_gap_mapping_skill_closure.md`
- `docs/p2_m10_idea_generation_skill_closure.md`
- `docs/p2_m11_screening_skill_closure.md`
- `docs/p2_m12_experiment_matrix_skill_closure.md`
- `docs/p2_m13_claim_ledger_skill_closure.md`
- `docs/p2_m14_manuscript_drafting_skill_closure.md`

## Final Research Workflow Capability Chain

The final Phase 2 capability chain is:

```text
retrieve_sources
-> create_evidence_seeds
-> extract_evidence_cards
-> enrich_evidence_cards
-> rank_evidence
-> build_minimal_topic_to_evidence_report
-> build_landscape
-> map_gaps
-> generate_candidate_ideas
-> screen_novelty_feasibility_risk
-> create_experiment_matrix
-> build_claim_ledger
-> draft_manuscript_section
```

Step roles:

- `retrieve_sources`: bounded source acquisition
- `create_evidence_seeds`: source-to-seed conversion
- `extract_evidence_cards`: Evidence Card extraction
- `enrich_evidence_cards`: Evidence Card enrichment
- `rank_evidence`: evidence selection and coverage diagnostics
- `build_minimal_topic_to_evidence_report`: minimal evidence-grounded topic report
- `build_landscape`: literature landscape construction
- `map_gaps`: gap mapping
- `generate_candidate_ideas`: candidate idea generation
- `screen_novelty_feasibility_risk`: preliminary novelty / feasibility / risk screening
- `create_experiment_matrix`: conservative experiment matrix scaffold
- `build_claim_ledger`: traceable claim ledger scaffold
- `draft_manuscript_section`: manuscript-adjacent draft scaffold

The chain is available through explicit workflow profiles. It is not an instruction for ordinary chat to auto-run all steps.

## Workflow Profiles And Terminal Steps

Final workflow profiles:

- `workflow_minimal_report`
- `workflow_literature_landscape`
- `workflow_gap_mapping`
- `workflow_idea_generation`
- `workflow_screening`
- `workflow_experiment_matrix`
- `workflow_claim_ledger`
- `workflow_manuscript_scaffold`
- `workflow_full_research_discovery`

Terminal steps:

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

Every workflow profile must be explicit. No workflow profile is ordinary chat default behavior. No workflow may auto-advance beyond its terminal step.

## Availability Matrix

| Workflow profile | Availability |
| --- | --- |
| `workflow_minimal_report` | available |
| `workflow_literature_landscape` | available |
| `workflow_gap_mapping` | available |
| `workflow_idea_generation` | available |
| `workflow_screening` | available |
| `workflow_experiment_matrix` | available |
| `workflow_claim_ledger` | available |
| `workflow_manuscript_scaffold` | available |
| `workflow_full_research_discovery` | available as explicit workflow only |

`workflow_full_research_discovery` remains explicit only. Ordinary chat must not trigger it by default.

Skill wrapper availability does not imply ordinary chat availability. A downstream skill being available in the registry does not mean upstream workflows auto-advance into it.

## Chat Layer / Workflow Layer / Runtime Boundary

Final architecture boundary:

```text
Chat Interface
  -> Intent / Workflow Router
  -> Workflow Profile / Plan Template
  -> literature-research-agent Controller
  -> Skill Registry
  -> Skill Wrappers
  -> Artifacts / Validation / Audit
```

Chat Layer responsibilities:

- user interaction
- intent interpretation
- explicit workflow selection
- parameter collection
- progress display
- artifact summary

Workflow Layer responsibilities:

- workflow profiles
- terminal-step rules
- explicit invocation
- workflow availability

literature-research-agent Runtime responsibilities:

- workspace
- state
- plan
- controller
- skill registry
- wrapper dispatch
- validation
- audit
- artifact manifest
- Claude CLI bounded adapter
- native fallback controller

The chat layer must not be described or implemented as automatically executing the full research chain.

## No-Auto-Advance Rule

Final no-auto-advance rules:

- default minimal chain stops at minimal report
- explicit landscape stops at `build_landscape`
- explicit gap mapping stops at `map_gaps`
- explicit idea generation stops at `generate_candidate_ideas`
- explicit screening stops at `screen_novelty_feasibility_risk`
- explicit experiment matrix stops at `create_experiment_matrix`
- explicit claim ledger stops at `build_claim_ledger`
- explicit manuscript scaffold stops at `draft_manuscript_section`
- ordinary chat does not trigger `workflow_full_research_discovery`

A downstream skill being available in the registry does not mean upstream workflows auto-advance into it.

## Skill Registry Final State

Available / executable skills:

- `retrieve_sources`
- `create_evidence_seeds`
- `extract_evidence_cards`
- `enrich_evidence_cards`
- `rank_evidence`
- `build_minimal_topic_to_evidence_report`
- `validate_evidence_cards`
- `validate_artifact_manifest`
- `build_landscape`
- `map_gaps`
- `generate_candidate_ideas`
- `screen_novelty_feasibility_risk`
- `create_experiment_matrix`
- `build_claim_ledger`
- `draft_manuscript_section`

Stub / non-executable future skill:

- `draft_evidence_grounded_report`

`draft_evidence_grounded_report` remains separate from the P2-M14 executable manuscript scaffold unless explicitly designed later. Unknown or future skills remain non-executable.

## Artifact Families

Final Phase 2 artifact families:

- `retrieval/`: source candidates and retrieval warnings
- `evidence/`: seeds, extracted cards, enriched cards
- `ranked_evidence/`: evidence selection and coverage diagnostics
- `reports/`: minimal topic-to-evidence report
- `landscape/`: literature landscape artifacts
- `gaps/`: gap map artifacts
- `ideas/`: candidate idea artifacts
- `screening/`: novelty / feasibility / risk screening artifacts
- `experiments/`: experiment matrix artifacts
- `claims/`: claim ledger artifacts
- `drafts/`: manuscript scaffold artifacts
- `audit/`: artifact manifest and audit-related records
- `logs/`: controller events, tool calls, validation results
- `state.json`: workspace execution state
- `plan.md`: workspace plan and controller status summary

## Controller Integration Summary

PlatformNativeFallbackController executes a downstream workflow skill only when the active plan explicitly contains that skill.

ClaudeCodeBackedMinimalController executes a downstream workflow skill only when a validated `CALL_TOOL` decision explicitly requests that skill and A6 / A4 / A5 gates accept it.

Claude CLI emits bounded decisions only. Claude CLI does not execute skills directly. The platform executes wrappers, validates artifacts, and updates audit / manifest / state / plan.

## Real Claude CLI Smoke Coverage

All P2-M8 through P2-M14 real Claude CLI tests are opt-in. The default test suite skips real CLI tests.

Coverage:

- P2-M8 `build_landscape`
  - bounded decision smoke
  - one-step `run_once` smoke
- P2-M9 `map_gaps`
  - bounded decision smoke
  - one-step `run_once` smoke
- P2-M10 `generate_candidate_ideas`
  - bounded decision smoke
  - one-step `run_once` smoke
- P2-M11 `screen_novelty_feasibility_risk`
  - bounded decision smoke
  - one-step `run_once` smoke
- P2-M12 `create_experiment_matrix`
  - bounded decision smoke
  - one-step `run_once` smoke
- P2-M13 `build_claim_ledger`
  - bounded decision smoke
  - one-step `run_once` smoke
- P2-M14 `draft_manuscript_section`
  - bounded decision smoke
  - one-step `run_once` smoke

## Safety And Overclaim Boundary

Phase 2 forbids:

- raw retrieval directly entering downstream reports / landscape / gaps / ideas / screening / experiment matrix / claim ledger / manuscript scaffold
- unsupported claims
- validated result claims without experimental data
- final claims
- publication-ready manuscript generation
- wet-lab protocol generation
- safety protocol generation
- automatic full workflow execution from ordinary chat
- unrestricted tool execution by Claude CLI

Downstream artifact safety semantics:

- screening artifacts are preliminary
- experiment matrix artifacts are planning scaffolds
- claim ledger artifacts are traceability scaffolds
- manuscript drafting artifacts are non-final scaffold drafts
- all downstream artifacts require human expert review

## What Phase 2 Does Not Do

Phase 2 does not implement:

- ordinary chat default full research execution
- autonomous research execution without explicit workflow
- final manuscript writing
- publication-ready manuscript generation
- experimental result validation
- wet-lab protocol generation
- safety protocol generation
- automatic database mutation beyond artifact / state / audit management
- unrestricted tool execution by Claude CLI

## Recommended Next Phase

The recommended next phase is:

```text
Phase 3: Workflow Productization / Chat Router Integration
```

Possible Phase 3 breakdown:

- P3-M1 Workflow Profile Registry
- P3-M2 Chat Intent To Workflow Router
- P3-M3 Workflow Parameter Collection
- P3-M4 Workflow Execution UI / Progress Events
- P3-M5 Artifact Browser / Summary Layer
- P3-M6 Workflow Resume / Replay / Export
- P3-M7 Permission And Safety UX
- P3-M8 End-to-End User Acceptance Tests

Do not add new research skills before productizing the explicit workflow profile layer and chat-router boundary.
