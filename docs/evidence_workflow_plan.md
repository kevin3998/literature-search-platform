# Evidence-Grounded Research Workflow Implementation Plan

> **For agentic workers:** REQUIRED EXECUTION RULE: before implementing any module, read this file, select exactly one module, restate that module's goal/scope/acceptance criteria to the user, implement only that module, run the listed tests, update that module's status, then stop for user confirmation. Do not batch multiple modules.

**Goal:** Build a task-driven, evidence-grounded research workflow system over the local materials literature library without introducing domain-specific material profiles.

**Architecture:** The system uses finite Task Profiles and general Evidence Cards as the stable core. Retrieval returns citable source candidates; open extraction converts text, abstract, figure, table, and caption sources into weakly structured but strongly traceable Evidence Cards; downstream landscape, gap, idea, risk screening, and reports consume Evidence Cards only.

**Tech Stack:** FastAPI backend, artifact-first workflow persistence, read-only access to existing SQLite literature/research databases, existing `literature_search` Research Agent integration, workflow engine under `backend/modules/workflow`, React/Vite frontend, pytest backend tests, Vite production build.

---

## 1. Project Positioning

This project is not:

- A general chatbot.
- A generic RAG wrapper.
- An automatic science agent.
- A Domain Profile driven materials expert database.
- A system that directly turns chunks into reports.
- A Modex/ARIS-style feature collection.

This project is:

> A Task Profile + Evidence Card + Evidence Role driven local materials research evidence workflow system.

Evidence Cards are not Claim Ledgers. An Evidence Card represents one traceable evidence unit extracted from a source. A Claim Ledger is a later writing/audit object that maps manuscript or report claims to one or more Evidence Cards. Do not collapse these objects.

The intended workflow is:

```text
Topic
→ Task Profile
→ Retrieval
→ Open Evidence Extraction
→ Evidence Role Classification
→ Entity / Relation Extraction
→ Evidence Ranking
→ Landscape Aggregation
→ Gap Mapping
→ Evidence-Constrained Idea Generation
→ Novelty / Feasibility / Risk Screening
→ Evidence-Grounded Report
```

The system must not use this as the primary design:

```text
Topic
→ Detect material domain
→ Load HER / membrane / electrolyte / TCO / alloy / catalyst profile
→ Extract through a domain schema
```

The governing principle is:

> Fixed research task structure, not fixed material domain structure. Fixed evidence roles, not fixed domain fields.

Database safety constraint:

> Existing literature and research databases are read-only inputs. The system may inspect and query them, but must not modify, migrate, delete, vacuum, rebuild, or otherwise mutate them. MVP persistence for the new evidence workflow is artifact-first and must not add an `evidence_cards` SQLite table.

Allowed database interaction is limited to read-only queries and calls through existing read APIs. New evidence workflow state must be written to artifacts, not to database tables.

LLM empirical validation boundary:

> Core evidence workflow modules must remain runnable in deterministic local tests without a live model. However, implementation and acceptance work may call an LLM for manual smoke tests, realistic extraction/classification/report checks, and bug discovery. Bugs found from live LLM responses should be fixed in code or prompts and then covered by deterministic regression tests where practical.

Live LLM calls are allowed only as validation or injected extractor/classifier/report-generation behavior. They must not become a hidden requirement for default unit tests, CI, artifact loading, ranking, retrieval adapters, or database access. Any live LLM test result used for acceptance should record the topic, input artifact or seed/card IDs, model/provider when available, observed failure, and the code or prompt fix made.

## 2. Current Assumptions

### 2.1 Observed Project Structure

The current repository at `/Users/chenlintao/literature-agent-platform` contains:

- `backend/main.py`: FastAPI application entry.
- `backend/api/*_router.py`: API routers for chat, corpus, literature search, workflows, modules, settings, and library browsing.
- `backend/core/memory_db.py`: SQLite schema for sessions, messages, turns, search results, evidence items, jobs, tool traces, research state, and workflow runs.
- `backend/core/session_store.py`: session, message, evidence, research state, and export persistence logic.
- `backend/core/report.py`: research record / export rendering with grounding summaries.
- `backend/modules/literature_search/`: wrapper around the external Research Agent code and local literature index.
- `backend/modules/literature_search/retrieval/`: Block 2 packet logic for intent, rewrite, breadth, coverage, selection, and normalized evidence candidates.
- `backend/modules/literature_search/agent/`: tool-calling chat agent, tool specs, role policy, and grounding.
- `backend/modules/workflow/`: native workflow templates, store, orchestrator, runners, external novelty sources, and agent-step prompts.
- `backend/modules/idea_discovery/` and `backend/modules/experiment_bridge/`: module placeholders / integration surface.
- `frontend/src/components/`: UI workbench, workflow view, retrieval inspector, research state panel, chat panels, and settings.
- `docs/capability-blocks/`: previous capability planning documents.

### 2.2 Observed Data / Index State

The local Research Agent data directory is expected at:

```text
/Users/chenlintao/paper-crawler-ops/literature_data
```

The current read-only research index inspected at:

```text
/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/research_index.sqlite
```

Observed counts:

| Entity | Count |
|---|---:|
| `papers` | 114,585 |
| `paper_sections` | 2,317,574 |
| `paper_chunks` | 3,936,792 |
| `paper_assets` | 924,180 |
| `documents` | 5,755,168 |

Observed index tables include:

- `papers`
- `paper_sections`
- `paper_chunks`
- `paper_assets`
- `documents`
- `documents_fts`
- `vector_index`
- `vector_records`
- `index_errors`
- `vector_errors`

Important observed columns:

- `papers`: `paper_id`, `article_id`, `doi`, `title`, `year`, `journal`, `site`, `article_dir`, `md_path`, `abstract_path`, `metadata_json`, `index_version`.
- `paper_sections`: `paper_id`, `section_id`, `heading`, `heading_norm`, `source_path`, `text`.
- `paper_chunks`: `paper_id`, `section_id`, `chunk_index`, `heading`, `source_path`, `content`.
- `paper_assets`: `paper_id`, `kind`, `source_path`, `label`, `caption`.

### 2.3 Existing Retrieval / Evidence Capabilities

Observed reusable capabilities:

- `LiteratureResearchService.search(...)` wraps the local Research Agent search.
- `LiteratureResearchService.acquire_evidence(...)` already builds an `EvidenceAcquisitionPacket`.
- `backend/modules/literature_search/retrieval/schemas.py` defines:
  - `QueryIntent`
  - `RewrittenQuery`
  - `EvidenceCandidate`
  - `Coverage`
  - `Breadth`
  - `EvidenceAcquisitionPacket`
- `EvidenceCandidate` already includes citable identifiers such as `evidence_id`, `paper_id`, `doi`, `section_id`, `chunk_index`, `source_path`, and asset fields.
- Chat grounding logic exists in `backend/modules/literature_search/agent/grounding.py`.
- Current persistence has `evidence_items`, but this is not yet a full task-level Evidence Card store.

### 2.4 Existing Workflow Capabilities

Observed workflow capabilities:

- `workflow_runs` and `workflow_steps` persist native workflow state.
- `backend/modules/workflow/templates.py` defines several templates, including `idea-discovery`.
- `idea-discovery` currently has runnable steps:
  - `research-lit`
  - `idea-creator`
  - `novelty-check`
  - `idea-report`
- `backend/modules/workflow/step_defs.py` contains prompts for idea generation, novelty check, and idea report.
- Current idea generation consumes an evidence block, but Evidence Cards are not yet the first-class intermediate object.

### 2.5 Existing Persistence Capabilities

Observed SQLite tables in `platform_memory.sqlite` include:

- `sessions`
- `messages`
- `turns`
- `search_results`
- `evidence_items`
- `artifacts`
- `conversation_artifact_links`
- `jobs`
- `job_events`
- `tool_traces`
- `research_state`
- `paper_states`
- `research_state_events`
- `workflow_runs`
- `workflow_steps`

