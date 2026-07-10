import React, { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  Activity,
  Bot,
  BrainCircuit,
  Copy,
  Eye,
  EyeOff,
  FolderCog,
  Palette,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Settings2,
  Telescope,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { useAppStore } from "../store/useAppStore";

// Product-named categories (single-level nav). Each regroups fields that live in
// the backend settings scopes (general/models/agent/retrieval/memory/...).
const CATEGORIES = [
  ["account", "账户", UserRound],
  ["general", "常规", Settings2],
  ["appearance", "外观", Palette],
  ["models", "模型", BrainCircuit],
  ["agent", "智能体", Bot],
  ["retrieval", "检索", Telescope],
  ["environment", "环境", FolderCog],
];

// Editable [scope, key] descriptors per category — drives precise per-field dirty
// detection and partial Save (so categories that share a backend scope, e.g. 常规
// and 智能体 both touch `memory`, don't bleed dirty state into each other).
const CATEGORY_FIELDS = {
  account: [], // read-only placeholder until a real login/account system is wired
  general: [
    ["general", "platform_name"],
    ["general", "default_module"],
    ["general", "default_literature_tab"],
    ["memory", "auto_generate_session_title"],
    ["memory", "show_archived_sessions"],
    ["memory", "auto_link_artifacts"],
    ["general", "show_debug_json"],
  ],
  appearance: [
    ["general", "theme"],
    ["general", "compact_mode"],
  ],
  models: [
    ["models", "temperature"],
    ["models", "max_tokens"],
    ["models", "timeout_seconds"],
    ["models", "retry_count"],
    ["models", "multimodal_enabled"],
    ["models", "multimodal_profile_id"],
    ["models", "multimodal_model"],
    ["models", "multimodal_scan_default"],
  ],
  agent: [
    ["agent", "enabled"],
    ["agent", "answer_mode"],
    ["agent", "max_tool_iterations"],
    ["agent", "tool_budget"],
    ["agent", "enforce_citations"],
    ["agent", "grounding_mode"],
    ["memory", "auto_use_previous_evidence"],
    ["memory", "context_message_limit"],
    ["memory", "context_search_limit"],
    ["memory", "evidence_limit_multiplier"],
  ],
  retrieval: [
    ["retrieval", "default_retrieval"],
    ["retrieval", "default_scope"],
    ["retrieval", "default_profile"],
    ["retrieval", "default_limit"],
    ["retrieval", "default_evidence_per_article_limit"],
    ["retrieval", "default_expand_assets"],
    ["retrieval", "default_year_from"],
    ["retrieval", "default_year_to"],
  ],
  environment: [],
  external_sources: [
    ["external_sources", "arxiv_enabled"],
    ["external_sources", "semantic_scholar_enabled"],
    ["external_sources", "openalex_enabled"],
    ["external_sources", "exa_enabled"],
    ["external_sources", "crossref_enabled"],
    ["external_sources", "default_year_window"],
    ["external_sources", "per_source_limit"],
    ["external_sources", "timeout_seconds"],
    ["external_sources", "retry_count"],
    ["external_sources", "allow_unverified_candidates"],
    ["external_sources", "mark_concurrent_work_from_year"],
    ["external_sources", "openalex_email"],
  ],
};

const SUPPORTED_PROVIDERS = ["openai", "openai_compatible", "deepseek", "ollama"];
const MODEL_PROVIDERS = ["none", "openai", "anthropic", "gemini", "deepseek", "ollama", "openai_compatible"];
const LITERATURE_TABS = ["chat", "overview", "search", "paper", "evidence", "pack", "task", "run", "extract", "analysis", "artifacts"];
const LITERATURE_TAB_LABELS = {
  chat: "问答",
  overview: "概览",
  search: "检索",
  paper: "文献",
  evidence: "证据",
  pack: "证据包",
  task: "任务",
  run: "运行",
  extract: "抽取",
  analysis: "分析",
  artifacts: "产物",
};

const DEFAULT_MODELS = { openai: "gpt-4o", deepseek: "deepseek-chat", ollama: "llama3.1" };
const DEFAULT_BASE_URLS = { deepseek: "https://api.deepseek.com/v1", ollama: "http://127.0.0.1:11434/v1" };
const DEEPSEEK_MODELS = ["deepseek-chat", "deepseek-reasoner"];
const AUTO_MODEL_VALUES = Object.values(DEFAULT_MODELS);
const AUTO_BASE_URL_VALUES = Object.values(DEFAULT_BASE_URLS);
const EMPTY_FORM = { name: "", provider: "openai", base_url: "", model: "gpt-4o", api_key: "" };

const REASON_LABELS = {
  provider_none: "未配置模型服务商",
  agent_disabled: "智能体已在设置中关闭",
  provider_unsupported: "当前服务商暂不支持智能体",
  missing_chat_model: "缺少对话模型",
  missing_base_url: "缺少基础地址",
  missing_api_key: "缺少 API 密钥",
  ollama_model_unavailable: "Ollama 中未找到该模型",
  research_agent_unavailable: "研究智能体不可用",
};

function fieldsDirty(fields, draft, values) {
  if (!draft || !values) return false;
  return fields.some(([scope, key]) => (draft[scope] || {})[key] !== (values[scope] || {})[key]);
}

export default function SettingsModal() {
  const open = useAppStore((s) => s.settings.open);
  const activeTab = useAppStore((s) => s.settings.activeTab);
  const setTab = useAppStore((s) => s.setSettingsTab);
  const closeSettings = useAppStore((s) => s.closeSettings);
  const loading = useAppStore((s) => s.settings.loading);
  const draft = useAppStore((s) => s.settings.draft);
  const values = useAppStore((s) => s.settings.values);
  const error = useAppStore((s) => s.settings.error);

  const anyDirty = useMemo(
    () => Object.values(CATEGORY_FIELDS).some((fields) => fieldsDirty(fields, draft, values)),
    [draft, values]
  );

  const attemptClose = () => {
    if (anyDirty && !window.confirm("有未保存的修改，放弃更改并关闭？")) return;
    closeSettings();
  };

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") attemptClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, anyDirty]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6" onMouseDown={attemptClose}>
      <div
        className="flex h-[88vh] w-full max-w-[1000px] overflow-hidden rounded-xl border border-line bg-paper-0 shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Left rail: single-level category nav (no search box per Block 1 v1) */}
        <aside className="flex w-[208px] flex-shrink-0 flex-col border-r border-line bg-paper-50">
          <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-1">
            {CATEGORIES.map(([key, label, Icon]) => {
              const dirty = fieldsDirty(CATEGORY_FIELDS[key] || [], draft, values);
              return (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={clsx(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-[12.5px] transition-colors",
                    activeTab === key ? "bg-ink-900 text-paper-50" : "text-ink-500 hover:bg-paper-100 hover:text-ink-900"
                  )}
                >
                  <Icon size={15} />
                  <span className="flex-1 text-left truncate">{label}</span>
                  {dirty && <span className="h-1.5 w-1.5 rounded-full bg-amber" title="有未保存修改" />}
                </button>
              );
            })}
          </nav>
        </aside>

        {/* Right: header + active category content */}
        <div className="flex flex-1 flex-col min-w-0">
          <header className="flex h-12 flex-shrink-0 items-center justify-between border-b border-line px-5">
            <h1 className="font-serif text-[16px] text-ink-900">设置</h1>
            <button
              onClick={attemptClose}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-400 hover:bg-paper-100 hover:text-ink-900"
              title="关闭（Esc）"
            >
              <X size={16} />
            </button>
          </header>
          <main className="flex-1 overflow-y-auto px-5 py-4">
            {loading && !draft ? (
              <div className="flex h-full items-center justify-center text-[13px] text-ink-500">正在加载设置…</div>
            ) : (
              <>
                {error && (
                  <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{error}</div>
                )}
                {activeTab === "account" && <AccountCategory />}
                {activeTab === "general" && <GeneralCategory />}
                {activeTab === "appearance" && <AppearanceCategory />}
                {activeTab === "models" && <ModelsCategory />}
                {activeTab === "agent" && <AgentCategory />}
                {activeTab === "retrieval" && <RetrievalCategory />}
                {activeTab === "environment" && <EnvironmentCategory />}
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

// ── Categories ────────────────────────────────────────────────────────────────

function AccountCategory() {
  const currentUser = useAppStore((s) => s.currentUser);
  const accountState = useAppStore((s) => s.account);
  const loadAccountSecurity = useAppStore((s) => s.loadAccountSecurity);
  const updateAccountProfile = useAppStore((s) => s.updateAccountProfile);
  const changePassword = useAppStore((s) => s.changeAccountPassword);
  const createApiToken = useAppStore((s) => s.createAccountApiToken);
  const revokeApiToken = useAppStore((s) => s.revokeAccountApiToken);
  const [displayName, setDisplayName] = useState(currentUser?.display_name || currentUser?.displayName || "");
  const [avatarUrl, setAvatarUrl] = useState(currentUser?.avatar_url || currentUser?.avatarUrl || "");
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "" });
  const [tokenName, setTokenName] = useState("CLI");
  const initial = (currentUser?.display_name || currentUser?.displayName || currentUser?.email || "?").trim().charAt(0) || "?";
  const apiTokens = accountState.apiTokens || [];
  const sessions = accountState.sessions || [];

  useEffect(() => { loadAccountSecurity().catch(() => {}); }, [loadAccountSecurity]);
  useEffect(() => {
    setDisplayName(currentUser?.display_name || currentUser?.displayName || "");
    setAvatarUrl(currentUser?.avatar_url || currentUser?.avatarUrl || "");
  }, [currentUser]);

  const saveProfile = async (event) => {
    event.preventDefault();
    await updateAccountProfile({ display_name: displayName, avatar_url: avatarUrl || null });
  };

  const submitPassword = async (event) => {
    event.preventDefault();
    await changePassword(passwords);
    setPasswords({ current_password: "", new_password: "" });
  };

  const submitToken = async (event) => {
    event.preventDefault();
    await createApiToken({ name: tokenName || "API Token" });
    setTokenName("CLI");
  };

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <h2 className="mb-4 font-serif text-[16px] text-ink-900">账户</h2>

        <Group title="登录状态">
          <div className="flex items-center justify-between gap-3 rounded-md border border-line bg-paper-50 px-3 py-2">
            <span className="min-w-0 truncate text-[13px] text-ink-700">{currentUser?.email || "未记录邮箱"}</span>
            <StatusPill status={currentUser?.status === "active" ? "ok" : "warning"} text={currentUser?.status || "unknown"} />
          </div>
        </Group>

        <Group title="个人资料">
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-ink-900 text-[18px] font-serif text-paper-50">
              {avatarUrl ? <img src={avatarUrl} alt="" className="h-full w-full rounded-full object-cover" /> : initial}
            </span>
            <div className="min-w-0">
              <div className="text-[14px] text-ink-900">{currentUser?.display_name || currentUser?.displayName || "未命名用户"}</div>
              <div className="text-[12.5px] text-ink-500">{currentUser?.email || "—"}</div>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12.5px]">
            <KV label="角色" value={currentUser?.role || "user"} />
            <KV label="认证模式" value={currentUser?.auth_mode || currentUser?.authMode || "local-password"} />
          </div>
          <form onSubmit={saveProfile} className="mt-4 space-y-3">
            <FormGrid>
              <Field label="显示名">
                <input className="form-input" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
              </Field>
              <Field label="头像 URL">
                <input className="form-input" value={avatarUrl} onChange={(event) => setAvatarUrl(event.target.value)} placeholder="https://..." />
              </Field>
            </FormGrid>
            <button className="btn-dark" type="submit" disabled={accountState.loading}>保存资料</button>
          </form>
        </Group>

        <Group title="修改密码">
          <form onSubmit={submitPassword} className="space-y-3">
            <FormGrid>
              <Field label="当前密码">
                <input className="form-input" type="password" value={passwords.current_password} onChange={(event) => setPasswords((value) => ({ ...value, current_password: event.target.value }))} required autoComplete="current-password" />
              </Field>
              <Field label="新密码">
                <input className="form-input" type="password" value={passwords.new_password} onChange={(event) => setPasswords((value) => ({ ...value, new_password: event.target.value }))} required minLength={8} autoComplete="new-password" />
              </Field>
            </FormGrid>
            <button className="btn-light" type="submit" disabled={accountState.loading}>修改密码</button>
          </form>
        </Group>

        <Group title="浏览器会话">
          {sessions.length === 0 ? <EmptyState text="暂无活跃会话记录。" /> : (
            <div className="overflow-hidden rounded-md border border-line">
              {sessions.map((session) => <AccountRow key={session.session_id || session.sessionId} left={session.user_agent || session.userAgent || "Browser session"} right={fmtDateTime(session.last_seen_at || session.lastSeenAt || session.created_at || session.createdAt)} />)}
            </div>
          )}
        </Group>

        <Group title="API Tokens">
          <form onSubmit={submitToken} className="mb-3 flex flex-wrap items-end gap-2">
            <Field label="名称">
              <input className="form-input min-w-[220px]" value={tokenName} onChange={(event) => setTokenName(event.target.value)} required />
            </Field>
            <button className="btn-dark" type="submit" disabled={accountState.loading}>创建 API Token</button>
          </form>
          {accountState.lastCreatedToken?.api_token && (
            <div className="mb-3 rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12px] text-ink-700">
              新 Token：<code className="break-all font-mono">{accountState.lastCreatedToken.api_token}</code>
            </div>
          )}
          {apiTokens.length === 0 ? <EmptyState text="暂无 API Token。" /> : (
            <div className="overflow-hidden rounded-md border border-line">
              {apiTokens.map((token) => (
                <div key={token.token_id || token.tokenId} className="flex items-center justify-between gap-3 border-b border-line px-3 py-2 last:border-b-0">
                  <div className="min-w-0">
                    <div className="truncate text-[13px] text-ink-800">{token.name}</div>
                    <div className="font-mono text-[11px] text-ink-500">{token.token_preview || token.tokenPreview || "lap_..."} · 创建 {fmtDateTime(token.created_at || token.createdAt)}</div>
                  </div>
                  <button className="btn-light" type="button" onClick={() => revokeApiToken(token.token_id || token.tokenId)} disabled={accountState.loading}>撤销</button>
                </div>
              ))}
            </div>
          )}
        </Group>

        {accountState.error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{accountState.error}</div>}
      </section>
    </div>
  );
}

