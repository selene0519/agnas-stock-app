export type DataStatus = "NORMAL" | "PARTIAL" | "STALE" | "NO_DATA" | "ERROR";
export type Market = "KR" | "US" | "kr" | "us" | "all";
export type Mode = "conservative" | "balanced" | "aggressive" | "all";
export type Horizon = "short" | "swing" | "mid" | "long" | "all";

export type PriceSession =
  | "kr_premarket"
  | "kr_intraday"
  | "kr_after_close"
  | "kr_closed"
  | "kr_closed_weekend"
  | "kr_closed_holiday"
  | "us_premarket"
  | "us_intraday"
  | "us_after_close"
  | "us_closed"
  | "us_closed_weekend"
  | "us_closed_holiday"
  | "UNKNOWN";

export type RecommendMode = "보수" | "균형" | "공격" | "conservative" | "balanced" | "aggressive";
export type InvestPeriod = "단기" | "스윙" | "중기" | "장기" | "short" | "swing" | "mid" | "long";
export type RiskLevel = "안전" | "주의" | "위험" | "손절필요" | "LOW" | "WATCH" | "HIGH";
export type HoldingJudgment = "보유 유지" | "일부 익절" | "손절 근접" | "손절 실행 필요" | "추가 매수 금지" | "관망";

export interface PatternStrategy {
  status?: string;
  action?: string;
  riskStatus?: string;
  confidence?: number;
  primaryPattern?: string;
  secondaryPatterns?: string[];
  marketStructure?: string;
  trendPhase?: string;
  historicalSupportLevels?: number[];
  isBlocked?: boolean;
  message?: string;
}

export interface StockCandidate {
  id: string;
  symbol: string;
  name: string;
  market: Market;
  currentPrice: number | null;
  basePrice: number | null;
  entryPrice: number | null;
  stopLoss: number | null;
  targetPrice: number | null;
  rrRatio: number | null;
  probShort: number | null;
  probSwing: number | null;
  probMid: number | null;
  expectedPrice: number | null;
  mode: RecommendMode;
  period: InvestPeriod;
  dataStatus: DataStatus;
  priceSession: PriceSession;
  priceSource: string;
  priceSourceDate: string;
  warnings: string[];
  isBanned: boolean;
  banReason: string | null;
  change: number | null;
  volume: number | null;
  sector: string | null;
  updatedAt: string;
  patternStrategy?: PatternStrategy;
}

export interface Holding {
  id: string;
  symbol: string;
  name: string;
  market: Market;
  buyPrice: number;
  qty: number;
  currentPrice: number | null;
  stopLoss: number;
  targetPrice: number;
  riskLevel: RiskLevel;
  pnlPct: number | null;
  judgment: HoldingJudgment;
  buyDate: string;
  memo: string;
}

export interface VirtualTrade {
  id: string;
  date: string;
  symbol: string;
  name: string;
  market: Market;
  entryPrice: number;
  actualHigh: number | null;
  actualLow: number | null;
  actualClose: number | null;
  entryReached: boolean;
  virtualFilled: boolean;
  stopLossHit: boolean;
  targetHit: boolean;
  virtualPnlPct: number | null;
  failReason: string | null;
  mode: RecommendMode;
}

export interface PreMarketReport {
  date: string;
  market: Market;
  candidates: StockCandidate[];
  macroWarnings: string[];
  dataStatus: DataStatus;
  generatedAt: string;
}

export interface PostMarketVerification {
  predictionDate: string;
  resultDate: string;
  symbol: string;
  name: string;
  predictedDir: "상승" | "하락" | "보합";
  actualResult: "성공" | "실패" | "부분";
  stopLossMatch: boolean;
  targetMatch: boolean;
  entryReached: boolean;
  failReason: string | null;
  needsCorrection: boolean;
}

export interface NewsItem {
  id: string;
  title: string;
  summary: string;
  source: string;
  publishedAt: string;
  tags: string[];
  symbol: string | null;
  url: string;
  isWarning: boolean;
}

export interface DisclosureItem {
  id: string;
  company: string;
  symbol: string;
  market: Market;
  title: string;
  disclosedAt: string;
  source: "DART" | "SEC" | "Finnhub" | string;
  url: string;
  isWarning: boolean;
}

export interface FundamentalData {
  symbol: string;
  name: string;
  market: Market;
  eps: number | null;
  per: number | null;
  pbr: number | null;
  revenue: number | null;
  operatingProfit: number | null;
  netProfit: number | null;
  debtRatio: number | null;
  supplyScore: number | null;
  dataStatus: DataStatus;
  missingReasons: Record<string, string>;
  updatedAt: string;
}

export interface MarketSummary {
  date: string;
  market?: Market;
  tradableCount?: number;
  waitingCount?: number;
  virtualFilledCount?: number;
  macroWarningCount?: number;
  overallDataStatus: DataStatus;
  topCandidates?: StockCandidate[];
  topSignals?: StockCandidate[];
  warnings?: string[];
  virtualOpSummary?: { totalTrades: number; successRate: number; avgPnl: number };
  latestNews?: NewsItem[];
  priceSession: PriceSession | { kr: PriceSession; us: PriceSession };
  automationStatus?: "OK" | "WARN" | "ERROR";
  lastUpdated: string;
}

export interface AutomationStatus {
  githubActionsOk: boolean;
  csvGenerated: boolean;
  csvInMain: boolean;
  backendRead: boolean;
  frontendReflected: boolean;
  lastRunAt: string;
  nextRunAt: string;
  errors: string[];
}

export interface DataSourceStatus {
  name: string;
  type: "KIS" | "DART" | "SEC" | "Finnhub" | "GNews" | "OHLCV" | "Manual" | string;
  status: DataStatus;
  lastUpdated: string;
  recordCount: number;
  message: string;
}

export interface WatchItem {
  symbol: string;
  name: string;
  market: Market;
  memo: string;
  addedAt: string;
  inCandidatePool: boolean;
  currentPrice: number | null;
  basePrice: number | null;
  stopLoss: number | null;
  targetPrice: number | null;
}
