# Claude Code-Style Research Agent Architecture Pivot Plan

> **For agentic workers:** This document is a planning artifact only. Do not implement controller/runtime code from this document until the user explicitly confirms the next A-stage. Existing M1-M7 evidence workflow modules remain valid and must not be deleted, bypassed, or rewritten during the pivot.

**Goal:** Reposition the platform from a fixed workflow-first research pipeline into a workspace-based, plan-driven, tool-using, artifact-audited research agent architecture while preserving M1-M7 as core contracts and callable research skills.

**Architecture:** The new architecture treats each research task as a durable workspace. An Agent Controller observes the workspace, updates a plan, calls registered research tools, validates artifacts, records audit events, and decides whether to continue, branch, retry, or stop. Evidence Cards remain the mandatory evidence substrate between raw sources and downstream landscape, gap, idea, screening, report, experiment, and manuscript artifacts.

**Tech Stack:** Existing FastAPI backend, artifact-first persistence, read-only literature SQLite databases, current `literature_search` integration, existing workflow/evidence modules, pytest, and future backend-only controller/registry/workspace modules. No frontend, database, or runtime implementation is included in this planning document.

---

## 1. Executive Decision

The project should pivot from:

```text
Fixed linear workflow:
Topic -> Retrieval -> Evidence -> Ranking -> Landscape -> Gap -> Idea -> Report
```

to:

```text
Agentic research loop:
Research Task
-> Research Workspace
-> Agent Controller observes current state
-> Agent Controller creates or updates plan
-> Agent Controller selects tools / skills
-> Tools produce artifacts
-> Artifacts are validated and audited
-> Agent Controller decides next step
-> Final research artifact is generated
```

This is not a rejection of M1-M7. It is a change in how M1-M7 are orchestrated. The current evidence workflow becomes the first reliable toolchain inside a broader agentic research operating model.

The short version:

```text
M1-M7 are no longer "the whole workflow".
M1-M7 become the first evidence-grounded research tool set.
```

## 2. What Is Claude Code-Style Research Agent Architecture?

Claude Code-style architecture is not defined by the ability to call a CLI command. It is defined by an operating pattern:

```text
read current workspace and context
-> understand task
-> make or revise a plan
-> choose a tool
-> execute one bounded action
-> inspect the artifact/output
-> validate the result
-> update state and plan
-> continue, branch, retry, or stop
```

For this platform, the equivalent is:

```text
read task.md / plan.md / state.json / artifacts
-> understand research task state
-> decide the next research operation
-> call a registered research skill
-> write artifacts under the task workspace
-> validate artifacts against schemas and audit rules
-> update plan and state
-> repeat until a stopping condition is met
```

The main design shift is from a pipeline that assumes the next step is fixed to a controller that decides the next step based on workspace state and artifact quality.

Claude Code-style does not mean:

- Letting an LLM freely reason over raw chunks.
- Replacing Evidence Cards with raw retrieval snippets.
- Adding a broad multi-agent chat room.
- Using Domain Profiles as the main architecture.
- Treating Claude Code CLI as an uncontrolled black-box runtime.

It means:

- Workspace first.
- Plan first.
- Tool calls are explicit.
- Artifacts are persistent and inspectable.
- Validation gates decide whether the system can proceed.
- The controller does not invent final scientific conclusions directly.

## 3. Difference From The Current Fixed Evidence Workflow

Current evidence workflow:

```text
Topic
-> Task Profile
-> Retrieval
-> EvidenceCardSeed
-> Evidence Card
-> Role / Entity / Relation Enrichment
-> Minimal Evidence Report
-> Evidence Ranking / Diversity Selection
```

This is valuable, but it is still close to a fixed pipeline. It assumes that once a topic starts, the next stage is known.

New architecture:

```text
Research task
-> workspace state
-> controller chooses action
-> tool produces artifact
-> validator checks artifact
-> controller updates plan
```

The difference is not the evidence objects. The difference is orchestration.

| Dimension | Current Workflow-First | Claude Code-Style Research Agent |
|---|---|---|
| Unit of work | workflow run | research workspace |
| Step order | mostly fixed | plan-driven and state-dependent |
| M1-M7 role | pipeline stages | tools / skills / contracts |
| Failure handling | step failed or warning | inspect artifact, retry, branch, or degrade |
| Evidence control | Evidence Cards already central | Evidence Cards become non-bypassable controller gate |
| Output | report-like artifact | artifact graph plus final artifact |
| Expansion | add more stages | add registered skills and plan templates |

## 4. Non-Negotiable Principles

### 4.1 Do Not Push Aside M1-M7

M1-M7 remain important foundations and should be reclassified as:

- data contracts
- artifact contracts
- research tools
- callable skills
- validation units

They include:

- `EvidenceCardSeed`
- `EvidenceCard`
- Evidence roles
- Entity / relation structures
- Task Profiles
- Artifact-first persistence
- Topic-scope retrieval
- Open evidence extraction
- Role/entity/relation enrichment
- Minimal topic-to-evidence report
- Evidence ranking / diversity selection

### 4.2 Evidence Card Remains The Scientific Evidence Core

The allowed chain remains:

```text
source / chunk / caption / table
-> EvidenceCardSeed
-> Evidence Card
-> ranking / landscape / gap / idea / report
```

The forbidden chain remains:

```text
raw chunk
-> free LLM reasoning
-> report
```

The Agent Controller may choose tools, order, retries, and stopping points. It must not bypass Evidence Cards when producing scientific claims, ideas, reports, experiment plans, or manuscript text.

### 4.3 Claude Code-Style Is Not Domain Profile

The architecture must keep the current anti-Domain-Profile stance:

```text
fixed research task structure, not fixed material domain structure
fixed evidence roles, not fixed domain fields
Task Profile / Tool Skill, not HER / membrane / electrolyte / TCO schemas
```

Domain-specific helpers can exist later as optional extractors or query hints. They must not become the primary schema or MVP dependency.

### 4.4 Artifact-First Remains Mandatory

Existing SQLite literature/research databases remain read-only inputs.

Forbidden:

- migration
- update/delete
- vacuum
- reindex
- vector rebuild
- all-library extraction
- new SQLite `evidence_cards` table during MVP

