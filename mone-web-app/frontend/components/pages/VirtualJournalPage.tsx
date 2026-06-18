"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, BookOpenCheck, CheckCircle2, Play, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
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

function metric(label: string, value: any, tone = "text-slate-100") {
  return (
    <div className="rounded-lg bg-slate-950/60 px-3 py-2 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
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

  const scope = useMemo(() => ({ market, mode, horizon, sourceType: "FORWARD_PAPER_TRADE" }), [market, mode, horizon]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [tradeRes, patternRes, suggestionRes, statusRes] = await Promise.all([
        mone.virtualTrades({ ...scope, limit: 200 }),
        mone.journalFailurePatterns(scope),
        mone.journalCalibrationSuggestions(scope),
        mone.journalAutoCaptureStatus(),
      ]);
      if (tradeRes.status === "ERROR") throw new Error(tradeRes.error || "journal load failed");
      setTrades(tradeRes.items || []);
      setPatterns(patternRes.items || []);
      setSuggestions(suggestionRes.items || []);
      setAutoStatus(statusRes || {});
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
              <span>가상 매매일지</span>
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
                  <th className="py-2">복기</th>
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
                      <div className="font-mono text-[11px] uppercase text-slate-400">{item.market} / {item.mode} / {item.horizon}</div>
                      <div className="mt-1 text-[11px] text-slate-500">{item.as_of_date}</div>
                    </td>
                    <td className="py-3 pr-3">
                      <span className={`inline-flex rounded-md px-2 py-1 text-[11px] font-semibold ${toneForOutcome(String(item.outcome || "PENDING"))}`}>
                        {item.outcome || "PENDING"}
                      </span>
                    </td>
                    <td className={`py-3 pr-3 text-right font-mono tabular-nums ${Number(item.net_pnl_pct) >= 0 ? "text-emerald-300" : "text-red-300"}`}>{fmtNum(item.net_pnl_pct, "%")}</td>
                    <td className="py-3 pr-3 text-right font-mono tabular-nums text-slate-300">{fmtNum(item.mfe_pct, "%")}</td>
                    <td className="py-3 pr-3 text-right font-mono tabular-nums text-slate-300">{fmtNum(item.mae_pct, "%")}</td>
                    <td className="py-3 pr-3 font-mono text-[11px] text-amber-300">{item.failure_reason || "-"}</td>
                    <td className="max-w-sm py-3 text-[12px] leading-5 text-slate-400">{item.review_text || "-"}</td>
                  </tr>
                ))}
                {!trades.length && (
                  <tr>
                    <td colSpan={8} className="py-10 text-center text-sm text-slate-500">아직 가상 매매일지가 없습니다.</td>
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
    </div>
  );
}
