"use client";

import { BarChart2, Briefcase, Cpu, LayoutDashboard, LogIn, LogOut, MoreHorizontal, Search, ShieldCheck, UserRound, X } from "lucide-react";
import { useRef, useState } from "react";
import type { PageId } from "./Sidebar";
import type { MoneUserProfile } from "@/lib/userId";
import { useFocusTrap } from "@/lib/useFocusTrap";

interface BottomNavProps {
  current: PageId;
  onChange: (id: PageId) => void;
  isAdmin?: boolean;
  onAdminLogin?: () => void;
  userProfile?: MoneUserProfile | null;
  onUserLogout?: () => void;
}

const primaryTabs: { id: PageId; label: string; Icon: React.ElementType }[] = [
  { id: "home", label: "홈", Icon: LayoutDashboard },
  { id: "stocks", label: "탐색", Icon: Search },
  { id: "holdings", label: "보유", Icon: Briefcase },
  { id: "chart", label: "분석", Icon: BarChart2 },
];

const moreTabs: { id: PageId; label: string; desc: string; Icon: React.ElementType }[] = [
  { id: "advanced", label: "MONE 트레이딩", desc: "모의투자, AI 매매일지, 계산기, 몬테카를로, 전략검증", Icon: Cpu },
];

const adminTab: { id: PageId; label: string; desc: string; Icon: React.ElementType } = {
  id: "admin",
  label: "관리자",
  desc: "동기화, 캐시, 데이터 점검",
  Icon: ShieldCheck,
};

export default function BottomNav({ current, onChange, isAdmin = false, onAdminLogin, userProfile, onUserLogout }: BottomNavProps) {
  const [moreOpen, setMoreOpen] = useState(false);
  const moreTriggerRef = useRef<HTMLButtonElement | null>(null);
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const visibleMoreTabs = isAdmin ? [...moreTabs, adminTab] : moreTabs;
  const isMoreActive = current === "admin" || visibleMoreTabs.some((t) => t.id === current);

  const handlePrimary = (id: PageId) => {
    onChange(id);
    setMoreOpen(false);
  };

  const handleMore = (id: PageId) => {
    onChange(id);
    setMoreOpen(false);
  };

  const closeMore = () => {
    setMoreOpen(false);
    window.setTimeout(() => moreTriggerRef.current?.focus(), 0);
  };

  useFocusTrap(moreOpen, sheetRef, closeMore);

  return (
    <>
      {moreOpen && (
        <>
          <button type="button" className="fixed inset-0 z-40 cursor-default md:hidden" onClick={closeMore} aria-label="더보기 닫기" />
          <div
            ref={sheetRef}
            id="mone-more-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mone-more-title"
            tabIndex={-1}
            className="fixed left-0 right-0 z-50 rounded-t-2xl border-t border-slate-700 bg-slate-900 px-3 pt-4 outline-none md:hidden"
            style={{ bottom: "56px" }}
          >
            <div className="mb-3 flex items-center justify-between">
              <span id="mone-more-title" className="text-sm font-semibold text-slate-200">더보기</span>
              <button
                type="button"
                onClick={closeMore}
                className="flex h-11 w-11 items-center justify-center rounded-full text-slate-400 transition-[background-color,transform] active:scale-[0.96]"
                aria-label="닫기"
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-800/90"><X size={18} /></span>
              </button>
            </div>
            <div className="grid gap-2 pb-4">
              {visibleMoreTabs.map(({ id, label, desc, Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => handleMore(id)}
                  className={`flex items-center gap-3 rounded-xl p-3 text-left transition-colors active:scale-[0.96] ${
                    current === id
                      ? "bg-blue-500/20 text-blue-400 ring-1 ring-blue-500/30"
                      : "bg-slate-800 text-slate-300 active:bg-slate-700"
                  }`}
                  aria-current={current === id ? "page" : undefined}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-950/70">
                    <Icon size={18} aria-hidden="true" />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13px] font-bold">{label}</span>
                    <span className="mt-0.5 block text-[11px] text-slate-500">{desc}</span>
                  </span>
                </button>
              ))}
              {!isAdmin && (
                userProfile ? (
                  /* OAuth 로그인 상태 */
                  <div className="flex items-center gap-3 rounded-xl bg-amber-500/10 p-3 ring-1 ring-amber-500/20">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/15">
                      <UserRound size={18} className="text-amber-300" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-bold text-amber-200">
                        {userProfile.name || userProfile.email || userProfile.provider || "사용자"}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-slate-500">로그인됨 · {userProfile.provider || "oauth"}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => { onUserLogout?.(); setMoreOpen(false); }}
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-800 hover:text-slate-200"
                      title="로그아웃"
                      aria-label="로그아웃"
                    >
                      <LogOut size={16} aria-hidden="true" />
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      onAdminLogin?.();
                      setMoreOpen(false);
                    }}
                    className={`flex items-center gap-3 rounded-xl p-3 text-left transition-colors active:scale-[0.96] ${
                      current === "admin" ? "bg-blue-500/20 text-blue-400 ring-1 ring-blue-500/30" : "bg-slate-800 text-slate-300 active:bg-slate-700"
                    }`}
                    aria-current={current === "admin" ? "page" : undefined}
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-950/70">
                      <LogIn size={18} />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-bold">로그인</span>
                      <span className="mt-0.5 block text-[11px] text-slate-500">관리자, 카카오, 구글 로그인</span>
                    </span>
                  </button>
                )
              )}
            </div>
          </div>
        </>
      )}

      <nav
        className="fixed bottom-0 left-0 right-0 z-30 border-t border-slate-800 bg-slate-950/95 backdrop-blur md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="flex h-14">
          {primaryTabs.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => handlePrimary(id)}
              className={`flex flex-1 flex-col items-center justify-center gap-1 transition-colors active:scale-[0.96] ${
                current === id ? "text-blue-400" : "text-slate-500"
              }`}
              aria-current={current === id ? "page" : undefined}
            >
              <Icon size={20} strokeWidth={current === id ? 2.5 : 1.8} aria-hidden="true" />
              <span className="text-[10px] font-medium">{label}</span>
            </button>
          ))}

          <button
            ref={moreTriggerRef}
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            className={`flex flex-1 flex-col items-center justify-center gap-1 transition-colors active:scale-[0.96] ${
              isMoreActive || moreOpen ? "text-blue-400" : "text-slate-500"
            }`}
            aria-expanded={moreOpen}
            aria-controls="mone-more-sheet"
            aria-haspopup="dialog"
          >
            <MoreHorizontal size={20} strokeWidth={isMoreActive || moreOpen ? 2.5 : 1.8} aria-hidden="true" />
            <span className="text-[10px] font-medium">더보기</span>
            {isMoreActive && (
              <span className="absolute mt-0 h-1 w-1 rounded-full bg-blue-400" style={{ marginTop: "-18px" }} />
            )}
          </button>
        </div>
      </nav>
    </>
  );
}
