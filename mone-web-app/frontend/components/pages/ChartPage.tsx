"use client";

import { useEffect, useMemo, useState } from "react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, money, type Market } from "@/lib/api";
import { displayName, normalizeMarket, normalizeSymbol, priceText } from "@/lib/moneDisplay";

function toSymbol(item: any, index = 0): MoneSymbol | null {
  const symbol = normalizeSymbol(item);
  if (!symbol) return null;
  const market = normalizeMarket(item?.market, symbol);
  const name = displayName(item);
  return {
    id: String(item?.id || `${market}-${symbol}-${index}`),
    symbol,
    name,
    market,
    label: `${name} (${symbol})`,
    isWatch: Boolean(item?.isWatch || item?.watch),
  };
}

function fallbackSymbol(market: Market): MoneSymbol {
  if (market === "us") return { id: "us-NVDA", symbol: "NVDA", name: "NVIDIA", market: "us", label: "NVIDIA (NVDA)", isWatch: true };
  return { id: "kr-131970", symbol: "131970", name: "두산테스나", market: "kr", label: "두산테스나 (131970)", isWatch: true };
}

function levelValue(levels: any, key: "entry" | "stop" | "target" | "expected") {
  const keys: Record<typeof key, string[]> = {
    entry: ["entry", "entryPrice"],
    stop: ["stop", "stopLoss", "stopPrice"],
    target: ["target", "targetPrice"],
    expected: ["expectedPrice", "expected"],
  };
  for (const name of keys[key]) {
    const value = Number(levels?.[name]);
    if (Number.isFinite(value) && value > 0) return value;
  }
  return 0;
}

