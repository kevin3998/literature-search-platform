# 结构化文献数据抽取工作台设计

日期：2026-07-06

## 目标

新增一个一级模块：结构化文献数据抽取工作台。

这个模块用于把本地文献库转化为可复用的结构化研究数据集。它不是 Chat 的附属功能，也不是临时的一次性抽取工具，而是一个任务型工作台：用户可以围绕某个主题创建抽取任务，收集文献，定义自定义 schema，批量抽取结构化信息，人工审阅修正，并导出 CSV、JSONL、Excel 或证据报告。

目标流程：

```text
新建抽取任务
-> 从本地文献库收集文献
-> 确认 included collection
-> 定义并冻结自定义 schema
-> 配置任务级模型
-> 构建 evidence packet
-> 运行批量结构化抽取
-> 审阅、修正、局部重抽
-> 导出结构化数据和证据报告
```

## 产品定位

平台当前已经具备本地文献检索、证据获取、基于证据的问答、研究记录、报告导出和研究工作流能力。结构化文献数据抽取工作台补齐的是另一个核心环节：从本地文献库生产可复用、可审计、可导出的研究数据资产。

第一版采用明确边界：

```text
一个任务 = 一个文献集合 + 一个主 schema + 多次抽取运行
```

这个边界足够稳定，适合第一版落地。后续可以扩展到“一个研究项目包含多个 collection、多个 schema、多个输出表”，但第一版不把任务做成小型数据管理系统。

这个边界不等于“一篇论文只能生成一条记录”。第一版 UI 可以默认提供 paper-level table，但数据模型和 schema 设计必须支持更细粒度的 record unit。材料、催化剂、膜材料和实验条件类抽取经常是一篇论文包含多个材料体系、多个样品、多个测试条件和多组性能指标，因此抽取记录需要支持层级结构：

```text
Paper
  -> Material / Sample
    -> Experiment / Condition
      -> Performance Value
```

第一版至少需要在 schema 和 record 层支持：

```text
record_unit:
  paper_level
  material_level
  sample_level
  experiment_level
  condition_level

record:
  paper_id
  record_id
  record_type
  parent_record_id
  fields
  evidence
```

这样第一版可以先以论文级表格交付，同时不把系统锁死在论文元信息抽取。

## 一级模块形态

结构化文献数据抽取工作台作为平台左侧导航中的一级模块，与“文献检索分析”“研究工作流”等模块并列。

模块首页是任务列表，而不是聊天界面：

```text
任务名称                  文献数    字段数    最近运行       状态
AI 综述工具数据抽取        126       18       2026-07-06    待审阅
肿瘤免疫治疗指标抽取       84        24       2026-07-05    已完成
LLM Agent Benchmark        210       15       2026-07-03    抽取中
```

用户可以创建、打开、复制、归档和删除任务，也可以从已有任务复制 schema。

## 任务工作区

每个任务打开后进入固定工作区：

```text
Overview
Sources / Collection
Schema
Extraction Runs
Review Table
Exports
```

这个模块不是以聊天作为主入口，但 LLM 辅助能力贯穿关键步骤：

- 在 Collection 阶段辅助扩展检索词和筛选候选文献。
- 在 Schema 阶段辅助生成、修改、拆分、合并字段。
- 在 Extraction 阶段按照冻结的 schema 执行结构化抽取。
- 在 Review 阶段解释低置信字段、重抽某篇论文或某个字段。
- 在 Export 阶段生成 data dictionary 和 evidence report。

## 任务状态

任务需要有清晰状态，帮助用户知道下一步该做什么：

```text
draft
collecting
collection_ready
schema_ready
extracting
review_required
completed
exported
failed
```

状态应表达用户当前最需要关注的动作。例如，抽取完成但存在大量低置信字段时，任务状态应为 `review_required`，而不是简单显示 `completed`。

## 任务产物归属

所有输出按任务分类保存。用户不应该在一个全局 artifact 池中寻找某个抽取任务的结果。

概念上的任务产物结构：

