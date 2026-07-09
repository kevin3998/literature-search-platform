# Frontend Interaction And Visual Bug Checklist

这份清单用于排查 `literature-agent-platform` 前端层面的交互与视觉问题，重点关注用户实际操作时是否顺畅、状态是否可信、布局是否稳定、反馈是否清晰。它不覆盖后端算法质量，但会覆盖后端异常如何被前端正确呈现。

## 0. 使用方式

每次完成一轮前端改动后，至少跑一遍：

```bash
cd /Users/chenlintao/literature-agent-platform/frontend
npm run build
```

然后按下面清单做浏览器手动检查。推荐固定检查视口：

- Desktop: 1440 x 900
- Laptop: 1280 x 800
- Narrow: 1024 x 768
- Mobile-like: 390 x 844

建议重点测试真实模块：

- `literature_search`
- Settings
- 左侧会话栏
- Chat
- Artifacts / Jobs / Research Record

## 1. App Shell / Overall Layout

- [ ] 页面首次打开不白屏。
- [ ] 后端未启动时，前端显示可理解错误，而不是无限 loading 或空白。
- [ ] 顶部栏、左侧栏、主工作区、右侧栏边界清楚。
- [ ] 主工作区高度正确，占满剩余空间，不出现整个页面和内部区域同时滚动的混乱情况。
- [ ] 在 1280px 宽度下，左侧栏、主区、右侧结果区不相互挤压到不可用。
- [ ] 在窄屏下，文字和按钮没有明显重叠。
- [ ] 页面背景、面板、边框、阴影风格一致。
- [ ] 没有孤立的巨大空白区域。
- [ ] 没有卡片嵌套卡片导致层级混乱。
- [ ] 所有主要区域都有稳定尺寸，loading、hover、错误提示不会造成布局跳动。

## 2. TopBar

- [ ] 当前模块标题显示正确。
- [ ] 当前 session 标题显示正确。
- [ ] 打开 Settings 后，TopBar 标题切换为 Settings。
- [ ] 关闭 Settings 后，回到原 active module 和 active session。
- [ ] 齿轮按钮 hover/click 状态明确。
- [ ] Settings 打开时，齿轮按钮状态与页面状态一致。
- [ ] TopBar 中长标题不会挤压按钮或溢出。
- [ ] 后端状态异常时，TopBar 不白屏。

## 3. Sidebar / Module Navigation

- [ ] 模块列表能正常显示。
- [ ] 当前 active module 高亮明确。
- [ ] coming soon 模块不能误导用户以为可完整使用。
- [ ] 切换模块时，主工作区切换正确。
- [ ] 切换模块不丢失当前模块已有 session 状态。
- [ ] 模块名称较长时不会溢出。
- [ ] Sidebar 滚动时不会影响主工作区滚动。
- [ ] Sidebar 宽度固定，hover 不导致主布局跳动。

## 4. Sidebar / Session List

- [ ] session 列表加载成功。
- [ ] 无 session 时能自动创建或显示明确空状态。
- [ ] 点击 session 能切换消息历史。
- [ ] active session 高亮明确。
- [ ] session title 过长时正确截断。
- [ ] favorite / pinned / tags 状态显示不挤压标题。
- [ ] pinned session 排在顶部。
- [ ] archived session 默认不显示。
- [ ] deleted session 默认不显示。
- [ ] 删除当前 active session 后，自动切换到下一条可用 session 或创建新 session。
- [ ] 刷新页面后 active session 恢复。
- [ ] 后端 session API 失败时，有错误提示，不清空已有 UI。

## 5. Session Right-click Menu

- [ ] 右键 session 行时，不出现浏览器默认菜单。
- [ ] 右键菜单出现在鼠标附近。
- [ ] 菜单不会超出窗口右侧或底部。
- [ ] 点击菜单外部能关闭。
- [ ] 按 Escape 能关闭。
- [ ] 滚动 Sidebar 时菜单关闭或位置正确。
- [ ] 切换模块时菜单关闭。
- [ ] 左键点击 session 不触发右键菜单。
- [ ] 重命名成功后，列表立即更新。
- [ ] 收藏/取消收藏成功后，状态立即更新。
- [ ] 置顶/取消置顶成功后，排序立即更新。
- [ ] 设置标签成功后，标签显示正确。
- [ ] 归档后，该 session 从默认列表隐藏。
- [ ] 删除前有确认弹窗。
- [ ] 删除是软删除，UI 文案不要暗示物理删除。
- [ ] 操作失败时，菜单关闭策略和错误提示一致。

