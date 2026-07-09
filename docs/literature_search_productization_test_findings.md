# Literature Search Productization Test Findings

Test date: 2026-07-07
Tester: Codex
Scope: Literature Search productization behavior, with emphasis on intent routing, library status queries, zero-result explanations, UI state consistency, Chinese output, and right-side workspace semantics.

## Productization Baseline

Literature Search should behave as a research-facing evidence workbench, not a single generic retrieval chat. The accepted baseline is:

1. Library status queries are first-class Literature Search capabilities.
2. Intent routing uses deterministic lightweight routes before LLM/retrieval fallback.
3. Chinese prompts should receive Chinese answers by default.
4. Zero-result and failure explanations are first-class behavior.
5. Right-side tabs have clear boundaries: evidence, papers, audit.
6. The main answer area is result-first.
7. Attachments are session-scoped material, not library evidence.
8. UI execution state must match actual backend execution.
9. Simple questions should stay lightweight; research questions may enter the full evidence chain.
10. Failures should include actionable next steps.

## Test Environment

- Workspace: `/Users/chenlintao/literature-agent-platform`
- Frontend under test: Vite dev server on `http://127.0.0.1:5173` confirmed by `lsof`.
- Backend under test:
  - Initial expected backend `http://127.0.0.1:8000` was not running.
  - Starting with the documented/default `pc_plus` Python failed because `python-multipart` is missing.
  - Continued behavioral testing with `/opt/anaconda3/bin/python3`, where backend startup succeeded on `http://127.0.0.1:8000`.
- Existing app state: user had manually tested Literature Search and observed a simple library-count question entering the retrieval/evidence path.

## Severity Definitions

- P0: Product-blocking or misleading behavior, such as wrong route, false implication that the library is empty, fabricated citations, or raw/internal output shown to users.
- P1: Major product quality issue, such as unclear zero-result explanations, inconsistent UI state, poor audit visibility, or language mismatch.
- P2: Polish or ergonomics issue, such as wording, density, empty-state quality, or secondary interaction clarity.

## Executive Summary

Tested groups: environment, A plain chat/identity, B library status/metadata, C topic coverage, D research QA, E zero-result/topic coverage, F citation/evidence UI, G session attachments, H/I right-side workbench UI, and J language/failure wording.

Current status:

- Passing baseline:
  - Plain greeting `你好` stays lightweight and does not trigger retrieval.
  - Chinese research query can retrieve local evidence and produce a grounded answer.
- Product-blocking findings:
  - The documented/default backend runtime cannot start because `python-multipart` is missing.
  - Library-count questions are misrouted into retrieval and can falsely imply the corpus has no usable records.
  - At least one research answer produced nonstandard pseudo-citations and failed citation audit despite having available evidence.
  - Session attachments can be uploaded and listed, but attachment-only answers are blocked by the literature evidence gate instead of answering from the uploaded material.
  - A previous attachment+retrieval turn remained `running` with no assistant message even after search results were recorded.
- Major productization findings:
  - Corpus status endpoint is too slow for chat-time status questions.
  - Right-side audit/papers tabs do not explain route decisions, actual query, corpus non-empty status, or zero-result cause.
  - Quick research QA can take close to 90 seconds and includes recovered tool timeouts without a useful user-facing summary.
  - Negative topic coverage is not represented; adjacent lexical matches can be labeled as `sufficient`.
  - Library metadata questions such as indexed count, recent imports, year coverage, and journal distribution are answered via ad hoc retrieval samples instead of metadata.
  - English plain capability questions can be corrupted by the citation gate into a Chinese "evidence insufficient" answer even when no retrieval should be required.
  - Attachment+literature turns can complete, but observed latency was about 180 seconds and citation audit was `off`.
  - The UI still exposes an extra `数据抽取` main navigation item, which violates the agreed four-entry IA.
  - Evidence/detail UI is partially usable, but citation labels, evidence ids, paper snippets, and audit details are not yet product-grade.

Recommended repair order:

1. Fix startup/runtime dependency (`python-multipart`) so the product can reliably launch.
2. Add deterministic library-status routing and a lightweight corpus stats path.
3. Fix zero-result templates so retrieval no-hit, evidence no-hit, empty corpus, and unsupported negative answers are distinct.
4. Strengthen citation output guard so nonstandard pseudo-citations cannot be accepted as grounded answers.
5. Upgrade audit/papers tab payloads to expose intent, route, query, corpus status, hit/evidence counts, and failure layer.
6. Revisit quick-mode latency and tool expansion policy.
7. Add a dedicated no-hit/topic-coverage response mode so "库里有没有..." questions do not use the generic evidence-insufficient template.
8. Fix attachment answer routing so uploaded session material is a valid answer source without being mixed into formal literature evidence.
9. Tighten right-side UI semantics: citation labels, evidence ids, audit route details, and paper detail interactions.

## Test Run Log

