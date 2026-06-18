"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";
import Image from "next/image";
import Sidebar, { type PageId } from "../components/Sidebar";
import BottomNav from "../components/BottomNav";
import TopHoldingTicker from "../components/TopHoldingTicker";
import SessionSafetyBanner from "../components/SessionSafetyBanner";
import AppLaunchLoading, { type AppLaunchLoadingStep } from "../components/AppLaunchLoading";
import HomePage from "../components/pages/HomePage";
import ReportPage from "../components/pages/ReportPage";
import StocksPage from "../components/pages/StocksPage";
import HoldingsPage from "../components/pages/HoldingsPage";
import ChartPage from "../components/pages/ChartPage";
import NewsPage from "../components/pages/NewsPage";
import PredictionPage from "../components/pages/PredictionPage";
import AdvancedPage from "../components/pages/AdvancedPage";
import PaperTradingPage from "../components/pages/PaperTradingPage";
import VirtualJournalPage from "../components/pages/VirtualJournalPage";
import AdminPage from "../components/pages/AdminPage";
import AdminLoginPage from "../components/pages/AdminLoginPage";
import BrokerPage from "../components/pages/BrokerPage";
import { mone } from "../lib/api";
import { clearAdminToken, getAdminToken, saveAdminToken } from "../lib/adminAuth";
import { clearAuthenticatedUser, getUserId, getUserProfile, getUserToken, type MoneUserProfile } from "../lib/userId";
import { getDefaultMarketBySession } from "../lib/marketSession";
import { getCachedBootPreload, runBootPreload, type BootPreloadState } from "../lib/bootPreload";

const initialNotifications: { msg: string; time: string; warn: boolean }[] = [];

export const dynamic = "force-dynamic";