## 6. Settings Workbench

- [ ] 点击 TopBar 齿轮能打开 Settings。
- [ ] Settings 不是 module，不创建新 session。
- [ ] Settings 打开不改变 activeModuleId。
- [ ] Settings tabs 切换正常。
- [ ] 保存按钮只保存当前 scope。
- [ ] Reset 只重置目标 scope。
- [ ] 保存中有 loading / disabled 状态，避免重复点击。
- [ ] 保存成功后 effective settings 及时刷新。
- [ ] 保存失败后 draft 不丢。
- [ ] Settings API 失败时显示错误，不影响 Chat/Search 基本工作区。
- [ ] 表单 label、输入框、说明文字对齐一致。
- [ ] 数字输入不会出现 NaN 或空值导致页面崩溃。
- [ ] 下拉值和后端允许值一致。

## 7. Settings / Models

- [ ] model profiles 列表能加载。
- [ ] 无模型配置时有明确空状态。
- [ ] 新增配置表单能展开/收起。
- [ ] provider 切换后默认 model/base_url 自动填充合理。
- [ ] API key 默认只显示 masked key。
- [ ] 点击 reveal 后才显示完整 key。
- [ ] copy key 成功/失败有反馈。
- [ ] 删除配置前有确认或足够明确的操作反馈。
- [ ] 激活配置后 active 状态高亮。
- [ ] active profile 与 Settings effective 中 provider/model 一致。
- [ ] 模型测试过程中按钮 disabled。
- [ ] 测试结果显示 provider、model、latency 或 error。
- [ ] 未配置 key 时显示“未配置”，不要误导为模型不可用。
- [ ] 环境变量优先时 UI 能说明来源。
- [ ] 长 base_url 不撑破表格。

## 8. Settings / Agent, Retrieval, Memory, Diagnostics

- [ ] Agent enabled 状态和 Chat 是否走 Agent path 的说明一致。
- [ ] quick/deep mode 选择清楚。
- [ ] max_tool_iterations/tool_budget 输入有合理范围。
- [ ] Retrieval 默认值在 Search tab label 中正确反映。
- [ ] Memory DB path、大小、统计显示正确。
- [ ] Diagnostics 单项失败不导致整个页面 500/白屏。
- [ ] Diagnostics overall 状态和各项 check 一致。
- [ ] Research Agent path 异常时显示 error detail。
- [ ] vector unavailable reason 能显示。
- [ ] 刷新 Diagnostics 时有 loading 状态。

## 9. Literature Search Workbench / Tabs

- [ ] Chat tab 默认可用。
- [ ] tab 高亮正确。
- [ ] tab 切换不丢失已有表单输入，除非明确设计为重置。
- [ ] tabs 过多时不挤压到不可点击。
- [ ] compact tab 只显示图标时有 tooltip/title。
- [ ] Overview 状态卡 loading/error/data 三态明确。
- [ ] Search/Paper/Evidence/Pack/Task/Run 等工具 tab 不白屏。
- [ ] 高级工具返回 JSON 时格式可读。
- [ ] 长 JSON 不撑破布局。
- [ ] 表单错误有提示，不只是在 console 报错。

## 10. Chat Panel

- [ ] 输入框可输入多行。
- [ ] Enter / Shift+Enter 行为符合设计。
- [ ] 发送空消息被阻止。
- [ ] 发送中按钮 disabled 或有 loading。
- [ ] 发送后用户消息立即显示。
- [ ] streaming token 能逐步显示。
- [ ] streaming 结束后状态恢复。
- [ ] 流式过程中切换 session 不会把 token 写到错误 session。
- [ ] 后端 stream error 显示为 assistant error message。
- [ ] 网络中断不会无限 loading。
- [ ] 多轮消息顺序正确。
- [ ] 刷新页面后历史消息恢复。
- [ ] 长回答可滚动，不撑破页面。
- [ ] 代码块/Markdown/列表显示不溢出。
- [ ] 回答中的 `[E#]` citation chip 高亮正确。
- [ ] citation footer 在 streaming 完成后显示。
- [ ] citation warning 有明显但不刺眼的视觉提示。
- [ ] “研究记录”“导出报告”按钮在无 session 或无 record 时处理合理。

