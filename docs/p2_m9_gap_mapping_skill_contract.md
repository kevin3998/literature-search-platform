# P2-M9 Gap Mapping Skill Contract And Stub-safe Wrapper

## Purpose

P2-M9.1 defines the bounded contract and artifact schema for the Phase 2 Gap Mapping Skill. P2-M9.2 adds a deterministic, stub-safe executable wrapper that maps coverage and diagnostic structure into bounded gap artifacts.

The skill name is:

```text
map_gaps
```

In P2-M9.2, `map_gaps` is available as a deterministic stub-safe executable wrapper.

Implementation closure after P2-M9.4b is documented in:

```text
docs/p2_m9_gap_mapping_skill_closure.md
```

## Gap Mapping Role

Gap Mapping consumes landscape artifacts, enriched Evidence Cards, selected / ranked evidence, and coverage diagnostics to identify evidence coverage gaps, under-supported comparison dimensions, source-type imbalance, role imbalance, and condition coverage gaps.

The allowed chain is:

```text
landscape artifacts
-> enriched Evidence Cards
-> selected / ranked evidence
-> coverage diagnostics
-> gap map
```

The forbidden chain is:

```text
raw retrieval candidates
-> free-form speculation
-> gap map
```

Gap Mapping is not:

- candidate idea generation
- novelty screening
- feasibility screening
- experiment design
- manuscript writing
- free-form opportunity speculation

## Legal Inputs

Required inputs:

```text
landscape/literature_landscape.json
landscape/landscape_coverage_diagnostics.json
evidence/evidence_cards.enriched.json
ranked_evidence/evidence_selection.json
ranked_evidence/coverage_diagnostics.json
```

Optional inputs:

```text
landscape/literature_landscape.md
reports/minimal_topic_to_evidence_report.json
```

The optional minimal report can only act as an evidence-grounded summary aid. It cannot replace landscape JSON, enriched Evidence Cards, selected evidence, or diagnostics.

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
```

Validation rejects any `retrieval/...` input with:

```text
raw_retrieval_candidates_not_allowed_for_gap_mapping
```

Missing landscape JSON should be reported as:

```text
missing_landscape_artifact
```

Missing evidence references should be reported as:

```text
gap_mapping_requires_evidence_references
```

## Output Artifacts

The Gap Mapping Skill contract declares exactly these output artifacts:

```text
gaps/gap_map.json
gaps/gap_map.md
gaps/gap_coverage_diagnostics.json
```

It must not output:

- candidate ideas
- novelty screening
- feasibility screening
- experiment plan
- manuscript section

## P2-M9.2 Deterministic Wrapper

The P2-M9.2 wrapper reads landscape JSON, landscape diagnostics, enriched Evidence Cards, ranked evidence selection, and ranking coverage diagnostics. It generates gaps only from deterministic evidence-structure signals:

1. missing roles from coverage diagnostics
2. dominant source warnings
3. missing source types such as `missing_figure_source_type`
4. landscape clusters represented by a single evidence card
5. selected evidence dominated by a single source paper
6. sparse axis coverage across material, defect, mechanism, or condition dimensions

The wrapper does not infer opportunity claims. It does not write candidate ideas, proposed research directions, novelty screening, feasibility screening, experiment plans, or manuscript drafts.

Missing axis values are recorded as:

```text
missing_gap_axis_value:<axis_name>:<evidence_id>
```

Each generated gap must include a basis referencing at least one of:

```text
landscape_cluster_ids
evidence_ids
coverage_warnings
diagnostic_refs
```

## Gap Map JSON Schema

The stable schema version is:

```text
gap_map_v1
```

Minimum JSON shape:

```json
{
  "task_id": "...",
  "topic": "...",
  "gap_map_id": "...",
  "input_artifacts": [],
  "landscape_id": "...",
  "evidence_ids": [],
  "source_paper_ids": [],
  "gap_axes": [],
  "gaps": [],
  "coverage": {},
  "supporting_evidence": [],
  "limitations": [],
  "warnings": [],
  "created_at": 0,
  "schema_version": "gap_map_v1"
}
```

Initial gap axes may include:

- `material_system`
- `mechanistic_role`
- `defect_type`
- `synthesis_strategy`
- `performance_metric`
- `characterization_method`
- `application_condition`
- `source_type`
- `evidence_role`

These axes must be derived from landscape artifacts, Evidence Cards, and coverage diagnostics. They are not a new hand-written domain ontology.

## Gap Record Contract

Each gap has this minimum shape:

```json
{
  "gap_id": "...",
  "gap_type": "coverage_gap",
  "title": "...",
  "description": "...",
  "axis_values": {},
  "basis": {
    "landscape_cluster_ids": [],
    "evidence_ids": [],
    "coverage_warnings": [],
    "diagnostic_refs": []
  },
  "severity": "low",
  "confidence": "low",
  "not_an_idea": true,
  "warnings": []
}
```

Allowed `gap_type` values:

- `coverage_gap`
- `comparison_gap`
- `evidence_quality_gap`
- `source_type_gap`
- `role_gap`
- `condition_gap`

Rules:

- every gap must have `basis`
- basis must reference at least one landscape cluster, evidence id, coverage warning, or diagnostic reference
- severity and confidence are limited to `low`, `medium`, or `high`
- `not_an_idea` must be `true`
- gaps must not include experiment proposals or proposed research directions

## Coverage Contract

Recommended coverage fields:

```json
{
  "num_landscape_clusters": 0,
  "num_evidence_cards": 0,
  "num_selected_evidence": 0,
  "num_source_papers": 0,
  "source_type_distribution": {},
  "role_distribution": {},
  "axis_coverage": {},
  "missing_roles": [],
  "dominant_source_warning": false,
  "coverage_warnings": []
}
```

Coverage diagnostics are part of the artifact contract because gap quality depends on preserved diagnostic context.

## Markdown Structure

The human-readable artifact should use this minimal structure:

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

The markdown must include evidence references such as:

```text
evidence_id
paper_id
landscape_cluster_id
diagnostic reference
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