function AccountRow({ left, right }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2 last:border-b-0">
      <span className="min-w-0 truncate text-[13px] text-ink-800">{left}</span>
      <span className="flex-shrink-0 font-mono text-[11px] text-ink-500">{right || "—"}</span>
    </div>
  );
}

function GeneralCategory() {
  const modules = useAppStore((s) => s.modules);
  const general = useScope("general");
  const memory = useScope("memory");
  const edit = useAppStore((s) => s.editSettings);
  const developerMode = useAppStore((s) => s.developerMode);
  const setDeveloperMode = useAppStore((s) => s.setDeveloperMode);
  return (
    <CategorySection category="general" title="常规" description="平台启动行为与基础偏好。">
      <Group title="基础">
        <FormGrid>
          <Field label="平台名称">
            <input className="form-input" value={general.platform_name || ""} onChange={(e) => edit("general", "platform_name", e.target.value)} />
          </Field>
          <Field label="默认启动模块">
            <select className="form-input" value={general.default_module || "literature_search"} onChange={(e) => edit("general", "default_module", e.target.value)}>
              {modules.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </Field>
          <Field label="默认文献页签">
            <select className="form-input" value={general.default_literature_tab || "chat"} onChange={(e) => edit("general", "default_literature_tab", e.target.value)}>
              {LITERATURE_TABS.map((tab) => <option key={tab} value={tab}>{LITERATURE_TAB_LABELS[tab] || tab}</option>)}
            </select>
          </Field>
        </FormGrid>
      </Group>
      <Group title="会话">
        <ToggleRow label="自动生成会话标题" checked={!!memory.auto_generate_session_title} onChange={(v) => edit("memory", "auto_generate_session_title", v)} />
        <ToggleRow label="显示归档会话" checked={!!memory.show_archived_sessions} onChange={(v) => edit("memory", "show_archived_sessions", v)} />
        <ToggleRow label="自动关联产物" checked={!!memory.auto_link_artifacts} onChange={(v) => edit("memory", "auto_link_artifacts", v)} />
      </Group>
      <Group title="开发">
        {/* UI-only preference (localStorage), applied immediately — not part of
            the saved settings draft. Exposes the manual tool consoles. */}
        <ToggleRow
          label="开发者模式（工具控制台）"
          checked={developerMode}
          onChange={(v) => setDeveloperMode(v)}
        />
        <ToggleRow label="显示 Debug JSON" checked={!!general.show_debug_json} onChange={(v) => edit("general", "show_debug_json", v)} />
      </Group>
    </CategorySection>
  );
}

function AppearanceCategory() {
  const general = useScope("general");
  const edit = useAppStore((s) => s.editSettings);
  return (
    <CategorySection category="appearance" title="外观" description="主题与布局显示偏好。">
      <Group title="主题">
        <FormGrid>
          <Field label="主题">
            <select className="form-input" value={general.theme || "light"} onChange={(e) => edit("general", "theme", e.target.value)}>
              <option value="light">浅色</option>
              <option value="system">跟随系统</option>
            </select>
          </Field>
        </FormGrid>
      </Group>
      <Group title="布局">
        <ToggleRow label="紧凑模式" checked={!!general.compact_mode} onChange={(v) => edit("general", "compact_mode", v)} />
      </Group>
    </CategorySection>
  );
}

function ModelsCategory() {
  const profiles = useAppStore((s) => s.modelProfiles.items);
  const loadingProfiles = useAppStore((s) => s.modelProfiles.loading);
  const profilesError = useAppStore((s) => s.modelProfiles.error);
  const load = useAppStore((s) => s.loadModelProfiles);
  const [editing, setEditing] = useState(null); // null | "new" | profileId

  useEffect(() => { load().catch(() => {}); }, [load]);

  return (
    <div className="space-y-4">
      <EffectiveModelCard />

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="font-serif text-[16px] text-ink-900">模型配置档</h2>
            <p className="mt-1 text-[12.5px] text-ink-500">管理多套模型与 API Key。点「新增配置」或「编辑」即可加密保存/重新保存密钥。</p>
          </div>
          <button className="btn-dark inline-flex items-center gap-1.5" onClick={() => setEditing(editing === "new" ? null : "new")}>
            <Plus size={14} /> 新增配置 / API Key
          </button>
        </div>
        {profilesError && <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{profilesError}</div>}
        {editing === "new" && <ProfileForm onClose={() => setEditing(null)} />}
        {loadingProfiles && profiles.length === 0 ? (
          <EmptyState text="正在加载配置…" />
        ) : profiles.length === 0 ? (
          <EmptyState text="还没有模型配置。点「新增配置 / API Key」添加 provider、模型与密钥。" />
        ) : (
          <div className="overflow-hidden rounded-md border border-line">
            <div className="grid grid-cols-[minmax(0,1.1fr)_minmax(170px,1fr)_minmax(0,1.2fr)_auto] gap-3 bg-paper-50 px-3 py-2 text-[13px] font-medium text-ink-500">
              <div>名称</div>
              <div>API Key 状态</div>
              <div>服务商 · 模型</div>
              <div className="text-right">操作</div>
            </div>
            <div>
              {profiles.map((p) => (
                <ProfileRow key={p.id} profile={p} editing={editing === p.id} onEdit={() => setEditing(editing === p.id ? null : p.id)} onClose={() => setEditing(null)} />
              ))}
            </div>
          </div>
        )}
      </section>

      <MultimodalModelSettings profiles={profiles} />
      <AdvancedModelParams />
      <CCSwitchImportPlaceholder />
    </div>
  );
}

// Reserved slot for CC Switch import — kept visible so the entry point exists,
// but the flow itself is deferred (Block 1 v1 does not implement import).
function CCSwitchImportPlaceholder() {
  return (
    <section className="rounded-lg border border-dashed border-line bg-paper-0 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-[16px] text-ink-900">导入 · CC Switch</h2>
          <p className="mt-1 text-[12.5px] text-ink-500">
            后续将支持从 CC Switch 预览并导入服务商 / 模型 / Base URL / 密钥到模型配置档（只读预览，显式勾选后导入，不自动激活）。
          </p>
        </div>
        <button className="btn-light cursor-not-allowed opacity-60" disabled title="当前 v1 不实现，后续接入">
          预览导入
        </button>
      </div>
    </section>
  );
}

function EffectiveModelCard() {
  const readiness = useAppStore((s) => s.settings.readiness);
  if (!readiness) return null;
  const m = readiness.active_model || {};
  const envOverrides = (readiness.warnings || []).includes("env_overrides_profile");
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-serif text-[16px] text-ink-900">当前生效模型</h2>
        <StatusPill status={readiness.ready ? "ok" : "warning"} text={readiness.ready ? "智能体就绪" : "智能体未就绪"} />
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12.5px]">
        <KV label="服务商" value={m.provider} />
        <KV label="模型" value={m.model || "—"} mono />
        <KV label="基础地址" value={m.base_url || "—"} mono />
        <KV label="密钥来源" value={m.api_key_source || "none"} />
      </div>
      {envOverrides && (
        <p className="mt-3 rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12px] text-ink-700">
          环境变量正在覆盖 profile 中保存的密钥。
        </p>
      )}
      {!readiness.ready && (
        <div className="mt-3 rounded-md border border-amber/30 bg-amber/10 px-3 py-2 text-[12px] text-ink-700">
          <div>原因：{(readiness.reasons || []).map((r) => REASON_LABELS[r] || r).join("、") || "未知"}</div>
          <div className="mt-0.5 text-ink-500">文献检索问答会提示先配置可用模型。</div>
        </div>
      )}
    </section>
  );
}

