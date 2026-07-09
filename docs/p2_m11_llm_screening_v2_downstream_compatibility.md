# P2-M11 LLM Screening v2 Downstream Compatibility Note

## Current Status

`screen_novelty_feasibility_risk` is now the active P2-M11 LLM-assisted local
evidence triage wrapper.

Active output:

```text
schema_version = idea_screening_v2
analysis_mode = llm_assisted_local_evidence_triage
```

The output artifact paths remain stable:

```text
screening/idea_screening_results.json
screening/idea_screening_results.md
screening/screening_diagnostics.json
```

LLM availability is now required. If no LLM client is available, P2-M11 returns:

```text
status = BLOCKED
error = llm_required_for_screening
```

No final screening artifacts are written in that case.

## What Changed From The Original Deterministic Wrapper

The original deterministic artifact emitted conservative placeholder statuses
such as:

```text
novelty.status = requires_external_search
feasibility.status = requires_expert_review
risk.status = requires_risk_review
```

The active `idea_screening_v2` artifact instead contains LLM-assisted local
triage fields:

```text
local_novelty_triage
external_novelty_search
feasibility_triage
risk_triage
overall_triage
```

External novelty search remains explicitly not performed:

```text
external_novelty_search.status = not_performed
```

## Preserved Safety Boundary

P2-M11 v2 still rejects:

```text
raw retrieval packets
raw chunks
unenriched evidence seeds
unknown evidence IDs
unknown gap IDs
unknown paper IDs
final novelty claims
final feasibility claims
experiment plans
experimental protocols
manuscript drafts
final claims
```

Every screened idea must still preserve:

```text
not_an_experiment_plan = true
not_a_validated_claim = true
```

## Downstream Migration Status

P2-M12, P2-M13, and P2-M14 now consume `idea_screening_v2` through the
downstream screening adapter. Their deterministic wrappers receive conservative
planning inputs derived from the LLM-assisted local triage fields:

```text
local_novelty_triage -> novelty_status = requires_external_search
feasibility_triage -> feasibility_status = requires_expert_review
risk_triage -> risk_status = requires_risk_review
```

Controller and test chains that intentionally execute P2-M11 before downstream
stages must inject or construct an LLM client. If they do not, P2-M11 correctly
blocks at:

```text
llm_required_for_screening
```

This must not be fixed by restoring deterministic fallback behavior.

## Verified Green Scope

The following P2-M11 and Research Workflows tests pass with the v2 behavior:

```bash
PYTHONPATH=backend pytest \
  backend/tests/test_screening_skill_contract.py \
  backend/tests/test_screening_skill_wrapper.py \
  backend/tests/test_explicit_screening_controller_integration.py \
  backend/tests/test_real_claude_cli_screening_decision_smoke.py \
  backend/tests/test_real_claude_cli_screening_run_once_smoke.py \
  backend/tests/test_workflow_engine.py \
  backend/tests/test_workflow_router_task_profile.py -q
```

Observed result:

```text
64 passed, 2 skipped
```

The real Claude CLI screening smoke tests remain opt-in and skip by default.

## Full Backend Test Status

After the downstream adapter migration, full backend regression should no
longer fail because of screening schema mismatch. P2-M12/P2-M13/P2-M14 remain
deterministic and still do not call LLMs directly.

## Adapter Contract

The adapter must:

1. Reject unsupported screening schemas.
2. Reject screening artifacts that claim external novelty search was performed.
3. Reject screened ideas without gap/evidence basis or boundary flags.
4. Preserve conservative downstream statuses.
5. Preserve the prohibition on experiment protocols, synthesis recipes,
   manuscript drafts, and final claims.
