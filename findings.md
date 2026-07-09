# Findings

- Current platform has FastAPI backend, React/Vite frontend, and a module registry with `literature_search`, `idea_discovery`, and `experiment_bridge`.
- The workspace at `/Users/chenlintao/literature-agent-platform` is currently not a git repository; `git status` fails with `fatal: not a git repository`.
- Existing chat stream protocol supports `step`, `papers`, `search_meta`, `token`, `citation`, `done`, and `error`.
- Real research code lives at `/Users/chenlintao/paper-crawler-ops/literature_research`.
- Real data lives at `/Users/chenlintao/paper-crawler-ops/literature_data`.
- `research.cli selfcheck` succeeds and reports `literature-research-agent` with a large existing index.
- Direct Python import from platform backend succeeds when `/Users/chenlintao/paper-crawler-ops/literature_research` is on `sys.path`.
- Hybrid search can degrade to FTS when vector index is not built; UI should surface `vector_unavailable_reason`.
- `SessionStore` and literature-search `JobStore` now use SQLite persistence with sessions, messages, turns, search results, evidence items, jobs, job events, artifacts, and conversation-artifact links.
- Frontend sessions are backend-backed, restore messages, and persist active session selection through localStorage.
- Sidebar session rows now have a custom webpage right-click menu with rename, favorite, pin, tags, archive, and soft delete.
- Settings v1 exists as a platform-level TopBar workbench with General, Models, Agent, Research Agent, Retrieval, Memory, and Diagnostics.
- Settings ordinary values are stored in SQLite; effective runtime precedence is explicit payload > SQLite settings > environment variables > built-in defaults.
- API keys are handled through environment variables or encrypted secret storage, not plain settings rows.
- Named model profiles exist. Activating a profile mirrors provider/base URL/model settings into the active Models scope and makes the encrypted profile key available to LLM resolution.
- `backend/core/llm/client.py` provides an OpenAI-compatible provider-agnostic client for OpenAI/OpenAI-compatible/DeepSeek/Ollama-style calls.
- `backend/modules/literature_search/agent/loop.py` implements a tool-calling LLM loop with evidence citation audit.
- `backend/modules/literature_search/agent/tools.py` exposes quick/deep research tools to the LLM, including search, paper sections/chunks, evidence expand, pack, task/run, extract, compare, verify, and quality.
- `literature_search` Chat first tries the LLM agent path when Research Agent is available and Settings reports LLM enabled; otherwise it falls back to retrieval summary/mock behavior.
- Message rendering supports inline `[E#]` citation highlighting and a citation footer.
- A one-command local development launcher exists at `dev.sh`; it defaults memory DB to `./.runtime/platform_memory.sqlite`.
- CC Switch import is not yet implemented. Earlier inspection found a likely DB at `/Users/chenlintao/.cc-switch/cc-switch.db`; recommended import mode is backend read-only preview plus explicit import into model profiles, without exposing plaintext keys to frontend unless the user requests reveal.
- Full test/build baseline on 2026-06-26: backend tests passed (`32 passed`), frontend production build passed.
- Long-term capability planning now lives in `docs/capability-blocks/`. The accepted map has 12 blocks and explicitly adds canonical metadata schema, answer permission policy, read-only vs state-changing tool boundaries, and observability.
- The capability map now includes Block 12 for management/collaboration. This should remain a later platformization track until the single-user `literature_search` research loop is stable.
- Frontend interaction and visual QA now has a dedicated checklist at `docs/frontend-interaction-visual-bug-checklist.md`.
- As of 2026-06-30, the implementation has advanced beyond initial planning:
  - Block 0 Research Index identity and health dashboard are implemented.
  - Block 2 retrieval/evidence acquisition packet logic is implemented.
  - Block 3 grounding/answer-permission guardrails are implemented as an additive post-answer pass.
  - Block 4 tool specs, permission levels, structured errors, and persisted tool traces are implemented.
  - Block 5 Chat orchestration has expanded with role/mode policy, coverage-aware behavior, and fallback handling.
  - Block 6 research state has concrete SQLite tables and frontend panel support.
  - Block 7/10 workflow gallery/console and backend workflow engine are implemented, including the first available Idea Discovery path (`research-lit` + `idea-creator`).