Relevant current persistence limits:

- `evidence_items` stores turn/session evidence, snippets, metadata, and payload JSON.
- It is not yet a normalized, reusable, task-scoped Evidence Card store.
- There is no observed first-class `task_profiles` table or `evidence_cards` table.
- There is no observed landscape/gap/idea schema independent of generated Markdown artifacts.
- New evidence workflow persistence must not add an `evidence_cards` SQLite table during MVP. Evidence Cards should be persisted as workflow artifacts.

### 2.6 Current Problems / Directional Gaps

- Evidence Candidates and evidence items exist, but Evidence Cards are not yet the central data object.
- Figure/table/caption evidence exists in the index, but is not yet clearly promoted to first-class Evidence Card sources in the workflow.
- Current workflow is still close to `research-lit → idea → novelty → report`; it should be refactored toward `Task Profile → Evidence Cards → Landscape → Gap → Idea → Report`.
- Current `idea-creator` prompt can generate ideas before a structured landscape/gap artifact exists.
- Current report artifacts can use evidence, but the required chain should become stricter: source candidate → Evidence Card → landscape/gap/idea/claim → report.
- Current task/workflow templates include broad future flows such as automatic review and full pipeline. These should not drive the MVP.
- Current system has many platform capabilities; next development should be narrowly staged and module-gated.

### 2.7 Unknown / Need Inspection

- Unknown / Need inspection: exact shape of raw `documents` rows across all `kind` values, especially table content versus table captions.
- Unknown / Need inspection: whether figure images have OCR, structured labels, or only captions/assets metadata.
- Unknown / Need inspection: whether table contents are fully indexed as text, separate rows, or only caption/asset metadata in all publishers.
- Unknown / Need inspection: current artifact writer conventions inside the external `/Users/chenlintao/paper-crawler-ops/literature_research` package.
- Resolved constraint: Evidence Cards remain artifact-first during MVP; do not add a SQLite `evidence_cards` table.
- Unknown / Need inspection: exact frontend UX for Task Profile selection; existing `WorkflowView.jsx` should be inspected before implementation.
- Unknown / Need inspection: latency and token cost for extracting 50-200 Evidence Cards from a typical topic.
- Unknown / Need inspection: whether vector search is consistently available in the local environment or should be treated as optional with FTS fallback.

## 3. Core Architecture Principle

The core architecture is:

```text
Topic
→ Task Profile
→ Retrieval
→ Evidence Card
→ Landscape
→ Gap
→ Idea
→ Risk Screening
→ Report
```

### Why Task Profile, Not Domain Profile

Task Profiles are finite; material domains are effectively unbounded.

Do not create primary architecture around:

- `HERProfile`
- `MembraneProfile`
- `ElectrolyteProfile`
- `TCOProfile`
- `AlloyProfile`
- `CatalystProfile`
- `ThermoelectricProfile`
- `PerovskiteProfile`

Reasons:

- Materials science is too broad for maintainable domain schema proliferation.
- Many papers cross domains and mechanisms; forced domain assignment loses information.
- Early domain fields would constrain new topics and cross-field ideas.
- The MVP value is evidence grounding and workflow closure, not domain ontology completeness.
- Evidence roles such as `performance`, `mechanism`, `condition`, and `limitation` are reusable across domains.

Domain-specific fields may be added later only as optional extractors or post-processors. They must not be required for the MVP workflow.

### Source-to-Report Rule

Reports must not consume raw chunks directly.

Allowed chain:

```text
chunk / abstract / section / figure / table / caption
→ Evidence Card
→ landscape / gap / idea / claim
→ report
```

Blocked chain:

```text
chunk
→ report
```

Every key report claim must trace to Evidence Cards, and every Evidence Card must trace to source location.

## 4. Core Data Objects

### 4.1 Topic

**Purpose:** Captures the user research topic and any scope constraints.

**Minimum fields:**

- `topic_id`
- `raw_topic`
- `normalized_query`
- `scope`
- `time_range`
- `inclusion_notes`
- `exclusion_notes`
- `created_at`

**Relationships:**

- Has one selected Task Profile.
- Feeds retrieval.
- Appears in Evidence Card relevance fields.

**Persistence:** MVP can store in `workflow_runs.topic` plus manifest JSON. Later may become a normalized table if topics need reuse.

**MVP:** Yes.

### 4.2 EvidenceCardSeed

**Purpose:** A normalized, provenance-preserving source candidate adapter output. It bridges retrieval candidates and Evidence Cards without performing extraction or enrichment.

**Minimum fields:**

- `seed_id`
- `source_evidence_id`
- `paper_id`
- `doi`
- `title`
- `year`
- `journal`
- `source_path`
- `section_id`
- `chunk_id`
- `asset_id`
- `asset_type`
- `locator`
- `raw_text`
- `raw_caption`
- `candidate_kind`
- `retrieval_score`
- `warnings`

**Relationships:**

- Created from retrieval output, `EvidenceCandidate`, documents rows, or asset rows.
- Feeds M5 Open Evidence Extraction.
- One seed may produce zero, one, or several Evidence Cards, depending on extraction.

**Persistence:** Artifact-only in MVP, usually inside the source candidate packet or extraction cache.

**MVP:** Yes.

### 4.3 Task Profile

**Purpose:** Defines task-specific evidence roles, aggregation behavior, outputs, and audit gates.

**Minimum fields:**

- `profile_id`
- `name`
- `goal`
- `required_evidence_roles`
- `optional_evidence_roles`
- `input_schema`
- `artifact_sequence`
- `audit_rules`

**Relationships:**

- Selected by a workflow run.
- Guides retrieval, extraction, ranking, aggregation, and report export.

**Persistence:** MVP can be static Python registry. Persist selected `profile_id` and resolved profile snapshot in workflow manifest.

**MVP:** Yes.

### 4.4 Evidence Card

**Purpose:** First-class evidence object produced from retrievable source candidates.

**Minimum fields:** Defined in Section 5.

**Relationships:**

- Created from one source candidate.
- Can support multiple landscape units, gaps, ideas, claims, and report sections.
- May link to current `evidence_id` from `documents.id` as a source-level citation.
- Is not a Claim Ledger entry. It does not assert that a manuscript/report claim is verified; it only records source-grounded evidence and extraction metadata.

**Persistence:** Yes, artifact-first only in MVP. Do not add an `evidence_cards` SQLite table.

**MVP:** Yes.

### 4.5 Evidence Role

**Purpose:** Describes what function the evidence serves in a research task.

**Minimum values:**

- `background`
- `material_system`
- `method`
- `structure`
- `property`
- `performance`
- `mechanism`
- `characterization`
- `comparison`
- `limitation`
- `condition`
- `calculation`
- `hypothesis`
- `figure_evidence`
- `table_evidence`

**Relationships:**

- Attached to Evidence Cards.
- Used by Task Profiles for extraction/ranking/coverage.
- Stored as one `primary_role` plus zero or more `secondary_roles`.

**Persistence:** Stored inside Evidence Card. No separate table in MVP.

**MVP:** Yes.

### 4.6 Entity

**Purpose:** Open extraction of scientific entities without domain-specific fields.

**Minimum categories:**

- `materials`
- `methods`
- `properties`
- `metrics`
- `values`
- `units`
- `conditions`
- `characterization_tools`
- `mechanisms`
- `applications`

**Relationships:**

- Stored in Evidence Cards.
- Used for landscape grouping and comparison tables.

**Persistence:** Stored inside Evidence Card JSON in MVP.

**MVP:** Yes.

### 4.7 Relation

**Purpose:** Represents an open factual relation extracted from evidence.

**Minimum fields:**

- `subject`
- `predicate`
- `object`
- `qualifiers`
- `condition`
- `confidence`

**Relationships:**

- Stored in Evidence Card.
- Supports landscape/gap/claim synthesis.

**Persistence:** Stored inside Evidence Card JSON in MVP.

**MVP:** Yes.

