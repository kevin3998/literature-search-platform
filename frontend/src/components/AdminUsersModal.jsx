import React from "react";
import { Edit3, KeyRound, LogOut, RefreshCw, Search, Shield, ShieldOff, Unplug, UserCheck, UserX, X } from "lucide-react";
import { useAppStore } from "../store/useAppStore";

export default function AdminUsersModal() {
  const open = useAppStore((s) => s.adminUsersOpen);
  const adminUsers = useAppStore((s) => s.adminUsers);
  const closeAdminUsers = useAppStore((s) => s.closeAdminUsers);
  const updateAdminUsers = useAppStore((s) => s.updateAdminUsers);
  const loadAdminUsers = useAppStore((s) => s.loadAdminUsers);
  const updateAdminUser = useAppStore((s) => s.updateAdminUser);
  const resetPassword = useAppStore((s) => s.resetAdminUserPassword);
  const revokeSessions = useAppStore((s) => s.revokeAdminUserSessions);
  const revokeApiTokens = useAppStore((s) => s.revokeAdminUserApiTokens);

  if (!open) return null;

  const runSearch = (event) => {
    event.preventDefault();
    loadAdminUsers({ query: adminUsers.query || "", includeSystem: !!adminUsers.includeSystem }).catch(() => {});
  };

  const toggleIncludeSystem = (event) => {
    loadAdminUsers({ includeSystem: event.target.checked }).catch(() => {});
  };

  const editDisplayName = async (user) => {
    const userId = user.user_id || user.userId;
    const currentName = user.display_name || user.displayName || "";
    const nextName = window.prompt("编辑显示名", currentName);
    if (!nextName || nextName.trim() === currentName) return;
    await updateAdminUser(userId, { display_name: nextName.trim() });
  };

  const toggleRole = async (user) => {
    const userId = user.user_id || user.userId;
    const isAdmin = (user.role || "user") === "admin";
    const nextRole = isAdmin ? "user" : "admin";
    if (!window.confirm(isAdmin ? "确认设为普通用户？" : "确认设为管理员？")) return;
    await updateAdminUser(userId, { role: nextRole });
  };

  const toggleStatus = async (user) => {
    const userId = user.user_id || user.userId;
    const isActive = (user.status || "active") === "active";
    if (isActive && !window.confirm("确认禁用该用户？")) return;
    await updateAdminUser(userId, { status: isActive ? "disabled" : "active" });
  };

  const resetUserPassword = async (user) => {
    if (user.has_password === false || user.hasPassword === false) return;
    const nextPassword = window.prompt(`为 ${user.email || user.display_name || user.user_id} 设置新密码`);
    if (!nextPassword) return;
    await resetPassword(user.user_id || user.userId, nextPassword);
  };

  const revokeUserSessions = async (user) => {
    if (!window.confirm("确认撤销该用户的登录会话？")) return;
    await revokeSessions(user.user_id || user.userId);
  };

  const revokeUserApiTokens = async (user) => {
    if (!window.confirm("确认撤销该用户的 API Tokens？")) return;
    await revokeApiTokens(user.user_id || user.userId);
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-6" onMouseDown={closeAdminUsers}>
      <div className="flex max-h-[88vh] w-full max-w-[1180px] flex-col overflow-hidden rounded-xl border border-line bg-paper-0 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex min-h-14 flex-shrink-0 items-center justify-between gap-4 border-b border-line px-5">
          <div>
            <h1 className="font-serif text-[16px] text-ink-900">用户管理</h1>
          </div>
          <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
            <form className="relative w-full max-w-[280px]" onSubmit={runSearch}>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400" size={14} />
              <input
                className="form-input h-8 w-full pl-8 text-[12px]"
                value={adminUsers.query || ""}
                onChange={(event) => updateAdminUsers({ query: event.target.value })}
                placeholder="搜索"
              />
            </form>
            <label className="inline-flex h-8 flex-shrink-0 items-center gap-2 rounded-md border border-line px-2.5 text-[12px] text-ink-600 hover:bg-paper-50">
              <input type="checkbox" checked={!!adminUsers.includeSystem} onChange={toggleIncludeSystem} disabled={adminUsers.loading} />
              显示系统身份
            </label>
            <button className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line text-ink-500 hover:bg-paper-100 hover:text-ink-900" type="button" title="刷新" onClick={() => loadAdminUsers().catch(() => {})} disabled={adminUsers.loading}>
              <RefreshCw size={15} className={adminUsers.loading ? "animate-spin" : ""} />
            </button>
            <button className="inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-400 hover:bg-paper-100 hover:text-ink-900" type="button" title="关闭" onClick={closeAdminUsers}>
              <X size={16} />
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-auto p-5">
          {adminUsers.error && <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700">{adminUsers.error}</div>}
          {adminUsers.loading && adminUsers.items.length === 0 ? (
            <div className="rounded-md border border-dashed border-line bg-paper-50 p-4 text-[13px] text-ink-500">正在加载用户…</div>
          ) : adminUsers.items.length === 0 ? (
            <div className="rounded-md border border-dashed border-line bg-paper-50 p-4 text-[13px] text-ink-500">暂无用户。</div>
          ) : (
            <div className="min-w-[1060px] overflow-hidden rounded-md border border-line">
              <div className="grid grid-cols-[minmax(210px,1.2fr)_minmax(150px,0.8fr)_120px_88px_96px_120px_260px] gap-3 border-b border-line bg-paper-50 px-3 py-2 text-[12px] font-medium text-ink-500">
                <div>邮箱</div>
                <div>显示名</div>
                <div>账号类型</div>
                <div>role</div>
                <div>status</div>
                <div>最近登录</div>
                <div className="text-right">操作</div>
              </div>
              {adminUsers.items.map((user) => (
                <UserRow
                  key={user.user_id || user.userId}
                  user={user}
                  loading={adminUsers.loading}
                  editDisplayName={editDisplayName}
                  toggleRole={toggleRole}
                  toggleStatus={toggleStatus}
                  resetPassword={resetUserPassword}
                  revokeSessions={revokeUserSessions}
                  revokeApiTokens={revokeUserApiTokens}
                />
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function UserRow({ user, loading, editDisplayName, toggleRole, toggleStatus, resetPassword, revokeSessions, revokeApiTokens }) {
  const role = user.role || "user";
  const status = user.status || "active";
  const accountType = user.account_type || user.accountType || "system";
  const isSystemIdentity = user.is_system_identity ?? user.isSystemIdentity ?? accountType === "system";
  const hasPassword = user.has_password ?? user.hasPassword ?? false;
  const providers = user.providers || [];
  const providerTitle = providers.length ? providers.join(", ") : accountType;

  return (
    <div className="grid grid-cols-[minmax(210px,1.2fr)_minmax(150px,0.8fr)_120px_88px_96px_120px_260px] items-center gap-3 border-b border-line px-3 py-2 text-[12.5px] last:border-b-0">
      <div className="min-w-0 truncate text-ink-900" title={user.email || ""}>{user.email || "—"}</div>
      <div className="min-w-0 truncate text-ink-700" title={user.display_name || user.displayName || ""}>{user.display_name || user.displayName || "—"}</div>
      <div>
        <span className={`inline-flex max-w-full items-center rounded-md border px-2 py-1 text-[11px] ${isSystemIdentity ? "border-amber/30 bg-amber/10 text-amber" : "border-teal/30 bg-teal/10 text-teal"}`} title={providerTitle}>
          {isSystemIdentity ? "系统/历史身份" : "本地账号"}
        </span>
      </div>
      <div>
        <span className={`inline-flex rounded-md border px-2 py-1 font-mono text-[11px] ${role === "admin" ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-line bg-paper-50 text-ink-600"}`}>
          {role}
        </span>
      </div>
      <div>
        <span className={`inline-flex rounded-md border px-2 py-1 font-mono text-[11px] ${status === "active" ? "border-teal/30 bg-teal/10 text-teal" : "border-red-200 bg-red-50 text-red-600"}`}>
          {status}
        </span>
      </div>
      <div className="font-mono text-[11px] text-ink-500">{fmtDateTime(user.last_login_at || user.lastLoginAt)}</div>
      <div className="flex justify-end gap-1">
        <IconButton title="编辑显示名" Icon={Edit3} onClick={() => editDisplayName(user)} disabled={loading} />
        <IconButton title={role === "admin" ? "设为普通用户" : "设为管理员"} Icon={role === "admin" ? ShieldOff : Shield} onClick={() => toggleRole(user)} disabled={loading} danger={role === "admin"} />
        <IconButton title={status === "active" ? "禁用" : "启用"} Icon={status === "active" ? UserX : UserCheck} onClick={() => toggleStatus(user)} disabled={loading} danger={status === "active"} />
        <IconButton title={hasPassword ? "重置密码" : "无密码凭据"} Icon={KeyRound} onClick={() => resetPassword(user)} disabled={loading || !hasPassword} />
        <IconButton title="撤销会话" Icon={LogOut} onClick={() => revokeSessions(user)} disabled={loading} danger />
        <IconButton title="撤销 API Tokens" Icon={Unplug} onClick={() => revokeApiTokens(user)} disabled={loading} danger />
      </div>
    </div>
  );
}

function IconButton({ title, Icon, onClick, disabled = false, danger = false }) {
  return (
    <button
      className={`inline-flex h-8 w-8 items-center justify-center rounded-md border transition ${danger ? "border-red-200 text-red-600 hover:bg-red-50" : "border-line text-ink-500 hover:bg-paper-100 hover:text-ink-900"} disabled:cursor-not-allowed disabled:opacity-40`}
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
    >
      <Icon size={14} />
    </button>
  );
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
