# Block 1: Configuration / Runtime Readiness

## Goal

让用户清楚知道当前 Agent 是否可运行、由哪个模型驱动、使用哪套数据路径、哪些能力可用、哪些能力会 fallback。

## Scope

包含：

- Settings。
- model profiles。
- encrypted API key / secret store。
- active provider/model/base_url。
- Agent enabled、quick/deep mode、tool budget。
- Research Agent code dir、data dir、memory DB、artifact root。
- retrieval defaults。
- vector/index status。
- diagnostics。
- fallback reason。
- CC Switch 或其他外部配置导入（后续实现，不纳入当前 Block 1 v1 验收）。

不包含：

- Corpus 本身的数据质量治理。
- 具体 retrieval ranking 逻辑。
- Chat Agent prompt 策略。

## Current State

当前项目已经具备 Settings 页面，可以在 Models 中配置 API、provider、base URL、model 和多套 model profiles。API key 通过 encrypted secret store 保存。Agent 参数、Retrieval 默认值、Memory 参数、Research Agent 路径和 Diagnostics 也已经存在。

## Target Capability

Settings 不做独立总览首页，而是参考 Codex 设置的轻量分类导航，让配置项按用户心智分组，同时在相关分类内就地显示 runtime readiness：

- 当前 active model 明确可见。
- Agent Ready / Not Ready 原因明确。
- Research Agent import、selfcheck、index、vector 状态明确。
- Memory DB 与 artifact root 可见。
- 配置优先级可解释。
- fallback 到检索摘要时，UI 能说明触发原因。
- 为后续 CC Switch 快捷导入预留位置；当前 v1 不实现导入流程。

入口形态：

- Settings 入口从 TopBar 迁移到左侧 Sidebar 底部。
- 点击底部入口时，先打开账户/设置菜单：
  - 已通过 API 密钥登录（当前只读状态，后续接入真实登录）。
  - 设置。
  - 退出登录（当前占位，后续接入登录体系）。
- 点击“设置”后进入 Settings 页面。

Settings 窗口形态：

- 点击“设置”后打开居中的 Settings modal，而不是进入整页设置。
- 背景应用内容保留但加半透明遮罩，强调这是工作台级弹窗。
- modal 左侧为一层设置导航栏。
- modal 右侧为当前分类内容区。
- 右上角提供关闭按钮；点击遮罩或 Esc 可关闭。
- 不需要“返回应用”，关闭窗口即可回到当前工作台状态。
- 左侧分类使用产品化命名，避免直接暴露工程模块层级。
- 左侧只保留一层分类导航，不使用树形目录、展开项或二级导航。
- 分类内部的字段分组只在右侧内容区呈现，形式类似 Claude Settings。
- 不做首页总览卡片；ready / warning / fallback 信息嵌入对应分类。
- 窗口建议宽度约 900-1040px，高度不超过视口 85%-90%；内容区独立滚动。

建议分类：

- 账户：本地用户 / API key 登录状态占位，后续接入真实登录、个人资料和退出登录。
- 常规：平台名称、默认模块、默认 Literature tab、基础启动行为。
- 外观：主题、紧凑模式、debug JSON 等显示偏好。
- 模型：model profiles、provider、base_url、model、API key、model test；预留 CC Switch 导入位置但 v1 不实现。
- 智能体：Agent enabled、quick/deep、tool budget、citation enforcement、fallback behavior。
- 检索：retrieval defaults、index/vector 状态、retrieval fallback reason。
- 环境：Research Agent code dir、data dir、memory DB、artifact root、Diagnostics。

## Design Questions

- Settings 是否需要总览首页？
  - 当前决策：不需要。采用 Claude 风格居中 modal + 分类导航，更轻量，避免把 Settings 做成另一个 dashboard。
  - readiness 信息仍然需要，但应出现在“模型 / 智能体 / 检索 / 环境”等相关分类内。
- `models.api_key_source` 是否要区分 env/profile/stored/none 并在 UI 强提示？
- CC Switch 导入是否只做 preview + explicit import，不自动覆盖 active profile？
  - 当前决策：后续实现；不纳入本轮 v1 验收。
