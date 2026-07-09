# P2-M14 Report / Manuscript Drafting Skill Closure

## Purpose

This document closes P2-M14 Report / Manuscript Drafting Skill after contract definition, deterministic wrapper implementation, explicit controller integration, workflow profile boundary correction, and real Claude CLI bounded manuscript scaffold smoke validation.

本文档用于在 P2-M14 Report / Manuscript Drafting Skill 完成 contract、deterministic wrapper、explicit controller integration、workflow profile boundary correction 和真实 Claude CLI bounded smoke 后，固定该能力的实现边界和验证结果。

P2-M14 is available as an explicit, deterministic, evidence-grounded manuscript scaffold skill. It is not a final manuscript writer, final abstract generator, final results / discussion writer, final conclusion generator, final claim generator, experimental result interpreter, hypothesis validation engine, or publication-ready text generator.

## P2-M14 Completion Summary

- P2-M14.1 Manuscript Drafting Skill Contract And Artifact Schema: Done
- P2-M14.2 Stub-safe Manuscript Drafting Wrapper: Done
- P2-M14.3 Explicit Manuscript Drafting Controller Integration: Done
- P2-M14.4a Real Claude CLI Bounded Manuscript Decision Smoke: Done
- P2-M14.4b Real CLI One-Step Manuscript run_once Smoke: Done
- P2-M14.5 Documentation And Closure: Done

P2-M14 is now available as an explicit, deterministic, evidence-grounded manuscript scaffold skill.

P2-M14 does not implement final manuscript writing, final abstract generation, final results / discussion writing, final conclusion generation, final claims, experimental result interpretation, or publication-ready manuscript generation.

## Manuscript Drafting Skill Role

`draft_manuscript_section` assembles conservative manuscript-adjacent scaffold artifacts using claim ledger artifacts, experiment matrix artifacts, screening results, candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, ranked evidence, and diagnostics.

It is based on:

- `claims/claim_ledger.json`
- `claims/claim_ledger_diagnostics.json`
- `claims/claim_ledger.md`
- `experiments/experiment_matrix.json`
- `experiments/experiment_matrix_diagnostics.json`
- `experiments/experiment_matrix.md`
- `screening/idea_screening_results.json`
- `screening/screening_diagnostics.json`
- `screening/idea_screening_results.md`
- `ideas/candidate_ideas.json`
- `ideas/idea_generation_diagnostics.json`
- `ideas/candidate_ideas.md`
- `gaps/gap_map.json`
- `gaps/gap_coverage_diagnostics.json`
- `gaps/gap_map.md`
- `landscape/literature_landscape.json`
- `landscape/landscape_coverage_diagnostics.json`
- `landscape/literature_landscape.md`
- `evidence/evidence_cards.enriched.json`
- `ranked_evidence/evidence_selection.json`
- `ranked_evidence/coverage_diagnostics.json`
- optional `reports/minimal_topic_to_evidence_report.json`

It is not based on:

- `retrieval/source_candidate_packet.json`
- `retrieval/retrieval_warnings.json`
- `retrieval/...`
- raw chunks
- raw papers
- `evidence/evidence_card_seeds.json`
- `evidence/evidence_cards.initial.json`
- unvalidated landscape markdown without landscape JSON
- unvalidated gap markdown without gap JSON
- unvalidated idea markdown without `candidate_ideas.json`
- unvalidated screening markdown without `idea_screening_results.json`
- unvalidated experiment matrix markdown without `experiment_matrix.json`
- unvalidated claim ledger markdown without `claim_ledger.json`

It is not:

- a final manuscript writer
- a final abstract generator
- a final results writer
- a final discussion writer
- a final conclusion generator
- a final claim generator
- an experimental result interpreter
- a hypothesis validation engine
- a publication-ready text generator

## Artifact Contract

Required input artifacts:

- `claims/claim_ledger.json`
- `claims/claim_ledger_diagnostics.json`
- `experiments/experiment_matrix.json`
- `experiments/experiment_matrix_diagnostics.json`
- `screening/idea_screening_results.json`
- `screening/screening_diagnostics.json`
- `ideas/candidate_ideas.json`
- `ideas/idea_generation_diagnostics.json`
- `gaps/gap_map.json`
- `gaps/gap_coverage_diagnostics.json`
- `landscape/literature_landscape.json`
- `landscape/landscape_coverage_diagnostics.json`
- `evidence/evidence_cards.enriched.json`
- `ranked_evidence/evidence_selection.json`
- `ranked_evidence/coverage_diagnostics.json`