- Current verified baseline on 2026-06-30: backend tests `167 passed`; frontend `npm run build` passes.

## 2026-07-03 Workflow Boundary Findings

- `docs/roadmap_flattening.md` already says Phase 2 skills are bounded registered skills and warns against automatic manuscript drafting, but it lacks a single workflow-profile layer that separates Chat, workflow selection, controller runtime, and skill wrappers.
- P2-M8 through P2-M13 closure docs consistently say each downstream capability is explicit-only and must not auto-advance from the previous terminal step.
- `backend/modules/research_agent_controller/plan_templates.py` uses explicit plan builder names for P2-M8 through P2-M13; comments/docstring should clarify these are literature-research-agent workflow profiles, not default chat behavior.
- `PlatformNativeFallbackController` only enters P2 downstream skills when the workspace plan text explicitly includes that skill name. The minimal chain stops after `build_minimal_topic_to_evidence_report`.
- `backend/modules/workflow/templates.py` exposes controlled research-controller templates in `list_templates()`. Legacy broad templates such as `full-pipeline` remain addressable by id for historical compatibility but are not part of the default new-run gallery.
- Ordinary `frontend/src/components/ChatPanel.jsx` and `backend/modules/literature_search/module.py` handle chat interaction, role/depth selection, and evidence-grounded answers; they do not invoke the research_agent_controller plan templates by default.
- P2-M14 manuscript scaffold needs clearer workflow-level wording: ordinary chat must not trigger `draft_manuscript_section`, and the manuscript workflow profile remains unavailable/contract-only at the workflow-profile boundary until explicit manuscript scaffold integration is accepted.

## 2026-07-07 Literature Search Product QA Rerun Findings

- New rerun report: `docs/literature_search_product_test_rerun_2026-07-07.md`.
- Previously critical startup/runtime issue is resolved in the current environment: `pc_plus` imports backend and `python-multipart` is available.
- Library status is now first-class at API level:
  - `library_count`, `library_indexed_count`, `library_year_coverage`, `library_journal_distribution`, and `library_recent_imports` use `intent_route + library_status` and return in about 0.4s.
  - `/api/corpus/quick-stats` returns authoritative corpus metadata: 147371 papers, 147372 article-index rows, years 2010-2026, top journal `ACS Applied Materials & Interfaces`.
- Attachment-only is fixed when the frontend protocol sends active `attachment_ids`: it routes to `attachment_only`, records `used_attachments`, avoids citation metadata, and labels the source as an uploaded attachment.
- Missing attachment questions now return a specific Chinese `attachment_missing` explanation.
- No-hit topic answer is semantically improved and says the local library did not find the topic without implying the corpus is empty; however the live research fallback still lacks structured `failure_code` metadata for the audit tab.
- Evidence curation works in current source code: a fresh backend on port 8010 accepted `/evidence-status`, updated `evidence_pool.status_counts`, and recorded `field=evidence_status` provenance. The existing port-8000 process was stale and did not expose the newest route until restart.
- Current unresolved UI/product issues:
  - Sidebar still shows `数据抽取 / 结构化任务`, contrary to the four-entry IA.
  - Literature Search at 390px width still overflows horizontally; right panel extends offscreen and textarea width can be 0.
  - Citation labels remain ambiguous: inline buttons render as bare numbers while evidence cards use ordinals plus real evidence IDs.
  - Plain-help live LLM route returns a good non-citation answer but does not emit `route=plain_help` metadata.
- Supplemental long-path rerun closed the previous unverified bucket:
  - English and Chinese LLM/materials-discovery research queries each took over 190s and hit three search timeouts.
  - English research answer still leaks process narration such as `I'll search...` / `Let me try...` into the persisted answer.
  - Attachment + literature path still takes about 194s; attachment summary works, but literature retrieval timed out and produced no evidence.
  - Adjacent negative topic coverage remains wrong: `火星土壤超导材料` returns adjacent Martian-soil evidence and `coverage.status=sufficient` even though the answer says no direct topic match.
  - Exact `large language models for materials discovery` query still times out through multiple rewrites.
  - Existing DB still has two old `turns.status='running'` rows without assistant messages, so abandoned-stream cleanup/recovery is still missing.

## 2026-07-07 Priority Repair Batch 1 Findings

