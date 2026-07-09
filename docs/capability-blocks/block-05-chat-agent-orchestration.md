# Block 5: Chat Agent / Orchestration Loop

## Goal

让 Chat 成为唯一的普通研究入口。用户不需要理解或手动选择底层工具，只需要用自然语言表达研究目标；Agent 负责判断是否需要检索、复用证据、读取论文、构建证据包、生成对比、建议深度研究或直接作答。

Block 5 关注的是 **Agent 如何组织一轮研究对话**：

- 什么时候检索。
- 什么时候复用上一轮证据。
- 什么时候读取论文细节。
- 什么时候构建 pack / comparison / report。
- 什么时候停止调用工具并回答。
- 什么时候说明证据不足。
- 什么时候建议用户确认后进入深度研究。

工具的安全执行、权限、trace、错误恢复由 Block 4 负责；Block 5 只决定“该不该用、何时用、何时停、如何对用户表达过程”。

## Product Principle

最终产品不应表现为工具控制台，而应表现为文献研究对话工作台。

用户看到的是：

- 研究问题。
- Agent 的回答。
- 证据来源。
- 覆盖度与局限。
- 生成的研究产物。
- 任务进度。
- 引用/质量审计。

用户不应该看到或操作：

- Search tool。
- Paper chunks tool。
- Evidence expand tool。
- Pack tool。
- Extract / Compare tool。
- Verify / Quality tool。

这些都是 Agent 的内部动作。

## Scope

包含：

- Chat Agent system prompt / policy。
- ReAct loop 编排。
- quick / deep 研究模式边界。
- evidence reuse 策略。
- coverage / breadth 驱动的停止条件。
- deep research 建议与用户确认。
- 工具失败后的对话恢复策略。
- streaming step events 的用户语义。
- answer synthesis。
- fallback to retrieval summary。

不包含：

- 工具内部可靠性、权限、trace 细节（Block 4）。
- corpus 数据治理（Block 0）。
- 检索质量与 evidence acquisition 细节（Block 2）。
- claim-level grounding 细节（Block 3）。
- 深度任务引擎内部实现（Block 7）。
- 完整前端信息架构（Block 10）。

## Current State

当前系统已经具备基础 Agent loop：

```text
User message
-> system prompt + history + memory context
-> LLM tool calls
-> ToolRegistry / Tool Execution Layer
-> tool results back to LLM
-> final answer
-> citation / grounding audit
```

当前已有能力：

- LLM 可用时走 Agent path。
- LLM 不可用或 Agent disabled 时 fallback 到本地检索摘要。
- 支持 quick / deep answer mode。
- 支持 max iterations / tool budget。
- 支持 memory context 注入。
- 支持工具步骤 streaming。
- 支持 citation audit / grounding。
- Block 4 已经提供 ToolSpec、permission gate、job runner、structured error、tool trace。

当前仍需完善：

- Agent 选择工具主要依赖 prompt 自觉，缺少稳定的编排策略。
- quick / deep 对用户来说仍偏技术参数，需要转化为“快速回答 / 深度研究”的研究意图。
- coverage / breadth 对停止条件和深度研究建议的影响需要固化。
- 多轮追问何时复用 evidence、何时重新检索需要更明确。
- 工具失败后的恢复策略需要进入对话编排，而不只是返回 error。
- 过程状态需要隐藏工具名，改成用户能理解的研究动作。

## Target Experience

### 普通快速回答

用户提问：

```text
钙钛矿太阳能电池稳定性提升主要有哪些策略？
```

Agent 行为：

```text
检索证据
筛选可引用片段
必要时读取关键论文
回答并引用证据
展示覆盖度和来源
```

用户看到：

```text
正在检索证据...
正在筛选证据...
引用检查完成

回答正文 [E1][E2]

证据来源
覆盖度
引用审计
```

### 多轮追问

用户追问：

```text
那它们分别用了什么测试条件？
```

