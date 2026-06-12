"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Star } from "lucide-react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import {
  dedupeBySymbol,
  dataFreshnessBadgeClass,
  dataFreshnessInfo,
  dataTrustBadgeClass,
  dataTrustLabel,
  dataTrustNotice,
  displayName,
  firstText,
  formatMoney,
  horizonLabel,
  modeLabel,
  priceText,
  sanitizeCodeLabel,
  sourceStatusLabel,
  strategyTagLabel,
  toNumber,
} from "@/lib/moneDisplay";
import { getDefaultMarketBySession } from "@/lib/marketSession";

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

const RECOMMENDATION_LIMIT = 50;

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
    <div className="min-w-0 rounded-xl bg-slate-950 px-2 py-2">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className={`mt-0.5 min-w-0 break-keep font-mono text-[11px] font-semibold leading-tight sm:text-xs ${color}`}>
        {value || "-"}
      </div>
    </div>
  );
}

function compactPriceText(value: string, market: string) {
  const text = String(value || "").trim();
  if (!text || text === "-") return text || "-";
  if (String(market).toLowerCase() === "us" || text.startsWith("$")) return text;
  const n = toNumber(text);
  if (n === null) return text;
  if (n >= 1_000_000) return `${Math.round(n / 1000).toLocaleString("ko-KR")}천원`;
  return `${Math.round(n).toLocaleString("ko-KR")}원`;
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
  if (value === "PRICE_PENDING" || value === "NO_PRICE") return "현재가 수집 대기";
  if (value === "DATA_PENDING") return "데이터 수집 대기";
  if (value === "STALE") return "시세 갱신 필요";
  if (value === "ERROR") return "오류";
  return value || "";
}

async function copySymbolForKoreaInvestment(symbol: string) {
  const clean = String(symbol || "").trim();
  if (!clean) return;
  try {
    await navigator.clipboard.writeText(clean);
  } catch {
    // 일부 PC WebView에서는 clipboard 권한이 없어도 안내만 계속 표시한다.
  }
}

async function openKoreaInvestment(symbol: string, market: string) {
  await copySymbolForKoreaInvestment(symbol);
  const marketLabel = market === "us" ? "미국" : "국내";
  window.alert(`종목코드 ${symbol}을 복사했습니다.\n한국투자증권 앱에서 ${marketLabel} 종목코드 ${symbol}을 검색하세요.`);
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

const PATTERN_ACTION_KO: Record<string, string> = {
  SCALE_IN: "분할 접근", WATCH_ONLY: "관찰", WAIT_PULLBACK: "눌림 대기",
  HOLD_CASH: "현금 대기", AVOID_CHASE: "추격 금지", BLOCKED: "진입 차단",
  BUY: "매수", STRONG_BUY: "강력매수", SELL: "매도", STRONG_SELL: "강력매도",
  HOLD: "보유", ENTER: "진입", EXIT: "청산", WAIT: "대기",
};
const PATTERN_RISK_KO: Record<string, string> = {
  NONE: "정상", PULLBACK_RISK: "눌림 위험", OVERHEATED_CHASE_RISK: "과열 추격 주의",
  FALSE_BREAKOUT_RISK: "가짜 돌파 주의", STRUCTURE_BREAKDOWN: "구조 이탈",
  DATA_QUALITY_RISK: "데이터 확인 필요",
};
const PATTERN_TYPE_KO: Record<string, string> = {
  horizontal_support_rebound: "지지 반등", relative_strength: "상대강도 우위",
  resistance_breakout: "저항 돌파", breakout_retest: "돌파 후 재확인",
  trend_up_pullback: "상승 추세 눌림", range_bottom_rebound: "박스 하단 반등",
  volatility_contraction_expansion: "변동성 수축 후 확장", volume_turnaround: "거래량 전환",
  overheated_chase_risk: "과열 추격 위험", false_breakout_risk: "가짜 돌파 위험",
  downtrend_bounce_trap: "하락 반등 함정", resistance_chase_risk: "저항 추격 위험",
};
const ENTRY_ACTION_CODES = new Set(["SCALE_IN", "WAIT_PULLBACK", "BUY", "STRONG_BUY", "ENTER"]);
const OBSERVE_ACTION_CODES = new Set(["HOLD_CASH", "WATCH_ONLY", "WAIT", "HOLD", "AVOID_CHASE", "BLOCKED"]);

function firstPlainText(...values: any[]): string {
  for (const value of values) {
    if (typeof value !== "string" && typeof value !== "number") continue;
    const text = String(value).trim();
    if (text && text !== "-" && text !== "NaN" && text !== "null" && text !== "undefined") return text;
  }
  return "-";
}

function safeKoreanLabel(
  value: any,
  map: Record<string, string> = {},
  fallback: string | null = null,
): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const text = String(value).trim();
  if (!text || text === "-") return null;
  const upper = text.toUpperCase();
  if (map[text]) return map[text];
  if (map[upper]) return map[upper];
  const sanitized = sanitizeCodeLabel(text);
  if (sanitized && sanitized !== text) return sanitized;
  if (/[가-힣]/.test(text) && !/^[A-Z0-9_./-]+$/.test(text)) return text;
  return fallback;
}

function recommendationBadgeLabel(item: any, actionCode: string, actionText: string | null): string | null {
  const baseLabel = sourceStatusLabel(item.sourceStatus);
  if (!baseLabel) return null;
  if (actionCode === "HOLD_CASH" || actionCode === "WATCH_ONLY" || actionText === "현금 대기") return "관찰 후보";
  if (ENTRY_ACTION_CODES.has(actionCode)) return "진입 후보";
  if (OBSERVE_ACTION_CODES.has(actionCode) && baseLabel === "조건일치") return "조건 포착";
  return baseLabel === "조건일치" ? "조건 포착" : baseLabel;
}