New evidence workflow and agentic research state must be persisted as artifacts under task/workflow workspaces.

### 4.5 Agentic Does Not Mean Free Generation

The controller can reason about process. It cannot freely generate scientific conclusions.

Rules:

- idea must come from a gap
- gap must come from landscape/evidence or explicit missing evidence
- landscape must come from Evidence Cards or selected evidence
- report must come from Evidence Cards and downstream artifacts
- manuscript writing must come from Claim Ledger
- novelty check is conservative screening, not final innovation proof
- unsupported assumptions must remain visible

## 5. Repositioning M1-M7

M1-M7 should be treated as the first toolchain inside the workspace architecture.

| Module | Current Identity | New Identity |
|---|---|---|
| M1 Core Evidence Card Schema | schema module | core data contract and validation unit |
| M2 Evidence Storage | artifact store | artifact persistence contract |
| M3 Task Profile | workflow input metadata | task profile / plan template constraint |
| M4 Topic-Scope Retrieval | retrieval stage | `retrieve_sources` and `create_evidence_seeds` skill |
| M5 Open Evidence Extraction | extraction stage | `extract_evidence_cards` skill |
| M6 Role/Entity/Relation Enrichment | enrichment stage | `enrich_evidence_cards` skill |
| M6.5 Minimal Report | minimal workflow slice | first workspace-based agent loop test scenario |
| M7 Ranking/Diversity | ranking stage | optional `rank_evidence` skill callable by controller |

M1-M7 should not remain only as a single linear workflow. They should become callable tools with declared inputs, outputs, artifacts, validators, and failure modes.

The old linear sequence can remain as a default plan template:

```text
Topic-to-Report default plan template
-> retrieve_sources
-> extract_evidence_cards
-> enrich_evidence_cards
-> rank_evidence
-> build_minimal_topic_to_evidence_report
```

But the controller should be able to skip, retry, branch, or call additional diagnostics based on artifact state.

## 6. Should Topic-to-Report Be Preserved?

Yes, but its role should change.

Do not treat `Topic-to-Report` as the permanent fixed pipeline. Treat it as:

- the default plan template
- the first reliable workspace scenario
- the regression fixture for controller behavior
- the simplest path for users who want a bounded evidence report

It should become:

```text
Topic-to-Report Plan Template
```

not:

```text
Only possible workflow
```

This preserves current work while allowing future tasks such as literature landscape, experiment planning, claim ledger, and manuscript writing to become plan templates or skill bundles.

## 7. Research Workspace Design

Each research task should have an isolated workspace:

```text
research_tasks/{task_id}/
  task.md
  plan.md
  state.json
  retrieval/
  evidence/
  ranked_evidence/
  landscape/
  gaps/
  ideas/
  screening/
  reports/
  experiments/
  claim_ledger/
  manuscript/
  logs/
  audit/
```

### 7.1 `task.md`

Human-readable task definition.

Contains:

- original user request
- normalized research topic
- task profile or plan template
- scope restrictions
- manual assumptions
- explicit exclusions
- creation timestamp

Purpose:

```text
The controller reads this as the task contract.
```

### 7.2 `plan.md`

Human-readable execution plan.

Contains:

- current goal
- planned steps
- status per step
- selected skills
- stop conditions
- unresolved questions
- controller rationale summaries

Purpose:

```text
The controller updates this as it works, similar to a research lab notebook plan.
```

### 7.3 `state.json`

Machine-readable controller state.

Minimum structure:

```json
{
  "task_id": "task_...",
  "task_profile_id": "topic-to-report",
  "status": "running",
  "current_phase": "evidence",
  "completed_steps": [],
  "pending_steps": [],
  "artifact_index": {},
  "warnings": [],
  "blockers": [],
  "last_action": null,
  "updated_at": 0
}
```

Purpose:

```text
The controller uses this for resumability and deterministic state transitions.
```

### 7.4 `retrieval/`

Artifacts from source retrieval.

Examples:

```text
retrieval/source_candidate_packet.json
retrieval/retrieval_plan.json
retrieval/retrieval_warnings.json
retrieval/query_routes.json
```

Purpose:

```text
Preserve what was searched, how it was searched, what was skipped, and what warnings were produced.
```

### 7.5 `evidence/`

Evidence seed and card artifacts.

Examples:

```text
evidence/evidence_card_seeds.json
evidence/evidence_cards.initial.json
evidence/evidence_cards.enriched.json
evidence/evidence_validation.json
```

Purpose:

```text
Make Evidence Cards the non-bypassable substrate for downstream artifacts.
```

### 7.6 `ranked_evidence/`

M7 selection outputs.

Examples:

```text
ranked_evidence/evidence_selection.json
ranked_evidence/coverage_diagnostics.json
```

Purpose:

```text
Record selected representative evidence, role coverage, source diversity, and ranking rationale.
```

### 7.7 `landscape/`

Future M8 skill outputs.

Examples:

```text
landscape/landscape_units.json
landscape/material_method_application_matrix.json
landscape/landscape_summary.md
```

Purpose:

```text
Organize Evidence Cards into research terrain without jumping to ideas.
```

### 7.8 `gaps/`

Future gap mapping outputs.

Examples:

```text
gaps/gap_table.json
gaps/missing_evidence.json
gaps/gap_audit.md
```

Purpose:

```text
Represent gaps as evidence-backed or missing-evidence-backed objects.
```

### 7.9 `ideas/`

Future idea-generation outputs.

Examples:

```text
ideas/candidate_ideas.json
ideas/idea_to_gap_links.json
ideas/unsupported_assumptions.json
```

Purpose:

```text
Ensure every idea traces to a gap, supporting evidence, and explicit assumptions.
```

### 7.10 `screening/`

Future novelty/feasibility/risk outputs.

Examples:

```text
screening/novelty_screening.json
screening/feasibility_risk.json
screening/validation_requirements.json
```

Purpose:

```text
Keep novelty conservative and auditable.
```

### 7.11 `reports/`

Report artifacts.

Examples:

```text
reports/minimal_topic_to_evidence_report.md
reports/evidence_grounded_report.md
reports/report_claim_audit.json
```

