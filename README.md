# 文献智能体平台

基于「文献检索分析 agent」搭建的可交互网页平台，专门为后续扩展（Idea
Discovery、Experiment Bridge 等环节）预留了架构空间。当前已实现：

- 文献检索分析模块：已接入完整 `literature_research` Research Agent 工作台
- Idea Discovery / Experiment Bridge 两个"即将上线"占位模块，用来演示新增模块的标准流程
- 团队内部部署所需的最小后端（FastAPI + SSE 流式接口）+ 前端（React）

```
literature-agent-platform/
├── backend/         FastAPI 服务，封装 agent、提供流式对话接口
│   ├── core/        模块统一接口、注册表、会话存储、公共数据结构
│   ├── modules/     每个功能环节一个子包（literature_search / idea_discovery / experiment_bridge）
│   └── api/         HTTP 路由（/api/modules, /api/chat/stream, /api/literature-search）
└── frontend/        React + Vite + Tailwind 的交互界面
    └── src/
        ├── store/   全局状态（zustand），管理模块/会话/消息/检索结果
        ├── components/
        └── api/     封装 SSE 流式请求解析
```

## 快速运行

一键开发启动：

```bash
cd /Users/chenlintao/literature-agent-platform
bash dev.sh
```

这个脚本会自动设置默认 Research Agent 路径并同时启动后端和前端。启动后直接打开
`http://127.0.0.1:5173`。

默认的会话数据库会放到项目内的 `./.runtime/platform_memory.sqlite`，避免依赖外部
目录权限；如需继续使用外部路径，可在启动前手动覆盖 `LITERATURE_MEMORY_DB_PATH`。

开发新功能前建议先跑一遍前后端契约 smoke，避免在半坏后端或字段漂移状态下继续开发：

```bash
PYTHONPATH=backend pytest backend/tests/test_platform_readiness.py backend/tests/test_api_contract_sessions_chat.py backend/tests/test_api_contract_settings_workflow.py -q
node --test frontend/tests/*.test.mjs
```

结构化数据抽取的真实任务验收是 opt-in 测试，会使用本地真实 Research Index 和当前平台真实 LLM 配置：

```bash
RUN_REAL_STRUCTURED_EXTRACTION_ACCEPTANCE=1 \
STRUCTURED_EXTRACTION_ACCEPTANCE_QUERY="membrane" \
STRUCTURED_EXTRACTION_ACCEPTANCE_MEMORY_DB=/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/platform_memory.sqlite \
PYTHONPATH=backend pytest backend/tests/test_structured_extraction_real_task_acceptance.py -q -s
```

`dev.sh` 会使用 `/api/readiness` 判断后端是否真正可复用；如果 readiness 不通过，
不要继续复用该进程，先重启后端或释放端口。

如果你想手动拆开启动，也可以分别执行：

后端：

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

建议用 `paper-crawler-ops` 的同一 Python 环境启动后端，并显式配置 Research Agent
代码目录和数据目录：

```bash
export LITERATURE_RESEARCH_CODE_DIR=/Users/chenlintao/paper-crawler-ops/literature_research
export LITERATURE_DATA_DIR=/Users/chenlintao/paper-crawler-ops/literature_data
# 可选：覆盖会话/任务/Artifact 链接数据库位置
export LITERATURE_MEMORY_DB_PATH=/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/platform_memory.sqlite
cd /Users/chenlintao/literature-agent-platform/backend
/opt/anaconda3/envs/pc_plus/bin/uvicorn main:app --reload --port 8000
```

前端（另开一个终端）：

```bash
cd frontend
npm install
npm run dev:host
```

打开 `http://localhost:5173` 即可看到界面。前端开发服务器已经配置好 `/api`
代理到 `http://127.0.0.1:8000`，不需要额外配置 CORS。

「文献检索分析」模块现在包含多标签工作台：