export default function StocksPage({ onNavigate }: { onNavigate?: (page: string) => void } = {}) {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [watchOnly, setWatchOnly] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [loadError, setLoadError] = useState("");
  const [loadNotice, setLoadNotice] = useState("");
  const [watchlist, setWatchlist] = useState<WatchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [watchSaving, setWatchSaving] = useState(false);
  const [autoCurating, setAutoCurating] = useState(false);
  const [watchMessage, setWatchMessage] = useState("");
  const [holdingMessage, setHoldingMessage] = useState("");
  const [holdingSaving, setHoldingSaving] = useState(false);
  const [quoteRefreshing, setQuoteRefreshing] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [searchResults, setSearchResults] = useState<MoneSymbol[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [, setCashVersion] = useState(0);
  const [scoredWatch, setScoredWatch] = useState<any>(null);
  const [scoredLoading, setScoredLoading] = useState(false);
  const [sectorFilter, setSectorFilter] = useState<string | null>(null);
  const [sectorsList, setSectorsList] = useState<string[]>([]);
  const [groupFilter, setGroupFilter] = useState<string | null>(null);
  const [groupsList, setGroupsList] = useState<string[]>([]);
  const [groupAssigning, setGroupAssigning] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<"finalScore" | "expectedValue" | "upsideScore" | "rrScore">("finalScore");
  const [screenerOpen, setScreenerOpen] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [hideDataPending, setHideDataPending] = useState(false);
  const [hideBlockedOnly, setHideBlockedOnly] = useState(false);
  const [nameQuery, setNameQuery] = useState("");

  useEffect(() => {
    if (market === "kr") {
      mone.sectorsList({ market }).then((r) => {
        setSectorsList(Array.isArray(r.items) ? r.items.slice(0, 20).map((s: any) => s.sector) : []);
      }).catch(() => setSectorsList([]));
    }
    mone.watchlistGroups({ market }).then((r) => {
      setGroupsList(Array.isArray(r.groups) ? r.groups.filter((g: string) => g !== "미분류") : []);
    }).catch(() => setGroupsList([]));
  }, [market]);

  async function assignGroup(symbol: string, marketStr: string, group: string) {
    let finalGroup = group;
    if (group === "__new__") {
      const input = window.prompt("새 그룹 이름을 입력하세요 (예: AI주, 배당주, 단기후보):");
      if (!input) return;
      finalGroup = input.trim();
    }
    setGroupAssigning(symbol);
    try {
      await mone.watchlistSetGroup({ market: marketStr, symbol, group: finalGroup });
      setGroupsList((prev) => (finalGroup && !prev.includes(finalGroup) ? [...prev, finalGroup] : prev));
    } finally {
      setGroupAssigning(null);
    }
  }

  async function loadScoredWatchlist() {
    setScoredLoading(true);
    try {
      const data = await mone.watchlistScored({ market, mode, horizon });
      setScoredWatch(data);
    } catch {
      setScoredWatch(null);
    } finally {
      setScoredLoading(false);
    }
  }

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
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setLoadError("");
    setLoadNotice("");
    mone
      .recommendations({ market, mode, horizon, limit: Math.min(RECOMMENDATION_LIMIT, 50), watchOnly }, controller.signal) // /api/final/recommendations le=50
      .then(async (data) => {
        if (!active) return;
        if (data?.status === "ERROR") {
          // 취소된 요청의 에러는 무시
          if (controller.signal.aborted) return;
          const fallback = await mone.candidates({
            market,
            strategy: mode,
            term: horizon,
            limit: Math.min(RECOMMENDATION_LIMIT, 60),
          });
          if (!active || controller.signal.aborted) return;
          if (fallback?.status !== "ERROR") {
            const fallbackItems = dedupeBySymbol(Array.isArray(fallback.items) ? fallback.items : []);
            const watchKeys = new Set(watchlist.map((row) => watchKey(row)));
            const filteredFallback = watchOnly
              ? fallbackItems.filter((item) => {
                  const itemMarket = cleanMarket(item.market || market || "kr");
                  return watchKeys.has(
                    watchKey({
                      market: itemMarket,
                      symbol: cleanSymbol(item.symbol, itemMarket),
                    }),
                  );
                })
              : fallbackItems;
            setItems(filteredFallback);
            setLoadNotice("추천 요약 API가 지연되어 후보 API 기준으로 표시 중입니다.");
            return;
          }
          setItems([]);
          setLoadError(data.error || "추천 후보를 불러오지 못했습니다.");
          return;
        }
        setItems(dedupeBySymbol(Array.isArray(data.items) ? data.items : []));
        if (data?.status && data.status !== "OK" && data.status !== "NO_DATA") {
          setLoadError(`추천 데이터 상태: ${data.status}`);
        }
      })
      .catch((error) => {
        if (!active) return;
        setItems([]);
        setLoadError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
      controller.abort();
    };
  }, [market, mode, horizon, watchOnly, watchlist.length, refreshVersion]);

  const sectorFiltered = useMemo(() => {
    let result = items;
    if (sectorFilter) {
      result = result.filter((item) => {
        const sec = String(item.sector || item.sectorLabel || "").trim();
        return sec === sectorFilter || sec.startsWith(sectorFilter);
      });
    }
    if (groupFilter) {
      result = result.filter((item) => String(item.group || "미분류").trim() === groupFilter);
    }
    if (minScore > 0) {
      result = result.filter((item) => Number(item.finalScore ?? 0) >= minScore);
    }
    if (tagFilter) {
      result = result.filter((item) => {
        const tags: string[] = Array.isArray(item.strategyTags) ? item.strategyTags : [];
        return tags.includes(tagFilter);
      });
    }
    if (hideDataPending) {
      result = result.filter((item) => !["DATA_PENDING", "STALE"].includes(String(item.dataStatus || "")));
    }
    if (hideBlockedOnly) {
      result = result.filter((item) => String(item.tradeBlockStatus || "") !== "BLOCK");
    }
    if (nameQuery.trim()) {
      const needle = nameQuery.trim().toLowerCase();
      result = result.filter((item) =>
        `${displayName(item)} ${item.symbol}`.toLowerCase().includes(needle)
      );
    }
    return result;
  }, [items, sectorFilter, groupFilter, minScore, tagFilter, hideDataPending, hideBlockedOnly, nameQuery]);

  const allTags = useMemo(() => {
    const tagSet = new Set<string>();
    items.forEach((item) => {
      (Array.isArray(item.strategyTags) ? item.strategyTags : []).forEach((t: string) => tagSet.add(t));
    });
    return Array.from(tagSet).sort();
  }, [items]);

  const activeFilterCount = [
    minScore > 0, tagFilter != null, hideDataPending, hideBlockedOnly,
    nameQuery.trim() !== "", sectorFilter != null, groupFilter != null,
  ].filter(Boolean).length;

  function applyScreenerPreset(preset: "quality" | "entry" | "clean" | "watch") {
    if (preset === "quality") {
      setMinScore(60);
      setHideBlockedOnly(true);
      setHideDataPending(true);
      setTagFilter(null);
    } else if (preset === "entry") {
      setMinScore(50);
      setHideBlockedOnly(true);
      setHideDataPending(false);
      setTagFilter(null);
    } else if (preset === "clean") {
      setMinScore(0);
      setHideBlockedOnly(true);
      setHideDataPending(true);
      setTagFilter(null);
    } else if (preset === "watch") {
      setWatchOnly(true);
      setMinScore(40);
      setHideBlockedOnly(false);
      setHideDataPending(false);
    }
  }

  const visible = useMemo(() => {
    const base = sectorFilter || groupFilter || minScore > 0 || tagFilter || hideDataPending || hideBlockedOnly || nameQuery.trim() ? sectorFiltered : items;
    let result = base;
    if (selected) {
      const selectedMarket = cleanMarket(selected.market || market || "kr");
      const selectedSymbol = cleanSymbol(selected.symbol, selectedMarket);
      const matched = base.filter((item) => {
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
    }
    return [...result].sort((a, b) => Number(b[sortBy] ?? 0) - Number(a[sortBy] ?? 0));
  }, [items, selected, market, sectorFiltered, sectorFilter, groupFilter, minScore, tagFilter, hideDataPending, hideBlockedOnly, nameQuery, sortBy]);

  const filterStats = useMemo(() => {
    const normal = sectorFiltered.filter((item) => String(item.dataStatus || "").toUpperCase() === "NORMAL").length;
    const blocked = sectorFiltered.filter((item) => String(item.tradeBlockStatus || "").toUpperCase() === "BLOCK").length;
    const caution = sectorFiltered.filter((item) => String(item.tradeBlockStatus || "").toUpperCase() === "CAUTION").length;
    return { normal, blocked, caution };
  }, [sectorFiltered]);

  const recommendationFreshness = useMemo(() => {
    const sample = visible.find((item) => !item.isSearchOnly) || items[0] || {};
    return dataFreshnessInfo({
      market: sample.market || market,
      latestDataDate: firstText(sample.latestDataDate, sample.dataDate, sample.sourceDate, sample.ohlcvLatestDate, sample.priceDate, ""),
      recoGeneratedAt: firstText(sample.recoGeneratedAt, sample.generatedAt, sample.updatedAt, ""),
      dataStatus: loadError ? "NO_DATA" : sample.dataStatus,
    });
  }, [items, visible, loadError]);

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

  async function applySmartWatchlist() {
    setAutoCurating(true);
    setWatchMessage("");
    try {
      const targetMarket = market === "all" ? "all" : market;
      const result = await mone.applyAutoWatchlist({ market: targetMarket, limitPerMarket: 12 });
      if (result?.status === "ERROR") throw new Error(result.error || "자동 선별 실패");
      const saved = Array.isArray(result.items)
        ? result.items.map(normalizeWatch).filter((row) => row.symbol)
        : [];
      setWatchlist(saved);
      await loadWatchlist();
      setWatchOnly(true);
      setRefreshVersion((value) => value + 1);
      setWatchMessage(
        `핵심 관심종목 자동선별 완료 · ${saved.length.toLocaleString("ko-KR")}개 (${result.policy || "추천 데이터 기준"})`,
      );
      window.dispatchEvent(new CustomEvent("mone-watchlist-updated"));
    } catch (error) {
      setWatchMessage(`자동선별 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setAutoCurating(false);
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

  async function refreshOneQuote(item: any) {
    const itemMarket = cleanMarket(item.market || market || "kr");
    const clean = itemMarket === "all" ? "kr" : itemMarket;
    const symbol = cleanSymbol(item.symbol, clean);
    const name = displayName(item) || symbol;
    if (!symbol) return;
    const key = `${clean}-${symbol}`;
    setQuoteRefreshing(key);
    setHoldingMessage("");
    try {
      const result = await mone.refreshOneQuote({ market: clean, symbol, name });
      if (result?.status === "OK") {
        setHoldingMessage(`${name} 현재가를 새로고침했습니다.`);
        const refreshed = await mone.symbols({ market: clean, q: symbol, limit: 5 });
        const next = Array.isArray(refreshed.items) ? refreshed.items : [];
        if (next.length) {
          setSearchResults((rows) => rows.map((row) => (cleanSymbol(row.symbol, clean) === symbol ? { ...row, ...next[0] } : row)));
          if (selected && cleanSymbol(selected.symbol, clean) === symbol) setSelected({ ...selected, ...next[0] });
        }
      } else {
        setHoldingMessage(`${name} 현재가 새로고침 실패: ${result?.error || "시세 수집 실패 / 다시 시도"}`);
      }
      setRefreshVersion((value) => value + 1);
    } catch (error) {
      setHoldingMessage(`현재가 새로고침 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setQuoteRefreshing(null);
    }
  }

  async function refreshTargetQuotes() {
    setQuoteRefreshing("batch");
    setHoldingMessage("");
    try {
      const result = await mone.refreshTargetQuotes({ market, limit: 20 });
      setHoldingMessage(
        `현재가 새로고침: 성공 ${result?.successCount ?? 0}건 / 실패 ${result?.failureCount ?? 0}건 / 대기 ${result?.pendingCount ?? 0}건`,
      );
      setRefreshVersion((value) => value + 1);
    } catch (error) {
      setHoldingMessage(`전체 현재가 새로고침 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setQuoteRefreshing(null);
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

  const SUGGEST_STYLE: Record<string, string> = {
    "즉시 진입 검토": "border-emerald-600/40 bg-emerald-900/20 text-emerald-300",
    "타이밍 대기":    "border-amber-600/40 bg-amber-900/20 text-amber-300",
    "제거 고려":      "border-red-600/40 bg-red-900/20 text-red-300",
    "모니터링":       "border-slate-700 bg-slate-800 text-slate-400",
    "데이터 없음":    "border-slate-800 bg-slate-900 text-slate-600",
  };

  return (
    <div className="space-y-6">
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
        <div className="grid grid-cols-4 gap-2">
          {marketTabs.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setMarket(item.id);
                setSelected(null);
              }}
              className={`min-w-0 rounded-xl px-2 py-2 text-sm ${market === item.id ? "bg-blue-600 text-white" : "bg-slate-950 text-slate-400"}`}
            >
              {item.label}
            </button>
          ))}
          <button
            onClick={() => setWatchOnly(!watchOnly)}
            className={`min-w-0 rounded-xl px-2 py-2 text-sm ${watchOnly ? "bg-amber-500 text-slate-950" : "bg-slate-950 text-slate-400"}`}
          >
            관심종목
          </button>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <button
            onClick={applySmartWatchlist}
            disabled={autoCurating || watchSaving}
            className="min-w-0 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-2 py-2 text-xs font-bold text-emerald-300 disabled:opacity-50 sm:text-sm"
          >
            {autoCurating ? "선별 중..." : "자동선별"}
          </button>
          <button
            onClick={refreshTargetQuotes}
            disabled={quoteRefreshing === "batch"}
            className="min-w-0 rounded-xl border border-cyan-500/30 bg-cyan-500/10 px-2 py-2 text-xs font-bold text-cyan-300 disabled:opacity-50 sm:text-sm"
          >
            현재가 갱신
          </button>
          <button
            onClick={loadScoredWatchlist}
            disabled={scoredLoading}
            className="min-w-0 rounded-xl border border-violet-500/30 bg-violet-500/10 px-2 py-2 text-xs font-bold text-violet-300 disabled:opacity-50 sm:text-sm"
          >
            {scoredLoading ? "분석 중..." : "점수 분석"}
          </button>
        </div>

        {/* 그룹 필터 */}
        {groupsList.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <span className="text-[10px] text-slate-500 self-center">그룹:</span>
            <button onClick={() => setGroupFilter(null)}
              className={`rounded-full px-3 py-1 text-[11px] font-medium ${!groupFilter ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
              전체
            </button>
            {groupsList.map((g) => (
              <button key={g} onClick={() => setGroupFilter(g === groupFilter ? null : g)}
                className={`rounded-full px-3 py-1 text-[11px] font-medium ${groupFilter === g ? "bg-teal-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
                {g}
              </button>
            ))}
          </div>
        )}

        {/* 섹터 필터 */}
        {sectorsList.length > 0 && (
          <div className="mt-4 flex flex-col gap-1.5 sm:max-w-xs">
            <label htmlFor="stocks-sector-filter" className="text-[10px] text-slate-500">
              섹터
            </label>
            <select
              id="stocks-sector-filter"
              value={sectorFilter || ""}
              onChange={(e) => setSectorFilter(e.target.value || null)}
              className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-violet-500"
            >
              <option value="">전체</option>
              {sectorsList.map((sec) => (
                <option key={sec} value={sec}>
                  {sec}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* 스크리너 패널 토글 */}
        <div className="mt-4">
          <button
            onClick={() => setScreenerOpen((v) => !v)}
            className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-semibold transition-colors ${screenerOpen ? "border-sky-600/60 bg-sky-900/20 text-sky-300" : "border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-600 hover:text-slate-200"}`}>
            스크리너
            {activeFilterCount > 0 && (
              <span className="rounded-full bg-sky-600 px-1.5 py-0.5 text-[10px] font-bold text-white">{activeFilterCount}</span>
            )}
            <span className="ml-1 text-[10px] opacity-60">{screenerOpen ? "▲" : "▼"}</span>
          </button>

          {screenerOpen && (
            <div className="mt-2 rounded-2xl border border-slate-700/60 bg-slate-900/60 p-4 space-y-4">
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">빠른 선별</label>
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {[
                    { id: "quality", label: "상위·정상", hint: "60점+ 데이터 정상" },
                    { id: "entry", label: "관찰 후보", hint: "50점+ 차단 제외" },
                    { id: "clean", label: "데이터 정상", hint: "대기/차단 제외" },
                    { id: "watch", label: "관심만", hint: "관심 후보 집중" },
                  ].map((preset) => (
                    <button
                      key={preset.id}
                      onClick={() => applyScreenerPreset(preset.id as "quality" | "entry" | "clean" | "watch")}
                      className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-left hover:border-sky-600/60 hover:bg-sky-950/20"
                    >
                      <div className="text-xs font-bold text-slate-100">{preset.label}</div>
                      <div className="mt-0.5 text-[10px] text-slate-500">{preset.hint}</div>
                    </button>
                  ))}
                </div>
              </div>
              {/* 이름/티커 검색 */}
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">종목 검색</label>
                <input
                  type="text"
                  value={nameQuery}
                  onChange={(e) => setNameQuery(e.target.value)}
                  placeholder="이름 또는 티커 입력"
                  className="mt-1 w-full max-w-xs rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-sky-600"
                />
              </div>

              {/* 최소 점수 */}
              <div>
                <div className="flex items-center justify-between">
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">최소 finalScore</label>
                  <span className="font-mono text-xs text-slate-300">{minScore} 이상</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {[0, 30, 40, 50, 60].map((val) => (
                    <button key={val} onClick={() => setMinScore(val)}
                      className={`rounded-full px-3 py-1 text-[11px] font-medium ${minScore === val ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
                      {val === 0 ? "전체" : `${val}+`}
                    </button>
                  ))}
                </div>
              </div>

              {/* 전략 태그 */}
              {allTags.length > 0 && (
                <div>
                  <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">전략 태그</label>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <button onClick={() => setTagFilter(null)}
                      className={`rounded-full px-3 py-1 text-[11px] font-medium ${!tagFilter ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
                      전체
                    </button>
                    {allTags.map((tag) => (
                      <button key={tag} onClick={() => setTagFilter(tag === tagFilter ? null : tag)}
                        className={`rounded-full px-3 py-1 text-[11px] font-medium ${tagFilter === tag ? "bg-amber-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
                        {tag}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 데이터 상태 필터 */}
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">데이터·진입 상태</label>
                <div className="mt-2 flex flex-wrap gap-2">
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
                    <input type="checkbox" checked={hideDataPending} onChange={(e) => setHideDataPending(e.target.checked)}
                      className="rounded border-slate-700 bg-slate-800 accent-sky-500" />
                    DATA_PENDING / STALE 숨기기
                  </label>
                  <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
                    <input type="checkbox" checked={hideBlockedOnly} onChange={(e) => setHideBlockedOnly(e.target.checked)}
                      className="rounded border-slate-700 bg-slate-800 accent-sky-500" />
                    BLOCK 종목 숨기기
                  </label>
                </div>
              </div>

              {/* 결과 요약 + 전체 초기화 */}
              <div className="flex items-center justify-between border-t border-slate-700/50 pt-3">
                <span className="text-xs text-slate-500">
                  필터 결과: <span className="font-mono text-slate-200">{sectorFiltered.length}</span> / {items.length}개
                </span>
                {activeFilterCount > 0 && (
                  <button onClick={() => {
                    setMinScore(0); setTagFilter(null); setHideDataPending(false);
                    setHideBlockedOnly(false); setNameQuery(""); setSectorFilter(null); setGroupFilter(null);
                  }} className="rounded-lg border border-slate-700 px-3 py-1 text-[11px] text-slate-400 hover:bg-slate-800">
                    필터 전체 초기화
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* 관심종목 자동선별 결과 */}
        {scoredWatch && Array.isArray(scoredWatch.items) && scoredWatch.items.length === 0 && (
          <div className="mt-4 rounded-xl border border-slate-700/40 bg-slate-900/40 px-4 py-3 text-xs text-slate-500">
            관심종목 점수 분석 결과가 없습니다.
            {scoredWatch.reason && <span className="ml-1 text-amber-400">{scoredWatch.reason}</span>}
            {!scoredWatch.reason && <span className="ml-1">관심종목({watchlist.length}개)이 추천 파일에 매칭되지 않았거나 추천 데이터가 없습니다. 핵심 관심 자동선별 후 다시 시도하세요.</span>}
          </div>
        )}
        {scoredWatch && Array.isArray(scoredWatch.items) && scoredWatch.items.length > 0 && (
          <div className="mt-5 rounded-2xl border border-violet-800/30 bg-violet-950/10 p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <span className="text-sm font-semibold text-slate-100">관심종목 점수 분석</span>
                <span className="ml-2 text-xs text-slate-500">{modeLabel(mode)} × {horizonLabel(horizon)}</span>
              </div>
              <div className="flex gap-2 text-[11px]">
                {[
                  { key: "immediate", label: "즉시", color: "text-emerald-300" },
                  { key: "waiting",   label: "대기", color: "text-amber-300" },
                  { key: "monitor",   label: "관찰", color: "text-slate-400" },
                  { key: "remove",    label: "제거", color: "text-red-300" },
                ].map(({ key, label, color }) => (
                  scoredWatch.summary?.[key] > 0 && (
                    <span key={key} className={color}>{label} {scoredWatch.summary[key]}</span>
                  )
                ))}
              </div>
              <button onClick={() => setScoredWatch(null)} className="text-slate-600 hover:text-slate-400">✕</button>
            </div>
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {scoredWatch.items.map((it: any) => (
                <div key={it.symbol} className={`flex items-center justify-between rounded-xl border px-3 py-2 text-[11px] ${SUGGEST_STYLE[it.suggestion] || SUGGEST_STYLE["모니터링"]}`}>
                  <div className="min-w-0 flex-1">
                    <span className="font-semibold">{it.name || it.symbol}</span>
                    <span className="ml-1.5 text-[10px] opacity-60">{it.symbol}</span>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {it.finalScore > 0 && <span className="font-mono">{it.finalScore.toFixed(0)}점</span>}
                    {it.expectedValue !== 0 && <span className={`font-mono ${it.expectedValue >= 0 ? "opacity-80" : "text-red-400"}`}>EV {it.expectedValue >= 0 ? "+" : ""}{it.expectedValue?.toFixed(1)}%</span>}
                    <span className="rounded-full border px-1.5 py-0.5 text-[10px]">{it.suggestion}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

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
                        {row.currentPriceText || "실시간 현재가 없음"}
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
                  <div className="mt-2 text-[10px] text-slate-600">현재 추천 후보는 아닙니다 · 분석 화면에서 상세 확인 가능</div>
                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      className="flex-1 inline-flex items-center justify-center rounded-xl border border-blue-600/40 bg-blue-600/10 px-3 py-2 text-xs font-bold text-blue-300 hover:bg-blue-600/20"
                      onClick={() => {
                        window.localStorage.setItem("mone_chart_symbol", rowSymbol);
                        window.localStorage.setItem("mone_chart_market", rowMarket);
                        window.localStorage.setItem("mone_chart_name", row.name || rowSymbol);
                        window.localStorage.setItem("mone_chart_price", String(row.currentPrice || ""));
                        window.localStorage.setItem("mone_chart_price_text", row.currentPriceText || "");
                        window.dispatchEvent(new CustomEvent("mone-open-chart", { detail: row }));
                        onNavigate?.("chart");
                      }}
                    >
                      분석 보기 →
                    </button>
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
                      className={`flex-1 rounded-xl border px-3 py-2 text-xs font-bold disabled:opacity-50 ${
                        watched
                          ? "border-amber-400/30 bg-amber-400/10 text-amber-300 hover:bg-amber-400/20"
                          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                      }`}
                    >
                      {watched ? "관심 해제" : "관심 등록"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-slate-500">
          {loading
            ? "후보를 불러오는 중..."
            : `${modeLabel(mode)} · ${horizonLabel(horizon)} / 표시 ${visible.length.toLocaleString("ko-KR")}개 / 우선 로딩 ${items.length.toLocaleString("ko-KR")}개`}
          {!loading && items.length >= RECOMMENDATION_LIMIT && (
            <span className="ml-2 rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] text-slate-400">
              상위 {RECOMMENDATION_LIMIT}개 우선
            </span>
          )}
        </div>
        {!selected && (
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-slate-500"
          >
            <option value="finalScore">종합점수순</option>
            <option value="expectedValue">EV순</option>
            <option value="upsideScore">상승여력순</option>
            <option value="rrScore">손익비순</option>
          </select>
        )}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-xs text-slate-400">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-slate-200">추천 목록</span>
          <span className={`rounded-full border px-2 py-0.5 ${dataFreshnessBadgeClass(recommendationFreshness.state)}`}>
            {recommendationFreshness.label}
          </span>
          <span>{recommendationFreshness.basisText}</span>
          <span className="text-slate-600">· 상세 판단은 카드의 MONE 판단 보기에서 분석 탭으로 이어집니다.</span>
        </div>
      </div>

      {loadError && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          추천 후보 로딩이 지연되거나 실패했습니다. 조건을 줄이거나 잠시 후 다시 시도하세요.
          <span className="ml-2 text-xs text-amber-300/80">{loadError}</span>
        </div>
      )}

      {loadNotice && !loadError && (
        <div className="rounded-xl border border-sky-500/30 bg-sky-500/10 px-4 py-3 text-sm text-sky-200">
          {loadNotice}
        </div>
      )}

      {visible.length === 0 && !loading && !loadError && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-8 text-center">
          <p className="text-slate-400">현재 조건에 맞는 후보가 없습니다.</p>
          <div className="mt-3 space-y-1 text-xs text-slate-600">
            {watchOnly && items.length === 0 && <p>• 관심종목이 없거나 추천 파일에 매칭되지 않음 → "관심 자동선별" 또는 관심종목만 보기 해제</p>}
            {watchOnly && items.length > 0 && visible.length === 0 && <p>• 관심종목 {watchlist.length}개 중 {modeLabel(mode)}/{horizonLabel(horizon)} 추천에 매칭된 종목 없음 → 성향·기간 변경 또는 관심종목만 보기 해제</p>}
            {!watchOnly && items.length === 0 && <p>• 추천 파일({modeLabel(mode)}/{horizonLabel(horizon)})이 비어있음 — GitHub Actions 실행 후 데이터가 채워집니다</p>}
            {!watchOnly && items.length > 0 && visible.length === 0 && sectorFilter && <p>• 섹터 필터 "{sectorFilter}" 에 해당하는 종목 없음 → 섹터 필터 해제</p>}
            {!watchOnly && items.length > 0 && visible.length === 0 && groupFilter && <p>• 그룹 필터 "{groupFilter}" 에 해당하는 종목 없음 → 그룹 필터 해제</p>}
          </div>
          <div className="mt-4 flex justify-center gap-2">
            {watchOnly && <button onClick={() => setWatchOnly(false)} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">관심종목만 보기 해제</button>}
            {sectorFilter && <button onClick={() => setSectorFilter(null)} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">섹터 필터 해제</button>}
            {groupFilter && <button onClick={() => setGroupFilter(null)} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">그룹 필터 해제</button>}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {visible.map((item: any, index: number) => {
          const hasRecommendation = !item.isSearchOnly;
          const marketValue = String(item.market || market);
          const currentRaw = priceText(
            item,
            "current",
            priceText(item, "entry", "현재가 없음"),
          );
          const entryRaw = hasRecommendation ? adjustedText(item, "entry", mode, marketValue) : "추천 데이터 없음";
          const targetRaw = hasRecommendation ? adjustedText(item, "target", mode, marketValue) : "추천 데이터 없음";
          const current = compactPriceText(currentRaw, marketValue);
          const entry = compactPriceText(entryRaw, marketValue);
          const target = compactPriceText(targetRaw, marketValue);
          const watched = isWatched(item);
          const patternAction = firstPlainText(
            item.patternStrategy?.action,
            item.patternStrategyAction,
            item.patternAction,
            item.newEntryDecision,
            item.buyTiming,
            "",
          );
          // ── 비추천 검색종목: 간단 카드 ──
          if (item.isSearchOnly) {
            const soMarket = cleanMarket(item.market || market || "kr");
            const soSymbol = cleanSymbol(item.symbol, soMarket);
            return (
              <div key={`search-only-${soMarket}-${soSymbol}-${index}`} className="rounded-2xl border border-slate-700/50 bg-slate-900/30 p-3 sm:p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-bold text-slate-100">{displayName(item)}</div>
                    <div className="mt-0.5 font-mono text-xs text-slate-500">{soSymbol} · {soMarket.toUpperCase()}</div>
                  </div>
                  {watched && (
                    <span className="shrink-0 rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">관심</span>
                  )}
                </div>
                <div className="mt-2 text-xs text-slate-500">현재 추천 후보는 아니지만 분석할 수 있습니다.</div>
                {current && !current.includes("없음") && (
                  <div className="mt-2 flex items-center justify-between">
                    <span className="text-xs text-slate-500">현재가</span>
                    <span className="break-keep font-mono text-sm font-bold text-cyan-300">{current}</span>
                  </div>
                )}
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    className="flex-1 inline-flex items-center justify-center rounded-xl border border-blue-600/40 bg-blue-600/10 px-3 py-2 text-xs font-bold text-blue-300 hover:bg-blue-600/20"
                    onClick={() => {
                      window.localStorage.setItem("mone_chart_symbol", soSymbol);
                      window.localStorage.setItem("mone_chart_market", soMarket);
                      window.localStorage.setItem("mone_chart_name", displayName(item) || soSymbol);
                      window.localStorage.setItem("mone_chart_price", String(item.currentPrice || ""));
                      window.localStorage.setItem("mone_chart_price_text", currentRaw);
                      window.dispatchEvent(new CustomEvent("mone-open-chart", { detail: item }));
                      onNavigate?.("chart");
                    }}
                  >
                    분석 보기 →
                  </button>
                  <button
                    type="button"
                    className={`flex-1 inline-flex items-center justify-center rounded-xl border px-3 py-2 text-xs font-bold disabled:opacity-50 ${watched ? "border-amber-400/30 bg-amber-400/10 text-amber-300 hover:bg-amber-400/20" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"}`}
                    onClick={() => toggleWatch({ market: soMarket, symbol: soSymbol, name: displayName(item) || soSymbol })}
                    disabled={watchSaving}
                  >
                    {watched ? "관심 해제" : "관심 등록"}
                  </button>
                </div>
              </div>
            );
          }

          // ── 추천 카드 ──────────────────────────────────────────────
          const ps = item.patternStrategy && typeof item.patternStrategy === "object" ? item.patternStrategy : null;
          const psActionRaw = ps?.action && typeof ps.action === "string" ? ps.action
            : patternAction && patternAction !== "-" ? patternAction : null;
          const psRiskRaw = ps?.riskStatus && typeof ps.riskStatus === "string" ? ps.riskStatus : null;
          const psPatternRaw = ps?.primaryPattern && typeof ps.primaryPattern === "string" ? ps.primaryPattern : null;
          const psConf = ps?.confidence != null ? Math.round(Number(ps.confidence))
            : item.finalScore > 0 ? Math.round(item.finalScore) : null;
          const actionCode = String(psActionRaw || "").trim().toUpperCase();
          const actionText = safeKoreanLabel(psActionRaw, PATTERN_ACTION_KO);
          const riskText = psRiskRaw ? safeKoreanLabel(psRiskRaw, PATTERN_RISK_KO, "확인 필요") : "정상";
          const patternText = safeKoreanLabel(psPatternRaw, PATTERN_TYPE_KO);
          const topBadgeLabel = recommendationBadgeLabel(item, actionCode, actionText);

          // 태그: 넓어진 카드 폭에 맞춰 핵심 신호를 한 줄에 최대 5개까지 표시
          const MAX_VISIBLE_TAGS = 5;
          const TAG_LABEL: Record<string, string> = {
            CAUTION:"⚠ 주의", MA_CONVERGENCE:"이격도 수렴", PULLBACK_BUY:"눌림목",
            MOMENTUM:"모멘텀", VOLUME_BREAKOUT:"거래량 증가", BREAKOUT_52W:"52주 돌파",
            NEAR_52W_HIGH:"신고가 근접", BB_SQUEEZE:"변동성 압축", STABLE_LOW_RISK:"안정형",
            UNDERVALUED_GROWTH:"저평가 성장주", GOLDEN_CROSS:"🔼 골든크로스",
            DEATH_CROSS:"🔽 데드크로스", MID_GOLDEN_CROSS:"📈 중기 골든크로스",
            MID_DEATH_CROSS:"📉 중기 데드크로스", TRAILING_STOP_ALERT:"⚡ 트레일링 손절",
            LOW_RISK_STABLE:"안정형", BREAKOUT:"돌파",
          };
          const TAG_COLOR: Record<string, string> = {
            CAUTION:"border-red-600/40 bg-red-600/10 text-red-300",
            DEATH_CROSS:"border-red-600/40 bg-red-600/10 text-red-300",
            MID_DEATH_CROSS:"border-red-700/40 bg-red-700/10 text-red-400",
            TRAILING_STOP_ALERT:"border-amber-500/40 bg-amber-500/10 text-amber-300",
            GOLDEN_CROSS:"border-emerald-400/40 bg-emerald-400/10 text-emerald-300",
            MID_GOLDEN_CROSS:"border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
            MA_CONVERGENCE:"border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
            PULLBACK_BUY:"border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
            MOMENTUM:"border-orange-500/40 bg-orange-500/10 text-orange-300",
            VOLUME_BREAKOUT:"border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
            BREAKOUT_52W:"border-violet-500/40 bg-violet-500/10 text-violet-300",
            BREAKOUT:"border-violet-500/40 bg-violet-500/10 text-violet-300",
            LOW_RISK_STABLE:"border-teal-500/40 bg-teal-500/10 text-teal-300",
          };
          const visibleTags: { key: string; label: string; cls: string }[] = [];
          const addVisibleTag = (key: string, label: string | null, cls = "border-slate-600 bg-slate-800 text-slate-300") => {
            if (!label || visibleTags.length >= MAX_VISIBLE_TAGS) return;
            if (visibleTags.some((tag) => tag.key === key || tag.label === label)) return;
            visibleTags.push({ key, label, cls });
          };
          if (Array.isArray(item.strategyTags)) {
            const tagLabels = Array.isArray(item.strategyTagLabels) ? item.strategyTagLabels : [];
            for (let i = 0; i < item.strategyTags.length; i += 1) {
              const tag = item.strategyTags[i];
              const lbl = tagLabels[i] || TAG_LABEL[tag] || strategyTagLabel(tag) || safeKoreanLabel(tag);
              addVisibleTag(tag, lbl, TAG_COLOR[tag]);
            }
          }
          // surgeLabel 처리
          if (item.surgeLabel && item.surgeLabel !== "판단 대기" && visibleTags.length < MAX_VISIBLE_TAGS) {
            for (const t of String(item.surgeLabel).split("|").map((s: string) => s.trim()).filter(Boolean)) {
              addVisibleTag(t, safeKoreanLabel(t), "border-slate-700 bg-slate-950 text-slate-300");
            }
          }
          if (item.maConvergence)
            addVisibleTag("ma_convergence", "이격도 수렴", "border-cyan-500/40 bg-cyan-500/10 text-cyan-300");
          if (item.supplySignal === "STRONG_BUY")
            addVisibleTag("supply_strong", "기관+외국인", "border-blue-400/40 bg-blue-400/10 text-blue-300");
          else if (item.supplySignal === "INST_BUY")
            addVisibleTag("supply_inst", "기관 순매수", "border-sky-500/30 bg-sky-500/10 text-sky-300");

          return (
            <div
              key={`${item.market}-${item.symbol}-${index}`}
              className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3 sm:p-4"
            >
              {/* 헤더 */}
              <div className="mb-3 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-base font-bold text-slate-100 leading-tight">{displayName(item)}</h3>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-xs text-slate-500">{item.symbol} · {String(item.market || market).toUpperCase()}</span>
                    {topBadgeLabel && <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">{topBadgeLabel}</span>}
                    {dataTrustLabel(item) !== "정상" && (
                      <span className={`rounded border px-1.5 py-0.5 text-[10px] ${dataTrustBadgeClass(item)}`}>{dataTrustLabel(item)}</span>
                    )}
                    {watched && <span className="rounded-md border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">관심</span>}
                  </div>
                </div>
              </div>

              {/* MONE 판단 */}
              <div className="mb-3 rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2">
                <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">MONE 판단</div>
                <div className="text-xs text-slate-200 leading-relaxed">
                  {[
                    actionText,
                    `위험 ${riskText}`,
                    patternText ? `패턴 ${patternText}` : null,
                    psConf != null ? `신뢰도 ${psConf}` : null,
                  ].filter(Boolean).join(" · ")}
                </div>
              </div>

              {/* 가격 3개 */}
              <div className="mb-3 grid grid-cols-3 gap-1.5 text-sm sm:gap-2">
                <Cell label="현재가" value={current} tone={current.includes("확인") ? "amber" : "normal"} />
                <Cell label="기준가" value={entry} tone="blue" />
                <Cell label="목표가" value={target} tone="green" />
              </div>

              {/* 태그 */}
              {visibleTags.length > 0 && (
                <div className="mb-3 flex flex-nowrap gap-1 overflow-hidden">
                  {visibleTags.map((t) => (
                    <span key={t.key} className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-bold leading-4 ${t.cls}`}>{t.label}</span>
                  ))}
                </div>
              )}

              {/* 주의 사유 */}
              {Array.isArray(item.cautionReasons) && (() => {
                const reasons = item.cautionReasons
                  .map((r: any) => safeKoreanLabel(r))
                  .filter((r: string | null): r is string => Boolean(r));
                return reasons.length > 0 ? (
                  <div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                    ⚠ {reasons.join(" · ")}
                  </div>
                ) : null;
              })()}

              {/* 버튼 */}
              <div className="flex gap-2">
                <button
                  type="button"
                  className="flex-1 inline-flex items-center justify-center rounded-xl border border-blue-600/40 bg-blue-600/10 px-3 py-2 text-xs font-bold text-blue-300 hover:bg-blue-600/20"
                  onClick={() => {
                    window.localStorage.setItem("mone_chart_symbol", String(item.symbol || ""));
                    window.localStorage.setItem("mone_chart_market", cleanMarket(item.market || market));
                    window.localStorage.setItem("mone_chart_name", displayName(item) || String(item.symbol || ""));
                    window.localStorage.setItem("mone_chart_price", String(item.currentPrice || item.price || ""));
                    window.localStorage.setItem("mone_chart_price_text", priceText(item, "current", ""));
                    window.dispatchEvent(new CustomEvent("mone-open-chart", { detail: item }));
                    onNavigate?.("chart");
                  }}
                >
                  분석 보기 →
                </button>
                <button
                  type="button"
                  className={`inline-flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-bold disabled:opacity-50 ${
                    watched
                      ? "border-amber-400/30 bg-amber-400/10 text-amber-300 hover:bg-amber-400/20"
                      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                  }`}
                  onClick={() => toggleWatch(item)}
                  disabled={watchSaving}
                >
                  <Star size={12} /> {watched ? "관심 해제" : "관심"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
