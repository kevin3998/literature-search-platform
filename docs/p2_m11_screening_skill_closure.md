# P2-M11 Novelty / Feasibility / Risk Screening Skill Closure

## Current Active Implementation Note

This closure records the original deterministic P2-M11 milestone. The active
implementation has since been upgraded to LLM-assisted local evidence triage:

- active schema: `idea_screening_v2`
- active analysis mode: `llm_assisted_local_evidence_triage`
- LLM unavailable behavior: `BLOCKED` with `llm_required_for_screening`
- external novelty search: `not_performed`

The original safety boundary remains in force: P2-M11 still cannot generate
experiment plans, experimental protocols, manuscript drafts, final claims, or
final novelty / feasibility / risk conclusions.

## Purpose

This document closes P2-M11 Novelty / Feasibility / Risk Screening Skill after contract definition, deterministic wrapper implementation, explicit controller integration, and real Claude CLI bounded screening smoke validation.

本文档用于在 P2-M11 Novelty / Feasibility / Risk Screening Skill 完成 contract、deterministic wrapper、explicit controller integration 和真实 Claude CLI bounded smoke 后，固定该能力的实现边界和验证结果。

## P2-M11 Completion Summary

- P2-M11.1 Novelty / Feasibility / Risk Screening Skill Contract And Artifact Schema: Done
- P2-M11.2 Stub-safe Screening Wrapper: Done
- P2-M11.3 Explicit Screening Controller Integration: Done
- P2-M11.4a Real Claude CLI Bounded Screening Decision Smoke: Done
- P2-M11.4b Real CLI One-Step Screening run_once Smoke: Done

P2-M11 is now available as an explicit, deterministic, evidence-grounded screening skill.

P2-M11 does not implement experiment planning, experimental protocols, manuscript drafting, claim ledger construction, or final recommendations.

## Screening Skill Role

`screen_novelty_feasibility_risk` assembles conservative screening results for candidate ideas using candidate idea artifacts, gap maps, landscape artifacts, enriched Evidence Cards, ranked evidence, and diagnostics.

It is based on:

- `ideas/candidate_ideas.json`
- `ideas/idea_generation_diagnostics.json`
- optional `ideas/candidate_ideas.md`
- `gaps/gap_map.json`
- `gaps/gap_coverage_diagnostics.json`
- optional `gaps/gap_map.md`
- `landscape/literature_landscape.json`
- `landscape/landscape_coverage_diagnostics.json`
- optional `landscape/literature_landscape.md`
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

## Artifact Contract

Required input artifacts:

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

- `ideas/candidate_ideas.md`
- `gaps/gap_map.md`
- `landscape/literature_landscape.md`
- `reports/minimal_topic_to_evidence_report.json`

Output artifacts:

- `screening/idea_screening_results.json`
- `screening/idea_screening_results.md`
- `screening/screening_diagnostics.json`

Forbidden inputs:

- `retrieval/...`
- raw chunks
- raw papers
- `evidence/evidence_card_seeds.json`
- `evidence/evidence_cards.initial.json`
- unvalidated landscape markdown without landscape JSON
- unvalidated gap markdown without gap JSON
- unvalidated idea markdown without `candidate_ideas.json`

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_screening
missing_candidate_ideas_artifact
missing_screening_input
screening_requires_gap_and_evidence_basis
screening_requires_unscreened_candidate_ideas
unsupported_screening_claim
```

## Screening JSON Schema

The stable schema version is:

```text
idea_screening_v2
```

Core fields:

- `task_id`
- `topic`
- `screening_id`
- `input_artifacts`
- `idea_set_id`
- `gap_map_id`
- `landscape_id`
- `evidence_ids`
- `source_paper_ids`
- `screened_ideas`
- `screening_scope`
- `screening_policy`
- `limitations`
- `warnings`
- `created_at`
- `schema_version`

Each screened idea has:

- `idea_id`
- `source_idea_title`
- `gap_ids`
- `evidence_ids`
- `novelty`
- `feasibility`
- `risk`
- `overall_screening`
- `not_an_experiment_plan = true`
- `not_a_validated_claim = true`
- `warnings`

Key constraints:

- Every screened idea must reference a source `idea_id`.
- Every screened idea must preserve `gap_ids`.
- Every screened idea must preserve `evidence_ids`.
- Novelty / feasibility / risk fields must contain basis or limitations.
- Every screened idea must have `not_an_experiment_plan = true`.
- Every screened idea must have `not_a_validated_claim = true`.
- Screening results must not claim final novelty, feasibility, risk status, experimental validation, or performance improvement as established facts.

## Screening Markdown Structure

Allowed sections:

```markdown
# Idea Screening Results

