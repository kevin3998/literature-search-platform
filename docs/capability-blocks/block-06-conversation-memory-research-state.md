# Block 6: Shared Research Workspace / Conversation Memory / Research State

## Goal

Block 6 的最终成果不是让某一个文献检索 Agent 拥有更长的聊天记忆，而是让平台形成一个可持续推进的课题工作区。

用户进入的一级对象应该是一个 Research Session / Research Workspace，而不是某个孤立 Agent 的聊天窗口。文献检索、证据获取、论文分析、综述生成、报告导出等能力都应该作为这个课题工作区下的 specialist subagents 存在。

最终体验是：

- 左侧侧边栏展示课题 / research sessions。
- 用户点进某个课题后，进入该课题的共享研究现场。
- 主界面仍然是自然语言对话，但对话背后由 Research Orchestrator 判断应该调用哪个 subagent。
- 每个 subagent 只负责自己的专业能力。
- 所有 subagents 共享同一个 Research State。
- 用户刷新页面、切换视图、稍后回来，都能从同一个研究状态继续推进。

一句话定义：

> Block 6 让每个课题成为一个可恢复、可审计、可交接、可由多个 subagent 共同推进的研究工作区。

> **实现注记（2026-06-28 确认）**：下文 §1–§12 是面向用户的最终形态愿景。具体的实现立场、
> subagent 的真实形态、数据模型边界与分期，以文末「实现立场与分期」一节为**权威约定**；当愿景叙事
> （尤其 §3/§4 把 subagent 描述成"被 Orchestrator 选择的独立智能体"）与该节冲突时，以该节为准。

## Final User-Facing Shape

### 1. 左侧侧边栏呈现课题，而不是孤立 Agent 会话

最终左侧侧边栏不应该主要呈现：

```text
文献检索 Agent 会话 A
分析 Agent 会话 B
报告 Agent 会话 C
```

而应该呈现：

```text
课题 1: LLM literature review agents
课题 2: RAG evaluation methods
课题 3: scientific claim verification
```

用户点击一个课题后，看到的是这个课题的完整研究现场。

这个研究现场里可以使用多个能力：

```text
[检索文献] [补充证据] [分析论文] [生成综述] [导出报告]
```

这些按钮是显式快捷入口，但不是唯一入口。用户也可以直接用自然语言提出任务，由系统自动判断该交给哪个 subagent。

### 2. 主界面呈现为 Research Workspace

进入某个课题后，界面上应该同时呈现三层信息：

第一层是 Conversation Timeline：

- 用户和系统的自然语言交互。
- 每一轮记录由哪个 subagent 响应。
- 每一轮记录产生了哪些 evidence、artifact、state update。

第二层是 Evidence / Artifact Workspace：

- 当前候选论文。
- 当前 evidence pool。
- 当前 evidence pack。
- 当前 artifact。
- 文献、证据、回答、artifact 之间的关联。

第三层是 Research State：

- 当前课题主题。
- 当前研究目标。
- 当前阶段。
- 已完成事项。
- 未解决问题。
- 已排除方向。
- 当前 gaps。
- 建议下一步。
- 可用 subagents 及其适用场景。

用户感受到的不是“我打开了一段聊天记录”，而是“我回到了上次离开的研究桌面”。

### 3. Research Orchestrator 自动选择 subagent

最终系统中应该存在一个面向用户的 Research Orchestrator。

用户不需要先手动判断“现在应该找文献、分析论文，还是写报告”。用户可以直接说：

```text
继续推进这个课题。
```

Orchestrator 应该读取当前 Research State，然后判断下一步应该调用哪个 specialist subagent。

例如：

- 用户说“看看还有没有 claim-level citation benchmark”，系统调用 Retrieval Agent。
- 用户说“把保留的几篇论文方法差异整理一下”，系统调用 Analysis Agent。
- 用户说“基于当前材料写一个综述提纲”，系统调用 Synthesis Agent。
- 用户说“导出当前研究记录”，系统调用 Report Agent。
- 用户说“继续推进整个课题”，系统根据 gaps、open questions 和 current stage 自动决定下一步。

