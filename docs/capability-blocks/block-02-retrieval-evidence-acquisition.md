# Block 2: Retrieval / Evidence Acquisition

## Goal

让 Agent 稳定获取足够、相关、可引用、可审计的证据，而不是只返回若干论文卡片。

Block 2 的目标不是“能搜论文”，而是把平台从：

```text
search(query) -> papers + snippets
```

升级为：

```text
acquire_evidence(question) -> evidence acquisition packet + coverage judgment
```

完成后，Agent 内部应该能判断，并在需要时用用户可理解的方式说明：

- 我理解了什么检索意图。
- 我尝试了哪些 query / rewrite / retrieval 路径。
- 实际使用了哪种检索方式，是否发生降级。
- 我获得了哪些可引用证据。
- 当前证据覆盖是 sufficient / partial / weak / none。
- 是否可以回答、只能部分回答、需要补检索，或必须拒绝生成事实性结论。

## Scope

包含：

- query understanding。
- query intent detection。
- query rewrite / expansion。
- DOI / article_id / paper_id / title lookup。
- FTS / vector / hybrid / metadata lookup。
- scope、profile、filters、year range。
- section/chunk fetch。
- evidence expand。
- table/figure/SI lookup。
- retrieval fallback。
- no-hit recovery。
- query plan。
- evidence candidate normalization。
- evidence candidate selection / rerank。
- evidence coverage judgment。
- evidence acquisition packet。
- retrieval regression tests。
- 用户可见的检索进度状态展示。
- 开发/诊断用 Retrieval Inspector。

不包含：

- 最终回答怎么写。
- claim-level audit。
- artifact 生命周期管理。
- 多用户权限模型。
- 长流程 deep research task orchestration。

## Current State

平台已有 `/api/literature-search/search`、paper show/sections/chunks、evidence expand，并且 Chat fallback 路径和 Agent tools 都能调用 search。

当前已满足：

- Search 能返回 `query_plan`、`retrieval_used`、`vector_unavailable_reason`、`results` 和 evidence snippets。
- Agent tool 已支持 `search`、`paper_sections`、`paper_chunks`、`evidence_expand`、`pack`。
- Chat Agent 已能通过 tool calling 自主检索，并要求用 `[E#]` 引用证据。
- citation audit 已能发现虚构引用或有证据未引用。
- Block 0 已让 canonical `paper_id` 贯穿 Search -> Evidence -> Memory -> Report。
- 前端 Search tab 已能展示检索结果、retrieval 路径和部分 query plan 信息。

当前主要缺口：

- 还没有统一的一等 `EvidenceAcquisitionPacket`。
- evidence 仍主要挂在 `results[*].evidence` 下，没有标准化展平成 `evidence_candidates`。
- query intent / rewrite / expansion 还没有平台级契约。
- no-hit recovery 还没有标准流程。
- fallback reason 和 coverage notes 还没有统一输出。
- Agent 还不能稳定根据 coverage 判断是否补检索或拒答。
- 前端还缺少成品化的检索进度状态展示。
- 开发/诊断模式还缺少完整 Retrieval Inspector。
- 缺少固定 retrieval regression set。

## Target Capability

Retrieval 层应该输出可审计的 evidence acquisition packet：

```text
query
query_intent
query_plan
rewritten_queries
retrieval_requested
retrieval_used
filters
results
evidence_candidates
expanded_assets
fallback_reason
coverage
coverage_notes
warnings
debug
```

Agent 不只知道“命中 N 篇”，还应该知道：

- 证据覆盖是否足够。
- 是否需要补检索。
- 是否存在 vector 降级。
- 是否 no-hit。
- 是否过度依赖单篇论文。
- 是否缺少 method/result/table 等关键证据。
- 是否能进入 Block 3 的 grounded answer 阶段。

## Product Interaction Principle

Block 2 的复杂过程大部分应该是隐式后台能力。用户界面不应该把 query plan、rewrite、fallback、coverage calculation、candidate scoring 等内部细节作为常规交互内容展示出来。

成品交互应该体现“Agent 正在认真检索和获取证据”，而不是暴露“Agent 的内部检索工程细节”。

建议分为两类：

```text
User-facing progress:
  横向节点状态，实时展示当前正在进行哪一步。
  只展示阶段名、状态、简短结果，不展示详细 query/rewrite/fallback 数据。

Developer diagnostics:
  仅用于调试、验收和开发模式。
  可查看完整 packet、query plan、fallback steps、candidate table。
```