export default function App() {
  const [mounted, setMounted] = useState(false);
  const [page, setPage] = useState<PageId>("home");
  const [tradeOrder, setTradeOrder] = useState<{ symbol: string; name: string; price: number; market: "kr" | "us" } | null>(null);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifications, setNotifications] = useState(initialNotifications);
  const [adminToken, setAdminTokenState] = useState("");
  const [userProfile, setUserProfile] = useState<MoneUserProfile | null>(null);
  const [userToken, setUserTokenState] = useState("");
  const [booting, setBooting] = useState(true);
  const [bootProgress, setBootProgress] = useState(8);
  const [bootMessage, setBootMessage] = useState("MONE을 여는 중...");
  const [bootDelayed, setBootDelayed] = useState(false);
  const [bootState, setBootState] = useState<BootPreloadState>({
    bootStatus: "idle",
    bootData: {},
    hasBootData: false,
  });
  const [bootSteps, setBootSteps] = useState<AppLaunchLoadingStep[]>([
    { label: "서버 상태 확인", status: "active" },
    { label: "화면 준비", status: "pending" },
  ]);

  useEffect(() => {
    // HTML 인라인 스플래시 제거 (layout.tsx의 #mone-html-splash)
    const htmlSplash = document.getElementById("mone-html-splash");
    if (htmlSplash) htmlSplash.style.display = "none";

    const cachedBoot = getCachedBootPreload();
    if (cachedBoot.hasBootData) {
      setBootState(cachedBoot);
      setBooting(false);
    }
    setAdminTokenState(getAdminToken());
    setUserProfile(getUserProfile());
    setUserTokenState(getUserToken());
    getUserId(); // 최초 방문 시 UUID 생성 및 localStorage 저장
    setMounted(true);
  }, []);


  useEffect(() => {
    if (!mounted) return;

    let cancelled = false;
    const cachedBoot = getCachedBootPreload();
    const showLaunchLoading = !cachedBoot.hasBootData;
    if (!showLaunchLoading) {
      setBootState(cachedBoot);
      setBooting(false);
    } else {
      setBooting(true);
      setBootState({ bootStatus: "loading", bootData: {}, hasBootData: false });
    }

    const delayTimer = window.setTimeout(() => {
      if (!cancelled && showLaunchLoading) setBootDelayed(true);
    }, 5000); // 5초 후 "서버 응답이 늦어지고 있어요" 표시

    // Hard maximum: 10초 후 로딩 화면을 강제로 닫고 앱 진입
    // Render.com 콜드스타트(30s)에서 무한 대기하는 문제를 방지
    const maxBootTimer = window.setTimeout(() => {
      if (!cancelled && showLaunchLoading) setBooting(false);
    }, 10000);

    const updateBoot = (progress: number, message: string, step: "server" | "home" | "stocks" | "done") => {
      if (cancelled) return;
      setBootProgress(progress);
      setBootMessage(message);
      // All requests fire in parallel, so all steps are "active" at once while loading
      setBootSteps([
        { label: "서버 상태 확인", status: step === "done" ? "done" : "active" },
        { label: "화면 준비", status: step === "done" ? "done" : "active" },
      ]);
    };

    async function runBootChecks() {
      try {
        const nextBootState = await runBootPreload((progress) => {
          if (showLaunchLoading) updateBoot(progress.progress, progress.message, progress.step);
        });
        if (cancelled) return;
        setBootState(nextBootState);
        if (showLaunchLoading) {
          window.setTimeout(() => {
            if (!cancelled) setBooting(false);
          }, 450);
        }
      } catch (err) {
        console.warn("MONE launch loading failed:", err);
        if (!cancelled) {
          const fallbackBoot = getCachedBootPreload();
          setBootState(fallbackBoot.hasBootData ? fallbackBoot : {
            bootStatus: "degraded",
            bootData: {},
            hasBootData: false,
            errors: [err instanceof Error ? err.message : String(err)],
          });
          if (showLaunchLoading) {
            updateBoot(100, "서버 확인이 늦어져도 화면을 먼저 열게요", "done");
            window.setTimeout(() => {
              if (!cancelled) setBooting(false);
            }, 700);
          }
        }
      } finally {
        window.clearTimeout(delayTimer);
        window.clearTimeout(maxBootTimer);
      }
    }

    runBootChecks();

    return () => {
      cancelled = true;
      window.clearTimeout(delayTimer);
      window.clearTimeout(maxBootTimer);
    };
  }, [mounted]);

  // 실적 일정 + 진입 근접 알림 로드
  useEffect(() => {
    if (!notifOpen) return;
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
  }, [notifOpen]);

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
    const anonId = encodeURIComponent(getUserId());
    window.location.href = `/mone-api/api/auth/oauth/${provider}/start?anonId=${anonId}`;
  }, []);

  const renderPage = () => {
    switch (page) {
      case "home":
        return <HomePage onNavigate={setPage} onTradePaper={(order) => { setTradeOrder(order); setPage("advanced"); }} bootData={bootState.bootData} bootStatus={bootState.bootStatus} booting={booting} />;
      case "report":
        return <ReportPage />;
      case "stocks":
        return <StocksPage onNavigate={(p) => setPage(p as PageId)} bootData={bootState.bootData} />;
      case "holdings":
        return <HoldingsPage userToken={userToken || null} onNavigate={(p) => setPage(p as PageId)} bootData={bootState.bootData} />;
      case "chart":
        return <ChartPage />;
      case "news":
        return <NewsPage />;
      case "prediction":
        return <PredictionPage />;
      case "advanced":
        return <AdvancedPage initialOrder={tradeOrder ?? undefined} />;
      case "paper":
        return <PaperTradingPage />;
      case "journal":
        return <VirtualJournalPage />;
      case "broker":
        return (
          <BrokerPage
            userToken={userToken || null}
            onLogin={() => setPage("admin")}
            onNavigate={(p) => setPage(p as PageId)}
          />
        );
      case "admin":
        if (adminToken) return <AdminPage authToken={adminToken} onLogout={handleAdminLogout} />;
        if (userProfile) { setTimeout(() => setPage("home"), 0); return <HomePage onNavigate={setPage} bootData={bootState.bootData} bootStatus={bootState.bootStatus} booting={booting} />; }
        return <AdminLoginPage onSuccess={handleAdminLogin} onUserLogin={openUserLogin} />;
      default:
        return <HomePage bootData={bootState.bootData} bootStatus={bootState.bootStatus} booting={booting} />;
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
      {booting && (
        <AppLaunchLoading
          progress={bootProgress}
          message={bootMessage}
          steps={bootSteps}
          delayed={bootDelayed}
        />
      )}

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
        <main className="flex-1 overflow-y-auto p-3 pb-[calc(56px+env(safe-area-inset-bottom))] md:p-6 md:pb-6">
          <div className="mx-auto max-w-7xl space-y-4">
            <SessionSafetyBanner market={getDefaultMarketBySession()} />
            {renderPage()}
          </div>
        </main>
      </div>

      {/* 모바일 하단 탭바 */}
      <BottomNav current={page} onChange={setPage} isAdmin={Boolean(adminToken)} onAdminLogin={openAdminLogin} userProfile={userProfile} onUserLogout={handleUserLogout} />
    </div>
  );
}
