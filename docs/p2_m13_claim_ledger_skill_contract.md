# P2-M13 Claim Ledger Skill Contract

## Purpose

P2-M13.1 defines the bounded contract and artifact schema for the Claim Ledger Skill.
P2-M13.2 adds a deterministic, stub-safe wrapper for assembling conservative,
traceable claim ledger artifacts from the experiment matrix and upstream
evidence-grounded artifacts.

The skill is executable through the A4 wrapper dispatch after P2-M13.2, but
remains conservative and bounded. It does not draft manuscripts, generate final
claims, interpret experimental results, call an LLM, or call real Claude CLI.

P2-M13.1 did not build a real claim ledger. P2-M13.2 implements only a
deterministic traceability assembly wrapper, not free-form claim generation.

The skill name is:

```text
build_claim_ledger
```

## Claim Ledger Role

`build_claim_ledger` will organize traceable claim records from experiment matrix artifacts, screening results, candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics.

The intended organization is:

```text
claim candidate
-> claim type
-> claim status
-> evidence basis
-> upstream artifact basis
-> support level
-> limitations
-> allowed downstream use
-> prohibited overclaiming
```

P2-M13 is downstream of P2-M12. It consumes experiment matrix artifacts as conservative planning scaffolds. It must not treat experiment matrix entries as validated experimental results.

P2-M13 is not:

- a manuscript writer
- a final conclusion generator
- an experimental result interpreter
- a claim validation engine
- an external novelty search
- a wet-lab result analyzer

## Legal Inputs

Required inputs:

```text
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
experiments/experiment_matrix.md
screening/idea_screening_results.md
ideas/candidate_ideas.md
gaps/gap_map.md
landscape/literature_landscape.md
reports/minimal_topic_to_evidence_report.json
```

Optional markdown and report artifacts can only act as evidence-grounded readable aids. They cannot replace experiment matrix JSON, screening JSON, candidate ideas JSON, gap map JSON, landscape JSON, enriched Evidence Cards, selected evidence, or diagnostics.

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
unvalidated experiment matrix markdown without experiment matrix JSON
```

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_claim_ledger
missing_experiment_matrix_artifact
claim_ledger_requires_experiment_matrix
claim_ledger_requires_traceable_evidence_basis
claim_ledger_requires_non_final_claim_status
claim_ledger_rejects_validated_result_claim
```

## Output Artifacts

Future successful execution will write:

```text
claims/claim_ledger.json
claims/claim_ledger.md
claims/claim_ledger_diagnostics.json
```

P2-M13.1 defines these paths only. It does not write them.

The claim ledger skill must not output:

```text
manuscript_section
final_claims
paper_conclusion
abstract
discussion_section
experimental_results
```

## Claim Ledger JSON Schema

The stable schema version is:

```text
claim_ledger_v1
```

Core fields:

- `task_id`
- `topic`
- `claim_ledger_id`
- `input_artifacts`
- `experiment_matrix_id`
- `screening_id`
- `idea_set_id`
- `gap_map_id`
- `landscape_id`
- `evidence_ids`
- `source_paper_ids`
- `claims`
- `ledger_scope`
- `claim_policy`
- `limitations`
- `warnings`
- `created_at`
- `schema_version`

Each claim record has:

- `claim_id`
- `claim_text`
- `claim_type`
- `claim_status`
- `source_artifacts`
- `source_idea_ids`
- `source_experiment_ids`
- `gap_ids`
- `evidence_ids`
- `source_paper_ids`
- `supporting_evidence`
- `upstream_dependencies`
- `support_level`
- `allowed_downstream_use`
- `prohibited_uses`
- `limitations`
- `not_a_final_claim = true`
- `not_experimentally_validated = true`
- `requires_human_review = true`
- `warnings`

Allowed `claim_type` values:

```text
literature_observation
evidence_summary
gap_statement
candidate_hypothesis
screening_assessment
experiment_matrix_rationale
limitation_statement
```

Allowed `claim_status` values:

```text
evidence_supported_literature_claim
evidence_grounded_candidate
hypothesis_requires_validation
screening_preliminary
matrix_planning_scaffold
insufficient_support
rejected_overclaim
```

Allowed `support_level` values:

```text
none
low
medium
high
```

Allowed `allowed_downstream_use` values:

```text
background_context
gap_framing
hypothesis_framing
planning_rationale
limitation_only
not_for_manuscript_claim
```

Key constraints:

- Every claim must have `claim_id`.
- Every claim must have `claim_type`.
- Every claim must have `claim_status`.
- Every claim must reference `source_artifacts`.
- Every claim must preserve `evidence_ids`, unless `claim_status` is `insufficient_support` or `rejected_overclaim`.
- Every claim must have `not_a_final_claim = true`.
- Every claim must have `not_experimentally_validated = true`.
- Every claim must have `requires_human_review = true`.
- Claim ledger artifacts must not assert experimental results have been obtained.
- Claim ledger artifacts must not assert candidate hypotheses have been proven.
- Claim ledger artifacts must not assert performance will improve.
- Claim ledger artifacts must not generate manuscript-ready conclusions.

## Claim Ledger Markdown Structure

Allowed sections:

```markdown
# Claim Ledger

## Scope

## Upstream Evidence And Artifact Base

## Claim Records

## Claim Status Summary

## Claims Not Suitable For Manuscript Use

## Limitations

## Required Human Review

## Evidence References
```