用户默认看到的是轻量、成品化的过程条，例如：

```text
理解问题 -> 检索文献 -> 筛选证据 -> 检查证据 -> 组织回答
```

每个节点只表达状态：

```text
pending | running | done | warning | failed
```

可以附带非常短的提示，例如：

```text
检索文献：已找到相关候选
筛选证据：证据偏少
检查证据：可部分回答
```

不应默认展示：

- rewritten queries 明细。
- retrieval scores。
- fallback steps 明细。
- raw evidence candidate table。
- coverage 计算过程。
- raw packet JSON。

这些内容只进入开发/诊断模式，不作为普通研究工作流的一部分。

## Product Requirements

- Most retrieval intelligence is implicit. The default product UI must not expose internal query plans, rewrites, fallback steps, raw scores, or raw packet JSON.
- User-facing retrieval progress is not chain-of-thought. It only reports observable task stages and coarse status.
- Coverage must be translated into user-readable trust signals, such as evidence sufficient, evidence limited, evidence missing, answer will be partial, or additional search may help.
- Weak or missing evidence is a valid outcome. The Agent should present it gracefully and avoid unsupported conclusions.
- Evidence should be representative, diverse, and answer-relevant, not merely high-scoring.
- Evidence sufficiency is task-dependent. DOI lookup, title lookup, topic review, recent progress, mechanism, and metric comparison require different sufficiency expectations.
- Follow-up questions should reuse prior evidence when appropriate and retrieve more only when needed.
- The system should balance evidence sufficiency with latency and user attention. It should not over-search when enough evidence exists or when no usable evidence is likely.
- The system must separate retrieval breadth from LLM context budget. A quick grounded answer can be based on representative evidence; comprehensive field coverage requires a deep, batched research flow.
- Block 2 decides evidence acquisition and sufficiency. Block 3 handles claim-level grounding and final citation discipline.

## Implementation Objectives

### 1. Query Intent Understanding

Agent 需要先判断用户问题属于哪类检索任务。

目标结构：

```text
query_intent:
  type
  confidence
  detected_entities
  suggested_filters
  suggested_retrieval
```

需要支持的问题类型：

| Type | Description | Retrieval Behavior |
|---|---|---|
| `doi` | DOI 精确查询 | DOI normalization + metadata lookup |
| `article_id` | article_id 查询 | exact metadata lookup |
| `paper_id` | canonical paper_id 查询 | exact metadata lookup |
| `title` | 论文标题或近似标题查询 | title normalization + fuzzy / FTS lookup |
| `author_year_journal` | 作者、年份、期刊组合查询 | metadata filters + FTS |
| `topic` | 普通主题查询 | hybrid retrieval |
| `recent_review` | 最新进展 / recent / SOTA | hybrid + year boost + coverage by year |
| `mechanism` | 机制、方法、原理类问题 | method/result/discussion section boost |
| `metric_compare` | 指标、数据、对比类问题 | table/result kind boost |
| `followup` | 追问 | reuse session evidence + optional supplemental search |
| `unknown` | 无法分类 | conservative hybrid search |

### 2. Query Plan

每次检索都必须生成结构化 `query_plan`。

目标结构：

```text
query_plan:
  original_query
  query_intent
  rewritten_queries
  retrieval_requested
  retrieval_steps
  filters_requested
  filters_applied
  fallback_steps
  final_retrieval_used
  warnings
```

示例：

```text
original_query: "RAG 在科研场景中的最新进展"
query_intent: recent_review
rewritten_queries:
  - "retrieval augmented generation scientific research"
  - "RAG literature review research assistant"
  - "retrieval augmented generation scientific discovery recent"
retrieval_requested: hybrid
retrieval_steps:
  - hybrid semantic + fts
  - recent-year boosted ranking
filters_applied:
  year_from: 2021
fallback_steps:
  - vector unavailable -> fts
final_retrieval_used: fts
warnings:
  - vector_index_not_built
```

### 3. Query Rewrite / Expansion

Agent 不能只用用户原句搜索，需要根据问题类型生成多个检索表达。

需要支持：

| Capability | Requirement |
|---|---|
| DOI normalization | 清洗 DOI，去掉 URL 前缀，统一大小写和尾部标点 |
| title normalization | 去标点、大小写、停用词，支持近似标题匹配 |
| bilingual expansion | 中文问题生成英文关键词 |
| abbreviation expansion | 如 RAG -> retrieval augmented generation |
| synonym expansion | 同义词、领域术语变体 |
| recent query expansion | latest / recent / state-of-the-art / progress |
| metric-oriented expansion | efficiency、stability、accuracy、flux 等指标词扩展 |
| section-aware rewrite | method/result/discussion/table 等分区检索 |
| failed query relaxation | no-hit 后自动放宽 query |

