# Block 8: Artifact / Knowledge Asset Management

## Goal

把 Agent 产生的中间产物变成可浏览、可复用、可继续研究的知识资产，而不是一次性文件。

## Scope

包含：

- artifact index。
- artifact viewer。
- evidence pack。
- saved query。
- candidate list。
- extracted table。
- comparison matrix。
- analysis bundle。
- notes。
- artifact reverse links。
- pin/favorite/tag。
- continue from artifact。
- collections/topic folders。

不包含：

- 最终报告排版。
- corpus 导入。
- Chat tool selection。

## Current State

当前 ArtifactStore 可以扫描 `research_agent` 目录下的 packs、tasks、runs、extractions、comparisons、analysis_bundles、verifications、notes、syntheses、quality 等 artifacts。SQLite 中也有 artifacts 和 conversation_artifact_links。前端有 Artifacts tab 和 viewer 基础能力。

## Target Capability

每个 artifact 都有：

```text
artifact_id
artifact_type
title
summary
json_path
markdown_path
created_at
source_session_id
source_turn_id
source_job_id
linked_papers
linked_evidence
tags
favorite
usable_next_actions
```

用户可以从 artifact 继续：

- 追问。
- 创建 task。
- 生成 report。
- 加入 collection。
- 标记有用/无关。

## Design Questions

- Artifact metadata 是以文件为准，还是 SQLite index 为准？
- Artifact 修改是否允许回写文件？
- artifact tags/favorite 是全局还是 session-specific？
- “continue from artifact” 应该注入哪些 context？
- 是否需要 artifact collections？

## Interfaces And Data Concerns

重点接口：

- `/api/literature-search/artifacts`
- `/api/literature-search/artifacts/{artifact_id}`
- `/api/sessions/{session_id}/artifacts`
- future: artifact annotation APIs
- future: continue-from-artifact action

## Test And Acceptance

最小验收：

- 新 job 产生 artifact 后可被 artifact index 扫描。
- artifact 能反查 session/turn/job。
- artifact viewer 能展示 JSON summary 和 Markdown 内容。
- 从 artifact 继续追问时，Chat context 包含 artifact summary。
- archive/delete session 不破坏 artifact 文件。

## Open Discussion

- 是否需要 Notebook 概念？
- 是否把 evidence pack 作为一级资产？
- Artifact 是否要支持版本历史？

