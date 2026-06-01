"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone } from "@/lib/api";
import { dedupeBySymbol, displayName, formatMoney, normalizeMarket, normalizeSymbol, pctText, toNumber } from "@/lib/moneDisplay";

type TickerItem = {
  id: string;
  symbol: string;
  name: string;
  market: "kr" | "us";
  currentPriceText: string;
  changePctText: string;
  changeStatus?: "normal" | "pending" | "no-base" | "stale" | "error";
};

function derivePrice(row: any, market: string) {
  const text = String(row.currentPriceText || row.priceText || "").trim();
  if (text && text !== "-" && !text.includes("산출")) return text.replace(/₩/g, "");
  return formatMoney(row.currentPrice ?? row.price, market, "가격 확인 필요");
}

function deriveChange(row: any): { text: string; status: TickerItem["changeStatus"] } {
  const direct = String(row.changePctText || row.changeText || "").trim();
  if (direct && direct !== "-" && direct.includes("%")) return { text: direct, status: "normal" };

  const numeric = toNumber(row.changePct ?? row.changeRate);
  if (numeric !== null && Number.isFinite(numeric) && numeric !== 0) {
    return { text: pctText(numeric), status: "normal" };
  }

  const current = toNumber(row.currentPrice ?? row.price ?? row.currentPriceText);
  const prev = toNumber(row.prevClose ?? row.previousClose ?? row.prevCloseText);
  if (current !== null && prev !== null && prev > 0) {
    return { text: pctText(((current - prev) / prev) * 100), status: "normal" };
  }

  if (current === null || current <= 0) return { text: "현재가 수집 대기", status: "pending" };
  return { text: "전일 기준 없음", status: "no-base" };
}

async function fetchTickerRows(): Promise<TickerItem[]> {
  const data: any = await mone.holdingsClean({ market: "all", limit: 50 });
  const rows = dedupeBySymbol(Array.isArray(data?.items) ? data.items : []);
  return rows.map((row: any, index: number) => {
    const symbol = normalizeSymbol(row);
    const market = normalizeMarket(row.market, symbol);
    const change = deriveChange(row);
    return {
      id: `holding-${market}-${symbol}-${index}`,
      symbol,
      market,
      name: displayName(row),
      currentPriceText: derivePrice(row, market),
      changePctText: change.text,
      changeStatus: change.status,
    };
  });
}

export default function TopHoldingTicker() {
  const [items, setItems] = useState<TickerItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const holdings = await fetchTickerRows();
      setItems(holdings.slice(0, 13));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, []);

  const displayItems = useMemo(() => (items.length ? [...items, ...items] : []), [items]);

  return (
    <div className="flex h-8 min-w-0 flex-1 items-center gap-3 overflow-hidden">
      <span className="hidden shrink-0 rounded-md border border-slate-800 bg-slate-950/70 px-2 py-1 text-[10px] font-bold tracking-[0.18em] text-slate-500 lg:inline">
        보유 티커 {items.length ? `${items.length}개` : loading ? "로딩" : "대기"}
      </span>

      <div className="relative min-w-0 flex-1 overflow-hidden" style={{ maskImage: "linear-gradient(to right, transparent, black 8%, black 92%, transparent)" }}>
        {error ? (
          <div className="text-xs text-red-300">티커 데이터 연결 확인 필요</div>
        ) : displayItems.length === 0 ? (
          <div className="text-xs text-slate-500">보유종목 티커를 불러오는 중...</div>
        ) : (
          <div className="flex w-max animate-[moneTicker_45s_linear_infinite] items-center gap-7 whitespace-nowrap">
            {displayItems.map((item, index) => {
              const isDown = item.changePctText.startsWith("-");
              const needsPrice = item.currentPriceText.includes("확인") || item.currentPriceText.includes("대기");
              const needsBase = item.changeStatus && item.changeStatus !== "normal";
              return (
                <span key={`${item.id}-${index}`} className="inline-flex items-center gap-2 text-xs">
                  <span className="font-semibold text-slate-200">{item.name}</span>
                  <span className="font-mono text-slate-500">{item.symbol}</span>
                  <span className={`font-mono ${needsPrice ? "text-amber-300" : "text-slate-100"}`}>{item.currentPriceText}</span>
                  <span className={isDown ? "font-mono text-red-400" : needsBase ? "font-mono text-amber-300" : "font-mono text-emerald-400"}>
                    {item.changePctText}
                  </span>
                </span>
              );
            })}
          </div>
        )}
      </div>

      <button onClick={load} className="shrink-0 rounded-lg border border-slate-800 bg-slate-900/70 p-1.5 text-slate-500 hover:text-slate-200" title="상단 티커 새로고침">
        <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
      </button>
    </div>
  );
}