Purpose:

```text
Generate readable outputs only from Evidence Cards and downstream artifacts.
```

### 7.12 `experiments/`

Future experiment planning outputs.

Examples:

```text
experiments/sample_matrix.json
experiments/testing_matrix.json
experiments/decision_tree.md
experiments/missing_evidence.json
```

Purpose:

```text
Assist experiment planning without claiming automatic experiment execution.
```

### 7.13 `claim_ledger/`

Future writing/audit substrate.

Examples:

```text
claim_ledger/claims.json
claim_ledger/claim_to_evidence_links.json
claim_ledger/unsupported_claims.json
```

Purpose:

```text
Separate Evidence Cards from manuscript claims.
```

### 7.14 `manuscript/`

Future manuscript drafting outputs.

Examples:

```text
manuscript/outline.md
manuscript/introduction.draft.md
manuscript/unsupported_claim_audit.json
```

Purpose:

```text
Draft sections only after Claim Ledger exists.
```

### 7.15 `logs/`

Operational logs.

Examples:

```text
logs/controller_events.jsonl
logs/tool_calls.jsonl
logs/llm_calls.jsonl
```

Purpose:

```text
Make controller behavior inspectable and resumable.
```

### 7.16 `audit/`

Validation and manual review outputs.

Examples:

```text
audit/artifact_manifest.json
audit/validation_results.json
audit/manual_verification_checklist.md
audit/provenance_graph.json
```

Purpose:

```text
Preserve what passed, what failed, what was skipped, and what still requires human verification.
```

## 8. Agent Controller Design

The Agent Controller is the bottom-level research operating loop.

It should not directly produce final scientific conclusions. It should coordinate tools and artifacts.

Core loop:

```text
observe current workspace
-> load task.md, plan.md, state.json, artifact index
-> understand current task state
-> decide next action
-> call exactly one tool / skill
-> inspect produced artifact
-> validate output
-> update state.json and plan.md
-> stop, continue, retry, or request user input
```

### 8.1 Controller Responsibilities

The controller should:

- maintain task state
- maintain plan state
- select tools from a registry
- enforce artifact prerequisites
- enforce Evidence Card gates
- validate tool outputs
- record warnings and failures
- decide whether to retry, branch, degrade, or stop
- preserve a readable audit trail
- request user input when a scientific or scope decision cannot be inferred safely

### 8.2 Controller Non-Responsibilities

The controller should not:

- directly write final research conclusions from raw chunks
- directly generate ideas without gap artifacts
- directly generate report claims without Evidence Cards
- alter read-only databases
- hide missing evidence
- treat LLM confidence as scientific truth
- silently proceed after validator failure

### 8.3 Controller Decision Types

The controller needs a limited set of decisions:

```text
CALL_TOOL
VALIDATE_ARTIFACT
RETRY_WITH_ADJUSTED_INPUT
BRANCH_PLAN
SKIP_WITH_WARNING
REQUEST_USER_INPUT
STOP_SUCCESS
STOP_BLOCKED
```

This bounded decision vocabulary helps prevent a free-form agent from becoming irreproducible.

### 8.4 State Transition Example

```text
Task: "大语言模型在材料发现中的应用"

observe:
  no retrieval artifact

plan:
  call retrieve_sources

tool:
  retrieve_sources

validate:
  source candidates exist
  figure/table/caption missing warning exists

next:
  call extract_evidence_cards on available seeds
```

If retrieval times out:

```text
validate:
  no source candidates
  timeout warning exists

next:
  retry with safer query plan
  or stop blocked with retrieval_timeout
```

## 9. Tool / Skill Registry Design

Every research operation should be a registered tool or skill.

Minimum registry fields:

```json
{
  "name": "retrieve_sources",
  "purpose": "Find topic-scoped source candidates from the local literature library.",
  "input_schema": {},
  "output_schema": {},
  "required_artifacts": [],
  "produced_artifacts": [],
  "validation_rules": [],
  "failure_modes": [],
  "execution_mode": "deterministic | llm_assisted | hybrid",
  "database_access": "read_only | none",
  "writes_artifacts": true
}
```

### 9.1 Initial Skill Set

| Skill | Purpose | Based On | Mode |
|---|---|---|---|
| `retrieve_sources` | find source candidates | M4 | deterministic/hybrid retrieval |
| `create_evidence_seeds` | normalize candidates to seeds | M1/M4 | deterministic |
| `extract_evidence_cards` | create initial cards | M5 | deterministic fallback + LLM-assisted |
| `enrich_evidence_cards` | role/entity/relation enrichment | M6 | deterministic fallback + LLM-assisted |
| `rank_evidence` | rank and diversify cards | M7 | deterministic |
| `build_minimal_topic_to_evidence_report` | minimal evidence report | M6.5 | deterministic rendering |
| `validate_evidence_cards` | schema and provenance checks | M1/M6 | deterministic |
| `validate_artifact_manifest` | artifact completeness checks | M2/future audit | deterministic |

### 9.2 Future Skill Set

| Skill | Purpose | Dependency |
|---|---|---|
| `build_landscape` | organize Evidence Cards into research landscape units | selected/enriched cards |
| `map_gaps` | identify evidence-backed gaps and missing-evidence gaps | landscape |
| `generate_candidate_ideas` | generate evidence-constrained ideas from gaps | gaps |
| `screen_novelty_feasibility_risk` | conservative screening | ideas + evidence |
| `draft_evidence_grounded_report` | report from evidence/landscape/gap/ideas | downstream artifacts |
| `create_experiment_matrix` | sample/testing/characterization matrix | screened ideas |
| `build_claim_ledger` | map claims to Evidence Cards | reports/manuscript task |
| `draft_manuscript_section` | draft section from Claim Ledger | claim ledger |

### 9.3 Skill Contract Template

Each skill should eventually have:

```text
name:
purpose:
input schema:
output schema:
required artifacts:
produced artifacts:
validation rules:
failure modes:
deterministic or LLM-assisted:
read-only database access:
artifact write locations:
audit events:
```

Example:

