# Progress

## 2026-06-25
- Started full implementation of the complete research agent inside the existing `literature_search` module.
- Added backend service, artifact store, job store/runner, literature-search API router, and chat adapter integration.
- Added frontend literature search workbench, API client methods, zustand state, and job streaming.
- Updated README with the complete Research Agent startup and API notes.
- Started implementation of SQLite conversation memory/session persistence.
- Added SQLite memory schema, persistent session store, chat turn recording, persistent job store, and frontend backend-backed sessions.

## 2026-06-26
- Updated repository status after several completed buildout phases: Settings v1, model profiles, encrypted secrets, LLM tool-calling agent loop, citation audit, session right-click menu, and `dev.sh` are now present in the codebase.
- Confirmed the workspace is not currently a git repository, so status tracking is file/test-based rather than git-based.
- Verified backend baseline: `PYTHONPATH=backend pytest backend/tests -q` passed with 32 tests.
- Verified frontend baseline: `cd frontend && npm run build` passed.
- Updated `task_plan.md` and `findings.md` to remove stale notes about in-memory sessions/jobs and to add the next planned phases.
- Current recommended next build step: implement CC Switch read-only preview/import into model profiles, then run a real-provider end-to-end grounded Chat smoke test.
- Created `docs/capability-blocks/` with a README and 12 block-specific planning Markdown files for future per-block discussion:
  - Corpus / Data Lifecycle / Canonical Metadata
  - Configuration / Runtime Readiness
  - Retrieval / Evidence Acquisition
  - Evidence Grounding / Claim-level Citation / Answer Permission
  - Tool / Action Execution / Permission Boundary
  - Chat Agent / Orchestration Loop
  - Conversation Memory / Research State
  - Deep Research Task Engine
  - Artifact / Knowledge Asset Management
  - Report / Audit / Export
  - User Experience / Workbench IA
  - Evaluation / Observability / Reliability / Operations
- Added Block 12 planning document for Management / Collaboration Framework, covering user registration, login, roles, workspaces, admin console, sharing, permissions, audit logs, and migration from `local_user` mode.

## 2026-06-27
- Added `docs/frontend-interaction-visual-bug-checklist.md`, a detailed frontend QA checklist focused on interaction behavior, visual presentation, layout stability, loading/error states, Settings, Chat, Sidebar, Jobs, Artifacts, Research Record, responsiveness, accessibility, and high-risk regression scenarios.
- Implemented Block 0 (Corpus Data Lifecycle / Research Index Identity):
  - Canonical `paper_id` (from `research_index.sqlite.papers`) now flows through Search → Evidence → Memory → Report. `to_chat_papers` surfaces `paper_id`/`index_version`; `evidence_items` gained `paper_id/section_id/chunk_index/index_version` columns (migrated via `_ensure_column`); report 来源汇总 now prints `paper_id + DOI + index_version`, backfilled at export time.
  - New `CorpusService` (`modules/literature_search/corpus.py`): read-only resolver (DOI/article_id/source_path → paper_id), on-disk path integrity checks, fast coverage counts, and a Research Index Health dashboard (does NOT call the 100s `index_health`; uses cheap `index_status`/`vector_status`/coverage + integrity sample).
  - New `/api/corpus/*` router: `dashboard`, `resolve`, `paper-paths`, `maintenance/jobs`, `maintenance/{action}`. Maintenance (`health_check`/`index_refresh`/`vector_build`) is admin-gated via `LITERATURE_PLATFORM_ROLE` (default admin; `viewer` = read-only, 403 on maintenance). Jobs run through the shared `literature_search_shared` job store/runner.
  - Frontend: `HomeDashboard.jsx` is the default landing page (Research Index Health) with coverage cards, vector-not-built warning, integrity sample, and admin maintenance buttons with live job streaming. Sidebar gained a 首页·索引健康 entry; `homeOpen` state in the store.
  - Tests: `test_corpus_identity.py`, `test_corpus_memory_report.py` (40 backend tests pass; frontend build passes). Verified live against the real 87,091-paper index; dashboard ~0.35s.

