# Literature Search Product Test Rerun - 2026-07-07

Tester: Codex
Scope: Re-test Literature Search productization after the recent trusted-answer, review-workbench, and research-session workbench fixes.

## Status Legend

- `resolved`: Previously reported issue is now verified fixed in the current state.
- `partially_resolved`: The core failure is improved, but product-quality gaps remain.
- `unresolved`: The issue still reproduces.
- `new`: Newly observed issue in this rerun.

## Test Matrix

| Area | Checks |
|---|---|
| Startup / dependencies | Backend import, running readiness, `python-multipart`, frontend build |
| Lightweight intent routing | help/plain chat, library count/index/year/journal/recent-import, attachment-only/missing |
| Corpus status | `/api/corpus/quick-stats`, route answers use stats not retrieval |
| Attachments | txt/pdf API contract, attachment-only answer boundary, deleted/missing attachment |
| Zero-result / failure explanation | no-hit topic, no-candidate, no-usable-evidence labels and UI audit |
| Review workbench | right tabs evidence/papers/audit, route/failure/attachment/library metadata, detail overlay |
| Research session workbench | evidence pool, evidence status API, paper status, suggested actions, research state summary |
| UI / IA | sidebar entries, responsive behavior, P2-M12/protocol boundary text |

## Command Evidence

- Dependency/startup:
  - `/opt/anaconda3/envs/pc_plus/bin/python` can import `multipart`, `fastapi`, `uvicorn`, and `main`.
  - Output: `pc_plus_import_ok`, `multipart 0.0.32`, `app_routes 14`.
  - Classification impact: previous `LS-P0-001` is resolved in the current runtime/dependency setup.
- Running backend readiness:
  - `GET http://127.0.0.1:8000/api/readiness` returned `ready=true`, `overall=ok`.
  - Registry currently reports `module_ids=["literature_search"]`.
- Quick corpus stats:
  - `GET /api/corpus/quick-stats` returned in `0.447896s`.
  - Key values: `paper_count=147371`, `article_index_count=147372`, `year_range=[2010,2026]`, top journal `ACS Applied Materials & Interfaces=29197`, `recent_imports=8`.
- Backend targeted regression:
  - `PYTHONPATH=backend pytest backend/tests/test_lightweight_routes.py backend/tests/test_corpus_quick_stats.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_api_contract_sessions_chat.py backend/tests/test_session_attachments.py backend/tests/test_research_state.py -q`
  - Initial rerun result: `30 passed`.
- Post-repair backend verification for the structured audit metadata batch:
  - Added/updated tests for `plain_help/plain_chat` `intent_route` events, deterministic plain-chat fallback when LLM is unavailable, no-candidate failure explanations, and chat-router persistence of `failure_code/failure_message`.
  - `PYTHONPATH=backend pytest backend/tests/test_lightweight_routes.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_api_contract_sessions_chat.py backend/tests/test_session_attachments.py backend/tests/test_research_state.py -q` -> `31 passed`.
  - `PYTHONPATH=backend pytest backend/tests/test_tool_execution.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_api_contract_sessions_chat.py -q` -> `36 passed`.
  - `PYTHONPATH=backend pytest backend/tests -q` -> `692 passed, 24 skipped`.
- Frontend regression/build:
  - `node --test frontend/tests/*.test.mjs`
  - Initial rerun result: `58 passed`.
  - `npm --prefix frontend run build`
  - Result: build passed; only Vite chunk-size warning.