### 4.8 Landscape Unit

**Purpose:** Aggregated research landscape row or cluster derived from Evidence Cards.

**Minimum fields:**

- `landscape_id`
- `topic_id`
- `axis`
- `label`
- `summary`
- `evidence_card_ids`
- `coverage_notes`
- `limitations`

**Relationships:**

- Derived from Evidence Cards.
- Feeds Gap Mapping.

**Persistence:** MVP artifact JSON/Markdown only.

**MVP:** Yes.

### 4.9 Gap

**Purpose:** Traceable research gap, unresolved conflict, missing evidence, limitation, or underexplored combination.

**Minimum fields:**

- `gap_id`
- `gap_type`
- `statement`
- `supporting_evidence_card_ids`
- `missing_evidence`
- `why_it_matters`
- `risk_notes`

**Relationships:**

- Derived from Landscape Units and Evidence Cards.
- Feeds Candidate Ideas.

**Persistence:** MVP artifact JSON/Markdown.

**MVP:** Yes.

### 4.10 Candidate Idea

**Purpose:** Evidence-constrained candidate research direction.

**Minimum fields:**

- `idea_id`
- `title`
- `scientific_rationale`
- `gap_ids`
- `supporting_evidence_card_ids`
- `unsupported_assumptions`
- `required_validation`
- `recommended_experiments`

**Relationships:**

- Must reference one or more gaps.
- Must reference supporting Evidence Cards.
- Feeds risk screening and report.

**Persistence:** MVP artifact JSON/Markdown.

**MVP:** Yes.

### 4.11 Risk Screening Result

**Purpose:** Conservative novelty, feasibility, and risk screening.

**Minimum fields:**

- `idea_id`
- `novelty_label`
- `feasibility_label`
- `risk_label`
- `closest_prior_work`
- `local_overlap_evidence_card_ids`
- `missing_checks`
- `manual_verification_required`

**Relationships:**

- Attached to Candidate Ideas.
- Feeds report.

**Persistence:** MVP artifact JSON/Markdown.

**MVP:** Yes.

### 4.12 Evidence-Grounded Report

**Purpose:** Final traceable report artifact.

**Minimum sections:**

- Scope lock
- Search summary
- Evidence coverage
- Landscape table
- Gap table
- Candidate ideas
- Novelty / feasibility / risk screening
- Evidence index
- Unsupported assumptions
- Manual verification checklist
- Risk notes
- Source grounding

**Relationships:**

- Consumes Evidence Cards, Landscape Units, Gaps, Candidate Ideas, and Risk Screening Results.

**Persistence:** Markdown artifact plus JSON manifest.

**MVP:** Yes.

## 5. Minimal Evidence Card Schema

Use weak structure plus strong provenance. Do not add domain-specific required fields.

```yaml
evidence_id:
seed_id:
source_evidence_id:
paper_id:
title:
doi:
year:
journal:

source:
  source_path:
  section_id:
  chunk_id:
  asset_id:
  asset_type: text | abstract | figure | table | caption
  locator:

primary_role: background | material_system | method | structure | property | performance | mechanism | characterization | comparison | limitation | condition | calculation | hypothesis | figure_evidence | table_evidence
secondary_roles:
  - background | material_system | method | structure | property | performance | mechanism | characterization | comparison | limitation | condition | calculation | hypothesis | figure_evidence | table_evidence

verbatim_snippet:
normalized_statement:

entities:
  materials: []
  methods: []
  properties: []
  metrics: []
  values: []
  units: []
  conditions: []
  characterization_tools: []
  mechanisms: []
  applications: []

relations:
  - subject:
    predicate:
    object:
    qualifiers:
    condition:
    confidence:

relevance:
  topic:
  relevance_reason:
  relevance_score:

support:
  support_strength: direct | indirect | weak
  extraction_confidence:
  uncertainty:
  unsupported_parts: []
```

### Evidence Source Requirements

Evidence Cards may come from:

- Full-text section chunks.
- Abstract text.
- Section text.
- Figure captions.
- Table captions.
- Table content.
- Figure/table asset metadata.

Figure and table evidence is first-class, not attachment-only.

### Role Policy

- Every Evidence Card must have exactly one `primary_role`.
- Every Evidence Card may have zero or more `secondary_roles`.
- `primary_role` is used for coverage, ranking, and landscape grouping.
- `secondary_roles` preserve multi-use evidence without duplicating cards.
- Role values are task/evidence roles, not domain fields.

### Evidence Card Is Not Claim Ledger

Evidence Cards are source-grounded evidence units. They do not certify a report or manuscript claim by themselves. Later Claim Ledger objects must map claims to Evidence Cards and evaluate support status separately.

### Evidence ID Policy

- Source-level citable `evidence_id` may reuse the existing `E{documents.id}` convention where available.
- Card-level IDs should be deterministic for cacheability, such as a hash of `workflow_id`, source `evidence_id`, source locator, and extraction version.
- Do not mint IDs that cannot be traced back to `paper_id` and source location.
- `EvidenceCardSeed` IDs should be deterministic and stable across retries when the same source candidate is used.

## 6. Task Profile Design

MVP activation rule:

- Only `Topic-to-Report` is active in the first implementation sequence.
- All other Task Profiles are stubs: they may be defined in the registry for future compatibility, but must not be exposed as runnable workflows until their modules are explicitly implemented and accepted.
- Stub profiles must not trigger extraction, report generation, UI promises, or background jobs.

### 6.1 Topic-to-Report

**Goal:** Produce a traceable research report from a topic.

**Required evidence roles:**

- `background`
- `material_system`
- `method`
- `property`
- `performance`
- `mechanism`
- `comparison`
- `limitation`
- `condition`
- `figure_evidence`
- `table_evidence`

**Inputs:**

- Topic
- Scope options
- Retrieval budget
- Optional year/site/journal filters

**Outputs:**

- Scope lock
- Search summary
- Evidence coverage
- Landscape table
- Gap table
- Candidate ideas
- Risk screening
- Evidence-grounded report
- Evidence index
- Manual verification checklist

**Intermediate artifacts:**

- Evidence Card set
- Landscape units
- Gap table
- Candidate ideas
- Screening results

**Audit points:**

- Every report claim links to Evidence Cards.
- Every idea links to at least one gap.
- Every gap links to Evidence Cards and missing evidence.
- Unsupported assumptions are explicitly listed.

**MVP:** Yes.

### 6.2 Literature Landscape

**Goal:** Map the structure of a research area without generating ideas.

**Required evidence roles:**

- `background`
- `material_system`
- `method`
- `performance`
- `mechanism`
- `comparison`
- `limitation`

**Inputs:** Topic, scope, retrieval budget.

**Outputs:** Landscape units, evidence coverage, cluster summaries, evidence index.

**Intermediate artifacts:** Evidence Card set, landscape table.

**Audit points:** Each landscape unit must cite Evidence Cards and expose coverage limitations.

**MVP:** Stub only; implemented later or as an internal substage of Topic-to-Report after evidence workflow basics are stable.

### 6.3 Performance Comparison

**Goal:** Compare metrics across materials/methods while preserving condition mismatch warnings.

**Required evidence roles:**

- `material_system`
- `performance`
- `condition`
- `comparison`
- `table_evidence`

**Inputs:** Topic or selected materials, metric focus, optional filters.

**Outputs:** Comparison table, metric normalization notes, condition mismatch warnings, benchmark limitations.

**Intermediate artifacts:** Performance Evidence Cards, normalized comparison rows.

**Audit points:** Values must preserve unit, condition, source, and extraction confidence.

**MVP:** Stub only; support through Evidence Cards and later specialize.

### 6.4 Mechanism Analysis

**Goal:** Analyze proposed mechanisms and competing explanations.

**Required evidence roles:**

- `mechanism`
- `characterization`
- `calculation`
- `comparison`
- `limitation`
- `condition`

**Inputs:** Topic or selected mechanism claim.

