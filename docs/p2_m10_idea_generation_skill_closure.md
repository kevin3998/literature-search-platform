# P2-M10 Idea Generation Skill Closure

## Purpose

This document closes P2-M10 Idea Generation Skill after contract definition, deterministic wrapper implementation, explicit controller integration, and real Claude CLI bounded idea generation smoke validation.

本文档用于在 P2-M10 Idea Generation Skill 完成 contract、deterministic wrapper、explicit controller integration 和真实 Claude CLI bounded smoke 后，固定该能力的实现边界和验证结果。

## P2-M10 Completion Summary

- P2-M10.1 Idea Generation Skill Contract And Artifact Schema: Done
- P2-M10.2 Stub-safe Idea Generation Wrapper: Done
- P2-M10.3 Explicit Idea Generation Controller Integration: Done
- P2-M10.4a Real Claude CLI Bounded Idea Generation Decision Smoke: Done
- P2-M10.4b Real CLI One-Step Idea Generation run_once Smoke: Done

P2-M10 is now available as an explicit, deterministic, gap-grounded candidate idea generation skill.

P2-M10 does not implement novelty screening, feasibility screening, risk screening, experiment planning, or manuscript drafting.

## Idea Generation Skill Role

`generate_candidate_ideas` assembles unscreened candidate research ideas from validated gap maps, landscape artifacts, enriched Evidence Cards, ranked evidence, and diagnostics.

It is based on:

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

## Artifact Contract

Required input artifacts:

- `gaps/gap_map.json`
- `gaps/gap_coverage_diagnostics.json`
- `landscape/literature_landscape.json`
- `landscape/landscape_coverage_diagnostics.json`
- `evidence/evidence_cards.enriched.json`
- `ranked_evidence/evidence_selection.json`
- `ranked_evidence/coverage_diagnostics.json`

Optional input artifacts:

- `gaps/gap_map.md`
- `landscape/literature_landscape.md`
- `reports/minimal_topic_to_evidence_report.json`

Output artifacts:

- `ideas/candidate_ideas.json`
- `ideas/candidate_ideas.md`
- `ideas/idea_generation_diagnostics.json`

Forbidden inputs:

- `retrieval/...`
- raw chunks
- raw papers
- `evidence/evidence_card_seeds.json`
- `evidence/evidence_cards.initial.json`
- unvalidated landscape markdown without landscape JSON
- unvalidated gap markdown without gap JSON

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_idea_generation
missing_gap_map_artifact
idea_generation_requires_evidence_references
candidate_idea_requires_gap_basis
unsupported_candidate_idea_claim
```

## Candidate Ideas JSON Schema

The stable schema version is:

```text
candidate_ideas_v1
```

Core fields:

- `task_id`
- `topic`
- `idea_set_id`
- `input_artifacts`
- `gap_map_id`
- `landscape_id`
- `evidence_ids`
- `source_paper_ids`
- `ideas`
- `generation_scope`
- `constraints`
- `limitations`
- `warnings`
- `created_at`
- `schema_version`

Each candidate idea has:

- `idea_id`
- `title`
- `summary`
- `idea_type`
- `gap_basis`
- `evidence_basis`
- `rationale`
- `expected_contribution`
- `assumptions`
- `constraints`
- `not_yet_screened = true`
- `requires_novelty_screening = true`
- `requires_feasibility_screening = true`
- `warnings`

Key constraints:

- Every idea must have `gap_basis`.
- Every idea must have `evidence_basis`.
- Every idea must reference at least one `gap_id`.
- Every idea must reference at least one `evidence_id`.
- Every idea must be marked `not_yet_screened = true`.
- Every idea must require novelty and feasibility screening.
- Ideas must not claim novelty, feasibility, risk status, experimental validation, or performance improvement as established facts.

## Candidate Ideas Markdown Structure

Allowed sections:

```markdown
# Candidate Ideas

## Scope

## Gap And Evidence Base

## Candidate Idea Set

## Assumptions And Constraints

## Required Downstream Screening

## Limitations