Optional input artifacts:

- `claims/claim_ledger.md`
- `experiments/experiment_matrix.md`
- `screening/idea_screening_results.md`
- `ideas/candidate_ideas.md`
- `gaps/gap_map.md`
- `landscape/literature_landscape.md`
- `reports/minimal_topic_to_evidence_report.json`

Output artifacts:

- `drafts/manuscript_section_draft.json`
- `drafts/manuscript_section_draft.md`
- `drafts/manuscript_section_diagnostics.json`

Forbidden inputs:

- `retrieval/...`
- raw chunks
- raw papers
- `evidence/evidence_card_seeds.json`
- `evidence/evidence_cards.initial.json`
- unvalidated landscape markdown without landscape JSON
- unvalidated gap markdown without gap JSON
- unvalidated idea markdown without `candidate_ideas.json`
- unvalidated screening markdown without `idea_screening_results.json`
- unvalidated experiment matrix markdown without `experiment_matrix.json`
- unvalidated claim ledger markdown without `claim_ledger.json`

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_manuscript_drafting
missing_claim_ledger_artifact
missing_manuscript_drafting_input
manuscript_drafting_requires_claim_ledger
manuscript_drafting_requires_traceable_claims
manuscript_drafting_rejects_unvalidated_claims
manuscript_drafting_rejects_final_claim_overwrite
manuscript_drafting_rejects_raw_experimental_result_claims
```

## Manuscript Draft JSON Schema

The stable schema version is:

```text
manuscript_section_draft_v1
```

Core fields:

- `task_id`
- `topic`
- `draft_id`
- `draft_type`
- `target_section`
- `input_artifacts`
- `claim_ledger_id`
- `experiment_matrix_id`
- `screening_id`
- `idea_set_id`
- `gap_map_id`
- `landscape_id`
- `evidence_ids`
- `source_paper_ids`
- `draft_blocks`
- `citation_map`
- `unsupported_claims`
- `draft_policy`
- `limitations`
- `warnings`
- `created_at`
- `schema_version`

Each draft block has:

- `block_id`
- `block_type`
- `text`
- `claim_ids`
- `evidence_ids`
- `source_paper_ids`
- `allowed_downstream_use`
- `support_level`
- `requires_human_review = true`
- `not_final_text = true`
- `not_peer_reviewed = true`
- `not_experimentally_validated = true`
- `warnings`

Allowed `block_type` values:

```text
context
evidence_summary
gap_framing
hypothesis_framing
rationale
limitation
transition
caution
```

Each citation map record has:

- `citation_id`
- `claim_id`
- `evidence_ids`
- `source_paper_ids`
- `source_artifacts`
- `citation_status`

Each unsupported claim record has:

- `unsupported_claim_id`
- `text`
- `reason`
- `source_artifacts`
- `recommended_action`

Key constraints:

- Every draft block must have `block_id`, `block_type`, and `text`.
- Every non-transition / non-caution block must reference `claim_ids`.
- Evidence-bearing draft blocks must preserve `evidence_ids`.
- Every draft block must have `requires_human_review = true`.
- Every draft block must have `not_final_text = true`.
- Every draft block must have `not_peer_reviewed = true`.
- Candidate / screening / experiment matrix blocks must have `not_experimentally_validated = true`.
- Citation map records must preserve `claim_id`, `evidence_ids`, `source_paper_ids`, and `source_artifacts`.
- Draft artifacts must not assert experimental validation, manuscript conclusions, performance improvement, direct readiness, or final claims as established facts.

## Manuscript Draft Markdown Structure

Allowed sections:

```markdown
# Manuscript Section Draft

## Draft Scope

## Source Artifact Base

## Draft Blocks

## Citation Map

## Unsupported Or Downgraded Claims

## Limitations

## Required Human Review

