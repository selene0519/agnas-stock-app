"use client";

import { FormEvent, useState } from "react";
import { Lock, ShieldCheck } from "lucide-react";

interface AdminLoginPageProps {
  onSuccess: (token: string) => void;
}

export default function AdminLoginPage({ onSuccess }: AdminLoginPageProps) {
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password.trim()) return;
    setLoading(true);
    setMessage("");
    try {
      const res = await fetch("/mone-api/api/auth/admin-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.token) {
        const code = data.code || data.status || "LOGIN_FAILED";
        setMessage(code === "ADMIN_AUTH_NOT_CONFIGURED" ? "관리자 비밀번호 환경변수가 아직 설정되지 않았습니다." : "관리자 비밀번호를 확인해주세요.");
        return;
      }
      onSuccess(String(data.token));
      setPassword("");
    } catch (error) {
      setMessage(`로그인 요청 실패: ${error}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-[70vh] items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-slate-800 bg-slate-900/70 p-5 shadow-2xl">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/15 text-blue-300">
            <ShieldCheck size={20} />
          </span>
          <div>
            <h1 className="text-lg font-bold text-slate-100">관리자 로그인</h1>
            <p className="text-xs text-slate-500">관리자 기능은 로그인 후에만 표시됩니다.</p>
          </div>
        </div>

        <label className="mt-5 block text-xs font-medium text-slate-400" htmlFor="admin-password">
          비밀번호
        </label>
        <div className="mt-2 flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 focus-within:border-blue-500/70">
          <Lock size={16} className="shrink-0 text-slate-500" />
          <input
            id="admin-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="min-w-0 flex-1 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-700"
            placeholder="관리자 비밀번호"
            autoComplete="current-password"
          />
        </div>

        {message && <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">{message}</div>}

        <button
          type="submit"
          disabled={loading || !password.trim()}
          className="mt-4 flex h-10 w-full items-center justify-center rounded-xl bg-blue-600 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "로그인 중..." : "로그인"}
        </button>
      </form>
    </div>
  );
}