## 2026-06-30
- Re-read the current project after the latest foundational implementation. The codebase now includes:
  - `backend/api/corpus_router.py` and `HomeDashboard.jsx` for Research Index Health / Block 0.
  - `backend/modules/literature_search/retrieval/*` and `/api/literature-search/acquire-evidence` for Block 2 evidence acquisition packets.
  - `agent/grounding.py`, expanded `agent/loop.py`, and grounding tests for Block 3 answer permission / claim-level guardrails.
  - `agent/tool_specs.py`, `tool_errors.py`, tool traces in `memory_db.py` / `session_store.py`, and role/mode-aware tool execution for Block 4.
  - orchestration policy / role handling and readiness-aware Chat Agent path for Block 5.
  - research_state / paper_states / research_state_events and `ResearchStatePanel.jsx` for Block 6.
  - native workflow engine under `backend/modules/workflow/*`, `/api/workflows`, and `WorkflowView.jsx` for Block 7/10, including Idea Discovery template with corpus-stage + first agent-step idea generation.
- Verification on 2026-06-30:
  - `PYTHONPATH=backend pytest backend/tests -q` passed: 167 tests.
  - `cd frontend && npm run build` passed.
  - Workspace is still not a git repository (`git status` fails), so future implementation tracking remains file/test based unless git is initialized.

## 2026-07-03
- Started architecture / workflow boundary correction pass.
- Scope is limited to documentation, plan-template semantics, and lightweight explicit workflow boundary tests if needed.
- Explicitly excluding P2-M14.2 implementation, real Claude CLI calls, LLM calls, database changes, and default chat auto-advance into research workflows.
- Added `docs/workflow_profile_boundary.md`.
- Clarified workflow-profile boundaries in `docs/roadmap_flattening.md`, `docs/p2_m14_manuscript_drafting_skill_contract.md`, `backend/modules/research_agent_controller/plan_templates.py`, and `backend/modules/workflow/templates.py`.
- Added `backend/tests/test_workflow_profile_boundary.py` for terminal step and default workflow gallery boundaries.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_workflow_profile_boundary.py -q` -> 5 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_explicit_claim_ledger_controller_integration.py -q` -> 20 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_explicit_experiment_matrix_controller_integration.py -q` -> 15 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_manuscript_drafting_skill_contract.py -q` -> 5 passed.

## 2026-07-07
- Started Literature Search productization QA after user reported obvious UI/product defects.
- Created `docs/literature_search_productization_test_findings.md` as the dedicated issue log for intent routing, library status, zero-result explanation, right-side tabs, Chinese output, and evidence grounding findings.
- Initial findings:
  - Default `pc_plus` backend runtime cannot start after attachment route addition because `python-multipart` is missing.
  - Corpus dashboard confirms the library is non-empty (`147371` papers) but the endpoint is too slow for chat-time status questions.
  - `当前文献库中一共有多少文献？` is misrouted into retrieval, searches `*`, returns 0 evidence, and falsely implies no usable library records.
  - Right-side audit/papers tabs do not explain route decisions, actual query, corpus non-empty status, or zero-result cause.
  - Research QA can retrieve evidence but still has product issues: pseudo/failed citations in one English probe, high latency and recovered tool timeouts in the Chinese probe.
- Continued and completed the Literature Search productization testing pass without applying fixes.
- Added third-batch coverage to `docs/literature_search_productization_test_findings.md`:
  - Attachment tests for txt, PDF, unsupported type, count limit, deletion, attachment-only answering, and attachment+literature answering.
  - Citation/UI tests for successful evidence answers, failed citation audit, evidence detail overlay, paper tab readability, and audit detail completeness.
  - Navigation IA check showing the sidebar still exposes an extra `数据抽取` entry.
  - Chinese failure wording check showing errors are mostly Chinese but still semantically generic.
  - Mobile/narrow-screen smoke check showing Literature Search is not usable at 390px width.
- Current findings file now records 34 test rows and 27 issue entries across P0/P1/P2.

## 2026-07-07 rerun
- Created and completed `docs/literature_search_product_test_rerun_2026-07-07.md` as a fresh product QA rerun and issue-classification report.
- Verified current automated baseline:
  - `pc_plus` can import backend with `python-multipart`.
  - `/api/readiness` is ready/ok.
  - `/api/corpus/quick-stats` returns authoritative counts in about 0.45s.
  - targeted backend Literature Search tests: 30 passed.
  - frontend Node tests: 58 passed.
  - frontend build passed.
  - backend full regression: 687 passed, 24 skipped.
