"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, BookOpenCheck, CheckCircle2, ClipboardCheck, Play, RefreshCw, ShieldCheck, Target, TimerReset, TrendingUp, XCircle, Zap } from "lucide-react";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import { outcomeTone, toneClassName } from "@/lib/tone";
import { displayName } from "@/lib/moneDisplay";
import { SegmentedControl } from "@/components/ui/SegmentedControl";

type ScopeMarket = Extract<Market, "kr" | "us" | "all">;
type ScopeMode = Extract<Mode, "conservative" | "balanced" | "aggressive" | "all">;
type ScopeHorizon = Extract<Horizon, "short" | "swing" | "mid" | "all">;
type ScopeSession = "all" | "PREMARKET_PLAN" | "INTRADAY_CHECK" | "AFTER_CLOSE_TRADE" | "FOLLOWUP_EVALUATION";
type FailureAnalysisBasis = "all" | "evaluated" | "pending" | "dataQuality";
type JournalView = "journal" | "perf" | "diag";
type ListSource = "all" | "FORWARD_PAPER_TRADE" | "MANUAL_REVIEWED" | "HISTORICAL_REPLAY";

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
  { id: "INTRADAY_CHECK", label: "Intraday" },
  { id: "AFTER_CLOSE_TRADE", label: "After close" },
  { id: "FOLLOWUP_EVALUATION", label: "Follow-up" },
];

const listSources: { id: ListSource; label: string }[] = [
  { id: "all", label: "전체 소스" },
  { id: "FORWARD_PAPER_TRADE", label: "자동" },
  { id: "MANUAL_REVIEWED", label: "검토완료" },
  { id: "HISTORICAL_REPLAY", label: "리플레이" },
];

const views: { id: JournalView; label: string }[] = [
  { id: "journal", label: "일지" },
  { id: "perf", label: "성과" },
  { id: "diag", label: "정밀 진단" },
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
      <div className="text-[11px] text-slate-400">{label}</div>
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
      <div className="mt-1 flex justify-between font-mono text-[13px] leading-5 text-slate-400">
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
    if (wr == null) return "bg-slate-800 text-slate-400";
    if (wr >= 0.6) return "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30";
    if (wr >= 0.45) return "bg-amber-500/15 text-amber-300 border border-amber-500/25";
    return "bg-red-500/15 text-red-300 border border-red-500/25";
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[400px] text-center text-xs">
        <thead>
          <tr className="text-slate-400">
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

function fmtMoney(value: any, market: string) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return market === "us"
    ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : `${Math.round(n).toLocaleString("ko-KR")}원`;
}

