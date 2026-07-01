export type Market = "kr" | "us" | "all";
export type Mode = "conservative" | "balanced" | "aggressive" | "all";
export type Horizon = "short" | "swing" | "mid" | "long" | "all";

import { getUserId } from "./userId";

function getMoneUserHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const id = getUserId();
    return id ? { "x-mone-user": id } : {};
  } catch {
    return {};
  }
}

export interface ApiList<T = any> {
  status: string;
  market?: string;
  count?: number;
  items?: T[];
  error?: string;
  [key: string]: any;
}

/** 추천 카드 아이템 타입 — 4차 이벤트 필드 + 5차 adaptive 필드 포함 */
export interface RecommendationItem {
  symbol: string;
  name?: string;
  market?: string;
  mode?: string;
  horizon?: string;
  currentPrice?: number;
  entry?: number;
  stop?: number;
  target?: number;
  opportunityScore?: number;
  entryScore?: number;
  riskScore?: number;
  finalRankScore?: number;
  decisionBucket?: string;
  buyTiming?: string;
  sellTiming?: string;
  newEntryDecision?: string;
  holderDecision?: string;
  recommended?: boolean;
  executionStatus?: string;
  exitStatus?: string;
  pnlText?: string;
  eventBadges?: string[];
  eventBadgesText?: string;
  eventRiskScore?: number;
  newsReliabilityScore?: number;
  surgeLabel?: string;
  surgeReason?: string;
  eventContext?: string;
  dataSourceType?: string;
  // 4차 이벤트 컨텍스트 필드
  eventContextUsed?: boolean;
  newsEventTag?: string;
  disclosureEventTag?: string;
  earningsEventTag?: string;
  macroEventTag?: string;
  sectorEventTag?: string;
  eventReliabilityScore?: number;
  eventSummary?: string;
  eventDataSourceType?: string;
  eventScoreAdjustment?: number;
  // 5차 adaptive score 자가보정 필드
  adaptiveScoreUsed?: boolean;
  adaptiveScoreAdjustment?: number;
  adaptiveScoreSummary?: string;
  adaptiveSignalBreakdown?: Record<string, number>;
  adaptiveConfidence?: number;
  adaptiveLearningStatus?: "ACTIVE" | "LOW_SAMPLE" | "DISABLED" | "DATA_INSUFFICIENT";
  // 6차 UI 반영 여부 필드 (차트신호·빗각·지지·저항·가짜돌파)
  chartSignalUsed?: boolean;
  chartSignalSummary?: string;
  trendlineUsed?: boolean;
  trendlineLearningStatus?: string;
  trendlineProjected5d?: number;
  trendlineProjected20d?: number;
  trendlineProjected60d?: number;
  supportUsed?: boolean;
  resistanceUsed?: boolean;
  fakeBreakoutRiskUsed?: boolean;
  // 6차 score breakdown 필드
  baseScore?: number;
  chartScoreAdjustment?: number;
  finalScore?: number;
  setupScore?: number;
  overextensionRisk?: number;
  momentumContinuationScore?: number;
  diagnosticSignals?: Array<{
    key: string;
    label: string;
    value: number;
    role: "diagnostic_only";
    finalScoreIncluded: false;
  }>;
  diagnosticSignalNote?: string;
  validationConfidence?: number;
  entryBasis?: string;
  targetBasis?: string;
  stopBasis?: string;
  [key: string]: any;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/mone-api";
const DIRECT_BACKEND = process.env.NEXT_PUBLIC_DIRECT_API_BASE_URL || "";
const configuredTimeout = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS || 90000);
const API_TIMEOUT_MS = Number.isFinite(configuredTimeout) && configuredTimeout > 0
  ? configuredTimeout
  : 90000;

function isAbsoluteUrl(value: string) {
  return value.startsWith("http://") || value.startsWith("https://");
}

function isLocalhostUrl(value: string) {
  try {
    const hostname = new URL(value).hostname;
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
  } catch {
    return false;
  }
}

