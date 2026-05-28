"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { EmptyReason, Section, StatCard } from "@/components/Cards";
import { DataTable, type Column } from "@/components/DataTable";
import { firstSubPage, NAV_GROUPS, Sidebar, visibleGroups, type AppMode } from "@/components/Sidebar";
import { API_BASE, deleteJson, fetchVirtualPortfolio, getJson, money, patchJson, postJson, type ApiList, type Market, type Security } from "@/lib/api";

type FileItem = {
  path: string;
  exists: boolean;
  status: "OK" | "MISSING";
  bytes: number;
  rows: number;
  updatedAt: string;
};

type EnvItem = { key: string; status: "OK" | "MISSING" };

type DataSourceItem = {
  key: string;
  name: string;
  status: "OK" | "MISSING";
  files: number;
  csvFiles: number;
  rows: number;
  latestUpdatedAt: string;
  target: string;
  examples: string[];
  message: string;
};

type NewsItem = {
  title: string;
  summary: string;
  sourceName: string;
  publishedAt: string;
  symbol: string;
  name: string;
  url?: string;
  nextAction?: string;
};

type DisclosureItem = {
  symbol: string;
  name: string;
  title: string;
  date: string;
  sourceName: string;
  url?: string;
  status?: string;
};

type CompanyAnalysisItem = {
  symbol: string;
  name: string;
  currentPriceText: string;
  supply: string;
  earnings: string;
  valuation: string;
  chart: string;
  flowStatus: string;
  earningsStatus: string;
  valuationStatus: string;
  dataStatus: string;
  eps?: string;
  per?: string;
  pbr?: string;
  roe?: string;
  revenue?: string;
  operatingIncome?: string;
  netIncome?: string;
  annualPerformance?: string;
  quarterlyPerformance?: string;
  incomeStatementStatus?: string;
  esg?: string;
  research?: string;
  raw?: Record<string, unknown>;
};

type VirtualPreviewItem = {
  symbol: string;
  name: string;
  swingGrade: string;
  mode: string;
  modeLabel: string;
  currentPrice: string;
  entry: string;
  shares: string;
  invested: string;
  loss: string;
  profit: string;
  accountLossPct: string;
  accountProfitPct: string;
  buyRule: string;
  holdDays: string | number;
  summary: string;
};

type VirtualPreviewResponse = ApiList<VirtualPreviewItem> & { mode: string; modeLabel: string };

type VirtualPortfolioResponse = {
  market?: Market;
  mode: string;
  modeLabel: string;
  totalCapital: string;
  invested: string;
  cash: string;
  lossTotal: string;
  profitTotal: string;
  lossPct: string;
  profitPct: string;
  count: number;
  candidateCount?: number;
  cards: { label: string; value: string; note: string }[];
  items: (VirtualPreviewItem & { executionStatus?: string })[];
  topName?: string;
  note?: string;
};

type StrategyMode = "conservative" | "balanced" | "aggressive";
type TimingBucket = "today" | "wait" | "next" | "risk";
type DecisionHorizon = "short" | "swing" | "mid";

const HORIZON_LABEL: Record<DecisionHorizon, string> = {
  short: "단기",
  swing: "스윙",
  mid: "중기"
};

type FinalExecution = {
  executionStatus?: string;
  executionReason?: string;
  filled?: boolean;
  excludedFromReturn?: boolean;
  exitStatus?: string;
  pnlText?: string;
  dayHigh?: string;
  dayLow?: string;
  ohlcvDate?: string;
  ohlcvSource?: string;
};

type FinalRecommendationItem = Security & {
  mode?: StrategyMode;
  modeLabel?: string;
  horizon?: DecisionHorizon;
  horizonLabel?: string;
  decisionBucket?: string;
  buyTiming?: string;
  sellTiming?: string;
  newEntryDecision?: string;
  holderDecision?: string;
  decisionReason?: string;
  eventBadgesText?: string;
  eventRiskScore?: number;
  newsReliabilityScore?: number;
  surgeLabel?: string;
  surgeReason?: string;
  finalRankScore?: number;
  opportunityScore?: number | string;
  entryScore?: number | string;
  riskScore?: number | string;
  probabilityText?: string;
  expectedPriceText?: string;
  executionStatus?: string;
  exitStatus?: string;
  pnlText?: string;
  execution?: FinalExecution;
};

type FinalRecommendationsResponse = {
  status?: string;
  market?: Market;
  mode?: StrategyMode;
  modeLabel?: string;
  horizon?: DecisionHorizon;
  horizonLabel?: string;
  count: number;
  universeCount?: number;
  rule?: string;
  sources?: string[];
  items: FinalRecommendationItem[];
};

type FinalExecutionSummary = {
  status?: string;
  conditionalOrders: number;
  filledCount: number;
  unfilledCount: number;
  filledReturnAvgText?: string;
  rule?: string;
  items: FinalRecommendationItem[];
};

type FinalDataCenter = {
  status?: string;
  updatedAt?: string;
  todayDataSource?: string;
  githubStatus?: string;
  stockAppBridgeStatus?: string;
  chartData?: string;
  flowData?: string;
  orderbookData?: string;
  disclosureData?: string;
  summary?: { label: string; value: string; note: string }[];
};

type FinalMacroEvent = {
  sourceType?: string;
  symbol?: string;
  name?: string;
  date?: string;
  title?: string;
  badgeText?: string;
  riskScore?: number;
  action?: string;
};

type FinalMacroEvents = { status?: string; count: number; items: FinalMacroEvent[] };

type FinalPortfolioRisk = {
  status?: string;
  candidateCount?: number;
  filledCount?: number;
  topSector?: string;
  marketMix?: string;
  averageRiskScore?: number;
  averageEventRiskScore?: number;
  cashPolicy?: string;
  warnings?: string[];
  sectorDistribution?: Record<string, number>;
};

const STRATEGY_MODE_LABEL: Record<StrategyMode, string> = {
  conservative: "보수",
  balanced: "균형",
  aggressive: "공격"
};

const EMPTY_PORTFOLIO_BY_MODE: Record<StrategyMode, VirtualPortfolioResponse> = {
  conservative: { mode: "conservative", modeLabel: "보수", totalCapital: "-", invested: "-", cash: "-", lossTotal: "-", profitTotal: "-", lossPct: "-", profitPct: "-", count: 0, cards: [], items: [], note: "" },
  balanced: { mode: "balanced", modeLabel: "균형", totalCapital: "-", invested: "-", cash: "-", lossTotal: "-", profitTotal: "-", lossPct: "-", profitPct: "-", count: 0, cards: [], items: [], note: "" },
  aggressive: { mode: "aggressive", modeLabel: "공격", totalCapital: "-", invested: "-", cash: "-", lossTotal: "-", profitTotal: "-", lossPct: "-", profitPct: "-", count: 0, cards: [], items: [], note: "" }
};

function emptyPortfolio(mode: StrategyMode): VirtualPortfolioResponse {
  return { ...EMPTY_PORTFOLIO_BY_MODE[mode], items: [], cards: [] };
}

function normalizePortfolioResponse(raw: unknown, mode: StrategyMode = "balanced"): VirtualPortfolioResponse {
  const container = (raw ?? {}) as { data?: unknown; portfolio?: unknown };
  const p = (container.data ?? container.portfolio ?? raw ?? {}) as Partial<VirtualPortfolioResponse> & {
    candidateCount?: number | string;
    loss?: string;
    profit?: string;
  };
  const base = emptyPortfolio(mode);
  const items = Array.isArray(p.items) ? p.items : [];
  const parsedCount = Number(p.count ?? p.candidateCount ?? items.length ?? 0);
  const count = Number.isFinite(parsedCount) ? parsedCount : items.length;
  return {
    ...base,
    ...p,
    mode: p.mode || mode,
    modeLabel: p.modeLabel || STRATEGY_MODE_LABEL[mode],
    count,
    candidateCount: count,
    cards: Array.isArray(p.cards) ? p.cards : [],
    items,
    lossTotal: p.lossTotal ?? p.loss ?? "-",
    profitTotal: p.profitTotal ?? p.profit ?? "-",
    topName: items?.[0]?.name ?? "후보 없음"
  };
}

function normalizePortfolio(mode: StrategyMode, value?: unknown): VirtualPortfolioResponse {
  return normalizePortfolioResponse(value, mode);
}

function normalizePortfolioMap(source?: Partial<Record<StrategyMode, unknown>> | null): Record<StrategyMode, VirtualPortfolioResponse> {
  return {
    conservative: normalizePortfolioResponse(source?.conservative, "conservative"),
    balanced: normalizePortfolioResponse(source?.balanced, "balanced"),
    aggressive: normalizePortfolioResponse(source?.aggressive, "aggressive"),
  };
}

async function fetchPortfolioMap(market: Market): Promise<Record<StrategyMode, VirtualPortfolioResponse>> {
  const timeout = new Promise<Record<StrategyMode, VirtualPortfolioResponse>>((resolve) => {
    window.setTimeout(() => resolve(normalizePortfolioMap()), 12000);
  });
  const request = (async () => {
    const [conservative, balanced, aggressive] = await Promise.all([
      fetchVirtualPortfolio<unknown>(market, "conservative"),
      fetchVirtualPortfolio<unknown>(market, "balanced"),
      fetchVirtualPortfolio<unknown>(market, "aggressive")
    ]);
    const normalizedConservative = normalizePortfolioResponse(conservative, "conservative");
    const normalizedBalanced = normalizePortfolioResponse(balanced, "balanced");
    const normalizedAggressive = normalizePortfolioResponse(aggressive, "aggressive");
    console.log("[MONE] raw portfolio api responses", { conservative, balanced, aggressive });
    console.log("[MONE] normalized portfolios", {
      conservative: normalizedConservative,
      balanced: normalizedBalanced,
      aggressive: normalizedAggressive
    });
    return {
      conservative: normalizedConservative,
      balanced: normalizedBalanced,
      aggressive: normalizedAggressive
    };
  })();
  return Promise.race([request, timeout]).catch((err) => {
    console.warn("[MONE] portfolio API fallback", err);
    return normalizePortfolioMap();
  });
}

type MarketSummary = {
  market: Market;
  marketLabel: string;
  cards: Record<string, string>[];
  dataStatus: Record<string, string>[];
  dashboard: Record<string, string>[];
  sources: string[];
  updatedAt: string;
  automation?: Record<string, unknown>;
};

type HistoryResponse = {
  count: number;
  source: string;
  items: Record<string, string>[];
};

type PremarketItem = Security & {
  sourceGroup: string;
  expectedOpen: string;
  expectedClose: string;
  target2Text: string;
  riskReward: string;
  riskStatus: string;
};

type IntradayItem = Security & {
  divergencePct?: number | null;
  divergenceText: string;
  stopBreakText: string;
  targetHitText: string;
  holdingRisk: string;
  newsRiskStatus: string;
  intradayDecision: string;
};

type ClosingItem = {
  symbol: string;
  name: string;
  predictionBaseDate: string;
  actualResultDate: string;
  directionHit: string;
  rangeHit: string;
  entryTouched: string;
  stopTakeProfit: string;
  failedSymbol: string;
  failureReason: string;
};

type ClosingReport = ApiList<ClosingItem> & {
  directionHitRate: string;
  rangeHitRate: string;
  predictionHistoryCount: number;
  outcomeHistoryCount: number;
  outcomes: Record<string, string>[];
};

type ReportFile = {
  path: string;
  fileName: string;
  group: string;
  rows: number;
  columns: number;
  updatedAt: string;
  bytes: number;
  status: "OK" | "EMPTY" | "MISSING";
  fallbackStatus: string;
  preview: Record<string, string>[];
};

type ReportFilesResponse = {
  count: number;
  fallbackPolicy: string[];
  items: ReportFile[];
};

type QuoteRefreshResponse = {
  status: "OK" | "PARTIAL" | "NO_REFRESH";
  market: Market | "all";
  updatedAt: string;
  refreshed: number;
  failed: number;
  providers: {
    kis: "OK" | "MISSING";
    finnhub: "OK" | "MISSING";
  };
  items: Array<{ symbol: string; currentPrice: number; priceTime: string; priceSource: string }>;
  failedItems: Array<{ symbol: string; error: string; fallbackKept?: boolean }>;
};

type BacktestItem = {
  strategy: string;
  status: string;
  totalReturn: string;
  winRate: string;
  mdd: string;
  sharpe: string;
  trades: string;
  recentResult: string;
};

type BacktestResponse = ApiList<BacktestItem> & {
  status: string;
  warnings: string[];
  predictionRows: number;
  totalPredictionRows?: number;
  outcomeRows: number;
  recentOutcomes: Record<string, string>[];
  recentTrades?: Record<string, string | number>[];
  diagnostics?: Record<string, string | number>[];
  ohlcv?: {
    files: number;
    eligibleSymbols: number;
    minDaysRequired: number;
    predictionMatchedSymbols: number;
    insufficient?: Record<string, string | number>[];
    schemaErrors?: Record<string, string | number>[];
  };
};

type PredictionInsightResponse = {
  market: Market;
  status: string;
  summary: {
    predictionRows: number;
    historyRows: number;
    outcomeRows: number;
    validationRows: number;
    success: number;
    fail: number;
    neutral: number;
    successRate: string;
    coverage: string;
  };
  diagnostics: Record<string, SimpleValue>[];
  bySymbol: Record<string, SimpleValue>[];
  byPeriod: Record<string, SimpleValue>[];
  failures: Record<string, SimpleValue>[];
  corrections: Record<string, SimpleValue>[];
  sources: string[];
};


type ScannerItem = Security & {
  bucket: string;
  theme: string;
  group: string;
  riskLevel: string;
  score: string;
  reason: string;
  isHolding: boolean;
  watchlistAction: string;
};

type CalculatorResults = {
  kelly?: Record<string, string | number>;
  var?: Record<string, string | number>;
  rr?: Record<string, string | number | null>;
};

type MonteCarloResponse = {
  p5: number;
  p50: number;
  p95: number;
  upProbability: string;
  expectedFinalPrice: number;
  varText: string;
  cvarText: string;
  chart: { day: number; p5: number; p50: number; p95: number }[];
};

type CorrelationResponse = {
  status: string;
  reason: string;
  assets?: string[];
  items: { pair: string; correlation: number; interpretation: string }[];
  matrix: Record<string, string | number>[];
  sources: string[];
  diversificationNote?: string;
};

type ChartPoint = {
  date: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  ma5?: number;
  ma20?: number;
  ma60?: number;
  bbUpper?: number;
  bbLower?: number;
  rsi?: number;
  macd?: number;
  macdSignal?: number;
};

type ChartResponse = {
  status: string;
  symbol: string;
  market: Market;
  source: string;
  count?: number;
  message?: string;
  latest?: ChartPoint;
  indicatorStatus?: string[];
  items: ChartPoint[];
};

type GitHubActionsStatus = {
  status: string;
  repo?: string;
  message?: string;
  workflows?: Record<string, string | number>[];
  runs?: Record<string, string>[];
  latestScheduled?: Record<string, string> | null;
};

type WriteResponse = {
  status: string;
  action?: string;
  message: string;
  market?: Market;
  symbol?: string;
  backupFile?: string;
  count?: number;
};

type HoldingForm = {
  symbol: string;
  name: string;
  avgPrice: string;
  quantity: string;
  memo: string;
};

type WatchForm = {
  symbol: string;
  name: string;
  memo: string;
};

type CalculatorForm = {
  capital: string;
  winRate: string;
  payoffRatio: string;
  portfolioValue: string;
  expectedReturn: string;
  volatility: string;
  confidence: string;
  entry: string;
  stop: string;
  target: string;
};

type MonteCarloForm = {
  currentPrice: string;
  expectedReturn: string;
  volatility: string;
  days: string;
  simulations: string;
};

const candidateTabs = [
  ["action", "오늘 확인"],
  ["pullback", "눌림목"],
  ["flow", "수급"],
  ["risk", "주의"]
] as const;

const buyCandidateTabs = [
  ["action", "오늘 확인"],
  ["pullback", "눌림목"],
  ["flow", "수급"]
] as const;

const sourceLabel = (source?: string) => source || "소스 없음";


async function safeGetJson<T>(path: string, fallback: T, timeoutMs = 8000): Promise<T> {
  try {
    return await getJson<T>(path, timeoutMs);
  } catch (err) {
    console.warn(`[MONE] optional API fallback: ${path}`, err);
    return fallback;
  }
}

function newsTag(item: NewsItem) {
  const text = `${item.title ?? ""} ${item.summary ?? ""} ${item.name ?? ""} ${item.sourceName ?? ""}`;
  const hasRealName = item.name && !["종목", "시장", item.symbol].includes(item.name) && !/^\d{4,6}$/.test(item.name);
  if (/공시|실적|계약|증자|분기|사업보고|합병|분할|수주|공급계약|자사주|배당/.test(text)) return "공시/이슈";
  if (/삼성전자|하이닉스|반도체|HBM|AI반도체|메모리|파운드리|엔비디아|NVDA/.test(text)) return "반도체";
  if (/전지|배터리|2차전지|LG에너지|에코프로|포스코퓨처/.test(text)) return "2차전지";
  if (/로봇|AI|인공지능|자동화|로보틱스/.test(text)) return "AI·로봇";
  if (hasRealName || (item.symbol && item.symbol !== "종목")) return "개별";
  if (/외국인|기관|개인|순매수|순매도|매수|매도/.test(text)) return "수급";
  if (/코스피|코스닥|나스닥|S&P|다우|지수/.test(text)) return "지수";
  if (/증시|시장|환율|금리/.test(text)) return "시장";
  return "뉴스";
}