## 11. Agent Step Timeline

- [ ] step running 状态明确。
- [ ] step done 状态明确。
- [ ] step error 状态明确。
- [ ] 多个 step 顺序正确。
- [ ] 工具调用 label 不过长溢出。
- [ ] 长时间运行时用户能看出仍在工作。
- [ ] fallback 时显示 fallback reason。
- [ ] tool budget reached 时显示明确说明。
- [ ] step timeline 不因为新 token 流入而频繁抖动。

## 12. Results Panel / Paper Cards

- [ ] papers event 到达后右侧结果更新。
- [ ] 无结果时显示空状态。
- [ ] paper title 长文本正确换行或截断。
- [ ] DOI/source path/metadata 不撑破卡片。
- [ ] relevance/year/journal 显示位置稳定。
- [ ] evidence snippet 可读。
- [ ] evidence id 明确。
- [ ] 点击 paper/evidence 的行为明确。
- [ ] Search 结果和 Chat 结果不会互相覆盖成混乱状态。
- [ ] 切换 session 后右侧结果与该 session 对应。

## 13. Search Tab

- [ ] query textarea 有默认值或 placeholder。
- [ ] limit 为空时使用 Settings 默认值。
- [ ] 用户显式填写 limit 时覆盖 Settings 默认。
- [ ] retrieval/scope/profile 默认值显示正确。
- [ ] 运行检索时按钮 loading。
- [ ] 检索失败时显示错误。
- [ ] results 数量与 returned count 一致。
- [ ] query_plan 显示 retrieval_used。
- [ ] vector fallback reason 显示。
- [ ] evidence snippets 展示 evidence_id、kind、confidence、source_path。
- [ ] 搜索结果过多时页面滚动顺畅。

## 14. Paper / Evidence / Pack Tools

- [ ] article_id / DOI / paper_id 输入错误时有提示。
- [ ] paper show/sections/chunks 三个按钮响应明确。
- [ ] evidence expand 必填字段不足时不静默失败。
- [ ] expand 结果中的 linked assets 可读。
- [ ] pack 创建成功后 artifacts 列表刷新。
- [ ] pack 创建失败时显示 error。
- [ ] JSON 结果能复制或至少易读。

## 15. Task / Run / Long Jobs

- [ ] 创建 job 后立即显示 queued/running 状态。
- [ ] SSE 连接成功后 stage timeline 更新。
- [ ] stage running/done/error 清楚。
- [ ] artifact event 到达后 artifacts 列表刷新。
- [ ] job done 后 loading 停止。
- [ ] job error 后 loading 停止并显示错误。
- [ ] 刷新页面后历史 job 可见。
- [ ] stream replay 不重复渲染同一事件。
- [ ] run resume 按钮只在可 resume 状态显示。
- [ ] 多个 job 同时存在时 active job 不混淆。

## 16. Artifacts

- [ ] artifacts 列表能加载。
- [ ] 无 artifacts 时有空状态。
- [ ] artifact type/title/created_at 显示正确。
- [ ] 点击 artifact 能打开详情。
- [ ] JSON summary 可读。
- [ ] Markdown 内容可读。
- [ ] 内容很长时 viewer 内滚动，不撑破页面。
- [ ] artifact path 长文本不溢出。
- [ ] artifact 与 session/turn/job 的链接显示正确。
- [ ] artifact 加载失败时显示错误。
- [ ] 新 job 产生 artifact 后列表自动或手动刷新可见。

## 17. Research Record / Export

- [ ] 研究记录 modal/drawer 能打开。
- [ ] 无 record 时显示空状态。
- [ ] 每轮 turn 展示 question、answer、evidence、artifacts、citation audit。
- [ ] citation warning 在 record 中可见。
- [ ] source_path 可读且不撑破布局。
- [ ] 关闭 modal 后回到原位置。
- [ ] 导出 Markdown 成功下载。
- [ ] 导出失败有错误提示。
- [ ] 导出按钮不会在 streaming 中造成状态冲突。

