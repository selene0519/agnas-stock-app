"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";
import Image from "next/image";
import Sidebar, { type PageId } from "../components/Sidebar";
import BottomNav from "../components/BottomNav";
import TopHoldingTicker from "../components/TopHoldingTicker";
import SessionSafetyBanner from "../components/SessionSafetyBanner";
import HomePage from "../components/pages/HomePage";
import ReportPage from "../components/pages/ReportPage";
import StocksPage from "../components/pages/StocksPage";
import HoldingsPage from "../components/pages/HoldingsPage";
import ChartPage from "../components/pages/ChartPage";
import NewsPage from "../components/pages/NewsPage";
import PredictionPage from "../components/pages/PredictionPage";
import AdvancedPage from "../components/pages/AdvancedPage";
import AdminPage from "../components/pages/AdminPage";
import AdminLoginPage from "../components/pages/AdminLoginPage";
import { mone } from "../lib/api";
import { clearAdminToken, getAdminToken, saveAdminToken } from "../lib/adminAuth";
import { clearAuthenticatedUser, getUserId, getUserProfile, type MoneUserProfile } from "../lib/userId";
import { getDefaultMarketBySession } from "../lib/marketSession";

const initialNotifications: { msg: string; time: string; warn: boolean }[] = [];

export const dynamic = "force-dynamic";

