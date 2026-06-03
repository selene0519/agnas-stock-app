"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone, type Market } from "@/lib/api";
import { dedupeBySymbol, displayName, firstText, horizonLabel, modeLabel, pctText, priceText, probabilityText, toNumber } from "@/lib/moneDisplay";
import { getDefaultMarketBySession } from "@/lib/marketSession";

type Strategy = "conservative" | "balanced" | "aggressive";
type Term = "short" | "swing" | "mid";

function avg(items: any[], getter: (item: any) => number | null) {
  const nums = items.map(getter).filter((value): value is number => Number.isFinite(value as number));
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

type ValidationStatus = "검증대기" | "미체결" | "체결" | "목표도달" | "손절" | "보류" | "오류";

function resolveStatus(item: any): ValidationStatus {
  const bucket = String(item.decisionBucket || item.decision_bucket || "").toLowerCase();
  const block = String(item.tradeBlockStatus || item.trade_block_status || "").toUpperCase();
  const outcome = String(item.outcome || item.result || "").toLowerCase();
  if (outcome.includes("목표") || outcome.includes("target")) return "목표도달";
  if (outcome.includes("손절") || outcome.includes("stop")) return "손절";
  if (outcome.includes("체결") || outcome.includes("executed")) return "체결";
  if (bucket === "보류" || bucket === "제외" || block === "CAUTION" || block === "BLOCK") return "보류";
  if (bucket === "실행" || bucket === "즉시실행") return "체결";
  if (bucket === "대기") return "미체결";
  return "검증대기";
}

const STATUS_STYLE: Record<ValidationStatus, string> = {
  "검증대기": "border-slate-700 bg-slate-800/60 text-slate-400",
  "미체결":   "border-amber-600/30 bg-amber-900/20 text-amber-300",
  "체결":     "border-blue-500/30 bg-blue-900/20 text-blue-300",
  "목표도달": "border-emerald-500/30 bg-emerald-900/20 text-emerald-300",
  "손절":     "border-red-500/30 bg-red-900/20 text-red-300",
  "보류":     "border-slate-600/30 bg-slate-800/40 text-slate-500",
  "오류":     "border-red-700/30 bg-red-950/20 text-red-400",
};

function scoreOf(item: any) {
  const direct = toNumber(item.score ?? item.finalScore ?? item.totalScore ?? item.riskScore);
  if (direct !== null && direct > 0) return direct;
  const p = toNumber(item.probability ?? item.probabilityText ?? item.prob5d);
  return p !== null ? Math.max(1, Math.min(100, p)) : null;
}

function mergeBySymbol(predictions: any[], recommendations: any[]) {
  const recMap = new Map<string, any>();
  for (const item of dedupeBySymbol(recommendations)) recMap.set(`${item.market}-${item.symbol}`, item);
  return dedupeBySymbol(predictions).map((item) => {
    const rec = recMap.get(`${item.market}-${item.symbol}`) || {};
    return { ...rec, ...item, name: displayName({ ...rec, ...item }), recommendation: rec };
  });
}

export default function PredictionPage() {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [strategy, setStrategy] = useState<Strategy>("balanced");
  const [term, setTerm] = useState<Term>("swing");
  const [data, setData] = useState<any>({ items: [] });
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [pred, rec] = await Promise.all([
        mone.predictions({ market, mode: strategy, horizon: term, limit: 300 }),
        mone.recommendations({ market, mode: strategy, horizon: term, limit: 300 }),
      ]);
      const predItems = Array.isArray(pred.items) ? pred.items : [];
      const recItems = Array.isArray(rec.items) ? rec.items : [];
      const merged = predItems.length ? mergeBySymbol(predItems, recItems) : dedupeBySymbol(recItems);
      setData({ ...pred, items: merged, recommendationCount: recItems.length });
    } catch (error) {
      setData({ status: "ERROR", error: String(error), items: [] });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [market, strategy, term]);

  const items = Array.isArray(data.items) ? data.items : [];
  const top = useMemo(() => items.slice(0, 30), [items]);

  const stats = useMemo(() => {
    if (!top.length) return null;
    const statuses = top.map(resolveStatus);
    const targetCount = statuses.filter((s) => s === "목표도달").length;
    const stopCount = statuses.filter((s) => s === "손절").length;
    const executedCount = statuses.filter((s) => s === "체결" || s === "목표도달" || s === "손절").length;
    const winRate = executedCount > 0 ? (targetCount / executedCount) * 100 : 0;
    const avgEv = avg(top, (item) => toNumber(item.expectedValue ?? item.ev));
    return { targetCount, stopCount, executedCount, winRate, avgEv, statusCounts: Object.fromEntries(["검증대기","미체결","체결","목표도달","손절","보류"].map((s) => [s, statuses.filter((x) => x === s).length])) };
  }, [top]);

  const strategyTabs: { id: Strategy; label: string }[] = [
    { id: "conservative", label: "보수" },
    { id: "balanced", label: "균형" },
    { id: "aggressive", label: "공격" },
  ];
  const termTabs: { id: Term; label: string }[] = [
    { id: "short", label: "단기" },
    { id: "swing", label: "스윙" },
    { id: "mid", label: "중기" },
  ];

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">예측·검증</h1>
          <p className="mt-1 text-sm text-slate-400">확률 예측, 예상가, 진입/손절/목표를 기간과 성향별로 확인합니다.</p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> 새로고침
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "kr", "us"] as Market[]).map((item) => (
          <button key={item} onClick={() => setMarket(item)} className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>{item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}</button>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">투자 성향</div>
            <div className="flex flex-wrap gap-2">
              {strategyTabs.map((item) => (
                <button key={item.id} onClick={() => setStrategy(item.id)} className={`rounded-xl px-4 py-2 text-sm ${strategy === item.id ? "bg-emerald-600 text-white" : "bg-slate-950 text-slate-400"}`}>{item.label}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">투자 기간</div>
            <div className="flex flex-wrap gap-2">
              {termTabs.map((item) => (
                <button key={item.id} onClick={() => setTerm(item.id)} className={`rounded-xl px-4 py-2 text-sm ${term === item.id ? "bg-cyan-600 text-white" : "bg-slate-950 text-slate-400"}`}>{item.label}</button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card label="표시 후보" value={`${top.length}개`} />
        <Card label="현재 조건" value={`${modeLabel(strategy)} · ${horizonLabel(term)}`} />
        <Card label="평균 확률" value={`${avg(top, (item) => toNumber(item.probability ?? item.probabilityText ?? item.prob5d)).toFixed(1)}%`} />
        <Card label="평균 점수" value={`${avg(top, scoreOf).toFixed(1)}점`} />
      </div>

      {stats && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
          <div className="mb-3 text-xs font-semibold text-slate-400">상태별 분포</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.statusCounts).map(([status, count]) => count > 0 && (
              <span key={status} className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${STATUS_STYLE[status as ValidationStatus]}`}>
                {status} {count}
              </span>
            ))}
          </div>
          {stats.executedCount > 0 && (
            <div className="mt-3 grid grid-cols-3 gap-3 text-center text-xs">
              <div className="rounded-xl bg-slate-950/60 py-2">
                <div className="text-slate-500">체결 승률</div>
                <div className={`mt-1 font-mono font-bold ${stats.winRate >= 50 ? "text-emerald-300" : "text-amber-300"}`}>{stats.winRate.toFixed(1)}%</div>
              </div>
              <div className="rounded-xl bg-slate-950/60 py-2">
                <div className="text-slate-500">목표 / 손절</div>
                <div className="mt-1 font-mono font-bold"><span className="text-emerald-300">{stats.targetCount}</span> / <span className="text-red-300">{stats.stopCount}</span></div>
              </div>
              <div className="rounded-xl bg-slate-950/60 py-2">
                <div className="text-slate-500">평균 EV</div>
                <div className={`mt-1 font-mono font-bold ${stats.avgEv >= 0 ? "text-emerald-300" : "text-red-300"}`}>{stats.avgEv >= 0 ? "+" : ""}{stats.avgEv.toFixed(1)}%</div>
              </div>
            </div>
          )}
          {stats.executedCount === 0 && (
            <p className="mt-2 text-[11px] text-slate-600">체결/결과 데이터가 없습니다. decisionBucket이 "실행"인 종목이 없거나 outcome 필드가 채워지지 않았습니다.</p>
          )}
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60">
        <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">
          predictions/table과 recommendations를 market+symbol 기준으로 병합했습니다. 진입/손절/목표가 비면 추천값으로 보강합니다.
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1200px] text-left text-sm">
            <thead className="border-b border-slate-800 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3">종목</th>
                <th className="px-4 py-3">시장</th>
                <th className="px-4 py-3">확률</th>
                <th className="px-4 py-3">점수</th>
                <th className="px-4 py-3">현재가</th>
                <th className="px-4 py-3">진입가</th>
                <th className="px-4 py-3">손절가</th>
                <th className="px-4 py-3">목표가</th>
                <th className="px-4 py-3">예상가</th>
                <th className="px-4 py-3">1/3/5/10일</th>
                <th className="px-4 py-3">상태</th>
              </tr>
            </thead>
            <tbody>
              {top.map((item: any, index: number) => {
                const score = scoreOf(item);
                const prob1d = firstText(item.prob1dText, item.prob1d ? pctText(item.prob1d) : null, probabilityText(item));
                const prob3d = firstText(item.prob3dText, item.prob3d ? pctText(item.prob3d) : null, probabilityText(item));
                const prob5d = firstText(item.prob5dText, item.prob5d ? pctText(item.prob5d) : null, probabilityText(item));
                const prob10d = firstText(item.prob10dText, item.prob10d ? pctText(item.prob10d) : null, probabilityText(item));
                const current = priceText(item, "current", priceText(item.recommendation || {}, "current", "가격 확인"));
                const entry = priceText(item, "entry", priceText(item.recommendation || {}, "entry", current));
                const stop = priceText(item, "stop", priceText(item.recommendation || {}, "stop", "손절 확인"));
                const target = priceText(item, "target", priceText(item.recommendation || {}, "target", "목표 확인"));
                const expected = priceText(item, "expected", target);
                return (
                  <tr key={`${item.market}-${item.symbol}-${index}`} className="border-b border-slate-800/60">
                    <td className="px-4 py-3"><div className="font-semibold text-slate-100">{displayName(item)}</div><div className="font-mono text-xs text-slate-500">{item.symbol}</div></td>
                    <td className="px-4 py-3 uppercase text-slate-400">{item.market}</td>
                    <td className="px-4 py-3 font-mono text-emerald-300">{probabilityText(item, "확률 확인")}</td>
                    <td className="px-4 py-3 font-mono text-cyan-300">{score !== null ? score.toFixed(1) : "점수 확인"}</td>
                    <td className="px-4 py-3 font-mono">{current}</td>
                    <td className="px-4 py-3 font-mono text-sky-300">{entry}</td>
                    <td className="px-4 py-3 font-mono text-red-300">{stop}</td>
                    <td className="px-4 py-3 font-mono text-emerald-300">{target}</td>
                    <td className="px-4 py-3 font-mono text-violet-300">{expected}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-300">{prob1d} / {prob3d} / {prob5d} / {prob10d}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-lg border px-2 py-1 text-[10px] font-bold ${STATUS_STYLE[resolveStatus(item)]}`}>{resolveStatus(item)}</span>
                    </td>
                  </tr>
                );
              })}
              {top.length === 0 && <tr><td colSpan={11} className="px-4 py-10 text-center text-slate-500">예측 데이터가 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><div className="text-sm text-slate-500">{label}</div><div className="mt-2 font-mono text-2xl font-bold text-slate-100">{value}</div></div>;
}
