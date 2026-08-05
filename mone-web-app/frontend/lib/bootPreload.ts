"use client";

import { clearApiSnapshots, writeApiSnapshot } from "./api";
import { getAuthenticatedUserId, getUserToken } from "./userId";

export type BootStatus = "idle" | "loading" | "ready" | "degraded";

export type BootPreloadData = {
  krHomeSummary?: any;
  usHomeSummary?: any;
  krStocksCache?: any;
  usStocksCache?: any;
  holdingsCache?: any;
};

export type BootPreloadState = {
  bootStatus: BootStatus;
  bootData: BootPreloadData;
  bootCompletedAt?: string;
  hasBootData: boolean;
  errors?: string[];
};

type BootProgress = {
  progress: number;
  message: string;
  step: "server" | "home" | "stocks" | "done";
};

type StoredCache = BootPreloadState & {
  krDataVersion?: string | null;
  usDataVersion?: string | null;
};

type JsonResult = { ok: true; value: any } | { ok: false; error: string };
type HomeSnapshotResult = { ok: true; value: any; stocksCache: any } | { ok: false; error: string };

const BOOT_CACHE_KEY = "mone:boot-preload:v6";
const BOOT_FALLBACK_TTL_MS = 24 * 60 * 60 * 1000;
const HEALTH_CHECK_TIMEOUT_MS = 8000;
const SNAPSHOT_FETCH_TIMEOUT_MS = 12000;

const EMPTY_BOOT_STATE: BootPreloadState = {
  bootStatus: "idle",
  bootData: {},
  hasBootData: false,
};

function isObject(value: unknown): value is Record<string, any> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function readStoredCache(): StoredCache | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(BOOT_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!isObject(parsed) || !isObject(parsed.bootData)) return null;
    return parsed as StoredCache;
  } catch {
    return null;
  }
}

function writeStoredCache(state: StoredCache) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(BOOT_CACHE_KEY, JSON.stringify(state));
  } catch {
    // Best-effort cache only.
  }
}

export function getCachedBootPreload(): BootPreloadState {
  const stored = readStoredCache();
  if (!stored?.hasBootData) return EMPTY_BOOT_STATE;
  const completedAt = Date.parse(String(stored.bootCompletedAt || ""));
  if (Number.isFinite(completedAt) && Date.now() - completedAt > BOOT_FALLBACK_TTL_MS) return EMPTY_BOOT_STATE;
  return stored;
}