**Outputs:** Mechanistic claims, supporting evidence, alternative explanations, unsupported assumptions, required validation.

**Intermediate artifacts:** Mechanism Evidence Cards, relation map, claim support table.

**Audit points:** Distinguish direct characterization evidence from interpretation/hypothesis.

**MVP:** Stub only; support roles in Topic-to-Report.

### 6.5 Gap Analysis

**Goal:** Identify traceable gaps, contradictions, limitations, and underexplored combinations.

**Required evidence roles:**

- `limitation`
- `comparison`
- `mechanism`
- `condition`
- `performance`
- `hypothesis`

**Inputs:** Landscape units and Evidence Cards.

**Outputs:** Gap table with support, missing evidence, why-it-matters, and risk notes.

**Intermediate artifacts:** Gap artifact JSON/Markdown.

**Audit points:** No gap may be generated without evidence support and explicit missing evidence.

**MVP:** Stub only until M8/M9 are reached; not active at M3.

### 6.6 Idea Discovery

**Goal:** Generate candidate ideas constrained by evidence-backed gaps.

**Required evidence roles:**

- `limitation`
- `comparison`
- `mechanism`
- `performance`
- `method`
- `condition`

**Inputs:** Gap table, Evidence Cards, landscape units.

**Outputs:** Candidate ideas with supporting evidence, unsupported assumptions, validation needs, and recommended experiments.

**Intermediate artifacts:** Candidate ideas JSON/Markdown.

**Audit points:** Every idea must reference gaps and Evidence Cards. Free brainstorming without gap linkage is not allowed.

**MVP:** Stub only until M10; not active at M3.

### 6.7 Novelty Screening

**Goal:** Perform conservative novelty and overlap screening.

**Required evidence roles:**

- `comparison`
- `method`
- `material_system`
- `mechanism`
- `performance`
- `limitation`

**Inputs:** Candidate ideas, Evidence Cards, optional external scholarly candidates.

**Outputs:** Novelty labels, closest prior work, overlap notes, manual verification items.

**Intermediate artifacts:** Screening record JSON/Markdown.

**Audit points:** Never state final innovation. Use labels such as `likely known`, `partially explored`, `potentially novel combination`, `insufficient evidence`, and `high-risk novelty claim`.

**MVP:** Stub only until M11; not active at M3.

### 6.8 Experiment Planning

**Goal:** Turn a selected idea into a human-reviewable experimental matrix.

**Required evidence roles:**

- `method`
- `material_system`
- `condition`
- `characterization`
- `performance`
- `limitation`
- `mechanism`

**Inputs:** Selected idea, Evidence Cards, risk screening.

**Outputs:** Sample matrix, synthesis variables, control groups, characterization matrix, testing matrix, expected observations, failure modes, missing evidence.

**Intermediate artifacts:** Experiment plan JSON/Markdown.

**Audit points:** Must disclose missing evidence and unsupported assumptions; must not claim automatic experiment execution.

**MVP:** No. Mid-term module.

### 6.9 Claim Support / Manuscript Writing

**Goal:** Support writing through claim ledger and evidence audit.

**Required evidence roles:**

- Any role relevant to the claim ledger.

**Inputs:** Evidence Cards, candidate claims, section outline.

**Outputs:** Claim ledger, verified claims, unsupported claim audit, paragraph drafts, revision notes.

**Intermediate artifacts:** Claim ledger JSON/Markdown, manuscript support notes.

**Audit points:** Manuscript prose must be generated from verified claims, not raw chunks.

**MVP:** No. Later module.

## 7. Planned Module Roadmap

### Status Legend

- `Not Started`: no implementation work has begun.
- `In Progress`: current active module.
- `Done`: acceptance criteria passed and tests reported.
- `Blocked`: cannot proceed without plan revision, user decision, or external dependency.

### M0: Project Inspection and Plan Finalization

**Module ID:** M0

**Module name:** Project Inspection and Plan Finalization

**Goal:** Confirm the plan, current assumptions, and module order before functional development.

**Scope:**

- Review this plan with the user.
- Adjust module order, file placement, and MVP boundaries if needed.
- Freeze execution protocol for M1.

**Inputs:**

- `docs/evidence_workflow_plan.md`
- User feedback
- Existing repository state

**Outputs:**

- Confirmed plan file
- Updated `Unknown / Need inspection` list if necessary
- Clear decision whether to start M1

**Files likely to change:**

- Modify: `docs/evidence_workflow_plan.md`

**Dependencies:** None.

**Acceptance criteria:**

- User confirms the plan or requests specific revisions.
- M1 entry has clear scope and likely files.
- No functional code has been changed during M0.

**Test strategy:**

- Documentation-only review.
- Confirm `docs/evidence_workflow_plan.md` exists and contains all required sections.

**Risks:**

- Plan may still be too broad.
- Existing workflow code may constrain ideal module boundaries.

**Rollback plan:**

- Revert edits to `docs/evidence_workflow_plan.md` only.

**Status:** Done

**Completion notes:** User confirmed the plan by requesting M1 implementation. No functional code was changed during M0.

### M1: Core Evidence Card Schema

**Module ID:** M1

**Module name:** Core Evidence Card Schema

**Goal:** Add a general Evidence Card contract without introducing Domain Profiles.

**Scope:**

- Define Evidence Card dataclass / Pydantic-compatible schema.
- Define `EvidenceCardSeed` as the source candidate adapter output.
- Define adapter helpers for converting existing `EvidenceCandidate`-like dicts into `EvidenceCardSeed`.
- Define Evidence Role enum-like constants.
- Define open `entities` and `relations` structures.
- Add validation helpers for provenance and required fields.
- Do not implement extraction logic yet.

**Inputs:**

- Section 5 schema
- Existing `EvidenceCandidate` from `backend/modules/literature_search/retrieval/schemas.py`

**Outputs:**

- Evidence Card schema module
- EvidenceCardSeed schema and source candidate adapter
- Unit tests for schema validation and serialization

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/__init__.py`
- Create: `backend/modules/evidence_workflow/schemas.py`
- Create: `backend/tests/test_evidence_card_schema.py`

**Dependencies:** M0 confirmed.

**Acceptance criteria:**

- Evidence Card supports text, abstract, figure, table, and caption source types.
- Evidence Card uses exactly one `primary_role` and zero or more `secondary_roles`.
- Evidence roles are general and do not include domain names such as HER, membrane, electrolyte, or TCO.
- Entities and relations are open lists/dicts, not domain-specific required fields.
- Schema requires provenance fields sufficient to trace back to source.
- EvidenceCardSeed can be created from a representative existing `EvidenceCandidate` dict without losing provenance.
- Tests pass for valid card, missing provenance, primary/secondary role card, open relation card, and seed adapter.

**Test strategy:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_schema.py -q`
- `PYTHONPATH=backend pytest backend/tests -q`

**Risks:**

- Over-modeling the schema too early.
- Making fields mandatory that are not available for all asset types.

**Rollback plan:**

- Remove `backend/modules/evidence_workflow/`.
- Remove `backend/tests/test_evidence_card_schema.py`.

**Verification results:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_schema.py -q` -> 7 passed.
- `PYTHONPATH=backend pytest backend/tests -q` -> 199 passed.

**Status:** Done

### M2: Evidence Storage / Artifact Persistence

**Module ID:** M2

**Module name:** Evidence Storage / Artifact Persistence

**Goal:** Support Evidence Card save/read/cache and source traceability.

**Scope:**

- Implement a small store for workflow-scoped Evidence Card artifacts.
- Use artifact-first persistence only.
- Store JSON artifacts under `research_agent/evidence_workflows/{workflow_id}/`.
- Do not add a SQLite `evidence_cards` table.
- Do not modify existing literature/research databases.
- Do not build extraction yet.

**Inputs:**

- Evidence Card objects from M1
- Workflow ID
- Source candidate metadata

**Outputs:**

- Save/read/list Evidence Card set
- Artifact metadata compatible with current job/artifact event style

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/store.py`
- Create: `backend/tests/test_evidence_card_store.py`
- Do not modify: `backend/core/memory_db.py` for `evidence_cards`
- Do not modify: existing literature or Research Agent SQLite databases