export default function ChartPage() {
  const [market, setMarket] = useState<Market>("all");
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [levels, setLevels] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [seedLoading, setSeedLoading] = useState(false);

  useEffect(() => {
    let active = true;
    if (selected) return;

    async function selectInitialSymbol() {
      setSeedLoading(true);
      try {
        const holdings = await mone.holdingsClean({ market, limit: 20 });
        if (!active || selected) return;
        const holding = Array.isArray(holdings.items) ? holdings.items.map(toSymbol).find(Boolean) : null;
        if (holding) {
          setSelected(holding);
          return;
        }

        const recommendations = await mone.recommendations({ market, mode: "balanced", horizon: "swing", limit: 20 });
        if (!active || selected) return;
        const candidate = Array.isArray(recommendations.items) ? recommendations.items.map(toSymbol).find(Boolean) : null;
        setSelected(candidate || fallbackSymbol(market));
      } finally {
        if (active) setSeedLoading(false);
      }
    }

    selectInitialSymbol();
    return () => {
      active = false;
    };
  }, [market, selected]);

  useEffect(() => {
    if (!selected) {
      setRows([]);
      setLevels(null);
      return;
    }

    let active = true;
    setLoading(true);
    Promise.all([
      mone.ohlcv({ market: selected.market, symbol: selected.symbol, limit: 260 }),
      mone.recommendations({ market: selected.market, mode: "balanced", horizon: "swing", limit: 300 }),
    ])
      .then(([chartData, recommendationData]) => {
        if (!active) return;
        setRows(Array.isArray(chartData.items) ? chartData.items : []);
        const matched = Array.isArray(recommendationData.items)
          ? recommendationData.items.find((item: any) => normalizeSymbol(item) === selected.symbol)
          : null;
        setLevels(matched || null);
      })
      .catch(() => {
        if (active) {
          setRows([]);
          setLevels(null);
        }
      })
      .finally(() => active && setLoading(false));

    return () => {
      active = false;
    };
  }, [selected]);

  const latest = rows.at(-1);
  const display = rows.slice(-90);
  const levelNumbers = ["entry", "stop", "target", "expected"].map((key) => levelValue(levels, key as any)).filter(Boolean);
  const max = useMemo(() => Math.max(...display.map((row) => Number(row.high || row.close || 0)), ...levelNumbers, 1), [display, levelNumbers]);
  const min = useMemo(() => Math.min(...display.map((row) => Number(row.low || row.close || max)), ...levelNumbers, max), [display, levelNumbers, max]);
  const y = (close: number) => (max === min ? 120 : 220 - ((close - min) / (max - min)) * 190);
  const points = display.map((row, index) => `${20 + (index / Math.max(display.length - 1, 1)) * 900},${y(Number(row.close || 0))}`).join(" ");
  const lines = [
    { key: "entry", label: "진입가", color: "rgb(16 185 129)", value: levelValue(levels, "entry") },
    { key: "stop", label: "손절가", color: "rgb(248 113 113)", value: levelValue(levels, "stop") },
    { key: "target", label: "목표가", color: "rgb(34 211 238)", value: levelValue(levels, "target") },
    { key: "expected", label: "예상가", color: "rgb(168 85 247)", value: levelValue(levels, "expected") },
  ].filter((line) => line.value > 0);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">차트·기술분석</h1>
        <p className="mt-1 text-sm text-slate-400">실제 OHLCV 가격 흐름과 추천 기준선을 함께 확인합니다.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "kr", "us"] as Market[]).map((item) => (
          <button
            key={item}
            onClick={() => {
              setMarket(item);
              setSelected(null);
            }}
            className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}
          >
            {item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}
          </button>
        ))}
      </div>

      <SymbolSearchSelect market={market} value={selected?.symbol || ""} onChange={setSelected} />

      {!selected && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
          {seedLoading ? "기본 종목을 불러오는 중..." : "종목명 또는 종목코드로 검색하거나 목록에서 종목을 선택하세요."}
        </div>
      )}

      {selected && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-bold text-slate-100">{selected.name}</h2>
              <p className="font-mono text-sm text-slate-500">{selected.symbol} · {selected.market.toUpperCase()}</p>
            </div>
            <div className="text-right">
              <div className="text-xs text-slate-500">최근 종가</div>
              <div className="font-mono text-xl font-bold text-emerald-400">{latest ? money(latest.close, selected.market) : "-"}</div>
            </div>
          </div>

          {loading && <div className="py-20 text-center text-slate-500">차트 데이터를 불러오는 중...</div>}

          {!loading && rows.length === 0 && (
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-8 text-center text-amber-200">
              이 종목의 OHLCV 데이터가 아직 연결되지 않았습니다. `data/market/ohlcv` 또는 `/api/ohlcv` 연결 상태를 확인해야 합니다.
            </div>
          )}

          {!loading && rows.length > 0 && (
            <div className="space-y-4">
              <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                <svg viewBox="0 0 960 260" className="h-80 w-full">
                  {[0, 1, 2, 3].map((grid) => (
                    <line key={grid} x1="20" x2="920" y1={35 + grid * 55} y2={35 + grid * 55} stroke="rgb(51 65 85)" strokeDasharray="4 4" />
                  ))}
                  {lines.map((line) => {
                    const yy = y(line.value);
                    return (
                      <g key={line.key}>
                        <line x1="20" x2="920" y1={yy} y2={yy} stroke={line.color} strokeDasharray={line.key === "entry" ? "0" : "6 5"} strokeWidth="1.5" />
                        <text x="925" y={yy + 4} fill={line.color} fontSize="12">{line.label}</text>
                      </g>
                    );
                  })}
                  <polyline points={points} fill="none" stroke="rgb(59 130 246)" strokeWidth="3" />
                </svg>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500 md:grid-cols-5">
                  <div>데이터 수: {rows.length}</div>
                  <div>최근 일자: {latest?.date || "-"}</div>
                  <div>고가: {latest ? money(latest.high, selected.market) : "-"}</div>
                  <div>저가: {latest ? money(latest.low, selected.market) : "-"}</div>
                  <div>거래량: {Number(latest?.volume || 0).toLocaleString("ko-KR")}</div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                <Info label="진입가" value={levels ? priceText(levels, "entry", "추천 기준 없음") : "추천 기준 없음"} />
                <Info label="손절가" value={levels ? priceText(levels, "stop", "추천 기준 없음") : "추천 기준 없음"} />
                <Info label="목표가" value={levels ? priceText(levels, "target", "추천 기준 없음") : "추천 기준 없음"} />
                <Info label="예상가" value={levels ? priceText(levels, "expected", "추천 기준 없음") : "추천 기준 없음"} />
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-400">
                고급 차트 기능은 준비 중입니다. 현재 버전은 실제 OHLCV 기본 차트와 추천 기준선 표시를 우선 제공합니다.
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 font-mono font-semibold text-slate-100">{value}</div>
    </div>
  );
}