- Real API rerun showed library count/index/year/journal/recent-import questions now use deterministic `intent_route + library_status` routes with no retrieval steps.
- Real API rerun showed attachment-only works when frontend protocol sends active `attachment_ids`, and missing attachments now return a specific Chinese explanation.
- Browser rerun showed the right-side Literature Search workbench has `证据 / 文献 / 审计`, evidence filters, curation actions, attachment input, and research state strip.
- Unresolved product issues remain:
  - main sidebar still exposes `数据抽取 / 结构化任务`;
  - 390px Literature Search layout still horizontally overflows and textarea width can be 0;
  - citation labels remain ambiguous (`1`, `2`, etc. vs evidence IDs);
  - live plain-help/no-hit paths still lack some structured route/failure metadata for audit.
- Continued the rerun to close the previous long-path evidence gap using a fresh backend on port 8011:
  - English research QA took 194.15s, had three search timeouts, leaked English process narration, and ended not-answerable.
  - Chinese research QA took 203.47s, had three search timeouts, and ended not-answerable.
  - Attachment + literature took 193.91s; attachment summary worked but all literature searches timed out.
  - Martian-soil superconducting query still marked adjacent evidence as `coverage.status=sufficient`.
  - Exact `large language models for materials discovery` topic query still took 193.47s and timed out three times.
  - SQLite still contains two old `turns.status='running'` rows with no assistant message.
- Updated `docs/literature_search_product_test_rerun_2026-07-07.md` so former not-verified long-path issues are classified as unresolved or unresolved risk rather than left unclassified.

## 2026-07-07 priority repair batch 1
- Implemented the first priority Literature Search UI repair batch from the rerun report:
  - Removed/demoted the `数据抽取 / 结构化任务` primary sidebar entry while leaving structured extraction implementation code intact.
  - Added a responsive sidebar rail (`68px` on narrow screens, `256px` from `md` upward) so Literature Search has enough usable width at mobile/narrow viewports.
  - Made the Literature Search workbench stack `ChatPanel` and `ResultsPanel` on narrow screens; the right panel is now `w-full` on narrow screens and `lg:w-[380px]` on desktop.
  - Added mobile input safeguards (`min-w-0`, full-width input shell, wrapped header actions) so the textarea no longer collapses to width `0`.
  - Added `frontend/src/components/citationLabels.js` and wired inline citations, citation footer rows, and evidence cards to show `证据 1` style display ordinals separately from `证据ID：...` true IDs.
- Added `frontend/tests/literature_search_ui_contract.test.mjs` covering sidebar IA, responsive layout source contracts, textarea shrink behavior, and citation label semantics.
- Verification:
  - `node --test frontend/tests/literature_search_ui_contract.test.mjs` -> 6 passed.
  - `node --test frontend/tests/*.test.mjs` -> 64 passed after one rerun; an intermediate all-files run exposed a transient global `fetch` mock timing issue in structured-extraction tests, while the isolated `api_client_contract` run and the final all-files run passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.
  - Browser 390x844 check: `scrollWidth=390`, sidebar width `68`, right workbench `x=68 / width=322`, textarea width `176`, no visible `数据抽取 / 结构化任务`, and readable `证据 1` citation labels present.

## 2026-07-07 priority repair batch 2
- Implemented the structured audit metadata repair batch:
  - `plain_help` now emits `intent_route(route=plain_help)` before LLM/deterministic help responses.
  - `plain_chat` now emits `intent_route(route=plain_chat)`.
  - Lightweight plain chat no longer turns LLM-unavailable greetings into errors; it falls back to deterministic ordinary-chat copy.
  - Non-research orchestration fallback emits `intent_route(route=plain_chat)` before ordinary plain-chat handling.
  - Zero-candidate research fallback now emits `failure_explanation`; if quick corpus stats show the local corpus is non-empty, the code is `library_not_empty_but_no_query_hit`.
  - Chat router already persisted `failure_explanation`; added a contract test to lock assistant metadata persistence for `failure_code/failure_message`.
