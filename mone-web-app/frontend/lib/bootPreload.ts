"use client";

export type BootStatus = "idle" | "loading" | "ready" | "degraded";

export type BootPreloadData = {
  krHomeSummary?: any;
  usHomeSummary?: any;
  krStocksCache?: any;   // balanced/swing recommendations for StocksPage
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

const BOOT_CACHE_KEY = "mone:boot-preload:v2";
const BOOT_CACHE_MAX_AGE_MS = 12 * 60 * 60 * 1000; // 12시간 (추천/요약 데이터는 Actions 1~2회/일만 변경)
// Per-request timeout — prevents the loading screen hanging on Render.com cold start.
// Render.com free tier takes up to ~30s to wake; requests queue and resolve together,
// so 8s is generous for a warm server but won't cause infinite waits on cold start.
const BOOT_REQUEST_TIMEOUT_MS = 8000;

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

function readStoredBootState(): BootPreloadState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(BOOT_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!isObject(parsed) || !isObject(parsed.bootData)) return null;
    const completedAt = Date.parse(String(parsed.bootCompletedAt || ""));
    if (!Number.isFinite(completedAt)) return null;
    if (Date.now() - completedAt > BOOT_CACHE_MAX_AGE_MS) return null;
    const state: BootPreloadState = {
      bootStatus: parsed.bootStatus === "degraded" ? "degraded" : "ready",
      bootData: parsed.bootData,
      bootCompletedAt: parsed.bootCompletedAt,
      hasBootData: hasAnyBootData(parsed.bootData),
      errors: Array.isArray(parsed.errors) ? parsed.errors : [],
    };
    return state.hasBootData ? state : null;
  } catch {
    return null;
  }
}

export function getCachedBootPreload(): BootPreloadState {
  return readStoredBootState() || EMPTY_BOOT_STATE;
}

function saveBootState(state: BootPreloadState) {
  if (typeof window === "undefined" || !state.hasBootData) return;
  try {
    window.localStorage.setItem(BOOT_CACHE_KEY, JSON.stringify(state));
  } catch {
    // Cache writes are best-effort; boot should never be blocked by storage.
  }
}

async function fetchBootJson(path: string): Promise<any> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BOOT_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(path, { cache: "no-store", signal: controller.signal });
    clearTimeout(timer);
    if (!response.ok) throw new Error(`${response.status} ${path}`);
    return response.json();
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

async function settleBootJson(path: string): Promise<{ ok: true; value: any } | { ok: false; error: string }> {
  try {
    return { ok: true, value: await fetchBootJson(path) };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function runBootPreload(onProgress?: (progress: BootProgress) => void): Promise<BootPreloadState> {
  onProgress?.({ progress: 20, message: "서버에 연결하는 중...", step: "server" });

  // All 6 requests fire simultaneously.
  // On Render.com cold start (~30s), they all queue together and are served at once —
  // much faster than the previous sequential approach (health → home → stocks = 3× waits).
  const [, krHomeSummary, usHomeSummary, krStocksCache, usStocksCache, holdingsCache] = await Promise.all([
    settleBootJson("/mone-api/health"),
    settleBootJson("/mone-api/home/summary?market=kr&limit=12"),
    settleBootJson("/mone-api/home/summary?market=us&limit=12"),
    settleBootJson("/mone-api/final/recommendations?market=kr&mode=balanced&horizon=swing&limit=50"),
    settleBootJson("/mone-api/final/recommendations?market=us&mode=balanced&horizon=swing&limit=50"),
    settleBootJson("/mone-api/api/holdings-clean?market=all&limit=500"),
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
  saveBootState(state);
  onProgress?.({ progress: 100, message: hasBootData ? "시장홈을 열고 있어요" : "앱을 여는 중...", step: "done" });
  return state;
}