function canUseDirectBackendFallback() {
  if (!DIRECT_BACKEND || !isAbsoluteUrl(DIRECT_BACKEND)) return false;
  if (typeof window === "undefined") return true;

  const pageHost = window.location.hostname;
  const pageIsLocal = pageHost === "localhost" || pageHost === "127.0.0.1" || pageHost === "::1";
  return pageIsLocal || !isLocalhostUrl(DIRECT_BACKEND);
}

function buildUrl(baseUrl: string, path: string, params?: Record<string, string | number | boolean | undefined | null>) {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const isAbsolute = isAbsoluteUrl(baseUrl);
  const origin = typeof window === "undefined" ? "http://localhost:3200" : window.location.origin;
  const url = new URL(`${baseUrl}${cleanPath}`, isAbsolute ? undefined : origin);

  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });

  if (typeof window === "undefined" && !isAbsolute) {
    return url.toString().replace("http://localhost:3200", "");
  }

  return url.toString();
}

// 일시적 오류에만 재시도 (네트워크 단절, 503 cold-start)
// 비즈니스 오류(404, 400, 422)는 재시도 하지 않음
function isRetryableStatus(status: number) {
  return status === 503 || status === 502 || status === 504;
}

async function fetchJson<T>(url: string, externalSignal?: AbortSignal, retryCount = 0): Promise<T> {
  const MAX_RETRIES = 2;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);

  if (externalSignal?.aborted) {
    clearTimeout(timer);
    return { status: "ERROR", error: "Request cancelled", items: [], count: 0 } as T;
  }
  externalSignal?.addEventListener("abort", () => controller.abort(), { once: true });

  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json", ...getMoneUserHeader() },
      signal: controller.signal,
    });

    const text = await response.text().catch(() => "");

    if (!response.ok) {
      if (response.status === 503) {
        let body: any = {};
        try { body = JSON.parse(text); } catch { /* ignore */ }
        if (body?.error === "BACKEND_COLD_START_TIMEOUT") {
          return {
            status: "ERROR",
            error: "서버 초기화 중입니다. 잠시 후 새로고침해 주세요. (약 30~60초 소요)",
            retryAfter: body.retryAfter || 30,
            items: [], count: 0,
          } as T;
        }
        // 일반 503: 지수 백오프 재시도
        if (retryCount < MAX_RETRIES && !externalSignal?.aborted) {
          const delay = Math.min(2000 * 2 ** retryCount, 10000);
          await new Promise(r => setTimeout(r, delay));
          return fetchJson<T>(url, externalSignal, retryCount + 1);
        }
      }
      if (isRetryableStatus(response.status) && retryCount < MAX_RETRIES && !externalSignal?.aborted) {
        const delay = Math.min(1500 * 2 ** retryCount, 8000);
        await new Promise(r => setTimeout(r, delay));
        return fetchJson<T>(url, externalSignal, retryCount + 1);
      }
      return {
        status: "ERROR",
        error: `${response.status} ${response.statusText} ${text.slice(0, 300)}`,
        items: [], count: 0,
      } as T;
    }

    try {
      return JSON.parse(text) as T;
    } catch {
      return {
        status: "ERROR",
        error: `Invalid JSON response: ${text.slice(0, 300)}`,
        items: [], count: 0,
      } as T;
    }
  } catch (error) {
    const isAbort = error instanceof DOMException && error.name === "AbortError";
    // 네트워크 단절은 재시도
    if (!isAbort && retryCount < MAX_RETRIES && !externalSignal?.aborted) {
      const delay = Math.min(1000 * 2 ** retryCount, 6000);
      await new Promise(r => setTimeout(r, delay));
      return fetchJson<T>(url, externalSignal, retryCount + 1);
    }
    return {
      status: "ERROR",
      error: isAbort
        ? `요청 시간 초과 (${API_TIMEOUT_MS / 1000}초)`
        : error instanceof Error ? error.message : String(error),
      items: [], count: 0,
    } as T;
  } finally {
    clearTimeout(timer);
  }
}