- Chat：保留原有对话式快速检索摘要
- Overview：selfcheck、index、vector 状态
- Search：高级检索、query plan、evidence snippets
- Paper / Evidence：论文结构、sections、chunks、evidence expand
- Pack / Task / Run：证据包、任务、完整 research run
- Extract/Compare / Analysis / Quality：指标抽取、analysis bundle、验证和质量审计
- Artifacts：浏览 `literature_data/research_agent/` 下已有 JSON/Markdown 产物

顶部栏右侧的齿轮按钮会打开 Settings v1。Settings 是平台级配置中心，不属于左侧
agent 模块，也不会创建会话。当前包含：

- General：平台名称、默认模块、默认 Literature tab、基础 UI 偏好
- Models：**模型配置表** + 高级参数。配置表可管理多套命名模型（名称 + provider +
  base_url + 模型 + 加密密钥），密钥默认以掩码 `sk-xxx...xxxx` 展示、可按需查看/复制完整
  明文（仅经专用 reveal 端点）；点「激活」决定 Chat Agent 用哪一套，激活项会镜像进
  provider/chat_model。密钥加密存于会话库之外，永不写入会话 SQLite。
- Agent：工具调用 Agent 运行参数（enabled / answer_mode quick|deep /
  max_tool_iterations / tool_budget / enforce_citations）与就绪状态
- Research Agent：只读显示 code dir、data dir、memory DB、artifact root 与状态
- Retrieval：Search/Chat 快速检索默认 retrieval、scope、profile、top_k 等参数
- Memory：会话上下文窗口、evidence 使用策略与 SQLite 统计
- Diagnostics：后端、Settings DB、Research Agent、索引、向量、LLM 配置等诊断

Settings 的普通配置保存在同一个 SQLite memory DB 中。运行时优先级为：

```text
request payload 显式传入值
> SQLite settings
> environment variables
> built-in defaults
```

API key 解析优先级：**环境变量 > 激活配置的密钥 > 旧版 per-provider 密钥**。

1. 在 Settings → Models 的「模型配置表」新增配置并保存密钥（推荐）。密钥用 Fernet 加密后存到
   会话库之外的独立文件（默认 `~/.literature-agent/secrets.enc` + 0600 权限的
   `secret.key`，可用 `LITERATURE_SECRET_STORE_PATH` / `LITERATURE_SECRET_KEY_PATH`
   覆盖），不会随 `research_agent/` 或会话 SQLite 备份泄漏。列表只返回掩码，完整明文仅在
   点击「复制/查看」时经 `POST /api/settings/model-profiles/{id}/reveal` 返回。
