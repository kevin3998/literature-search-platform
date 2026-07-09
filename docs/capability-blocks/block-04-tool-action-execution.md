# Block 4: Tool / Action Execution / Permission Boundary

## Goal

让 Agent 使用的每个工具都有清晰 schema、权限边界、执行结果和错误恢复策略。

产品目标上，工具应作为 Agent 的内部执行能力，而不是普通用户需要手动操作的 Workbench 功能。用户表达研究目标，Agent 自动调用 search、paper reading、evidence pack、run、extract、compare、verify、quality 等工具；界面只展示回答、证据、覆盖度、产物、任务进度和审计结果。

## Scope

包含：

- tool definitions。
- input validation。
- output normalization。
- timeout。
- retry。
- error recovery。
- permission boundary。
- read-only tools。
- state-creating tools。
- state-mutating tools。
- tool trace。
- Agent-internal tool execution contract。
- 自动工具调用后的 user-visible result/events/artifacts 映射。

不包含：

- Agent 何时选择某个工具。
- 完整 UI 信息架构。
- 底层 corpus 导入策略。
- 普通用户手动调用 Search / Paper / Evidence / Pack / Task / Run / Extract / Analysis 等工具控制台。

## Current State

当前 `ToolRegistry` 已把 Research Agent 能力包装为 LLM tools，包括 search、paper sections/chunks、evidence expand、pack、task_run、run、extract、compare、verify_answer、quality。工具结果会写入 session store 或产生 events。

当前前端 Workbench 仍暴露 Search、Paper、Evidence、Pack、Task、Run、Extract/Compare、Analysis、Artifacts 等人工工具 tabs。这是早期调试/能力验证形态，不是目标产品形态。Block 4 后续实现应把这些能力归入 Agent 自动调用和结果展示，不再把普通用户引导到逐个工具手动执行的流程。

当前实现已经具备“可调用”的基础，但还不是完整 Tool Execution Layer：

- quick/deep 只有粗粒度 gating，没有 read-only / state-creating / state-mutating / admin / destructive 等正式权限层。
- LLM tool 路径与 API/Workbench 路径执行策略不一致；部分长任务在 API 中走 job runner，但在 LLM tool 中直接同步调用 service。
- 工具事件、job events、artifact records 已存在，但缺少统一 tool trace。
- 工具失败通常只返回 `{"error": "..."}`，缺少结构化错误码、retryable 标记和 recovery hint。
- 没有按工具配置 timeout / retry / confirmation policy。
- LLM tool schema 与后端 Pydantic request schema 有差异，缺少 schema version 和统一来源。
- 用户可见结果与内部 tool result 尚未形成稳定映射；删除人工工具 tabs 后，需要保证证据、覆盖度、产物、任务进度和审计仍清晰可见。

## Target Capability

Block 4 最终应提供一个独立的工具执行层：

```text
AgentLoop
  -> ToolExecutionLayer
  -> ToolSpec Registry
  -> Permission Gate
  -> Input Validator
  -> Execution Adapter
       -> direct short tool
       -> job runner long tool
  -> Result Normalizer
  -> ToolTrace Recorder
  -> User-visible Event Mapper
  -> compact tool result back to LLM
```

工具使用形态：

- 用户不可见工具名，不需要手动选择工具。
- 普通研究流程从 Chat 进入，由 Agent 自动调用工具。
- 工具执行过程以简短状态、证据来源、coverage、artifact、job progress、citation audit 展示。
- 不保留普通用户可见的高级工具/调试工具区。
- 管理维护类动作（例如 index refresh、vector build）不进入普通 Workbench；只能在系统健康/维护场景中按权限触发。

工具按权限分层：

Read-only tools:

- search
- paper lookup
- paper sections
- paper chunks
- evidence expand
- table lookup
- figure lookup
- artifact read
- status read

State-creating tools:

- create evidence pack
- create task
- create run
- create extraction
- create comparison
- create report
- save note

State-mutating tools:

- resume task/run
- update artifact metadata
- tag/favorite/archive
- refresh index
- rebuild vector index
- delete/restore artifact

不同 Agent mode 暴露不同工具：

- quick chat: read-only first, limited temporary state creation。
- deep research: state-creating tools。
- admin/maintenance: index refresh / vector build / destructive mutation。

