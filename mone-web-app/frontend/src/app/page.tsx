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
import { firstSubPage, NAV_GROUPS, Sidebar } from "@/components/Sidebar";
import { API_BASE, deleteJson, getJson, money, patchJson, postJson, type ApiList, type Market, type Security } from "@/lib/api";

type FileItem = {
  path: string;
  exists: boolean;
  status: "OK" | "MISSING";
  bytes: number;
  rows: number;
  updatedAt: string;
};

type EnvItem = { key: string; status: "OK" | "MISSING" };

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

type MarketSummary = {
  market: Market;
  marketLabel: string;
  cards: Record<string, string>[];
  dataStatus: Record<string, string>[];
  dashboard: Record<string, string>[];
  sources: string[];
  updatedAt: string;
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

const sourceLabel = (source?: string) => source || "소스 없음";

export default function Home() {
  const [activeCategory, setActiveCategory] = useState("시장 홈");
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
  const [predictionHistory, setPredictionHistory] = useState<HistoryResponse>({ count: 0, source: "", items: [] });
  const [outcomeHistory, setOutcomeHistory] = useState<HistoryResponse>({ count: 0, source: "", items: [] });
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
      try {
        const [
          summaryData,
          symbolData,
          positionData,
          newsData,
          predictionData,
          fileData,
          envData,
          predHistory,
          outcomes,
          premarketData,
          intradayData,
          closingData,
          reportFileData,
          backtestData,
          scannerData,
          watchlistData,
          directHoldingsData,
          correlationData
        ] =
          await Promise.all([
            getJson<MarketSummary>(`/api/market/summary?market=${market}`),
            getJson<ApiList<Security>>(`/api/symbols?market=${market}`),
            getJson<ApiList<Security>>(`/api/positions?market=${market}`),
            getJson<ApiList<NewsItem>>(`/api/news?market=${market}`),
            getJson<ApiList<Security>>(`/api/predictions?market=${market}`),
            getJson<{ items: FileItem[] }>("/api/status/files"),
            getJson<{ items: EnvItem[] }>("/api/status/env"),
            getJson<HistoryResponse>("/api/history/predictions"),
            getJson<HistoryResponse>("/api/history/outcomes"),
            getJson<ApiList<PremarketItem>>(`/api/reports/premarket?market=${market}`),
            getJson<ApiList<IntradayItem>>(`/api/reports/intraday?market=${market}`),
            getJson<ClosingReport>(`/api/reports/closing?market=${market}`),
            getJson<ReportFilesResponse>("/api/reports/files"),
            getJson<BacktestResponse>(`/api/advanced/backtest?market=${market}`),
            getJson<ApiList<ScannerItem>>(`/api/advanced/scanner?market=${market}`),
            getJson<ApiList<Security>>(`/api/watchlist?market=${market}`),
            getJson<ApiList<Security>>(`/api/holdings?market=${market}`),
            getJson<CorrelationResponse>(`/api/advanced/correlation?market=${market}`)
          ]);
        const candidateData = await Promise.all(
          candidateTabs.map(([type]) => getJson<ApiList<Security>>(`/api/candidates?market=${market}&type=${type}`))
        );

        if (cancelled) return;
        setSummary(summaryData);
        setSymbols(symbolData);
        setPositions(positionData);
        setNews(newsData);
        setPredictions(predictionData);
        setFiles(fileData.items);
        setEnv(envData.items);
        setPredictionHistory(predHistory);
        setOutcomeHistory(outcomes);
        setPremarket(premarketData);
        setIntraday(intradayData);
        setClosing(closingData);
        setReportFiles(reportFileData);
        setBacktest(backtestData);
        setScanner(scannerData);
        setWatchlist(watchlistData);
        setDirectHoldings(directHoldingsData);
        setCorrelation(correlationData);
        setCandidates(Object.fromEntries(candidateTabs.map(([type], idx) => [type, candidateData[idx]])));
        setSelectedSymbol(symbolData.items[0] ?? null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "데이터 로딩 실패");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [market, refreshTick]);

  const currentGroup = NAV_GROUPS.find((group) => group.title === activeCategory) ?? NAV_GROUPS[0];
  const marketName = market === "kr" ? "국장" : "미장";
  const updatedAt = summary?.updatedAt ?? "기준시각 없음";
  const apiOk = env.filter((item) => item.status === "OK").length;
  const apiMissing = env.filter((item) => item.status === "MISSING").length;
  const filesMissing = files.filter((item) => item.status === "MISSING").length;

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
      return scanner.items.filter((item) => `${item.theme} ${item.group} ${item.reason}`.includes("저평가"));
    }
    return scanner.items.filter((item) => item.bucket === scannerFilter || `${item.theme} ${item.group} ${item.reason}`.includes(scannerFilter));
  }, [scanner.items, scannerFilter]);

  const directHoldingsBySymbol = useMemo(() => new Map(directHoldings.items.map((item) => [item.symbol, item])), [directHoldings.items]);

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
              setActiveSubPage("보유 관리");
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

  const compactSymbolColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "action", header: "다음 행동", render: (row) => row.nextAction || "다음 행동 없음" },
    { key: "reason", header: "근거", render: (row) => row.reason || row.warning || "근거 없음" }
  ];

  const premarketColumns: Column<PremarketItem>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "priceTime", header: "가격기준시각", render: (row) => row.priceTime || "현재가 기준시각 없음" },
    { key: "priceSource", header: "가격출처", render: (row) => row.priceSource || "가격출처 없음" },
    { key: "open", header: "예상 시초가", render: (row) => row.expectedOpen },
    { key: "close", header: "예상 종가", render: (row) => row.expectedClose },
    { key: "entry", header: "기준가", render: (row) => row.entryText || "기준가 없음" },
    { key: "stop", header: "손절가", render: (row) => row.stopText || "손절가 없음" },
    { key: "tp1", header: "1차 목표가", render: (row) => row.targetText || "목표가 없음" },
    { key: "tp2", header: "2차 목표가", render: (row) => row.target2Text || "2차 목표가 없음" },
    { key: "rr", header: "손익비", render: (row) => row.riskReward || "손익비 없음" },
    { key: "action", header: "다음 행동", render: (row) => row.nextAction || "다음 행동 없음" },
    { key: "risk", header: "리스크 상태", render: (row) => <LongText text={row.riskStatus || "리스크 상태 없음"} /> },
    { key: "status", header: "데이터 상태", render: (row) => row.dataStatus || "데이터 상태 없음" }
  ];

  const intradayColumns: Column<IntradayItem>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "gap", header: "기준가 괴리율", render: (row) => <GainText value={row.divergencePct} text={row.divergenceText} /> },
    { key: "stop", header: "손절 이탈", render: (row) => row.stopBreakText },
    { key: "target", header: "목표 도달", render: (row) => row.targetHitText },
    { key: "holding", header: "보유 위험", render: (row) => row.holdingRisk },
    { key: "news", header: "뉴스/리스크", render: (row) => <LongText text={row.newsRiskStatus} /> },
    { key: "priceTime", header: "가격기준시각", render: (row) => row.priceTime || "현재가 기준시각 없음" },
    { key: "priceSource", header: "가격출처", render: (row) => row.priceSource || "가격출처 없음" },
    { key: "decision", header: "장중 판단", render: (row) => <DecisionPill text={row.intradayDecision} /> }
  ];

  const closingColumns: Column<ClosingItem>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "base", header: "예측 기준일", render: (row) => row.predictionBaseDate },
    { key: "actual", header: "실제 결과일", render: (row) => row.actualResultDate },
    { key: "direction", header: "방향 적중", render: (row) => row.directionHit },
    { key: "range", header: "범위 적중", render: (row) => row.rangeHit },
    { key: "entry", header: "주문 기준가", render: (row) => row.entryTouched },
    { key: "touch", header: "손절/익절", render: (row) => row.stopTakeProfit },
    { key: "failed", header: "실패 종목", render: (row) => row.failedSymbol },
    { key: "reason", header: "실패/부족 사유", render: (row) => <LongText text={row.failureReason} /> }
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
    { key: "reason", header: "근거", render: (row) => <LongText text={row.reason || "근거 없음"} /> },
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
      <Sidebar activeCategory={activeCategory} onSelectCategory={selectCategory} />
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
              API {apiOk} OK / {apiMissing} MISSING · 파일 누락 {filesMissing}
              {quoteStatus ? (
                <span className="ml-2 text-accent">
                  현재가 {quoteStatus.status} · 성공 {quoteStatus.refreshed} / 실패 {quoteStatus.failed}
                </span>
              ) : null}
            </div>
          </div>

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
    if (activeSubPage === "운영 대시보드") {
      return (
        <Section title="운영 대시보드">
          <SimpleRecords rows={summary?.dashboard ?? []} empty="운영 대시보드 데이터 없음" />
        </Section>
      );
    }

    if (activeSubPage === "오늘 체크") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="매수 후보" value={candidates.action?.count ?? 0} note={sourceLabel(candidates.action?.source)} tone="accent" />
            <StatCard label="주의 후보" value={candidates.risk?.count ?? 0} note={sourceLabel(candidates.risk?.source)} tone="warn" />
            <StatCard label="보유 종목" value={positions.count} note={sourceLabel(positions.source)} tone="good" />
            <StatCard label="뉴스" value={news.count || "뉴스 없음"} note={sourceLabel(news.source)} />
          </div>
          <Section title="오늘 확인 후보">
            <DataTable rows={(candidates.action?.items ?? []).slice(0, 10)} columns={compactSymbolColumns} onRowClick={setSelectedSymbol} />
          </Section>
        </>
      );
    }

    return (
      <>
        <div className="grid gap-3 md:grid-cols-4">
          <StatCard label="선택 종목" value={symbols.count} note={sourceLabel(symbols.source)} tone="accent" />
          <StatCard label="보유 종목" value={positions.count} note={sourceLabel(positions.source)} tone="good" />
          <StatCard label="뉴스" value={news.count || "뉴스 없음"} note={sourceLabel(news.source)} tone={news.count ? "accent" : "warn"} />
          <StatCard label="예측 이력" value={predictionHistory.count} note={predictionHistory.source} />
        </div>
        <Section title="오늘 요약">
          {summary?.cards?.length ? (
            <div className="grid gap-3 md:grid-cols-5">
              {summary.cards.map((card, idx) => (
                <StatCard
                  key={idx}
                  label={String(card["카드"] ?? card["category"] ?? `요약 ${idx + 1}`)}
                  value={String(card["건수"] ?? card["count"] ?? "-")}
                  note={String(card["TOP"] ?? card["설명"] ?? "요약 없음")}
                  tone={idx === 0 ? "good" : "neutral"}
                />
              ))}
            </div>
          ) : (
            <EmptyReason text="오늘 요약 파일이 없습니다." />
          )}
        </Section>
      </>
    );
  }

  function renderReports() {
    if (activeSubPage === "장전 리포트") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="장전 항목" value={premarket.count || "데이터 없음"} note={(premarket.sources ?? []).slice(0, 2).join(" · ") || "소스 없음"} tone="accent" />
            <StatCard label="오늘 요약" value={summary?.cards?.length ?? 0} note="today_summary" />
            <StatCard label="주의 후보" value={premarket.items.filter((item) => item.sourceGroup === "주의").length} note="risk_cards" tone="warn" />
            <StatCard label="확률 후보" value={premarket.items.filter((item) => item.sourceGroup === "확률").length} note="future_probability" tone="good" />
          </div>
          <Section title="장전 리포트">
            {premarket.items.length ? (
              <DataTable rows={premarket.items} columns={premarketColumns} onRowClick={setSelectedSymbol} />
            ) : (
              <EmptyReason text="장전 리포트 데이터 없음" />
            )}
          </Section>
        </>
      );
    }
    if (activeSubPage === "장중 체크") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="장중 점검" value={intraday.count || "데이터 없음"} note={(intraday.sources ?? []).slice(0, 2).join(" · ") || "소스 없음"} tone="accent" />
            <StatCard label="보유 종목" value={positions.count} note={sourceLabel(positions.source)} tone="good" />
            <StatCard label="손절 주의" value={intraday.items.filter((item) => item.intradayDecision === "손절 주의").length} tone="warn" />
            <StatCard label="익절 검토" value={intraday.items.filter((item) => item.intradayDecision === "익절 검토").length} tone="good" />
          </div>
          <Section title="장중 체크">
            {intraday.items.length ? (
              <DataTable rows={intraday.items} columns={intradayColumns} onRowClick={setSelectedSymbol} />
            ) : (
              <EmptyReason text="장중 체크 데이터 없음" />
            )}
          </Section>
        </>
      );
    }
    if (activeSubPage === "장마감 검증") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="최근 예측" value={closing.count || "검증 데이터 없음"} note={(closing.sources ?? []).join(" · ")} tone="accent" />
            <StatCard label="방향 적중률" value={closing.directionHitRate} note="전체 direction_hit 기준" tone="good" />
            <StatCard label="범위 적중률" value={closing.rangeHitRate} note="open/close range 기준" />
            <StatCard label="outcome_history" value={closing.outcomeHistoryCount} note="rows" />
          </div>
          <Section title="장마감 검증">
            {closing.items.length ? (
              <DataTable rows={closing.items} columns={closingColumns} />
            ) : (
              <EmptyReason text="장마감 검증 데이터 없음" />
            )}
          </Section>
        </>
      );
    }
    return (
      <>
        <div className="grid gap-3 md:grid-cols-4">
          <StatCard label="리포트 파일" value={reportFiles.count} note={`fallback ${reportFiles.fallbackPolicy.join(" → ") || "상태 없음"}`} tone="accent" />
          <StatCard label="OK" value={reportFiles.items.filter((item) => item.status === "OK").length} tone="good" />
          <StatCard label="비어 있음" value={reportFiles.items.filter((item) => item.status !== "OK").length} tone="warn" />
          <StatCard label="CSV 미리보기" value="표시" note="각 파일 상위 3행" />
        </div>
        <Section title="리포트 센터">
          {reportFiles.items.length ? (
            <DataTable rows={reportFiles.items} columns={reportFileColumns} />
          ) : (
            <EmptyReason text="reports 파일 목록 없음" />
          )}
        </Section>
        <Section title="CSV 미리보기">
          <div className="grid gap-3 xl:grid-cols-2">
            {reportFiles.items.slice(0, 8).map((file) => (
              <div key={file.path} className="rounded-lg border border-line bg-card p-4">
                <div className="text-sm font-black text-white">{file.fileName}</div>
                <div className="mt-1 text-xs text-muted">
                  {file.group} · {file.rows} rows · {file.columns} cols · {file.fallbackStatus}
                </div>
                <SimpleRecords rows={file.preview ?? []} empty="CSV 미리보기 없음" />
              </div>
            ))}
          </div>
        </Section>
      </>
    );
  }

  function renderSymbolDiscovery() {
    if (activeSubPage === "관심종목") {
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
          <Section title={`${marketName} 관심종목`} right={<span className="text-xs text-muted">{watchlist.count}개 · {sourceLabel(watchlist.source)}</span>}>
            <DataTable
              rows={watchlist.items}
              columns={[
                ...symbolColumns,
                {
                  key: "delete",
                  header: "관리",
                  render: (row) => (
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        deleteWatchlistSymbol(row.symbol);
                      }}
                      className="rounded-md border border-warn/40 px-2 py-1 text-xs font-bold text-warn"
                    >
                      삭제
                    </button>
                  )
                }
              ]}
              onRowClick={setSelectedSymbol}
            />
          </Section>
        </>
      );
    }

    if (activeSubPage === "후보군") {
      return (
        <>
          <WriteStatus text={writeStatus} />
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="후보군" value={scanner.count} note="candidate/watchlist/v92 cards" tone="accent" />
            <StatCard label="관심종목" value={watchlist.count} note={sourceLabel(watchlist.source)} />
            <StatCard label="보유 제외" value={scanner.items.filter((item) => !item.isHolding).length} />
            <StatCard label="쓰기 안전장치" value="백업 후 저장" note="watchlist만 수정" tone="good" />
          </div>
          <Section title="후보군 / 관심종목 편입">
            <DataTable rows={filteredScanner} columns={scannerColumns} onRowClick={setSelectedSymbol} />
          </Section>
        </>
      );
    }

    if (activeSubPage === "매수 후보" || activeSubPage === "매수금지 / 주의") {
      const type = activeSubPage === "매수금지 / 주의" ? "risk" : candidateType;
      const list = candidates[type]?.items ?? [];
      return (
        <>
          <WriteStatus text={writeStatus} />
          <div className="flex flex-wrap gap-2">
            {candidateTabs.map(([typeId, label]) => (
              <button
                key={typeId}
                onClick={() => setCandidateType(typeId)}
                className={`rounded-md border px-3 py-2 text-sm font-bold ${
                  type === typeId ? "border-accent bg-accent/15 text-accent" : "border-line bg-panel text-slate-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <Section title={`${marketName} ${activeSubPage}`}>
            <DataTable rows={list} columns={[...compactSymbolColumns, { key: "watch", header: "관심종목", render: (row) => <button onClick={(event) => { event.stopPropagation(); addWatchlistFrom(row); }} className="rounded-md border border-accent/45 px-2 py-1 text-xs font-bold text-accent hover:bg-accent hover:text-ink">추가</button> }]} onRowClick={setSelectedSymbol} />
          </Section>
        </>
      );
    }

    return (
      <>
        <WriteStatus text={writeStatus} />
        <Section
          title={`${marketName} ${activeSubPage}`}
          right={<span className="text-xs text-muted">{symbols.count}개 · {sourceLabel(symbols.source)}</span>}
        >
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="종목명 또는 코드 검색"
            className="mb-3 w-full rounded-lg border border-line bg-panel px-4 py-3 text-sm outline-none focus:border-accent"
          />
          <DataTable rows={filteredSymbols} columns={[...symbolColumns, { key: "watch", header: "관심종목", render: (row) => <button onClick={(event) => { event.stopPropagation(); addWatchlistFrom(row); }} className="rounded-md border border-accent/45 px-2 py-1 text-xs font-bold text-accent hover:bg-accent hover:text-ink">추가</button> }]} onRowClick={setSelectedSymbol} />
        </Section>
        <Section title="상세 카드">
          {selectedSymbol ? <SymbolDetailCard item={selectedSymbol} /> : <EmptyReason text="선택된 종목이 없습니다." />}
        </Section>
      </>
    );
  }

  function renderPositions() {
    const displayRows = activeSubPage === "보유 관리" ? directHoldings.items : positions.items;
    const positive = displayRows.filter((item) => (item.pnl ?? 0) > 0).length;
    const negative = displayRows.filter((item) => (item.pnl ?? 0) < 0).length;
    return (
      <>
        <WriteStatus text={writeStatus} />
        <div className="grid gap-3 md:grid-cols-4">
          <StatCard label="보유 종목" value={displayRows.length} note={activeSubPage === "보유 관리" ? sourceLabel(directHoldings.source) : sourceLabel(positions.source)} tone="good" />
          <StatCard label="수익 구간" value={positive} note="평가손익 기준" tone="accent" />
          <StatCard label="손실 구간" value={negative} note="평가손익 기준" tone={negative ? "warn" : "good"} />
          <StatCard label="쓰기 안전장치" value="백업 후 저장" note="holdings 파일만 수정" tone="warn" />
        </div>
        {activeSubPage === "보유 관리" ? (
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
        ) : null}
        <Section title={`${marketName} ${activeSubPage}`}>
          <DataTable rows={displayRows} columns={activeSubPage === "손절·목표가" ? orderLineColumns : positionColumns} onRowClick={setSelectedSymbol} />
        </Section>
      </>
    );
  }

  function renderCharts() {
    if (activeSubPage === "기술지표") {
      return (
        <Section title="기술지표 점검">
          <DataTable rows={symbols.items} columns={scoreColumns} onRowClick={setSelectedSymbol} />
        </Section>
      );
    }
    if (activeSubPage === "지지·저항" || activeSubPage === "예측선 / 주문선") {
      return (
        <Section title={activeSubPage}>
          <DataTable rows={symbols.items} columns={orderLineColumns} onRowClick={setSelectedSymbol} />
        </Section>
      );
    }
    return (
      <>
        <Section title="차트 보기">
          {historyChart.length ? (
            <div className="h-72 rounded-lg border border-line bg-panel p-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={historyChart}>
                  <defs>
                    <linearGradient id="returnGradient" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.7} />
                      <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="rgba(148,163,184,.16)" />
                  <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid rgba(148,163,184,.25)" }} />
                  <Area type="monotone" dataKey="value" stroke="#38bdf8" fill="url(#returnGradient)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyReason text="차트 데이터 부족" />
          )}
        </Section>
        <Section title="선택 종목 가격 기준">
          <DataTable rows={symbols.items.slice(0, 20)} columns={symbolColumns} onRowClick={setSelectedSymbol} />
        </Section>
      </>
    );
  }

  function renderNewsCompany() {
    if (activeSubPage === "공시") {
      return (
        <Section title="공시">
          {news.items.length ? (
            <DataTable
              rows={news.items}
              columns={[
                { key: "title", header: "제목", render: (row) => row.title },
                { key: "source", header: "출처", render: (row) => row.sourceName },
                { key: "time", header: "게시시간", render: (row) => row.publishedAt },
                { key: "name", header: "연결 종목", render: (row) => row.name || row.symbol || "연결 종목 없음" }
              ]}
            />
          ) : (
            <EmptyReason text="공시 전용 데이터 없음" />
          )}
        </Section>
      );
    }
    if (activeSubPage === "기업분석") {
      return (
        <Section title="기업분석">
          <DataTable rows={symbols.items} columns={scoreColumns} onRowClick={setSelectedSymbol} />
        </Section>
      );
    }
    if (activeSubPage === "종목 내러티브") {
      return (
        <Section title="종목 내러티브">
          <DataTable rows={symbols.items.slice(0, 30)} columns={compactSymbolColumns} onRowClick={setSelectedSymbol} />
        </Section>
      );
    }
    return (
      <>
        <div className="grid gap-3 md:grid-cols-3">
          <StatCard label="뉴스" value={news.count || "뉴스 없음"} note={sourceLabel(news.source)} tone={news.count ? "accent" : "warn"} />
          <StatCard label="기업분석" value={symbols.count ? "연결됨" : "기준가 없음"} note="company_integrated report" />
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
                    {item.sourceName} · {item.publishedAt}
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
    if (activeSubPage === "예측 기록") {
      return <HistoryTable title="예측 기록" history={predictionHistory} />;
    }
    if (activeSubPage === "결과 검증") {
      return <HistoryTable title="결과 검증" history={outcomeHistory} />;
    }
    if (activeSubPage === "실패 복기" || activeSubPage === "자동 보정") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="예측 기록" value={predictionHistory.count} note={predictionHistory.source} tone="accent" />
            <StatCard label="결과 검증" value={outcomeHistory.count} note={outcomeHistory.source} />
            <StatCard label={activeSubPage} value="데이터 연결" note="자동 규칙은 후속 버전에서 보강" tone="warn" />
          </div>
          <HistoryTable title={activeSubPage} history={activeSubPage === "실패 복기" ? outcomeHistory : predictionHistory} />
        </>
      );
    }
    return (
      <>
        <div className="grid gap-3 md:grid-cols-3">
          <StatCard label="확률 행" value={predictions.count} note={sourceLabel(predictions.source)} tone="accent" />
          <StatCard label="prediction_history" value={predictionHistory.count} note={predictionHistory.source} />
          <StatCard label="outcome_history" value={outcomeHistory.count} note={outcomeHistory.source} />
        </div>
        <Section title="확률 예측">
          <DataTable
            rows={predictions.items}
            columns={[
              { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
              { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
              { key: "confidence", header: "신뢰도", render: (row) => String(row.confidence ?? "신뢰도 없음") },
              { key: "action", header: "다음 행동", render: (row) => row.nextAction || "다음 행동 없음" }
            ]}
            onRowClick={setSelectedSymbol}
          />
        </Section>
      </>
    );
  }

  function renderAdmin() {
    if (activeSubPage === "데이터 점검") return <FileStatusTable rows={files} />;
    if (activeSubPage === "API 상태" || activeSubPage === "자동화 상태") return <ApiStatus env={env} />;
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
            <StatCard label="스캐너 대상" value={scanner.count} note="candidate/watchlist/cards 조합" tone="accent" />
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
            {filteredScanner.length ? <DataTable rows={filteredScanner} columns={scannerColumns} onRowClick={setSelectedSymbol} /> : <EmptyReason text="조건에 맞는 스캐너 결과 없음" />}
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

function PriceBlock({ item, compact = false }: { item: Security; compact?: boolean }) {
  return (
    <div>
      <div className={compact ? "font-bold text-white" : "text-base font-black text-white"}>
        {item.currentPriceText || "기준가 없음"}
      </div>
      <div className="mt-1 text-xs leading-5 text-muted">
        {item.priceTime || "기준시각 없음"} · {item.priceSource || "가격출처 없음"}
      </div>
    </div>
  );
}

function GainText({ value, text }: { value?: number | null; text?: string }) {
  const tone = (value ?? 0) < 0 ? "text-warn" : (value ?? 0) > 0 ? "text-good" : "text-slate-300";
  return <span className={`font-black ${tone}`}>{text || "평가 데이터 없음"}</span>;
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

function SymbolDetailCard({ item }: { item: Security }) {
  return (
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
        {item.avgPriceText || item.returnPctText ? (
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <StatCard label="평균단가" value={item.avgPriceText || "평균단가 없음"} />
            <StatCard label="수익률" value={item.returnPctText || "수익률 없음"} tone={(item.returnPct ?? 0) < 0 ? "warn" : "good"} />
            <StatCard label="평가손익" value={item.pnlText || "평가손익 없음"} tone={(item.pnl ?? 0) < 0 ? "warn" : "good"} />
          </div>
        ) : null}
      </div>
      <div className="rounded-lg border border-line bg-panel p-4">
        <div className="text-sm font-black text-white">상태</div>
        <p className="mt-2 text-sm leading-6 text-slate-300">{item.dataStatus || "상태 없음"}</p>
        <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-muted">
          <span>수급: {item.scores?.supply || "수급 데이터 없음"}</span>
          <span>실적: {item.scores?.earnings || "재무 데이터 없음"}</span>
          <span>밸류: {item.scores?.valuation || "재무 데이터 없음"}</span>
          <span>차트: {item.scores?.chart || "차트 데이터 부족"}</span>
        </div>
      </div>
    </div>
  );
}

type SimpleValue = string | number | boolean | null | undefined;

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <div className="text-xs font-bold text-muted">{label}</div>
      <div className="mt-1 text-lg font-black text-white">{value}</div>
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