这和 tool calling 的关系是：

```text
User request
  -> Research Orchestrator chooses specialist subagent
  -> Specialist subagent chooses tools
  -> Tools produce evidence / artifacts / state updates
  -> Shared Research State is updated
```

subagent 像更高层的 tool 一样被选择，但它不是一个简单函数，而是一组专业能力、工具、输入输出约定和状态写入权限的组合。

### 4. Subagents 是课题内的专业角色

Block 6 最终形态中，至少应明确这些 specialist subagents 的位置。

Retrieval Agent：

- 负责检索论文。
- 扩展 query。
- 获取 evidence。
- 建立 candidate paper set。
- 标记 coverage gaps。
- 生成或更新 evidence pack。
- 不负责深度理论分析和综述写作。

Evidence Agent / Evidence Curator：

- 负责整理、去重、归并 evidence。
- 标记 evidence 与 paper、section、chunk、turn 的关系。
- 标记 evidence 的状态，如 accepted、weak、needs review。

Analysis Agent：

- 读取已保留论文和 evidence pack。
- 负责比较论文、归纳方法差异、识别争议点。
- 不重新承担底层检索职责，除非请求 Retrieval Agent 补证据。

Synthesis Agent：

- 读取 analysis notes、accepted evidence 和 current artifact。
- 负责组织综述结构、生成论证链、形成草稿。

Report Agent：

- 负责审计链、引用、导出、格式化报告。
- 读取已有 state 和 artifacts，不重新发明研究过程。

Deep Research Agent：

- 负责后续长流程、多阶段任务编排。
- 可以跨多个 subagents 调度任务，但仍写回同一个 Research State。

这些 subagents 不应该形成互相割裂的会话。它们都是同一个课题工作区里的专业执行者。

### 5. Shared Research State 是所有 subagents 的共同上下文

Block 6 的核心呈现不是“某个 Agent 的 memory”，而是 Shared Research State。

这个 state 应该让用户清楚看到：

- 这个课题现在在研究什么。
- 已经检索过什么。
- 当前保留哪些论文。
- 当前排除了哪些论文或方向。
- 当前有哪些 evidence。
- 当前有哪些 artifact。
- 当前还有哪些 gaps。
- 下一步适合调用哪个 subagent。

典型呈现内容：

```text
Current Topic
当前课题主题。

Research Objective
当前研究目标。

Current Stage
例如 retrieval / evidence curation / analysis / synthesis / report。

Candidate Papers
当前候选论文集合，每篇论文有状态。

Evidence Pool
当前 evidence 集合，以及 evidence 与 paper / turn / artifact 的关系。

Accepted Evidence Pack
当前被保留、可交接给分析或写作 subagent 的证据包。

Completed Questions
已经回答或处理过的问题。

Open Questions
还需要继续检索、分析或验证的问题。

Excluded Directions
用户或系统明确排除过的方向。

Coverage Gaps
当前证据不足、检索不足或尚未覆盖的区域。

Active Artifact
当前正在生成或维护的草稿、报告、比较表或研究记录。

Suggested Next Actions
系统建议的下一步动作，以及建议调用的 subagent。
```

### 6. 文献检索 Agent 不越权成为分析 Agent

当前已经接入的平台能力主要是文献检索 Agent。Block 6 的最终设计必须避免把它错误扩展成全能研究 Agent。

用户在检索阶段说：

```text
继续刚才那个方向。
```

Retrieval Agent 合理的响应应该是：

```text
我们之前围绕 X 主题进行了检索，目前保留了 5 篇候选论文，排除了 2 个方向，已有 evidence 覆盖 A 和 B，但 C 方向还缺少证据。下一步可以继续扩展 C，或者把当前 evidence pack 交给分析 Agent。
```

