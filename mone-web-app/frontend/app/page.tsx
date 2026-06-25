"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Moon, Sun, X } from "lucide-react";
import dynamicImport from "next/dynamic";
import Image from "next/image";
import Sidebar, { type PageId } from "../components/Sidebar";
import BottomNav from "../components/BottomNav";
import TopHoldingTicker from "../components/TopHoldingTicker";
import SessionSafetyBanner from "../components/SessionSafetyBanner";
import AppLaunchLoading, { type AppLaunchLoadingStep } from "../components/AppLaunchLoading";
import HomePage from "../components/pages/HomePage";
import { mone } from "../lib/api";
import { clearAdminToken, getAdminToken, saveAdminToken } from "../lib/adminAuth";
import { clearAuthenticatedUser, getUserId, getUserProfile, getUserToken, type MoneUserProfile } from "../lib/userId";
import { getDefaultMarketBySession } from "../lib/marketSession";
import { getCachedBootPreload, runBootPreload, type BootPreloadState } from "../lib/bootPreload";
import { useFocusTrap } from "../lib/useFocusTrap";

const initialNotifications: { msg: string; time: string; warn: boolean }[] = [];

function PageLoading() {
  return <div className="py-16 text-center text-sm text-slate-500" role="status">화면을 불러오는 중…</div>;
}

const ReportPage = dynamicImport(() => import("../components/pages/ReportPage"), { loading: () => <PageLoading /> });
const StocksPage = dynamicImport(() => import("../components/pages/StocksPage"), { loading: () => <PageLoading /> });
const HoldingsPage = dynamicImport(() => import("../components/pages/HoldingsPage"), { loading: () => <PageLoading /> });
const ChartPage = dynamicImport(() => import("../components/pages/ChartPage"), { loading: () => <PageLoading /> });
const NewsPage = dynamicImport(() => import("../components/pages/NewsPage"), { loading: () => <PageLoading /> });
const PredictionPage = dynamicImport(() => import("../components/pages/PredictionPage"), { loading: () => <PageLoading /> });
const AdvancedPage = dynamicImport(() => import("../components/pages/AdvancedPage"), { loading: () => <PageLoading /> });
const PaperTradingPage = dynamicImport(() => import("../components/pages/PaperTradingPage"), { loading: () => <PageLoading /> });
const VirtualJournalPage = dynamicImport(() => import("../components/pages/VirtualJournalPage"), { loading: () => <PageLoading /> });
const AdminPage = dynamicImport(() => import("../components/pages/AdminPage"), { loading: () => <PageLoading /> });
const AdminLoginPage = dynamicImport(() => import("../components/pages/AdminLoginPage"), { loading: () => <PageLoading /> });
const BrokerPage = dynamicImport(() => import("../components/pages/BrokerPage"), { loading: () => <PageLoading /> });

const pageIds: PageId[] = ["home", "report", "stocks", "holdings", "chart", "news", "prediction", "advanced", "paper", "journal", "broker", "admin"];

function isPageId(value: string | null): value is PageId {
  return Boolean(value && pageIds.includes(value as PageId));
}

export const dynamic = "force-dynamic";