| ID | Group | Input | Expected Intent | Actual Behavior | Status | Severity | Issue IDs |
|---|---|---|---|---|---|---|---|
| ENV-1 | Environment | Start backend with `/opt/anaconda3/envs/pc_plus/bin/python -m uvicorn main:app` | Backend starts | Startup fails at import time: FastAPI `File(...)` route requires `python-multipart`; package missing in `pc_plus` | Fail | P0 | LS-P0-001 |
| ENV-2 | Environment | `GET /api/corpus/dashboard` | Fast enough corpus status for UI/status questions | Request took more than 40 seconds before output became available; eventually returned corpus status | Partial | P1 | LS-P1-001 |
| A1 | Plain chat | `你好` | Plain chat | API returned a direct Chinese greeting; no retrieval steps | Pass | - | - |
| A2 | Identity | `你是谁？` | Assistant identity / capability explanation | API returned Chinese answer and no retrieval steps, but wording says "普通对话助手" and under-describes product capabilities | Partial | P2 | LS-P2-001 |
| B1 | Library status | `当前文献库中一共有多少文献？` | Library status query / corpus stats | Misrouted into retrieval; searched `*`; returned 0 papers/evidence; answer implied no usable library records despite corpus having 147371 papers | Fail | P0 | LS-P0-002, LS-P0-003 |
| B1-UI-Audit | Library status UI audit | Existing UI session with same input | Audit should explain route and zero-result cause | Audit tab only says citation check / evidence coverage / retrieval strategy; strategy detail says "未提供"; no explanation that this was misrouted or that corpus is non-empty | Fail | P1 | LS-P1-002 |
| B1-UI-Papers | Library status papers tab | Existing UI session with same input | Papers tab should distinguish corpus non-empty from this-turn no-hit | Papers tab says "暂无检索文献" only; does not show corpus has 147371 papers or explain no-hit vs empty library | Fail | P1 | LS-P1-003 |
| D1-EN | Research QA | `What are the applications of large language models in materials discovery?` | Research retrieval + evidence-grounded answer | FTS found 9 papers / 15 evidence after 15.8s, but final citation audit was `uncited`; persisted answer contains pseudo/nonstandard evidence strings and right evidence would be empty | Fail | P0/P1 | LS-P0-004, LS-P1-004 |
| D1-ZH | Research QA | `大语言模型在材料发现中的应用有哪些？` | Chinese research answer with evidence | FTS found 10 papers / 15 evidence after 17.2s; answer eventually persisted with citations, but total latency was about 89s and two `paper_chunks` calls timed out | Partial | P1 | LS-P1-005, LS-P1-006 |
| E1 | Topic no-specific-match | `文献库里有没有关于火星土壤超导材料的论文？` | Topic coverage / likely negative answer | FTS found 8 lexically related papers and 14 evidence; coverage marked `sufficient`; answer says no dedicated papers, with evidence mostly proving adjacent/irrelevant matches | Partial | P1 | LS-P1-007 |

## Test Run Log - Second Batch

| ID | Group | Input | Expected Intent | Actual Behavior | Status | Severity | Issue IDs |
|---|---|---|---|---|---|---|---|
| B2 | Library status | `现在有多少篇文献已经完成索引？` | Library status / indexed count | Misrouted into retrieval query `文献总数 索引数量`; 0 papers/evidence; returned generic evidence-insufficient answer | Fail | P0 | LS-P0-005 |
| B3 | Library metadata | `最近导入了哪些文献？` | Recent indexed/imported papers | Misrouted into retrieval query `最近导入 新文献`; 0 papers/evidence; returned generic evidence-insufficient answer | Fail | P0 | LS-P0-005 |
| B4 | Library metadata | `当前文献库覆盖哪些年份？` | Metadata year distribution | Used retrieval samples and inferred 2019-2023; true SQLite baseline is 2010-2026 | Fail | P0 | LS-P0-006 |
| B5 | Library metadata | `当前文献库主要包含哪些期刊？` | Metadata journal distribution | Used retrieval samples and returned partial journal list; missed true top-journal counts | Fail | P1 | LS-P1-008 |
| C1 | Topic coverage | `文献库里有没有关于 large language models for materials discovery 的文献？` | Fast topic coverage with representative papers | First exact search timed out after 30s; second query succeeded with 8 papers/15 evidence; final answer useful but took 75s | Partial | P1 | LS-P1-009 |
| C2 | Topic coverage | `文献库里有没有关于大语言模型辅助材料发现的论文？` | Topic coverage | Worked: 8 papers/15 evidence in 10s, Chinese answer with valid citations | Pass | - | - |
| C3 | Topic no-hit | `文献库里有没有关于量子香蕉电池的论文？` | No-hit explanation distinguishing corpus non-empty | 0 papers/evidence; returned generic evidence-insufficient template, not a topic-coverage no-hit explanation | Fail | P1 | LS-P1-010 |
| J2 | English capability | `What can you do?` | Plain capability answer | No retrieval steps, but final persisted answer was generic Chinese evidence-insufficient template | Fail | P0 | LS-P0-007 |
| J3 | Mixed-language research | `请总结 LLM for materials discovery 的主要方向` | Chinese research summary | Answer was Chinese and evidence-grounded, but took 103s, ran 3 searches and had an `evidence_expand` timeout | Partial | P1 | LS-P1-005, LS-P1-006 |

## Test Run Log - Third Batch