**Dependencies:** M1.

**Acceptance criteria:**

- Can persist and reload a list of Evidence Cards.
- Reloaded cards preserve IDs, source locator, roles, entities, relations, and support fields.
- Store is workflow-scoped and does not trigger full-library processing.
- Cache format includes an extraction/schema version.
- No SQLite schema changes are introduced.

**Test strategy:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_store.py -q`
- Existing backend test suite.

**Risks:**

- Duplicating existing `evidence_items` responsibilities.
- Accidentally treating artifact persistence as permission to mutate existing databases.

**Rollback plan:**

- Remove store module and tests.
- Remove generated test artifacts. No database rollback should be needed because M2 must not modify SQLite schemas.

**Verification results:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_store.py -q` -> 10 passed.
- `PYTHONPATH=backend pytest backend/tests -q` -> 209 passed.

**Status:** Done

### M3: Topic Scope and Task Profile Input

**Module ID:** M3

**Module name:** Topic Scope and Task Profile Input

**Goal:** Add Task Profile selection and scope lock as workflow inputs.

**Scope:**

- Create a finite Task Profile registry.
- Add and activate only the `topic-to-report` profile.
- Define other Task Profiles as non-runnable stubs only.
- Record selected profile ID and profile snapshot in the workflow manifest payload/artifact without adding database columns or tables.
- Surface scope lock fields in backend response.
- Frontend changes only if required for selecting/displaying the profile.

**Inputs:**

- User topic
- Scope options
- Task Profile ID

**Outputs:**

- Workflow manifest with task profile and scope lock
- Profile-specific role requirements

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/task_profiles.py`
- Modify: `backend/modules/workflow/store.py`
- Modify: `backend/modules/workflow/templates.py`
- Modify: `backend/api/workflow_router.py`
- Test: `backend/tests/test_workflow_engine.py`
- Possibly modify: `frontend/src/components/WorkflowView.jsx`
- Possibly modify: `frontend/src/api/client.js`

**Dependencies:** M1. M2 optional if profile recording does not require card artifacts.

**Acceptance criteria:**

- Workflow run can be created with `task_profile_id = topic-to-report`.
- Manifest contains required evidence roles and audit rules.
- Stub profiles are visible to backend tests as definitions but cannot be launched as runnable workflows.
- No Domain Profile concept is introduced.
- No database schema changes are introduced.
- Existing workflow creation tests still pass.

**Test strategy:**

- Add focused backend tests for profile registry and workflow manifest.
- Run `PYTHONPATH=backend pytest backend/tests/test_workflow_engine.py -q`.
- Run full backend tests.
- If frontend changed, run `cd frontend && npm run build`.

**Risks:**

- Coupling Task Profile too tightly to current workflow templates.
- UI change expanding scope.

**Rollback plan:**

- Revert profile registry and workflow manifest changes.
- Keep M1 schema unaffected.

**Verification results:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_workflow_task_profiles.py -q` -> 6 passed.
- `PYTHONPATH=backend pytest backend/tests/test_workflow_router_task_profile.py -q` -> 3 passed.
- `PYTHONPATH=backend pytest backend/tests/test_workflow_engine.py -q` -> 21 passed.
- `PYTHONPATH=backend pytest backend/tests -q` -> 222 passed.

**Status:** Done

### M4: Topic-Scope Retrieval

**Module ID:** M4

**Module name:** Topic-Scope Retrieval

**Goal:** Reuse existing retrieval to produce source candidates for a selected topic and Task Profile.

**Scope:**

- Wrap existing `acquire_evidence` for Task Profile needs.
- Produce `EvidenceCardSeed` source candidates.
- Include text and abstract candidates when available.
- Attempt figure/table/caption candidates on a best-effort basis.
- Emit coverage warnings when figure/table/caption candidates are unavailable, incomplete, or unsupported by retrieval output.
- Do not extract Evidence Cards yet beyond candidate normalization.

**Inputs:**

- Topic
- Task Profile
- Scope lock
- Retrieval budget

**Outputs:**

- Source candidate packet
- EvidenceCardSeed list
- Coverage notes
- Warnings for missing source types or fallback retrieval

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/retrieval.py`
- Test: `backend/tests/test_evidence_workflow_retrieval.py`
- Possibly modify: `backend/modules/literature_search/service.py` to expose asset/caption candidate helpers if needed
- Possibly modify: `backend/modules/literature_search/retrieval/packet.py`

**Dependencies:** M3.

**Acceptance criteria:**

- Given a topic, returns bounded source candidates with `paper_id`, `evidence_id` or locator, `source_path`, and source type.
- Retrieval remains topic-scoped and does not scan the full library.
- Figure/table/caption retrieval is best-effort and emits coverage warnings when incomplete.
- Coverage output marks missing source types instead of hallucinating them.

**Test strategy:**

- Unit tests with a fake search function returning mixed text/asset results.
- Integration test with existing service can be skipped if environment-specific, but code must handle service absence cleanly.
- Existing retrieval packet tests continue to pass.

**Risks:**

- Asset retrieval support may be incomplete in current Research Agent.
- Search output may not always expose enough asset metadata.

**Rollback plan:**

- Remove evidence workflow retrieval wrapper.
- Leave underlying literature search untouched.

**Verification results:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_workflow_retrieval.py -q` -> 8 passed.
- `PYTHONPATH=backend pytest backend/tests/test_retrieval_packet.py -q` -> 20 passed.
- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_schema.py -q` -> 7 passed.
- `PYTHONPATH=backend pytest backend/tests -q` -> 230 passed.

**Status:** Done

### M5: Open Evidence Extraction

**Module ID:** M5

**Module name:** Open Evidence Extraction

**Goal:** Convert text, abstract, figure caption, table caption, and table content seeds into initial Evidence Card drafts.

**Scope:**

- Implement source-type-aware extraction pipeline.
- Use Task Profile evidence roles as extraction targets.
- Support deterministic fallback extraction for metadata/provenance even when LLM extraction is unavailable.
- Produce initial card drafts with provenance, verbatim snippet, normalized statement, relevance, and support fields.
- Do not perform final role classification.
- Do not perform entity extraction.
- Do not perform relation extraction.
- Do not generate landscape/gaps/ideas yet.

**Inputs:**

- EvidenceCardSeed list from M4
- Task Profile
- Topic

**Outputs:**

- Initial Evidence Card draft set
- Extraction warnings
- Cache artifact

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/extraction.py`
- Create: `backend/modules/evidence_workflow/prompts.py`
- Modify: `backend/modules/evidence_workflow/store.py`
- Test: `backend/tests/test_open_evidence_extraction.py`

**Dependencies:** M1, M2, M4.

**Acceptance criteria:**

- Extracts initial Evidence Card drafts from at least text and caption-like seeds in tests.
- Stores verbatim snippet and normalized statement separately.
- Preserves source locator and source type.
- Does not require domain-specific metric fields.
- Does not populate final entities or relations.
- Does not claim a final primary role unless it is deterministically obvious from source type; M6 is responsible for final role enrichment.
- Failed extraction yields warning and does not block other candidates.

**Test strategy:**

- Scripted extractor tests with representative text, figure caption, and table caption examples.
- Optional live LLM smoke tests through the injected extractor interface; failures should be reduced to deterministic regression tests when possible.
- Store round-trip test after extraction.
- Full backend tests.

**Risks:**

- LLM extraction may be noisy.
- Captions may contain dense metric content requiring careful prompts.
- Token cost can grow quickly.

**Rollback plan:**

- Disable extraction stage through feature flag or workflow availability.
- Preserve source candidates for inspection.

**Verification results:**

