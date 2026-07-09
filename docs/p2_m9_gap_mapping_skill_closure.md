# P2-M9 Gap Mapping Skill Closure

## Purpose

This document closes P2-M9 Gap Mapping Skill after contract definition, deterministic wrapper implementation, explicit controller integration, and real Claude CLI bounded gap mapping smoke validation.

本文档用于在 P2-M9 Gap Mapping Skill 完成 contract、deterministic wrapper、explicit controller integration 和真实 Claude CLI bounded smoke 后，固定该能力的实现边界和验证结果。

## P2-M9 Completion Summary

- P2-M9.1 Gap Mapping Skill Contract And Artifact Schema: Done
- P2-M9.2 Stub-safe Gap Mapping Wrapper: Done
- P2-M9.3 Explicit Gap Mapping Controller Integration: Done
- P2-M9.4a Real Claude CLI Bounded Gap Mapping Decision Smoke: Done
- P2-M9.4b Real CLI One-Step Gap Mapping run_once Smoke: Done

P2-M9 is now available as an explicit, deterministic, evidence-grounded gap mapping skill.

P2-M9 does not implement candidate idea generation, novelty screening, feasibility screening, experiment planning, or manuscript drafting.

## Gap Mapping Skill Role

`map_gaps` identifies evidence-structure gaps from landscape artifacts, enriched Evidence Cards, ranked evidence, and coverage diagnostics.

It is based on:

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

## Artifact Contract

Required input artifacts:

- `landscape/literature_landscape.json`
- `landscape/landscape_coverage_diagnostics.json`
- `evidence/evidence_cards.enriched.json`
- `ranked_evidence/evidence_selection.json`
- `ranked_evidence/coverage_diagnostics.json`

Optional input artifacts:

- `landscape/literature_landscape.md`
- `reports/minimal_topic_to_evidence_report.json`

Output artifacts:

- `gaps/gap_map.json`
- `gaps/gap_map.md`
- `gaps/gap_coverage_diagnostics.json`

Forbidden inputs:

- `retrieval/...`
- raw chunks
- raw papers
- `evidence/evidence_card_seeds.json`
- `evidence/evidence_cards.initial.json`
- unvalidated landscape markdown without landscape JSON

Primary validation errors:

```text
raw_retrieval_candidates_not_allowed_for_gap_mapping
missing_landscape_artifact
gap_mapping_requires_evidence_references
```

## Gap Map JSON Schema

The stable schema version is:

```text
gap_map_v1
```

Core fields:

- `task_id`
- `topic`
- `gap_map_id`
- `input_artifacts`
- `landscape_id`
- `evidence_ids`
- `source_paper_ids`
- `gap_axes`
- `gaps`
- `coverage`
- `supporting_evidence`
- `limitations`
- `warnings`
- `created_at`
- `schema_version`

Key constraints:

- Every gap must have basis.
- Every gap must set `not_an_idea = true`.
- Gap basis must trace to evidence IDs, landscape clusters, coverage warnings, or diagnostic references.
- Supporting evidence must reference `gap_ids`.
- Coverage warnings must be preserved.
- Unsupported opportunity claims are not allowed.

## Gap Map Markdown Structure

Allowed sections:

```markdown
# Gap Map

## Scope

## Evidence And Landscape Base

## Gap Axes

## Identified Evidence Gaps

## Coverage Diagnostics

## Limitations

## Evidence References
```

Forbidden sections:

```markdown
## Candidate Ideas
## Proposed Research Directions
## Novelty Screening
## Feasibility Screening
## Experiment Plan
## Manuscript Draft
```

These belong to P2-M10 and later modules, not P2-M9.

## Deterministic Construction Rule

The P2-M9.2 wrapper:

1. Reads landscape JSON, landscape diagnostics, enriched Evidence Cards, selected evidence, and ranking diagnostics.
2. Extracts `landscape_id`, cluster IDs, evidence IDs, paper IDs, source types, roles, axis values, and coverage warnings.
3. Generates gaps only from verifiable diagnostics.
4. Supports gap sources including missing roles, dominant source warning, missing source types, sparse clusters, single-paper dominance, and sparse axis coverage.
5. Requires every gap to include basis.
6. Marks every gap with `not_an_idea = true`.
7. Links supporting evidence back to gap IDs.
8. Preserves coverage diagnostics and warnings.
9. Uses no semantic gap reasoning and no LLM generation.

The current gap mapping skill is a conservative evidence-structure diagnostic layer, not an idea generator.

## Controller Integration Boundary

Default minimal topic-to-evidence chain still stops at minimal report.