- 是否允许不同模块使用不同 model profile，还是平台级单 active profile？
- Settings 错误是否要进入 Diagnostics history？
- 退出登录在未接入账号系统前是否只做 disabled/占位？
  - 当前建议：保留菜单项，但标记为后续接入，不触发破坏性行为。

## UX Rationale

这种形式比 Settings 总览页更直观，原因是：

- Settings 是低频配置入口，用户通常带着明确目标进入，例如换模型、改路径、看索引状态。分类导航比总览页更快到达目标。
- 左侧底部入口符合 Codex、ChatGPT、Slack 等工具型产品习惯：设置属于账户/工作台级操作，不应该占用顶部任务栏主空间。
- 居中 modal 符合 Claude 的设置体验：用户不会离开当前工作台上下文，关闭后能回到原来的会话 / workbench 状态。
- 先弹出账户菜单为后续登录、多用户、退出登录、profile 切换预留位置，不需要以后重做入口。
- 不做总览可以降低早期 UI 复杂度；runtime readiness 仍保留为局部状态提示，不丢能力。

最终分类目录：

```text
Settings modal
├─ 账户
├─ 常规
├─ 外观
├─ 模型
├─ 智能体
├─ 检索
└─ 环境
```

左侧导航只显示上面这一层。每个分类的右侧内容可以分段，但这些分段不进入左侧目录。

右侧内容分组：

```text
账户
- 登录状态：已通过 API 密钥登录（只读占位）
- 个人资料：本地用户、角色、登录方式（占位）
- 后续动作：编辑资料、修改密码、退出登录（disabled/占位）

常规
- 基础：平台名称、默认启动模块、默认 Literature tab
- 会话：自动生成 session title、显示归档会话
- 开发：显示 Debug JSON

外观
- 主题：light / system
- 布局：紧凑模式

模型
- 当前生效模型：provider、model、base_url、API key source、Agent Ready / Not Ready
- Model profiles：新增、编辑、删除、激活、reveal/copy key、测试连接
- 高级参数：temperature、max_tokens、timeout_seconds、retry_count
- 导入：预留 CC Switch preview/import 入口，当前 v1 不实现

智能体
- 运行：Agent enabled、Agent Ready / Not Ready、fallback mode
- 回答模式：quick / deep
- 工具调用：max_tool_iterations、tool_budget
- 证据约束：enforce_citations
- 上下文策略：auto_use_previous_evidence、context_message_limit、context_search_limit、evidence_limit_multiplier

检索
- 默认参数：default_retrieval、default_scope、default_profile、Top K、evidence_per_article_limit、expand_assets、year_from/year_to
- 状态：index status、vector status、vector fallback reason

环境
- Research Agent：code dir、data dir、artifact root、import/selfcheck status
- Storage：memory DB path、DB exists/size、sessions/messages/evidence/jobs/artifact links count
- Diagnostics：backend health、settings DB、memory DB、selfcheck、index/vector、LLM config、artifact root、failed jobs
```

需要避免的问题：

- 分类命名不能过度产品化到看不懂。比如“模型”里必须清楚显示 model profiles / API key / provider。
- Diagnostics 不应完全藏起来；环境分类里仍要能一键刷新诊断。
- Agent Not Ready / fallback reason 必须在 Chat 发生 fallback 时可见，不能只藏在 Settings。

## Interaction Constraints

导航 v1：

- 左侧只显示一级分类，不提供搜索框。
- 不使用树形目录、展开项或二级导航。
- 如后续设置项明显增多，再考虑增加搜索；当前 v1 保持 Claude 风格的轻量分类列表。

保存策略：

- 沿用当前分类级 Save / Reset，不做即时保存。
- 用户在某个分类内修改后，该分类显示 dirty 状态。
- Save 只提交当前分类相关字段；Reset 只重置当前分类草稿。
- API key、model profile reveal/copy、model test 属于显式动作，不通过普通 Save 隐式触发。
- 关闭 Settings 时如果有未保存修改，需要提示保留/放弃；v1 也可先阻止关闭并要求保存或重置。

