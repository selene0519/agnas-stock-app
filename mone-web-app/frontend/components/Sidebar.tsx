"use client";

import {
  BarChart2,
  Brain,
  Briefcase,
  ChevronRight,
  Cpu,
  FileBarChart2,
  LayoutDashboard,
  Menu,
  Newspaper,
  Search,
  Settings,
  X,
} from "lucide-react";
import Image from "next/image";
import { useState } from "react";

export type PageId =
  | "home"
  | "report"
  | "stocks"
  | "holdings"
  | "chart"
  | "news"
  | "prediction"
  | "advanced"
  | "admin";

const navItems: { id: PageId; label: string; icon: React.ReactNode; desktopOnly?: boolean }[] = [
  { id: "home", label: "시장 홈", icon: <LayoutDashboard size={16} /> },
  { id: "report", label: "운용 리포트", icon: <FileBarChart2 size={16} /> },
  { id: "stocks", label: "종목 탐색", icon: <Search size={16} /> },
  { id: "holdings", label: "보유·리스크", icon: <Briefcase size={16} /> },
  { id: "chart", label: "차트·기술분석", icon: <BarChart2 size={16} /> },
  { id: "news", label: "뉴스·기업분석", icon: <Newspaper size={16} /> },
  { id: "prediction", label: "예측·검증", icon: <Brain size={16} /> },
  { id: "advanced", label: "고급분석", icon: <Cpu size={16} /> },
  { id: "admin", label: "관리자 모드", icon: <Settings size={16} />, desktopOnly: true },
];

interface Props {
  current: PageId;
  onChange: (id: PageId) => void;
  mobileOpen?: boolean;
  onMobileToggle?: () => void;
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

export default function Sidebar({ current, onChange, mobileOpen: mobileOpenProp, onMobileToggle }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpenInternal, setMobileOpenInternal] = useState(false);
  const mobileOpen = mobileOpenProp ?? mobileOpenInternal;
  const setMobileOpen = onMobileToggle ? () => onMobileToggle() : setMobileOpenInternal;

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
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {navItems.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`nav-item w-full ${current === item.id ? "active" : ""} ${collapsed ? "justify-center px-2" : ""} ${item.desktopOnly ? "hidden md:flex" : ""}`}
            onClick={() => {
              onChange(item.id);
              setMobileOpen(false);
            }}
            title={collapsed ? item.label : undefined}
          >
            <span className="shrink-0">{item.icon}</span>
            {!collapsed && <span>{item.label}</span>}
          </button>
        ))}
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
    <>
      <aside className={`hidden h-screen shrink-0 border-r border-slate-800 bg-slate-950/95 transition-all duration-300 md:block ${collapsed ? "w-16" : "w-60"}`}>
        <SidebarContent />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
          <aside className="relative h-full w-64 border-r border-slate-800 bg-slate-950">
            <SidebarContent />
          </aside>
        </div>
      )}
    </>
  );
}