export default function Home() {
  const [activeCategory, setActiveCategory] = useState("시장 홈");
  const [appMode, setAppMode] = useState<AppMode>("general");
  const [activeSubPage, setActiveSubPage] = useState("요약");
  const [market, setMarket] = useState<Market>("kr");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshTick, setRefreshTick] = useState(0);
  const [quoteRefreshing, setQuoteRefreshing] = useState(false);
  const [quoteStatus, setQuoteStatus] = useState<QuoteRefreshResponse | null>(null);
  const [summary, setSummary] = useState<MarketSummary | null>(null);
  const [symbols, setSymbols] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [positions, setPositions] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [news, setNews] = useState<ApiList<NewsItem>>({ count: 0, items: [] });
  const [predictions, setPredictions] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [candidates, setCandidates] = useState<Record<string, ApiList<Security>>>({});
  const [files, setFiles] = useState<FileItem[]>([]);
  const [env, setEnv] = useState<EnvItem[]>([]);
  const [dataSources, setDataSources] = useState<DataSourceItem[]>([]);
  const [predictionHistory, setPredictionHistory] = useState<HistoryResponse>({ count: 0, source: "", items: [] });
  const [outcomeHistory, setOutcomeHistory] = useState<HistoryResponse>({ count: 0, source: "", items: [] });
  const [predictionInsights, setPredictionInsights] = useState<PredictionInsightResponse>({ market: "kr", status: "NO_DATA", summary: { predictionRows: 0, historyRows: 0, outcomeRows: 0, validationRows: 0, success: 0, fail: 0, neutral: 0, successRate: "검증 데이터 부족", coverage: "검증 데이터 부족" }, diagnostics: [], bySymbol: [], byPeriod: [], failures: [], corrections: [], sources: [] });
  const [premarket, setPremarket] = useState<ApiList<PremarketItem>>({ count: 0, items: [], sources: [] });
  const [intraday, setIntraday] = useState<ApiList<IntradayItem>>({ count: 0, items: [], sources: [] });
  const [closing, setClosing] = useState<ClosingReport>({
    count: 0,
    items: [],
    sources: [],
    directionHitRate: "검증 데이터 부족",
    rangeHitRate: "검증 데이터 부족",
    predictionHistoryCount: 0,
    outcomeHistoryCount: 0,
    outcomes: []
  });
  const [reportFiles, setReportFiles] = useState<ReportFilesResponse>({ count: 0, fallbackPolicy: [], items: [] });
  const [backtest, setBacktest] = useState<BacktestResponse>({ count: 0, items: [], status: "NO_DATA", warnings: [], predictionRows: 0, outcomeRows: 0, recentOutcomes: [] });
  const [scanner, setScanner] = useState<ApiList<ScannerItem>>({ count: 0, items: [] });
  const [watchlist, setWatchlist] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [directHoldings, setDirectHoldings] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [scannerFilter, setScannerFilter] = useState("전체");
  const [calculator, setCalculator] = useState<CalculatorResults>({});
  const [monteCarlo, setMonteCarlo] = useState<MonteCarloResponse | null>(null);
  const [correlation, setCorrelation] = useState<CorrelationResponse>({ status: "NO_DATA", reason: "상관관계 계산 데이터 부족", items: [], matrix: [], sources: [] });
  const [chartData, setChartData] = useState<ChartResponse>({ status: "NO_DATA", symbol: "", market: "kr", source: "", items: [] });
  const [githubActions, setGithubActions] = useState<GitHubActionsStatus>({ status: "NOT_LOADED", message: "GitHub Actions 상태를 아직 읽지 않았습니다.", workflows: [], runs: [] });
  const [disclosures, setDisclosures] = useState<ApiList<DisclosureItem>>({ count: 0, items: [], sources: [] });
  const [companyAnalysis, setCompanyAnalysis] = useState<ApiList<CompanyAnalysisItem>>({ count: 0, items: [] });
  const [disclosureRefreshStatus, setDisclosureRefreshStatus] = useState("");
  const [virtualPreview, setVirtualPreview] = useState<VirtualPreviewResponse>({ count: 0, items: [], mode: "balanced", modeLabel: "균형" });
  const [virtualPortfolio, setVirtualPortfolio] = useState<VirtualPortfolioResponse>(emptyPortfolio("balanced"));
  const [virtualPortfolios, setVirtualPortfolios] = useState<Record<StrategyMode, VirtualPortfolioResponse>>(normalizePortfolioMap());
  const [strategyMode, setStrategyMode] = useState<StrategyMode>("balanced");
  const [decisionHorizon, setDecisionHorizon] = useState<DecisionHorizon>("swing");
  const [finalRecommendations, setFinalRecommendations] = useState<FinalRecommendationsResponse>({ count: 0, items: [] });
  const [finalExecutions, setFinalExecutions] = useState<FinalExecutionSummary>({ conditionalOrders: 0, filledCount: 0, unfilledCount: 0, items: [] });
  const [finalDataCenter, setFinalDataCenter] = useState<FinalDataCenter>({ status: "NOT_LOADED" });
  const [finalMacroEvents, setFinalMacroEvents] = useState<FinalMacroEvents>({ count: 0, items: [] });
  const [finalPortfolioRisk, setFinalPortfolioRisk] = useState<FinalPortfolioRisk>({ status: "NOT_LOADED", warnings: [] });
  const [query, setQuery] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState<Security | null>(null);
  const [candidateType, setCandidateType] = useState<(typeof candidateTabs)[number][0]>("action");
  const [writeStatus, setWriteStatus] = useState("");
  const [watchForm, setWatchForm] = useState<WatchForm>({ symbol: "", name: "", memo: "" });
  const [holdingForm, setHoldingForm] = useState<HoldingForm>({ symbol: "", name: "", avgPrice: "", quantity: "", memo: "" });
  const [calculatorForm, setCalculatorForm] = useState<CalculatorForm>({
    capital: "10000000",
    winRate: "55",
    payoffRatio: "1.7",
    portfolioValue: "10000000",
    expectedReturn: "8",
    volatility: "25",
    confidence: "95",
    entry: "100",
    stop: "92",
    target: "118"
  });
  const [monteCarloForm, setMonteCarloForm] = useState<MonteCarloForm>({
    currentPrice: "",
    expectedReturn: "8",
    volatility: "25",
    days: "60",
    simulations: "1000"
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");

      // v3.4: 첫 화면은 무거운 관리/점검 API를 기다리지 않고 먼저 띄웁니다.
      // 시장 홈에 필요한 핵심 데이터만 먼저 읽고, 나머지는 백그라운드로 채웁니다.
      try {
        const [
          summaryData,
          symbolData,
          positionData,
          newsData,
          predictionData,
          virtualPreviewData,
          portfolioMapData
        ] = await Promise.all([
          safeGetJson<MarketSummary>(`/api/market/summary?market=${market}`, { market, marketLabel: market === "kr" ? "국장" : "미장", cards: [], dataStatus: [], dashboard: [], sources: [], updatedAt: "" }),
          safeGetJson<ApiList<Security>>(`/api/symbols?market=${market}`, { count: 0, items: [] }),
          safeGetJson<ApiList<Security>>(`/api/positions?market=${market}`, { count: 0, items: [] }),
          safeGetJson<ApiList<NewsItem>>(`/api/news?market=${market}`, { count: 0, items: [] }),
          safeGetJson<ApiList<Security>>(`/api/predictions?market=${market}`, { count: 0, items: [] }),
          safeGetJson<VirtualPreviewResponse>(`/api/virtual/preview?market=${market}&mode=${strategyMode}`, { count: 0, items: [], mode: strategyMode, modeLabel: STRATEGY_MODE_LABEL[strategyMode] }),
          fetchPortfolioMap(market)
        ]);

        const candidateData = await Promise.all(
          candidateTabs.map(([type]) => safeGetJson<ApiList<Security>>(`/api/candidates?market=${market}&type=${type}`, { count: 0, items: [] }))
        );

        if (cancelled) return;
        setSummary(summaryData);
        setSymbols(symbolData);
        setPositions(positionData);
        setNews(newsData);
        setPredictions(predictionData);
        setVirtualPreview(virtualPreviewData);
        const portfolios = normalizePortfolioMap(portfolioMapData);
        console.log("[MONE] rendered mode cards", portfolios);
        setVirtualPortfolios(portfolios);
        setVirtualPortfolio(portfolios[strategyMode] ?? portfolios.balanced);
        setCandidates(Object.fromEntries(candidateTabs.map(([type], idx) => [type, candidateData[idx]])));
        setSelectedSymbol((prev) => prev ?? symbolData.items[0] ?? null);
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "핵심 데이터 로딩 실패");
          setLoading(false);
        }
        return;
      }

      // v3.4: 무거운 데이터 상태/관리/검증 API는 화면을 먼저 띄운 뒤 백그라운드로 읽습니다.
      void (async () => {
        const [
          fileData,
          envData,
          dataSourceData,
          predHistory,
          outcomes,
          insightData,
          premarketData,
          intradayData,
          closingData,
          reportFileData,
          backtestData,
          scannerData,
          watchlistData,
          directHoldingsData,
          correlationData,
          githubActionsData,
          disclosureData,
          companyAnalysisData
        ] = await Promise.all([
          safeGetJson<{ items: FileItem[] }>("/api/status/files", { items: [] }),
          safeGetJson<{ items: EnvItem[] }>("/api/status/env", { items: [] }),
          safeGetJson<{ items: DataSourceItem[] }>("/api/status/data-sources", { items: [] }),
          safeGetJson<HistoryResponse>(`/api/history/predictions?market=${market}`, { count: 0, source: "", items: [] }),
          safeGetJson<HistoryResponse>(`/api/history/outcomes?market=${market}`, { count: 0, source: "", items: [] }),
          safeGetJson<PredictionInsightResponse>(`/api/insights/prediction?market=${market}`, { market, status: "NO_DATA", summary: { predictionRows: 0, historyRows: 0, outcomeRows: 0, validationRows: 0, success: 0, fail: 0, neutral: 0, successRate: "검증 데이터 부족", coverage: "검증 데이터 부족" }, diagnostics: [], bySymbol: [], byPeriod: [], failures: [], corrections: [], sources: [] }),
          safeGetJson<ApiList<PremarketItem>>(`/api/reports/premarket?market=${market}`, { count: 0, items: [], sources: [] }),
          safeGetJson<ApiList<IntradayItem>>(`/api/reports/intraday?market=${market}`, { count: 0, items: [], sources: [] }),
          safeGetJson<ClosingReport>(`/api/reports/closing?market=${market}`, { count: 0, items: [], sources: [], directionHitRate: "검증 데이터 부족", rangeHitRate: "검증 데이터 부족", predictionHistoryCount: 0, outcomeHistoryCount: 0, outcomes: [] }),
          safeGetJson<ReportFilesResponse>("/api/reports/files", { count: 0, fallbackPolicy: [], items: [] }),
          safeGetJson<BacktestResponse>(`/api/advanced/backtest?market=${market}`, { count: 0, items: [], status: "NO_DATA", warnings: [], predictionRows: 0, outcomeRows: 0, recentOutcomes: [] }, 20000),
          safeGetJson<ApiList<ScannerItem>>(`/api/advanced/scanner?market=${market}`, { count: 0, items: [] }, 20000),
          safeGetJson<ApiList<Security>>(`/api/watchlist?market=${market}`, { count: 0, items: [] }),
          safeGetJson<ApiList<Security>>(`/api/holdings?market=${market}`, { count: 0, items: [] }),
          safeGetJson<CorrelationResponse>(`/api/advanced/correlation?market=${market}`, { status: "NO_DATA", reason: "상관관계 계산 데이터 부족", items: [], matrix: [], sources: [] }),
          safeGetJson<GitHubActionsStatus>("/api/status/github-actions", { status: "NOT_LOADED", message: "GitHub Actions 상태를 읽지 못했습니다.", workflows: [], runs: [] }),
          safeGetJson<ApiList<DisclosureItem>>(`/api/disclosures?market=${market}`, { count: 0, items: [], sources: [] }),
          safeGetJson<ApiList<CompanyAnalysisItem>>(`/api/company-analysis?market=${market}`, { count: 0, items: [] }, 20000)
        ]);

        if (cancelled) return;
        setFiles(fileData.items);
        setEnv(envData.items);
        setDataSources(dataSourceData.items);
        setPredictionHistory(predHistory);
        setOutcomeHistory(outcomes);
        setPredictionInsights(insightData);
        setPremarket(premarketData);
        setIntraday(intradayData);
        setClosing(closingData);
        setReportFiles(reportFileData);
        setBacktest(backtestData);
        setScanner(scannerData);
        setWatchlist(watchlistData);
        setDirectHoldings(directHoldingsData);
        setCorrelation(correlationData);
        setGithubActions(githubActionsData);
        setDisclosures(disclosureData);
        setCompanyAnalysis(companyAnalysisData);
      })();
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [market, refreshTick]);

  useEffect(() => {
    setVirtualPortfolio(virtualPortfolios[strategyMode] ?? virtualPortfolios.balanced);
  }, [strategyMode, virtualPortfolios]);

  useEffect(() => {
    let cancelled = false;
    async function loadModePreview() {
      const preview = await safeGetJson<VirtualPreviewResponse>(
        `/api/virtual/preview?market=${market}&mode=${strategyMode}`,
        { count: 0, items: [], mode: strategyMode, modeLabel: STRATEGY_MODE_LABEL[strategyMode] },
        15000
      );
      if (!cancelled) setVirtualPreview(preview);
    }
    void loadModePreview();
    return () => { cancelled = true; };
  }, [market, strategyMode, refreshTick]);

  useEffect(() => {
    let cancelled = false;
    async function loadVisibleHeavyData() {
      if (activeCategory === "뉴스·기업분석") {
        const data = await safeGetJson<ApiList<CompanyAnalysisItem>>(`/api/company-analysis?market=${market}`, { count: 0, items: [] }, 20000);
        if (!cancelled) setCompanyAnalysis(data);
      }
      if (activeCategory === "예측·검증") {
        const data = await safeGetJson<ApiList<Security>>(`/api/predictions?market=${market}`, { count: 0, items: [] }, 15000);
        if (!cancelled) setPredictions(data);
      }
      if (activeCategory === "고급 분석") {
        const data = await safeGetJson<ApiList<ScannerItem>>(`/api/advanced/scanner?market=${market}`, { count: 0, items: [] }, 20000);
        if (!cancelled) setScanner(data);
      }
    }
    void loadVisibleHeavyData();
    return () => { cancelled = true; };
  }, [activeCategory, market, refreshTick]);

  useEffect(() => {
    let cancelled = false;
    async function loadFinalEngine() {
      const [recommendations, executions, dataCenter, macroEvents, portfolioRisk] = await Promise.all([
        safeGetJson<FinalRecommendationsResponse>(`/api/final/recommendations?market=${market}&mode=${strategyMode}&horizon=${decisionHorizon}`, { count: 0, items: [] }),
        safeGetJson<FinalExecutionSummary>(`/api/final/conditional-executions?market=${market}&mode=${strategyMode}&horizon=${decisionHorizon}`, { conditionalOrders: 0, filledCount: 0, unfilledCount: 0, items: [] }),
        safeGetJson<FinalDataCenter>(`/api/final/data-center?market=${market}`, { status: "NO_DATA" }),
        safeGetJson<FinalMacroEvents>(`/api/final/macro-events?market=${market}`, { count: 0, items: [] }),
        safeGetJson<FinalPortfolioRisk>(`/api/final/portfolio-risk?market=${market}&mode=${strategyMode}&horizon=${decisionHorizon}`, { status: "NO_DATA", warnings: [] })
      ]);
      if (cancelled) return;
      setFinalRecommendations(recommendations);
      setFinalExecutions(executions);
      setFinalDataCenter(dataCenter);
      setFinalMacroEvents(macroEvents);
      setFinalPortfolioRisk(portfolioRisk);
    }
    void loadFinalEngine();
    return () => { cancelled = true; };
  }, [market, strategyMode, decisionHorizon, refreshTick]);

  useEffect(() => {
    let cancelled = false;
    async function loadSelectedChart() {
      const symbol = selectedSymbol?.symbol ?? symbols.items[0]?.symbol;
      if (!symbol) {
        setChartData({ status: "NO_DATA", symbol: "", market, source: "", items: [] });
        return;
      }
      try {
        const chart = await getJson<ChartResponse>(`/api/chart/${encodeURIComponent(symbol)}?market=${market}`);
        if (!cancelled) setChartData(chart);
      } catch (err) {
        if (!cancelled) setChartData({ status: "ERROR", symbol, market, source: "", message: err instanceof Error ? err.message : "차트 데이터 로딩 실패", items: [] });
      }
    }
    loadSelectedChart();
    return () => {
      cancelled = true;
    };
  }, [market, selectedSymbol?.symbol, symbols.items]);

  const currentGroup = visibleGroups(appMode).find((group) => group.title === activeCategory) ?? visibleGroups(appMode)[0] ?? NAV_GROUPS[0];
  const marketName = market === "kr" ? "국장" : "미장";
  const updatedAt = summary?.updatedAt ?? "기준시각 없음";
  const apiOk = env.filter((item) => item.status === "OK").length;
  const apiMissing = env.filter((item) => item.status === "MISSING").length;
  const filesMissing = files.filter((item) => item.status === "MISSING").length;
  const generalDataStatusText = finalDataCenter.status && finalDataCenter.status !== "NOT_LOADED"
    ? finalDataCenter.status
    : dataSources.some((item) => item.status === "OK")
      ? "일부 연결 확인"
      : "확인 중";
  const generalDataStatusNote = [
    finalDataCenter.chartData ? `차트 ${finalDataCenter.chartData}` : null,
    finalDataCenter.disclosureData ? `공시 ${finalDataCenter.disclosureData}` : null,
    finalDataCenter.todayDataSource ? `출처 ${finalDataCenter.todayDataSource}` : null
  ].filter(Boolean).join(" · ") || "상세 상태는 관리자 모드에서 확인";

  const filteredSymbols = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return symbols.items;
    return symbols.items.filter((item) => `${item.symbol} ${item.name}`.toLowerCase().includes(needle));
  }, [query, symbols.items]);

  const historyChart = outcomeHistory.items.slice(-40).map((row, idx) => ({
    idx: idx + 1,
    date: row.date ?? `${idx + 1}`,
    value: Number(row.return_5d ?? row.return_3d ?? row.return_1d ?? 0)
  }));

  const filteredScanner = useMemo(() => {
    if (scannerFilter === "전체") return scanner.items;
    if (scannerFilter === "보유 제외") return scanner.items.filter((item) => !item.isHolding);
    if (scannerFilter === "저평가") {
      return scanner.items.filter((item) => `${item.theme} ${item.group} ${item.riskLevel}`.includes("저평가"));
    }
    return scanner.items.filter((item) => item.bucket === scannerFilter || `${item.theme} ${item.group} ${item.riskLevel}`.includes(scannerFilter));
  }, [scanner.items, scannerFilter]);
  const displayedScanner = filteredScanner.length || !scanner.items.length ? filteredScanner : scanner.items;
  const predictionRows = useMemo(() => {
    const hasModeData = predictions.items.some((item) => (item.recommendationModes ?? []).length > 0);
    return predictions.items.filter((item) => {
      const modes = item.recommendationModes ?? [];
      if (!modes.length) return !hasModeData;
      return modes.includes(strategyMode);
    });
  }, [predictions.items, strategyMode]);
  const selectedPortfolioPreview = virtualPortfolios[strategyMode] ?? virtualPortfolio;
  const selectedPreviewRows = selectedPortfolioPreview.items.length ? selectedPortfolioPreview.items : virtualPreview.items;

  const directHoldingsBySymbol = useMemo(() => new Map(directHoldings.items.map((item) => [item.symbol, item])), [directHoldings.items]);
  const predictionBySymbol = useMemo(() => new Map(predictions.items.map((item) => [item.symbol, item])), [predictions.items]);
  const watchSymbols = useMemo(() => new Set(watchlist.items.map((item) => item.symbol)), [watchlist.items]);
  const holdingSymbols = useMemo(() => new Set([...positions.items, ...directHoldings.items].map((item) => item.symbol)), [positions.items, directHoldings.items]);

  const discoveryRows = useMemo(() => {
    type DiscoveryItem = Security & { discoverySource?: string; isWatchlisted?: boolean; isHoldingNow?: boolean };
    const bySymbol = new Map<string, DiscoveryItem>();
    const add = (item: Security, source: string) => {
      if (!item.symbol) return;
      const prev = bySymbol.get(item.symbol);
      const merged: DiscoveryItem = {
        ...(prev ?? item),
        ...item,
        discoverySource: prev?.discoverySource ? `${prev.discoverySource} · ${source}` : source,
        isWatchlisted: watchSymbols.has(item.symbol),
        isHoldingNow: holdingSymbols.has(item.symbol)
      };
      bySymbol.set(item.symbol, merged);
    };
    symbols.items.forEach((item) => add(item, "오늘 선택"));
    watchlist.items.forEach((item) => add(item, "관심"));
    positions.items.forEach((item) => add(item, "보유"));
    scanner.items.forEach((item) => add(item, "후보군"));
    return Array.from(bySymbol.values());
  }, [symbols.items, watchlist.items, positions.items, scanner.items, watchSymbols, holdingSymbols]);

  const filteredDiscoveryRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return discoveryRows;
    return discoveryRows.filter((item) => `${item.symbol} ${item.name} ${item.discoverySource ?? ""}`.toLowerCase().includes(needle));
  }, [query, discoveryRows]);

  function parseNumber(value: string, fallback = 0) {
    const out = Number(String(value || "").replace(/,/g, ""));
    return Number.isFinite(out) ? out : fallback;
  }

  async function addWatchlistFrom(item: Pick<Security, "symbol" | "name">) {
    setWriteStatus("관심종목 저장 중...");
    try {
      const res = await postJson<WriteResponse>("/api/watchlist", {
        market,
        symbol: item.symbol,
        name: item.name,
        memo: "MONE Web에서 추가"
      });
      setWriteStatus(`${res.status}: ${res.message}${res.backupFile ? ` · 백업 ${res.backupFile}` : ""}`);
      setRefreshTick((value) => value + 1);
    } catch (err) {
      setWriteStatus(err instanceof Error ? err.message : "관심종목 저장 실패");
    }
  }

  async function addWatchlistManual() {
    if (!watchForm.symbol.trim()) {
      setWriteStatus("관심종목 추가 실패: 종목코드/티커가 필요합니다.");
      return;
    }
    await addWatchlistFrom({ symbol: watchForm.symbol.trim(), name: watchForm.name.trim() || watchForm.symbol.trim() });
    setWatchForm({ symbol: "", name: "", memo: "" });
  }

  async function deleteWatchlistSymbol(symbol: string) {
    if (!window.confirm(`${symbol} 관심종목을 삭제할까요?`)) return;
    setWriteStatus("관심종목 삭제 중...");
    try {
      const res = await deleteJson<WriteResponse>(`/api/watchlist/${encodeURIComponent(symbol)}?market=${market}`);
      setWriteStatus(`${res.status}: ${res.message}${res.backupFile ? ` · 백업 ${res.backupFile}` : ""}`);
      setRefreshTick((value) => value + 1);
    } catch (err) {
      setWriteStatus(err instanceof Error ? err.message : "관심종목 삭제 실패");
    }
  }

  async function refreshDisclosures() {
    setDisclosureRefreshStatus("공시 수집 중...");
    try {
      const res = await postJson<{ status: string; results: Array<{ market: string; status: string; count: number; message: string; file?: string }> }>(`/api/disclosures/refresh?market=${market}&days=30`, {});
      const message = res.results?.map((row) => `${row.market.toUpperCase()} ${row.status} ${row.count}건`).join(" · ") || res.status;
      setDisclosureRefreshStatus(`공시 수집 결과: ${message}`);
      const refreshed = await getJson<ApiList<DisclosureItem>>(`/api/disclosures?market=${market}`);
      setDisclosures(refreshed);
      setRefreshTick((value) => value + 1);
    } catch (err) {
      setDisclosureRefreshStatus(err instanceof Error ? err.message : "공시 수집 실패");
    }
  }

  function fillHoldingForm(item: Security) {
    setHoldingForm({
      symbol: item.symbol,
      name: item.name,
      avgPrice: item.avgPrice ? String(item.avgPrice) : "",
      quantity: item.quantity ? String(item.quantity) : "",
      memo: item.nextAction || ""
    });
  }

  async function saveHolding() {
    if (!holdingForm.symbol.trim()) {
      setWriteStatus("보유종목 저장 실패: 종목코드/티커가 필요합니다.");
      return;
    }
    setWriteStatus("보유종목 저장 중...");
    try {
      const exists = directHoldingsBySymbol.has(holdingForm.symbol.trim().toUpperCase());
      const payload = {
        market,
        symbol: holdingForm.symbol.trim(),
        name: holdingForm.name.trim() || holdingForm.symbol.trim(),
        avgPrice: parseNumber(holdingForm.avgPrice),
        quantity: parseNumber(holdingForm.quantity),
        memo: holdingForm.memo.trim()
      };
      const res = exists
        ? await patchJson<WriteResponse>(`/api/holdings/${encodeURIComponent(payload.symbol)}`, payload)
        : await postJson<WriteResponse>("/api/holdings", payload);
      setWriteStatus(`${res.status}: ${res.message}${res.backupFile ? ` · 백업 ${res.backupFile}` : ""}`);
      setRefreshTick((value) => value + 1);
    } catch (err) {
      setWriteStatus(err instanceof Error ? err.message : "보유종목 저장 실패");
    }
  }

  async function deleteHoldingSymbol(symbol: string) {
    if (!window.confirm(`${symbol} 보유종목을 삭제할까요? 삭제 전 백업이 생성됩니다.`)) return;
    setWriteStatus("보유종목 삭제 중...");
    try {
      const res = await deleteJson<WriteResponse>(`/api/holdings/${encodeURIComponent(symbol)}?market=${market}`);
      setWriteStatus(`${res.status}: ${res.message}${res.backupFile ? ` · 백업 ${res.backupFile}` : ""}`);
      setRefreshTick((value) => value + 1);
    } catch (err) {
      setWriteStatus(err instanceof Error ? err.message : "보유종목 삭제 실패");
    }
  }

  const symbolColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} /> },
    { key: "entry", header: "기준가", render: (row) => row.entryText || money(row.entry, market) },
    { key: "stop", header: "손절", render: (row) => row.stopText || money(row.stop, market) },
    { key: "target", header: "목표", render: (row) => row.targetText || money(row.target, market) },
    { key: "status", header: "상태", render: (row) => row.dataStatus || "상태 없음" }
  ];

  const positionColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "quantity", header: "수량", render: (row) => row.quantityText || "보유수량 없음" },
    { key: "avgPrice", header: "평균단가", render: (row) => row.avgPriceText || "평균단가 없음" },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "returnPct", header: "수익률", render: (row) => <GainText value={row.returnPct} text={row.returnPctText} /> },
    { key: "pnl", header: "평가손익", render: (row) => <GainText value={row.pnl} text={row.pnlText} /> },
    { key: "action", header: "다음 행동", render: (row) => row.nextAction || "다음 행동 없음" },
    {
      key: "manage",
      header: "관리",
      render: (row) => (
        <div className="flex gap-2">
          <button
            onClick={(event) => {
              event.stopPropagation();
              fillHoldingForm(row);
              setActiveSubPage("보유 현황");
            }}
            className="rounded-md border border-accent/40 px-2 py-1 text-xs font-bold text-accent"
          >
            수정
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation();
              deleteHoldingSymbol(row.symbol);
            }}
            className="rounded-md border border-warn/40 px-2 py-1 text-xs font-bold text-warn"
          >
            삭제
          </button>
        </div>
      )
    }
  ];

  const scoreColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "supply", header: "수급", render: (row) => row.scores?.supply || "수급 데이터 없음" },
    { key: "earnings", header: "실적", render: (row) => row.scores?.earnings || "재무 데이터 없음" },
    { key: "valuation", header: "밸류", render: (row) => row.scores?.valuation || "재무 데이터 없음" },
    { key: "chart", header: "차트", render: (row) => row.scores?.chart || "차트 데이터 부족" },
    { key: "status", header: "상태", render: (row) => row.dataStatus || "상태 없음" }
  ];

  const orderLineColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "entry", header: "기준가", render: (row) => row.entryText || "기준가 없음" },
    { key: "stop", header: "손절가", render: (row) => row.stopText || "손절가 없음" },
    { key: "target", header: "목표가", render: (row) => row.targetText || "목표가 없음" }
  ];

  const pnlColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "quantity", header: "수량", render: (row) => row.quantityText || "수량 없음" },
    { key: "avgPrice", header: "평균단가", render: (row) => row.avgPriceText || "평균단가 없음" },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "marketValue", header: "평가금액", render: (row) => row.marketValueText || "평가금액 없음" },
    { key: "pnl", header: "평가손익", render: (row) => <GainText value={row.pnl} text={row.pnlText} /> },
    { key: "returnPct", header: "수익률", render: (row) => <GainText value={row.returnPct} text={row.returnPctText} /> }
  ];

  const positionCalcColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "quantity", header: "수량", render: (row) => row.quantityText || "수량 없음" },
    { key: "cost", header: "투자원금", render: (row) => row.costBasisText || "투자원금 없음" },
    { key: "value", header: "평가금액", render: (row) => row.marketValueText || "평가금액 없음" },
    { key: "pnl", header: "손익", render: (row) => <GainText value={row.pnl} text={row.pnlText} /> },
    { key: "decision", header: "점검", render: (row) => <LongText text={row.nextAction || row.dataStatus || "보유 유지/축소 여부는 손절가와 목표가 기준으로 확인"} /> }
  ];

  const compactSymbolColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "action", header: "다음 행동", render: (row) => row.nextAction || "다음 행동 없음" },
    { key: "reason", header: "근거", render: (row) => row.reason || row.warning || "근거 없음" }
  ];

  const premarketColumns: Column<PremarketItem>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact hideMeta /> },
    { key: "open", header: "예상 시초가", render: (row) => row.expectedOpen || "예상 시초가 없음" },
    { key: "close", header: "예상 종가", render: (row) => row.expectedClose || "예상 종가 없음" },
    { key: "entry", header: "기준가", render: (row) => priceText(row.entryText, row.entry, "기준가") },
    { key: "stop", header: "손절가", render: (row) => priceText(row.stopText, row.stop, "손절가") },
    { key: "target", header: "목표가", render: (row) => priceText(row.targetText, row.target, "목표가") },
    { key: "rr", header: "손익비", render: (row) => formatRiskReward(row.riskReward) }
  ];

  const intradayColumns: Column<IntradayItem>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact hideMeta /> },
    { key: "gap", header: "기준가와 거리", render: (row) => <GainText value={row.divergencePct} text={row.divergenceText} /> },
    { key: "zone", header: "구간", render: (row) => intradayZoneText(row) },
    { key: "holding", header: "보유 여부", render: (row) => row.holdingRisk || "보유종목 아님" },
    { key: "decision", header: "장중 판단", render: (row) => <LongText text={intradayDecisionText(row)} /> }
  ];

  const closingColumns: Column<ClosingItem>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "base", header: "예측일", render: (row) => row.predictionBaseDate || "예측일 없음" },
    { key: "actual", header: "결과일", render: (row) => row.actualResultDate || "결과일 없음" },
    { key: "direction", header: "방향", render: (row) => row.directionHit || "방향 데이터 없음" },
    { key: "range", header: "범위", render: (row) => row.rangeHit || "범위 데이터 없음" },
    { key: "touch", header: "손절/익절", render: (row) => row.stopTakeProfit || "손절/익절 데이터 없음" },
    { key: "reason", header: "사유", render: (row) => <LongText text={compactClosingReason(row.failureReason || row.failedSymbol || "사유 없음")} /> }
  ];

  const reportFileColumns: Column<ReportFile>[] = [
    { key: "name", header: "파일명", render: (row) => <b>{row.fileName}</b> },
    { key: "group", header: "그룹", render: (row) => row.group },
    { key: "rows", header: "rows", render: (row) => row.rows },
    { key: "cols", header: "cols", render: (row) => row.columns },
    { key: "updated", header: "수정시각", render: (row) => row.updatedAt || "기준시각 없음" },
    { key: "bytes", header: "크기", render: (row) => `${row.bytes.toLocaleString()} B` },
    { key: "status", header: "상태", render: (row) => <StatusPill status={row.status === "OK" ? "OK" : "MISSING"} /> },
    { key: "fallback", header: "fallback", render: (row) => row.fallbackStatus }
  ];

  const backtestColumns: Column<BacktestItem>[] = [
    { key: "strategy", header: "전략", render: (row) => <b>{row.strategy}</b> },
    { key: "return", header: "수익률", render: (row) => row.totalReturn },
    { key: "win", header: "승률", render: (row) => row.winRate },
    { key: "mdd", header: "MDD", render: (row) => row.mdd },
    { key: "sharpe", header: "Sharpe", render: (row) => row.sharpe },
    { key: "trades", header: "거래 수", render: (row) => row.trades },
    { key: "status", header: "상태", render: (row) => row.status },
    { key: "recent", header: "최근 결과", render: (row) => <LongText text={row.recentResult} /> }
  ];

  const scannerColumns: Column<ScannerItem>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "bucket", header: "구분", render: (row) => row.bucket },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "score", header: "점수", render: (row) => row.score || "점수 없음" },
    { key: "theme", header: "테마", render: (row) => row.theme || "테마 없음" },
    { key: "risk", header: "리스크", render: (row) => <LongText text={row.riskLevel || "리스크 없음"} /> },
    { key: "holding", header: "보유", render: (row) => (row.isHolding ? "보유 중" : "미보유") },
    {
      key: "action",
      header: "관심종목",
      render: (row) => (
        <button
          onClick={(event) => {
            event.stopPropagation();
            addWatchlistFrom(row);
          }}
          className="rounded-md border border-accent/45 px-2 py-1 text-xs font-bold text-accent hover:bg-accent hover:text-ink"
        >
          추가
        </button>
      )
    }
  ];

  function selectCategory(category: string) {
    setActiveCategory(category);
    setActiveSubPage(firstSubPage(category));
  }

  function switchAppMode(mode: AppMode) {
    setAppMode(mode);
    const nextCategory = mode === "admin" ? "관리" : "시장 홈";
    setActiveCategory(nextCategory);
    setActiveSubPage(firstSubPage(nextCategory));
  }

  async function refreshQuotes() {
    setQuoteRefreshing(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/quotes/refresh?market=${market}`, { method: "POST" });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const payload = (await res.json()) as QuoteRefreshResponse;
      setQuoteStatus(payload);
      setRefreshTick((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "현재가 새로고침 실패");
    } finally {
      setQuoteRefreshing(false);
    }
  }

  async function runCalculators() {
    try {
      const [kelly, valueAtRisk, rr] = await Promise.all([
        postJson<Record<string, string | number>>("/api/advanced/calculator/kelly", {
          capital: parseNumber(calculatorForm.capital, 10000000),
          winRate: parseNumber(calculatorForm.winRate, 55),
          payoffRatio: parseNumber(calculatorForm.payoffRatio, 1.7)
        }),
        postJson<Record<string, string | number>>("/api/advanced/calculator/var", {
          portfolioValue: parseNumber(calculatorForm.portfolioValue, 10000000),
          expectedReturn: parseNumber(calculatorForm.expectedReturn, 8),
          volatility: parseNumber(calculatorForm.volatility, 25),
          confidence: parseNumber(calculatorForm.confidence, 95)
        }),
        postJson<Record<string, string | number | null>>("/api/advanced/calculator/risk-reward", {
          entry: parseNumber(calculatorForm.entry, 100),
          stop: parseNumber(calculatorForm.stop, 92),
          target: parseNumber(calculatorForm.target, 118)
        })
      ]);
      setCalculator({ kelly, var: valueAtRisk, rr });
    } catch (err) {
      setError(err instanceof Error ? err.message : "계산기 실행 실패");
    }
  }

  async function runMonteCarlo() {
    try {
      const currentPrice = parseNumber(monteCarloForm.currentPrice, selectedSymbol?.currentPrice ?? symbols.items[0]?.currentPrice ?? 100);
      const result = await postJson<MonteCarloResponse>("/api/advanced/monte-carlo", {
        currentPrice,
        expectedReturn: parseNumber(monteCarloForm.expectedReturn, 8),
        volatility: parseNumber(monteCarloForm.volatility, 25),
        days: parseNumber(monteCarloForm.days, 60),
        simulations: parseNumber(monteCarloForm.simulations, 1000)
      });
      setMonteCarlo(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "몬테카를로 실행 실패");
    }
  }

  return (
    <main>
      <Sidebar activeCategory={activeCategory} onSelectCategory={selectCategory} appMode={appMode} />
      <div className="min-h-screen pl-64 md:pl-72">
        <header className="sticky top-0 z-10 border-b border-line bg-ink/95 backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 md:px-6">
            <div>
              <div className="text-xs font-bold text-muted">데이터 기준시각</div>
              <div className="text-sm font-semibold text-slate-100">{updatedAt}</div>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-line bg-panel p-1">
              <button
                className={`rounded-md px-4 py-2 text-sm font-bold ${market === "kr" ? "bg-accent text-ink" : "text-slate-300"}`}
                onClick={() => setMarket("kr")}
              >
                국장
              </button>
              <button
                className={`rounded-md px-4 py-2 text-sm font-bold ${market === "us" ? "bg-accent text-ink" : "text-slate-300"}`}
                onClick={() => setMarket("us")}
              >
                미장
              </button>
            </div>
            <div className="flex items-center gap-1 rounded-lg border border-line bg-panel p-1">
              <button
                className={`rounded-md px-3 py-2 text-xs font-black ${appMode === "general" ? "bg-accent text-ink" : "text-slate-300"}`}
                onClick={() => switchAppMode("general")}
              >
                일반 모드
              </button>
              <button
                className={`rounded-md px-3 py-2 text-xs font-black ${appMode === "admin" ? "bg-warn text-ink" : "text-slate-300"}`}
                onClick={() => switchAppMode("admin")}
              >
                관리자 모드
              </button>
            </div>
            {appMode === "general" ? <ModeSelector value={strategyMode} onChange={setStrategyMode} /> : null}
            <button
              onClick={refreshQuotes}
              disabled={quoteRefreshing}
              className="rounded-lg border border-accent/45 bg-accent/12 px-4 py-2 text-sm font-black text-accent transition hover:bg-accent hover:text-ink disabled:cursor-wait disabled:opacity-60"
            >
              {quoteRefreshing ? "새로고침 중" : "현재가 새로고침"}
            </button>
          </div>
        </header>

        <div className="px-5 py-5 md:px-6">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-sm font-bold text-accent">{marketName}</div>
              <h1 className="mt-1 text-3xl font-black text-white">{activeCategory}</h1>
              <div className="mt-1 text-sm text-muted">현재 화면: {activeSubPage}</div>
            </div>
            <div className="rounded-lg border border-line bg-panel px-4 py-3 text-sm text-muted">
              {appMode === "admin" ? (
                <>
                  API {apiOk} OK / {apiMissing} MISSING · 파일 누락 {filesMissing}
                  {quoteStatus ? (
                    <span className="ml-2 text-accent">
                      현재가 {quoteStatus.status} · 성공 {quoteStatus.refreshed} / 실패 {quoteStatus.failed}
                    </span>
                  ) : null}
                </>
              ) : (
                <>
                  데이터 상태: <span className="font-black text-accent">{generalDataStatusText}</span>
                  <span className="ml-2 text-xs">{generalDataStatusNote}</span>
                </>
              )}
            </div>
          </div>

          {currentGroup.items.length > 1 ? (
            <div className="mb-5 flex flex-wrap gap-2">
              {currentGroup.items.map((item) => (
                <button
                  key={item}
                  onClick={() => setActiveSubPage(item)}
                  className={[
                    "rounded-full border px-4 py-2 text-sm font-bold transition",
                    activeSubPage === item
                      ? "border-accent bg-accent text-ink"
                      : "border-line bg-panel text-slate-300 hover:border-accent/50 hover:text-white"
                  ].join(" ")}
                >
                  {item}
                </button>
              ))}
            </div>
          ) : null}

          {loading ? <EmptyReason text="데이터를 읽는 중입니다." /> : null}
          {error ? <EmptyReason text={`API 연결 확인 필요: ${error}. backend 실행 주소는 ${API_BASE} 입니다.`} /> : null}
          {!loading && !error ? renderPage() : null}
        </div>
      </div>
    </main>
  );

  function renderPage() {
    if (activeCategory === "시장 홈") return renderMarketHome();
    if (activeCategory === "운용 리포트") return renderReports();
    if (activeCategory === "종목 탐색") return renderSymbolDiscovery();
    if (activeCategory === "보유·리스크") return renderPositions();
    if (activeCategory === "차트·기술분석") return renderCharts();
    if (activeCategory === "뉴스·기업분석") return renderNewsCompany();
    if (activeCategory === "예측·검증") return renderPredictions();
    if (activeCategory === "고급 분석") return renderAdvanced();
    if (activeCategory === "관리") return renderAdmin();
    return <ComingSoon title={activeSubPage} />;
  }

  function renderMarketHome() {
    const selectedPortfolio = normalizePortfolio(strategyMode, virtualPortfolios[strategyMode] ?? virtualPortfolio);
    const timingGroups = groupPortfolioItemsByTiming(selectedPortfolio.items ?? [], strategyMode);
    const homeNews = buildHomeNews(news.items, 3);
    const topCandidates = finalRecommendations.items.slice(0, 3);
    const todayEntryCount = topCandidates.filter((item) => isTodayEntryCandidate(item)).length || timingGroups.today.length;
    const waitCount = topCandidates.filter((item) => isWaitCandidate(item)).length || timingGroups.wait.length;
    const dataBasis = dataBasisLabel(updatedAt, finalDataCenter.todayDataSource);
    const conditionalReturn = finalExecutions.filledReturnAvgText || selectedPortfolio.profitPct || "검증 대기";
    const dataStatusValue = dataStatusLabel(finalDataCenter.status, dataSources);
    const dataStatusNote = [
      finalDataCenter.chartData ? `차트 ${finalDataCenter.chartData}` : null,
      finalDataCenter.disclosureData ? `공시 ${finalDataCenter.disclosureData}` : null,
      finalDataCenter.flowData ? `수급 ${finalDataCenter.flowData}` : null
    ].filter(Boolean).join(" · ") || "상세는 관리자 모드";

    return (
      <>
        <Section
          title="오늘 운용 요약"
          right={<span className="text-xs text-muted">시장 홈은 핵심 판단만 짧게 표시 · 상세 표는 각 메뉴에서 확인</span>}
        >
          <div className="mb-3 rounded-xl border border-accent/30 bg-accent/10 px-4 py-3 text-sm leading-6 text-slate-100">
            <span className="font-black text-accent">데이터 기준:</span> {dataBasis}
            <span className="mx-2 text-line">|</span>
            <span className="font-black text-accent">선택:</span> {marketName} · {STRATEGY_MODE_LABEL[strategyMode]} · {HORIZON_LABEL[decisionHorizon]}
            <span className="mx-2 text-line">|</span>
            <span className="text-muted">{updatedAt || "기준시각 확인 중"}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-5">
            <StatCard label="오늘 진입 가능" value={`${todayEntryCount}개`} note="조건 충족 또는 진입가 근접" tone={todayEntryCount ? "good" : "neutral"} />
            <StatCard label="기다릴 후보" value={`${waitCount}개`} note="좋은 종목이지만 진입가 대기" tone="accent" />
            <StatCard label="조건부 가상체결" value={`${finalExecutions.filledCount || 0}건`} note={`가상 검증 · 미체결 ${finalExecutions.unfilledCount || 0}건`} tone="accent" />
            <StatCard label="매크로·이벤트 주의" value={`${finalMacroEvents.count || 0}건`} note={finalMacroEvents.items[0]?.badgeText || "유의 이벤트 점검"} tone={finalMacroEvents.count ? "warn" : "neutral"} />
            <StatCard label="데이터 상태" value={dataStatusValue} note={dataStatusNote} tone={dataStatusValue.includes("정상") ? "good" : "warn"} />
          </div>
        </Section>

        <Section
          title="오늘 TOP 후보"
          right={<button onClick={() => { setActiveCategory("종목 탐색"); setActiveSubPage("오늘 매수 검토"); }} className="rounded-md border border-accent/45 px-3 py-1.5 text-xs font-black text-accent hover:bg-accent hover:text-ink">전체 후보 보기</button>}
        >
          {topCandidates.length ? (
            <div className="grid gap-3 lg:grid-cols-3">
              {topCandidates.map((item, idx) => renderHomeTopCandidate(item, idx))}
            </div>
          ) : (
            <EmptyReason text="오늘 TOP 후보를 불러오는 중입니다. 후보 표는 종목 탐색에서 확인할 수 있습니다." />
          )}
        </Section>

        <Section title="조건부 가상운용 · 리스크 요약" right={<span className="text-xs text-muted">추천됨 ≠ 매수됨 · 진입가 도달 시에만 가상체결</span>}>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-2xl border border-accent/35 bg-panel p-4 shadow-soft">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <div className="text-base font-black text-white">조건부 가상운용 요약</div>
                  <div className="mt-1 text-xs text-muted">장마감 후 OHLCV 기준으로 체결/미체결 확정</div>
                </div>
                <Badge text="가상 검증" tone="warn" />
              </div>
              <div className="grid gap-2 sm:grid-cols-4">
                <MiniMetric label="조건부 주문" value={`${finalExecutions.conditionalOrders || selectedPortfolio.count || 0}건`} />
                <MiniMetric label="체결" value={`${finalExecutions.filledCount || 0}건`} tone="good" />
                <MiniMetric label="미체결" value={`${finalExecutions.unfilledCount || 0}건`} />
                <MiniMetric label="체결 기준 수익률" value={conditionalReturn} tone={String(conditionalReturn).includes("-") ? "warn" : "good"} />
              </div>
              <div className="mt-3 rounded-lg bg-white/5 px-3 py-2 text-xs font-bold leading-5 text-slate-200">
                진입가가 당일 고가/저가 범위에 도달한 종목만 체결로 기록 · 미체결은 수익률 계산 제외
              </div>
            </div>

            <div className="rounded-2xl border border-line bg-panel p-4 shadow-soft">
              <div className="mb-3 text-base font-black text-white">리스크 요약</div>
              <div className="grid gap-2 sm:grid-cols-3">
                <MiniMetric label="매크로 주의" value={`${finalMacroEvents.count || 0}건`} tone={finalMacroEvents.count ? "warn" : "neutral"} />
                <MiniMetric label="포트폴리오 주의" value={(finalPortfolioRisk.warnings ?? []).length ? `${(finalPortfolioRisk.warnings ?? []).length}건` : "0건"} tone={(finalPortfolioRisk.warnings ?? []).length ? "warn" : "good"} />
                <MiniMetric label="데이터 주의" value={dataStatusValue.includes("정상") ? "0건" : "확인"} tone={dataStatusValue.includes("정상") ? "good" : "warn"} />
              </div>
              <div className="mt-3 space-y-2 text-xs leading-5 text-muted">
                <div>· {finalMacroEvents.items[0]?.title || "오늘 주요 매크로/이벤트 리스크 감지 대기"}</div>
                <div>· {(finalPortfolioRisk.warnings ?? []).slice(0, 1).join(" · ") || "섹터/상관관계 쏠림 특이사항 낮음"}</div>
                <div>· {dataStatusNote}</div>
              </div>
            </div>
          </div>
        </Section>

        <Section
          title="오늘 뉴스·공시 핵심"
          right={<button onClick={() => { setActiveCategory("뉴스·기업분석"); setActiveSubPage("뉴스 요약"); }} className="rounded-md border border-accent/45 px-3 py-1.5 text-xs font-black text-accent hover:bg-accent hover:text-ink">더보기</button>}
        >
          {homeNews.length ? (
            <ul className="rounded-xl border border-line bg-panel p-4 shadow-soft">
              {homeNews.map((item, idx) => (
                <li key={`${item.title}-${idx}`} className="grid gap-3 border-b border-line/70 py-3 first:pt-0 last:border-b-0 last:pb-0 md:grid-cols-[120px_1fr_260px]">
                  <span className="w-fit rounded-md bg-white/10 px-2 py-1 text-xs font-black text-accent">{newsTag(item)}</span>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold text-slate-100" title={item.title}>{item.title || "뉴스 제목 없음"}</div>
                    <div className="mt-1 text-xs text-muted">{[item.sourceName, item.publishedAt, item.name || item.symbol].filter(Boolean).join(" · ") || "뉴스 정보 없음"}</div>
                  </div>
                  <div className="text-xs leading-5 text-muted">
                    <span className="font-black text-accent">판단 영향</span> · {newsImpactText(item)}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyReason text="표시할 뉴스·공시 핵심 요약이 없습니다." />
          )}
        </Section>
      </>
    );
  }

  function renderHomeTopCandidate(item: FinalRecommendationItem, idx: number) {
    return (
      <button
        key={`home-top-${item.symbol}-${idx}`}
        onClick={() => setSelectedSymbol(item)}
        className="rounded-2xl border border-line bg-panel p-4 text-left shadow-soft transition hover:border-accent/60 hover:bg-accent/5"
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="mb-2 flex flex-wrap gap-1">
              <Badge text={`TOP ${idx + 1}`} tone={idx === 0 ? "good" : "neutral"} />
              <Badge text={item.decisionBucket || "판단 대기"} tone={isTodayEntryCandidate(item) ? "good" : isWaitCandidate(item) ? "neutral" : "warn"} />
              <Badge text={item.horizonLabel || HORIZON_LABEL[decisionHorizon]} />
            </div>
            <div className="text-lg font-black text-white">{item.name || item.symbol}</div>
            <div className="mt-1 text-xs text-muted">{item.symbol}</div>
          </div>
          <div className="text-right">
            <div className="text-base font-black text-white">{item.currentPriceText || money(item.currentPrice, market) || "현재가 없음"}</div>
            <div className="mt-1 text-xs text-muted">현재가</div>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <PriceMini label="권장 진입가" value={priceText(item.entryText, item.entry, "진입가")} />
          <PriceMini label="손절" value={priceText(item.stopText, item.stop, "손절가")} tone="warn" />
          <PriceMini label="목표" value={priceText(item.targetText, item.target, "목표가")} tone="good" />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <MiniMetric label="기회 점수" value={`${item.opportunityScore ?? "-"}점`} />
          <MiniMetric label="진입 점수" value={`${item.entryScore ?? "-"}점`} />
        </div>
        <div className="mt-3 rounded-lg bg-white/5 px-3 py-2 text-xs font-bold leading-5 text-slate-200">
          {item.buyTiming || item.decisionReason || "조건 충족 시 조건부 진입"}
        </div>
      </button>
    );
  }

  function renderTimingLane(title: string, bucket: TimingBucket, items: VirtualPortfolioResponse["items"], description: string) {
    return (
      <div className="rounded-2xl border border-line bg-panel/70 p-4 shadow-soft">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-base font-black text-white">{title}</div>
            <div className="mt-1 text-xs text-muted">{description}</div>
          </div>
          <span className="rounded-full bg-white/10 px-2 py-1 text-xs font-black text-accent">{items.length}개</span>
        </div>
        <div className="mt-3 space-y-3">
          {items.length ? items.slice(0, 4).map((item) => renderTimingCandidateCard(item, bucket)) : <EmptyReason text="해당 분류 후보가 없습니다." />}
        </div>
      </div>
    );
  }

  function renderTimingCandidateCard(item: VirtualPortfolioResponse["items"][number], bucket: TimingBucket) {
    const security = portfolioItemToSecurity(item, market, strategyMode);
    const eventBadge = eventMacroBadgeFromText(`${item.name} ${item.symbol} ${item.summary ?? ""} ${item.buyRule ?? ""}`);
    return (
      <button
        key={`${strategyMode}-${bucket}-${item.symbol}`}
        onClick={() => setSelectedSymbol(security)}
        className="w-full rounded-xl border border-line bg-ink/40 p-3 text-left transition hover:border-accent/60 hover:bg-accent/5"
      >
        <div className="flex flex-wrap gap-1">
          <Badge text={item.swingGrade || "스윙군 산출 대기"} />
          <Badge text={STRATEGY_MODE_LABEL[strategyMode]} />
          <Badge text={timingLabel(bucket)} tone={bucket === "risk" ? "warn" : bucket === "today" ? "good" : "neutral"} />
          <Badge text={discoveryLabelFromItem(item)} />
          {eventBadge ? <Badge text={eventBadge} tone="warn" /> : null}
        </div>
        <div className="mt-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-base font-black text-white">{item.name || item.symbol}</div>
            <div className="mt-1 text-xs text-muted">{item.symbol} · {item.executionStatus || timingDescription(bucket)}</div>
          </div>
          <div className="text-right">
            <div className="text-sm font-black text-white">{item.currentPrice || "현재가 없음"}</div>
            <div className="mt-1 text-xs text-muted">현재가</div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <PriceMini label="권장 진입가" value={item.entry || "산출 필요"} />
          <PriceMini label="손절 시 손실" value={item.loss || "산출 필요"} tone="warn" />
          <PriceMini label="목표 도달 시 이익" value={item.profit || "산출 필요"} tone="good" />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <MiniMetric label="기회 점수" value={`${opportunityScoreFromPortfolio(item)}점`} />
          <MiniMetric label="진입 점수" value={`${entryScoreFromPortfolio(item, strategyMode)}점`} />
        </div>
        <div className="mt-2 rounded-lg bg-white/5 px-3 py-2 text-xs font-bold leading-5 text-slate-200">
          {timingActionText(bucket, item, strategyMode)} · 유효기간 D+3 · 스윙 검증 D+5
        </div>
      </button>
    );
  }

  function renderTodayCandidateCard(item: Security) {
    const prediction = predictionBySymbol.get(item.symbol) ?? item;
    const bucket = timingBucketForSecurity(item, strategyMode);
    return (
      <button
        key={item.symbol}
        onClick={() => setSelectedSymbol(item)}
        className="rounded-xl border border-line bg-panel p-4 text-left shadow-soft transition hover:border-accent/60 hover:bg-accent/5"
      >
        <div className="flex flex-wrap gap-1">
          <Badge text={item.swingGrade || "스윙군 산출 대기"} />
          <Badge text={STRATEGY_MODE_LABEL[strategyMode]} />
          <Badge text={timingLabel(bucket)} tone={bucket === "risk" ? "warn" : bucket === "today" ? "good" : "neutral"} />
        </div>
        <div className="mt-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-lg font-black text-white">{item.name || item.symbol}</div>
            <div className="mt-1 text-xs text-muted">{item.symbol}</div>
          </div>
          <div className="text-right">
            <div className="text-base font-black text-white">{item.currentPriceText || "현재가 없음"}</div>
            <div className="mt-1 text-xs text-muted">{item.priceTime || "기준시각 없음"}</div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <PriceMini label="권장 진입가" value={priceText(item.entryText, item.entry, "진입가")} />
          <PriceMini label="손절가" value={priceText(item.stopText, item.stop, "손절가")} tone="warn" />
          <PriceMini label="목표가" value={priceText(item.targetText, item.target, "목표가")} tone="good" />
        </div>
        <div className="mt-3 rounded-lg bg-accent/10 px-3 py-2 text-xs font-bold leading-5 text-slate-100">
          {predictionLine(prediction)}
        </div>
        <div className="mt-2 rounded-lg bg-white/5 px-3 py-2 text-xs font-bold leading-5 text-slate-200">
          {timingActionText(bucket, null, strategyMode)} · {tradePlanLine(item, strategyMode)}
        </div>
      </button>
    );
  }

  function renderPortfolioCandidateCard(item: VirtualPortfolioResponse["items"][number]) {
    const bucket = timingBucketForPortfolioItem(item, strategyMode);
    return renderTimingCandidateCard(item, bucket);
  }

  function priceText(text?: string, value?: number | null, label = "가격") {
    if (text && text.trim() && !text.includes("없음")) return text;
    if (value) return money(value, market);
    return `${label} 산출 필요`;
  }

  function buildHomeNews(items: NewsItem[], limit: number) {
    const tagRank: Record<string, number> = { "공시/이슈": 0, "반도체": 1, "2차전지": 2, "AI·로봇": 3, "수급": 4, "지수": 5, "시장": 6, "뉴스": 7, "개별": 8 };
    const prepared = items
      .map((item, idx) => ({ item, idx, tag: newsTag(item) }))
      .sort((a, b) => (tagRank[a.tag] ?? 9) - (tagRank[b.tag] ?? 9) || a.idx - b.idx);
    const picked: NewsItem[] = [];
    const tagCounts = new Map<string, number>();
    const seenTitles = new Set<string>();
    const seenSources = new Map<string, number>();

    for (const { item, tag } of prepared) {
      if (tag === "개별") continue;
      const titleKey = (item.title || "").replace(/\s+/g, " ").slice(0, 34);
      if (!titleKey || seenTitles.has(titleKey)) continue;
      if ((tagCounts.get(tag) ?? 0) >= 1) continue;
      if (item.sourceName && (seenSources.get(item.sourceName) ?? 0) >= 2) continue;
      picked.push(item);
      seenTitles.add(titleKey);
      tagCounts.set(tag, (tagCounts.get(tag) ?? 0) + 1);
      if (item.sourceName) seenSources.set(item.sourceName, (seenSources.get(item.sourceName) ?? 0) + 1);
      if (picked.length >= limit) return picked;
    }

    for (const { item } of prepared) {
      if (picked.length >= limit) break;
      const titleKey = (item.title || "").replace(/\s+/g, " ").slice(0, 34);
      if (!titleKey || seenTitles.has(titleKey)) continue;
      picked.push(item);
      seenTitles.add(titleKey);
    }
    return picked;
  }

  function newsTag(item: NewsItem) {
    const text = `${item.title ?? ""} ${item.summary ?? ""} ${item.name ?? ""} ${item.sourceName ?? ""}`;
    const hasRealName = item.name && !["종목", "시장", item.symbol].includes(item.name) && !/^\d{4,6}$/.test(item.name);
    if (/공시|실적|계약|증자|분기|사업보고|합병|분할|수주|공급계약|자사주|배당/.test(text)) return "공시/이슈";
    if (/삼성전자|하이닉스|반도체|HBM|AI반도체|메모리|파운드리|엔비디아|NVDA/.test(text)) return "반도체";
    if (/전지|배터리|2차전지|LG에너지|에코프로|양극재|음극재/.test(text)) return "2차전지";
    if (/로봇|AI|인공지능|자동화|로보스타|두산로보틱스/.test(text)) return "AI·로봇";
    if (hasRealName || (item.symbol && item.symbol !== "종목")) return "개별";
    if (/외국인|기관|개인|순매수|순매도|매수|매도/.test(text)) return "수급";
    if (/코스피|코스닥|나스닥|S&P|다우|지수/.test(text)) return "지수";
    if (/증시|시장|환율|금리/.test(text)) return "시장";
    return "뉴스";
  }


  function isTodayEntryCandidate(item: FinalRecommendationItem) {
    const text = `${item.decisionBucket ?? ""} ${item.newEntryDecision ?? ""} ${item.buyTiming ?? ""}`;
    return /오늘|진입 가능|조건부 진입|체결 가능/.test(text) && !/주의|금지|대기/.test(text);
  }

  function isWaitCandidate(item: FinalRecommendationItem) {
    const text = `${item.decisionBucket ?? ""} ${item.newEntryDecision ?? ""} ${item.buyTiming ?? ""}`;
    return /기다|대기|다음|눌림|확인/.test(text) && !/금지/.test(text);
  }

  function dataBasisLabel(timeText?: string, source?: string) {
    const sourceText = source ? `${source} 기준` : "MONE final 기준";
    const now = new Date();
    const todayKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    if (timeText && timeText.includes(todayKey)) return `오늘 데이터 · ${sourceText}`;
    if (timeText) return `전일 또는 최근 업데이트 · ${sourceText}`;
    return `기준시각 확인 중 · ${sourceText}`;
  }

  function dataStatusLabel(status?: string, sources?: DataSourceItem[]) {
    const okSources = sources?.filter((item) => item.status === "OK").length ?? 0;
    if (status && /OK|READY|정상|운영 안정/i.test(status)) return "정상";
    if (okSources > 0) return "일부 확인";
    if (status && status !== "NOT_LOADED") return status;
    return "확인 중";
  }

  function newsImpactText(item: NewsItem) {
    const text = `${item.title ?? ""} ${item.summary ?? ""}`;
    if (/수주|공급계약|계약|자사주|배당|실적 개선|흑자/.test(text)) return "긍정적 · 실적/수급 신뢰도 보강";
    if (/증자|CB|전환사채|BW|감자|소송|제재|하향/.test(text)) return "주의 · 위험 점수 상향";
    if (/FOMC|CPI|PPI|PCE|고용|금리|파월|환율/.test(text)) return "중립~주의 · 변동성 확대 가능";
    if (/기관|외국인|순매수|수급/.test(text)) return "긍정적 · 수급 모멘텀 확인";
    if (/코스피|코스닥|나스닥|S&P|지수|시장/.test(text)) return "시장 영향 · 지수 분위기 반영";
    return item.nextAction || "판단 영향 확인 필요";
  }
  function renderReports() {
    if (activeSubPage === "장전 리포트") {
      return (
        <Section title="장전 리포트">
          {premarket.items.length ? (
            <DataTable rows={premarket.items} columns={premarketColumns} onRowClick={setSelectedSymbol} />
          ) : (
            <EmptyReason text="장전 리포트 데이터 없음" />
          )}
        </Section>
      );
    }
    if (activeSubPage === "장중 체크") {
      const validRows = intraday.items.filter((item) => hasUsablePriceLevel(item.entryText, item.entry));
      const excluded = intraday.items.length - validRows.length;
      return (
        <Section
          title="장중 체크"
          right={excluded > 0 ? <span className="text-xs text-muted">기준가 없는 종목 {excluded}개 제외</span> : null}
        >
          {validRows.length ? (
            <DataTable rows={validRows} columns={intradayColumns} onRowClick={setSelectedSymbol} />
          ) : (
            <EmptyReason text="장중 체크 가능한 항목이 없습니다. 기준가가 없는 항목은 메인 표에서 제외했습니다." />
          )}
        </Section>
      );
    }
    if (activeSubPage === "장마감 검증") {
      const validRows = closing.items.filter(isClosingVerifiable);
      const excluded = closing.items.length - validRows.length;
      return (
        <Section
          title="장마감 검증"
          right={excluded > 0 ? <span className="text-xs text-muted">검증 데이터 부족 {excluded}개 제외</span> : null}
        >
          {validRows.length ? (
            <DataTable rows={validRows} columns={closingColumns} />
          ) : (
            <EmptyReason text="오늘 장마감 검증 가능한 항목이 없습니다. 예상 시초가/종가 또는 실제 OHLC 데이터가 부족한 항목은 제외했습니다." />
          )}
        </Section>
      );
    }
    return <EmptyReason text="운용 리포트 메뉴를 선택하세요." />;
  }

  function renderSymbolDiscovery() {
    if (activeSubPage === "오늘 매수 검토") {
      const safeType = candidateType === "risk" ? "action" : candidateType;
      const list = pickForMode(candidates[safeType]?.items ?? [], strategyMode, 30);
      return (
        <>
          <WriteStatus text={writeStatus} />
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <ModeSelector value={strategyMode} onChange={setStrategyMode} />
            {buyCandidateTabs.map(([typeId, label]) => (
              <button
                key={typeId}
                onClick={() => setCandidateType(typeId)}
                className={`rounded-md border px-3 py-2 text-sm font-bold ${
                  safeType === typeId ? "border-accent bg-accent/15 text-accent" : "border-line bg-panel text-slate-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <Section title={`${marketName} 오늘 매수 검토`}>
            {list.length ? (
              <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
                {list.map((item) => renderTradeCandidateCard(item, "buy"))}
              </div>
            ) : (
              <EmptyReason text="오늘 매수 검토 후보가 없습니다." />
            )}
          </Section>
        </>
      );
    }

    if (activeSubPage === "매수금지 / 주의") {
      const list = candidates.risk?.items ?? [];
      return (
        <>
          <WriteStatus text={writeStatus} />
          <Section title={`${marketName} 매수금지 / 주의`}>
            {list.length ? (
              <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
                {list.map((item) => renderTradeCandidateCard(item, "risk"))}
              </div>
            ) : (
              <EmptyReason text="매수금지 / 주의 후보가 없습니다." />
            )}
          </Section>
        </>
      );
    }

    return (
      <>
        <WriteStatus text={writeStatus} />
        <Section title="관심종목 직접 추가">
          <div className="grid gap-3 md:grid-cols-4">
            <FormInput label="종목코드/티커" value={watchForm.symbol} onChange={(value) => setWatchForm((form) => ({ ...form, symbol: value }))} />
            <FormInput label="종목명" value={watchForm.name} onChange={(value) => setWatchForm((form) => ({ ...form, name: value }))} />
            <FormInput label="메모" value={watchForm.memo} onChange={(value) => setWatchForm((form) => ({ ...form, memo: value }))} />
            <button onClick={addWatchlistManual} className="rounded-lg border border-accent/45 bg-accent/12 px-4 py-3 text-sm font-black text-accent hover:bg-accent hover:text-ink">관심종목 추가</button>
          </div>
        </Section>
        <Section
          title={`${marketName} 종목 검색 / 관심`}
          right={<span className="text-xs text-muted">검색 범위: 오늘 선택 · 관심 · 보유 · 후보군</span>}
        >
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="종목명 또는 코드 검색"
            className="mb-3 w-full rounded-lg border border-line bg-panel px-4 py-3 text-sm outline-none focus:border-accent"
          />
          <DataTable
            rows={filteredDiscoveryRows}
            columns={[
              { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
              { key: "symbol", header: "코드", render: (row) => row.symbol },
              { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
              { key: "entry", header: "기준가", render: (row) => priceText(row.entryText, row.entry, "기준가") },
              { key: "stop", header: "손절가", render: (row) => priceText(row.stopText, row.stop, "손절가") },
              { key: "target", header: "목표가", render: (row) => priceText(row.targetText, row.target, "목표가") },
              { key: "source", header: "구분", render: (row) => row.discoverySource || "검색 대상" },
              { key: "chart", header: "차트", render: (row) => <button onClick={(event) => { event.stopPropagation(); setSelectedSymbol(row); setActiveCategory("차트·기술분석"); setActiveSubPage("차트 보기"); }} className="rounded-md border border-accent/45 px-2 py-1 text-xs font-bold text-accent hover:bg-accent hover:text-ink">보기</button> },
              { key: "watch", header: "관심", render: (row) => row.isWatchlisted ? <span className="text-xs font-bold text-good">관심중</span> : <button onClick={(event) => { event.stopPropagation(); addWatchlistFrom(row); }} className="rounded-md border border-accent/45 px-2 py-1 text-xs font-bold text-accent hover:bg-accent hover:text-ink">추가</button> }
            ]}
            onRowClick={setSelectedSymbol}
          />
        </Section>
        <Section title="상세 카드">
          {selectedSymbol ? <SymbolDetailCard item={selectedSymbol} mode={strategyMode} newsItems={news.items} disclosures={disclosures.items} companyItems={companyAnalysis.items} /> : <EmptyReason text="선택된 종목이 없습니다." />}
        </Section>
      </>
    );
  }

  function renderTradeCandidateCard(item: Security, mode: "buy" | "risk") {
    const prediction = predictionBySymbol.get(item.symbol) ?? item;
    const status = mode === "risk" ? shortRiskText(item.warning || item.reason || item.dataStatus || "관망") : formatRiskRewardFromPrices(item);
    return (
      <button
        key={`${mode}-${item.symbol}`}
        onClick={() => setSelectedSymbol(item)}
        className={`rounded-xl border bg-panel p-4 text-left shadow-soft transition hover:bg-accent/5 ${mode === "risk" ? "border-warn/45 hover:border-warn" : "border-line hover:border-accent/60"}`}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-lg font-black text-white">{item.name || item.symbol}</div>
            <div className="mt-1 text-xs text-muted">{item.symbol}</div>
          </div>
          <div className="text-right">
            <div className="text-base font-black text-white">{item.currentPriceText || "현재가 없음"}</div>
            <div className="mt-1 text-xs text-muted">{item.priceTime || "기준시각 없음"}</div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2 text-sm">
          <PriceMini label="기준가" value={priceText(item.entryText, item.entry, "기준가")} />
          <PriceMini label="손절가" value={priceText(item.stopText, item.stop, "손절가")} tone="warn" />
          <PriceMini label="목표가" value={priceText(item.targetText, item.target, "목표가")} tone="good" />
        </div>
        <div className="mt-3 rounded-lg bg-white/5 px-3 py-2 text-xs font-bold leading-5 text-slate-200">
          {mode === "buy" ? `${status} · ${predictionLine(prediction)} · ${tradePlanLine(item, strategyMode)}` : `상태 ${status} · ${gapText(item)} · ${tradePlanLine(item, strategyMode)}`}
        </div>
        <div className="mt-3 flex justify-end">
          <button onClick={(event) => { event.stopPropagation(); addWatchlistFrom(item); }} className="rounded-md border border-accent/45 px-2 py-1 text-xs font-bold text-accent hover:bg-accent hover:text-ink">관심 추가</button>
        </div>
      </button>
    );
  }

  function renderPositions() {
    const managementRows = directHoldings.items.length ? directHoldings.items : positions.items;
    return (
      <>
        <WriteStatus text={writeStatus} />
        <Section title={`${marketName} 보유 현황`}>
          {managementRows.length ? (
            <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
              {managementRows.map((item) => renderHoldingCard(item))}
            </div>
          ) : (
            <EmptyReason text="보유종목이 없습니다." />
          )}
        </Section>
        <Section title="보유종목 추가 / 수정">
          <div className="grid gap-3 md:grid-cols-6">
            <FormInput label="종목코드/티커" value={holdingForm.symbol} onChange={(value) => setHoldingForm((form) => ({ ...form, symbol: value }))} />
            <FormInput label="종목명" value={holdingForm.name} onChange={(value) => setHoldingForm((form) => ({ ...form, name: value }))} />
            <FormInput label="평균단가" value={holdingForm.avgPrice} onChange={(value) => setHoldingForm((form) => ({ ...form, avgPrice: value }))} />
            <FormInput label="수량" value={holdingForm.quantity} onChange={(value) => setHoldingForm((form) => ({ ...form, quantity: value }))} />
            <FormInput label="메모" value={holdingForm.memo} onChange={(value) => setHoldingForm((form) => ({ ...form, memo: value }))} />
            <button onClick={saveHolding} className="rounded-lg border border-accent/45 bg-accent/12 px-4 py-3 text-sm font-black text-accent hover:bg-accent hover:text-ink">저장 / 업데이트</button>
          </div>
        </Section>
      </>
    );
  }

  function renderHoldingCard(item: Security) {
    const risk = holdingRiskText(item);
    return (
      <div key={item.symbol} className="rounded-xl border border-line bg-panel p-4 shadow-soft">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-lg font-black text-white">{item.name || item.symbol}</div>
            <div className="mt-1 text-xs text-muted">{item.symbol}</div>
          </div>
          <div className="text-right">
            <div className="text-base font-black text-white">{item.currentPriceText || "현재가 없음"}</div>
            <div className="mt-1 text-xs text-muted">{item.priceTime || "기준시각 없음"}</div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 text-sm">
          <MiniMetric label="수량" value={item.quantityText || "수량 없음"} />
          <MiniMetric label="평균단가" value={item.avgPriceText || "평균단가 없음"} />
          <MiniMetric label="평가손익" value={item.pnlText || "평가손익 없음"} />
          <MiniMetric label="수익률" value={item.returnPctText || "수익률 없음"} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <PriceMini label="손절가" value={priceText(item.stopText, item.stop, "손절가")} tone="warn" />
          <PriceMini label="목표가" value={priceText(item.targetText, item.target, "목표가")} tone="good" />
        </div>
        <div className="mt-3 rounded-lg bg-white/5 px-3 py-2 text-xs font-bold leading-5 text-slate-200">
          상태 {holdingStatusText(item)} · 리스크 {risk}
        </div>
        <div className="mt-3 flex gap-2">
          <button
            onClick={() => fillHoldingForm(item)}
            className="rounded-md border border-accent/40 px-2 py-1 text-xs font-bold text-accent"
          >
            수정
          </button>
          <button
            onClick={() => deleteHoldingSymbol(item.symbol)}
            className="rounded-md border border-warn/40 px-2 py-1 text-xs font-bold text-warn"
          >
            삭제
          </button>
        </div>
      </div>
    );
  }

  function renderCharts() {
    const chartUniverse = symbols.items.length ? symbols.items : [...positions.items, ...watchlist.items];
    const selected = selectedSymbol ?? chartUniverse[0] ?? null;
    return (
      <>
        <Section
          title="차트 보기"
          right={
            chartUniverse.length ? (
              <select
                value={selected?.symbol ?? ""}
                onChange={(event) => {
                  const found = chartUniverse.find((item) => item.symbol === event.target.value);
                  if (found) setSelectedSymbol(found);
                }}
                className="min-w-56 rounded-lg border border-line bg-panel px-3 py-2 text-sm font-bold text-white outline-none focus:border-accent"
              >
                {chartUniverse.map((item) => (
                  <option key={item.symbol} value={item.symbol}>
                    {item.name || item.symbol} ({item.symbol})
                  </option>
                ))}
              </select>
            ) : null
          }
        >
          {selected ? (
            <div className="mb-4 grid gap-3 md:grid-cols-4">
              <PriceMini label="현재가" value={selected.currentPriceText || "현재가 없음"} />
              <PriceMini label="기준가" value={priceText(selected.entryText, selected.entry, "기준가")} />
              <PriceMini label="손절가" value={priceText(selected.stopText, selected.stop, "손절가")} tone="warn" />
              <PriceMini label="목표가" value={priceText(selected.targetText, selected.target, "목표가")} tone="good" />
              <PriceMini label="단기 예상가" value={expectedPriceText(selected, "short")} />
              <PriceMini label="스윙 예상가" value={expectedPriceText(selected, "swing")} />
              <PriceMini label="중기 예상가" value={expectedPriceText(selected, "mid")} />
              <PriceMini label="상태" value={priceLevelStatus(selected)} />
            </div>
          ) : null}
          {chartData.items.length ? (
            <>
              <div className="mb-3 text-xs text-muted">차트 소스: {chartData.source || "소스 없음"} · {chartData.count ?? chartData.items.length} rows · 캔들/거래량/MA/BB/RSI/MACD 계산값 제공</div>
              <div className="h-80 rounded-lg border border-line bg-panel p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData.items}>
                    <CartesianGrid stroke="rgba(148,163,184,.16)" />
                    <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid rgba(148,163,184,.25)" }} />
                    <Line type="monotone" dataKey="close" stroke="#38bdf8" dot={false} name="종가" />
                    <Line type="monotone" dataKey="ma5" stroke="#22c55e" dot={false} name="MA5" />
                    <Line type="monotone" dataKey="ma20" stroke="#f59e0b" dot={false} name="MA20" />
                    <Line type="monotone" dataKey="bbUpper" stroke="#94a3b8" dot={false} name="BB 상단" />
                    <Line type="monotone" dataKey="bbLower" stroke="#94a3b8" dot={false} name="BB 하단" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                <MiniMetric label="RSI" value={formatNumber(chartData.latest?.rsi, "RSI 부족")} />
                <MiniMetric label="MACD" value={formatNumber(chartData.latest?.macd, "MACD 부족")} />
                <MiniMetric label="거래량" value={formatNumber(chartData.latest?.volume, "거래량 부족")} />
              </div>
              <div className="mt-3 h-32 rounded-lg border border-line bg-panel p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData.items}>
                    <XAxis dataKey="date" hide />
                    <YAxis hide />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid rgba(148,163,184,.25)" }} />
                    <Bar dataKey="volume" name="거래량" fill="#38bdf8" opacity={0.45} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
                {(chartData.indicatorStatus ?? []).map((text, idx) => (
                  <span key={idx} className="rounded-md border border-line bg-panel px-2 py-1">{text}</span>
                ))}
              </div>
            </>
          ) : (
            <EmptyReason text={chartData.message || "차트 데이터 준비 중입니다. 현재는 가격 기준선과 예상가 요약을 우선 표시합니다."} />
          )}
        </Section>
      </>
    );
  }

  function renderNewsCompany() {
    if (activeSubPage === "공시") {
      return (
        <Section
          title="공시"
          right={
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
              <span>{(disclosures.sources ?? []).join(" · ") || "공시 CSV 감지 대기"}</span>
              <button onClick={refreshDisclosures} className="rounded-md border border-accent/40 px-2 py-1 font-bold text-accent hover:bg-accent hover:text-ink">공시 수집</button>
            </div>
          }
        >
          {disclosures.items.length ? (
            <DataTable
              rows={disclosures.items}
              columns={[
                { key: "name", header: "회사", render: (row) => <b>{row.name || row.symbol}</b> },
                { key: "title", header: "공시 제목", render: (row) => <LongText text={row.title} /> },
                { key: "date", header: "공시일", render: (row) => row.date || "공시일 없음" },
                { key: "source", header: "출처", render: (row) => row.sourceName || "출처 없음" },
                { key: "link", header: "링크", render: (row) => row.url ? <a className="text-accent" href={row.url} target="_blank">열기</a> : "링크 없음" }
              ]}
            />
          ) : (
            <>
              <EmptyReason text="공시 데이터 없음 · DART/SEC 공시 수집 CSV가 아직 없습니다." />
              <div className="mt-4 rounded-xl border border-line bg-panel p-4 text-sm leading-6 text-muted">
                뉴스 요약 데이터는 공시 탭에 표시하지 않습니다. 공시 CSV가 생성되면 이 화면에 실제 공시만 표시됩니다.
                {disclosureRefreshStatus ? <div className="mt-2 font-bold text-accent">{disclosureRefreshStatus}</div> : null}
              </div>
            </>
          )}
        </Section>
      );
    }

    if (activeSubPage === "기업분석") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="기업분석 행" value={companyAnalysis.count} note={sourceLabel(companyAnalysis.source)} tone={companyAnalysis.count ? "accent" : "warn"} />
            <StatCard label="공시" value={disclosures.count} note="공시 CSV 연결 상태" />
            <StatCard label="수급/재무" value={dataSources.find((item) => item.key === "flow")?.status ?? "확인 필요"} note="관리 > 데이터 소스" />
            <StatCard label="시장" value={marketName} />
          </div>
          <Section title="기업분석">
            {companyAnalysis.items.length ? (
              <DataTable
                rows={companyAnalysis.items}
                columns={[
                  { key: "name", header: "종목", render: (row) => <b>{row.name || row.symbol}</b> },
                  { key: "price", header: "현재가", render: (row) => row.currentPriceText || "현재가 없음" },
                  { key: "supply", header: "수급", render: (row) => row.supply || row.flowStatus || "수급 데이터 없음" },
                  { key: "eps", header: "EPS", render: (row) => row.eps || "EPS 데이터 없음" },
                  { key: "per", header: "PER/PBR", render: (row) => `${row.per || "PER 없음"} / ${row.pbr || "PBR 없음"}` },
                  { key: "profit", header: "매출/영업익", render: (row) => <LongText text={`${row.revenue || "매출 없음"} / ${row.operatingIncome || "영업익 없음"}`} /> },
                  { key: "income", header: "연간/분기", render: (row) => <LongText text={`${row.annualPerformance || "연간실적 대기"} / ${row.quarterlyPerformance || "분기실적 대기"}`} /> },
                  { key: "status", header: "상태", render: (row) => row.incomeStatementStatus || row.dataStatus || "상태 없음" }
                ]}
              />
            ) : (
              <EmptyReason text="기업분석 데이터 없음" />
            )}
          </Section>
        </>
      );
    }

    return (
      <>
        <div className="grid gap-3 md:grid-cols-3">
          <StatCard label="뉴스" value={news.count || "뉴스 없음"} note={sourceLabel(news.source)} tone={news.count ? "accent" : "warn"} />
          <StatCard label="공시" value={disclosures.count || "공시 없음"} note="공시 탭에서 확인" />
          <StatCard label="시장" value={marketName} note="뉴스·공시·재무 통합 화면" />
        </div>
        <Section title="뉴스 요약">
          {news.items.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {news.items.map((item, idx) => (
                <a
                  key={idx}
                  href={item.url || undefined}
                  target="_blank"
                  className="rounded-lg border border-line bg-card p-4 hover:border-accent/50"
                >
                  <div className="text-xs text-muted">
                    [{newsTag(item)}] {item.sourceName} · {item.publishedAt}
                  </div>
                  <div className="mt-2 font-black text-white">{item.title}</div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">{item.summary || "요약 없음"}</p>
                  <div className="mt-3 text-xs text-accent">{item.name || item.symbol || "연결 종목 없음"}</div>
                </a>
              ))}
            </div>
          ) : (
            <EmptyReason text="뉴스 없음" />
          )}
        </Section>
      </>
    );
  }

  function renderPredictions() {
    return (
      <>
        <div className="grid gap-3 md:grid-cols-3">
          <StatCard label="확률 행" value={predictionRows.length} note={`${STRATEGY_MODE_LABEL[strategyMode]} 모드 필터 · 전체 ${predictions.count}행`} tone="accent" />
          <StatCard label="표시 항목" value="단기 · 스윙 · 중기" note={sourceLabel(predictions.source)} />
          <StatCard label="시장" value={marketName} note="참고용 예측 지표" />
        </div>
        <Section title={`확률 예측 · ${STRATEGY_MODE_LABEL[strategyMode]} 모드`}>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <ModeSelector value={strategyMode} onChange={setStrategyMode} />
            <span className="text-xs text-muted">추천과 가상 운용 계산 기준이 함께 바뀝니다.</span>
          </div>
          <DataTable
            rows={predictionRows}
            columns={[
              { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
              { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
              { key: "short", header: "단기", render: (row) => probabilityCell(row, "short") },
              { key: "swing", header: "스윙", render: (row) => probabilityCell(row, "swing") },
              { key: "mid", header: "중기", render: (row) => probabilityCell(row, "mid") },
              { key: "grade", header: "스윙군", render: (row) => row.swingGrade || "스윙 C군" },
              { key: "mode", header: "추천모드", render: (row) => row.recommendationModeText || "추천 모드 산출 필요" }
            ]}
            onRowClick={setSelectedSymbol}
          />
        </Section>
        <Section title={`가상 운용 미리보기 · ${STRATEGY_MODE_LABEL[strategyMode]}`}>
          {selectedPreviewRows.length ? (
            <DataTable
              rows={selectedPreviewRows}
              columns={[
                { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
                { key: "grade", header: "스윙군", render: (row) => row.swingGrade },
                { key: "entry", header: "예상 매수가", render: (row) => row.entry },
                { key: "shares", header: "수량", render: (row) => row.shares },
                { key: "invested", header: "투입금", render: (row) => row.invested },
                { key: "loss", header: "손실", render: (row) => row.loss },
                { key: "profit", header: "이익", render: (row) => row.profit },
                { key: "account", header: "운용 수익률", render: (row) => `${row.accountLossPct} / ${row.accountProfitPct}` },
                { key: "rule", header: "체결 기준", render: (row) => <LongText text={row.buyRule} /> }
              ]}
            />
          ) : (
            <EmptyReason text="해당 모드의 가상 운용 후보가 부족합니다." />
          )}
        </Section>
      </>
    );
  }

  function renderPredictionAdmin() {
    if (activeSubPage === "예측 기록") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="예측 기록" value={predictionHistory.count} note={predictionHistory.source} tone="accent" />
            <StatCard label="시장 예측 rows" value={predictionInsights.summary.predictionRows} note={market === "kr" ? "국장" : "미장"} />
            <StatCard label="검증 커버리지" value={predictionInsights.summary.coverage} note="검증 rows / 예측 rows" />
            <StatCard label="성공률" value={predictionInsights.summary.successRate} note="success/fail 기준" tone="good" />
          </div>
          <Section title="종목별 예측 성과">
            <SimpleRecords rows={predictionInsights.bySymbol.slice(0, 60)} empty="종목별 성과 데이터 부족" />
          </Section>
          <HistoryTable title="예측 기록" history={predictionHistory} />
        </>
      );
    }
    if (activeSubPage === "결과 검증") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="결과 검증" value={outcomeHistory.count} note={outcomeHistory.source} tone="accent" />
            <StatCard label="성공" value={predictionInsights.summary.success} tone="good" />
            <StatCard label="실패" value={predictionInsights.summary.fail} tone="warn" />
            <StatCard label="중립/대기" value={predictionInsights.summary.neutral} />
          </div>
          <Section title="기간별 적중률">
            <SimpleRecords rows={predictionInsights.byPeriod} empty="기간별 검증 데이터 부족" />
          </Section>
          <HistoryTable title="결과 검증" history={outcomeHistory} />
        </>
      );
    }
    if (activeSubPage === "실패 복기") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="실패 후보" value={predictionInsights.failures.length} note="최근 실패/불일치 행" tone="warn" />
            <StatCard label="검증 사용 rows" value={predictionInsights.summary.validationRows} note="outcome > history > predictions" />
            <StatCard label="실패" value={predictionInsights.summary.fail} tone="warn" />
            <StatCard label="성공률" value={predictionInsights.summary.successRate} />
          </div>
          <Section title="실패 복기">
            <SimpleRecords rows={predictionInsights.failures} empty="실패 복기 데이터 부족" />
          </Section>
          <Section title="진단">
            <SimpleRecords rows={predictionInsights.diagnostics} empty="예측 진단 데이터 부족" />
          </Section>
        </>
      );
    }
    if (activeSubPage === "자동 보정") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="자동 보정 후보" value={predictionInsights.corrections.length} note="종목/기간별 제안" tone="accent" />
            <StatCard label="검증 커버리지" value={predictionInsights.summary.coverage} />
            <StatCard label="실패" value={predictionInsights.summary.fail} tone="warn" />
            <StatCard label="성공" value={predictionInsights.summary.success} tone="good" />
          </div>
          <Section title="자동 보정 후보">
            <SimpleRecords rows={predictionInsights.corrections} empty="자동 보정 후보 부족" />
          </Section>
          <Section title="종목별 보정 참고">
            <SimpleRecords rows={predictionInsights.bySymbol.slice(0, 40)} empty="종목별 보정 데이터 부족" />
          </Section>
        </>
      );
    }
    return null;
  }


  function renderBacktestAdmin() {
    if (activeSubPage === "백테스트") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="백테스트 상태" value={backtest.status || "NO_DATA"} note={(backtest.warnings ?? []).join(" · ") || "상태 없음"} tone={backtest.status === "OK" ? "good" : "warn"} />
            <StatCard label="전략 수" value={backtest.count} note="OHLCV 기반 전략" tone="accent" />
            <StatCard label="전체 예측 rows" value={backtest.totalPredictionRows ?? backtest.predictionRows} note="predictions.csv" />
            <StatCard label="결과 검증 rows" value={backtest.outcomeRows} note="outcome_history.csv" />
            <StatCard label="OHLCV 파일" value={backtest.ohlcv?.files ?? 0} note="data/market/ohlcv" tone="accent" />
            <StatCard label="30일 이상 종목" value={backtest.ohlcv?.eligibleSymbols ?? 0} note={`최소 ${backtest.ohlcv?.minDaysRequired ?? 30}일`} tone={(backtest.ohlcv?.eligibleSymbols ?? 0) ? "good" : "warn"} />
            <StatCard label="예측+가격 매칭" value={backtest.ohlcv?.predictionMatchedSymbols ?? 0} note="예측과 OHLCV 모두 존재" />
            <StatCard label="시장 필터 rows" value={backtest.predictionRows} note={market === "kr" ? "국장" : "미장"} />
          </div>
          <Section title="백테스트 데이터 진단">
            <SimpleRecords rows={backtest.diagnostics ?? []} empty="백테스트 진단 데이터 없음" />
          </Section>
          <Section title="백테스트 전략별 성과">
            {backtest.items.length ? <DataTable rows={backtest.items} columns={backtestColumns} /> : <EmptyReason text="백테스트 데이터 부족 사유: 전략 신호 또는 OHLCV 기록 부족" />}
          </Section>
          <Section title="최근 백테스트 신호">
            <SimpleRecords rows={(backtest.recentTrades ?? []).slice(0, 20)} empty="최근 백테스트 신호 없음" />
          </Section>
          <Section title="최근 결과">
            <SimpleRecords rows={backtest.recentOutcomes.slice(0, 20)} empty="최근 검증 결과 없음" />
          </Section>
        </>
      );
    }
    return null;
  }
  function renderAdmin() {
    const backtestAdmin = renderBacktestAdmin();
    if (backtestAdmin) return backtestAdmin;
    const predictionAdmin = renderPredictionAdmin();
    if (predictionAdmin) return predictionAdmin;
    if (activeSubPage === "데이터 점검") return <FileStatusTable rows={files} />;
    if (activeSubPage === "데이터 소스") return <DataSourceStatus rows={dataSources} />;
    if (activeSubPage === "API 상태") return <ApiStatus env={env} />;
    if (activeSubPage === "자동화 상태") return <AutomationStatus automation={summary?.automation} updatedAt={updatedAt} github={githubActions} />;
    return <FileStatusTable rows={files.filter((item) => item.path.includes("history") || item.path.includes("daily_watch"))} />;
  }

  function renderAdvanced() {
    if (activeSubPage === "백테스트") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="백테스트 상태" value={backtest.status || "NO_DATA"} note={(backtest.warnings ?? []).join(" · ") || "상태 없음"} tone={backtest.status === "OK" ? "good" : "warn"} />
            <StatCard label="전략 수" value={backtest.count} note="OHLCV 기반 전략" tone="accent" />
            <StatCard label="전체 예측 rows" value={backtest.totalPredictionRows ?? backtest.predictionRows} note="predictions.csv" />
            <StatCard label="결과 검증 rows" value={backtest.outcomeRows} note="outcome_history.csv" />
            <StatCard label="OHLCV 파일" value={backtest.ohlcv?.files ?? 0} note="data/market/ohlcv" tone="accent" />
            <StatCard label="30일 이상 종목" value={backtest.ohlcv?.eligibleSymbols ?? 0} note={`최소 ${backtest.ohlcv?.minDaysRequired ?? 30}일`} tone={(backtest.ohlcv?.eligibleSymbols ?? 0) ? "good" : "warn"} />
            <StatCard label="예측+가격 매칭" value={backtest.ohlcv?.predictionMatchedSymbols ?? 0} note="예측과 OHLCV 모두 존재" />
            <StatCard label="시장 필터 rows" value={backtest.predictionRows} note={market === "kr" ? "국장" : "미장"} />
          </div>
          <Section title="백테스트 데이터 진단">
            <SimpleRecords rows={backtest.diagnostics ?? []} empty="백테스트 진단 데이터 없음" />
          </Section>
          <Section title="백테스트 전략별 성과">
            {backtest.items.length ? <DataTable rows={backtest.items} columns={backtestColumns} /> : <EmptyReason text="백테스트 데이터 부족 사유: 전략 신호 또는 OHLCV 기록 부족" />}
          </Section>
          <Section title="최근 백테스트 신호">
            <SimpleRecords rows={(backtest.recentTrades ?? []).slice(0, 20)} empty="최근 백테스트 신호 없음" />
          </Section>
          <Section title="최근 결과">
            <SimpleRecords rows={backtest.recentOutcomes.slice(0, 20)} empty="최근 검증 결과 없음" />
          </Section>
        </>
      );
    }
    if (activeSubPage === "스캐너") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="스캐너 대상" value={scanner.count || scanner.items.length} note="candidate/watchlist/cards 조합" tone="accent" />
            <StatCard label="현재 필터" value={scannerFilter} />
            <StatCard label="보유 제외" value={scanner.items.filter((item) => !item.isHolding).length} />
            <StatCard label="관심종목 편입" value="활성화" note="중복 방지 + 백업 후 저장" tone="good" />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {["전체", "BUY", "주의", "눌림목", "수급", "저평가", "보유 제외"].map((filter) => (
              <button
                key={filter}
                onClick={() => setScannerFilter(filter)}
                className={`rounded-full border px-3 py-2 text-sm font-bold ${scannerFilter === filter ? "border-accent bg-accent text-ink" : "border-line bg-panel text-slate-300"}`}
              >
                {filter}
              </button>
            ))}
          </div>
          <Section title="스캐너">
            {displayedScanner.length ? (
              <>
                {!filteredScanner.length && scanner.items.length ? <div className="mb-3 text-xs text-muted">현재 필터에 맞는 결과가 없어 전체 스캐너 결과를 표시합니다.</div> : null}
                <DataTable rows={displayedScanner} columns={scannerColumns} onRowClick={setSelectedSymbol} />
              </>
            ) : (
              <EmptyReason text="조건에 맞는 스캐너 결과 없음" />
            )}
          </Section>
        </>
      );
    }
    if (activeSubPage === "계산기") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="Kelly" value={String(calculator.kelly?.halfKellyText ?? "미계산")} note="Half Kelly 기준" tone="accent" />
            <StatCard label="VaR / CVaR" value={String(calculator.var?.varPct ?? "미계산")} note={String(calculator.var?.cvarPct ?? "실행 필요")} tone="warn" />
            <StatCard label="손익비" value={String(calculator.rr?.ratioText ?? "미계산")} note="자동주문 없음" />
          </div>
          <Section title="계산기 입력">
            <div className="mb-3 rounded-lg border border-line bg-panel px-4 py-3 text-sm leading-6 text-muted">
              기본값으로 바로 계산할 수 있지만, 실제 매매 전에는 자본·진입가·손절가·목표가를 본인 계획에 맞게 수정하세요. 이 계산기는 주문을 실행하지 않습니다.
            </div>
            <div className="grid gap-3 md:grid-cols-5">
              <FormInput label="자본" value={calculatorForm.capital} onChange={(value) => setCalculatorForm((form) => ({ ...form, capital: value }))} />
              <FormInput label="승률(%)" value={calculatorForm.winRate} onChange={(value) => setCalculatorForm((form) => ({ ...form, winRate: value }))} />
              <FormInput label="Payoff" value={calculatorForm.payoffRatio} onChange={(value) => setCalculatorForm((form) => ({ ...form, payoffRatio: value }))} />
              <FormInput label="VaR 신뢰도(%)" value={calculatorForm.confidence} onChange={(value) => setCalculatorForm((form) => ({ ...form, confidence: value }))} />
              <button onClick={runCalculators} className="rounded-lg border border-accent/45 bg-accent/12 px-4 py-3 text-sm font-black text-accent hover:bg-accent hover:text-ink">계산 실행</button>
              <FormInput label="포트폴리오 금액" value={calculatorForm.portfolioValue} onChange={(value) => setCalculatorForm((form) => ({ ...form, portfolioValue: value }))} />
              <FormInput label="기대수익률(%)" value={calculatorForm.expectedReturn} onChange={(value) => setCalculatorForm((form) => ({ ...form, expectedReturn: value }))} />
              <FormInput label="변동성(%)" value={calculatorForm.volatility} onChange={(value) => setCalculatorForm((form) => ({ ...form, volatility: value }))} />
              <FormInput label="진입가" value={calculatorForm.entry} onChange={(value) => setCalculatorForm((form) => ({ ...form, entry: value }))} />
              <FormInput label="손절가 / 목표가" value={`${calculatorForm.stop} / ${calculatorForm.target}`} onChange={(value) => { const [stop, target] = value.split("/").map((v) => v.trim()); setCalculatorForm((form) => ({ ...form, stop: stop ?? form.stop, target: target ?? form.target })); }} />
            </div>
          </Section>
          <Section title="계산 결과">
            <SimpleRecords
              rows={[
                { 계산: "Kelly 포지션 사이징", 결과: String(calculator.kelly?.halfKellyText ?? "계산 전"), 설명: String(calculator.kelly?.note ?? "계산 결과만 표시합니다.") },
                { 계산: "VaR / CVaR", 결과: `${String(calculator.var?.varPct ?? "계산 전")} / ${String(calculator.var?.cvarPct ?? "계산 전")}`, 설명: "손실 분위수 기반" },
                { 계산: "위험조정수익률", 결과: String(calculator.rr?.rewardPct ?? "계산 전"), 설명: "목표 보상률 참고" },
                { 계산: "손익비", 결과: String(calculator.rr?.ratioText ?? "계산 전"), 설명: "진입/손절/목표 기반" },
                { 계산: "포지션 수량", 결과: String(calculator.kelly?.positionAmountText ?? "계산 전"), 설명: "자동주문은 지원하지 않음" }
              ]}
              empty="계산 결과 없음"
            />
          </Section>
        </>
      );
    }
    if (activeSubPage === "몬테카를로") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-5">
            <StatCard label="P5" value={monteCarlo?.p5 ?? "미계산"} />
            <StatCard label="P50" value={monteCarlo?.p50 ?? "미계산"} tone="accent" />
            <StatCard label="P95" value={monteCarlo?.p95 ?? "미계산"} tone="good" />
            <StatCard label="상승확률" value={monteCarlo?.upProbability ?? "미계산"} />
            <button onClick={runMonteCarlo} className="rounded-lg border border-accent/45 bg-accent/12 px-4 py-3 text-sm font-black text-accent hover:bg-accent hover:text-ink">시뮬레이션 실행</button>
          </div>
          <Section title="몬테카를로 입력">
            <div className="mb-3 rounded-lg border border-line bg-panel px-4 py-3 text-sm leading-6 text-muted">
              현재가를 비워두면 선택 종목의 현재가로 실행합니다. 기본값 실행은 가능하지만, 선택 종목의 OHLCV와 변동성 값이 충분할수록 해석 신뢰도가 좋아집니다.
            </div>
            <div className="grid gap-3 md:grid-cols-5">
              <FormInput label="현재가" value={monteCarloForm.currentPrice} placeholder={String(selectedSymbol?.currentPrice ?? symbols.items[0]?.currentPrice ?? 100)} onChange={(value) => setMonteCarloForm((form) => ({ ...form, currentPrice: value }))} />
              <FormInput label="기대수익률(%)" value={monteCarloForm.expectedReturn} onChange={(value) => setMonteCarloForm((form) => ({ ...form, expectedReturn: value }))} />
              <FormInput label="변동성(%)" value={monteCarloForm.volatility} onChange={(value) => setMonteCarloForm((form) => ({ ...form, volatility: value }))} />
              <FormInput label="기간(일)" value={monteCarloForm.days} onChange={(value) => setMonteCarloForm((form) => ({ ...form, days: value }))} />
              <FormInput label="시뮬레이션 수" value={monteCarloForm.simulations} onChange={(value) => setMonteCarloForm((form) => ({ ...form, simulations: value }))} />
            </div>
          </Section>
          <Section title="몬테카를로 GBM 경로">
            {monteCarlo?.chart?.length ? (
              <div className="h-72 rounded-lg border border-line bg-panel p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={monteCarlo.chart}>
                    <CartesianGrid stroke="rgba(148,163,184,.16)" />
                    <XAxis dataKey="day" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid rgba(148,163,184,.25)" }} />
                    <Line type="monotone" dataKey="p5" stroke="#f59e0b" dot={false} />
                    <Line type="monotone" dataKey="p50" stroke="#38bdf8" dot={false} />
                    <Line type="monotone" dataKey="p95" stroke="#22c55e" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyReason text="몬테카를로 입력값을 확인한 뒤 시뮬레이션 실행을 누르세요." />
            )}
          </Section>
          <Section title="위험 지표">
            <SimpleRecords rows={[{ 예상최종가: String(monteCarlo?.expectedFinalPrice ?? "미계산"), VaR: monteCarlo?.varText ?? "미계산", CVaR: monteCarlo?.cvarText ?? "미계산" }]} empty="위험 지표 없음" />
          </Section>
        </>
      );
    }
    if (activeSubPage === "상관관계 / 히트맵") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="상태" value={correlation.status} note={correlation.reason} tone={correlation.status === "OK" ? "good" : "warn"} />
            <StatCard label="자산 수" value={correlation.assets?.length ?? 0} note={(correlation.sources ?? []).join(" · ")} tone="accent" />
            <StatCard label="분산 효과" value="설명" note={correlation.diversificationNote ?? "상관관계 계산 데이터 부족"} />
          </div>
          <Section title="상관관계 / 히트맵">
            {correlation.matrix.length ? <CorrelationHeatmap matrix={correlation.matrix} /> : <EmptyReason text="상관관계 계산 데이터 부족" />}
          </Section>
          <Section title="상관관계 페어">
            {correlation.items.length ? (
              <DataTable
                rows={correlation.items}
                columns={[
                  { key: "pair", header: "페어", render: (row) => row.pair },
                  { key: "corr", header: "상관", render: (row) => row.correlation.toFixed(3) },
                  { key: "interp", header: "해석", render: (row) => row.interpretation }
                ]}
              />
            ) : (
              <EmptyReason text="상관관계 계산 데이터 부족" />
            )}
          </Section>
        </>
      );
    }
    return <ComingSoon title={activeSubPage} />;
  }
}