- Updated tests:
  - `backend/tests/test_literature_search_lightweight_chat.py`
  - `backend/tests/test_api_contract_sessions_chat.py`
  - `backend/tests/test_tool_execution.py`
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_literature_search_lightweight_chat.py -q` -> 7 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_lightweight_routes.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_api_contract_sessions_chat.py backend/tests/test_session_attachments.py backend/tests/test_research_state.py -q` -> 31 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_tool_execution.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_api_contract_sessions_chat.py -q` -> 36 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 692 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 64 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.
- Report updated: `docs/literature_search_product_test_rerun_2026-07-07.md` now marks plain route metadata and no-hit fallback metadata as resolved in source/tests, with live API smoke still recommended after backend restart.

## 2026-07-07 priority repair batch 3
- Implemented the long-path reliability repair batch from the rerun report:
  - Search tool timeouts are no longer retried inside a single tool call (`search` `max_retries=0`), removing one layer of duplicated 30s waits.
  - Agent loop now records a search timeout in the per-turn guard, emits `failure_explanation(code=tool_timeout_failed)`, and blocks further search calls in the same turn after a timeout.
  - Final agent answers are sanitized for common process narration prefixes such as `I'll search...`, `Let me try...`, and Chinese equivalents; if sanitization changes the final answer, the stream emits `answer_reset` and replays the cleaned answer so persisted content matches the UI.
  - Direct existence queries such as “有没有关于 X 的论文” now require direct topic-term coverage before `coverage.status` can remain `sufficient`; adjacent results missing a key topic term are downgraded and record `missing_aspects=["direct_topic_match"]`.
  - `SessionStore` now recovers stale abandoned streaming turns on initialization: old `running` turns with no assistant message are marked `failed` and receive a Chinese assistant note explaining that the previous answer was interrupted.
- Added/updated tests:
  - `backend/tests/test_agent_loop.py`
  - `backend/tests/test_tool_execution.py`
  - `backend/tests/test_retrieval_packet.py`
  - `backend/tests/test_memory_persistence.py`
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_agent_loop.py -q` -> 20 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_tool_execution.py -q` -> 25 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_retrieval_packet.py -q` -> 23 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_memory_persistence.py -q` -> 9 passed.
  - Combined Literature Search regression set -> 105 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 697 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 65 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.
- Remaining after this batch:
  - A fresh live API smoke after backend restart is still needed to verify real-provider latency and metadata behavior against the running server.
  - Dev-server freshness/readiness versioning remains a follow-up.

## 2026-07-07 dev-server freshness signal
- Added lightweight build metadata to `/api/readiness`:
  - `build.api_version`
  - `build.readiness_contract_version`
  - `build.capabilities`
