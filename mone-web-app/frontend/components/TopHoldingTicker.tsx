"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone } from "@/lib/api";
import { getUserId } from "@/lib/userId";
import {
  dedupeBySymbol,
  displayName,
  formatMoney,
  normalizeMarket,
  normalizeSymbol,
  pctText,
  toNumber,
} from "@/lib/moneDisplay";

type TickerSource = "holdings" | "watchlist" | "recommendations";

type TickerItem = {
  id: string;
  symbol: string;
  name: string;
  market: "kr" | "us";
  currentPriceText: string;
  changePctText: string;
  changeStatus: "normal" | "pending" | "no-base" | "stale" | "error";
  source: TickerSource;
};

function closeValue(row: any) {
  return toNumber(row?.close ?? row?.Close ?? row?.stck_clpr ?? row?.currentPrice);
}

function ohlcvFallbackChange(rows: any[], current: number | null): { text: string; status: TickerItem["changeStatus"] } | null {
  const closes = (rows || [])
    .map((row) => closeValue(row))
    .filter((value): value is number => value !== null && Number.isFinite(value) && value > 0);
  if (closes.length < 2) return null;
  const latest = current && current > 0 ? current : closes.at(-1)!;
  const prev = closes.at(-2)!;
  if (prev <= 0) return null;
  return { text: pctText(((latest - prev) / prev) * 100), status: "normal" };
}

function derivePrice(row: any, market: string, ohlcvRows: any[] = []) {
  const text = String(row.currentPriceText || row.priceText || row.closeText || "").trim();
  if (text && text !== "-") return text;
  const direct = toNumber(row.currentPrice ?? row.price ?? row.close);
  if (direct && direct > 0) return formatMoney(direct, market, "가격 대기");
  // OHLCV latest close 사용
  const closes = ohlcvRows
    .map((r) => toNumber(r?.close ?? r?.Close ?? r?.stck_clpr))
    .filter((v): v is number => v !== null && v > 0);
  if (closes.length > 0) return formatMoney(closes.at(-1)!, market, "가격 대기");
  return "가격 대기";
}

function deriveChange(row: any, fallbackRows: any[] = []): { text: string; status: TickerItem["changeStatus"] } {
  const current = toNumber(row.currentPrice ?? row.price ?? row.close ?? row.currentPriceText);
  if (current === null || current <= 0) {
    const ohlcvFallback = ohlcvFallbackChange(fallbackRows, null);
    if (ohlcvFallback) return ohlcvFallback;
    return { text: "가격 대기", status: "pending" };
  }

  const direct = String(
    row.changePctText || row.priceChangePercentText || row.changeText || row.priceChangeText || ""
  ).trim();
  if (direct && direct !== "-" && direct.includes("%")) return { text: direct, status: "normal" };

  const numeric = toNumber(row.changePct ?? row.changePercent ?? row.priceChangePercent ?? row.changeRate);
  if (numeric !== null && Number.isFinite(numeric)) return { text: pctText(numeric), status: "normal" };

  const prev = toNumber(row.prevClose ?? row.previousClose ?? row.prevCloseText);
  if (prev !== null && prev > 0) {
    return { text: pctText(((current - prev) / prev) * 100), status: "normal" };
  }

  const fallback = ohlcvFallbackChange(fallbackRows, current);
  if (fallback) return fallback;

  return { text: "", status: "no-base" };
}

async function enrichRows(rows: any[], source: TickerSource): Promise<TickerItem[]> {
  const sliced = dedupeBySymbol(rows).slice(0, 13);
  const enriched = await Promise.all(
    sliced.map(async (row: any) => {
      const symbol = normalizeSymbol(row);
      const market = normalizeMarket(row.market, symbol);
      const preliminary = deriveChange(row);
      // "normal"이면 OHLCV 불필요, 그 외(pending 포함)는 가격·등락률 보완용 조회
      if (preliminary.status === "normal") return { row, ohlcvRows: [] };
      try {
        const data = await mone.ohlcv({ market, symbol, limit: 10 });
        return { row, ohlcvRows: Array.isArray(data?.items) ? data.items : [] };
      } catch {
        return { row, ohlcvRows: [] };
      }
    })
  );

  return enriched.map(({ row, ohlcvRows }: any, index: number) => {
    const symbol = normalizeSymbol(row);
    const market = normalizeMarket(row.market, symbol);
    const change = deriveChange(row, ohlcvRows);
    return {
      id: `${source}-${market}-${symbol}-${index}`,
      symbol,
      market,
      name: displayName(row),
      currentPriceText: derivePrice(row, market, ohlcvRows),
      changePctText: change.text,
      changeStatus: change.status,
      source,
    };
  });
}