它不应该直接承担完整的深度分析、综述写作或报告生成。

当用户要求分析时：

```text
把这几篇论文的方法差异整理一下。
```

系统应该由 Orchestrator 路由到 Analysis Agent，而不是让 Retrieval Agent 勉强完成。

这样职责不会矛盾：

- Retrieval Agent 负责找材料。
- Analysis Agent 负责理解和比较材料。
- Synthesis Agent 负责组织论证。
- Report Agent 负责输出和审计。
- Shared Research State 负责承接所有中间结果。

### 7. 用户既可以手动选择，也可以让系统自动判断

最终界面应该同时支持两种工作方式。

显式模式：

用户点击按钮：

```text
[检索文献] [分析证据] [生成综述] [导出报告]
```

系统直接调用对应 subagent。

自然语言模式：

用户输入：

```text
继续推进这个课题。
```

系统自动判断：

- 当前是否缺文献。
- 当前是否缺 evidence。
- 当前是否已经适合分析。
- 当前是否需要生成 artifact。
- 当前是否应该导出报告。

然后自动选择 subagent。

用户不需要理解系统内部有哪些 Agent，也能自然推进研究；但高级用户仍然可以明确选择使用哪个 subagent。

### 8. "继续" 的最终体验

Block 6 完成后，用户打开旧课题并输入：

```text
继续
```

系统不应该问：

```text
你想继续什么？
```

而应该根据 Shared Research State 给出类似响应：

```text
我们之前在研究 LLM literature review agents。当前阶段是 evidence curation。

已经保留 5 篇候选论文，其中 3 篇有较完整 evidence，2 篇还缺少方法细节证据。

已排除方向包括纯推荐系统和通用 chatbot memory。

当前 open questions 是：
1. 是否存在 claim-level citation benchmark。
2. 哪些系统支持可审计的 evidence trail。

建议下一步先调用 Retrieval Agent 补充 benchmark 相关证据，然后再把 evidence pack 交给 Analysis Agent 做方法比较。
```

这体现的是课题级记忆，而不是单轮聊天记忆。

### 9. Refresh / Reopen 后状态完整恢复

最终用户可以放心刷新页面、关闭浏览器、重启服务后回来。

恢复内容包括：

- 会话消息。
- 当前课题标题。
- 当前 research objective。
- 当前 stage。
- candidate papers。
- accepted / excluded / needs-review paper 状态。
- evidence pool。
- active evidence pack。
- linked artifacts。
- active artifact。
- open questions。
- completed questions。
- excluded directions。
- coverage gaps。
- suggested next actions。
- active jobs。
- 每轮由哪个 subagent 处理。

用户不需要从聊天记录里重新翻找上下文。

### 10. Evidence、Paper、Artifact、Turn 的关系清晰可见

最终系统应让用户能追踪：

- 某个回答由哪个 subagent 生成。
- 这个 subagent 使用了哪些 evidence。
- evidence 来自哪篇 paper。
- paper 为什么被保留或排除。
- artifact 是在哪一轮产生或更新的。
- artifact 使用了哪些 evidence。
- 当前 Research State 的某个结论来自哪些历史 turn。

这让研究状态可审计，而不是一个无法解释的自动摘要。

### 11. Session 管理不破坏研究资产

归档、软删除、收藏、置顶、标签等 session 操作应作用于课题入口，而不是破坏底层资产。

最终效果：

- 归档课题只会从默认列表隐藏。
- 软删除课题不应立即删除底层 artifacts。
- evidence 和 artifact 可以继续被审计或复用。
- 恢复课题后 Shared Research State 仍然可用。
- 后续跨课题复用 evidence pack 或 artifact 时，不依赖原聊天窗口仍然打开。

### 12. 最终演示路径

Block 6 完成后，应该能演示下面的完整用户路径：