```text
structured_extraction/
  tasks/
    {task_id}/
      task.json
      collection/
        collection.json
        paper_refs.jsonl
        candidate_decisions.jsonl
      schemas/
        schema_v1.json
        schema_v2.json
      evidence_packets/
        packet_run_001.jsonl
      prompts/
        extraction_contract_v1.json
      runs/
        run_001/
          run.json
          records.jsonl
          field_evidence.jsonl
          quality_flags.jsonl
          errors.jsonl
      exports/
        export_001.csv
        export_001.jsonl
        export_001.xlsx
        evidence_report.md
        data_dictionary.md
      audit/
        review_changes.jsonl
        export_history.jsonl
```

第一版默认保存 paper refs 和 manifest，不默认物理复制全文文件。每篇文献至少保留：

```text
paper_id
doi
title
source_path
md_path
index_version
```

这样既节省空间，又保持与 Research Index canonical `paper_id` 的一致性。后续可以增加 snapshot package，把源文献和抽取结果打包归档。

Structured Extraction Workbench 默认只读 Research Index，不直接修改原始文献库、主索引、正文 markdown、图表资产或 vector records。Research Index 是 canonical read-only source；抽取任务只保存 task-specific derived artifacts，包括 collection、schema、evidence packets、runs、review events 和 exports。

## 模块一：任务管理

任务管理负责任务生命周期和任务级元数据。

用户能力：

- 新建抽取任务。
- 修改任务名称和描述。
- 查看任务状态、文献数、字段数、运行次数、导出次数。
- 复制任务，可选择复制 schema 和模型配置。
- 归档或删除任务。
- 打开任务工作区。

每个任务记录：

```text
task_id
name
description
status
created_at
updated_at
current_collection_version
current_schema_version
model_settings
last_run_summary
```

任务管理本身不执行抽取。它负责组织其他模块，并给用户一个稳定入口。

## 模块二：文献收集 Collection Builder

Collection 必须先于 schema 存在。Schema 是服务于某一批文献的，不应脱离 collection 抽象定义。

第一版支持两个文献收集入口。

### 入口一：Metadata / Keyword Collection

用户基于本地库已有 metadata 和 Research Index 检索候选文献。

支持的检索和过滤维度：

```text
keyword
title
abstract
author
year
journal
DOI
paper_id
article_id
site
metadata.json 中已有字段
```

检索结果先进入候选池，不直接进入最终 collection。

### 入口二：Research Question Expansion

用户输入研究问题或主题，例如：

```text
大语言模型如何辅助系统综述中的文献筛选和数据抽取？
```

系统使用任务的 Schema Assistant Model 进行本地检索扩展：

```text
研究问题
-> 关键词组
-> 同义词
-> 相关概念
-> 多条本地 metadata 检索 query
-> 合并候选文献
-> 去重
-> 对候选摘要 / metadata 进行 LLM relevance screening
```

第一版确认采用 B 方案：

```text
生成本地检索 query + 对候选摘要 / metadata 做 LLM relevance screening
```

第一版不做多轮迭代扩展。后续可以从命中文献中提取新关键词，再继续扩展。

### 候选池 Candidate Pool

候选池和最终 included collection 分离。

每篇候选文献记录：

```text
paper_id
title
authors
year
journal
doi
source_path
index_version
candidate_source
source_query
matched_fields
metadata_score
llm_decision
llm_relevance_score
llm_reason
included
excluded
user_decision
exclude_reason
duplicate_group_id
canonical_paper_id
duplicate_reason
```

候选来源包括：

```text
metadata_search
question_expansion
manual_add
imported_ref
```

### LLM 辅助筛选

LLM refinement 是可选增强，但应作为一等能力提供。

它可以：

- 基于 metadata 和 abstract 总结候选文献。
- 将候选文献分类为 include、exclude、uncertain。
- 按用户定义的标签归类。
- 给出相关性分数。
- 解释纳入或排除理由。
- 标记需要人工判断的模糊候选。

LLM 不能静默决定最终 collection。用户必须显式纳入、排除，或点击“接受全部高置信候选”。

排除理由需要标准化，避免后续无法解释 collection 是如何形成的。第一版建议支持：

```text
not_relevant
review_article
no_full_text
not_target_material
not_target_method
not_target_application
duplicate
insufficient_data
non_experimental
non_english_or_non_chinese
other
```