async function fetchWatchlistRows(): Promise<any[]> {
  const [kr, us] = await Promise.all([
    mone.watchlist({ market: "kr", limit: 20 }).catch(() => null),
    mone.watchlist({ market: "us", limit: 20 }).catch(() => null),
  ]);
  return [
    ...(Array.isArray(kr?.items) ? kr.items : []),
    ...(Array.isArray(us?.items) ? us.items : []),
  ];
}

async function fetchRecommendationRows(): Promise<any[]> {
  const [kr, us] = await Promise.all([
    mone.recommendations({ market: "kr", mode: "balanced", horizon: "swing", limit: 20 }).catch(() => null),
    mone.recommendations({ market: "us", mode: "balanced", horizon: "swing", limit: 20 }).catch(() => null),
  ]);
  return [
    ...(Array.isArray(kr?.items) ? kr.items : []),
    ...(Array.isArray(us?.items) ? us.items : []),
  ];
}

async function fetchTickerRows(): Promise<TickerItem[]> {
  const userId = getUserId();
  const data: any = await mone.holdingsClean({ market: "all", limit: 50 });
  const holdingsRows = Array.isArray(data?.items) ? data.items : [];
  const isPersonalHoldings = Boolean(userId) && data?.authority === "personal_user_holdings";
  if (isPersonalHoldings && holdingsRows.length > 0) return enrichRows(holdingsRows, "holdings");

  const watchlistRows = await fetchWatchlistRows();
  if (watchlistRows.length > 0) return enrichRows(watchlistRows, "watchlist");

  return enrichRows(await fetchRecommendationRows(), "recommendations");
}

function labelForSource(item?: TickerItem) {
  if (!item) return "추천 대기";
  if (item.source === "holdings") return "보유 티커";
  if (item.source === "watchlist") return "관심 티커";
  return "추천 티커";
}

export default function TopHoldingTicker() {
  const [items, setItems] = useState<TickerItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const tickerRows = await fetchTickerRows();
      setItems(tickerRows.slice(0, 13));
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
    window.addEventListener("mone-holdings-updated", load);
    window.addEventListener("mone-watchlist-updated", load);
    return () => {
      window.removeEventListener("focus", load);
      window.removeEventListener("mone-holdings-updated", load);
      window.removeEventListener("mone-watchlist-updated", load);
    };
  }, []);

  const displayItems = useMemo(() => (items.length ? [...items, ...items] : []), [items]);
  const tickerLabel = labelForSource(items[0]);

  return (
    <div className="flex h-8 min-w-0 flex-1 items-center gap-3 overflow-hidden">
      <span className="hidden shrink-0 rounded-md border border-slate-800 bg-slate-950/70 px-2 py-1 text-[10px] font-bold tracking-[0.18em] text-slate-500 lg:inline">
        {tickerLabel} {items.length ? `${items.length}개` : loading ? "로딩" : "0개"}
      </span>

      <div
        className="relative min-w-0 flex-1 overflow-hidden"
        style={{
          maskImage: "linear-gradient(to right, transparent, black 8%, black 92%, transparent)",
          WebkitMaskImage: "linear-gradient(to right, transparent, black 8%, black 92%, transparent)",
        }}
      >
        {error ? (
          <div className="text-xs text-red-300">티커 데이터 연결 확인 필요</div>
        ) : displayItems.length === 0 ? (
          <div className="text-xs text-slate-500">추천/관심 티커를 불러오는 중...</div>
        ) : (
          <div className="flex w-max animate-[moneTicker_45s_linear_infinite] items-center gap-7 whitespace-nowrap">
            {displayItems.map((item, index) => {
              const isDown = item.changePctText.startsWith("-");
              const needsPrice = item.changeStatus === "pending";
              const needsBase = item.changeStatus !== "normal" && item.changeStatus !== "pending";
              const showChange = item.changeStatus === "normal" && item.changePctText;
              return (
                <span key={`${item.id}-${index}`} className="inline-flex items-center gap-2 text-xs">
                  <span className="font-semibold text-slate-200">{item.name}</span>
                  <span className="font-mono text-slate-500">{item.symbol}</span>
                  <span className={`font-mono ${needsPrice ? "text-amber-300" : "text-slate-100"}`}>{item.currentPriceText}</span>
                  {showChange && (
                    <span className={isDown ? "font-mono text-red-400" : needsBase ? "font-mono text-amber-300" : "font-mono text-emerald-400"}>
                      {item.changePctText}
                    </span>
                  )}
                </span>
              );
            })}
          </div>
        )}
      </div>

      <button
        onClick={load}
        className="shrink-0 rounded-lg border border-slate-800 bg-slate-900/70 p-1.5 text-slate-500 hover:text-slate-200"
        title="상단 티커 새로고침"
      >
        <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
      </button>
    </div>
  );
}