只读与可编辑边界：

- Research Agent code dir、data dir、memory DB path、artifact root 在 v1 只读展示。
- index/vector/selfcheck/diagnostics 在 Settings 中只读刷新，不提供维护或重建动作。
- Memory DB stats、job counts、artifact links counts 只读展示。
- 路径编辑、索引维护、向量重建属于后续能力或 Block 0/Home Dashboard 管理动作，不放入 Block 1 Settings v1。

窗口与响应式：

- v1 优先桌面宽屏体验。
- modal 建议宽度 900-1040px，高度不超过视口 85%-90%。
- 小于最小宽度时可以保持可滚动，不要求完整移动端适配。
- 后续如需要移动端，可将左侧一级分类压缩为顶部 select / segmented control，但不在 v1 范围内。

## Runtime Readiness Placement

不做总览首页后，readiness 信息按位置分散展示：

- 模型：显示 active model、provider、model、base_url、API key source、model test 结果。
- 智能体：显示 Agent enabled、answer mode、tool budget、Agent Ready / Not Ready、fallback mode。
- 检索：显示 retrieval 默认路径、index/vector 状态、vector fallback reason。
- 环境：显示 Research Agent import/selfcheck、路径、memory DB、artifact root、diagnostics。
- Chat：当 Agent fallback 到检索摘要时，在步骤日志或消息 metadata 中显示 fallback reason。

## Models Implementation Goals

Models 是 Block 1 中最优先打磨的子系统。它决定 Chat Agent 能否进入 LLM tool-calling path，也决定 fallback 是否可解释。

### Current Models Implementation

当前已经具备：

- 多套 model profiles：name、provider、base_url、model、API key。
- profile 可新增、编辑、删除、激活。
- 激活 profile 后，会把 provider / base_url / model 镜像到 active models 设置。
- API key 不写入普通 SQLite settings；profile key 通过 encrypted secret store 保存。
- profile 列表只返回 masked key。
- 明文 key 只通过显式 reveal/copy endpoint 返回。
- model test endpoint 已能区分连接成功、无法连接、服务拒绝、HTTP status 等情况。
- key 解析优先级已存在：environment variable > active profile > legacy stored key。
- `models.api_key_source` 已能表达 env / profile / stored / none。
- Chat Agent 已能根据当前模型配置决定走 LLM Agent path 或 fallback 到本地检索摘要。

### Target Models Experience

模型分类中需要有一个清晰的“当前生效模型”区域，而不是只靠表格里的 active badge：

```text
当前生效模型
Provider: deepseek
Model: deepseek-chat
Base URL: https://api.deepseek.com/v1
API Key Source: profile
Agent: Ready
```

当环境变量覆盖 profile key 时，需要强提示：

```text
API Key Source: env
环境变量正在覆盖 profile 中保存的密钥。
```

当不可运行时，需要展示具体原因，而不是只显示“未激活可用模型”：

```text
Agent: Not Ready
原因：缺少 API key / 缺少 Chat Model / provider 暂不支持 Agent / model test 未通过
Fallback：本地检索摘要
```

### Readiness Contract

Models UI 不应只依赖 `llm_enabled()`。后端需要提供更严格的 readiness contract，至少覆盖：

- provider 是否为 none。
- Agent 是否 enabled。
- provider 是否被当前 LLM client 支持。
- chat_model 是否非空。
- base_url 是否必填且已配置（如 openai_compatible）。
- API key 是否可解析；source 是 env / profile / stored / none。
- 对 ollama 是否允许 dummy key。
- openai SDK / provider client 依赖是否可用。
- Research Agent 是否 import 成功。
- 最近一次 model test 状态是否成功、失败或未运行。

建议后端返回结构：

```json
{
  "ready": false,
  "mode": "retrieval_summary",
  "active_model": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "api_key_source": "profile"
  },
  "reasons": ["missing_chat_model"],
  "warnings": ["model_test_not_run"],
  "fallback_mode": "local_retrieval_summary"
}
```

### Provider Boundaries

Provider 选项需要和当前真实支持能力一致：

