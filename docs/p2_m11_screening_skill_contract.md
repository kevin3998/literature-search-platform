# P2-M11 Novelty / Feasibility / Risk Screening Skill Contract

## Current Active Implementation Note

As of the P2-M11 LLM-assisted upgrade, the active `screen_novelty_feasibility_risk`
implementation writes `schema_version = idea_screening_v2` and uses
`analysis_mode = llm_assisted_local_evidence_triage`.

The deterministic input/output guards in this contract still apply: raw
retrieval packets, raw chunks, unvalidated evidence seeds, and markdown-only
inputs are not allowed to drive screening. The key semantic change is that the
screening analysis itself now requires an injected platform LLM client. If no
LLM client is available, P2-M11 returns `BLOCKED` with
`llm_required_for_screening` and does not write final screening artifacts.

External novelty search remains `not_performed`; P2-M11 still must not produce
experiment plans, experimental protocols, manuscript drafts, final claims, or
final novelty / feasibility / risk conclusions.

## Purpose

P2-M11.1 defines the bounded contract and artifact schema for the Phase 2 Novelty / Feasibility / Risk Screening Skill.

The skill name is:

```text
screen_novelty_feasibility_risk
```

P2-M11.1 is contract-only. P2-M11.2 adds the deterministic stub-safe wrapper. P2-M11.3 adds explicit controller integration only. P2-M11 does not implement real novelty screening, feasibility screening, risk screening, experiment planning, manuscript drafting, real Claude CLI smoke tests, or LLM-based review.

## Screening Role

`screen_novelty_feasibility_risk` will consume P2-M10 candidate ideas and their evidence basis to produce structured screening results for:

- `novelty_status`
- `feasibility_status`
- `risk_status`
- evidence support
- screening limitations
- required follow-up checks

The screening skill is downstream of:

```text
candidate ideas
-> gap map
-> landscape artifacts
-> enriched Evidence Cards
-> selected / ranked evidence
-> diagnostics
-> screening results
```

P2-M11 is not:

- new idea generation
- experiment design
- manuscript writing
- claim ledger construction
- free-form expert review
- final novelty or feasibility proof

## Legal Inputs

Required inputs:

```text
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
ideas/candidate_ideas.md
gaps/gap_map.md
landscape/literature_landscape.md
reports/minimal_topic_to_evidence_report.json
```