1. 用户在左侧创建课题：`LLM agents for literature review`。
2. 用户输入：`帮我找 claim-level citation 和 literature review agent 相关论文。`
3. Orchestrator 判断需要检索，调用 Retrieval Agent。
4. Retrieval Agent 搜索论文、获取 evidence，写入 Shared Research State。
5. Research State 面板显示 candidate papers、evidence pool、coverage gaps。
6. 用户说：`保留第一篇和第三篇，排除纯推荐系统方向。`
7. Shared Research State 更新 paper status 和 excluded directions。
8. 用户说：`继续看看有没有 benchmark。`
9. Orchestrator 继续调用 Retrieval Agent，而不是启动分析。
10. 用户说：`把保留论文的方法差异整理一下。`
11. Orchestrator 判断这是分析任务，调用 Analysis Agent。
12. Analysis Agent 读取同一个 evidence pack，生成比较结果并写回 artifact。
13. 用户刷新页面。
14. 用户重新打开该课题。
15. Conversation、candidate papers、evidence、excluded directions、open questions、artifact 全部恢复。
16. 用户输入：`继续。`
17. Orchestrator 根据当前 state 建议下一步，并选择合适 subagent。

这条路径体现最终形态：

> 用户推进的是一个课题；subagents 是课题中的专业执行角色；Shared Research State 是所有动作共同维护的研究现场。

## Scope

包含：

- Research Workspace / Research Session 的最终呈现。
- Shared Research State 的最终用户可见内容。
- Conversation Memory 与 Research State 的关系。
- Orchestrator 自动选择 subagent 的最终体验。
- Subagent 作为课题内专业角色的边界。
- 检索、证据、分析、综合、报告之间的交接效果。
- session 恢复、归档、软删除后的用户可见行为。

不包含：

- 具体数据库表设计。
- 具体 API 实现。
- 具体 prompt 实现。
- Deep Research stage engine 的内部执行流程。
- Artifact 文件内容管理细节。
- 登录、多用户权限和课题组协作。

## Acceptance Criteria

最终验收不以“是否新增某张表”为标准，而以用户可见结果为标准：

- 用户打开旧课题时，可以看到完整 Research State，而不是只有聊天记录。
- 用户输入“继续”时，系统能基于课题状态恢复上下文并建议下一步。
- 系统能区分检索、分析、综合、报告等任务，并选择合适 subagent。
- Retrieval Agent 不越权承担深度分析和综述写作。
- 不同 subagents 共享同一个 Research State，而不是各自维护孤立会话。
- 用户显式点击能力按钮和自然语言请求都能触发正确 subagent。
- candidate papers、evidence、artifacts、turns、subagent actions 之间的关系可见。
- 刷新页面或重开课题后，Research State 完整恢复。
- 用户保留、排除、确认、否定过的内容会影响后续 subagent 选择和任务执行。
- 归档或软删除课题不会破坏底层 evidence 和 artifacts。

## 实现立场与分期（2026-06-28 确认，权威）

本节是 Block 6 的实现契约，覆盖 §1–§12 愿景叙事中与之冲突的部分。决策均已与负责人确认。

### 统一立场：subagent = 同一个 loop 上的「角色 profile」，不是独立智能体

- subagent **不是**独立 LLM agent，也**不**新增 Orchestrator/planner 的额外 LLM pass。它是同一个
  `AgentLoop` 上的一个**角色 profile**：`ToolSpec.agent_modes` 从 `{quick, deep}` 泛化为 role
  （retrieval / evidence / analysis / synthesis / report / deep_research），每个 role =
  「工具暴露子集 + 一段 prompt 片段 + 对 Research State 的写权限子集」三者的组合。复用 Block 4 已有的
  `specs_for_mode()` gating 机制。