候选池还需要显式处理重复文献，例如 same DOI、same title、preprint vs published version、conference vs journal version、duplicate local files。重复文献不应直接删除，而应归入 duplicate group，并标记 canonical paper，便于用户确认保留哪一条。

### Included Collection

Included collection 是用户确认后的文献集合，后续 schema 和 extraction 只针对该集合运行。

当用户进入 schema 冻结或抽取前，需要冻结 collection version：

```text
collection_version
included_papers
created_at
selection_summary
source_queries
decision_counts
```

后续增删文献应创建新的 collection version，而不是修改历史版本。

## 模块三：Evidence Packet Builder

Evidence Packet Builder 是抽取前的内部子模块，用于明确抽取模型实际读取什么证据。

第一版不应把整篇 markdown 直接交给模型自由抽取。更稳妥的链路是：

```text
paper markdown / tables / figures metadata
-> section parsing
-> candidate evidence retrieval
-> evidence packet construction
-> schema-guided extraction
-> validation
-> review
```

Evidence packet 可以按论文、record type、字段组或具体字段构建。它应尽量复用现有 Research Index 中的 sections、chunks、tables、figures 和 source paths。

概念结构：

```text
paper_id
schema_version
record_type
field_group
retrieved_sections
chunks
tables
figures
source_paths
construction_query
warnings
```

Evidence packet 的作用：

- 控制 token 成本。
- 避免模型从全文中自由发挥。
- 让字段值与证据真实绑定。
- 支持字段级或字段组级重抽。
- 区分“证据没找到”和“模型抽取错误”。
- 支持材料、样品、实验条件和性能值之间的证据对齐。

第一版可以先按字段组构建 packet，例如 `material_identity`、`synthesis`、`test_condition`、`performance`。后续再扩展到更细粒度的字段级 packet。

## 模块四：Schema Designer

Schema Designer 允许用户完全自定义字段，同时由 LLM 辅助完成字段内容和格式确认。

用户不需要手写严格 JSON。主交互应是结构化字段编辑器，并配合 LLM 辅助。

Schema Designer 需要区分 record schema 和 field schema。Field schema 描述每个字段怎么抽取；record schema 描述当前任务到底在抽取什么类型的记录。

Record schema 包含：

```text
record_type
record_unit
primary_entity
one_paper_may_have_multiple_records
record_identity_fields
deduplication_keys
parent_record_type
field_groups
```

例如膜材料任务可以定义：

```text
record_type: membrane_sample
record_unit: sample_level
primary_entity: membrane
one_paper_may_have_multiple_records: true
record_identity_fields:
  - paper_id
  - membrane_name
  - test_condition
```

催化剂任务可以定义：

```text
record_type: catalyst_sample
record_unit: experiment_level
primary_entity: catalyst
one_paper_may_have_multiple_records: true
record_identity_fields:
  - paper_id
  - catalyst_name
  - electrolyte
  - current_density
```

每个字段包含：

```text
key
label
type
description
extraction_instruction
required
missing_policy
evidence_required
allowed_values
unit
validation_rule
example_values
notes
```

第一版字段类型：

```text
string
number
boolean
enum
multi_enum
list
date
object
evidence_text
```

Schema Designer 支持：

- 用户手动新增字段。
- 用户编辑字段名称、key、类型、说明和抽取指令。
- LLM 基于任务上下文和样本文献建议字段。
- LLM 重写不清楚的字段说明。
- LLM 拆分、合并、规范化字段。
- LLM 基于样本文献给出示例值。
- 用户确认后冻结 schema version。

核心原则：

```text
Schema 是正式任务对象，不是一次性 prompt。
```

每次 extraction run 都绑定到某个 schema version。历史 run 不会因为 schema 后续修改而改变含义。

Schema 修改需要保留 change metadata。第一版不要求自动迁移旧结果，但需要记录：

```text
schema_change_type
old_field_key
new_field_key
migration_strategy
requires_rerun
migration_note
```

支持的 change type 至少包括：

```text
field_added
field_removed
field_renamed
field_split
field_merged
field_deprecated
record_unit_changed
```

## 模块五：Prompt Contract Compiler

用户确认后的 schema 必须进入抽取 prompt，但不应作为一段原始文本粗暴拼接。