- Post-repair frontend verification for the first priority UI batch:
  - Added `frontend/tests/literature_search_ui_contract.test.mjs`.
  - `node --test frontend/tests/literature_search_ui_contract.test.mjs` -> `6 passed`.
  - `node --test frontend/tests/*.test.mjs` -> `64 passed`.
  - `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
  - Static boundary search found no `数据抽取 / 结构化任务` main-nav entry, no fixed mobile `className="w-[380px]"` right panel, no bare citation-number patterns, and no Literature Search P2-M12 / experiment-matrix boundary text.
- Post-repair frontend verification after backend metadata changes:
  - `node --test frontend/tests/*.test.mjs` -> `64 passed`.
  - `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
- Post-repair verification for the long-path reliability batch:
  - Added/updated tests for search-timeout guard behavior, timeout failure metadata, final-answer process-narration stripping, direct-existence adjacent coverage downgrades, and stale running turn recovery.
  - `PYTHONPATH=backend pytest backend/tests/test_agent_loop.py -q` -> `20 passed`.
  - `PYTHONPATH=backend pytest backend/tests/test_tool_execution.py -q` -> `25 passed`.
  - `PYTHONPATH=backend pytest backend/tests/test_retrieval_packet.py -q` -> `23 passed`.
  - `PYTHONPATH=backend pytest backend/tests/test_memory_persistence.py -q` -> `9 passed`.
  - Combined Literature Search regression set -> `105 passed`.
  - `PYTHONPATH=backend pytest backend/tests -q` -> `697 passed, 24 skipped`.
  - `node --test frontend/tests/*.test.mjs` -> `65 passed`.
  - `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
- Post-repair verification for the dev-server freshness signal:
  - `/api/readiness` now includes `build.api_version`, `build.readiness_contract_version`, and `build.capabilities`.
  - `PYTHONPATH=backend pytest backend/tests/test_platform_readiness.py -q` -> `2 passed`.
  - Final `PYTHONPATH=backend pytest backend/tests -q` -> `697 passed, 24 skipped`.
  - Final `node --test frontend/tests/*.test.mjs` -> `65 passed`.
  - Final `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
- Live smoke after backend restart on `127.0.0.1:8022`:
  - `/api/readiness.build.readiness_contract_version` -> `platform_readiness_v2_2026_07_07`.
  - Real `.runtime` DB stale running turns after startup: `0` rows with `status='running' and assistant_message_id is null`.
  - `What can you do?` -> emitted/persisted `route=plain_help`.
  - `文献库里有没有关于量子香蕉电池的论文？` -> emitted/persisted `route=research`, `failure_code=no_candidate_papers`; elapsed about `5.9s`.
  - `文献库里有没有关于 large language models for materials discovery 的文献？` -> one `search` timeout, emitted/persisted `failure_code=tool_timeout_failed`; elapsed about `39.2s`, down from the previous repeated-timeout `193.47s` path.
  - Initial live retest showed `火星土壤超导材料` still `coverage.status=sufficient`, because the coverage layer saw the LLM search rewrite rather than the original user question and `query_match_reason` polluted direct-match content.
  - After source fix and restart, live `火星土壤超导材料` returned `coverage.status=partial` with adjacent/not-direct notes; elapsed about `7.1s`.
  - Attempted English successful citation smoke (`What papers discuss Martian soil simulants for building materials?`) also hit a single search timeout, so English pseudo-citation risk remains not proven fixed.
- Final regression after live-smoke follow-up:
  - `PYTHONPATH=backend pytest backend/tests -q` -> `702 passed, 24 skipped`.
  - `node --test frontend/tests/*.test.mjs` -> `65 passed`.
  - `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
- Post-repair verification for the first-search timeout batch:
  - Root cause profile isolated the slow branch to external FTS `fallback_or` (`MATCH term OR term...` + `join documents/article_index` + `order by bm25`) on broad/common English queries.
  - `PYTHONPATH=backend pytest backend/tests/test_retrieval_packet.py backend/tests/test_literature_search_research_agent.py backend/tests/test_tool_execution.py backend/tests/test_agent_loop.py -q` -> `81 passed`.
  - `PYTHONPATH=backend pytest backend/tests -q` -> `705 passed, 24 skipped`.
  - `node --test frontend/tests/*.test.mjs` -> `66 passed`.
  - `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
  - Real-index `service.search("large language models for materials discovery", limit=8, retrieval="fts")` -> `3.57s`, 8 results, `fallback_or.skipped=true`.
  - Real-index `service.acquire_evidence("large language models for materials discovery", retrieval="fts", limit=8)` -> `3.38s`, 8 results, 13 evidence candidates, `coverage=sufficient`.
  - Real-index `service.acquire_evidence("What papers discuss Martian soil simulants for building materials?", retrieval="fts", limit=8)` -> `0.362s`, 8 results, 13 evidence candidates, `coverage=sufficient`.
  - Fresh `/api/chat/stream` smoke on `127.0.0.1:8022` confirmed the then-current readiness and `intent_route(route=research)`, then failed before search with configured model error `model 'llama3.1' not found`; this was later superseded by the active-profile precedence correction and DeepSeek live smoke below.
- Post-direction-correction verification for LLM-required research QA:
  - Product decision: Literature Search research QA requires a working LLM and must not fall back to a local retrieval-summary answer.
  - Fresh `/api/chat/stream` smoke on `127.0.0.1:8022` with the bad `llama3.1` config returned in `0.28s`.
  - It emitted `intent_route(route=research)` and `failure_explanation(code=llm_runtime_unavailable)`.
  - It emitted no `search_meta`, no `papers`, no `error`, and no local retrieval-summary answer.
  - User-facing answer: configured model `llama3.1` is unavailable or not installed; switch to an available model.
  - `PYTHONPATH=backend pytest backend/tests -q` -> `706 passed, 24 skipped`.
  - `node --test frontend/tests/*.test.mjs` -> `66 passed`.
  - `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
- Post-active-profile correction verification for API-model research QA:
  - Product correction: Literature Search research QA is based on the configured API model profile; local/Ollama readiness is relevant only when the user selects that provider.
  - Fixed Settings precedence so the active profile overrides stale `settings.models` fields.
  - `GET /api/settings/readiness` on fresh current-source backend `127.0.0.1:8031` returned `ready=true`, `mode=agent`, `active_model.provider=deepseek`, `active_model.model=deepseek-chat`, `api_key_source=profile`.
  - Live English cited-answer smoke, `What papers discuss Martian soil simulants for building materials?`, completed in `47.49s`, returned candidate papers, persisted `route=research`, `citation.status=ok`, `missing_ids=[]`, and no English process-preface leakage.
  - Live attachment + literature smoke, `请先总结附件内容，再结合文献库补充“大语言模型在材料发现中的应用”的相关研究。`, emitted `attachment_context`, returned candidate papers, persisted `used_attachments`, and ended with `citation.status=ok`, `missing_ids=[]`.
  - Added deterministic cleanup for Chinese final-answer process prefaces and deterministic `来自上传附件《...》` source-marker fallback when active parsed attachments are loaded into a research turn.
  - `PYTHONPATH=backend pytest backend/tests/test_agent_loop.py backend/tests/test_session_attachments.py backend/tests/test_literature_search_lightweight_chat.py backend/tests/test_literature_search_research_agent.py backend/tests/test_settings.py backend/tests/test_api_contract_settings_workflow.py backend/tests/test_api_contract_sessions_chat.py -q` -> `67 passed`.
  - `PYTHONPATH=backend pytest backend/tests -q` -> `713 passed, 24 skipped`.
  - `node --test frontend/tests/*.test.mjs` -> `69 passed`.
  - `npm --prefix frontend run build` -> build passed; only Vite chunk-size warning.
- Backend full regression:
  - `PYTHONPATH=backend pytest backend/tests -q`
  - Initial rerun result: `687 passed, 24 skipped`.
- Boundary search:
  - `rg -n "P2-M12|experiment matrix|create_experiment_matrix|实验矩阵|实验方案|protocol|final claims" ...`
  - Result: no matches in the Literature Search workbench/store files checked.

## API / Product Evidence

### Library Status Routes

All tested library-status questions now used deterministic lightweight routing, emitted `intent_route` + `library_status`, produced no retrieval `step` events, and did not create citation metadata.

| Case | Input | Route | Time | Evidence |
|---|---|---:|---:|---|
| library count | `当前文献库中一共有多少文献？` | `library_count` | `0.419s` | Answer: `147,371` papers, `147,372` article-index records, `2,911,107` sections, `4,979,646` chunks |
| indexed count | `现在有多少篇文献已经完成索引？` | `library_indexed_count` | `0.416s` | Explains `papers` vs `article_index` counts |
| year coverage | `当前文献库覆盖哪些年份？` | `library_year_coverage` | `0.398s` | Answer: `2010-2026`, top years from metadata |
| journal distribution | `当前文献库主要包含哪些期刊？` | `library_journal_distribution` | `0.395s` | Returns top journal counts from metadata |
| recent imports | `最近导入了哪些文献？` | `library_recent_imports` | `0.395s` | Returns recent indexed/imported items |

### Plain Help / Identity

| Case | Input | Actual |
|---|---|---|
| English help | `What can you do?` | Initial rerun: no retrieval steps, no citation, English capability answer, but missing `route=plain_help` metadata. Post-repair source/tests now emit `intent_route(route=plain_help)` before LLM/deterministic help responses. |
| Chinese identity | `你是谁？` | Initial rerun: no retrieval steps, no citation, Chinese identity answer, but missing `route=plain_help` metadata. Post-repair source/tests now emit `intent_route(route=plain_help)` before LLM/deterministic help responses. |
| Casual plain chat | `你好` | Post-repair source/tests emit `intent_route(route=plain_chat)` and, if LLM is unavailable, return a deterministic non-retrieval answer instead of an error. |

### Attachment Routes

| Case | Input | Actual |
|---|---|---|
| Missing attachment | `请总结刚才的附件。` without active attachment IDs | `route=attachment_missing`, `failure_code=attachment_missing`, Chinese explanation: `当前会话没有可用附件...` |
| Upload txt | Upload `material_note.txt` | Parsed successfully; `status=parsed`, `char_count=44`, preview available |
| Attachment-only with protocol | Same question with `options.attachment_ids=[attachment_id]` | `route=attachment_only`, `used_attachments={attachment_count:1, filenames:["material_note.txt"]}`, no citation, answer summarizes attachment and ends with `来自上传附件《material_note.txt》` |
| Attachment-only without protocol | Same question without `options.attachment_ids` | Correctly treated as `attachment_missing`; this is expected for raw API calls and confirms the frontend must send active attachment IDs. |

### Topic No-Hit

Input: `文献库里有没有关于量子香蕉电池的论文？`

- Time: `3.773s`.
- It entered research retrieval, searched `量子香蕉电池`, returned 0 candidate papers / 0 evidence.
- Answer is now semantically clearer than the old generic template:
  - says local library did not find papers about the topic;
  - states 0 matched papers;
  - says this does not mean the library is empty or that the topic cannot exist elsewhere;
  - suggests alternative searches.
- Remaining gap:
  - Initial rerun assistant metadata did not include a structured `failure_code` / `failure_explanation`.
  - Post-repair source/tests now emit `failure_explanation(code=library_not_empty_but_no_query_hit)` when research fallback returns zero candidate papers and quick corpus stats show the local library is non-empty.
  - A fresh live API rerun should still be performed after restarting the dev backend to confirm the running process exposes the new route/failure metadata.

### Evidence Curation API

The existing live backend on port 8000 returned 404 for `POST /api/sessions/{id}/evidence-status`, while the current worktree contains the route. A fresh backend started on temporary port 8010 with the current code verified the feature:

- `POST /api/sessions/s_22f7b87fd3d4/evidence-status`
- Evidence item: `ei_039d28e65b32`
- Temporary mutation: `candidate -> needs_review`, note `QA 复测临时标记`
- Response included:
  - `temporary_status=needs_review`
  - `status_counts={"candidate":13,"needs_review":1}`
  - latest provenance `field=evidence_status`
- The status was restored to its original value after the test.

Interpretation: current code is correct, but the running 8000 backend had not been restarted after the latest backend route addition. This is a dev-server freshness issue, not a current source-code failure.

### Supplemental Long-Path Rerun

To close the previous long-path evidence gap, a fresh backend was started on port 8011 with the current worktree and the same memory DB. The long-path results were written to `/tmp/lit_product_long_rerun.json`.

| Case | Input / path | Time | Result |
|---|---|---:|---|
| English research QA | `What are the applications of large language models in materials discovery?` | `194.15s` | Three `search` calls timed out; answer started with English process narration; no evidence pool; citation metadata in assistant metadata was `audit_status=advisory`, `answer_permission=not_answerable`. |
| Chinese research QA | `大语言模型在材料发现中的应用有哪些？` | `203.47s` | Three `search` calls timed out; no evidence; not-answerable advisory citation metadata. |
| Attachment + literature | Upload `perovskite_note.txt`, ask `请先总结附件内容，再结合文献库补充相关研究。` | `193.91s` | Attachment summary succeeded, but all three literature searches timed out; no literature evidence; not-answerable advisory citation metadata. |
| Adjacent negative coverage | `文献库里有没有关于火星土壤超导材料的论文？` | `7.88s` | Returned 8 papers / 14 evidence and `coverage.status=sufficient`, but answer says there are no direct "火星土壤超导材料" papers; evidence is adjacent Martian soil / construction / chemistry material. |
| Exact English topic query | `文献库里有没有关于 large language models for materials discovery 的文献？` | `193.47s` | Three search attempts timed out, including simplified `LLM materials discovery`; no evidence; not-answerable advisory citation metadata. |

Additional DB state check:

- Table `turns` still contains two old `running` turns with no assistant message:
  - `s_084a644a517e / t_295f4f51b335`: `请先总结附件内容，再结合文献库补充相关研究。`
  - `s_87338d6d7260 / t_fca3193b3a8d`: `大语言模型在材料发现中的应用有哪些？`
- The long-path rerun sessions themselves completed and did not create new stuck `running` turns.

## UI Evidence

Browser target: `http://127.0.0.1:5173/`.

### App Shell / IA

- Visible sidebar entries:
  - `首页 / 索引健康`
  - `文献检索 / 实时证据问答`
  - `研究工作流 / 受控任务引擎`
  - `数据抽取 / 结构化任务`
  - `设置 / 平台与模型`
- The agreed current IA expected four main entries. `数据抽取 / 结构化任务` is still visible.
- No forbidden workflow text was found in the visible app shell or Literature Search workbench: no `P2-M12`, `experiment matrix`, `create_experiment_matrix`, `实验矩阵`, `实验方案`, `protocol`, or `final claims`.

### Literature Search Workbench

The Literature Search page shows:

- right-side tabs: `证据 / 文献 / 审计`;
- input modes: `快速回答 / 证据审阅 / 深度分析`;
- session-level attachment file input accepting txt/pdf;
- compact research state strip:
  - phase/stage;
  - open questions;
  - accepted papers;
  - accepted evidence;
- evidence tab filters:
  - `本轮 / 证据池 / 已保留 / 待复核 / 已排除`;
- evidence curation buttons:
  - `保留 / 排除 / 待复核 / 备注`.

### Responsive Layout

Viewport: `390x844`.

Initial rerun result:

- `scrollWidth=636`, `viewport width=390`, so horizontal overflow still exists.
- Right workbench starts around `x=256` with width `380`, extending beyond the viewport.
- Several stage/status elements extend beyond the viewport.
- The input `textarea` exists but measured width is `0`.

Post-repair result:

- Main sidebar collapses to a `68px` icon rail on narrow screens.
- Literature Search page at `390x844` measured `scrollWidth=390` and `bodyScrollWidth=390`.
- Right workbench measured `x=68`, `width=322`, inside the viewport.
- Input `textarea` measured `width=176`, no longer `0`.
- Right-side tabs `证据 / 文献 / 审计` remained present.

Classification impact: previous `LS-P1-017` is resolved for the 390px smoke scenario.

### Session Restore

During a reload on the home view, the app briefly showed `打开会话失败：session not found`. Clicking `文献检索` then opened the workbench successfully with chat input and tabs. This is not currently blocking, but it is a new product-quality observation and should be re-tested with a clean browser profile / cleared local storage.

## Issue Classification

### Resolved

| Issue | Current status | Evidence |
|---|---|---|
| LS-P0-001 default backend runtime missing multipart | resolved | `pc_plus_import_ok`, `multipart 0.0.32`, backend import succeeds |
| LS-P1-001 slow status path for chat-time library questions | resolved for chat/status route | `/api/corpus/quick-stats` returns in ~0.45s; chat status routes return in ~0.4s |
| LS-P0-002 library count misrouted into retrieval | resolved | `library_count` emits `intent_route + library_status`, no retrieval steps |
| LS-P0-003 zero-result library count falsely implies empty corpus | resolved | library-count answer uses corpus stats and says local-statistics boundary |
| LS-P0-005 library metadata direct route missing | resolved | indexed count and recent imports now use deterministic metadata route |
| LS-P0-006 year coverage sample-based wrong answer | resolved | year coverage returns `2010-2026` from metadata route |
| LS-P1-008 journal coverage sample-based answer | resolved | top journals and counts returned from metadata route |
| LS-P0-008 attachment-only ignored parsed attachments | resolved when frontend protocol sends `attachment_ids` | attachment-only route summarizes uploaded txt and marks `来自上传附件《...》` |
| LS-P2-002 deleted/missing attachment explanation | resolved | `attachment_missing` returns Chinese actionable explanation |
| P2-M12 / experiment matrix Literature Search boundary | resolved | static and visible UI search found no forbidden entry text |
| LS-P1-014 extra `数据抽取` main navigation entry | resolved | Main sidebar no longer renders `数据抽取 / 结构化任务`; structured extraction code remains internal/unexposed as a primary entry |
| LS-P1-017 mobile/narrow Literature Search layout unusable | resolved for 390px smoke | Sidebar collapses to 68px; right workbench stacks below chat; measured `scrollWidth=390`, textarea width `176` |
| LS-P1-013 ambiguous citation labels / two ID systems | resolved for UI labeling | Inline citations and evidence cards now display `证据 1` style ordinals; real identifiers are labeled as `证据ID：...` |
| LS-P0-007 `What can you do?` corrupted by citation gate | resolved for route/citation metadata | Help/plain paths emit `intent_route`, do not emit citation, and tests verify help is not rewritten to evidence-insufficient text |
| LS-P2-001 identity wording too narrow | resolved for route metadata | `plain_help` route is now emitted before identity/help answers; wording quality remains subject to live LLM content |
| LS-P1-010 no-hit topic generic template | resolved for fallback metadata | Zero-candidate research fallback emits `failure_explanation` with `library_not_empty_but_no_query_hit` when the local corpus is non-empty |
| LS-P1-016 generic Chinese failure layer | resolved for no-hit/attachment metadata | Attachment missing and no-hit now have structured Chinese failure metadata; timeout-specific failures remain in the long-path bucket |
| LS-P1-002 audit tab route/failure explanation | resolved for plain/no-hit source contract | Frontend already consumes route/failure metadata; backend now emits route for plain help/chat and failure for no-candidate fallback |
| LS-P1-003 papers tab empty-corpus vs no-hit | resolved for no-candidate fallback metadata | No-candidate fallback now carries `library_not_empty_but_no_query_hit`, allowing the papers tab to distinguish no-hit from empty corpus |
| LS-P1-004 English/internal process text leaks into answer | resolved in source/tests | Final answer sanitization strips common English/Chinese process narration prefixes and replays the cleaned answer via `answer_reset`; `test_final_answer_process_narration_is_stripped_after_failed_search` passes |
| LS-P1-006 tool timeout summary / recovery | resolved in source/tests | Search timeout now emits `failure_explanation(code=tool_timeout_failed)` and blocks further search calls in the same turn; `test_search_timeout_stops_additional_searches_and_emits_failure` passes |
| LS-P1-006a first-search timeout on broad English queries | resolved in source + real-index service checks | External FTS fallback OR is skipped once phrase/core routes fill the candidate pool; English research questions are normalized before retrieval. Real-index evidence acquisition for the prior English blockers now returns in `0.36s-3.38s` with candidates and sufficient coverage. |
| LS-P1-006b model unavailable research QA semantics | resolved per product direction | Research QA now requires LLM. Bad/missing model config returns `llm_required_for_research` or `llm_runtime_unavailable` with Chinese diagnostics and no local retrieval-summary answer. Settings readiness also checks Ollama `/api/tags`; the current missing `llama3.1` config reports `ollama_model_unavailable` and `blocked_requires_llm` instead of “ready”. |
| LS-P1-012 abandoned streams stuck running | resolved in source/tests | `SessionStore` recovers old running turns with no assistant message by marking them failed and inserting a readable Chinese assistant note; recovery test passes |
| LS-P1-007 related-but-no-direct-match topic coverage | resolved in source/tests and live smoke | Direct existence queries now use the original user question, require direct key-topic-term coverage in the same evidence locus, ignore `query_match_reason`, and live `火星土壤超导材料` now returns `coverage.status=partial` with adjacent/not-direct notes |
| LS-P1-015 paper tab/detail interaction | resolved in source/tests | `buildPaperItems()` now merges research-state candidate papers with current retrieval papers by multiple identities, preserving candidate status while restoring readable snippet/abstract/authors/year/venue for right-side cards and middle detail overlay. Regression test covers the enrichment path. |
| LS-P1-005 quick research QA latency | resolved for retrieval layer and successful API smoke | Repeated search timeouts are stopped after one timeout, slow external FTS fallback OR is bounded, and fresh real-index evidence acquisition now returns in `3.269s` for `large language models for materials discovery` and `0.341s` for `What papers discuss Martian soil simulants for building materials?`, both with 8 results and `coverage=sufficient`. A successful DeepSeek cited-answer smoke completed with `citation.status=ok`; provider generation latency remains a UX/performance observation. |
| LS-P1-004b real-provider final-answer process narration | resolved in source/tests | DeepSeek live smokes exposed additional Chinese final-answer prefaces. The cleanup now strips `获得/收集/已有充分证据` and `让我整合/给出回答` variants before persistence/audit; latest source tests cover these observed variants. The same live smokes verified attachment marker/metadata/citation behavior. |
| LS-P1-018 active API model profile precedence | resolved in source/tests and live smoke | Active DeepSeek profile now overrides stale `settings.models` Ollama fields in readiness/runtime settings/effective config. `/api/settings/readiness` reports `ready=true`, `provider=deepseek`, `api_key_source=profile`; focused settings tests pass. |

### Partially Resolved

| Issue | Current status | Remaining gap |
|---|---|---|
| LS-P1-011 attachment + literature latency | functionally_resolved; performance follow-up remains | Successful DeepSeek live runs now emit `attachment_context`, use parsed attachments as session context, keep formal literature evidence as `[E#]`, persist `used_attachments`, and return `citation.status=ok`. Observed end-to-end latency varies from `35.7s` to `126.67s`, so UX/performance tuning remains useful. |
| LS-P1-009 exact-query timeout before simplified query | resolved in source/tests, real-index checks, and API-profile smoke | Repeated timeout behavior is fixed, first-search fallback OR is bounded, and live API model smokes now complete. Continue monitoring provider latency separately from retrieval latency. |

### Unresolved

| Issue | Current status | Evidence |
|---|---|---|
| None currently blocking the tested Literature Search priority-repair scope | n/a | Current source has backend full regression, frontend Node tests, frontend build, English cited-answer smoke, and attachment+literature smoke evidence. |

### New / Fresh Observations

| ID | Severity | Status | Evidence | Suggested next action |
|---|---|---|---|---|
| LS-NEW-001 | P1 | resolved in source/tests | Existing dev backend on `8000` did not expose `/evidence-status`; fresh backend on `8010` did. `/api/readiness` now exposes build/version/capability metadata so stale servers are easier to detect. | Confirm the build metadata during the next live smoke after backend restart. |
| LS-NEW-002 | P1 | resolved in source/tests | Plain-help live path produced no citation and good answer, but assistant metadata had no `route=plain_help`. | Implemented `intent_route` for `plain_help/plain_chat`; rerun live API after backend restart. |
| LS-NEW-003 | P1 | resolved in source/tests | Topic no-hit main answer is good, but assistant metadata has no `failure_code`. | Implemented `failure_explanation` for no-candidate research fallback; rerun live API after backend restart. |
| LS-NEW-004 | P2 | resolved in source/tests | Home reload could surface `打开会话失败：session not found` when the remembered active session was stale. Frontend store tests now cover stale remembered session recovery to the next available session and stale-only recovery by creating a fresh session. | Re-test manually with stale localStorage in browser if desired; source behavior is covered by `literature_search_store_contract.test.mjs`. |

## Recommended Repair Order

First priority UI batch completed after the rerun:

- removed/demoted `数据抽取 / 结构化任务` from the main sidebar;
- made Literature Search usable at 390px width by collapsing the sidebar and stacking the right workbench;
- clarified citation labels by separating display ordinals from true evidence IDs.

Next recommended repair order:

1. Optimize attachment + literature combined answer latency and streaming UX:
   - current semantics/citation/metadata are correct;
   - observed successful DeepSeek runs still vary from `35.7s` to `126.67s`.
2. Keep using `/api/readiness.build` during live smoke to confirm the running backend is the current code.
3. For LLM-based Literature Search QA, also check `/api/settings/readiness`; it must show the intended active API profile before attempting successful cited-answer smoke tests.
4. Consider adding a concise answer mode or generation budget for long combined attachment + literature answers so users see the answer sooner without losing citation integrity.