function AgentCategory() {
  const agent = useScope("agent");
  const memory = useScope("memory");
  const edit = useAppStore((s) => s.editSettings);
  const readiness = useAppStore((s) => s.settings.readiness);
  return (
    <CategorySection category="agent" title="智能体" description="工具调用智能体的运行参数。需先在「模型」配好服务商 / 模型 / 密钥。">
      <Group title="运行">
        <div className="mb-3">
          <StatusPill
            status={readiness?.ready ? "ok" : "warning"}
            text={readiness?.ready ? "智能体就绪：对话走工具调用" : "智能体未就绪：文献检索问答需要可用模型"}
          />
          {readiness && !readiness.ready && (
            <p className="mt-2 text-[12px] text-ink-500">
              原因：{(readiness.reasons || []).map((r) => REASON_LABELS[r] || r).join("、") || "未知"}
            </p>
          )}
        </div>
        <ToggleRow label="启用 Agent（关闭后文献检索问答会提示配置模型）" checked={!!agent.enabled} onChange={(v) => edit("agent", "enabled", v)} />
      </Group>
      <Group title="回答模式">
        <FormGrid>
          <Field label="回答模式">
            <select className="form-input" value={agent.answer_mode || "quick"} onChange={(e) => edit("agent", "answer_mode", e.target.value)}>
              <option value="quick">快速（检索 / 证据包等基础工具）</option>
              <option value="deep">深度（额外开放 task_run / run / extract / compare）</option>
            </select>
          </Field>
        </FormGrid>
      </Group>
      <Group title="工具调用">
        <FormGrid>
          <NumberField scope="agent" name="max_tool_iterations" label="最大工具迭代次数" value={agent.max_tool_iterations} />
          <NumberField scope="agent" name="tool_budget" label="工具预算" value={agent.tool_budget} />
        </FormGrid>
      </Group>
      <Group title="证据约束">
        <ToggleRow label="强制引用校验（标记虚构 / 未标注引用）" checked={!!agent.enforce_citations} onChange={(v) => edit("agent", "enforce_citations", v)} />
        <FormGrid>
          <Field label="证据接地模式（claim 级证据把关）">
            <select className="form-input" value={agent.grounding_mode || "audit"} onChange={(e) => edit("agent", "grounding_mode", e.target.value)}>
              <option value="audit">审计（默认·确定性底座：标记虚构引用 + 无证据不乱答，不调用额外模型）</option>
              <option value="strict">严格（额外 LLM 逐条把关，越界结论自动降级 / 改写）</option>
              <option value="warn">警告（额外 LLM 把关，只标记不改写）</option>
              <option value="off">关闭（完全关闭，含虚构引用标记）</option>
            </select>
          </Field>
        </FormGrid>
      </Group>
      <Group title="上下文策略">
        <FormGrid>
          <NumberField scope="memory" name="context_message_limit" label="最近消息数" value={memory.context_message_limit} />
          <NumberField scope="memory" name="context_search_limit" label="最近检索数" value={memory.context_search_limit} />
          <NumberField scope="memory" name="evidence_limit_multiplier" label="证据数量倍率" value={memory.evidence_limit_multiplier} />
        </FormGrid>
        <ToggleRow label="追问自动使用上一轮证据" checked={!!memory.auto_use_previous_evidence} onChange={(v) => edit("memory", "auto_use_previous_evidence", v)} />
      </Group>
    </CategorySection>
  );
}