系统应将 schema 编译成正式的 extraction prompt contract：

```text
schema_definition
-> normalized field contract
-> output JSON contract
-> evidence requirements
-> validation rules
-> extraction_prompt_contract
```

每个字段在 contract 中明确：

```text
抽取什么
期望输出类型
找不到时如何处理
是否必须给 evidence
证据需要精确到哪一层
允许值或枚举范围
校验规则
```

Prompt contract 还必须包含抽取纪律，尤其是材料和实验条件级任务中的 alignment 约束：

```text
不得根据常识补全。
不得从摘要推断实验细节。
找不到证据时必须返回 missing。
不得把不同样品的组成、制备条件和性能混合。
不得把不同测试条件下的数据合并。
所有性能值必须绑定测试条件。
数值必须尽量保留 raw value、normalized value 和 unit。
无法确认样品 / 条件对应关系时必须标记 ambiguous_value。
```

字段值建议保存更丰富的结构，而不是只有 value：

```text
raw_value
normalized_value
unit
condition_context
evidence_text
evidence_location
extraction_note
```

每次抽取运行记录：

```text
task_id
collection_version
schema_version
prompt_contract_version
schema_assist_model_profile_id
extraction_model_profile_id
run_id
```

这样每条结构化记录都能追溯到 schema、prompt contract、模型配置和具体运行。

## 模块六：任务级模型配置

数据抽取任务使用独立模型配置，不强制与 Chat Agent 共用模型。

采用确认后的方案 3：

```text
任务保存 model profile 引用 + 参数覆盖项。
密钥仍由平台 Settings / secret store 管理。
```

任务不保存明文 API key。

第一版至少包含两个模型位：

```text
Schema Assistant Model
Extraction Model
```

后续可以扩展：

```text
Review Model
Fallback Model
```

任务级参数覆盖：

```text
temperature
max_tokens
response_format
batch_size
retry_on_invalid_json
rate_limit
```

这样可以让 schema 辅助使用理解能力更强的模型，而批量抽取使用成本更低、JSON 输出更稳定的模型。

## 模块七：Extraction Runs

Extraction Run 对冻结的 collection version 和冻结的 schema version 执行批量抽取。

运行前用户应看到确认信息：

```text
任务：AI 综述工具数据抽取
文献数：126
Schema：v2
字段数：18
Record unit：sample_level
抽取模型：任务中选择的 Extraction Model
预计输出：每篇论文 1 条或多条记录
```

运行中展示用户可理解的阶段：

```text
准备文献
构建 evidence packet
抽取字段
校验 JSON
保存结果
标记待审阅项
完成
```

Extraction Run 不应假设每篇论文只生成一条记录。系统应按照 record schema 和 record_unit，从每篇 included paper 中生成 0 条、1 条或多条 structured records。

记录结构：

```text
record_id
paper_id
record_type
record_unit
parent_record_id
record_identity
fields
evidence_packet_id
quality_flags
review_priority
status
```

每个字段保存：

```text
raw_value
normalized_value
unit
condition_context
confidence
evidence
source section/chunk
missing_reason
validation_status
model_output_trace
```

批量抽取必须支持失败恢复和局部重跑。每篇论文或每个 record 的处理状态至少包括：

```text
pending
running
succeeded
failed
skipped
needs_review
```

第一版至少应支持：

```text
retry_failed_only
rerun_selected_papers
rerun_selected_fields
```

后续可以扩展 pause、resume、cancel、retry_low_confidence_only。

运行界面应展示批处理状态：

```text
已处理 / 总数
成功数
失败数
待审阅数
模型调用次数
错误类型分布
```

如果模型供应商返回 token usage，应记录并展示实际 token 消耗；如果暂时不可得，可以先展示模型调用次数和平均耗时。

低质量或失败结果不能被静默隐藏，应进入 Review Table 并清晰标记。

## 模块八：Validation & Quality Flags

系统可以保留模型自评 confidence，但不能把它作为核心质量判断。结构化抽取的质量应主要由可解释的 quality flags 和 review priority 表达。

字段级或记录级 quality flags 包括：

