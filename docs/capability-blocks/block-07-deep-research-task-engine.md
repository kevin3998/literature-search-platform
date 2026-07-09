# Block 7: Deep Research Task Engine

## Goal

把复杂科研问题从单轮 Chat 扩展为可规划、可执行、可恢复、可审计的长流程研究任务。

## Scope

包含：

- task definition。
- scope locking。
- subquestion decomposition。
- evidence coverage。
- stage transition。
- checkpoint。
- resume。
- retry。
- quality gate。
- final synthesis。
- job timeline。

不包含：

- 普通 Chat fallback。
- corpus 导入。
- 报告视觉排版。

## Current State

底层 Research Agent 已有 task/run/extract/compare/analysis/verify/quality/synthesize/notes 能力。平台已暴露长任务 API，并用 job + SSE 展示进度。前端已有 Task / Run / Extract / Analysis 等 tabs，但更像工具面板。

## Target Capability

Deep Research 是 task engine，而不是一堆按钮：

```text
define task
lock scope
plan subquestions
collect evidence
build pack
run extraction/comparison
verify claims
quality gate
synthesize
produce artifacts/report
```

Chat 可以建议启动 Deep Research，但任务执行和状态管理由 Task Engine 承担。

## Design Questions

- Deep Research 启动前是否必须让用户确认 scope 和目标？
- task plan 是否可以编辑？
- run 中断后如何 resume？
- quality gate failed 时是否阻止 final synthesis？
- Deep Research 结果是 report、artifact bundle，还是两者？

## Interfaces And Data Concerns

重点接口：

- `/api/literature-search/task/plan`
- `/api/literature-search/task/run`
- `/api/literature-search/run`
- `/api/literature-search/runs`
- `/api/literature-search/runs/{run_id}`
- `/api/literature-search/runs/{run_id}/resume`
- job stream endpoints

需要明确 task/run manifest schema 和 stage artifact schema。

## Test And Acceptance

最小验收：

- task plan 能生成 subquestions。
- task run 能产出 task artifact。
- full run 能产出 manifest、summary、stage artifacts。
- refresh 后历史 job/run 可恢复查看。
- run 失败时显示失败 stage 和 error。
- resume 能创建新 job 并链接旧 run。

## Open Discussion

- Deep Research 是否应从 Chat 中以“确认卡片”方式启动？
- 是否需要 Deep Research Dashboard？
- 是否先支持 quick deep-run，再做可编辑 plan？

