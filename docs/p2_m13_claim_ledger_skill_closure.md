# P2-M13 Claim Ledger Skill Closure

## Purpose

This document closes P2-M13 Claim Ledger Skill after contract definition, deterministic wrapper implementation, explicit controller integration, and real Claude CLI bounded claim ledger smoke validation.

本文档用于在 P2-M13 Claim Ledger Skill 完成 contract、deterministic wrapper、explicit controller integration 和真实 Claude CLI bounded smoke 后，固定该能力的实现边界和验证结果。

P2-M13 is available as an explicit, deterministic, evidence-grounded claim ledger skill. It is not a manuscript writer, abstract generator, results / discussion writer, conclusion generator, final claim generator, experimental result interpreter, hypothesis validator, or performance validation engine.

## P2-M13 Completion Summary

- P2-M13.1 Claim Ledger Skill Contract And Artifact Schema: Done
- P2-M13.2 Stub-safe Claim Ledger Wrapper: Done
- P2-M13.3 Explicit Claim Ledger Controller Integration: Done
- P2-M13.4a Real Claude CLI Bounded Claim Ledger Decision Smoke: Done
- P2-M13.4b Real CLI One-Step Claim Ledger run_once Smoke: Done

P2-M13 is now available as an explicit, deterministic, evidence-grounded claim ledger skill.

P2-M13 does not implement manuscript drafting, abstract generation, results / discussion writing, conclusion generation, final claim generation, or experimental result interpretation.

## Claim Ledger Skill Role

`build_claim_ledger` assembles conservative traceable claim ledger artifacts using experiment matrix artifacts, screening results, candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, ranked evidence, and diagnostics.

It is based on:

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

It is not:

- a manuscript writer
- an abstract generator
- a results / discussion writer
- a conclusion generator
- a final claim generator
- an experimental result interpreter
- a hypothesis validator
- a performance validation engine

## Artifact Contract

Required input artifacts:

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

- `experiments/experiment_matrix.md`
- `screening/idea_screening_results.md`
- `ideas/candidate_ideas.md`
- `gaps/gap_map.md`
- `landscape/literature_landscape.md`
- `reports/minimal_topic_to_evidence_report.json`

Output artifacts:

- `claims/claim_ledger.json`
- `claims/claim_ledger.md`
- `claims/claim_ledger_diagnostics.json`

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

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_claim_ledger
missing_experiment_matrix_artifact
missing_claim_ledger_input
claim_ledger_requires_experiment_matrix
claim_ledger_requires_traceable_evidence_basis
claim_ledger_requires_non_final_claim_status
claim_ledger_rejects_validated_result_claim
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

Key constraints:

- Every claim must have `claim_id`.
- Every claim must have `claim_type`.
- Every claim must have `claim_status`.
- Every claim must reference `source_artifacts`.
- Evidence-bearing claims must preserve `evidence_ids`.
- Every claim must have `not_a_final_claim = true`.
- Every claim must have `not_experimentally_validated = true`.
- Every claim must have `requires_human_review = true`.
- Claim ledger artifacts must not assert experimental validation, manuscript conclusions, performance improvement, direct readiness, or final claims as established facts.

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

Forbidden sections:

```markdown
## Manuscript Draft
## Abstract
## Results And Discussion
## Conclusion
## Final Claims
```

These belong to P2-M14 or human manuscript-writing workflows. They do not belong to P2-M13.

## Deterministic Construction Rule

The P2-M13.2 wrapper:

1. Reads experiment matrix, experiment diagnostics, screening results, screening diagnostics, candidate ideas, idea diagnostics, gap map, gap diagnostics, landscape artifacts, enriched Evidence Cards, selected evidence, and ranking diagnostics.
2. Extracts `experiment_matrix_id`, `experiment_id`, `source_idea_id`, `screening_id`, `idea_set_id`, `gap_map_id`, `landscape_id`, `gap_ids`, `evidence_ids`, source paper IDs, screening basis, `hypothesis_under_test`, design variables, characterization targets, limitations, warnings, and diagnostic refs.
3. Generates conservative claim records for literature observations, gap statements, candidate hypotheses, screening assessments, experiment matrix rationale, and limitations.
4. Rejects raw retrieval inputs.
5. Rejects experiment matrices without candidates.
6. Rejects claim records without traceable evidence basis where evidence is required.
7. Rejects claim records written as final, validated, manuscript-ready, or experimental-result claims.
8. Preserves upstream IDs, evidence IDs, source artifacts, warnings, and diagnostic references.
9. Marks every claim as `not_a_final_claim`, `not_experimentally_validated`, and `requires_human_review`.
10. Does not call an LLM.
11. Does not perform manuscript drafting.
12. Does not interpret unperformed experiments as results.

The current claim ledger skill is a conservative evidence-grounded traceability layer, not a manuscript writer, final-claim generator, experimental result interpreter, or hypothesis validation engine.

## Controller Integration Boundary

Default minimal topic-to-evidence chain still stops at minimal report.

Explicit landscape plans still stop at `build_landscape`.

Explicit gap mapping plans still stop at `map_gaps`.

Explicit idea generation plans still stop at `generate_candidate_ideas`.

Explicit screening plans still stop at `screen_novelty_feasibility_risk`.

Explicit experiment matrix plans still stop at `create_experiment_matrix`.

`build_claim_ledger` is executed only when the plan explicitly includes a claim ledger step or a bounded CLI decision explicitly requests `build_claim_ledger`.

PlatformNativeFallbackController:

