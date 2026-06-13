"use client";

export type BootStatus = "idle" | "loading" | "ready" | "degraded";

export type BootPreloadData = {
  krOperationSummary?: any;
  usOperationSummary?: any;
  krDataQuality?: any;
  usDataQuality?: any;
  krRecommendations?: any;
  usRecommendations?: any;
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
  step: "server" | "quality" | "recommendations" | "done";
};

const BOOT_CACHE_KEY = "mone:boot-preload:v1";
const BOOT_CACHE_MAX_AGE_MS = 15 * 60 * 1000;

const EMPTY_BOOT_STATE: BootPreloadState = {
  bootStatus: "idle",
  bootData: {},
  hasBootData: false,
};

function isObject(value: unknown): value is Record<string, any> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function hasPayload(value: unknown) {
  return isObject(value) && String(value.status || "").toUpperCase() !== "ERROR";
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

async function fetchBootJson(path: string) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
}

async function settleBootJson(path: string): Promise<{ ok: true; value: any } | { ok: false; error: string }> {
  try {
    return { ok: true, value: await fetchBootJson(path) };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
}

export async function runBootPreload(onProgress?: (progress: BootProgress) => void): Promise<BootPreloadState> {
  onProgress?.({ progress: 18, message: "서버 연결을 확인하고 있어요", step: "server" });
  await settleBootJson("/mone-api/health");

  onProgress?.({ progress: 42, message: "시장 요약과 데이터 상태를 미리 불러오고 있어요", step: "quality" });
  const [krOperationSummary, usOperationSummary, krDataQuality, usDataQuality] = await Promise.all([
    settleBootJson("/mone-api/final/operation-summary?market=kr"),
    settleBootJson("/mone-api/final/operation-summary?market=us"),
    settleBootJson("/mone-api/final/data-quality?market=kr&mode=quick"),
    settleBootJson("/mone-api/final/data-quality?market=us&mode=quick"),
  ]);

  onProgress?.({ progress: 72, message: "오늘의 추천 후보를 준비하고 있어요", step: "recommendations" });
  const [krRecommendations, usRecommendations] = await Promise.all([
    settleBootJson("/mone-api/final/recommendations?market=kr&limit=5"),
    settleBootJson("/mone-api/final/recommendations?market=us&limit=5"),
  ]);

  const pairs = {
    krOperationSummary,
    usOperationSummary,
    krDataQuality,
    usDataQuality,
    krRecommendations,
    usRecommendations,
  };
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
  onProgress?.({ progress: 100, message: hasBootData ? "시장홈을 열고 있어요" : "기본 화면을 열고 있어요", step: "done" });
  return state;
}
