"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone } from "@/lib/api";

type TickerItem = {
  id: string;
  symbol: string;
  name: string;
  market: string;
  currentPrice?: number;
  currentPriceText?: string;
  changePctText?: string;
};

const KR_NAME_MAP: Record<string, string> = {
  "005930": "삼성전자",
  "000660": "SK하이닉스",
  "005380": "현대차",
  "003490": "대한항공",
  "373220": "LG에너지솔루션",
  "015760": "한국전력",
  "058470": "리노공업",
  "006400": "삼성SDI",
  "035420": "NAVER",
  "035720": "카카오",
  "207940": "삼성바이오로직스",
  "196170": "알테오젠",
  "086520": "에코프로",
};

const US_NAME_MAP: Record<string, string> = {
  NVDA: "NVIDIA",
  GOOGL: "Alphabet",
  GOOG: "Alphabet",
  TSLA: "Tesla",
  AAPL: "Apple",
  MSFT: "Microsoft",
  AMZN: "Amazon",
};

function displayName(symbol: string, market: string, raw?: string) {
  const sym = String(symbol || "").toUpperCase();
  const mapped = market === "kr" ? KR_NAME_MAP[sym] : US_NAME_MAP[sym];
  const name = String(raw || "").trim();
  return mapped || (name && name !== sym ? name : sym);
}

function priceText(value: unknown, market: string, fallback?: string) {
  const n = Number(String(value ?? "").replace(/[^0-9.-]/g, ""));
  if (Number.isFinite(n) && n > 0) {
    return market === "us" ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `${Math.round(n).toLocaleString("ko-KR")}원`;
  }
  return fallback && fallback !== "-" ? fallback : "현재가 산출 필요";
}

function unique(items: TickerItem[]) {
  const seen = new Set<string>();
  const out: TickerItem[] = [];
  for (const item of items) {
    const symbol = String(item.symbol || "").toUpperCase();
    const market = String(item.market || (symbol.match(/^\d{6}$/) ? "kr" : "us")).toLowerCase();
    const key = `${market}-${symbol}`;
    if (!symbol || seen.has(key)) continue;
    seen.add(key);
    out.push({ ...item, symbol, market, name: displayName(symbol, market, item.name) });
  }
  return out;
}

async function fetchHoldings(): Promise<TickerItem[]> {
  const data: any = await mone.holdingsClean({ market: "all", limit: 50 });
  const rows = Array.isArray(data?.items) ? data.items : [];
  return rows.map((row: any, index: number) => {
    const symbol = String(row.symbol || row.code || "").toUpperCase();
    const market = String(row.market || (symbol.match(/^\d{6}$/) ? "kr" : "us")).toLowerCase();
    return {
      id: `holding-${market}-${symbol}-${index}`,
      symbol,
      name: displayName(symbol, market, row.name),
      market,
      currentPrice: Number(row.currentPrice || 0),
      currentPriceText: priceText(row.currentPrice, market, row.currentPriceText),
      changePctText: row.changePctText || "+0.00%",
    };
  });
}

async function fetchWatch(): Promise<TickerItem[]> {
  const data: any = await mone.symbols({ market: "all", limit: 20 });
  const rows = Array.isArray(data?.items) ? data.items : [];
  return rows.map((row: any, index: number) => {
    const symbol = String(row.symbol || "").toUpperCase();
    const market = String(row.market || (symbol.match(/^\d{6}$/) ? "kr" : "us")).toLowerCase();
    return {
      id: `watch-${market}-${symbol}-${index}`,
      symbol,
      name: displayName(symbol, market, row.name),
      market,
      currentPrice: Number(row.currentPrice || row.price || 0),
      currentPriceText: priceText(row.currentPrice || row.price, market, row.currentPriceText),
      changePctText: row.changePctText || "+0.00%",
    };
  });
}

export default function TopHoldingTicker() {
  const [items, setItems] = useState<TickerItem[]>([]);
  const [source, setSource] = useState("불러오는 중");
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const holdings = unique(await fetchHoldings());
      if (holdings.length) {
        setItems(holdings.slice(0, 12));
        setSource("보유종목");
        return;
      }
      const watch = unique(await fetchWatch());
      setItems(watch.slice(0, 12));
      setSource("관심종목");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, []);

  const displayItems = useMemo(() => {
    const fallback: TickerItem[] = [
      { id: "fallback-kr-005930", symbol: "005930", name: "삼성전자", market: "kr", currentPrice: 0, currentPriceText: "현재가 산출 필요", changePctText: "+0.00%" },
      { id: "fallback-kr-000660", symbol: "000660", name: "SK하이닉스", market: "kr", currentPrice: 0, currentPriceText: "현재가 산출 필요", changePctText: "+0.00%" },
    ];
    const base = items.length ? items : fallback;
    return [...base, ...base];
  }, [items]);

  return (
    <div className="flex h-8 min-w-0 flex-1 items-center gap-3 overflow-hidden">
      <span className="hidden shrink-0 rounded-md border border-slate-800 bg-slate-950/70 px-2 py-1 text-[10px] font-bold tracking-[0.18em] text-slate-500 lg:inline">
        {source}
      </span>
      <div className="relative min-w-0 flex-1 overflow-hidden" style={{ maskImage: "linear-gradient(to right, transparent, black 8%, black 92%, transparent)" }}>
        <div className="flex w-max animate-[moneTicker_45s_linear_infinite] items-center gap-7 whitespace-nowrap">
          {displayItems.map((item, index) => (
            <span key={`${item.id}-${index}`} className="inline-flex items-center gap-2 text-xs">
              <span className="font-semibold text-slate-300">{displayName(item.symbol, item.market, item.name)}</span>
              <span className="font-mono text-slate-100">{item.currentPriceText || priceText(item.currentPrice, item.market)}</span>
              <span className={(item.changePctText || "").startsWith("-") ? "font-mono text-red-400" : "font-mono text-emerald-400"}>
                {item.changePctText || "+0.00%"}
              </span>
            </span>
          ))}
        </div>
      </div>
      <button onClick={load} className="shrink-0 rounded-lg border border-slate-800 bg-slate-900/70 p-1.5 text-slate-500 hover:text-slate-200" title="상단 티커 새로고침">
        <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
      </button>
    </div>
  );
}
