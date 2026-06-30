"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, BookOpenCheck, CheckCircle2, ClipboardCheck, Play, RefreshCw, ShieldCheck, TimerReset, TrendingUp, XCircle } from "lucide-react";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import { outcomeTone, toneClassName } from "@/lib/tone";
import { displayName } from "@/lib/moneDisplay";
import { SegmentedControl } from "@/components/ui/SegmentedControl";

type ScopeMarket = Extract<Market, "kr" | "us" | "all">;
type ScopeMode = Extract<Mode, "conservative" | "balanced" | "aggressive" | "all">;
type ScopeHorizon = Extract<Horizon, "short" | "swing" | "mid" | "all">;
type ScopeSession = "all" | "PREMARKET_PLAN" | "INTRADAY_CHECK" | "AFTER_CLOSE_TRADE" | "FOLLOWUP_EVALUATION";
type FailureAnalysisBasis = "all" | "evaluated" | "pending" | "dataQuality";

const markets: { id: ScopeMarket; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "kr", label: "KR" },
  { id: "us", label: "US" },
];

const modes: { id: ScopeMode; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "conservative", label: "보수" },
  { id: "balanced", label: "균형" },
  { id: "aggressive", label: "공격" },
];

const horizons: { id: ScopeHorizon; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "short", label: "단기" },
  { id: "swing", label: "스윙" },
  { id: "mid", label: "중기" },
];

const sessions: { id: ScopeSession; label: string }[] = [
  { id: "all", label: "All" },
  { id: "PREMARKET_PLAN", label: "Premarket" },
  { id: "AFTER_CLOSE_TRADE", label: "After close" },
  { id: "FOLLOWUP_EVALUATION", label: "Follow-up" },
];

const failureBasisOptions: { id: FailureAnalysisBasis; label: string }[] = [
  { id: "all", label: "전체 기준" },
  { id: "evaluated", label: "평가 완료" },
  { id: "pending", label: "평가 대기" },
  { id: "dataQuality", label: "데이터 품질" },
];

const SESSION_LABEL: Record<string, string> = {
  PREMARKET_PLAN: "Premarket plan",
  INTRADAY_CHECK: "Intraday check",
  AFTER_CLOSE_TRADE: "After-close paper trade",
  FOLLOWUP_EVALUATION: "Follow-up evaluation",
};