```text
name: rank_evidence
purpose: Select representative Evidence Cards while preserving role, paper, and source diversity.
input schema: enriched Evidence Cards, Task Profile, ranking config
output schema: EvidenceSelectionResult
required artifacts: evidence/evidence_cards.enriched.json
produced artifacts: ranked_evidence/evidence_selection.json
validation rules: selected_count <= limit; score components present; warnings for missing roles/source types
failure modes: no cards; invalid roles; empty selection
mode: deterministic
```

## 10. Artifact And Audit System

The artifact system must become the backbone of the architecture.

Every tool call should record:

- input artifacts
- input parameters
- tool name
- tool version
- model/provider if LLM-assisted
- output artifacts
- validation result
- warnings
- start/end timestamp
- controller decision after validation

### 10.1 Artifact Manifest

Each workspace should include:

```text
audit/artifact_manifest.json
```

Minimum structure:

```json
{
  "task_id": "task_...",
  "artifacts": [
    {
      "artifact_id": "evidence_cards.enriched",
      "artifact_type": "evidence_cards",
      "path": "evidence/evidence_cards.enriched.json",
      "created_by": "enrich_evidence_cards",
      "tool_version": "m6_role_entity_relation_v1",
      "input_artifacts": ["evidence/evidence_cards.initial.json"],
      "created_at": 0,
      "validation_status": "passed",
      "warnings": []
    }
  ]
}
```

### 10.2 Validation Gates

The controller should not proceed because a file exists. It should proceed because validation passes or because a controlled degradation is recorded.

Examples:

```text
retrieval gate:
  must have at least one source candidate
  must record source-type coverage

evidence gate:
  every Evidence Card must have paper_id, source_path, source type, role, and statement/snippet

ranking gate:
  every selected card must include score components
  missing required roles must be explicit warnings

report gate:
  every report claim must cite Evidence Cards or downstream artifact IDs
```

### 10.3 Audit Logs

Use append-only logs:

```text
logs/controller_events.jsonl
logs/tool_calls.jsonl
logs/llm_calls.jsonl
audit/validation_results.json
```

The audit layer should make it possible to answer:

- Why did the controller choose this tool?
- What input did the tool consume?
- What did the tool produce?
- What validator passed or failed?
- What evidence supports this output?
- What warnings were ignored or accepted?

## 11. Evidence Card In The New Architecture

Evidence Card remains the central scientific evidence unit.

It is not:

- a raw chunk
- a report claim
- a Claim Ledger entry
- a novelty judgment
- an idea
- an experiment plan

It is:

- a traceable evidence unit
- a normalized bridge from source to downstream artifacts
- the required substrate for landscape/gap/idea/report tools
- the object that makes audit possible

In the new controller architecture, Evidence Card is not merely a schema. It becomes a gate:

```text
No Evidence Cards -> no landscape/gap/idea/report
Invalid Evidence Cards -> repair/retry/stop
Insufficient Evidence Cards -> warning/degrade/request user input
```

## 12. Preventing Raw Chunk To Report

The controller must enforce this rule:

```text
raw retrieval candidates may only feed seed/card tools
reports may only consume Evidence Cards and downstream structured artifacts
```

Required checks:

- report generator input cannot include raw `documents` rows directly
- report must include an evidence index
- claims must reference Evidence Card IDs
- unsupported claims must be listed
- missing figure/table/caption coverage must remain visible

If a report tool receives raw chunks, the validator should fail.

## 13. Preventing Free Idea / Report Generation

Idea generation should require:

```text
Evidence Cards
-> landscape
-> gap table
-> candidate idea
```

Each idea must include:

- idea title
- scientific rationale
- supporting evidence
- linked gap IDs
- novelty risk
- feasibility risk
- required validation
- recommended experiments
- unsupported assumptions

Report generation should require:

```text
Evidence Cards
-> selected evidence
-> landscape/gap/idea/screening artifacts as needed
-> evidence-grounded report
```

Manuscript writing should require:

```text
Evidence Cards
-> Claim Ledger
-> verified claims
-> outline
-> paragraph drafting
-> unsupported claim audit
```

The controller can decide when to call these skills, but it cannot relax their evidence prerequisites.

## 14. Claude Code CLI Role Options

The platform should adopt a Claude Code CLI-backed controller architecture as the main target.

The intended architecture is:

```text
Frontend / API
  ↓
Research Task Workspace
  ↓
Platform Runtime Boundary
  - schemas
  - Evidence Card gates
  - skill registry
  - validators
  - artifact store
  - audit logs
  - database safety rules
  ↓
Claude Code CLI-backed Controller
  - observes allowed workspace files
  - reads task.md / plan.md / state.json / artifact manifest
  - selects next registered skill
  - invokes skill through approved interfaces
  - inspects output artifacts
  - updates plan/state through approved files
  - stops / retries / branches under validator control
  ↓
Registered Research Skills
  - retrieve_sources
  - create_evidence_seeds
  - extract_evidence_cards
  - enrich_evidence_cards
  - rank_evidence
  - build_minimal_topic_to_evidence_report
  - future landscape / gap / idea / report / claim-ledger skills
```

The key position is:

> The platform adopts a Claude Code CLI-backed controller architecture, where Claude Code CLI provides the agentic planning and control loop, while the platform owns all scientific contracts, evidence gates, tool boundaries, artifact persistence, validation, and auditability.

Claude Code CLI should not be treated merely as a reference pattern or developer-only experiment. It is the primary controller backend candidate. The platform-native layer exists to constrain and audit it.

### Platform Runtime Boundary

The platform-owned boundary must define what Claude Code CLI can observe, call, write, and return.

Claude Code CLI must not:

- directly read raw chunks and generate a report
- bypass `EvidenceCardSeed` / Evidence Card
- freely define scientific schemas
- modify SQLite databases
- execute migration, update, delete, vacuum, reindex, or vector rebuild
- perform all-library extraction
- freely generate ideas or reports
- execute unregistered research logic
- write final artifacts without platform validation

Claude Code CLI must:

- work through registered skills
- operate inside an allowed research workspace
- read only approved workspace files and approved read-only literature interfaces
- produce bounded decisions or skill requests
- generate controller event logs
- generate tool call logs
- update artifact manifests through approved mechanisms
- allow platform validators to approve or reject every output before the next step

