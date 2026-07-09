# P2-M12 Experiment Matrix Skill Contract

## Purpose

P2-M12.1 defines the bounded contract and artifact schema for the Experiment Matrix Skill.
P2-M12.2 adds a deterministic, stub-safe wrapper for assembling conservative
experiment matrix artifacts from already-screened ideas and evidence-grounded
upstream artifacts. P2-M12.3 adds explicit controller integration: controllers
may execute `create_experiment_matrix` only when the plan or CLI-backed fake
decision explicitly requests that skill.

Implementation closure is documented in `docs/p2_m12_experiment_matrix_skill_closure.md`.

The skill name is:

```text
create_experiment_matrix
```

P2-M12.2 is executable through the A4 skill wrapper dispatch, but remains
stub-safe. It does not implement real experiment planning, experimental
protocols, step-by-step synthesis recipes, safety procedures, manuscript
drafting, final claims, real Claude CLI smoke tests, or LLM-based design.
P2-M12.3 does not add any real Claude CLI experiment matrix smoke test.

## Experiment Matrix Role

`create_experiment_matrix` will organize screened candidate ideas into a structured, traceable matrix for downstream experimental planning under explicit constraints.

It is downstream of:

```text
screening results
-> candidate ideas
-> gap map
-> landscape artifacts
-> enriched Evidence Cards
-> selected / ranked evidence
-> diagnostics
-> experiment matrix
```

The matrix should preserve:

```text
candidate idea -> experiment objective -> variables -> controls -> comparison groups
-> characterization targets -> expected evidence type -> decision criteria -> limitations
```

P2-M12 is not:

- a wet-lab protocol generator
- a step-by-step synthesis recipe generator
- a safety procedure generator
- a manuscript writer
- a final claim generator
- a claim ledger builder

## Legal Inputs

Required inputs:

```text
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
screening/idea_screening_results.md
ideas/candidate_ideas.md
gaps/gap_map.md
landscape/literature_landscape.md
reports/minimal_topic_to_evidence_report.json
```

Optional markdown and report artifacts can only act as evidence-grounded readable aids. They cannot replace screening JSON, candidate ideas JSON, gap map JSON, landscape JSON, enriched Evidence Cards, selected evidence, or diagnostics.

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
```

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_experiment_matrix
missing_screening_results_artifact
experiment_matrix_requires_screened_ideas
experiment_matrix_requires_gap_and_evidence_basis
experiment_matrix_requires_conservative_screening_status
unsupported_experiment_matrix_claim
```

## Output Artifacts

Successful P2-M12.2 execution writes:

```text
experiments/experiment_matrix.json
experiments/experiment_matrix.md
experiments/experiment_matrix_diagnostics.json
```

These artifacts are deterministic assemblies from screening and evidence
artifacts. They are not wet-lab plans and are not final scientific claims.

The experiment matrix skill must not output:

```text
experimental_protocol
step_by_step_synthesis_recipe
safety_protocol
manuscript_section
final_claims
claim_ledger
```

## Experiment Matrix JSON Schema

The stable schema version is:

```text
experiment_matrix_v1
```

Core fields:

- `task_id`
- `topic`
- `experiment_matrix_id`
- `input_artifacts`
- `screening_id`
- `idea_set_id`
- `gap_map_id`
- `landscape_id`
- `evidence_ids`
- `source_paper_ids`
- `experiment_candidates`
- `matrix_scope`
- `design_policy`
- `limitations`
- `warnings`
- `created_at`
- `schema_version`

Each experiment candidate has:

- `experiment_id`
- `source_idea_id`
- `screened_idea_ref`
- `objective`
- `hypothesis_under_test`
- `gap_ids`
- `evidence_ids`
- `screening_basis`
- `design_variables`
- `control_groups`
- `comparison_groups`
- `characterization_targets`
- `expected_observations`
- `decision_criteria`
- `data_to_record`
- `constraints`
- `risk_notes`
- `not_a_protocol = true`
- `not_a_validated_claim = true`
- `requires_expert_review = true`
- `warnings`

`screening_basis` preserves:

- `novelty_status`
- `feasibility_status`
- `risk_status`
- `required_follow_up`
- `limitations`

Each design variable has:

- `variable_id`
- `name`
- `role`
- `allowed_level_description`
- `rationale`
- `evidence_refs`
- `constraints`
- `not_a_stepwise_instruction = true`

Allowed design variable roles:

```text
composition
structure
defect
synthesis_condition
treatment_condition
characterization_condition
performance_condition
comparison_factor
```

Each characterization target has:

- `target_id`
- `target`
- `purpose`
- `linked_gap_ids`
- `linked_evidence_ids`
- `expected_evidence_type`
- `limitations`

Allowed characterization purposes:

```text
verify_structure
verify_defect
verify_composition
verify_mechanism
verify_performance
compare_control
```

Key constraints:

- Every experiment candidate must reference `source_idea_id`.
- Every experiment candidate must reference screening basis.
- Every experiment candidate must preserve `gap_ids`.
- Every experiment candidate must preserve `evidence_ids`.
- Every experiment candidate must have `not_a_protocol = true`.
- Every experiment candidate must have `not_a_validated_claim = true`.
- Every experiment candidate must have `requires_expert_review = true`.
- Design variables must have `not_a_stepwise_instruction = true`.
- The matrix must not provide step-by-step wet-lab procedures.
- The matrix must not claim experiments are feasible as established fact.
- The matrix must not claim performance will improve.
- The matrix must not output manuscript-ready claims.