- This makes stale development servers easier to diagnose after backend route/contract changes.
- Added readiness contract assertions in `backend/tests/test_platform_readiness.py`.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_platform_readiness.py -q` -> 2 passed.
  - Focused reliability/readiness regression set -> 79 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 697 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 65 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-07 live smoke follow-up
- Started a fresh current-source backend on `127.0.0.1:8022` against `.runtime/platform_memory.sqlite`.
- Verified `/api/readiness.build` reports `platform_readiness_v2_2026_07_07` with `literature_search_reliability_batch`.
- Verified real `.runtime` stale-turn recovery: `turns.status='running' and assistant_message_id is null` count is now `0`.
- Live `/api/chat/stream` smoke results after backend restart:
  - `What can you do?` -> `intent_route(route=plain_help)` persisted in assistant metadata.
  - `文献库里有没有关于量子香蕉电池的论文？` -> `intent_route(route=research)`, `failure_explanation(code=no_candidate_papers)`, and assistant metadata persists `failure_code=no_candidate_papers`.
  - `文献库里有没有关于 large language models for materials discovery 的文献？` -> one search timeout, `failure_explanation(code=tool_timeout_failed)`, elapsed about `39s` instead of the previous repeated-timeout `193s` path.
- Live smoke revealed one remaining source issue: direct negative coverage still used the LLM-rewritten search query instead of the original user question, so `火星土壤超导材料` still appeared `sufficient` in the live agent path.
- Fixed that source issue:
  - `ToolRegistry` now passes `_original_user_query` into `build_packet`.
  - `build_packet` uses `_original_user_query` for coverage judgment but does not forward it to the underlying search.
  - Direct-topic matching now ignores `query_match_reason` so matched-term metadata cannot masquerade as evidence content.
- Added regression coverage:
  - `test_direct_existence_uses_original_user_query_after_llm_rewrite`
  - `test_direct_existence_ignores_query_match_reason_as_content`
  - `test_search_tool_passes_original_question_to_packet`
- Verified direct service and live API after restart:
  - direct service coverage for `火星土壤超导材料` is now `partial` with `missing_aspects=["direct_topic_match"]`.
  - live API coverage for the same query is now `partial`, notes include adjacent/not-direct wording, and elapsed about `7s`.
- Attempted a successful English cited-answer smoke (`What papers discuss Martian soil simulants for building materials?`), but it also hit a single search timeout and returned structured `tool_timeout_failed`; therefore English pseudo-citation risk remains not proven fixed.
- Final verification after this follow-up:
  - `PYTHONPATH=backend pytest backend/tests -q` -> 702 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 65 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-07 priority repair batch 4
- Investigated the remaining first-search timeout performance issue for English/broad topic queries.
- Root cause evidence:
  - The slow branch was external FTS `fallback_or`: `documents_fts MATCH ("term" OR ...)` joined to `documents` / `article_index` and ordered by `bm25`.
  - For `large language models for materials discovery`, phrase/core routes returned 200 rows in about `3.4s` / `0.1s`, while fallback OR join timed out after `12s`.
  - For `What papers discuss Martian soil simulants for building materials?`, the raw question produced zero phrase/core hits because low-information words (`what/papers/discuss/for`) were included, forcing the same slow fallback OR path.
- Implemented two scoped fixes:
  - `LiteratureResearchService` now wraps external `ResearchSearch` with a bounded `_route_rows` override that skips `fallback_or` when phrase/core routes already fill the candidate pool.
  - English research questions now get a high-signal retrieval rewrite first, e.g. `What papers discuss Martian soil simulants for building materials?` -> `Martian soil simulants building materials`, while retaining the original wording for audit.
- Real index verification:
  - `service.search("large language models for materials discovery", limit=8, retrieval="fts")` -> `3.57s`, 8 results, `fallback_or.skipped=true`.
  - `service.search("Martian soil simulants building materials", limit=8, retrieval="fts")` -> `0.375s`, 8 results, `fallback_or.skipped=true`.
  - `service.acquire_evidence("large language models for materials discovery", retrieval="fts", limit=8)` -> `3.38s`, 8 results, 13 evidence candidates, `coverage=sufficient`.
  - `service.acquire_evidence("What papers discuss Martian soil simulants for building materials?", retrieval="fts", limit=8)` -> `0.362s`, 8 results, 13 evidence candidates, `coverage=sufficient`.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_retrieval_packet.py backend/tests/test_literature_search_research_agent.py backend/tests/test_tool_execution.py backend/tests/test_agent_loop.py -q` -> 81 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 705 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 66 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.
- Attempted full live `/api/chat/stream` smoke on a fresh current-source backend at `127.0.0.1:8022`:
  - `/api/readiness.build.readiness_contract_version` was current.
  - The English research request emitted `intent_route(route=research)`.
  - The run then failed before search because the configured model returned `model 'llama3.1' not found`.
  - Therefore a successful English cited-answer runtime smoke remains unverified due to local LLM configuration, not due to the repaired retrieval path.

## 2026-07-07 priority repair batch 5
- Adjusted direction after product decision: Literature Search research QA is LLM-based and must not generate a local retrieval-summary substitute when the model is unavailable.
- Updated research route behavior:
  - If Agent/LLM is disabled or unavailable, emit `failure_explanation(code=llm_required_for_research)` and a Chinese blocking message.
  - If the configured model fails at runtime, emit `failure_explanation(code=llm_runtime_unavailable)` and a Chinese model-configuration diagnostic.
  - Do not emit `search_meta`, `papers`, citation metadata, or local retrieval-summary answer in those blocked paths.
