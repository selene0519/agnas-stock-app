"use client";

import { useEffect, useMemo, useState } from "react";
import { BellRing, RefreshCw, ShieldAlert, X } from "lucide-react";
import { mone } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { priceSessionLabel, statusLabel } from "@/lib/utils";
import { displayName, normalizeMarket, normalizeSymbol } from "@/lib/moneDisplay";

type Market = "kr" | "us" | "all";

function labelSession(session?: string, fallback?: string, status?: string) {
  if (!session) {
    if (status === "NETWORK_ERROR") return fallback || "동기화 지연";
    if (status === "ERROR") return fallback || "데이터 없음";
    return fallback || "세션 확인 중";
  }
  return priceSessionLabel(session) || fallback || session;
}

function alertTitle(alert: any) {
  const symbol = normalizeSymbol(alert);
  const market = normalizeMarket(alert.market, symbol);
  return displayName(symbol, market, alert.nameKr || alert.koreanName || alert.name || alert.company);
}

export default function SessionSafetyBanner({
  market = getDefaultMarketBySession(),
  onRefresh,
}: {
  market?: Market;
  onRefresh?: () => void;
}) {
  const [quality, setQuality] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [hidden, setHidden] = useState(false);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const q: any = await mone.dataQuality({ market });
      const payload = market === "all" ? q?.[getDefaultMarketBySession()] || q : q;
      setQuality(payload);

      const alertMarket = market === "all" ? getDefaultMarketBySession() : market;
      const alertResult: any = await mone.nearAlerts({ market: alertMarket, thresholdPct: 1, limit: 5 });
      setAlerts(Array.isArray(alertResult?.items) ? alertResult.items : []);

      window.localStorage.setItem("mone_kill_switch", payload?.killSwitch ? "1" : "0");
      window.dispatchEvent(new CustomEvent("mone-data-quality", { detail: payload }));
      onRefresh?.();
    } catch (error) {
      const payload = {
        status: "NETWORK_ERROR",
        dataStatus: "PARTIAL",
        killSwitch: false,
        networkError: true,
        sessionDescription: "동기화 지연",
        error: error instanceof Error ? error.message : String(error),
      };
      setQuality(payload);
      window.localStorage.setItem("mone_kill_switch", "0");
      window.dispatchEvent(new CustomEvent("mone-data-quality", { detail: payload }));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    const handleFocus = () => refresh();
    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleFocus);
    return () => {
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleFocus);
    };
  }, [market]);

  const tone = useMemo(() => {
    if (quality?.killSwitch) return "border-red-500/40 bg-red-500/10 text-red-100";
    if (quality?.networkError) return "border-amber-500/30 bg-amber-500/10 text-amber-100";
    if (quality?.isHoliday) return "border-blue-500/30 bg-blue-500/10 text-blue-100";
    if (quality?.dataStatus === "PARTIAL") return "border-amber-500/30 bg-amber-500/10 text-amber-100";
    return "border-emerald-500/20 bg-emerald-500/5 text-slate-200";
  }, [quality]);

  if (hidden || !quality) return null;

  return (
    <>
      {quality?.killSwitch && !quality?.isHoliday && (
        <div className="pointer-events-none fixed inset-0 z-[90] bg-red-950/30 backdrop-blur-[1px]">
          <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-2xl border border-red-400/40 bg-red-950/90 px-5 py-3 shadow-2xl">
            <div className="flex items-center gap-2 text-red-100">
              <ShieldAlert size={16} />
              <span className="text-sm font-bold">데이터 안전장치 작동 · 주문 판단 중지</span>
            </div>
            <p className="mt-1 text-xs text-red-200">STALE / NO_DATA / ERROR 상태에서는 추천 카드와 주문 가이드를 사용하지 마세요.</p>
          </div>
        </div>
      )}

      <div className={`rounded-xl border px-3.5 py-2.5 shadow-sm ${tone}`}>
          <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[9px] font-bold uppercase tracking-[0.2em] text-slate-400">
              세션 · 데이터 보호 · {marketLabel(market)}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[13px] font-semibold">
              <span>{labelSession(quality.priceSession, quality.sessionDescription, quality.status || quality.dataStatus)}</span>
              <span className="rounded-md bg-slate-950/50 px-1.5 py-0.5 font-mono text-[11px]">{statusLabel(quality.dataStatus || quality.status)}</span>
              {quality.killSwitch && !quality.isHoliday && <span className="rounded-md bg-red-500/20 px-1.5 py-0.5 text-[11px] text-red-100">킬스위치</span>}
              {quality.isHoliday && <span className="rounded-md bg-blue-500/20 px-1.5 py-0.5 text-[11px] text-blue-100">복기 모드</span>}
            </div>
            {quality.killSwitch && !quality.isHoliday ? (
              <p className="mt-0.5 text-[11px] text-red-200">데이터 상태가 안전하지 않아 신규 진입 판단을 중단해야 합니다.</p>
            ) : quality.isHoliday ? (
              <p className="mt-0.5 text-[11px] text-blue-200">시장 휴장일입니다. 신규 진입보다 지난 운용 리포트와 검증 결과를 확인하세요.</p>
            ) : alerts.length > 0 ? (
              <p className="mt-0.5 text-[11px] text-amber-200">현재 기준가/손절가 1% 이내 근접 알림 {alerts.length}건이 있습니다.</p>
            ) : quality.networkError ? (
              <p className="mt-0.5 text-[11px] text-amber-300">데이터 품질 확인 요청이 지연되었습니다. 기존 화면 데이터는 유지하며, 동기화 버튼으로 다시 확인할 수 있습니다.</p>
            ) : quality.status === "ERROR" || quality.dataStatus === "ERROR" ? (
              <p className="mt-0.5 text-[11px] text-amber-300">수집 결과를 확인하지 못했습니다. GitHub Actions 또는 로컬 수집기 실행 후 동기화하세요.</p>
            ) : (
              <p className="mt-0.5 text-[11px] text-slate-400">화면 복귀 시 세션과 데이터 상태를 자동으로 다시 동기화합니다.</p>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <button onClick={refresh} className="inline-flex min-h-10 items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-[11px] font-bold text-slate-200 transition-[background-color,border-color,transform] hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400 active:scale-[0.96]">
              <RefreshCw aria-hidden="true" size={11} className={loading ? "animate-spin" : ""} />
              <span className="hidden sm:inline">동기화</span>
            </button>
            <button onClick={() => setHidden(true)} className="inline-flex min-h-10 items-center gap-1 rounded-lg border border-slate-800 px-2.5 py-1.5 text-[11px] text-slate-400 transition-[border-color,color,transform] hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-400 active:scale-[0.96]">
              <X aria-hidden="true" size={11} />
              <span className="hidden sm:inline">숨김</span>
            </button>
          </div>
        </div>
        {alerts.length > 0 && !quality.killSwitch && !quality.isHoliday && (
          <div className="mt-2 flex max-w-full gap-1.5 overflow-x-auto pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden" aria-label={`근접 알림 ${alerts.length}건`}>
            {alerts.map((alert, index) => {
              const title = alertTitle(alert);
              const symbol = normalizeSymbol(alert);
              return (
                <button
                  type="button"
                  key={`${symbol}-${alert.type || index}`}
                  title={title}
                  aria-label={`근접 알림: ${title}`}
                  onClick={() => window.dispatchEvent(new CustomEvent("mone-open-near-alert", { detail: alert }))}
                  className="inline-flex min-h-8 min-w-[132px] max-w-[190px] flex-1 items-center gap-1 rounded-lg border border-amber-500/25 bg-amber-500/8 px-2 py-1 text-left text-[10px] text-amber-200 transition-[background-color,border-color,transform] hover:border-amber-400/40 hover:bg-amber-500/14 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-400 active:scale-[0.96]"
                >
                  <BellRing aria-hidden="true" size={10} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{title}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