## Evidence References
```

Forbidden sections:

```markdown
## Novelty Screening
## Feasibility Screening
## Risk Screening
## Experiment Plan
## Manuscript Draft
```

These belong to P2-M11 and later modules, not P2-M10.

## Deterministic Construction Rule

The P2-M10.2 wrapper:

1. Reads gap map, gap diagnostics, landscape artifacts, enriched Evidence Cards, selected evidence, and ranking diagnostics.
2. Extracts `gap_ids`, `gap_types`, gap basis, `landscape_id`, landscape clusters, `evidence_ids`, `paper_ids`, and coverage warnings.
3. Generates at most one conservative candidate idea per valid gap.
4. Skips weak gaps without evidence basis and records diagnostics.
5. Maps `gap_type` to conservative `idea_type`.
6. Uses template-based candidate idea titles and summaries.
7. Preserves `gap_basis` and `evidence_basis` for every idea.
8. Marks ideas as `not_yet_screened` and requiring novelty / feasibility screening.
9. Rejects forbidden novelty / feasibility / validation claims.
10. Uses no LLM generation and no free-form brainstorming.

The current idea generation skill is a conservative gap-grounded candidate assembly layer, not a novelty evaluator or experiment planner.

## Controller Integration Boundary

Default minimal topic-to-evidence chain still stops at minimal report.

Explicit landscape plans still stop at `build_landscape`.

Explicit gap mapping plans still stop at `map_gaps`.

`generate_candidate_ideas` is executed only when the plan explicitly includes an idea generation step or a bounded CLI decision explicitly requests `generate_candidate_ideas`.

PlatformNativeFallbackController:

- executes `generate_candidate_ideas` only under an explicit idea generation plan
- validates idea generation inputs before execution
- validates candidate idea outputs after execution

ClaudeCodeBackedMinimalController:

- can execute `generate_candidate_ideas` only if a valid `CALL_TOOL generate_candidate_ideas` decision is received and validated
- uses the same platform wrapper and validation gates as other registered skills
- does not call real Claude CLI in default tests

Forbidden automatic extensions:

```text
minimal report -> automatic landscape
landscape -> automatic gap mapping
gap map -> automatic idea generation
candidate ideas -> automatic novelty / feasibility screening
```

## Real Claude CLI Smoke Validation

P2-M10.4a:

- Real Claude CLI emitted a valid `CALL_TOOL generate_candidate_ideas` envelope.
- No skill was executed.
- No controller `run_once` was called.
- No idea artifact was generated.

P2-M10.4b:

- Real Claude CLI emitted `CALL_TOOL generate_candidate_ideas`.
- Controller ran exactly one `run_once`.
- Platform executed deterministic `generate_candidate_ideas` wrapper.
- No `run_until_stop` was called.
- No retrieve / seed / extract / enrich / rank / report / landscape / gap mapping step was executed.
- Idea artifacts were generated and validated.

P2-M10.4b result:

```text
real_cli_invoked: true
exit_code: 0
timed_out: false
parse_success: true
validation_success: true
decision_type / skill_name: CALL_TOOL / generate_candidate_ideas
run_once_count: 1
run_until_stop_called: false
executed_skills: ["generate_candidate_ideas"]
```

Generated artifacts:

- `ideas/candidate_ideas.json`
- `ideas/candidate_ideas.md`
- `ideas/idea_generation_diagnostics.json`

Artifact checks:

- `schema_version = candidate_ideas_v1`
- `idea_set_id` present
- `gap_map_id = gap_map_idea_run_once`
- `landscape_id = landscape_idea_run_once`
- `evidence_ids = ["ecard_001", "ecard_002"]`
- `idea_count = 1`
- every idea has gap basis
- every idea has evidence basis
- every idea has `not_yet_screened = true`
- every idea has `requires_novelty_screening = true`
- every idea has `requires_feasibility_screening = true`
- forbidden claims absent
- validation errors absent
- markdown contains Evidence References
- forbidden markdown sections absent
- coverage / gap warnings preserved

## Test Status

Default tests:

```bash
PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_idea_generation_run_once_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_idea_generation_decision_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_explicit_idea_generation_controller_integration.py -q
# 12 passed

PYTHONPATH=backend pytest backend/tests/test_idea_generation_skill_wrapper.py -q
# 11 passed

PYTHONPATH=backend pytest backend/tests/test_idea_generation_skill_contract.py -q
# 6 passed

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_backend.py -q
# 11 passed, 1 skipped

PYTHONPATH=backend pytest backend/tests -q
# 447 passed, 15 skipped
```

Real opt-in smoke:

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_idea_generation_run_once_smoke.py -q -s
# 1 passed in 12.14s
```

## Safety Boundary

1. Claude CLI does not execute `generate_candidate_ideas` directly.
2. Claude CLI emits bounded decisions only.
3. Platform validates and executes the wrapper.
4. No real Claude CLI is called in default tests.
5. No LLM is used for idea content generation.
6. No M1-M7 code was modified.
7. No database schema was modified.
8. No raw retrieval artifact can enter idea generation.
9. No P2-M11+ skill is executable.
10. No novelty / feasibility / risk / experiment / manuscript artifact is generated.
11. Candidate ideas remain unscreened.
12. Candidate ideas must not claim novelty, feasibility, or validation as established facts.

## Known Limitations

1. Current `generate_candidate_ideas` is deterministic and conservative.
2. It does not perform creative brainstorming.
3. It does not evaluate novelty.
4. It does not evaluate feasibility.
5. It does not rank risks.
6. It does not design experiments.
7. It does not draft manuscripts.
8. It depends on the quality of gap maps, landscape artifacts, enriched Evidence Cards, and diagnostics.
9. Smoke fixtures are small and do not validate large-scale idea quality.
10. Ideas are candidate directions only and require downstream screening.

## Next Step Recommendation

The next recommended step is:

```text
P2-M11.1 Novelty / Feasibility / Risk Screening Skill Contract And Artifact Schema
```

Do not directly implement novelty / feasibility / risk screening. Start with the contract, artifact schema, input boundary, forbidden inputs, and validation expectations.

P2-M11 should consume candidate idea artifacts, gap map artifacts, landscape artifacts, enriched Evidence Cards, selected evidence, and diagnostics. It must not consume raw retrieval artifacts directly.

Candidate ideas from P2-M10 are unscreened. P2-M11 may later evaluate novelty, feasibility, and risk under explicit constraints.
