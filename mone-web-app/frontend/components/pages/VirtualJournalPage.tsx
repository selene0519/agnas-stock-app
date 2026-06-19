"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, BookOpenCheck, CheckCircle2, ClipboardCheck, Play, RefreshCw, ShieldCheck, TrendingUp, XCircle } from "lucide-react";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";

type ScopeMarket = Extract<Market, "kr" | "us" | "all">;
type ScopeMode = Extract<Mode, "conservative" | "balanced" | "aggressive" | "all">;
type ScopeHorizon = Extract<Horizon, "short" | "swing" | "mid" | "all">;

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

function fmtNum(value: any, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "-";
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

function toneForOutcome(outcome: string) {
  if (outcome === "TARGET_HIT") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (outcome === "STOP_HIT" || outcome === "TIME_EXIT_NEAR_STOP") return "border-red-500/30 bg-red-500/10 text-red-300";
  if (outcome.startsWith("TIME_EXIT")) return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  if (outcome === "PENDING" || outcome === "DATA_PENDING") return "border-sky-500/30 bg-sky-500/10 text-sky-300";
  return "border-slate-700 bg-slate-800 text-slate-300";
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
  const [replayDate, setReplayDate] = useState(defaultReplayDate);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [trades, setTrades] = useState<any[]>([]);
  const [patterns, setPatterns] = useState<any[]>([]);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [autoStatus, setAutoStatus] = useState<any>({});
  const [analyticsData, setAnalyticsData] = useState<any>({});
  const [perfData, setPerfData] = useState<any>(null);

  const scope = useMemo(() => ({ market, mode, horizon, sourceType: "FORWARD_PAPER_TRADE" }), [market, mode, horizon]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [tradeRes, patternRes, suggestionRes, statusRes, analyticsRes, perfRes] = await Promise.all([
        mone.virtualTrades({ ...scope, limit: 200 }),
        mone.journalFailurePatterns(scope),
        mone.journalCalibrationSuggestions(scope),
        mone.journalAutoCaptureStatus(),
        mone.journalAnalytics(scope),
        mone.journalPerformance({ market: scope.market, mode: scope.mode, horizon: scope.horizon }),
      ]);
      if (tradeRes.status === "ERROR") throw new Error(tradeRes.error || "journal load failed");
      setTrades(tradeRes.items || []);
      setPatterns(patternRes.items || []);
      setSuggestions(suggestionRes.items || []);
      setAutoStatus(statusRes || {});
      setAnalyticsData(analyticsRes || {});
      setPerfData(perfRes?.status === "OK" ? perfRes : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  const runAction = async (kind: "capture" | "evaluate" | "auto" | "replay") => {
    setBusy(kind);
    setError("");
    try {
      if (kind === "capture") {
        const targetMarket = market === "all" ? "kr" : market;
        const targetMode = mode === "all" ? "balanced" : mode;
        const targetHorizon = horizon === "all" ? "swing" : horizon;
        await mone.virtualTradeCapture({ market: targetMarket, mode: targetMode, horizon: targetHorizon, limit: 5 });
      } else if (kind === "evaluate") {
        await mone.virtualTradeEvaluate({ ...scope, limit: 500 });
      } else if (kind === "replay") {
        const targetMarket = market === "all" ? "kr" : market;
        const targetMode = mode === "all" ? "balanced" : mode;
        const targetHorizon = horizon === "all" ? "swing" : horizon;
        await mone.journalHistoricalReplay({ market: targetMarket, mode: targetMode, horizon: targetHorizon, asOfDate: replayDate, limit: 5, evaluateAfter: true });
      } else {
        await mone.journalAutoCaptureRun({ market, limit: 5, evaluateAfter: true, force: true });
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

  const approvedSuggestions = useMemo(
    () => suggestions.filter((item) => item.approvalStatus === "APPROVED").slice(0, 4),
    [suggestions],
  );

  return (
    <div className="space-y-4">
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
          <div className="flex flex-wrap gap-2">
            <button onClick={load} disabled={loading || !!busy} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-slate-800 px-3 text-sm font-semibold text-slate-200 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.14)] transition-transform active:scale-[0.96] disabled:opacity-50">
              <RefreshCw size={15} /> 새로고침
            </button>
            <button onClick={() => runAction("evaluate")} disabled={!!busy} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-cyan-500/12 px-3 text-sm font-semibold text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)] transition-transform active:scale-[0.96] disabled:opacity-50">
              <Activity size={15} /> 평가 실행
            </button>
            <button onClick={() => runAction("auto")} disabled={!!busy} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-emerald-500/12 px-3 text-sm font-semibold text-emerald-200 shadow-[inset_0_0_0_1px_rgba(52,211,153,0.25)] transition-transform active:scale-[0.96] disabled:opacity-50">
              <Play size={15} /> 자동 캡처 실행
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
          {[markets, modes, horizons].map((group, groupIndex) => (
            <div key={groupIndex} className="flex rounded-lg bg-slate-950/60 p-1 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
              {group.map((item) => {
                const active = groupIndex === 0 ? market === item.id : groupIndex === 1 ? mode === item.id : horizon === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => groupIndex === 0 ? setMarket(item.id as ScopeMarket) : groupIndex === 1 ? setMode(item.id as ScopeMode) : setHorizon(item.id as ScopeHorizon)}
                    className={`min-h-9 rounded-md px-3 text-xs font-semibold transition-colors ${active ? "bg-slate-700 text-white" : "text-slate-500 hover:text-slate-200"}`}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {error && <div className="mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-200 shadow-[inset_0_0_0_1px_rgba(239,68,68,0.22)]">{error}</div>}
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg bg-slate-900/50 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-200">최근 일지</h2>
            <span className="font-mono text-xs tabular-nums text-slate-500">{loading ? "loading" : `${trades.length} rows`}</span>
          </div>
          <div className="overflow-x-auto">
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
                      <div className="font-semibold text-slate-100">{item.name || item.symbol}</div>
                      <div className="font-mono text-[11px] text-slate-500">{item.symbol}</div>
                    </td>
                    <td className="py-3 pr-3">
                      <div className="font-mono text-[11px] uppercase text-slate-400">
                        {String(item.market || "").toUpperCase()} / {MODE_SHORT[item.mode] ?? item.mode} / {HORIZON_SHORT[item.horizon] ?? item.horizon}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">{item.as_of_date}</div>
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
                    <td className="max-w-sm py-3 pr-3 text-[12px] leading-5 text-slate-400">{item.review_text || "-"}</td>
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
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">Synthetic cutoff replay v1입니다. 후보 생성은 입력 날짜까지의 OHLCV만 사용하고, 평가는 저장 후 별도로 수행합니다.</p>
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
    </div>
  );
}
