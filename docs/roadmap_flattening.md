# Roadmap Flattening After Architecture Foundation

## Purpose

This document flattens the project roadmap after completion of the architecture foundation stage. It archives A1-A8, S1-S9, T1, and D1 as Phase 1 work, and defines Phase 2 as research capability expansion starting from P2-M8.

本文档用于在架构底座完成后收敛项目路线编号体系，将 A1-A8、S1-S9、T1、D1 统一归档为 Phase 1，并将后续科研能力扩展统一命名为 Phase 2 下的 M 系列任务。

## Why Flatten The Roadmap

The A/S/D/T labels were useful during architecture stabilization, smoke validation, documentation checkpoints, and technical debt handling. However, continuing these labels as top-level roadmap items would create unnecessary nesting and make future planning harder to read.

A/S/D/T 编号在架构验证阶段用于控风险是合理的，但如果继续作为一级路线滚动，会导致路线层级越来越多，不利于后续科研能力模块的规划、测试和沟通。

The flattened roadmap keeps the completed architecture work visible while returning future research capability planning to the M-series vocabulary.

## Phase 1: Architecture Foundation

Phase 1 archives the completed architecture foundation work:

- A1 Research Workspace Model
- A2 Agent State / Plan Schema
- A3 Tool / Skill Registry
- A4 Callable Skill Wrappers
- A5 Artifact Validation / Audit Gates
- A6 Claude Code CLI Controller Contract
- A7a Mock CLI-backed Minimal Agent Loop
- A7b Real Claude Code CLI Invocation Adapter
- A8 Platform-native Fallback Controller Baseline
- S1 Real CLI Contract Smoke Test
- S2 Contract Compliance Hardening
- S3 CALL_TOOL Contract Smoke
- S4 One-Step run_once Smoke
- S5 Two-Step Smoke
- S6 Three-Step Smoke
- S7 Four-Step Smoke
- S8 Five-Step Smoke
- S9 Minimal Report Smoke
- T1 SQLite Initialization / Import Side Effect Cleanup
- D1 Real Claude CLI Smoke Results Documentation

Phase 1 established the platform architecture foundation:

- workspace model
- plan / state / decision schema
- skill registry
- callable skill wrappers
- validation and audit gates
- Claude CLI controller contract
- real Claude CLI invocation adapter
- controlled real CLI smoke validation from retrieval to minimal report
- platform-native deterministic fallback controller
- SQLite initialization race cleanup
- architecture checkpoint documentation

## Phase 1 Final Architecture State

Primary controller path:

```text
Claude CLI-backed controller
```

Fallback / regression path:

```text
Platform-native deterministic fallback controller
```

Shared platform boundary:

- registered skill wrappers
- artifact validation gates
- audit logs
- artifact manifest
- state / plan updates
- no direct database mutation by controllers
- no raw retrieval -> report bypass

Phase 1 validates the minimal topic-to-evidence chain:

```text
retrieve_sources
-> create_evidence_seeds
-> extract_evidence_cards
-> enrich_evidence_cards
-> rank_evidence
-> build_minimal_topic_to_evidence_report
```

## Phase 2: Research Capability Expansion

Phase 2 starts after the architecture foundation is complete. Its purpose is to add bounded downstream research capabilities as registered skills, not to create a free-form research agent.

Phase 2 capabilities are workflow capabilities under literature-research-agent. They are not default chat execution behavior. Chat should invoke them through explicit workflow profiles / plan templates, with a workflow router or user selection choosing the terminal step before controller execution starts.

Phase 2 capabilities are workflow capabilities under `literature-research-agent`.
They are not default chat execution behavior. The chat interface should invoke
them only through explicit workflow profiles / plan templates selected by a user
or a workflow router.

The intended boundary is:

```text
Chat Interface
  -> Intent / Workflow Router
  -> Workflow Profile / Plan Template
  -> literature-research-agent Controller
  -> Skill Registry
  -> Skill Wrappers
  -> Artifacts / Validation / Audit
```

Phase 2 modules should use the following names:

- P2-M8: Landscape Skill — contract, wrapper, explicit controller integration, and real CLI one-step smoke completed.
- P2-M9: Gap Mapping Skill — contract, wrapper, explicit controller integration, and real CLI one-step smoke completed.
- P2-M10: Idea Generation Skill — contract, wrapper, explicit controller integration, and real CLI one-step smoke completed.
- P2-M11: Novelty / Feasibility / Risk Screening Skill — contract, wrapper, explicit controller integration, and real CLI one-step smoke completed.
- P2-M12: Experiment Matrix Skill — contract, wrapper, explicit controller integration, and real CLI one-step smoke completed.
- P2-M13: Claim Ledger Skill — contract, wrapper, explicit controller integration, and real CLI one-step smoke completed.
- P2-M14: Report / Manuscript Drafting Skill — contract, deterministic wrapper, explicit controller integration, workflow boundary, and real CLI one-step smoke completed.

## Standard Development Pattern For Each P2-M Skill

Each P2-M skill should follow the same small development pattern:

1. Skill contract
2. Registry entry
3. Stub-safe wrapper
4. Input / output artifact schema
5. Validation gate
6. Platform-native fallback test
7. Claude CLI bounded decision smoke test
8. Minimal documentation note

These are substeps inside each P2-M module, not new top-level roadmap series.

这些只是每个 P2-M 能力内部的标准开发步骤，不再作为新的一级编号体系展开。

## Numbering Rule From Now On

Do:

```text
P2-M8 Landscape Skill
P2-M9 Gap Mapping Skill
P2-M10 Idea Generation Skill
```

Do not:

```text
A9
S10
D3
T2 as normal roadmap continuation
```

Technical debt can still be tracked, but it should not interrupt the main roadmap unless it blocks the next P2-M module.

## What Not To Do Next

Do not directly implement all M8-M14.

Do not generate landscape / gap / idea in free form.

Do not bypass Evidence Cards.

Do not let Claude CLI directly execute skills.

Do not let the fallback controller become the primary agentic controller.

Do not create new top-level A/S/D/T sequences unless there is a clear exceptional reason.

## Phase 2 Final Closure

Phase 2 final closure is documented in:

```text
docs/phase2_final_closure.md
```

P2-M8 through P2-M14 are complete as explicit literature-research-agent
workflow capabilities. They are not ordinary chat default behavior.

The completed Phase 2 downstream skill closures are documented in:

```text
docs/p2_m8_landscape_skill_closure.md
docs/p2_m9_gap_mapping_skill_closure.md
docs/p2_m10_idea_generation_skill_closure.md
docs/p2_m11_screening_skill_closure.md
docs/p2_m12_experiment_matrix_skill_closure.md
docs/p2_m13_claim_ledger_skill_closure.md
docs/p2_m14_manuscript_drafting_skill_closure.md
```

The recommended next phase is:

```text
Phase 3: Workflow Productization / Chat Router Integration
```

Do not proceed automatically. Phase 3 should productize workflow profiles,
chat-router intent mapping, parameter collection, progress UX, artifact browsing,
resume / replay / export, permission UX, and end-to-end acceptance tests before
adding new research skills.
