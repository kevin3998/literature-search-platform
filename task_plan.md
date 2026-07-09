# Task Plan: Literature Agent Platform Buildout

## Goal
Build the platform around the existing `literature_search` module first: complete the local Research Agent loop, persistent memory, model configuration, grounded chat, artifacts/jobs, and a practical developer workflow before adding heavier platform framework such as login or additional modules.

## Phases
- [x] Phase 1: Full Research Agent integration inside existing `literature_search`
- [x] Phase 2: Literature search API router, job streaming, artifact browsing, chat compatibility
- [x] Phase 3: Frontend Literature Search workbench with Research Agent tool tabs
- [x] Phase 4: SQLite conversation memory, session persistence, turn/search/evidence/job/artifact links
- [x] Phase 5: Sidebar session management with custom right-click menu, pin/favorite/tag/archive/delete
- [x] Phase 6: Settings v1 with General, Models, Agent, Research Agent, Retrieval, Memory, Diagnostics
- [x] Phase 7: Encrypted secret store, named model profiles, model activation/test/reveal APIs
- [x] Phase 8: LLM tool-calling chat loop with research tools, citation audit, and readable blocked diagnostics
- [x] Phase 9: One-command developer startup through `dev.sh`
- [ ] Phase 10: CC Switch read-only preview/import for model profiles
- [ ] Phase 11: End-to-end real-provider smoke testing for grounded Chat Agent
- [ ] Phase 12: Simplify Literature Search workbench around the core feature loop
- [ ] Phase 13: Improve artifact/session reuse actions and research-record navigation
- [ ] Phase 14: Add reliability smoke scripts and development diagnostics
- [x] Phase 0/Block 0: Canonical paper_id identity propagation + Research Index Health home dashboard
- [x] Phase 15: Split long-term Research Agent buildout into 12 capability block planning documents
- [x] Phase 16: Add Block 12 for management, collaboration, user accounts, admin, and workspace planning

## Decisions
- Keep the existing `literature_search` module id and left navigation entry.
- Add `/api/literature-search/*` endpoints.
- Use direct Python imports from `LITERATURE_RESEARCH_CODE_DIR`.
- Use SQLite memory for sessions/messages/turns/search/evidence/jobs/artifact links.
- During one-command local development, default SQLite memory lives at `./.runtime/platform_memory.sqlite`; external data/artifacts remain under `LITERATURE_DATA_DIR`.
- Persist jobs and job events in SQLite; persistent research artifacts remain in `LITERATURE_DATA_DIR/research_agent`.
- Do not touch crawler, Cloudflare solver, or ops supervisor.
- Settings is a platform-level workbench opened from the TopBar, not a left-side agent module.
- API keys are not stored in plain SQLite; named model profile keys are encrypted in `~/.literature-agent/secrets.enc` by default.
- Literature Search research QA is LLM-based. If no usable model/provider is configured, research turns return a readable blocked diagnostic instead of a local retrieval-summary substitute.
- Prioritize the `literature_search` feature loop before login/multi-user framework.
- Long-term planning is organized under `docs/capability-blocks/`, one Markdown file per capability block, so future discussions can happen in separate sessions without one oversized plan.
- Block 12 covers future group/workspace management, users, roles, admin console, permissions, and collaboration. It is intentionally later than the single-user research loop.
- Block 0 should not mint platform paper IDs. Use `/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/research_index.sqlite` `papers.paper_id` as the canonical paper identity and propagate it through Search, Evidence, Artifact, Report, and Memory.
- Research Index Health should become a Home Dashboard shown after startup/login, with read-only status for normal users and future admin-only maintenance actions such as health check, changed-paper refresh, and vector build.

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| `git status` failed because workspace is not a git repository | Status check on 2026-06-26 | Treat current status as file/test-based. Recommend initializing or attaching git before larger changes. |
| Frontend port binding can fail in restricted sandbox with `EPERM` | Earlier dev-start verification | `dev.sh` is intended for the user's normal local environment; backend/frontend build and tests still verify. |

## Current Verification
- 2026-06-26: `PYTHONPATH=backend pytest backend/tests -q` passed, 32 tests.
- 2026-06-26: `cd frontend && npm run build` passed.
- 2026-06-26: Workspace contains 59 backend/frontend source files counted under `backend` and `frontend/src`.

