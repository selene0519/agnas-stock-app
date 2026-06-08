"use client";

import { LogOut, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { clearAuthenticatedUser, getUserProfile, type MoneUserProfile } from "@/lib/userId";

export default function UserAuthButtons() {
  const [profile, setProfile] = useState<MoneUserProfile | null>(null);

  useEffect(() => {
    setProfile(getUserProfile());
  }, []);

  const login = (provider: "google" | "kakao") => {
    window.location.href = `/mone-api/api/auth/oauth/${provider}/start`;
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
        className="rounded-lg border border-slate-700 bg-slate-800/50 px-1.5 py-1 text-[11px] text-slate-300 hover:border-blue-500 hover:text-white sm:px-2 sm:text-xs"
      >
        Google
      </button>
      <button
        type="button"
        onClick={() => login("kakao")}
        className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-1.5 py-1 text-[11px] text-amber-200 hover:bg-amber-500/20 sm:px-2 sm:text-xs"
      >
        Kakao
      </button>
    </div>
  );
}
