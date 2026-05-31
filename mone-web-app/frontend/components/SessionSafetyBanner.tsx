"use client";

import { useEffect, useMemo, useState } from "react";
import { BellRing, RefreshCw, ShieldAlert, X } from "lucide-react";
import { mone } from "@/lib/api";
import { priceSessionLabel, statusLabel } from "@/lib/utils";
import { displayName, normalizeMarket, normalizeSymbol } from "@/lib/moneDisplay";

type Market = "kr" | "us" | "all";

function labelSession(session?: string, fallback?: string) {
  if (!session) return fallback || "세션 확인 중";
  return priceSessionLabel(session) || fallback || session;
}

function alertTitle(alert: any) {
  const symbol = normalizeSymbol(alert);
  const market = normalizeMarket(alert.market, symbol);
  const name = displayName(symbol, market, alert.name || alert.company);
  const kind = String(alert.message || alert.type || "진입가 임박").replace(symbol, "").trim() || "진입가 임박";
  return `${kind}: ${name}`;
}

export default function SessionSafetyBanner({ market = "kr", onRefresh }: { market?: Market; onRefresh?: () => void }) {
  const [quality, setQuality] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [hidden, setHidden] = useState(false);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const q: any = await mone.dataQuality({ market });
      const payload = market === "all" ? q?.kr || q : q;
      setQuality(payload);

      const alertMarket = market === "all" ? "kr" : market;
      const alertResult: any = await mone.nearAlerts({ market: alertMarket, thresholdPct: 1, limit: 5 });
      setAlerts(Array.isArray(alertResult?.items) ? alertResult.items : []);

      window.localStorage.setItem("mone_kill_switch", payload?.killSwitch ? "1" : "0");
      window.dispatchEvent(new CustomEvent("mone-data-quality", { detail: payload }));
      onRefresh?.();
    } catch (error) {
      const payload = { status: "ERROR", dataStatus: "ERROR", killSwitch: true, error: error instanceof Error ? error.message : String(error) };
      setQuality(payload);
      window.localStorage.setItem("mone_kill_switch", "1");
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
    if (quality?.killSwitch) return "border-red-500/40 bg-red-950/40 text-red-100";
    if (quality?.isHoliday) return "border-blue-500/30 bg-blue-950/20 text-blue-100";
    if (quality?.dataStatus === "PARTIAL") return "border-amber-500/30 bg-amber-950/20 text-amber-100";
    return "border-emerald-500/20 bg-emerald-950/10 text-slate-200";
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

      <div className={`rounded-2xl border px-4 py-3 shadow-sm ${tone}`}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-400">세션 · 데이터 보호</div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm font-semibold">
              <span>{labelSession(quality.priceSession, quality.sessionDescription)}</span>
              <span className="rounded-md bg-slate-950/50 px-2 py-0.5 font-mono text-xs">{statusLabel(quality.dataStatus || quality.status)}</span>
              {quality.killSwitch && !quality.isHoliday && <span className="rounded-md bg-red-500/20 px-2 py-0.5 text-xs text-red-100">킬스위치</span>}
              {quality.isHoliday && <span className="rounded-md bg-blue-500/20 px-2 py-0.5 text-xs text-blue-100">복기 모드</span>}
            </div>
            {quality.killSwitch && !quality.isHoliday ? (
              <p className="mt-1 text-xs text-red-200">데이터 상태가 안전하지 않아 신규 진입 판단을 중단해야 합니다.</p>
            ) : quality.isHoliday ? (
              <p className="mt-1 text-xs text-blue-200">시장 휴장일입니다. 신규 진입보다 지난 운용 리포트와 검증 결과를 확인하세요.</p>
            ) : alerts.length > 0 ? (
              <p className="mt-1 text-xs text-amber-200">현재 진입가/손절가 1% 이내 근접 알림 {alerts.length}건이 있습니다.</p>
            ) : (
              <p className="mt-1 text-xs text-slate-400">화면 복귀 시 세션과 데이터 상태를 자동으로 다시 동기화합니다.</p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {alerts.slice(0, 3).map((alert, index) => (
              <span key={`${normalizeSymbol(alert)}-${alert.type || index}`} className="inline-flex items-center gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs text-amber-200">
                <BellRing size={11} />
                {alertTitle(alert)}
                {normalizeSymbol(alert) && <span className="font-mono text-amber-300/70">{normalizeSymbol(alert)}</span>}
              </span>
            ))}
            <button onClick={refresh} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-bold text-slate-200 hover:bg-slate-800">
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              동기화
            </button>
            <button onClick={() => setHidden(true)} className="inline-flex items-center gap-1 rounded-xl border border-slate-800 px-3 py-2 text-xs text-slate-400 hover:text-slate-200">
              <X size={12} />
              숨김
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