- executes `build_claim_ledger` only under an explicit claim ledger plan

ClaudeCodeBackedMinimalController:

- can execute `build_claim_ledger` only if a valid `CALL_TOOL build_claim_ledger` decision is received and validated
- validates claim ledger inputs and outputs through the controller gate path

Forbidden automatic extensions:

```text
minimal report -> automatic landscape
landscape -> automatic gap mapping
gap map -> automatic idea generation
candidate ideas -> automatic screening
screening -> automatic experiment matrix
experiment matrix -> automatic claim ledger
claim ledger -> automatic manuscript drafting
```

## Real Claude CLI Smoke Validation

P2-M13.4a:

- Real Claude CLI emitted a valid `CALL_TOOL build_claim_ledger` envelope.
- No skill was executed.
- No controller `run_once` was called.
- No claim ledger artifact was generated.
- `state.json`, `plan.md`, and `audit/artifact_manifest.json` were unchanged by the CLI decision smoke.

P2-M13.4b:

- Real Claude CLI emitted `CALL_TOOL build_claim_ledger`.
- Controller ran exactly one `run_once`.
- Platform executed deterministic `build_claim_ledger` wrapper.
- No `run_until_stop` was called.
- No retrieve / seed / extract / enrich / rank / report / landscape / gap mapping / idea generation / screening / experiment matrix step was executed.
- Claim ledger artifacts were generated and validated.

P2-M13.4b result:

```text
real_cli_invoked: true
exit_code: 0
timed_out: false
parse_success: true
validation_success: true
decision_type / skill_name: CALL_TOOL / build_claim_ledger
run_once_count: 1
run_until_stop_called: false
executed_skills: ["build_claim_ledger"]
```

Generated artifacts:

- `claims/claim_ledger.json`
- `claims/claim_ledger.md`
- `claims/claim_ledger_diagnostics.json`

Artifact checks:

- `schema_version = claim_ledger_v1`
- `claim_count = 7`
- `claim_ledger_id` present
- `experiment_matrix_id` present
- `screening_id` present
- `idea_set_id` present
- `gap_map_id` present
- `landscape_id` present
- claims have `claim_id`, `claim_type`, `claim_status`, and `source_artifacts`
- evidence-bearing claims preserve `evidence_ids`
- all claims set `not_a_final_claim = true`
- all claims set `not_experimentally_validated = true`
- all claims set `requires_human_review = true`
- markdown contains Evidence References
- forbidden manuscript / abstract / results / conclusion / final claims sections absent
- forbidden overclaim phrases absent

Audit, manifest, state, and plan:

- manifest registered all three claim ledger artifacts
- `controller_events = 1`
- `tool_calls = 1`
- `validation_results = 1`
- state includes completed `build_claim_ledger`
- plan contains `build_claim_ledger`

## Test Status

Default tests:

```bash
PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_claim_ledger_run_once_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_claim_ledger_decision_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_explicit_claim_ledger_controller_integration.py -q
# 20 passed

PYTHONPATH=backend pytest backend/tests/test_claim_ledger_skill_wrapper.py -q
# 10 passed

PYTHONPATH=backend pytest backend/tests/test_claim_ledger_skill_contract.py -q
# 5 passed

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_backend.py -q
# 11 passed, 1 skipped

PYTHONPATH=backend pytest backend/tests -q
# 549 passed, 21 skipped
```

Real opt-in smoke:

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_claim_ledger_run_once_smoke.py -q -s
# 1 passed
```

## Safety Boundary

1. Claude CLI does not execute `build_claim_ledger` directly.
2. Claude CLI emits bounded decisions only.
3. The platform validates and executes the wrapper.
4. No real Claude CLI is called in default tests.
5. No LLM is used for claim ledger content generation.
6. No M1-M7 code was modified for P2-M13.
7. No database schema was modified.
8. No raw retrieval artifact can enter claim ledger.
9. No P2-M14+ skill is executable.
10. No manuscript / abstract / results / conclusion / final claim artifact is generated.
11. Claim ledger records remain conservative and bounded.
12. Claim ledger records must not claim experimental validation, hypothesis proof, performance improvement, direct readiness, or manuscript-ready conclusions as established facts.

## Known Limitations

1. Current `build_claim_ledger` is deterministic and conservative.
2. It does not draft manuscript text.
3. It does not generate abstracts.
4. It does not generate results / discussion sections.
5. It does not generate conclusions.
6. It does not generate final claims.
7. It does not interpret experimental results.
8. It does not validate hypotheses experimentally.
9. It does not perform expert claim review.
10. It depends on the quality of experiment matrix artifacts, screening results, candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics.
11. Smoke fixtures are small and do not validate large-scale claim ledger quality.
12. Claim ledger outputs are traceability scaffolds only and require human expert review before any manuscript use.

## Next Step Recommendation

The next recommended step is:

```text
P2-M14.1 Report / Manuscript Drafting Skill Contract And Artifact Schema
```

Do not directly implement manuscript drafting. Start with contract, artifact schema, input boundary, forbidden inputs, allowed manuscript-adjacent outputs, and validation expectations.

P2-M14 should consume claim ledger artifacts, experiment matrix artifacts, screening results, candidate ideas, gap map artifacts, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics. It must not consume raw retrieval artifacts directly.

Claim ledger records from P2-M13 are conservative traceability scaffolds. P2-M14 may later define bounded draft artifacts under explicit constraints, but must not treat candidate hypotheses, experiment matrix entries, or preliminary screening records as validated experimental conclusions.
