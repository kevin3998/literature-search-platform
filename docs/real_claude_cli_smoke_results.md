# Real Claude CLI Smoke Results And Architecture Boundary

## Purpose

This document records the S1-S9 real Claude Code CLI smoke test results, the
current architecture boundary, the test strategy, known warnings, and suggested
next steps.

D1 is documentation only. It does not change controller code, skill wrappers,
validators, M1-M7 modules, frontend code, workflow behavior, or any database.

## Architecture Conclusion

Claude Code CLI is integrated as a local controller backend adapter. It does
not directly execute research skills. It does not directly modify state, plan,
manifest, or database. It emits bounded CLI controller decisions. The platform
parses, validates, executes registered skills, updates artifacts, and records
audit logs.

Claude Code CLI 在本平台中定位为本地 controller backend adapter，而不是
skill executor、database access layer 或自由 shell agent。

The control boundary is:

```text
Claude Code CLI
-> emits cli_controller_contract_v1 envelope
-> A6 parser / validator
-> platform controller
-> registered skill wrapper
-> artifact validation gates
-> state / plan / manifest / audit updates
```

The forbidden boundary crossing is:

```text
Claude Code CLI
-> direct shell execution
-> direct database access
-> direct state / plan / manifest mutation
-> direct report generation from raw retrieval artifacts
```

## Completed Stages

| Stage | Status |
|---|---|
| A1 Research Workspace Model | Done |
| A2 Agent State / Plan Schema | Done |
| A3 Tool / Skill Registry | Done |
| A4 Callable Skill Wrappers | Done |
| A5 Artifact Validation / Audit Gates | Done |
| A6 Claude Code CLI Controller Contract | Done |
| A7a Mock CLI-backed Minimal Agent Loop | Done |
| A7b Real Claude Code CLI Invocation Adapter | Done |
| S1 Real CLI Contract Smoke Test | Done |
| S2 Contract Compliance Hardening | Done |
| S3 CALL_TOOL Contract Smoke | Done |
| S4 One-Step run_once Smoke | Done |
| S5 Two-Step Smoke | Done |
| S6 Three-Step Smoke | Done |
| S7 Four-Step Smoke | Done |
| S8 Five-Step Smoke | Done |
| S9 Minimal Report Smoke | Done |

## S1-S9 Results

| Stage | Purpose | Real CLI Invoked? | Executed Skills | Generated Artifacts | Result | Notes / Warnings |
|---|---|---:|---|---|---|---|
| S1 | Validate real CLI invocation and A6 parse boundary. | Yes | None | None | Expected rejection | Real CLI opt-in call succeeded, but stdout was Markdown fenced JSON. A6 parser returned `UNPARSEABLE_OUTPUT`. Parser was not loosened. |
| S2 | Harden prompt until CLI emits bare JSON. | Yes | None | None | Passed | `parse_success=true`, `validation_success=true`, `decision_type=STOP_BLOCKED`, `format_issue=none`. |
| S3 | Validate contract-level `CALL_TOOL retrieve_sources`. | Yes | None | None | Passed | Real CLI emitted `CALL_TOOL retrieve_sources`. No skill execution; only contract-level `skill_request` validation. |
| S4 | Execute one controlled `run_once`. | Yes | `retrieve_sources` | `retrieval/source_candidate_packet.json`, `retrieval/retrieval_warnings.json` | Passed | Platform executed the skill with fake `acquire_evidence_fn`; no real database retrieval. |
| S5 | Execute two controlled `run_once` steps. | Yes | `retrieve_sources`, `create_evidence_seeds` | S4 artifacts plus `evidence/evidence_card_seeds.json` | Passed | Real CLI observed retrieval artifacts and requested the seed creation step. |
| S6 | Execute three controlled `run_once` steps. | Yes | `retrieve_sources`, `create_evidence_seeds`, `extract_evidence_cards` | S5 artifacts plus `evidence/evidence_cards.initial.json` | Passed | M5 extraction used deterministic fallback; no external LLM/API. |
| S7 | Execute four controlled `run_once` steps. | Yes | `retrieve_sources`, `create_evidence_seeds`, `extract_evidence_cards`, `enrich_evidence_cards` | S6 artifacts plus `evidence/evidence_cards.enriched.json` | Passed | M6 enrichment used fallback. Warning: `role_enrichment_fallback:*`. |
| S8 | Execute five controlled `run_once` steps. | Yes | `retrieve_sources`, `create_evidence_seeds`, `extract_evidence_cards`, `enrich_evidence_cards`, `rank_evidence` | S7 artifacts plus `ranked_evidence/evidence_selection.json`, `ranked_evidence/coverage_diagnostics.json` | Passed | `ranking_validation_status=degraded_with_warning`. Expected with a single text-evidence fixture. |
| S9 | Execute minimal report step after ranked evidence exists. | Yes | S8 skills plus `build_minimal_topic_to_evidence_report` | S8 artifacts plus `reports/minimal_topic_to_evidence_report.md`, `reports/minimal_topic_to_evidence_report.json` | Passed | `report_input_gate_status=passed`, `report_result_status=success`, `report_contains_evidence_references=true`, `report_scope_valid=true`. |