The platform owns:

- schemas
- Evidence Card contracts
- Research Workspace structure
- Tool / Skill Registry
- artifact paths
- validators
- audit logs
- database safety rules
- deterministic fallback paths where needed

### Option A: Platform-Native Controller As Fallback / Validation Baseline

Platform implements its own minimal controller loop and uses Claude Code-style ideas without relying on the CLI as the main runtime controller.

Pros:

- stable deterministic baseline
- useful for tests and regression
- useful for failure recovery
- easier to run in restricted environments
- provides a comparator for CLI-backed behavior

Cons:

- no longer the main intended architecture
- risks duplicating the agentic reasoning layer
- may drift into a second workflow engine if overbuilt
- should not replace the CLI-backed controller target

New role:

```text
Secondary: fallback / validation baseline / deterministic comparator
```

### Option B: Claude Code CLI As Controller Backend

Claude Code CLI acts as the bottom-level agentic controller backend. It observes the allowed workspace, reasons over task/plan/state/artifacts, selects the next registered skill, requests execution through approved interfaces, inspects resulting artifacts, and updates plan/state under platform validation.

Pros:

- best match to the desired Claude Code-style operating model
- brings a mature agentic planning/action-selection loop into the research runtime
- avoids prematurely rebuilding a weaker controller from scratch
- can use workspace files, plans, logs, and artifacts as its natural operating substrate
- lets platform-native code focus on scientific contracts, tool boundaries, validators, persistence, and safety
- can support dynamic retries, branching, and artifact inspection better than a fixed workflow

Cons:

- black-box behavior risk
- reproducibility must be enforced through platform-owned logs and validators
- deployment and permission boundaries must be designed carefully
- CLI output must be parsed into bounded decisions / skill requests / state updates
- runtime safety depends on a strict Platform Runtime Boundary

New role:

```text
Primary: main architecture target
```

Option B does not mean handing scientific judgment to an uncontrolled CLI. It means the CLI provides controller reasoning while the platform owns every scientific and safety boundary.

### Option C: Claude Code CLI As Engineering / Development Agent

Claude Code CLI remains useful for developing the platform itself: writing code, debugging, generating plans, and assisting with engineering tasks.

Pros:

- continues to accelerate platform development
- keeps engineering support separate from user-side scientific runtime responsibilities
- useful for creating and reviewing A-stage implementation plans

Cons:

- not sufficient by itself for the desired product architecture
- does not validate user-side research controller behavior

New role:

```text
Supporting: engineering / development agent
```

### Recommendation

Recommended ordering:

```text
Primary: Option B — Claude Code CLI as Controller Backend
Secondary: Option A — Platform-native fallback / validation baseline
Supporting: Option C — Engineering / development agent
```

This changes the architecture judgment:

- Option B is the main product/runtime target.
- Option A is no longer the primary architecture. It is a fallback and test baseline.
- Option C remains useful but is not the core runtime direction.
- Claude Code CLI-backed control must be constrained by the Platform Runtime Boundary.
- The platform owns scientific objects, artifacts, validators, and audit logs.

The architecture should say:

```text
Claude Code CLI is the primary controller backend candidate, but it operates inside a platform-owned scientific and safety boundary.
```

## 15. Reassessing M8-M14

### 15.1 Should M8-M14 Continue Directly?

Recommendation: pause direct linear implementation of M8-M14.

Reason:

M8-M14 are exactly the stages where a fixed pipeline can become brittle:

- landscape
- gap mapping
- idea generation
- novelty/risk screening
- report writing
- experiment planning
- claim ledger / manuscript

These should become skills behind the Platform Runtime Boundary and should be invoked by the Claude Code CLI-backed Controller only after artifacts and validators exist.

### 15.2 Should M8-M14 Become Skills?

Yes.

Reclassify them as skills:

```text
build_landscape
map_gaps
generate_candidate_ideas
screen_novelty_feasibility_risk
draft_evidence_grounded_report
create_experiment_matrix
build_claim_ledger
draft_manuscript_section
```

Each skill should have explicit prerequisites and validators.

### 15.3 Should Topic-to-Report Become A Default Plan Template?

Yes.

`Topic-to-Report` should become:

```text
default plan template
```

not:

```text
hardcoded universal workflow
```

### 15.4 Can M6.5 Be The First Claude Code CLI-Backed Agent Loop Scenario?

Yes.

M6.5 is the best first scenario because it is:

- already bounded
- evidence-centered
- artifact-first
- does not require landscape/gap/idea
- has visible warnings/checklists
- can prove the CLI-backed controller loop without expanding scientific ambition

### 15.5 Should M7 Be Controller-Selectable?

Yes.

M7 should become an optional skill:

```text
rank_evidence
```

The Claude Code CLI-backed Controller should call it when:

- too many Evidence Cards exist
- report requires a representative set
- role/source/paper diversity needs diagnosis
- downstream landscape/gap tools need a selected evidence subset

### 15.6 Should Landscape / Gap / Idea / Report Be Dynamically Selected?

Yes.

The controller may choose:

- build minimal evidence report only
- build landscape first
- request more retrieval before gap mapping
- rank evidence before report
- stop if evidence is insufficient

But the controller cannot violate artifact prerequisites.

## 16. Proposed A-Stage Pivot Plan

### A0: Architecture Pivot Planning

**Goal:** Establish the Claude Code CLI-backed architecture direction and stop accidental continuation of the old linear roadmap.

**Scope:**

- Create this architecture plan.
- Reclassify M1-M7 as tools/contracts.
- Define workspace, boundary, registry, audit, and Claude Code CLI-backed controller direction.
- Do not implement runtime code.

**Dependencies:** Completed M1-M7.

**Files likely to change:**

```text
docs/claude_code_style_research_agent_architecture.md
```

**Acceptance criteria:**

- M1-M7 are preserved.
- Option B is clearly identified as the primary architecture target.
- Platform Runtime Boundary is defined.
- M8-M14 are reclassified as skills.

**Tests:** No functional tests. Documentation-only.