目标输出：

```text
rewritten_queries:
  - query
  - reason
  - retrieval_hint
  - filters_hint
```

### 4. Retrieval Strategy

Block 2 应支持多种 retrieval strategy，并能根据场景选择。

| Retrieval | Use Case |
|---|---|
| `fts` | 精确关键词、标题、DOI、术语查询 |
| `vector` | 语义查询、概念型问题 |
| `hybrid` | 默认策略，结合语义和关键词 |
| `metadata_lookup` | DOI、article_id、paper_id、title、year、journal |
| `section_chunk_fetch` | 获取更完整上下文 |
| `asset_lookup` | table / figure / SI |
| `evidence_expand` | 从 snippet 扩展到上下文或资产 |

默认逻辑：

```text
DOI / title -> metadata + fts
主题问题 -> hybrid
最新进展 -> hybrid + year boost
数据问题 -> hybrid + table/result kind boost
机制问题 -> hybrid + method/result/discussion section boost
vector 不可用 -> fts fallback
no-hit -> query relaxation + retrieval switch
```

### 5. Fallback / No-hit Recovery

强 Agent 不能一次搜不到就结束。

标准恢复流程：

```text
Attempt 1: original query + requested/default retrieval
Attempt 2: rewritten query + hybrid/fts
Attempt 3: relax filters
Attempt 4: remove year/section/kind restriction
Attempt 5: metadata/title fallback
Attempt 6: return no usable evidence, without fabricating evidence
```

目标字段：

```text
fallback_reason:
  code
  message
  triggered_by
  attempted_recoveries
  final_status
```

常见 code：

```text
vector_index_not_built
vector_query_failed
no_results
low_evidence_count
over_restricted_filters
metadata_lookup_failed
asset_not_found
```

### 6. Evidence Candidate Normalization

这是 Block 2 的核心输出之一。

目标是把所有候选证据展平成标准列表：

```text
evidence_candidates:
  evidence_id
  paper_id
  article_id
  doi
  title
  year
  journal
  kind
  section
  section_id
  chunk_index
  snippet
  expanded_context
  confidence
  relevance_score
  source_path
  source_locator
  asset_path
  asset_label
  retrieval_source
  query_match_reason
```

必须保证：

- 每条证据可追溯到 paper。
- 每条证据可追溯到本地 `source_path`。
- 每条证据有稳定 `evidence_id`。
- 每条证据能被 Chat Agent 引用。
- 每条证据能进入 research record / export。
- 每条证据能参与 coverage 判断和评估。

### 7. Evidence Selection / Rerank

检索不是返回越多越好，而是要选择可用证据。

第一阶段使用 deterministic selector，不优先引入 LLM reranker。

建议评分：

```text
score = relevance
      + confidence
      + section_weight
      + kind_weight
      + recency_weight
      + diversity_bonus
      - same_paper_penalty
```

需要满足：

| Goal | Requirement |
|---|---|
| 多论文覆盖 | 避免单篇论文垄断 |
| 多证据类型覆盖 | abstract / result / table / figure 合理分布 |
| 高相关优先 | query term / semantic score 高的优先 |
| 高可信优先 | confidence 高的优先 |
| 最新问题时间加权 | recent 类问题重视年份 |
| 数据问题 table 优先 | metric/table evidence 提权 |
| 控制总量 | 避免 Agent 上下文爆炸 |

默认建议（注意：这些数值已被 §8 的 intent-aware 三层预算取代/细化——
`total_evidence_limit` 现在等于按意图变化的 selection pool 预算，进入 LLM 的
context evidence 另有更小的预算）：

```text
evidence_per_article_limit: 2-3
selection_pool (≈ total_evidence_limit): intent-aware, e.g. 3 (doi) .. 30 (recent_review)
min_distinct_papers_for_review: 3
```

### 8. Breadth vs Context Budget

Block 2 必须把“检索候选池的广度”和“进入 LLM 上下文的证据数量”解耦。

核心原则：

```text
candidate pool can be broad
LLM context evidence must stay bounded
```

原因：