Optional markdown and report artifacts can only act as evidence-grounded readable aids. They cannot replace candidate ideas JSON, gap map JSON, landscape JSON, enriched Evidence Cards, selected evidence, or diagnostics.

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
```

Validation should reject any `retrieval/...` input with:

```text
raw_retrieval_candidates_not_allowed_for_screening
```

Missing candidate ideas should be reported as:

```text
missing_candidate_ideas_artifact
```

Candidate ideas without gap and evidence basis should be reported as:

```text
screening_requires_gap_and_evidence_basis
```

Candidate ideas that are already screened should be reported as:

```text
screening_requires_unscreened_candidate_ideas
```

## Output Artifacts

The Screening Skill contract declares exactly these output artifacts:

```text
screening/idea_screening_results.json
screening/idea_screening_results.md
screening/screening_diagnostics.json
```

It must not output:

- experiment plan
- experimental protocol
- manuscript section
- claim ledger
- final recommendation without limitations
- final novelty or feasibility proof

## Screening JSON Schema

The stable schema version is:

```text
idea_screening_v2
```

Minimum JSON shape:

```json
{
  "task_id": "...",
  "topic": "...",
  "screening_id": "...",
  "input_artifacts": [],
  "idea_set_id": "...",
  "gap_map_id": "...",
  "landscape_id": "...",
  "evidence_ids": [],
  "source_paper_ids": [],
  "analysis_mode": "llm_assisted_local_evidence_triage",
  "llm_provenance": {
    "external_novelty_search_performed": false
  },
  "screened_ideas": [],
  "screening_scope": {},
  "screening_policy": {},
  "limitations": [],
  "warnings": [],
  "created_at": 0,
  "schema_version": "idea_screening_v2"
}
```

Each screened idea has this minimum shape:

```json
{
  "idea_id": "...",
  "source_idea_title": "...",
  "gap_ids": [],
  "evidence_ids": [],
  "novelty": {
    "status": "not_screened",
    "basis": [],
    "limitations": [],
    "confidence": "low"
  },
  "feasibility": {
    "status": "not_screened",
    "basis": [],
    "constraints": [],
    "required_resources": [],
    "limitations": [],
    "confidence": "low"
  },
  "risk": {
    "status": "not_screened",
    "risk_factors": [],
    "basis": [],
    "mitigation_notes": [],
    "limitations": [],
    "confidence": "low"
  },
  "overall_screening": {
    "status": "not_recommended_yet",
    "rationale": "...",
    "required_follow_up": []
  },
  "not_an_experiment_plan": true,
  "not_a_validated_claim": true,
  "warnings": []
}
```

Allowed novelty status values:

- `not_screened`
- `insufficient_evidence`
- `potentially_incremental`
- `potentially_distinct`
- `requires_external_search`

Allowed feasibility status values:

- `not_screened`
- `insufficient_evidence`
- `low`
- `medium`
- `high`
- `requires_expert_review`

Allowed risk status values:

- `not_screened`
- `low`
- `medium`
- `high`
- `requires_risk_review`

Allowed overall screening status values:

- `not_recommended_yet`
- `needs_external_novelty_check`
- `needs_feasibility_review`
- `ready_for_experiment_planning_candidate`

Rules:

- every screened idea must reference source `idea_id`
- every screened idea must preserve `gap_ids`
- every screened idea must preserve `evidence_ids`
- novelty / feasibility / risk fields must have basis or limitations
- `not_an_experiment_plan` must be `true`
- `not_a_validated_claim` must be `true`
- screening must not claim final novelty as established fact
- screening must not claim feasibility as validated fact
- screening must not provide a concrete experiment protocol
- screening must not generate manuscript-ready claims

## Screening Markdown Structure

The human-readable artifact should use this minimal structure:

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

The markdown must include evidence references such as:

```text
idea_id
gap_id
evidence_id
paper_id
landscape_cluster_id
diagnostic reference
```

Forbidden sections:

```markdown
## Experiment Plan
## Experimental Protocol
## Manuscript Draft
## Final Claims
```

These belong to P2-M12 and P2-M14 or later modules, not P2-M11.

## Validation Expectations

P2-M11.1 records the future validation expectations:

1. input artifacts exist
2. candidate ideas JSON exists and is parseable
3. `schema_version == "candidate_ideas_v1"` for candidate ideas JSON
4. no `retrieval/...` input
5. every candidate idea has gap basis and evidence basis
6. every candidate idea has `not_yet_screened == true` before screening
7. gap map JSON exists and is parseable
8. landscape JSON exists and is parseable
9. output JSON is parseable
10. `schema_version == "idea_screening_v2"`
11. every screened idea references source `idea_id`
12. every screened idea preserves `gap_ids` and `evidence_ids`
13. local novelty / feasibility / risk triage fields have rationale or limitations
14. `not_an_experiment_plan == true`
15. `not_a_validated_claim == true`
16. markdown contains Evidence References
17. markdown does not contain experiment / protocol / manuscript / final claim sections
18. screening does not claim final novelty or feasibility as established fact

The lightweight contract helper validates schema, path, and forbidden input expectations. P2-M11 must not call an LLM.

## Registry Boundary

`screen_novelty_feasibility_risk` is:

```text
status = available
requires_evidence_cards = true
allows_raw_chunks = false
database_access = none
writes_artifacts = true
```

P2-M11.2 adds deterministic stub-safe wrapper dispatch for `screen_novelty_feasibility_risk`.
P2-M11.3 adds explicit controller integration for `screen_novelty_feasibility_risk`.
P2-M11.4a / P2-M11.4b add opt-in real Claude CLI bounded decision and one-step `run_once` smoke validation.

Implementation closure is documented in `docs/p2_m11_screening_skill_closure.md`.

The wrapper remains conservative:

- no external novelty search
- no expert feasibility review
- no risk assessment as a final conclusion
- no experiment plan
- no manuscript section
- no final claims

Successful execution writes:

```text
screening/idea_screening_results.json
screening/idea_screening_results.md
screening/screening_diagnostics.json
```

The generated screening results keep `not_an_experiment_plan = true` and `not_a_validated_claim = true`.

P2-M12+ skills remain stub-only and non-executable.

## Controller Integration Boundary

P2-M11.3 makes screening executable only when it is explicit:

```text
explicit screening plan
or explicit CLI-backed fake CALL_TOOL screen_novelty_feasibility_risk
-> deterministic P2-M11.2 wrapper
-> screening artifacts / audit / manifest / state / plan update
```

The default and upstream explicit plans keep their boundaries:

- minimal topic-to-evidence stops at `build_minimal_topic_to_evidence_report`
- explicit landscape stops at `build_landscape`
- explicit gap mapping stops at `map_gaps`
- explicit idea generation stops at `generate_candidate_ideas`
- explicit screening is the first plan template that includes `screen_novelty_feasibility_risk`

The platform-native fallback controller selects screening by checking that the plan contains `screen_novelty_feasibility_risk` and that screening outputs are missing. It does not infer screening merely because candidate ideas exist.

The Claude CLI-backed controller can execute screening only when the backend returns a valid bounded `CALL_TOOL screen_novelty_feasibility_risk` envelope. P2-M11.3 does not add a real Claude CLI screening smoke test.

Screening input gates reject raw retrieval inputs with:

```text
raw_retrieval_candidates_not_allowed_for_screening
```

## What P2-M11 Does Not Do

P2-M11.1 / P2-M11.2 / P2-M11.3 do not:

- implement real novelty screening
- implement real feasibility screening
- implement real risk screening
- make default or upstream explicit controller loops auto-enter screening
- run real Claude CLI smoke tests
- call an LLM
- implement experiment planning
- implement manuscript drafting
- modify M1-M7
- modify databases or SQLite schema
- consume raw retrieval artifacts
- claim novelty or feasibility has been proven

## Next Step Recommendation

The next recommended step is:

```text
P2-M12.1 Experiment Matrix Skill Contract And Artifact Schema
```

Do not proceed automatically. P2-M12.1 should start with contract, artifact schema, input boundary, forbidden inputs, and validation expectations. It should not directly implement experiment matrix generation, experiment protocols, manuscript drafting, final claims, raw retrieval inputs, or unsupported novelty / feasibility claims.