| ID | Group | Input | Expected Intent | Actual Behavior | Status | Severity | Issue IDs |
|---|---|---|---|---|---|---|---|
| G1 | Attachment txt-only | Upload `material_note.txt`, ask `请总结我上传的附件，不需要检索外部文献。` | Answer from session attachment only; do not require literature evidence | Attachment was parsed and recorded in user metadata, but final answer said no local literature evidence and did not summarize the attachment | Fail | P0 | LS-P0-008 |
| G2 | Attachment PDF upload | Upload a valid simple `valid_note.pdf` | PDF parsed into session-scoped attachment | Valid PDF parsed successfully with preview `[PDF 第 1 页] ...` | Pass | - | - |
| G2b | Attachment PDF answer | Ask `请总结这个 PDF 附件，不需要检索外部文献。` | Answer from parsed PDF attachment | Final answer again used generic no-literature-evidence template and ignored parsed PDF content | Fail | P0 | LS-P0-008 |
| G3 | Attachment + literature | Upload txt, ask `请先总结附件内容，再结合文献库补充相关研究。` | Stream progress, summarize attachment, retrieve literature, produce cited answer | Controlled rerun completed but took ~180s; previous run `s_084a644a517e` remained `running` with search results recorded but no assistant message | Partial | P1 | LS-P1-011, LS-P1-012 |
| G4 | Attachment delete | Upload txt, delete it, then ask with deleted attachment id | Deleted attachment should not enter context | User metadata had no attachment after deletion; answer still used generic no-evidence template, which is expected for missing attachment but not very helpful | Partial | P2 | LS-P2-002 |
| G5 | Unsupported attachment | Upload `bad.md` | Reject unsupported type with Chinese error | Returned 400: `仅支持上传 .txt 或 .pdf 文件。` | Pass | - | - |
| G6 | Attachment count limit | Upload 6 txt files in one session | First 5 accepted, 6th rejected with Chinese error | First 5 parsed; 6th returned `当前会话最多保留 5 个附件，请先移除旧附件。` | Pass | - | - |
| F1 | Citation audit failure | Existing session `s_4e7e7b68b2b8` | Invalid/nonstandard citations should block grounded answer or be clearly flagged | Metadata had `audit_status=uncited`, `available_count=15`, but persisted answer looked evidence-like | Fail | P0 | LS-P0-004 |
| F2 | Successful citation UI | Existing session `s_76c901ca0fa9` | Inline citations and right evidence should be understandable | Main answer rendered citation buttons as bare numbers (`1`, `23`, etc.); evidence tab maps `E1/E2` to true ids like `E5438946`, creating two ID layers | Partial | P1 | LS-P1-013 |
| H1 | Main navigation | Open app sidebar | Four main entries only: Home, Literature Search, Research Workflows, Settings | Sidebar also shows `数据抽取 / 结构化任务` | Fail | P1 | LS-P1-014 |
| H2 | Zero-result right tabs | Library-count failed session | Evidence/Papers/Audit tabs explain misroute, corpus non-empty, query, failure layer | Evidence says no used evidence; Papers says no retrieved papers; Audit detail says `检索方式 未提供 / 查询扩展 未提供` | Fail | P1 | LS-P1-002, LS-P1-003 |
| H3 | Evidence detail overlay | Successful evidence session, click evidence card | Center pane shows readable evidence details | Center switched to `证据详情` and showed title, snippet, evidence id, section, source path, DOI | Pass | - | - |
| H4 | Paper tab / detail | Successful evidence session, open paper tab and click paper card | Center pane shows readable paper detail | Paper tab shows noisy snippets with multiple paper titles concatenated; clicking card did not visibly switch to a clear `文献详情` view | Partial | P1 | LS-P1-015 |
| H5 | Mobile/narrow layout | View Literature Search at 390x844 | Layout stacks or provides usable horizontal navigation/input | Main content and right panel overflow horizontally; mode buttons become narrow vertical blocks; textarea width becomes 0 | Fail | P1 | LS-P1-017 |
| J4 | Chinese default / failure wording | Attachment errors and zero-result cases | User-facing errors in Chinese, but semantically specific | Upload boundary errors are Chinese; no-hit and attachment ignored cases use generic literature-evidence template that misstates the failure layer | Partial | P1 | LS-P1-010, LS-P1-016 |

## Issues

### LS-P0-001: Default backend runtime cannot start after attachment route addition

- Severity: P0
- Area: startup / deployment / attachment dependency
- Reproduction:
  1. Run backend with `/opt/anaconda3/envs/pc_plus/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000`.
  2. Import reaches `backend/api/modules_router.py` attachment upload route.
- Actual:
  - Backend exits before serving requests.
  - Error: `Form data requires "python-multipart" to be installed.`
- Expected:
  - `dev.sh` default backend runtime should start cleanly.
- Product impact:
  - User can see a frontend-only app if Vite is already running, but backend API is unavailable.
  - This makes Literature Search appear broken before any product-level behavior can be evaluated.
- Likely root cause:
  - Attachment upload introduced `UploadFile = File(...)` but the default runtime environment does not include `python-multipart`.