Agent 应优先判断这是不是上一轮主题的追问。如果 recent evidence 足够，应先复用已有 evidence 或读取相关 paper chunks，而不是盲目重新搜索。

如果用户明显切换主题：

```text
换成 MXene 膜材料呢？
```

Agent 应重新检索，而不是复用上一轮钙钛矿证据。

### 代表性概览与深度研究

当 coverage / breadth 显示当前证据只能支持代表性概览时，Agent 应明确说明：

- 当前回答不是完整综述。
- 本地库中可能还有更多候选文献。
- 如需完整覆盖，可以开始深度研究。

关键原则：

**quick 模式不自动升级 deep。**

如果需要更大范围研究，Agent 只建议：

```text
当前结果更适合作为代表性概览。是否开始深度研究？
```

用户确认后，下一轮才以 deep mode 执行。

### 深度研究

deep mode 是用户确认后的研究强度升级，不是工具菜单。

用户看到的动作应是：

- 开始深度研究。
- 正在运行研究任务。
- 正在生成对比。
- 正在整理报告。
- 深度研究完成。

而不是：

- run tool called。
- extract tool called。
- compare tool called。

deep mode 可以使用 Block 4 中已治理的 job-backed tools，例如 run、task_run、extract、compare。长任务进度通过 job events 展示。

## Orchestration Strategy

Block 5 不引入额外 planner LLM pass。为了保证速度和可维护性，最终方案采用：

```text
确定性 orchestration policy
+ 当前 ReAct loop
+ Block 4 Tool Execution Layer
```

原因：

- 额外 planner pass 会增加延迟。
- 多一个 LLM 决策层会增加不稳定性。
- 规则散落在多个 prompt 中会难维护。
- 当前系统已经有可用 ReAct loop，应该增强其边界，而不是重写为复杂多智能体结构。

推荐结构：

```text
User message
-> lightweight intent / context policy
-> prompt policy injection
-> ReAct loop
-> tool execution
-> coverage / breadth / error observation
-> stop or continue
-> answer synthesis
-> citation / grounding audit
-> user-visible result
```

这里的 policy 是确定性的轻量规则，不是单独的模型调用。

## Core Policies

### Mode Policy

quick mode：

- 默认模式。
- 适合普通问答、局部比较、多轮追问。
- 可以使用 read-only 工具和有限 state-creating 工具。
- 不自动触发 deep research。
- 不触发 admin / maintenance / destructive 动作。

deep mode：

- 只能由用户显式选择或确认。
- 适合综合综述、跨论文对比、指标抽取、报告生成。
- 可以使用 job-backed research tools。
- 需要展示任务进度和产物。

### No Auto Deep Escalation

这是 Block 5 的核心边界。

Agent 可以建议 deep research，但不能在 quick 模式中自行升级并启动 deep tools。

原因：

- deep research 会创建更多状态和长任务。
- 用户需要控制研究强度。
- 这与 Block 4 的权限边界一致。
- 可以避免用户只是问一个快速问题，却被带入复杂流程。

### Evidence Reuse Policy

Agent 应判断当前问题是否是追问。

可优先复用 evidence 的情况：

- “那它的实验条件是什么？”
- “这些方法有什么差异？”
- “上面第二篇用了什么材料？”
- “它的测试温度是多少？”

应重新检索的情况：

- 用户切换材料体系。
- 用户切换研究领域。
- 用户要求新的时间范围。
- 用户要求另一个 corpus/topic。
- 上一轮 evidence 与当前问题无明显关系。

复用 evidence 时，UI 可以轻量提示：

```text
基于上一轮证据继续分析
```

但不需要让用户选择工具。

### Coverage / Breadth Stop Policy

coverage 是回答是否充分的主要依据。

```text
sufficient -> 停止检索，直接回答。
partial -> 回答被支持的部分，并列出缺口。
weak -> 最多尝试一次更有针对性的补充检索；仍不足则说明限制。
none -> 不给事实结论，说明本地库没有可用证据。
```