- `PYTHONPATH=backend pytest backend/tests/test_open_evidence_extraction.py -q` -> 9 passed.
- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_schema.py -q` -> 7 passed.
- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_store.py -q` -> 10 passed.
- `PYTHONPATH=backend pytest backend/tests/test_evidence_workflow_retrieval.py -q` -> 8 passed.
- `PYTHONPATH=backend pytest backend/tests -q` -> 239 passed.

**Status:** Done

### M6: Evidence Role Classification and Entity / Relation Extraction

**Module ID:** M6

**Module name:** Evidence Role Classification and Entity / Relation Extraction

**Goal:** Enrich initial Evidence Card drafts with final primary role, secondary roles, open entities, and relations.

**Scope:**

- Assign exactly one final `primary_role` for each card.
- Assign zero or more `secondary_roles`.
- Extract open entity lists and relation triples.
- Add confidence and uncertainty fields.
- Do not introduce material-domain schemas.

**Inputs:**

- Initial Evidence Card drafts from M5
- Task Profile role requirements

**Outputs:**

- Enriched Evidence Cards with final primary role, secondary roles, entities, relations, and support fields
- Role coverage summary

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/classification.py`
- Modify: `backend/modules/evidence_workflow/extraction.py`
- Modify: `backend/modules/evidence_workflow/schemas.py`
- Test: `backend/tests/test_evidence_role_entity_relation.py`

**Dependencies:** M5.

**Acceptance criteria:**

- A performance evidence example can store metric/value/unit/condition without domain-specific fields.
- A mechanism evidence example can store mechanism/characterization relation.
- A limitation evidence example can be classified with `primary_role = limitation`.
- Role classifier accepts one primary role plus multiple secondary roles per card.
- Tests assert no required field references a material domain profile.

**Test strategy:**

- Unit tests using scripted classifier output.
- Optional live LLM smoke tests through the injected classifier interface; failures should be reduced to deterministic regression tests when possible.
- Schema validation tests for multi-role cards and relation confidence.
- Full backend tests.

**Risks:**

- Role classification ambiguity.
- Overfitting tests to examples.

**Rollback plan:**

- Keep initial Evidence Card drafts from M5 and disable downstream stages that require enriched Evidence Cards.

**Verification results:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_role_entity_relation.py -q` -> 9 passed.
- `PYTHONPATH=backend pytest backend/tests/test_open_evidence_extraction.py -q` -> 9 passed.
- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_schema.py -q` -> 7 passed.
- `PYTHONPATH=backend pytest backend/tests/test_evidence_card_store.py -q` -> 10 passed.
- `PYTHONPATH=backend pytest backend/tests -q` -> 248 passed.

**Status:** Done

### M6.5: Minimal Topic-to-Evidence Report Slice

**Module ID:** M6.5

**Module name:** Minimal Topic-to-Evidence Report Slice

**Goal:** Prove the evidence workflow can run end-to-end from topic to a minimal evidence report before building landscape, gap, idea, and full report stages.

**Scope:**

- Assemble a minimal workflow slice:
  - topic-to-report Task Profile input
  - topic-scope retrieval
  - EvidenceCardSeed generation
  - initial card extraction
  - role/entity/relation enrichment
  - artifact-first persistence
  - minimal evidence report export
- The minimal report includes scope lock, retrieval summary, Evidence Card table, role coverage, source-type coverage warnings, and manual verification checklist.
- Do not implement landscape aggregation.
- Do not implement gap mapping.
- Do not implement idea generation.
- Do not implement novelty screening.

**Inputs:**

- Topic
- Task Profile `topic-to-report`
- Enriched Evidence Cards from M6

**Outputs:**

- Minimal topic-to-evidence Markdown report
- Minimal JSON manifest with Evidence Card IDs and source coverage

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/minimal_report.py`
- Possibly modify: `backend/modules/evidence_workflow/store.py`
- Test: `backend/tests/test_minimal_topic_to_evidence_report.py`

**Dependencies:** M1, M2, M3, M4, M5, M6.

**Acceptance criteria:**

- Produces a minimal report from enriched Evidence Cards without raw chunk-to-report generation.
- Report includes Evidence Card IDs, source locators, primary/secondary roles, coverage warnings, and manual verification checklist.
- Figure/table/caption absence is reported as coverage warning, not hidden.
- Report does not include landscape, gap, idea, novelty, or full research synthesis sections.

**Test strategy:**

- Golden Markdown structure test.
- Test that raw chunks do not appear unless they are inside Evidence Card snippets.
- Test that missing figure/table/caption coverage appears in warnings.
- Optional live LLM smoke test of injected M5/M6 extraction/classification on a small source candidate packet before report rendering.

**Risks:**

- The minimal slice could expand into full report too early.
- Users may confuse it with the final evidence-grounded research report.

**Rollback plan:**

- Keep Evidence Cards and artifacts; remove minimal report generation entry point.

**Verification results:**

- `PYTHONPATH=backend pytest backend/tests/test_minimal_topic_to_evidence_report.py -q` -> 6 passed.
- `PYTHONPATH=backend pytest backend/tests/test_minimal_topic_to_evidence_report.py backend/tests/test_evidence_workflow_retrieval.py backend/tests/test_open_evidence_extraction.py backend/tests/test_evidence_role_entity_relation.py backend/tests/test_evidence_card_store.py -q` -> 42 passed.
- `PYTHONPATH=backend pytest backend/tests -q` -> 254 passed.

**Status:** Done

### M7: Evidence Ranking and Diversity Selection

**Module ID:** M7

**Module name:** Evidence Ranking and Diversity Selection

**Goal:** Select a representative Evidence Card set by relevance, support strength, role coverage, source diversity, and paper diversity.

**Scope:**

- Implement scoring and diversity selection.
- Add coverage report by role and source type.
- Prevent one paper or one source type from dominating the evidence set.

**Inputs:**

- Evidence Cards from M6
- Task Profile
- Retrieval budget

**Outputs:**

- Ranked Evidence Cards
- Selected Evidence Set
- Coverage and diversity warnings

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/ranking.py`
- Test: `backend/tests/test_evidence_ranking.py`
- Extend: `backend/modules/evidence_workflow/store.py`

**Dependencies:** M6. M6.5 should be completed before using ranking in a user-facing workflow.

**Acceptance criteria:**

- Cards are ranked by relevance and support strength.
- Selection preserves required role coverage when available.
- Dominant-paper warnings are emitted when selected cards over-rely on one paper.
- Source diversity includes text/caption/table/figure when available.

**Test strategy:**

- Deterministic ranking tests with synthetic cards.
- Coverage warning tests.
- Full backend tests.

**Risks:**

- Scoring can become opaque.
- Diversity may suppress the most relevant evidence if weights are poorly chosen.

**Rollback plan:**

- Fall back to simple relevance-sort plus explicit warning that diversity selection is disabled.

**Verification:**

- `PYTHONPATH=backend pytest backend/tests/test_evidence_ranking.py -q` → 8 passed
- `PYTHONPATH=backend pytest backend/tests/test_evidence_ranking.py backend/tests/test_evidence_role_entity_relation.py backend/tests/test_minimal_topic_to_evidence_report.py backend/tests/test_evidence_card_store.py -q` → 33 passed
- `PYTHONPATH=backend pytest backend/tests -q` → 262 passed

**Status:** Done

### M8: Landscape Aggregation

**Module ID:** M8

**Module name:** Landscape Aggregation

**Goal:** Build landscape units from selected Evidence Cards.

**Scope:**

- Aggregate cards by general axes such as material system, method, mechanism, performance metric, condition, and limitation.
- Produce landscape table JSON/Markdown.
- Do not generate gaps or ideas yet.

**Inputs:**

- Selected Evidence Cards from M7
- Task Profile

**Outputs:**

- Landscape units
- Landscape artifact
- Coverage notes

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/landscape.py`
- Test: `backend/tests/test_landscape_aggregation.py`

**Dependencies:** M7.

**Acceptance criteria:**

