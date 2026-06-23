"use client";

import { useEffect, useState, type ReactNode } from "react";
import { mone } from "@/lib/api";
import {
  Brain,
  Calculator,
  ChevronDown,
  ChevronUp,
  Gauge,
  HelpCircle,
  RefreshCw,
  ShieldAlert,
  TrendingDown,
} from "lucide-react";

type Signal = { type: "positive" | "neutral" | "warning"; text: string };
type BiasCheck = { type: string; level: "ok" | "caution" | "warning"; title: string; text: string; action?: string | null };
type Scenario = { label: string; price: number; pct: number };

type ValuationMethod = {
  key: string;
  label: string;
  status: string;
  statusLabel: string;
  fairValue?: number | null;
  upsidePct?: number | null;
  assumptions: string[];
  missingFields: string[];
  note: string;
};

type AltmanRisk = {
  status: string;
  score?: number | null;
  zone: string;
  zoneLabel: string;
  missingFields: string[];
};

type LeverageMetric = {
  key: string;
  label: string;
  value?: number | null;
  status: string;
  note: string;
  missingFields: string[];
};

type DeepDive = {
  status: string;
  scoreBearing: boolean;
  coverage: { availableBlocks: number; totalBlocks: number };
  intrinsicValuation: {
    status: string;
    scoreBearing: boolean;
    currentPrice?: number | null;
    consensusFairValue?: number | null;
    consensusUpsidePct?: number | null;
    methods: ValuationMethod[];
    disclaimer: string;
  };
  bankruptcyRisk: {
    grade: string;
    altman: AltmanRisk;
    proxySignals: Signal[];
    scoreBearing: boolean;
  };
  leverageAnalysis: {
    status: string;
    metrics: LeverageMetric[];
    proxyNote?: string | null;
    scoreBearing: boolean;
  };
  challengeQuestion: {
    severity: "neutral" | "caution" | "warning";
    question: string;
    reason: string;
  };
};

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
  deepDive?: DeepDive;
};

function toneClass(type: Signal["type"]) {
  if (type === "positive") return "text-emerald-300";
  if (type === "warning") return "text-red-300";
  return "text-slate-400";
}

function statusTone(status: string) {
  if (["NORMAL", "SAFE", "LOW"].includes(status)) return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (["PARTIAL", "GRAY", "MEDIUM", "ASSUMPTION_REQUIRED"].includes(status)) {
    return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  }
  if (["DISTRESS", "HIGH"].includes(status)) return "border-red-500/30 bg-red-500/10 text-red-300";
  return "border-slate-600 bg-slate-800/60 text-slate-300";
}

function statusLabel(status: string) {
  return {
    NORMAL: "계산 가능",
    PARTIAL: "부분 계산",
    DATA_PENDING: "데이터 대기",
    ASSUMPTION_REQUIRED: "가정 필요",
    SAFE: "낮음",
    GRAY: "관찰",
    DISTRESS: "높음",
    LOW: "낮음",
    MEDIUM: "보통",
    HIGH: "높음",
    UNKNOWN: "대기",
  }[status] || status;
}

function formatPrice(value?: number | null, market?: string) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  if (market === "us") {
    return `$${value.toLocaleString("en-US", { maximumFractionDigits: value >= 100 ? 0 : 2 })}`;
  }
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