- Agent v1 支持：openai、openai_compatible、deepseek、ollama。
- anthropic / gemini 如果仍显示，需要标记为“待支持”或禁止作为 Agent active provider。
- openai_compatible 必须提示 base_url 必填。
- deepseek 自动给出默认 base_url，但用户可覆盖。
- ollama 默认 base_url 为本地地址，不要求真实 API key。
- provider 变化时可以自动填默认 model/base_url，但不得覆盖用户手动输入的非默认值。

### Model Test UX

model test 结果需要转换成用户可理解的状态，而不是只展示原始错误：

- 配置不完整：缺 provider / model / base_url / key。
- 密钥缺失：当前 provider 没有 env/profile/stored key。
- 网络不可达：base_url 错误或服务不可达。
- 服务拒绝：key 无效、余额不足、模型名不支持、服务商风控。
- 成功：显示 latency、实际返回 model、provider。

测试结果应保留可展开的 raw error，方便排查，但默认展示短结论。

### Profile Safety

profile 操作需要避免误伤：

- 创建 profile 后默认不自动激活，但提供“激活此配置”的快捷动作。
- 删除 active profile 前需要确认。
- 删除 active profile 后，需要明确当前 Agent 将 Not Ready 或切回 provider none。
- reveal 明文 key 后应支持手动隐藏；后续可增加自动隐藏。
- copy key 必须仍通过显式 reveal endpoint，不在列表响应中返回明文。

### Future: CC Switch Import

CC Switch 导入属于 Models 的后续重点，但不纳入当前 Block 1 v1 实现与验收：

- 只读 preview，不自动写入。
- preview 显示可导入项：name、provider、base_url、model、是否包含 key。
- 用户显式勾选后 import。
- key 导入 encrypted secret store。
- 导入后默认不自动激活；提供“激活此 profile”动作。
- 不把 CC Switch 中的 plaintext key 回传到前端列表；仅展示 masked/has_key。

### Models Acceptance

Models 子系统验收：

- 用户能一眼看出当前真正生效的 provider/model/base_url/key source。
- env key 覆盖 profile key 时，UI 有明确提示。
- 无 API key、无 chat_model、unsupported provider、Research Agent import failed 时，Not Ready 原因明确。
- openai_compatible 无 base_url 时不能显示为 Ready。
- ollama 无 API key 时仍可在本地 base_url 场景下进入可测试/可运行状态。
- model test 成功、连接失败、服务拒绝、模型不可用、配置缺失都能显示不同结论。
- 删除 active profile 有确认，并且删除后的 Agent 状态不会误显示为 Ready。
- CC Switch preview/import 暂不要求实现；后续实现时不得自动覆盖 active profile。

## Interfaces And Data Concerns

需要关注：

- `/api/settings`
- `/api/settings/effective`
- `/api/settings/diagnostics`
- `/api/settings/model-profiles`
- `/api/settings/models/test`
- future: `/api/settings/import/cc-switch/preview`（后续）
- future: `/api/settings/import/cc-switch`（后续）

## Test And Acceptance

最小验收：

- 无 API key 时，Agent Not Ready 原因明确。
- 新增并激活 model profile 后，Chat Agent Ready。
- active model 在 Settings、Diagnostics、Chat runtime metadata 中一致。
- Settings 入口位于 Sidebar 底部；首次点击出现账户/设置菜单，点击“设置”才进入 Settings。
- Settings 以居中 modal 打开，包含左侧一层轻量分类导航、右上关闭按钮，不出现独立总览首页。
- Settings 左侧保留“账户”一级分类，用于显示本地用户/API key 登录状态占位。
- Settings v1 不显示搜索栏。
- 关闭 Settings 后，用户回到打开前的当前工作台/会话状态。
- model test 能区分配置不完整、key 缺失、base URL 不可达、模型不可用。
- Research Agent 路径异常时 Settings 不白屏。
- fallback reason 可被记录和展示。

## Open Discussion

- Settings 是否应支持 profile export/import？
- CC Switch 中的 key 是否允许导入到 encrypted secret store？
- 是否需要“只读安全模式”，禁止 state-changing tools？