- Each landscape unit references Evidence Card IDs.
- Landscape axes are task/evidence based, not domain profile based.
- Output includes limitations and coverage notes.
- No unit is created without evidence.

**Test strategy:**

- Unit tests using synthetic card sets.
- Artifact shape tests.
- Full backend tests.

**Risks:**

- Aggregation may produce overly broad units.
- Entity extraction quality affects landscape quality.

**Rollback plan:**

- Emit role-grouped evidence summary instead of full landscape aggregation.

**Status:** Not Started

### M9: Gap Mapping

**Module ID:** M9

**Module name:** Gap Mapping

**Goal:** Generate a traceable gap table from landscape units and limitation evidence.

**Scope:**

- Identify gaps, contradictions, underexplored combinations, missing evidence, and limitations.
- Each gap must cite Evidence Cards and state missing evidence.
- Do not generate ideas yet.

**Inputs:**

- Landscape units from M8
- Evidence Cards from M7

**Outputs:**

- Gap table JSON/Markdown

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/gaps.py`
- Test: `backend/tests/test_gap_mapping.py`

**Dependencies:** M8.

**Acceptance criteria:**

- Every gap has supporting Evidence Card IDs.
- Every gap has `missing_evidence`.
- Gaps distinguish observed limitation from inferred opportunity.
- No unsupported gap is emitted as a factual conclusion.

**Test strategy:**

- Synthetic landscape/gap tests.
- Unsupported gap rejection tests.
- Full backend tests.

**Risks:**

- Gap generation can drift into free ideation.
- Missing evidence may be confused with novelty.

**Rollback plan:**

- Disable generated gaps and output limitation-only gap candidates for manual review.

**Status:** Not Started

### M10: Evidence-Constrained Idea Generation

**Module ID:** M10

**Module name:** Evidence-Constrained Idea Generation

**Goal:** Generate candidate ideas only from traceable gaps and Evidence Cards.

**Scope:**

- Add a new evidence workflow idea stage for gap-grounded idea generation.
- Do not modify the legacy `idea-discovery` workflow in this module.
- Do not replace existing `idea-creator`, `novelty-check`, or `idea-report` steps during M10.
- Each idea must contain gap links, evidence links, unsupported assumptions, validation needs, and recommended experiments.
- Do not run novelty screening yet except local overlap notes already present in evidence.

**Inputs:**

- Gap table from M9
- Evidence Cards
- Landscape units

**Outputs:**

- Candidate ideas JSON/Markdown

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/ideas.py`
- Possibly create: `backend/modules/evidence_workflow/idea_stage.py`
- Possibly modify: `backend/modules/workflow/templates.py` only to add a new evidence workflow stage/template entry, not to alter legacy `idea-discovery`
- Test: `backend/tests/test_evidence_constrained_ideas.py`

**Dependencies:** M9.

**Acceptance criteria:**

- Every idea references at least one gap.
- Every idea references supporting Evidence Cards.
- Unsupported assumptions are explicitly listed.
- Ideas are not generated directly from raw chunks.
- Existing legacy idea-discovery tests and behavior remain unchanged.

**Test strategy:**

- Scripted LLM or deterministic generator tests.
- Validation test rejects ideas without gap/evidence links.
- Workflow engine tests only if a new evidence workflow stage is wired into templates.

**Risks:**

- New evidence idea stage may duplicate old behavior if boundaries are unclear.
- LLM may omit structured references unless strongly constrained.

**Rollback plan:**

- Disable the new evidence idea stage; legacy idea-discovery remains untouched.

**Status:** Not Started

### M11: Novelty / Feasibility / Risk Screening

**Module ID:** M11

**Module name:** Novelty / Feasibility / Risk Screening

**Goal:** Conservatively screen candidate ideas without claiming final innovation.

**Scope:**

- Add labels for local overlap, world novelty uncertainty, feasibility, and risk.
- Reuse existing external novelty modules where appropriate.
- Add feasibility/risk dimensions from evidence and unsupported assumptions.

**Inputs:**

- Candidate ideas
- Evidence Cards
- Optional external scholarly candidates

**Outputs:**

