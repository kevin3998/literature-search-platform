# P2-M10 Idea Generation Skill Contract, Wrapper, And Explicit Controller Integration

## Purpose

P2-M10.1 defines the bounded contract and artifact schema for the Phase 2 Idea Generation Skill. P2-M10.2 adds a deterministic, stub-safe executable wrapper that assembles candidate ideas from validated gap and evidence artifacts. P2-M10.3 adds explicit controller integration only when a plan or bounded CLI decision explicitly requests idea generation.

The skill name is:

```text
generate_candidate_ideas
```

In P2-M10.2, `generate_candidate_ideas` is available as a deterministic stub-safe executable wrapper.

## Idea Generation Role

Idea Generation consumes validated gap maps, landscape artifacts, enriched Evidence Cards, selected evidence, and coverage diagnostics to produce evidence-constrained candidate research ideas.

The allowed chain is:

```text
gap map
-> landscape artifacts
-> enriched Evidence Cards
-> selected / ranked evidence
-> coverage diagnostics
-> candidate ideas
```

Each candidate idea must trace back to:

- `gap_ids`
- `evidence_ids`
- `landscape_cluster_ids`
- coverage diagnostics
- supporting evidence

Idea Generation is not:

- free-form brainstorming
- unsupported hypothesis generation
- novelty screening
- feasibility screening
- risk screening
- experiment design
- manuscript writing

P2-M10 generates candidate ideas only. It does not determine whether an idea is novel, feasible, safe, low-risk, or experimentally validated.

## Legal Inputs

Required inputs:

```text
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
gaps/gap_map.md
landscape/literature_landscape.md
reports/minimal_topic_to_evidence_report.json
```

The optional minimal report can only act as an evidence-grounded summary aid. It cannot replace the gap map, landscape JSON, enriched Evidence Cards, selected evidence, or diagnostics.

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
```

Validation should reject any `retrieval/...` input with:

```text
raw_retrieval_candidates_not_allowed_for_idea_generation
```

Missing gap map should be reported as:

```text
missing_gap_map_artifact
```

Missing evidence references should be reported as:

```text
idea_generation_requires_evidence_references
```

An idea without gap basis should be reported as:

```text
candidate_idea_requires_gap_basis
```

## Output Artifacts

The Idea Generation Skill contract declares exactly these output artifacts:

```text
ideas/candidate_ideas.json
ideas/candidate_ideas.md
ideas/idea_generation_diagnostics.json
```

It must not output:

- novelty screening
- feasibility screening
- risk screening
- experiment plan
- manuscript section

## P2-M10.2 Deterministic Wrapper

The P2-M10.2 wrapper reads gap map JSON, gap diagnostics, landscape JSON, landscape diagnostics, enriched Evidence Cards, ranked evidence selection, and ranking coverage diagnostics. It generates candidate ideas only from deterministic gap-record signals:

1. validated gap records with `gap_id`
2. gap basis with evidence IDs or supporting evidence references
3. landscape cluster references
4. coverage warnings
5. diagnostic references
6. selected Evidence Cards and source paper IDs

The wrapper maps gap types conservatively:

- `coverage_gap` -> `data_integration`
- `comparison_gap` -> `comparative_study`
- `evidence_quality_gap` -> `characterization_strategy`
- `source_type_gap` -> `characterization_strategy`
- `role_gap` -> `mechanism_hypothesis`
- `condition_gap` -> `performance_validation`

Each gap can produce at most one candidate idea. Gaps without evidence basis are skipped and recorded in diagnostics.

The wrapper does not infer unsupported ideas. It does not write novelty screening, feasibility screening, risk screening, experiment plans, or manuscript drafts.

Forbidden claim checks reject unsupported phrases such as:

```text
is novel
is feasible
has been validated
experimentally validated
will improve
will enhance
proves that
confirms that
should be synthesized
should be tested
```

## Candidate Ideas JSON Schema

The stable schema version is:

```text
candidate_ideas_v1
```

Minimum JSON shape:

```json
{
  "task_id": "...",
  "topic": "...",
  "idea_set_id": "...",
  "input_artifacts": [],
  "gap_map_id": "...",
  "landscape_id": "...",
  "evidence_ids": [],
  "source_paper_ids": [],
  "ideas": [],
  "generation_scope": {},
  "constraints": {},
  "limitations": [],
  "warnings": [],
  "created_at": 0,
  "schema_version": "candidate_ideas_v1"
}
```

Each candidate idea has this minimum shape:

```json
{
  "idea_id": "...",
  "title": "...",
  "summary": "...",
  "idea_type": "comparative_study",
  "gap_basis": {
    "gap_ids": [],
    "gap_types": [],
    "landscape_cluster_ids": [],
    "evidence_ids": [],
    "coverage_warnings": [],
    "diagnostic_refs": []
  },
  "evidence_basis": {
    "supporting_evidence_ids": [],
    "source_paper_ids": [],
    "representative_claim_refs": []
  },
  "rationale": "...",
  "expected_contribution": "...",
  "assumptions": [],
  "constraints": [],
  "not_yet_screened": true,
  "requires_novelty_screening": true,
  "requires_feasibility_screening": true,
  "warnings": []
}
```

Allowed `idea_type` values:

- `mechanism_hypothesis`
- `material_strategy`
- `synthesis_strategy`
- `characterization_strategy`
- `performance_validation`
- `comparative_study`
- `data_integration`

Rules:

- every idea must have `gap_basis`
- every idea must have `evidence_basis`
- `gap_basis` must reference at least one `gap_id`
- `evidence_basis` must reference at least one `evidence_id`
- `not_yet_screened` must be `true`
- `requires_novelty_screening` must be `true`
- `requires_feasibility_screening` must be `true`
- ideas must not be written as verified conclusions
- ideas must not claim novelty, feasibility, risk status, or experimental validation as established facts

## Candidate Ideas Markdown Structure

The human-readable artifact should use this minimal structure:

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
## Novelty Screening
## Feasibility Screening
## Risk Screening
## Experiment Plan
## Manuscript Draft
```