- The extra primary sidebar entry was a UI exposure problem, not a missing feature dependency: removing the `数据抽取 / 结构化任务` button from `Sidebar.jsx` is enough to match the current Literature Search IA while preserving structured extraction code and APIs for later/internal use.
- The 390px textarea collapse had two layers:
  - `ResultsPanel` used an unconditional fixed `w-[380px]`, which caused the right workbench to extend offscreen.
  - The global sidebar stayed at `256px` on a `390px` viewport, leaving only `134px` for the whole workbench; after buttons, gaps, and padding, the textarea measured `0`.
- The effective narrow-screen fix is therefore both local and shell-level:
  - Literature Search stacks chat and right workbench with `flex-col lg:flex-row`.
  - Results panel uses `w-full lg:w-[380px]`.
  - Sidebar uses a `68px` icon rail below `md`.
  - Chat input uses `min-w-0` and a full-width input shell.
- Citation ambiguity came from using the same visual language for three different concepts:
  - inline first-appearance citation number;
  - right-panel evidence-card ordinal;
  - backend/agent evidence IDs.
- The UI now treats ordinals as display labels (`证据 1`) and true identifiers as explicit metadata (`证据ID：...`), reducing confusion without changing backend citation data.
- Browser verification at 390x844 after the repair measured `scrollWidth=390`, right workbench width `322`, textarea width `176`, no visible structured-extraction main entry, and visible `证据 1` labels.

## 2026-07-07 Priority Repair Batch 2 Findings

- The structured audit metadata gap had two backend causes:
  - `plain_help` / `plain_chat` were correctly short-circuiting retrieval, but they did not emit `intent_route`, so `chat_router` had nothing to persist as assistant route metadata.
  - Research fallback with zero candidate papers emitted `papers=[]` and a readable answer, but no `failure_explanation`, so the UI could not distinguish no-hit from empty corpus in the audit/papers tabs.
- `chat_router` already had the correct persistence hooks for `intent_route` and `failure_explanation`; the missing part was upstream event emission.
- Lightweight plain chat with LLM disabled previously returned an error for simple greetings. This conflicted with the product goal that ordinary questions should not be evidence-gated or model-gated into scary failures. It now falls back to deterministic ordinary-chat copy.
- Zero-candidate research fallback now checks quick corpus stats before choosing the failure code:
  - non-empty available corpus -> `library_not_empty_but_no_query_hit`;
  - explicitly unavailable/empty corpus -> `empty_or_unavailable_corpus`;
  - unknown stats -> `no_candidate_papers`.
- Existing full backend tests needed alignment in `test_tool_execution.py`: the correct invariant is still "do not construct ToolRegistry / do not enter AgentLoop", but the event sequence now includes `intent_route` and deterministic fallback text.

## 2026-07-07 Priority Repair Batch 3 Findings

- The long-path ~193-203s latency had a clear multiplicative retry cause:
  - the `search` tool had a 30s timeout and `max_retries=1`, so one model search request could cost about 60s;
  - the outer agent guard allowed up to 3 search calls per turn, so repeated model rewrites could naturally reach about 180s before synthesis.
- Fixing only SQL/FTS performance would not address the product failure mode. The first reliability fix is to remove the duplicated timeout retry and stop further searches after the first search timeout in a turn.
- `AgentLoop` now emits structured timeout metadata (`failure_explanation: tool_timeout_failed`) as soon as a search timeout is observed, giving the UI audit tab a stable explanation instead of relying on free-text answer wording.
- Process narration leakage was not caused by `chat_router` persistence: the router already clears accumulated tokens on `answer_reset`. The remaining leak came from final model content itself containing phrases such as `I'll search...` after failed tool attempts. The loop now sanitizes common English/Chinese process-narration prefixes before grounding/citation audit and before persistence.
- Adjacent-match coverage needed a query-shape distinction:
  - normal topic/review queries can use representative adjacent evidence;
  - direct existence queries (“有没有关于 X 的论文”, “papers about X”) must not call coverage `sufficient` unless all key topic terms are represented.