- Removed stale UI/settings copy that said Chat would fall back to a local retrieval summary; Settings now says Literature Search research QA needs an available model.
- Live smoke on fresh current-source backend at `127.0.0.1:8022` with the current bad `llama3.1` config:
  - elapsed `0.28s`;
  - emitted `intent_route(route=research)`;
  - emitted `failure_explanation(code=llm_runtime_unavailable)`;
  - emitted no `search_meta`, no `papers`, and no `error` event;
  - answer text says the configured model `llama3.1` is unavailable and asks the user to switch to an available model.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_literature_search_research_agent.py -q` -> 15 passed.
  - Focused Literature Search/backend regression set -> 94 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 706 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 66 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-07 priority repair batch 5 readiness follow-up
- Tightened Settings readiness to match the LLM-required product direction:
  - `provider=ollama` is no longer treated as ready merely because no API key is required.
  - Readiness now checks Ollama `/api/tags` and requires the configured chat model to exist.
  - Missing local Ollama model reports `ollama_model_unavailable` with Chinese labels in Settings and chat fallback diagnostics.
- Live verification on a fresh current-source backend at `127.0.0.1:8023`:
  - `/api/settings/readiness` returned `ready=false`, `mode=blocked`, `fallback_mode=blocked_requires_llm`, and `reasons=["ollama_model_unavailable"]` for the current `ollama/llama3.1` config.
  - `/api/chat/stream` for `What papers discuss Martian soil simulants for building materials?` emitted `intent_route(route=research)` and `failure_explanation(code=llm_runtime_unavailable)`, with no `papers`, no `search_meta`, no citation event, and no local retrieval-summary answer.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_settings.py backend/tests/test_api_contract_settings_workflow.py -q` -> 15 passed.
  - `PYTHONPATH=backend pytest backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_literature_search_research_agent.py -q` -> 15 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 707 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 66 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-07 priority repair batch 6
- Resolved the remaining stale-session UI recovery observation (`LS-NEW-004`):
  - If Literature Search remembers an active session whose detail endpoints now return `session not found`, `selectModule()` removes that stale session from local frontend state.
  - If another listed session is available, it opens the next available session and updates `localStorage`.
  - If no valid session remains, it creates a fresh `新对话` session and updates `localStorage`.
  - Non-missing-session errors still surface as user-visible errors; the recovery is scoped to 404/not-found stale session state.
- Added frontend store contract tests for both recovery branches:
  - stale remembered session -> next available session;
  - stale remembered session only -> create fresh session.
- Verification:
  - `node --test frontend/tests/literature_search_store_contract.test.mjs` -> 9 passed.
  - `node --test frontend/tests/*.test.mjs` -> 68 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 707 passed, 24 skipped.

## 2026-07-07 priority repair batch 7
- Resolved the `LS-P1-015` paper tab/detail clarity gap in source/tests.
- Root cause:
  - `buildPaperItems()` preferred `researchState.candidate_papers` once available.
  - Those candidate papers carry status/evidence counts, but often lack the current retrieval result's readable fields such as `snippet`, `abstract`, `authors`, `year`, and `venue`.
  - As a result, the right-side paper cards and middle paper detail overlay could show curated status while losing useful match text.
- Implemented a view-model merge:
  - current retrieval papers are indexed by multiple identities (`key`, `id`, `paper_id`, `paperId`, `doi`, `article_id`);
  - research-state candidate papers keep authoritative status/note/count fields;
  - current retrieval fields enrich the same paper for card/detail readability;
  - `findPaper()` benefits because it reads from `buildPaperItems()`.
- Verification:
  - `node --test frontend/tests/literature_search_view_model.test.mjs` -> 8 passed.
  - `node --test frontend/tests/*.test.mjs` -> 69 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 707 passed, 24 skipped.

## 2026-07-07 priority repair batch 8
- Added automated guardrails for two remaining LLM-dependent live-smoke risks:
  - English successful-answer pseudo-citation risk now has a controlled `AgentLoop` regression: search returns real evidence `E1`, the fake English model answers with fabricated `[E99]`, and citation audit must emit `status=warning`, `audit_status=unverified`, `missing_ids=["E99"]`, and no `used_evidence`.
  - Attachment + literature combined turns now have a blocked-path regression for the current LLM-required semantics: when LLM is disabled, even with parsed attachments present, the turn emits `llm_required_for_research` and does not call local retrieval summary/search fallback.