- 一次 grounded chat answer 受 LLM 上下文窗口限制，必须有 evidence cap。
- 某领域的全面覆盖往往涉及几十、几百甚至上千篇论文，不能靠一次回答塞进上下文。
- 只把 `limit=8/20` 当作“系统看到的全部文献”会误判覆盖度。
- 可信系统应该先广泛召回以估计覆盖，再选择少量代表性证据进入回答。

目标分层：

| Layer | Purpose | Requirement |
|---|---|---|
| `retrieval_candidate_pool` | 估计领域广度、覆盖度和用户可浏览候选 | 可以大于 LLM 上下文容量 |
| `evidence_selection_pool` | 去重、筛选、聚类、代表性排序 | 保留跨论文、跨方向、跨年份的候选 |
| `llm_context_evidence` | 支撑一次 grounded answer | 必须严格有界，避免 token 爆炸 |
| `deep_research_flow` | 系统综述、全面覆盖、长报告 | 应走分批聚合 / map-reduce，而不是单次 chat |

目标字段：

```text
breadth:
  candidate_paper_count
  candidate_evidence_count
  selected_evidence_count
  llm_context_evidence_count
  estimated_total_matches
  estimate_is_lower_bound
  cluster_count
  clusters_covered
  missing_clusters
  cluster_method
  breadth_limited
  deep_research_suggested
  breadth_notes
```

实现说明：

- `estimated_total_matches` 为**近似值**，由 query_plan 的候选计数推得（底层无精确
  count，向量未建）；当底层候选扫描达到上限时记为下界，置 `estimate_is_lower_bound=true`。
- `cluster_*` 第一阶段为**轻量规则近似**（matched-term/期刊/年份），`cluster_method`
  标注来源；向量索引建好后再升级为语义聚类。
- `breadth` 应与 `coverage` 一并写入 research record / export，便于审计“本次为代表性样本”。

用户可理解的信任信号：

```text
本库命中约 N 篇相关文献；本次回答基于其中 M 条代表性证据。
这些证据覆盖 K 个主要方向。
当前回答是代表性概览，不是完整系统综述。
如需全面综述，建议启动深度研究任务。
```

`breadth_limited` 应在以下情况出现：

- candidate pool 明显大于 LLM context evidence。
- query intent 是 `topic` / `recent_review` / `metric_compare` 这类广域任务。
- evidence selector 只能选取代表性样本，不能覆盖所有方向。
- vector/hybrid 召回不可用，导致大规模语义召回能力受限。

`deep_research_suggested` 应在以下情况出现：

- 用户问题明显要求全面综述、系统回顾、领域全景、所有方法对比。
- candidate pool 很大，但单次回答只能覆盖部分簇。
- coverage 足以支持“代表性回答”，但不足以宣称“全面覆盖”。
- 用户要求报告、综述、表格化抽取、跨大量论文综合。

Quick answer 与 deep research 的边界：

| Task | Block 2 Quick Answer | Deep Research Flow |
|---|---|---|
| 单篇 DOI / title 查询 | 适合 | 通常不需要 |
| 具体机制或指标问题 | 适合，但需说明证据边界 | 如需多论文系统对比则建议 |
| 最新进展概览 | 适合代表性概览 | 全面综述应建议 |
| 全领域系统综述 | 不应宣称全面 | 应走分批聚合 |
| 几百篇论文综合 | 不适合单次 chat | 应走 map-reduce |

### 9. Coverage Judgment

Agent 需要知道“证据够不够回答”。

目标输出：

```text
coverage:
  status: sufficient | partial | weak | none
  distinct_paper_count
  evidence_count
  year_range
  sections_covered
  evidence_kinds
  dominant_paper_ratio
  candidate_paper_count
  selected_evidence_count
  breadth_limited
  deep_research_suggested
  missing_aspects
  coverage_notes
```

示例 notes：

```text
- Only 1 paper found; not enough for a review-style answer.
- Vector retrieval unavailable; results are FTS-only.
- Most evidence comes from abstracts, lacking method/result support.
- Recent-progress query has no evidence after 2022.
- Broad query matched many candidates; this answer uses representative evidence only.
```

Coverage status 建议：

| Status | Meaning | Agent Behavior |
|---|---|---|
| `sufficient` | 证据数量、来源、类型基本足够 | 可以进入 Block 3 grounded answer |
| `partial` | 能回答部分内容，但有明确缺口 | 部分回答并说明缺口，或补检索 |
| `weak` | 证据少、偏、旧或只有低置信 snippet | 优先补检索；必要时说明不足 |
| `none` | 没有可用证据 | 不生成事实结论 |

### 10. Evidence Acquisition Packet

