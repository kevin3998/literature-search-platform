# P2-M12 Experiment Matrix Skill Closure

## Purpose

This document closes P2-M12 Experiment Matrix Skill after contract definition, deterministic wrapper implementation, explicit controller integration, and real Claude CLI bounded experiment matrix smoke validation.

It fixes the implementation boundary and validation record for P2-M12. The skill is available as a bounded, deterministic, evidence-grounded experiment matrix assembly layer. It is not a wet-lab protocol generator, step-by-step procedure generator, synthesis recipe generator, safety protocol generator, claim ledger builder, manuscript drafter, or final claim generator.

## P2-M12 Completion Summary

- P2-M12.1 Experiment Matrix Skill Contract And Artifact Schema: Done
- P2-M12.2 Stub-safe Experiment Matrix Wrapper: Done
- P2-M12.3 Explicit Experiment Matrix Controller Integration: Done
- P2-M12.4a Real Claude CLI Bounded Experiment Matrix Decision Smoke: Done
- P2-M12.4b Real CLI One-Step Experiment Matrix run_once Smoke: Done

P2-M12 is now available as an explicit, deterministic, evidence-grounded experiment matrix skill.

P2-M12 does not implement claim ledger construction, manuscript drafting, final claim generation, wet-lab protocols, step-by-step synthesis recipes, or safety protocols.

## Experiment Matrix Skill Role

`create_experiment_matrix` assembles conservative experiment matrix artifacts using screening results, candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, ranked evidence, and diagnostics.

It is based on:

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
- raw chunks
- raw papers
- unvalidated seeds
- initial cards without enrichment
- unvalidated landscape markdown without landscape JSON
- unvalidated gap markdown without gap JSON
- unvalidated idea markdown without `candidate_ideas.json`
- unvalidated screening markdown without `idea_screening_results.json`

## Artifact Contract

Required input artifacts:

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

- `screening/idea_screening_results.md`
- `ideas/candidate_ideas.md`
- `gaps/gap_map.md`
- `landscape/literature_landscape.md`
- `reports/minimal_topic_to_evidence_report.json`

Output artifacts:

- `experiments/experiment_matrix.json`
- `experiments/experiment_matrix.md`
- `experiments/experiment_matrix_diagnostics.json`

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

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_experiment_matrix
missing_screening_results_artifact
missing_experiment_matrix_input
experiment_matrix_requires_screened_ideas
experiment_matrix_requires_gap_and_evidence_basis
experiment_matrix_requires_conservative_screening_status
unsupported_experiment_matrix_claim
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

Each design variable has:

- `variable_id`
- `name`
- `role`
- `allowed_level_description`
- `rationale`
- `evidence_refs`
- `constraints`
- `not_a_stepwise_instruction = true`

Key constraints:

- Every experiment candidate must reference `source_idea_id`.
- Every experiment candidate must reference `screening_basis`.
- Every experiment candidate must preserve `gap_ids` and `evidence_ids`.
- Every experiment candidate must have `not_a_protocol = true`.
- Every experiment candidate must have `not_a_validated_claim = true`.
- Every experiment candidate must have `requires_expert_review = true`.
- Every design variable must have `not_a_stepwise_instruction = true`.
- Experiment matrix artifacts must not claim feasibility, validation, performance improvement, final conclusions, or direct experimental readiness as established facts.

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

Forbidden sections:

```markdown
## Experimental Protocol
## Step-by-step Procedure
## Synthesis Recipe
## Safety Protocol
## Manuscript Draft
## Final Claims
```

These belong to downstream human experiment design, safety review, claim ledger construction, or writing workflows. They do not belong to P2-M12.

## Deterministic Construction Rule

The P2-M12.2 wrapper:

1. Reads screening results, screening diagnostics, candidate ideas, idea diagnostics, gap map, gap diagnostics, landscape artifacts, enriched Evidence Cards, selected evidence, and ranking diagnostics.
2. Extracts `screening_id`, `idea_set_id`, source idea, screened idea refs, `gap_ids`, `evidence_ids`, source paper IDs, conservative screening statuses, required follow-up, limitations, and diagnostic refs.
3. Generates at most one conservative experiment candidate per valid screened idea.
4. Rejects screened ideas without gap / evidence basis.
5. Rejects non-conservative screening statuses or final-claim style screening records.
6. Creates high-level experiment objectives and hypotheses under test without treating them as validated claims.
7. Creates only high-level design variables, controls, comparison groups, characterization targets, data categories, decision criteria, constraints, and risk notes.
8. Marks every experiment candidate as `not_a_protocol`, `not_a_validated_claim`, and `requires_expert_review`.
9. Marks every design variable as `not_a_stepwise_instruction`.
10. Rejects forbidden protocol, final claim, feasibility, validation, readiness, and performance-improvement phrases.
11. Uses no LLM generation, real experiment planning, wet-lab protocol generation, or step-by-step procedure generation.

The current experiment matrix skill is a conservative evidence-grounded matrix assembly layer, not a protocol generator, safety procedure generator, final claim generator, or manuscript drafting tool.

## Controller Integration Boundary

Default minimal topic-to-evidence chain still stops at minimal report.

Explicit landscape plans still stop at `build_landscape`.

Explicit gap mapping plans still stop at `map_gaps`.

Explicit idea generation plans still stop at `generate_candidate_ideas`.

Explicit screening plans still stop at `screen_novelty_feasibility_risk`.

`create_experiment_matrix` is executed only when the plan explicitly includes an experiment matrix step or a bounded CLI decision explicitly requests `create_experiment_matrix`.