## Experiment Matrix Markdown Structure

Allowed sections:

```markdown
# Experiment Matrix

## Scope

## Screening And Evidence Base

## Candidate Experiment Matrix

## Variables And Controls

## Characterization Targets

## Data To Record

## Required Expert Review

## Limitations

## Evidence References
```

Evidence references should include stable identifiers such as:

```text
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
## Experimental Protocol
## Step-by-step Procedure
## Synthesis Recipe
## Safety Protocol
## Manuscript Draft
## Final Claims
```

These belong to downstream human planning or later modules, not P2-M12.

## Validation Expectations

The P2-M12.2 lightweight validator checks:

1. Input artifacts exist.
2. Screening results JSON exists and is parseable.
3. Screening schema version is `idea_screening_v2`.
4. Candidate ideas JSON exists and is parseable.
5. Candidate ideas schema version is `candidate_ideas_v1`.
6. No `retrieval/...` input is present.
7. Every screened idea has `idea_id`, `gap_ids`, and `evidence_ids`.
8. Every screened idea has `not_an_experiment_plan = true`.
9. Every screened idea has `not_a_validated_claim = true`.
10. Gap map JSON exists and is parseable.
11. Landscape JSON exists and is parseable.
12. Output JSON is parseable.
13. Schema version is `experiment_matrix_v1`.
14. Every experiment candidate references `source_idea_id`.
15. Every experiment candidate references screening basis.
16. Every experiment candidate preserves `gap_ids` and `evidence_ids`.
17. `not_a_protocol = true`.
18. `not_a_validated_claim = true`.
19. `requires_expert_review = true`.
20. Markdown contains Evidence References.
21. Markdown excludes experimental protocol / step-by-step / synthesis recipe / safety protocol / manuscript / final claim sections.
22. Experiment matrix does not claim feasibility, performance improvement, or validation as established fact.

## Registry Boundary

`create_experiment_matrix` is:

```text
status = available
requires_evidence_cards = true
allows_raw_chunks = false
database_access = none
writes_artifacts = true
```

P2-M12.2 registers an A4 wrapper dispatch entry for `create_experiment_matrix`.
The wrapper is deterministic and conservative. It reads only structured
screening, idea, gap, landscape, enriched evidence, ranked evidence, and
diagnostics artifacts.

P2-M12.3 adds plan-gated controller integration. Fallback and Claude CLI-backed
controllers do not automatically enter experiment matrix generation.

Controller boundaries:

- The default minimal topic-to-evidence plan stops at the minimal report.
- The explicit landscape plan stops at `build_landscape`.
- The explicit gap mapping plan stops at `map_gaps`.
- The explicit idea generation plan stops at `generate_candidate_ideas`.
- The explicit screening plan stops at `screen_novelty_feasibility_risk`.
- Only an explicit experiment matrix plan contains `create_experiment_matrix`.
- CLI-backed fake backend decisions may call `create_experiment_matrix` only through the normal A6/A4/A5 controller path.

P2-M13+ skills remain stub-only and non-executable.

## Deterministic Wrapper Behavior

The wrapper:

- validates required inputs exist and are parseable JSON
- rejects `retrieval/...`, raw chunks, raw markdown papers, seed cards, and initial cards
- requires `idea_screening_v2`, `candidate_ideas_v1`, `gap_map_v1`, `landscape_v1`, and `experiment_matrix_v1`
- requires screened ideas with gap and evidence basis
- requires conservative screening statuses such as `requires_external_search`, `requires_expert_review`, and `requires_risk_review`
- creates at most one experiment candidate per valid screened idea, up to 10 candidates
- preserves source idea, gap, evidence, screening, paper, landscape, and diagnostic references
- writes conservative objectives, hypotheses-under-test, high-level variables, controls, characterization targets, data categories, limitations, and warnings
- rejects forbidden markdown sections and unsupported claim phrases

The wrapper returns `validation_failed` for raw retrieval inputs, unsupported
claims, non-conservative screening status, missing screened ideas, or missing
gap/evidence basis. It returns `blocked` for missing required input artifacts.

## Explicit Controller Integration

The explicit experiment matrix plan appends one final step after screening:

```text
create_experiment_matrix
```

That step requires:

```text
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

Successful explicit controller execution writes and registers:

```text
experiments/experiment_matrix.json
experiments/experiment_matrix.md
experiments/experiment_matrix_diagnostics.json
```

Controller validation records an `experiment_matrix_output_gate` result, updates
the artifact manifest, writes controller/tool/validation logs, and marks
`create_experiment_matrix` in workspace state and plan summaries.

## What P2-M12 Does Not Do

P2-M12 does not:

- implement real experiment planning
- make fallback controller auto-enter experiment matrix generation
- make Claude CLI-backed controller request experiment matrix in smoke tests
- implement experimental protocols
- implement step-by-step synthesis recipes
- implement safety protocols
- implement manuscript drafting
- implement final claims
- call real Claude CLI
- call an LLM
- modify M1-M7
- modify databases or SQLite schema
- consume raw retrieval artifacts
- claim experiment feasibility has been verified
- claim performance will improve

## Closure

P2-M12 has completed contract definition, deterministic wrapper implementation,
explicit controller integration, real Claude CLI bounded decision smoke, and
real CLI one-step `run_once` smoke. The closure record is:

```text
docs/p2_m12_experiment_matrix_skill_closure.md
```

Do not proceed automatically to P2-M13 from this contract document. P2-M13
should start with claim ledger contract, artifact schema, input boundary,
forbidden inputs, and validation expectations.