**Rollback plan:** Keep `docs/evidence_workflow_plan.md` as the active roadmap and archive this pivot document as an exploration note.

### A1: Research Workspace Model

**Goal:** Define and implement a durable workspace layout for research tasks.

**Scope:**

- Workspace path convention.
- `task.md`, `plan.md`, `state.json`.
- Artifact subdirectories.
- Workspace manifest.
- No CLI controller runtime yet.

**Dependencies:** A0.

**Files likely to change:**

- Create: `backend/modules/research_workspace/`
- Create: `backend/modules/research_workspace/schemas.py`
- Create: `backend/modules/research_workspace/store.py`
- Test: `backend/tests/test_research_workspace.py`

**Acceptance criteria:**

- Can create a workspace under artifact-first storage.
- Can read/write task, plan, state, artifact manifest.
- Workflow state is file-based, not database-based.
- Invalid task IDs cannot escape workspace root.
- Workspace layout supports a future Claude Code CLI-backed Controller.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_research_workspace.py -q
```

**Rollback plan:** Disable workspace creation and keep M2 workflow artifact directories.

### A2: Agent State / Plan Schema

**Goal:** Define controller-readable state and plan schemas before integrating Claude Code CLI.

**Scope:**

- `AgentPlan`
- `AgentStep`
- `AgentState`
- decision vocabulary
- stop conditions
- validation status fields
- bounded CLI decision representation

**Dependencies:** A1.

**Files likely to change:**

- Create: `backend/modules/research_agent_controller/schemas.py`
- Test: `backend/tests/test_research_agent_state_plan.py`

**Acceptance criteria:**

- Plan/state serialize to JSON-safe dicts.
- Steps can be pending/running/completed/failed/skipped.
- Decisions are bounded to a fixed vocabulary.
- State references artifacts by IDs and paths.
- CLI-readable plan/state files are explicit and minimal.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_research_agent_state_plan.py -q
```

**Rollback plan:** Keep plan/state as human-written markdown only.

### A3: Tool / Skill Registry

**Goal:** Define the only research skills Claude Code CLI may request.

**Scope:**

- Skill metadata schema.
- Input/output artifact requirements.
- Deterministic vs LLM-assisted mode.
- Failure mode declaration.
- Registry stubs for M1-M7 and future M8-M14.
- Approved skill request format for CLI-backed controller use.

**Dependencies:** A2.

**Files likely to change:**

- Create: `backend/modules/research_agent_controller/skill_registry.py`
- Test: `backend/tests/test_research_skill_registry.py`

**Acceptance criteria:**

- Registry lists M1-M7-derived skills.
- Future M8-M14 skills can exist as non-runnable stubs.
- Every skill declares produced artifacts and validation rules.
- Registry does not import retrieval/database/workflow runtime.
- Unregistered skill requests can be rejected deterministically.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_research_skill_registry.py -q
```

**Rollback plan:** Keep M3 Task Profiles as the only high-level task registry.

### A4: Wrap M1-M7 As Callable Skills

**Goal:** Add thin wrappers around existing M1-M7 functions so the Claude Code CLI-backed Controller can request them consistently through approved interfaces.

**Scope:**

- Do not rewrite M1-M7 internals.
- Add wrappers with stable input/output artifact contracts.
- Make wrappers callable from tests.
- Preserve existing M6.5 and M7 behavior.
- Return structured tool results to the controller boundary.

**Dependencies:** A3.

**Files likely to change:**

- Create: `backend/modules/research_agent_controller/skills/evidence_tools.py`
- Test: `backend/tests/test_research_evidence_skills.py`

**Acceptance criteria:**

- `retrieve_sources` calls M4 adapter.
- `extract_evidence_cards` calls M5.
- `enrich_evidence_cards` calls M6.
- `rank_evidence` calls M7.
- Artifacts are written under workspace paths.
- No raw chunk-to-report path exists.
- Tool wrappers can be invoked only through registered skill names.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_research_evidence_skills.py -q
```

**Rollback plan:** Use existing M6.5 function directly without controller wrappers.

### A5: Artifact Validation And Audit Gates

**Goal:** Make artifact validation the platform-owned gate around Claude Code CLI-backed control.

**Scope:**

- Artifact manifest.
- Validation result schema.
- Evidence Card validation gate.
- Ranking selection validation gate.
- Report input validation gate.
- Audit log writer.
- CLI controller event log format.

**Dependencies:** A4.

**Files likely to change:**

- Create: `backend/modules/research_agent_controller/audit.py`
- Create: `backend/modules/research_agent_controller/validators.py`
- Test: `backend/tests/test_research_artifact_audit.py`

**Acceptance criteria:**

- Every tool call records input artifacts, output artifacts, warnings, and validation status.
- Every CLI controller decision can be logged.
- Invalid Evidence Cards block downstream report skills.
- Missing source types produce warnings, not fake evidence.
- Audit logs are append-only artifacts.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_research_artifact_audit.py -q
```

**Rollback plan:** Keep current artifact metadata from M2/M6.5/M7 only.

### A6: Claude Code CLI Controller Contract

**Goal:** Define how the platform exposes a bounded workspace, plan, state, artifact manifest, and skill registry to Claude Code CLI.

**Scope:**

- Define what Claude Code CLI can observe.
- Define what Claude Code CLI can request.
- Define what Claude Code CLI can write.
- Define CLI action input/output contracts.
- Define skill request schema.
- Define invalid output handling.
- Define timeout and retry handling.
- Define controller event log entries.
- Do not implement the full runtime loop yet.

**Dependencies:** A5.

**Files likely to change:**

- Create: `backend/modules/research_agent_controller/cli_contract.py`
- Create: `docs/claude_code_cli_controller_contract.md`
- Test: `backend/tests/test_claude_code_cli_controller_contract.py`

**Acceptance criteria:**

- Contract defines allowed workspace read paths.
- Contract defines allowed write paths.
- Contract defines registered skill request format.
- Contract defines bounded decision output.
- Contract rejects raw shell/database mutation requests.
- Contract records validation and parsing failures.
- Contract has no direct M8-M14 execution.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_claude_code_cli_controller_contract.py -q
```

