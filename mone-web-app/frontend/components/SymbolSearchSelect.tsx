"use client";

import { useEffect, useMemo, useState } from "react";
import { mone, type Market } from "@/lib/api";

export interface MoneSymbol {
  id: string;
  symbol: string;
  name: string;
  market: "kr" | "us";
  label: string;
  isWatch?: boolean;
}

function normalize(item: any, index: number): MoneSymbol {
  const symbol = String(item.symbol || item.code || item.ticker || "").toUpperCase();
  const market = String(item.market || (symbol.match(/^\d{6}$/) ? "kr" : "us")).toLowerCase() as "kr" | "us";
  const rawName = String(item.name || item.company || "").trim();
  const name = rawName && rawName !== symbol ? rawName : symbol;
  return {
    id: String(item.id || `${market}-${symbol}-${index}`),
    symbol,
    name,
    market,
    label: `${name} (${symbol})`,
    isWatch: Boolean(item.isWatch),
  };
}

function dedupe(items: MoneSymbol[]) {
  const seen = new Set<string>();
  const out: MoneSymbol[] = [];
  for (const item of items) {
    const key = `${item.market}-${item.symbol}`;
    if (!item.symbol || seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

export default function SymbolSearchSelect({
  market = "all",
  value = "",
  watchOnly = false,
  onChange,
  className = "",
}: {
  market?: Market;
  value?: string;
  watchOnly?: boolean;
  onChange: (symbol: MoneSymbol | null) => void;
  className?: string;
}) {
  const [symbols, setSymbols] = useState<MoneSymbol[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(value);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);

    mone
      .symbols({ market, watchOnly, limit: 10000 })
      .then((data) => {
        if (!alive) return;
        const next = Array.isArray(data.items) ? data.items.map(normalize) : [];
        setSymbols(dedupe(next));
      })
      .catch(() => {
        if (!alive) return;
        setSymbols([]);
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [market, watchOnly]);

  useEffect(() => {
    setSelected(value || "");
  }, [value]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q
      ? symbols.filter((item) => {
          return (
            item.symbol.toLowerCase().includes(q) ||
            item.name.toLowerCase().includes(q) ||
            item.label.toLowerCase().includes(q)
          );
        })
      : symbols;

    return base.slice(0, 500);
  }, [symbols, query]);

  function select(symbol: string) {
    setSelected(symbol);

    if (!symbol) {
      onChange(null);
      return;
    }

    const found = symbols.find((item) => item.symbol === symbol) || null;
    onChange(found);
  }

  return (
    <div className={`rounded-2xl border border-slate-800 bg-slate-950/40 p-3 ${className}`}>
      <div className="flex flex-col gap-2 md:flex-row">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="종목명 또는 종목코드 검색"
          className="h-11 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-blue-500"
        />

        <select
          value={selected}
          onChange={(event) => select(event.target.value)}
          className="h-11 min-w-[300px] rounded-xl border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:border-blue-500"
        >
          <option value="">전체 종목 보기</option>

          {filtered.map((item, index) => (
            <option key={`${item.market}-${item.symbol}-${index}`} value={item.symbol}>
              {item.isWatch ? "★ " : ""}
              {item.name} ({item.symbol})
            </option>
          ))}
        </select>
      </div>

      <div className="mt-2 text-xs text-slate-500">
        {loading
          ? "종목을 불러오는 중..."
          : `전체 ${symbols.length.toLocaleString("ko-KR")}개 중 ${filtered.length.toLocaleString("ko-KR")}개 표시`}
      </div>
    </div>
  );
}