## 18. Loading / Empty / Error States

- [ ] 每个异步区域都有 loading。
- [ ] 每个列表都有 empty state。
- [ ] 每个 API 错误都有用户可见反馈。
- [ ] 错误文案包含可操作线索。
- [ ] error banner 不遮挡关键按钮。
- [ ] 重试按钮存在于适合场景。
- [ ] loading skeleton/spinner 不造成布局跳动。
- [ ] 后端 500、网络失败、JSON parse error 都不会白屏。

## 19. Visual Consistency

- [ ] 字体层级一致：页面标题、section title、card title、body、metadata。
- [ ] 按钮尺寸一致。
- [ ] icon button 有 title/tooltip。
- [ ] 主按钮/次按钮/危险按钮风格区分明显。
- [ ] 表单输入高度一致。
- [ ] 边框颜色一致。
- [ ] hover/focus/active 状态一致。
- [ ] disabled 状态清楚。
- [ ] 危险操作使用红色或明确警示。
- [ ] 不使用过多同色系导致层级不清。
- [ ] 文字没有负 letter-spacing。
- [ ] 文本不因 viewport width 线性缩放。

## 20. Accessibility And Keyboard

- [ ] 主要按钮可键盘 focus。
- [ ] focus ring 可见。
- [ ] Escape 关闭右键菜单和 modal。
- [ ] modal 打开时焦点不迷失。
- [ ] icon-only button 有 title 或 aria-label。
- [ ] 表单 input 有 label。
- [ ] 错误信息与对应输入关系清楚。
- [ ] 色彩不是唯一状态表达方式。
- [ ] 常用文本对比度足够。

## 21. Responsive Behavior

- [ ] 1440px 下三栏布局正常。
- [ ] 1280px 下右侧栏不挤压 Chat。
- [ ] 1024px 下 tab/sidebar 仍可操作。
- [ ] mobile-like 宽度下不出现严重横向滚动。
- [ ] 表格在窄屏下可滚动或改为堆叠。
- [ ] 长 URL/path/code 不撑破容器。
- [ ] modal 在小屏上不超出视口。
- [ ] 右键菜单在窗口边缘能自动调整位置。

## 22. State Synchronization

- [ ] active session 与 messages 一致。
- [ ] active module 与 session list 一致。
- [ ] Settings draft 与 saved values 区分清楚。
- [ ] Settings effective 与 UI 默认值一致。
- [ ] model profile active 后 Agent readiness 及时刷新。
- [ ] Search 结果与当前 session/turn 关联正确。
- [ ] job events 与 active job 关联正确。
- [ ] artifact refresh 不清空 selected artifact，除非它不存在。
- [ ] localStorage 中 active session id 不存在时能恢复。

## 23. Browser Console And Network

- [ ] 正常流程下 console 无 React key warning。
- [ ] 正常流程下 console 无 uncontrolled/controlled input warning。
- [ ] 正常流程下 console 无 uncaught error。
- [ ] SSE 断开时不会疯狂重连。
- [ ] API 失败不会重复发请求造成刷屏。
- [ ] Settings 保存不会发送 api_key 到普通 `/api/settings`。
- [ ] model profile list 响应不包含明文 key。
- [ ] reveal key 只在用户点击时触发。

## 24. High-risk Regression Scenarios

每次较大改动后至少手动跑这些：

- [ ] 首次启动，无 session，无 model profile。
- [ ] 新建 model profile，激活，测试连接。
- [ ] Chat 提问，确认 streaming、step、papers、citation 正常。
- [ ] 刷新页面，确认 session 和消息恢复。
- [ ] 右键当前 session，重命名、置顶、归档、删除。
- [ ] Search tab 运行检索，确认 results/evidence 显示。
- [ ] 创建一个 job，确认 SSE timeline 和 artifact 刷新。
- [ ] 打开 artifact，确认 JSON/Markdown viewer 正常。
- [ ] 打开研究记录并导出报告。
- [ ] 后端停止时刷新页面，确认错误展示。