function strategyModeScore(item: Security, mode: StrategyMode) {
  const grade = item.swingGradeCode || (item.swingGrade?.includes("A") ? "A" : item.swingGrade?.includes("B") ? "B" : "C");
  const modes = item.recommendationModes ?? [];
  let score = modes.includes(mode) ? 30 : 0;
  if (mode === "conservative") score += grade === "A" ? 40 : grade === "B" ? 10 : -20;
  if (mode === "balanced") score += grade === "A" ? 35 : grade === "B" ? 25 : 5;
  if (mode === "aggressive") score += grade === "A" ? 30 : grade === "B" ? 24 : 16;
  const rrText = formatRiskRewardFromPrices(item);
  const rr = Number(rrText.replace(/[^0-9.]/g, ""));
  if (Number.isFinite(rr)) score += Math.min(20, rr * 6);
  if (item.currentPrice && item.entry) {
    const gap = (item.currentPrice - item.entry) / item.entry;
    if (mode === "conservative") score += gap <= 0.02 ? 15 : -15;
    if (mode === "balanced") score += gap <= 0.06 ? 12 : -8;
    if (mode === "aggressive") score += gap <= 0.12 ? 10 : -5;
  }
  return score;
}

function pickForMode(items: Security[], mode: StrategyMode, limit = 30) {
  return [...items]
    .filter((item) => {
      const modes = item.recommendationModes ?? [];
      if (modes.includes(mode)) return true;
      if (mode === "aggressive") return Boolean(item.entry && item.stop && item.target);
      return false;
    })
    .sort((a, b) => strategyModeScore(b, mode) - strategyModeScore(a, mode))
    .slice(0, limit);
}

