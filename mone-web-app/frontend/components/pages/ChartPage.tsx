"use client";

import { useEffect, useMemo, useState } from "react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, money, type Market } from "@/lib/api";

export default function ChartPage() {
  const [market, setMarket] = useState<Market>("all");
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selected) {
      setRows([]);
      return;
    }

    let active = true;
    setLoading(true);

    mone
      .ohlcv({
        market: selected.market,
        symbol: selected.symbol,
        limit: 260,
      })
      .then((data) => {
        if (!active) return;
        setRows(Array.isArray(data.items) ? data.items : []);
      })
      .catch(() => {
        if (!active) return;
        setRows([]);
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [selected]);

  const latest = rows.at(-1);
  const display = rows.slice(-90);

  const max = useMemo(() => {
    return Math.max(...display.map((row) => Number(row.close || 0)), 1);
  }, [display]);

  const min = useMemo(() => {
    return Math.min(...display.map((row) => Number(row.close || max)), max);
  }, [display, max]);

  const y = (close: number) => {
    if (max === min) return 120;
    return 220 - ((close - min) / (max - min)) * 190;
  };

  const points = display
    .map((row, index) => {
      const x = 20 + (index / Math.max(display.length - 1, 1)) * 900;
      return `${x},${y(Number(row.close || 0))}`;
    })
    .join(" ");

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">차트·기술분석</h1>
        <p className="mt-1 text-sm text-slate-400">
          종목을 선택해 OHLCV 가격 흐름을 확인합니다.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "kr", "us"] as Market[]).map((item) => (
          <button
            key={item}
            onClick={() => {
              setMarket(item);
              setSelected(null);
            }}
            className={`rounded-xl px-4 py-2 text-sm ${
              market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"
            }`}
          >
            {item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}
          </button>
        ))}
      </div>

      <SymbolSearchSelect
        market={market}
        value={selected?.symbol || ""}
        onChange={setSelected}
      />

      {!selected && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
          종목명 또는 종목코드로 검색하거나 목록에서 종목을 선택하세요.
        </div>
      )}

      {selected && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold text-slate-100">{selected.name}</h2>
              <p className="font-mono text-sm text-slate-500">
                {selected.symbol} · {selected.market.toUpperCase()}
              </p>
            </div>

            <div className="text-right">
              <div className="text-xs text-slate-500">최근 종가</div>
              <div className="font-mono text-xl font-bold text-emerald-400">
                {latest ? money(latest.close, selected.market) : "-"}
              </div>
            </div>
          </div>

          {loading && (
            <div className="py-20 text-center text-slate-500">차트 데이터를 불러오는 중...</div>
          )}

          {!loading && rows.length === 0 && (
            <div className="py-20 text-center text-slate-500">
              이 종목의 OHLCV 데이터가 없습니다.
            </div>
          )}

          {!loading && rows.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
              <svg viewBox="0 0 960 260" className="h-80 w-full">
                {[0, 1, 2, 3].map((grid) => (
                  <line
                    key={grid}
                    x1="20"
                    x2="920"
                    y1={35 + grid * 55}
                    y2={35 + grid * 55}
                    stroke="rgb(51 65 85)"
                    strokeDasharray="4 4"
                  />
                ))}

                <polyline
                  points={points}
                  fill="none"
                  stroke="rgb(59 130 246)"
                  strokeWidth="3"
                />
              </svg>

              <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500 md:grid-cols-5">
                <div>데이터 수: {rows.length}</div>
                <div>최근 일자: {latest?.date || "-"}</div>
                <div>고가: {latest ? money(latest.high, selected.market) : "-"}</div>
                <div>저가: {latest ? money(latest.low, selected.market) : "-"}</div>
                <div>거래량: {latest?.volume?.toLocaleString?.() || "-"}</div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