export default function App() {
  const [mounted, setMounted] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [page, setPage] = useState<PageId>("home");
  const [tradeOrder, setTradeOrder] = useState<{ symbol: string; name: string; price: number; market: "kr" | "us"; quantity?: number } | null>(null);
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
  const mainRef = useRef<HTMLElement | null>(null);
  const notificationButtonRef = useRef<HTMLButtonElement | null>(null);
  const notificationPanelRef = useRef<HTMLDivElement | null>(null);

  const navigateTo = useCallback((nextPage: PageId, options?: { replace?: boolean }) => {
    setPage(nextPage);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (nextPage === "home") url.searchParams.delete("page");
    else url.searchParams.set("page", nextPage);
    const method = options?.replace ? "replaceState" : "pushState";
    window.history[method]({ page: nextPage }, "", `${url.pathname}${url.search}${url.hash}`);
  }, []);

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
    const storedTheme = window.localStorage.getItem("mone:theme");
    const initialTheme = storedTheme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = initialTheme;
    setTheme(initialTheme);
    const requestedPage = new URLSearchParams(window.location.search).get("page");
    if (isPageId(requestedPage)) setPage(requestedPage);
    setMounted(true);
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const requestedPage = new URLSearchParams(window.location.search).get("page");
      setPage(isPageId(requestedPage) ? requestedPage : "home");
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    mainRef.current?.focus({ preventScroll: true });
  }, [mounted, page]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      window.localStorage.setItem("mone:theme", next);
      return next;
    });
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
    const handler = () => navigateTo("chart");
    window.addEventListener("mone-open-chart", handler);
    return () => window.removeEventListener("mone-open-chart", handler);
  }, [navigateTo]);

  const closeNotifications = useCallback(() => {
    setNotifOpen(false);
    window.setTimeout(() => notificationButtonRef.current?.focus(), 0);
  }, []);

  useFocusTrap(notifOpen, notificationPanelRef, closeNotifications);

  useEffect(() => {
    if (mounted && page === "admin" && userProfile && !adminToken) {
      navigateTo("home", { replace: true });
    }
  }, [adminToken, mounted, navigateTo, page, userProfile]);

  const handleAdminLogin = useCallback((token: string) => {
    saveAdminToken(token);
    setAdminTokenState(token);
    navigateTo("admin", { replace: true });
  }, [navigateTo]);

  const handleAdminLogout = useCallback(() => {
    clearAdminToken();
    setAdminTokenState("");
    navigateTo("home", { replace: true });
  }, [navigateTo]);

  const handleUserLogout = useCallback(() => {
    clearAuthenticatedUser();
    setUserProfile(null);
    navigateTo("home", { replace: true });
  }, [navigateTo]);

  const openAdminLogin = useCallback(() => {
    navigateTo("admin");
  }, [navigateTo]);

  const openUserLogin = useCallback((provider: "google" | "kakao") => {
    window.location.href = `/mone-api/api/auth/oauth/${provider}/start`;
  }, []);

  const renderPage = () => {
    switch (page) {
      case "home":
        return <HomePage onNavigate={navigateTo} onTradePaper={(order) => { setTradeOrder(order); navigateTo("advanced"); }} bootData={bootState.bootData} bootStatus={bootState.bootStatus} booting={booting} />;
      case "report":
        return <ReportPage />;
      case "stocks":
        return <StocksPage onNavigate={(p) => navigateTo(p as PageId)} bootData={bootState.bootData} />;
      case "holdings":
        return <HoldingsPage userToken={userToken || null} onNavigate={(p) => navigateTo(p as PageId)} bootData={bootState.bootData} />;
      case "chart":
        return <ChartPage />;
      case "news":
        return <NewsPage />;
      case "prediction":
        return <PredictionPage />;
      case "advanced":
        return <AdvancedPage initialOrder={tradeOrder ?? undefined} onOrderConsumed={() => setTradeOrder(null)} />;
      case "paper":
        return <PaperTradingPage />;
      case "journal":
        return <VirtualJournalPage />;
      case "broker":
        return (
          <BrokerPage
            userToken={userToken || null}
            onLogin={() => navigateTo("admin")}
            onNavigate={(p) => navigateTo(p as PageId)}
          />
        );
      case "admin":
        if (adminToken) return <AdminPage authToken={adminToken} onLogout={handleAdminLogout} />;
        if (userProfile) {
          return <HomePage onNavigate={navigateTo} bootData={bootState.bootData} bootStatus={bootState.bootStatus} booting={booting} />;
        }
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
    <div className="mone-app-shell flex h-dvh overflow-hidden" style={{ background: "var(--bg-primary)" }}>
      <a href="#main-content" className="skip-link">본문으로 건너뛰기</a>
      {booting && (
        <AppLaunchLoading
          progress={bootProgress}
          message={bootMessage}
          steps={bootSteps}
          delayed={bootDelayed}
        />
      )}

      {/* 데스크톱 사이드바 */}
      <Sidebar current={page} onChange={navigateTo} isAdmin={Boolean(adminToken)} onAdminLogin={openAdminLogin} onAdminLogout={handleAdminLogout} userProfile={userProfile} onUserLogout={handleUserLogout} />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* 헤더 */}
        <header className="mone-app-header flex h-12 shrink-0 items-center gap-2 border-b border-slate-800 bg-slate-900/60 px-3 backdrop-blur md:px-5">
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

            <button
              type="button"
              onClick={toggleTheme}
              title={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}
              aria-label={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}
              className="mone-header-button relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-full text-slate-400 transition-[background-color,color,transform] hover:bg-slate-800/55 hover:text-white active:scale-[0.96]"
            >
              <Sun
                size={14}
                className={`absolute text-amber-300 transition-[opacity,scale,filter] duration-200 ${theme === "dark" ? "opacity-100 scale-100 blur-0" : "opacity-0 scale-25 blur-[4px]"}`}
              />
              <Moon
                size={14}
                className={`absolute text-blue-500 transition-[opacity,scale,filter] duration-200 ${theme === "light" ? "opacity-100 scale-100 blur-0" : "opacity-0 scale-25 blur-[4px]"}`}
              />
            </button>

            {/* 알림 */}
            <div className="relative">
              <button
                ref={notificationButtonRef}
                type="button"
                className="mone-header-button relative flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition-[background-color,color,transform] hover:bg-slate-800/55 hover:text-white active:scale-[0.96]"
                onClick={() => setNotifOpen(!notifOpen)}
                title="알림"
                aria-label="알림"
                aria-haspopup="dialog"
                aria-expanded={notifOpen}
                aria-controls="notification-panel"
              >
                <Bell size={14} aria-hidden="true" />
                {notifications.length > 0 && (
                  <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-amber-400" />
                )}
              </button>
              {notifOpen && (
                <>
                  <button type="button" className="fixed inset-0 z-30 cursor-default" onClick={closeNotifications} aria-label="알림 닫기" />
                  <div
                    ref={notificationPanelRef}
                    id="notification-panel"
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="notification-title"
                    tabIndex={-1}
                    className="animate-slide-up absolute right-0 top-10 z-40 w-72 rounded-xl border border-slate-700 bg-slate-900 shadow-2xl outline-none"
                  >
                    <div className="flex min-h-11 items-center justify-between border-b border-slate-800 pl-3 text-sm font-medium text-white">
                      <span id="notification-title">알림</span>
                      <button type="button" onClick={closeNotifications} className="flex h-11 w-11 items-center justify-center text-slate-400 hover:text-white" aria-label="알림 닫기"><X size={16} aria-hidden="true" /></button>
                    </div>
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
        <main ref={mainRef} id="main-content" tabIndex={-1} className="flex-1 overflow-y-auto p-3 pb-[calc(56px+env(safe-area-inset-bottom))] outline-none md:p-6 md:pb-6">
          <div className="mx-auto max-w-7xl space-y-4">
            <SessionSafetyBanner market={getDefaultMarketBySession()} />
            {renderPage()}
          </div>
        </main>
      </div>

      {/* 모바일 하단 탭바 */}
      <BottomNav current={page} onChange={navigateTo} isAdmin={Boolean(adminToken)} onAdminLogin={openAdminLogin} userProfile={userProfile} onUserLogout={handleUserLogout} />
    </div>
  );
}