function bootRequestHeaders(): Record<string, string> {
  try {
    const userId = getAuthenticatedUserId();
    const token = getUserToken();
    return {
      ...(userId ? { "x-mone-user": userId } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  } catch {
    return {};
  }
}

async function fetchWithTimeout(path: string, timeoutMs: number): Promise<any> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(path, { cache: "no-store", headers: bootRequestHeaders(), signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`${res.status} ${path}`);
    return res.json();
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

async function settleJson(path: string, timeoutMs: number): Promise<JsonResult> {
  try {
    return { ok: true, value: await fetchWithTimeout(path, timeoutMs) };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

function resultError(result: JsonResult | HomeSnapshotResult) {
  return result.ok === false ? result.error : "";
}

function marketDataVersion(health: any, market: "kr" | "us"): string | null {
  if (!isObject(health)) return null;
  const versions = health.dataVersions;
  if (isObject(versions)) {
    const marketVersion = versions[market] || versions[market.toUpperCase()];
    return JSON.stringify(marketVersion || versions);
  }
  const quality = health.dataQuality || health.checks;
  if (isObject(quality)) {
    const marketQuality = quality[market] || quality[market.toUpperCase()];
    if (marketQuality) return JSON.stringify(marketQuality);
  }
  const fallback = health.generatedAt || health.updatedAt || health.timestamp || "";
  return fallback ? String(fallback) : null;
}

function extractBalancedSwingItems(homeSummary: any): any[] {
  const matrix = homeSummary?.matrix;
  if (!isObject(matrix)) return [];
  const candidates = [
    (matrix as any).balanced_swing,
    (matrix as any)["balanced-swing"],
    (matrix as any).balanced?.swing,
  ];
  for (const candidate of candidates) {
    if (Array.isArray(candidate?.items)) return candidate.items;
  }
  for (const value of Object.values(matrix)) {
    if (isObject(value) && Array.isArray((value as any).items)) return (value as any).items;
  }
  return [];
}

async function fetchHomeSnapshot(market: "kr" | "us"): Promise<HomeSnapshotResult> {
  const result = await settleJson(`/mone-api/api/home/summary?market=${market}&limit=12`, SNAPSHOT_FETCH_TIMEOUT_MS);
  if (result.ok === false) return result;

  writeApiSnapshot("/api/home/summary", { market, limit: 12 }, result.value);

  const items = extractBalancedSwingItems(result.value);
  const stocksCache = {
    status: result.value?.status || "OK",
    market,
    mode: "balanced",
    horizon: "swing",
    count: items.length,
    items,
    source: "boot_home_summary_snapshot",
  };
  writeApiSnapshot("/api/final/recommendations", { market, mode: "balanced", horizon: "swing", limit: 50, watchOnly: false }, stocksCache);
  writeApiSnapshot("/api/final/recommendations", { market, mode: "balanced", horizon: "swing", limit: 50 }, stocksCache);
  return { ok: true as const, value: result.value, stocksCache };
}

async function fetchApiSnapshot(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>,
  timeoutMs = 25000,
) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const query = search.toString();
  const result = await settleJson(`/mone-api${path}${query ? `?${query}` : ""}`, timeoutMs);
  if (result.ok) writeApiSnapshot(path, params, result.value);
  return result;
}

async function fetchAuxiliarySnapshots(market: "kr" | "us") {
  const jobs = [
    fetchApiSnapshot("/api/market/fear-greed", { market }, 12000),
    fetchApiSnapshot("/api/final/operation-summary", { market, mode: "balanced", horizon: "swing" }, 25000),
    fetchApiSnapshot("/api/holdings-clean", { market, limit: 500 }, 12000),
    fetchApiSnapshot("/api/earnings-calendar", { market, days: 14 }, 12000),
    fetchApiSnapshot("/api/calendar/today", { market }, 12000),
    fetchApiSnapshot("/api/risk/near-alerts", { market, thresholdPct: 5 }, 12000),
    fetchApiSnapshot("/api/signals/ledger", { market, limit: 12 }, 12000),
    fetchApiSnapshot("/api/watchlist-edit", { market: "all" }, 12000),
    fetchApiSnapshot("/api/watchlist/groups", { market }, 12000),
    fetchApiSnapshot("/api/sectors", { market }, 12000),
  ];
  return Promise.all(jobs);
}

async function fetchChartSnapshot(market: "kr" | "us", homeSummary: any) {
  const symbol = String(extractBalancedSwingItems(homeSummary)[0]?.symbol || "").toUpperCase();
  if (!symbol) return [];
  const indexSymbol = market === "us" ? "SPY" : "KOSPI";
  const jobs = [
    fetchApiSnapshot("/api/ohlcv", { market, symbol, limit: 260, futureProjectionBars: 12 }, 30000),
    fetchApiSnapshot("/api/final/recommendation-detail", { market, symbol }, 30000),
    fetchApiSnapshot("/api/news", { market, limit: 200 }, 12000),
    fetchApiSnapshot("/api/disclosures", { market, limit: 200, watchOnly: false }, 12000),
    fetchApiSnapshot("/api/company-analysis", { market, q: symbol, limit: 20 }, 20000),
    fetchApiSnapshot("/api/pattern/strategy", { market, symbol }, 20000),
    fetchApiSnapshot(`/api/chart/index/${indexSymbol}`, { market, limit: 520 }, 20000),
    fetchApiSnapshot(`/api/chart/analysis/${symbol}`, { market }, 20000),
    fetchApiSnapshot(`/api/chart/similar-pattern/${symbol}`, { market }, 20000),
    fetchApiSnapshot(`/api/symbol/${symbol}/events`, { market }, 12000),
  ];
  return Promise.all(jobs);
}

function snapshotErrors(results: JsonResult[]): string[] {
  return results.flatMap((result) => result.ok === false ? [result.error] : []);
}

async function preloadSupportingSnapshots(krHomeSummary: any, usHomeSummary: any): Promise<string[]> {
  const [krAuxiliary, usAuxiliary, krChart, usChart] = await Promise.all([
    fetchAuxiliarySnapshots("kr"),
    fetchAuxiliarySnapshots("us"),
    krHomeSummary ? fetchChartSnapshot("kr", krHomeSummary) : Promise.resolve([]),
    usHomeSummary ? fetchChartSnapshot("us", usHomeSummary) : Promise.resolve([]),
  ]);
  return [
    ...snapshotErrors(krAuxiliary),
    ...snapshotErrors(usAuxiliary),
    ...snapshotErrors(krChart),
    ...snapshotErrors(usChart),
  ];
}

export async function runBootPreload(onProgress?: (progress: BootProgress) => void): Promise<BootPreloadState> {
  onProgress?.({ progress: 12, message: "서버와 데이터 버전을 확인하는 중...", step: "server" });

  const stored = readStoredCache();
  const healthResult = await settleJson("/mone-api/health", HEALTH_CHECK_TIMEOUT_MS);
  const krDataVersion = healthResult.ok ? marketDataVersion(healthResult.value, "kr") : stored?.krDataVersion ?? null;
  const usDataVersion = healthResult.ok ? marketDataVersion(healthResult.value, "us") : stored?.usDataVersion ?? null;

  if (stored?.hasBootData && stored.krDataVersion === krDataVersion && stored.usDataVersion === usDataVersion) {
    const supportErrors = await preloadSupportingSnapshots(
      stored.bootData.krHomeSummary,
      stored.bootData.usHomeSummary,
    );
    const errors = [resultError(healthResult), ...supportErrors].filter(Boolean);
    onProgress?.({ progress: 100, message: "저장된 예측 스냅샷을 여는 중...", step: "done" });
    return {
      ...stored,
      bootStatus: errors.length === 0 ? "ready" : "degraded",
      errors,
    };
  }

  if (stored?.hasBootData && (!healthResult.ok || (!krDataVersion && !usDataVersion))) {
    onProgress?.({ progress: 100, message: "기존 예측 스냅샷을 여는 중...", step: "done" });
    return {
      ...stored,
      bootStatus: "degraded",
      errors: healthResult.ok ? stored.errors : [resultError(healthResult)],
    };
  }

  clearApiSnapshots();

  onProgress?.({ progress: 32, message: "국장 예측 스냅샷을 받는 중...", step: "home" });
  const [krHome, usHome] = await Promise.all([
    fetchHomeSnapshot("kr"),
    fetchHomeSnapshot("us"),
  ]);

  onProgress?.({ progress: 66, message: "미장 예측 스냅샷을 받는 중...", step: "stocks" });

  onProgress?.({ progress: 84, message: "보조 화면 데이터를 저장하는 중...", step: "stocks" });
  const [krAuxiliary, usAuxiliary, krChart, usChart] = await Promise.all([
    fetchAuxiliarySnapshots("kr"),
    fetchAuxiliarySnapshots("us"),
    krHome.ok ? fetchChartSnapshot("kr", krHome.value) : Promise.resolve([]),
    usHome.ok ? fetchChartSnapshot("us", usHome.value) : Promise.resolve([]),
  ]);

  onProgress?.({ progress: 92, message: "대표 차트 분석을 저장하는 중...", step: "stocks" });
  const errors = [
    resultError(healthResult),
    resultError(krHome),
    resultError(usHome),
    ...snapshotErrors(krAuxiliary),
    ...snapshotErrors(usAuxiliary),
    ...snapshotErrors(krChart),
    ...snapshotErrors(usChart),
  ].filter(Boolean);

  const state: BootPreloadState = {
    bootStatus: errors.length === 0 ? "ready" : "degraded",
    bootData: {
      krHomeSummary: krHome.ok ? krHome.value : stored?.bootData?.krHomeSummary,
      usHomeSummary: usHome.ok ? usHome.value : stored?.bootData?.usHomeSummary,
      krStocksCache: krHome.ok ? krHome.stocksCache : stored?.bootData?.krStocksCache,
      usStocksCache: usHome.ok ? usHome.stocksCache : stored?.bootData?.usStocksCache,
      holdingsCache: krHome.ok ? krHome.value?.holdings : stored?.bootData?.holdingsCache,
    },
    bootCompletedAt: new Date().toISOString(),
    hasBootData: Boolean((krHome.ok && krHome.value) || (usHome.ok && usHome.value) || stored?.hasBootData),
    errors,
  };

  writeStoredCache({ ...state, krDataVersion, usDataVersion });
  onProgress?.({ progress: 100, message: "오늘의 예측 화면을 여는 중...", step: "done" });
  return state;
}