- Suggested follow-up:
  - Add `python-multipart` to the project dependency/runtime setup or change the documented backend Python environment.
  - Add a startup/import smoke test under the same Python environment used by `dev.sh`.

### LS-P1-001: Corpus dashboard is too slow for first-class library status queries

- Severity: P1
- Area: corpus status / library state UX
- Reproduction:
  1. With backend running, call `GET /api/corpus/dashboard`.
  2. Observe response time.
- Actual:
  - Request did not return within the initial 40 second observation window.
  - It eventually returned corpus status after waiting longer.
- Expected:
  - Library status questions such as "当前文献库有多少文献？" need a lightweight, near-instant status path.
- Product impact:
  - If chat relies on the heavy dashboard endpoint, simple corpus-count questions will feel stuck or be misrouted to retrieval.
  - A slow status endpoint discourages using library status as a first-class route.
- Baseline returned by endpoint:
  - `coverage.papers`: 147371
  - `coverage.sections`: 2911107
  - `coverage.chunks`: 4979646
  - `vector.built`: false
  - `warnings`: `vector_not_built`
- Suggested follow-up:
  - Add a lightweight corpus stats endpoint or cache fast counts.
  - Use lightweight stats for chat/library-status intent, not the full dashboard payload.

### LS-P0-002: Library count question is misrouted into retrieval/evidence QA

- Severity: P0
- Area: intent routing / library status
- Reproduction:
  1. Create a clean Literature Search session.
  2. Ask `当前文献库中一共有多少文献？`.
- Expected:
  - Intent: library status query.
  - Backend path: corpus/library stats.
  - Answer: direct paper count, currently known baseline `147371` papers from corpus dashboard.
  - UI: a light "读取文献库统计" state, not evidence retrieval.
- Actual:
  - The agent emitted retrieval steps.
  - It searched local library with query `*`.
  - It returned 0 papers and 0 evidence.
  - Coverage was `none`.
- Product impact:
  - A simple corpus-count question is treated as an evidence question.
  - This is exactly the class of bug shown in the user's screenshot.
- Likely root cause:
  - No deterministic lightweight route for corpus/library status queries before the generic agent/retrieval route.

### LS-P0-003: Zero-result answer falsely implies the library may have no usable records

- Severity: P0
- Area: zero-result explanation / answer safety
- Reproduction:
  - Same as LS-P0-002.
- Actual answer excerpt:
  - `当前本地文献库中没有可用的文献记录（检索返回 0 篇论文、0 条证据）`
  - `这可能是因为文献索引尚未构建完成，或者当前库中确实还没有导入任何文献。`
- Contradicting baseline:
  - Corpus dashboard returned `147371` papers, `2911107` sections, and `4979646` chunks.
- Expected:
  - If retrieval returns 0, say "本轮检索没有命中/没有证据", not "文献库没有文献记录".
  - For this intent, do not run retrieval at all; answer from corpus stats.
- Product impact:
  - Users may incorrectly believe their literature library is empty or unusable.
- Likely root cause:
  - The fallback zero-result template conflates retrieval no-hit, evidence no-hit, and empty corpus.

### LS-P0-005: Library metadata questions have no direct metadata route

- Severity: P0
- Area: intent routing / library metadata
- Reproduction:
  - Ask `现在有多少篇文献已经完成索引？`.
  - Ask `最近导入了哪些文献？`.
- Actual:
  - Indexed-count query searched `文献总数 索引数量`, returned 0 papers/evidence, and emitted the generic evidence-insufficient answer.
  - Recent-import query searched `最近导入 新文献`, returned 0 papers/evidence, and emitted the same template.
- Expected:
  - Indexed count should use corpus/index metadata.
  - Recent imports should query `papers.indexed_at` or equivalent metadata.
- Authoritative SQLite baseline:
  - `article_index`: 147372
  - `papers`: 147371
  - latest indexed examples include `10.1002/adma.201904824` and `10.1002/adma.201906357`, both indexed at `2026-07-05T23:11:32`.
- Product impact:
  - The entire library-status/metadata family is not first-class yet.

### LS-P0-006: Year coverage answer is factually wrong because it samples retrieval results

- Severity: P0
- Area: library metadata / factual correctness
- Reproduction:
  - Ask `当前文献库覆盖哪些年份？`.
- Actual:
  - The agent searched broad/random terms, including `machine learning`.
  - It answered that the confirmable year range is `2019 年 ~ 2023 年`.
- Authoritative SQLite baseline:
  - Valid four-digit year range: 2010-2026.
  - Top year counts:
    - 2025: 26439
    - 2024: 19405
    - 2023: 9806
    - 2026: 6896
    - 2022: 6240
- Expected:
  - Use metadata distribution, not evidence retrieval samples.
- Product impact:
  - This is not just a UX issue; it returns a wrong corpus fact.

### LS-P1-002: Audit tab does not explain route decisions or zero-result cause

- Severity: P1
- Area: right-side audit workbench
- Reproduction:
  1. Open the UI session containing `当前文献库中一共有多少文献`.
  2. Click the `审计` tab and open `检索策略`.