**Rollback plan:** Keep A1-A5 boundary artifacts and postpone CLI-backed runtime integration.

### A7: Claude Code CLI-Backed Minimal Agent Loop

**Goal:** Validate Claude Code CLI-backed control using the existing M6.5 minimal topic-to-evidence scenario.

**Scope:**

- Claude Code CLI reads the bounded workspace.
- Claude Code CLI reads `task.md`, `plan.md`, `state.json`, and artifact manifest.
- Claude Code CLI chooses the next step.
- Claude Code CLI can request only registered M1-M7 skills.
- Platform executes requested skills through approved wrappers.
- Every step produces artifacts.
- Platform validators approve or reject outputs.
- `state.json` and `plan.md` are updated through approved files.
- Failures become `blocked`, `retry`, or `validation_failed`.
- Do not enter M8-M14.
- Do not generate landscape/gap/idea/full report.

**Dependencies:** A6.

**Files likely to change:**

- Create: `backend/modules/research_agent_controller/cli_backed_controller.py`
- Create: `backend/modules/research_agent_controller/plan_templates.py`
- Test: `backend/tests/test_claude_code_cli_backed_minimal_loop.py`

**Acceptance criteria:**

- Given a topic, a workspace is created.
- Claude Code CLI-backed controller runs retrieve -> extract -> enrich -> minimal report.
- It may request `rank_evidence`.
- It cannot request unregistered skills.
- It stops with warnings when evidence coverage is insufficient.
- It never passes raw chunks to report generation.
- Every CLI decision and skill request is logged.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_claude_code_cli_backed_minimal_loop.py -q
```

**Rollback plan:** Disable CLI-backed controller entry and use A8 platform-native fallback or existing M6.5 direct slice.

### A8: Platform-Native Fallback Controller Baseline

**Goal:** Provide a simplified platform-native fallback loop for regression tests, abnormal recovery, and comparison against the CLI-backed controller.

**Scope:**

- Implement or preserve a deterministic loop for the M6.5 scenario.
- Use the same workspace, skill registry, and validators.
- Do not replace A7 as the main controller path.
- Use it as baseline and fallback.

**Dependencies:** A7.

**Files likely to change:**

- Create: `backend/modules/research_agent_controller/native_fallback_controller.py`
- Test: `backend/tests/test_platform_native_fallback_controller.py`

**Acceptance criteria:**

- Fallback loop can run the minimal topic-to-evidence plan.
- It uses the same registered skills and validators.
- It is deterministic enough for regression tests.
- It is explicitly not the primary architecture.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_platform_native_fallback_controller.py -q
```

**Rollback plan:** Keep existing M6.5 direct function as fallback.

### A9: Expand To Landscape / Gap / Idea Skills

**Goal:** Resume M8-M14 as registered, gated skills rather than a fixed pipeline.

**Scope:**

- Implement `build_landscape`.
- Implement `map_gaps`.
- Implement `generate_candidate_ideas`.
- Implement screening and report skills only after landscape/gap artifacts are stable.
- Allow the Claude Code CLI-backed Controller to choose these skills only after prerequisite artifacts pass validation.

**Dependencies:** A7 and A8.

**Files likely to change:**

- Future modules under `backend/modules/evidence_workflow/` or `backend/modules/research_agent_controller/skills/`.
- Future tests per skill.

**Acceptance criteria:**

- Landscape consumes Evidence Cards or selected Evidence Cards.
- Gaps consume landscape and evidence.
- Ideas consume gaps and evidence.
- Reports consume Evidence Cards and downstream artifacts.
- Controller can choose whether to proceed based on validation.

**Tests:**

```bash
PYTHONPATH=backend pytest backend/tests/test_landscape_skill.py -q
PYTHONPATH=backend pytest backend/tests/test_gap_skill.py -q
PYTHONPATH=backend pytest backend/tests/test_evidence_constrained_idea_skill.py -q
```

**Rollback plan:** Keep A7 as the stable CLI-backed MVP and postpone idea/report expansion.

## 17. Key Risks And Controls

Because Option B is the primary architecture target, risks must be controlled through platform-owned boundaries rather than avoided by downgrading CLI involvement.

### 17.1 Claude Code CLI Black-Box Risk

Risk:

Claude Code CLI behavior may be difficult to reproduce, constrain, or audit if treated as an unconstrained runtime.

Control:

- Use a Platform Runtime Boundary.
- Parse CLI output into bounded decisions / skill requests / state updates.
- Reject unparseable or out-of-contract output.
- Log every CLI decision, tool request, input artifact, output artifact, and validation result.
- Use platform-native fallback as regression comparator, not as the primary architecture.

### 17.2 Controller Over-Freedom

Risk:

The controller may become an unrestricted LLM agent that improvises.

Control:

- Bounded decision vocabulary.
- Skill registry.
- Artifact prerequisites.
- Validation gates.
- Explicit stop conditions.
- No raw chunk-to-report path.
- CLI can request only registered skills.
- CLI cannot invent new schemas.

### 17.3 Workspace Sandbox Risk

Risk:

Claude Code CLI may observe or modify files outside the intended research task boundary.

Control:

- Workspace sandbox.
- Allowlist readable workspace files.
- Allowlist writable plan/state/log/artifact paths.
- No direct access to mutable database files.
- Read-only literature access only through approved interfaces.

### 17.4 Artifact Graph Disorder

Risk:

Breaking a fixed workflow into dynamic skills can make artifact relationships confusing.

Control:

- Artifact manifest.
- Input/output artifact IDs.
- Tool call logs.
- Provenance graph.
- Standard workspace directories.
- Artifact manifest updates are mandatory for every accepted tool output.

### 17.5 Artifact Validation Gate Risk

Risk:

A file may exist but be scientifically or structurally invalid.

Control:

- File existence is not success.
- Validator status must be `passed` or explicitly `degraded_with_warning`.
- Invalid Evidence Cards block landscape/gap/idea/report.
- Invalid report inputs block report generation.

### 17.6 Evidence Card Gate Risk

Risk:

The CLI-backed controller may try to proceed directly from retrieval snippets to synthesis.

Control:

