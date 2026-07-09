# Block 9: Report / Audit / Export

## Goal

把 Agent 的研究过程和结论导出为可交付、可审计、可复现的科研报告。

## Scope

包含：

- answer report。
- research report。
- research record。
- evidence table。
- source summary。
- citation audit summary。
- unresolved gaps。
- run manifest。
- Markdown export。
- Word export。
- quality report。

不包含：

- 中间 artifact 生命周期。
- retrieval ranking 细节。
- 登录和权限。

## Current State

当前已有 research record 和 Markdown export 基础能力。Chat 中可以打开研究记录，导出报告包含问题、检索、证据、artifact、citation audit 等信息。

## Target Capability

报告应该清楚区分：

- 用户问题。
- 检索策略。
- 使用的 corpus/index version。
- 证据表。
- 结论。
- 每个关键 claim 的 citation。
- 未解决问题。
- 证据不足或冲突。
- 生成时间和模型配置。
- artifact/run provenance。

## Design Questions

- 报告是 per-turn、per-session、per-run，还是三种都支持？
- 是否需要模板：brief answer、literature review、comparison report、deep research report？
- Word export 是否是必需，还是后续可选？
- 报告中是否展示 tool trace？
- citation audit warning 是否必须出现在报告首页？

## Interfaces And Data Concerns

重点接口：

- `/api/sessions/{id}/record`
- `/api/sessions/{id}/export`
- future: `/api/reports`
- future: `/api/reports/{id}/export.docx`

报告数据来源：

```text
messages
turns
search_results
evidence_items
artifacts
jobs
citation metadata
settings/model metadata
```

## Test And Acceptance

最小验收：

- 导出的 Markdown 包含 evidence table。
- 报告中每条 evidence 有 DOI/title/source_path。
- citation audit warning 被明确展示。
- no-evidence 回答不会被包装成确定报告。
- report 可以反查 session turn。

## Open Discussion

- 是否先定义一个标准 report schema，再生成 Markdown/Word？
- 是否让用户选择报告模板？
- 是否支持报告编辑后再导出？