- The new coverage rule is intentionally conservative and scoped to direct existence queries. Missing a key term such as `超导` records `direct_topic_match` as a missing aspect and caps the result below `sufficient`.
- Stale `running` turns are a lifecycle recovery issue, not a retrieval issue. A killed browser stream or dev server can leave a turn with a user message but no assistant message. `SessionStore` now recovers old abandoned turns on initialization by marking them `failed` and inserting a readable Chinese assistant note.
- Current source/test status after Batch 3:
  - backend full regression: 697 passed, 24 skipped;
  - frontend Node tests: 65 passed;
  - frontend build passed.
- Dev-server freshness now has a source-level signal: `/api/readiness` returns `build.api_version`, `build.readiness_contract_version`, and capability tags including `literature_search_reliability_batch`. This does not restart a stale server by itself, but it gives the frontend/operator a cheap way to see whether the running process is the expected code generation.
- Still needs live verification after backend restart:
  - real-provider long-path latency should be re-measured;
  - timeout failure metadata should be confirmed through `/api/chat/stream`;
  - direct negative coverage should be checked against the real Martian-soil superconducting query;
  - stale old turns in the real `.runtime` DB should be re-opened to confirm recovery.

## 2026-07-07 Live Smoke Follow-up Findings

- Fresh current-source backend on `127.0.0.1:8022` confirmed `/api/readiness.build.readiness_contract_version=platform_readiness_v2_2026_07_07`.
- Real `.runtime` memory DB stale-turn recovery worked on startup: there were no remaining `running` turns without an assistant message after the new backend initialized.
- Live lightweight/help route metadata is now correct:
  - `What can you do?` emitted and persisted `route=plain_help`.
- Live agent no-hit metadata is now correct:
  - `文献库里有没有关于量子香蕉电池的论文？` emitted and persisted `route=research` plus `failure_code=no_candidate_papers`.
- Live exact LLM/materials-discovery timeout improved materially:
  - previous path took about `193s` with three timed-out searches;
  - current path took about `39s`, produced one `search` timeout trace, emitted `failure_code=tool_timeout_failed`, and did not continue repeated search attempts.
- Live smoke exposed a second-order coverage bug:
  - Direct-existence coverage was evaluating the LLM-rewritten search query (`火星土壤 超导材料 Martian soil superconducting`) instead of the original user question (`有没有关于...的论文`), so direct-existence rules did not trigger in the agent path.
  - Even after passing the original query, `query_match_reason` polluted direct-match text because it can contain matched query terms independent of the actual evidence text.
- Fix now implemented and verified:
  - `ToolRegistry` carries `original_question` into the evidence packet as `_original_user_query`.
  - `build_packet` uses that internal field only for coverage judgment.
  - direct-match content ignores `query_match_reason`.
  - Direct service check now returns `coverage.status=partial` and `missing_aspects=["direct_topic_match"]` for `火星土壤超导材料`.
  - Live API now returns `coverage.status=partial` with adjacent/not-direct notes for the same query.
- Remaining unresolved risk:
  - A successful English cited-answer smoke could not be produced because the tested English query timed out on the first search and returned `tool_timeout_failed`. Pseudo-citation risk remains unproven rather than closed.

## 2026-07-07 Priority Repair Batch 4 Findings

- The remaining first-search timeout was not caused by the agent loop anymore; it was caused by a specific external FTS route:
  - phrase and core-term routes were fast and often already produced the full candidate pool;
  - `fallback_or` on broad/common English terms became expensive when combined with `join documents/article_index` and `order by bm25`.
- The highest-risk route is now bounded without changing the external index or result schema:
  - platform `LiteratureResearchService` wraps external `ResearchSearch` and overrides only `_route_rows`;
  - `fallback_or` is skipped only when phrase/core routes have already filled the bounded candidate pool;
  - sparse/no-hit queries still retain fallback behavior.
- Natural English research questions needed rewrite normalization before search:
  - raw question text such as `What papers discuss ...?` included low-information terms that made phrase/core return zero rows and forced fallback;
  - rewrite now emits high-signal terms first while keeping the original question in the rewrite list for auditability.
- Real index checks now produce fast, usable packets for the previously blocking English cases:
  - `large language models for materials discovery` evidence acquisition returns in about `3.4s`;
  - `What papers discuss Martian soil simulants for building materials?` evidence acquisition returns in about `0.36s`;
  - both return candidates and `coverage=sufficient`.
- Current automated baseline after this batch:
  - backend full regression: 705 passed, 24 skipped;
  - frontend Node tests: 66 passed;
  - frontend build passed.