- Actual:
  - Audit shows 3 generic items: citation check, evidence coverage, retrieval strategy.
  - Retrieval strategy detail says:
    - `检索方式：未提供`
    - `查询扩展：未提供`
    - `向量检索说明：无`
  - It does not show detected intent, route, actual query `*`, corpus non-empty baseline, or why 0 occurred.
- Expected:
  - Audit should show `intent = library_status_query` or explain misclassification.
  - It should distinguish empty corpus vs no candidate papers vs no evidence.

### LS-P1-003: Papers tab does not distinguish empty corpus from this-turn no-hit

- Severity: P1
- Area: right-side papers tab / zero-result UX
- Reproduction:
  - Open `文献` tab for the same B1 session.
- Actual:
  - Shows only `暂无检索文献`.
- Expected:
  - For library status questions, show corpus stats or a status card.
  - For retrieval no-hit, explicitly say the corpus is non-empty but this query had no matched papers.

### LS-P1-008: Journal coverage answer is sample-based and omits authoritative counts

- Severity: P1
- Area: library metadata / journal distribution
- Reproduction:
  - Ask `当前文献库主要包含哪些期刊？`.
- Actual:
  - The agent searched `期刊 journal name` and `journal name publisher`.
  - It returned a partial list from retrieved samples, then warned it was not a complete journal list.
- Authoritative SQLite baseline top journals:
  - `ACS Applied Materials & Interfaces`: 29197
  - `Journal of Materials Chemistry A`: 20616
  - `Journal of the American Chemical Society`: 18930
  - `Small`: 16886
  - `Advanced Science`: 13397
  - `ACS Nano`: 13032
  - `Advanced Functional Materials`: 11296
  - `Advanced Materials`: 10511
- Expected:
  - Return top journals with counts from metadata.
- Product impact:
  - The answer is caveated but still fails the "library status as first-class ability" goal.

### LS-P0-004: Research answer can produce nonstandard pseudo-citations that fail citation audit

- Severity: P0
- Area: citation grounding / final answer validation
- Reproduction:
  1. Ask `What are the applications of large language models in materials discovery?`.
  2. Inspect persisted assistant message and citation metadata.
- Actual:
  - Retrieval found 9 papers and 15 evidence.
  - Persisted answer contains nonstandard pseudo-citation text such as `[E4431795相关论文内容]`.
  - Citation metadata reports `audit_status: uncited`, `used_evidence: []`, `cited_ids: []`, while `available_count: 15`.
- Expected:
  - Answer should cite exact allowed evidence ids like `[E5438956]`.
  - If citations are invalid or uncited, the final user-facing answer should not be treated as grounded.
- Product impact:
  - The main answer looks evidence-like but the right-side evidence tab would be empty.
  - This breaks user trust in the evidence workbench.

### LS-P1-004: English/internal process text leaks into user-visible answer flow

- Severity: P1
- Area: language / process narration
- Reproduction:
  - Same as D1-EN.
- Actual:
  - Initial streamed tokens and step labels include English process narration: `I'll search for literature...`, `I now have comprehensive information...`.
  - Persisted answer begins with English process text before Chinese answer content.
- Expected:
  - UI/system process should use Chinese by default in this product.
  - Process narration should not be persisted as part of the final answer.

### LS-P0-007: Plain English capability question is corrupted by citation/grounding fallback

- Severity: P0
- Area: plain chat / language / citation gate
- Reproduction:
  - Ask `What can you do?`.
- Actual:
  - Stream had no retrieval steps.
  - Persisted answer was the Chinese generic evidence-insufficient template.
  - Citation metadata existed with 0 available evidence.
- Expected:
  - This should be a plain capability answer and should not pass through evidence-grounding as a factual literature answer.
- Product impact:
  - Ordinary onboarding/help questions can fail in a confusing way.
- Likely root cause:
  - Plain-chat response may be overwritten or gated by a citation fallback path even when no retrieval was requested.

### LS-P0-008: Session attachments are parsed but not treated as answerable context

- Severity: P0
- Area: session attachments / answer routing / grounding boundary
- Reproduction:
  1. Upload a parsed `.txt` attachment to a Literature Search session.
  2. Ask `请总结我上传的附件，不需要检索外部文献。`.
  3. Repeat with a valid parsed PDF attachment and ask `请总结这个 PDF 附件，不需要检索外部文献。`.
- Actual:
  - Attachment metadata is saved on the user message.
  - `session_attachments` contains parsed text/preview.
  - Final assistant answer says no local literature evidence was found and refuses to answer from the attachment.
- Expected:
  - Session attachments are user-provided context and should be answerable without formal literature evidence.
  - The answer should clearly label attachment-derived statements, e.g. `来自上传附件《...》`.
  - Attachment content must not be mixed into formal `[E#]` literature evidence.
- Product impact:
  - The newly added attachment feature appears broken for its primary use case.
- Likely root cause:
  - Parsed attachments are injected into context, but the final answer/grounding path still treats "no literature evidence" as not answerable.

### LS-P1-005: Research QA latency is high for quick mode

- Severity: P1
- Area: latency / quick mode UX
- Reproduction:
  - Ask `大语言模型在材料发现中的应用有哪些？`.
- Actual timing:
  - Search results arrived at ~17.2s.
  - Final done arrived at ~89.4s.