breadth 是回答是否“全面”的依据。

```text
breadth_limited = true -> 必须称为代表性概览。
deep_research_suggested = true -> quick 模式中建议深度研究。
```

Agent 不应在证据有限时使用：

- “全面证明”
- “所有研究都表明”
- “完整综述”
- “该领域一致认为”

除非 deep research 已完成并且 evidence coverage 支持这种表述。

### Tool Failure Recovery Policy

Block 4 已经提供 structured error 和 recovery_hint。Block 5 应使用这些信息指导对话。

典型策略：

- `validation_error`: 不重复同样错误参数，修正或说明无法继续。
- `permission_denied`: 不重试；说明当前模式不支持，并建议用户确认深度研究。
- `paper_not_found`: 先搜索或请用户提供 DOI / paper_id / title。
- `timeout`: 缩小范围，或建议 deep research。
- `job_failed`: 告诉用户任务失败，并建议缩小问题或重试。
- `index_unavailable`: 明确说明本地索引不可用，不编造答案。

Agent 不应在同一个 turn 内反复调用相同失败工具造成循环。

### Stop Condition Policy

Agent 应停止调用工具并回答的情况：

- 已获得 sufficient coverage。
- 已达到 partial coverage，且补充检索收益有限。
- 已经执行过一次 targeted retry，但仍 weak。
- 工具预算接近耗尽。
- 用户问题可以基于 recent evidence 直接回答。
- deep research job 已完成并返回产物。

Agent 应停止并说明无法回答的情况：

- coverage 为 none。
- 本地库没有可用证据。
- 工具失败且 recovery_hint 需要用户补充信息。
- 当前模式不允许执行所需动作。

## User-visible Process Language

过程状态必须使用用户语义，不显示工具名。

推荐状态：

```text
正在理解研究问题
正在检索证据
正在筛选证据
正在读取关键论文
正在展开表格/图片证据
正在整理证据包
正在生成对比
正在进行深度研究
正在检查引用
正在检查研究质量
引用检查完成
```

避免显示：

```text
calling search
paper_chunks
pack
run
extract
compare
verify_answer
quality
```

## Interface Expectations

Chat stream events 面向用户体验应保持稳定：

```text
step
search_meta
papers
coverage
artifact
job
tool_trace
deep_research_suggestion
token
citation
grounding_status
error
done
```

其中：

- `step` 使用用户语义。
- `coverage` 决定回答边界。
- `deep_research_suggestion` 表示建议，不表示自动执行。
- `tool_trace` 可折叠展示，用于审计，不作为普通流程主界面。
- `artifact/job` 展示产物和进度。

## Acceptance Criteria

最终验收：

- Chat 是普通用户的唯一研究入口。
- 普通用户不需要手动进入 Search / Paper / Evidence / Pack / Task / Run / Extract / Analysis 工具界面。
- quick 模式不会自动升级 deep。
- coverage / breadth 不足时，quick 只建议深度研究并等待用户确认。
- 用户确认后，下一轮可用 deep mode 执行深度研究。
- 多轮追问能优先复用相关 recent evidence。
- 切换主题时不会错误复用上一轮 evidence。
- sufficient coverage 时 Agent 能停止检索并回答。
- weak / none coverage 时 Agent 不编造事实结论。
- 工具失败后不会在同一 turn 内反复绕圈。
- 过程状态简洁，不暴露底层工具名。
- Agent path 不增加额外 planner LLM pass，保持响应速度。
- 规则集中、可测试、可维护，不把关键策略散落在多个 prompt 中。

## Open Decisions

- “开始深度研究”的确认入口放在回答下方，还是右侧研究上下文面板。
- deep research 完成后，是否自动生成报告，还是只生成可打开的研究产物。
- 是否在回答中显式显示“本轮复用了上一轮证据”。
- partial / weak coverage 下，允许几次 targeted supplemental search。当前建议最多一次，避免拖慢和绕圈。
