"use client";

import { useEffect, useState } from "react";
import { mone, type Market, type Mode, type Horizon } from "@/lib/api";
import { BarChart2, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";

const BACKTEST_CACHE_KEY = "mone:backtest-compare-cache:v2";
const BACKTEST_CACHE_TTL = 30 * 60 * 1000;
const BACKTEST_LOAD_TIMEOUT_MS = 12_000;

function readBacktestCache(market: Market): Record<string, any> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(BACKTEST_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed.market !== market) return null;
    if (Date.now() - (parsed.ts || 0) > BACKTEST_CACHE_TTL) return null;
    return parsed.results || null;
  } catch {
    return null;
  }
}

function writeBacktestCache(market: Market, results: Record<string, any>) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(BACKTEST_CACHE_KEY, JSON.stringify({ market, results, ts: Date.now() }));
  } catch {}
}

type StrategyResult = {
  mode: Mode;
  horizon: Horizon;
  status: string;
  total_trades: number;
  executed_trades: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  profit_loss_ratio: number;
  total_return_pct: number;
};

const MODES: { id: Mode; label: string; color: string }[] = [
  { id: "conservative", label: "보수", color: "text-sky-300" },
  { id: "balanced", label: "균형", color: "text-emerald-300" },
  { id: "aggressive", label: "공격", color: "text-orange-300" },
];

const HORIZONS: { id: Horizon; label: string }[] = [
  { id: "short", label: "단기" },
  { id: "swing", label: "스윙" },
  { id: "mid", label: "중기" },
];

function WinRateBadge({ rate }: { rate: number }) {
  const cls =
    rate >= 60
      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
      : rate >= 45
      ? "bg-sky-500/20 text-sky-300 border-sky-500/30"
      : rate > 0
      ? "bg-amber-500/20 text-amber-300 border-amber-500/30"
      : "bg-slate-700/40 text-slate-400 border-slate-700";
  return (
    <span className={`rounded-md border px-1.5 py-0.5 text-xs font-bold ${cls}`}>
      {rate > 0 ? `${rate}%` : "—"}
    </span>
  );
}

function ReturnLabel({ pct }: { pct: number }) {
  if (!pct) return <span className="text-slate-400 text-xs">—</span>;
  const color = pct > 0 ? "text-emerald-400" : "text-red-400";
  const sign = pct > 0 ? "+" : "";
  return (
    <span className={`whitespace-nowrap font-mono text-xs font-bold ${color}`} title="평균 수익률">
      <span className="mr-0.5 font-sans text-[10px] font-medium text-slate-500">평균</span>
      {sign}{pct.toFixed(1)}%
    </span>
  );
}

function resultFromJournalPerformance(
  market: Market,
  mode: Mode,
  horizon: Horizon,
  journalRows: any[]
): StrategyResult | null {
  const row = journalRows.find(
    (item) => (item?.market === market || item?.market === "all") && item?.mode === mode && item?.horizon === horizon
  );
  const count = Number(row?.count || 0);
  if (!row || count <= 0) return null;
  const winRateRaw = Number(row.winRate || 0);
  const winRate = winRateRaw <= 1 ? winRateRaw * 100 : winRateRaw;
  return {
    mode,
    horizon,
    status: "OK",
    total_trades: count,
    executed_trades: count,
    win_count: Number(row.wins || 0),
    loss_count: Math.max(0, count - Number(row.wins || 0)),
    win_rate: Number(winRate.toFixed(1)),
    profit_loss_ratio: 0,
    total_return_pct: Number(row.avgPnlPct || 0),
  };
}

function StrategyCell({ result, loading }: { result: StrategyResult | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-[10px] text-slate-600 py-3">
        …
      </div>
    );
  }
  if (!result || result.status !== "OK" || result.total_trades === 0) {
    return (
      <div className="flex h-full items-center justify-center text-[10px] text-slate-600 py-3">
        데이터 없음
      </div>
    );
  }
  return (
    <div className="py-2 px-1 space-y-1">
      <div className="flex items-center justify-between">
        <WinRateBadge rate={result.win_rate} />
        <ReturnLabel pct={result.total_return_pct} />
      </div>
      <div className="flex items-center justify-between gap-1 text-[10px] text-slate-400">
        <span className="font-mono text-slate-400">{result.executed_trades}<span className="text-slate-600">/{result.total_trades}</span></span>
        <span className="font-mono">{result.profit_loss_ratio > 0 ? `RR ${result.profit_loss_ratio.toFixed(1)}` : "—"}</span>
      </div>
    </div>
  );
}