- Expected:
  - Quick mode should either answer from selected evidence after the first search or present a clear progress/continuation state.
  - Long-running paper expansion should be reserved for deep mode or made visibly cancellable.

### LS-P1-006: Tool timeouts are user-visible process risks but not summarized productively

- Severity: P1
- Area: tool execution / audit / recovery
- Reproduction:
  - Same as D1-ZH.
- Actual:
  - Two `paper_chunks` calls timed out after 20s each.
  - The stream then recovered by calling `paper_sections`.
  - Final answer was produced, but the product-level summary does not clearly explain that partial tool failures occurred and were recovered.
- Expected:
  - Audit should summarize partial tool failures in Chinese and distinguish recovered tool timeouts from answer failure.

### LS-P1-011: Attachment plus literature path has product-breaking latency

- Severity: P1
- Area: attachment + retrieval orchestration / streaming UX
- Reproduction:
  1. Upload a short txt attachment about perovskite solar cell stability.
  2. Ask `请先总结附件内容，再结合文献库补充相关研究。`.
- Actual:
  - Controlled rerun completed and produced a useful answer with attachment summary plus literature evidence.
  - End-to-end runtime was about 180 seconds.
  - During the long run, the user experience appears stalled unless they watch detailed streaming tokens.
- Expected:
  - The UI should show a clear staged process: reading attachment, searching library, selecting evidence, composing answer.
  - Quick mode should not spend three minutes unless the user explicitly chooses deep analysis.
- Product impact:
  - A core "attachment + literature" use case feels hung.

### LS-P1-012: Interrupted or abandoned streams can leave turns stuck in `running`

- Severity: P1
- Area: session state / stream lifecycle
- Reproduction:
  - Session `s_084a644a517e`, query `请先总结附件内容，再结合文献库补充相关研究。`.
- Actual:
  - User message and attachment metadata exist.
  - Search results were recorded, including one later successful English query with 5 papers / 10 evidence.
  - Turn status remains `running`, `assistant_message_id` is null, and no assistant message appears.
- Expected:
  - If a stream is interrupted, the turn should become failed/interrupted with a readable state, or resume/finalize when backend work completes.
- Product impact:
  - UI can show a task as indefinitely running even though backend partial artifacts exist.

### LS-P1-007: Topic coverage negative answers need a distinct "related but not directly matching" state

- Severity: P1
- Area: topic coverage / zero-result semantics / retrieval evaluation
- Reproduction:
  - Ask `文献库里有没有关于火星土壤超导材料的论文？`.
- Actual:
  - FTS query `火星土壤 超导材料 Martian soil superconducting`.
  - Search found 8 candidate papers and 14 evidence.
  - Coverage was marked `sufficient`.
  - Answer concluded the local library has no dedicated papers about Martian-soil superconducting materials, but cited adjacent evidence about Martian soil, construction materials, perchlorate chemistry, and superconducting detectors in references.
- Expected:
  - This should not be simply "sufficient" coverage.
  - Product state should distinguish:
    - exact/direct topic match
    - adjacent lexical matches
    - negative answer supported by absence/direct mismatch
    - no-hit
- Product impact:
  - Users may see "证据较充分" and assume the answer is strongly supported, when the actual support is mostly indirect mismatch evidence.
- Suggested follow-up:
  - Add a topic-coverage status such as `related_but_no_direct_match` or `negative_coverage`.
  - Audit should show why matched papers are adjacent rather than directly answering the requested topic.

### LS-P1-009: Topic coverage can spend 30s on a timed-out exact query before succeeding

- Severity: P1
- Area: topic coverage / query planning / latency
- Reproduction:
  - Ask `文献库里有没有关于 large language models for materials discovery 的文献？`.
- Actual:
  - First search `large language models for materials discovery` timed out after 30s.
  - Second search `large language models materials discovery` succeeded.
  - Final answer took ~75s.
- Expected:
  - Topic coverage should use robust query rewriting and avoid waiting the full timeout for an over-constrained exact query when a simpler query can succeed.

### LS-P1-010: No-hit topic coverage uses generic evidence-insufficient template

- Severity: P1
- Area: zero-result explanation / topic coverage
- Reproduction:
  - Ask `文献库里有没有关于量子香蕉电池的论文？`.
- Actual:
  - Query returned 0 papers/evidence.
  - Answer used generic template: `本地文献库在本轮检索中没有返回可用于支撑结论的证据...`
- Expected:
  - For `库里有没有...` topic coverage, answer should say:
    - 当前文献库非空；
    - 本轮未命中该主题；
    - 不代表现实中不存在；
    - actual query and suggested alternative terms.

### LS-P1-013: Citation labels in UI are ambiguous and split across two ID systems

- Severity: P1
- Area: citation UI / evidence tab
- Reproduction:
  - Open successful session `s_76c901ca0fa9`.
- Actual:
  - Main answer renders citation controls as bare numbers such as `1`, `23`, `45`.
  - Right evidence tab labels cards as `E1`, `E2`, etc., while also showing true evidence ids such as `E5438946`.
