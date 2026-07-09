# Research Agent Capability Blocks

这个目录把完整科研 Agent 拆成 12 个可独立讨论、独立规划、独立验收的能力块。后续可以在不同会话中分别引用某个 block 文件继续细化，避免把所有设计塞进一个巨大 plan。

## Current Project Baseline

当前项目已经具备：

- `literature_search` 模块内接入完整本地 Research Agent。
- Settings 中可配置模型、API key、model profiles、Agent 参数、Retrieval 默认值、Memory 参数与 Diagnostics。
- API key 通过独立 encrypted secret store 保存，不写入普通 settings SQLite。
- Chat 已有 LLM tool-calling Agent 路径，并在 LLM 不可用时 fallback 到本地检索摘要。
- 会话、消息、turn、search result、evidence、job event、artifact link 已 SQLite 持久化。
- 左侧会话支持右键菜单：重命名、收藏、置顶、标签、归档、软删除。
- Research record / Markdown export 已有基础能力。
- `dev.sh` 支持一键开发启动。

因此后续重点不是重新补基础框架，而是把 `literature_search` 做成稳定、可信、可复用的科研工作流闭环。

## Capability Map

| Block | File | Purpose |
|---|---|---|
| Block 0 | [block-00-corpus-data-lifecycle.md](./block-00-corpus-data-lifecycle.md) | Research Index 身份、Home Health Dashboard、索引/资产覆盖和维护任务 |
| Block 1 | [block-01-configuration-runtime-readiness.md](./block-01-configuration-runtime-readiness.md) | 配置、模型、路径、运行就绪状态 |
| Block 2 | [block-02-retrieval-evidence-acquisition.md](./block-02-retrieval-evidence-acquisition.md) | 检索、证据获取、query plan、expand |
| Block 3 | [block-03-evidence-grounding-answer-permission.md](./block-03-evidence-grounding-answer-permission.md) | Claim-level grounding、引用、回答权限边界 |
| Block 4 | [block-04-tool-action-execution.md](./block-04-tool-action-execution.md) | 工具 schema、权限、执行稳定性 |
| Block 5 | [block-05-chat-agent-orchestration.md](./block-05-chat-agent-orchestration.md) | Chat Agent 决策、ReAct loop、工具选择 |
| Block 6 | [block-06-conversation-memory-research-state.md](./block-06-conversation-memory-research-state.md) | 会话记忆与研究状态 |
| Block 7 | [block-07-deep-research-task-engine.md](./block-07-deep-research-task-engine.md) | 长流程研究任务引擎 |
| Block 8 | [block-08-artifact-knowledge-assets.md](./block-08-artifact-knowledge-assets.md) | Artifact、知识资产、复用 |
| Block 9 | [block-09-report-audit-export.md](./block-09-report-audit-export.md) | 报告、审计、导出 |
| Block 10 | [block-10-user-experience-workbench-ia.md](./block-10-user-experience-workbench-ia.md) | 前端工作台信息架构 |
| Block 11 | [block-11-evaluation-observability-reliability.md](./block-11-evaluation-observability-reliability.md) | 评估、可观测性、可靠性、运维 |
| Block 12 | [block-12-management-collaboration-framework.md](./block-12-management-collaboration-framework.md) | 用户、课题组、管理员、权限与协作管理 |

## Suggested Discussion Order

建议优先讨论：

1. Block 0: Research Index Identity / Corpus Data Lifecycle
2. Block 2: Retrieval / Evidence Acquisition
3. Block 3: Evidence Grounding / Answer Permission
4. Block 11: Evaluation / Observability / Reliability
5. Block 5: Chat Agent / Orchestration
6. Block 6: Conversation Memory / Research State
7. Block 9: Report / Audit / Export
8. Block 8: Artifact / Knowledge Assets
9. Block 4: Tool / Action Execution
10. Block 10: UX / Workbench IA
11. Block 7: Deep Research Task Engine
12. Block 1: Configuration polish / platform readiness
13. Block 12: Management / Collaboration Framework

这个顺序不是实现顺序的硬约束，而是为了先稳住数据、证据、可信度和可验证性。

Block 12 面向后续课题组化和多人部署，建议在单用户 `literature_search` 研究闭环稳定后再展开实现，但可以提前规划数据模型和权限边界，避免前期设计阻碍后续扩展。