PlatformNativeFallbackController:

- executes `create_experiment_matrix` only under an explicit experiment matrix plan
- does not automatically continue from screening to experiment matrix unless that explicit plan is present

ClaudeCodeBackedMinimalController:

- can execute `create_experiment_matrix` only if a valid `CALL_TOOL create_experiment_matrix` decision is received and validated
- validates experiment matrix inputs and outputs through the controller gate path

Forbidden automatic extensions:

```text
minimal report -> automatic landscape
landscape -> automatic gap mapping
gap map -> automatic idea generation
candidate ideas -> automatic screening
screening -> automatic experiment matrix
experiment matrix -> automatic claim ledger
experiment matrix -> automatic manuscript drafting
```

## Real Claude CLI Smoke Validation

P2-M12.4a:

- Real Claude CLI emitted a valid `CALL_TOOL create_experiment_matrix` envelope.
- No skill was executed.
- No controller `run_once` was called.
- No experiment matrix artifact was generated.
- `state.json`, `plan.md`, and `audit/artifact_manifest.json` were unchanged by the CLI decision smoke.

P2-M12.4b:

- Real Claude CLI emitted `CALL_TOOL create_experiment_matrix`.
- Controller ran exactly one `run_once`.
- Platform executed deterministic `create_experiment_matrix` wrapper.
- No `run_until_stop` was called.
- No retrieve / seed / extract / enrich / rank / report / landscape / gap mapping / idea generation / screening step was executed.
- Experiment matrix artifacts were generated and validated.

P2-M12.4b result:

```text
real_cli_invoked: true
exit_code: 0
timed_out: false
parse_success: true
validation_success: true
decision_type / skill_name: CALL_TOOL / create_experiment_matrix
run_once_count: 1
run_until_stop_called: false
executed_skills: ["create_experiment_matrix"]
```

Generated artifacts:

- `experiments/experiment_matrix.json`
- `experiments/experiment_matrix.md`
- `experiments/experiment_matrix_diagnostics.json`

Artifact checks:

- `schema_version = experiment_matrix_v1`
- `experiment_matrix_id` present
- `screening_id` present
- `idea_set_id` present
- `gap_map_id` present
- `landscape_id` present
- experiment candidate present
- evidence / gap / screening basis preserved
- `not_a_protocol`, `not_a_validated_claim`, `requires_expert_review`, and `not_a_stepwise_instruction` flags set
- markdown contains Evidence References
- forbidden sections absent
- forbidden protocol / final-claim phrases absent

Audit, manifest, state, and plan:

- manifest registered all three experiment artifacts
- `controller_events = 1`
- `tool_calls = 1`
- `validation_results = 1`
- state includes completed `create_experiment_matrix`
- plan contains `create_experiment_matrix`

## Test Status

Default tests:

```bash
PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_experiment_matrix_run_once_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_experiment_matrix_decision_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_explicit_experiment_matrix_controller_integration.py -q
# 15 passed

PYTHONPATH=backend pytest backend/tests/test_experiment_matrix_skill_wrapper.py -q
# 11 passed

PYTHONPATH=backend pytest backend/tests/test_experiment_matrix_skill_contract.py -q
# 6 passed

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_backend.py -q
# 11 passed, 1 skipped

PYTHONPATH=backend pytest backend/tests -q
# 511 passed, 19 skipped
```

Real opt-in smoke:

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_experiment_matrix_run_once_smoke.py -q -s
# 1 passed in 16.00s
```

## Safety Boundary

1. Claude CLI does not execute `create_experiment_matrix` directly.
2. Claude CLI emits bounded decisions only.
3. The platform validates and executes the wrapper.
4. No real Claude CLI is called in default tests.
5. No LLM is used for experiment matrix content generation.
6. No M1-M7 code was modified for P2-M12.
7. No database schema was modified.
8. No raw retrieval artifact can enter experiment matrix.
9. No P2-M13+ skill is executable.
10. No claim ledger / manuscript / final claim artifact is generated.
11. No wet-lab protocol / step-by-step procedure / synthesis recipe / safety protocol is generated.
12. Experiment matrix results remain conservative and bounded.
13. Experiment matrix results must not claim feasibility, validation, direct readiness, or performance improvement as established facts.

## Known Limitations

1. Current `create_experiment_matrix` is deterministic and conservative.
2. It does not perform real experiment planning.
3. It does not generate wet-lab protocols.
4. It does not generate step-by-step synthesis procedures.
5. It does not generate safety protocols.
6. It does not perform expert feasibility review.
7. It does not produce claim ledgers.
8. It does not draft manuscripts.
9. It does not produce final claims.
10. It depends on the quality of screening results, candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, and diagnostics.
11. Smoke fixtures are small and do not validate large-scale experiment matrix quality.
12. Experiment matrix outputs are structured planning scaffolds only and require human expert review before any experimental execution.

## Next Step Recommendation

The next recommended step is:

```text
P2-M13.1 Claim Ledger Skill Contract And Artifact Schema
```

Do not directly implement claim ledger construction. Start with contract, artifact schema, input boundary, forbidden inputs, and validation expectations.

P2-M13 should consume experiment matrix artifacts, screening results, candidate ideas, gap map artifacts, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics. It must not consume raw retrieval artifacts directly.

Experiment matrix results from P2-M12 are conservative planning scaffolds. P2-M13 may later define claim ledger artifacts under explicit constraints, but must not treat experiment matrix entries as validated experimental claims.