- Screening results JSON/Markdown

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/screening.py`
- Modify: `backend/modules/workflow/external_novelty/*` only if needed
- Modify: `backend/modules/workflow/step_defs.py`
- Test: `backend/tests/test_risk_screening.py`

**Dependencies:** M10.

**Acceptance criteria:**

- Uses conservative labels:
  - `likely_known`
  - `partially_explored`
  - `potentially_novel_combination`
  - `insufficient_evidence`
  - `high_risk_novelty_claim`
- Does not output final innovation claims.
- Lists manual verification requirements.
- Flags API/search limitations explicitly.

**Test strategy:**

- Unit tests for label normalization.
- Tests for external search failure resulting in `insufficient_evidence` or search-incomplete warnings.
- Existing external novelty tests.

**Risks:**

- Users may overinterpret screening as final novelty proof.
- External APIs may rate limit.

**Rollback plan:**

- Disable external screening and output local-only screening with clear warning.

**Status:** Not Started

### M12: Evidence-Grounded Report Export

**Module ID:** M12

**Module name:** Evidence-Grounded Report Export

**Goal:** Export a report that is fully grounded in Evidence Cards.

**Scope:**

- Generate Markdown report from artifacts.
- Include evidence index, unsupported assumptions, manual verification checklist, risk notes, and source grounding.
- Prevent report generation if required upstream artifacts are missing.

**Inputs:**

- Evidence Cards
- Landscape units
- Gaps
- Candidate ideas
- Screening results

**Outputs:**

- Evidence-grounded Markdown report
- JSON report manifest

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/report.py`
- Modify: `backend/core/report.py` only if integrating with session export
- Modify: `backend/modules/workflow/runners/agent_step.py` or new runner only if needed
- Test: `backend/tests/test_evidence_grounded_report.py`

**Dependencies:** M11.

**Acceptance criteria:**

- Report contains an Evidence Index.
- Every core report section references Evidence Card IDs.
- Unsupported assumptions are separated from supported claims.
- Manual verification checklist is present.
- Report does not cite raw chunks directly.

**Test strategy:**

- Golden Markdown structure test.
- Missing artifact rejection test.
- Full backend tests.

**Risks:**

- Report may become too verbose.
- Existing export logic may overlap with new report artifact.

**Rollback plan:**

- Keep report as standalone workflow artifact and avoid touching existing chat export until stable.

**Status:** Not Started

### M13: Experiment Planning Matrix

**Module ID:** M13

**Module name:** Experiment Planning Matrix

**Goal:** Generate a human-reviewable experimental plan from a selected idea.

**Scope:**

- Convert selected idea into sample matrix, variables, controls, characterization, tests, expected observations, failure modes, and missing evidence.
- Do not implement experiment execution.
- Do not claim autonomous experiment design.

**Inputs:**

- Selected idea
- Evidence Cards
- Screening result

**Outputs:**

- Experiment planning matrix JSON/Markdown

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/experiment_plan.py`
- Possibly modify: `backend/modules/experiment_bridge/module.py`
- Test: `backend/tests/test_experiment_planning_matrix.py`

**Dependencies:** M12 or at least M10/M11 if report export is not needed.

**Acceptance criteria:**

- Output includes sample matrix, synthesis variables, control groups, characterization matrix, testing matrix, expected observations, failure modes, and missing evidence.
- Every recommendation references Evidence Cards or is listed as an unsupported assumption.
- No automatic execution behavior is added.

**Test strategy:**

- Synthetic idea-to-matrix tests.
- Unsupported assumption propagation tests.

**Risks:**

- Experimental advice can become too generic.
- Safety and equipment constraints may be missing.

**Rollback plan:**

- Keep experiment planning hidden from UI until quality is acceptable.

**Status:** Not Started

### M14: Claim Ledger and Manuscript Support

**Module ID:** M14

**Module name:** Claim Ledger and Manuscript Support

**Goal:** Support manuscript writing through claim ledger and evidence audit.

**Scope:**

- Add claim ledger object.
- Map claims to Evidence Cards.
- Draft paragraphs only from verified claims.
- Audit unsupported claims.

**Inputs:**

- Evidence Cards
- Report artifacts
- User-provided manuscript outline or claim list

**Outputs:**

- Claim ledger
- Verified claims
- Unsupported claim audit
- Draft paragraphs

**Files likely to change:**

- Create: `backend/modules/evidence_workflow/claims.py`
- Create: `backend/modules/evidence_workflow/writing.py`
- Test: `backend/tests/test_claim_ledger.py`
- Possibly frontend support later

**Dependencies:** M12.

**Acceptance criteria:**

- Claims cannot be marked verified without Evidence Card links.
- Drafting step lists unsupported claims separately.
- Paragraphs include traceable claim IDs or evidence IDs.
- No full free-form paper generation is introduced.

**Test strategy:**

- Claim support matrix tests.
- Unsupported claim audit tests.
- Report-to-claim ledger integration test.

**Risks:**

- Writing can drift into unsupported generation.
- Users may expect full paper automation.

**Rollback plan:**

- Disable drafting and keep claim ledger audit only.

**Status:** Not Started

## 8. Execution Protocol

This protocol is mandatory after the user confirms this plan.

1. Execute exactly one module at a time.
2. Before implementation, read this file and locate the requested module.
3. Restate the module goal, scope, likely modified files, and acceptance criteria.
4. Do not modify files unrelated to the current module.
5. Do not implement future module functionality early.
6. Run the module-specific tests listed in the module.
7. Run broader regression tests when the module touches shared code.
8. If tests fail, fix within the current module or mark the module Blocked; do not proceed to the next module.
9. After the module passes acceptance criteria, update that module status in this file.
10. Provide a concise summary of changes and test results.
11. Stop and wait for user confirmation before starting another module.
12. If the plan proves wrong, update this file first and wait for user confirmation.
13. Do not bypass Evidence Cards to create a more impressive demo.
14. Do not implement M1-M5 or any other group of modules in one pass.
15. Do not introduce Domain Profiles as a dependency for any MVP module.
16. Treat all existing SQLite databases under `literature_data` and `research_agent` as read-only inputs.
17. Do not add an `evidence_cards` table or any new SQLite schema for Evidence Cards during MVP.
18. Do not run destructive or mutating database operations such as migration, delete, update, vacuum, reindex, index rebuild, or vector rebuild. This remains forbidden unless the user explicitly changes the database permission model in writing.
19. Live LLM calls are allowed for manual smoke tests and debugging when the user permits them, but default automated tests must remain deterministic unless explicitly marked and skipped by default.
20. When a live LLM response exposes a bug, fix the code or prompt boundary and add a deterministic regression fixture when practical.

## 9. Testing Baseline

Use these commands as the default verification baseline when relevant:

```bash
PYTHONPATH=backend pytest backend/tests -q
```

```bash
cd frontend && npm run build
```

For documentation-only changes, record that no functional tests were required.

The workspace is currently not a git repository based on previous inspection, so commit steps are not required unless git is initialized later.

## 10. 30-Day Execution Plan

30-day priority is to run a reliable evidence workflow first. Do not rush into gap, idea, novelty, or full report until topic-to-evidence is stable.

### Week 1: Plan Confirmation + Evidence Card / Seed Foundation

**Modules:** M0, M1, possibly M2 if M1 is accepted quickly.

**Deliverables:**

- Confirmed plan.
- General Evidence Card schema with `primary_role` and `secondary_roles`.
- EvidenceCardSeed and source candidate adapter.
- Tests proving weak structure, strong provenance, and adapter behavior.

**Acceptance:**

- No Domain Profiles introduced.
- Evidence Card schema supports text, abstract, figure, table, and caption sources.
- Evidence Card is explicitly separate from Claim Ledger.

### Week 2: Artifact Persistence + Topic-to-Report Profile + Retrieval Seeds

**Modules:** M2, M3, M4.

**Deliverables:**

- Artifact-first workflow-scoped Evidence Card persistence.
- Active `topic-to-report` Task Profile.
- Stub-only definitions for other Task Profiles.
- Topic-scope EvidenceCardSeed retrieval.
- Best-effort figure/table/caption retrieval with coverage warnings.

**Acceptance:**

- No SQLite `evidence_cards` table is added.
- Retrieval is bounded by topic and budget.
- Candidate sources preserve figure/table/caption evidence when available and warn when unavailable.

### Week 3: Initial Cards + Enrichment

**Modules:** M5, M6.

**Deliverables:**

- Initial Evidence Card drafts from text/caption/table-like sources.
- Role/entity/relation enrichment.
- Final `primary_role` + `secondary_roles`.
- Open entities and relations without domain schema.

**Acceptance:**

- 30-100 enriched Evidence Cards can be generated for a topic without full-library processing.
- Cards include provenance, roles, entities/relations, support fields, and coverage warnings.

### Week 4: Minimal Topic-to-Evidence Report Slice

**Modules:** M6.5, then M7 only if M6.5 is accepted early.

**Deliverables:**

- Minimal topic-to-evidence report.
- Evidence Card table.
- Role/source coverage summary.
- Manual verification checklist.
- Optional first pass at ranking/diversity after the minimal slice works.

**Acceptance:**

- Report uses Evidence Cards only, not raw chunks.
- Missing figure/table/caption evidence is surfaced as coverage warnings.
- No gap, idea, novelty, or full report sections are required in the 30-day MVP.

## 11. Designs To Avoid

Avoid these designs during MVP:

- Domain Profile as the main architecture.
- Hard-coded material-domain schemas.
- Raw chunk-to-report generation.
- Figure/table/caption treated as secondary attachments.
- Idea generation before Evidence Cards, landscape, and gaps.
- Novelty screening that claims final innovation.
- Full-library evidence extraction.
- Multi-agent orchestration before evidence objects are stable.
- UI-first workflow expansion.
- Automatic experiment execution.
- Full paper generation without a claim ledger.
- Broad workflow marketplace behavior before `topic-to-report` is reliable.

## 12. Immediate Next Step

Current status:

- This document is the only planned change for the current turn.
- No functional development has been performed.
- M1 has not started.
- Evidence Card code has not been written.
- Workflow logic has not been modified.
- Retrieval logic has not been modified.
- Existing databases remain read-only; no database schema or data modifications have been performed.

Next step after user confirmation:

1. Finish M0 by applying any requested edits to this plan.
2. If the plan is approved, begin M1: Core Evidence Card Schema.
3. Do not start M2 until M1 passes its acceptance criteria and the user confirms moving forward.

## 13. Key Questions For User Confirmation

Confirmed constraints:

1. M2 uses artifact-first persistence only. Do not add a SQLite `evidence_cards` table.
2. Existing literature/research databases are read-only inputs. Do not mutate them.
3. M1 includes `EvidenceCardSeed` and a source candidate adapter.
4. Evidence Cards use `primary_role` plus `secondary_roles`.
5. Evidence Card is not Claim Ledger.
6. M3 activates only `topic-to-report`; other Task Profiles are stubs.
7. M4 handles figure/table/caption retrieval as best-effort with coverage warnings.
8. M5 creates initial card drafts; M6 performs role/entity/relation enrichment.
9. M10 adds a new evidence workflow idea stage and does not modify legacy `idea-discovery`.
10. M6.5 is added as the Minimal Topic-to-Evidence Report Slice.
11. The 30-day plan prioritizes a reliable evidence workflow before gap/idea/full-report ambitions.

Open questions:

1. What topic should be used as the first acceptance fixture? Recommended: choose a topic with strong local coverage and table/figure evidence so text/caption/table paths are all exercised.
2. Should frontend changes be deferred until backend artifacts are stable? Recommended MVP: defer visible frontend work except minimal workflow/profile display.
3. Should generated evidence workflow artifacts live under `research_agent/evidence_workflows/{workflow_id}/` exactly, or under a different artifact directory name?