Explicit landscape plans still stop at `build_landscape`.

`map_gaps` is executed only when the plan explicitly includes a gap mapping step or a bounded CLI decision explicitly requests `map_gaps`.

PlatformNativeFallbackController:

- executes `map_gaps` only under an explicit gap mapping plan
- validates gap mapping inputs before execution
- validates gap map outputs after execution

ClaudeCodeBackedMinimalController:

- can execute `map_gaps` only if a valid `CALL_TOOL map_gaps` decision is received and validated
- uses the same platform wrapper and validation gates as other registered skills
- does not add real Claude CLI gap mapping smoke tests to default tests

Forbidden automatic extensions:

```text
minimal report -> automatic gap mapping
landscape -> automatic gap mapping
gap map -> automatic idea generation
```

## Real Claude CLI Smoke Validation

P2-M9.4a:

- Real Claude CLI emitted a valid `CALL_TOOL map_gaps` envelope.
- No skill was executed.
- No controller `run_once` was called.
- No gap artifact was generated.

P2-M9.4b:

- Real Claude CLI emitted `CALL_TOOL map_gaps`.
- Controller ran exactly one `run_once`.
- Platform executed deterministic `map_gaps` wrapper.
- No `run_until_stop` was called.
- No retrieve / seed / extract / enrich / rank / report / landscape step was executed.
- Gap artifacts were generated and validated.

P2-M9.4b result:

```text
real_cli_invoked: true
exit_code: 0
timed_out: false
parse_success: true
validation_success: true
decision_type / skill_name: CALL_TOOL / map_gaps
run_once_count: 1
run_until_stop_called: false
executed_skills: ["map_gaps"]
```

Generated artifacts:

- `gaps/gap_map.json`
- `gaps/gap_map.md`
- `gaps/gap_coverage_diagnostics.json`

Artifact checks:

- `schema_version = gap_map_v1`
- `landscape_id = landscape_gap_run_once`
- `evidence_ids = ["ecard_001", "ecard_002"]`
- `gap_count = 7`
- every gap has basis
- every gap has `not_an_idea = true`
- supporting evidence references gap IDs
- markdown contains Evidence References
- forbidden markdown sections absent
- coverage warnings preserved

## Test Status

Default tests:

```bash
PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_gap_mapping_run_once_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_gap_mapping_decision_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_explicit_gap_mapping_controller_integration.py -q
# 8 passed

PYTHONPATH=backend pytest backend/tests/test_gap_mapping_skill_wrapper.py -q
# 10 passed

PYTHONPATH=backend pytest backend/tests/test_gap_mapping_skill_contract.py -q
# 6 passed

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_backend.py -q
# 11 passed, 1 skipped

PYTHONPATH=backend pytest backend/tests -q
# 418 passed, 13 skipped
```

Real opt-in smoke:

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_gap_mapping_run_once_smoke.py -q -s
# 1 passed
```

The real opt-in smoke is documented here as prior validation. It was not rerun during this documentation-only closure pass.

## Safety Boundary

1. Claude CLI does not execute `map_gaps` directly.
2. Claude CLI emits bounded decision only.
3. Platform validates and executes the wrapper.
4. No real Claude CLI is called in default tests.
5. No LLM is used for gap content generation.
6. No M1-M7 code was modified.
7. No database schema was modified.
8. No raw retrieval artifact can enter gap mapping.
9. No P2-M10+ skill is executable as part of P2-M9.
10. No candidate ideas / novelty / feasibility / experiment / manuscript artifact is generated.

## Known Limitations

1. Current `map_gaps` is deterministic and conservative.
2. It does not perform semantic gap reasoning.
3. It does not generate candidate ideas.
4. It does not evaluate novelty or feasibility.
5. It depends on the quality of landscape artifacts, enriched Evidence Cards, and coverage diagnostics.
6. Smoke fixtures are small and do not validate large-scale gap mapping quality.
7. Coverage warnings may be expected when input evidence is sparse.
8. Gaps are evidence-structure gaps, not research proposals.

## Next Step Recommendation

The recommended next step is:

```text
P2-M10.1: Idea Generation Skill Contract And Artifact Schema
```

Do not directly implement idea generation. Start with contract, artifact schema, input boundary, forbidden inputs, and validation expectations.

P2-M10 should consume gap map artifacts, landscape artifacts, enriched Evidence Cards, selected evidence, and coverage diagnostics. It must not consume raw retrieval artifacts directly.

Candidate ideas must be separated from gap records. P2-M9 describes evidence gaps; P2-M10 may later generate candidate ideas from validated gaps under explicit constraints.