```text
json_valid
type_valid
evidence_found
evidence_exact_match
unit_valid
enum_valid
cross_field_consistent
missing_required_field
condition_context_missing
value_conflict_detected
invalid_json
no_evidence
ambiguous_value
extraction_error
```

系统基于这些 flags 形成 review priority：

```text
low
medium
high
```

例如，`evidence_found + unit_valid` 可以降低审阅优先级；`condition_context_missing`、`value_conflict_detected`、`missing_required_field` 应提高审阅优先级。

质量标志的目标不是替代人工判断，而是让用户知道哪些记录最需要审阅。

## 模块九：Review Table

Review Table 是抽取完成后的主要工作界面。

它表现为一个结构化数据表：

```text
Paper | Year | Record | Field A | Field B | Quality Flags | Review Priority | Status
```

如果任务是 sample_level、experiment_level 或 condition_level，表格行应对应 record，而不是 paper。Paper metadata 作为行的上下文列展示。

用户可以：

- 按字段筛选。
- 按缺失值筛选。
- 按 quality flags 或 review priority 筛选。
- 按校验状态筛选。
- 按年份、论文、review priority、可选 confidence 或状态排序。
- 手动编辑字段值。
- 查看字段级 evidence。
- 接受 LLM 抽取值。
- 标记人工确认。
- 对单篇论文重新抽取。
- 对某个字段批量重新抽取。
- 查看或撤销人工修改记录。

人工修改应保存为 review event，而不是直接覆盖历史。

Review Table 采用 overlay 机制：

```text
base_record = 模型原始抽取结果
review_events = 接受 / 编辑 / 拒绝 / 重抽 / 锁定
effective_record = 当前表格显示和导出的结果
```

字段状态至少包括：

```text
unreviewed
accepted
edited
rejected
rerun_required
locked
```

人工确认或编辑后的字段默认 locked。局部重抽不能静默覆盖 locked 字段；用户必须显式选择“允许覆盖人工确认字段”。

Review event 记录：

```text
task_id
record_id
field_key
old_value
new_value
actor
reason
created_at
locked
```

## 模块十：Export Center

Export Center 负责任务级导出。

第一版导出格式：

```text
CSV
JSONL
Excel
Markdown evidence report
Data dictionary
```

导出模式需要支持宽表和长表：

```text
wide_table
long_table
nested_json
evidence_bundle
```

宽表适合人工查看和常规 Excel/CSV：

```text
paper_id | title | record_id | sample_name | flux | rejection | pressure | evidence
```

长表适合数据库、知识图谱和统计分析：

```text
record_id | paper_id | field_key | value | unit | evidence | status
```

导出选项：

```text
导出所有字段或选中字段
是否包含 evidence
是否包含 confidence
是否包含 paper_id / DOI / source_path
是否只导出人工确认记录
是否包含 missing values
是否包含 validation flags
是否导出 raw/base record 或 effective record
```

导出文件保存在任务目录，并展示导出历史：

```text
export_20260706_001.csv
export_20260706_002.xlsx
records_schema_v2.jsonl
data_dictionary_v2.md
evidence_report_v2.md
```

## 模块十一：Audit And Provenance

审计和溯源是横向要求。

系统必须保存：

- 候选文献如何被找到。
- 每篇文献为什么被纳入或排除。
- 是否使用 LLM 筛选。
- 使用了哪个 collection version。
- 使用了哪个 schema version。
- 使用了哪个 prompt contract version。
- 使用了哪个 evidence packet。
- 使用了哪个 model profile。
- 哪次 extraction run 生成了某个字段值。
- 哪些 quality flags 导致记录进入待审阅。
- 哪些值被人工修改过。
- 哪个 export 生成了某个文件。

用户应该能回答：

```text
这篇文献为什么在任务里？
这个字段值为什么这样抽取？
支撑证据在哪里？
它是哪个 schema 和哪个模型生成的？
它是否被人工编辑过？
它出现在哪个导出文件里？
```

## 第一版完整用户闭环

第一版完成后，用户应能完成以下闭环：

