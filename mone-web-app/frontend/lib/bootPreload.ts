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

const BOOT_CACHE_KEY = "mone:boot-preload:v4";
const BOOT_FALLBACK_TTL_MS = 24 * 60 * 60 * 1000;
const HEALTH_CHECK_TIMEOUT_MS = 4000;

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

export function getCachedBootPreload(): BootPreloadState {
  const stored = readStoredCache();
  if (!stored?.hasBootData) return EMPTY_BOOT_STATE;
  const completedAt = Date.parse(String(stored.bootCompletedAt || ""));
  if (Number.isFinite(completedAt) && Date.now() - completedAt > BOOT_FALLBACK_TTL_MS) return EMPTY_BOOT_STATE;
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

export async function runBootPreload(onProgress?: (progress: BootProgress) => void): Promise<BootPreloadState> {
  onProgress?.({ progress: 20, message: "서버 상태 확인 중...", step: "server" });

  // Keep launch light. Market prediction snapshots are cached and refreshed by
  // each page, so app boot should not eagerly fetch KR+US home/recommendations.
  const healthResult = await settleJson("/mone-api/health", HEALTH_CHECK_TIMEOUT_MS);

  const state: BootPreloadState = {
    bootStatus: healthResult.ok ? "ready" : "degraded",
    bootData: {},
    bootCompletedAt: new Date().toISOString(),
    hasBootData: false,
    errors: healthResult.ok === true ? [] : [healthResult.error],
  };

  onProgress?.({ progress: 100, message: "화면을 여는 중...", step: "done" });
  return state;
}