function ModeSelector({ value, onChange }: { value: StrategyMode; onChange: (value: StrategyMode) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-lg border border-line bg-panel p-1">
      {(["conservative", "balanced", "aggressive"] as StrategyMode[]).map((mode) => (
        <button
          key={mode}
          type="button"
          onClick={() => onChange(mode)}
          className={`rounded-md px-3 py-1.5 text-xs font-black transition ${value === mode ? "bg-accent text-ink" : "text-slate-300 hover:bg-white/5 hover:text-white"}`}
        >
          {STRATEGY_MODE_LABEL[mode]}
        </button>
      ))}
    </div>
  );
}

function modeGuideText(mode: StrategyMode) {
  if (mode === "conservative") return "손실 제한 우선 · 기준가 근처 또는 이하만 진입 · 이벤트 전 급등주는 대기";
  if (mode === "aggressive") return "상승 여력과 모멘텀 우선 · 돌파 진입 일부 허용 · 손절선 짧게";
  return "수익 기회와 리스크 균형 · 기준가 ±1% 중심 · 스윙 A/B군 우선";
}

function groupPortfolioItemsByTiming(items: VirtualPortfolioResponse["items"], mode: StrategyMode): Record<TimingBucket, VirtualPortfolioResponse["items"]> {
  const groups: Record<TimingBucket, VirtualPortfolioResponse["items"]> = { today: [], wait: [], next: [], risk: [] };
  for (const item of items ?? []) {
    groups[timingBucketForPortfolioItem(item, mode)].push(item);
  }
  return groups;
}