- Orchestrator 退化为**轻量路由**，无独立 LLM pass：
  - 显式能力按钮（检索/分析/综合/导出）→ **确定性**地设置当前 role。
  - 自然语言（"继续"）→ 由现有单 agent 读取**注入的 Research State** 自行决定下一步，必要时做一次廉价
    分类，**不**新起 orchestrator 智能体。
- 这条立场与 [[block-05-chat-agent-orchestration]] 的"无额外 planner pass / deep-research 是 mode
  而非 agent / 拒绝确定性硬分类闸门"**一致**，不构成取代。deep_research 仍是一个 role/mode，不是平行路径。

### 容器与边界约定

- **课题 = session（1:1）**：复用现有 `sessions` 表，不引入新的父级实体。subagent 是课题内的**角色**，
  不是独立子会话。归档 / 软删 / pin / `build_record` / Block 0 首页导航全部复用。
- **stage 仅为建议性标签**（retrieval / evidence curation / analysis / synthesis / report），驱动
  "suggested next actions" 与按钮高亮，**永不**硬性 gating 任何 role —— 与 LLM 判断的立场保持一致。

### Research State 数据模型：派生投影 vs 被授权事实

为避免 §10 自己警告的"无法解释的自动摘要"，state 明确切成两类：

- **派生投影（derived，不落第二份库，按需重算，永远真实）**：candidate papers 集合、evidence pool、
  coverage gaps —— 来自已有的 `evidence_items` / `search_results.coverage_json` / `turns`。
- **被授权的事实（authored，落库且带 provenance）**：research objective、current stage、
  per-(session, paper) 状态（accepted / excluded / needs-review）、excluded directions、
  open / completed questions、suggested next actions。这些**不可派生**，只能由用户动作或 LLM 通过
  **结构化的 state-mutation 操作**写入，且每次写入都记录"哪个 turn / 哪个 role / 用户"作为来源
  （满足 §10 可审计）。**禁止**每轮让 LLM 整体重写一段 state blob。

注意：「candidate paper set 带状态」今天**不是**一等实体（论文散落在 `search_results.results_json`
与 `evidence_items` 中），需新增 per-(session, paper) 状态记录，不是简单投影。

### 分期

- **6a（本次实现，block 内核）**：
  - 数据模型：派生投影逻辑 + 新增 authored 实体（per-session-paper 状态表、session 级 research-state
    字段、state-event provenance 日志表）。
  - 只读 Research State 面板（三栏工作台的第三栏）。
  - 刷新 / 重开课题后 Research State 完整恢复。
  - 数据模型须**预留 state→prompt 注入出口**（供 6b 用），避免 6b 返工 `_memory_block`。
  - 6a 交付即满足大半验收：打开旧课题看到完整 state、刷新恢复、关系可见。
- **6b（已完成）**：状态策展的用户动作（论文保留/排除/待复核、excluded directions、open questions、
  objective、stage）+ 把 authored state 注入回 agent 上下文（`_memory_block` 顶部渲染"当前课题研究状态"，
  "继续"与"保留/排除影响后续"由此成立）。无 schema 变更，复用 6a 的写路径。
- **6c（已完成）**：多角色编排。role = 同一 loop 上的 profile（`agent/roles.py`：general/retrieval/
  evidence/analysis/synthesis/report，各含 tool 子集 + prompt 片段 + 建议 stage + 可强制 deep）。
  `ToolRegistry(role_tools=)` 把 mode 的工具集**交集**到角色子集（结构性阻止检索角色做分析）；
  `AgentLoop(role_prompt=)` 注入角色边界。轻量路由、无 planner pass：显式按钮确定性设 role，
  free-form chat 用 general（保留 6c 前行为）。每轮 role 落 `turns.role` + 助手消息 metadata，可恢复/可审计。

### 本 block 明确推迟

- 跨课题复用 evidence pack：`artifacts` 表已是 session 无关的（可复用），但 `evidence_items` 是
  session 作用域；跨课题证据复用需额外设计，推迟（原文 §11 本就写为"后续"）。