- This does not replace the still-required real-provider smoke; it reduces the remaining risk by proving the deterministic audit floor and blocked semantics under controlled conditions.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_agent_loop.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_literature_search_research_agent.py -q` -> 38 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 709 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 69 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-07 priority repair batch 9
- Re-audited remaining partially resolved items against current source and runtime readiness.
- Current model readiness remains blocked:
  - `ready=false`
  - `mode=blocked`
  - `reasons=["ollama_model_unavailable"]`
  - `fallback_mode=blocked_requires_llm`
- Re-ran real-index evidence acquisition for the previously problematic broad English queries:
  - `large language models for materials discovery` -> `3.269s`, 8 results, `coverage=sufficient`.
  - `What papers discuss Martian soil simulants for building materials?` -> `0.341s`, 8 results, `coverage=sufficient`.
- Updated the rerun report so `LS-P1-005` is no longer treated as an open retrieval-latency tuning item. This was later superseded by Batch 10, which fixed active API profile precedence and completed the successful-answer smokes with DeepSeek.
- Static fallback-summary boundary check still only finds the negative assertion that "本地检索摘要" must not appear.

## 2026-07-07 priority repair batch 10
- Corrected the model-readiness diagnosis after user clarification:
  - active model profiles now take precedence over stale `settings.models`;
  - current readiness reports `provider=deepseek`, `model=deepseek-chat`, `base_url=https://api.deepseek.com/v1`, `api_key_source=profile`;
  - `/api/settings` and `/api/settings/effective` now expose the active profile values/source so the UI does not imply a local Ollama path when a configured API profile is active.
- Re-ran real API/LLM smokes on a fresh current-source backend at `127.0.0.1:8031`:
  - English cited answer, `What papers discuss Martian soil simulants for building materials?`, completed in `47.49s`, returned candidate papers, `citation.status=ok`, `missing_ids=[]`, and no process-preface leakage.
  - Attachment + literature combined query completed with `attachment_context`, `route=research`, candidate papers, `citation.status=ok`, `missing_ids=[]`, formal `[E#]` literature citations, and `used_attachments={"attachment_count":1,"filenames":["llm_materials_note.txt"]}`.
- Tightened final-answer cleanup for real-provider outputs:
  - strips English and Chinese process prefaces such as "I already have sufficient evidence...", "非常好，我已经获得...", "现在我有足够的证据...", and "让我整合...";
  - adds a deterministic `来自上传附件《filename》` source marker when parsed session attachments are loaded into a research turn and the model omits that marker;
  - emits and persists `attachment_context` metadata from `chat_router` for any turn carrying parsed active attachments, not only attachment-only routes.