## Next Priority
Use the capability block docs as the discussion backbone. Recommended first detailed design topic: Block 0 Research Index Identity / Corpus Data Lifecycle, followed by Retrieval and Evidence Grounding.

## Current Focus: Workflow Profile Boundary Correction
- [x] Inspect docs and controller plan templates for chat-vs-workflow semantic drift.
- [x] Add or update workflow profile boundary documentation.
- [x] Add lightweight boundary tests only if they clarify explicit workflow terminal steps.
- [x] Run targeted non-Claude, non-LLM tests.

## Current Focus Constraints
- Do not implement P2-M14.2.
- Do not call real Claude CLI or any LLM.
- Do not modify databases or M1-M7 behavior.
- Do not make ordinary chat auto-run research workflows.

## Current Focus: Literature Search Product QA Rerun
- [x] Restore previous productization findings and test baseline.
- [x] Create a fresh rerun report file.
- [x] Run dependency/startup, readiness, quick-stats, backend, frontend, and build checks.
- [x] Execute real API product-path tests for library status, plain help, attachment missing, attachment-only, and topic no-hit.
- [x] Execute browser UI checks for sidebar IA, Literature Search workbench, tabs, curation controls, and mobile/narrow layout.
- [x] Classify previous issues as resolved / partially resolved / unresolved or unresolved risk, and record new observations.
- [x] Run supplemental long-path checks for research latency, attachment+literature, adjacent negative coverage, exact-query timeout, and stuck running turns.

Report: `docs/literature_search_product_test_rerun_2026-07-07.md`

## Current Focus: Literature Search Priority Repair Batch 1
- [x] Add contract tests for first-priority UI regressions.
- [x] Remove/demote `数据抽取 / 结构化任务` from the main sidebar.
- [x] Fix 390px Literature Search layout by collapsing the app sidebar, stacking the workbench, and preserving textarea width.
- [x] Clarify citation display labels so UI ordinals are separate from true evidence IDs.
- [x] Run frontend Node tests and production build.
- [x] Update the rerun report, findings, and progress files with repair evidence.

## Current Focus: Literature Search Priority Repair Batch 2
- [x] Add regression tests for `plain_help/plain_chat` route metadata.
- [x] Add regression tests for no-candidate research fallback failure metadata.
- [x] Emit `intent_route` for plain help/chat paths and persist it through chat stream metadata.
- [x] Emit `failure_explanation` for zero-candidate research fallback and persist it through chat stream metadata.
- [x] Preserve no-Agent short-circuit behavior while allowing deterministic ordinary-chat fallback when LLM is unavailable.
- [x] Run backend full regression plus frontend Node/build regression.
- [x] Update the rerun report, findings, and progress files with repair evidence.

## Current Focus: Literature Search Priority Repair Batch 3
- [x] Add regression tests for search timeout stopping repeated searches and emitting timeout failure metadata.
- [x] Add regression tests for stripping process narration from final answers.
- [x] Add regression tests for adjacent-match direct existence coverage downgrades.
- [x] Add regression tests for stale running turn recovery.
- [x] Disable duplicated search retry inside one tool call.
- [x] Stop additional search calls after a search timeout in the same agent turn.
- [x] Emit `failure_explanation(code=tool_timeout_failed)` for timeout-failed research turns.
- [x] Sanitize common English/Chinese process narration from final answers before persistence/audit.
- [x] Downgrade direct-existence coverage when key topic terms are missing.
- [x] Recover old abandoned `running` turns with readable Chinese assistant messages.
- [x] Run backend full regression plus frontend Node/build regression.
- [x] Update the rerun report, findings, and progress files with repair evidence.

## Next Priority From Rerun Report
- [x] Investigate and repair first-search timeout performance for English/broad topic queries; the slow external FTS `fallback_or` path is now bounded and English research questions are normalized before retrieval.
- [x] Re-audit broad English real-index evidence acquisition latency; prior blockers now return in `0.341s-3.269s` with results and sufficient coverage.
- [x] Re-run attachment + literature combined live path after confirming the configured API model profile is active.
- [x] Revisit remaining real-provider pseudo-citation risk with a successful cited English research answer using the active DeepSeek API profile.
- Use `/api/readiness.build` during live smoke to confirm the running backend is fresh.
- Track attachment + literature combined answer latency as a follow-up UX/performance item; semantics and citation/attachment metadata are now verified.