## Evidence References
```

Optional scaffold sections:

```markdown
## Background Context Draft
## Literature-Grounded Gap Framing Draft
## Hypothesis And Rationale Draft
## Limitations Draft
## Discussion Scaffold
```

Forbidden sections:

```markdown
## Final Abstract
## Final Results
## Final Discussion
## Final Conclusion
## Final Claims
## Submission-Ready Manuscript
```

These belong to human manuscript-writing and finalization workflows. They do not belong to the P2-M14 scaffold artifact.

## Deterministic Construction Rule

The P2-M14.2 wrapper:

1. Reads claim ledger, claim ledger diagnostics, experiment matrix, experiment diagnostics, screening results, screening diagnostics, candidate ideas, idea diagnostics, gap map, gap diagnostics, landscape artifacts, enriched Evidence Cards, selected evidence, and ranking diagnostics.
2. Extracts `claim_ledger_id`, `claim_id`, `claim_text`, `claim_type`, `claim_status`, `allowed_downstream_use`, `support_level`, `source_artifacts`, `evidence_ids`, `source_paper_ids`, `gap_ids`, `source_idea_ids`, `source_experiment_ids`, limitations, warnings, and diagnostic refs.
3. Generates conservative draft blocks for context, evidence summary, gap framing, hypothesis framing, rationale, limitations, transition, and caution.
4. Generates citation map records from claim / evidence / paper / source artifact mappings.
5. Records unsupported claims for rejected overclaims, final-claim attempts, unsupported claims, or experimental-validation attempts.
6. Rejects raw retrieval inputs.
7. Rejects claim ledgers without claims.
8. Rejects claim records without traceable basis where traceability is required.
9. Rejects claim records written as final, validated, publication-ready, or experimental-result claims.
10. Preserves upstream IDs, evidence IDs, source paper IDs, source artifacts, warnings, and diagnostic references.
11. Marks every draft block as `requires_human_review`, `not_final_text`, `not_peer_reviewed`, and `not_experimentally_validated`.
12. Does not call an LLM.
13. Does not perform final manuscript drafting.
14. Does not interpret unperformed experiments as results.

The current manuscript drafting skill is a conservative evidence-grounded scaffold layer, not a final manuscript writer, publication-ready text generator, final-claim generator, or experimental result interpreter.

## Controller Integration Boundary

Default minimal topic-to-evidence chain still stops at minimal report.

Explicit workflow terminal boundaries:

- explicit landscape plan still stops at `build_landscape`
- explicit gap mapping plan still stops at `map_gaps`
- explicit idea generation plan still stops at `generate_candidate_ideas`
- explicit screening plan still stops at `screen_novelty_feasibility_risk`
- explicit experiment matrix plan still stops at `create_experiment_matrix`
- explicit claim ledger plan still stops at `build_claim_ledger`
- `draft_manuscript_section` is executed only when the plan explicitly includes a manuscript scaffold step or a bounded CLI decision explicitly requests `draft_manuscript_section`

PlatformNativeFallbackController:

- executes `draft_manuscript_section` only under an explicit manuscript scaffold plan

ClaudeCodeBackedMinimalController:

- can execute `draft_manuscript_section` only if a valid `CALL_TOOL draft_manuscript_section` decision is received and validated

Forbidden automatic extensions:

```text
minimal report -> automatic landscape
landscape -> automatic gap mapping
gap map -> automatic idea generation
candidate ideas -> automatic screening
screening -> automatic experiment matrix
experiment matrix -> automatic claim ledger
claim ledger -> automatic manuscript drafting
ordinary chat -> automatic full research discovery
```

## Workflow Profile Boundary

The workflow profile boundary correction fixed these layer semantics:

- Chat Layer is the interaction layer.
- Workflow Layer defines explicit workflow profiles and terminal steps.
- literature-research-agent Runtime executes only explicitly selected bounded workflows.
- P2-M8 to P2-M14 are workflow capabilities, not default chat behavior.
- Ordinary chat must not trigger `workflow_full_research_discovery` by default.

Current workflow availability:

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

## Real Claude CLI Smoke Validation

P2-M14.4a:

- Real Claude CLI emitted a valid `CALL_TOOL draft_manuscript_section` envelope.
- No skill was executed.
- No controller `run_once` was called.
- No manuscript draft artifact was generated.

P2-M14.4b:

- Real Claude CLI emitted `CALL_TOOL draft_manuscript_section`.
- Controller ran exactly one `run_once`.
- Platform executed deterministic `draft_manuscript_section` wrapper.
- No `run_until_stop` was called.
- No retrieve / seed / extract / enrich / rank / report / landscape / gap mapping / idea generation / screening / experiment matrix / claim ledger step was executed.
- Manuscript scaffold artifacts were generated and validated.

P2-M14.4b result:

```text
real_cli_invoked: true
parse_success: true
validation_success: true
decision_type / skill_name: CALL_TOOL / draft_manuscript_section
run_once_count: 1
run_until_stop_called: false
executed_skills: ["draft_manuscript_section"]
forbidden_executed: []
```

Generated artifacts:

- `drafts/manuscript_section_draft.json`
- `drafts/manuscript_section_draft.md`
- `drafts/manuscript_section_diagnostics.json`

Artifact checks:

- `schema_version = manuscript_section_draft_v1`
- `draft_id` present
- `claim_ledger_id` present
- `experiment_matrix_id` present
- `screening_id` present
- `idea_set_id` present
- `gap_map_id` present
- `landscape_id` present
- `draft_blocks` present
- `citation_map` present
- `unsupported_claims` present
- `evidence_ids` preserved
- review / finality flags correct
- diagnostics warnings preserved
- markdown contains Evidence References
- markdown contains Required Human Review
- forbidden final abstract / results / discussion / conclusion / claims sections absent
- submission-ready / publication-ready language absent

Audit, state, and plan:

- manifest registered all three draft artifacts
- `controller_events = 1`
- `tool_calls = 1`
- `validation_results = 1`
- state includes completed `draft_manuscript_section`
- plan contains manuscript step status summary

## Test Status

Default tests:

```bash
PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_manuscript_drafting_run_once_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_manuscript_drafting_decision_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_explicit_manuscript_drafting_controller_integration.py -q
# 22 passed

