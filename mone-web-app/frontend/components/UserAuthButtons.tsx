"use client";

import { LogOut, UserRound, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { clearAuthenticatedUser, getUserId, getUserProfile, type MoneUserProfile } from "@/lib/userId";

export default function UserAuthButtons() {
  const [profile, setProfile] = useState<MoneUserProfile | null>(null);
  const [loggingIn, setLoggingIn] = useState<"google" | "kakao" | null>(null);

  useEffect(() => {
    setProfile(getUserProfile());
  }, []);

  const login = async (provider: "google" | "kakao") => {
    setLoggingIn(provider);
    // 백엔드 cold-start 대기: health check로 서버 깨우기
    try {
      await fetch("/mone-api/health", { method: "GET", cache: "no-store", signal: AbortSignal.timeout(55000) });
    } catch {
      // health check 실패해도 OAuth 시도는 계속 (에러는 OAuth 단에서 처리)
    }
    const anonId = encodeURIComponent(getUserId());
    window.location.href = `/mone-api/api/auth/oauth/${provider}/start?anonId=${anonId}`;
  };

  const logout = () => {
    clearAuthenticatedUser();
    setProfile(null);
    window.location.reload();
  };

  if (profile?.userId) {
    return (
      <div className="flex max-w-[132px] items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/50 px-1.5 py-1 text-[11px] text-slate-300 sm:max-w-[180px] sm:px-2 sm:text-xs">
        <UserRound size={13} className="shrink-0" />
        <span className="min-w-0 truncate">{profile.name || profile.email || profile.provider || "로그인"}</span>
        <button
          type="button"
          onClick={logout}
          className="ml-0.5 shrink-0 text-slate-500 hover:text-slate-200"
          title="로그아웃"
        >
          <LogOut size={13} />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => login("google")}
        disabled={loggingIn != null}
        className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800/50 px-1.5 py-1 text-[11px] text-slate-300 hover:border-blue-500 hover:text-white disabled:opacity-60 sm:px-2 sm:text-xs"
      >
        {loggingIn === "google" ? <><Loader2 size={11} className="animate-spin" />서버 연결중</> : "Google"}
      </button>
      <button
        type="button"
        onClick={() => login("kakao")}
        disabled={loggingIn != null}
        className="flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-1.5 py-1 text-[11px] text-amber-200 hover:bg-amber-500/20 disabled:opacity-60 sm:px-2 sm:text-xs"
      >
        {loggingIn === "kakao" ? <><Loader2 size={11} className="animate-spin" />서버 연결중</> : "Kakao"}
      </button>
    </div>
  );
}
