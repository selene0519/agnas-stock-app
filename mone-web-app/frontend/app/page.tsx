"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";
import Sidebar, { type PageId } from "../components/Sidebar";
import TopHoldingTicker from "../components/TopHoldingTicker";
import SessionSafetyBanner from "../components/SessionSafetyBanner";
import CashInputBar from "../components/CashInputBar";
import HomePage from "../components/pages/HomePage";
import ReportPage from "../components/pages/ReportPage";
import StocksPage from "../components/pages/StocksPage";
import HoldingsPage from "../components/pages/HoldingsPage";
import ChartPage from "../components/pages/ChartPage";
import NewsPage from "../components/pages/NewsPage";
import PredictionPage from "../components/pages/PredictionPage";
import AdvancedPage from "../components/pages/AdvancedPage";
import AdminPage from "../components/pages/AdminPage";
import { mone } from "../lib/api";
import { getDefaultMarketBySession } from "../lib/marketSession";

const initialNotifications = [
  { msg: "데이터 연결 상태를 확인했습니다.", time: "방금 전", warn: false },
  { msg: "진입가는 실제 도달 시에만 체결로 봅니다.", time: "12분 전", warn: false },
  { msg: "오래된 데이터는 정상으로 표시하지 않습니다.", time: "1시간 전", warn: true },
];

export const dynamic = "force-dynamic";

export default function App() {
  const [mounted, setMounted] = useState(false);
  const [page, setPage] = useState<PageId>("home");
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifications, setNotifications] = useState(initialNotifications);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [, setDataVersion] = useState(0);

  useEffect(() => setMounted(true), []);

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
        return <AdminPage />;
      default:
        return <HomePage />;
    }
  };

  const headerDate = mounted
    ? new Date().toLocaleDateString("ko-KR", { month: "short", day: "numeric", weekday: "short" })
    : "날짜";

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: "var(--bg-primary)" }}>
      <Sidebar current={page} onChange={setPage} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-slate-800 bg-slate-900/60 px-4 backdrop-blur md:px-5">
          <TopHoldingTicker />
          <div className="ml-3 flex items-center gap-2">
            <span className="hidden font-mono text-xs text-slate-500 md:block">{headerDate}</span>
            <span className="hidden text-slate-700 md:block">·</span>
            <span className="hidden text-xs text-slate-500 md:block">{mounted ? "실시간 동기화" : "방금 전"}</span>
            <div className="relative">
              <button
                className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 bg-slate-800/50 text-slate-400 transition-colors hover:border-slate-600 hover:text-white"
                onClick={() => setNotifOpen(!notifOpen)}
                title="알림"
              >
                <Bell size={14} />
                {notifications.length > 0 && <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-amber-400" />}
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
        <main className="flex-1 overflow-y-auto p-4 md:p-6">
          <div className="mx-auto max-w-7xl space-y-4">
            <SessionSafetyBanner market={getDefaultMarketBySession()} />
            <CashInputBar />
            {loading && (
              <div className="rounded-xl border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-200">
                데이터를 불러오는 중입니다...
              </div>
            )}
            {error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                데이터 연결 오류: {error}
              </div>
            )}
            {renderPage()}
          </div>
        </main>
      </div>
    </div>
  );
}