function timingBucketForPortfolioItem(item: VirtualPortfolioResponse["items"][number], mode: StrategyMode): TimingBucket {
  const executionStatus = `${item.executionStatus ?? ""}`;
  if (executionStatus) {
    if (executionStatus.includes("체결 가능")) return "today";
    if (executionStatus.includes("대기")) return "wait";
    if (executionStatus.includes("기준가") || executionStatus.includes("다음")) return "next";
    return "risk";
  }
  const status = `${item.buyRule ?? ""} ${item.summary ?? ""}`;
  const current = parseMoneyText(item.currentPrice || "");
  const entry = parseMoneyText(item.entry || "");
  const grade = `${item.swingGrade ?? ""}`;
  if (/매수금지|주의|추격|과열|손절|불가/.test(status)) return "risk";
  if (/체결 가능|기준가 아래|진입 가능/.test(status)) return "today";
  if (Number.isFinite(current) && Number.isFinite(entry) && entry > 0) {
    const gap = (current - entry) / entry;
    const todayLimit = mode === "conservative" ? 0.003 : mode === "aggressive" ? 0.025 : 0.01;
    const waitLimit = mode === "conservative" ? 0.025 : mode === "aggressive" ? 0.09 : 0.05;
    if (gap <= todayLimit) return "today";
    if (gap <= waitLimit) return "wait";
    if (gap <= waitLimit * 1.7 && !grade.includes("C")) return "next";
    return "risk";
  }
  if (/대기|눌림|기다/.test(status)) return "wait";
  if (grade.includes("A")) return mode === "aggressive" ? "today" : "wait";
  return "next";
}