1. 新建数据抽取任务。
2. 通过 metadata / keyword 检索收集候选文献。
3. 通过 research question expansion 收集候选文献。
4. 对候选摘要 / metadata 运行 LLM relevance screening。
5. 人工确认 included papers 并冻结 collection version。
6. 自定义 record schema 和 field schema，并使用 LLM 辅助完善字段。
7. 冻结 schema version。
8. 选择任务级 Schema Assistant Model 和 Extraction Model。
9. 构建 evidence packet。
10. 对 included collection 批量运行结构化抽取。
11. 查看字段值、quality flags、review priority、证据和 review 状态。
12. 人工修正字段值，或对选中论文 / 字段重抽。
13. 导出宽表、长表、JSONL、Excel、evidence report 和 data dictionary。

## 第一版非目标

第一版不需要实现：

- 一个任务内多个主 schema。
- 一个任务内多个独立 collection。
- 外网文献搜索。
- 多轮迭代式 query expansion。
- 无用户确认的全自动纳入。
- 默认物理复制所有源文献。
- 自动迁移旧 schema 下的历史抽取结果。
- 协作审阅、角色分配或审核队列。
- 为抽取任务单独保存明文密钥。
- 通用 no-code 数据库构建器。

这些能力可以后续扩展，不影响第一版核心边界。

## 验收标准

### 功能验收

- 数据抽取工作台作为一级模块出现。
- 用户可以创建并重新打开任务。
- 候选文献可以通过 metadata / keyword 检索收集。
- 候选文献可以通过 research question expansion 收集。
- LLM screening 可以将候选标记为 include、exclude、uncertain。
- 用户可以确认 included papers 并创建 collection version。
- 用户可以定义 record schema 和自定义字段，并获得 LLM 辅助。
- Schema 可以冻结并版本化。
- Schema change metadata 可以记录字段新增、删除、拆分、合并、重命名和是否需要重跑。
- 任务级模型配置可以引用平台 model profile。
- Evidence Packet Builder 可以为抽取构建可追溯 evidence packet。
- Extraction run 绑定 collection version、schema version、prompt contract version、evidence packet 和 model profile。
- 抽取结果支持 paper_level 以外的 record_unit，并允许一篇论文生成多条记录。
- 抽取结果包含 raw value、normalized value、unit、condition context、证据、quality flags、review priority 和缺失原因。
- Review Table 支持 base record、review events 和 effective record。
- Review Table 支持查看、筛选、人工修正、锁定字段和局部重抽。
- Export Center 支持宽表、长表、JSONL、Excel 和 evidence report 导出。

### 产品验收

- 用户能清楚理解这是任务型工作台，而不是 Chat 附属功能。
- 用户能看到当前步骤和下一步动作。
- LLM 辅助可用，但不会隐藏关键决策。
- 文献纳入需要用户确认。
- 低置信和失败抽取结果可见、可处理。
- 质量判断主要通过 quality flags 和 review priority 表达，而不是依赖模型自评 confidence。
- 任务输出按任务归属，易于查找和复用。
- Structured Extraction Workbench 默认只读 Research Index，不污染原始文献库和主索引。

### 审计验收

- 每篇 included paper 记录 collection 来源和用户决策。
- 每个抽取字段值记录生成它的 run、schema、prompt contract 和 evidence packet。
- 每次人工修正被记录。
- 人工确认或编辑后的 locked 字段不会被局部重抽静默覆盖。
- 每个导出文件被记录在任务历史中。

## 建议分工模块

后续实现可以按以下 workstreams 拆分：

```text
1. Task Management
2. Collection Builder
3. Evidence Packet Builder
4. Schema Designer
5. Prompt Contract Compiler
6. Model Settings
7. Extraction Engine
8. Validation & Quality Flags
9. Review Table
10. Export & Provenance
```

这些模块边界与产品工作区和后端数据归属保持一致，便于后续分工和分阶段落地。

## 后续扩展方向

未来可以增加：

- 多轮 research question expansion。
- 一个任务内多个 collection。
- 一个任务内多个 schema。
- 跨任务 schema library。
- 自动 schema migration。
- 针对 uncertain candidates 的主动学习式筛选。
- 包含源文献和抽取结果的 snapshot package。
- 协作审阅和 reviewer assignment。
- 字段级质量指标。
- schema version 差异比较。
- 与 deep research workflow 集成。