- No Evidence Cards means no landscape/gap/idea/report.
- Report skill does not accept raw chunks.
- Idea skill requires gap IDs and supporting Evidence Card IDs.
- Claim Ledger is required before manuscript writing.

### 17.7 Database Safety Risk

Risk:

CLI-backed runtime may attempt broad file or command access that mutates databases.

Control:

- Existing SQLite databases are read-only inputs.
- No migration, update, delete, vacuum, reindex, vector rebuild.
- All new state writes go to artifacts.
- Skill wrappers enforce read-only access.

### 17.8 Timeout And Loop Budget Risk

Risk:

The CLI-backed controller may retry too often or spend excessive time/tokens.

Control:

- Maximum controller loop count.
- Maximum retries per skill.
- Maximum time budget.
- Maximum token/model budget.
- Stop states: `blocked`, `validation_failed`, `budget_exceeded`.

### 17.9 Task State Complexity

Risk:

State management becomes more complex than current workflow steps.

Control:

- Keep `state.json` minimal.
- Use append-only logs for details.
- Do not mirror all state into SQLite.
- Add CLI-backed controller only after A1-A6 boundary exists.

### 17.10 Frontend Complexity

Risk:

An agentic workspace can create complicated UI requirements.

Control:

- Defer frontend changes.
- Backend-first A1-A7.
- Expose plan/state/artifact manifest later.
- Avoid interactive multi-agent UI before backend loop is stable.

### 17.11 Tool Chain Too Long

Risk:

Long tool chains can fail in hard-to-debug ways.

Control:

- One tool call per controller step.
- Validate every artifact.
- Stop early when evidence is insufficient.
- Support resume from workspace state.

### 17.12 LLM Bypasses Evidence Card

Risk:

LLM-assisted skills may generate unsupported idea/report text.

Control:

- Validators reject report claims without Evidence Card IDs.
- Idea skill requires gap IDs and supporting card IDs.
- Manuscript skill requires Claim Ledger.
- LLM prompts are not enough; schema validators are required.

### 17.13 Rebuilding The Existing Workflow Engine

Risk:

Platform-native layers may duplicate `backend/modules/workflow` or grow into a second full workflow engine.

Control:

- Treat current workflow engine as a separate existing capability.
- A1-A8 should focus on research workspace, CLI contract, and skill boundaries, not generic workflow scheduling.
- Reuse artifact and existing evidence functions.
- Do not prematurely replace existing workflow UI.

### 17.14 M1-M7成果失控

Risk:

Introducing dynamic agent logic too early could destabilize the validated evidence modules.

Control:

- Wrap M1-M7, do not rewrite them.
- Keep current tests.
- Add CLI contract and controller tests around wrappers.
- M6.5 remains direct fallback path.

### 17.15 Retrieval Latency And Source Coverage

Risk:

Agentic loop may retry slow retrieval routes repeatedly.

Control:

- Add route-level budgets before broad controller rollout.
- Record retrieval warnings.
- Prefer best-effort source-type retrieval.
- Do not allow controller to loop indefinitely on retrieval.

## 18. Immediate Recommendation

Do not continue directly into M8-M14 as linear modules.

Do not implement a platform-native controller as the main route.

First update the architecture around a Claude Code CLI-backed Controller. This document makes that update.

Then proceed with:

```text
A1-A5: build the platform-owned boundary
A6: define the Claude Code CLI Controller Contract
A7: implement the Claude Code CLI-backed Minimal Agent Loop
A8: add platform-native fallback baseline
A9: expand to landscape / gap / idea skills
```

A1-A5 are not building a fully platform-owned controller. They are building the controlled environment that allows Claude Code CLI to act as controller backend safely.

The next implementation step is still:

```text
A1: Research Workspace Model
```

But its purpose is now clearer:

```text
Create the workspace substrate required by the future CLI-backed controller.
```

Rationale for A1:

- It does not disturb M1-M7.
- It creates the substrate needed for a Claude Code CLI-backed controller.
- It makes artifacts and state concrete.
- It can be tested without LLM, frontend, or database changes.
- It gives M6.5 and M7 a place to live as workspace artifacts.

Only after A1-A5 should the project define the A6 CLI Controller Contract. Only after A6 should it implement the A7 CLI-backed minimal loop.

## 19. Open Questions For User Confirmation

1. Should the workspace root be:

```text
research_agent/research_tasks/{task_id}/
```

or should it reuse:

```text
research_agent/evidence_workflows/{workflow_id}/
```

with a new workspace manifest?

Recommendation: use `research_agent/research_tasks/{task_id}/` for the new architecture, while keeping existing `evidence_workflows/` artifacts readable.

2. Should A1 expose a CLI-facing workspace manifest shape immediately, or keep the initial workspace manifest generic?

Recommendation: include CLI-facing fields early, but keep them inert until A6.

3. Should A1 be purely backend filesystem workspace, or should it also add API visibility?

Recommendation: backend filesystem only first; API later.

4. Should existing `WorkflowStore` remain separate from the new CLI-backed controller?

Recommendation: yes. Do not merge them until A7 proves the CLI-backed controller loop.

5. How strict should the initial Claude Code CLI workspace sandbox be?

Recommendation: strict allowlist: task workspace files plus approved skill invocation interface only.

6. Should platform-native fallback A8 be implemented immediately after A7, or only after the CLI-backed loop shows instability?

Recommendation: implement A8 after A7 as a regression baseline, not as a replacement.

7. Should M4 retrieval performance fixes happen before A1?

Recommendation: M4 safe retrieval fixes are important, but they are orthogonal. If the next goal is architecture pivot, do A1 first. If the next goal is reliable real-topic runs, fix M4 safe retrieval before A6.

## 20. Final Position

The future platform should become:

> A Claude Code CLI-backed, workspace-based, evidence-gated, artifact-audited research agent system. Claude Code CLI provides the bottom-level agentic controller backend, while the platform owns scientific schemas, Evidence Card gates, registered skills, artifact persistence, validators, audit logs, and database safety boundaries.

M1-M7 are not obsolete. They are the first stable evidence skill set. The pivot is about moving from a fixed chain of modules to a Claude Code CLI-backed research operating loop constrained by platform-owned scientific contracts and audit gates.
