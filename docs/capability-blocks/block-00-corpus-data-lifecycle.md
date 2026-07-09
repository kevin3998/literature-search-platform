# Block 0: Research Index Identity / Corpus Data Lifecycle

## Goal

接入并尊重本地文献库已经建立的 Research Index 身份层，确保 Agent 搜索、引用、生成报告和复用 artifact 时，都指向底层同一套可追溯、可更新、可验证的文献身份。

同时，将 Research Index Health 升级为平台启动/登录后的 Home Dashboard，让用户在进入具体研究工作前，先清楚知道本地文献库是否可用、索引是否完整、向量检索是否可用、最近维护任务是否成功。

这个 block 回答的问题是：Agent 搜的到底是哪一版 corpus？每篇文献的元数据、正文、图片、表格、补充材料、索引状态是否一致且可追溯？系统当前是否处于可信可用状态？

核心原则：

```text
不要在平台层另造 paper_id。
使用 research_agent/research_index.sqlite.papers.paper_id 作为 canonical paper identity。
```

## Scope

包含：

- 平台消费并透传底层 `paper_id`。
- Search、Evidence、Artifact、Report、Memory 使用同一 `paper_id`。
- 从 `doi` / `article_id` / `source_path` resolve 到底层 `paper_id`。
- 读取并展示 `papers`、`paper_sections`、`paper_chunks`、`paper_assets`、`vector_records` 覆盖状态。
- index version、indexed_at、mtime、data health checks。
- evidence 与 section/chunk/asset 位置绑定。
- vector index 构建、刷新和覆盖状态记录。
- Home Dashboard 展示 Research Index 健康状态、覆盖率、最近维护任务和关键风险。
- 在网页中触发受控的索引维护任务，例如 health check、refresh changed papers、build/rebuild vector index。
- 为后续管理员权限预留维护操作边界。

不包含：

- Chat Agent 如何选择工具。
- 具体回答如何生成。
- 前端报告展示细节。
- 平台重新实现文献导入、去重或 DOI 规范化主流程。
- 平台另建一套 canonical paper ID。
- 非管理员用户的索引变更能力。

## Current State

当前项目已经依赖 `/Users/chenlintao/paper-crawler-ops/literature_data` 和底层 `literature_research` 的现有索引。平台层可以读取 index status、vector status、search results、paper sections/chunks 和 artifacts。

本地库不是只有每篇文章目录下的 `meta.json`。实际 Research Index 已经在 `/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/research_index.sqlite` 中建立了 canonical paper registry：

```text
papers.paper_id text primary key
papers.article_id integer unique
papers.doi
papers.article_dir
papers.md_path
papers.metadata_json
papers.index_version
paper_sections.paper_id
paper_chunks.paper_id
paper_assets.paper_id
vector_records.paper_id
```

根据 2026-06-26 的本地检查：

```text
papers: 87091
distinct paper_id: 87091
distinct article_id: 87091
distinct lower(doi): 87091
paper_sections: 1773530, 覆盖 87091 篇
paper_chunks: 2984304, 覆盖 87091 篇
paper_assets: figure 581201, table 111313
papers.index_version: 全部为 3
vector_records: 0
```

因此当前缺口不是“平台需要生产 canonical paper metadata”，而是：平台层尚未把底层已有的 `paper_id` 全链路透传到 Search、Evidence、Artifact、Report、Memory。

另一个缺口是：当前 Research Index 的健康状态还没有成为平台首页级信息。用户进入系统后，不能一眼判断文献库、FTS、sections/chunks、assets、vector index、最近维护任务是否处于可信状态。

## Target Capability

每篇文献在平台中都使用底层 Research Index 已有的稳定 identity，并能被各层统一引用：

```text
paper_id
article_id
doi
title
authors
journal
year
site
article_dir
md_path
metadata_json
indexed_at
mtime
index_version
section_id
chunk_id
asset_id
asset_kind
source_path
chunk_count
fts_index_status
vector_index_status
vector_record_count
evidence_id
```

`meta.json` 仍然是重要的原始文献元数据来源；但平台应以 `research_index.sqlite.papers` 作为已索引、已规范化、可检索的 registry，而不是逐个扫描 `meta.json` 后另造身份。

Home Dashboard 的目标效果：

- 启动或登录后默认进入 Research Index Health 首页。
- 用户能一眼看到 corpus 是否可用、索引是否完整、vector 是否可用。
- 用户能看到当前 paper、section、chunk、figure、table、vector 覆盖情况。
- 用户能看到最近一次 index refresh、vector build、health check 的状态。
- 普通用户只能查看状态；后续管理员可以从网页触发维护任务。
- 维护任务运行时有清晰的状态反馈，而不是让用户猜测后台是否在工作。

## Design Questions

- 当前 API 返回的 search result / evidence item 是否已经携带底层 `paper_id`？如果没有，在哪一层补齐？
- `article_id` 作为底层唯一记录 ID，和 `paper_id` 在平台 memory/report/artifact 中应如何同时保存？
- `index_version`、`indexed_at`、`mtime` 如何进入 search result、evidence item 和 report source audit？
- vector index 为空时，平台如何清楚显示 vector coverage，而不是只显示 generic unavailable？
- figure/table/SI 缺失时如何标记，而不是静默失败？
- Home Dashboard 如何把 Research Index Health 作为首页级状态，而不是藏在 Settings 诊断里？
- 网页触发索引维护时，如何清楚区分普通用户只读能力和管理员维护能力？

## Interfaces And Data Concerns

需要逐步明确：

- 平台 `PaperRef` JSON 表达，直接基于底层 `paper_id`。
- Evidence item 如何引用 `paper_id + section_id/chunk_id/asset_id + index_version`。
- Artifact metadata 如何记录涉及的 `paper_id` 列表。
- Report export 如何输出 `paper_id`、DOI、source path、index version。
- Index status API 是否应返回 papers/sections/chunks/assets/vector coverage。
- Home Dashboard 如何表达 overall health、coverage、recent jobs、maintenance actions。
- Maintenance job 需要记录 action、status、started_at、completed_at、影响范围和错误摘要。

## Test And Acceptance

最小验收：

- DOI 精确查找能 resolve 到底层 `paper_id`。
- title 模糊查找结果包含底层 `paper_id`。
- search result、evidence item、report source 使用同一底层 `paper_id`。
- conversation memory 持久化 evidence 时保存 `paper_id`。
- report source audit 输出 `paper_id + doi + index_version`。
- source_path、markdown_path、figure/table/SI path 不存在时可被检测并报告。
- index status 能显示 papers/sections/chunks/assets/vector coverage 与 index version。
- 启动/登录后首页展示 Research Index Health，而不是默认进入空白或单一 Chat 页面。
- Health 首页能明确显示 vector index 未构建或覆盖不足等 warning。
- 管理员维护入口能从网页触发 health check、index refresh、vector build 等任务，并显示任务状态。
- 普通用户无法执行索引变更操作，但仍能查看健康状态。

## Open Discussion

- 平台 SQLite 是否只缓存会话内用到的 `PaperRef` 快照，而不是缓存全库 paper metadata？
- Home Dashboard 的首屏应该优先展示哪些健康指标？
- 管理员维护操作第一版开放到什么粒度：只允许 refresh changed papers 和 vector build，还是允许完整 rebuild？
- 是否需要在首页展示最近 crawler/import/run 记录，帮助解释 corpus 变化？
