"use client";

import { useEffect, useMemo, useState } from "react";
import { mone, money, type Horizon, type Market, type Mode } from "@/lib/api";
import { dedupeBySymbol, displayName, firstText, horizonLabel, modeLabel, priceText, probabilityText } from "@/lib/moneDisplay";

type Tab = "premarket" | "intraday" | "closing" | "virtual";

function Metric({ label, value, accent = false }: { label: string; value: any; accent?: boolean }) {
  return <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><div className="text-sm text-slate-500">{label}</div><div className={`mt-3 font-mono text-2xl font-bold ${accent ? "text-emerald-400" : "text-slate-100"}`}>{value}</div></div>;
}

function latestDate(items: any[]) {
  const dates = items.map((item) => item.date || item.asOf || item.tradeDate || item.validationDate).filter(Boolean).sort();
  return dates.at(-1) || "-";
}

export default function ReportPage() {
  const [market, setMarket] = useState<Market>("kr");
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [tab, setTab] = useState<Tab>("premarket");
  const [data, setData] = useState<any>({ status: "LOADING", items: [] });
  const [virtual, setVirtual] = useState<any>({ status: "LOADING" });

  useEffect(() => {
    let active = true;
    setData({ status: "LOADING", items: [] });
    const task = tab === "virtual"
      ? mone.backtestTrades({ market, mode, horizon, limit: 300 })
      : tab === "closing"
        ? mone.backtestTrades({ market, mode, horizon, limit: 300 })
        : mone.report(tab, { market, mode, horizon, limit: 300 });
    task.then((response) => active && setData(response || { status: "OK", items: [] })).catch((error) => active && setData({ status: "ERROR", error: String(error), items: [] }));
    mone.backtestSummary({ market, mode, horizon }).then((response) => active && setVirtual(response || {})).catch(() => active && setVirtual({}));
    return () => { active = false; };
  }, [market, mode, horizon, tab]);

  const rawItems = Array.isArray(data.items) ? data.items : [];
  const items = useMemo(() => (tab === "closing" || tab === "virtual" ? rawItems : dedupeBySymbol(rawItems)), [rawItems, tab]);
  const closing = tab === "closing";
  const virtualTab = tab === "virtual";

  const tabs: { id: Tab; label: string; desc: string }[] = [
    { id: "premarket", label: "장전 리포트", desc: "오늘 진입 후보와 계획" },
    { id: "intraday", label: "장중 체크", desc: "현재가 기준 진입/손절/목표 접근" },
    { id: "closing", label: "장마감 검증", desc: "당일 종가 기준 예측 검증" },
    { id: "virtual", label: "가상운용", desc: "조건부 체결과 성과" },
  ];
  const modes: { id: Mode; label: string }[] = [
    { id: "conservative", label: "보수" }, { id: "balanced", label: "균형" }, { id: "aggressive", label: "공격" },
  ];
  const horizons: { id: Horizon; label: string }[] = [
    { id: "short", label: "단기" }, { id: "swing", label: "스윙" }, { id: "mid", label: "중기" },
  ];

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div><h1 className="text-2xl font-bold text-slate-100">운용 리포트</h1><p className="mt-1 text-sm text-slate-400">장전, 장중, 장마감 검증, 가상운용을 분리해 확인합니다.</p></div>
        <div className="flex flex-wrap gap-2">{(["kr", "us"] as Market[]).map((item) => <button key={item} onClick={() => setMarket(item)} className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>{item === "kr" ? "국장" : "미장"}</button>)}</div>
      </div>

      <div className="grid grid-cols-1 gap-2 rounded-2xl bg-slate-900/60 p-2 md:grid-cols-4">
        {tabs.map((item) => <button key={item.id} onClick={() => setTab(item.id)} className={`rounded-xl p-3 text-left text-sm ${tab === item.id ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`}><div className="font-bold">{item.label}</div><div className="mt-1 text-[11px] opacity-75">{item.desc}</div></button>)}
      </div>

      <div className="flex flex-wrap gap-2">
        {modes.map((item) => <button key={item.id} onClick={() => setMode(item.id)} className={`rounded-xl px-3 py-1.5 text-xs ${mode === item.id ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"}`}>{item.label}</button>)}
        {horizons.map((item) => <button key={item.id} onClick={() => setHorizon(item.id)} className={`rounded-xl px-3 py-1.5 text-xs ${horizon === item.id ? "bg-cyan-600 text-white" : "bg-slate-900 text-slate-400"}`}>{item.label}</button>)}
      </div>

      {(closing || virtualTab) && <div className="grid grid-cols-1 gap-4 md:grid-cols-4"><Metric label="전체 검증" value={virtual.totalRecommendations ?? data.totalRecommendations ?? items.length} /><Metric label="가상 체결" value={virtual.executedTrades ?? data.executedTrades ?? 0} /><Metric label="승률" value={`${Number(virtual.winRate ?? data.winRate ?? 0).toFixed(2)}%`} /><Metric label="누적 수익률" value={`${Number(virtual.cumulativeReturnPct ?? data.cumulativeReturnPct ?? 0).toFixed(2)}%`} accent /></div>}

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50">
        <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">
          {market === "kr" ? "국장" : "미장"} · {modeLabel(mode)} · {horizonLabel(horizon)} · 기준일 {latestDate(items)} · {items.length.toLocaleString()}건
        </div>
        {items.length === 0 ? <div className="p-12 text-center text-slate-500">{data.status === "ERROR" ? `데이터 로딩 오류: ${data.error}` : "표시할 리포트 데이터가 없습니다."}</div> : <div className="overflow-x-auto"><table className="w-full min-w-[1100px] text-left text-sm"><thead className="bg-slate-950/50 text-xs text-slate-500"><tr><th className="px-4 py-3">종목</th>{closing || virtualTab ? <><th className="px-4 py-3">일자</th><th className="px-4 py-3">체결</th><th className="px-4 py-3">결과</th><th className="px-4 py-3">수익률</th><th className="px-4 py-3">출처</th></> : <><th className="px-4 py-3">현재가</th><th className="px-4 py-3">진입가</th><th className="px-4 py-3">손절가</th><th className="px-4 py-3">목표가</th><th className="px-4 py-3">확률</th><th className="px-4 py-3">상태</th></>}</tr></thead><tbody>{items.map((item: any, index: number) => <tr key={`${item.id || item.symbol || "report"}-${index}`} className="border-t border-slate-800/70"><td className="px-4 py-4"><div className="font-semibold text-slate-100">{displayName(item)}</div><div className="font-mono text-xs text-slate-500">{item.symbol || "-"} · {(item.market || market).toUpperCase()}</div></td>{closing || virtualTab ? <><td className="px-4 py-4 font-mono text-slate-300">{item.date || item.tradeDate || "-"}</td><td className="px-4 py-4 text-emerald-400">{item.executionStatus || item.executed || "조건 확인"}</td><td className="px-4 py-4 text-slate-200">{item.outcomeResult || item.result || "검증 대기"}</td><td className="px-4 py-4 font-mono text-emerald-400">{Number(item.realizedReturnPct || item.returnPct || 0).toFixed(2)}%</td><td className="px-4 py-4 text-xs text-slate-500">{item.sourceFile || item.source || "-"}</td></> : <><td className="px-4 py-4 font-mono text-slate-100">{priceText(item, "current", money(item.currentPrice, market))}</td><td className="px-4 py-4 font-mono text-blue-300">{priceText(item, "entry", money(item.entry, market))}</td><td className="px-4 py-4 font-mono text-red-400">{priceText(item, "stop", money(item.stop, market))}</td><td className="px-4 py-4 font-mono text-emerald-400">{priceText(item, "target", money(item.target, market))}</td><td className="px-4 py-4 font-mono text-slate-300">{probabilityText(item, "확률 확인")}</td><td className="px-4 py-4"><span className="rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-400">{firstText(item.priceDataStatus, item.dataStatus, item.sourceStatus, "확인")}</span></td></>}</tr>)}</tbody></table></div>}
      </div>
    </div>
  );
}
