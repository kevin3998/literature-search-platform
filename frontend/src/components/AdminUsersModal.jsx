import React from "react";
import { RotateCcw, X } from "lucide-react";
import { useAppStore } from "../store/useAppStore";

export default function AdminUsersModal() {
  const open = useAppStore((s) => s.adminUsersOpen);
  const adminUsers = useAppStore((s) => s.adminUsers);
  const closeAdminUsers = useAppStore((s) => s.closeAdminUsers);
  const loadAdminUsers = useAppStore((s) => s.loadAdminUsers);
  const updateAdminUser = useAppStore((s) => s.updateAdminUser);
  const resetPassword = useAppStore((s) => s.resetAdminUserPassword);

  if (!open) return null;

  const resetUserPassword = async (user) => {
    const nextPassword = window.prompt(`为 ${user.email || user.display_name || user.user_id} 设置新密码`);
    if (!nextPassword) return;
    await resetPassword(user.user_id || user.userId, nextPassword);
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-6" onMouseDown={closeAdminUsers}>
      <div className="flex max-h-[86vh] w-full max-w-[980px] flex-col overflow-hidden rounded-xl border border-line bg-paper-0 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex h-12 flex-shrink-0 items-center justify-between border-b border-line px-5">
          <div>
            <h1 className="font-serif text-[16px] text-ink-900">用户管理</h1>
            <div className="text-[12px] text-ink-500">普通用户 / 管理员，active / disabled</div>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-light" type="button" onClick={() => loadAdminUsers()} disabled={adminUsers.loading}>刷新</button>
            <button className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-400 hover:bg-paper-100 hover:text-ink-900" type="button" title="关闭" onClick={closeAdminUsers}>
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
            <div className="min-w-[760px] overflow-hidden rounded-md border border-line">
              <div className="grid grid-cols-[minmax(220px,1.2fr)_minmax(150px,0.8fr)_110px_120px_130px_110px] gap-3 border-b border-line bg-paper-50 px-3 py-2 text-[12px] font-medium text-ink-500">
                <div>邮箱</div>
                <div>显示名</div>
                <div>role</div>
                <div>status</div>
                <div>最近登录</div>
                <div className="text-right">操作</div>
              </div>
              {adminUsers.items.map((user) => {
                const userId = user.user_id || user.userId;
                return (
                  <div key={userId} className="grid grid-cols-[minmax(220px,1.2fr)_minmax(150px,0.8fr)_110px_120px_130px_110px] gap-3 border-b border-line px-3 py-2 text-[12.5px] last:border-b-0">
                    <div className="min-w-0 truncate text-ink-900">{user.email || "—"}</div>
                    <div className="min-w-0 truncate text-ink-700">{user.display_name || user.displayName || "—"}</div>
                    <select className="form-input h-8 py-1" value={user.role || "user"} onChange={(event) => updateAdminUser(userId, { role: event.target.value })} disabled={adminUsers.loading}>
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                    <select className="form-input h-8 py-1" value={user.status || "active"} onChange={(event) => updateAdminUser(userId, { status: event.target.value })} disabled={adminUsers.loading}>
                      <option value="active">active</option>
                      <option value="disabled">disabled / 禁用</option>
                    </select>
                    <div className="font-mono text-[11px] text-ink-500">{fmtDateTime(user.last_login_at || user.lastLoginAt)}</div>
                    <div className="flex justify-end">
                      <button className="inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-500 hover:bg-paper-100 hover:text-ink-900" type="button" title="重置密码" onClick={() => resetUserPassword(user)} disabled={adminUsers.loading}>
                        <RotateCcw size={14} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </main>
      </div>
    </div>
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