export async function apiGet<T = any>(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>,
  signal?: AbortSignal
): Promise<T> {
  const proxyUrl = buildUrl(API_BASE, path, params);
  const proxyResult: any = await fetchJson<T>(proxyUrl, signal);

  if (proxyResult?.status !== "ERROR") {
    return proxyResult as T;
  }

  // 취소된 경우 direct fallback 시도하지 않음
  if (signal?.aborted) {
    return proxyResult as T;
  }

  if (!canUseDirectBackendFallback()) {
    return {
      ...proxyResult,
      directFallbackSkipped: true,
      directFallbackReason: DIRECT_BACKEND
        ? "Direct localhost backend fallback is disabled outside local development"
        : "Direct backend fallback is not configured",
    } as T;
  }

  const directUrl = buildUrl(DIRECT_BACKEND, path, params);
  const directResult: any = await fetchJson<T>(directUrl, signal);

  if (directResult?.status === "ERROR") {
    directResult.proxyError = proxyResult.error;
  }

  return directResult as T;
}

export function money(value: number | string | null | undefined, market: Market = "kr") {
  const n = Number(String(value ?? "").replace(/,/g, ""));
  if (!Number.isFinite(n) || n <= 0) return "-";
  if (market === "us") return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  return `${Math.round(n).toLocaleString()}원`;
}


export async function apiPost<T = any>(
  path: string,
  body?: any,
  params?: Record<string, string | number | boolean | undefined | null>
): Promise<T> {
  const postJson = async (url: string): Promise<T> => {
    try {
      const response = await fetch(url, {
        method: "POST",
        cache: "no-store",
        headers: { Accept: "application/json", "Content-Type": "application/json", ...getMoneUserHeader() },
        body: JSON.stringify(body || {}),
      });
      const text = await response.text().catch(() => "");
      if (!response.ok) {
        return { status: "ERROR", error: `${response.status} ${response.statusText} ${text.slice(0, 500)}`, items: [], count: 0 } as T;
      }
      try {
        return JSON.parse(text) as T;
      } catch {
        return { status: "ERROR", error: "Invalid JSON response", items: [], count: 0 } as T;
      }
    } catch (error) {
      return { status: "ERROR", error: error instanceof Error ? error.message : String(error), items: [], count: 0 } as T;
    }
  };

  const proxyUrl = buildUrl(API_BASE, path, params);
  const proxyResult: any = await postJson(proxyUrl);
  if (proxyResult?.status !== "ERROR") return proxyResult as T;

  if (!canUseDirectBackendFallback()) {
    return {
      ...proxyResult,
      directFallbackSkipped: true,
      directFallbackReason: DIRECT_BACKEND
        ? "Direct localhost backend fallback is disabled outside local development"
        : "Direct backend fallback is not configured",
    } as T;
  }

  const directUrl = buildUrl(DIRECT_BACKEND, path, params);
  const directResult: any = await postJson(directUrl);
  if (directResult?.status === "ERROR") directResult.proxyError = proxyResult.error;
  return directResult as T;
}