function RetrievalCategory() {
  const retrieval = useScope("retrieval");
  const edit = useAppStore((s) => s.editSettings);
  const diagnostics = useAppStore((s) => s.settings.diagnostics);
  const indexCheck = (diagnostics?.checks || []).find((c) => c.id === "research_agent.index");
  const vectorCheck = (diagnostics?.checks || []).find((c) => c.id === "research_agent.vector");
  return (
    <CategorySection category="retrieval" title="检索" description="检索与对话快速检索的默认参数；表单显式填写时会覆盖这里。">
      <Group title="默认参数">
        <FormGrid>
          <Field label="默认检索方式">
            <select className="form-input" value={retrieval.default_retrieval || "hybrid"} onChange={(e) => edit("retrieval", "default_retrieval", e.target.value)}>
              {["hybrid", "fts", "vector"].map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </Field>
          <Field label="默认范围">
            <select className="form-input" value={retrieval.default_scope || "library"} onChange={(e) => edit("retrieval", "default_scope", e.target.value)}>
              {["library", "collection", "library+boost"].map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </Field>
          <Field label="默认配置档">
            <input className="form-input" value={retrieval.default_profile || "default"} onChange={(e) => edit("retrieval", "default_profile", e.target.value)} />
          </Field>
          <NumberField scope="retrieval" name="default_limit" label="Top K 数量" value={retrieval.default_limit} />
          <NumberField scope="retrieval" name="default_evidence_per_article_limit" label="每篇文献证据数" value={retrieval.default_evidence_per_article_limit} />
          <NumberField scope="retrieval" name="default_year_from" label="起始年份" value={retrieval.default_year_from || ""} nullable />
          <NumberField scope="retrieval" name="default_year_to" label="结束年份" value={retrieval.default_year_to || ""} nullable />
        </FormGrid>
        <ToggleRow label="默认展开关联资产" checked={!!retrieval.default_expand_assets} onChange={(v) => edit("retrieval", "default_expand_assets", v)} />
      </Group>
      <Group title="状态（只读）">
        <CheckRow label="索引" check={indexCheck} />
        <CheckRow label="向量" check={vectorCheck} />
      </Group>
    </CategorySection>
  );
}

function EnvironmentCategory() {
  const research = useScope("research_agent");
  const memory = useScope("memory");
  const external = useScope("external_sources");
  const edit = useAppStore((s) => s.editSettings);
  const diagnostics = useAppStore((s) => s.settings.diagnostics);
  const refresh = useAppStore((s) => s.refreshDiagnostics);
  const stats = memory.stats || {};
  const externalCheck = (diagnostics?.checks || []).find((c) => c.id === "external_sources.scholarly");
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <h2 className="mb-3 font-serif text-[16px] text-ink-900">研究智能体</h2>
        <div className="grid gap-3">
          <ReadOnlyPath label="代码目录" value={research.code_dir} />
          <ReadOnlyPath label="数据目录" value={research.data_dir} />
          <ReadOnlyPath label="产物根目录" value={research.artifact_root} />
        </div>
        <div className="mt-3">
          <DiagnosticsList diagnostics={(diagnostics?.checks || []).filter((c) => c.id.startsWith("research_agent") && c.id !== "research_agent.index" && c.id !== "research_agent.vector")} />
        </div>
      </section>

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <h2 className="mb-3 font-serif text-[16px] text-ink-900">外部来源</h2>
        <div className="grid gap-2">
          <ExternalSourceRow label="arXiv" source={externalCheck?.detail?.arxiv} />
          <ExternalSourceRow label="Semantic Scholar" source={externalCheck?.detail?.semantic_scholar} />
          <ExternalSourceRow label="OpenAlex" source={externalCheck?.detail?.openalex} />
          <ExternalSourceRow label="Exa" source={externalCheck?.detail?.exa} />
          <ExternalSourceRow label="CrossRef" source={externalCheck?.detail?.crossref} />
        </div>
      </section>

      <CategorySection category="external_sources" title="外部来源配置" description="想法查新的世界范围学术检索默认配置。工作流页面后续只做本次运行覆盖。">
        <Group title="来源开关">
          <ToggleRow label="启用 arXiv" checked={!!external.arxiv_enabled} onChange={(v) => edit("external_sources", "arxiv_enabled", v)} />
          <ToggleRow label="启用 Semantic Scholar" checked={!!external.semantic_scholar_enabled} onChange={(v) => edit("external_sources", "semantic_scholar_enabled", v)} />
          <ToggleRow label="启用 OpenAlex" checked={!!external.openalex_enabled} onChange={(v) => edit("external_sources", "openalex_enabled", v)} />
          <ToggleRow label="启用 Exa 广域网页检索" checked={!!external.exa_enabled} onChange={(v) => edit("external_sources", "exa_enabled", v)} />
          <ToggleRow label="启用 CrossRef DOI 验证" checked={!!external.crossref_enabled} onChange={(v) => edit("external_sources", "crossref_enabled", v)} />
        </Group>
        <Group title="默认查新策略">
          <FormGrid>
            <NumberField scope="external_sources" name="default_year_window" label="默认年份窗口（年）" value={external.default_year_window} />
            <NumberField scope="external_sources" name="per_source_limit" label="每个来源 / 查询数量" value={external.per_source_limit} />
            <NumberField scope="external_sources" name="mark_concurrent_work_from_year" label="同期工作起始年" value={external.mark_concurrent_work_from_year} />
            <Field label="OpenAlex 联系邮箱">
              <input className="form-input" value={external.openalex_email || ""} onChange={(e) => edit("external_sources", "openalex_email", e.target.value)} placeholder="建议填写联系邮箱，降低限流风险" />
            </Field>
            <NumberField scope="external_sources" name="timeout_seconds" label="超时时间（秒）" value={external.timeout_seconds} />
            <NumberField scope="external_sources" name="retry_count" label="重试次数" value={external.retry_count} />
          </FormGrid>
          <ToggleRow label="允许未验证候选保留在报告中" checked={!!external.allow_unverified_candidates} onChange={(v) => edit("external_sources", "allow_unverified_candidates", v)} />
        </Group>
        <Group title="API 密钥">
          <div className="grid gap-2">
            <ExternalSecretRow
              label="Semantic Scholar API 密钥"
              sourceId="semantic_scholar"
              configured={!!external.semantic_scholar_key_configured}
              keySource={external.semantic_scholar_key_source}
              placeholder="可选，但强烈建议；否则容易 429"
            />
            <ExternalSecretRow
              label="Exa API 密钥"
              sourceId="exa"
              configured={!!external.exa_key_configured}
              keySource={external.exa_key_source}
              placeholder="可选；用于 broad web search"
            />
          </div>
        </Group>
      </CategorySection>

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <h2 className="mb-3 font-serif text-[16px] text-ink-900">存储</h2>
        <ReadOnlyPath label="记忆数据库路径" value={memory.db_path} />
        <div className="my-4 grid grid-cols-4 gap-3">
          {Object.entries(stats).filter(([, v]) => typeof v === "number").map(([key, v]) => (
            <div key={key} className="rounded-md border border-line bg-paper-50 p-3">
              <div className="font-mono text-[10.5px] text-ink-500">{key}</div>
              <div className="mt-1 font-serif text-[18px] text-ink-900">{v}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-line bg-paper-0 p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-serif text-[16px] text-ink-900">诊断</h2>
            <p className="mt-1 text-[12.5px] text-ink-500">单项失败不会阻塞设置页面。</p>
          </div>
          <button className="btn-dark" onClick={refresh}>刷新诊断</button>
        </div>
        <div className="mb-3"><StatusPill status={diagnostics?.overall || "warning"} text={`总体：${statusText(diagnostics?.overall || "unknown")}`} /></div>
        <DiagnosticsList diagnostics={diagnostics?.checks || []} />
      </section>
    </div>
  );
}

function ExternalSourceRow({ label, source }) {
  const status = source?.status || "warning";
  const details = [];
  if (source?.api_key_required) details.push(source.api_key_configured ? "密钥已配置" : "缺少密钥");
  else if (source?.api_key_configured) details.push("密钥已配置");
  if (source?.email_configured || source?.contact_email_configured) details.push("联系邮箱已配置");
  if (status === "skipped_no_api_key") details.push("缺少密钥，已跳过可选广域检索");
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-line bg-paper-50 px-3 py-2">
      <div>
        <div className="text-[13px] text-ink-800">{label}</div>
        <div className="text-[11.5px] text-ink-500">{details.join(" · ") || "无需密钥即可使用"}</div>
      </div>
      <StatusPill status={status === "ok" ? "ok" : "warning"} text={statusText(status)} />
    </div>
  );
}

function ExternalSecretRow({ label, sourceId, configured, keySource, placeholder }) {
  const save = useAppStore((s) => s.saveExternalSourceSecret);
  const clear = useAppStore((s) => s.clearExternalSourceSecret);
  const saving = useAppStore((s) => s.settings.saving);
  const [value, setValue] = useState("");
  const [localError, setLocalError] = useState("");
  const submit = async () => {
    if (!value.trim()) {
      setLocalError("请粘贴 API key");
      return;
    }
    setLocalError("");
    await save(sourceId, value.trim());
    setValue("");
  };
  const remove = async () => {
    if (keySource === "env") {
      setLocalError("当前密钥来自环境变量，需在启动环境中移除。");
      return;
    }
    await clear(sourceId);
  };
  return (
    <div className="rounded-md border border-line bg-paper-50 px-3 py-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-[13px] text-ink-800">{label}</div>
          <div className="text-[11.5px] text-ink-500">
            {configured ? `已配置${keySource ? ` · ${keySource}` : ""}` : "未配置"} · {placeholder}
          </div>
        </div>
        <StatusPill status={configured ? "ok" : "warning"} text={configured ? "已配置" : "未配置"} />
      </div>
      <div className="flex gap-2">
        <input
          type="password"
          autoComplete="off"
          className="form-input flex-1"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="加密保存，不明文返回"
        />
        <button className="btn-dark" disabled={saving} onClick={submit}>保存</button>
        <button className="btn-light" disabled={saving || !configured} onClick={remove}>清除</button>
      </div>
      {localError && <p className="mt-1.5 text-[12px] text-amber-700">{localError}</p>}
    </div>
  );
}

// ── Models sub-components (moved from the old workbench) ─────────────────────────

function ProfileRow({ profile, editing, onEdit, onClose }) {
  const activate = useAppStore((s) => s.activateModelProfile);
  const remove = useAppStore((s) => s.removeModelProfile);
  const reveal = useAppStore((s) => s.revealModelProfile);
  const test = useAppStore((s) => s.testModelProfile);
  const result = useAppStore((s) => s.modelProfiles.testById[profile.id]);
  const [shown, setShown] = useState(null);
  const [busy, setBusy] = useState(false);

  const copy = async () => {
    const key = await reveal(profile.id);
    if (key) await navigator.clipboard?.writeText(key);
  };
  const toggleReveal = async () => {
    if (shown) { setShown(null); return; }
    setShown(await reveal(profile.id));
  };
  const runTest = async () => { setBusy(true); try { await test(profile.id); } finally { setBusy(false); } };
  const onRemove = () => {
    const msg = profile.active
      ? "这是当前已激活的配置，删除后智能体将变为未就绪（或切回空服务商）。确认删除？"
      : "确认删除该模型配置？";
    if (window.confirm(msg)) remove(profile.id);
  };

  if (editing) {
    return (
      <div className="border-t border-line bg-paper-50 p-3"><ProfileForm profile={profile} onClose={onClose} /></div>
    );
  }

  return (
    <>
      <div className={clsx("grid grid-cols-[minmax(0,1.1fr)_minmax(170px,1fr)_minmax(0,1.2fr)_auto] items-center gap-3 border-t border-line px-3 py-2.5 text-[13px]", profile.active && "bg-amber/5")}>
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2 text-ink-900">
            {profile.active && <span className="h-1.5 w-1.5 rounded-full bg-amber" />} {profile.name}
          </div>
        </div>
        <div className="min-w-0">
          {profile.has_key ? (
            <div className="flex min-w-0 items-center gap-1.5">
              <code className="min-w-0 truncate font-mono text-[12px] text-ink-700">{shown || profile.key_masked}</code>
              <button title="显示/隐藏" className="text-ink-400 hover:text-ink-700" onClick={toggleReveal}>
                {shown ? <EyeOff size={13} /> : <Eye size={13} />}
              </button>
              <button title="复制完整密钥" className="text-ink-400 hover:text-ink-700" onClick={copy}><Copy size={13} /></button>
            </div>
          ) : (
            <span className="text-[12px] text-amber-700">未保存密钥，点编辑补充</span>
          )}
        </div>
        <div className="min-w-0">
          <div className="truncate text-ink-700">{profile.provider} · <span className="font-mono text-[12px]">{profile.model || "—"}</span></div>
          {profile.base_url && <div className="truncate font-mono text-[10.5px] text-ink-400">{profile.base_url}</div>}
        </div>
        <div data-testid="model-profile-actions" className="shrink-0">
          <div className="flex min-w-[112px] items-center justify-end gap-1.5">
            {profile.active ? (
              <StatusPill status="ok" text="已激活" />
            ) : (
              <button className="btn-light px-2 py-1 text-[12px]" onClick={() => activate(profile.id)}>激活</button>
            )}
            <button className="p-1 text-ink-400 hover:text-ink-700" title="测试连接" disabled={busy} onClick={runTest}><Activity size={14} /></button>
            <button className="p-1 text-ink-400 hover:text-ink-700" title="编辑配置 / 重新保存 API Key" onClick={onEdit}><Pencil size={14} /></button>
            <button className="p-1 text-ink-400 hover:text-red-600" title="删除" onClick={onRemove}><Trash2 size={14} /></button>
          </div>
        </div>
      </div>
      {result && (
        <div className="border-t border-line bg-paper-50 px-3 py-2"><ModelTestResult result={result} /></div>
      )}
    </>
  );
}

function ProfileForm({ profile, onClose }) {
  const create = useAppStore((s) => s.createModelProfile);
  const update = useAppStore((s) => s.updateModelProfile);
  const isEdit = !!profile;
  const [form, setForm] = useState(
    isEdit
      ? { name: profile.name, provider: profile.provider, base_url: profile.base_url, model: profile.model, api_key: "" }
      : { ...EMPTY_FORM, base_url: DEFAULT_BASE_URLS.openai || "" }
  );
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const onProvider = (next) => {
    setForm((f) => {
      const model = (f.model || "").trim();
      const baseUrl = (f.base_url || "").trim();
      return {
        ...f,
        provider: next,
        model: !model || AUTO_MODEL_VALUES.includes(model) ? (DEFAULT_MODELS[next] || "") : model,
        base_url: !baseUrl || AUTO_BASE_URL_VALUES.includes(baseUrl) ? (DEFAULT_BASE_URLS[next] || "") : baseUrl,
      };
    });
  };

  const needsBaseUrl = form.provider === "openai_compatible" && !(form.base_url || "").trim();
  // Make form validity VISIBLE: a missing required field used to silently
  // disable the button / early-return from submit with no feedback, so the user
  // thought "保存没反应". Now we say exactly what's missing.
  const [submitError, setSubmitError] = useState("");
  const invalidReason = !form.name.trim()
    ? "请填写名称"
    : !form.provider
    ? "请选择服务商"
    : needsBaseUrl
    ? "openai_compatible 需填写基础地址"
    : "";

  const submit = async () => {
    if (invalidReason) {
      setSubmitError(invalidReason);
      return;
    }
    setSubmitError("");
    setBusy(true);
    try {
      if (isEdit) await update(profile.id, form);
      else await create(form);
      onClose();
    } catch (e) {
      setSubmitError(e.message || "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mb-3 rounded-md border border-line bg-paper-50 p-3">
      <FormGrid>
        <Field label="名称"><input className="form-input" value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="如 DeepSeek 主力" /></Field>
        <Field label="服务商">
          <select className="form-input" value={form.provider} onChange={(e) => onProvider(e.target.value)}>
            {MODEL_PROVIDERS.filter((p) => p !== "none").map((p) => (
              <option key={p} value={p}>{SUPPORTED_PROVIDERS.includes(p) ? p : `${p}（待支持）`}</option>
            ))}
          </select>
        </Field>
        <Field label="模型">
          <input
            className="form-input"
            value={form.model}
            onChange={(e) => set("model", e.target.value)}
            placeholder={form.provider === "deepseek" ? "deepseek-chat" : "如 gpt-4o"}
            list={form.provider === "deepseek" ? "deepseek-model-options" : undefined}
          />
          {form.provider === "deepseek" && (
            <datalist id="deepseek-model-options">
              {DEEPSEEK_MODELS.map((model) => <option key={model} value={model} />)}
            </datalist>
          )}
        </Field>
        <Field label="基础地址"><input className="form-input" value={form.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder={form.provider === "openai_compatible" ? "必填" : "留空用默认"} /></Field>
        <Field label={isEdit ? "API Key（留空保留原密钥）" : "API Key"}>
          <input type="password" autoComplete="off" className="form-input" value={form.api_key} onChange={(e) => set("api_key", e.target.value)} placeholder="加密保存" />
        </Field>
      </FormGrid>
      {isEdit && (
        <p className="mt-2 text-[12px] text-ink-500">如果当前配置显示“未保存密钥”，请在这里重新粘贴 API Key 后保存。</p>
      )}
      {!SUPPORTED_PROVIDERS.includes(form.provider) && (
        <p className="mt-2 text-[12px] text-amber-700">该 provider 暂不支持 Agent，激活后文献检索问答会提示先配置可用模型。</p>
      )}
      {needsBaseUrl && <p className="mt-2 text-[12px] text-amber-700">openai_compatible 需要填写基础地址。</p>}
      {submitError && <p className="mt-2 text-[12px] text-red-600">{submitError}</p>}
      <div className="mt-3 flex items-center gap-2">
        <button className="btn-dark inline-flex items-center gap-1.5" disabled={busy} onClick={submit} title={invalidReason || undefined}>
          <Save size={14} /> {busy ? "保存中…" : isEdit ? "保存修改" : "创建并保存"}
        </button>
        <button className="btn-light" onClick={onClose}>取消</button>
        {invalidReason && !submitError && <span className="text-[12px] text-ink-400">{invalidReason}</span>}
      </div>
    </div>
  );
}

function AdvancedModelParams() {
  const models = useScope("models");
  return (
    <CategorySection category="models" title="高级参数" description="生成参数（作用于当前激活模型）。">
      <FormGrid>
        <NumberField scope="models" name="temperature" label="温度" value={models.temperature} step="0.1" />
        <NumberField scope="models" name="max_tokens" label="最大输出长度（0 或留空 = 模型最大值）" value={models.max_tokens} nullable />
        <NumberField scope="models" name="timeout_seconds" label="超时时间（秒）" value={models.timeout_seconds} />
        <NumberField scope="models" name="retry_count" label="重试次数" value={models.retry_count} />
      </FormGrid>
      <p className="mt-2 text-[12px] text-ink-500">
        最大输出长度用于限制模型单次回复规模。设为 0 或留空时不显式限制，由服务端使用该模型支持的最大输出长度。
      </p>
    </CategorySection>
  );
}

function MultimodalModelSettings({ profiles = [] }) {
  const models = useScope("models");
  const edit = useAppStore((s) => s.editSettings);
  const selectedProfile = profiles.find((profile) => profile.id === models.multimodal_profile_id);
  const inherited = !models.multimodal_profile_id;
  const ready = !!models.multimodal_enabled && !!((models.multimodal_model || "").trim() || selectedProfile?.model || inherited);
  return (
    <CategorySection category="models" title="多模态模型" description="用于结果审阅中的图片 / 表格 / 页面复核与补充。任务页只负责授权运行，不保存 API Key。">
      <Group title="启用状态">
        <div className="mb-3 flex items-center justify-between gap-3 rounded-md border border-line bg-paper-50 px-3 py-2">
          <div>
            <div className="text-[13px] text-ink-800">Run 级多模态复核</div>
            <div className="text-[11.5px] text-ink-500">默认不会自动修改最终数据，结果进入“多模态待确认”。</div>
          </div>
          <StatusPill status={ready ? "ok" : "warning"} text={ready ? "已就绪" : "未就绪"} />
        </div>
        <ToggleRow label="启用多模态审阅入口" checked={!!models.multimodal_enabled} onChange={(v) => edit("models", "multimodal_enabled", v)} />
      </Group>
      <Group title="模型选择">
        <FormGrid>
          <Field label="多模态配置档">
            <select className="form-input" value={models.multimodal_profile_id || ""} onChange={(e) => edit("models", "multimodal_profile_id", e.target.value)}>
              <option value="">继承当前生效模型</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name} · {profile.model || "未填写模型"}</option>
              ))}
            </select>
          </Field>
          <Field label="多模态模型名">
            <input
              className="form-input"
              value={models.multimodal_model || ""}
              onChange={(e) => edit("models", "multimodal_model", e.target.value)}
              placeholder={selectedProfile?.model || "如 gpt-4o；留空则继承"}
            />
          </Field>
          <Field label="默认扫描范围">
            <select className="form-input" value={models.multimodal_scan_default || "related_pages_assets"} onChange={(e) => edit("models", "multimodal_scan_default", e.target.value)}>
              <option value="evidence_only">仅检查已有证据</option>
              <option value="related_pages_assets">检查相关页面与图表</option>
              <option value="full_document">全篇深度扫描</option>
            </select>
          </Field>
        </FormGrid>
        <p className="mt-2 text-[12px] text-ink-500">
          请选择支持图片输入的模型。配置档的 API Key 在上方“模型配置档”中加密保存；这里不重复保存密钥。
        </p>
      </Group>
    </CategorySection>
  );
}

function ModelTestResult({ result }) {
  const ok = result.available;
  const reached = result.reached_server;
  const headline = ok ? "连接成功" : reached ? "请求被拒绝" : "无法连接";
  const hasLatency = typeof result.latency_ms === "number";
  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={ok ? "ok" : "error"} text={headline} />
        {hasLatency && <span className="text-[12px] text-ink-500">{ok ? "" : reached ? "往返耗时 " : "耗时 "}{result.latency_ms} ms</span>}
        {result.status_code && <span className="font-mono text-[11px] text-ink-500">HTTP {result.status_code}</span>}
        {result.model && <span className="font-mono text-[11.5px] text-ink-600">{result.model}</span>}
      </div>
      {!ok && reached && (
        <p className="mt-1.5 text-[12px] text-ink-500">已连到服务端（故有往返延迟），但服务端拒绝了请求 —— 这不是网络问题，而是密钥 / 模型 / 额度或服务商策略问题。</p>
      )}
      {result.message && <p className="mt-1.5 text-[12.5px] text-ink-600">{result.message}</p>}
      {result.error && <pre className="result-pre mt-2 max-h-[160px] overflow-auto">{result.error}</pre>}
    </div>
  );
}

// ── Shared presentational helpers ───────────────────────────────────────────────

function CategorySection({ category, title, description, children }) {
  const saveCategory = useAppStore((s) => s.saveCategory);
  const resetCategory = useAppStore((s) => s.resetCategory);
  const saving = useAppStore((s) => s.settings.saving);
  const draft = useAppStore((s) => s.settings.draft);
  const values = useAppStore((s) => s.settings.values);
  const fields = CATEGORY_FIELDS[category] || [];
  const dirty = fieldsDirty(fields, draft, values);
  return (
    <section className="rounded-lg border border-line bg-paper-0 p-4">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-[16px] text-ink-900">{title}</h2>
          {description && <p className="mt-1 text-[12.5px] text-ink-500">{description}</p>}
        </div>
        <div className="flex gap-2">
          <button className="btn-light inline-flex items-center gap-1.5" disabled={saving || !dirty} onClick={() => resetCategory(fields)}>
            <RotateCcw size={14} /> 重置
          </button>
          <button className="btn-dark inline-flex items-center gap-1.5" disabled={saving || !dirty} onClick={() => saveCategory(fields)}>
            <Save size={14} /> 保存
          </button>
        </div>
      </div>
      {children}
    </section>
  );
}

function Group({ title, children }) {
  return (
    <div className="mb-4 last:mb-0">
      {title && <div className="mb-2 font-mono text-[10.5px] uppercase tracking-[0.12em] text-ink-400">{title}</div>}
      {children}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] text-ink-500">{label}</span>
      {children}
    </label>
  );
}

