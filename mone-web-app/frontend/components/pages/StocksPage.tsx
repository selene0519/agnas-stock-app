"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, Star } from "lucide-react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import {
  dedupeBySymbol,
  displayName,
  formatMoney,
  horizonLabel,
  modeLabel,
  priceText,
  probabilityText,
  toNumber,
} from "@/lib/moneDisplay";

type WatchRow = {
  market: Market;
  symbol: string;
  name: string;
  targetReason?: string;
};

type HoldingEditRow = {
  market: Market;
  symbol: string;
  name: string;
  quantity: number;
  avgPrice: number;
  targetReason?: string;
};

function Cell({
  label,
  value,
  tone = "normal",
}: {
  label: string;
  value?: string;
  tone?: "normal" | "blue" | "red" | "green" | "amber";
}) {
  const color =
    tone === "blue"
      ? "text-blue-300"
      : tone === "red"
        ? "text-red-400"
        : tone === "green"
          ? "text-emerald-400"
          : tone === "amber"
            ? "text-amber-300"
            : "text-slate-100";
  return (
    <div className="rounded-xl bg-slate-950 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`font-mono ${color}`}>{value || "-"}</div>
    </div>
  );
}

function qtyText(item: any, mode: Mode) {
  if (typeof window === "undefined") return "";
  const cash = Number(window.localStorage.getItem("mone_cash_amount") || "0");
  const price = toNumber(
    item.entryPrice ||
      item.entry ||
      item.entryText ||
      item.currentPrice ||
      item.currentPriceText,
  );
  if (!Number.isFinite(cash) || cash <= 0 || price === null || price <= 0)
    return "";
  const ratio =
    mode === "conservative" ? 0.02 : mode === "aggressive" ? 0.12 : 0.05;
  const qty = Math.floor((cash * ratio) / price);
  return qty > 0 ? `${qty.toLocaleString("ko-KR")}주` : "1주 미만";
}

function adjustedText(
  item: any,
  key: "stop" | "target" | "entry",
  mode: Mode,
  market: string,
) {
  const base = toNumber(
    key === "stop"
      ? item.stopPrice || item.stop || item.stopText
      : key === "target"
        ? item.targetPrice || item.target || item.targetText
        : item.entryPrice || item.entry || item.entryText,
  );
  const current = toNumber(
    item.currentPrice ||
      item.currentPriceText ||
      item.entryPrice ||
      item.entryText,
  );
  const price = base ?? current;
  if (price === null || price <= 0) return "-";
  if (key === "entry") return formatMoney(price, market);
  const modeAdj =
    mode === "conservative"
      ? key === "stop"
        ? 0.985
        : 0.97
      : mode === "aggressive"
        ? key === "stop"
          ? 0.97
          : 1.05
        : 1;
  return formatMoney(price * modeAdj, market);
}

function cleanMarket(value: any): Market {
  const v = String(value || "kr").toLowerCase();
  if (v === "us") return "us";
  if (v === "all") return "all";
  return "kr";
}

function cleanSymbol(symbol: any, market: Market) {
  const raw = String(symbol || "").trim();
  if (market === "kr")
    return raw
      .replace(/[^0-9]/g, "")
      .padStart(6, "0")
      .slice(-6);
  return raw.toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
}

function watchKey(row: { market?: any; symbol?: any }) {
  const market = cleanMarket(row.market || "kr");
  return `${market}-${cleanSymbol(row.symbol, market)}`;
}

function statusText(status?: string) {
  const value = String(status || "").toUpperCase();
  if (value === "NORMAL") return "정상";
  if (value === "PRICE_PENDING" || value === "NO_PRICE") return "KIS 수집 대기";
  if (value === "DATA_PENDING") return "데이터 수집 대기";
  if (value === "STALE") return "시세 갱신 필요";
  if (value === "ERROR") return "오류";
  return value || "";
}

function normalizeWatch(item: any): WatchRow {
  const market = cleanMarket(item.market);
  return {
    market: market === "all" ? "kr" : market,
    symbol: cleanSymbol(item.symbol || item.code || item.ticker, market),
    name: String(item.name || item.companyName || "").trim(),
    targetReason: item.targetReason,
  };
}

function normalizeHoldingEdit(item: any): HoldingEditRow | null {
  const market = cleanMarket(item.market);
  const clean = market === "all" ? "kr" : market;
  const symbol = cleanSymbol(item.symbol || item.code || item.ticker, clean);
  const quantity = Number(String(item.quantity ?? item.qty ?? "").replace(/,/g, ""));
  const avgPrice = Number(String(item.avgPrice ?? item.avg_price ?? item.averagePrice ?? "").replace(/,/g, ""));
  if (!symbol || !Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(avgPrice) || avgPrice <= 0) return null;
  return {
    market: clean,
    symbol,
    name: String(item.name || item.companyName || symbol).trim(),
    quantity,
    avgPrice,
    targetReason: item.targetReason,
  };
}