- Remaining follow-up:
  - A fresh live `/api/chat/stream` smoke was attempted against a current backend, but the configured model failed with `model 'llama3.1' not found` before any search tool call.
  - After the product-direction correction, this is now an expected blocked path rather than a fallback-to-summary path: research QA requires a working LLM.
  - Superseded by Batch 10: the active DeepSeek API profile was later confirmed ready and the successful cited English answer smoke completed with `citation.status=ok`.

## 2026-07-07 Priority Repair Batch 5 Findings

- Product decision clarified the boundary: Literature Search research QA is LLM-assisted and must not fabricate a deterministic local retrieval-summary answer when the model is unavailable.
- The previous fallback-summary wording was present in both backend behavior and Settings copy. It created the wrong product promise: users could think research answers are available without a configured model.
- Current behavior now distinguishes first-class deterministic features from LLM-required research QA:
  - library status routes remain deterministic and do not require LLM;
  - plain help/chat can still give lightweight non-research responses;
  - attachment-only summarization still needs LLM and reports a readable unavailable message when missing;
  - research QA blocks with `llm_required_for_research` or `llm_runtime_unavailable`.
- Live smoke with the stale `llama3.1` model config now returns in about `0.28s` with a Chinese model diagnostic, no local summary, no papers, and no search metadata.
- Settings readiness had one remaining semantic mismatch:
  - `provider=ollama` previously counted as ready whenever a chat model name was configured, because Ollama does not need an API key.
  - That was still a false positive for the LLM-required product direction: the current local Ollama service had no `llama3.1` model installed, so research QA would fail only at runtime.
- Readiness now checks Ollama `/api/tags` and returns `ollama_model_unavailable` when the configured model is absent. This turns the bad local model state into an upfront blocked diagnostic instead of a misleading “agent ready” state.
- Live readiness verification now returns `ready=false`, `mode=blocked`, and `fallback_mode=blocked_requires_llm` for the current `ollama/llama3.1` config.
- Current automated baseline after this correction:
  - backend full regression: 707 passed, 24 skipped;
  - frontend Node tests: 66 passed;
  - frontend build passed.

## 2026-07-07 Priority Repair Batch 6 Findings

- `LS-NEW-004` was a frontend session lifecycle recovery issue, not a backend session-store issue.
- Root cause:
  - `selectModule()` trusted the remembered/listed active session ID enough to call `selectSession()`;
  - if a detail endpoint for that session returned `session not found`, the error bubbled to the top-level `打开会话失败` app error;
  - the code did not remove the stale session ID from `activeSessionByModule` / `localStorage` or try another available session.
- The fix is scoped:
  - only errors whose message indicates `session not found` / `not found` / `未找到` trigger recovery;
  - other load failures still surface as user-visible errors;
  - recovery first tries the next listed session, then creates a fresh session when no other option remains.
- Automated evidence:
  - frontend store tests now cover both stale-session recovery branches;
  - full frontend Node suite now reports 68 passed;
  - backend regression remains 707 passed, 24 skipped.

## 2026-07-07 Priority Repair Batch 7 Findings

- `LS-P1-015` had a real view-model data-loss cause, not just a manual QA coverage gap.
- Root cause:
  - when `researchState.candidate_papers` existed, `buildPaperItems()` used that array as the sole paper source;
  - the candidate-papers array is good for session status and evidence counts, but it is intentionally compact and often lacks snippets/abstract/authors/venue from the latest retrieval result;
  - therefore the paper tab/detail could become less readable exactly after research-state curation became available.
- The view model now merges instead of choosing one source:
  - research-state papers remain the authoritative status/note/count source;
  - current retrieval papers enrich matching candidates with readable fields;
  - matching uses multiple stable identities, including `key`, `id`, `paper_id`, `paperId`, `doi`, and `article_id`.
- This keeps the product boundary clear: paper cards/details remain candidate-literature previews, not final evidence claims, but users can now inspect the useful snippet/metadata without opening another panel.
- Automated evidence:
  - `buildPaperItems enriches research state candidate papers with current retrieval snippets` covers the regression;
  - full frontend Node suite now reports 69 passed;
  - backend regression remains 707 passed, 24 skipped.