这些 mode 是内部工具暴露策略，不是用户需要理解或手动操作的工具菜单。若前端需要展示 mode，也应以“快速回答 / 深度研究”这类研究意图表达，而不是直接展示底层工具。

工具暴露应分为三类：

Agent Auto Tools:

- 由 Agent 自动调用，普通用户不可见工具名。
- 例如 search、paper_chunks、evidence_expand、pack、extract、compare、verify_answer、quality。

User-visible Actions:

- 用户看到的是业务动作，不是底层工具。
- 例如“快速回答”、“开始深度研究”、“生成报告”、“检查引用”。

Admin Maintenance Actions:

- 仅在系统健康/维护场景出现。
- 例如 health_check、index_refresh、vector_build。
- 不进入普通文献研究 Workbench，不作为 Agent 普通自动工具。

## ToolSpec Contract

每个工具应注册为一个结构化 `ToolSpec`，而不是只存在于 `_QUICK_TOOLS` / `_DEEP_TOOLS` 列表中。

```text
name
display_name
description
schema_version
input_schema
output_schema
permission_level
agent_modes
execution_mode
timeout_seconds
retry_policy
requires_confirmation
state_change_type
artifact_types
visible_event_mapping
recovery_hints
tests
```

推荐字段含义：

- `permission_level`: `read_only` / `state_creating` / `state_mutating` / `admin_maintenance` / `destructive`。
- `agent_modes`: `quick` / `deep` / `admin` 中允许暴露的内部 mode。
- `execution_mode`: `direct` / `job_required` / `job_preferred`。
- `requires_confirmation`: 对 state-mutating、admin、destructive 工具为 true；确认应通过自然语言或业务动作，不展示底层工具按钮。
- `visible_event_mapping`: 定义工具结果如何映射到用户可见的 evidence、coverage、artifact、job progress、citation audit。

## Initial Tool Matrix Direction

v1 不急于新增大量工具，先治理当前已有能力。

| Tool | Permission | Agent Exposure | Execution | User-visible result |
|---|---|---|---|---|
| search / acquire_evidence | read_only | quick/deep | direct | papers, evidence, coverage, breadth |
| paper_sections | read_only | quick/deep | direct | optional paper structure summary |
| paper_chunks | read_only | quick/deep | direct | citable supporting evidence |
| evidence_expand | read_only | quick/deep | direct | table/figure/evidence detail |
| pack | state_creating | quick/deep | job_preferred | evidence pack artifact, evidence summary |
| task_run | state_creating | deep | job_required | task artifact, job progress |
| run | state_creating | deep | job_required | run artifact, job progress, report links |
| extract | state_creating | deep | job_required | extraction artifact |
| compare | state_creating | deep | job_required | comparison artifact/table |
| verify_answer | read_only | deep or post-answer internal | direct/job_preferred | citation audit |
| quality | read_only | deep or post-answer internal | direct/job_preferred | quality warnings |
| artifact_read | read_only | internal/result rendering | direct | artifact preview |
| status_read | read_only | internal/system status | direct | readiness/status indicator |
| run_resume | state_mutating | not ordinary Agent v1 | job_required | resumed job progress |
| index_refresh | admin_maintenance | not ordinary Agent | job_required | maintenance progress |
| vector_build | admin_maintenance | not ordinary Agent | job_required | maintenance progress |
| delete/restore artifact | destructive | not v1 | job_required | audit-only after confirmation |

## Execution Policy

Direct tools:

- 适合短、只读、可快速失败的工具。
- 必须有 timeout。
- 失败返回结构化错误，不抛出到 Agent loop。

Job tools:

- 长任务、创建 artifact、维护任务必须走 job runner。
- LLM 调用这类工具时，不应长时间同步阻塞。
- Agent 可获得 job id、状态摘要、必要的最终 artifact 摘要。
- 前端通过 job events 展示进度。

Retry policy:

- read-only 检索类工具可允许少量 retry。
- state-creating 工具谨慎 retry，避免重复 artifact。
- state-mutating、admin、destructive 工具默认不自动 retry。

Timeout policy:

- `search`、`paper_sections`、`paper_chunks`、`evidence_expand` 使用短 timeout。
- `pack`、`task_run`、`run`、`extract`、`compare` 通过 job runner 管理长执行。
- timeout 必须写入 tool trace，并映射为用户可理解的进度/失败状态。