## Scope

## Candidate Ideas Screened

## Novelty Screening Summary

## Feasibility Screening Summary

## Risk Screening Summary

## Required Follow-up Checks

## Limitations

## Evidence References
```

Forbidden sections:

```markdown
## Experiment Plan
## Experimental Protocol
## Manuscript Draft
## Final Claims
```

These belong to P2-M12 and later modules, not P2-M11.

## Deterministic Construction Rule

The P2-M11.2 wrapper:

1. Reads candidate ideas, idea diagnostics, gap map, gap diagnostics, landscape artifacts, enriched Evidence Cards, selected evidence, and ranking diagnostics.
2. Extracts `idea_id`, idea title, `idea_type`, `gap_basis`, `evidence_basis`, `gap_ids`, `evidence_ids`, `source_paper_ids`, coverage warnings, diagnostic refs, and screening flags.
3. Generates one conservative screening result per valid candidate idea.
4. Rejects candidate ideas without gap / evidence basis.
5. Rejects candidate ideas that are not marked as unscreened.
6. Keeps novelty status conservative, usually `requires_external_search` or `insufficient_evidence`.
7. Keeps feasibility status conservative, usually `requires_expert_review` or `insufficient_evidence`.
8. Keeps risk status conservative, usually `requires_risk_review`.
9. Marks every screened idea as `not_an_experiment_plan` and `not_a_validated_claim`.
10. Rejects forbidden novelty / feasibility / validation / final claim phrases.
11. Uses no LLM generation, external novelty search, real feasibility review, or real risk assessment.

The current screening skill is a conservative evidence-grounded screening assembly layer, not a final novelty evaluator, feasibility validator, experiment planner, or manuscript claim generator.

## Controller Integration Boundary

Default minimal topic-to-evidence chain still stops at minimal report.

Explicit landscape plans still stop at `build_landscape`.

Explicit gap mapping plans still stop at `map_gaps`.

Explicit idea generation plans still stop at `generate_candidate_ideas`.

`screen_novelty_feasibility_risk` is executed only when the plan explicitly includes a screening step or a bounded CLI decision explicitly requests `screen_novelty_feasibility_risk`.

PlatformNativeFallbackController:

- executes `screen_novelty_feasibility_risk` only under an explicit screening plan
- validates screening inputs before execution
- validates screening outputs after execution

ClaudeCodeBackedMinimalController:

- can execute `screen_novelty_feasibility_risk` only if a valid `CALL_TOOL screen_novelty_feasibility_risk` decision is received and validated
- uses the same platform wrapper and validation gates as other registered skills
- does not call real Claude CLI in default tests

Forbidden automatic extensions:

```text
minimal report -> automatic landscape
landscape -> automatic gap mapping
gap map -> automatic idea generation
candidate ideas -> automatic screening
screening -> automatic experiment planning
screening -> automatic manuscript drafting
```

## Real Claude CLI Smoke Validation

P2-M11.4a:

- Real Claude CLI emitted a valid `CALL_TOOL screen_novelty_feasibility_risk` envelope.
- No skill was executed.
- No controller `run_once` was called.
- No screening artifact was generated.

P2-M11.4b:

- Real Claude CLI emitted `CALL_TOOL screen_novelty_feasibility_risk`.
- Controller ran exactly one `run_once`.
- Platform executed deterministic `screen_novelty_feasibility_risk` wrapper.
- No `run_until_stop` was called.
- No retrieve / seed / extract / enrich / rank / report / landscape / gap mapping / idea generation step was executed.
- Screening artifacts were generated and validated.

P2-M11.4b result:

```text
real_cli_invoked: true
exit_code: 0
timed_out: false
parse_success: true
validation_success: true
decision_type / skill_name: CALL_TOOL / screen_novelty_feasibility_risk
run_once_count: 1
run_until_stop_called: false
executed_skills: ["screen_novelty_feasibility_risk"]
```

Generated artifacts:

- `screening/idea_screening_results.json`
- `screening/idea_screening_results.md`
- `screening/screening_diagnostics.json`

Artifact checks:

- `schema_version = idea_screening_v2`
- `screening_id` present
- `idea_set_id` present
- `gap_map_id` present
- `landscape_id` present
- `evidence_ids` nonempty
- `screened_ideas` nonempty
- every screened idea preserves `idea_id` / `gap_ids` / `evidence_ids`
- novelty / feasibility / risk fields have basis or limitations
- `novelty.status = requires_external_search`
- `feasibility.status = requires_expert_review`
- `risk.status = requires_risk_review`
- markdown contains Evidence References
- forbidden markdown sections absent
- forbidden claims absent

## Test Status

Default tests:

```bash
PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_screening_run_once_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_screening_decision_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_explicit_screening_controller_integration.py -q
# 13 passed