These belong to P2-M11 and later modules, not P2-M10.1.

## Validation Expectations

P2-M10.1 records the future validation expectations:

1. input artifacts exist
2. gap map JSON exists and is parseable
3. `schema_version == "gap_map_v1"` for gap map JSON
4. no `retrieval/...` input
5. landscape JSON exists and is parseable
6. enriched Evidence Cards and selected evidence are present
7. output JSON is parseable
8. `schema_version == "candidate_ideas_v1"`
9. every idea has gap basis
10. every idea has evidence basis
11. every idea references at least one `gap_id`
12. every idea references at least one `evidence_id`
13. every idea has `not_yet_screened == true`
14. every idea has `requires_novelty_screening == true`
15. every idea has `requires_feasibility_screening == true`
16. markdown contains Evidence References
17. markdown does not contain novelty / feasibility / risk / experiment / manuscript sections
18. no idea claims novelty, feasibility, risk status, or validation as an established fact

The lightweight contract helper validates schema/path/forbidden input expectations. P2-M10.1 must not call an LLM.

## Registry Boundary

`generate_candidate_ideas` is:

```text
status = available
requires_evidence_cards = true
allows_raw_chunks = false
database_access = none
writes_artifacts = true
```

P2-M10.2 adds wrapper dispatch for `generate_candidate_ideas`.

Default minimal topic-to-evidence, explicit landscape, and explicit gap mapping controller behavior remain unchanged. Idea generation is not automatically entered after gap mapping.

P2-M10.3 adds explicit controller execution boundaries:

- default minimal topic-to-evidence plans still stop at minimal report
- explicit landscape plans still stop at `build_landscape`
- explicit gap mapping plans still stop at `map_gaps`
- explicit idea generation plans may execute `generate_candidate_ideas`
- CLI-backed fake controllers may execute `generate_candidate_ideas` only when a valid bounded `CALL_TOOL generate_candidate_ideas` request is received
- real Claude CLI idea smoke is not part of default tests
- P2-M11+ skills remain unavailable for execution

## What P2-M10 Does Not Do

P2-M10.1 / P2-M10.2 / P2-M10.3 do not:

- implement real candidate idea generation
- modify controller loops
- run real Claude CLI smoke tests
- call an LLM
- implement novelty screening
- implement feasibility screening
- implement risk screening
- implement experiment planning
- implement manuscript drafting
- modify M1-M7
- modify databases

## Next Step Recommendation

Implementation closure is documented in:

```text
docs/p2_m10_idea_generation_skill_closure.md
```

The next recommended step is:

```text
P2-M11.1 Novelty / Feasibility / Risk Screening Skill Contract And Artifact Schema
```

Do not proceed automatically. P2-M11.1 should start with contract, artifact schema, input boundary, forbidden inputs, and validation expectations. It should not directly implement novelty screening, feasibility screening, risk screening, experiment planning, or manuscript drafting.
