"use client";

import { useEffect, useState } from "react";
import { mone } from "@/lib/api";
import { RefreshCw, ChevronDown, ChevronUp, ShieldAlert, TrendingDown, Brain } from "lucide-react";

type Signal = { type: "positive" | "neutral" | "warning"; text: string };
type BiasCheck = { type: string; level: "ok" | "caution" | "warning"; title: string; text: string; action?: string | null };
type Scenario = { label: string; price: number; pct: number };

type AnalysisData = {
  status: string;
  symbol: string;
  market: string;
  name: string;
  currentPrice?: number;
  hasRecommendation: boolean;
  inHoldings: boolean;
  holdingPnlPct?: number;
  inWatchlist: boolean;
  indicators: {
    rsi14?: number;
    mdd60?: number;
    atrPct?: number;
    qualityScore?: number;
    riskScore?: number;
    finalScore?: number;
    ev?: number;
    rrActual?: number;
    dataStatus?: string;
  };
  financialHealth: {
    grade: string;
    signals: Signal[];
    warnings: Signal[];
  };
  downsideRisk: {
    grade: string;
    gradeLabel: string;
    signals: Signal[];
    scenarios: Scenario[];
    stopPrice?: number;
    targetPrice?: number;
  };
  cognitiveBias: {
    checks: BiasCheck[];
    warningCount: number;
    cautionCount: number;
  };
};

function SignalRow({ signal }: { signal: Signal }) {
  const cls =
    signal.type === "positive"
      ? "text-emerald-300"
      : signal.type === "warning"
      ? "text-red-300"
      : "text-slate-400";
  const dot =
    signal.type === "positive" ? "bg-emerald-400" : signal.type === "warning" ? "bg-red-400" : "bg-slate-500";
  return (
    <div className="flex items-start gap-2 py-1">
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      <span className={`text-xs leading-relaxed ${cls}`}>{signal.text}</span>
    </div>
  );
}

function BiasCard({ check }: { check: BiasCheck }) {
  const levelStyle =
    check.level === "warning"
      ? "border-red-500/30 bg-red-950/20"
      : check.level === "caution"
      ? "border-amber-500/30 bg-amber-950/20"
      : "border-emerald-500/20 bg-emerald-950/10";
  const titleColor =
    check.level === "warning" ? "text-red-300" : check.level === "caution" ? "text-amber-300" : "text-emerald-300";
  const icon = check.level === "warning" ? "⚠" : check.level === "caution" ? "!" : "✓";

  return (
    <div className={`rounded-xl border px-3 py-2.5 ${levelStyle}`}>
      <div className={`flex items-center gap-1.5 text-xs font-bold ${titleColor}`}>
        <span>{icon}</span>
        {check.title}
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{check.text}</p>
      {check.action && (
        <p className={`mt-1.5 text-[11px] font-semibold ${titleColor}`}>→ {check.action}</p>
      )}
    </div>
  );
}

function GradeBadge({ grade, label }: { grade: string; label?: string }) {
  const cls =
    grade === "A" || grade === "LOW"
      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
      : grade === "B" || grade === "MEDIUM"
      ? "bg-sky-500/20 text-sky-300 border-sky-500/30"
      : grade === "C"
      ? "bg-amber-500/20 text-amber-300 border-amber-500/30"
      : "bg-red-500/20 text-red-300 border-red-500/30";
  return (
    <span className={`rounded-md border px-2 py-0.5 text-xs font-bold ${cls}`}>
      {label || grade}
    </span>
  );
}

function Panel({ title, icon, badge, badgeLabel, children, defaultOpen = false }: {
  title: string;
  icon: React.ReactNode;
  badge?: string;
  badgeLabel?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50">
      <button
        className="flex w-full items-center justify-between px-4 py-3"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          {icon}
          {title}
          {badge && <GradeBadge grade={badge} label={badgeLabel} />}
        </div>
        {open ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>
      {open && <div className="border-t border-slate-700/40 px-4 pb-4 pt-3">{children}</div>}
    </div>
  );
}

export default function StockResearchPanel({
  symbol,
  market,
}: {
  symbol: string;
  market: string;
}) {
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!symbol) return;
    setLoading(true);
    try {
      const res: any = await mone.stockAnalysis({ symbol, market });
      setData(res);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [symbol, market]);

  if (!symbol) return null;

  return (
    <div className="space-y-3">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
          리서치 분석
        </p>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 disabled:opacity-50"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      {loading && !data && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-6 text-center text-xs text-slate-500">
          분석 중...
        </div>
      )}

      {data?.status === "ERROR" && (
        <div className="rounded-xl border border-red-500/20 bg-red-950/10 px-4 py-3 text-xs text-red-300">
          분석 데이터를 불러오지 못했습니다.
        </div>
      )}

      {data && data.status === "OK" && (
        <>
          {/* #2 재무건전성 */}
          <Panel
            title="재무건전성 / 밸류에이션"
            icon={<ShieldAlert size={14} className="text-sky-400" />}
            badge={data.financialHealth.grade}
            defaultOpen
          >
            <div className="space-y-0.5">
              {data.financialHealth.signals.map((s, i) => <SignalRow key={i} signal={s} />)}
              {data.financialHealth.warnings.map((w, i) => <SignalRow key={`w${i}`} signal={w} />)}
            </div>
            {!data.hasRecommendation && (
              <p className="mt-2 text-[11px] text-amber-400">추천 파일에 없는 종목 — 일부 지표만 표시됩니다.</p>
            )}
          </Panel>

          {/* #3 다운사이드 리스크 */}
          <Panel
            title="다운사이드 리스크"
            icon={<TrendingDown size={14} className="text-orange-400" />}
            badge={data.downsideRisk.grade}
            badgeLabel={data.downsideRisk.gradeLabel}
            defaultOpen
          >
            <div className="space-y-0.5">
              {data.downsideRisk.signals.map((s, i) => <SignalRow key={i} signal={s} />)}
            </div>
            {data.downsideRisk.scenarios.length > 0 && (
              <div className="mt-3">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  스트레스 시나리오
                </p>
                <div className="grid grid-cols-3 gap-1.5">
                  {data.downsideRisk.scenarios.map((sc, i) => (
                    <div key={i} className="rounded-lg border border-red-500/20 bg-red-950/10 px-2 py-1.5 text-center">
                      <div className="text-[10px] text-slate-500">{sc.label}</div>
                      <div className="mt-0.5 font-mono text-xs font-bold text-red-300">
                        {sc.price.toLocaleString()}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Panel>

          {/* #5 인지 교정 */}
          <Panel
            title="매매 판단 / 인지 교정"
            icon={<Brain size={14} className="text-violet-400" />}
            badge={
              data.cognitiveBias.warningCount > 0
                ? "HIGH"
                : data.cognitiveBias.cautionCount > 0
                ? "MEDIUM"
                : "LOW"
            }
            badgeLabel={
              data.cognitiveBias.warningCount > 0
                ? `경보 ${data.cognitiveBias.warningCount}`
                : data.cognitiveBias.cautionCount > 0
                ? `주의 ${data.cognitiveBias.cautionCount}`
                : "정상"
            }
            defaultOpen={data.cognitiveBias.warningCount > 0}
          >
            <div className="space-y-2">
              {data.cognitiveBias.checks.map((c, i) => <BiasCard key={i} check={c} />)}
            </div>
            {!data.inHoldings && !data.inWatchlist && (
              <p className="mt-2 text-[11px] text-slate-500">보유/관심 종목에 추가하면 더 정확한 인지 교정 분석이 가능합니다.</p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
