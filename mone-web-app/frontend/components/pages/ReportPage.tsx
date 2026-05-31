"use client";

import { useEffect, useMemo, useState } from "react";
import { mone, money, type Market, type Mode, type Horizon } from "@/lib/api";

type Tab = "premarket" | "intraday" | "closing";

function Metric({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: any;
  accent?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-3 font-mono text-2xl font-bold ${accent ? "text-emerald-400" : "text-slate-100"}`}>
        {value}
      </div>
    </div>
  );
}

export default function ReportPage() {
  const [market, setMarket] = useState<Market>("kr");
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [tab, setTab] = useState<Tab>("premarket");
  const [data, setData] = useState<any>({ status: "LOADING", items: [] });

  useEffect(() => {
    let active = true;

    setData({ status: "LOADING", items: [] });

    mone
      .report(tab, { market, mode, horizon, limit: 300 })
      .then((response) => {
        if (!active) return;
        setData(response || { status: "OK", items: [] });
      })
      .catch((error) => {
        if (!active) return;
        setData({ status: "ERROR", error: String(error), items: [] });
      });

    return () => {
      active = false;
    };
  }, [market, mode, horizon, tab]);

  const items = useMemo(() => {
    return Array.isArray(data.items) ? data.items : [];
  }, [data.items]);

  const closing = tab === "closing";

  const tabs: { id: Tab; label: string }[] = [
    { id: "premarket", label: "장전 리포트" },
    { id: "intraday", label: "장중 체크" },
    { id: "closing", label: "장마감 검증" },
  ];

  const modes: { id: Mode; label: string }[] = [
    { id: "conservative", label: "보수" },
    { id: "balanced", label: "균형" },
    { id: "aggressive", label: "공격" },
  ];

  const horizons: { id: Horizon; label: string }[] = [
    { id: "short", label: "단기" },
    { id: "swing", label: "스윙" },
    { id: "mid", label: "중기" },
  ];

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">운용 리포트</h1>
          <p className="mt-1 text-sm text-slate-400">
            장전 준비, 장중 체크, 장마감 검증 리포트를 확인합니다.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {(["kr", "us"] as Market[]).map((item) => (
            <button
              key={item}
              onClick={() => setMarket(item)}
              className={`rounded-xl px-4 py-2 text-sm ${
                market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"
              }`}
            >
              {item === "kr" ? "국장" : "미장"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 rounded-2xl bg-slate-900/60 p-2">
        {tabs.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`rounded-xl px-4 py-2 text-sm ${
              tab === item.id ? "bg-blue-600 text-white" : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {modes.map((item) => (
          <button
            key={item.id}
            onClick={() => setMode(item.id)}
            className={`rounded-xl px-3 py-1.5 text-xs ${
              mode === item.id ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"
            }`}
          >
            {item.label}
          </button>
        ))}

        {horizons.map((item) => (
          <button
            key={item.id}
            onClick={() => setHorizon(item.id)}
            className={`rounded-xl px-3 py-1.5 text-xs ${
              horizon === item.id ? "bg-cyan-600 text-white" : "bg-slate-900 text-slate-400"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {closing && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <Metric label="전체 검증" value={data.totalRecommendations ?? 0} />
          <Metric label="가상 체결" value={data.executedTrades ?? 0} />
          <Metric label="승률" value={`${Number(data.winRate ?? 0).toFixed(2)}%`} />
          <Metric label="누적 수익률" value={`${Number(data.cumulativeReturnPct ?? 0).toFixed(2)}%`} accent />
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/50">
        <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">
          가격 기준: {market === "kr" ? "국장 최신 OHLCV / KIS" : "미장 최신 OHLCV / 현재가"} · {items.length.toLocaleString()}건
        </div>

        {items.length === 0 ? (
          <div className="p-12 text-center text-slate-500">
            {data.status === "ERROR" ? `데이터 로딩 오류: ${data.error}` : "표시할 리포트 데이터가 없습니다."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] text-left text-sm">
              <thead className="bg-slate-950/50 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3">종목</th>

                  {closing ? (
                    <>
                      <th className="px-4 py-3">일자</th>
                      <th className="px-4 py-3">체결</th>
                      <th className="px-4 py-3">결과</th>
                      <th className="px-4 py-3">수익률</th>
                      <th className="px-4 py-3">출처</th>
                    </>
                  ) : (
                    <>
                      <th className="px-4 py-3">현재가</th>
                      <th className="px-4 py-3">진입가</th>
                      <th className="px-4 py-3">손절가</th>
                      <th className="px-4 py-3">목표가</th>
                      <th className="px-4 py-3">확률</th>
                      <th className="px-4 py-3">상태</th>
                    </>
                  )}
                </tr>
              </thead>

              <tbody>
                {items.map((item: any, index: number) => (
                  <tr key={`${item.id || item.symbol || "report"}-${index}`} className="border-t border-slate-800/70">
                    <td className="px-4 py-4">
                      <div className="font-semibold text-slate-100">{item.name || item.symbol || "-"}</div>
                      <div className="font-mono text-xs text-slate-500">
                        {item.symbol || "-"} · {(item.market || market).toUpperCase()}
                      </div>
                    </td>

                    {closing ? (
                      <>
                        <td className="px-4 py-4 font-mono text-slate-300">{item.date || "-"}</td>
                        <td className="px-4 py-4 text-emerald-400">{item.executionStatus || "-"}</td>
                        <td className="px-4 py-4 text-slate-200">{item.outcomeResult || "-"}</td>
                        <td className="px-4 py-4 font-mono text-emerald-400">
                          {Number(item.realizedReturnPct || 0).toFixed(2)}%
                        </td>
                        <td className="px-4 py-4 text-xs text-slate-500">{item.sourceFile || "-"}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-4 font-mono text-slate-100">
                          {item.currentPriceText || money(item.currentPrice, market)}
                        </td>
                        <td className="px-4 py-4 font-mono text-blue-300">
                          {item.entryText || money(item.entry, market)}
                        </td>
                        <td className="px-4 py-4 font-mono text-red-400">
                          {item.stopText || money(item.stop, market)}
                        </td>
                        <td className="px-4 py-4 font-mono text-emerald-400">
                          {item.targetText || money(item.target, market)}
                        </td>
                        <td className="px-4 py-4 font-mono text-slate-300">{item.probabilityText || "-"}</td>
                        <td className="px-4 py-4">
                          <span className="rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-400">
                            {item.priceDataStatus || "PARTIAL"}
                          </span>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