function fmtNum(value: any, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

function toneForOutcome(outcome: string) {
  return toneClassName(outcomeTone(outcome));
}

const OUTCOME_LABEL: Record<string, string> = {
  TARGET_HIT: "목표달성",
  STOP_HIT: "손절",
  TIME_EXIT_NEAR_STOP: "만료(손)",
  TIME_EXIT_PROFIT: "만료(익)",
  TIME_EXIT_LOSS: "만료(손)",
  TIME_EXIT: "기간만료",
  PENDING: "진행중",
  DATA_PENDING: "데이터 대기",
  CANCELLED: "취소",
  EXPIRED: "만료",
  WIN: "수익",
  LOSS: "손실",
};
function outcomeLabel(outcome: string) {
  return OUTCOME_LABEL[outcome] ?? outcome;
}

const MODE_SHORT: Record<string, string> = { conservative: "보수", balanced: "균형", aggressive: "공격" };
const HORIZON_SHORT: Record<string, string> = { short: "단기", swing: "스윙", mid: "중기" };

function metric(label: string, value: any, tone = "text-slate-100") {
  return (
    <div className="rounded-lg bg-slate-950/60 px-3 py-2 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

const MODES_ORDER = ["conservative", "balanced", "aggressive"];
const HORIZONS_ORDER = ["short", "swing", "mid"];
const MODE_KO: Record<string, string> = { conservative: "보수", balanced: "균형", aggressive: "공격" };
const HORIZON_KO: Record<string, string> = { short: "단기", swing: "스윙", mid: "중기" };

const FAILURE_REASON_LABELS: Record<string, string> = {
  UNKNOWN: "원인 미분류",
  DATA_MISSING: "데이터 부족",
  PRICE_INVALID: "가격 오류",
  ENTRY_NOT_TOUCHED: "진입가 미도달",
  TARGET_BEFORE_STOP: "목표가 선도달",
  STOP_BEFORE_TARGET: "손절 선도달",
  TARGET_NOT_REACHED: "목표가 미도달",
  DIRECTION_FAILED: "방향성 실패",
  STOP_TOO_TIGHT: "손절폭 과소",
  OVEREXTENDED_ENTRY: "과열 구간 진입",
  MARKET_GAP: "갭 변동 영향",
  MISSED_PROFIT_CAPTURE: "수익 구간 포착 실패",
  DATA_QUALITY_PROBLEM: "데이터 품질 문제",
  ENTRY_PRICE_TOO_DEEP: "진입가 과도 보수",
  TARGET_TOO_FAR_OR_MOMENTUM_WEAK: "목표가 과대 또는 모멘텀 약함",
  WEAK_CANDIDATE_SIGNAL: "후보 선정 신호 약함",
  HIGH_DRAWDOWN_BEFORE_SUCCESS: "진입 후 역행폭 과대",
  NO_FUTURE_BARS_YET: "평가 대기",
  INSUFFICIENT_HOLDING_PERIOD: "평가 기간 부족",
  ENTRY_TOUCHED_BUT_NO_EXIT: "진입 후 미청산",
  MISSING_ENTRY_PRICE: "진입가 누락",
  MISSING_TARGET_OR_STOP: "목표/손절가 누락",
  INVALID_PRICE_PATH: "가격 경로 오류",
  SYMBOL_OR_DATE_MISMATCH: "종목/날짜 매칭 실패",
  PENDING_EVALUATION: "평가 대기",
  UNCLASSIFIED_PRICE_PATH: "가격 경로 미분류",
};

const PENDING_FAILURE_REASONS = new Set(["NO_FUTURE_BARS_YET", "PENDING_EVALUATION", "INSUFFICIENT_HOLDING_PERIOD"]);
const DATA_QUALITY_FAILURE_REASONS = new Set(["DATA_MISSING", "PRICE_INVALID", "MISSING_ENTRY_PRICE", "MISSING_TARGET_OR_STOP", "INVALID_PRICE_PATH", "SYMBOL_OR_DATE_MISMATCH"]);

function EquityCurveSparkline({ points }: { points: Array<{ date: string; cumPnlPct: number; drawdownPct: number }> }) {
  if (points.length < 2) return null;
  const pnls = points.map((p) => p.cumPnlPct);
  const minY = Math.min(...pnls, 0);
  const maxY = Math.max(...pnls, 0);
  const rangeY = maxY - minY || 1;
  const W = 800;
  const H = 80;
  const pad = 4;
  const toX = (i: number) => pad + (i / (points.length - 1)) * (W - 2 * pad);
  const toY = (v: number) => pad + ((maxY - v) / rangeY) * (H - 2 * pad);
  const zeroY = toY(0);
  const polyline = points.map((p, i) => `${toX(i).toFixed(1)},${toY(p.cumPnlPct).toFixed(1)}`).join(" ");
  const areaPath = `M ${toX(0)},${zeroY} L ${points.map((p, i) => `${toX(i).toFixed(1)},${toY(p.cumPnlPct).toFixed(1)}`).join(" L ")} L ${toX(points.length - 1)},${zeroY} Z`;
  const finalPnl = pnls[pnls.length - 1];
  const lineColor = finalPnl >= 0 ? "#34d399" : "#f87171";
  const fillColor = finalPnl >= 0 ? "rgba(52,211,153,0.12)" : "rgba(248,113,113,0.10)";
  return (
    <div className="w-full overflow-hidden">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-20 w-full">
        {/* zero line */}
        <line x1={pad} y1={zeroY} x2={W - pad} y2={zeroY} stroke="rgba(148,163,184,0.20)" strokeWidth="1" strokeDasharray="4,4" />
        {/* area fill */}
        <path d={areaPath} fill={fillColor} />
        {/* curve */}
        <polyline points={polyline} fill="none" stroke={lineColor} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {/* last point dot */}
        <circle cx={toX(points.length - 1)} cy={toY(finalPnl)} r="3" fill={lineColor} />
      </svg>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-slate-500">
        <span>{points[0]?.date || ""}</span>
        <span className={finalPnl >= 0 ? "text-emerald-300" : "text-red-300"}>{finalPnl >= 0 ? "+" : ""}{finalPnl.toFixed(2)}%</span>
        <span>{points[points.length - 1]?.date || ""}</span>
      </div>
    </div>
  );
}

function StrategyMatrix({ strategyRows }: { strategyRows: any[] }) {
  const lookup = new Map<string, any>();
  // Use market="all" rollup rows so mixed-market data aggregates correctly
  for (const row of strategyRows) {
    if (row.market === "all") lookup.set(`${row.mode}_${row.horizon}`, row);
  }
  const winRateTone = (wr: number | null) => {
    if (wr == null) return "bg-slate-800 text-slate-500";
    if (wr >= 0.6) return "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
    if (wr >= 0.45) return "bg-amber-500/15 text-amber-300 border border-amber-500/25";
    return "bg-red-500/15 text-red-300 border border-red-500/25";
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[400px] text-center text-xs">
        <thead>
          <tr className="text-slate-500">
            <th className="pb-2 pr-3 text-left font-medium">전략</th>
            {HORIZONS_ORDER.map((hz) => (
              <th key={hz} className="pb-2 font-medium">{HORIZON_KO[hz]}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">
          {MODES_ORDER.map((md) => (
            <tr key={md}>
              <td className="py-2 pr-3 text-left font-medium text-slate-400">{MODE_KO[md]}</td>
              {HORIZONS_ORDER.map((hz) => {
                const row = lookup.get(`${md}_${hz}`);
                const wr = row?.winRate ?? null;
                return (
                  <td key={hz} className="py-2">
                    {row && row.count > 0 ? (
                      <div className={`mx-auto inline-flex min-w-[72px] flex-col rounded-lg px-2 py-1.5 ${winRateTone(wr)}`}>
                        <span className="font-mono text-sm font-bold tabular-nums">
                          {wr != null ? `${(wr * 100).toFixed(0)}%` : "-"}
                        </span>
                        <span className="text-[10px] opacity-70">n={row.count}</span>
                        {row.avgPnlPct != null && (
                          <span className={`text-[10px] tabular-nums ${row.avgPnlPct >= 0 ? "text-emerald-400/80" : "text-red-400/80"}`}>
                            {row.avgPnlPct >= 0 ? "+" : ""}{row.avgPnlPct.toFixed(2)}%
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="font-mono text-slate-600">—</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function VirtualJournalPage() {
  const defaultReplayDate = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - 120);
    return d.toISOString().slice(0, 10);
  }, []);
  const [market, setMarket] = useState<ScopeMarket>("all");
  const [mode, setMode] = useState<ScopeMode>("all");
  const [horizon, setHorizon] = useState<ScopeHorizon>("all");
  const [journalSession, setJournalSession] = useState<ScopeSession>("all");
  const [replayDate, setReplayDate] = useState(defaultReplayDate);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [trades, setTrades] = useState<any[]>([]);
  const [patterns, setPatterns] = useState<any[]>([]);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [autoStatus, setAutoStatus] = useState<any>({});
  const [analyticsData, setAnalyticsData] = useState<any>({});
  const [failureAnalytics, setFailureAnalytics] = useState<any>({});
  const [improvementData, setImprovementData] = useState<any>({});
  const [analogData, setAnalogData] = useState<any>({});
  const [perfData, setPerfData] = useState<any>(null);
  const [attrData, setAttrData] = useState<any>(null);
  const [effData, setEffData] = useState<any>(null);
  const [feedbackData, setFeedbackData] = useState<any>(null);
  const [selfLearningData, setSelfLearningData] = useState<any>(null);
  const [opsData, setOpsData] = useState<any>(null);
  const [failureBasis, setFailureBasis] = useState<FailureAnalysisBasis>("all");
  const [stopLossData, setStopLossData] = useState<any>({});
  const [entryTimingData, setEntryTimingData] = useState<any>({});

  const scope = useMemo(() => ({ market, mode, horizon, sourceType: "FORWARD_PAPER_TRADE", journalSession }), [market, mode, horizon, journalSession]);
  const actionSession = journalSession === "all" ? "AFTER_CLOSE_TRADE" : journalSession;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [tradeRes, patternRes, suggestionRes, statusRes, analyticsRes, failureAnalyticsRes, improvementRes, stopLossRes, entryTimingRes, perfRes, attrRes, effRes, feedbackRes, selfLearningRes, opsRes] = await Promise.all([
        mone.virtualTrades({ ...scope, limit: 200 }),
        mone.journalFailurePatterns(scope),
        mone.journalCalibrationSuggestions(scope),
        mone.journalAutoCaptureStatus(),
        mone.journalAnalytics(scope),
        mone.virtualFailureAnalytics(scope),
        mone.virtualImprovementPriorities(scope),
        mone.virtualStopLossDiagnostics(scope),
        mone.virtualEntryTimingDiagnostics(scope),
        mone.journalPerformance({ market: scope.market, mode: scope.mode, horizon: scope.horizon }),
        mone.journalAttribution({ market: scope.market, mode: scope.mode, horizon: scope.horizon }),
        mone.journalEntryEfficiency({ market: scope.market, horizon: scope.horizon }),
        mone.journalAttributionFeedback({ market: scope.market }),
        mone.journalSelfLearningStatus({ market: scope.market }),
        mone.journalOpsDashboard({ market: scope.market }),
      ]);
      if (tradeRes.status === "ERROR") throw new Error(tradeRes.error || "journal load failed");
      setTrades(tradeRes.items || []);
      setPatterns(patternRes.items || []);
      setSuggestions(suggestionRes.items || []);
      setAutoStatus(statusRes || {});
      setAnalyticsData(analyticsRes || {});
      setFailureAnalytics(failureAnalyticsRes || {});
      setImprovementData(improvementRes || {});
      setStopLossData(stopLossRes || {});
      setEntryTimingData(entryTimingRes || {});
      setPerfData(perfRes?.status === "OK" ? perfRes : null);
      setAttrData(attrRes?.status === "OK" ? attrRes : null);
      setEffData(effRes?.status === "OK" ? effRes : null);
      setFeedbackData(feedbackRes?.status === "OK" || feedbackRes?.status === "LOW_SAMPLE" ? feedbackRes : null);
      setSelfLearningData(selfLearningRes?.status === "OK" ? selfLearningRes : null);
      setOpsData(opsRes?.status === "OK" ? opsRes : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  const runAction = async (kind: "capture" | "evaluate" | "auto" | "replay" | "backfill" | "analog" | "self-calibrate") => {
    setBusy(kind);
    setError("");
    try {
      if (kind === "capture") {
        const targetMarket = market === "all" ? "kr" : market;
        const targetMode = mode === "all" ? "balanced" : mode;
        const targetHorizon = horizon === "all" ? "swing" : horizon;
        await mone.virtualTradeCapture({ market: targetMarket, mode: targetMode, horizon: targetHorizon, journalSession: actionSession, limit: 5 });
      } else if (kind === "evaluate") {
        await mone.virtualTradeEvaluate({ ...scope, limit: 500 });
      } else if (kind === "replay") {
        const targetMarket = market === "all" ? "kr" : market;
        const targetMode = mode === "all" ? "balanced" : mode;
        const targetHorizon = horizon === "all" ? "swing" : horizon;
        await mone.journalHistoricalReplay({ market: targetMarket, mode: targetMode, horizon: targetHorizon, asOfDate: replayDate, limit: 5, evaluateAfter: true });
      } else if (kind === "backfill") {
        const targetMarket = market === "all" ? "kr" : market;
        const targetMode = mode === "all" ? "balanced" : mode;
        const targetHorizon = horizon === "all" ? "swing" : horizon;
        await mone.journalHistoricalReplayBackfill({ market: targetMarket, mode: targetMode, horizon: targetHorizon, startDate: replayDate, stepDays: 20, limit: 5, maxRuns: 24, evaluateAfter: true });
      } else if (kind === "analog") {
        const targetMarket = market === "all" ? "kr" : market;
        const targetMode = mode === "all" ? "balanced" : mode;
        const targetHorizon = horizon === "all" ? "swing" : horizon;
        const res = await mone.journalMarketAnalogsRun({ market: targetMarket, mode: targetMode, horizon: targetHorizon, analogLimit: 5, replayLimit: 5, runReplay: true });
        if (res.status === "ERROR") throw new Error(res.error || "market analog replay failed");
        setAnalogData(res);
      } else if (kind === "self-calibrate") {
        await mone.journalSelfLearningAutoCalibrate({ market, appliedBy: "auto_self_learning", apply: true, maxApplications: 4 });
      } else {
        await mone.journalAutoCaptureRun({ market, journalSession: actionSession, limit: 5, evaluateAfter: actionSession === "AFTER_CLOSE_TRADE", force: true });
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const reviewTrade = async (journalId: string) => {
    setBusy(`review:${journalId}`);
    setError("");
    try {
      await mone.journalTradeReview(journalId, { reviewedBy: "local_admin" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const reviewSuggestion = async (item: any, decision: "APPROVED" | "REJECTED") => {
    if (!item?.suggestionId) return;
    setBusy(`${decision}:${item.suggestionId}`);
    setError("");
    try {
      await mone.journalCalibrationApprove(item.suggestionId, { decision, reviewedBy: "local_admin" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const applyApprovedSuggestions = async () => {
    setBusy("apply-approved");
    setError("");
    try {
      await mone.journalCalibrationApplyApproved({ appliedBy: "local_admin" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const rollbackSelfLearning = async () => {
    setBusy("self-rollback");
    setError("");
    try {
      await mone.journalSelfLearningRollback({ requestedBy: "local_admin" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const stats = useMemo(() => {
    const evaluated = trades.filter((item) => ["EVALUATED", "CANCELLED"].includes(String(item.status || "").toUpperCase()));
    const open = trades.filter((item) => !["EVALUATED", "CANCELLED", "DATA_INVALID"].includes(String(item.status || "").toUpperCase()));
    const avg = evaluated
      .map((item) => Number(item.net_pnl_pct))
      .filter((value) => Number.isFinite(value));
    const wins = evaluated.filter((item) => String(item.outcome) === "TARGET_HIT").length;
    return {
      total: trades.length,
      open: open.length,
      evaluated: evaluated.length,
      avgPnl: avg.length ? avg.reduce((a, b) => a + b, 0) / avg.length : null,
      winRate: evaluated.length ? (wins / evaluated.length) * 100 : null,
    };
  }, [trades]);

  const topFailures = useMemo(() => {
    const map = new Map<string, number>();
    patterns.forEach((group) => {
      Object.entries(group.failureCounts || {}).forEach(([key, value]) => {
        if (!key || key === "NONE") return;
        map.set(key, (map.get(key) || 0) + Number(value || 0));
      });
    });
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [patterns]);

  const failureSummary = failureAnalytics?.summary || {};
  const failureAllTop5 = (failureSummary.topFailureReasons || failureAnalytics?.failureReasons || []).slice(0, 5);
  const failureRowsByBasis: Record<FailureAnalysisBasis, any[]> = {
    all: failureAnalytics?.reasonBreakdownAll || failureAnalytics?.failureReasons || failureAllTop5,
    evaluated: failureAnalytics?.reasonBreakdownEvaluatedOnly || [],
    pending: failureAnalytics?.reasonBreakdownPending || [],
    dataQuality: failureAnalytics?.reasonBreakdownDataQuality || [],
  };
  const selectedFailureRows = (failureRowsByBasis[failureBasis] || []).slice(0, 5);
  const selectedFailureTitle = {
    all: "전체 기준 failureReason TOP 5",
    evaluated: "평가 완료 기준 failureReason TOP 5",
    pending: "평가 대기 기준 failureReason TOP 5",
    dataQuality: "데이터 품질 기준 failureReason TOP 5",
  }[failureBasis];
  const selectedFailureNote = {
    all: "전체 거래 기준에는 평가 대기와 데이터 품질 상태가 함께 포함됩니다.",
    evaluated: "평가 대기와 데이터 품질 항목을 제외한, 충분히 판정 가능한 거래 기준입니다.",
    pending: "평가 대기 항목은 실패로 계산하지 않습니다.",
    dataQuality: "데이터 품질 항목은 추천 점수 문제가 아니라 수집/결과 데이터 점검 신호입니다.",
  }[failureBasis];
  const fmtRate = (value: any) => {
    if (value === null || value === undefined || value === "") return "-";
    const n = Number(value);
    return Number.isFinite(n) ? `${(Math.round((n * 100 + 1e-8) * 10) / 10).toFixed(1)}%` : "-";
  };
  const failureLabel = (reason: string) => {
    const normalized = String(reason || "UNKNOWN").trim().toUpperCase() || "UNKNOWN";
    const labels = failureAnalytics?.labels || {};
    return labels[normalized] || FAILURE_REASON_LABELS[normalized] || `미정의 원인 (${normalized})`;
  };
  const topReasonRatio = (reason: string) => {
    const row = failureAllTop5.find((item: any) => String(item.failureReason || item.reason || "").toUpperCase() === reason);
    const ratio = Number(row?.ratio);
    return Number.isFinite(ratio) ? ratio : 0;
  };
  const unknownRatio = topReasonRatio("UNKNOWN");
  const pendingTopRatio = failureAllTop5.reduce((sum: number, item: any) => {
    const reason = String(item.failureReason || item.reason || "").toUpperCase();
    return sum + (PENDING_FAILURE_REASONS.has(reason) ? Number(item.ratio || 0) : 0);
  }, 0);
  const dataIssueTopRatio = failureAllTop5.reduce((sum: number, item: any) => {
    const reason = String(item.failureReason || item.reason || "").toUpperCase();
    return sum + (DATA_QUALITY_FAILURE_REASONS.has(reason) ? Number(item.ratio || 0) : 0);
  }, 0);
  const failureItemRatio = (item: any) => {
    const groupRatio = Number(item?.ratioWithinGroup);
    const allRatio = Number(item?.ratioWithinAll);
    const fallback = Number(item?.ratio);
    if (failureBasis === "all") {
      if (Number.isFinite(allRatio)) return allRatio;
      return Number.isFinite(fallback) ? fallback : null;
    }
    if (Number.isFinite(groupRatio)) return groupRatio;
    return Number.isFinite(fallback) ? fallback : null;
  };
  const overallPriorityRatio = (evidence: any) => {
    const direct = Number(evidence?.overallRatio);
    if (Number.isFinite(direct)) return direct;
    const total = Number(improvementData?.summary?.totalTrades ?? failureSummary.totalTrades);
    const count = Number(evidence?.count);
    return Number.isFinite(total) && total > 0 && Number.isFinite(count) ? count / total : null;
  };

  const priorityItems = (improvementData?.priorities || []).slice(0, 5);
  const severityLabel = (severity: string) => ({ high: "높음", medium: "중간", low: "낮음" }[severity] || "낮음");
  const severityTone = (severity: string) => {
    if (severity === "high") return "bg-red-500/12 text-red-200 shadow-[inset_0_0_0_1px_rgba(248,113,113,0.22)]";
    if (severity === "medium") return "bg-amber-500/12 text-amber-200 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.22)]";
    return "bg-slate-800 text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]";
  };
  const stopLossSummary = stopLossData?.summary || {};
  const stopLossPatch = stopLossData?.patch || {};
  const stopLossCauses = (stopLossData?.causeCandidates || []).slice(0, 3);
  const stopLossCauseLabel = (causeType: string) => ({
    OVEREXTENSION_RISK_HIGH: "과열 진입 연관",
    MARKET_GAP_RISK: "갭 변동 위험",
    MODE_SPECIFIC_STOP_FAILURE: "특정 모드 집중",
    MARKET_SPECIFIC_STOP_FAILURE: "특정 시장 집중",
    ENTRY_TIMING_TOO_EARLY: "진입 타이밍 역행",
    HIGH_DRAWDOWN_BEFORE_SUCCESS: "진입 후 역행폭",
    WEAK_CANDIDATE_QUALITY: "후보 품질 약화",
    STOP_BAND_DESIGN_WEAK: "손절 설계 추가 검증",
  }[causeType] || causeType);
  const entryTimingSummary = entryTimingData?.summary || {};
  const entryTimingReplay = entryTimingData?.beforeAfterReplay || {};
  const entryTimingReasons = (entryTimingData?.riskReasonTop || []).slice(0, 3);
  const entryTimingModeLabel = (modeValue: string) => ({
    diagnostic_only: "진단 전용",
    active_if_validated: "검증 후 활성",
    active: "활성 적용",
  }[modeValue] || "진단 전용");
  const riskReasonLabel = (reason: string) => ({
    OVEREXTENSION_RISK_HIGH: "과열 위험 높음",
    OVEREXTENDED_ENTRY: "과열 구간 진입",
    MARKET_GAP: "갭 변동 영향",
    MAE_DEEPER_THAN_MFE: "역행폭 과대",
    STOP_TOO_TIGHT: "손절폭 과소",
    STOP_BEFORE_TARGET: "손절 선도달",
    LOW_MOMENTUM_WITH_OVEREXTENSION: "과열 대비 모멘텀 약함",
    LOW_SETUP_IN_STOP_FAILURE_GROUP: "setup 진단 약함",
  }[reason] || reason);

  const approvedSuggestions = useMemo(
    () => suggestions.filter((item) => item.approvalStatus === "APPROVED" && item.applicationStatus !== "APPLIED").slice(0, 4),
    [suggestions],
  );

  return (
    <div className="min-w-0 max-w-full space-y-4 overflow-x-hidden">
      <section className="rounded-lg bg-slate-900/60 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <BookOpenCheck size={17} className="text-cyan-300" />
              <span>AI 매매일지</span>
            </div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              추천 시점의 판단을 고정하고, 이후 체결과 결과를 보수적으로 평가합니다. 보정은 제안까지만 만들고 자동 반영하지 않습니다.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-1.5 sm:flex sm:w-auto sm:flex-wrap sm:gap-2">
            <button onClick={load} disabled={loading || !!busy} className="inline-flex min-h-10 items-center justify-center gap-1 whitespace-nowrap rounded-lg bg-slate-800 px-1 text-[11px] font-semibold text-slate-200 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.14)] transition-transform active:scale-[0.96] disabled:opacity-50 sm:gap-1.5 sm:px-3 sm:text-sm">
              <RefreshCw size={13} className="shrink-0" /> 새로고침
            </button>
            <button onClick={() => runAction("evaluate")} disabled={!!busy} className="inline-flex min-h-10 items-center justify-center gap-1 whitespace-nowrap rounded-lg bg-cyan-500/12 px-1 text-[11px] font-semibold text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)] transition-transform active:scale-[0.96] disabled:opacity-50 sm:gap-1.5 sm:px-3 sm:text-sm">
              <Activity size={13} className="shrink-0" /> 평가 실행
            </button>
            <button onClick={() => runAction("auto")} disabled={!!busy} className="inline-flex min-h-10 items-center justify-center gap-1 whitespace-nowrap rounded-lg bg-emerald-500/12 px-1 text-[11px] font-semibold text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.25)] transition-transform active:scale-[0.96] disabled:opacity-50 sm:gap-1.5 sm:px-3 sm:text-sm">
              <Play size={13} className="shrink-0" /> 자동 캡처
            </button>
            <button onClick={() => runAction("analog")} disabled={!!busy} className="inline-flex min-h-10 items-center justify-center gap-1 whitespace-nowrap rounded-lg bg-indigo-500/12 px-1 text-[11px] font-semibold text-indigo-200 shadow-[inset_0_0_0_1px_rgba(129,140,248,0.25)] transition-transform active:scale-[0.96] disabled:opacity-50 sm:gap-1.5 sm:px-3 sm:text-sm">
              <Activity size={13} className="shrink-0" /> 유사 장세
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-5">
          {metric("전체 일지", stats.total)}
          {metric("열린 평가", stats.open, stats.open ? "text-sky-300" : "text-slate-100")}
          {metric("평가 완료", stats.evaluated)}
          {metric("평균 PnL", stats.avgPnl == null ? "-" : `${stats.avgPnl.toFixed(2)}%`, (stats.avgPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300")}
          {metric("목표 도달률", stats.winRate == null ? "-" : `${stats.winRate.toFixed(1)}%`)}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <SegmentedControl<ScopeMarket> options={markets.map((m) => ({ value: m.id, label: m.label }))} value={market} onChange={setMarket} className="w-auto" />
          <SegmentedControl<ScopeMode> options={modes.map((m) => ({ value: m.id, label: m.label }))} value={mode} onChange={setMode} className="w-auto" />
          <SegmentedControl<ScopeHorizon> options={horizons.map((h) => ({ value: h.id, label: h.label }))} value={horizon} onChange={setHorizon} className="w-auto" />
          <SegmentedControl<ScopeSession> options={sessions.map((s) => ({ value: s.id, label: s.label }))} value={journalSession} onChange={setJournalSession} className="w-auto" />
        </div>

        {error && <div className="mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-200 shadow-[inset_0_0_0_1px_rgba(239,68,68,0.22)]">{error}</div>}
      </section>

      <section className="rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Activity size={16} className="text-amber-300" />
              <span>실패 원인 분석</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              실패 원인 분석은 추천 로직 개선을 위한 진단 지표이며, 현재 추천 순위에는 직접 반영되지 않습니다.
            </p>
          </div>
          <span className="font-mono text-[11px] uppercase tracking-wide text-slate-500">
            {String(scope.market).toUpperCase()} / {scope.mode} / {scope.horizon}
          </span>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {metric("전체 일지", failureSummary.totalTrades ?? 0)}
          {metric("평가 완료", failureSummary.evaluatedTrades ?? 0, "text-emerald-300")}
          {metric("평가 대기", failureSummary.pendingTrades ?? 0, "text-sky-300")}
          {metric("데이터 문제", failureSummary.dataIssueTrades ?? 0, "text-cyan-300")}
          {metric("평가 완료율", fmtRate(failureSummary.evaluatedCoverageRate), "text-slate-100")}
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {metric("진입가 터치율", fmtRate(failureSummary.entryTouchedRate))}
          {metric("목표가 선도달률", fmtRate(failureSummary.targetBeforeStopRate), "text-emerald-300")}
          {metric("손절 선도달률", fmtRate(failureSummary.stopBeforeTargetRate), "text-red-300")}
          {metric("진입가 미도달 비율", fmtRate(failureSummary.entryNotTouchedRate), "text-amber-300")}
          {metric("평균 MFE", failureSummary.avgMFE == null ? "-" : `${Number(failureSummary.avgMFE).toFixed(2)}%`, "text-cyan-300")}
          {metric("평균 MAE", failureSummary.avgMAE == null ? "-" : `${Number(failureSummary.avgMAE).toFixed(2)}%`, "text-rose-300")}
        </div>

        {(unknownRatio >= 0.3 || pendingTopRatio > 0 || dataIssueTopRatio > 0) && (
          <div className="mt-4 grid gap-2 lg:grid-cols-2">
            {unknownRatio >= 0.3 && (
              <div className="rounded-lg bg-amber-500/10 px-3 py-2 text-xs leading-5 text-amber-100 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.18)]">
                원인 미분류 비율이 높으면 일부 거래의 터치 순서 또는 결과 데이터가 충분히 분류되지 않았다는 뜻입니다. 추천 로직 변경이 아니라 분류 품질 점검 신호로 해석하세요.
              </div>
            )}
            {pendingTopRatio > 0 && (
              <div className="rounded-lg bg-sky-500/10 px-3 py-2 text-xs leading-5 text-sky-100 shadow-[inset_0_0_0_1px_rgba(56,189,248,0.16)]">
                평가 대기와 평가 기간 부족은 추천 실패가 아니라 미래 봉 또는 보유기간이 아직 충분하지 않은 관찰 상태입니다.
              </div>
            )}
            {dataIssueTopRatio > 0 && (
              <div className="rounded-lg bg-cyan-500/10 px-3 py-2 text-xs leading-5 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.16)]">
                데이터 부족, 가격 경로 오류, 종목/날짜 매칭 실패는 추천 점수 문제가 아니라 가격/결과 데이터 수집 품질 점검이 필요하다는 의미일 수 있습니다.
              </div>
            )}
          </div>
        )}

        <div className="mt-4 grid gap-3 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-3 flex flex-col gap-2">
              <div className="text-xs font-semibold text-slate-400">{selectedFailureTitle}</div>
              <SegmentedControl<FailureAnalysisBasis>
                options={failureBasisOptions.map((item) => ({ value: item.id, label: item.label }))}
                value={failureBasis}
                onChange={setFailureBasis}
                className="w-full"
              />
              <div className="text-[11px] leading-4 text-slate-500">{selectedFailureNote}</div>
            </div>
            <div className="space-y-2">
              {selectedFailureRows.map((item: any) => {
                const reason = String(item.failureReason || item.reason || "UNKNOWN");
                const ratio = failureItemRatio(item);
                return (
                  <div key={reason} className="flex items-center justify-between gap-3 rounded-md bg-slate-900/70 px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-200">{failureLabel(reason)}</div>
                      <div className="font-mono text-[10px] text-slate-500">{reason}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-sm font-semibold tabular-nums text-slate-100">{item.count ?? 0}</div>
                      <div className="font-mono text-[10px] text-slate-500">
                        {failureBasis === "all" ? "전체 대비 " : "그룹 내 "}
                        {fmtRate(ratio)}
                      </div>
                      {failureBasis !== "all" && (
                        <div className="font-mono text-[10px] text-slate-600">전체 대비 {fmtRate(item.ratioWithinAll)}</div>
                      )}
                    </div>
                  </div>
                );
              })}
              {!selectedFailureRows.length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-500">분석 가능한 평가 데이터가 아직 없습니다.</div>
              )}
            </div>
          </div>

          <div className="rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">KR/US · 모드 · 기간별 분해</div>
            <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
              {(failureAnalytics?.groups || []).slice(0, 12).map((row: any, index: number) => (
                <div key={`${row.market}-${row.mode}-${row.horizon}-${row.failureReason}-${index}`} className="rounded-md bg-slate-900/70 px-3 py-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0 text-xs font-semibold text-slate-200">
                      {failureLabel(String(row.failureReason || "UNKNOWN"))}
                    </div>
                    <span className="font-mono text-xs tabular-nums text-slate-300">n={row.count ?? 0}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 font-mono text-[10px] text-slate-500">
                    <span>{String(row.market || "-").toUpperCase()}</span>
                    <span>{row.mode || "-"}</span>
                    <span>{row.horizon || "-"}</span>
                    <span>{row.holdingDaysBucket || "-"}</span>
                    <span>{row.setupBucket || "-"}</span>
                    <span>{row.regime || "-"}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] tabular-nums">
                    <span className="text-slate-400">수익 {row.avgReturn == null ? "-" : `${Number(row.avgReturn).toFixed(2)}%`}</span>
                    <span className="text-emerald-300">MFE {row.avgMFE == null ? "-" : `${Number(row.avgMFE).toFixed(2)}%`}</span>
                    <span className="text-rose-300">MAE {row.avgMAE == null ? "-" : `${Number(row.avgMAE).toFixed(2)}%`}</span>
                    <span className="text-slate-400">진입 {fmtRate(row.entryTouchedRate)}</span>
                  </div>
                </div>
              ))}
              {!(failureAnalytics?.groups || []).length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-500">분해할 데이터가 아직 없습니다.</div>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <TrendingUp size={16} className="text-cyan-300" />
              <span>개선 우선순위</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              현재 추천 로직에는 직접 반영되지 않는 진단 결과입니다. 아래 항목은 바로 로직을 바꾸라는 뜻이 아니라, 먼저 검증해야 할 순서입니다.
            </p>
          </div>
          <span className="font-mono text-[11px] uppercase tracking-wide text-slate-500">
            top {priorityItems.length || 0} / diagnostic only
          </span>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-3">
          {priorityItems.slice(0, 3).map((item: any) => {
            const evidence = item.evidence || {};
            const conditionRate = evidence.conditionRate ?? evidence.ratio;
            return (
              <div key={item.issueType || item.rank} className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-[10px] text-cyan-300">#{item.rank ?? "-"}</div>
                    <div className="mt-1 break-keep text-sm font-semibold leading-5 text-slate-100">{item.title || item.issueType}</div>
                    <div className="mt-1 break-all font-mono text-[10px] leading-4 text-slate-500">{item.issueType || "-"}</div>
                  </div>
                  <span className={`shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold ${severityTone(String(item.severity || "low"))}`}>
                    {severityLabel(String(item.severity || "low"))}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[10px] text-slate-500">근거</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-200">{evidence.count ?? 0}건</div>
                  </div>
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[10px] text-slate-500">전체 대비</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(overallPriorityRatio(evidence))}</div>
                  </div>
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[10px] text-slate-500">조건 충족률</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(conditionRate)}</div>
                  </div>
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[10px] text-slate-500">MAE</div>
                    <div className="font-mono text-xs font-semibold text-rose-300">{evidence.avgMAE == null ? "-" : `${Number(evidence.avgMAE).toFixed(2)}%`}</div>
                  </div>
                </div>
                <div className="mt-3 break-keep text-xs leading-5 text-slate-300">{item.recommendation || "-"}</div>
                <div className="mt-2 break-words rounded-md bg-cyan-500/8 px-2 py-2 text-[11px] leading-5 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.14)] [overflow-wrap:anywhere]">
                  {item.safeNextStep || "표본을 추가로 검증하세요."}
                </div>
              </div>
            );
          })}
          {!priorityItems.length && (
            <div className="rounded-lg bg-slate-950/55 px-3 py-8 text-center text-xs text-slate-500 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)] lg:col-span-3">
              개선 우선순위를 만들 평가 데이터가 아직 없습니다.
            </div>
          )}
        </div>
      </section>

      <section className="rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <ShieldCheck size={16} className="text-rose-300" />
              <span>손절 실패 진단</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              이 분석은 평가 완료 거래만 기준으로 합니다. 손절가 산식을 직접 변경하지 않고, 손절 실패 가능성이 높은 진입 조건을 먼저 점검합니다.
            </p>
          </div>
          <span className={`w-fit rounded-md px-2 py-1 text-[11px] font-semibold ${stopLossPatch.appliedPatch ? "bg-emerald-500/12 text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.22)]" : "bg-slate-800 text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]"}`}>
            {stopLossPatch.appliedPatch ? "패치 적용" : "진단 전용"}
          </span>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          {metric("평가 완료 거래", stopLossSummary.totalEvaluatedTrades ?? 0)}
          {metric("손절 실패 수", stopLossSummary.stopFailureTrades ?? 0, "text-rose-300")}
          {metric("손절 실패율", fmtRate(stopLossSummary.stopFailureRate), "text-rose-300")}
          {metric("손절폭 과소", fmtRate(stopLossSummary.stopTooTightRate), "text-amber-300")}
          {metric("손절 선도달", fmtRate(stopLossSummary.stopBeforeTargetRate), "text-red-300")}
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">연관성 요약</div>
            <div className="grid grid-cols-2 gap-2">
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
                <div className="text-[10px] text-slate-500">과열 진입</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(stopLossSummary.overextensionAssociationRate)}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
                <div className="text-[10px] text-slate-500">갭 변동</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(stopLossSummary.marketGapAssociationRate)}</div>
              </div>
            </div>
            <div className="mt-3 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[11px] leading-5 text-slate-400 [overflow-wrap:anywhere]">
              추천 로직 변경이 적용된 경우, 적용 범위와 검증 결과를 함께 표시합니다. 현재 상태: {stopLossPatch.patchReason || "분석 데이터가 아직 충분하지 않습니다."}
            </div>
          </div>

          <div className="rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">주요 원인 후보 TOP 3</div>
            <div className="space-y-2">
              {stopLossCauses.map((item: any, index: number) => (
                <div key={`${item.causeType || index}`} className="rounded-md bg-slate-900/70 px-3 py-2">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-200">{stopLossCauseLabel(String(item.causeType || ""))}</div>
                      <div className="mt-0.5 break-all font-mono text-[10px] leading-4 text-slate-500">{item.causeType || "-"}</div>
                    </div>
                    <span className="shrink-0 font-mono text-[10px] text-slate-500">#{index + 1}</span>
                  </div>
                  <div className="mt-1 break-keep text-[11px] leading-5 text-slate-400">{item.summary || item.title || "-"}</div>
                </div>
              ))}
              {!stopLossCauses.length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-500">손절 실패 원인 후보를 만들 평가 완료 데이터가 아직 없습니다.</div>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="min-w-0 overflow-hidden rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <TimerReset size={16} className="shrink-0 text-amber-300" />
              <span>진입 타이밍 안전장치</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              이 기능은 손절가를 넓히지 않고, 손절 실패 가능성이 높은 이른 진입을 WAIT_PULLBACK/CAUTION으로 낮추는 안전장치입니다. 검증 기준을 만족하지 않으면 추천 로직에는 반영하지 않습니다.
            </p>
          </div>
          <span className={`w-fit shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold ${entryTimingData?.appliedGuard ? "bg-emerald-500/12 text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.22)]" : "bg-slate-800 text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]"}`}>
            {entryTimingData?.appliedGuard ? "활성 적용" : entryTimingModeLabel(String(entryTimingData?.guardMode || "diagnostic_only"))}
          </span>
        </div>

        <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          {metric("평가 완료 거래", entryTimingSummary.totalEvaluatedTrades ?? 0)}
          {metric("위험 거래", entryTimingSummary.entryTimingRiskTrades ?? 0, "text-amber-300")}
          {metric("HIGH risk 비율", fmtRate(entryTimingSummary.highRiskRate), "text-red-300")}
          {metric("downgrade 후보", entryTimingSummary.actionDowngradeCandidateCount ?? 0, "text-cyan-300")}
          {metric("현재 적용", entryTimingData?.appliedGuard ? "active" : "preview", entryTimingData?.appliedGuard ? "text-emerald-300" : "text-slate-300")}
        </div>

        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">before / after replay</div>
            <div className="grid grid-cols-2 gap-2 text-center">
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[10px] text-slate-500">손절 실패율 전</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-rose-300">{fmtRate(entryTimingReplay.stopFailureRateBefore)}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[10px] text-slate-500">손절 실패율 후</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-rose-300">{fmtRate(entryTimingReplay.stopFailureRateAfter)}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[10px] text-slate-500">평균 수익률 전</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{entryTimingReplay.avgReturnBefore == null ? "-" : `${Number(entryTimingReplay.avgReturnBefore).toFixed(2)}%`}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[10px] text-slate-500">평균 수익률 후</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{entryTimingReplay.avgReturnAfter == null ? "-" : `${Number(entryTimingReplay.avgReturnAfter).toFixed(2)}%`}</div>
              </div>
            </div>
            <div className="mt-3 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[11px] leading-5 text-slate-400 [overflow-wrap:anywhere]">
              현재 결과는 평가 완료 거래 기준입니다. 활성 판단: {entryTimingData?.activationReason || "평가 완료 데이터가 아직 충분하지 않습니다."}
            </div>
          </div>

          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">주요 사유 TOP 3</div>
            <div className="space-y-2">
              {entryTimingReasons.map((item: any, index: number) => (
                <div key={`${item.reason || index}`} className="min-w-0 rounded-md bg-slate-900/70 px-3 py-2">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-200">{riskReasonLabel(String(item.reason || ""))}</div>
                      <div className="mt-0.5 break-all font-mono text-[10px] leading-4 text-slate-500">{item.reason || "-"}</div>
                    </div>
                    <span className="shrink-0 font-mono text-[10px] text-slate-500">#{index + 1}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] tabular-nums text-slate-500">
                    <span>{item.count ?? 0}건</span>
                    <span>{fmtRate(item.ratio)}</span>
                  </div>
                </div>
              ))}
              {!entryTimingReasons.length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-500">진입 타이밍 위험 사유를 만들 평가 완료 데이터가 아직 없습니다.</div>
              )}
            </div>
            <div className="mt-3 break-words rounded-md bg-amber-500/10 px-3 py-2 text-[11px] leading-5 text-amber-100 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.16)] [overflow-wrap:anywhere]">
              다음 조치: {entryTimingData?.recommendedNextStep || "표본을 추가로 쌓은 뒤 HIGH risk 후보를 별도 검증하세요."}
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">최근 일지</h2>
            <span className="font-mono text-xs tabular-nums text-slate-500">{loading ? "loading" : `${trades.length} rows`}</span>
          </div>
          {/* 모바일 카드 뷰 */}
          <div className="space-y-2.5 sm:hidden">
            {trades.slice(0, 80).map((item) => (
              <div key={item.journal_id} className="rounded-xl bg-slate-950/50 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-semibold text-slate-100">{displayName(item) || item.symbol}</div>
                    <div className="font-mono text-[11px] text-slate-500">{item.symbol}</div>
                  </div>
                  <span className={`inline-flex shrink-0 whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-semibold ${toneForOutcome(String(item.outcome || "PENDING"))}`}>
                    {outcomeLabel(String(item.outcome || "PENDING"))}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-500">
                  <span className="font-mono uppercase text-slate-400">
                    {String(item.market || "").toUpperCase()} / {MODE_SHORT[item.mode] ?? item.mode} / {HORIZON_SHORT[item.horizon] ?? item.horizon}
                  </span>
                  <span>{item.as_of_date}</span>
                  <span className="font-mono text-[10px] text-cyan-400">{SESSION_LABEL[String(item.journal_session || item.journalSession)] ?? String(item.journal_session || item.journalSession || "AFTER_CLOSE_TRADE")}</span>
                  <span className={`font-mono text-[10px] ${item.source_type === "MANUAL_REVIEWED" ? "text-emerald-400" : "text-slate-600"}`}>
                    {item.source_type === "MANUAL_REVIEWED" ? "검토완료" : item.source_type === "FORWARD_PAPER_TRADE" ? "자동" : item.source_type}
                  </span>
                </div>
                <div className="mt-2.5 grid grid-cols-3 gap-2 text-center">
                  <div className="rounded-lg bg-slate-900/60 px-2 py-1.5">
                    <div className="text-[10px] text-slate-500">PnL</div>
                    <div className={`font-mono text-xs font-semibold tabular-nums ${Number(item.net_pnl_pct) >= 0 ? "text-emerald-300" : "text-red-300"}`}>{fmtNum(item.net_pnl_pct, "%")}</div>
                  </div>
                  <div className="rounded-lg bg-slate-900/60 px-2 py-1.5">
                    <div className="text-[10px] text-slate-500">MFE</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-300">{fmtNum(item.mfe_pct, "%")}</div>
                  </div>
                  <div className="rounded-lg bg-slate-900/60 px-2 py-1.5">
                    <div className="text-[10px] text-slate-500">MAE</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-300">{fmtNum(item.mae_pct, "%")}</div>
                  </div>
                </div>
                {item.failure_reason && (
                  <div className="mt-2 font-mono text-[11px] text-amber-300">
                    {item.failure_reason}
                    {item.secondary_tags && <span className="ml-1 text-slate-500">{item.secondary_tags}</span>}
                  </div>
                )}
                {item.review_text && (
                  <div className="mt-2 text-[12px] leading-5 text-slate-400">{item.review_text}</div>
                )}
                {!item.review_text && item.session_note && (
                  <div className="mt-2 text-[12px] leading-5 text-slate-400">{item.session_note}</div>
                )}
                {String(item.source_type) === "FORWARD_PAPER_TRADE" && String(item.status) === "EVALUATED" && (
                  <button
                    onClick={() => reviewTrade(item.journal_id)}
                    disabled={busy === `review:${item.journal_id}`}
                    title="검토 완료로 표시 (MANUAL_REVIEWED 승격, 보정 가중치 1.2 적용)"
                    className="mt-2.5 inline-flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-1 text-[11px] font-semibold text-emerald-300 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.20)] transition-transform active:scale-[0.95] disabled:opacity-40"
                  >
                    <ClipboardCheck size={11} /> 검토
                  </button>
                )}
              </div>
            ))}
            {!trades.length && (
              <div className="py-10 text-center text-sm text-slate-500">아직 가상 매매일지가 없습니다.</div>
            )}
          </div>

          {/* 데스크톱 테이블 뷰 */}
          <div className="hidden overflow-x-auto sm:block">
            <table className="w-full min-w-[900px] text-left text-xs">
              <thead className="text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="py-2 pr-3">종목</th>
                  <th className="py-2 pr-3">범위</th>
                  <th className="py-2 pr-3">결과</th>
                  <th className="py-2 pr-3 text-right">PnL</th>
                  <th className="py-2 pr-3 text-right">MFE</th>
                  <th className="py-2 pr-3 text-right">MAE</th>
                  <th className="py-2 pr-3">실패 태그</th>
                  <th className="py-2 pr-3">복기</th>
                  <th className="py-2">검토</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/70">
                {trades.slice(0, 80).map((item) => (
                  <tr key={item.journal_id} className="align-top text-slate-300">
                    <td className="py-3 pr-3">
                      <div className="font-semibold text-slate-100">{displayName(item) || item.symbol}</div>
                      <div className="font-mono text-[11px] text-slate-500">{item.symbol}</div>
                    </td>
                    <td className="py-3 pr-3">
                      <div className="font-mono text-[11px] uppercase text-slate-400">
                        {String(item.market || "").toUpperCase()} / {MODE_SHORT[item.mode] ?? item.mode} / {HORIZON_SHORT[item.horizon] ?? item.horizon}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">{item.as_of_date}</div>
                      <div className="mt-1 font-mono text-[10px] text-cyan-400">{SESSION_LABEL[String(item.journal_session || item.journalSession)] ?? String(item.journal_session || item.journalSession || "AFTER_CLOSE_TRADE")}</div>
                      <div className={`mt-1 font-mono text-[10px] ${item.source_type === "MANUAL_REVIEWED" ? "text-emerald-400" : "text-slate-600"}`}>
                        {item.source_type === "MANUAL_REVIEWED" ? "검토완료" : item.source_type === "FORWARD_PAPER_TRADE" ? "자동" : item.source_type}
                      </div>
                    </td>
                    <td className="py-3 pr-3">
                      <span className={`inline-flex whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-semibold ${toneForOutcome(String(item.outcome || "PENDING"))}`}>
                        {outcomeLabel(String(item.outcome || "PENDING"))}
                      </span>
                    </td>
                    <td className={`py-3 pr-3 text-right font-mono tabular-nums ${Number(item.net_pnl_pct) >= 0 ? "text-emerald-300" : "text-red-300"}`}>{fmtNum(item.net_pnl_pct, "%")}</td>
                    <td className="py-3 pr-3 text-right font-mono tabular-nums text-slate-300">{fmtNum(item.mfe_pct, "%")}</td>
                    <td className="py-3 pr-3 text-right font-mono tabular-nums text-slate-300">{fmtNum(item.mae_pct, "%")}</td>
                    <td className="py-3 pr-3 font-mono text-[11px] text-amber-300">
                      <div>{item.failure_reason || "-"}</div>
                      {item.secondary_tags && <div className="mt-0.5 text-slate-500">{item.secondary_tags}</div>}
                    </td>
                    <td className="max-w-sm py-3 pr-3 text-[12px] leading-5 text-slate-400">{item.review_text || item.session_note || "-"}</td>
                    <td className="py-3">
                      {String(item.source_type) === "FORWARD_PAPER_TRADE" && String(item.status) === "EVALUATED" && (
                        <button
                          onClick={() => reviewTrade(item.journal_id)}
                          disabled={busy === `review:${item.journal_id}`}
                          title="검토 완료로 표시 (MANUAL_REVIEWED 승격, 보정 가중치 1.2 적용)"
                          className="inline-flex items-center gap-1 rounded-md bg-emerald-500/10 px-2 py-1 text-[11px] font-semibold text-emerald-300 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.20)] transition-transform active:scale-[0.95] disabled:opacity-40"
                        >
                          <ClipboardCheck size={11} /> 검토
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {!trades.length && (
                  <tr>
                    <td colSpan={9} className="py-10 text-center text-sm text-slate-500">아직 가상 매매일지가 없습니다.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
              <ShieldCheck size={16} className="text-emerald-300" />
              <span>자동 캡처</span>
            </div>
            <div className="space-y-2 text-xs text-slate-400">
              <div className="flex justify-between gap-3"><span>상태</span><span className="font-mono text-slate-200">{autoStatus.status || "-"}</span></div>
              <div className="flex justify-between gap-3"><span>마지막 실행</span><span className="font-mono text-slate-200">{autoStatus.lastRunAt || "-"}</span></div>
              <div className="flex justify-between gap-3"><span>중복 방지 키</span><span className="font-mono text-slate-200">{(autoStatus.completedKeys || []).length}</span></div>
            </div>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h2 className="mb-3 text-sm font-semibold text-slate-200">히스토리컬 리플레이</h2>
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                type="date"
                value={replayDate}
                onChange={(event) => setReplayDate(event.target.value)}
                className="min-h-10 rounded-lg border border-slate-800 bg-slate-950 px-3 font-mono text-sm text-slate-200 outline-none focus:border-cyan-500"
              />
              <button
                onClick={() => runAction("replay")}
                disabled={!!busy || !replayDate}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-indigo-500/12 px-3 text-sm font-semibold text-indigo-200 shadow-[inset_0_0_0_1px_rgba(129,140,248,0.25)] transition-transform active:scale-[0.96] disabled:opacity-50"
              >
                <Play size={15} /> 리플레이
              </button>
              <button
                onClick={() => runAction("backfill")}
                disabled={!!busy || !replayDate}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-cyan-500/12 px-3 text-sm font-semibold text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)] transition-transform active:scale-[0.96] disabled:opacity-50"
              >
                <Play size={15} /> 과거 백필
              </button>
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">Synthetic cutoff replay v1입니다. 후보 생성은 입력 날짜까지의 OHLCV만 사용하고, 평가는 저장 후 별도로 수행합니다. 과거 백필은 선택 날짜부터 20일 간격으로 최대 24회 실행합니다.</p>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-slate-200">유사 장세 복기</h2>
              <span className="font-mono text-[11px] text-slate-500">{analogData.benchmarkSymbol || "-"}</span>
            </div>
            {analogData.summary && (
              <div className="mb-3 grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[10px] text-slate-500">평가 수</div>
                  <div className="font-mono text-sm font-semibold text-slate-200">{analogData.summary.evaluated ?? 0}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[10px] text-slate-500">평균 PnL</div>
                  <div className={`font-mono text-sm font-semibold ${(Number(analogData.summary.avgNetPnlPct) || 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                    {analogData.summary.avgNetPnlPct == null ? "-" : `${Number(analogData.summary.avgNetPnlPct).toFixed(2)}%`}
                  </div>
                </div>
              </div>
            )}
            <div className="space-y-2">
              {(analogData.items || []).slice(0, 5).map((item: any) => (
                <div key={item.date} className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-indigo-300">{item.date}</span>
                    <span className="font-mono text-[11px] text-slate-500">sim {Math.round(Number(item.similarity || 0) * 100)}%</span>
                  </div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{item.lesson || "-"}</div>
                </div>
              ))}
              {!(analogData.items || []).length && (
                <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-500">유사 장세 replay 결과가 아직 없습니다.</div>
              )}
            </div>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h2 className="mb-3 text-sm font-semibold text-slate-200">실패패턴</h2>
            <div className="space-y-2">
              {topFailures.map(([reason, count]) => (
                <div key={reason} className="flex items-center justify-between rounded-lg bg-slate-950/60 px-3 py-2">
                  <span className="font-mono text-[11px] text-amber-300">{reason}</span>
                  <span className="font-mono text-xs tabular-nums text-slate-300">{count}</span>
                </div>
              ))}
              {!topFailures.length && <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-500">평가 완료된 실패패턴이 아직 없습니다.</div>}
            </div>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h2 className="mb-3 text-sm font-semibold text-slate-200">보정 후보</h2>
            <div className="space-y-2">
              {suggestions.slice(0, 6).map((item, index) => (
                <div key={`${item.reason || item.status}-${index}`} className="rounded-lg bg-slate-950/60 px-3 py-2 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                  <div className="flex items-center justify-between gap-3">
                    <span className={`font-mono text-[11px] ${item.status === "SUGGESTED" ? "text-cyan-300" : "text-slate-500"}`}>{item.status}</span>
                    <span className="font-mono text-[11px] text-slate-500">{item.approvalStatus || "PENDING_REVIEW"} · {item.sampleCount || 0} samples</span>
                  </div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{item.message || item.reason || "-"}</div>
                  {item.status === "SUGGESTED" && item.approvalStatus === "PENDING_REVIEW" && (
                    <div className="mt-2 flex gap-2">
                      <button
                        onClick={() => reviewSuggestion(item, "APPROVED")}
                        disabled={!!busy}
                        className="inline-flex min-h-8 flex-1 items-center justify-center gap-1.5 rounded-md bg-emerald-500/12 px-2 text-xs font-semibold text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.22)] disabled:opacity-50"
                      >
                        <CheckCircle2 size={13} /> 승인
                      </button>
                      <button
                        onClick={() => reviewSuggestion(item, "REJECTED")}
                        disabled={!!busy}
                        className="inline-flex min-h-8 flex-1 items-center justify-center gap-1.5 rounded-md bg-slate-800 px-2 text-xs font-semibold text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.14)] disabled:opacity-50"
                      >
                        <XCircle size={13} /> 반려
                      </button>
                    </div>
                  )}
                </div>
              ))}
              {!suggestions.length && <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-500">보정 후보가 아직 없습니다.</div>}
            </div>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-slate-200">적용 대기</h2>
              <span className="font-mono text-[11px] tabular-nums text-slate-500">{approvedSuggestions.length} approved</span>
            </div>
            {approvedSuggestions.length > 0 && (
              <button
                onClick={applyApprovedSuggestions}
                disabled={!!busy}
                className="mb-3 inline-flex min-h-9 w-full items-center justify-center gap-1.5 rounded-md bg-cyan-500/12 px-3 text-xs font-semibold text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.24)] disabled:opacity-50"
              >
                <ShieldCheck size={13} /> 승인 보정 적용
              </button>
            )}
            <div className="space-y-2">
              {approvedSuggestions.map((item) => (
                <div key={item.suggestionId} className="rounded-lg bg-emerald-500/8 px-3 py-2 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.14)]">
                  <div className="font-mono text-[11px] text-emerald-300">{item.reason || item.status}</div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{item.message || "-"}</div>
                  <div className="mt-1 font-mono text-[11px] text-slate-500">{item.market} / {item.mode} / {item.horizon} / {item.sourceType}</div>
                </div>
              ))}
              {!approvedSuggestions.length && <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-500">승인됐지만 아직 적용되지 않은 보정 후보가 없습니다.</div>}
            </div>
          </div>
        </div>
      </section>

      {/* ── 성과 대시보드 ─────────────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-violet-400" />
          <h2 className="text-sm font-semibold text-slate-200">성과 대시보드</h2>
          {perfData && <span className="font-mono text-[11px] text-slate-500">{perfData.summary?.count ?? 0}건 평가 완료</span>}
        </div>

        {!perfData || (perfData.summary?.count ?? 0) === 0 ? (
          <div className="rounded-lg bg-slate-900/50 p-6 text-center text-sm text-slate-500 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            평가 완료된 거래 데이터가 쌓이면 전략별 성과가 표시됩니다.
          </div>
        ) : (
          <>
            {/* 요약 지표 */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {[
                { label: "전체 평가", value: String(perfData.summary.count) },
                { label: "승률", value: perfData.summary.winRate != null ? `${(perfData.summary.winRate * 100).toFixed(1)}%` : "-", tone: perfData.summary.winRate != null && perfData.summary.winRate >= 0.5 ? "text-emerald-300" : "text-amber-300" },
                { label: "평균 PnL", value: perfData.summary.avgPnlPct != null ? `${perfData.summary.avgPnlPct >= 0 ? "+" : ""}${perfData.summary.avgPnlPct.toFixed(2)}%` : "-", tone: (perfData.summary.avgPnlPct ?? 0) >= 0 ? "text-emerald-300" : "text-red-300" },
                { label: "누적 PnL", value: perfData.summary.totalPnlPct != null ? `${perfData.summary.totalPnlPct >= 0 ? "+" : ""}${perfData.summary.totalPnlPct.toFixed(2)}%` : "-", tone: (perfData.summary.totalPnlPct ?? 0) >= 0 ? "text-emerald-300" : "text-red-300" },
                { label: "샤프 (간이)", value: perfData.summary.sharpe != null ? String(perfData.summary.sharpe) : "-", tone: (perfData.summary.sharpe ?? 0) >= 1 ? "text-emerald-300" : (perfData.summary.sharpe ?? 0) >= 0 ? "text-amber-300" : "text-red-300" },
                { label: "최대 낙폭", value: perfData.summary.maxDrawdownPct != null ? `${perfData.summary.maxDrawdownPct.toFixed(2)}%` : "-", tone: (perfData.summary.maxDrawdownPct ?? 0) <= 5 ? "text-emerald-300" : (perfData.summary.maxDrawdownPct ?? 0) <= 15 ? "text-amber-300" : "text-red-300" },
              ].map(({ label, value, tone = "text-slate-100" }) => (
                <div key={label} className="rounded-lg bg-slate-950/60 px-3 py-2 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
                  <div className="text-[11px] text-slate-500">{label}</div>
                  <div className={`mt-1 font-mono text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
                </div>
              ))}
            </div>

            {/* Equity Curve */}
            {(perfData.equityCurve?.length ?? 0) > 1 && (
              <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
                <div className="mb-2 text-xs font-semibold text-slate-400">누적 PnL 곡선</div>
                <EquityCurveSparkline points={perfData.equityCurve} />
              </div>
            )}

            {/* 전략 매트릭스 (mode × horizon) */}
            <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
              <div className="mb-3 text-xs font-semibold text-slate-400">전략 매트릭스 (mode × horizon)</div>
              <StrategyMatrix strategyRows={perfData.strategyRows ?? []} />
            </div>
          </>
        )}
      </section>

      {/* ── 애널리틱스 ───────────────────────────────────────────── */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-200">애널리틱스</h2>

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {/* 레짐 전환 매트릭스 */}
          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">레짐 전환 × 결과</h3>
            {(analyticsData.regimeTransition || []).length === 0 ? (
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-500">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.regimeTransition as any[]).map((row, i) => (
                  <div key={i} className="flex items-center justify-between gap-2 rounded-md bg-slate-950/50 px-3 py-1.5">
                    <span className="font-mono text-[11px] text-slate-400">
                      {row.regime_entry ?? "-"} → {row.regime_exit ?? "-"}
                    </span>
                    <div className="flex gap-3">
                      <span className="font-mono text-[11px] text-emerald-300">W:{row.win ?? 0}</span>
                      <span className="font-mono text-[11px] text-red-300">L:{row.loss ?? 0}</span>
                      <span className="font-mono text-[11px] text-slate-400">n:{row.count ?? 0}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 신호 신뢰도 × 실패 분류 */}
          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">신호 신뢰도 × 실패 태그</h3>
            {(analyticsData.confidenceBreakdown || []).length === 0 ? (
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-500">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.confidenceBreakdown as any[]).map((row, i) => (
                  <div key={i} className="flex items-center justify-between gap-2 rounded-md bg-slate-950/50 px-3 py-1.5">
                    <span className="font-mono text-[11px] text-slate-400">
                      {row.confidence_band ?? "-"}
                    </span>
                    <div className="flex gap-3">
                      <span className="font-mono text-[11px] text-amber-300">{row.top_failure ?? "-"}</span>
                      <span className="font-mono text-[11px] text-slate-400">n:{row.count ?? 0}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 진입 방식 비교 */}
          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">진입 방식 비교</h3>
            {(analyticsData.entryTypeComparison || []).length === 0 ? (
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-500">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.entryTypeComparison as any[]).map((row, i) => (
                  <div key={i} className="rounded-md bg-slate-950/50 px-3 py-2">
                    <div className="font-mono text-[11px] text-slate-200">{row.entry_type ?? "-"}</div>
                    <div className="mt-1 flex gap-3">
                      <span className="font-mono text-[11px] text-emerald-300">승률 {row.win_rate != null ? `${(row.win_rate * 100).toFixed(0)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-400">평균PnL {row.avg_pnl != null ? `${Number(row.avg_pnl).toFixed(2)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-500">n:{row.count ?? 0}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 소스 유형 비교 */}
          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">소스 유형 비교</h3>
            {(analyticsData.sourceComparison || []).length === 0 ? (
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-500">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.sourceComparison as any[]).map((row, i) => (
                  <div key={i} className="rounded-md bg-slate-950/50 px-3 py-2">
                    <div className={`font-mono text-[11px] ${row.source_type === "MANUAL_REVIEWED" ? "text-emerald-300" : "text-slate-200"}`}>{row.source_type ?? "-"}</div>
                    <div className="mt-1 flex gap-3">
                      <span className="font-mono text-[11px] text-emerald-300">승률 {row.win_rate != null ? `${(row.win_rate * 100).toFixed(0)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-400">평균PnL {row.avg_pnl != null ? `${Number(row.avg_pnl).toFixed(2)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-500">가중치 {row.weight ?? "-"} · n:{row.count ?? 0}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── 귀속분석 ─────────────────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-200">귀속분석</h2>
          {attrData && <span className="font-mono text-[11px] text-slate-500">{attrData.count ?? 0}건 분석</span>}
        </div>

        {!attrData || (attrData.count ?? 0) === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-700 py-8 text-center text-xs text-slate-500">
            평가 완료 데이터가 충분하지 않습니다 — 체결 평가 후 귀속분석이 활성화됩니다
          </div>
        ) : (
          <div className="space-y-4">
            {/* EV 신호 정확도 */}
            <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs font-semibold text-slate-400">EV 신호 정확도</div>
                {attrData.evAccuracy?.correlation != null && (
                  <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${
                    attrData.evAccuracy.correlation > 0.1 ? "bg-emerald-500/15 text-emerald-300"
                    : attrData.evAccuracy.correlation < -0.1 ? "bg-red-500/15 text-red-300"
                    : "bg-slate-700 text-slate-400"
                  }`}>
                    r={attrData.evAccuracy.correlation} — {attrData.evAccuracy.correlationLabel}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  { label: "EV>0 신호 수", value: attrData.evAccuracy?.evPositive?.n ?? 0, unit: "건" },
                  { label: "EV>0 실제 승률", value: attrData.evAccuracy?.evPositive?.winRate != null ? `${(attrData.evAccuracy.evPositive.winRate * 100).toFixed(1)}%` : "-", tone: (attrData.evAccuracy?.evPositive?.winRate ?? 0) >= 0.5 ? "text-emerald-300" : "text-amber-300" },
                  { label: "EV>0 평균 PnL", value: attrData.evAccuracy?.evPositive?.avgPnlPct != null ? `${attrData.evAccuracy.evPositive.avgPnlPct >= 0 ? "+" : ""}${attrData.evAccuracy.evPositive.avgPnlPct.toFixed(2)}%` : "-", tone: (attrData.evAccuracy?.evPositive?.avgPnlPct ?? 0) >= 0 ? "text-emerald-300" : "text-red-300" },
                  { label: "EV 상관계수", value: attrData.evAccuracy?.correlation != null ? String(attrData.evAccuracy.correlation) : "-", tone: (attrData.evAccuracy?.correlation ?? 0) > 0.1 ? "text-emerald-300" : (attrData.evAccuracy?.correlation ?? 0) < -0.1 ? "text-red-300" : "text-slate-400" },
                ].map(({ label, value, unit, tone }: any) => (
                  <div key={label} className="rounded-lg bg-slate-950/50 px-3 py-2">
                    <div className="text-[10px] text-slate-500">{label}</div>
                    <div className={`mt-1 font-mono text-sm font-bold ${tone || "text-slate-200"}`}>{value}{unit ? ` ${unit}` : ""}</div>
                  </div>
                ))}
              </div>
              {(attrData.evAccuracy?.evQuartileBuckets?.length ?? 0) > 0 && (
                <div className="mt-3">
                  <div className="mb-1.5 text-[10px] text-slate-500">EV 사분위별 실수익</div>
                  <div className="flex gap-2">
                    {attrData.evAccuracy.evQuartileBuckets.map((b: any) => (
                      <div key={b.label} className="flex-1 rounded-lg bg-slate-800/60 px-2 py-1.5 text-center">
                        <div className="text-[9px] text-slate-500">{b.label}</div>
                        <div className={`font-mono text-xs font-bold ${(b.avgPnlPct ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                          {b.avgPnlPct != null ? `${b.avgPnlPct >= 0 ? "+" : ""}${b.avgPnlPct.toFixed(2)}%` : "-"}
                        </div>
                        <div className="text-[9px] text-slate-600">n={b.n}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* 팩터별 기여도 테이블 */}
            {[
              { key: "byRegime", label: "마켓 레짐별" },
              { key: "byMarket", label: "시장별" },
              { key: "byMode", label: "전략 모드별" },
              { key: "byHorizon", label: "투자 기간별" },
              { key: "byEntryType", label: "진입 유형별" },
              { key: "bySector", label: "섹터별" },
            ].map(({ key, label }) => {
              const rows: any[] = attrData[key] ?? [];
              if (rows.length === 0) return null;
              return (
                <div key={key} className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
                  <div className="mb-2 text-xs font-semibold text-slate-400">{label}</div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-[10px] text-slate-500">
                          <th className="pb-1.5 text-left font-medium">팩터</th>
                          <th className="pb-1.5 text-right font-medium">n</th>
                          <th className="pb-1.5 text-right font-medium">승률</th>
                          <th className="pb-1.5 text-right font-medium">평균PnL</th>
                          <th className="pb-1.5 text-right font-medium">IR</th>
                          <th className="pb-1.5 text-right font-medium">기여%</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/40">
                        {rows.map((r: any) => (
                          <tr key={r.factor}>
                            <td className="py-1.5 font-mono text-slate-300">{r.factor || "-"}</td>
                            <td className="py-1.5 text-right text-slate-400">{r.count}</td>
                            <td className={`py-1.5 text-right font-mono font-semibold ${(r.winRate ?? 0) >= 0.5 ? "text-emerald-400" : "text-amber-400"}`}>
                              {r.winRate != null ? `${(r.winRate * 100).toFixed(0)}%` : "-"}
                            </td>
                            <td className={`py-1.5 text-right font-mono font-semibold ${(r.avgPnlPct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                              {r.avgPnlPct != null ? `${r.avgPnlPct >= 0 ? "+" : ""}${r.avgPnlPct.toFixed(2)}%` : "-"}
                            </td>
                            <td className={`py-1.5 text-right font-mono ${(r.ir ?? 0) >= 0.5 ? "text-emerald-300" : (r.ir ?? 0) >= 0 ? "text-slate-300" : "text-red-300"}`}>
                              {r.ir != null ? r.ir.toFixed(2) : "-"}
                            </td>
                            <td className={`py-1.5 text-right font-mono ${(r.contribPct ?? 0) >= 0 ? "text-slate-300" : "text-red-400"}`}>
                              {r.contribPct != null ? `${r.contribPct >= 0 ? "+" : ""}${r.contribPct.toFixed(1)}%` : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-200">OLS factor model</h2>
          <span className="font-mono text-[11px] text-slate-500">
            {attrData?.regression?.status || "LOW_SAMPLE"}
            {attrData?.regression?.r2 != null ? ` · R2 ${attrData.regression.r2}` : ""}
          </span>
        </div>
        {!attrData || attrData.regression?.status !== "OK" ? (
          <div className="rounded-lg border border-dashed border-slate-700 py-6 text-center text-xs text-slate-500">
            Regression attribution needs at least {attrData?.regression?.minRequired ?? 12} evaluated trades with enough factor variation.
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {(attrData.regression?.coefficients || []).slice(0, 8).map((row: any) => (
              <div key={row.factor} className="flex items-center justify-between gap-3 rounded-md bg-slate-950/50 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <div className="truncate font-mono text-slate-300">{row.factor}</div>
                  <div className="text-[10px] text-slate-600">{row.group}</div>
                </div>
                <div className={`font-mono font-semibold ${row.coef >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                  {row.coef >= 0 ? "+" : ""}{Number(row.coef).toFixed(3)}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-200">진입 효율</h2>
            {effData && <span className="font-mono text-[11px] text-slate-500">{effData.filled ?? 0}/{effData.total ?? 0} filled</span>}
          </div>
          {!effData || (effData.total ?? 0) === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-700 py-8 text-center text-xs text-slate-500">
              진입 효율을 계산할 평가 완료 거래가 아직 없습니다.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: "체결률", value: effData.fillRate != null ? `${(effData.fillRate * 100).toFixed(1)}%` : "-" },
                  { label: "평균 슬리피지", value: effData.avgSlippagePct != null ? `${effData.avgSlippagePct >= 0 ? "+" : ""}${effData.avgSlippagePct.toFixed(2)}%` : "-" },
                  { label: "평균 진입일", value: effData.avgFillDays != null ? `${effData.avgFillDays.toFixed(1)}일` : "-" },
                ].map((item) => (
                  <div key={item.label} className="rounded-lg bg-slate-950/60 px-3 py-2">
                    <div className="text-[10px] text-slate-500">{item.label}</div>
                    <div className="mt-1 font-mono text-sm font-semibold text-slate-100">{item.value}</div>
                  </div>
                ))}
              </div>
              <div className="space-y-1">
                {(effData.byHorizon || []).map((row: any) => (
                  <div key={row.horizon} className="grid grid-cols-[0.8fr_1fr_1fr_1fr] items-center gap-2 rounded-md bg-slate-950/50 px-3 py-2 text-xs">
                    <span className="font-mono uppercase text-slate-300">{row.horizon}</span>
                    <span className="text-right font-mono text-slate-400">n:{row.total ?? 0}</span>
                    <span className={`text-right font-mono font-semibold ${(row.fillRate ?? 0) >= 0.6 ? "text-emerald-300" : "text-amber-300"}`}>
                      {row.fillRate != null ? `${(row.fillRate * 100).toFixed(0)}%` : "-"}
                    </span>
                    <span className={`text-right font-mono ${(row.avgSlippagePct ?? 0) <= 0.2 ? "text-slate-300" : "text-red-300"}`}>
                      {row.avgSlippagePct != null ? `${row.avgSlippagePct >= 0 ? "+" : ""}${row.avgSlippagePct.toFixed(2)}%` : "-"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-slate-200">모델 자기개선 피드백</h2>
            <div className="flex items-center gap-2">
              {feedbackData && <span className="font-mono text-[11px] text-slate-500">{feedbackData.sampleCount ?? 0} samples</span>}
              <button
                onClick={() => runAction("self-calibrate")}
                disabled={!!busy}
                className="inline-flex min-h-8 items-center justify-center rounded-lg bg-emerald-500/10 px-2 text-[11px] font-semibold text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.22)] transition-transform active:scale-[0.96] disabled:opacity-50"
              >
                자가보정 실행
              </button>
              <button
                onClick={rollbackSelfLearning}
                disabled={!!busy || !selfLearningData?.correctionVersion}
                className="inline-flex min-h-8 items-center justify-center rounded-lg bg-red-500/10 px-2 text-[11px] font-semibold text-red-200 shadow-[inset_0_0_0_1px_rgba(248,113,113,0.22)] transition-transform active:scale-[0.96] disabled:opacity-50"
              >
                롤백
              </button>
            </div>
          </div>
          {!feedbackData || feedbackData.status === "LOW_SAMPLE" ? (
            <div className="rounded-lg border border-dashed border-slate-700 py-8 text-center text-xs text-slate-500">
              표본이 부족합니다. 최소 {feedbackData?.minRequired ?? 10}건 이상 평가 후 피드백이 생성됩니다.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[10px] text-slate-500">기준 승률</div>
                  <div className="mt-1 font-mono text-sm font-semibold text-slate-100">
                    {feedbackData.baseWinRate != null ? `${(feedbackData.baseWinRate * 100).toFixed(1)}%` : "-"}
                  </div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[10px] text-slate-500">기준 평균 PnL</div>
                  <div className={`mt-1 font-mono text-sm font-semibold ${(feedbackData.baseAvgPnlPct ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                    {feedbackData.baseAvgPnlPct != null ? `${feedbackData.baseAvgPnlPct >= 0 ? "+" : ""}${feedbackData.baseAvgPnlPct.toFixed(2)}%` : "-"}
                  </div>
                </div>
              </div>
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
                Self-learning guarded. Eligible auto {selfLearningData?.eligibleAutoCount ?? 0} · low sample {selfLearningData?.lowSampleCount ?? 0} · applied {selfLearningData?.appliedCount ?? 0} · correction v{selfLearningData?.correctionVersion ?? 0}
              </div>
              {(selfLearningData?.performanceGate || opsData?.performanceGate) && (
                <div className={`rounded-lg border px-3 py-2 text-[11px] ${
                  (selfLearningData?.performanceGate || opsData?.performanceGate)?.status === "ROLLBACK_READY"
                    ? "border-red-500/30 bg-red-500/10 text-red-200"
                    : (selfLearningData?.performanceGate || opsData?.performanceGate)?.status === "LOW_SAMPLE"
                      ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
                      : "border-cyan-500/20 bg-cyan-500/5 text-cyan-200"
                }`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold">
                      Performance gate: {(selfLearningData?.performanceGate || opsData?.performanceGate)?.status}
                    </span>
                    <span className="font-mono">
                      rollback candidates {(selfLearningData?.performanceGate || opsData?.performanceGate)?.candidateCount ?? 0}
                    </span>
                  </div>
                  <div className="mt-1 text-slate-400">
                    Applied calibrations are checked after enough before/after evaluated trades accumulate.
                  </div>
                </div>
              )}
              <div className="rounded-lg bg-slate-950/60 p-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <div className="text-[10px] text-slate-500">학습 품질 점수</div>
                    <div className="mt-1 font-mono text-lg font-semibold text-slate-100">
                      {selfLearningData?.quality?.score ?? 0}<span className="ml-1 text-xs text-slate-500">/100</span>
                    </div>
                  </div>
                  <div className="rounded-lg bg-slate-900 px-2 py-1 font-mono text-sm font-semibold text-cyan-200">
                    {selfLearningData?.quality?.grade ?? "D"}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                  <div>
                    <div className="text-slate-500">유효표본</div>
                    <div className="font-mono text-slate-200">{selfLearningData?.quality?.effectiveSamples ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Forward</div>
                    <div className="font-mono text-slate-200">{selfLearningData?.quality?.forwardSamples ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">Replay</div>
                    <div className="font-mono text-slate-200">{selfLearningData?.quality?.historicalReplaySamples ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-slate-500">최근 실행</div>
                    <div className="truncate font-mono text-slate-200">{selfLearningData?.lastSelfLearningRun?.generatedAt ?? "-"}</div>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {(selfLearningData?.quality?.gates || []).map((gate: any) => (
                    <span
                      key={gate.name}
                      className={`rounded-md px-2 py-1 font-mono text-[10px] ${gate.status === "PASS" ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/10 text-amber-300"}`}
                    >
                      {gate.name}:{gate.status}
                    </span>
                  ))}
                </div>
              </div>
              {opsData && (
                <div className="rounded-lg bg-slate-950/60 p-3">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Ops dashboard</div>
                    <div className="font-mono text-[10px] text-slate-500">{opsData.generatedAt || "-"}</div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                    <div>
                      <div className="text-slate-500">Journal</div>
                      <div className="font-mono text-slate-200">{opsData.journal?.totalRows ?? 0}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Evaluated</div>
                      <div className="font-mono text-slate-200">{opsData.journal?.evaluatedRows ?? 0}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Open</div>
                      <div className="font-mono text-slate-200">{opsData.journal?.openRows ?? 0}</div>
                    </div>
                    <div>
                      <div className="text-slate-500">Files OK</div>
                      <div className="font-mono text-slate-200">
                        {(opsData.files || []).filter((f: any) => f.exists).length}/{(opsData.files || []).length}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-500">자동 최소 유효표본</div>
                  <div className="mt-1 font-mono text-slate-200">{selfLearningData?.policy?.minEffectiveSamples ?? "-"}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-500">회당 적용 한도</div>
                  <div className="mt-1 font-mono text-slate-200">{selfLearningData?.policy?.maxApplicationsPerRun ?? "-"}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-500">최대 실패비중</div>
                  <div className="mt-1 font-mono text-slate-200">{selfLearningData?.policy?.maxFailureShareForAutoApply != null ? `${(selfLearningData.policy.maxFailureShareForAutoApply * 100).toFixed(0)}%` : "-"}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-500">자동 승인자</div>
                  <div className="mt-1 truncate font-mono text-slate-200">{selfLearningData?.policy?.reviewer ?? "-"}</div>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-xs">
                  <thead className="text-[10px] text-slate-500">
                    <tr>
                      <th className="pb-2 text-left font-medium">전략</th>
                      <th className="pb-2 text-right font-medium">n</th>
                      <th className="pb-2 text-right font-medium">승률</th>
                      <th className="pb-2 text-right font-medium">평균PnL</th>
                      <th className="pb-2 text-right font-medium">배율</th>
                      <th className="pb-2 text-right font-medium">방향</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/50">
                    {(feedbackData.adjustments || []).slice(0, 12).map((row: any) => (
                      <tr key={`${row.mode}-${row.horizon}`}>
                        <td className="py-2 font-mono text-slate-300">{row.mode}/{row.horizon}</td>
                        <td className="py-2 text-right font-mono text-slate-400">{row.n}</td>
                        <td className="py-2 text-right font-mono text-slate-300">{row.winRate != null ? `${(row.winRate * 100).toFixed(0)}%` : "-"}</td>
                        <td className={`py-2 text-right font-mono ${(row.avgPnlPct ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                          {row.avgPnlPct != null ? `${row.avgPnlPct >= 0 ? "+" : ""}${row.avgPnlPct.toFixed(2)}%` : "-"}
                        </td>
                        <td className="py-2 text-right font-mono text-slate-200">{row.multiplier?.toFixed ? row.multiplier.toFixed(2) : row.multiplier}</td>
                        <td className={`py-2 text-right font-mono font-semibold ${row.direction === "BOOST" ? "text-emerald-300" : row.direction === "REDUCE" ? "text-red-300" : "text-slate-400"}`}>
                          {row.direction}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
