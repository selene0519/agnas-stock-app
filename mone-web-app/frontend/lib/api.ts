export type Market = "kr" | "us" | "all";
export type Mode = "conservative" | "balanced" | "aggressive" | "all";
export type Horizon = "short" | "swing" | "mid" | "long" | "all";

export interface ApiList<T = any> {
  status: string;
  market?: string;
  count?: number;
  items?: T[];
  error?: string;
  [key: string]: any;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/mone-api";
const DIRECT_BACKEND = process.env.NEXT_PUBLIC_DIRECT_API_BASE_URL || "http://127.0.0.1:8050";

function buildUrl(baseUrl: string, path: string, params?: Record<string, string | number | boolean | undefined | null>) {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  const isAbsolute = baseUrl.startsWith("http://") || baseUrl.startsWith("https://");
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

async function fetchJson<T>(url: string): Promise<T> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });

    const text = await response.text().catch(() => "");

    if (!response.ok) {
      return {
        status: "ERROR",
        error: `${response.status} ${response.statusText} ${text.slice(0, 500)}`,
        items: [],
        count: 0,
      } as T;
    }

    try {
      return JSON.parse(text) as T;
    } catch {
      return {
        status: "ERROR",
        error: `Invalid JSON response: ${text.slice(0, 500)}`,
        items: [],
        count: 0,
      } as T;
    }
  } catch (error) {
    return {
      status: "ERROR",
      error: error instanceof Error ? error.message : String(error),
      items: [],
      count: 0,
    } as T;
  }
}

export async function apiGet<T = any>(
  path: string,
  params?: Record<string, string | number | boolean | undefined | null>
): Promise<T> {
  const proxyUrl = buildUrl(API_BASE, path, params);
  const proxyResult: any = await fetchJson<T>(proxyUrl);

  if (proxyResult?.status !== "ERROR") {
    return proxyResult as T;
  }

  const directUrl = buildUrl(DIRECT_BACKEND, path, params);
  const directResult: any = await fetchJson<T>(directUrl);

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
        headers: { Accept: "application/json", "Content-Type": "application/json" },
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
  disclosureCalendar: (p?: { market?: Market; days?: number }) =>
    apiGet<ApiList>("/api/disclosure-calendar", p),
  watchlistGroups: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/watchlist/groups", p),
  watchlistSetGroup: (body: { market?: string; symbol: string; group: string }) =>
    apiPost<ApiList>("/api/watchlist/set-group", body),
  correlationMatrix: (p?: { market?: Market; days?: number }) =>
    apiGet<ApiList>("/api/risk/correlation", p),
  benchmarkComparison: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/risk/benchmark", p),
  validationDashboard: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/validation/dashboard", p),
  sectorExposure: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/risk/sector-exposure", p),
  journalGet: (p?: { market?: Market }) =>
    apiGet<ApiList>("/api/journal", p),
  journalAdd: (body: { market?: string; symbol?: string; name?: string; action?: string; price?: number; qty?: number; memo: string; review?: string; result?: string; returnPct?: number; tags?: string[] }) =>
    apiPost<ApiList>("/api/journal/add", body),
  journalUpdate: (id: string, body: Partial<{ memo: string; review: string; result: string; returnPct: number; tags: string[] }>) =>
    fetch(`${typeof window !== "undefined" ? "" : "http://127.0.0.1:8050"}/mone-api/api/journal/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.json()),
  journalDelete: (id: string) =>
    fetch(`${typeof window !== "undefined" ? "" : "http://127.0.0.1:8050"}/mone-api/api/journal/${id}`, { method: "DELETE" }).then(r => r.json()),
  recommendations: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; cash?: number; limit?: number; watchOnly?: boolean }) =>
    apiGet<ApiList>("/api/final/recommendations", p),
  candidates: (p?: { market?: Market; strategy?: Mode | string; term?: Horizon | string; cash?: number; limit?: number; watchOnly?: boolean }) =>
    apiGet<ApiList>("/api/v1/candidates", p),
  report: (type: "premarket" | "intraday" | "closing", p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>(`/api/reports/${type}`, p),
  virtualSummary: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/virtual/summary", p),
  backtestSummary: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string }) =>
    apiGet<ApiList>("/api/backtest/summary", p),
  backtestTrades: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/backtest/trades", p),
  ohlcv: (p: { market?: Market | "auto"; symbol: string; limit?: number }) =>
    apiGet<ApiList>("/api/ohlcv", p),
  companyAnalysis: (p?: { market?: Market; limit?: number; q?: string }) =>
    apiGet<ApiList>("/api/company-analysis", p),
  predictions: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; strategy?: Mode | string; term?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/predictions/table", p),
  predictionAccuracy: (p?: { market?: Market | "all" }) =>
    apiGet<ApiList>("/api/insights/prediction-accuracy", p),
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
  news: (p?: { market?: Market; limit?: number }) =>
    apiGet<ApiList>("/api/news", p),
  disclosures: (p?: { market?: Market; limit?: number }) =>
    apiGet<ApiList>("/api/disclosures", p),
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
  refreshOneQuote: (body: { market?: Market; symbol: string; name?: string }) =>
    apiPost<ApiList>("/api/quotes/refresh-one", body),
  refreshTargetQuotes: (body?: { market?: Market; limit?: number }) =>
    apiPost<ApiList>("/api/quotes/refresh-targets", body || {}),
  refreshWatchHoldingsQuotes: (body?: { market?: Market; limit?: number }) =>
    apiPost<ApiList>("/api/quotes/refresh-targets", body || {}),
  virtualLedger: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/virtual/ledger", p),
  virtualValidation: (p?: { market?: Market; mode?: Mode | string; horizon?: Horizon | string; limit?: number }) =>
    apiGet<ApiList>("/api/virtual/validation", p),
  orderbook: (p: { symbol: string; market: Market }) =>
    apiGet<any>("/api/quotes/orderbook", p),
  investor: (p: { symbol: string; market: Market }) =>
    apiGet<any>("/api/quotes/investor", p),
  chartIndex: (p: { indexSymbol: string; market: Market; limit?: number }) =>
    apiGet<any>(`/api/chart/index/${p.indexSymbol}`, { market: p.market, limit: p.limit }),
};

export default mone;