### S8 Ranking Warnings

The S8 fixture intentionally used one text evidence item. The following
warnings are acceptable in that smoke context and do not indicate controller
failure:

- `missing_required_roles`
- `dominant_paper_warning`
- `missing_figure_source_type`
- `missing_table_source_type`
- `missing_caption_source_type`

### S9 Scope Confirmation

S9 generated only:

- `reports/minimal_topic_to_evidence_report.md`
- `reports/minimal_topic_to_evidence_report.json`

S9 did not generate:

- landscape
- gap map
- candidate ideas
- novelty / feasibility / risk screening
- experiment plan
- manuscript section
- full report

## Final S9 Artifact Chain

The successful S9 artifact chain is:

```text
retrieval/source_candidate_packet.json
retrieval/retrieval_warnings.json
evidence/evidence_card_seeds.json
evidence/evidence_cards.initial.json
evidence/evidence_cards.enriched.json
ranked_evidence/evidence_selection.json
ranked_evidence/coverage_diagnostics.json
reports/minimal_topic_to_evidence_report.md
reports/minimal_topic_to_evidence_report.json
```

This is the first successful real Claude CLI-backed minimal topic-to-evidence
report chain under platform validation and audit control.

## Safety Boundary

The current safety boundary is:

1. Claude CLI never directly executes skills.
2. Claude CLI only emits `CliOutputEnvelope`.
3. Platform validates all CLI decisions through the A6 contract.
4. Platform executes only registered available skills.
5. Platform updates `state.json`, `plan.md`, and `audit/artifact_manifest.json`.
6. Platform records audit logs.
7. Raw retrieval candidates cannot enter report generation.
8. Reports must use Evidence Cards / selected evidence.
9. Default tests do not invoke real Claude CLI.
10. Real CLI tests are opt-in only.
11. No database mutation occurred.
12. No M1-M7 internal code was modified.

## Test Strategy

### Default Tests

Default tests do not call real Claude CLI. They keep real CLI smoke tests
skipped and validate unit, contract, fake backend, controller, wrapper, and
negative gate behavior.

Latest recorded command:

```bash
PYTHONPATH=backend pytest backend/tests -q
```

Latest recorded result:

```text
359 passed, 9 skipped
```

### Opt-In Real CLI Tests

Real Claude CLI tests must be explicitly opted in with
`RUN_REAL_CLAUDE_CLI_TEST=1`.

```bash
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_contract_smoke.py -q -s
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_call_tool_smoke.py -q -s
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_one_step_run_once_smoke.py -q -s
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_two_step_smoke.py -q -s
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_three_step_smoke.py -q -s
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_four_step_smoke.py -q -s
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_five_step_smoke.py -q -s
RUN_REAL_CLAUDE_CLI_TEST=1 PYTHONPATH=backend pytest backend/tests/test_real_claude_cli_minimal_report_smoke.py -q -s
```

### Negative Gate Test

The report input gate explicitly rejects raw retrieval artifacts:

```text
retrieval/... as report input
-> validate_report_inputs()
-> rejected
-> raw_retrieval_candidates_not_allowed_for_report
```

This protects the report path from bypassing Evidence Card extraction,
enrichment, ranking, and validation.

## Known Warnings And Technical Debt

These items are recorded but not fixed in D1.

1. SQLite initialization / duplicate column race can occur in parallel focused
   tests. Sequential focused tests and full backend regression pass. This should
   be handled as a separate technical debt item.

2. `rank_evidence` smoke uses a single text evidence fixture. Therefore
   coverage diagnostics may be `degraded_with_warning`.

3. `fake_acquire_evidence_fn` is used in real CLI smoke tests. These tests
   validate controller integration, not real retrieval quality.

4. `role_enrichment_fallback:*` may occur in S7/S8/S9 smoke fixtures. This is
   warning-level unless the enrichment wrapper fails.

## Next Step Options

Do not proceed directly to M8-M14.

Two reasonable next steps are:

### Option A: A8 Platform-Native Fallback Controller Baseline

Goal:

```text
Implement a platform-native fallback controller that does not depend on Claude
CLI, for regression baseline coverage and CLI-unavailable fallback behavior.
```

### Option B: T1 SQLite Initialization / Import Side Effect Cleanup

Goal:

```text
Investigate and fix the occasional SQLite duplicate-column / initialization
race observed during parallel focused test collection.
```

Recommended next step:

```text
T1 first if engineering stability is prioritized.
A8 first if architecture roadmap continuity is prioritized.
```

D1 does not implement A8 or T1.

After A8 and T1, the architecture foundation is archived as Phase 1. Future roadmap items should use the flattened Phase 2 naming convention described in `docs/roadmap_flattening.md`.