Block 2 最终产物是统一 packet。

建议结构：

```text
EvidenceAcquisitionPacket:
  query
  query_intent
  query_plan
  rewritten_queries
  retrieval_requested
  retrieval_used
  filters
  fallback_reason
  results
  evidence_candidates
  expanded_assets
  coverage
  breadth
  coverage_notes
  warnings
  debug
```

这个 packet 应该被以下模块共用：

| Consumer | Use |
|---|---|
| Chat Agent | 判断是否继续检索、是否可以回答 |
| Search tab | 展示成品化检索进度和结果摘要 |
| Evidence tab | 展开候选证据 |
| Research record | 审计检索链路 |
| Export report | 保留来源说明 |
| Evaluation | 做检索回归测试 |
| Block 3 | 判断回答权限和 grounding |
| Block 11 | 统计可靠性和降级率 |

### 11. Agent Decision Logic

Chat Agent 在 Block 2 完成后，不应该只是机械调用 search。

目标逻辑：

```text
1. search / acquire_evidence
2. inspect packet.coverage
3. if coverage = none:
     do not answer factual content; report no usable local evidence
4. if coverage = weak:
     attempt supplemental retrieval or state insufficiency
5. if coverage = partial:
     answer only supported parts and list gaps
6. if coverage = sufficient:
     proceed to Block 3 grounded answer
7. if breadth.breadth_limited = true:
     present the answer as representative, not exhaustive
8. if breadth.deep_research_suggested = true:
     suggest a deep research / report flow for comprehensive coverage
```

补检索动作可以包括：

- rewrite query。
- change retrieval。
- relax filters。
- fetch sections/chunks。
- expand evidence。
- build pack。

### 12. User-facing Retrieval Progress

前端不是 Block 2 的核心，但必须让 Agent 的证据获取过程有清晰、克制、成品化的状态表达。

主界面应展示横向节点状态，而不是详细检索内部信息。

```text
理解问题 -> 检索文献 -> 筛选证据 -> 检查证据 -> 组织回答
```

每个节点字段建议：

```text
id
label
status
short_message
started_at
completed_at
```

状态：

```text
pending
running
done
warning
failed
```

示例：

```text
理解问题: done, "已识别问题类型"
检索文献: running, "正在查找本地文献库"
筛选证据: pending
检查证据: pending
组织回答: pending
```

注意：`short_message` 应该是产品化文案，不应暴露完整 query plan、rewrite、fallback 或内部评分。

### 13. Developer Retrieval Diagnostics

完整 Retrieval Inspector 只作为开发、测试、诊断能力，不应默认出现在普通用户主界面。

Developer diagnostics 可展示：

```text
original query
query intent
rewritten queries
retrieval requested / used
filters applied
fallback steps
coverage status
coverage notes
warning badges
evidence candidate table
raw packet JSON
```

Evidence candidate table 字段可以包括：

```text
EID
Title
Year
Section
Kind
Confidence
Score
Source
Expand
```

## Interfaces And Data Concerns

重点接口：

- `/api/literature-search/search`
- `/api/literature-search/papers/{article_id}`
- `/api/literature-search/papers/show`
- `/api/literature-search/papers/sections`
- `/api/literature-search/papers/chunks`
- `/api/literature-search/evidence/expand`
- Agent tool: `search`
- Agent tool: `paper_sections`
- Agent tool: `paper_chunks`
- Agent tool: `evidence_expand`

Recommended backend additions:

- `EvidenceCandidate` schema。
- `Coverage` schema。
- `FallbackReason` schema。
- `EvidenceAcquisitionPacket` schema。
- Packet builder that wraps raw `ResearchSearch.search()` output.
- Deterministic evidence selector.
- Query intent / rewrite helper.
- Retrieval regression fixtures.

Compatibility requirement:

- Existing `/api/literature-search/search` consumers should keep working.
- Existing `results` shape should not be removed abruptly.
- New packet fields can be additive.
- Chat Agent compact tool payload should be updated to use packet fields.

## Implementation Priority