function timingBucketForSecurity(item: Security, mode: StrategyMode): TimingBucket {
  const text = `${item.dataStatus ?? ""} ${item.warning ?? ""} ${item.reason ?? ""} ${item.nextAction ?? ""}`;
  if (/매수금지|주의|추격|과열/.test(text)) return "risk";
  if (item.currentPrice && item.entry) {
    const gap = (item.currentPrice - item.entry) / item.entry;
    const todayLimit = mode === "conservative" ? 0.003 : mode === "aggressive" ? 0.025 : 0.01;
    const waitLimit = mode === "conservative" ? 0.025 : mode === "aggressive" ? 0.09 : 0.05;
    if (gap <= todayLimit) return "today";
    if (gap <= waitLimit) return "wait";
    return "next";
  }
  return "wait";
}

function timingLabel(bucket: TimingBucket) {
  if (bucket === "today") return "오늘 진입 가능";
  if (bucket === "wait") return "기다릴 후보";
  if (bucket === "next") return "다음 진입 후보";
  return "매수금지/주의";
}

function timingDescription(bucket: TimingBucket) {
  if (bucket === "today") return "진입 조건 근처";
  if (bucket === "wait") return "진입가 대기";
  if (bucket === "next") return "D+1~D+3 재확인";
  return "신규 진입 제한";
}