function BestStrategyBadge({ results }: { results: Record<string, StrategyResult | null> }) {
  let best: { key: string; result: StrategyResult } | null = null;
  for (const [key, r] of Object.entries(results)) {
    if (!r || r.status !== "OK" || r.executed_trades < 3) continue;
    if (!best || r.win_rate > best.result.win_rate) {
      best = { key, result: r };
    }
  }
  if (!best) return null;
  const [mode, horizon] = best.key.split(":");
  const modeLabel = MODES.find((m) => m.id === mode)?.label || mode;
  const horizonLabel = HORIZONS.find((h) => h.id === horizon)?.label || horizon;
  return (
    <div className="flex items-center gap-2 rounded-xl border border-emerald-500/20 bg-emerald-950/20 px-3 py-2">
      <TrendingUp size={13} className="text-emerald-400 shrink-0" />
      <div>
        <span className="text-xs text-emerald-300 font-semibold">
          최고 전략: {modeLabel} × {horizonLabel}
        </span>
        <span className="ml-2 text-[11px] text-slate-400">
          승률 {best.result.win_rate}% · 평균 {best.result.total_return_pct > 0 ? "+" : ""}{best.result.total_return_pct.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

export default function BacktestComparePanel() {
  const [market, setMarket] = useState<Market>("kr");
  const [results, setResults] = useState<Record<string, StrategyResult | null>>({});
  const [loading, setLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [notice, setNotice] = useState("");

  async function loadAll(force = false) {
    if (!force) {
      const cached = readBacktestCache(market);
      if (cached) {
        setResults(cached);
        setLoading(false);
        setIsRefreshing(true);
      } else {
        setLoading(true);
      }
    }

    if (force) setIsRefreshing(true);
    setNotice("");

    const combos: { mode: Mode; horizon: Horizon }[] = [];
    for (const m of MODES) {
      for (const h of HORIZONS) {
        combos.push({ mode: m.id, horizon: h.id });
      }
    }

    try {
      const dashboard: any = await Promise.race([
        mone.validationDashboard({ market }),
        new Promise((_, reject) => {
          window.setTimeout(() => reject(new Error("BACKTEST_LOAD_TIMEOUT")), BACKTEST_LOAD_TIMEOUT_MS);
        }),
      ]);
      const stats = dashboard?.stats || {};
      const dashboardCompleted = Number(
        dashboard?.summary?.realizedCompleted ?? dashboard?.summary?.totalCompleted ?? 0
      );
      let journalRows: any[] = [];
      if (dashboardCompleted <= 0) {
        const journalPerf: any = await Promise.race([
          mone.journalPerformance({ market }),
          new Promise((_, reject) => {
            window.setTimeout(() => reject(new Error("BACKTEST_LOAD_TIMEOUT")), BACKTEST_LOAD_TIMEOUT_MS);
          }),
        ]);
        journalRows = Array.isArray(journalPerf?.strategyRows) ? journalPerf.strategyRows : [];
      }
      const entries = combos.map(({ mode, horizon }) => {
        const raw = stats[`${mode}_${horizon}`] || {};
        const completed = Number(raw.realizedCompleted ?? raw.meaningfulCompleted ?? raw.completed ?? 0);
        const pending = Number(raw.pending ?? raw.pendingCount ?? 0);
        const journalResult =
          dashboardCompleted <= 0 ? resultFromJournalPerformance(market, mode, horizon, journalRows) : null;
        if (journalResult) return [`${mode}:${horizon}`, journalResult];
        const winRate = Number(raw.realizedWinRate ?? raw.meaningfulWinRate ?? raw.winRate ?? 0);
        const avgReturn = Number(raw.realizedAvgReturn ?? raw.meaningfulAvgReturn ?? raw.avgReturn ?? 0);
        const wins = Math.round(completed * winRate / 100);
        const result: StrategyResult = {
          mode,
          horizon,
          status: completed + pending > 0 ? "OK" : "NO_DATA",
          total_trades: completed + pending,
          executed_trades: completed,
          win_count: wins,
          loss_count: Math.max(0, completed - wins),
          win_rate: winRate,
          profit_loss_ratio: 0,
          total_return_pct: avgReturn,
        };
        return [`${mode}:${horizon}`, result];
      });
      const newResults = Object.fromEntries(entries);
      setResults(newResults);
      writeBacktestCache(market, newResults);
    } catch {
      setNotice("검증 데이터 응답이 지연되어 빈 상태를 먼저 표시합니다.");
      setResults((current) =>
        Object.keys(current).length > 0
          ? current
          : Object.fromEntries(combos.map(({ mode, horizon }) => [`${mode}:${horizon}`, null]))
      );
    }
    setLoading(false);
    setIsRefreshing(false);
  }

  useEffect(() => {
    loadAll(false);
  }, [market]);

  const totalExecuted = Object.values(results).reduce(
    (sum, r) => sum + (r?.executed_trades || 0),
    0
  );
  const validResults = Object.values(results).filter(
    (r) => r && r.status === "OK" && r.executed_trades > 0
  ) as StrategyResult[];
  const avgWinRate =
    validResults.length > 0
      ? validResults.reduce((s, r) => s + r.win_rate, 0) / validResults.length
      : 0;

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <BarChart2 size={14} className="text-cyan-400" />
          <span className="text-sm font-bold text-slate-200">전략 검증 (9전략)</span>
          <span className="text-[10px] text-slate-400">(실현 손익 기준)</span>
        </div>
        <div className="flex items-center gap-2">
          {(["kr", "us"] as Market[]).map((mk) => (
            <button
              type="button"
              key={mk}
              onClick={() => setMarket(mk)}
              aria-pressed={market === mk}
              className={`min-h-11 rounded-lg px-3 py-1 text-xs font-semibold transition-colors ${market === mk ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}
            >
              {mk === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button
            type="button"
            onClick={() => loadAll(true)}
            disabled={loading || isRefreshing}
            title="전략 검증 새로고침"
            aria-label="전략 검증 데이터 새로고침"
            className="flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            <RefreshCw size={11} aria-hidden="true" className={(loading || isRefreshing) ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* 요약 통계 */}
      {notice && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
          {notice}
        </div>
      )}

      {/* 요약 통계 */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "실현 검증 거래", value: totalExecuted > 0 ? `${totalExecuted}건` : "—" },
          { label: "전략 평균 승률", value: validResults.length > 0 ? `${avgWinRate.toFixed(1)}%` : "—" },
          { label: "활성 전략 수", value: `${validResults.length}/9` },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-slate-700/40 bg-slate-800/30 px-3 py-2 text-center">
            <div className="text-[10px] text-slate-400">{label}</div>
            <div className="mt-0.5 text-sm font-bold text-slate-200">{value}</div>
          </div>
        ))}
      </div>

      {/* 베스트 전략 */}
      <BestStrategyBadge results={results} />

      {/* 비교 카드 (모바일) */}
      <div className="space-y-3 sm:hidden">
        {MODES.map((mode) => (
          <div key={mode.id} className="rounded-2xl border border-slate-700/60 bg-slate-900/50 overflow-hidden">
            <div className="border-b border-slate-700/40 px-3 py-2">
              <span className={`text-xs font-bold ${mode.color}`}>{mode.label}</span>
            </div>
            <div className="divide-y divide-slate-700/40">
              {HORIZONS.map((horizon) => {
                const key = `${mode.id}:${horizon.id}`;
                const result = results[key] || null;
                const cellLoading = loading && !result;
                return (
                  <div key={key} className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <span className="w-10 shrink-0 text-[11px] font-semibold text-slate-400">{horizon.label}</span>
                    {cellLoading ? (
                      <span className="text-[10px] text-slate-600">…</span>
                    ) : !result || result.status !== "OK" || result.total_trades === 0 ? (
                      <span className="text-[10px] text-slate-600">데이터 없음</span>
                    ) : (
                      <div className="flex flex-1 items-center justify-end gap-3">
                        <span className="font-mono text-[10px] text-slate-400">{result.executed_trades}<span className="text-slate-600">/{result.total_trades}</span></span>
                        <ReturnLabel pct={result.total_return_pct} />
                        <WinRateBadge rate={result.win_rate} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 비교 그리드 (데스크톱) */}
      <div className="hidden rounded-2xl border border-slate-700/60 bg-slate-900/50 overflow-hidden sm:block">
        {/* 컬럼 헤더 (horizons) */}
        <div className="grid grid-cols-4 border-b border-slate-700/40">
          <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-600">
            전략
          </div>
          {HORIZONS.map((h) => (
            <div key={h.id} className="border-l border-slate-700/40 px-3 py-2 text-center text-[10px] font-bold uppercase tracking-wider text-slate-400">
              {h.label}
            </div>
          ))}
        </div>

        {/* 행 (modes) */}
        {MODES.map((mode, mi) => (
          <div
            key={mode.id}
            className={`grid grid-cols-4 ${mi < MODES.length - 1 ? "border-b border-slate-700/40" : ""}`}
          >
            <div className="flex items-center px-3 py-2">
              <span className={`text-xs font-bold ${mode.color}`}>{mode.label}</span>
            </div>
            {HORIZONS.map((horizon) => {
              const key = `${mode.id}:${horizon.id}`;
              return (
                <div key={key} className="border-l border-slate-700/40 px-2">
                  <StrategyCell result={results[key] || null} loading={loading && !results[key]} />
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {totalExecuted < 30 && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-950/10 px-3 py-2 text-[11px] text-amber-400">
          <TrendingDown size={12} />
          데이터 누적 중 (총 {totalExecuted}건) — 각 전략당 10건 이상 쌓여야 통계가 의미 있습니다.
        </div>
      )}
    </div>
  );
}