function NumberField({ scope, name, label, value, step = "1", nullable = false }) {
  const edit = useAppStore((s) => s.editSettings);
  return (
    <Field label={label}>
      <input
        className="form-input"
        type="number"
        step={step}
        value={value ?? ""}
        onChange={(e) => {
          if (nullable && e.target.value === "") edit(scope, name, null);
          else edit(scope, name, step === "1" ? Number.parseInt(e.target.value || "0", 10) : Number(e.target.value));
        }}
      />
    </Field>
  );
}

function ToggleRow({ label, checked, onChange }) {
  return (
    <label className="mt-2 flex items-center justify-between gap-3 rounded-md border border-line bg-paper-50 px-3 py-2">
      <span className="text-[13px] text-ink-700">{label}</span>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function FormGrid({ children }) {
  return <div className="grid grid-cols-2 gap-3">{children}</div>;
}

function KV({ label, value, mono = false }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 py-0.5">
      <span className="text-ink-500">{label}</span>
      <span className={clsx("text-ink-900", mono && "font-mono text-[11.5px] break-all text-right")}>{value}</span>
    </div>
  );
}

function ReadOnlyPath({ label, value }) {
  return (
    <div className="rounded-md border border-line bg-paper-50 px-3 py-2">
      <div className="mb-1 text-[12px] text-ink-500">{label}</div>
      <code className="break-all font-mono text-[11.5px] text-ink-800">{value || "—"}</code>
    </div>
  );
}

function CheckRow({ label, check }) {
  const status = check?.status || "warning";
  const detail = check?.detail || {};
  const summary = detail.message || detail.reason || detail.vector_unavailable_reason || "";
  return (
    <div className="mt-2 flex items-center justify-between gap-3 rounded-md border border-line bg-paper-50 px-3 py-2">
      <span className="text-[13px] text-ink-700">{label}</span>
      <div className="flex items-center gap-2">
        {summary && <span className="text-[11.5px] text-ink-500">{String(summary)}</span>}
        <StatusPill status={status} text={statusText(status)} />
      </div>
    </div>
  );
}

function DiagnosticsList({ diagnostics }) {
  if (!diagnostics?.length) return <EmptyState text="暂无诊断结果。" />;
  return (
    <div className="space-y-2">
      {diagnostics.map((check) => (
        <div key={check.id} className="rounded-md border border-line bg-paper-50 p-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[13px] text-ink-900">{check.label}</div>
              <div className="font-mono text-[10.5px] text-ink-500">{check.id}</div>
            </div>
            <StatusPill status={check.status} text={statusText(check.status)} />
          </div>
          <pre className="result-pre mt-3 max-h-[220px] overflow-auto">{JSON.stringify(check.detail || {}, null, 2)}</pre>
        </div>
      ))}
    </div>
  );
}

function StatusPill({ status, text }) {
  return (
    <span className={clsx(
      "inline-flex rounded-full px-2 py-1 font-mono text-[10.5px]",
      status === "ok" ? "bg-teal/15 text-teal" : status === "error" ? "bg-red-50 text-red-700" : "bg-amber/15 text-ink-700"
    )}>
      {text}
    </span>
  );
}

function statusText(status) {
  return {
    ok: "正常",
    error: "错误",
    warning: "警告",
    unknown: "未知",
    configured: "已配置",
    missing: "未配置",
    skipped_no_api_key: "缺少密钥已跳过",
  }[status] || status || "-";
}

function fmtDateTime(value) {
  if (!value) return "—";
  const ms = typeof value === "number" && value < 100000000000 ? value * 1000 : value;
  try {
    return new Date(ms).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return String(value);
  }
}

function EmptyState({ text }) {
  return <div className="rounded-md border border-dashed border-line bg-paper-50 p-4 text-[13px] text-ink-500">{text}</div>;
}

function useScope(scope) {
  return useAppStore((s) => (s.settings.draft && s.settings.draft[scope]) || {});
}
