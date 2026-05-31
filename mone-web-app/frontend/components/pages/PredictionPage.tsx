"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone, type Market } from "@/lib/api";

type Strategy = "conservative" | "balanced" | "aggressive";
type Term = "short" | "swing" | "mid";

const STRATEGY_LABEL: Record<Strategy, string> = {
  conservative: "보수",
  balanced: "균형",
  aggressive: "공격",
};

const TERM_LABEL: Record<Term, string> = {
  short: "단기",
  swing: "스윙",
  mid: "중기",
};

function price(value: any, market: string) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return market === "us" ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `${Math.round(n).toLocaleString()}원`;
}

function avg(items: any[], key: string) {
  const nums = items.map((item) => Number(item[key])).filter((item) => Number.isFinite(item));
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

export default function PredictionPage() {
  const [market, setMarket] = useState<Market>("all");
  const [strategy, setStrategy] = useState<Strategy>("balanced");
  const [term, setTerm] = useState<Term>("swing");
  const [data, setData] = useState<any>({ items: [] });
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const result = await mone.predictions({ market, mode: strategy, horizon: term, limit: 300 });
      setData(result);
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

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">예측·검증</h1>
          <p className="mt-1 text-sm text-slate-400">확률 예측, 예상가, 검증 요약을 기간과 성향별로 확인합니다.</p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "kr", "us"] as Market[]).map((item) => (
          <button key={item} onClick={() => setMarket(item)} className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {(["conservative", "balanced", "aggressive"] as Strategy[]).map((item) => (
          <button key={item} onClick={() => setStrategy(item)} className={`rounded-xl px-4 py-2 text-sm ${strategy === item ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {STRATEGY_LABEL[item]}
          </button>
        ))}
        {(["short", "swing", "mid"] as Term[]).map((item) => (
          <button key={item} onClick={() => setTerm(item)} className={`rounded-xl px-4 py-2 text-sm ${term === item ? "bg-cyan-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {TERM_LABEL[item]}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card label="표시 후보" value={`${top.length}개`} />
        <Card label="현재 조건" value={`${STRATEGY_LABEL[strategy]} · ${TERM_LABEL[term]}`} />
        <Card label="평균 확률" value={`${avg(top, "probability").toFixed(1)}%`} />
        <Card label="평균 점수" value={`${avg(top, "score").toFixed(1)}점`} />
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1100px] text-left text-sm">
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
                <th className="px-4 py-3">상태</th>
              </tr>
            </thead>
            <tbody>
              {top.map((item: any, index: number) => (
                <tr key={`${item.market}-${item.symbol}-${index}`} className="border-b border-slate-800/60">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-slate-100">{item.name || item.symbol}</div>
                    <div className="font-mono text-xs text-slate-500">{item.symbol}</div>
                  </td>
                  <td className="px-4 py-3 uppercase text-slate-400">{item.market}</td>
                  <td className="px-4 py-3 font-mono text-emerald-300">{item.probabilityText || `${Number(item.probability || 0).toFixed(1)}%`}</td>
                  <td className="px-4 py-3 font-mono text-cyan-300">{item.score ?? "-"}</td>
                  <td className="px-4 py-3 font-mono">{price(item.currentPrice, item.market)}</td>
                  <td className="px-4 py-3 font-mono text-sky-300">{price(item.entryPrice, item.market)}</td>
                  <td className="px-4 py-3 font-mono text-red-300">{price(item.stopPrice, item.market)}</td>
                  <td className="px-4 py-3 font-mono text-emerald-300">{price(item.targetPrice, item.market)}</td>
                  <td className="px-4 py-3 font-mono text-violet-300">{price(item.expectedPrice, item.market)}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-lg border px-2 py-1 text-[10px] font-bold ${item.dataStatus === "OK" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300"}`}>
                      {item.dataStatus || "PARTIAL"}
                    </span>
                  </td>
                </tr>
              ))}
              {top.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-10 text-center text-slate-500">예측 데이터가 없습니다.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 font-mono text-2xl font-bold text-slate-100">{value}</div>
    </div>
  );
}
