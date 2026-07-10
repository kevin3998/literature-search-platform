import React, { useState } from "react";
import { LogIn, UserPlus } from "lucide-react";
import { useAppStore } from "../store/useAppStore";

export default function AuthScreen() {
  const mode = useAppStore((s) => s.auth.mode);
  const loading = useAppStore((s) => s.auth.loading);
  const error = useAppStore((s) => s.auth.error);
  const setAuthMode = useAppStore((s) => s.setAuthMode);
  const authLogin = useAppStore((s) => s.authLogin);
  const authSignup = useAppStore((s) => s.authSignup);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const signup = mode === "signup";

  const submit = (event) => {
    event.preventDefault();
    if (signup) {
      authSignup({ email, display_name: displayName, password });
    } else {
      authLogin({ email, password });
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-paper-50 px-4">
      <form onSubmit={submit} className="w-full max-w-[360px] rounded-lg border border-line bg-paper-0 p-5 shadow-xl">
        <div className="mb-4 flex items-center gap-2">
          {signup ? <UserPlus size={18} className="text-ink-700" /> : <LogIn size={18} className="text-ink-700" />}
          <h1 className="font-serif text-[18px] text-ink-900">{signup ? "注册账号" : "登录"}</h1>
        </div>

        {error && <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700">{error}</div>}

        <label className="mb-3 block text-[12.5px] text-ink-700">
          邮箱
          <input className="form-input mt-1" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" />
        </label>

        {signup && (
          <label className="mb-3 block text-[12.5px] text-ink-700">
            显示名
            <input className="form-input mt-1" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required autoComplete="name" />
          </label>
        )}

        <label className="mb-4 block text-[12.5px] text-ink-700">
          密码
          <input className="form-input mt-1" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} autoComplete={signup ? "new-password" : "current-password"} />
        </label>

        <button className="btn-dark w-full" type="submit" disabled={loading}>
          {loading ? "处理中..." : signup ? "注册并进入" : "登录"}
        </button>
        <button className="mt-3 w-full rounded-md px-2 py-1.5 text-[12.5px] text-ink-500 hover:bg-paper-100 hover:text-ink-900" type="button" onClick={() => setAuthMode(signup ? "login" : "signup")}>
          {signup ? "已有账号，去登录" : "没有账号，注册一个"}
        </button>
      </form>
    </div>
  );
}
