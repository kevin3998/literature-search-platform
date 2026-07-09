# P2-M14 Report / Manuscript Drafting Skill Contract

## Purpose

P2-M14.1 defines the bounded contract and artifact schema for the Report / Manuscript Drafting Skill. P2-M14.2 adds the deterministic, stub-safe A4 wrapper for the primary bounded skill. P2-M14.3 adds explicit-only controller integration for the manuscript scaffold workflow.

This document covers the contract metadata, input / output artifact boundaries, schema objects, validation expectations, registry metadata, P2-M14.2 wrapper behavior, and P2-M14.3 explicit controller integration. It does not describe abstract generation, results / discussion drafting, conclusion generation, final claim generation, real Claude CLI smoke tests, or LLM calls.

Workflow boundary correction:

`draft_manuscript_section` belongs to the explicit manuscript scaffold workflow.
It is not ordinary chat behavior. Ordinary chat must not trigger manuscript
drafting unless the user selects a manuscript scaffold workflow or a future
chat router explicitly resolves to that workflow profile.

At the workflow-profile boundary, `workflow_manuscript_scaffold` is available
only through the explicit manuscript scaffold workflow. `workflow_full_research_discovery`
is available only as an explicit workflow, not default chat behavior.

The primary skill name is:

```text
draft_manuscript_section
```

`draft_manuscript_section` is available after P2-M14.2 as a deterministic scaffold builder and is controller-reachable after P2-M14.3 only through explicit manuscript scaffold execution or an explicit bounded controller decision. It remains manuscript-adjacent and human-review-required; it is not a final manuscript generator.

`draft_evidence_grounded_report` remains a separate future stub unless explicitly planned later.

`draft_manuscript_section` is part of the explicit manuscript scaffold workflow.
It must not be triggered by ordinary chat or by the explicit claim ledger
workflow unless a manuscript scaffold workflow is explicitly selected and
available.

## Manuscript Drafting Skill Role

`draft_manuscript_section` is a bounded manuscript-adjacent drafting wrapper. It consumes claim ledger artifacts, experiment matrix artifacts, screening results, candidate ideas, gap map artifacts, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics.

Bounded outputs include:

- evidence-grounded section draft
- structured report draft
- background / literature context draft
- gap framing draft
- hypothesis framing draft
- limitations-aware discussion scaffold

P2-M14.2 generates these outputs as conservative scaffold artifacts only.

The skill must not generate or assert:

- final accepted manuscript
- validated experimental conclusion
- completed results section based on unperformed experiments
- final claims
- publication-ready conclusion
- unsupported mechanism claim
- unsupported performance claim

It is not:

- an experimental result interpreter
- a claim validation engine
- a hypothesis proof engine
- a novelty proof engine
- a wet-lab protocol generator
- a safety protocol generator

## Legal Inputs

Required inputs:

```text
claims/claim_ledger.json
claims/claim_ledger_diagnostics.json
experiments/experiment_matrix.json
experiments/experiment_matrix_diagnostics.json
screening/idea_screening_results.json
screening/screening_diagnostics.json
ideas/candidate_ideas.json
ideas/idea_generation_diagnostics.json
gaps/gap_map.json
gaps/gap_coverage_diagnostics.json
landscape/literature_landscape.json
landscape/landscape_coverage_diagnostics.json
evidence/evidence_cards.enriched.json
ranked_evidence/evidence_selection.json
ranked_evidence/coverage_diagnostics.json
```

Optional inputs:

```text
claims/claim_ledger.md
experiments/experiment_matrix.md
screening/idea_screening_results.md
ideas/candidate_ideas.md
gaps/gap_map.md
landscape/literature_landscape.md
reports/minimal_topic_to_evidence_report.json
```

Optional markdown and report artifacts can only act as evidence-grounded readable aids. They cannot replace claim ledger JSON, experiment matrix JSON, screening JSON, candidate ideas JSON, gap map JSON, landscape JSON, enriched Evidence Cards, selected evidence, or diagnostics.

## Forbidden Inputs

Forbidden inputs:

```text
retrieval/source_candidate_packet.json
retrieval/retrieval_warnings.json
retrieval/...
raw chunks
raw markdown papers
evidence/evidence_card_seeds.json
evidence/evidence_cards.initial.json
unvalidated landscape markdown without landscape JSON
unvalidated gap markdown without gap JSON
unvalidated idea markdown without candidate_ideas JSON
unvalidated screening markdown without screening JSON
unvalidated experiment matrix markdown without experiment_matrix JSON
unvalidated claim ledger markdown without claim_ledger JSON
```

Validation rejects `retrieval/...` input artifacts.

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_manuscript_drafting
missing_claim_ledger_artifact
manuscript_drafting_requires_claim_ledger
manuscript_drafting_requires_traceable_claims
manuscript_drafting_rejects_unvalidated_claims
manuscript_drafting_rejects_final_claim_overwrite
manuscript_drafting_rejects_raw_experimental_result_claims
```

## Output Artifacts

Successful execution writes:

```text
drafts/manuscript_section_draft.json
drafts/manuscript_section_draft.md
drafts/manuscript_section_diagnostics.json
```

P2-M14.2 writes these paths through the A4 wrapper only.

The manuscript drafting skill must not output:

```text
final_manuscript
accepted_manuscript
submission_ready_manuscript
final_claims
validated_results
publication_conclusion
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