Evidence references should include stable identifiers such as:

```text
claim_id
experiment_id
idea_id
screening_id
gap_id
evidence_id
paper_id
landscape_cluster_id
diagnostic reference
```

Forbidden sections:

```markdown
## Manuscript Draft
## Abstract
## Results And Discussion
## Conclusion
## Final Claims
```

These belong to P2-M14 or an external human writing workflow, not P2-M13.1.

## Validation Expectations

Future validators should check:

1. Input artifacts exist.
2. Experiment matrix JSON exists and is parseable.
3. Experiment matrix schema version is `experiment_matrix_v1`.
4. Screening results JSON exists and is parseable.
5. Screening schema version is `idea_screening_v2`.
6. Candidate ideas JSON exists and is parseable.
7. Candidate ideas schema version is `candidate_ideas_v1`.
8. No `retrieval/...` input is present.
9. Experiment candidates preserve source idea / gap / evidence basis.
10. Screening results do not contain final claims.
11. Output JSON is parseable.
12. Schema version is `claim_ledger_v1`.
13. Every claim has `claim_id`, `claim_type`, and `claim_status`.
14. Every claim references `source_artifacts`.
15. Every evidence-bearing claim references `evidence_ids`.
16. Every claim has `not_a_final_claim = true`.
17. Every claim has `not_experimentally_validated = true`.
18. Every claim has `requires_human_review = true`.
19. Markdown contains Evidence References.
20. Markdown excludes manuscript / abstract / results / conclusion / final claims sections.
21. Claim ledger does not assert experimental validation, performance improvement, or final manuscript conclusions.

## Deterministic Wrapper Behavior

The P2-M13.2 wrapper:

- validates required inputs exist and are parseable JSON
- rejects `retrieval/...`, raw chunks, raw markdown papers, seed cards, and initial cards
- requires `experiment_matrix_v1`, `idea_screening_v2`, `candidate_ideas_v1`, `gap_map_v1`, `landscape_v1`, and `claim_ledger_v1`
- requires experiment matrix candidates with source idea, gap, and evidence basis
- builds conservative claim records for literature observations, gap statements, candidate hypotheses, screening assessments, experiment matrix rationale, and limitations
- preserves experiment, idea, screening, gap, evidence, paper, landscape, and diagnostic references
- marks every claim as `not_a_final_claim`, `not_experimentally_validated`, and `requires_human_review`
- rejects forbidden manuscript-ready, final-claim, validation, feasibility, novelty, and performance-improvement phrases
- uses no LLM generation, real experiment interpretation, manuscript drafting, or final claim generation

The current claim ledger skill is a conservative traceability assembly layer,
not a manuscript claim writer or experimental result validator.

## Registry Boundary

`build_claim_ledger` is:

```text
status = available
requires_evidence_cards = true
allows_raw_chunks = false
database_access = none
writes_artifacts = true
```

P2-M13.2 registers an A4 wrapper dispatch entry for `build_claim_ledger`.

P2-M13.3 adds explicit controller integration only:

- `PlatformNativeFallbackController` executes `build_claim_ledger` only when the active plan explicitly contains `build_claim_ledger`
- default minimal, landscape, gap mapping, idea generation, screening, and experiment matrix plans do not auto-enter claim ledger construction
- `ClaudeCodeBackedMinimalController` can execute `build_claim_ledger` when a fake CLI backend explicitly returns a valid `CALL_TOOL build_claim_ledger` envelope
- claim ledger controller preflight rejects `retrieval/...`, raw chunks, seed cards, initial cards, and disallowed markdown inputs
- claim ledger output validation checks `claim_ledger_v1`, evidence references, review flags, and forbidden manuscript/final-claim phrasing

Claude CLI-backed flows must not request real claim ledger smoke tests in this stage.

P2-M14+ skills remain stub-only and non-executable.

## What P2-M13.1 Does Not Do

P2-M13 does not:

- make fallback controller auto-enter claim ledger construction
- make Claude CLI request claim ledger smoke tests
- implement manuscript drafting
- generate final claims
- generate abstracts
- generate results / discussion sections
- generate conclusions
- call real Claude CLI
- call an LLM
- modify M1-M7
- modify databases or SQLite schema
- consume raw retrieval artifacts
- claim experimental results have been validated
- claim candidate hypotheses have been proven
- output manuscript-ready claims

## P2-M13.3 Closure

P2-M13.3 is complete at the controller integration baseline:

```text
explicit claim ledger plan / explicit fake CLI build_claim_ledger request
→ deterministic build_claim_ledger wrapper
→ validation / audit / manifest / state / plan update
→ stop
```

No real Claude CLI invocation, LLM call, manuscript drafting, final claim generation, M1-M7 change, or database change is part of P2-M13.3.

## P2-M13 Closure Document

Implementation closure for P2-M13, including the P2-M13.4a / P2-M13.4b real Claude CLI smoke validation record, is documented in:

```text
docs/p2_m13_claim_ledger_skill_closure.md
```

## Next Step Recommendation

The next recommended step is:

```text
P2-M14.1 Report / Manuscript Drafting Skill Contract And Artifact Schema
```

Do not proceed automatically. P2-M14.1 should begin with contract, artifact
schema, input boundary, forbidden inputs, allowed manuscript-adjacent outputs,
and validation expectations. It must not directly implement manuscript drafting
or treat P2-M13 claim ledger records as validated experimental conclusions.
