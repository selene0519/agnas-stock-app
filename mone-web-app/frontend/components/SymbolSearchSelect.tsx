"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { mone, type Market } from "@/lib/api";

export type MoneSymbol = {
  symbol: string;
  name: string;
  market: Market;
  label?: string;
  isWatch?: boolean;
  currentPrice?: number | string | null;
  currentPriceText?: string;
  priceSource?: string;
  source?: string;
  dataStatus?: string;
  [key: string]: any;
};

type Props = {
  market?: Market;
  watchOnly?: boolean;
  value?: string;
  onChange?: (item: MoneSymbol | null) => void;
  onResults?: (items: MoneSymbol[], query: string) => void;
  placeholder?: string;
  className?: string;
};

function normalizeMarket(value: any): Market {
  const v = String(value || "all").toLowerCase();
  if (v === "kr" || v === "us" || v === "all") return v;
  return "all";
}

function cleanText(value: any) {
  return String(value ?? "").trim();
}

export default function SymbolSearchSelect({
  market = "all",
  watchOnly = false,
  value = "",
  onChange,
  onResults,
  placeholder = "종목명 또는 종목코드 검색",
  className = "",
}: Props) {
  const [query, setQuery] = useState(value || "");
  const [items, setItems] = useState<MoneSymbol[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const suppressNextSearchRef = useRef(false);

  useEffect(() => {
    suppressNextSearchRef.current = true;
    setQuery(value || "");
    setItems([]);
    setOpen(false);
    setLoading(false);
  }, [value]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!boxRef.current) return;
      if (!boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, []);

  useEffect(() => {
    let active = true;
    const q = query.trim();

    if (suppressNextSearchRef.current) {
      suppressNextSearchRef.current = false;
      onResults?.([], q);
      return;
    }

    if (!q) {
      setItems([]);
      setLoading(false);
      onResults?.([], "");
      return;
    }

    const timer = window.setTimeout(() => {
      setLoading(true);
      mone
        .symbols({
          market: normalizeMarket(market),
          q,
          watchOnly,
          limit: 50,
        } as any)
        .then((payload: any) => {
          if (!active) return;
          const rows = Array.isArray(payload?.items) ? payload.items : [];
          const normalized = rows
            .map((row: any) => ({
              ...row,
              symbol: cleanText(row.symbol || row.code || row.ticker),
              name: cleanText(row.name || row.companyName || row.company_name || row.symbol),
              market: normalizeMarket(row.market || market),
              label: cleanText(row.label || `${row.name || row.symbol} ${row.symbol || ""}`),
              currentPrice: row.currentPrice ?? row.price ?? row.last ?? row.close ?? null,
              currentPriceText: cleanText(row.currentPriceText || row.priceText || ""),
              priceSource: cleanText(row.priceSource || row.source || ""),
              source: cleanText(row.source || ""),
              dataStatus: cleanText(row.dataStatus || ""),
            }))
            .filter((row: MoneSymbol) => row.symbol && row.name);
          setItems(normalized);
          onResults?.(normalized, q);
          setOpen(true);
        })
        .catch(() => {
          if (active) {
            setItems([]);
            onResults?.([], q);
          }
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 180);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query, market, watchOnly, onResults]);

  const exact = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return items.find(
      (item) =>
        item.symbol.toLowerCase() === q ||
        item.name.toLowerCase() === q ||
        `${item.name} ${item.symbol}`.toLowerCase() === q,
    );
  }, [items, query]);

  const selectItem = (item: MoneSymbol) => {
    setQuery(item.name || item.symbol);
    setOpen(false);
    onChange?.(item);
  };

  const clear = () => {
    setQuery("");
    setItems([]);
    setOpen(false);
    onChange?.(null);
  };

  return (
    <div ref={boxRef} className={`relative ${className}`}>
      <div className="flex items-center gap-2 rounded-2xl border border-slate-800 bg-slate-950 px-4 py-3 focus-within:border-blue-500">
        <Search size={18} className="text-slate-500" />
        <input
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => query.trim() && setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && exact) selectItem(exact);
            if (event.key === "Escape") setOpen(false);
          }}
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent text-sm text-slate-100 outline-none placeholder:text-slate-600"
        />
        {query && (
          <button
            type="button"
            onClick={clear}
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-200"
            aria-label="검색어 지우기"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {open && query.trim() && (
        <div className="absolute z-50 mt-2 max-h-96 w-full overflow-auto rounded-2xl border border-slate-800 bg-slate-950 p-2 shadow-2xl">
          {loading && <div className="px-3 py-3 text-sm text-slate-500">검색 중...</div>}

          {!loading && items.length === 0 && (
            <div className="px-3 py-3 text-sm text-amber-300">
              검색 결과가 없습니다. 관심종목이 아니어도 전체 종목에서 검색합니다.
            </div>
          )}

          {!loading &&
            items.map((item) => (
              <button
                key={`${item.market}-${item.symbol}`}
                type="button"
                onClick={() => selectItem(item)}
                className="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-3 text-left hover:bg-slate-900"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold text-slate-100">{item.name}</div>
                  <div className="font-mono text-xs text-slate-500">
                    {item.symbol} / {String(item.market).toUpperCase()}
                    {item.isWatch ? " / 관심" : ""}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className={`font-mono text-xs ${item.currentPriceText ? "text-slate-300" : "text-amber-300"}`}>
                    {item.currentPriceText || "가격 확인 필요"}
                  </div>
                  <div className="text-[10px] text-slate-600">
                    {item.priceSource || item.source || (String(item.dataStatus || "").toUpperCase() === "PRICE_PENDING" ? "KIS 수집 대기" : item.dataStatus) || ""}
                  </div>
                </div>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
