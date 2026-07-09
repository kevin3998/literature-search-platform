# Block 12: Management / Collaboration Framework

## Goal

为后续课题组、多人协作和正式部署补齐管理框架，包括用户注册、登录、角色权限、管理员设置、课题组空间、共享资产和审计管理。

这个 block 的核心问题是：当平台不再是单用户本地工具，而是给课题组中不同老师、学生、合作者共同使用时，如何保证数据隔离、权限清晰、协作顺畅、管理员可控。

## Scope

包含：

- 用户注册与登录。
- 用户 profile。
- 角色与权限。
- 管理员控制台。
- 课题组 / workspace。
- 成员邀请与移除。
- session / artifact / report 的归属与共享。
- 用户级 Settings / Model Profiles / Secrets。
- 资源配额与使用统计。
- 操作审计。
- 数据备份与恢复策略。
- 部署安全设置。

不包含：

- 单用户本地研究闭环的核心能力。
- Retrieval、Evidence、Chat Agent 的算法策略。
- 具体学校/机构 SSO 集成细节，除非后续明确需要。

## Current State

当前系统是单用户本地模式：

- 默认用户可视为 `local_user`。
- `sessions.user_id` 已经预留。
- Settings、model profiles、secret store 当前偏平台级或本地用户级。
- session、message、turn、job、artifact links 已 SQLite 持久化。
- 左侧会话已经支持收藏、置顶、标签、归档、软删除。

当前缺口：

- 无用户注册/登录。
- 无管理员角色。
- 无课题组 workspace。
- 无 per-user settings/model profile/secret 隔离。
- 无共享 artifact/report 的权限模型。
- 无管理后台。

## Target Capability

平台支持从单用户本地模式平滑升级为课题组多人模式：

```text
User
-> belongs to one or more Workspaces / Research Groups
-> has roles and permissions
-> owns sessions, artifacts, reports, settings, secrets
-> can share selected assets with group members
```

管理员可以：

- 管理用户。
- 管理课题组。
- 设置默认模型和 Research Agent 路径。
- 查看系统诊断。
- 查看 job 状态。
- 设置资源限制。
- 管理备份。
- 查看审计日志。

普通用户可以：

- 注册/登录。
- 管理自己的会话、报告、artifact。
- 配置自己的模型 profile，或使用管理员提供的共享模型。
- 将 session/report/artifact 分享给课题组。
- 接收别人分享的研究资产。

## Suggested Roles

初始角色建议：

```text
owner
admin
researcher
viewer
```

权限示例：

- `owner`: 管理整个部署、所有 workspace、系统设置、管理员。
- `admin`: 管理所在 workspace 用户、共享配置、资源与审计。
- `researcher`: 创建 session、运行 Agent、创建 artifact/report、分享资产。
- `viewer`: 查看被分享的 session/report/artifact，不可运行长任务或修改资产。

后续可以补充：

- `guest`
- `service_account`
- `billing_or_quota_admin`

## Data Model Considerations

建议预留或新增：

```text
users
- user_id
- email
- display_name
- password_hash
- status
- created_at
- updated_at

workspaces
- workspace_id
- name
- owner_user_id
- status
- created_at
- updated_at

workspace_members
- workspace_id
- user_id
- role
- joined_at

invites
- invite_id
- workspace_id
- email
- role
- token_hash
- expires_at
- accepted_at

permissions
- role
- permission_key

asset_shares
- share_id
- asset_type
- asset_id
- owner_user_id
- workspace_id
- target_user_id
- permission
- created_at

audit_logs
- audit_id
- actor_user_id
- workspace_id
- action
- target_type
- target_id
- metadata_json
- created_at
```

现有表需要扩展或明确使用：

- `sessions.user_id`
- `sessions.workspace_id`
- `artifacts.owner_user_id`
- `artifacts.workspace_id`
- `jobs.user_id`
- `jobs.workspace_id`
- `settings` 增加 user/workspace scope 或 profile scope
- `settings_profiles` 增加 owner/workspace scope

## Settings And Secrets Boundary

多人模式下必须重新定义 Settings 和 Secrets 的作用域：

```text
system settings
workspace settings
user settings
request overrides
```

模型配置建议分三类：