## 2026-07-07 Priority Repair Batch 8 Findings

- The remaining English pseudo-citation issue cannot be fully closed without a successful real-provider cited-answer smoke, but its deterministic audit floor can be proven independently.
- Added a controlled English successful-answer regression:
  - the search tool returns real evidence `E1`;
  - the fake English LLM answers with fabricated `[E99]`;
  - `AgentLoop` emits a warning citation event with `audit_status=unverified`, `missing_ids=["E99"]`, and `used_evidence=[]`.
- This proves that even when the answer is otherwise a successful English synthesis path, a fake evidence id cannot silently become a UI evidence card.
- Added a controlled attachment + literature regression for the new product semantics:
  - parsed attachments are present;
  - user asks to summarize attachment and combine literature;
  - with LLM disabled, the turn blocks as `llm_required_for_research` and does not call local retrieval/search fallback.
- Current automated baseline after adding these risk tests:
  - backend full regression: 709 passed, 24 skipped;
  - frontend Node tests: 69 passed;
  - frontend build passed.
- Remaining proof gap:
  - a successful real-provider cited English answer and attachment+literature combined run still require a configured available LLM.

## 2026-07-07 Priority Repair Batch 9 Findings

- Re-audit showed that `LS-P1-005` was still listed as partially resolved because the report text mixed two different concerns:
  - retrieval/search latency for broad English queries;
  - successful end-to-end answer smoke with a working LLM.
- Current evidence supports closing the retrieval-latency part:
  - `large language models for materials discovery` real-index evidence acquisition completes in `3.269s` with 8 results and `coverage=sufficient`;
  - `What papers discuss Martian soil simulants for building materials?` completes in `0.341s` with 8 results and `coverage=sufficient`.
- At the time of Batch 9, settings readiness appeared to be an external-state blocker for successful answer smoke:
  - active model is `ollama/llama3.1`;
  - readiness reports `ready=false` with `ollama_model_unavailable`;
  - per product direction, research QA must block rather than generate a local retrieval-summary substitute.
- Superseded by Batch 10: the blocker was active-profile precedence drift, not absence of an API model. After active profile precedence was fixed, DeepSeek live smokes completed.

## 2026-07-07 Priority Repair Batch 10 Findings

- The prior "Ollama unavailable" diagnosis was a configuration-precedence bug, not the intended product state.
  - An active DeepSeek API profile existed and had an API key.
  - Stale `settings.models` still contained `provider=ollama` and `chat_model=llama3.1`.
  - Readiness and runtime settings were reading the stale model fields in some paths, which incorrectly made an API-configured product look blocked by a missing local model.
- Settings now treat the active model profile as the runtime authority:
  - `settings_store.model_config()` uses the active profile provider/model/base URL;
  - readiness uses that effective model config;
  - hydrated `/api/settings` and `/api/settings/effective` show profile-derived model fields and source.
- Real-provider smokes now prove the LLM/API main path:
  - DeepSeek readiness is `ready=true`, `mode=agent`, `api_key_source=profile`;
  - English research QA produced a cited answer with real evidence IDs and `citation.status=ok`;
  - attachment + literature combined QA uses parsed attachments as session context while keeping formal literature evidence in `[E#]` citations.
- The live combined path exposed two answer-quality boundary issues:
  - `attachment_context` was only emitted by attachment-only routes, so research turns with active attachments had no assistant metadata for UI audit.
  - DeepSeek sometimes prefaced final answers with process narration such as "我已经收集了充分的证据 / 让我整合..." even after tool narration reset.
- The current source fixes both at deterministic boundaries:
  - `chat_router` emits/persists `attachment_context` whenever parsed active attachments are included in the turn;
  - `AgentLoop` strips common English/Chinese final-answer process prefaces before citation audit/persistence;
  - `AgentLoop` adds a source marker when attachment context is loaded and the model omitted `来自上传附件《...》`.
- Remaining non-blocking observation:
  - combined attachment + literature live answer generation remains variable (`35.7s-126.67s` observed), but the latest runs returned correct route, attachment metadata, candidate papers, and citation status.
- Current automated baseline:
  - backend full regression: 713 passed, 24 skipped;
  - frontend Node tests: 69 passed;
  - frontend build passed with the existing Vite chunk-size warning.