Allowed `draft_type` values:

```text
manuscript_section
evidence_grounded_report_section
discussion_scaffold
```

Allowed `target_section` values:

```text
background
literature_review
research_gap
hypothesis_and_rationale
limitations
discussion_scaffold
```

Each `draft_block` has:

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

Allowed `allowed_downstream_use` values:

```text
draft_context
draft_gap_framing
draft_hypothesis_framing
draft_limitation
not_for_final_submission
```

Each `citation_map` record has:

- `citation_id`
- `claim_id`
- `evidence_ids`
- `source_paper_ids`
- `source_artifacts`
- `citation_status`

Allowed `citation_status` values:

```text
evidence_grounded
needs_manual_verification
insufficient_support
```

Each `unsupported_claims` record has:

- `unsupported_claim_id`
- `text`
- `reason`
- `source_artifacts`
- `recommended_action`

Allowed unsupported claim reasons:

```text
no_claim_ledger_basis
no_evidence_basis
overclaim
final_claim_attempt
experimental_validation_not_available
```

Allowed recommended actions:

```text
remove
downgrade
rewrite_as_hypothesis
move_to_limitations
request_user_input
```

Key constraints:

- Every draft block must reference `claim_ids` unless `block_type` is `transition` or `caution`.
- Every evidence-bearing block must reference `evidence_ids`.
- Every draft block must set `requires_human_review = true`.
- Every draft block must set `not_final_text = true`.
- Every draft block must set `not_peer_reviewed = true`.
- Candidate / screening / experiment matrix draft blocks must set `not_experimentally_validated = true`.
- Draft blocks must not upgrade `hypothesis_requires_validation`, `screening_preliminary`, or `matrix_planning_scaffold` records into validated results.
- Draft artifacts must not generate publication-ready final conclusions.

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

Optional allowed sections:

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

P2-M14.2 generates a bounded draft scaffold, but it must not generate a final manuscript.

## Validation Expectations

Future validators should check:

1. Input artifacts exist.
2. Claim ledger JSON exists and is parseable.
3. Claim ledger `schema_version == claim_ledger_v1`.
4. Experiment matrix JSON exists and is parseable.
5. Experiment matrix `schema_version == experiment_matrix_v1`.
6. Screening results JSON exists and is parseable.
7. Screening `schema_version == idea_screening_v2`.
8. Candidate ideas JSON exists and is parseable.
9. Candidate ideas `schema_version == candidate_ideas_v1`.
10. Gap map JSON exists and is parseable.
11. Gap map `schema_version == gap_map_v1`.
12. Landscape JSON exists and is parseable.
13. Landscape `schema_version == landscape_v1`.
14. No `retrieval/...` input.
15. Claim ledger contains claims.
16. Every draft block references `claim_ids` unless `transition` or `caution`.
17. Evidence-bearing draft blocks reference `evidence_ids`.
18. Draft blocks do not introduce unsupported claims.
19. Draft blocks do not upgrade preliminary claims into validated results.
20. Every draft block has `requires_human_review == true`.
21. Every draft block has `not_final_text == true`.
22. Every draft block has `not_peer_reviewed == true`.
23. Candidate / screening / experiment matrix blocks have `not_experimentally_validated == true`.
24. Markdown contains Evidence References.
25. Markdown does not contain final abstract / final results / final conclusion / final claims / submission-ready manuscript sections.
26. Artifact does not assert experimental validation, performance improvement, direct readiness, or final manuscript conclusions.

P2-M14.2 implements a lightweight deterministic drafting validator around these expectations.

## Registry Boundary

`draft_manuscript_section` is:

```text
status = available
requires_evidence_cards = true
allows_raw_chunks = false
database_access = none
writes_artifacts = true
```

`draft_manuscript_section` is in `EVIDENCE_SKILL_WRAPPERS` after P2-M14.2 and has an A4 execution dispatch entry.

`draft_evidence_grounded_report` remains future / separate unless explicitly planned later.

P2-M14.3 adds explicit-only native fallback and CLI-backed fake controller integration for `draft_manuscript_section`. It does not add real Claude CLI smoke.

P2-M14 implementation closure, including real Claude CLI bounded decision and one-step `run_once` smoke validation, is documented in:

```text
docs/p2_m14_manuscript_drafting_skill_closure.md
```

## What P2-M14.3 Does Not Do

P2-M14.3 does not:

- add real Claude CLI smoke tests
- call a real Claude CLI
- call an LLM
- generate final abstract
- generate final results
- generate final discussion
- generate final conclusion
- generate final claims
- modify M1-M7
- modify databases or SQLite schema
- consume raw retrieval artifacts
- claim experimental results have been validated
- claim candidate hypotheses have been proven
- output submission-ready manuscript text

## Next Step Recommendation

The next recommended step is:

```text
Phase 2 Final Closure / Workflow Profile Cleanup
```

Do not proceed automatically. The manuscript scaffold workflow should remain
explicit-only and must not let ordinary chat or default controller paths
auto-enter manuscript drafting.