| Priority | Item | Reason |
|---|---|---|
| P0 | Define `EvidenceAcquisitionPacket` schema | 稳定后端契约 |
| P0 | Define `EvidenceCandidate` schema | Agent、前端、评估、报告共用 |
| P0 | Add packet builder after raw search | 不重写底层检索，先统一输出 |
| P0 | Add `coverage` and `coverage_notes` | 让 Agent 知道证据是否足够 |
| P0 | Standardize `fallback_reason` | 降级和失败必须可审计 |
| P1 | Add no-hit recovery | 防止无结果时直接失败或胡答 |
| P1 | Add query intent detection | DOI、标题、主题、最新进展分流 |
| P1 | Add query rewrite / expansion | 提升召回率 |
| P1 | Add evidence selector | 避免噪声和单篇垄断 |
| P1 | Separate candidate pool from context evidence | 先广泛召回，再有限上下文作答 |
| P1 | Add breadth signals | 让系统知道回答是代表性概览还是接近全面覆盖 |
| P2 | Add user-facing retrieval progress timeline | 让用户感知 Agent 正在进行证据获取 |
| P2 | Add developer Retrieval Inspector | 仅用于开发、调试、验收，不进入默认用户流程 |
| P2 | Add retrieval regression set | 持续验收检索质量 |
| P3 | Optional LLM reranker / selector | 等规则和回归稳定后再引入 |

## Test And Acceptance

最小验收：

- DOI 精确检索稳定命中目标论文。
- title 模糊检索能命中目标论文。
- 中文主题查询能生成英文 rewrite 或等价关键词，并返回相关证据。
- hybrid 降级到 FTS 时有明确 reason。
- “RAG 在科研场景中的最新进展”类问题能返回多篇不同年份/方向证据，或明确说明 coverage 不足。
- evidence expand 能从 evidence id 找到更完整上下文或资产。
- no-hit 情况不会生成伪证据。
- 单篇论文不会垄断全部候选证据。
- 数据/指标查询能优先返回 table/result 类型证据。
- section 查询能让 method/result/discussion 等限制生效。
- Agent 在 coverage weak / none 时能补检索或拒绝事实性回答。
- 广域主题查询能区分 candidate pool 与进入 LLM 的 evidence context。
- 当候选池明显大于上下文容量时，系统能给出 `breadth_limited` 信号。
- 当用户要求全面综述或系统回顾时，系统能建议 deep research / map-reduce 流程，而不是在单次 chat 中宣称全面。

Regression set should cover:

| Test | Acceptance |
|---|---|
| DOI exact lookup | Stable hit for target paper |
| Title fuzzy lookup | Near-title input hits target paper |
| Chinese topic query | Relevant English/expanded query evidence returned |
| Recent-progress query | Year coverage or insufficiency note produced |
| Vector unavailable | `fallback_reason` is explicit |
| No-hit query | No fabricated evidence |
| Single-paper dominance | Selector limits dominant paper ratio |
| Table evidence query | Table/result evidence is boosted |
| Section query | Section filter affects candidates |
| Agent supplemental search | Weak coverage can trigger follow-up retrieval |
| Candidate/context split | Large candidate pool does not enlarge LLM evidence context blindly |
| Breadth-limited overview | Broad query marks representative answer rather than exhaustive coverage |
| Deep research handoff | Comprehensive review request suggests batched/deep flow |

Final acceptance:

```text
1. Every search has query_plan.
2. Every search has normalized evidence_candidates.
3. Every search has coverage judgment.
4. Every fallback has explicit reason.
5. No-hit never produces fake evidence.
6. Agent can use coverage to decide answer / partial answer / retry / refuse.
7. Search breadth and LLM context evidence are separate budgets.
8. Broad answers expose representative coverage through `breadth_limited` / `deep_research_suggested`.
9. Frontend can display a polished retrieval progress timeline without exposing internal details.
10. Developer diagnostics can inspect the full packet when needed.
11. Regression tests cover DOI/title/topic/no-hit/fallback/diversity/breadth.
```

## Open Discussion

- query rewrite 是由规则提供、底层 Research Agent 提供，还是可选 LLM rewrite？
- 用户可见的横向节点状态应包含哪些阶段，如何避免像“假进度”？
- Retrieval Inspector 是否只在开发/诊断模式开放？
- “最新进展”类问题是否默认加入 year filter，还是只做 time-aware ranking？
- no-hit 时最多自动恢复几轮，避免过度检索？
- evidence candidates 是否需要二阶段 rerank？
- LLM evidence selector 是否只在 deep mode 使用？
- evidence_per_article_limit 默认值如何避免单篇论文垄断证据？
- coverage status 的阈值是否应按 query intent 区分？
- candidate pool、selection pool、LLM context evidence 的默认预算分别是多少？
- breadth clusters 使用领域分类、关键词聚类、向量聚类，还是先用轻量规则近似？
- 什么条件下从 quick answer 明确切换或建议 deep research flow？