- Remaining product observation:
  - attachment + literature combined live runs are functionally correct but can still take `35.7s-126.67s` depending on provider generation latency and answer length; this is now a performance/UX optimization item, not a semantic correctness blocker.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_agent_loop.py backend/tests/test_session_attachments.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_literature_search_research_agent.py backend/tests/test_settings.py backend/tests/test_api_contract_settings_workflow.py backend/tests/test_api_contract_sessions_chat.py -q` -> 67 passed.
  - `PYTHONPATH=backend pytest backend/tests -q` -> 713 passed, 24 skipped.
  - `node --test frontend/tests/*.test.mjs` -> 69 passed.
  - `npm --prefix frontend run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-09 formal user management task 7
- Added formal browser-auth frontend API contracts and client support:
  - exported `authApi`, `accountApi`, and `adminApi` from `frontend/src/api/client.js`;
  - all formal browser API calls send `credentials: "include"`;
  - account/admin/logout mutations fetch `/api/auth/csrf` and send `X-CSRF-Token`;
  - admin user/audit queries use encoded query strings and user IDs.
- Kept the existing development `X-User-Id` adapter behavior through `apiHeaders()` / `apiUploadHeaders()`.
- Verification:
  - `cd frontend && node --test tests/api_client_contract.test.mjs` -> 40 passed.
  - `cd frontend && node --test tests/*.test.mjs` -> 85 passed.
  - `cd frontend && npm run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-10 formal user management task 8
- Added frontend auth bootstrap and login/registration gate:
  - `useAppStore` now owns `currentUser`, `auth.status`, `auth.mode`, `auth.loading`, and `auth.error`;
  - `bootstrapAuth()` calls `/api/auth/me`, sends authenticated users into `loadModules()`, and leaves unauthenticated users at `login_required` without loading modules;
  - `authLogin()`, `authSignup()`, and `authLogout()` call the formal auth API client and reset browser app state on logout;
  - `App.jsx` now checks auth first and renders `AuthScreen` when login is required;
  - `AuthScreen.jsx` provides compact email/password login and self-service registration with display name.
- Also made `fetchModules()` and `fetchLibrary()` send `credentials: "include"` so the authenticated startup path carries the DB session cookie.
- Verification:
  - `cd frontend && node --test tests/literature_search_store_contract.test.mjs tests/auth_ui_contract.test.mjs` -> 12 passed.
  - `cd frontend && node --test tests/*.test.mjs` -> 88 passed.
  - `cd frontend && npm run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-10 formal user management task 9
- Added Account settings and Admin Users UI:
  - Settings Account tab now uses `currentUser`, supports display name/avatar update, password change, active sessions display, and API token create/revoke;
  - store now owns `account`, `adminUsersOpen`, and `adminUsers` state with account/admin API actions;
  - TopBar shows the current user and provides Account, Admin Users (admin only), and Logout icon actions;
  - `AdminUsersModal.jsx` provides role/status controls and password reset for admins.
- Verification:
  - `cd frontend && node --test tests/auth_ui_contract.test.mjs` -> 3 passed.
  - `cd frontend && node --test tests/auth_ui_contract.test.mjs tests/literature_search_store_contract.test.mjs` -> 14 passed.
  - `cd frontend && node --test tests/*.test.mjs` -> 90 passed.
  - `cd frontend && npm run build` -> passed with only the existing Vite chunk-size warning.

## 2026-07-10 formal user management task 10
- Documented formal local login and deployment readiness:
  - `.env.example` keeps `AUTH_MODE=dev-header` as the development default and adds commented local-password cookie/session settings;
  - `docs/deployment.md` now describes Formal Local Login, first-admin bootstrap, opaque `lap_session`, CSRF cookie/header, API tokens, and trusted-header as an SSO/reverse-proxy bridge;
  - `README.md` now points teams to `AUTH_MODE=local-password` for formal browser login and removes the stale local retrieval-summary fallback statement.
- Verification:
  - `PYTHONPATH=backend pytest backend/tests/test_auth_config.py backend/tests/test_passwords.py backend/tests/test_formal_auth.py backend/tests/test_account_api.py backend/tests/test_admin_users_api.py backend/tests/test_postgres_migrations.py -q -rs` -> 21 passed, 23 skipped because `TEST_DATABASE_URL` is not configured.
  - `PYTHONPATH=backend pytest backend/tests/test_postgres_m2_core_runtime.py backend/tests/test_user_context.py backend/tests/test_api_contract_sessions_chat.py backend/tests/test_api_contract_settings_workflow.py -q -rs` -> 10 passed, 5 skipped because `TEST_DATABASE_URL` / `DATABASE_URL` runtime DB coverage is not configured.
  - Explicit `TEST_DATABASE_URL=postgresql+psycopg://literature_agent:...@127.0.0.1:5432/literature_agent` attempts failed before test logic because local Postgres lacks role `literature_agent`; no app code failure was indicated.
  - `cd frontend && node --test tests/api_client_contract.test.mjs tests/literature_search_store_contract.test.mjs tests/auth_ui_contract.test.mjs` -> 54 passed.
  - `cd frontend && npm run build` -> passed with only the existing Vite chunk-size warning.
- Manual dev-server smoke was not run: existing services already occupy `8000` and `5173`, `dev.sh` would stop the existing backend on `8000`, Vite proxy is fixed to `8000`, and the local test DB role is absent.
