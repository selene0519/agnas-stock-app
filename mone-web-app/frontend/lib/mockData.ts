import type {
  Horizon,
  Market,
  MarketSummary,
  Mode,
  StockCandidate,
} from "./types";

export function nowIso() {
  return new Date().toISOString();
}

export const mockRunnerStatus = {
  status: "READY",
  message: "Data loading standby",
  backendConnected: true,
  frontendReflected: true,
  lastRunAt: nowIso(),
  nextRunAt: nowIso(),
  errors: ["Data loading standby"],
};

export const mockMarketSummary: MarketSummary = {
  date: new Date().toISOString().slice(0, 10),
  market: "all",
  priceSession: "UNKNOWN",
  overallDataStatus: "PARTIAL",
  lastUpdated: nowIso(),
  topSignals: [],
  warnings: [],
};

export const mockCandidates: StockCandidate[] = [];

export const mockStocks: StockCandidate[] = [];

export const mockReports = {
  premarket: [],
  intraday: [],
  closing: [],
};

export const mockNews = [];

export const mockDisclosures = [];

export const mockPredictionSummary = {
  status: "READY",
  total: 0,
  validated: 0,
  winRate: 0,
  avgReturn: 0,
};

export const mockBacktestSummary = {
  status: "READY",
  totalRecommendations: 0,
  executedTrades: 0,
  winRate: 0,
  cumulativeReturnPct: 0,
};

export const mockAdminStatus = {
  status: "READY",
  items: [],
};

export async function loadRealMoneData() {
  return {
    runnerStatus: mockRunnerStatus,
    marketSummary: mockMarketSummary,
    candidates: mockCandidates,
    stocks: mockStocks,
    reports: mockReports,
    news: mockNews,
    disclosures: mockDisclosures,
    predictionSummary: mockPredictionSummary,
    backtestSummary: mockBacktestSummary,
    adminStatus: mockAdminStatus,
  };
}

export function filterByMarket<T extends { market?: string }>(
  items: T[],
  market: Market
) {
  if (market === "all") return items;
  return items.filter((item) => String(item.market || "").toLowerCase() === market);
}

export function filterByMode<T>(items: T[], mode?: Mode) {
  void mode;
  return items;
}

export function filterByHorizon<T>(items: T[], horizon?: Horizon) {
  void horizon;
  return items;
}