function formatPct(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function SignalRow({ signal }: { signal: Signal }) {
  const dot =
    signal.type === "positive" ? "bg-emerald-400" : signal.type === "warning" ? "bg-red-400" : "bg-slate-500";
  return (
    <div className="flex items-start gap-2 py-1">
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      <span className={`text-xs leading-relaxed ${toneClass(signal.type)}`}>{signal.text}</span>
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

  return (
    <div className={`rounded-lg border px-3 py-2.5 ${levelStyle}`}>
      <div className={`flex items-center gap-1.5 text-xs font-bold ${titleColor}`}>
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
        {check.title}
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{check.text}</p>
      {check.action && <p className={`mt-1.5 text-[11px] font-semibold ${titleColor}`}>{check.action}</p>}
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
  return <span className={`rounded-md border px-2 py-0.5 text-xs font-bold ${cls}`}>{label || grade}</span>;
}

function StatusPill({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold ${statusTone(status)}`}>
      {label || statusLabel(status)}
    </span>
  );
}

function Panel({
  title,
  icon,
  badge,
  badgeLabel,
  children,
  defaultOpen = false,
}: {
  title: string;
  icon: ReactNode;
  badge?: string;
  badgeLabel?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/50">
      <button className="flex w-full items-center justify-between px-4 py-3" onClick={() => setOpen((v) => !v)}>
        <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-slate-200">
          {icon}
          <span className="truncate">{title}</span>
          {badge && <GradeBadge grade={badge} label={badgeLabel} />}
        </div>
        {open ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>
      {open && <div className="border-t border-slate-700/40 px-4 pb-4 pt-3">{children}</div>}
    </div>
  );
}

function ValuationMethodCard({ method, market }: { method: ValuationMethod; market: string }) {
  const upsideTone =
    method.upsidePct === null || method.upsidePct === undefined
      ? "text-slate-500"
      : method.upsidePct >= 10
      ? "text-emerald-300"
      : method.upsidePct < -10
      ? "text-red-300"
      : "text-amber-300";

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-950/30 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-bold text-slate-200">{method.label}</p>
        <StatusPill status={method.status} label={method.statusLabel} />
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">공정가치</p>
          <p className="mt-0.5 font-mono text-sm font-bold text-slate-100">{formatPrice(method.fairValue, market)}</p>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">현재가 대비</p>
          <p className={`mt-0.5 font-mono text-sm font-bold ${upsideTone}`}>{formatPct(method.upsidePct)}</p>
        </div>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{method.note}</p>
      {method.missingFields.length > 0 && (
        <p className="mt-1.5 text-[10px] leading-relaxed text-slate-500">대기 데이터: {method.missingFields.join(", ")}</p>
      )}
    </div>
  );
}

function ChallengeCard({ deepDive }: { deepDive: DeepDive }) {
  const severity = deepDive.challengeQuestion.severity;
  const cls =
    severity === "warning"
      ? "border-red-500/30 bg-red-950/20 text-red-200"
      : severity === "caution"
      ? "border-amber-500/30 bg-amber-950/20 text-amber-100"
      : "border-slate-700/60 bg-slate-950/30 text-slate-200";

  return (
    <div className={`rounded-lg border px-3 py-3 ${cls}`}>
      <div className="flex items-start gap-2">
        <HelpCircle size={15} className="mt-0.5 shrink-0" />
        <div>
          <p className="text-sm font-bold leading-snug">{deepDive.challengeQuestion.question}</p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{deepDive.challengeQuestion.reason}</p>
        </div>
      </div>
    </div>
  );
}

export default function StockResearchPanel({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<AnalysisData | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!symbol) return;
    setLoading(true);
    try {
      const res: AnalysisData = await mone.stockAnalysis({ symbol, market });
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

  const deepDive = data?.deepDive;
  const intrinsic = deepDive?.intrinsicValuation;
  const consensusTone =
    intrinsic?.consensusUpsidePct === undefined || intrinsic?.consensusUpsidePct === null
      ? "text-slate-500"
      : intrinsic.consensusUpsidePct >= 10
      ? "text-emerald-300"
      : intrinsic.consensusUpsidePct < -10
      ? "text-red-300"
      : "text-amber-300";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">리서치 분석</p>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-400 transition hover:bg-slate-800 disabled:opacity-50"
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
          <Panel
            title="재무건전성 / 밸류에이션"
            icon={<ShieldAlert size={14} className="text-sky-400" />}
            badge={data.financialHealth.grade}
            defaultOpen
          >
            <div className="space-y-0.5">
              {data.financialHealth.signals.map((signal, index) => (
                <SignalRow key={index} signal={signal} />
              ))}
              {data.financialHealth.warnings.map((warning, index) => (
                <SignalRow key={`warning-${index}`} signal={warning} />
              ))}
            </div>
            {!data.hasRecommendation && (
              <p className="mt-2 text-[11px] text-amber-400">추천 파일에 없는 종목이라 일부 지표만 표시됩니다.</p>
            )}
          </Panel>

          {deepDive && intrinsic && (
            <Panel
              title="절대가치 점검"
              icon={<Calculator size={14} className="text-emerald-400" />}
              badge={intrinsic.status === "DATA_PENDING" ? "MEDIUM" : "LOW"}
              badgeLabel={statusLabel(intrinsic.status)}
              defaultOpen
            >
              <div className="mb-3 grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-slate-700/60 bg-slate-950/30 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">보조 평균가치</p>
                  <p className="mt-0.5 font-mono text-sm font-bold text-slate-100">
                    {formatPrice(intrinsic.consensusFairValue, market)}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-700/60 bg-slate-950/30 px-3 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">현재가 대비</p>
                  <p className={`mt-0.5 font-mono text-sm font-bold ${consensusTone}`}>
                    {formatPct(intrinsic.consensusUpsidePct)}
                  </p>
                </div>
              </div>
              <div className="grid gap-2 md:grid-cols-3">
                {intrinsic.methods.map((method) => (
                  <ValuationMethodCard key={method.key} method={method} market={market} />
                ))}
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-slate-500">{intrinsic.disclaimer}</p>
            </Panel>
          )}

          {deepDive && (
            <Panel
              title="부도위험 / 레버리지"
              icon={<Gauge size={14} className="text-amber-400" />}
              badge={deepDive.bankruptcyRisk.grade}
              badgeLabel={statusLabel(deepDive.bankruptcyRisk.grade)}
              defaultOpen={!["LOW", "UNKNOWN"].includes(deepDive.bankruptcyRisk.grade)}
            >
              <div className="grid gap-2 md:grid-cols-2">
                <div className="rounded-lg border border-slate-700/60 bg-slate-950/30 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-bold text-slate-200">Altman Z-score</p>
                    <StatusPill
                      status={deepDive.bankruptcyRisk.altman.zone}
                      label={deepDive.bankruptcyRisk.altman.zoneLabel}
                    />
                  </div>
                  <p className="mt-2 font-mono text-lg font-bold text-slate-100">
                    {deepDive.bankruptcyRisk.altman.score ?? "-"}
                  </p>
                  {deepDive.bankruptcyRisk.altman.missingFields.length > 0 && (
                    <p className="mt-1 text-[10px] leading-relaxed text-slate-500">
                      대기 데이터: {deepDive.bankruptcyRisk.altman.missingFields.slice(0, 5).join(", ")}
                    </p>
                  )}
                </div>
                <div className="rounded-lg border border-slate-700/60 bg-slate-950/30 px-3 py-2.5">
                  <p className="text-xs font-bold text-slate-200">레버리지 민감도</p>
                  <div className="mt-2 grid grid-cols-3 gap-1.5">
                    {deepDive.leverageAnalysis.metrics.map((metric) => (
                      <div key={metric.key} className="rounded-md border border-slate-700/60 bg-slate-900/60 px-2 py-1.5">
                        <p className="text-[10px] text-slate-500">{metric.label}</p>
                        <p className="font-mono text-xs font-bold text-slate-100">{metric.value ?? "-"}</p>
                      </div>
                    ))}
                  </div>
                  {deepDive.leverageAnalysis.proxyNote && (
                    <p className="mt-2 text-[10px] leading-relaxed text-slate-500">{deepDive.leverageAnalysis.proxyNote}</p>
                  )}
                </div>
              </div>
              {deepDive.bankruptcyRisk.proxySignals.length > 0 && (
                <div className="mt-3 space-y-0.5">
                  {deepDive.bankruptcyRisk.proxySignals.map((signal, index) => (
                    <SignalRow key={index} signal={signal} />
                  ))}
                </div>
              )}
            </Panel>
          )}

          <Panel
            title="다운사이드 리스크"
            icon={<TrendingDown size={14} className="text-orange-400" />}
            badge={data.downsideRisk.grade}
            badgeLabel={data.downsideRisk.gradeLabel}
            defaultOpen
          >
            <div className="space-y-0.5">
              {data.downsideRisk.signals.map((signal, index) => (
                <SignalRow key={index} signal={signal} />
              ))}
            </div>
            {data.downsideRisk.scenarios.length > 0 && (
              <div className="mt-3">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  스트레스 시나리오
                </p>
                <div className="grid grid-cols-3 gap-1.5">
                  {data.downsideRisk.scenarios.map((scenario, index) => (
                    <div key={index} className="rounded-lg border border-red-500/20 bg-red-950/10 px-2 py-1.5 text-center">
                      <div className="text-[10px] text-slate-500">{scenario.label}</div>
                      <div className="mt-0.5 font-mono text-xs font-bold text-red-300">
                        {formatPrice(scenario.price, market)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Panel>

          <Panel
            title="매매 판단 / 인지 교정"
            icon={<Brain size={14} className="text-violet-400" />}
            badge={data.cognitiveBias.warningCount > 0 ? "HIGH" : data.cognitiveBias.cautionCount > 0 ? "MEDIUM" : "LOW"}
            badgeLabel={
              data.cognitiveBias.warningCount > 0
                ? `경보 ${data.cognitiveBias.warningCount}`
                : data.cognitiveBias.cautionCount > 0
                ? `주의 ${data.cognitiveBias.cautionCount}`
                : "정상"
            }
            defaultOpen={data.cognitiveBias.warningCount > 0 || deepDive?.challengeQuestion.severity !== "neutral"}
          >
            <div className="space-y-2">
              {deepDive && <ChallengeCard deepDive={deepDive} />}
              {data.cognitiveBias.checks.map((check, index) => (
                <BiasCard key={index} check={check} />
              ))}
            </div>
            {!data.inHoldings && !data.inWatchlist && (
              <p className="mt-2 text-[11px] text-slate-500">
                보유 또는 관심 종목에 추가하면 더 정확한 인지 교정 분석이 가능합니다.
              </p>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
