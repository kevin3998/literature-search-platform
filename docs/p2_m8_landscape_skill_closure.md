# P2-M8 Landscape Skill Closure

## Purpose

This document closes P2-M8 Landscape Skill after contract definition, deterministic wrapper implementation, explicit controller integration, and real Claude CLI bounded landscape smoke validation.

本文档用于在 P2-M8 Landscape Skill 完成 contract、deterministic wrapper、explicit controller integration 和真实 Claude CLI bounded smoke 后，固定该能力的实现边界和验证结果。

## P2-M8 Completion Summary

- P2-M8.1 Landscape Skill Contract And Artifact Schema: Done
- P2-M8.2 Stub-safe Landscape Wrapper: Done
- P2-M8.3 Explicit Landscape Controller Integration: Done
- P2-M8.4a Real Claude CLI Bounded Landscape Decision Smoke: Done
- P2-M8.4b Real CLI One-Step Landscape run_once Smoke: Done

P2-M8 is now available as an explicit, deterministic, evidence-grounded landscape skill.

P2-M8 does not implement gap mapping, idea generation, novelty screening, experiment planning, or manuscript drafting.

## Landscape Skill Role

`build_landscape` organizes enriched Evidence Cards and ranked evidence into a topic-level literature landscape.

It is based on:

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

## Artifact Contract

Required input artifacts:

- `evidence/evidence_cards.enriched.json`
- `ranked_evidence/evidence_selection.json`
- `ranked_evidence/coverage_diagnostics.json`

Optional input artifact:

- `reports/minimal_topic_to_evidence_report.json`

Output artifacts:

- `landscape/literature_landscape.json`
- `landscape/literature_landscape.md`
- `landscape/landscape_coverage_diagnostics.json`

Forbidden inputs:

- `retrieval/...`
- raw chunks
- raw papers
- `evidence/evidence_card_seeds.json`
- `evidence/evidence_cards.initial.json`

Forbidden retrieval inputs are rejected with:

```text
raw_retrieval_candidates_not_allowed_for_landscape
```

## Landscape JSON Schema

Core fields:

- `task_id`
- `topic`
- `landscape_id`
- `input_artifacts`
- `evidence_ids`
- `source_paper_ids`
- `landscape_axes`
- `clusters`
- `coverage`
- `representative_evidence`
- `limitations`
- `warnings`
- `created_at`
- `schema_version = landscape_v1`

Key constraints:

- Every cluster must reference `evidence_ids`.
- Representative claims must trace back to `evidence_ids`.
- Coverage warnings must be preserved.
- Unsupported claims are not allowed.

## Landscape Markdown Structure

Allowed sections:

```markdown
# Literature Landscape

## Scope

## Evidence Base

## Landscape Axes

## Main Evidence Clusters

## Coverage Diagnostics

## Limitations

## Evidence References
```

Forbidden sections:

```markdown
## Research Gaps
## Candidate Ideas
## Novelty Screening
## Experiment Plan
## Manuscript Draft
```

These belong to P2-M9 and later modules, not P2-M8.

## Deterministic Construction Rule

The P2-M8.2 wrapper:

1. Reads enriched Evidence Cards and ranked evidence.
2. Extracts `evidence_id`, `paper_id`, source reference, role, material system, defect type, source type, and `normalized_statement` / `verbatim_snippet`.
3. Groups deterministically by `primary_role -> material_system -> defect_type`.
4. Maps missing values to `unknown` and records warnings.
5. Copies representative claims from evidence statements instead of generating them freely.
6. Preserves coverage diagnostics.
7. Uses no semantic clustering and no LLM generation.

The current landscape skill is a conservative evidence organization layer, not an interpretive review generator.

## Controller Integration Boundary

Default minimal topic-to-evidence chain still stops at minimal report.

`build_landscape` is executed only when the plan explicitly includes a landscape step or a bounded CLI decision explicitly requests `build_landscape`.

PlatformNativeFallbackController:

- executes `build_landscape` only under explicit landscape plan
- does not automatically continue from minimal report to landscape

ClaudeCodeBackedMinimalController:

- can execute `build_landscape` only if a valid `CALL_TOOL build_landscape` decision is received and validated
- does not add real Claude CLI landscape smoke to default tests

Forbidden automatic extensions:

```text
minimal report -> automatic landscape
landscape -> automatic gap
landscape -> automatic idea
```

## Real Claude CLI Smoke Validation

P2-M8.4a:

- Real Claude CLI emitted a valid `CALL_TOOL build_landscape` envelope.
- No skill was executed.
- No controller `run_once` was called.
- No landscape artifact was generated.

P2-M8.4b:

- Real Claude CLI emitted `CALL_TOOL build_landscape`.
- Controller ran exactly one `run_once`.
- Platform executed deterministic `build_landscape` wrapper.
- No `run_until_stop` was called.
- No retrieve / seed / extract / enrich / rank / report step was executed.
- Landscape artifacts were generated and validated.

P2-M8.4b result:

```text
real_cli_invoked: true
parse_success: true
validation_success: true
decision_type / skill_name: CALL_TOOL / build_landscape
```

Generated artifacts:

- `landscape/literature_landscape.json`
- `landscape/literature_landscape.md`
- `landscape/landscape_coverage_diagnostics.json`

Artifact checks:

- `schema_version = landscape_v1`
- `evidence_ids = ["ecard_001"]`
- clusters non-empty
- cluster `evidence_ids` present
- representative claims reference `evidence_id`
- markdown contains Evidence References
- forbidden markdown sections absent
- coverage warnings preserved

## Test Status

Default tests:

```bash
PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_landscape_run_once_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_landscape_decision_smoke.py -q
# 1 skipped

PYTHONPATH=backend pytest backend/tests/test_explicit_landscape_controller_integration.py -q
# 7 passed

PYTHONPATH=backend pytest backend/tests/test_landscape_skill_wrapper.py -q
# 8 passed

PYTHONPATH=backend pytest backend/tests/test_landscape_skill_contract.py -q
# 6 passed

PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_backend.py -q
# 11 passed, 1 skipped

PYTHONPATH=backend pytest backend/tests -q
# 394 passed, 11 skipped
```

Real opt-in smoke:

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_landscape_run_once_smoke.py -q -s
# 1 passed in 11.79s
```

## Safety Boundary

1. Claude CLI does not execute `build_landscape` directly.
2. Claude CLI emits bounded decision only.
3. Platform validates and executes the wrapper.
4. No real Claude CLI is called in default tests.
5. No LLM is used for landscape content generation.
6. No M1-M7 code was modified.
7. No database schema was modified.
8. No raw retrieval artifact can enter landscape.
9. No P2-M9+ skill is executable.
10. No gap / idea / novelty / experiment / manuscript artifact is generated.

## Known Limitations

1. Current `build_landscape` is deterministic and conservative.
2. It does not perform semantic clustering.
3. It does not infer research gaps.
4. It does not generate candidate ideas.
5. It depends on quality of enriched Evidence Cards and ranking diagnostics.
6. Smoke fixtures are small and do not validate large-scale landscape quality.
7. Coverage warnings may be expected when input evidence is sparse.

## Next Step Recommendation

Recommended next step:

```text
P2-M9.1: Gap Mapping Skill Contract And Artifact Schema
```

Do not directly implement gap generation.

Start with contract, artifact schema, input boundary, forbidden inputs, and validation expectations.

P2-M9 should consume landscape artifacts, enriched Evidence Cards, selected evidence, and coverage diagnostics. It must not consume raw retrieval artifacts directly.