2. 仍可用环境变量（适合无界面/服务器部署，且优先级最高）：

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
export DEEPSEEK_API_KEY=...
export LITERATURE_LLM_API_KEY=...
```

Chat 工具调用 Agent：当 `models.provider` 配置为受支持的 provider（openai /
openai_compatible / deepseek / ollama）且对应 API key 环境变量就绪、`agent.enabled`
为真时，Chat 会自动切换为**工具调用 Agent**——LLM 自主调用 search / pack /
task_run / run 等底层能力，按需多轮检索，基于证据强制 `[E#]` 引用，并利用会话
记忆支持追问。每轮结束会做一次引用校验（虚构引用 / 有证据未引用都会标记
warning），结果写入该条 assistant 消息的 metadata 并在前端显示「已用证据」。

未配置可用 LLM 时，Chat 自动回退到本地检索摘要，保持离线可用。`agent` 配置项
（`enabled` / `max_tool_iterations` / `tool_budget` / `enforce_citations` /
`answer_mode`）可在 Settings 中调整；`answer_mode=deep` 会额外开放
extract / compare / verify_answer / quality 等工具。答案为逐字（token）流式输出。

研究记录与导出（可审计）：Chat 顶部「研究记录」按钮打开审计抽屉，按轮展示
「问题 → 检索 → 证据（含本地 source_path）→ 产物 → 引用校验」的完整链路；
「导出报告」一键下载可引用的 Markdown（含来源汇总，每条证据可溯源到本地文件）。
对应接口 `GET /api/sessions/{id}/record` 与 `GET /api/sessions/{id}/export`。

会话、消息、turn、检索结果、evidence、job events、artifact 链接会持久化到 SQLite：

```text
/Users/chenlintao/paper-crawler-ops/literature_data/research_agent/platform_memory.sqlite
```

备份时建议同时备份这个 SQLite 文件和 `literature_data/research_agent/` 下的 artifacts。

## Research Agent API

完整 Research Agent 挂在现有 `literature_search` 模块下，不新增独立模块。主要 API：

- `GET /api/literature-search/selfcheck`
- `GET /api/literature-search/index/status`
- `POST /api/literature-search/search`
- `POST /api/literature-search/task/run`
- `POST /api/literature-search/run`
- `GET /api/literature-search/artifacts`
- `GET /api/literature-search/jobs/{job_id}/stream`

长流程接口返回 `job_id`，前端会自动订阅 SSE 任务流并展示 stage、artifact、
result、error、done 事件。

## 整体交互设计说明

- 左侧栏：模块导航（可扩展，新增模块自动出现）+ 当前模块下的对话历史
- 中间：类似聊天的对话区。每轮提问下方会先展示 agent 的"步骤日志"（等宽字体，
  模拟实验记录/仪器打印的风格），再展示最终回答（衬线字体，强调可读性），
  这是用来让用户看清 agent 检索/分析的中间过程，而不是一个黑箱
- 右侧栏：两个标签——"检索结果"展示结构化的文献卡片（标题、作者、年份、
  相关度、摘要片段、本地文件定位），"本地文献库"展示当前配置目录下的全部文献文件

本地文献库目录通过环境变量配置：

```bash
export LIBRARY_DIR=/path/to/your/literature/folder
```

未配置时会展示演示文件列表，方便先看界面效果。

## 如何新增一个模块（比如真正开发 Idea Discovery）

1. 在 `backend/modules/` 下抄一份 `idea_discovery/` 目录结构
2. 继承 `core/module_base.py` 里的 `AgentModule`，实现 `handle_chat()`
   （可以参考 `literature_search/module.py`，按需 yield `step` / `papers` /
   `token` / `done` 事件）
3. 在 `backend/modules/__init__.py` 里 `registry.register(YourModule())`
4. 把 `status` 从 `"coming_soon"` 改成 `"active"`

前端不需要改任何代码——左侧导航、对话界面、结果展示都会自动适配新模块。
如果某个新模块需要专属的可视化（比如 Experiment Bridge 未来可能要展示实验
步骤的时间线图，而不只是文字），可以在 `ResultsPanel.jsx` 里按 `module.id`
分支渲染专属组件，思路跟现在的"检索结果卡片"完全一样。

## 团队部署提示

- 当前会话、消息、turn、检索结果、evidence、job event 与 artifact 链接已经使用
  SQLite 持久化；本地开发默认数据库在 `./.runtime/platform_memory.sqlite`，生产/研究
  数据部署时可用 `LITERATURE_MEMORY_DB_PATH` 指向
  `literature_data/research_agent/platform_memory.sqlite`
- 当前已经具备轻量 User Workspace Boundary：无登录请求默认归属 `local_user`，
  开发/测试可用 `X-User-Id` 模拟用户；sessions/workflows/jobs/artifacts 有用户归属，
  新用户产物进入 `LITERATURE_USER_DATA_ROOT` 下的用户目录。详见
  `docs/user_workspace_boundary.md`
- 完整账号管理仍是下一阶段：生产环境不能信任浏览器直接传来的 `X-User-Id`，
  应由登录态、反向代理或 token 认证层生成 backend `UserContext`
- 用户级 Settings/Profile/Secret 作用域尚未拆分；当前仍是 platform-level 配置
- 正式部署时，把 `backend/main.py` 里 CORS 的 `allow_origins` 改成你们团队
  实际访问网页的域名/端口
