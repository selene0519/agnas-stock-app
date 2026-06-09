"use client";

import { FormEvent, useState } from "react";
import { Lock, LogIn, ShieldCheck, UserRound } from "lucide-react";

interface AdminLoginPageProps {
  onSuccess: (token: string) => void;
  onUserLogin?: (provider: "google" | "kakao") => void;
}

export default function AdminLoginPage({ onSuccess, onUserLogin }: AdminLoginPageProps) {
  const [adminId, setAdminId] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!adminId.trim() || !password.trim()) return;
    setLoading(true);
    setMessage("");
    try {
      const res = await fetch("/mone-api/api/auth/admin-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ adminId, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.token) {
        const code = data.code || data.status || "LOGIN_FAILED";
        setMessage(code === "ADMIN_AUTH_NOT_CONFIGURED" ? "관리자 ID/비밀번호 환경변수가 아직 설정되지 않았습니다." : "관리자 ID 또는 비밀번호를 확인해주세요.");
        return;
      }
      onSuccess(String(data.token));
      setAdminId("");
      setPassword("");
    } catch (error) {
      setMessage(`로그인 요청 실패: ${error}`);
    } finally {
      setLoading(false);
    }
  }

  const startOAuth = (provider: "google" | "kakao") => {
    if (onUserLogin) {
      onUserLogin(provider);
      return;
    }
    window.location.href = `/mone-api/api/auth/oauth/${provider}/start`;
  };

  return (
    <div className="flex min-h-[70vh] items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/70 p-5 shadow-2xl">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-blue-500/15 text-blue-300">
            <LogIn size={21} />
          </span>
          <div>
            <h1 className="text-xl font-bold text-slate-100">로그인</h1>
            <p className="text-xs text-slate-500">카카오, 구글, 관리자 로그인을 한 화면에서 선택하세요.</p>
          </div>
        </div>

        <div className="mt-6 grid gap-2">
          <button
            type="button"
            onClick={() => startOAuth("kakao")}
            className="flex h-12 items-center justify-center rounded-xl border border-amber-400/50 bg-amber-300 text-sm font-bold text-slate-950 transition-colors hover:bg-amber-200"
          >
            카카오로 시작하기
          </button>
          <button
            type="button"
            onClick={() => startOAuth("google")}
            className="flex h-12 items-center justify-center rounded-xl border border-slate-700 bg-slate-950 text-sm font-bold text-slate-100 transition-colors hover:border-blue-400/70"
          >
            Google로 시작하기
          </button>
        </div>

        <div className="my-6 flex items-center gap-3">
          <span className="h-px flex-1 bg-slate-800" />
          <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-600">관리자 로그인</span>
          <span className="h-px flex-1 bg-slate-800" />
        </div>

        <form onSubmit={submit}>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <ShieldCheck size={16} className="text-blue-300" />
            관리자 권한
          </div>

          <label className="mt-4 block text-xs font-medium text-slate-400" htmlFor="admin-id">
            관리자 ID
          </label>
          <div className="mt-2 flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 focus-within:border-blue-500/70">
            <UserRound size={16} className="shrink-0 text-slate-500" />
            <input
              id="admin-id"
              type="text"
              value={adminId}
              onChange={(event) => setAdminId(event.target.value)}
              className="min-w-0 flex-1 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-700"
              placeholder="관리자 ID"
              autoComplete="username"
            />
          </div>

          <label className="mt-4 block text-xs font-medium text-slate-400" htmlFor="admin-password">
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
            disabled={loading || !adminId.trim() || !password.trim()}
            className="mt-4 flex h-11 w-full items-center justify-center rounded-xl bg-blue-600 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "로그인 중..." : "관리자 로그인"}
          </button>
        </form>
      </div>
    </div>
  );
}
