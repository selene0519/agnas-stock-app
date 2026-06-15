"use client";

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

const BOOT_CACHE_KEY = "mone:boot-preload:v3"; // v3 — version-based invalidation
// Fallback TTL: if health check fails and we can't compare versions,
// use cached data for up to 24 hours rather than forcing a full reload.
const BOOT_FALLBACK_TTL_MS = 24 * 60 * 60 * 1000;
// Per-request timeout for full data preload
const BOOT_REQUEST_TIMEOUT_MS = 8000;
// Health check timeout — short, we just need the version fields
const HEALTH_CHECK_TIMEOUT_MS = 4000;

const EMPTY_BOOT_STATE: BootPreloadState = {
  bootStatus: "idle",
  bootData: {},
  hasBootData: false,
};

function isObject(value: unknown): value is Record<string, any> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function hasPayload(value: unknown) {
  return isObject(value) && String((value as any).status || "").toUpperCase() !== "ERROR";
}

function hasAnyBootData(data: BootPreloadData) {
  return Object.values(data).some(hasPayload);
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

function saveCache(state: BootPreloadState, krDataVersion?: string | null, usDataVersion?: string | null) {
  if (typeof window === "undefined" || !state.hasBootData) return;
  try {
    const toStore: StoredCache = { ...state, krDataVersion, usDataVersion };
    window.localStorage.setItem(BOOT_CACHE_KEY, JSON.stringify(toStore));
  } catch {
    // best-effort
  }
}

export function getCachedBootPreload(): BootPreloadState {
  const stored = readStoredCache();
  if (!stored) return EMPTY_BOOT_STATE;
  // Check fallback TTL — only used when version check is unavailable
  const completedAt = Date.parse(String(stored.bootCompletedAt || ""));
  if (Number.isFinite(completedAt) && Date.now() - completedAt > BOOT_FALLBACK_TTL_MS) return EMPTY_BOOT_STATE;
  if (!stored.hasBootData) return EMPTY_BOOT_STATE;
  return stored;
}

async function fetchWithTimeout(path: string, timeoutMs: number): Promise<any> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(path, { cache: "no-store", signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`${res.status} ${path}`);
    return res.json();
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

async function settleJson(path: string, timeoutMs: number): Promise<{ ok: true; value: any } | { ok: false; error: string }> {
  try {
    return { ok: true, value: await fetchWithTimeout(path, timeoutMs) };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

function extractDataVersions(health: any): { kr: string | null; us: string | null } {
  const v = health?.dataVersions;
  if (isObject(v)) {
    return {
      kr: v.kr ? String(v.kr) : null,
      us: v.us ? String(v.us) : null,
    };
  }
  // fallback: use latestFileModifiedAt from marketQuality
  const mq = health?.marketQuality;
  if (isObject(mq)) {
    return {
      kr: mq.kr?.latestFileModifiedAt ? String(mq.kr.latestFileModifiedAt) : null,
      us: mq.us?.latestFileModifiedAt ? String(mq.us.latestFileModifiedAt) : null,
    };
  }
  return { kr: null, us: null };
}

export async function runBootPreload(onProgress?: (progress: BootProgress) => void): Promise<BootPreloadState> {
  onProgress?.({ progress: 10, message: "데이터 버전 확인 중...", step: "server" });

  // Step 1: Quick health check to get current data versions (4s timeout)
  const healthResult = await settleJson("/mone-api/health", HEALTH_CHECK_TIMEOUT_MS);
  const currentVersions = healthResult.ok ? extractDataVersions(healthResult.value) : null;

  // Step 2: Compare with cached versions
  const stored = readStoredCache();
  if (stored?.hasBootData && currentVersions) {
    const krMatch = !currentVersions.kr || stored.krDataVersion === currentVersions.kr;
    const usMatch = !currentVersions.us || stored.usDataVersion === currentVersions.us;
    if (krMatch && usMatch) {
      // Versions match — use cache, no need to reload
      onProgress?.({ progress: 100, message: "시장홈을 열고 있어요", step: "done" });
      return stored;
    }
  }

  // Step 3: Versions differ (or no cache) → full data reload
  onProgress?.({ progress: 30, message: "새 예측 데이터 받는 중...", step: "home" });

  const [, krHomeSummary, usHomeSummary, krStocksCache, usStocksCache, holdingsCache] = await Promise.all([
    settleJson("/mone-api/health", BOOT_REQUEST_TIMEOUT_MS),
    settleJson("/mone-api/home/summary?market=kr&limit=12", BOOT_REQUEST_TIMEOUT_MS),
    settleJson("/mone-api/home/summary?market=us&limit=12", BOOT_REQUEST_TIMEOUT_MS),
    settleJson("/mone-api/final/recommendations?market=kr&mode=balanced&horizon=swing&limit=50", BOOT_REQUEST_TIMEOUT_MS),
    settleJson("/mone-api/final/recommendations?market=us&mode=balanced&horizon=swing&limit=50", BOOT_REQUEST_TIMEOUT_MS),
    settleJson("/mone-api/api/holdings-clean?market=all&limit=500", BOOT_REQUEST_TIMEOUT_MS),
  ]);

  const pairs = { krHomeSummary, usHomeSummary, krStocksCache, usStocksCache, holdingsCache };
  const bootData: BootPreloadData = {};
  const errors: string[] = [];
  Object.entries(pairs).forEach(([key, result]) => {
    if (result.ok === true) bootData[key as keyof BootPreloadData] = result.value;
    else errors.push(`${key}: ${result.error}`);
  });

  const hasBootData = hasAnyBootData(bootData);
  const state: BootPreloadState = {
    bootStatus: errors.length ? "degraded" : "ready",
    bootData,
    bootCompletedAt: new Date().toISOString(),
    hasBootData,
    errors,
  };

  if (hasBootData) {
    saveCache(state, currentVersions?.kr, currentVersions?.us);
  }

  onProgress?.({ progress: 100, message: hasBootData ? "시장홈을 열고 있어요" : "앱을 여는 중...", step: "done" });
  return state;
}