export default function StocksPage() {
  const [market, setMarket] = useState<Market>("all");
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [watchOnly, setWatchOnly] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [watchlist, setWatchlist] = useState<WatchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [watchSaving, setWatchSaving] = useState(false);
  const [watchMessage, setWatchMessage] = useState("");
  const [holdingMessage, setHoldingMessage] = useState("");
  const [holdingSaving, setHoldingSaving] = useState(false);
  const [searchResults, setSearchResults] = useState<MoneSymbol[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [, setCashVersion] = useState(0);

  async function loadWatchlist() {
    try {
      const data = await mone.watchlistEdit({ market: "all" });
      const rows = Array.isArray(data.items)
        ? data.items.map(normalizeWatch)
        : [];
      setWatchlist(rows.filter((row) => row.symbol));
    } catch {
      setWatchlist([]);
    }
  }

  async function saveWatchlist(
    nextRows: WatchRow[],
    message = "관심종목을 저장했습니다.",
  ) {
    setWatchSaving(true);
    setWatchMessage("");
    try {
      const unique = Array.from(
        new Map(
          nextRows
            .filter((row) => row.symbol)
            .map((row) => [watchKey(row), row]),
        ).values(),
      );
      const result = await mone.saveWatchlistEdit({ items: unique });
      if (result?.status === "ERROR")
        throw new Error(result.error || "관심종목 저장 실패");
      const saved = Array.isArray(result.items)
        ? result.items.map(normalizeWatch)
        : unique;
      setWatchlist(saved.filter((row) => row.symbol));
      setWatchMessage(message);
      window.dispatchEvent(new CustomEvent("mone-watchlist-updated"));
    } catch (error) {
      setWatchMessage(
        `저장 실패: ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setWatchSaving(false);
    }
  }

  useEffect(() => {
    const onCash = () => setCashVersion((value) => value + 1);
    window.addEventListener("mone-cash-updated", onCash);
    return () => window.removeEventListener("mone-cash-updated", onCash);
  }, []);

  useEffect(() => {
    loadWatchlist();
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    mone
      .recommendations({ market, mode, horizon, limit: 500, watchOnly })
      .then((data) => {
        if (!active) return;
        setItems(dedupeBySymbol(Array.isArray(data.items) ? data.items : []));
      })
      .catch(() => active && setItems([]))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [market, mode, horizon, watchOnly, watchlist.length]);

  const visible = useMemo(() => {
    if (!selected) return items;
    const selectedMarket = cleanMarket(selected.market || market || "kr");
    const selectedSymbol = cleanSymbol(selected.symbol, selectedMarket);
    const matched = items.filter((item) => {
      const itemMarket = cleanMarket(item.market || selectedMarket);
      return (
        cleanSymbol(item.symbol, itemMarket) === selectedSymbol &&
        (market === "all" || itemMarket === market)
      );
    });
    if (matched.length > 0) return matched;
    return [
      {
        market: selectedMarket === "all" ? "kr" : selectedMarket,
        symbol: selectedSymbol,
        name: selected.name || selectedSymbol,
        companyName: selected.name || selectedSymbol,
        currentPrice: selected.currentPrice,
        currentPriceText: selected.currentPriceText,
        priceSource: selected.priceSource,
        priceTime: selected.priceTime,
        sourceStatus: "SEARCH_ONLY",
        isSearchOnly: true,
      },
    ];
  }, [items, selected, market]);

  const selectedWatchRow = useMemo(() => {
    if (!selected) return null;
    const selectedMarket = cleanMarket(selected.market || market || "kr");
    return {
      market: selectedMarket === "all" ? "kr" : selectedMarket,
      symbol: cleanSymbol(selected.symbol, selectedMarket),
      name: selected.name || selected.symbol,
    } satisfies WatchRow;
  }, [selected, market]);

  const watchSet = useMemo(() => new Set(watchlist.map(watchKey)), [watchlist]);

  const handleSearchResults = useCallback((rows: MoneSymbol[], query: string) => {
    setSearchResults(rows);
    setSearchQuery(query);
  }, []);

  function selectSearchResult(row: MoneSymbol) {
    setSelected(row);
    setSearchResults([row]);
    setSearchQuery(row.name || row.symbol || "");
  }

  function isWatched(item: any) {
    return watchSet.has(watchKey(item));
  }

  function toggleWatch(item: any) {
    const row = normalizeWatch({
      market: item.market || market,
      symbol: item.symbol,
      name: displayName(item),
      targetReason: item.targetReason || "search_watch_added",
    });
    const key = watchKey(row);
    if (watchSet.has(key)) {
      saveWatchlist(
        watchlist.filter((watch) => watchKey(watch) !== key),
        `${row.name || row.symbol} 관심종목에서 삭제했습니다.`,
      );
    } else {
      saveWatchlist(
        [...watchlist, row],
        `${row.name || row.symbol} 관심종목에 등록했습니다.`,
      );
    }
  }

  async function addHoldingFromItem(item: any) {
    const itemMarket = cleanMarket(item.market || market || "kr");
    const clean = itemMarket === "all" ? "kr" : itemMarket;
    const symbol = cleanSymbol(item.symbol, clean);
    const name = displayName(item) || symbol;
    const current = toNumber(item.currentPrice || item.currentPriceText || item.price || item.close);
    const defaultPrice = current && current > 0 ? String(Math.round(current)) : "";
    const quantityText = window.prompt(`${name} 보유 수량을 입력하세요.`, "1");
    if (quantityText === null) return;
    const avgText = window.prompt(`${name} 평균단가를 입력하세요.`, defaultPrice);
    if (avgText === null) return;

    const quantity = Number(quantityText.replace(/,/g, ""));
    const avgPrice = Number(avgText.replace(/,/g, ""));
    if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isFinite(avgPrice) || avgPrice <= 0) {
      setHoldingMessage("보유 추가 실패: 수량과 평균단가는 0보다 큰 숫자여야 합니다.");
      return;
    }

    setHoldingSaving(true);
    setHoldingMessage("");
    try {
      const existing = await mone.holdingsEdit({ market: "all" });
      const existingRows = Array.isArray(existing.items)
        ? existing.items.map(normalizeHoldingEdit).filter(Boolean) as HoldingEditRow[]
        : [];
      const key = `${clean}-${symbol}`;
      const nextMap = new Map(existingRows.map((row) => [`${row.market}-${row.symbol}`, row]));
      nextMap.set(key, { market: clean, symbol, name, quantity, avgPrice, targetReason: "search_holding_added" });
      const result = await mone.saveHoldingsEdit({ items: Array.from(nextMap.values()) });
      if (result?.status === "ERROR") throw new Error(result.error || "보유종목 저장 실패");
      setHoldingMessage(`${name} 보유종목에 추가했습니다.`);
      window.dispatchEvent(new CustomEvent("mone-holdings-updated"));
    } catch (error) {
      setHoldingMessage(`보유 추가 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setHoldingSaving(false);
    }
  }

  const marketTabs: { id: Market; label: string }[] = [
    { id: "all", label: "전체" },
    { id: "kr", label: "국장" },
    { id: "us", label: "미장" },
  ];
  const modeTabs: { id: Mode; label: string; desc: string }[] = [
    { id: "conservative", label: "보수", desc: "좁은 손절·안정 우선" },
    { id: "balanced", label: "균형", desc: "기회와 위험 균형" },
    { id: "aggressive", label: "공격", desc: "목표폭·모멘텀 우선" },
  ];
  const horizonTabs: { id: Horizon; label: string; desc: string }[] = [
    { id: "short", label: "단기", desc: "1~3일" },
    { id: "swing", label: "스윙", desc: "3~10일" },
    { id: "mid", label: "중기", desc: "2주 이상" },
  ];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">종목 탐색</h1>
        <p className="mt-1 text-sm text-slate-400">
          관심종목과 전체 후보를 시장, 투자 성향, 투자 기간 기준으로 탐색합니다.
        </p>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">
          시장
        </div>
        <div className="flex flex-wrap gap-2">
          {marketTabs.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setMarket(item.id);
                setSelected(null);
              }}
              className={`rounded-xl px-4 py-2 text-sm ${market === item.id ? "bg-blue-600 text-white" : "bg-slate-950 text-slate-400"}`}
            >
              {item.label}
            </button>
          ))}
          <button
            onClick={() => setWatchOnly(!watchOnly)}
            className={`rounded-xl px-4 py-2 text-sm ${watchOnly ? "bg-amber-500 text-slate-950" : "bg-slate-950 text-slate-400"}`}
          >
            관심종목만 보기
          </button>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">
              투자 성향
            </div>
            <div className="grid grid-cols-3 gap-2">
              {modeTabs.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setMode(item.id)}
                  className={`rounded-xl border p-3 text-left ${mode === item.id ? "border-emerald-500 bg-emerald-500/10 text-white" : "border-slate-800 bg-slate-950 text-slate-400"}`}
                >
                  <div className="font-bold">{item.label}</div>
                  <div className="mt-1 text-[11px] text-slate-500">
                    {item.desc}
                  </div>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">
              투자 기간
            </div>
            <div className="grid grid-cols-3 gap-2">
              {horizonTabs.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setHorizon(item.id)}
                  className={`rounded-xl border p-3 text-left ${horizon === item.id ? "border-cyan-500 bg-cyan-500/10 text-white" : "border-slate-800 bg-slate-950 text-slate-400"}`}
                >
                  <div className="font-bold">{item.label}</div>
                  <div className="mt-1 text-[11px] text-slate-500">
                    {item.desc}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_auto]">
        <SymbolSearchSelect
          market={market}
          watchOnly={false}
          value={selected?.symbol || ""}
          onChange={setSelected}
          onResults={handleSearchResults}
        />
        {selectedWatchRow && (
          <button
            onClick={() => toggleWatch(selectedWatchRow)}
            disabled={watchSaving}
            className={`rounded-xl border px-4 py-3 text-sm font-bold disabled:opacity-50 ${
              watchSet.has(watchKey(selectedWatchRow))
                ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
                : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
            }`}
          >
            {watchSet.has(watchKey(selectedWatchRow))
              ? "관심 해제"
              : "관심 등록"}
          </button>
        )}
      </div>

      {watchMessage && (
        <div className="rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-300">
          {watchMessage}
        </div>
      )}

      {holdingMessage && (
        <div className="rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-300">
          {holdingMessage}
        </div>
      )}


      {searchResults.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-bold text-slate-100">검색 결과</div>
              <div className="text-xs text-slate-500">
                {searchQuery ? `"${searchQuery}" 검색 결과 ${searchResults.length.toLocaleString("ko-KR")}개` : "전체 종목 검색 결과"}
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                setSearchResults([]);
                setSearchQuery("");
              }}
              className="rounded-xl border border-slate-800 px-3 py-2 text-xs font-bold text-slate-400 hover:bg-slate-800"
            >
              결과 닫기
            </button>
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
            {searchResults.slice(0, 12).map((row) => {
              const rowMarket = cleanMarket(row.market || market || "kr");
              const rowSymbol = cleanSymbol(row.symbol, rowMarket);
              const watched = watchSet.has(watchKey({ market: rowMarket, symbol: rowSymbol }));
              return (
                <div
                  key={`${rowMarket}-${rowSymbol}`}
                  className="rounded-xl border border-slate-800 bg-slate-950 p-3"
                >
                  <button
                    type="button"
                    onClick={() => selectSearchResult(row)}
                    className="block w-full text-left"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-bold text-slate-100">
                          {row.name || rowSymbol}
                        </div>
                        <div className="font-mono text-xs text-slate-500">
                          {rowSymbol} · {rowMarket.toUpperCase()}
                        </div>
                      </div>
                      {watched && (
                        <span className="shrink-0 rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                          관심
                        </span>
                      )}
                    </div>
                    <div className="mt-2 flex items-center justify-between text-xs">
                      <span className="text-slate-500">현재가</span>
                      <span className={`font-mono ${row.currentPriceText ? "text-cyan-300" : "text-amber-300"}`}>
                        {row.currentPriceText || "가격 확인 필요"}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-[11px]">
                      <span className="truncate text-slate-600">
                        출처: {row.priceSource || row.source || "symbol master"}
                      </span>
                      <span className={String(row.dataStatus || "").toUpperCase() === "NORMAL" ? "text-emerald-400" : "text-amber-300"}>
                        {statusText(row.dataStatus)}
                      </span>
                    </div>
                  </button>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        toggleWatch({
                          market: rowMarket,
                          symbol: rowSymbol,
                          name: row.name || rowSymbol,
                          targetReason: "search_watch_added",
                        })
                      }
                      disabled={watchSaving}
                      className={`rounded-xl border px-3 py-2 text-xs font-bold disabled:opacity-50 ${
                        watched
                          ? "border-amber-400/30 bg-amber-400/10 text-amber-300 hover:bg-amber-400/20"
                          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                      }`}
                    >
                      {watched ? "관심 해제" : "관심 등록"}
                    </button>
                    <button
                      type="button"
                      onClick={() => addHoldingFromItem(row)}
                      disabled={holdingSaving}
                      className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-bold text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
                    >
                      보유 추가
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="text-sm text-slate-500">
        {loading
          ? "후보를 불러오는 중..."
          : `${modeLabel(mode)} · ${horizonLabel(horizon)} 조건 / 표시 ${visible.length.toLocaleString("ko-KR")}개 / 전체 ${items.length.toLocaleString("ko-KR")}개`}
      </div>

      {visible.length === 0 && !loading && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
          현재 조건에 맞는 후보가 없습니다. 시장, 관심종목, 투자 성향, 기간
          필터를 변경해보세요.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {visible.map((item: any, index: number) => {
          const hasRecommendation = !item.isSearchOnly;
          const quantity = hasRecommendation ? qtyText(item, mode) : "";
          const marketValue = String(item.market || market);
          const current = priceText(
            item,
            "current",
            priceText(item, "entry", "현재가 없음"),
          );
          const entry = hasRecommendation ? adjustedText(item, "entry", mode, marketValue) : "추천 데이터 없음";
          const stop = hasRecommendation ? adjustedText(item, "stop", mode, marketValue) : "추천 데이터 없음";
          const target = hasRecommendation ? adjustedText(item, "target", mode, marketValue) : "추천 데이터 없음";
          const prob = hasRecommendation ? probabilityText(item, "추천 데이터 없음") : "추천 데이터 없음";
          const watched = isWatched(item);
          return (
            <div
              key={`${item.market}-${item.symbol}-${index}`}
              className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"
            >
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-bold text-slate-100">
                      {displayName(item)}
                    </h3>
                    {watched && (
                      <span className="rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                        관심
                      </span>
                    )}
                  </div>
                  <p className="font-mono text-sm text-slate-500">
                    {item.symbol} ·{" "}
                    {String(item.market || market).toUpperCase()}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-600">
                    요청: {modeLabel(mode)} / {horizonLabel(horizon)} · 소스:{" "}
                    {modeLabel(item.sourceMode || item.mode || mode)} /{" "}
                    {horizonLabel(
                      item.sourceHorizon || item.horizon || horizon,
                    )}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">
                    {item.sourceStatus || "MATCH"}
                  </span>
                  {item.isSearchOnly ? (
                    <span className="rounded bg-blue-500/10 px-2 py-1 text-xs text-blue-300">
                      검색종목
                    </span>
                  ) : null}
                  {(item.warning_reason || item.warningReason) && (
                    <span className="rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-400">
                      주의
                    </span>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <Cell
                  label="현재가"
                  value={current}
                  tone={current.includes("확인") ? "amber" : "normal"}
                />
                <Cell label="진입가" value={entry} tone={hasRecommendation ? "blue" : "amber"} />
                <Cell label="손절가" value={stop} tone={hasRecommendation ? "red" : "amber"} />
                <Cell label="목표가" value={target} tone={hasRecommendation ? "green" : "amber"} />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <Cell label="확률" value={prob} tone="green" />
                <Cell
                  label="예상가"
                  value={hasRecommendation ? priceText(item, "expected", target) : "추천 데이터 없음"}
                  tone={hasRecommendation ? "blue" : "amber"}
                />
              </div>
              {quantity && (
                <div className="mt-2 flex items-center justify-between text-sm">
                  <span className="text-slate-500">
                    {modeLabel(mode)} 비중 기준 수량
                  </span>
                  <span className="font-mono text-emerald-300">{quantity}</span>
                </div>
              )}
              {(item.computedFields || item.fallbackReason) && (
                <div className="mt-3 rounded-xl border border-slate-700 bg-slate-950/60 p-3 text-xs text-slate-400">
                  자동/보강:{" "}
                  {Array.isArray(item.computedFields)
                    ? item.computedFields.join(", ")
                    : item.fallbackReason || "계산값 포함"}
                </div>
              )}

              <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
                <button
                  type="button"
                  className={`inline-flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-xs font-bold ${
                    watched
                      ? "border-amber-400/30 bg-amber-400/10 text-amber-300 hover:bg-amber-400/20"
                      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                  }`}
                  onClick={() => toggleWatch(item)}
                  disabled={watchSaving}
                >
                  <Star size={13} /> {watched ? "관심 해제" : "관심 등록"}
                </button>
                <button
                  type="button"
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-bold text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
                  onClick={() => addHoldingFromItem(item)}
                  disabled={holdingSaving}
                >
                  보유 추가
                </button>
                <button
                  type="button"
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-bold text-slate-200 hover:bg-slate-700"
                  onClick={() =>
                    window.location.assign(
                      item.market === "kr" ? "mstock://" : "tossinvest://",
                    )
                  }
                >
                  <ExternalLink size={13} /> MTS 열기
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

