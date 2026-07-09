# Block 10: User Experience / Workbench IA

## Goal

把底层大量能力组织成清晰的研究工作台，让用户沿着自然主路径完成提问、检索、看证据、深度研究、复用资产和导出报告。

## Scope

包含：

- 信息架构。
- Chat 主路径。
- Evidence Inspector。
- Artifacts 面板。
- Runs / Jobs 面板。
- Status / Diagnostics 面板。
- Advanced tools。
- 空状态。
- error/fallback 提示。
- right-click/session management。

不包含：

- 底层工具实现。
- corpus schema。
- LLM provider 接入。

## Current State

当前 Literature Search Workbench 有 Chat、Overview、Search、Paper、Evidence、Pack、Task、Run、Extract/Compare、Analysis、Artifacts 多个 tab。功能完整，但更像开发者工具面板，主研究路径还可以收敛。

## Target Capability

推荐最小信息架构：

```text
Chat
Search
Deep Research
Artifacts
Status
Advanced
```

右侧常驻或可切换 inspector：

```text
Evidence Inspector
Artifact Inspector
Job Timeline
Research State
```

核心用户路径：

```text
提问 -> Agent 检索 -> 展示证据 -> 生成回答 -> 展开来源 -> 保存资产 -> 深度研究 -> 导出报告
```

## Design Questions

- 当前 11 个 tabs 是否应收敛？
- Evidence Inspector 是否应该在 Chat 中常驻？
- Search tab 与 Chat 的边界是什么？
- Advanced tools 如何避免干扰主流程？
- job timeline 放在右侧、Deep Research 页面，还是全局抽屉？
- fallback/error 应该在哪里显示？

## Interfaces And Data Concerns

前端主要状态：

```text
active module
active session
active literature tab
selected evidence
selected artifact
active job
research state
settings readiness
```

## Test And Acceptance

最小验收：

- 新用户能从 Chat 完成一次检索问答。
- 用户能展开引用 evidence。
- 用户能从回答进入 research record/export。
- 用户能找到 job status 和 artifacts。
- Advanced tools 不阻断主流程。
- 错误/fallback 明确可见。

## Open Discussion

- 是否先画一个工作台 wireframe？
- 是否保留当前全部 tab，但通过分组减少复杂度？
- 是否需要“Research Home”总览页？

