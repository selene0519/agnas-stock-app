"use client";

import { useEffect, useMemo, useState } from "react";
import { mone, type Market } from "@/lib/api";
import { dedupeBySymbol, displayName, normalizeMarket, normalizeSymbol } from "@/lib/moneDisplay";

export interface MoneSymbol { id: string; symbol: string; name: string; market: "kr" | "us"; label: string; isWatch?: boolean; }

function normalize(item: any, index: number): MoneSymbol {
  const symbol = normalizeSymbol(item);
  const market = normalizeMarket(item.market, symbol);
  const name = displayName(item);
  return { id: String(item.id || `${market}-${symbol}-${index}`), symbol, name, market, label: `${name} (${symbol})`, isWatch: Boolean(item.isWatch || item.watch) };
}

export default function SymbolSearchSelect({ market = "all", value = "", watchOnly = false, onChange, className = "" }: { market?: Market; value?: string; watchOnly?: boolean; onChange: (symbol: MoneSymbol | null) => void; className?: string }) {
  const [symbols, setSymbols] = useState<MoneSymbol[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(value);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.allSettled([mone.symbols({ market, watchOnly, limit: 10000 }), mone.holdingsClean({ market, limit: 500 }), mone.recommendations({ market, mode: "balanced", horizon: "swing", limit: 500 })])
      .then((results) => {
        if (!alive) return;
        const raw = results.flatMap((result: any) => result.status === "fulfilled" && Array.isArray(result.value?.items) ? result.value.items : []);
        const next = dedupeBySymbol(raw).map(normalize).filter((item) => !watchOnly || item.isWatch || true);
        setSymbols(next);
      })
      .catch(() => alive && setSymbols([]))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [market, watchOnly]);

  useEffect(() => { setSelected(value || ""); }, [value]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q ? symbols.filter((item) => item.symbol.toLowerCase().includes(q) || item.name.toLowerCase().includes(q) || item.label.toLowerCase().includes(q)) : symbols;
    return base.slice(0, 500);
  }, [symbols, query]);

  function select(symbol: string) { setSelected(symbol); onChange(symbol ? symbols.find((item) => item.symbol === symbol) || null : null); }

  return <div className={`rounded-2xl border border-slate-800 bg-slate-950/40 p-3 ${className}`}><div className="flex flex-col gap-2 md:flex-row"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="종목명 또는 종목코드 검색" className="h-11 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-blue-500" /><select value={selected} onChange={(event) => select(event.target.value)} className="h-11 min-w-[300px] rounded-xl border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus:border-blue-500"><option value="">전체 종목 보기</option>{filtered.map((item, index) => <option key={`${item.market}-${item.symbol}-${index}`} value={item.symbol}>{item.isWatch ? "★ " : ""}{item.name} ({item.symbol})</option>)}</select></div><div className="mt-2 text-xs text-slate-500">{loading ? "종목을 불러오는 중..." : `전체 ${symbols.length.toLocaleString("ko-KR")}개 중 ${filtered.length.toLocaleString("ko-KR")}개 표시`}</div></div>;
}