- Expected:
  - Inline citations, evidence-card labels, and true evidence ids should be clearly mapped.
  - The user should not have to infer whether `E1` is a UI ordinal or a real evidence id.
- Product impact:
  - The evidence workbench is harder to trust and audit.

### LS-P1-014: Main sidebar still exposes an extra `数据抽取` entry

- Severity: P1
- Area: information architecture / navigation
- Reproduction:
  - Open the app sidebar.
- Actual:
  - Sidebar entries: 首页, 文献检索, 研究工作流, 数据抽取, 设置.
- Expected:
  - Agreed product IA for this phase: Home / Literature Search / Research Workflows / Settings.
- Product impact:
  - The cleaned controlled architecture is diluted by an extra main entry not covered by the current productization scope.

### LS-P1-015: Paper tab snippets and detail interaction are not product-grade

- Severity: P1
- Area: paper results UI / detail overlay
- Reproduction:
  1. Open successful session `s_76c901ca0fa9`.
  2. Open `文献` tab.
  3. Inspect paper cards and click a card.
- Actual:
  - Some paper snippets concatenate unrelated titles/authors, e.g. a TransPolymer card showing adjacent LLM paper references.
  - Clicking a paper card did not visibly switch the center pane into a clear `文献详情` state during browser verification.
- Expected:
  - Paper cards should show one paper's title, venue/year, concise abstract/snippet, and key evidence.
  - Clicking should reliably open a readable center detail view.
- Product impact:
  - Users cannot confidently inspect why a paper was retrieved.

### LS-P1-016: Failure templates are Chinese but do not explain the correct failure layer

- Severity: P1
- Area: Chinese output / failure explanation
- Reproduction:
  - Ask no-hit topic questions, library metadata questions, and attachment-only summary questions.
- Actual:
  - The text is generally Chinese, but many failures use the same generic `本地文献库在本轮检索中没有返回可用于支撑结论的证据` template.
- Expected:
  - Chinese output should be semantically specific:
    - library-status misroute
    - topic no-hit
    - evidence no-hit
    - attachment ignored / attachment missing
    - tool timeout / recovered timeout
- Product impact:
  - Users see Chinese text but still cannot understand what actually failed.

### LS-P1-017: Literature Search layout is not usable at mobile/narrow width

- Severity: P1
- Area: responsive layout / mobile usability
- Reproduction:
  - Set browser viewport to 390x844 and inspect Literature Search.
- Actual:
  - Main content and right-side workbench remain positioned horizontally beyond the viewport.
  - Several controls have x coordinates outside the 390px width.
  - Input textarea measured width is 0 while attachment/send buttons remain visible.
  - Mode buttons become very narrow vertical blocks.
- Expected:
  - The layout should stack or provide a controlled mobile drawer/tab layout.
  - The message input should remain usable.
- Product impact:
  - Literature Search is effectively desktop-only despite product workbench expectations.

### LS-P2-001: Assistant identity answer is too narrow and implementation-facing

- Severity: P2
- Area: assistant personality / product wording
- Reproduction:
  - Ask `你是谁？`.
- Actual:
  - Answer describes itself as `文献研究工作台中的普通对话助手`.
- Expected:
  - Answer should describe product capabilities naturally:
    - literature search
    - library status
    - evidence review
    - citation audit
    - attachment-assisted Q&A
  - Avoid "普通对话助手" as the primary identity.

### LS-P2-002: Asking about a deleted attachment should explain that no active attachment is available

- Severity: P2
- Area: attachment UX / empty state
- Reproduction:
  1. Upload a txt attachment.
  2. Delete it.
  3. Ask `请总结刚才的附件。`.
- Actual:
  - Deleted attachment is correctly absent from user metadata and context.
  - Assistant falls back to generic no-literature-evidence wording.
- Expected:
  - The answer should say the current session has no active attachment available for this turn and suggest re-uploading it.

## Raw Observations

- `lsof` initially showed only frontend `node ... vite --host 127.0.0.1 --port 5173`.
- `curl http://127.0.0.1:8000/api/modules` initially failed to connect.
- `pc_plus` dependency check: `multipart FAIL ModuleNotFoundError`.
- base Python dependency check: `multipart OK 0.0.9`, `pypdf OK 6.9.2`, `fastapi OK 0.115.0`, `uvicorn OK 0.30.6`.
- `GET /api/readiness` under base Python returned ready/ok.
- `GET /api/modules` returned only `literature_search`, which matches the cleaned main navigation/module boundary.
- `GET /api/corpus/dashboard` eventually returned a non-empty corpus: 147371 papers, 2911107 sections, 4979646 chunks, vector index not built.
- Clean API session `s_a17c30a90688`:
  - `你好`: no steps, direct Chinese greeting.
  - `你是谁？`: no steps, Chinese answer but narrow identity wording.
  - `当前文献库中一共有多少文献？`: searched `*`, papers 0, evidence 0, coverage none, citation permission `not_answerable`.
- UI existing session `s_ad33172fd3b2`:
  - Same library-count question shows full five-step retrieval/evidence strip.
  - Audit tab lacks route/query/failure-layer detail.
  - Papers tab only says no retrieved papers.
