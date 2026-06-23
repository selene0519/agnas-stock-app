"use client";

import { BarChart2, Briefcase, ChevronRight, Cpu, LayoutDashboard, LogIn, LogOut, MoreHorizontal, Search, ShieldCheck, UserRound } from "lucide-react";
import Image from "next/image";
import { useState } from "react";
import type { MoneUserProfile } from "@/lib/userId";

export type PageId =
  | "home"
  | "report"
  | "stocks"
  | "holdings"
  | "chart"
  | "news"
  | "prediction"
  | "advanced"
  | "paper"
  | "journal"
  | "broker"
  | "admin";

const primaryItems: { id: PageId; label: string; icon: React.ReactNode }[] = [
  { id: "home", label: "MONE 홈", icon: <LayoutDashboard size={16} /> },
  { id: "stocks", label: "종목 탐색", icon: <Search size={16} /> },
  { id: "holdings", label: "보유·리스크", icon: <Briefcase size={16} /> },
  { id: "chart", label: "분석", icon: <BarChart2 size={16} /> },
];

const moreItems: { id: PageId; label: string; icon: React.ReactNode }[] = [
  { id: "advanced", label: "MONE 트레이딩", icon: <Cpu size={16} /> },
];

const adminItem: { id: PageId; label: string; icon: React.ReactNode } = {
  id: "admin",
  label: "관리자",
  icon: <ShieldCheck size={16} />,
};

interface Props {
  current: PageId;
  onChange: (id: PageId) => void;
  isAdmin?: boolean;
  onAdminLogin?: () => void;
  onAdminLogout?: () => void;
  userProfile?: MoneUserProfile | null;
  onUserLogout?: () => void;
}

function BrandMark({ collapsed }: { collapsed: boolean }) {
  if (collapsed) {
    return (
      <div className="flex w-full items-center justify-center">
        <Image src="/brand/mone-symbol.png" alt="MONE" width={34} height={34} className="h-8 w-8 object-contain" priority />
      </div>
    );
  }

  return (
    <div className="flex min-w-0 items-center gap-3">
      <Image src="/brand/mone-symbol.png" alt="MONE" width={34} height={34} className="h-8 w-8 shrink-0 object-contain" priority />
      <div className="min-w-0">
        <div className="font-mono text-[20px] font-semibold leading-none tracking-[0.32em] text-slate-100">MONE</div>
        <div className="mt-1 text-[9px] font-medium tracking-[0.22em] text-slate-500">AGNAS STOCK APP</div>
      </div>
    </div>
  );
}

export default function Sidebar({ current, onChange, isAdmin = false, onAdminLogin, onAdminLogout, userProfile, onUserLogout }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const visibleMoreItems = isAdmin ? [...moreItems, adminItem] : moreItems;

  const SidebarContent = () => (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-5">
        <BrandMark collapsed={collapsed} />
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="ml-auto hidden text-slate-500 transition-colors hover:text-slate-300 md:block"
          title={collapsed ? "메뉴 펼치기" : "메뉴 접기"}
        >
          <ChevronRight size={14} className={`transition-transform ${collapsed ? "" : "rotate-180"}`} />
        </button>
      </div>
      <nav className="flex flex-1 flex-col gap-0 overflow-y-auto p-2">
        <div className="space-y-0.5">
          {primaryItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item w-full ${current === item.id ? "active" : ""} ${collapsed ? "justify-center px-2" : ""}`}
              onClick={() => onChange(item.id)}
              title={collapsed ? item.label : undefined}
            >
              <span className="shrink-0">{item.icon}</span>
              {!collapsed && <span>{item.label}</span>}
            </button>
          ))}
        </div>

        <div className="mt-auto space-y-0.5 border-t border-slate-800/40 pt-2">
          {!collapsed && (
            <div className="flex items-center gap-1 px-2 pb-1 pt-1 text-[9px] font-semibold uppercase tracking-widest text-slate-700">
              <MoreHorizontal size={10} />
              <span>더보기</span>
            </div>
          )}
          {visibleMoreItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-item w-full opacity-50 hover:opacity-80 ${current === item.id ? "active opacity-100" : ""} ${collapsed ? "justify-center px-2" : ""}`}
              onClick={() => onChange(item.id)}
              title={collapsed ? item.label : undefined}
            >
              <span className="shrink-0">{item.icon}</span>
              {!collapsed && <span>{item.label}</span>}
            </button>
          ))}
          {!collapsed && (
            userProfile ? (
              /* OAuth 로그인 상태 */
              <div className="flex items-center gap-2 rounded-lg px-3 py-2">
                <UserRound size={14} className="shrink-0 text-amber-400" />
                <span className="min-w-0 flex-1 truncate text-xs text-slate-300">
                  {userProfile.name || userProfile.email || userProfile.provider || "사용자"}
                </span>
                <button type="button" onClick={onUserLogout} title="로그아웃" className="shrink-0 text-slate-500 hover:text-slate-200">
                  <LogOut size={13} />
                </button>
              </div>
            ) : (
              /* 비로그인 / 관리자 상태 */
              <button
                type="button"
                className={`nav-item w-full opacity-70 hover:opacity-100 ${current === "admin" && !isAdmin ? "active opacity-100" : ""}`}
                onClick={isAdmin ? onAdminLogout : onAdminLogin}
              >
                <span className="shrink-0">{isAdmin ? <LogOut size={16} /> : <LogIn size={16} />}</span>
                <span>{isAdmin ? "관리자 로그아웃" : "로그인"}</span>
              </button>
            )
          )}
        </div>
      </nav>
      {!collapsed && (
        <div className="border-t border-slate-800 p-3">
          <div className="font-mono text-[10px] text-slate-600">v10.8 · MONE Stock App</div>
          <div className="mt-0.5 text-[10px] text-slate-600">© 2026 AGNAS</div>
        </div>
      )}
    </div>
  );

  return (
    <aside className={`hidden h-screen shrink-0 border-r border-slate-800 bg-slate-950/95 transition-all duration-300 md:block ${collapsed ? "w-16" : "w-60"}`}>
      <SidebarContent />
    </aside>
  );
}