export default function App() {
  const [mounted, setMounted] = useState(false);
  const [page, setPage] = useState<PageId>("home");
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifications, setNotifications] = useState(initialNotifications);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [, setDataVersion] = useState(0);
  const [adminToken, setAdminTokenState] = useState("");
  const [userProfile, setUserProfile] = useState<MoneUserProfile | null>(null);

  useEffect(() => {
    setMounted(true);
    setAdminTokenState(getAdminToken());
    setUserProfile(getUserProfile());
    getUserId(); // 최초 방문 시 UUID 생성 및 localStorage 저장
    // Render free-tier cold-start 방지: 앱 로드 즉시 백엔드 warm-up ping (결과 무시)
    fetch("/mone-api/health", { cache: "no-store" }).catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await mone.dataQuality({ market: getDefaultMarketBySession() });
      setDataVersion((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [refresh]);

  // 실적 일정 + 진입 근접 알림 로드
  useEffect(() => {
    async function loadNotifications() {
      const items: { msg: string; time: string; warn: boolean }[] = [];
      try {
        // 실적 발표 일정 (7일 이내)
        const earn = await mone.earningsCalendar({ market: "all", days: 7 });
        const today = new Date();
        for (const e of (earn.items || []).slice(0, 5)) {
          const rd = new Date(e.date);
          const diff = Math.ceil((rd.getTime() - today.getTime()) / 86400000);
          if (diff >= 0 && diff <= 7) {
            const label = e.market === "kr" ? "국장" : "미장";
            items.push({
              msg: `[${label}] ${e.name || e.symbol} 실적발표 D-${diff}${e.estimate ? ` (EPS 예상 ${e.estimate})` : ""}`,
              time: e.date,
              warn: diff <= 2,
            });
          }
        }
        // 진입 근접 알림
        const alerts = await mone.nearAlerts({ thresholdPct: 3, limit: 5 });
        for (const a of (alerts.items || [])) {
          items.push({
            msg: `${a.name || a.symbol} 진입가 근접 (${a.gapPct != null ? `${Number(a.gapPct).toFixed(1)}% 차이` : "확인 필요"})`,
            time: "지금",
            warn: true,
          });
        }
      } catch {}
      if (items.length > 0) setNotifications(items);
    }
    loadNotifications();
  }, []);

  useEffect(() => {
    const handler = () => setPage("chart");
    window.addEventListener("mone-open-chart", handler);
    return () => window.removeEventListener("mone-open-chart", handler);
  }, []);

  const handleAdminLogin = useCallback((token: string) => {
    saveAdminToken(token);
    setAdminTokenState(token);
    setPage("admin");
  }, []);

  const handleAdminLogout = useCallback(() => {
    clearAdminToken();
    setAdminTokenState("");
    setPage("home");
  }, []);

  const handleUserLogout = useCallback(() => {
    clearAuthenticatedUser();
    setUserProfile(null);
    setPage("home");
  }, []);

  const openAdminLogin = useCallback(() => {
    setPage("admin");
  }, []);

  const openUserLogin = useCallback((provider: "google" | "kakao") => {
    window.location.href = `/mone-api/api/auth/oauth/${provider}/start`;
  }, []);

  const renderPage = () => {
    switch (page) {
      case "home":
        return <HomePage onNavigate={setPage} />;
      case "report":
        return <ReportPage />;
      case "stocks":
        return <StocksPage />;
      case "holdings":
        return <HoldingsPage />;
      case "chart":
        return <ChartPage />;
      case "news":
        return <NewsPage />;
      case "prediction":
        return <PredictionPage />;
      case "advanced":
        return <AdvancedPage />;
      case "admin":
        if (adminToken) return <AdminPage authToken={adminToken} onLogout={handleAdminLogout} />;
        if (userProfile) { setTimeout(() => setPage("home"), 0); return <HomePage onNavigate={setPage} />; }
        return <AdminLoginPage onSuccess={handleAdminLogin} onUserLogin={openUserLogin} />;
      default:
        return <HomePage />;
    }
  };

  const headerDate = mounted
    ? new Date().toLocaleDateString("ko-KR", { month: "short", day: "numeric", weekday: "short" })
    : "날짜";

  // SSR / hydration mismatch 방지 — 클라이언트 마운트 전에는 빈 배경만 렌더
  if (!mounted) {
    return <div className="flex h-screen" style={{ background: "var(--bg-primary)" }} />;
  }

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg-primary)" }}>
      {/* 데스크톱 사이드바 */}
      <Sidebar current={page} onChange={setPage} isAdmin={Boolean(adminToken)} onAdminLogin={openAdminLogin} onAdminLogout={handleAdminLogout} userProfile={userProfile} onUserLogout={handleUserLogout} />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* 헤더 */}
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-slate-800 bg-slate-900/60 px-3 backdrop-blur md:px-5">
          {/* 모바일: MONE 로고 */}
          <div className="flex shrink-0 items-center gap-2 md:hidden">
            <Image src="/brand/mone-symbol.png" alt="MONE" width={26} height={26} className="h-6 w-6 object-contain" priority />
            <span className="font-mono text-[13px] font-semibold tracking-widest text-slate-200">MONE</span>
          </div>

          <div className="min-w-0 flex-1">
            <TopHoldingTicker />
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden font-mono text-xs text-slate-500 md:block">{headerDate}</span>
            <span className="hidden text-slate-700 md:block">·</span>
            <span className="hidden text-xs text-slate-500 md:block">{mounted ? "실시간 동기화" : "방금 전"}</span>

            {/* 알림 */}
            <div className="relative">
              <button
                className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 bg-slate-800/50 text-slate-400 transition-colors hover:border-slate-600 hover:text-white"
                onClick={() => setNotifOpen(!notifOpen)}
                title="알림"
              >
                <Bell size={14} />
                {notifications.length > 0 && (
                  <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-amber-400" />
                )}
              </button>
              {notifOpen && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setNotifOpen(false)} />
                  <div className="animate-slide-up absolute right-0 top-10 z-40 w-72 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
                    <div className="border-b border-slate-800 p-3 text-sm font-medium text-white">알림</div>
                    <div className="divide-y divide-slate-800/50">
                      {notifications.length === 0 ? (
                        <div className="px-3 py-6 text-center text-xs text-slate-500">새 알림이 없습니다</div>
                      ) : (
                        notifications.map((item, index) => (
                          <div key={`${item.msg}-${index}`} className={`px-3 py-2.5 text-xs ${item.warn ? "text-amber-300" : "text-slate-300"}`}>
                            <div className="font-medium">{item.msg}</div>
                            <div className="mt-0.5 text-slate-500">{item.time}</div>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="border-t border-slate-800 p-2">
                      <button
                        type="button"
                        onClick={() => setNotifications([])}
                        className="w-full rounded-lg border border-slate-700 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-white"
                      >
                        모두 확인
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        {/* 메인 콘텐츠 — 모바일은 하단 탭바 높이(56px) + safe area 만큼 여백 */}
        <main className="flex-1 overflow-y-auto p-4 pb-[calc(56px+env(safe-area-inset-bottom))] md:p-6 md:pb-6">
          <div className="mx-auto max-w-7xl space-y-4">
            <SessionSafetyBanner market={getDefaultMarketBySession()} />
            {loading && (
              <div className="space-y-3">
                <div className="skeleton h-16 w-full" />
                <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                  <div className="skeleton h-24" />
                  <div className="skeleton h-24" />
                  <div className="skeleton col-span-2 h-24 md:col-span-1" />
                </div>
                <div className="skeleton h-40 w-full" />
              </div>
            )}
            {error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-red-200">데이터 연결 오류: {error}</span>
                  <button
                    onClick={refresh}
                    className="ml-3 shrink-0 rounded-lg border border-red-500/40 px-3 py-1 text-xs text-red-300 hover:bg-red-500/10"
                  >
                    재시도
                  </button>
                </div>
              </div>
            )}
            {renderPage()}
          </div>
        </main>
      </div>

      {/* 모바일 하단 탭바 */}
      <BottomNav current={page} onChange={setPage} isAdmin={Boolean(adminToken)} onAdminLogin={openAdminLogin} userProfile={userProfile} onUserLogout={handleUserLogout} />
    </div>
  );
}