- 管理员共享模型：workspace 内可用，但用户看不到密钥。
- 用户私有模型：只对自己可用。
- 环境变量模型：部署级最高优先级。

Secret store 需要支持：

- per-user encrypted secret。
- per-workspace shared secret。
- secret reveal 权限控制。
- 管理员可删除/禁用，但默认不查看明文。

## Permission Boundary

需要特别控制：

Read-only actions:

- 查看自己的 session/report/artifact。
- 查看被分享的资产。
- 查看 workspace 公告或共享配置。

Research actions:

- 发起 Chat。
- 执行 search。
- 启动 Deep Research。
- 创建 artifact/report。

State-changing actions:

- 删除/归档 session。
- 分享 artifact/report。
- 修改 model profile。
- 修改 workspace settings。

Admin actions:

- 邀请/移除用户。
- 修改角色。
- 禁用用户。
- 查看审计日志。
- 配置共享模型。
- 管理备份/恢复。

System actions:

- 修改全局 Research Agent 路径。
- 重建全局索引。
- 修改部署安全设置。

## User Experience

新增入口建议：

- TopBar 用户菜单。
- Settings 中增加 Account / Workspace / Admin。
- 管理员看到 Admin Console。
- 左侧会话列表按 workspace 过滤。
- Artifact/Report viewer 显示 owner、workspace、share status。

管理员控制台初版可包含：

- Users。
- Workspaces。
- Model Profiles。
- Jobs。
- Diagnostics。
- Audit Logs。
- Backup。

## Migration Strategy

为了不破坏当前单用户模式，建议分阶段：

1. 保留 `local_user` 作为默认用户。
2. 新增 users/workspaces 表，但默认自动创建 `Local Workspace`。
3. 所有历史 session/artifact 归属 `local_user` + `local_workspace`。
4. 登录系统关闭时继续使用当前本地模式。
5. 启用登录后才强制鉴权。

这样可以支持：

- 本地单用户开发。
- 课题组服务器部署。
- 未来更正式的多租户部署。

## Design Questions

- 第一版登录是否只支持本地 email/password？
- 是否需要学校 SSO / OAuth / LDAP？
- 管理员是否能查看用户的私有 session？
- 用户私有 API key 是否允许管理员 reveal？建议默认不允许。
- 共享 artifact/report 是 workspace 级，还是也支持 point-to-point user share？
- 是否允许 viewer 运行 search？还是只能查看结果？
- 长任务资源配额按 user 还是 workspace 计算？
- 单 SQLite 是否足够，还是多人部署应切换 Postgres？

## Interfaces And Data Concerns

可能新增 API：

```text
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me

GET  /api/users
PATCH /api/users/{user_id}

GET  /api/workspaces
POST /api/workspaces
GET  /api/workspaces/{workspace_id}/members
POST /api/workspaces/{workspace_id}/invites
PATCH /api/workspaces/{workspace_id}/members/{user_id}
DELETE /api/workspaces/{workspace_id}/members/{user_id}

GET  /api/admin/audit-logs
GET  /api/admin/jobs
GET  /api/admin/diagnostics

POST /api/assets/{asset_type}/{asset_id}/share
DELETE /api/assets/{asset_type}/{asset_id}/share/{share_id}
```

需要统一鉴权中间件：

```text
request -> authenticate -> user context -> workspace context -> permission check -> handler
```

## Test And Acceptance

最小验收：

- 未启用登录时，现有本地单用户功能不受影响。
- 启用登录后，用户可注册/登录/退出。
- 用户只能看到自己的 session。
- workspace admin 可邀请成员。
- researcher 可创建 session/report/artifact。
- viewer 只能查看被分享资产。
- 用户私有 model profile 和 secret 不会被其他用户读取。
- 管理员能查看 job/diagnostics/audit logs。
- 历史 `local_user` 数据能自动归入默认 workspace。

## Open Discussion

- Block 12 是否在当前阶段只做 schema/权限设计，不做实现？
- 第一版管理框架是否必须支持 Postgres？
- 是否优先做 workspace + user isolation，再做完整 Admin Console？
- 管理员共享模型和用户私有模型如何共同出现在 Settings Models 页面？
- 是否需要“课题组模板配置”：默认模型、默认 retrieval、默认 report template？