function timingActionText(bucket: TimingBucket, item: VirtualPortfolioResponse["items"][number] | null, mode: StrategyMode) {
  const rule = item?.buyRule || (mode === "conservative" ? "기준가 근처 또는 이하" : mode === "aggressive" ? "돌파 유지 또는 짧은 손절" : "기준가 ±1%");
  if (bucket === "today") return `조건 충족 시 진입 · ${rule}`;
  if (bucket === "wait") return `지금 추격보다 진입가 대기 · ${rule}`;
  if (bucket === "next") return `오늘은 무리하지 않고 D+3 안에 재확인 · ${rule}`;
  return "신규 진입 제한 · 보유자는 손절선/익절선만 확인";
}

function opportunityScoreFromPortfolio(item: VirtualPortfolioResponse["items"][number]) {
  const grade = `${item.swingGrade ?? ""}`;
  let score = grade.includes("A") ? 78 : grade.includes("B") ? 66 : 54;
  const profit = Math.abs(parseMoneyText(item.profit || ""));
  const loss = Math.abs(parseMoneyText(item.loss || ""));
  if (profit && loss) score += Math.min(12, (profit / Math.max(loss, 1)) * 3);
  if (/수급|모멘텀|성장|실적|저평가/i.test(`${item.summary ?? ""} ${item.buyRule ?? ""}`)) score += 6;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function entryScoreFromPortfolio(item: VirtualPortfolioResponse["items"][number], mode: StrategyMode) {
  const current = parseMoneyText(item.currentPrice || "");
  const entry = parseMoneyText(item.entry || "");
  let score = mode === "conservative" ? 55 : mode === "aggressive" ? 62 : 60;
  if (Number.isFinite(current) && Number.isFinite(entry) && entry > 0) {
    const gap = Math.abs((current - entry) / entry);
    score += gap <= 0.01 ? 25 : gap <= 0.03 ? 15 : gap <= 0.07 ? 4 : -15;
  }
  if (/체결 가능|기준가 아래/.test(`${item.executionStatus ?? ""}`)) score += 12;
  if (/추격|과열|주의/.test(`${item.executionStatus ?? ""}`)) score -= 20;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function discoveryLabelFromItem(item: VirtualPortfolioResponse["items"][number]) {
  const text = `${item.name ?? ""} ${item.symbol ?? ""} ${item.summary ?? ""} ${item.buyRule ?? ""}`;
  if (/저평가|value|valuation/i.test(text)) return "저평가 성장";
  if (/실적|EPS|earnings|financial/i.test(text)) return "실적 개선";
  if (/수급|flow|거래대금|기관|외국인/i.test(text)) return "수급 포착";
  if (/모멘텀|돌파|테마|AI|우주|반도체|로봇/i.test(text)) return "모멘텀 초기";
  return "신규 발굴";
}

function eventMacroBadgeFromText(text: string) {
  if (/FOMC|CPI|PPI|PCE|고용|금리|파월|환율/i.test(text)) return "매크로 주의";
  if (/IPO|상장|SpaceX|스페이스X|보호예수|락업/i.test(text)) return "이벤트 주의";
  if (/실적발표|분기|잠정실적|컨센서스|EPS/i.test(text)) return "실적 이벤트";
  if (/공시|수주|계약|FDA|임상|증자|CB/i.test(text)) return "공시 이벤트";
  return "";
}

function intradayZoneText(item: IntradayItem) {
  const gap = item.divergencePct;
  const stopText = `${item.stopBreakText ?? ""}`;
  const targetText = `${item.targetHitText ?? ""}`;
  if (stopText.includes("이탈") || stopText.includes("근접")) return "손절 근접";
  if (targetText.includes("도달") || targetText.includes("근접")) return "목표가 근접";
  if (typeof gap === "number" && Number.isFinite(gap)) {
    if (gap >= 8) return "추격 부담";
    if (gap >= -2 && gap <= 3) return "기준가 근처";
    if (gap < -2) return "기준가 아래";
  }
  return item.intradayDecision || "관망";
}

function intradayDecisionText(item: IntradayItem) {
  const zone = intradayZoneText(item);
  const holding = `${item.holdingRisk ?? ""}`;
  if (zone === "손절 근접") return "손절 기준 우선 확인";
  if (zone === "목표가 근접") return "익절 기준 확인";
  if (zone === "추격 부담") return holding.includes("보유") ? "신규매수보다 보유 대응" : "신규매수 추격 주의";
  if (zone === "기준가 근처") return "진입 조건 재확인";
  if (zone === "기준가 아래") return "흐름 확인 후 대기";
  return item.intradayDecision || item.newsRiskStatus || "관망";
}

function priceLevelStatus(item: Security) {
  if (!item.currentPrice || !item.entry) return "기준가 산출 필요";
  const gap = ((item.currentPrice - item.entry) / item.entry) * 100;
  if (gap >= 8) return "추격 부담";
  if (gap >= -2 && gap <= 3) return "기준가 근처";
  if (gap < -2) return "기준가 아래";
  return "관망";
}

function PriceBlock({ item, compact = false, hideMeta = false }: { item: Security; compact?: boolean; hideMeta?: boolean }) {
  return (
    <div>
      <div className={compact ? "font-bold text-white" : "text-base font-black text-white"}>
        {item.currentPriceText || "현재가 없음"}
      </div>
      {!hideMeta ? (
        <div className="mt-1 text-xs leading-5 text-muted">
          {item.priceTime || "기준시각 없음"} · {item.priceSource || "가격출처 없음"}
        </div>
      ) : null}
    </div>
  );
}


function PriceMini({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "warn" }) {
  const color = tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : "text-slate-100";
  return (
    <div className="rounded-lg border border-line bg-card/70 px-3 py-2">
      <div className="text-[11px] font-bold text-muted">{label}</div>
      <div className={`mt-1 truncate text-sm font-black ${color}`} title={value}>{value}</div>
    </div>
  );
}

function rawText(item: Security, aliases: string[]) {
  const raw = item.raw ?? {};
  for (const key of aliases) {
    const value = raw[key];
    if (value !== undefined && value !== null && String(value).trim() && !["-", "없음", "nan", "null", "none"].includes(String(value).trim().toLowerCase())) {
      return String(value).trim();
    }
  }
  return "";
}

function normalizePercent(value?: string | number | null) {
  const text = String(value ?? "").trim();
  if (!text || ["-", "확률 없음", "nan", "null", "none"].includes(text.toLowerCase())) return "확률 없음";
  if (text.includes("%")) return text;
  const num = Number(text.replace(/,/g, ""));
  if (!Number.isFinite(num)) return text;
  const pct = Math.abs(num) <= 1 ? num * 100 : num;
  return `${pct.toFixed(pct % 1 === 0 ? 0 : 1)}%`;
}

function probabilityText(item: Security, horizon: "1" | "3" | "5" | "20" | "short" | "swing" | "mid") {
  const direct = horizon === "short" ? item.probShort : horizon === "swing" ? item.probSwing : horizon === "mid" ? item.probMid : horizon === "1" ? item.prob1d : horizon === "3" ? item.prob3d : horizon === "20" ? item.prob20d : item.prob5d;
  const key = horizon === "short" ? "1" : horizon === "swing" ? "5" : horizon === "mid" ? "20" : horizon;
  const raw = rawText(item, [
    `${key}일상승확률`,
    `prob_up_${key}d`,
    `prob${key}d`,
    `${key}d_probability`,
    `probability_${key}d`,
    `${key}일 확률`
  ]);
  return normalizePercent(direct ?? raw);
}

function expectedPriceText(item: Security, horizon: "1" | "3" | "5" | "20" | "short" | "swing" | "mid") {
  const direct = horizon === "short" ? item.expectedPriceShortText : horizon === "swing" ? item.expectedPriceSwingText : horizon === "mid" ? item.expectedPriceMidText : horizon === "1" ? item.expectedPrice1dText : horizon === "3" ? item.expectedPrice3dText : horizon === "20" ? item.expectedPrice20dText : item.expectedPrice5dText;
  const key = horizon === "short" ? "1" : horizon === "swing" ? "5" : horizon === "mid" ? "20" : horizon;
  if (direct && !direct.includes("없음")) return direct;
  const raw = rawText(item, [
    `${key}일예상가`,
    `${key}일 예상가`,
    `예상가_${key}일`,
    `expected_price_${key}d`,
    `pred_price_${key}d`,
    `predicted_price_${key}d`,
    `price_${key}d`,
    `target_price_${key}d`
  ]);
  const num = Number(String(raw).replace(/,/g, "").replace(/[$원]/g, ""));
  if (Number.isFinite(num) && num > 0) return money(num, item.market);
  return "예상가 산출 필요";
}

function probabilityCell(item: Security, horizon: "1" | "3" | "5" | "20" | "short" | "swing" | "mid") {
  return (
    <div>
      <div className="font-black text-white">{probabilityText(item, horizon)}</div>
      <div className="mt-1 text-xs text-muted">{expectedPriceText(item, horizon)}</div>
    </div>
  );
}

function predictionLine(item: Security) {
  return `단기 ${probabilityText(item, "short")} / ${expectedPriceText(item, "short")} · 스윙 ${probabilityText(item, "swing")} / ${expectedPriceText(item, "swing")} · 중기 ${probabilityText(item, "mid")} / ${expectedPriceText(item, "mid")}`;
}

function formatRiskReward(value?: string | number | null) {
  const text = String(value ?? "").trim();
  if (!text || text.includes("없음")) return "손익비 없음";
  const num = Number(text.replace(/,/g, "").replace(/[^0-9.+-]/g, ""));
  if (Number.isFinite(num) && num > 0) return `1:${num.toFixed(2)}`;
  return text;
}

function formatRiskRewardFromPrices(item: Security) {
  if (!item.entry || !item.stop || !item.target) return "손익비 산출 필요";
  const risk = Math.abs(item.entry - item.stop);
  const reward = Math.abs(item.target - item.entry);
  if (!risk || !reward) return "손익비 산출 필요";
  return `손익비 1:${(reward / risk).toFixed(2)}`;
}



function formatNumber(value: unknown, missing = "-") {
  const num = Number(value);
  if (!Number.isFinite(num)) return missing;
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function tradePlanLine(item: Security, mode: StrategyMode = "balanced") {
  const plan = item.virtualPlans?.[mode];
  if (plan?.summary && !plan.summary.includes("산출 필요")) {
    return `${item.swingGrade || "스윙 C군"} · ${plan.summary} · 운용수익률 ${plan.accountLossPctText ?? "-"} / ${plan.accountProfitPctText ?? "-"}`;
  }
  const entry = item.entry ?? item.currentPrice ?? null;
  if (!entry || !item.stop || !item.target) return "예상 매수가 기준 손실/이익 산출 필요";
  const lossPct = ((item.stop - entry) / entry) * 100;
  const profitPct = ((item.target - entry) / entry) * 100;
  const lossMoney = item.stop - entry;
  const profitMoney = item.target - entry;
  const defaultCapital = item.market === "us" ? 1000 : 1000000;
  const qty = Math.max(1, Math.floor(defaultCapital / entry));
  const capitalText = item.market === "us" ? "$1,000" : "100만원";
  const lossTotal = lossMoney * qty;
  const profitTotal = profitMoney * qty;
  return `${item.swingGrade || "스윙 C군"} · 예상 매수가 ${money(entry, item.market)} 기준 · 1주 손실 ${lossPct.toFixed(1)}% (${money(lossMoney, item.market)}) · 1주 이익 +${profitPct.toFixed(1)}% (${money(profitMoney, item.market)}) · ${capitalText} 기준 ${qty.toLocaleString()}주 / 손실 ${money(lossTotal, item.market)} / 이익 ${money(profitTotal, item.market)}`;
}

function gapText(item: Security) {
  if (!item.currentPrice || !item.entry) return "기준가 산출 필요";
  const gap = ((item.currentPrice - item.entry) / item.entry) * 100;
  return `기준가 대비 ${gap >= 0 ? "+" : ""}${gap.toFixed(1)}%`;
}

function hasUsablePriceLevel(text?: string, value?: number | null) {
  if (value && value > 0) return true;
  const raw = String(text ?? "");
  return Boolean(raw && !raw.includes("없음") && !raw.includes("산출 필요"));
}

function shortRiskText(text?: string) {
  const value = String(text ?? "").trim();
  if (!value || value.includes("없음")) return "관망";
  if (value.includes("손절")) return "손절 기준 확인";
  if (value.includes("과열")) return "과열";
  if (value.includes("관망")) return "관망";
  if (value.includes("뉴스")) return "뉴스 확인";
  return value.length > 18 ? `${value.slice(0, 18)}...` : value;
}

function isClosingVerifiable(row: ClosingItem) {
  const text = `${row.directionHit} ${row.rangeHit} ${row.entryTouched} ${row.stopTakeProfit} ${row.failureReason}`;
  return !/검증 데이터 부족|데이터 부족|부족|대기/.test(text);
}

function compactClosingReason(text: string) {
  if (!text) return "사유 없음";
  if (text.includes("검증 데이터 부족")) return "검증 데이터 부족";
  if (text.includes("시초")) return "시초 데이터 부족";
  if (text.includes("종가")) return "종가 데이터 부족";
  if (text.includes("손절")) return "손절 데이터 부족";
  if (text.includes("익절")) return "익절 데이터 부족";
  return text;
}

function holdingStatusText(item: Security) {
  if ((item.returnPct ?? 0) > 5) return "익절 검토";
  if ((item.returnPct ?? 0) > 0) return "보유 유지";
  if ((item.returnPct ?? 0) < -5) return "손실 관리";
  return "관망";
}

function holdingRiskText(item: Security) {
  if (!item.currentPrice || !item.stop) return "가격 기준 부족";
  const stopGap = ((item.currentPrice - item.stop) / item.currentPrice) * 100;
  if (stopGap <= 3) return "손절가 근접";
  if (item.target) {
    const targetGap = ((item.target - item.currentPrice) / item.currentPrice) * 100;
    if (targetGap <= 3 && targetGap >= -3) return "목표가 근접";
  }
  return "특별 리스크 없음";
}


function GainText({ value, text }: { value?: number | null; text?: string }) {
  const tone = (value ?? 0) < 0 ? "text-warn" : (value ?? 0) > 0 ? "text-good" : "text-slate-300";
  return <span className={`font-black ${tone}`}>{text || "평가 데이터 없음"}</span>;
}

function HorizonSelector({ value, onChange }: { value: DecisionHorizon; onChange: (value: DecisionHorizon) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {(["short", "swing", "mid"] as DecisionHorizon[]).map((horizon) => (
        <button
          key={horizon}
          type="button"
          onClick={() => onChange(horizon)}
          className={`rounded-full border px-3 py-1 text-xs font-black transition ${value === horizon ? "border-accent bg-accent text-ink" : "border-line bg-panel text-slate-300 hover:border-accent/50"}`}
        >
          {HORIZON_LABEL[horizon]}
        </button>
      ))}
    </div>
  );
}

function LongText({ text }: { text: string }) {
  return <span className="block max-w-[280px] truncate text-sm text-slate-300" title={text}>{text || "내용 없음"}</span>;
}

function DecisionPill({ text }: { text: string }) {
  const tone =
    text === "손절 주의"
      ? "bg-warn/15 text-warn"
      : text === "익절 검토" || text === "진입 가능"
        ? "bg-good/15 text-good"
        : "bg-white/5 text-slate-300";
  return <span className={`rounded-full px-2 py-1 text-xs font-black ${tone}`}>{text || "판단 없음"}</span>;
}

function StatusPill({ status }: { status: string }) {
  const ok = status === "OK";
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-black ${ok ? "bg-good/15 text-good" : "bg-warn/15 text-warn"}`}>
      {status}
    </span>
  );
}

function SymbolDetailCard({
  item,
  mode = "balanced",
  newsItems = [],
  disclosures = [],
  companyItems = []
}: {
  item: Security;
  mode?: StrategyMode;
  newsItems?: NewsItem[];
  disclosures?: DisclosureItem[];
  companyItems?: CompanyAnalysisItem[];
}) {
  const relatedNews = relatedRecords(newsItems, item).slice(0, 5);
  const relatedDisclosures = relatedRecords(disclosures, item).slice(0, 5);
  const company = relatedRecords(companyItems, item)[0] as CompanyAnalysisItem | undefined;
  const raw = (company?.raw ?? item.raw ?? {}) as Record<string, unknown>;
  const valueOf = (keys: string[], fallback = "데이터 연결 대기") => firstDisplayValue(raw, keys, fallback);

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr]">
        <div className="rounded-lg border border-line bg-card p-4">
          <div className="text-sm text-muted">
            {item.marketLabel} · {item.symbol}
          </div>
          <div className="mt-1 text-2xl font-black text-white">{item.name}</div>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <StatCard label="현재가" value={item.currentPriceText} note={`${item.priceTime} · ${item.priceSource}`} tone="accent" />
            <StatCard label="기준가" value={item.entryText || money(item.entry, item.market)} />
            <StatCard label="손절 / 목표" value={`${item.stopText || money(item.stop, item.market)} / ${item.targetText || money(item.target, item.market)}`} tone="warn" />
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <StatCard label="예상 시초가" value={item.expectedOpenText || valueOf(["예상시초가", "expected_open", "open_expected"], "산출 필요")} />
            <StatCard label="예상 종가" value={item.expectedCloseText || valueOf(["예상종가", "expected_close", "close_expected"], "산출 필요")} />
            <StatCard label="추천 성향" value={STRATEGY_MODE_LABEL[mode]} note={item.recommendationModeText || "모드별 점수 반영"} tone="good" />
          </div>
          <div className="mt-3 rounded-lg border border-line bg-panel p-3 text-sm leading-6 text-slate-200">
            <div className="font-black text-white">예측 · 가상 운용</div>
            <div className="mt-1">{predictionLine(item)}</div>
            <div className="mt-1">{tradePlanLine(item, mode)}</div>
          </div>
        </div>
        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="text-sm font-black text-white">데이터 신뢰도 / 상태</div>
          <p className="mt-2 text-sm leading-6 text-slate-300">{item.dataStatus || company?.dataStatus || "상태 없음"}</p>
          <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-muted">
            <span>수급: {company?.supply || item.scores?.supply || "수급 데이터 없음"}</span>
            <span>실적: {company?.earnings || item.scores?.earnings || "재무 데이터 없음"}</span>
            <span>밸류: {company?.valuation || item.scores?.valuation || "재무 데이터 없음"}</span>
            <span>차트: {company?.chart || item.scores?.chart || "차트 데이터 부족"}</span>
          </div>
        </div>
      </div>

      <Section title="종목 뉴스">
        {relatedNews.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {relatedNews.map((row, idx) => (
              <a key={idx} href={row.url || undefined} target="_blank" className="rounded-lg border border-line bg-card p-4 hover:border-accent/50">
                <div className="text-xs text-muted">[{newsTag(row)}] {row.sourceName || "뉴스"} · {row.publishedAt || "일자 없음"}</div>
                <div className="mt-2 font-black text-white">{row.title || "제목 없음"}</div>
                <p className="mt-2 text-sm leading-6 text-slate-300">{row.summary || "요약 없음"}</p>
              </a>
            ))}
          </div>
        ) : (
          <EmptyReason text="이 종목과 직접 매칭된 뉴스가 없습니다. 첫 화면은 시장·섹터 뉴스 중심으로 유지합니다." />
        )}
      </Section>

      <Section title="공시 / IR">
        {relatedDisclosures.length ? (
          <DataTable
            rows={relatedDisclosures}
            columns={[
              { key: "title", header: "공시/IR", render: (row) => <LongText text={row.title || "제목 없음"} /> },
              { key: "date", header: "일자", render: (row) => row.date || "일자 없음" },
              { key: "sourceName", header: "출처", render: (row) => row.sourceName || "출처 없음" },
              { key: "url", header: "링크", render: (row) => row.url ? <a className="text-accent" href={row.url} target="_blank">열기</a> : "링크 없음" }
            ]}
          />
        ) : (
          <EmptyReason text="공시/IR CSV가 아직 없거나 이 종목과 매칭되지 않았습니다." />
        )}
      </Section>

      <Section title="기업분석 상세">
        <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-4">
          <MiniMetric label="EPS" value={company?.eps || valueOf(["EPS", "eps", "주당순이익"])} />
          <MiniMetric label="PER" value={company?.per || valueOf(["PER", "per"])} />
          <MiniMetric label="PBR" value={company?.pbr || valueOf(["PBR", "pbr"])} />
          <MiniMetric label="ROE" value={company?.roe || valueOf(["ROE", "roe"])} />
          <MiniMetric label="매출" value={company?.revenue || valueOf(["매출", "매출액", "revenue", "sales"])} />
          <MiniMetric label="영업이익" value={company?.operatingIncome || valueOf(["영업이익", "operating_income", "op_income"])} />
          <MiniMetric label="순이익" value={company?.netIncome || valueOf(["순이익", "net_income", "당기순이익"])} />
          <MiniMetric label="부채비율" value={valueOf(["부채비율", "debt_ratio"])} />
          <MiniMetric label="연간실적" value={company?.annualPerformance || valueOf(["연간실적", "annual_result", "annual_performance"])} />
          <MiniMetric label="분기실적" value={company?.quarterlyPerformance || valueOf(["분기실적", "quarter_result", "quarterly_performance"])} />
          <MiniMetric label="ESG" value={company?.esg || valueOf(["ESG", "esg", "ESG등급"])} />
          <MiniMetric label="리서치" value={company?.research || valueOf(["리서치", "research", "report", "투자의견"])} />
        </div>
      </Section>
    </div>
  );
}



function buildModeSummaryFromPortfolio(portfolio: VirtualPortfolioResponse, mode: StrategyMode) {
  const rules: Record<StrategyMode, string> = {
    conservative: "스윙 A군·기준가 근처·손절 방어 우선",
    balanced: "스윙 A/B군·손익비와 체결 가능성 균형",
    aggressive: "A/B/C군·모멘텀 허용, 단 손절/목표 필수"
  };
  const top = portfolio.items?.[0];
  return {
    count: portfolio.count ?? portfolio.items?.length ?? 0,
    topName: top ? `${top.name || top.symbol} (${top.symbol})` : "후보 없음",
    lossText: portfolio.lossTotal || "-",
    profitText: portfolio.profitTotal || "-",
    rule: rules[mode]
  };
}

function portfolioItemToSecurity(item: VirtualPortfolioResponse["items"][number], market: Market, mode: StrategyMode = "balanced"): Security {
  return {
    symbol: item.symbol,
    name: item.name,
    market,
    marketLabel: market === "kr" ? "국장" : "미장",
    currentPrice: parseMoneyText(item.currentPrice || ""),
    currentPriceText: item.currentPrice || "현재가 없음",
    priceTime: "조건부 가상운용 계획",
    priceSource: "StockApp bridge",
    dataStatus: item.executionStatus || "가상 운용 후보",
    entry: parseMoneyText(item.entry || ""),
    entryText: item.entry || "예상매수가 산출 필요",
    swingGrade: item.swingGrade,
    recommendationModeText: item.modeLabel,
    recommendationModes: [item.mode || mode],
    virtualPlans: {
      [item.mode || mode]: {
        mode: item.mode || mode,
        modeLabel: item.modeLabel || STRATEGY_MODE_LABEL[mode],
        status: item.executionStatus,
        entryText: item.entry,
        sharesText: item.shares,
        investedText: item.invested,
        lossTotalText: item.loss,
        profitTotalText: item.profit,
        accountLossPctText: item.accountLossPct,
        accountProfitPctText: item.accountProfitPct,
        buyRule: item.buyRule,
        holdDays: item.holdDays
      }
    },
    raw: item as unknown as Record<string, unknown>
  };
}

function buildModeSummary(items: Security[], mode: StrategyMode, market: Market) {
  const maxPositions = mode === "conservative" ? 3 : mode === "aggressive" ? 8 : 5;
  const picked = pickForMode(items, mode, maxPositions);
  const capitalPerPosition = market === "us" ? 1000 : 1000000;
  const totalCapital = capitalPerPosition * maxPositions;
  let lossTotal = 0;
  let profitTotal = 0;
  for (const item of picked) {
    const plan = item.virtualPlans?.[mode];
    const rawLoss = plan?.lossTotalText ?? "";
    const rawProfit = plan?.profitTotalText ?? "";
    const loss = parseMoneyText(rawLoss);
    const profit = parseMoneyText(rawProfit);
    if (Number.isFinite(loss)) lossTotal += loss;
    else if (item.entry && item.stop) lossTotal += (item.stop - item.entry) * Math.max(1, Math.floor(capitalPerPosition / item.entry));
    if (Number.isFinite(profit)) profitTotal += profit;
    else if (item.entry && item.target) profitTotal += (item.target - item.entry) * Math.max(1, Math.floor(capitalPerPosition / item.entry));
  }
  const lossPct = totalCapital ? (lossTotal / totalCapital) * 100 : 0;
  const profitPct = totalCapital ? (profitTotal / totalCapital) * 100 : 0;
  const rules: Record<StrategyMode, string> = {
    conservative: "스윙 A군·기준가 근처·손절 방어 우선",
    balanced: "스윙 A/B군·손익비와 체결 가능성 균형",
    aggressive: "A/B/C군·모멘텀 허용, 단 손절/목표 필수"
  };
  return {
    count: picked.length,
    topName: picked[0] ? `${picked[0].name || picked[0].symbol} (${picked[0].symbol})` : "후보 없음",
    lossText: `${formatSignedMoneyForMarket(lossTotal, market)} · ${formatSignedPercent(lossPct)}`,
    profitText: `${formatSignedMoneyForMarket(profitTotal, market)} · ${formatSignedPercent(profitPct)}`,
    rule: rules[mode]
  };
}

function parseMoneyText(text: string) {
  const cleaned = String(text || "").replace(/[$,원\s]/g, "");
  const num = Number(cleaned.replace(/[^0-9.+-]/g, ""));
  return Number.isFinite(num) ? num : NaN;
}

function formatSignedMoneyForMarket(value: number, market: Market) {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (market === "us") return `${sign}$${abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `${sign}${Math.trunc(abs).toLocaleString()}원`;
}

function formatSignedPercent(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function relatedRecords<T extends { symbol?: string; name?: string; title?: string; summary?: string; raw?: Record<string, unknown> }>(items: T[], item: Security) {
  const symbol = normalizeComparable(item.symbol);
  const name = normalizeComparable(item.name);
  return items.filter((row) => {
    const rowSymbol = normalizeComparable(row.symbol || String(row.raw?.["종목코드"] ?? row.raw?.["ticker"] ?? ""));
    const rowName = normalizeComparable(row.name || String(row.raw?.["종목명"] ?? row.raw?.["corp_name"] ?? row.raw?.["company"] ?? ""));
    const text = normalizeComparable(`${row.title ?? ""} ${row.summary ?? ""}`);
    return Boolean((symbol && rowSymbol === symbol) || (name && rowName.includes(name)) || (name && text.includes(name)));
  });
}

function normalizeComparable(value?: string) {
  return String(value ?? "").replace(/[()\s]/g, "").toLowerCase();
}

function firstDisplayValue(raw: Record<string, unknown>, keys: string[], fallback: string) {
  for (const key of keys) {
    const value = raw[key];
    if (value !== undefined && value !== null) {
      const text = String(value).trim();
      if (text && !["-", "nan", "none", "null", "없음"].includes(text.toLowerCase())) return text;
    }
  }
  return fallback;
}

type SimpleValue = string | number | boolean | null | undefined;

function MiniMetric({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "neutral" | "good" | "warn" }) {
  const color = tone === "good" ? "text-good" : tone === "warn" ? "text-warn" : "text-white";
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <div className="text-xs font-bold text-muted">{label}</div>
      <div className={`mt-1 text-lg font-black ${color}`}>{value}</div>
    </div>
  );
}

function Badge({ text, tone = "neutral" }: { text: string; tone?: "neutral" | "good" | "warn" }) {
  const cls = tone === "good" ? "border-good/30 bg-good/10 text-good" : tone === "warn" ? "border-warn/30 bg-warn/10 text-warn" : "border-line bg-white/5 text-slate-200";
  return <span className={`rounded-full border px-2 py-1 text-[11px] font-black ${cls}`}>{text}</span>;
}

function InfoBox({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-4 shadow-soft">
      <div className="text-sm font-black text-white">{title}</div>
      <ul className="mt-2 space-y-1 text-xs leading-5 text-muted">
        {lines.map((line, idx) => <li key={`${title}-${idx}`}>· {line}</li>)}
      </ul>
    </div>
  );
}

function FormInput({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-bold text-muted">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm text-white outline-none focus:border-accent"
      />
    </label>
  );
}

function WriteStatus({ text }: { text: string }) {
  if (!text) return null;
  const isError = text.toLowerCase().includes("error") || text.includes("실패");
  return (
    <div className={`mb-4 rounded-lg border px-4 py-3 text-sm font-bold ${isError ? "border-warn/40 bg-warn/10 text-warn" : "border-accent/35 bg-accent/10 text-accent"}`}>
      {text}
    </div>
  );
}

function CorrelationHeatmap({ matrix }: { matrix: Record<string, SimpleValue>[] }) {
  const assets = Object.keys(matrix[0] ?? {}).filter((key) => key !== "asset");
  const tone = (value: SimpleValue) => {
    const corr = Number(value);
    if (!Number.isFinite(corr)) return "bg-white/5 text-muted";
    if (corr >= 0.8) return "bg-danger/25 text-danger";
    if (corr >= 0.5) return "bg-warn/20 text-warn";
    if (corr >= 0.2) return "bg-accent/16 text-accent";
    return "bg-good/16 text-good";
  };

  if (!assets.length) return <EmptyReason text="상관관계 계산 데이터 부족" />;

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel">
      <div className="scrollbar-thin overflow-x-auto">
        <table className="w-full min-w-[620px] border-collapse text-sm">
          <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="border-b border-line px-3 py-2 text-left">자산</th>
              {assets.map((asset) => (
                <th key={asset} className="border-b border-line px-3 py-2 text-center">
                  {asset}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row) => (
              <tr key={String(row.asset ?? "")}>
                <td className="border-b border-line px-3 py-2 font-bold text-white">{String(row.asset ?? "자산 없음")}</td>
                {assets.map((asset) => (
                  <td key={asset} className="border-b border-line px-2 py-2 text-center">
                    <span className={`inline-flex min-w-16 justify-center rounded-md px-2 py-1 text-xs font-black ${tone(row[asset])}`}>
                      {Number.isFinite(Number(row[asset])) ? Number(row[asset]).toFixed(3) : "부족"}
                    </span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SimpleRecords({ rows, empty }: { rows: Record<string, SimpleValue>[]; empty: string }) {
  if (!rows.length) return <EmptyReason text={empty} />;
  const keys = Object.keys(rows[0] ?? {}).slice(0, 5);
  return (
    <DataTable<Record<string, SimpleValue>>
      rows={rows}
      columns={keys.map((key) => ({
        key,
        header: key,
        render: (row) => String(row[key] ?? "데이터 없음")
      }))}
    />
  );
}

function FileStatusTable({ rows }: { rows: FileItem[] }) {
  return (
    <Section title="필수 파일 상태">
      <DataTable
        rows={rows}
        columns={[
          { key: "path", header: "파일", render: (row) => row.path },
          { key: "status", header: "상태", render: (row) => <StatusPill status={row.status} /> },
          { key: "rows", header: "rows", render: (row) => row.rows },
          { key: "updated", header: "수정시각", render: (row) => row.updatedAt || "기준시각 없음" }
        ]}
      />
    </Section>
  );
}

function DataSourceStatus({ rows }: { rows: DataSourceItem[] }) {
  return (
    <>
      <div className="grid gap-3 md:grid-cols-4">
        {rows.map((row) => (
          <StatCard
            key={row.key}
            label={row.name}
            value={row.status}
            note={`${row.files} files · ${row.rows} rows`}
            tone={row.status === "OK" ? "good" : "warn"}
          />
        ))}
      </div>
      <Section title="CSV 데이터 소스 연결 상태">
        <DataTable
          rows={rows}
          columns={[
            { key: "name", header: "구분", render: (row) => <b>{row.name}</b> },
            { key: "status", header: "상태", render: (row) => <StatusPill status={row.status} /> },
            { key: "files", header: "파일", render: (row) => row.files },
            { key: "rows", header: "rows", render: (row) => row.rows },
            { key: "target", header: "연결 화면", render: (row) => row.target },
            { key: "updated", header: "최근 수정", render: (row) => row.latestUpdatedAt || "기준시각 없음" },
            { key: "message", header: "상태 설명", render: (row) => <LongText text={row.message} /> }
          ]}
        />
      </Section>
      <Section title="감지된 파일 예시">
        <SimpleRecords
          rows={rows.map((row) => ({ 구분: row.name, 예시: row.examples.join(" · ") || "감지 파일 없음" }))}
          empty="데이터 소스 파일 없음"
        />
      </Section>
    </>
  );
}

function AutomationStatus({ automation, updatedAt, github }: { automation?: Record<string, unknown>; updatedAt: string; github: GitHubActionsStatus }) {
  const hasStatus = automation && Object.keys(automation).length > 0;
  const githubRows = [
    { 항목: "연결 상태", 값: github.status || "미확인" },
    { 항목: "repo", 값: github.repo || "repo 없음" },
    { 항목: "설명", 값: github.message || "설명 없음" },
    { 항목: "최근 Scheduled", 값: github.latestScheduled ? `${github.latestScheduled.name ?? "workflow"} · ${github.latestScheduled.conclusion ?? github.latestScheduled.status ?? "상태 없음"} · ${github.latestScheduled.updated_at ?? "시간 없음"}` : "Scheduled 실행 기록 없음" }
  ];
  const localRows = hasStatus
    ? Object.entries(automation as Record<string, unknown>).map(([key, value]) => ({ 항목: key, 값: typeof value === "object" ? JSON.stringify(value) : String(value ?? "") }))
    : [{ 항목: "로컬 상태 파일", 값: "감지 없음" }, { 항목: "마지막 데이터 기준시각", 값: updatedAt }];
  return (
    <>
      <div className="grid gap-3 md:grid-cols-3">
        <StatCard label="GitHub 연결" value={github.status === "OK" ? "연결됨" : github.status || "미확인"} note={github.message} tone={github.status === "OK" ? "good" : "warn"} />
        <StatCard label="Workflow" value={github.workflows?.length ?? 0} note="GitHub Actions API 기준" />
        <StatCard label="최근 데이터" value={updatedAt} note="앱 데이터 기준시각" />
      </div>
      <Section title="GitHub Actions 상태">
        <SimpleRecords rows={githubRows} empty="GitHub Actions 상태 데이터 없음" />
      </Section>
      <Section title="최근 실행 기록">
        <SimpleRecords rows={(github.runs ?? []).slice(0, 8)} empty="실행 기록 없음" />
      </Section>
      <Section title="로컬 자동화 상태 파일">
        <SimpleRecords rows={localRows} empty="로컬 자동화 상태 데이터 없음" />
      </Section>
    </>
  );
}

function ApiStatus({ env }: { env: EnvItem[] }) {
  const ok = env.filter((item) => item.status === "OK").length;
  const missing = env.filter((item) => item.status === "MISSING").length;
  const chart = [
    { name: "OK", value: ok },
    { name: "MISSING", value: missing }
  ];

  return (
    <>
      <div className="grid gap-3 md:grid-cols-3">
        <StatCard label="API OK" value={ok} tone="good" />
        <StatCard label="API MISSING" value={missing} tone={missing ? "warn" : "good"} />
        <StatCard label="Backend" value="OK" note={API_BASE} tone="accent" />
      </div>
      <Section title="환경 변수 상태">
        <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
          <DataTable
            rows={env}
            columns={[
              { key: "key", header: "키", render: (row) => row.key },
              { key: "status", header: "상태", render: (row) => <StatusPill status={row.status} /> }
            ]}
          />
          <div className="h-64 rounded-lg border border-line bg-panel p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chart}>
                <CartesianGrid stroke="rgba(148,163,184,.16)" />
                <XAxis dataKey="name" stroke="#94a3b8" />
                <YAxis allowDecimals={false} stroke="#94a3b8" />
                <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid rgba(148,163,184,.25)" }} />
                <Bar dataKey="value" fill="#38bdf8" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </Section>
    </>
  );
}

function HistoryTable({ title, history }: { title: string; history: HistoryResponse }) {
  const rows = history.items.slice(0, 100);
  const keys = Object.keys(rows[0] ?? {}).slice(0, 8);
  return (
    <>
      <div className="grid gap-3 md:grid-cols-2">
        <StatCard label={title} value={history.count} note={history.source} tone="accent" />
        <StatCard label="표시 범위" value={rows.length} note="최대 100 rows 미리보기" />
      </div>
      <Section title={title}>
        {rows.length ? (
          <DataTable<Record<string, string>>
            rows={rows}
            columns={keys.map((key) => ({ key, header: key, render: (row) => String(row[key] ?? "-") }))}
          />
        ) : (
          <EmptyReason text="기록 데이터 없음" />
        )}
      </Section>
    </>
  );
}

function ComingSoon({ title }: { title: string }) {
  return (
    <div className="rounded-lg border border-line bg-card p-8">
      <div className="text-sm font-bold text-accent">준비 중</div>
      <h2 className="mt-2 text-2xl font-black text-white">{title}</h2>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">
        메뉴는 유지했습니다. 기존 Streamlit 기능과 reports 산출물 연결을 확인한 뒤 실제 화면으로 확장합니다.
      </p>
    </div>
  );
}
