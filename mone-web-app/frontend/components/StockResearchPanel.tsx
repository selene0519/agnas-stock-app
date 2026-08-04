"use client";

import { useEffect, useMemo, useState } from "react";
import { mone } from "@/lib/api";
import { RefreshCw, ChevronDown, ChevronUp, ShieldAlert, TrendingDown, Brain, Building2 } from "lucide-react";

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
  companyProfile?: {
    businessSummary?: string;
    industryName?: string;
    establishedDate?: string;
    homepage?: string;
  };
  valuation?: {
    per?: number | null;
    pbr?: number | null;
    roe?: number | null;
    dividendYield?: number | null;
    marketCap?: number | null;
    revenue?: number | null;
    operatingProfit?: number | null;
    netIncome?: number | null;
    revenueGrowth?: number | null;
    debtRatio?: number | null;
    sourceYears?: string;
  };
};

/** 억/조 단위로 줄여 쓴다. 원 단위 12자리는 모바일에서 읽을 수 없다. */
function krwShort(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(1)}조`;
  if (abs >= 1e8) return `${Math.round(value / 1e8).toLocaleString("ko-KR")}억`;
  return value.toLocaleString("ko-KR");
}

function metric(value?: number | null, suffix = "", digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  return `${value.toFixed(digits)}${suffix}`;
}

/** 값이 하나도 없으면 카드를 그리지 않는다 — 빈 표를 보여주면 고장으로 보인다. */
function hasAnyValue(obj?: Record<string, unknown>): boolean {
  if (!obj) return false;
  return Object.entries(obj).some(([k, v]) =>
    k !== "sourceYears" && v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v)));
}

function ValueRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="text-[11px] text-slate-400">{label}</span>
      <span className="text-xs font-semibold tabular-nums text-slate-100">{value}</span>
    </div>
  );
}

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

function normalizeRsiSignals(data: AnalysisData | null, rsi14?: number | null): AnalysisData | null {
  if (!data) return data;
  // 손익비·기댓값은 전략(성향×기간)에 따라 달라지는 결정 지표라 추천/계획 카드가 단독으로
  // 소유한다. 리서치 카드는 선택 전략을 받지 않아(심볼 단위 기본전략) 계획 카드와 값이
  // 어긋나 보이므로, 여기서는 이 두 신호를 제거해 화면 간 모순을 없앤다.
  const isStrategyMetric = (s: Signal) => /손익비|기댓값|기대값/.test(s.text || "");
  const hasRsi = rsi14 != null && Number.isFinite(Number(rsi14));
  const nextRsi = hasRsi ? Math.round(Number(rsi14) * 10) / 10 : null;
  const financialHealth = data.financialHealth || { grade: "", signals: [], warnings: [] };
  const rewrite = (signal: Signal): Signal => {
    if (nextRsi == null || !/RSI/i.test(signal.text)) return signal;
    const type = nextRsi >= 80 ? "warning" : nextRsi <= 30 ? "positive" : "neutral";
    const state = nextRsi >= 80 ? "RSI 과열" : nextRsi <= 30 ? "RSI 과매도" : "RSI 정상";
    return { ...signal, type, text: `${state} (${nextRsi.toFixed(1)})` };
  };
  return {
    ...data,
    indicators: nextRsi != null ? { ...data.indicators, rsi14: nextRsi } : data.indicators,
    financialHealth: {
      ...financialHealth,
      signals: (financialHealth.signals || []).filter((s) => !isStrategyMetric(s)).map(rewrite),
      warnings: (financialHealth.warnings || []).filter((s) => !isStrategyMetric(s)).map(rewrite),
    },
  };
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
        {open ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
      </button>
      {open && <div className="border-t border-slate-700/40 px-4 pb-4 pt-3">{children}</div>}
    </div>
  );
}

export default function StockResearchPanel({
  symbol,
  market,
  rsi14,
}: {
  symbol: string;
  market: string;
  rsi14?: number | null;
}) {
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(false);
  const displayData = useMemo(() => normalizeRsiSignals(data, rsi14), [data, rsi14]);

  async function load() {
    if (!symbol) return;
    setLoading(true);
    try {
      const res: any = await mone.stockAnalysis({ symbol, market, rsi14 });
      setData(res);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [symbol, market, rsi14]);

  if (!symbol) return null;

  return (
    <div className="space-y-3">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
          리서치 분석
        </p>
        <button
          onClick={load}
          disabled={loading}
          className="flex min-h-11 items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 disabled:opacity-50"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      {loading && !data && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-6 text-center text-xs text-slate-400">
          분석 중...
        </div>
      )}

      {displayData?.status === "ERROR" && (
        <div className="rounded-xl border border-red-500/20 bg-red-950/10 px-4 py-3 text-xs text-red-300">
          분석 데이터를 불러오지 못했습니다.
        </div>
      )}

      {displayData && displayData.status === "OK" && (
        <>
          {/* #1 기업 정보 — 차트·공시·수급만으로는 "이 회사가 뭘 파는지" 알 수 없다. */}
          {(displayData.companyProfile?.businessSummary
            || displayData.companyProfile?.industryName
            || hasAnyValue(displayData.valuation as Record<string, unknown> | undefined)) && (
            <Panel
              title="기업 정보"
              icon={<Building2 size={14} className="text-teal-400" />}
              badge={displayData.companyProfile?.industryName || undefined}
              defaultOpen
            >
              {displayData.companyProfile?.businessSummary ? (
                <p className="mb-2 text-[11.5px] leading-relaxed text-slate-300">
                  {displayData.companyProfile.businessSummary}
                </p>
              ) : (
                <p className="mb-2 text-[11px] text-slate-400">사업 정보가 아직 수집되지 않았습니다.</p>
              )}

              {hasAnyValue(displayData.valuation as Record<string, unknown> | undefined) ? (
                <div className="grid grid-cols-2 gap-x-4">
                  <ValueRow label="PER" value={metric(displayData.valuation?.per, "배")} />
                  <ValueRow label="PBR" value={metric(displayData.valuation?.pbr, "배")} />
                  <ValueRow label="ROE" value={metric(displayData.valuation?.roe, "%", 1)} />
                  <ValueRow label="배당수익률" value={metric(displayData.valuation?.dividendYield, "%", 2)} />
                  <ValueRow label="시가총액" value={krwShort(displayData.valuation?.marketCap)} />
                  <ValueRow label="부채비율" value={metric(displayData.valuation?.debtRatio, "%", 1)} />
                  <ValueRow label="매출" value={krwShort(displayData.valuation?.revenue)} />
                  <ValueRow label="영업이익" value={krwShort(displayData.valuation?.operatingProfit)} />
                  <ValueRow label="순이익" value={krwShort(displayData.valuation?.netIncome)} />
                  <ValueRow label="매출성장" value={metric(displayData.valuation?.revenueGrowth, "%", 1)} />
                </div>
              ) : (
                <p className="text-[11px] text-slate-400">재무 데이터가 아직 수집되지 않았습니다.</p>
              )}

              {/* 어느 시점 수치인지 밝힌다 — 회계연도와 시장지표 수집 시점이 다르다. */}
              {displayData.valuation?.sourceYears && (
                <p className="mt-2 text-[10px] text-slate-400">
                  재무 기준: {displayData.valuation.sourceYears} 수집분
                </p>
              )}
            </Panel>
          )}

          {/* #2 재무건전성 */}
          <Panel
            title="재무건전성 / 밸류에이션"
            icon={<ShieldAlert size={14} className="text-sky-400" />}
            badge={displayData.financialHealth.grade}
            defaultOpen
          >
            <div className="space-y-0.5">
              {displayData.financialHealth.signals.map((s, i) => <SignalRow key={i} signal={s} />)}
              {displayData.financialHealth.warnings.map((w, i) => <SignalRow key={`w${i}`} signal={w} />)}
            </div>
            {!displayData.hasRecommendation && (
              <p className="mt-2 text-[11px] text-amber-400">추천 파일에 없는 종목 — 일부 지표만 표시됩니다.</p>
            )}
          </Panel>

          {/* #3 다운사이드 리스크 */}
          <Panel
            title="다운사이드 리스크"
            icon={<TrendingDown size={14} className="text-orange-400" />}
            badge={displayData.downsideRisk.grade}
            badgeLabel={displayData.downsideRisk.gradeLabel}
            defaultOpen
          >
            <div className="space-y-0.5">
              {displayData.downsideRisk.signals.map((s, i) => <SignalRow key={i} signal={s} />)}
            </div>
            {displayData.downsideRisk.scenarios.length > 0 && (
              <div className="mt-3">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  스트레스 시나리오
                </p>
                <div className="grid grid-cols-3 gap-1.5">
                  {displayData.downsideRisk.scenarios.map((sc, i) => (
                    <div key={i} className="rounded-lg border border-red-500/20 bg-red-950/10 px-2 py-1.5 text-center">
                      <div className="text-[10px] text-slate-400">{sc.label}</div>
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
              displayData.cognitiveBias.warningCount > 0
                ? "HIGH"
                : displayData.cognitiveBias.cautionCount > 0
                ? "MEDIUM"
                : "LOW"
            }
            badgeLabel={
              displayData.cognitiveBias.warningCount > 0
                ? `경보 ${displayData.cognitiveBias.warningCount}`
                : displayData.cognitiveBias.cautionCount > 0
                ? `주의 ${displayData.cognitiveBias.cautionCount}`
                : "정상"
            }
            defaultOpen={displayData.cognitiveBias.warningCount > 0}
          >
            <div className="space-y-2">
              {displayData.cognitiveBias.checks.map((c, i) => <BiasCard key={i} check={c} />)}
            </div>
            {!displayData.inHoldings && !displayData.inWatchlist && (
              <p className="mt-2 text-[11px] text-slate-400">보유/관심 종목에 추가하면 더 정확한 인지 교정 분석이 가능합니다.</p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