PYTHONPATH=backend pytest backend/tests/test_screening_skill_wrapper.py -q
# 13 passed

PYTHONPATH=backend pytest backend/tests/test_screening_skill_contract.py -q
# 6 passed

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_backend.py -q
# 11 passed, 1 skipped

PYTHONPATH=backend pytest backend/tests -q
# 479 passed, 17 skipped
```

Real opt-in smoke:

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_screening_run_once_smoke.py -q -s
# 1 passed
```

## Safety Boundary

1. Claude CLI does not execute `screen_novelty_feasibility_risk` directly.
2. Claude CLI emits bounded decisions only.
3. Platform validates and executes the wrapper.
4. No real Claude CLI is called in default tests.
5. No LLM is used for screening content generation.
6. No M1-M7 code was modified.
7. No database schema was modified.
8. No raw retrieval artifact can enter screening.
9. No P2-M12+ skill is executable.
10. No experiment plan / protocol / manuscript / final claim artifact is generated.
11. Screening results remain conservative and bounded.
12. Screening results must not claim novelty, feasibility, risk status, or validation as established facts.

## Known Limitations

1. Current `screen_novelty_feasibility_risk` is deterministic and conservative.
2. It does not perform external novelty search.
3. It does not perform real expert feasibility review.
4. It does not perform real risk assessment.
5. It does not design experiments.
6. It does not produce experimental protocols.
7. It does not draft manuscripts.
8. It does not produce final claims.
9. It depends on the quality of candidate ideas, gap maps, landscape artifacts, enriched Evidence Cards, and diagnostics.
10. Smoke fixtures are small and do not validate large-scale screening quality.
11. Screening results are structured preliminary assessments only and require downstream review.

## Next Step Recommendation

The next recommended step is:

```text
P2-M12.1 Experiment Matrix Skill Contract And Artifact Schema
```

Do not directly implement experiment matrix generation. Start with contract, artifact schema, input boundary, forbidden inputs, and validation expectations.

P2-M12 should consume screening results, candidate ideas, gap map artifacts, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics. It must not consume raw retrieval artifacts directly.

Screening results from P2-M11 are conservative preliminary assessments. P2-M12 may later define experiment matrix artifacts under explicit constraints, but must not treat screening results as final validated claims.
