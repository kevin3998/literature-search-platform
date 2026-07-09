# P2-M8.1 Landscape Skill Contract And Artifact Schema

Implementation closure is documented in `docs/p2_m8_landscape_skill_closure.md`.

## Purpose

P2-M8.1 defines the bounded contract and artifact schema for the Phase 2 Landscape Skill. P2-M8.2 adds a deterministic, stub-safe wrapper that performs conservative evidence aggregation only. It does not implement controller execution, Claude CLI smoke tests, gap mapping, idea generation, novelty screening, experiment planning, or manuscript drafting.

The skill name is:

```text
build_landscape
```

In P2-M8.2, `build_landscape` is available as a deterministic stub-safe executable wrapper.

## Position In The Research Chain

Landscape Skill consumes enriched Evidence Cards and selected / ranked evidence to build a topic-level literature landscape artifact. It describes evidence distribution, method / mechanism / material / performance patterns, coverage boundaries, and representative evidence structure.

The allowed chain is:

```text
Evidence Cards
-> ranked / selected evidence
-> literature landscape
```

The forbidden chain is:

```text
raw retrieval candidates
-> free-form summary
-> landscape
```

Landscape is not:

- gap generation
- idea generation
- novelty screening
- experiment design
- manuscript writing
- free-form review article generation

## Skill Registry Contract

`build_landscape` is:

```text
status = available
requires_evidence_cards = true
allows_raw_chunks = false
database_access = none
writes_artifacts = true
```

It remains bounded to deterministic aggregation. It must not perform semantic clustering, call an LLM, call Claude CLI, or generate downstream gap / idea / novelty / experiment / manuscript artifacts.

## Input Artifacts

Required inputs:

```text
evidence/evidence_cards.enriched.json
ranked_evidence/evidence_selection.json
ranked_evidence/coverage_diagnostics.json
```

Optional input:

```text
reports/minimal_topic_to_evidence_report.json
```

The optional minimal report can only act as an evidence-grounded summary aid. It cannot replace enriched Evidence Cards or selected evidence.

Forbidden inputs:

```text
retrieval/source_candidate_packet.json
retrieval/retrieval_warnings.json
raw chunks
raw markdown papers
evidence/evidence_card_seeds.json
evidence/evidence_cards.initial.json
```

Future validation should reject any `retrieval/...` input with:

```text
raw_retrieval_candidates_not_allowed_for_landscape
```

## Output Artifacts

The Landscape Skill contract declares exactly these output artifacts:

```text
landscape/literature_landscape.json
landscape/literature_landscape.md
landscape/landscape_coverage_diagnostics.json
```

It must not output:

- gap map
- candidate ideas
- novelty screening
- experiment plan
- manuscript section

## P2-M8.2 Deterministic Wrapper

The P2-M8.2 wrapper reads enriched Evidence Cards, ranked evidence selection, and coverage diagnostics. It groups evidence deterministically by:

```text
primary_role / mechanistic_role
-> material_system
-> defect_type
```

It extracts landscape axis values only from existing card entities and statements. Missing values are written as `unknown` and recorded as warnings such as:

```text
missing_axis_value:<axis_name>:<evidence_id>
```

Representative claims are copied from `normalized_statement` or `verbatim_snippet` and must cite `evidence_ids`. The wrapper does not infer unsupported scientific claims.

## P2-M8.3 Explicit Controller Integration

P2-M8.3 allows controllers to execute `build_landscape` only when landscape is explicitly requested.

Default minimal topic-to-evidence plans still stop after:

```text
build_minimal_topic_to_evidence_report
```

Explicit landscape execution is enabled by:

```text
build_explicit_landscape_plan(...)
```

or by a bounded CLI/fake-backend `CALL_TOOL build_landscape` request.

The platform-native fallback controller checks whether the current plan contains `build_landscape`. If it does not, completed minimal report artifacts still produce `STOP_SUCCESS`. If it does, the controller may run `build_landscape` after enriched Evidence Cards, ranked evidence selection, coverage diagnostics, and minimal report artifacts are available.

The CLI-backed controller can execute an accepted `CALL_TOOL build_landscape` request through the same registry, wrapper, validation, audit, manifest, state, and plan update boundary. P2-M8.3 does not add real Claude CLI landscape smoke tests.

## JSON Schema

The stable schema version is:

```text
landscape_v1
```

Minimum JSON shape:

```json
{
  "task_id": "...",
  "topic": "...",
  "landscape_id": "...",
  "input_artifacts": [],
  "evidence_ids": [],
  "source_paper_ids": [],
  "landscape_axes": [],
  "clusters": [],
  "coverage": {},
  "representative_evidence": [],
  "limitations": [],
  "warnings": [],
  "created_at": 0,
  "schema_version": "landscape_v1"
}
```

Initial landscape axes may include:

- `material_system`
- `synthesis_strategy`
- `defect_type`
- `mechanistic_role`
- `performance_metric`
- `characterization_method`
- `application_condition`

These are landscape organization dimensions, not a mandatory material-domain ontology.

## Cluster Contract

Each cluster has this minimum shape:

```json
{
  "cluster_id": "...",
  "title": "...",
  "description": "...",
  "axis_values": {},
  "evidence_ids": [],
  "source_paper_ids": [],
  "representative_claims": [],
  "confidence": "low",
  "warnings": []
}
```

Rules:

- every cluster must cite at least one `evidence_id`
- every representative claim must cite `evidence_ids`
- clusters must not be fabricated without evidence support
- confidence is limited to `low`, `medium`, or `high`

## Coverage Contract

Recommended coverage fields:

```json
{
  "num_evidence_cards": 0,
  "num_selected_evidence": 0,
  "num_source_papers": 0,
  "source_type_distribution": {},
  "role_distribution": {},
  "missing_roles": [],
  "dominant_source_warning": false,
  "coverage_warnings": []
}
```

Coverage diagnostics are part of the artifact contract because landscape quality depends on what evidence is missing as much as what evidence is present.

## Markdown Contract

The human-readable artifact should use this minimal structure:

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

The markdown must include evidence references such as:

```text
evidence_id
paper_id
source_path
```

Forbidden sections:

```markdown
## Research Gaps
## Candidate Ideas
## Novelty Screening
## Experiment Plan
## Manuscript Draft
```

These belong to later P2-M modules.

## Validation Expectations

P2-M8.1 records the future validation expectations:

1. input artifacts exist
2. input artifacts are validated enriched Evidence Cards / selected evidence
3. no `retrieval/...` input
4. output JSON is parseable
5. `schema_version == "landscape_v1"`
6. every cluster has `evidence_ids`
7. every representative claim references `evidence_id`
8. markdown contains Evidence References
9. landscape output does not include gap / idea / novelty / experiment / manuscript sections
10. coverage diagnostics are preserved

The lightweight contract helper may validate schema/path/forbidden input expectations. The P2-M8.2 wrapper also validates generated JSON and markdown boundaries. It must not call an LLM.

## Non-Goals

P2-M8 does not:

- change controller loops
- let Claude CLI request landscape smoke tests
- generate free-form or semantic landscape claims
- implement gap mapping, idea generation, novelty screening, experiment planning, or manuscript drafting
- modify M1-M7
- modify databases