Confirmation policy:

- 普通自动工具不要求用户看见底层工具名。
- state-mutating / admin / destructive 动作需要确认时，确认文案必须以业务语义表达，例如“是否刷新索引？”而不是“是否调用 index_refresh tool？”。
- quick chat 不允许触发 admin maintenance 或 destructive 动作。

## Error And Recovery Contract

工具错误返回应统一为结构化格式：

```json
{
  "ok": false,
  "error": {
    "code": "paper_not_found",
    "message": "No paper matched the provided DOI.",
    "retryable": false,
    "recovery_hint": "Run search first or ask the user for DOI, paper_id, or article_id."
  }
}
```

典型 error code：

- `validation_error`
- `permission_denied`
- `confirmation_required`
- `timeout`
- `job_failed`
- `paper_not_found`
- `artifact_not_found`
- `index_unavailable`
- `vector_unavailable`
- `external_provider_unavailable`
- `unknown_error`

LLM 可读取 `recovery_hint` 来决定下一步；前端可读取 `message` 和 `code` 展示简短失败状态。

## Design Questions

- quick mode 是否允许创建 evidence pack？
- state-changing tool 是否需要用户确认？如果需要，应通过自然语言确认或明确业务动作确认，而不是展示底层工具按钮。
- long-running tools 是否必须走 job runner？
- 工具失败是否应该给 LLM 可读的 recovery hint？
- tool schema 是否需要版本号？
- 现有 Workbench 人工工具 tabs 删除后，哪些执行结果必须保留在 Chat 右侧/回答下方展示？

## Interfaces And Data Concerns

每次工具调用应有 trace：

```text
tool_call_id
tool_name
schema_version
permission_level
agent_mode
arguments
started_at
completed_at
latency_ms
status
error_code
error_message
recovery_hint
result_summary
artifacts_created
jobs_created
state_changed
visible_events
```

Tool trace 应进入 session/research record，并能被后续 report audit、debug、evaluation 使用。trace 中的 arguments 需要考虑脱敏策略：API key、provider secret、绝对敏感路径等不应原样写入普通记录。

工具结果应拆成两份：

- compact result for LLM：短、结构化、可用于继续推理。
- visible events for UI：证据、coverage、artifact、job progress、citation audit、quality warning。

不要把底层 JSON 原样作为普通用户主要体验。

## Test And Acceptance

最小验收：

- quick mode 不会触发 index refresh 或 destructive mutation。
- state-changing tools 有明确 artifact/job/session link。
- 工具参数非法时返回结构化错误，不让 Agent 崩溃。
- timeout 被记录并展示。
- long job 工具通过 job events 可追踪。
- 普通用户 Workbench 不再暴露 Search / Paper / Evidence / Pack / Task / Run / Extract / Analysis 工具控制台。
- Chat 正常使用路径中，Agent 自动调用工具并展示必要的证据、覆盖度、artifact、job progress 和引用审计。
- 每个 Agent tool 都有 ToolSpec，包含 permission、execution_mode、timeout/retry、visible_event_mapping。
- LLM tool 路径和 API/job 路径对长任务使用一致的 job runner 策略。
- tool trace 能在一个 turn/research record 中复盘工具调用顺序、耗时、结果、错误和产物。
- 常见失败（validation、not found、timeout、permission denied、job failed）都有结构化 error 和 recovery_hint。
- 管理维护动作不会被普通 Agent 自动触发。

建议 regression tests：

- quick mode 只暴露 read-only 和允许的 limited state-creating tools。
- deep mode 暴露 state-creating tools，但长任务返回 job/link 可追踪。
- admin maintenance tools 不出现在 ordinary Agent definitions。
- 非法参数返回 `validation_error`。
- disabled/unauthorized tool 返回 `permission_denied`。
- direct tool timeout 产生 trace。
- job tool 创建 job、stream event、record artifact。
- tool failure 不导致 Agent loop 崩溃，并能继续给出可解释失败信息。

## Open Discussion

- 是否需要 tool permission 设置页？若需要，应偏系统/管理员设置，不作为普通研究 Workbench 的工具入口。
- 是否把 state-changing tool 默认改成“建议操作”，由用户通过自然语言或业务动作确认？
- 是否为每个工具建立单独 regression tests？