PYTHONPATH=backend pytest backend/tests/test_workflow_profile_boundary.py -q
# 5 passed

PYTHONPATH=backend pytest backend/tests/test_manuscript_drafting_skill_wrapper.py -q
# 8 passed

PYTHONPATH=backend pytest backend/tests/test_manuscript_drafting_skill_contract.py -q
# 5 passed

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_backend.py -q
# 11 passed, 1 skipped

PYTHONPATH=backend pytest backend/tests -q
# 598 passed, 23 skipped
```

Real opt-in smoke:

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_manuscript_drafting_run_once_smoke.py -q -s
# 1 passed
```

## Safety Boundary

1. Claude CLI does not execute `draft_manuscript_section` directly.
2. Claude CLI emits a bounded decision only.
3. Platform validates and executes the deterministic wrapper.
4. No real Claude CLI is called in default tests.
5. No LLM is used for manuscript scaffold content generation.
6. No M1-M7 code was modified.
7. No database schema was modified.
8. No raw retrieval artifact can enter manuscript drafting.
9. `draft_evidence_grounded_report` is not requested or executed by P2-M14.
10. No final manuscript / final abstract / final results / final discussion / final conclusion / final claim artifact is generated.
11. Manuscript scaffold records remain conservative and bounded.
12. Manuscript scaffold records must not claim experimental validation, hypothesis proof, performance improvement, direct readiness, submission readiness, publication readiness, or final conclusions as established facts.

## Known Limitations

1. Current `draft_manuscript_section` is deterministic and conservative.
2. It does not produce final manuscript text.
3. It does not generate final abstracts.
4. It does not generate final results or discussion sections.
5. It does not generate final conclusions.
6. It does not generate final claims.
7. It does not interpret experimental results.
8. It does not validate hypotheses experimentally.
9. It does not perform journal-specific manuscript formatting.
10. It does not perform citation style formatting.
11. It depends on the quality of claim ledger artifacts, experiment matrix artifacts, screening results, candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics.
12. Smoke fixtures are small and do not validate large-scale manuscript scaffold quality.
13. Manuscript scaffold outputs are traceability-aware drafting scaffolds only and require human expert review before any manuscript use.

## Next Step Recommendation

The recommended next step is:

```text
Phase 2 Final Closure / Workflow Profile Cleanup
```

After P2-M14 closure, Phase 2 should be closed by documenting the full literature-research-agent workflow profile set, final capability availability matrix, terminal-step rules, no-auto-advance guarantees, and chat-router integration boundary.

Do not add new research capabilities before Phase 2 final closure.