export const mone = {
  get: apiGet,
  symbols: (p?: { market?: Market; q?: string; watchOnly?: boolean; limit?: number }) =>
    apiGet<ApiList>("/api/symbols", p),
  watchlist: (p?: { market?: Market; limit?: number }) =>
    apiGet<ApiList>("/api/watchlist", p),
  homeSummary: (p?: { market?: Market; limit?: number }) =>
    apiGet<ApiList>("/api/home/summary", p),
  watchlistScored: (p?: { market?: Market; mode?: string; horizon?: string }) =>
    apiGet<ApiList>("/api/watchlist/scored", p),
  sectorsList: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/sectors", p),
  disclosureCalendar: (p?: { market?: Market; days?: number }, signal?: AbortSignal) =>
    apiGet<ApiList>("/api/disclosure-calendar", p, signal),
  watchlistGroups: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/watchlist/groups", p),
  watchlistSetGroup: (body: { market?: string; symbol: string; group: string }) =>
    apiPost<ApiList>("/api/watchlist/set-group", body),
  correlationMatrix: (p?: { market?: Market; days?: number }) =>
    apiGet<ApiList>("/api/advanced/correlation", p),
  advancedScanner: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number; deep?: boolean }) =>
    apiGet<ApiList>("/api/advanced/scanner", p),
  calculatorKelly: (body: { winRate?: number; payoffRatio?: number; capital?: number }) =>
    apiPost<any>("/api/advanced/calculator/kelly", body),
  calculatorRiskReward: (body: { entry?: number; stop?: number; target?: number }) =>
    apiPost<any>("/api/advanced/calculator/risk-reward", body),
  monteCarlo: (body: { currentPrice?: number; expectedReturn?: number; volatility?: number; days?: number; simulations?: number }) =>
    apiPost<any>("/api/advanced/monte-carlo", body),
  benchmarkComparison: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/risk/benchmark", p),
  validationDashboard: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/validation/dashboard", p),
  recommendationValidationSnapshot: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number; snapshotDate?: string }) =>
    apiPost<ApiList>("/api/validation/recommendations/snapshot", {}, p),
  recommendationValidation: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/validation/recommendations", p),
  recommendationValidationSummary: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/validation/recommendations/summary", p),
  recommendationValidationBySignal: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/validation/recommendations/by-signal", p),
  sectorExposure: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/risk/sector-exposure", p),
  journalGet: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/journal", p),
  journalAdd: (body: { market?: string; symbol?: string; name?: string; action?: string; price?: number; qty?: number; memo: string; review?: string; result?: string; returnPct?: number; tags?: string[] }) =>
    apiPost<ApiList>("/api/journal/add", body),
  journalUpdate: (id: string, body: Partial<{ memo: string; review: string; result: string; returnPct: number; tags: string[] }>) =>
    fetch(buildUrl(API_BASE, `/api/journal/${id}`), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json()),
  journalDelete: (id: string) =>
    fetch(buildUrl(API_BASE, `/api/journal/${id}`), { method: "DELETE" }).then(r => r.json()),
  recommendations: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; cash?: number; limit?: number; watchOnly?: boolean }, signal?: AbortSignal) =>
    apiGet<ApiList<RecommendationItem>>("/api/final/recommendations", p, signal),
  recommendationDetail: (p: { market?: Market; symbol: string }, signal?: AbortSignal) =>
    apiGet<ApiList>("/api/final/recommendation-detail", p, signal),
  candidates: (p?: { market?: Market; strategy?: Mode | string; term?: Horizon | string; cash?: number; limit?: number; watchOnly?: boolean }) =>
    apiGet<ApiList>("/api/v1/candidates", p),
  report: (type: "premarket" | "intraday" | "closing", p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>(`/api/reports/${type}`, p),
  virtualSummary: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/virtual/summary", p),
  virtualTrades: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string; status?: string; limit?: number }) =>
    apiGet<ApiList>("/api/journal/virtual-trades", p),
  virtualTradeCapture: (body?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string; limit?: number; includeEngine?: boolean }) =>
    apiPost<ApiList>("/api/journal/virtual-trades/capture", body || {}),
  virtualTradeEvaluate: (body?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string; limit?: number; force?: boolean }) =>
    apiPost<ApiList>("/api/journal/virtual-trades/evaluate", body || {}),
  journalFailurePatterns: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string }) =>
    apiGet<ApiList>("/api/journal/failure-patterns", p),
  journalCalibrationSuggestions: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string }) =>
    apiGet<ApiList>("/api/journal/calibration-suggestions", p),
  journalCalibrationApprove: (suggestionId: string, body?: { decision?: "APPROVED" | "REJECTED"; reviewedBy?: string; note?: string; beforeParams?: any; afterParams?: any }) =>
    apiPost<ApiList>(`/api/journal/calibration-suggestions/${encodeURIComponent(suggestionId)}/approve`, body || {}),
  journalCalibrationApplyApproved: (body?: { appliedBy?: string }) =>
    apiPost<ApiList>("/api/journal/calibration-suggestions/apply-approved", body || {}),
  journalSelfLearningStatus: (p?: { market?: Market | string }) =>
    apiGet<any>("/api/journal/self-learning/status", p),
  journalOpsDashboard: (p?: { market?: Market | string }) =>
    apiGet<any>("/api/journal/ops-dashboard", p),
  journalSelfLearningAutoCalibrate: (body?: { market?: Market | string; appliedBy?: string; apply?: boolean; maxApplications?: number }) =>
    apiPost<any>("/api/journal/self-learning/auto-calibrate", body || {}),
  journalPerformanceGate: (body?: { market?: Market | string; autoRollback?: boolean }) =>
    apiPost<any>("/api/journal/self-learning/performance-gate", body || {}),
  journalSelfLearningRollback: (body?: { version?: number; requestedBy?: string }) =>
    apiPost<any>("/api/journal/self-learning/rollback", body || {}),
  journalHistoricalReplay: (body: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; asOfDate: string; limit?: number; evaluateAfter?: boolean }) =>
    apiPost<ApiList>("/api/journal/historical-replay", body),
  journalHistoricalReplayBackfill: (body: { market?: Market | string; mode?: Mode | string; horizon?: Horizon | string; startDate: string; endDate?: string; stepDays?: number; limit?: number; maxRuns?: number; evaluateAfter?: boolean }) =>
    apiPost<ApiList>("/api/journal/historical-replay/backfill", body),
  journalMarketAnalogsRun: (body?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; asOfDate?: string; analogLimit?: number; replayLimit?: number; runReplay?: boolean }) =>
    apiPost<ApiList>("/api/journal/market-analogs/run", body || {}),
  journalAutoCaptureStatus: () =>
    apiGet<ApiList>("/api/journal/auto-capture/status"),
  journalAutoCaptureRun: (body?: { market?: Market; sourceType?: string; journalSession?: string; limit?: number; includeEngine?: boolean; evaluateAfter?: boolean; force?: boolean }) =>
    apiPost<ApiList>("/api/journal/auto-capture/run", body || {}),
  journalTradeReview: (journalId: string, body?: { reviewedBy?: string; reviewerNote?: string }) =>
    apiPost<ApiList>(`/api/journal/virtual-trades/${encodeURIComponent(journalId)}/review`, body || {}),
  journalAnalytics: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string }) =>
    apiGet<ApiList>("/api/journal/analytics", p),
  virtualFailureAnalytics: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string }) =>
    apiGet<ApiList>("/api/virtual/failure-analytics", p),
  virtualImprovementPriorities: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string; regime?: string; recommendationBucket?: string }) =>
    apiGet<ApiList>("/api/virtual/improvement-priorities", p),
  virtualStopLossDiagnostics: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string }) =>
    apiGet<ApiList>("/api/virtual/stop-loss-diagnostics", p),
  virtualEntryTimingDiagnostics: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string; regime?: string; recommendationBucket?: string }) =>
    apiGet<ApiList>("/api/virtual/entry-timing-diagnostics", p),
  virtualEntryNotTouchedDiagnostics: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string }) =>
    apiGet<ApiList>("/api/virtual/entry-not-touched-diagnostics", p),
  virtualMarketGapDiagnostics: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; sourceType?: string; journalSession?: string }) =>
    apiGet<ApiList>("/api/virtual/market-gap-diagnostics", p),
  virtualPerformanceGateDiagnostics: (p?: { market?: Market | string; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<any>("/api/virtual/performance-gate-diagnostics", p),
  journalPerformance: (p?: { market?: Market | string; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<any>("/api/journal/performance", p),
  journalAttribution: (p?: { market?: Market | string; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<any>("/api/journal/attribution", p),
  journalEntryEfficiency: (p?: { market?: Market | string; horizon?: Horizon | string }) =>
    apiGet<any>("/api/journal/entry-efficiency", p),
  journalAttributionFeedback: (p?: { market?: Market | string }) =>
    apiGet<any>("/api/journal/attribution-feedback", p),
  journalHistoricalStrategyCalibration: (p?: { market?: Market | string; minSamples?: number; includeChart?: boolean; includePattern?: boolean; symbolLimit?: number; maxCutoffs?: number }) =>
    apiGet<any>("/api/journal/historical-strategy-calibration", p),
  portfolioRiskBudget: (p?: { market?: Market | string }) =>
    apiGet<any>("/api/portfolio/risk-budget", p),
  backtestSummary: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/backtest/summary", p),
  backtestTrades: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/backtest/trades", p),
  adminPipeline: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/admin/pipeline", p),
  operationSummary: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/final/operation-summary", p),
  ohlcv: (p: { market?: Market | "auto"; symbol: string; limit?: number; futureProjectionBars?: number }, signal?: AbortSignal) =>
    apiGet<ApiList>("/api/ohlcv", p, signal),
  companyAnalysis: (p?: { market?: Market; limit?: number; q?: string }, signal?: AbortSignal) =>
    apiGet<ApiList>("/api/company-analysis", p, signal),
  predictions: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; strategy?: Mode | string; term?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/predictions/table", p),
  predictionAccuracy: (p?: { market?: Market | "all" }) =>
    apiGet<ApiList>("/api/insights/prediction-accuracy", p),
  chartAnalysisAccuracy: (p?: { market?: Market | "all"; futureBars?: number; symbolLimit?: number; maxCutoffs?: number }) =>
    apiGet<ApiList>("/api/insights/chart-analysis-accuracy", p),
  supplyZoneAccuracy: (p?: { market?: Market | "all"; futureBars?: number; symbolLimit?: number; maxCutoffs?: number; includeItems?: boolean }) =>
    apiGet<ApiList>("/api/insights/supply-zone-accuracy", p),
  trendlineAccuracy: (p?: { market?: Market | "all"; futureBars?: number; symbolLimit?: number; maxCutoffs?: number; includeItems?: boolean }) =>
    apiGet<ApiList>("/api/insights/trendline-accuracy", p),
  trendlineAnchorLearning: (p?: { market?: Market | "all"; symbol?: string; limit?: number }) =>
    apiGet<ApiList>("/api/insights/trendline-anchor-learning", p),
  holdings: (p?: { market?: Market; limit?: number }) =>
    apiGet<ApiList>("/api/holdings", p),
  holdingsClean: (p?: { market?: Market; limit?: number }) =>
    apiGet<ApiList>("/api/holdings-clean", p),
  holdingsEdit: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/holdings-edit", p),
  saveHoldingsEdit: (body: { items: any[] }) =>
    apiPost<ApiList>("/api/holdings-edit/save", body),
  watchlistEdit: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/watchlist-edit", p),
  saveWatchlistEdit: (body: { items: any[] }) =>
    apiPost<ApiList>("/api/watchlist-edit/save", body),
  autoWatchlistCandidates: (p?: { market?: Market; limitPerMarket?: number }) =>
    apiGet<ApiList>("/api/watchlist/auto-candidates", p),
  applyAutoWatchlist: (body?: { market?: Market; limitPerMarket?: number }) =>
    apiPost<ApiList>("/api/watchlist/auto-curate", body || {}),
  symbolEvents: (p: { symbol: string; market: Market }, signal?: AbortSignal) =>
    apiGet<any>(`/api/symbol/${p.symbol}/events`, { market: p.market }, signal),
  news: (p?: { market?: Market; limit?: number; watchOnly?: boolean }, signal?: AbortSignal) =>
    apiGet<ApiList>("/api/news", p, signal),
  disclosures: (p?: { market?: Market; limit?: number; watchOnly?: boolean }, signal?: AbortSignal) =>
    apiGet<ApiList>("/api/disclosures", p, signal),
  audit: () => apiGet<ApiList>("/api/data/audit"),
  github: () => apiGet<ApiList>("/api/health/github"),

  session: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/session", p),
  dataQuality: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/final/data-quality-live", p),
  positionSize: (p: { entry: number; cash: number; strategy?: Mode | string; market?: Market }) =>
    apiGet<ApiList>("/api/position/size", p),
  nearAlerts: (p?: { market?: Market; thresholdPct?: number; limit?: number }) =>
    apiGet<ApiList>("/api/risk/near-alerts", p),
  kisTokenStatus: () =>
    apiGet<ApiList>("/api/kis/token/status"),
  exchangeRate: (p?: { base?: string; target?: string }) =>
    apiGet<any>("/api/exchange-rate", p),
  refreshOneQuote: (body: { market?: Market; symbol: string; name?: string }) =>
    apiPost<ApiList>("/api/quotes/refresh-one", body),
  refreshTargetQuotes: (body?: { market?: Market; limit?: number }) =>
    apiPost<ApiList>("/api/quotes/refresh-targets", body || {}),
  refreshWatchHoldingsQuotes: (body?: { market?: Market; limit?: number }) =>
    apiPost<ApiList>("/api/quotes/refresh-targets", body || {}),
  kisHoldingsPreview: () =>
    apiGet<ApiList>("/api/kis/holdings"),
  kisHoldingsSync: (body?: { mode?: "merge" | "replace" }) =>
    apiPost<any>("/api/kis/holdings/sync", body || {}),
  importHoldingsCsv: (body: { market: Market; csv_text: string; mode?: "merge" | "replace" }) =>
    apiPost<any>("/api/holdings/import-csv", body),
  earningsCalendar: (p?: { market?: "kr" | "us" | "all"; days?: number }) =>
    apiGet<ApiList>("/api/earnings-calendar", p),
  // Calendar API (event_calendar.py 기반)
  calendarToday: (p?: { market?: "kr" | "us" | "all" }) =>
    apiGet<any>("/api/calendar/today", p),
  calendarMacro: (p?: { market?: "kr" | "us"; days?: number; impact?: "low" | "medium" | "high" }) =>
    apiGet<ApiList>("/api/calendar/macro", p),
  calendarEarnings: (p?: { market?: "kr" | "us"; days?: number; tracked?: boolean }) =>
    apiGet<ApiList>("/api/calendar/earnings", p),
  // Phase 3 — Signal Ledger
  signalsRecord: (body: Record<string, any>) =>
    apiPost<any>("/api/signals/record", body),
  signalsBadge: (p: { symbol: string; horizon?: string; mode?: string }) =>
    apiGet<any>("/api/signals/badge", p),
  signalsVerify: () =>
    apiPost<any>("/api/signals/verify", {}),
  signalsLedger: (p?: { market?: string; limit?: number }) =>
    apiGet<any>("/api/signals/ledger", p),
  // Phase 4 — Portfolio Conflict
  portfolioConflict: (p: { symbol: string; market?: string; sector?: string }) =>
    apiGet<any>("/api/portfolio/conflict", p),
  refreshNews: (market?: "kr" | "us" | "all") =>
    apiPost<any>("/api/news/refresh", {}, market ? { market } : {}),
  refreshDisclosures: (market?: "kr" | "us" | "all") =>
    apiPost<any>("/api/disclosures/refresh", {}, market ? { market } : {}),
  virtualLedger: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/virtual/ledger", p),
  virtualValidation: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/virtual/validation", p),
  orderbook: (p: { symbol: string; market: Market }) =>
    apiGet<any>("/api/quotes/orderbook", p),
  investor: (p: { symbol: string; market: Market }) =>
    apiGet<any>("/api/quotes/investor", p),
  chartIndex: (p: { indexSymbol: string; market: Market; limit?: number }, signal?: AbortSignal) =>
    apiGet<any>(`/api/chart/index/${p.indexSymbol}`, { market: p.market, limit: p.limit }, signal),
  chartAnalysis: (p: { symbol: string; market: Market }, signal?: AbortSignal) =>
    apiGet<any>(`/api/chart/analysis/${p.symbol}`, { market: p.market }, signal),
  similarPattern: (p: { symbol: string; market: Market }, signal?: AbortSignal) =>
    apiGet<any>(`/api/chart/similar-pattern/${p.symbol}`, { market: p.market }, signal),
  patternStrategy: (p: { symbol: string; market: Market }, signal?: AbortSignal) =>
    apiGet<any>("/api/pattern/strategy", p, signal),
  // Phase 5 — Adaptive Score
  adaptiveWeights: (p?: { limit?: number }) =>
    apiGet<ApiList>("/api/insights/adaptive-weights", p),
  validationRecommendationsSummary: (p?: { market?: Market | "all"; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/validation/recommendations/summary", p),
  // Data Coverage
  dataCoverage: () =>
    apiGet<any>("/api/data/coverage"),
  // Broker — 계좌 연동
  brokerConnections: (token: string) =>
    fetch(buildUrl(API_BASE, "/api/broker/connections"), {
      headers: { Authorization: `Bearer ${token}` },
    }).then((r) => r.json()),
  brokerTest: (token: string, body: { broker: string; appKey: string; appSecret: string }) =>
    fetch(buildUrl(API_BASE, "/api/broker/test"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  brokerConnect: (token: string, body: { broker: string; appKey: string; appSecret: string; accountNo: string }) =>
    fetch(buildUrl(API_BASE, "/api/broker/connect"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  brokerSyncHoldings: (token: string, body: { broker: string }) =>
    fetch(buildUrl(API_BASE, "/api/broker/sync-holdings"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  brokerLocalBridgeUpload: (token: string, body: { broker: string; accountNoHint?: string; mode?: string; items: any[] }) =>
    fetch(buildUrl(API_BASE, "/api/broker/local-bridge/upload"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  brokerDisconnect: (token: string, body: { broker: string }) =>
    fetch(buildUrl(API_BASE, "/api/broker/disconnect"), {
      method: "DELETE",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  stockAnalysis: (p: { symbol: string; market: string }) =>
    apiGet<any>(`/api/analysis/${encodeURIComponent(p.symbol)}`, { market: p.market }),

  // Telegram 알림
  alertsStatus: () => apiGet<any>("/api/alerts/status"),
  alertsTest: () => apiPost<any>("/api/alerts/test", {}),
  alertsCheck: (p?: { thresholdPct?: number; force?: boolean }) =>
    apiPost<any>("/api/alerts/check", {}, p as Record<string, string>),

  // 공포·탐욕 지수
  fearGreed: (p?: { market?: string }) => apiGet<any>("/api/market/fear-greed", p),

  // 페이퍼 트레이딩
  paperPositions: (p?: { market?: string }) => apiGet<any>("/api/paper/positions", p),
  paperHistory: (p?: { market?: string; limit?: number }) => apiGet<any>("/api/paper/history", p),
  paperSummary: (p?: { market?: string }) => apiGet<any>("/api/paper/summary", p),
  paperDrawdown: (p?: { market?: string }) => apiGet<any>("/api/paper/drawdown", p),
  paperStops: (p?: { market?: string }) => apiGet<any>("/api/paper/stops", p),
  paperStopsCheck: (p?: { market?: string }) => apiGet<any>("/api/paper/stops/check", p),
  paperStopUpdate: (market: string, symbol: string, body: { stopPrice?: number; targetPrice?: number; note?: string }) =>
    fetch(buildUrl(API_BASE, `/api/paper/stops/${market}/${symbol}`), { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json()),
  paperBuy: (body: { symbol: string; market: string; quantity: number; price?: number; name?: string; memo?: string }) =>
    apiPost<any>("/api/paper/buy", body),
  paperSell: (body: { symbol: string; market: string; quantity: number; price?: number; memo?: string }) =>
    apiPost<any>("/api/paper/sell", body),
  paperReset: (market?: string, opts?: { seedKr?: number; seedUs?: number }) => {
    const params = new URLSearchParams();
    if (market) params.set("market", market);
    if (opts?.seedKr != null && opts.seedKr > 0) params.set("seed_kr", String(opts.seedKr));
    if (opts?.seedUs != null && opts.seedUs > 0) params.set("seed_us", String(opts.seedUs));
    const qs = params.toString();
    return fetch(`${API_BASE}/api/paper/reset${qs ? `?${qs}` : ""}`, {
      method: "DELETE",
      headers: { ...getMoneUserHeader() },
    }).then((r) => r.json());
  },
};

export default mone;