These belong to later P2 modules.

## Validation Expectations

P2-M9.1 records the future validation expectations:

1. input artifacts exist
2. landscape JSON exists and is parseable
3. `schema_version == "landscape_v1"` for landscape JSON
4. no `retrieval/...` input
5. enriched Evidence Cards and selected evidence are present
6. output JSON is parseable
7. `schema_version == "gap_map_v1"`
8. every gap has basis
9. every gap basis references evidence id, landscape cluster, coverage warning, or diagnostic reference
10. no gap is phrased as candidate idea
11. markdown contains Evidence References
12. markdown does not contain idea / novelty / feasibility / experiment / manuscript sections
13. coverage diagnostics are preserved

The lightweight contract helper validates schema/path/forbidden input expectations. The P2-M9.2 wrapper also validates generated JSON and markdown boundaries. It must not call an LLM.

## Registry Boundary

`map_gaps` is:

```text
status = available
requires_evidence_cards = true
allows_raw_chunks = false
database_access = none
writes_artifacts = true
```

P2-M9.2 adds wrapper dispatch for `map_gaps`. P2-M9.3 adds explicit controller integration.

Default minimal topic-to-evidence and explicit landscape controller behavior remain unchanged. Gap mapping is not automatically entered after landscape unless the plan explicitly contains `map_gaps` or a CLI-backed controller receives a valid explicit `CALL_TOOL map_gaps` request.

## P2-M9.3 Explicit Controller Integration

P2-M9.3 adds:

```text
build_explicit_gap_mapping_plan(...)
```

This plan explicitly extends the existing chain:

```text
retrieve_sources
-> create_evidence_seeds
-> extract_evidence_cards
-> enrich_evidence_cards
-> rank_evidence
-> build_minimal_topic_to_evidence_report
-> build_landscape
-> map_gaps
```

Controller boundaries:

- default minimal plans still stop after `build_minimal_topic_to_evidence_report`
- explicit landscape plans still stop after `build_landscape`
- explicit gap mapping plans may execute `map_gaps` after required landscape and evidence artifacts exist
- CLI-backed fake or real controllers may execute `map_gaps` only when a validated `CALL_TOOL map_gaps` decision is received
- P2-M10+ future skills remain unavailable for execution

The controller-level input gate rejects forbidden `map_gaps` inputs such as `retrieval/...`, raw chunks, raw markdown papers, seeds, and initial cards. Missing landscape JSON is reported as `missing_landscape_artifact`.

## What P2-M9 Does Not Do

P2-M9.3 does not:

- implement free-form semantic gap reasoning
- add automatic gap mapping after landscape
- run real CLI smoke tests
- implement idea generation, novelty screening, feasibility screening, experiment planning, or manuscript drafting
- modify M1-M7
- modify databases

## Next Step Recommendation

The P2-M9 implementation closure is documented in:

```text
docs/p2_m9_gap_mapping_skill_closure.md
```

The next recommended module is `P2-M10.1 Idea Generation Skill Contract And Artifact Schema`, but idea generation should begin with contract and artifact boundaries only.