- Research English probe `s_4e7e7b68b2b8`:
  - Search metadata at ~15.76s: FTS used, vector unavailable because `vector_index_not_built`.
  - 9 candidate papers, 15 evidence, coverage sufficient.
  - Final citation metadata: `audit_status=uncited`, `used_evidence=[]`, despite long evidence-like answer.
- Research Chinese probe `s_039e1c926fb0`:
  - Search metadata at ~17.2s: FTS used, vector unavailable.
  - 10 candidate papers, 15 initial evidence, coverage sufficient.
  - `paper_chunks` succeeded once after ~14s, then timed out twice at 20s each.
  - Final done at ~89.4s; persisted answer has valid evidence ids and used evidence, but latency is too high for quick mode.
- Zero-result/topic-coverage probe `s_6643e0f3cae3`:
  - Query: `文献库里有没有关于火星土壤超导材料的论文？`
  - FTS found 8 papers and 14 evidence, coverage `sufficient`.
  - Answer conclusion was negative: no dedicated local papers about Martian-soil superconducting materials.
  - Evidence mostly supports adjacent matches, not the requested combined topic.
- SQLite metadata baseline:
  - `article_index`: 147372
  - `papers`: 147371
  - `sections`: 2911107
  - `chunks`: 4979646
  - valid year range: 2010-2026
  - top journals include ACS Applied Materials & Interfaces (29197), Journal of Materials Chemistry A (20616), Journal of the American Chemical Society (18930), Small (16886), Advanced Science (13397).
- Batch productization probes:
  - `s_4a768fd37696` indexed-count query: 0 retrieval results, generic evidence-insufficient answer.
  - `s_938f2f0c5506` recent-import query: 0 retrieval results, generic evidence-insufficient answer.
  - `s_c657eb0850cb` year-coverage query: sample-based answer incorrectly claimed 2019-2023.
  - `s_949ede6f8850` journal query: sample-based partial journal list.
  - `s_5a48a468b05f` English topic coverage: first search timed out, second succeeded, 75s total.
  - `s_76c901ca0fa9` Chinese LLM/materials topic coverage: 8 papers / 15 evidence, successful answer, but UI citations render as ordinals rather than stable evidence ids.
  - `s_880d7c9bfde1` no-hit topic: generic evidence-insufficient template.
  - `s_acd5cae5e141` English capability question: no retrieval steps but persisted generic evidence-insufficient answer.
  - `s_5023563ebf2d` mixed-language research: Chinese answer, evidence-grounded, 103s total with one `evidence_expand` timeout.
- Attachment probes:
  - `s_db4df52c2c1f`: txt upload parsed (`att_a4fee7bfcd52`, 67 chars); user message metadata includes attachment; assistant ignored attachment and returned no-literature-evidence template.
  - `s_e4f7b58074f9`: valid PDF upload parsed (`att_47206e524b57`, 67 chars); PDF summary request again returned no-literature-evidence template.
  - `s_22f7b87fd3d4`: attachment+literature controlled rerun completed after ~180s; final answer summarized attachment and cited literature, but citation audit metadata had `audit_status=off`.
  - `s_084a644a517e`: earlier attachment+literature run left turn `t_295f4f51b335` in `running` with no assistant message, while two search results were recorded.
  - `s_87f0d23fa792`: deleted attachment did not enter message metadata/context, as expected; response wording did not explain that no active attachment remained.
  - `s_7d0cda8fc525`: unsupported `.md` upload returned Chinese 400.
  - `s_c715335d73b2`: sixth active attachment returned Chinese 400 after five parsed txt uploads.
- UI browser probes:
  - Sidebar currently shows five main entries: 首页, 文献检索, 研究工作流, 数据抽取, 设置.
  - In the failed library-count session, `证据` tab says no used evidence; `文献` tab says no retrieved papers; `审计 -> 检索策略` detail says `检索方式 未提供`, `查询扩展 未提供`, `向量检索说明 无`.
  - In successful evidence session, evidence-card click opens a center `证据详情` overlay with title, snippet, evidence id, section, source path, DOI.
  - In successful evidence session, paper cards show noisy concatenated snippets; clicking the card did not visibly produce a clean center `文献详情` during this verification.

## Coverage Summary

Completed coverage:

- Environment/startup path.
- Plain chat and identity.
- Library status/count/index/recent/year/journal metadata questions.
- Topic coverage, direct-hit, no-hit, and adjacent negative cases.
- Research QA in Chinese, English, and mixed-language prompts.
- Citation failure and successful citation UI.
- Session attachment upload, PDF parse, txt parse, delete, unsupported type, count limit, attachment-only answer, and attachment+literature answer.
- Right-side `证据 / 文献 / 审计` tabs for no-hit and successful-evidence sessions.
- Center evidence detail overlay.
- Chinese failure wording quality.
- Mobile/narrow-screen smoke check at 390x844.

Remaining risks not exhaustively tested:

- Cross-user attachment isolation was covered by existing automated tests, not manually re-tested in browser.
- File-size limit was not manually tested with a 20MB file to avoid unnecessary local load; count/type/parse boundaries were tested.
- Real external provider variance was not isolated; observations reflect the current local backend/runtime and configured model path.