## Current Focus: Literature Search Priority Repair Batch 4
- [x] Profile external FTS routes with subprocess timeouts to avoid hanging the session.
- [x] Identify `fallback_or` join + BM25 ranking as the first-search timeout root cause.
- [x] Add regression tests for bounded route execution.
- [x] Add rewrite regression for English research-question normalization.
- [x] Skip `fallback_or` when phrase/core routes already satisfy the candidate pool.
- [x] Normalize English research questions to high-signal retrieval terms before raw wording.
- [x] Verify real-index `search` and `acquire_evidence` latency for the previously blocking English cases.
- [x] Run backend full regression plus frontend Node/build regression.
- [x] Confirm model-unavailable research QA blocks clearly instead of falling back to local retrieval summary.
- [x] Run fresh live chat-stream smoke for successful cited English answer and attachment+literature combined path after confirming the active API model profile (completed in Batch 10).

## Current Focus: Literature Search Priority Repair Batch 5
- [x] Align research QA semantics to “LLM required” per product direction.
- [x] Remove backend local retrieval-summary fallback for research QA when Agent/LLM is disabled or runtime model call fails.
- [x] Add regression tests for `llm_required_for_research` and `llm_runtime_unavailable`.
- [x] Replace Settings copy that promised local retrieval-summary fallback.
- [x] Live-smoke current bad model config: fast Chinese blocked response, no papers/search metadata/local summary.
- [x] Fix Settings readiness so an Ollama provider is not considered ready unless the configured model exists in `/api/tags`.
- [x] Add/readiness-test `ollama_model_unavailable` and surface it with Chinese UI/backend labels.
- [x] Run backend full regression plus frontend Node/build regression.

## Current Focus: Literature Search Priority Repair Batch 6
- [x] Add frontend contract tests for stale remembered session recovery.
- [x] Recover from missing remembered session by opening the next available session.
- [x] Recover from stale-only session list by creating a fresh session.
- [x] Keep non-404/non-missing session load failures user-visible.
- [x] Run frontend Node/build plus backend full regression.

## Current Focus: Literature Search Priority Repair Batch 7
- [x] Add view-model regression for candidate paper readability enrichment.
- [x] Merge research-state candidate papers with current retrieval papers by stable identity.
- [x] Preserve curated status/note/counts while restoring snippet/abstract/authors/year/venue in paper cards and details.
- [x] Run frontend Node/build plus backend full regression.

## Current Focus: Literature Search Priority Repair Batch 8
- [x] Add controlled English pseudo-citation regression for successful search path.
- [x] Add attachment + literature blocked-path regression under LLM-required semantics.
- [x] Run focused backend risk tests plus full backend/frontend regression.
- [x] Run real-provider successful cited English answer and attachment+literature smoke after confirming active API profile readiness.

## Current Focus: Literature Search Priority Repair Batch 9
- [x] Re-check Settings readiness at that point and record the apparent live-smoke blocker as `ollama_model_unavailable` (superseded by Batch 10 active-profile precedence fix).
- [x] Re-run real-index broad English evidence acquisition timing.
- [x] Update rerun report so retrieval-latency status is separated from the available-LLM smoke gap.

## Current Focus: Literature Search Priority Repair Batch 10
- [x] Correct Settings/model readiness precedence so active API model profiles override stale local model fields.
- [x] Add regression coverage for active profile precedence in readiness/settings/effective config.
- [x] Add regression coverage for Chinese final-answer process-preface stripping.
- [x] Add deterministic attachment source-marker fallback for research turns with active parsed attachments.
- [x] Emit and persist `attachment_context` metadata for all chat turns carrying parsed active attachments.
- [x] Re-run real-provider English cited-answer smoke.
- [x] Re-run real-provider attachment + literature combined smoke.
- [x] Run backend full regression, frontend Node tests, and frontend build.
