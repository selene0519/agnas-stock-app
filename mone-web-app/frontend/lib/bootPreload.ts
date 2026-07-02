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

const HOME_SUMMARY_TIMEOUT_MS = 7000;

function detectDefaultMarket(): "kr" | "us" {
  const hour = new Date().getHours();
  // 09:00~15:30 KST 범위면 국장, 그 외 미장
  return hour >= 9 && hour < 16 ? "kr" : "us";
}

export async function runBootPreload(onProgress?: (progress: BootProgress) => void): Promise<BootPreloadState> {
  onProgress?.({ progress: 15, message: "서버 상태 확인 중...", step: "server" });

  const primaryMarket = detectDefaultMarket();
  const secondaryMarket = primaryMarket === "kr" ? "us" : "kr";

  // 헬스체크 + 주 시장 홈 데이터 병렬 로드
  const [healthResult, primaryResult] = await Promise.all([
    settleJson("/mone-api/health", HEALTH_CHECK_TIMEOUT_MS),
    settleJson(`/mone-api/api/home/summary?market=${primaryMarket}&limit=12`, HOME_SUMMARY_TIMEOUT_MS),
  ]);

  onProgress?.({ progress: 70, message: "추천 데이터 로딩 중...", step: "home" });

  // 보조 시장도 병렬로 가져오되, 실패해도 무시
  const secondaryResult = await settleJson(`/mone-api/api/home/summary?market=${secondaryMarket}&limit=12`, HOME_SUMMARY_TIMEOUT_MS);

  const bootData: BootPreloadData = {};
  if (primaryResult.ok) {
    if (primaryMarket === "kr") bootData.krHomeSummary = primaryResult.value;
    else bootData.usHomeSummary = primaryResult.value;
  }
  if (secondaryResult.ok) {
    if (secondaryMarket === "kr") bootData.krHomeSummary = secondaryResult.value;
    else bootData.usHomeSummary = secondaryResult.value;
  }

  const hasBootData = Boolean(bootData.krHomeSummary || bootData.usHomeSummary);
  const errors: string[] = [];
  if ("error" in healthResult) errors.push(healthResult.error);
  if ("error" in primaryResult) errors.push(primaryResult.error);

  const state: BootPreloadState = {
    bootStatus: healthResult.ok ? (hasBootData ? "ready" : "degraded") : "degraded",
    bootData,
    bootCompletedAt: new Date().toISOString(),
    hasBootData,
    errors,
  };

  // 캐시에 저장 (24h TTL — getCachedBootPreload가 읽음)
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(BOOT_CACHE_KEY, JSON.stringify(state));
    }
  } catch { /* 스토리지 가득 차도 무시 */ }

  onProgress?.({ progress: 100, message: "화면을 여는 중...", step: "done" });
  return state;
}