function fmtPctValue(value: any, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n.toFixed(digits)}%`;
}

function fmtSignedPct(value: any, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

function AiPaperSurvivalPanel({
  data,
  preview,
  onRefresh,
  onPreview,
  busy,
}: {
  data: any;
  preview: any;
  onRefresh: () => void;
  onPreview: () => void;
  busy: boolean;
}) {
  const marketsData = data?.markets || {};
  const marketEntries = (["kr", "us"] as const).map((mk) => [mk, marketsData[mk] || {}] as const);
  const previewActions = Object.values(preview?.markets || {}).flatMap((item: any) => item?.actions || []).slice(0, 6);
  const stateTone = (state: string) => {
    if (state === "DEAD" || state === "CRITICAL") return "text-red-300";
    if (state === "DANGER") return "text-amber-300";
    return "text-emerald-300";
  };
  const actionTone = (action: string) => {
    if (action === "BUY") return "bg-emerald-500/15 text-emerald-300";
    if (action === "SELL") return "bg-red-500/15 text-red-300";
    return "bg-slate-700 text-slate-300";
  };
  const verdictTone = (verdict: string) => {
    if (verdict === "PROVING_EDGE" || verdict === "COMPETITIVE") return "text-emerald-300";
    if (verdict === "NOT_PROVEN") return "text-red-300";
    return "text-amber-300";
  };

  return (
    <section className="rounded-lg bg-slate-900/60 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <ShieldCheck size={16} className="text-emerald-300" />
            <span>AI 생존계좌</span>
          </div>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
            실제 주문 없이 AI 추천만으로 굴리는 검증 계좌입니다. 0원이 되면 실패로 멈추고, OOS 증거판으로 성능을 비교합니다.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={onPreview} disabled={busy} className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg bg-emerald-500/12 px-3 text-xs font-semibold text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.22)] disabled:opacity-50">
            <Play size={13} /> 다음 행동 점검
          </button>
          <button onClick={onRefresh} disabled={busy} className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg bg-slate-800 px-3 text-xs font-semibold text-slate-200 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.14)] disabled:opacity-50">
            <RefreshCw size={13} className={busy ? "animate-spin" : ""} /> 새로고침
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {marketEntries.map(([mk, item]) => {
          const summary = item?.summary || {};
          const survival = item?.survival || {};
          const positions = item?.positions || [];
          const activeAgent = item?.activeAgent || {};
          const proof = item?.proofBoard || {};
          const live = item?.liveMetrics || {};
          const proofRows = Array.isArray(proof.rows) ? proof.rows.slice(0, 3) : [];
          const state = survival.state || "UNKNOWN";
          const liveEnough = Number(live.sampleCount || 0) >= 5;
          return (
            <div key={mk} className="rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="rounded-md bg-slate-800 px-2 py-1 text-[11px] font-semibold text-slate-300">{mk.toUpperCase()}</span>
                  <span className={`font-mono text-xs font-semibold ${stateTone(state)}`}>{state}</span>
                </div>
                <span className="text-[11px] text-slate-400">후보 {item?.candidateCount ?? 0}개</span>
              </div>
              <div className="mt-3 rounded-md bg-slate-900/65 p-2 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                <div className="flex items-center justify-between gap-3 text-[11px]">
                  <span className="text-slate-400">현재 AI</span>
                  <span className="truncate text-right font-semibold text-slate-200">{activeAgent.label || summary.agentLabel || "-"}</span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-3 text-[11px]">
                  <span className="text-slate-400">OOS 판정</span>
                  <span className={`truncate text-right font-semibold ${verdictTone(proof.verdict)}`}>{proof.verdict || "UNPROVEN"}</span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-3 text-[11px]">
                  <span className="text-slate-400">검증 순위</span>
                  <span className="text-right text-slate-300">
                    {proof.currentRank ? `${proof.currentRank}/${proof.profileCount}` : "-"}
                    {proof.beatsBestBaseline ? " · baseline beat" : ""}
                  </span>
                </div>
                {item?.proofFailed && (
                  <div className="mt-2 rounded bg-red-500/10 px-2 py-1 text-[11px] font-semibold text-red-200">
                    잔고 소진: 검증 실패, 추가 매매 중지
                  </div>
                )}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {metric("계좌가치", fmtMoney(summary.portfolioValue ?? survival.portfolioValue, mk))}
                {metric("현금", fmtMoney(summary.cash, mk))}
                {metric("수익률", summary.totalReturnPct == null ? "-" : `${Number(summary.totalReturnPct).toFixed(2)}%`, Number(summary.totalReturnPct || 0) >= 0 ? "text-emerald-300" : "text-red-300")}
                {metric("생존율", survival.survivalPct == null ? "-" : `${Number(survival.survivalPct).toFixed(1)}%`, stateTone(state))}
              </div>
              <div className="mt-3 rounded-md bg-slate-900/65 p-2 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                <div className="mb-2 flex items-center justify-between gap-3 text-[11px]">
                  <span className="font-semibold text-slate-300">실전 NAV</span>
                  <span className={liveEnough ? "text-slate-400" : "text-amber-300"}>
                    {liveEnough ? `${live.sampleCount}개 구간` : `샘플 부족 ${live.sampleCount ?? 0}/5`}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">누적</span>
                    <span className={`font-mono ${Number(live.totalReturnPct || 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>{fmtSignedPct(live.totalReturnPct)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">MDD</span>
                    <span className="font-mono text-red-300">{fmtPctValue(live.mddPct)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">샤프</span>
                    <span className="font-mono text-slate-200">{live.sharpe == null ? "-" : Number(live.sharpe).toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">승률</span>
                    <span className="font-mono text-slate-200">{fmtPctValue(live.winRate, 1)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">현금비중</span>
                    <span className="font-mono text-slate-200">{fmtPctValue(live.cashPct, 1)}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-slate-400">고점</span>
                    <span className="font-mono text-slate-200">{fmtMoney(live.peakValue, mk)}</span>
                  </div>
                </div>
              </div>
              <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400">
                <span>보유 {summary.positionCount ?? positions.length ?? 0}개</span>
                <span>거래 {summary.tradeCount ?? 0}회</span>
                <span>NAV {data?.navRows ?? 0}행</span>
              </div>
              {proofRows.length > 0 && (
                <div className="mt-3 space-y-1">
                  {proofRows.map((row: any, idx: number) => (
                    <div key={`${mk}-${row.agentId}-${idx}`} className="grid grid-cols-[1fr_auto_auto] items-center gap-2 text-[13px] leading-5 text-slate-400">
                      <span className={row.agentId === activeAgent.id ? "truncate font-semibold text-slate-200" : "truncate"}>{idx + 1}. {row.agentLabel}</span>
                      <span className="font-mono">{Number(row.avgNetPnlPct || 0).toFixed(2)}%</span>
                      <span className="font-mono">WR {Number(row.winRate || 0).toFixed(1)}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {previewActions.length > 0 && (
        <div className="mt-3 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
          <div className="mb-2 text-xs font-semibold text-slate-400">다음 행동 미리보기</div>
          <div className="grid gap-2 md:grid-cols-2">
            {previewActions.map((action: any, index: number) => (
              <div key={`${action.market}-${action.symbol || action.reason || action.action}-${index}`} className="flex items-center justify-between gap-3 rounded-md bg-slate-900/70 px-3 py-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${actionTone(action.action)}`}>
                      {action.action}
                    </span>
                    <span className="truncate text-xs font-semibold text-slate-200">
                      {action.name || action.symbol || action.reason}
                    </span>
                    {action.symbol && <span className="font-mono text-[13px] leading-5 text-slate-400">{action.symbol}</span>}
                  </div>
                  <div className="mt-1 text-[11px] text-slate-400">{action.decision || action.reason || "-"}</div>
                </div>
                <div className="text-right font-mono text-[11px] text-slate-300">
                  <div>{action.price == null ? "-" : fmtMoney(action.price, action.market)}</div>
                  {action.quantity != null && <div className="text-slate-400">x {Number(action.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 })}</div>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
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
  const [view, setView] = useState<JournalView>("journal");
  const [listSource, setListSource] = useState<ListSource>("all");
  const [lensData, setLensData] = useState<any>(null);
  const [smartRank, setSmartRank] = useState<any>(null);
  const [highConv, setHighConv] = useState<any>(null);
  const [researchLeader, setResearchLeader] = useState<any>(null);
  const [researchRs, setResearchRs] = useState<any>(null);
  // 정밀 진단 탭의 진단 섹션들은 부가 정보라 기본 접힘(밀도 완화). 필요할 때만 펼친다.
  const [diagOpen, setDiagOpen] = useState<Record<string, boolean>>({});
  const toggleDiag = (key: string) => setDiagOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  const DiagToggle = ({ id }: { id: string }) => (
    <button
      type="button"
      aria-expanded={!!diagOpen[id]}
      onClick={() => toggleDiag(id)}
      className="shrink-0 rounded-lg border border-slate-800 bg-slate-900 px-2.5 py-1.5 font-mono text-[11px] font-semibold text-slate-400 transition-transform active:scale-[0.96]"
    >
      {diagOpen[id] ? "접기 ▲" : "펼치기 ▼"}
    </button>
  );
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
  const [entryNotTouchedData, setEntryNotTouchedData] = useState<any>({});
  const [marketGapData, setMarketGapData] = useState<any>({});
  const [overextendedData, setOverextendedData] = useState<any>({});
  const [profitCaptureData, setProfitCaptureData] = useState<any>({});
  const [perfGateData, setPerfGateData] = useState<any>({});
  const [aiPaperData, setAiPaperData] = useState<any>({});
  const [aiPaperPreview, setAiPaperPreview] = useState<any>({});

  const scope = useMemo(() => ({ market, mode, horizon, sourceType: "FORWARD_PAPER_TRADE", journalSession }), [market, mode, horizon, journalSession]);
  const actionSession = journalSession === "all" ? "AFTER_CLOSE_TRADE" : journalSession;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      // 개별 API 실패가 페이지 전체를 무너뜨리지 않도록 각 호출을 격리한다.
      // (한 엔드포인트의 네트워크 예외로 나머지 패널까지 사라지던 문제 방지)
      const safe = <T,>(p: Promise<T>, fallback: T): Promise<T> => p.then((v) => v ?? fallback).catch(() => fallback);
      const listSourceParam = listSource === "all" ? undefined : listSource;
      const [tradeRes, patternRes, suggestionRes, statusRes, analyticsRes, failureAnalyticsRes, improvementRes, stopLossRes, entryTimingRes, entryNotTouchedRes, marketGapRes, overextendedRes, profitCaptureRes, perfGateRes, perfRes, attrRes, effRes, feedbackRes, selfLearningRes, opsRes, lensRes, smartRes, hcRes, researchLeaderRes, researchRsRes] = await Promise.all([
        safe(mone.virtualTrades({ ...scope, sourceType: listSourceParam, limit: 200 }), { status: "ERROR", error: "일지 로드 실패", items: [] } as any),
        safe(mone.journalFailurePatterns(scope), {} as any),
        safe(mone.journalCalibrationSuggestions(scope), {} as any),
        safe(mone.journalAutoCaptureStatus(), {} as any),
        safe(mone.journalAnalytics(scope), {} as any),
        safe(mone.virtualFailureAnalytics(scope), {} as any),
        safe(mone.virtualImprovementPriorities(scope), {} as any),
        safe(mone.virtualStopLossDiagnostics(scope), {} as any),
        safe(mone.virtualEntryTimingDiagnostics(scope), {} as any),
        safe(mone.virtualEntryNotTouchedDiagnostics(scope), {} as any),
        safe(mone.virtualMarketGapDiagnostics(scope), {} as any),
        safe(mone.virtualOverextendedEntryDiagnostics(scope), {} as any),
        safe(mone.virtualProfitCaptureDiagnostics(scope), {} as any),
        safe(mone.virtualPerformanceGateDiagnostics({ market: scope.market, mode: scope.mode, horizon: scope.horizon }), {} as any),
        safe(mone.journalPerformance({ market: scope.market, mode: scope.mode, horizon: scope.horizon }), {} as any),
        safe(mone.journalAttribution({ market: scope.market, mode: scope.mode, horizon: scope.horizon }), {} as any),
        safe(mone.journalEntryEfficiency({ market: scope.market, horizon: scope.horizon }), {} as any),
        safe(mone.journalAttributionFeedback({ market: scope.market }), {} as any),
        safe(mone.journalSelfLearningStatus({ market: scope.market }), {} as any),
        safe(mone.journalOpsDashboard({ market: scope.market }), {} as any),
        safe(mone.lensCandidates({ market: "kr" }), {} as any),
        safe(mone.smartRank({ market: "kr" }), {} as any),
        safe(mone.highConviction({ market: "kr" }), {} as any),
        safe(mone.researchLeaderBreakout({ market: "kr" }), {} as any),
        safe(mone.researchRelativeStrength({ market: "kr" }), {} as any),
      ]);
      if (tradeRes.status === "ERROR") setError(tradeRes.error || "일지 로드 실패");
      setTrades(tradeRes.items || []);
      setPatterns(patternRes.items || []);
      setSuggestions(suggestionRes.items || []);
      setAutoStatus(statusRes || {});
      setAnalyticsData(analyticsRes || {});
      setFailureAnalytics(failureAnalyticsRes || {});
      setImprovementData(improvementRes || {});
      setStopLossData(stopLossRes || {});
      setEntryTimingData(entryTimingRes || {});
      setEntryNotTouchedData(entryNotTouchedRes || {});
      setMarketGapData(marketGapRes || {});
      setOverextendedData(overextendedRes || {});
      setProfitCaptureData(profitCaptureRes || {});
      setPerfGateData(perfGateRes || {});
      setPerfData(perfRes?.status === "OK" ? perfRes : null);
      setAttrData(attrRes?.status === "OK" ? attrRes : null);
      setEffData(effRes?.status === "OK" ? effRes : null);
      setFeedbackData(feedbackRes?.status === "OK" || feedbackRes?.status === "LOW_SAMPLE" ? feedbackRes : null);
      setSelfLearningData(selfLearningRes?.status === "OK" ? selfLearningRes : null);
      setOpsData(opsRes?.status === "OK" ? opsRes : null);
      setLensData(lensRes && (lensRes.status === "OK" || lensRes.status === "EMPTY") ? lensRes : null);
      setSmartRank(smartRes && (smartRes.status === "OK" || smartRes.status === "EMPTY") ? smartRes : null);
      setHighConv(hcRes && (hcRes.status === "OK" || hcRes.status === "EMPTY") ? hcRes : null);
      setResearchLeader(researchLeaderRes && (researchLeaderRes.status === "OK" || researchLeaderRes.status === "US_BACKDROP_UNFAVORABLE" || researchLeaderRes.status === "EMPTY") ? researchLeaderRes : null);
      setResearchRs(researchRsRes && (researchRsRes.status === "OK" || researchRsRes.status === "BEAR_DEFENSIVE" || researchRsRes.status === "EMPTY") ? researchRsRes : null);
      try {
        const aiPaperRes = await mone.aiPaperStatus({ market: scope.market });
        setAiPaperData(aiPaperRes?.status === "OK" ? aiPaperRes : {});
      } catch {
        setAiPaperData({});
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [scope, listSource]);

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

  const runAiPaperPreview = async () => {
    setBusy("ai-paper-preview");
    setError("");
    try {
      const res = await mone.aiPaperRun({ market, dryRun: true });
      if (res.status === "ERROR") throw new Error(res.error || "AI paper preview failed");
      setAiPaperPreview(res);
      try {
        const statusRes = await mone.aiPaperStatus({ market });
        setAiPaperData(statusRes?.status === "OK" ? statusRes : {});
      } catch {
        setAiPaperData({});
      }
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

  // 손익 비대칭(북극성): 손실↓·수익↑ 개선 여부를 직접 보여주는 지표.
  // 손익이 확정된(net_pnl_pct 유한) 거래만 대상으로 클라이언트에서 계산한다.
  const asymmetry = useMemo(() => {
    const pnls = trades.map((item) => Number(item.net_pnl_pct)).filter((v) => Number.isFinite(v));
    if (!pnls.length) return null;
    const wins = pnls.filter((v) => v > 0);
    const losses = pnls.filter((v) => v < 0);
    const sum = (arr: number[]) => arr.reduce((a, b) => a + b, 0);
    const grossProfit = sum(wins);
    const grossLoss = Math.abs(sum(losses));
    const avgWin = wins.length ? grossProfit / wins.length : null;
    const avgLoss = losses.length ? -grossLoss / losses.length : null; // 음수 표기
    const expectancy = sum(pnls) / pnls.length;
    const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : null;
    const payoff = avgWin != null && avgLoss != null && avgLoss !== 0 ? avgWin / Math.abs(avgLoss) : null;
    return {
      n: pnls.length,
      winCount: wins.length,
      lossCount: losses.length,
      winRate: (wins.length / pnls.length) * 100,
      avgWin,
      avgLoss,
      expectancy,
      profitFactor,
      payoff,
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
  const selfLearningPolicy = selfLearningData?.policy || {};
  const sourceMinSamples = selfLearningPolicy.sourceMinSamples || {};
  const maxAutoFailureShare = Number(selfLearningPolicy.maxFailureShareForAutoApply ?? 0.45);
  const calibrationAutoGate = (item: any) => {
    const sourceType = String(item.sourceType || item.source_type || "FORWARD_PAPER_TRADE").toUpperCase();
    const defaultMinSamples = sourceType === "MANUAL_REVIEWED" ? 35 : sourceType === "HISTORICAL_REPLAY" ? 150 : sourceType === "BACKTEST_EXPERIMENT" ? 999999 : 50;
    const minSamples = Number(sourceMinSamples[sourceType] ?? defaultMinSamples);
    const sampleCount = Number(item.sampleCount || 0);
    const missingSamples = Math.max(0, minSamples - sampleCount);
    const share = Number(item.share);
    const status = String(item.status || "").toUpperCase();
    const approvalStatus = String(item.approvalStatus || "PENDING_REVIEW").toUpperCase();
    const applicationStatus = String(item.applicationStatus || "NOT_APPLIED").toUpperCase();
    const blockers: string[] = [];
    if (status !== "SUGGESTED") blockers.push(status === "LOW_SAMPLE" ? "제안 표본 부족" : "제안 조건 미충족");
    if (missingSamples > 0) blockers.push(`자동 적용 표본 ${missingSamples.toLocaleString("ko-KR")}건 부족`);
    if (Number.isFinite(share) && Number.isFinite(maxAutoFailureShare) && share > maxAutoFailureShare) {
      blockers.push(`실패 비중 ${fmtRate(share)} > 자동 상한 ${fmtRate(maxAutoFailureShare)}`);
    }
    if (approvalStatus !== "APPROVED") blockers.push(approvalStatus === "REJECTED" ? "승인 반려" : "승인 대기");
    if (applicationStatus === "APPLIED") blockers.length = 0;
    const autoReady = applicationStatus === "APPLIED" || blockers.length === 0;
    return {
      sourceType,
      minSamples,
      sampleCount,
      missingSamples,
      share,
      approvalStatus,
      applicationStatus,
      autoReady,
      blockers,
      progressPct: minSamples > 0 ? Math.max(0, Math.min(100, (sampleCount / minSamples) * 100)) : 0,
      label: applicationStatus === "APPLIED" ? "적용 완료" : autoReady ? "자동 적용 가능" : "자동 적용 보류",
      tone: applicationStatus === "APPLIED" || autoReady
        ? "bg-emerald-500/12 text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.20)]"
        : status === "SUGGESTED"
          ? "bg-amber-500/12 text-amber-200 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.20)]"
          : "bg-slate-800 text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]",
    };
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
  const entryNotTouchedSummary = entryNotTouchedData?.summary || {};
  const entryNotTouchedPatch = entryNotTouchedData?.patch || {};
  const entryNotTouchedCauses = (entryNotTouchedData?.causeCandidates || []).slice(0, 3);
  const entryNotTouchedCauseLabel = (causeType: string) => ({
    ENTRY_WINDOW_TOO_SHORT: "진입 대기 기간 부족",
    ENTRY_PRICE_TOO_CONSERVATIVE: "진입가 과도 보수",
    STRONG_TREND_RAN_WITHOUT_PULLBACK: "강한 추세 눌림 없이 이탈",
    MODE_SPECIFIC_ENTRY_MISS: "특정 모드 집중",
    MARKET_SPECIFIC_ENTRY_MISS: "특정 시장 집중",
    HORIZON_ENTRY_DEPTH_MISMATCH: "특정 horizon 집중",
    ENTRY_NOT_TOUCHED_CAUSE_UNCLEAR: "원인 불분명",
  }[causeType] || causeType);
  const marketGapSummary = marketGapData?.summary || {};
  const marketGapPatch = marketGapData?.patch || {};
  const marketGapCauses = (marketGapData?.causeCandidates || []).slice(0, 3);
  const marketGapCauseLabel = (causeType: string) => ({
    KR_MARKET_GAP_CONCENTRATION: "KR 갭 위험 집중",
    GAP_DOWN_DOMINANT: "하락 갭 비중 높음",
    MODE_SPECIFIC_GAP_FAILURE: "특정 모드 집중",
    HORIZON_SPECIFIC_GAP_FAILURE: "특정 horizon 집중",
    GAP_PATTERN_UNCLEAR: "원인 불분명",
  }[causeType] || causeType);

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

        <div className="mt-4">
          <SegmentedControl<JournalView> options={views.map((v) => ({ value: v.id, label: v.label }))} value={view} onChange={setView} className="w-full" />
          <p className="mt-1.5 text-[13px] leading-5 text-slate-400">
            {view === "journal" && "체결·평가된 개별 거래와 자동 캡처·리플레이·보정 후보입니다."}
            {view === "perf" && "누적 성과·전략 매트릭스·귀속분석·모델 자기개선 피드백입니다."}
            {view === "diag" && "추천 로직 개선을 위한 진단 지표입니다. 현재 추천 순위에는 직접 반영되지 않습니다."}
          </p>
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

      <AiPaperSurvivalPanel
        data={aiPaperData}
        preview={aiPaperPreview}
        onRefresh={load}
        onPreview={runAiPaperPreview}
        busy={loading || !!busy}
      />

      {view === "diag" && (
      <>
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
          <div className="flex shrink-0 items-center gap-2">
            <span className="font-mono text-[11px] uppercase tracking-wide text-slate-400">
              {String(scope.market).toUpperCase()} / {scope.mode} / {scope.horizon}
            </span>
            <DiagToggle id="failureAnalysis" />
          </div>
        </div>

        {diagOpen.failureAnalysis && (
        <>
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
              <div className="text-[13px] leading-5 text-slate-400">{selectedFailureNote}</div>
            </div>
            <div className="space-y-2">
              {selectedFailureRows.map((item: any) => {
                const reason = String(item.failureReason || item.reason || "UNKNOWN");
                const ratio = failureItemRatio(item);
                return (
                  <div key={reason} className="flex items-center justify-between gap-3 rounded-md bg-slate-900/70 px-3 py-2">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-200">{failureLabel(reason)}</div>
                      <div className="font-mono text-[13px] leading-5 text-slate-400">{reason}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-sm font-semibold tabular-nums text-slate-100">{item.count ?? 0}</div>
                      <div className="font-mono text-[13px] leading-5 text-slate-400">
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
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-400">분석 가능한 평가 데이터가 아직 없습니다.</div>
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
                  <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 font-mono text-[13px] leading-5 text-slate-400">
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
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-400">분해할 데이터가 아직 없습니다.</div>
              )}
            </div>
          </div>
        </div>
        </>
        )}
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
          <div className="flex shrink-0 items-center gap-2">
            <span className="font-mono text-[11px] uppercase tracking-wide text-slate-400">
              top {priorityItems.length || 0} / diagnostic only
            </span>
            <DiagToggle id="priority" />
          </div>
        </div>

        {diagOpen.priority && (
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
                    <div className="mt-1 break-all font-mono text-[13px] leading-5 text-slate-400">{item.issueType || "-"}</div>
                  </div>
                  <span className={`shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold ${severityTone(String(item.severity || "low"))}`}>
                    {severityLabel(String(item.severity || "low"))}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-center">
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[13px] leading-5 text-slate-400">근거</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-200">{evidence.count ?? 0}건</div>
                  </div>
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[13px] leading-5 text-slate-400">전체 대비</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(overallPriorityRatio(evidence))}</div>
                  </div>
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[13px] leading-5 text-slate-400">조건 충족률</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(conditionRate)}</div>
                  </div>
                  <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-1.5">
                    <div className="text-[13px] leading-5 text-slate-400">MAE</div>
                    <div className="font-mono text-xs font-semibold text-rose-300">{evidence.avgMAE == null ? "-" : `${Number(evidence.avgMAE).toFixed(2)}%`}</div>
                  </div>
                </div>
                <div className="mt-3 break-keep text-xs leading-5 text-slate-300">{item.recommendation || "-"}</div>
                <div className="mt-2 break-words rounded-md bg-cyan-500/8 px-2 py-2 text-[13px] leading-6 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.14)] [overflow-wrap:anywhere]">
                  {item.safeNextStep || "표본을 추가로 검증하세요."}
                </div>
              </div>
            );
          })}
          {!priorityItems.length && (
            <div className="rounded-lg bg-slate-950/55 px-3 py-8 text-center text-xs text-slate-400 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)] lg:col-span-3">
              개선 우선순위를 만들 평가 데이터가 아직 없습니다.
            </div>
          )}
        </div>
        )}
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
          <div className="flex shrink-0 items-center gap-2">
            <span className={`w-fit rounded-md px-2 py-1 text-[11px] font-semibold ${stopLossPatch.appliedPatch ? "bg-emerald-500/12 text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.22)]" : "bg-slate-800 text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]"}`}>
              {stopLossPatch.appliedPatch ? "패치 적용" : "진단 전용"}
            </span>
            <DiagToggle id="stopLoss" />
          </div>
        </div>

        {diagOpen.stopLoss && (
        <>
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
                <div className="text-[13px] leading-5 text-slate-400">과열 진입</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(stopLossSummary.overextensionAssociationRate)}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
                <div className="text-[13px] leading-5 text-slate-400">갭 변동</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{fmtRate(stopLossSummary.marketGapAssociationRate)}</div>
              </div>
            </div>
            <div className="mt-3 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[13px] leading-6 text-slate-400 [overflow-wrap:anywhere]">
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
                      <div className="mt-0.5 break-all font-mono text-[13px] leading-5 text-slate-400">{item.causeType || "-"}</div>
                    </div>
                    <span className="shrink-0 font-mono text-[13px] leading-5 text-slate-400">#{index + 1}</span>
                  </div>
                  <div className="mt-1 break-keep text-[13px] leading-6 text-slate-400">{item.summary || item.title || "-"}</div>
                </div>
              ))}
              {!stopLossCauses.length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-400">손절 실패 원인 후보를 만들 평가 완료 데이터가 아직 없습니다.</div>
              )}
            </div>
          </div>
        </div>
        </>
        )}
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
          <div className="flex shrink-0 items-center gap-2">
            <span className={`w-fit shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold ${entryTimingData?.appliedGuard ? "bg-emerald-500/12 text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.22)]" : "bg-slate-800 text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]"}`}>
              {entryTimingData?.appliedGuard ? "활성 적용" : entryTimingModeLabel(String(entryTimingData?.guardMode || "diagnostic_only"))}
            </span>
            <DiagToggle id="entryTiming" />
          </div>
        </div>

        {diagOpen.entryTiming && (
        <>
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
                <div className="text-[13px] leading-5 text-slate-400">손절 실패율 전</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-rose-300">{fmtRate(entryTimingReplay.stopFailureRateBefore)}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">손절 실패율 후</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-rose-300">{fmtRate(entryTimingReplay.stopFailureRateAfter)}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">평균 수익률 전</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{entryTimingReplay.avgReturnBefore == null ? "-" : `${Number(entryTimingReplay.avgReturnBefore).toFixed(2)}%`}</div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">평균 수익률 후</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{entryTimingReplay.avgReturnAfter == null ? "-" : `${Number(entryTimingReplay.avgReturnAfter).toFixed(2)}%`}</div>
              </div>
            </div>
            <div className="mt-3 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[13px] leading-6 text-slate-400 [overflow-wrap:anywhere]">
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
                      <div className="mt-0.5 break-all font-mono text-[13px] leading-5 text-slate-400">{item.reason || "-"}</div>
                    </div>
                    <span className="shrink-0 font-mono text-[13px] leading-5 text-slate-400">#{index + 1}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] tabular-nums text-slate-400">
                    <span>{item.count ?? 0}건</span>
                    <span>{fmtRate(item.ratio)}</span>
                  </div>
                </div>
              ))}
              {!entryTimingReasons.length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-400">진입 타이밍 위험 사유를 만들 평가 완료 데이터가 아직 없습니다.</div>
              )}
            </div>
            <div className="mt-3 break-words rounded-md bg-amber-500/10 px-3 py-2 text-[13px] leading-6 text-amber-100 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.16)] [overflow-wrap:anywhere]">
              다음 조치: {entryTimingData?.recommendedNextStep || "표본을 추가로 쌓은 뒤 HIGH risk 후보를 별도 검증하세요."}
            </div>
          </div>
        </div>
        </>
        )}
      </section>

      <section className="min-w-0 overflow-hidden rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Target size={16} className="shrink-0 text-cyan-300" />
              <span>진입가 미도달 진단</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              추천은 나왔지만 평가 기간 동안 진입가까지 가격이 오지 않은 거래를 진단합니다. 진입가 산식이나 entry_window_days는 아직 변경하지 않았습니다.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="w-fit shrink-0 rounded-md bg-slate-800 px-2 py-1 text-[11px] font-semibold text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]">
              진단 전용
            </span>
            <DiagToggle id="entryNotTouched" />
          </div>
        </div>

        {diagOpen.entryNotTouched && (
        <>
        <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metric("평가 완료 거래", entryNotTouchedSummary.totalEvaluatedTrades ?? 0)}
          {metric("진입가 미도달", entryNotTouchedSummary.entryNotTouchedTrades ?? 0, "text-cyan-300")}
          {metric("미도달 비율", fmtRate(entryNotTouchedSummary.entryNotTouchedRate), "text-cyan-300")}
          {metric(
            "평균 진입 대기일",
            entryNotTouchedSummary.avgEntryWindowDays == null ? "-" : `${Number(entryNotTouchedSummary.avgEntryWindowDays).toFixed(1)}일`,
          )}
        </div>

        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">진입가 미도달 vs 진입 성공 비교</div>
            <div className="grid grid-cols-2 gap-2 text-center">
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">진입 대기일 (미도달)</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-cyan-300">
                  {entryNotTouchedSummary.avgEntryWindowDays == null ? "-" : `${Number(entryNotTouchedSummary.avgEntryWindowDays).toFixed(1)}일`}
                </div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">진입 대기일 (성공 기준)</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">
                  {entryNotTouchedSummary.avgEntryWindowDaysTouchedBaseline == null ? "-" : `${Number(entryNotTouchedSummary.avgEntryWindowDaysTouchedBaseline).toFixed(1)}일`}
                </div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">진입가 깊이 (미도달)</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-cyan-300">
                  {entryNotTouchedSummary.avgEntryDepthPct == null ? "-" : `${Number(entryNotTouchedSummary.avgEntryDepthPct).toFixed(2)}%`}
                </div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">진입가 깊이 (성공 기준)</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">
                  {entryNotTouchedSummary.avgEntryDepthPctTouchedBaseline == null ? "-" : `${Number(entryNotTouchedSummary.avgEntryDepthPctTouchedBaseline).toFixed(2)}%`}
                </div>
              </div>
            </div>
            <div className="mt-3 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[13px] leading-6 text-slate-400 [overflow-wrap:anywhere]">
              현재 결과는 평가 완료 거래 기준입니다. 적용 판단: {entryNotTouchedPatch.patchReason || "분석 데이터가 아직 충분하지 않습니다."}
            </div>
          </div>

          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">주요 원인 후보</div>
            <div className="space-y-2">
              {entryNotTouchedCauses.map((item: any, index: number) => (
                <div key={`${item.causeType || index}`} className="min-w-0 rounded-md bg-slate-900/70 px-3 py-2">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-200">{entryNotTouchedCauseLabel(String(item.causeType || ""))}</div>
                      <div className="mt-0.5 break-all font-mono text-[13px] leading-5 text-slate-400">{item.causeType || "-"}</div>
                    </div>
                    <span className="shrink-0 font-mono text-[13px] leading-5 text-slate-400">#{index + 1}</span>
                  </div>
                  <div className="mt-1 break-keep text-[13px] leading-6 text-slate-400">{item.summary || item.title || "-"}</div>
                </div>
              ))}
              {!entryNotTouchedCauses.length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-400">진입가 미도달 원인 후보를 만들 평가 완료 데이터가 아직 없습니다.</div>
              )}
            </div>
          </div>
        </div>
        </>
        )}
      </section>

      <section className="min-w-0 overflow-hidden rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Zap size={16} className="shrink-0 text-orange-300" />
              <span>갭 변동 위험 진단</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              전일 종가 기준 진입가와 다음날 시가(NEXT_OPEN 체결가) 사이의 괴리로 손절에 걸린 거래를 진단합니다. 추천 제외나 진입가 산식 변경은 아직 적용하지 않았습니다.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="w-fit shrink-0 rounded-md bg-slate-800 px-2 py-1 text-[11px] font-semibold text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]">
              진단 전용
            </span>
            <DiagToggle id="marketGap" />
          </div>
        </div>

        {diagOpen.marketGap && (
        <>
        <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metric("NEXT_OPEN 거래", marketGapSummary.nextOpenTrades ?? 0)}
          {metric("갭 실패", marketGapSummary.marketGapTrades ?? 0, "text-orange-300")}
          {metric("갭 실패율", fmtRate(marketGapSummary.marketGapRate), "text-orange-300")}
          {metric(
            "평균 갭",
            marketGapSummary.avgGapPct == null ? "-" : `${Number(marketGapSummary.avgGapPct).toFixed(2)}%`,
          )}
        </div>

        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">갭 실패 vs 정상 체결 비교</div>
            <div className="grid grid-cols-2 gap-2 text-center">
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">평균 수익률 (갭 실패)</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-rose-300">
                  {marketGapSummary.avgReturnGapGroup == null ? "-" : `${Number(marketGapSummary.avgReturnGapGroup).toFixed(2)}%`}
                </div>
              </div>
              <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2">
                <div className="text-[13px] leading-5 text-slate-400">평균 수익률 (정상 체결)</div>
                <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">
                  {marketGapSummary.avgReturnNonGapGroup == null ? "-" : `${Number(marketGapSummary.avgReturnNonGapGroup).toFixed(2)}%`}
                </div>
              </div>
            </div>
            <div className="mt-3 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[13px] leading-6 text-slate-400 [overflow-wrap:anywhere]">
              현재 결과는 평가 완료 NEXT_OPEN 거래 기준입니다. 적용 판단: {marketGapPatch.patchReason || "분석 데이터가 아직 충분하지 않습니다."}
            </div>
          </div>

          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">주요 원인 후보</div>
            <div className="space-y-2">
              {marketGapCauses.map((item: any, index: number) => (
                <div key={`${item.causeType || index}`} className="min-w-0 rounded-md bg-slate-900/70 px-3 py-2">
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-200">{marketGapCauseLabel(String(item.causeType || ""))}</div>
                      <div className="mt-0.5 break-all font-mono text-[13px] leading-5 text-slate-400">{item.causeType || "-"}</div>
                    </div>
                    <span className="shrink-0 font-mono text-[13px] leading-5 text-slate-400">#{index + 1}</span>
                  </div>
                  <div className="mt-1 break-keep text-[13px] leading-6 text-slate-400">{item.summary || item.title || "-"}</div>
                </div>
              ))}
              {!marketGapCauses.length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-6 text-center text-xs text-slate-400">갭 실패 원인 후보를 만들 평가 완료 데이터가 아직 없습니다.</div>
              )}
            </div>
          </div>
        </div>
        </>
        )}
      </section>

      {/* 과열구간 진입 진단 */}
      <section className="min-w-0 overflow-hidden rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <TrendingUp size={16} className="shrink-0 text-rose-300" />
              <span>과열구간 진입 진단</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              진입 시점 RSI·MA20 이격도를 기준으로 구간별 손절 실패율·수익률을 분석합니다. 추천 액션이나 진입가 산식은 변경하지 않습니다.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="w-fit shrink-0 rounded-md bg-slate-800 px-2 py-1 text-[11px] font-semibold text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]">
              진단 전용
            </span>
            <DiagToggle id="overextended" />
          </div>
        </div>

        {diagOpen.overextended && (
        <>
        <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {metric("평가 완료", overextendedData?.summary?.totalEvaluatedTrades ?? 0)}
          {metric("RSI 데이터 보유", overextendedData?.summary?.rsiDataAvailable ?? 0, "text-sky-300")}
          {metric("평균 RSI(진입)", overextendedData?.summary?.avgRsiAtEntry == null ? "-" : Number(overextendedData.summary.avgRsiAtEntry).toFixed(1))}
          {metric("평균 MA20 이격", overextendedData?.summary?.avgMa20DistAtEntry == null ? "-" : `${Number(overextendedData.summary.avgMa20DistAtEntry).toFixed(1)}%`)}
        </div>

        <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-2">
          {/* RSI 구간별 */}
          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">RSI 구간별 손절 실패율</div>
            <div className="space-y-1.5">
              {(overextendedData?.rsiSegments || []).filter((s: any) => s.count > 0).map((seg: any, i: number) => (
                <div key={i} className="flex min-w-0 items-center justify-between gap-2 rounded-md bg-slate-900/70 px-2.5 py-1.5">
                  <span className="min-w-0 truncate text-[11px] text-slate-300">{seg.segment}</span>
                  <div className="flex shrink-0 gap-3 font-mono text-[10px]">
                    <span className="text-slate-400">n={seg.count}</span>
                    <span className={`${(seg.stopFailRate || 0) > 0.6 ? "text-rose-300" : "text-slate-300"}`}>
                      손절{((seg.stopFailRate || 0) * 100).toFixed(0)}%
                    </span>
                    <span className={`${(seg.avgReturn || 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                      {(seg.avgReturn || 0) >= 0 ? "+" : ""}{(seg.avgReturn || 0).toFixed(2)}%
                    </span>
                  </div>
                </div>
              ))}
              {!(overextendedData?.rsiSegments || []).filter((s: any) => s.count > 0).length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-4 text-center text-xs text-slate-400">RSI 데이터 없음</div>
              )}
            </div>
          </div>

          {/* 원인 후보 */}
          <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="mb-2 text-xs font-semibold text-slate-400">주요 원인 후보</div>
            <div className="space-y-2">
              {(overextendedData?.causeCandidates || []).slice(0, 3).map((item: any, i: number) => (
                <div key={i} className="min-w-0 rounded-md bg-slate-900/70 px-3 py-2">
                  <div className="text-xs font-semibold text-slate-200">{item.title || item.causeType}</div>
                  <div className="mt-0.5 break-keep text-[13px] leading-6 text-slate-400">{item.summary || "-"}</div>
                </div>
              ))}
              {!(overextendedData?.causeCandidates || []).length && (
                <div className="rounded-md bg-slate-900/70 px-3 py-4 text-center text-xs text-slate-400">과열구간 원인 후보를 만들 평가 완료 데이터가 아직 없습니다.</div>
              )}
            </div>
            <div className="mt-2 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[13px] leading-6 text-slate-400 [overflow-wrap:anywhere]">
              적용 판단: {overextendedData?.patchReason || "분석 데이터를 불러오는 중입니다."}
            </div>
          </div>
        </div>
        </>
        )}
      </section>

      {/* 수익포착 실패 진단 */}
      <section className="min-w-0 overflow-hidden rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
              <Target size={16} className="shrink-0 text-amber-300" />
              <span>수익포착 실패 진단</span>
            </div>
            <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-400">
              MFE(최대 유리 이탈)·목표 진행률 기반으로 수익 기회가 있었지만 포착에 실패한 거래를 분석합니다. 목표가·손절가 산식은 변경하지 않습니다.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="w-fit shrink-0 rounded-md bg-slate-800 px-2 py-1 text-[11px] font-semibold text-slate-300 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.16)]">
              진단 전용
            </span>
            <DiagToggle id="profitCapture" />
          </div>
        </div>

        {diagOpen.profitCapture && (() => {
          const s = profitCaptureData?.summary || {};
          return (
            <>
              <div className="mt-4 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {metric("평가 완료", s.totalEvaluatedTrades ?? 0)}
                {metric("목표가 미달(만료)", s.targetNotReached ?? 0, "text-amber-300")}
                {metric("양의MFE 후 손절", s.stopWithMfe ?? 0, "text-rose-300")}
                {metric("기회 손실 건수", s.opportunityTrades ?? 0, "text-orange-300")}
              </div>

              <div className="mt-3 grid min-w-0 gap-3 lg:grid-cols-[1fr_1fr_1fr]">
                {/* 목표가 미달 그룹 */}
                <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                  <div className="mb-2 text-xs font-semibold text-slate-400">목표가 미도달(시간만료)</div>
                  {s.targetNotReachedMetrics?.count > 0 ? (
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-400">건수</span>
                        <span className="font-mono text-slate-200">{s.targetNotReachedMetrics.count}</span>
                      </div>
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-400">평균 진행률</span>
                        <span className="font-mono text-amber-300">{s.targetNotReachedMetrics.avgTargetProgress != null ? `${(s.targetNotReachedMetrics.avgTargetProgress * 100).toFixed(1)}%` : "-"}</span>
                      </div>
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-400">평균 MFE</span>
                        <span className="font-mono text-sky-300">{s.targetNotReachedMetrics.avgMfe != null ? `+${Number(s.targetNotReachedMetrics.avgMfe).toFixed(2)}%` : "-"}</span>
                      </div>
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-400">평균 수익률</span>
                        <span className={`font-mono ${(s.targetNotReachedMetrics.avgReturn || 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                          {s.targetNotReachedMetrics.avgReturn != null ? `${Number(s.targetNotReachedMetrics.avgReturn) >= 0 ? "+" : ""}${Number(s.targetNotReachedMetrics.avgReturn).toFixed(2)}%` : "-"}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center text-xs text-slate-400 py-3">데이터 없음</div>
                  )}
                </div>

                {/* 양의 MFE 후 손절 그룹 */}
                <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                  <div className="mb-2 text-xs font-semibold text-slate-400">상승 후 되돌림 손절</div>
                  {s.stopWithMfeMetrics?.count > 0 ? (
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-400">건수</span>
                        <span className="font-mono text-slate-200">{s.stopWithMfeMetrics.count}</span>
                      </div>
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-400">평균 MFE</span>
                        <span className="font-mono text-sky-300">{s.stopWithMfeMetrics.avgMfe != null ? `+${Number(s.stopWithMfeMetrics.avgMfe).toFixed(2)}%` : "-"}</span>
                      </div>
                      <div className="flex justify-between text-[11px]">
                        <span className="text-slate-400">평균 수익률</span>
                        <span className={`font-mono ${(s.stopWithMfeMetrics.avgReturn || 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                          {s.stopWithMfeMetrics.avgReturn != null ? `${Number(s.stopWithMfeMetrics.avgReturn) >= 0 ? "+" : ""}${Number(s.stopWithMfeMetrics.avgReturn).toFixed(2)}%` : "-"}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center text-xs text-slate-400 py-3">데이터 없음</div>
                  )}
                </div>

                {/* 원인 후보 */}
                <div className="min-w-0 rounded-lg bg-slate-950/55 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                  <div className="mb-2 text-xs font-semibold text-slate-400">주요 원인 후보</div>
                  <div className="space-y-2">
                    {(profitCaptureData?.causeCandidates || []).slice(0, 2).map((item: any, i: number) => (
                      <div key={i} className="min-w-0 rounded-md bg-slate-900/70 px-3 py-2">
                        <div className="text-xs font-semibold text-slate-200">{item.title || item.causeType}</div>
                        <div className="mt-0.5 line-clamp-3 break-keep text-[13px] leading-6 text-slate-400">{item.summary || "-"}</div>
                      </div>
                    ))}
                    {!(profitCaptureData?.causeCandidates || []).length && (
                      <div className="rounded-md bg-slate-900/70 px-3 py-4 text-center text-xs text-slate-400">수익포착 원인 후보 없음</div>
                    )}
                  </div>
                </div>
              </div>
              <div className="mt-2 break-words rounded-md bg-slate-900/70 px-3 py-2 text-[13px] leading-6 text-slate-400 [overflow-wrap:anywhere]">
                적용 판단: {profitCaptureData?.patchReason || "분석 데이터를 불러오는 중입니다."}
              </div>
            </>
          );
        })()}
      </section>

      {/* 성과 게이트 진단 */}
      <section className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">성과 게이트 진단</h2>
          <div className="flex shrink-0 items-center gap-2">
            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              perfGateData?.gateStatus === "OK" ? "bg-emerald-900/60 text-emerald-300" :
              perfGateData?.gateStatus === "COVERAGE_GAP" ? "bg-amber-900/60 text-amber-300" :
              perfGateData?.gateStatus === "CAUTION_LOW_SAMPLE" ? "bg-sky-900/60 text-sky-300" :
              perfGateData?.gateStatus === "BLOCKED_LOW_WIN_RATE" ? "bg-rose-900/60 text-rose-300" :
              "bg-slate-800 text-slate-400"
            }`}>
              {perfGateData?.gateStatus || "로딩 중"}
            </span>
            <DiagToggle id="perfGate" />
          </div>
        </div>
        {diagOpen.perfGate && (
        <>
        {perfGateData?.reason && (
          <div className="mb-3 rounded-md bg-slate-950/60 px-3 py-2 text-[13px] leading-6 text-slate-400">{perfGateData.reason}</div>
        )}
        <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">전체 완료</div>
            <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{perfGateData?.completed ?? "-"}</div>
          </div>
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">의미있는 완료</div>
            <div className={`mt-1 font-mono text-xs font-semibold tabular-nums ${(perfGateData?.meaningfulCompleted ?? 0) < 10 ? "text-amber-300" : "text-emerald-300"}`}>
              {perfGateData?.meaningfulCompleted ?? "-"}
            </div>
          </div>
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">플레이스홀더</div>
            <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-400">{perfGateData?.placeholderCount ?? "-"}</div>
          </div>
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">차단 여부</div>
            <div className={`mt-1 font-mono text-xs font-semibold tabular-nums ${perfGateData?.isTradeBlocked ? "text-rose-300" : "text-emerald-300"}`}>
              {perfGateData?.isTradeBlocked == null ? "-" : perfGateData.isTradeBlocked ? "차단" : "통과"}
            </div>
          </div>
        </div>
        <div className="mt-3 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">전체 승률</div>
            <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{perfGateData?.winRate != null ? `${perfGateData.winRate}%` : "-"}</div>
          </div>
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">의미있는 승률</div>
            <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{perfGateData?.meaningfulWinRate != null ? `${perfGateData.meaningfulWinRate}%` : "-"}</div>
          </div>
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">전체 평균수익률</div>
            <div className={`mt-1 font-mono text-xs font-semibold tabular-nums ${(perfGateData?.avgReturn ?? 0) < 0 ? "text-rose-300" : "text-emerald-300"}`}>
              {perfGateData?.avgReturn != null ? `${perfGateData.avgReturn}%` : "-"}
            </div>
          </div>
          <div className="min-w-0 rounded-md bg-slate-900/70 px-2 py-2 text-center">
            <div className="text-[13px] leading-5 text-slate-400">의미있는 평균수익률</div>
            <div className={`mt-1 font-mono text-xs font-semibold tabular-nums ${(perfGateData?.meaningfulAvgReturn ?? 0) < 0 ? "text-rose-300" : "text-emerald-300"}`}>
              {perfGateData?.meaningfulAvgReturn != null ? `${perfGateData.meaningfulAvgReturn}%` : "-"}
            </div>
          </div>
        </div>
        </>
        )}
      </section>
      </>
      )}

      {view === "journal" && (
      <>
      <section className="rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <ShieldCheck size={16} className="text-emerald-300" />
            <span>실전 신호 게이트</span>
          </div>
          {highConv ? (
            <span className={`rounded px-2 py-0.5 font-mono text-[11px] ${highConv.favorableRegime ? "bg-emerald-500/12 text-emerald-200" : "bg-red-500/12 text-red-200"}`}>
              {highConv.marketRegimeLabel || highConv.marketRegime}{highConv.favorableRegime ? " · 실전 ON" : " · 실전 OFF"}
            </span>
          ) : (
            <span className="font-mono text-[11px] text-slate-400">신호 없음</span>
          )}
        </div>
        <p className="mt-1 max-w-3xl text-[13px] leading-5 text-slate-400">
          앱이 지던 이유 = 전부 거래(실측 −1.92%/거래). 실측상 (+)인 유일 구성(강세장 + finalScore≥84)만 실전으로 냅니다. 그 외엔 현금 보존.
        </p>
        {highConv?.provenEdge && (
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {metric("실전 게이트 실측", `+${highConv.provenEdge.avgNetPct}%`, "text-emerald-300")}
            {metric("게이트 승률", `${highConv.provenEdge.winRate}%`)}
            {metric("전부 거래 시", `${highConv.provenEdge.baselineAllTrades}%`, "text-red-300")}
            {metric("실측 표본", `${highConv.provenEdge.realTrades}건`)}
          </div>
        )}
        {highConv?.forwardProof && (
          <div className="mt-2 rounded-md bg-slate-950/50 px-3 py-1.5 font-mono text-[10px] text-slate-400 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            forward 실적(게이트만 실제 정산): {highConv.forwardProof.settled ?? 0}건
            {(highConv.forwardProof.settled ?? 0) > 0
              ? ` · 평균 ${highConv.forwardProof.avgNetPct}% · 승률 ${highConv.forwardProof.winRate}%`
              : " — 아직 없음(실전 신호 뜨면 자동 축적, 이게 +0.72% 진짜 검증)"}
            {` · 대기 ${highConv.forwardProof.pending ?? 0}건`}
          </div>
        )}
        {highConv && highConv.actionableCount > 0 ? (
          <div className="mt-3 space-y-1.5">
            {(highConv.candidates || []).filter((c: any) => c.highConviction).slice(0, 8).map((c: any) => (
              <div key={c.symbol} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-emerald-500/8 px-3 py-2 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.2)]">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-slate-100">{c.name || c.symbol}</span>
                  <span className="font-mono text-[13px] leading-5 text-slate-400">{c.symbol}</span>
                  {c.supplySignal && <span className="rounded bg-sky-500/12 px-1.5 py-0.5 text-[9px] text-sky-200">{c.supplySignal}</span>}
                </div>
                <div className="flex items-center gap-3 font-mono text-[10px]">
                  <span className="text-slate-400">fs {c.finalScore}</span>
                  <span className="font-semibold text-emerald-300">실전 매수</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 rounded-lg bg-amber-500/8 px-3 py-4 text-center text-xs leading-5 text-amber-200 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.16)]">
            {highConv?.favorableRegime === false
              ? `${highConv.marketRegimeLabel || "현재 장세"} — 실전 매수 없음. 현금 보존이 정답(나쁜 장세 회피로 −1.9% 손실 차단).`
              : "실전 게이트 통과 종목 없음 — 관찰만."}
          </div>
        )}
      </section>

      <section className="rounded-lg bg-slate-900/40 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)] sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-300">
            <Activity size={16} className="text-sky-300" />
            <span>연구 중 — 아직 실전 아님</span>
          </div>
          <span className="rounded bg-sky-500/10 px-2 py-0.5 font-mono text-[10px] text-sky-300">PAPER ONLY</span>
        </div>
        <p className="mt-1 max-w-3xl text-[13px] leading-5 text-slate-400">
          위 실전 게이트와 별개입니다. 딥데이터(2014-2026) train/OOS 백테스트로 발굴된 후보지만, 아직 라이브 forward 증거가 쌓이지 않아 실전으로 안 냅니다.
          paper 계좌에서 성과가 쌓여 승격 기준(n≥12·PF&gt;1·승률≥50%)을 넘으면 위 실전 게이트로 이동합니다.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg bg-slate-950/40 px-3 py-2.5 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-semibold text-slate-300">주도주 돌파 (미장 배경 게이트)</span>
              <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${researchLeader?.usBackdropFavorable ? "bg-emerald-500/12 text-emerald-300" : "bg-slate-700/40 text-slate-400"}`}>
                {researchLeader ? (researchLeader.usBackdropFavorable ? "미장 상승 · 게이트 열림" : "미장 하락 · 게이트 닫힘") : "데이터 없음"}
              </span>
            </div>
            {researchLeader?.candidates?.length ? (
              <div className="mt-2 space-y-1">
                {researchLeader.candidates.slice(0, 5).map((c: any) => (
                  <div key={c.symbol} className="flex items-center justify-between font-mono text-[13px] leading-5 text-slate-400">
                    <span>{c.symbol}</span>
                    <span>진입 {c.entry} · RR {c.rrRatio}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-[13px] leading-5 text-slate-400">
                {researchLeader && !researchLeader.usBackdropFavorable
                  ? "미장이 하락추세라 오늘은 후보 없음(검증된 대로 정상 동작)."
                  : "오늘 조건에 맞는 주도주 없음."}
              </p>
            )}
          </div>
          <div className="rounded-lg bg-slate-950/40 px-3 py-2.5 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            <div className="flex items-center justify-between text-[11px]">
              <span className="font-semibold text-slate-300">상대강도 렌즈</span>
              <span className="rounded bg-slate-700/40 px-1.5 py-0.5 font-mono text-[13px] leading-5 text-slate-400">
                {researchRs?.regime || "-"}{researchRs?.status === "BEAR_DEFENSIVE" ? " · 방어모드" : ""}
              </span>
            </div>
            {researchRs?.status === "BEAR_DEFENSIVE" ? (
              <div className="mt-2 space-y-1">
                <p className="text-[13px] leading-5 text-amber-200">약세장 — 저변동 방어주로 로테이션(낙폭 절반 실측)</p>
                {(researchRs.defensiveHolds || []).slice(0, 5).map((c: any) => (
                  <div key={c.symbol} className="flex items-center justify-between font-mono text-[13px] leading-5 text-slate-400">
                    <span>{c.symbol}</span>
                    <span>변동성 {c.vol60Pct}%</span>
                  </div>
                ))}
              </div>
            ) : researchRs?.leaders?.length ? (
              <div className="mt-2 space-y-1">
                {researchRs.leaders.slice(0, 5).map((c: any) => (
                  <div key={c.symbol} className="flex items-center justify-between font-mono text-[13px] leading-5 text-slate-400">
                    <span>{c.symbol}</span>
                    <span>RS60 {c.rs60Pct}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-[13px] leading-5 text-slate-400">데이터 없음.</p>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Zap size={16} className="text-violet-300" />
            <span>AI 스마트 순위 · 선별 두뇌</span>
          </div>
          {smartRank ? (
            <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
              <span className={`rounded px-2 py-0.5 ${smartRank.marketRegime === "BEAR" ? "bg-red-500/12 text-red-200" : smartRank.marketRegime === "BULL" ? "bg-emerald-500/12 text-emerald-200" : "bg-amber-500/12 text-amber-200"}`}>
                {smartRank.marketRegime === "BEAR" ? "약세장" : smartRank.marketRegime === "BULL" ? "강세장" : "횡보장"}
              </span>
              <span className="rounded bg-violet-500/12 px-2 py-0.5 text-violet-200">{smartRank.featureCount ?? 14}개 신호 동시분석</span>
            </div>
          ) : (
            <span className="font-mono text-[11px] text-slate-400">순위 데이터 없음</span>
          )}
        </div>
        <p className="mt-1 max-w-3xl text-[13px] leading-5 text-slate-400">
          14개 신호를 동시에 저울질해 전 종목 순위를 매기는 선별 모델(사람은 못 하는 다중신호 비교). 아래 실증 성적은 안 본 구간(OOS) 검증치입니다.
        </p>
        {smartRank?.provenEdge && (
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {metric("상위20% 실손익", `${(smartRank.provenEdge.topQuintileNetPct ?? 0) >= 0 ? "+" : ""}${smartRank.provenEdge.topQuintileNetPct}%`, (smartRank.provenEdge.topQuintileNetPct ?? 0) >= 0 ? "text-emerald-300" : "text-red-300")}
            {metric("상-하위 스프레드", `${(smartRank.provenEdge.spreadPct ?? 0) >= 0 ? "+" : ""}${smartRank.provenEdge.spreadPct}%p`, "text-violet-300")}
            {metric("횡보장 상위20%", smartRank.provenEdge.topQuintileByRegime?.SIDE != null ? `${smartRank.provenEdge.topQuintileByRegime.SIDE >= 0 ? "+" : ""}${smartRank.provenEdge.topQuintileByRegime.SIDE}%` : "-", (smartRank.provenEdge.topQuintileByRegime?.SIDE ?? 0) >= 0 ? "text-emerald-300" : "text-red-300")}
            {metric("IC (예측 상관)", String(smartRank.provenEdge.ic ?? "-"))}
          </div>
        )}
        {smartRank && Array.isArray(smartRank.candidates) && smartRank.candidates.length > 0 ? (
          <div className="mt-3 space-y-1.5">
            {smartRank.candidates.slice(0, 8).map((c: any, idx: number) => (
              <div key={c.symbol} className={`flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 ${c.actionable ? "bg-emerald-500/8 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.18)]" : "bg-slate-950/50 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]"}`}>
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="font-mono text-[11px] text-violet-300">#{idx + 1}</span>
                  <span className="text-sm font-semibold text-slate-100">{c.name || c.symbol}</span>
                  <span className="font-mono text-[13px] leading-5 text-slate-400">{c.symbol}</span>
                  {c.supplySignal && <span className="rounded bg-sky-500/12 px-1.5 py-0.5 text-[9px] text-sky-200">{c.supplySignal}</span>}
                </div>
                <div className="flex items-center gap-3 font-mono text-[13px] leading-5 text-slate-400">
                  <span>점수 {c.modelScore}</span>
                  <span>RSI {c.rsi14}</span>
                  <span className={c.actionable ? "text-emerald-300" : "text-slate-400"}>{c.actionable ? "실행가능" : "caution"}</span>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 rounded-lg bg-slate-950/55 px-3 py-6 text-center text-xs text-slate-400 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            {smartRank?.status === "EMPTY" ? "스마트 순위 미생성 — build_smart_rank_kr.py 실행 필요." : "순위 후보가 없습니다."}
          </div>
        )}
        {smartRank?.marketRegime === "BEAR" && (
          <div className="mt-2 rounded-md bg-amber-500/8 px-3 py-1.5 text-[13px] leading-5 text-amber-200/80 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.14)]">
            ⚠ 약세장은 상위 픽도 OOS에서 (−)였습니다 — 순위는 참고만, 실행은 억제(caution).
          </div>
        )}
      </section>

      <section className="rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Target size={16} className="text-cyan-300" />
            <span>레짐 렌즈 · 자가보정</span>
          </div>
          {lensData ? (
            <div className="flex flex-wrap items-center gap-1.5 font-mono text-[11px]">
              <span className={`rounded px-2 py-0.5 ${lensData.marketRegime === "BEAR" ? "bg-red-500/12 text-red-200" : lensData.marketRegime === "BULL" ? "bg-emerald-500/12 text-emerald-200" : "bg-amber-500/12 text-amber-200"}`}>
                {lensData.marketRegime === "BEAR" ? "약세장" : lensData.marketRegime === "BULL" ? "강세장" : "횡보장"}
                {typeof lensData.breadthAboveMa60 === "number" ? ` · breadth ${lensData.breadthAboveMa60.toFixed(2)}` : ""}
              </span>
              <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">활성 렌즈: {lensData.activeLens === "BOTTOM_CATCH" ? "저점반등" : "돌파"}</span>
              {lensData.selfCalibrated && <span className="rounded bg-cyan-500/12 px-2 py-0.5 text-cyan-200">자가보정 ON</span>}
              {typeof lensData.liveSamplesTotal === "number" && (
                <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-400">
                  {lensData.liveSamplesTotal > 0 ? `라이브 실측 ${lensData.liveSamplesTotal}건` : "백테스트 prior 기반"}
                </span>
              )}
            </div>
          ) : (
            <span className="font-mono text-[11px] text-slate-400">렌즈 데이터 없음</span>
          )}
        </div>
        <p className="mt-1 max-w-3xl text-[13px] leading-5 text-slate-400">
          장세별 셋업(약세=저점반등, 강세·횡보=돌파)을 매매일지 실측으로 자가보정합니다. ACTIVE(실행가능)만 매수 후보이며, 최근 실측이 무너진 셋업은 자동 차단(SUPPRESSED)됩니다.
        </p>
        {lensData && Array.isArray(lensData.candidates) && lensData.candidates.length > 0 ? (
          <div className="mt-3 space-y-2">
            {lensData.candidates.slice(0, 8).map((c: any) => (
              <div key={c.symbol} className={`flex flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2 ${c.actionable ? "bg-emerald-500/8 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.18)]" : "bg-slate-950/50 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]"}`}>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-100">{c.name || c.symbol}</span>
                    <span className="font-mono text-[13px] leading-5 text-slate-400">{c.symbol}</span>
                    <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${c.setup === "BOTTOM_CATCH" ? "bg-indigo-500/15 text-indigo-200" : "bg-sky-500/15 text-sky-200"}`}>{c.setup === "BOTTOM_CATCH" ? "저점반등" : "돌파"}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[13px] leading-5 text-slate-400">
                    <span>진입 {fmtNum(c.entryRef)}</span>
                    <span className="text-red-300">손절 {fmtNum(c.stop)}</span>
                    <span className="text-emerald-300">목표 {fmtNum(c.target)}</span>
                    <span>RR {c.rrRatio ?? "-"}</span>
                    <span>RSI {c.rsi14}</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`font-mono text-[11px] font-semibold ${c.actionable ? "text-emerald-300" : "text-slate-400"}`}>
                    {c.actionable ? "실행가능" : "차단"}
                  </div>
                  <div className="font-mono text-[13px] leading-5 text-slate-400">
                    {c.calibrationGate}{c.actionable && c.sizeMultiplier ? ` · size ${Number(c.sizeMultiplier).toFixed(2)}` : ""}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 rounded-lg bg-slate-950/55 px-3 py-6 text-center text-xs text-slate-400 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            {lensData?.status === "EMPTY" ? "렌즈 후보 리포트 미생성 — 파이프라인(build_lens_journal→calibration→screen) 실행 필요." : "현재 레짐에서 실행가능한 렌즈 후보가 없습니다."}
          </div>
        )}
        {lensData?.disclaimer && (
          <div className="mt-2 rounded-md bg-amber-500/8 px-3 py-1.5 text-[13px] leading-5 text-amber-200/80 shadow-[inset_0_0_0_1px_rgba(251,191,36,0.14)]">
            ⚠ {lensData.disclaimer}
          </div>
        )}
      </section>

      <section className="rounded-lg bg-slate-900/55 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)] sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <TrendingUp size={16} className="text-emerald-300" />
            <span>손익 비대칭</span>
          </div>
          <span className="font-mono text-[11px] text-slate-400">
            {asymmetry ? `평가 ${asymmetry.n}건 · 승 ${asymmetry.winCount} / 패 ${asymmetry.lossCount}` : "평가 데이터 없음"}
          </span>
        </div>
        <p className="mt-1 max-w-3xl text-[13px] leading-5 text-slate-400">
          손실↓·수익↑ 비대칭이 이 앱의 목표입니다. Payoff(손익비)·Profit Factor가 1을 넘고 기대손익이 (+)여야 엣지가 있습니다.
        </p>
        {asymmetry ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {metric("기대손익/거래", `${asymmetry.expectancy >= 0 ? "+" : ""}${asymmetry.expectancy.toFixed(2)}%`, asymmetry.expectancy >= 0 ? "text-emerald-300" : "text-red-300")}
            {metric("Profit Factor", asymmetry.profitFactor == null ? "-" : asymmetry.profitFactor.toFixed(2), (asymmetry.profitFactor ?? 0) >= 1 ? "text-emerald-300" : "text-red-300")}
            {metric("Payoff(손익비)", asymmetry.payoff == null ? "-" : asymmetry.payoff.toFixed(2), (asymmetry.payoff ?? 0) >= 1 ? "text-emerald-300" : "text-amber-300")}
            {metric("평균 이익", asymmetry.avgWin == null ? "-" : `+${asymmetry.avgWin.toFixed(2)}%`, "text-emerald-300")}
            {metric("평균 손실", asymmetry.avgLoss == null ? "-" : `${asymmetry.avgLoss.toFixed(2)}%`, "text-red-300")}
            {metric("손익 승률", asymmetry.winRate == null ? "-" : `${asymmetry.winRate.toFixed(1)}%`)}
          </div>
        ) : (
          <div className="mt-3 rounded-lg bg-slate-950/55 px-3 py-6 text-center text-xs text-slate-400 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
            평가 완료(손익 확정) 거래가 쌓이면 손익 비대칭 지표가 표시됩니다.
          </div>
        )}
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">최근 일지</h2>
            <span className="font-mono text-xs tabular-nums text-slate-400">{loading ? "loading" : `${trades.length} rows`}</span>
          </div>
          <div className="mb-3">
            <SegmentedControl<ListSource> options={listSources.map((s) => ({ value: s.id, label: s.label }))} value={listSource} onChange={setListSource} className="w-full" />
          </div>
          {/* 모바일 카드 뷰 */}
          <div className="space-y-2.5 sm:hidden">
            {trades.slice(0, 80).map((item) => (
              <div key={item.journal_id} className="rounded-xl bg-slate-950/50 p-3 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-semibold text-slate-100">{displayName(item) || item.symbol}</div>
                    <div className="font-mono text-[11px] text-slate-400">{item.symbol}</div>
                  </div>
                  <span className={`inline-flex shrink-0 whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-semibold ${toneForOutcome(String(item.outcome || "PENDING"))}`}>
                    {outcomeLabel(String(item.outcome || "PENDING"))}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-400">
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
                    <div className="text-[13px] leading-5 text-slate-400">PnL</div>
                    <div className={`font-mono text-xs font-semibold tabular-nums ${Number(item.net_pnl_pct) >= 0 ? "text-emerald-300" : "text-red-300"}`}>{fmtNum(item.net_pnl_pct, "%")}</div>
                  </div>
                  <div className="rounded-lg bg-slate-900/60 px-2 py-1.5">
                    <div className="text-[13px] leading-5 text-slate-400">MFE</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-300">{fmtNum(item.mfe_pct, "%")}</div>
                  </div>
                  <div className="rounded-lg bg-slate-900/60 px-2 py-1.5">
                    <div className="text-[13px] leading-5 text-slate-400">MAE</div>
                    <div className="font-mono text-xs font-semibold tabular-nums text-slate-300">{fmtNum(item.mae_pct, "%")}</div>
                  </div>
                </div>
                {item.failure_reason && (
                  <div className="mt-2 font-mono text-[11px] text-amber-300">
                    {item.failure_reason}
                    {item.secondary_tags && <span className="ml-1 text-slate-400">{item.secondary_tags}</span>}
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
              <div className="py-10 text-center text-sm text-slate-400">아직 가상 매매일지가 없습니다.</div>
            )}
          </div>

          {/* 데스크톱 테이블 뷰 */}
          <div className="hidden overflow-x-auto sm:block">
            <table className="w-full min-w-[900px] text-left text-xs">
              <thead className="text-slate-400">
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
                      <div className="font-mono text-[11px] text-slate-400">{item.symbol}</div>
                    </td>
                    <td className="py-3 pr-3">
                      <div className="font-mono text-[11px] uppercase text-slate-400">
                        {String(item.market || "").toUpperCase()} / {MODE_SHORT[item.mode] ?? item.mode} / {HORIZON_SHORT[item.horizon] ?? item.horizon}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-400">{item.as_of_date}</div>
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
                      {item.secondary_tags && <div className="mt-0.5 text-slate-400">{item.secondary_tags}</div>}
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
                    <td colSpan={9} className="py-10 text-center text-sm text-slate-400">아직 가상 매매일지가 없습니다.</td>
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
            <p className="mt-2 text-xs leading-5 text-slate-400">Synthetic cutoff replay v1입니다. 후보 생성은 입력 날짜까지의 OHLCV만 사용하고, 평가는 저장 후 별도로 수행합니다. 과거 백필은 선택 날짜부터 20일 간격으로 최대 24회 실행합니다.</p>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-slate-200">유사 장세 복기</h2>
              <span className="font-mono text-[11px] text-slate-400">{analogData.benchmarkSymbol || "-"}</span>
            </div>
            {analogData.summary && (
              <div className="mb-3 grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[13px] leading-5 text-slate-400">평가 수</div>
                  <div className="font-mono text-sm font-semibold text-slate-200">{analogData.summary.evaluated ?? 0}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[13px] leading-5 text-slate-400">평균 PnL</div>
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
                    <span className="font-mono text-[11px] text-slate-400">sim {Math.round(Number(item.similarity || 0) * 100)}%</span>
                  </div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{item.lesson || "-"}</div>
                </div>
              ))}
              {!(analogData.items || []).length && (
                <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-400">유사 장세 replay 결과가 아직 없습니다.</div>
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
              {!topFailures.length && <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-400">평가 완료된 실패패턴이 아직 없습니다.</div>}
            </div>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-200">보정 후보</h2>
                <p className="mt-1 text-xs leading-5 text-slate-400">
                  개선사항은 자동 적용 게이트를 통과해야 매매 규칙에 반영됩니다.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-right text-[11px]">
                <div className="rounded-md bg-slate-950/60 px-2 py-1.5 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                  <div className="text-slate-400">자동 가능</div>
                  <div className="font-mono tabular-nums text-emerald-200">{selfLearningData?.eligibleAutoCount || 0}</div>
                </div>
                <div className="rounded-md bg-slate-950/60 px-2 py-1.5 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                  <div className="text-slate-400">표본 부족</div>
                  <div className="font-mono tabular-nums text-amber-200">{selfLearningData?.lowSampleCount || 0}</div>
                </div>
              </div>
            </div>
            <div className="space-y-2">
              {suggestions.slice(0, 6).map((item, index) => {
                const gate = calibrationAutoGate(item);
                return (
                <div key={`${item.reason || item.status}-${index}`} className="rounded-lg bg-slate-950/60 px-3 py-2 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.08)]">
                  <div className="flex items-center justify-between gap-3">
                    <span className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${gate.tone}`}>{gate.label}</span>
                    <span className="font-mono text-[11px] tabular-nums text-slate-400">
                      {gate.approvalStatus} · {gate.sampleCount.toLocaleString("ko-KR")} / {gate.minSamples.toLocaleString("ko-KR")}
                    </span>
                  </div>
                  <div className="mt-1 text-xs leading-5 text-slate-300">{item.message || item.reason || "-"}</div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className={`h-full rounded-full ${gate.autoReady ? "bg-emerald-400" : "bg-amber-400"}`}
                      style={{ width: `${gate.applicationStatus === "APPLIED" ? 100 : gate.progressPct}%` }}
                    />
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="rounded bg-slate-900 px-2 py-1 font-mono text-[10px] tabular-nums text-slate-400">
                      실패비중 {Number.isFinite(gate.share) ? fmtRate(gate.share) : "-"}
                    </span>
                    <span className="rounded bg-slate-900 px-2 py-1 font-mono text-[13px] leading-5 text-slate-400">{gate.sourceType}</span>
                    {gate.blockers.map((blocker) => (
                      <span key={blocker} className="rounded bg-amber-500/10 px-2 py-1 text-[13px] leading-5 text-amber-200">
                        {blocker}
                      </span>
                    ))}
                    {gate.autoReady && (
                      <span className="rounded bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-200">
                        적용 조건 충족
                      </span>
                    )}
                  </div>
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
                );
              })}
              {!suggestions.length && <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-400">보정 후보가 아직 없습니다.</div>}
            </div>
          </div>

          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-slate-200">적용 대기</h2>
              <span className="font-mono text-[11px] tabular-nums text-slate-400">{approvedSuggestions.length} approved</span>
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
                  <div className="mt-1 font-mono text-[11px] text-slate-400">{item.market} / {item.mode} / {item.horizon} / {item.sourceType}</div>
                </div>
              ))}
              {!approvedSuggestions.length && <div className="rounded-lg bg-slate-950/60 px-3 py-6 text-center text-xs text-slate-400">승인됐지만 아직 적용되지 않은 보정 후보가 없습니다.</div>}
            </div>
          </div>
        </div>
      </section>

      </>
      )}

      {view === "perf" && (
      <>
      {/* ── 성과 대시보드 ─────────────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-violet-400" />
          <h2 className="text-sm font-semibold text-slate-200">성과 대시보드</h2>
          {perfData && <span className="font-mono text-[11px] text-slate-400">{perfData.summary?.count ?? 0}건 평가 완료</span>}
        </div>

        {!perfData || (perfData.summary?.count ?? 0) === 0 ? (
          <div className="rounded-lg bg-slate-900/50 p-6 text-center text-sm text-slate-400 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
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
                  <div className="text-[11px] text-slate-400">{label}</div>
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
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-400">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.regimeTransition as any[]).map((row, i) => {
                  const [regEntry, regExit] = String(row.transition ?? "").split("→").map((s: string) => s.trim());
                  const winCount = Math.round((row.count ?? 0) * (row.winRate ?? 0));
                  const lossCount = (row.count ?? 0) - winCount;
                  return (
                    <div key={i} className="flex items-center justify-between gap-2 rounded-md bg-slate-950/50 px-3 py-1.5">
                      <span className="font-mono text-[11px] text-slate-400">
                        {regEntry ?? "-"} → {regExit ?? "-"}
                      </span>
                      <div className="flex gap-3">
                        <span className="font-mono text-[11px] text-emerald-300">W:{winCount}</span>
                        <span className="font-mono text-[11px] text-red-300">L:{lossCount}</span>
                        <span className="font-mono text-[11px] text-slate-400">n:{row.count ?? 0}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 신호 신뢰도 × 실패 분류 */}
          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">신호 신뢰도 × 실패 태그</h3>
            {(analyticsData.confidenceBreakdown || []).length === 0 ? (
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-400">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.confidenceBreakdown as any[]).map((row, i) => {
                  const topFailure = Object.keys(row.failureCounts || {})[0] ?? "-";
                  return (
                    <div key={i} className="flex items-center justify-between gap-2 rounded-md bg-slate-950/50 px-3 py-1.5">
                      <span className="font-mono text-[11px] text-slate-400">
                        {row.signalConfidence ?? "-"}
                      </span>
                      <div className="flex gap-3">
                        <span className="font-mono text-[11px] text-amber-300">{topFailure}</span>
                        <span className="font-mono text-[11px] text-slate-400">n:{row.total ?? 0}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 진입 방식 비교 */}
          <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">진입 방식 비교</h3>
            {(analyticsData.entryTypeComparison || []).length === 0 ? (
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-400">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.entryTypeComparison as any[]).map((row, i) => (
                  <div key={i} className="rounded-md bg-slate-950/50 px-3 py-2">
                    <div className="font-mono text-[11px] text-slate-200">{row.entryType ?? "-"}</div>
                    <div className="mt-1 flex gap-3">
                      <span className="font-mono text-[11px] text-emerald-300">승률 {row.winRate != null ? `${(row.winRate * 100).toFixed(0)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-400">평균PnL {row.avgPnlPct != null ? `${Number(row.avgPnlPct).toFixed(2)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-400">n:{row.count ?? 0}</span>
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
              <div className="rounded-lg bg-slate-950/60 py-6 text-center text-xs text-slate-400">데이터 없음</div>
            ) : (
              <div className="space-y-1">
                {(analyticsData.sourceComparison as any[]).map((row, i) => (
                  <div key={i} className="rounded-md bg-slate-950/50 px-3 py-2">
                    <div className={`font-mono text-[11px] ${row.sourceType === "MANUAL_REVIEWED" ? "text-emerald-300" : "text-slate-200"}`}>{row.sourceType ?? "-"}</div>
                    <div className="mt-1 flex gap-3">
                      <span className="font-mono text-[11px] text-emerald-300">승률 {row.winRate != null ? `${(row.winRate * 100).toFixed(0)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-400">평균PnL {row.avgPnlPct != null ? `${Number(row.avgPnlPct).toFixed(2)}%` : "-"}</span>
                      <span className="font-mono text-[11px] text-slate-400">n:{row.count ?? 0}</span>
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
          {attrData && <span className="font-mono text-[11px] text-slate-400">{attrData.count ?? 0}건 분석</span>}
        </div>

        {!attrData || (attrData.count ?? 0) === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-700 py-8 text-center text-xs text-slate-400">
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
                    <div className="text-[13px] leading-5 text-slate-400">{label}</div>
                    <div className={`mt-1 font-mono text-sm font-bold ${tone || "text-slate-200"}`}>{value}{unit ? ` ${unit}` : ""}</div>
                  </div>
                ))}
              </div>
              {(attrData.evAccuracy?.evQuartileBuckets?.length ?? 0) > 0 && (
                <div className="mt-3">
                  <div className="mb-1.5 text-[13px] leading-5 text-slate-400">EV 사분위별 실수익</div>
                  <div className="flex gap-2">
                    {attrData.evAccuracy.evQuartileBuckets.map((b: any) => (
                      <div key={b.label} className="flex-1 rounded-lg bg-slate-800/60 px-2 py-1.5 text-center">
                        <div className="text-[9px] text-slate-400">{b.label}</div>
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
                        <tr className="text-[13px] leading-5 text-slate-400">
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
          <span className="font-mono text-[11px] text-slate-400">
            {attrData?.regression?.status || "LOW_SAMPLE"}
            {attrData?.regression?.r2 != null ? ` · R2 ${attrData.regression.r2}` : ""}
          </span>
        </div>
        {!attrData || attrData.regression?.status !== "OK" ? (
          <div className="rounded-lg border border-dashed border-slate-700 py-6 text-center text-xs text-slate-400">
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
            {effData && <span className="font-mono text-[11px] text-slate-400">{effData.filled ?? 0}/{effData.total ?? 0} filled</span>}
          </div>
          {!effData || (effData.total ?? 0) === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-700 py-8 text-center text-xs text-slate-400">
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
                    <div className="text-[13px] leading-5 text-slate-400">{item.label}</div>
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
              {feedbackData && <span className="font-mono text-[11px] text-slate-400">{feedbackData.sampleCount ?? 0} samples</span>}
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
            <div className="rounded-lg border border-dashed border-slate-700 py-8 text-center text-xs text-slate-400">
              표본이 부족합니다. 최소 {feedbackData?.minRequired ?? 10}건 이상 평가 후 피드백이 생성됩니다.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[13px] leading-5 text-slate-400">기준 승률</div>
                  <div className="mt-1 font-mono text-sm font-semibold text-slate-100">
                    {feedbackData.baseWinRate != null ? `${(feedbackData.baseWinRate * 100).toFixed(1)}%` : "-"}
                  </div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-[13px] leading-5 text-slate-400">기준 평균 PnL</div>
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
                    <div className="text-[13px] leading-5 text-slate-400">학습 품질 점수</div>
                    <div className="mt-1 font-mono text-lg font-semibold text-slate-100">
                      {selfLearningData?.quality?.score ?? 0}<span className="ml-1 text-xs text-slate-400">/100</span>
                    </div>
                  </div>
                  <div className="rounded-lg bg-slate-900 px-2 py-1 font-mono text-sm font-semibold text-cyan-200">
                    {selfLearningData?.quality?.grade ?? "D"}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                  <div>
                    <div className="text-slate-400">유효표본</div>
                    <div className="font-mono text-slate-200">{selfLearningData?.quality?.effectiveSamples ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">Forward</div>
                    <div className="font-mono text-slate-200">{selfLearningData?.quality?.forwardSamples ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">Replay</div>
                    <div className="font-mono text-slate-200">{selfLearningData?.quality?.historicalReplaySamples ?? 0}</div>
                  </div>
                  <div>
                    <div className="text-slate-400">최근 실행</div>
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
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Ops dashboard</div>
                    <div className="font-mono text-[13px] leading-5 text-slate-400">{opsData.generatedAt || "-"}</div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                    <div>
                      <div className="text-slate-400">Journal</div>
                      <div className="font-mono text-slate-200">{opsData.journal?.totalRows ?? 0}</div>
                    </div>
                    <div>
                      <div className="text-slate-400">Evaluated</div>
                      <div className="font-mono text-slate-200">{opsData.journal?.evaluatedRows ?? 0}</div>
                    </div>
                    <div>
                      <div className="text-slate-400">Open</div>
                      <div className="font-mono text-slate-200">{opsData.journal?.openRows ?? 0}</div>
                    </div>
                    <div>
                      <div className="text-slate-400">Files OK</div>
                      <div className="font-mono text-slate-200">
                        {(opsData.files || []).filter((f: any) => f.exists).length}/{(opsData.files || []).length}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-400">자동 최소 유효표본</div>
                  <div className="mt-1 font-mono text-slate-200">{selfLearningData?.policy?.minEffectiveSamples ?? "-"}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-400">회당 적용 한도</div>
                  <div className="mt-1 font-mono text-slate-200">{selfLearningData?.policy?.maxApplicationsPerRun ?? "-"}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-400">최대 실패비중</div>
                  <div className="mt-1 font-mono text-slate-200">{selfLearningData?.policy?.maxFailureShareForAutoApply != null ? `${(selfLearningData.policy.maxFailureShareForAutoApply * 100).toFixed(0)}%` : "-"}</div>
                </div>
                <div className="rounded-lg bg-slate-950/60 px-3 py-2">
                  <div className="text-slate-400">자동 승인자</div>
                  <div className="mt-1 truncate font-mono text-slate-200">{selfLearningData?.policy?.reviewer ?? "-"}</div>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-xs">
                  <thead className="text-[13px] leading-5 text-slate-400">
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
      </>
      )}
    </div>
  );
}
