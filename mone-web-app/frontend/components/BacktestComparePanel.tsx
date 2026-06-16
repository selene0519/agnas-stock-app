"use client";

import { useEffect, useState } from "react";
import { mone, type Market, type Mode, type Horizon } from "@/lib/api";
import { BarChart2, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";

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
      : "bg-slate-700/40 text-slate-500 border-slate-700";
  return (
    <span className={`rounded-md border px-1.5 py-0.5 text-xs font-bold ${cls}`}>
      {rate > 0 ? `${rate}%` : "—"}
    </span>
  );
}

function ReturnLabel({ pct }: { pct: number }) {
  if (!pct) return <span className="text-slate-500 text-xs">—</span>;
  const color = pct > 0 ? "text-emerald-400" : "text-red-400";
  const sign = pct > 0 ? "+" : "";
  return <span className={`font-mono text-xs font-bold ${color}`}>{sign}{pct.toFixed(1)}%</span>;
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
    <div className="space-y-1.5 py-2 px-1">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-500">승률</span>
        <WinRateBadge rate={result.win_rate} />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-500">누적수익</span>
        <ReturnLabel pct={result.total_return_pct} />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-500">손익비</span>
        <span className="font-mono text-[11px] text-slate-300">
          {result.profit_loss_ratio > 0 ? result.profit_loss_ratio.toFixed(1) : "—"}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-500">체결</span>
        <span className="font-mono text-[11px] text-slate-400">
          {result.executed_trades}/{result.total_trades}
        </span>
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
          승률 {best.result.win_rate}% · 누적 {best.result.total_return_pct > 0 ? "+" : ""}{best.result.total_return_pct.toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

export default function BacktestComparePanel() {
  const [market, setMarket] = useState<Market>("kr");
  const [results, setResults] = useState<Record<string, StrategyResult | null>>({});
  const [loading, setLoading] = useState(false);

  async function loadAll() {
    setLoading(true);
    const combos: { mode: Mode; horizon: Horizon }[] = [];
    for (const m of MODES) {
      for (const h of HORIZONS) {
        combos.push({ mode: m.id, horizon: h.id });
      }
    }

    const entries = await Promise.all(
      combos.map(async ({ mode, horizon }) => {
        try {
          const res: any = await mone.backtestSummary({ market, mode, horizon });
          return [`${mode}:${horizon}`, { ...res, mode, horizon }];
        } catch {
          return [`${mode}:${horizon}`, null];
        }
      })
    );

    setResults(Object.fromEntries(entries));
    setLoading(false);
  }

  useEffect(() => {
    loadAll();
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
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart2 size={14} className="text-cyan-400" />
          <span className="text-sm font-bold text-slate-200">6전략 백테스트 비교</span>
          <span className="text-[10px] text-slate-500">(모의 체결 기준)</span>
        </div>
        <div className="flex items-center gap-2">
          {(["kr", "us"] as Market[]).map((mk) => (
            <button
              key={mk}
              onClick={() => setMarket(mk)}
              className={`rounded-lg px-3 py-1 text-xs font-semibold transition-colors ${market === mk ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}
            >
              {mk === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button
            onClick={loadAll}
            disabled={loading}
            className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* 요약 통계 */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: "총 모의 체결", value: totalExecuted > 0 ? `${totalExecuted}건` : "—" },
          { label: "전략 평균 승률", value: avgWinRate > 0 ? `${avgWinRate.toFixed(1)}%` : "—" },
          { label: "활성 전략 수", value: `${validResults.length}/9` },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-slate-700/40 bg-slate-800/30 px-3 py-2 text-center">
            <div className="text-[10px] text-slate-500">{label}</div>
            <div className="mt-0.5 text-sm font-bold text-slate-200">{value}</div>
          </div>
        ))}
      </div>

      {/* 베스트 전략 */}
      <BestStrategyBadge results={results} />

      {/* 비교 그리드 */}
      <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 overflow-hidden">
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
