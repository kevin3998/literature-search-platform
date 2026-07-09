# Block 11: Evaluation / Observability / Reliability / Operations

## Goal

建立一套能持续判断 Agent 是否变好、为什么出错、如何恢复的评估与可观测体系。

## Scope

包含：

- regression cases。
- retrieval eval。
- citation eval。
- no-evidence refusal test。
- multi-turn memory test。
- report structure test。
- backend tests。
- frontend build。
- smoke scripts。
- diagnostics。
- observability。
- structured logs。
- job recovery。
- backup/restore。

不包含：

- 具体 UI 视觉设计。
- LLM provider 商业策略。
- 多用户权限系统。

## Current State

当前已有后端 pytest、前端 build 验证、Settings diagnostics、job events、citation audit metadata、research record/export。最近 baseline 为 backend tests 32 passed、frontend build passed。

## Target Capability

Evaluation 判断“好不好”：

- DOI 精确检索是否命中。
- title 模糊检索是否命中。
- section 展开是否正确。
- 回答是否全部带 citation。
- citation 是否真实对应 evidence。
- no-evidence 是否拒绝硬答。
- 多轮追问是否复用上一轮 evidence。
- report 是否包含 evidence table 和 unresolved gaps。

Observability 判断“为什么不好”：

- 本次回答用了哪些工具。
- 每个工具耗时多少。
- 检索命中了哪些库。
- 哪些 evidence 被引用。
- 哪些 evidence 被丢弃。
- 是否触发 fallback。
- 是否发生 citation audit warning。
- job 卡在哪个 stage。
- 失败原因是什么。

## Design Questions

- 固定 regression cases 存在哪里？
- 是否需要 `smoke.sh` 一键验证？
- tool trace 存 SQLite 还是只写日志？
- LLM token usage 是否记录？
- Diagnostics 是否显示最近失败 turn/job？
- 评估是自动跑，还是手动触发？

## Interfaces And Data Concerns

建议 per-turn trace shape：

```text
turn_id
session_id
model_provider
model_name
memory_context_summary
tool_calls
retrieval_summary
evidence_selected
evidence_discarded
fallback_reason
citation_audit
token_usage
latency_ms
errors
```

建议 smoke checks：

```text
backend health
settings effective
active model profile
research selfcheck
index status
search smoke
chat agent smoke
citation audit smoke
frontend build
```

## Test And Acceptance

最小验收：

- 一条命令能跑核心 smoke。
- 每轮 Chat 可查看 tool trace。
- citation warning 可被 report/export 带出。
- job failed 后可查看 stage 和 error。
- Diagnostics 单项失败不导致页面崩溃。
- 备份说明覆盖 SQLite + artifacts + secret store。

## Open Discussion

- 是否先建立 20 个固定科研问题作为评估集？
- 是否需要可视化 trace viewer？
- 是否将 observability 接入前端 Research Record？

