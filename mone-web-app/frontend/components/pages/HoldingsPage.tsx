"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BriefcaseBusiness, ChevronDown, ChevronRight, Download, Eye, FileText, Link2, Pencil, Plus, RefreshCw, Save, Trash2, TriangleAlert, X, Zap } from "lucide-react";
import CashInputBar from "../CashInputBar";
import PortfolioOptimizePanel from "../PortfolioOptimizePanel";
import { mone } from "@/lib/api";
import { dataFreshnessBadgeClass, dataFreshnessInfo, displayName } from "@/lib/moneDisplay";
import { toneClassName } from "@/lib/tone";
import { getAuthenticatedUserId, getUserProfile, getUserToken } from "@/lib/userId";
import type { BootPreloadData } from "@/lib/bootPreload";
import { dataStatusLabel, normalizeAction, normalizeStatus, toneBadgeClass } from "@/lib/statusLabels";

type Market = "all" | "kr" | "us";
type MarketMode = "all" | "kr" | "us";
type PortfolioAnalysisTab = "benchmark" | "correlation" | "sector" | "optimize";
type RiskFocus = "all" | "stop" | "rebalance" | "price";
const HOLDINGS_API_TIMEOUT_MS = 90000;

function koreanSectorLabel(value: any, symbols: any[] = []) {
  const raw = String(value || "").trim();
  const labels: Record<string, string> = {
    "Consumer Cyclical": "경기소비재", Technology: "기술", "Financial Services": "금융",
    "Communication Services": "커뮤니케이션", Industrials: "산업재", Healthcare: "헬스케어",
    Energy: "에너지", Utilities: "유틸리티", "Real Estate": "부동산", "Basic Materials": "소재",
  };
  if (labels[raw]) return labels[raw];
  if (/^(other|기타|미분류|unknown)$/i.test(raw)) {
    const text = symbols.join(" ").toUpperCase();
    return /(TIGER|KODEX|ACE |ETF|ETN|SPY|QQQ|SCHD)/.test(text) ? "ETF" : "개별주";
  }
  return raw || "개별주";
}

function automaticMarket(): "kr" | "us" {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Seoul",
    weekday: "short",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const weekday = parts.find((part) => part.type === "weekday")?.value;
  const hour = Number(parts.find((part) => part.type === "hour")?.value || 12);
  if (weekday === "Sat" || weekday === "Sun") return "kr";
  return hour >= 22 || hour < 6 ? "us" : "kr";
}

type BrokerStatus = {
  broker: string;
  connected: boolean;
  status: string;
  lastSync?: number | null;
  connectedAt?: number | null;
  accountNoHint?: string;
};

type HoldingsPageProps = {
  userToken?: string | null;
  onNavigate?: (page: string) => void;
  bootData?: BootPreloadData | null;
};

type EditableHolding = {
  market: "kr" | "us";
  symbol: string;
  name: string;
  quantity: string;
  avgPrice: string;
  stopPrice?: string;
  targetPrice?: string;
};

function apiUrl(path: string) { return `/mone-api${path}`; }

async function getJson(path: string) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HOLDINGS_API_TIMEOUT_MS);
  try {
    const res = await fetch(apiUrl(path), { cache: "no-store", signal: controller.signal, headers: getMoneUserHeader() });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText} ${detail}`.trim());
    }
    return res.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`요청 시간이 ${HOLDINGS_API_TIMEOUT_MS / 1000}초를 넘었습니다.`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function getMoneUserHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const id = getAuthenticatedUserId();
    const token = getUserToken();
    return {
      ...(id ? { "x-mone-user": id } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  } catch { return {}; }
}

const LS_HOLDINGS_KEY = "mone:personal_holdings_v2";

function holdingStatusLabel(status: any): string {
  const s = String(status || "").toUpperCase();
  if (s === "LOCAL_ONLY") return "로컬 임시";
  if (s === "DATA_PENDING") return "분석 대기";
  if (s === "STALE") return "갱신 필요";
  if (s === "NO_PRICE" || s === "PRICE_PENDING") return "갱신 필요";
  if (s === "PREVIOUS_CLOSE_BASIS") return "최신 마감 기준";
  if (s === "INTRADAY_OBSERVE") return "관찰";
  if (s === "PARTIAL") return "일부 제한";
  if (s === "NORMAL" || s === "OK") return "정상";
  return status ? dataStatusLabel(status).label : "확인 중";
}

function saveHoldingsToLocalStorage(items: any[]) {
  try {
    localStorage.setItem(LS_HOLDINGS_KEY, JSON.stringify({ items, savedAt: new Date().toISOString() }));
  } catch {}
}

function loadHoldingsFromLocalStorage(): any[] {
  try {
    const raw = localStorage.getItem(LS_HOLDINGS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed.items) ? parsed.items : [];
  } catch { return []; }
}

async function postJson(path: string, body: any) {
  const res = await fetch(apiUrl(path), {
    method: "POST", cache: "no-store",
    headers: { Accept: "application/json", "Content-Type": "application/json", ...getMoneUserHeader() },
    body: JSON.stringify(body || {}),
  });
  const text = await res.text().catch(() => "");
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} ${text.slice(0, 500)}`.trim());
  return text ? JSON.parse(text) : {};
}

function dedupe(items: any[]) {
  const seen = new Set<string>();
  return (items || []).filter((item) => {
    const key = `${item.market}-${item.symbol}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}

// Module-level re-entry cache: avoids reload spinner when navigating away and back
const HOLDINGS_CACHE_TTL = 3 * 60 * 1000; // 3 min
type HoldingsCacheEntry = { data: any; market: Market; loadedAt: string; ts: number };
let _holdingsCache: HoldingsCacheEntry | null = null;
function readHoldingsCache(market: Market): HoldingsCacheEntry | null {
  if (!_holdingsCache) return null;
  if (_holdingsCache.market !== market) return null;
  if (Date.now() - _holdingsCache.ts > HOLDINGS_CACHE_TTL) return null;
  return _holdingsCache;
}
function writeHoldingsCache(market: Market, data: any, loadedAt: string) {
  _holdingsCache = { data, market, loadedAt, ts: Date.now() };
}

function emptyHoldingsPayload(market: Market, needsLogin = false) {
  return {
    status: "OK",
    authority: needsLogin ? "auth_required" : "personal",
    routeVersion: needsLogin ? "auth_required" : "personal_empty",
    market,
    count: 0,
    items: [],
    summary: {
      totalValue: 0,
      totalPnl: 0,
      riskCount: 0,
      totalValueText: "0원",
      totalPnlText: "+0원",
    },
    needsLogin,
  };
}

function extractPositionCandidates(summary: any) {
  const matrix = summary?.matrix || {};
  return Object.entries(matrix).flatMap(([key, cell]: [string, any]) => {
    const [mode, horizon] = key.split("_");
    const rows = Array.isArray(cell?.items) ? cell.items : [];
    return rows.map((item: any) => ({
      ...item,
      _mode: item._mode || item.mode || mode,
      _horizon: item._horizon || item.horizon || horizon,
      market: item.market || summary?.market,
    }));
  });
}

function cleanHoldingMarket(value: any): "kr" | "us" {
  return String(value || "kr").toLowerCase() === "us" ? "us" : "kr";
}
function cleanHoldingSymbol(symbol: any, market: "kr" | "us") {
  const raw = String(symbol || "").trim();
  if (market === "kr") return raw.replace(/[^0-9]/g, "").padStart(6, "0").slice(-6);
  return raw.toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
}
function editableKey(item: { market?: any; symbol?: any }) {
  const m = cleanHoldingMarket(item.market);
  return `${m}-${cleanHoldingSymbol(item.symbol, m)}`;
}
function toEditableHolding(item: any): EditableHolding {
  const market = cleanHoldingMarket(item.market);
  const stopValue = item.stopPrice ?? item.stop ?? "";
  const targetValue = item.targetPrice ?? item.target ?? "";
  return {
    market,
    symbol: cleanHoldingSymbol(item.symbol, market),
    name: String(item.name || "").trim(),
    quantity: String(item.quantity ?? "").replace(/[^0-9.]/g, ""),
    avgPrice: String(item.avgPrice ?? "").replace(/[^0-9.]/g, ""),
    stopPrice: String(stopValue).replace(/[^0-9.]/g, "") || undefined,
    targetPrice: String(targetValue).replace(/[^0-9.]/g, "") || undefined,
  };
}
function normalizeForSave(item: EditableHolding) {
  const market = cleanHoldingMarket(item.market);
  return {
    market, symbol: cleanHoldingSymbol(item.symbol, market),
    name: item.name.trim(),
    quantity: Number(String(item.quantity).replace(/,/g, "")),
    avgPrice: Number(String(item.avgPrice).replace(/,/g, "")),
    stopPrice: item.stopPrice ? Number(String(item.stopPrice).replace(/,/g, "")) : "",
    targetPrice: item.targetPrice ? Number(String(item.targetPrice).replace(/,/g, "")) : "",
  };
}

function formatHoldingMoney(value: number, market: "kr" | "us") {
  if (!Number.isFinite(value) || value <= 0) return "-";
  return market === "us"
    ? `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : `KRW ${Math.round(value).toLocaleString("ko-KR")}`;
}

function holdingAssetLabel(assetType: any) {
  const type = String(assetType || "stock");
  if (type === "stock") return "개별주";
  if (type === "leveraged_etf") return "레버리지 ETF";
  if (type === "inverse_etf") return "인버스 ETF";
  if (type === "dividend_etf") return "배당 ETF";
  if (type === "bond_etf") return "채권 ETF";
  if (type === "broad_etf") return "대표지수 ETF";
  if (type === "theme_etf") return "테마 ETF";
  if (type === "sector_etf") return "섹터 ETF";
  if (type === "long_term_etf") return "장기 ETF";
  return "유형 확인";
}

const ETF_NAME_MARKERS = [
  "ETF",
  "ETN",
  "KODEX",
  "TIGER",
  "ACE",
  "KBSTAR",
  "ARIRANG",
  "HANARO",
  "KOSEF",
  "SOL ",
  "SOL-",
  "RISE",
  "TIMEFOLIO",
  "PLUS",
  "FOCUS",
  "ISHARES",
  "VANGUARD",
  "SPDR",
  "INVESCO",
  "PROSHARES",
  "DIREXION",
  "GLOBAL X",
  "JPMORGAN",
  "FUND",
  "TRUST",
];
const ETF_SYMBOL_MARKERS = new Set([
  "SPY", "QQQ", "VOO", "VTI", "VT", "SCHD", "JEPI", "JEPQ", "DIA", "IWM",
  "TLT", "IEF", "SHY", "BND", "AGG", "GLD", "SLV", "XLK", "XLF", "XLE",
  "XLV", "XLY", "XLP", "XLI", "XLU", "XLC", "XLRE", "ARKK", "SOXX", "SMH",
]);

function normalizedHoldingAssetType(item: any): string {
  const explicit = String(
    item?.assetType || item?.instrumentType || item?.securityType || item?.category || item?.productType || ""
  ).trim().toLowerCase();
  if (explicit.includes("etf") || explicit.includes("etn") || explicit.includes("fund")) {
    return explicit.includes("leveraged") ? "leveraged_etf"
      : explicit.includes("inverse") ? "inverse_etf"
        : explicit.includes("bond") ? "bond_etf"
          : explicit.includes("dividend") ? "dividend_etf"
            : explicit || "broad_etf";
  }
  const market = cleanHoldingMarket(item?.market);
  const symbol = cleanHoldingSymbol(item?.symbol || item?.code || item?.ticker, market).toUpperCase();
  const haystack = [
    symbol,
    item?.name,
    item?.companyName,
    item?.displayName,
    item?.productName,
    item?.sector,
    item?.assetClass,
  ].join(" ").toUpperCase();
  if (ETF_SYMBOL_MARKERS.has(symbol) || ETF_NAME_MARKERS.some((marker) => haystack.includes(marker))) {
    if (/INVERSE|인버스|곱버스/.test(haystack)) return "inverse_etf";
    if (/LEVERAGE|LEVERAGED|2X|3X|레버리지/.test(haystack)) return "leveraged_etf";
    if (/DIVIDEND|SCHD|배당/.test(haystack)) return "dividend_etf";
    if (/BOND|TREASURY|TLT|IEF|SHY|AGG|BND|채권|국채/.test(haystack)) return "bond_etf";
    if (/KODEX 200|TIGER 200|SPY|QQQ|VOO|VTI|DIA|IWM/.test(haystack)) return "broad_etf";
    return "sector_etf";
  }
  return explicit || "stock";
}

function holdingPurposeLabel(purpose: any) {
  const value = String(purpose || "");
  if (value === "short_trade") return "단기";
  if (value === "swing") return "스윙";
  if (value === "long_term") return "장기";
  if (value === "savings_plan") return "적립";
  if (value === "dividend") return "배당";
  return "전략 확인";
}

function localHoldingDisplayRows(rows: any[]) {
  return dedupe(rows.map((row) => {
    const item = toEditableHolding(row);
    const market = item.market;
    const quantity = Number(item.quantity || 0);
    const avgPrice = Number(item.avgPrice || 0);
    const costBasis = quantity * avgPrice;
    return {
      ...item,
      quantity,
      avgPrice,
      avgPriceText: formatHoldingMoney(avgPrice, market),
      currentPrice: 0,
      currentPriceText: "price pending",
      marketValue: 0,
      marketValueText: "price pending",
      costBasis,
      costBasisText: formatHoldingMoney(costBasis, market),
      pnl: 0,
      pnlText: "-",
      pnlPctText: "-",
      riskStatus: "WATCH",
      dataStatus: "LOCAL_ONLY",
      priceSource: "local_personal_record",
    };
  }));
}

function localHoldingsPayload(rows: any[], market: Market) {
  const filtered = localHoldingDisplayRows(rows).filter((item) => market === "all" || item.market === market);
  const totalCost = filtered.reduce((acc, item) => acc + Number(item.costBasis || 0), 0);
  const mixedCurrency = new Set(filtered.map((item) => item.market)).size > 1;
  return {
    status: "OK",
    routeVersion: "local-personal-holdings",
    authority: "personal_local_storage",
    items: filtered,
    count: filtered.length,
    summary: {
      count: filtered.length,
      totalValue: totalCost,
      totalValueText: mixedCurrency ? "KR/US separated" : formatHoldingMoney(totalCost, filtered[0]?.market || "kr"),
      totalPnl: 0,
      totalPnlText: "-",
      mixedCurrency,
      riskCount: filtered.length,
      missingPriceCount: filtered.length,
    },
  };
}
function validateHoldingDraft(item: EditableHolding) {
  const n = normalizeForSave(item);
  if (!n.symbol) return "종목코드/티커가 필요합니다.";
  if (n.market === "kr" && !/^\d{6}$/.test(n.symbol)) return "국장 종목코드는 6자리여야 합니다.";
  if (!Number.isFinite(n.quantity) || n.quantity <= 0) return "수량은 0보다 커야 합니다.";
  if (!Number.isFinite(n.avgPrice) || n.avgPrice <= 0) return "평균단가는 0보다 커야 합니다.";
  return "";
}
// /api/holdings는 백엔드 모듈에 따라 riskStatus를 영문("HIGH"/"WATCH")으로 주기도 하고
// 한글("위험"/"주의")로 직접 주기도 한다(mone_v802_holdings_clean.py가 현재 라이브 경로).
// 한쪽만 인식하면 실제 "위험" 종목이 매칭 실패로 기본값("정상"/안전)으로 잘못 표시된다.
// 모든 비교는 이 정규화를 거쳐 영문 코드로 통일한 뒤 한다.
function normalizeRiskStatus(risk: unknown): "STOP_LOSS_DELAY" | "HIGH" | "WATCH" | "NORMAL" {
  const r = String(risk || "");
  if (r === "STOP_LOSS_DELAY" || r === "손절지연") return "STOP_LOSS_DELAY";
  if (r === "HIGH" || r === "위험") return "HIGH";
  if (r === "WATCH" || r === "주의") return "WATCH";
  return "NORMAL";
}
function riskBadgeClass(risk: string) {
  return toneBadgeClass(normalizeStatus(riskLabel(risk)).tone);
}
function riskLabel(risk: string) {
  const r = normalizeRiskStatus(risk);
  if (r === "STOP_LOSS_DELAY") return "위험";
  if (r === "HIGH") return "위험";
  if (r === "WATCH") return "주의";
  return "정상";
}
function brokerLabel(value: any) {
  const broker = String(value || "").toLowerCase();
  if (broker === "toss") return "토스증권 연동";
  if (broker === "kis") return "한국투자 연동";
  if (broker === "manual") return "직접 추가";
  if (broker === "file") return "파일 가져오기";
  if (broker.includes("local")) return "직접 추가";
  return broker ? `${broker} 연동` : "직접 추가";
}
function firstSourceText(...values: any[]) {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) return text;
  }
  return "";
}
function shortSourceDate(value: any) {
  if (value == null || value === "") return "";
  if (typeof value === "number" && Number.isFinite(value)) {
    const d = new Date(value > 10_000_000_000 ? value : value * 1000);
    return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(0, 10);
  }
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? text.slice(0, 16) : d.toISOString().slice(0, 10);
}
function humanDataSourceLabel(value: any, fallback = "개인 보유") {
  const raw = String(value || "").trim();
  const source = raw.toLowerCase();
  if (!source) return fallback;
  if (source.includes("auth_required")) return "로그인 필요";
  if (source.includes("personal") || source.includes("user_holdings")) return "개인 보유 DB";
  if (source.includes("local_bridge") || source.includes("broker")) return "브로커 업로드";
  if (source.includes("kis")) return "한국투자 업로드";
  if (source.includes("toss")) return "토스증권 업로드";
  if (source.includes("csv") || source.includes("file") || source.includes("snapshot")) return "업로드 파일";
  if (source.includes("manual") || source.includes("local")) return "직접 추가";
  return raw.length > 22 ? `${raw.slice(0, 22)}…` : raw;
}
function priceSourceLabel(value: any) {
  const source = String(value || "").toLowerCase();
  if (!source) return "";
  if (source.includes("kis") || source.includes("snapshot") || source.includes("intraday")) return "실시간 스냅샷";
  if (source.includes("finnhub") || source.includes("yfinance")) return "외부 시세";
  if (source.includes("ohlcv")) return "OHLCV 기준";
  return "가격 확인";
}
function brokerStatusLabel(status?: BrokerStatus) {
  if (!status || !status.connected) return "미연결";
  if (status.status === "SYNCING") return "동기화 중";
  if (status.status === "ERROR") return "동기화 실패";
  // "connected" = 파일이 업로드·로드됨 (실시간 계좌 조회 아님)
  return "파일 업로드됨";
}
function brokerSyncText(status?: BrokerStatus) {
  const ts = status?.lastSync || status?.connectedAt;
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  const timeStr = d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
  const dateStr = isToday ? "" : `${d.getMonth() + 1}/${d.getDate()} `;
  return `업로드 ${dateStr}${timeStr} (파일 기준)`;
}

// ── NAV 수익률 곡선 (실제/추정 구분) ─────────────────────────────────
function NavCurve() {
  const [navRows, setNavRows] = useState<any[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [kospiRows, setKospiRows] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [loginRequired, setLoginRequired] = useState(false);

  useEffect(() => {
    // 실제 계좌 누적수익률은 본인(로그인 사용자)만 봐야 한다 — 로그인 없이도
    // 누구나 포트폴리오 추이를 볼 수 있었던 문제를 막기 위해 토큰을 보낸다.
    const token = getUserToken();
    const profile = getUserProfile();
    if (!token || !profile) {
      setLoginRequired(true);
      setNavRows([]);
      return;
    }
    setLoginRequired(false);
    fetch("/mone-api/api/portfolio/nav", { cache: "no-store", headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((d) => {
        if (d.status === "LOGIN_REQUIRED") { setLoginRequired(true); setNavRows([]); return; }
        setNavRows(Array.isArray(d.items) ? d.items : []);
      })
      .catch(() => setNavRows([]));
    fetch("/mone-api/api/chart/index/KOSPI?market=kr&limit=365", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setKospiRows(Array.isArray(d.items) ? d.items : []))
      .catch(() => setKospiRows([]));
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || navRows.length < 2) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // 실제/추정 분리
    const actual = navRows.filter((r) => !r.isBackfill);
    const backfill = navRows.filter((r) => !!r.isBackfill);
    const allReturns = navRows.map((r) => Number(r.cumulativeReturn ?? 0));

    const minR = Math.min(...allReturns, 0);
    const maxR = Math.max(...allReturns, 0);
    const range = maxR - minR || 1;
    const pad = { t: 14, b: 22, l: 8, r: 8 };
    const chartW = W - pad.l - pad.r;
    const chartH = H - pad.t - pad.b;

    const dateIndex = new Map(navRows.map((r, i) => [r.date, i]));
    const toX = (date: string) => {
      const i = dateIndex.get(date) ?? 0;
      return pad.l + (i / (navRows.length - 1)) * chartW;
    };
    const toY = (v: number) => pad.t + chartH - ((v - minR) / range) * chartH;

    // 기준선 (0%)
    const zeroY = toY(0);
    ctx.strokeStyle = "#303236"; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(W - pad.r, zeroY); ctx.stroke();
    ctx.setLineDash([]);

    // KOSPI 비교선 (날짜 기반 join)
    if (kospiRows.length > 2 && navRows.length > 2) {
      const startDate = navRows[0].date;
      const filtered = kospiRows.filter((r) => (r.date || r.Date) >= startDate);
      if (filtered.length > 2) {
        const baseClose = Number(filtered[0].close || filtered[0].Close || 0);
        if (baseClose > 0) {
          // navRows의 날짜 범위에 맞춰 KOSPI 수익률 계산
          const kospiByDate = new Map(
            filtered.map((r) => [
              r.date || r.Date,
              ((Number(r.close || r.Close || 0) - baseClose) / baseClose) * 100,
            ])
          );
          const kospiPoints: [number, number][] = [];
          for (const row of navRows) {
            const kRet = kospiByDate.get(row.date);
            if (kRet !== undefined) kospiPoints.push([toX(row.date), toY(kRet)]);
          }
          if (kospiPoints.length > 2) {
            ctx.strokeStyle = "#8a8f9880"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(kospiPoints[0][0], kospiPoints[0][1]);
            for (let i = 1; i < kospiPoints.length; i++) ctx.lineTo(kospiPoints[i][0], kospiPoints[i][1]);
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }
      }
    }

    // 추정 백필 구간 (연한 색 + 대시)
    if (backfill.length > 1) {
      ctx.strokeStyle = "#38bdf840"; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
      ctx.beginPath();
      backfill.forEach((row, i) => {
        const x = toX(row.date); const y = toY(Number(row.cumulativeReturn ?? 0));
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke(); ctx.setLineDash([]);
    }

    // 실제 구간 (solid)
    if (actual.length > 1) {
      const lastReturn = Number(actual.at(-1)?.cumulativeReturn ?? 0);
      const isPos = lastReturn >= 0;
      ctx.strokeStyle = isPos ? "#22c55e" : "#ef4444";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      actual.forEach((row, i) => {
        const x = toX(row.date); const y = toY(Number(row.cumulativeReturn ?? 0));
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    // 날짜 레이블
    ctx.fillStyle = "#55585c"; ctx.font = "10px monospace";
    ctx.textAlign = "left";
    const firstDate = navRows[0]?.date ?? "";
    const lastDate = navRows.at(-1)?.date ?? "";
    if (firstDate) ctx.fillText(firstDate, pad.l, H - 4);
    if (lastDate) { ctx.textAlign = "right"; ctx.fillText(lastDate, W - pad.r, H - 4); }
  }, [navRows, kospiRows]);

  if (loginRequired) {
    return (
      <div className="mone-home-card px-3.5 py-3">
        <div className="text-sm font-semibold text-slate-200">NAV 누적 수익률</div>
        <p className="mt-1.5 text-xs text-slate-400">로그인 후 본인 포트폴리오 추이를 확인할 수 있습니다.</p>
      </div>
    );
  }

  if (navRows.length < 2) return null;

  const lastRow = navRows.filter((r) => !r.isBackfill).at(-1)
    ?? navRows.at(-1);
  const cumReturn = Number(lastRow?.cumulativeReturn ?? 0);
  const isPos = cumReturn >= 0;
  const actualCount = navRows.filter((r) => !r.isBackfill).length;
  const backfillCount = navRows.length - actualCount;

  return (
    <div className="mone-home-card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <span className="text-sm font-semibold text-slate-200">
          NAV 누적 수익률
          <span className={`ml-2 font-mono text-xs font-normal ${isPos ? "text-emerald-300" : "text-red-400"}`}>
            {isPos ? "+" : ""}{cumReturn.toFixed(2)}%
          </span>
        </span>
        <ChevronDown size={16} className={`shrink-0 text-slate-400 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      <div className={open ? "border-t border-slate-800 px-5 pb-5 pt-4" : "hidden"}>
        <div className="mb-3 flex items-center gap-2 text-[10px] text-slate-400">
          <span className="flex items-center gap-1">
            <span className="inline-block h-1.5 w-4 rounded bg-emerald-500"></span>
            실제 {actualCount}일
          </span>
          {backfillCount > 0 && (
            <span className="flex items-center gap-1">
              <span className="inline-block h-px w-4 border-t-2 border-dashed border-sky-400/60"></span>
              추정 백필 {backfillCount}일
            </span>
          )}
          {kospiRows.length > 0 && (
            <span className="flex items-center gap-1">
              <span className="inline-block h-px w-4 border-t border-dashed border-slate-500/60"></span>
              KOSPI
            </span>
          )}
        </div>
        {backfillCount > 0 && (
          <div className="mb-2 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-1.5 text-[10px] text-sky-400">
            ℹ 추정 백필: 현재 보유종목 기준 과거 OHLCV로 역산한 추정값입니다. 실제 과거 포트폴리오 수익률과 다를 수 있습니다.
          </div>
        )}
        {Math.abs(cumReturn) < 0.005 && actualCount <= 2 && (
          <div className="mb-2 rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-1.5 text-[10px] text-slate-400">
            실제 NAV 이력이 부족해 누적 수익률이 평평하게 보입니다. 보유 스냅샷이 쌓이면 곡선이 의미 있게 표시됩니다.
          </div>
        )}
        <canvas ref={canvasRef} width={800} height={110} className="w-full rounded-lg" style={{ height: "110px" }} />
      </div>
    </div>
  );
}

// ── 포트폴리오 구성 바 ─────────────────────────────────────────────────
function PortfolioCompositionBar({ items }: { items: any[] }) {
  const sorted = useMemo(() => {
    const withValue = items
      .map((item) => ({ ...item, _val: Number(item.valuation || item.marketValue || 0) }))
      .filter((item) => item._val > 0)
      .sort((a, b) => b._val - a._val);
    const total = withValue.reduce((acc, item) => acc + item._val, 0);
    // 상위 5개만 개별 표시하고 나머지는 "기타 N종목"으로 묶어 모바일 가독성 확보 (UX 보고서 6.3).
    const TOP = 5;
    if (withValue.length <= TOP + 1) return { items: withValue, total };
    const top = withValue.slice(0, TOP);
    const rest = withValue.slice(TOP);
    const restVal = rest.reduce((acc, item) => acc + item._val, 0);
    const merged = [...top, { market: "_", symbol: "_other", name: `기타 ${rest.length}종목`, _val: restVal, _isOther: true }];
    return { items: merged, total };
  }, [items]);

  if (sorted.total <= 0) return null;
  const colors = ["bg-teal-400","bg-cyan-400","bg-sky-400","bg-emerald-400","bg-amber-400","bg-slate-500"];
  const labelOf = (item: any) => (item._isOther ? item.name : displayName(item));

  return (
    <div className="mone-home-card p-3.5">
      <h2 className="mone-home-section-title mb-3">포트폴리오 구성</h2>
      <div className="flex h-4 w-full overflow-hidden rounded-full">
        {sorted.items.map((item, i) => {
          const pct = (item._val / sorted.total) * 100;
          return (
            <div key={`${item.market}-${item.symbol}`}
              className={`${colors[i % colors.length]} transition-[width] duration-300`}
              style={{ width: `${pct}%` }}
              title={`${labelOf(item)} ${pct.toFixed(1)}%`} />
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {sorted.items.map((item, i) => {
          const pct = (item._val / sorted.total) * 100;
          return (
            <div key={`${item.market}-${item.symbol}`} className="flex items-center gap-1.5">
              <div className={`h-2 w-2 shrink-0 rounded-full ${colors[i % colors.length]}`} />
              <span className="text-[11px] text-slate-300">{labelOf(item)}</span>
              <span className="font-mono text-[11px] text-slate-400">{pct.toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 종목 추가 폼 ───────────────────────────────────────────────────────
function AddHoldingForm({ onSave, onCancel, saving }: { onSave: (d: EditableHolding) => void; onCancel: () => void; saving: boolean }) {
  const [draft, setDraft] = useState<EditableHolding>({
    market: "kr",
    symbol: "",
    name: "",
    quantity: "",
    avgPrice: "",
    stopPrice: "",
    targetPrice: "",
  });
  const [error, setError] = useState("");
  function handleSave() {
    const err = validateHoldingDraft(draft);
    if (err) { setError(err); return; }
    setError(""); onSave(draft);
  }
  return (
    <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5">
      <div className="mb-4 text-sm font-bold text-emerald-200">직접 추가</div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <label className="text-xs text-slate-400">마켓
          <select value={draft.market} onChange={(e) => setDraft({ ...draft, market: e.target.value as "kr"|"us" })}
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400">
            <option value="kr">국장 (KR)</option>
            <option value="us">미장 (US)</option>
          </select>
        </label>
        {(["symbol","name","quantity","avgPrice"] as const).map((field) => (
          <label key={field} className="text-xs text-slate-400">
            {field === "symbol" ? "종목코드/티커" : field === "name" ? "종목명" : field === "quantity" ? "수량" : "평균단가"}
            <input type={field === "quantity" || field === "avgPrice" ? "number" : "text"}
              value={draft[field]}
              onChange={(e) => setDraft({ ...draft, [field]: e.target.value })}
              placeholder={field === "symbol" ? (draft.market === "kr" ? "005930" : "NVDA") : ""}
              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400" />
          </label>
        ))}
        <label className="text-xs text-slate-400">
          손절가
          <input
            type="number"
            value={draft.stopPrice || ""}
            onChange={(e) => setDraft({ ...draft, stopPrice: e.target.value })}
            placeholder={draft.market === "kr" ? "65000" : "118.5"}
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400"
          />
        </label>
        <label className="text-xs text-slate-400">
          목표가
          <input
            type="number"
            value={draft.targetPrice || ""}
            onChange={(e) => setDraft({ ...draft, targetPrice: e.target.value })}
            placeholder={draft.market === "kr" ? "82000" : "145"}
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400"
          />
        </label>
      </div>
      <p className="mt-2 text-[11px] text-slate-400">손절가·목표가는 선택 입력입니다. 비워 두면 현재가만 저장됩니다.</p>
      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      <div className="mt-4 flex gap-2">
        <button onClick={handleSave} disabled={saving}
          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white hover:bg-emerald-500 disabled:opacity-50">
          <Save size={13} /> 추가
        </button>
        <button onClick={onCancel}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
          <X size={13} /> 취소
        </button>
      </div>
    </div>
  );
}

// ── 메인 페이지 ────────────────────────────────────────────────────────
export default function HoldingsPage({ userToken, onNavigate, bootData }: HoldingsPageProps) {
  const hasHoldingsAuth = Boolean(userToken);
  const _bootHoldings = (() => {
    if (!hasHoldingsAuth) return null;
    const bc = bootData?.holdingsCache;
    if (bc && Array.isArray(bc.items) && bc.items.length > 0) return bc;
    return readHoldingsCache("all")?.data ?? null;
  })();

  const [marketMode, setMarketMode] = useState<MarketMode>("all");
  const [market, setMarket] = useState<Market>("all");
  const [holdingsViewTab, setHoldingsViewTab] = useState<"all" | "stock" | "etf">("all");
  const [holdingsDetailOpen, setHoldingsDetailOpen] = useState(false);
  const [riskFocus, setRiskFocus] = useState<RiskFocus>("all");
  const [portfolioAnalysisTab, setPortfolioAnalysisTab] = useState<PortfolioAnalysisTab>("benchmark");
  const [data, setData] = useState<any>(_bootHoldings ?? { items: [], summary: {} });
  const [loading, setLoading] = useState(!_bootHoldings);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<EditableHolding | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [deleteConfirmKey, setDeleteConfirmKey] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [addSaving, setAddSaving] = useState(false);
  const [sectorData, setSectorData] = useState<any>(null);
  const [benchmarkData, setBenchmarkData] = useState<any>(null);
  const [riskNote, setRiskNote] = useState("");
  const [refreshingAllQuotes, setRefreshingAllQuotes] = useState(false);
  const [usdToKrw, setUsdToKrw] = useState<{ rate: number; date: string } | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importMarket, setImportMarket] = useState<"kr" | "us">("kr");
  const [importCsvText, setImportCsvText] = useState("");
  const [importSaving, setImportSaving] = useState(false);
  const [brokerSyncing, setBrokerSyncing] = useState<string | null>(null);
  const [positionCandidates, setPositionCandidates] = useState<any[]>([]);
  const [kellyOpen, setKellyOpen] = useState(false);
  const [riskBudgetOpen, setRiskBudgetOpen] = useState(false);
  const [navChartOpen, setNavChartOpen] = useState(false);
  const [positionLoading, setPositionLoading] = useState(false);
  const [holdingsLoadedAt, setHoldingsLoadedAt] = useState("");
  const [exitSignals, setExitSignals] = useState<Record<string, any>>({});
  const [kellySizes, setKellySizes] = useState<any>(null);
  const [riskBudget, setRiskBudget] = useState<any>(null);
  const [soldHistory, setSoldHistory] = useState<any>(null);
  const [brokerConnections, setBrokerConnections] = useState<BrokerStatus[]>([]);
  // 서버가 보유를 서빙하면(로컬 CSV 또는 로그인 DB) 그대로 표시한다.
  // 로그인 게이팅은 서버(authRequired)가 담당하고, 여기서는 받은 items를 렌더한다.
  const items = useMemo(() => (
    dedupe(Array.isArray(data.items) ? data.items : [])
  ), [data.items]);
  const isPersonalHoldingsSource = String(data.authority || data.routeVersion || "").toLowerCase().includes("personal");

  function mergeEditableRows(rows: any[]) {
    const displayMap = new Map(items.map((item: any) => [editableKey(item), item]));
    return rows.map((row) => {
      const match = displayMap.get(editableKey(row));
      if (!match) return row;
      // 서버 row의 빈 값이 화면(match)의 기존 값을 덮지 않도록
      // stop/target은 서버값 → 화면값 → "" 순으로 fallback
      const stopVal = row.stopPrice || match.stopPrice || match.stop || "";
      const targetVal = row.targetPrice || match.targetPrice || match.target || "";
      return {
        ...row,
        market: row.market || match.market,
        symbol: row.symbol || match.symbol,
        name: row.name || match.name,
        quantity: row.quantity ?? match.quantity,
        avgPrice: row.avgPrice ?? match.avgPrice,
        stopPrice: stopVal,
        targetPrice: targetVal,
      };
    });
  }

  async function loadPositionCandidates(nextMarket: Market) {
    setPositionLoading(true);
    try {
      const markets = nextMarket === "all" ? ["kr", "us"] : [nextMarket];
      const results = await Promise.all(
        markets.map((m) => mone.homeSummary({ market: m as any, limit: 12 }).catch(() => null))
      );
      setPositionCandidates(dedupe(results.flatMap((result) => extractPositionCandidates(result))));
    } catch {
      setPositionCandidates([]);
    } finally {
      setPositionLoading(false);
    }
  }

  async function load(options: { background?: boolean } = {}) {
    // 토큰이 없어도 먼저 서버에 요청한다. 서버가 익명으로 보유를 서빙하면(로컬 CSV 원장)
    // 그대로 표시하고, authRequired(배포 익명)면 로그인 안내로 폴백한다.
    const cached = readHoldingsCache(market);
    if (cached && !options.background) {
      setData(cached.data);
      setHoldingsLoadedAt(cached.loadedAt);
      setLoading(false);
    } else if (!cached) {
      setLoading(true);
    }
    try {
      const result = await getJson(`/api/holdings-clean?market=${market}&limit=500`);
      const serverItems = Array.isArray(result.items) ? result.items : [];
      const localItems = loadHoldingsFromLocalStorage();
      let finalData: any;
      if (result?.authRequired && serverItems.length === 0) {
        // 서버가 보유를 노출하지 않음(로그인 필요). 로컬 백업이 있으면 표시, 없으면 로그인 안내.
        if (localItems.length > 0) {
          finalData = localHoldingsPayload(localItems, market);
          setData(finalData);
        } else {
          setData(emptyHoldingsPayload(market, true));
          setHoldingsLoadedAt(new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }));
          setBrokerConnections([]);
          setSectorData(null);
          setBenchmarkData(null);
          setRiskBudget(null);
          setSoldHistory(null);
          setLoading(false);
          return;
        }
      } else {
        if (serverItems.length > 0) saveHoldingsToLocalStorage(serverItems);
        finalData = result;
        setData(finalData);
      }
      const loadedAt = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
      setHoldingsLoadedAt(loadedAt);
      writeHoldingsCache(market, finalData, loadedAt);
      loadPositionCandidates(market);
      setLoading(false);
      // 청산 신호 비동기 로딩
      getJson(`/api/holdings/exit-signals?market=${market}`).then((res) => {
        if (Array.isArray(res?.signals)) {
          const map: Record<string, any> = {};
          for (const sig of res.signals) {
            map[`${sig.market}-${sig.symbol}`] = sig;
          }
          setExitSignals(map);
        }
      }).catch(() => {});
      getJson(`/api/portfolio/risk-budget?market=${market}`).then((res) => {
        if (res?.status) {
          setRiskBudget(res);
          if (Array.isArray(res.sectors) && res.sectors.length > 0) {
            setSectorData({ status: res.status, sectors: res.sectors });
          }
        }
      }).catch(() => setRiskBudget(null));
      getJson(`/api/holdings/sold-history?market=${market === "all" ? "all" : market}`).then((res) => {
        if (res?.status === "OK") setSoldHistory(res);
      }).catch(() => setSoldHistory(null));
      setRiskNote(market === "all" ? "전체 보기에서는 KR/US 보유를 함께 확인합니다. 통화 합산이 필요한 금액은 별도 안내합니다." : "");
      // 리스크 데이터는 백그라운드 로딩
      getJson(`/api/risk/benchmark?market=${market}`).then(setBenchmarkData).catch((error) => {
        setBenchmarkData({ status: "ERROR", error: String(error), items: [] });
      });
    } catch (error) {
      const localItems = hasHoldingsAuth ? loadHoldingsFromLocalStorage() : [];
      setData(localItems.length > 0
        ? localHoldingsPayload(localItems, market)
        : { status: "ERROR", error: String(error), items: [], summary: {} });
      setHoldingsLoadedAt(new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }));
      setLoading(false);
    }
  }

  useEffect(() => {
    const hasCached = Boolean(_bootHoldings || readHoldingsCache(market));
    load({ background: hasCached });
  }, [market, hasHoldingsAuth]);

  useEffect(() => {
    if (!userToken) {
      setBrokerConnections([]);
      return;
    }
    import("@/lib/api").then(({ mone }) =>
      mone.brokerConnections(userToken)
        .then((res: any) => setBrokerConnections(Array.isArray(res?.connections) ? res.connections : Array.isArray(res) ? res : []))
        .catch(() => setBrokerConnections([]))
    );
  }, [userToken]);

  // Kelly 포지션 사이즈 마운트 시 1회 fetch
  useEffect(() => {
    getJson("/api/advanced/kelly-sizes").then((res) => {
      if (res?.kellySizes) setKellySizes(res.kellySizes);
    }).catch(() => {});
  }, []);

  // 환율은 마운트 시 1회만 fetch (4시간 캐시)
  useEffect(() => {
    import("@/lib/api").then(({ mone }) =>
      mone.exchangeRate({ base: "USD", target: "KRW" })
        .then((r) => { if (r?.rate) setUsdToKrw({ rate: r.rate, date: r.date || "" }); })
        .catch(() => {})
    );
  }, []);

  async function loadEditableHoldings() {
    if (!hasHoldingsAuth) return [];
    try {
      const result = await getJson("/api/holdings-edit?market=all");
      return Array.isArray(result.items) ? mergeEditableRows(result.items.map(toEditableHolding)) : [];
    } catch {
      return loadHoldingsFromLocalStorage().map(toEditableHolding);
    }
  }

  async function saveRows(nextRows: any[], successMsg: string) {
    if (!hasHoldingsAuth) {
      setMessage("로그인 후 보유종목을 저장할 수 있습니다.");
      return;
    }
    // localStorage에 먼저 백업
    saveHoldingsToLocalStorage(nextRows);
    try {
      const result = await postJson("/api/holdings-edit/save", { items: nextRows });
      if (result?.status === "ERROR") throw new Error(result.error || "저장 실패");
      setMessage(successMsg);
    } catch (err) {
      // 서버 저장 실패 시 localStorage 백업 안내
      setMessage(`⚠ 서버 저장에 실패했지만 이 기기에는 임시 저장됐습니다. (${err instanceof Error ? err.message : "네트워크 오류"})`);
    }
    await load();
  }

  async function saveEdit(original: any) {
    if (!editDraft) return;
    const err = validateHoldingDraft(editDraft);
    if (err) { setMessage(err); return; }
    const key = editableKey(original);
    setSavingKey(key); setMessage("");
    try {
      const rows = await loadEditableHoldings();
      const n = normalizeForSave(editDraft);
      const nextRows = rows.filter((r) => editableKey(r) !== key)
        .concat([{ market: n.market, symbol: n.symbol, name: n.name, quantity: String(n.quantity), avgPrice: String(n.avgPrice), stopPrice: String(n.stopPrice ?? ""), targetPrice: String(n.targetPrice ?? "") }]);
      await saveRows(nextRows, "보유종목을 저장했습니다.");
      setEditKey(null); setEditDraft(null);
    } catch (error) {
      setMessage(`저장 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setSavingKey(null); }
  }

  async function deleteHolding(holding: any) {
    const key = editableKey(holding);
    setSavingKey(key); setMessage(""); setDeleteConfirmKey(null);
    try {
      const rows = await loadEditableHoldings();
      const nextRows = rows.filter((r) => editableKey(r) !== key);
      await saveRows(nextRows, "보유종목을 삭제했습니다.");
      if (editKey === key) { setEditKey(null); setEditDraft(null); }
    } catch (error) {
      setMessage(`삭제 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setSavingKey(null); }
  }

  async function refreshOneQuote(holding: any) {
    const key = editableKey(holding);
    setSavingKey(key); setMessage("");
    try {
      const res = await postJson("/api/quotes/refresh-one", { symbol: holding.symbol, market: holding.market, name: displayName(holding) });
      if (res?.status === "OK" || res?.quote?.ok) {
        setMessage(`${displayName(holding)} 현재가 새로고침 완료`);
        await load();
      } else {
        setMessage(`현재가 조회 실패: ${res?.error || res?.quote?.error || "알 수 없는 오류"}`);
      }
    } catch (error) {
      setMessage(`새로고침 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setSavingKey(null); }
  }

  async function refreshVisibleQuotes() {
    const m = market === "all" ? "all" : market;
    setRefreshingAllQuotes(true); setMessage("");
    try {
      const res = await postJson("/api/quotes/refresh-targets", { market: m, limit: 30 });
      setMessage(`현재가 수동 갱신: 성공 ${res?.successCount ?? 0}건 / 실패 ${res?.failureCount ?? 0}건 / 대기 ${res?.pendingCount ?? 0}건`);
      await load();
    } catch (error) {
      setMessage(`현재가 수동 갱신 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setRefreshingAllQuotes(false);
    }
  }

  async function syncBrokerHoldings(broker: string) {
    if (!userToken) {
      setMessage("로그인 후 계좌 연동을 사용할 수 있습니다.");
      return;
    }
    const brokerName = broker === "toss" ? "토스증권" : "한국투자";
    setBrokerSyncing(broker); setMessage("");
    try {
      const res = await import("@/lib/api").then(({ mone }) => mone.brokerSyncHoldings(userToken, { broker }));
      if (!res?.ok) throw new Error(res?.message || res?.error || `${brokerName} 브릿지 스냅샷 확인 실패`);
      setMessage(res.message || `${brokerName} 로컬 브릿지 스냅샷이 반영되어 있습니다.`);
      await load();
      window.dispatchEvent(new CustomEvent("mone-holdings-updated"));
    } catch (error) {
      setMessage(`${brokerName} 브릿지 확인 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setBrokerSyncing(null); }
  }

  async function importCsv() {
    if (!importCsvText.trim()) { setMessage("CSV 텍스트를 입력해 주세요."); return; }
    setImportSaving(true); setMessage("");
    try {
      const res = await import("@/lib/api").then(({ mone }) =>
        mone.importHoldingsCsv({ market: importMarket, csv_text: importCsvText, mode: "merge" })
      );
      if (res?.status === "ERROR") throw new Error(res.error || "CSV 가져오기 실패");
      setMessage(`CSV 가져오기 완료 — 추가 ${res.added ?? 0}개, 갱신 ${res.updated ?? 0}개 (${importMarket === "kr" ? "국장" : "미장"})`);
      setImportCsvText(""); setShowImport(false);
      await load();
    } catch (error) {
      setMessage(`CSV 가져오기 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setImportSaving(false); }
  }

  async function addHolding(draft: EditableHolding) {
    setAddSaving(true); setMessage("");
    try {
      const rows = await loadEditableHoldings();
      const n = normalizeForSave(draft);
      const key = `${n.market}-${n.symbol}`;
      const nextRows = rows.filter((r) => editableKey(r) !== key)
        .concat([{ market: n.market, symbol: n.symbol, name: n.name, quantity: String(n.quantity), avgPrice: String(n.avgPrice), stopPrice: String(n.stopPrice ?? ""), targetPrice: String(n.targetPrice ?? "") }]);
      await saveRows(nextRows, `${n.name || n.symbol} 종목을 추가했습니다.`);
      setShowAdd(false);
    } catch (error) {
      setMessage(`추가 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setAddSaving(false); }
  }

  const summary = data.summary || {};
  const tossStatus = brokerConnections.find((conn) => conn.broker === "toss");
  const kisStatus = brokerConnections.find((conn) => conn.broker === "kis");
  // 보유 데이터 신선도는 개별 종목이 실제로 쓴 가격 기준일 중 '가장 최신'을 대표로
  // 삼는다. items[0] 하나만 보면 첫 종목이 유독 오래된 경우(비유동 종목 등) 포트폴리오
  // 전체가 "오래됨"으로 오표시됐다. ISO(YYYY-MM-DD)는 사전식 정렬 = 시간순 정렬.
  const freshestHoldingDate = items
    .map((i: any) => String(i?.latestDataDate || i?.priceDate || i?.ohlcvLatestDate || i?.date || ""))
    .filter((d: string) => /^\d{4}-\d{2}-\d{2}/.test(d))
    .sort()
    .pop();
  // holdingsLoadedAt은 "이 페이지를 언제 열었나"를 뜻하는 클라이언트 벽시계 값이다.
  // 보유가 0개(비로그인/빈 상태)일 때 이 값이 동기화·데이터 기준으로 새어 들어가면
  // "데이터가 없는데 방금 갱신됨"처럼 보인다. 실제 보유가 있을 때만 스탬프로 쓴다.
  const holdingsStamp = items.length > 0 ? holdingsLoadedAt : "";
  const holdingFreshness = dataFreshnessInfo({
    latestDataDate: summary.latestDataDate || summary.ohlcvLatestDate || freshestHoldingDate || items[0]?.date,
    recoGeneratedAt: summary.updatedAt || data.updatedAt || holdingsStamp,
    dataStatus: data.status,
  });
  const holdingsSourceInfo = useMemo(() => {
    const authorityRaw = firstSourceText(data.holdingAuthority, summary.holdingAuthority, data.authority, data.routeVersion);
    const sourceRaw = firstSourceText(data.sourceSummary, summary.sourceSummary, data.dataSource, summary.dataSource, data.source, summary.source);
    const brokerRaw = firstSourceText(data.broker, summary.broker, data.sourceBroker, summary.sourceBroker, items[0]?.broker, items[0]?.sourceBroker);
    const syncedRaw = firstSourceText(data.syncedAt, summary.syncedAt, data.updatedAt, summary.updatedAt, holdingsStamp);
    const primary = humanDataSourceLabel(brokerRaw || sourceRaw || authorityRaw, isPersonalHoldingsSource ? "개인 보유 DB" : "보유 데이터");
    return {
      primary,
      authority: humanDataSourceLabel(authorityRaw, isPersonalHoldingsSource ? "개인 보유 DB" : "권한 확인"),
      source: humanDataSourceLabel(sourceRaw || brokerRaw, primary),
      synced: shortSourceDate(syncedRaw),
    };
  }, [data, summary, items, holdingsLoadedAt, isPersonalHoldingsSource]);
  const riskSourceInfo = useMemo(() => {
    const sourceRaw = firstSourceText(riskBudget?.sourceSummary, riskBudget?.dataSource, riskBudget?.source, riskBudget?.holdingAuthority);
    const syncedRaw = firstSourceText(riskBudget?.syncedAt, riskBudget?.updatedAt, riskBudget?.asOf, holdingsStamp);
    return {
      source: humanDataSourceLabel(sourceRaw || holdingsSourceInfo.source, holdingsSourceInfo.source),
      scope: market === "all" ? (summary.mixedCurrency ? "KR/US 통화 분리" : "전체") : market === "kr" ? "국장" : "미장",
      synced: shortSourceDate(syncedRaw) || holdingsSourceInfo.synced,
    };
  }, [riskBudget, holdingsSourceInfo, holdingsLoadedAt, market, summary.mixedCurrency]);
  const riskCount = Number(summary.riskCount ?? items.filter((item) => normalizeRiskStatus(item.riskStatus) !== "NORMAL").length);
  // 혼합통화(KR 원화 + US 달러)일 때 환율로 합산한 KRW 총액·손익.
  // 환율을 아직 못 받았으면 null → 상단 카드는 통화별 분리 배너에 위임한다.
  const combinedKrw = useMemo(() => {
    if (!summary.mixedCurrency || !usdToKrw?.rate) return null;
    const bd = Array.isArray(summary.marketBreakdown) ? summary.marketBreakdown : [];
    const us = bd.find((b: any) => b.market === "us");
    const kr = bd.find((b: any) => b.market === "kr");
    const value = Number(kr?.totalValue || 0) + Number(us?.totalValue || 0) * usdToKrw.rate;
    const pnl = Number(kr?.totalPnl || 0) + Number(us?.totalPnl || 0) * usdToKrw.rate;
    return { value, pnl };
  }, [summary.mixedCurrency, summary.marketBreakdown, usdToKrw]);
  const totalValueText = combinedKrw
    ? `${Math.round(combinedKrw.value).toLocaleString("ko-KR")}원`
    : summary.totalValueText || (items.length > 0 ?
      items.reduce((acc: number, item: any) => acc + Number(item.valuation || item.marketValue || 0), 0).toLocaleString("ko-KR") + "원" : "-");
  const totalPnlText = combinedKrw
    ? `${combinedKrw.pnl >= 0 ? "+" : ""}${Math.round(combinedKrw.pnl).toLocaleString("ko-KR")}원`
    : (summary.totalPnlText || "-");
  const totalPnlAccent = combinedKrw
    ? (combinedKrw.pnl >= 0 ? "text-emerald-300" : "text-red-300")
    : summary.mixedCurrency
      ? "text-slate-300"
      : Number(summary.totalPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300";
  const totalPnlPctText = summary.totalPnlPctText || summary.totalPnlPercentText || (() => {
    // 혼합통화일 때 KR·US 원가를 그냥 더하면 안 된다(₩1 ≠ $1). combinedKrw.value/pnl과
    // 동일하게 US 쪽만 환율을 곱해 KRW로 맞춘 뒤 합산해야 분모·분자 통화가 일치한다.
    const fx = combinedKrw && usdToKrw?.rate ? usdToKrw.rate : 1;
    const costBasis = items.reduce((sum: number, item: any) => {
      const raw = Number(item.avgPrice || 0) * Number(item.quantity || 0);
      const itemMarket = cleanHoldingMarket(item.market);
      return sum + (itemMarket === "us" ? raw * fx : raw);
    }, 0);
    const pnl = combinedKrw ? combinedKrw.pnl : Number(summary.totalPnl || 0);
    if (!Number.isFinite(costBasis) || costBasis <= 0 || !Number.isFinite(pnl)) return "수익률 확인 중";
    const pct = (pnl / costBasis) * 100;
    return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
  })();
  const showPersonalEmptyNotice = !loading && items.length === 0 && isPersonalHoldingsSource;

  const riskBudgetByHolding = useMemo(() => {
    const mapped = new Map<string, any>();
    for (const item of Array.isArray(riskBudget?.items) ? riskBudget.items : []) {
      const itemMarket = cleanHoldingMarket(item.market);
      const itemSymbol = cleanHoldingSymbol(item.symbol, itemMarket);
      mapped.set(`${itemMarket}:${itemSymbol}`, item);
    }
    return mapped;
  }, [riskBudget]);

  const holdingRiskScore = (holding: any) => {
    const holdingMarket = cleanHoldingMarket(holding.market);
    const holdingSymbol = cleanHoldingSymbol(holding.symbol, holdingMarket);
    const budget = riskBudgetByHolding.get(`${holdingMarket}:${holdingSymbol}`);
    const signal = exitSignals[`${holdingMarket}-${holding.symbol}`];
    const risk = normalizeRiskStatus(holding.riskStatus);
    const stopGap = holding.downsideGapPct != null ? Number(holding.downsideGapPct) : holding.stopGapPct != null ? Number(holding.stopGapPct) : null;
    const value = Number(holding.valuation || holding.marketValue || 0);
    const total = items.reduce((sum, item) => sum + Number(item.valuation || item.marketValue || 0), 0);
    const weight = total > 0 ? (value / total) * 100 : 0;
    let score = 0;

    if (signal?.signal === "SELL_STRONG") score += 3000;
    else if (signal?.signal === "SELL") score += 2200;
    else if (signal?.signal === "PARTIAL_EXIT") score += 1500;
    if (budget?.action === "REDUCE") score += 1800;
    score += Math.min(900, Math.max(0, Number(budget?.lossBudgetPct || 0) * 180));
    if (risk === "STOP_LOSS_DELAY") score += 1400;
    else if (risk === "HIGH") score += 1000;
    else if (risk === "WATCH") score += 500;
    if (stopGap !== null && stopGap <= 2) score += 400;
    else if (stopGap !== null && stopGap <= 5) score += 200;
    if (!holding.currentPrice || Number(holding.currentPrice) <= 0) score += 300;
    if (!(holding.downsideLine ?? holding.stopPrice ?? holding.stop ?? 0)) score += 150;
    if (weight > Number(riskBudget?.policy?.maxPositionWeightPct || 20)) score += 120;
    return score;
  };

  const matchesRiskFocus = (holding: any, focus: Exclude<RiskFocus, "all">) => {
    const holdingMarket = cleanHoldingMarket(holding.market);
    const holdingSymbol = cleanHoldingSymbol(holding.symbol, holdingMarket);
    const budget = riskBudgetByHolding.get(`${holdingMarket}:${holdingSymbol}`);
    const totalValue = items.reduce((sum, item) => sum + Number(item.valuation ?? item.marketValue ?? 0), 0);

    if (focus === "stop") {
      const maxLossPct = Number(riskBudget?.policy?.maxPositionLossPct || 2);
      const usesDefaultStop = Array.isArray(budget?.reasons)
        && budget.reasons.some((reason: unknown) => String(reason).toLowerCase().includes("default stop"));
      return budget
        ? Number(budget.lossBudgetPct || 0) > maxLossPct || !budget.stopPrice || usesDefaultStop
        : !holding.stopPrice || Number(holding.stopPrice) <= 0;
    }
    if (focus === "rebalance") {
      const maxWeightPct = Number(riskBudget?.policy?.maxPositionWeightPct || 20);
      const holdingValue = Number(holding.valuation ?? holding.marketValue ?? 0);
      const weightPct = totalValue > 0 ? (holdingValue / totalValue) * 100 : 0;
      return budget
        ? budget.action === "REDUCE" || Number(budget.weightPct || 0) > maxWeightPct
        : weightPct > maxWeightPct;
    }
    return !holding.currentPrice || Number(holding.currentPrice) <= 0;
  };

  const focusedHoldings = riskFocus === "all"
    ? items
    : items.filter((holding) => matchesRiskFocus(holding, riskFocus));

  const { individualStocks, etfHoldings } = useMemo(() => {
    const stocks: any[] = [];
    const etfs: any[] = [];

    for (const item of focusedHoldings) {
      const assetType = normalizedHoldingAssetType(item);
      const isEtf = assetType.includes("etf");
      if (isEtf) {
        etfs.push({ ...item, assetType });
      } else {
        stocks.push({ ...item, assetType });
      }
    }

    const byRisk = (a: any, b: any) => holdingRiskScore(b) - holdingRiskScore(a)
      || Number(b.valuation || b.marketValue || 0) - Number(a.valuation || a.marketValue || 0);
    stocks.sort(byRisk);
    etfs.sort(byRisk);

    return { individualStocks: stocks, etfHoldings: etfs };
  }, [focusedHoldings, riskBudgetByHolding, exitSignals, riskBudget]);
  const actionItems = useMemo(() => {
    const rows: { key: string; tone: "red" | "amber" | "blue"; title: string; detail: string; action?: "stop" | "target" }[] = [];
    for (const holding of items) {
      const name = displayName(holding);
      const symbol = String(holding.symbol || "");
      const assetType = normalizedHoldingAssetType(holding);
      const isEtf = assetType.includes("etf");
      const downsideLabel = String(holding.downsideLineLabel || (isEtf ? "리스크 기준선" : "손절선"));
      const upsideLabel = String(holding.upsideLineLabel || (isEtf ? "수익실현 기준선" : "목표가"));
      const hasDownside = Number(holding.downsideLine ?? holding.stopPrice ?? holding.stop ?? 0) > 0;
      const hasUpside = Number(holding.upsideLine ?? holding.targetPrice ?? holding.target ?? 0) > 0;
      const downsideMissing = !hasDownside;
      const targetMissing = !hasUpside;
      const stopGapPct = holding.downsideGapPct != null ? Number(holding.downsideGapPct) : holding.stopGapPct != null ? Number(holding.stopGapPct) : null;
      const targetGapPct = holding.targetGapPct != null ? Number(holding.targetGapPct) : null;
      if (!holding.currentPrice || Number(holding.currentPrice) <= 0) {
        rows.push({ key: `${symbol}-price`, tone: "amber", title: `${name} 갱신 필요`, detail: "현재가 없음 · 수동 갱신 또는 다음 수집 필요" });
      }
      if (downsideMissing) rows.push({ key: `${symbol}-stop`, tone: "amber", title: `${name} ${downsideLabel} 필요`, detail: isEtf ? "ETF 비중 조절 기준 없음" : "보유 리스크 판단 기준 없음", action: "stop" });
      if (targetMissing) rows.push({ key: `${symbol}-target`, tone: "blue", title: `${name} ${upsideLabel} 필요`, detail: isEtf ? "ETF 상단 조절 기준 없음" : "익절 판단 기준 없음", action: "target" });
      if (stopGapPct !== null && stopGapPct <= 2) {
        rows.push({ key: `${symbol}-stop-near`, tone: "red", title: `${name} ${downsideLabel} 근접`, detail: `${stopGapPct.toFixed(2)}% 여유` });
      } else if (stopGapPct !== null && stopGapPct <= 5) {
        rows.push({ key: `${symbol}-stop-watch`, tone: "amber", title: `${name} ${downsideLabel} 주의`, detail: `${stopGapPct.toFixed(2)}% 여유` });
      }
      if (targetGapPct !== null && targetGapPct >= 0 && targetGapPct <= 3) {
        rows.push({ key: `${symbol}-target-near`, tone: "blue", title: `${name} ${upsideLabel} 근접`, detail: `${targetGapPct.toFixed(2)}% 남음` });
      }
    }
    return rows.slice(0, 8);
  }, [items]);

  const riskOverview = useMemo(() => {
    const needsStopReview = items.filter((holding) => matchesRiskFocus(holding, "stop")).length;
    const needsRebalance = items.filter((holding) => matchesRiskFocus(holding, "rebalance")).length;
    const needsPriceReview = items.filter((holding) => matchesRiskFocus(holding, "price")).length;

    return [
      { key: "stop", label: "손절 · 손실 예산 점검", count: needsStopReview, tone: "red" as const },
      { key: "rebalance", label: "비중 초과 · 리밸런싱", count: needsRebalance, tone: "amber" as const },
      { key: "price", label: "가격 데이터 갱신", count: needsPriceReview, tone: "amber" as const },
    ];
  }, [items, riskBudget, riskBudgetByHolding]);

  const visibleRiskLossPct = useMemo(() => {
    if (riskBudget && !riskBudget.authRequired) return Number(riskBudget.totalLossBudgetPct || 0);
    const total = items.reduce((sum, holding) => sum + Number(holding.valuation ?? holding.marketValue ?? 0), 0);
    if (total <= 0) return 0;
    const loss = items.reduce((sum, holding) => {
      const value = Number(holding.valuation ?? holding.marketValue ?? 0);
      const current = Number(holding.currentPrice || 0);
      const stop = Number(holding.stopPrice || holding.stop || 0);
      const quantity = Number(holding.quantity || 0);
      return sum + (current > 0 && stop > 0 && quantity > 0 ? Math.max(0, current - stop) * quantity : value * 0.08);
    }, 0);
    return (loss / total) * 100;
  }, [items, riskBudget]);

  const visibleRiskSummary = useMemo(() => {
    if (riskBudget && !riskBudget.authRequired) {
      return {
        total: Number(riskBudget.totalValue || 0),
        lossAmount: Number(riskBudget.totalLossAmount || 0),
        missingStops: Number(riskBudget.missingStopCount || 0),
      };
    }
    const total = items.reduce((sum, holding) => sum + Number(holding.valuation ?? holding.marketValue ?? 0), 0);
    const missingStops = items.filter((holding) => Number(holding.stopPrice || holding.stop || 0) <= 0).length;
    return { total, lossAmount: total * visibleRiskLossPct / 100, missingStops };
  }, [items, visibleRiskLossPct, riskBudget]);

  const previewHoldings = useMemo(() => (
    [...items]
      .sort((a, b) => holdingRiskScore(b) - holdingRiskScore(a)
        || Number(b.valuation || b.marketValue || 0) - Number(a.valuation || a.marketValue || 0))
      .slice(0, 3)
  ), [items, riskBudgetByHolding, exitSignals, riskBudget]);
  const riskFocusLabel: Record<Exclude<RiskFocus, "all">, string> = {
    stop: "손절 · 손실 예산 점검",
    rebalance: "비중 초과 · 리밸런싱",
    price: "가격 데이터 갱신",
  };

  const personalBenchmarkItems = useMemo(() => {
    const apiItems = Array.isArray(benchmarkData?.items) ? benchmarkData.items : [];
    if (apiItems.length > 0) {
      return apiItems.map((item: any) => ({
        symbol: String(item.symbol || ""),
        name: String(item.name || item.symbol || ""),
        portfolioReturn: Number(item.portfolioReturn),
        benchmarkReturn: Number(item.benchmarkReturn),
        alpha: Number(item.alpha),
        benchmarkName: String(item.benchmarkName || benchmarkData?.benchmark || ""),
      })).filter((item: any) => Number.isFinite(item.portfolioReturn) && Number.isFinite(item.benchmarkReturn) && Number.isFinite(item.alpha));
    }
    const benchmarkReturn = Number(benchmarkData?.benchmarkReturn);
    if (!Number.isFinite(benchmarkReturn)) return [];
    return items.map((holding: any) => {
      const current = Number(holding.currentPrice || 0);
      const average = Number(holding.avgPrice || holding.averagePrice || 0);
      const directReturn = Number(holding.pnlPct ?? holding.returnPct ?? holding.profitLossRate);
      const portfolioReturn = Number.isFinite(directReturn)
        ? directReturn
        : current > 0 && average > 0 ? ((current - average) / average) * 100 : null;
      return {
        symbol: String(holding.symbol || ""),
        name: displayName(holding),
        portfolioReturn,
        benchmarkReturn,
        alpha: portfolioReturn == null ? null : portfolioReturn - benchmarkReturn,
      };
    }).filter((item) => item.portfolioReturn != null);
  }, [items, benchmarkData]);

  const portfolioSectors = useMemo(() => {
    const budgetSectors = Array.isArray(riskBudget?.sectors) ? riskBudget.sectors : [];
    if (budgetSectors.length > 0) return budgetSectors.map((sector: any) => ({
      sector: koreanSectorLabel(sector.sector),
      pct: Number(sector.weightPct || 0),
      status: sector.status || "OK",
      symbols: [] as string[],
    }));
    return Array.isArray(sectorData?.sectors) ? sectorData.sectors.map((sector: any) => ({ ...sector, sector: koreanSectorLabel(sector.sector, sector.symbols) })) : [];
  }, [riskBudget, sectorData]);

  const portfolioSnapshot = useMemo(() => {
    const valued = [...items]
      .map((holding) => Number(holding.valuation ?? holding.marketValue ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((a, b) => b - a);
    const total = valued.reduce((sum, value) => sum + value, 0);
    const share = (start: number, end: number) => total > 0
      ? (valued.slice(start, end).reduce((sum, value) => sum + value, 0) / total) * 100
      : 0;
    const alphaItems = personalBenchmarkItems.filter((item: any) => Number.isFinite(Number(item?.alpha)));
    const averageAlpha = alphaItems.length > 0
      ? alphaItems.reduce((sum: number, item: any) => sum + Number(item.alpha), 0) / alphaItems.length
      : null;
    return {
      total,
      top5Pct: share(0, 5),
      middlePct: share(5, 10),
      lowerPct: share(10, valued.length),
      averageAlpha,
    };
  }, [items, personalBenchmarkItems]);

  function openEditFromAction(actionKey: string) {
    const symbol = actionKey.replace(/-(stop|target|price|stop-near|stop-watch|target-near)$/g, "");
    const holding = items.find((item) => String(item.symbol || "") === symbol);
    if (!holding) return;
    const key = editableKey(holding);
    setEditKey(key);
    setEditDraft(toEditableHolding(holding));
    setDeleteConfirmKey(null);
    setMessage("");
  }

  function openHoldingsDetail(focus: RiskFocus = "all") {
    setRiskFocus(focus);
    setHoldingsDetailOpen(true);
    window.setTimeout(() => {
      document.getElementById("holdings-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
  }

  function selectMarket(mode: MarketMode) {
    setMarketMode(mode);
    setMarket(mode);
  }

  return (
    <div className="mone-home flex flex-col gap-4">
      {/* 헤더 */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="mone-page-title">보유·리스크</h1>
          <p className="mone-page-subtitle">보유 현황과 오늘의 리스크를 한눈에 확인하세요.</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => load()}
            title="보유 데이터 새로고침"
            aria-label="보유 데이터 새로고침"
            className="mone-home-inset inline-flex size-9 items-center justify-center rounded-[8px] border text-slate-400 transition-[color,transform] hover:text-slate-100 active:scale-[0.96]"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      <div className="mone-market-tabs">
        {([
          { key: "all", label: "전체" },
          { key: "kr", label: "국장" },
          { key: "us", label: "미장" },
        ] as const).map((item) => (
          <button key={item.key} type="button" onClick={() => selectMarket(item.key)}
            className={`active:scale-[0.96] ${marketMode === item.key ? "mone-selection-brand" : "text-slate-400 hover:text-slate-300"}`}>
            {item.label}
          </button>
        ))}
      </div>

      <section className={`${items.length === 0 ? "order-0" : "order-last"} mone-home-card p-3.5`}>
        <h2 className="mone-home-section-title">{items.length === 0 ? "보유 시작" : "계좌 · 데이터 관리"}</h2>
        {items.length === 0 && (
          <p className="mt-1 text-xs leading-5 text-slate-400">증권사 계좌를 연결하거나 보유 종목을 직접 추가해 포트폴리오 분석을 시작하세요.</p>
        )}
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => onNavigate?.("broker")}
            className="mone-home-inset flex min-h-[76px] items-center gap-3 rounded-[10px] border px-3 text-left transition-colors hover:bg-slate-900/45"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-teal-400/10 text-teal-300"><Link2 size={19} /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-[12px] font-semibold text-slate-100">증권사 연동</span>
              <span className="mt-1 block truncate text-[10px] text-slate-400">{tossStatus?.connected || kisStatus?.connected ? "연결 상태 확인" : "보유 데이터 자동 연동"}</span>
            </span>
            <ChevronRight size={14} className="shrink-0 text-slate-400" />
          </button>
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="mone-home-inset flex min-h-[76px] items-center gap-3 rounded-[10px] border px-3 text-left transition-colors hover:bg-slate-900/45"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-full bg-teal-400/10 text-teal-300"><Plus size={20} /></span>
            <span className="min-w-0 flex-1">
              <span className="block text-[12px] font-semibold text-slate-100">직접 추가</span>
              <span className="mt-1 block truncate text-[10px] text-slate-400">보유 종목을 직접 입력</span>
            </span>
            <ChevronRight size={14} className="shrink-0 text-slate-400" />
          </button>
        </div>
      </section>

      {/* 종목 추가 폼 */}
      {showAdd && <AddHoldingForm onSave={addHolding} onCancel={() => setShowAdd(false)} saving={addSaving} />}

      {/* CSV 가져오기 패널 */}
      {showImport && (
        <div className="rounded-2xl border border-violet-500/30 bg-violet-500/5 p-5">
          <div className="mb-3 text-sm font-bold text-violet-200">보유종목 가져오기 (나무·토스·키움 등)</div>
          <p className="mb-4 text-xs text-slate-400">
            증권사 앱/웹에서 보유종목 표를 복사해 아래에 붙여넣으세요.
            <br />헤더 포함 권장: <span className="font-mono text-slate-300">종목코드, 종목명, 수량, 평균단가</span>
            <br />헤더 없이 붙여넣으면 순서대로 <span className="font-mono text-slate-300">코드, 종목명, 수량, 평균단가</span> 로 처리합니다.
          </p>
          <div className="mb-3 flex items-center gap-3">
            <label className="text-xs text-slate-400">시장
              <select value={importMarket} onChange={(e) => setImportMarket(e.target.value as "kr" | "us")}
                className="ml-2 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-violet-400">
                <option value="kr">국장 (KR)</option>
                <option value="us">미장 (US)</option>
              </select>
            </label>
          </div>
          <textarea
            value={importCsvText}
            onChange={(e) => setImportCsvText(e.target.value)}
            placeholder={"종목코드\t종목명\t수량\t평균단가\n005930\t삼성전자\t10\t72000\n000660\tSK하이닉스\t5\t190000"}
            rows={7}
            className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-100 outline-none focus:border-violet-400"
          />
          <div className="mt-3 flex gap-2">
            <button onClick={importCsv} disabled={importSaving || !importCsvText.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-4 py-2 text-sm font-bold text-white hover:bg-violet-500 disabled:opacity-50">
              <FileText size={13} /> {importSaving ? "처리 중…" : "가져오기"}
            </button>
            <button onClick={() => { setShowImport(false); setImportCsvText(""); }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
              <X size={13} /> 취소
            </button>
          </div>
        </div>
      )}

      {/* 메시지 */}
      {message && (
        <div className={`flex items-center justify-between rounded-xl border px-4 py-3 text-sm ${
          message.startsWith("⚠") || message.includes("실패")
            ? toneClassName("danger")
            : "border-slate-700 bg-slate-900 text-slate-300"
        }`}>
          <span>{message}</span>
          <button onClick={() => setMessage("")} aria-label="알림 닫기" title="닫기" className="ml-3 shrink-0 text-slate-400 hover:text-slate-300"><X size={14} /></button>
        </div>
      )}

      {/* 요약 카드 */}
      {loading ? (
        <div className="grid grid-cols-2 gap-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-xl border border-slate-800 bg-slate-900 px-4 py-4">
              <div className="h-3 w-16 rounded bg-slate-700" />
              <div className="mt-2 h-6 w-24 rounded bg-slate-700" />
            </div>
          ))}
        </div>
      ) : items.length > 0 ? (
        <div className="grid grid-cols-2 gap-2">
          <SummaryCard label="총 평가금액" value={totalValueText} visual="value" />
          <SummaryCard label="총 평가손익" value={totalPnlText} accent={totalPnlAccent} subValue={totalPnlPctText} visual="pnl" />
          <SummaryCard label="보유 종목 수" value={`${items.length}개`} visual="holdings" />
          <SummaryCard label="주의/위험 종목 수" value={`${riskCount}개`} visual="risk"
            accent={riskCount > 0 ? "text-amber-300" : "text-emerald-300"} />
        </div>
      ) : null}

      <CashInputBar />

      {holdingsDetailOpen && soldHistory && soldHistory.count > 0 && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">매도 종목 실현손익 합계 (이 기능 도입 이후 매도분만)</span>
            <span className={`font-mono font-bold ${Number(soldHistory.totalRealizedPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
              {Number(soldHistory.totalRealizedPnl || 0) >= 0 ? "+" : ""}{Number(soldHistory.totalRealizedPnl || 0).toLocaleString("ko-KR")}
            </span>
          </div>
          <div className="mt-1 text-[11px] text-slate-600">위 평가손익은 현재 보유종목 기준입니다 — {soldHistory.note}</div>
        </div>
      )}

      <div className={`${holdingsDetailOpen ? "order-[80]" : "hidden"} mone-home-card p-3.5 text-xs text-slate-400`}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-200">보유 데이터 출처</span>
              <span className={`rounded-full border px-2 py-0.5 ${dataFreshnessBadgeClass(holdingFreshness.state)}`}>
                {holdingFreshness.label}
              </span>
            </div>
            <p className="mt-1 leading-5 text-slate-400">
              {holdingFreshness.basisText}
              {holdingsStamp ? ` · 목록 확인 ${holdingsStamp}` : ""}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <button onClick={() => load()}
              className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-[11px] text-slate-300 transition-[background-color,transform] hover:bg-slate-800 active:scale-[0.96]">
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> 새로고침
            </button>
            <button onClick={refreshVisibleQuotes} disabled={refreshingAllQuotes}
              className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2.5 py-1 text-[11px] text-blue-200 transition-[background-color,transform] hover:bg-blue-500/20 active:scale-[0.96] disabled:opacity-50">
              <Zap size={12} className={refreshingAllQuotes ? "animate-pulse" : ""} /> 현재가 갱신
            </button>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <SourceMini label="보유 출처" value={holdingsSourceInfo.primary} />
          <SourceMini label="권한 범위" value={holdingsSourceInfo.authority} />
          <SourceMini label="가격 기준" value={holdingFreshness.label} accent={holdingFreshness.state === "fresh" ? "text-emerald-300" : "text-amber-300"} />
          <SourceMini label="동기화" value={holdingsSourceInfo.synced || "확인 대기"} />
        </div>
      </div>

      {showPersonalEmptyNotice && (
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-xs leading-5 text-slate-400">
          <div className="font-semibold text-slate-200">이 브라우저의 개인 보유종목이 아직 비어 있습니다.</div>
          <p className="mt-1">공용 스냅샷이나 다른 사용자의 브릿지 데이터는 개인 보유와 자동으로 섞지 않습니다. 직접 추가, CSV 가져오기, 또는 브로커 연동 후 이 화면에 표시됩니다.</p>
        </div>
      )}

      {!loading && (
        <section className="mone-home-card p-3.5">
          <div className="flex items-center gap-2">
            <TriangleAlert size={18} className="text-amber-300" />
            <h2 className="mone-home-section-title">오늘 먼저 볼 리스크</h2>
            <span className={`ml-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${riskCount > 0 || actionItems.length > 0 ? toneClassName("warning") : toneClassName("safe")}`}>
              {riskCount > 0 || actionItems.length > 0 ? "주의 필요" : "정상"}
            </span>
            <button type="button" onClick={() => openHoldingsDetail()} className="ml-auto inline-flex items-center gap-0.5 text-[10.5px] font-semibold text-slate-400 hover:text-teal-300">
              전체 리스크 보기 <ChevronRight size={13} />
            </button>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {riskOverview.map((item) => {
              const isRed = item.tone === "red";
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => openHoldingsDetail(item.key as RiskFocus)}
                  className="mone-home-inset min-h-[86px] rounded-[10px] border px-2.5 py-3 text-left transition-colors hover:bg-slate-900/45"
                >
                  <span className={`block size-2 rounded-full ${isRed ? "bg-red-400" : "bg-amber-400"}`} />
                  <span className="mt-2 block break-keep text-[11px] font-semibold leading-4 text-slate-100">{item.label}</span>
                  <span className={`mt-2 inline-flex rounded-full border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${isRed ? "border-red-500/30 bg-red-500/10 text-red-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300"}`}>{item.count}종목</span>
                </button>
              );
            })}
          </div>
          {riskOverview.every((item) => item.count === 0) && (
            <p className="mt-2 text-[10px] text-emerald-300">현재 보유 기준으로 즉시 보정할 리스크 항목은 없습니다.</p>
          )}
          {holdingsDetailOpen && (
            <div className="mt-3 border-t border-slate-800/80 pt-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="mone-home-section-title">리스크 계산 기준</h2>
                <p className="mt-0.5 text-[10.5px] leading-5 text-slate-400">보유 출처와 같은 범위로 리스크 예산을 계산합니다.</p>
              </div>
              {riskBudget && (
                <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${riskBudget.status === "OVER_BUDGET" ? toneClassName("danger") : toneClassName("safe")}`}>
                  {riskBudget.status === "OVER_BUDGET" ? "예산 초과" : "정상"}
                </span>
              )}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <SourceMini label="리스크 출처" value={riskBudget?.authRequired && items.length > 0 ? "화면 보유 데이터" : riskSourceInfo.source} />
              <SourceMini label="계산 범위" value={riskSourceInfo.scope} />
              <SourceMini label="손실 예산" value={`${visibleRiskLossPct.toFixed(1)}%`} accent={visibleRiskLossPct > Number(riskBudget?.policy?.maxPortfolioLossPct || 6) ? "text-red-300" : "text-emerald-300"} />
              <SourceMini label="기준일" value={riskSourceInfo.synced || "확인 대기"} />
            </div>
            {riskBudget && (
              <button
                type="button"
                onClick={() => setRiskBudgetOpen((v) => !v)}
                className="mt-3 inline-flex min-h-9 w-full items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold text-slate-300 transition-[background-color,transform] hover:bg-slate-800 active:scale-[0.96]"
              >
                상세 리스크 예산 {riskBudgetOpen ? "접기" : "보기"}
                <ChevronDown size={14} className={`transition-transform ${riskBudgetOpen ? "rotate-180" : ""}`} />
              </button>
            )}
            {riskBudget && riskBudgetOpen && (
              <div className="mt-3 border-t border-slate-800 pt-3">
                <div className="grid gap-2 text-[11px] sm:grid-cols-3 lg:grid-cols-1">
                  <Mini label="예상 손실 예산" value={`${visibleRiskLossPct.toFixed(1)}% · ${Math.round(visibleRiskSummary.lossAmount).toLocaleString()}원`} accent={visibleRiskLossPct > Number(riskBudget.policy?.maxPortfolioLossPct || 6) ? "text-red-300" : "text-emerald-300"} />
                  <Mini label="허용 한도" value={`${Number(riskBudget.policy?.maxPortfolioLossPct || 0).toFixed(0)}%`} />
                  <Mini label="기본 손절 사용" value={`${riskBudget?.authRequired ? visibleRiskSummary.missingStops : riskBudget.missingStopCount || 0}개`} accent={(riskBudget?.authRequired ? visibleRiskSummary.missingStops : Number(riskBudget.missingStopCount || 0)) > 0 ? "text-amber-300" : "text-emerald-300"} />
                </div>
                {(riskBudget.warnings || []).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {riskBudget.warnings.map((warning: string) => (
                      <span key={warning} className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-200">{warning}</span>
                    ))}
                  </div>
                )}
                {(riskBudget.items || []).filter((item: any) => item.action === "REDUCE").length > 0 && (
                  <div className="mt-3 space-y-2">
                    {(riskBudget.items || []).filter((item: any) => item.action === "REDUCE").slice(0, 3).map((item: any) => (
                      <div key={`${item.market}-${item.symbol}`} className="rounded-xl border border-red-500/20 bg-slate-950/60 px-3 py-2 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-slate-100">{item.name}</span>
                          <span className="font-mono text-red-300">{Number(item.lossBudgetPct || 0).toFixed(1)}%</span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-400">
                          <span>{item.symbol}</span>
                          <span>현재 {Number(item.weightPct || 0).toFixed(1)}%</span>
                          <span>목표 {Number(item.recommendedWeightPct || 0).toFixed(1)}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {(riskBudget.correlation?.highCorrelationPairs || []).length > 0 && (
                  <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-950/10 px-3 py-2 text-[11px]">
                    <div className="font-semibold text-amber-200">상관계수 높은 묶음</div>
                    <div className="mt-1 space-y-1">
                      {riskBudget.correlation.highCorrelationPairs.slice(0, 3).map((pair: any) => (
                        <div key={`${pair.symbolA}-${pair.symbolB}`} className="flex items-center justify-between text-slate-400">
                          <span>{pair.symbolA} · {pair.symbolB}</span>
                          <span className="font-mono text-amber-300">r={Number(pair.correlation || 0).toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            </div>
          )}
        </section>
      )}

      {/* 개별주/ETF 보기 전환 */}
      {!loading && previewHoldings.length > 0 && (
        <section className="mone-home-card overflow-hidden">
          <div className="flex items-baseline gap-2 px-3.5 pb-2 pt-3.5">
            <h2 className="mone-home-section-title">보유종목 미리보기</h2>
            <button
              type="button"
              onClick={() => holdingsDetailOpen ? setHoldingsDetailOpen(false) : openHoldingsDetail()}
              className="ml-auto inline-flex items-center gap-0.5 text-[10.5px] font-semibold text-slate-400 transition-colors hover:text-teal-300"
            >
              {holdingsDetailOpen ? "간단히 보기" : "전체 보기"} <ChevronRight size={12} className={holdingsDetailOpen ? "rotate-90" : ""} />
            </button>
          </div>
          <div className="divide-y divide-slate-800/80">
            {previewHoldings.map((holding) => {
              const risk = normalizeRiskStatus(holding.riskStatus);
              const isRisk = risk === "STOP_LOSS_DELAY" || risk === "HIGH" || risk === "WATCH";
              const statusClass = risk === "STOP_LOSS_DELAY" || risk === "HIGH"
                ? "border-red-500/30 bg-red-500/10 text-red-300"
                : risk === "WATCH"
                  ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                  : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
              const pnl = Number(holding.pnl || 0);
              const pnlTone = pnl < 0 ? "text-red-300" : "text-emerald-300";
              const name = displayName(holding);
              const weight = holding.weightText || holding.weightPctText || holding.portfolioWeightText || (holding.weightPct != null ? `${Number(holding.weightPct).toFixed(1)}%` : "-");
              const symbol = `${holding.symbol} · ${holding.market === "kr" ? "KOSPI" : "NASDAQ"}`;
              return (
                <button
                  key={`preview-${holding.market}-${holding.symbol}`}
                  type="button"
                  onClick={() => openHoldingsDetail()}
                  className="grid min-h-[72px] w-full grid-cols-[36px_minmax(0,1fr)_42px_64px] items-center gap-2 px-3.5 text-left transition-colors hover:bg-slate-900/35"
                >
                  <span className={`grid size-9 place-items-center rounded-full text-[11px] font-semibold ${isRisk ? "bg-amber-400/10 text-amber-300" : "bg-teal-400/10 text-teal-300"}`}>{name.slice(0, 1)}</span>
                  <span className="min-w-0">
                    <span className="block truncate text-[12px] font-semibold text-slate-100">{name}</span>
                    <span className="mt-0.5 block truncate font-mono text-[9.5px] text-slate-400">{symbol}</span>
                  </span>
                  <span className="text-left">
                    <span className="block text-[9px] text-slate-400">비중</span>
                    <span className="mt-0.5 block font-mono text-[10.5px] font-semibold tabular-nums text-slate-200">{weight}</span>
                  </span>
                  <span className="text-right">
                    <span className="block text-[9px] text-slate-400">평가손익</span>
                    <span className={`mt-0.5 block font-mono text-[10.5px] font-semibold tabular-nums ${pnlTone}`}>{holding.pnlText || "-"}</span>
                    <span className={`mt-0.5 block font-mono text-[9px] tabular-nums ${pnlTone}`}>{holding.pnlPctText || "-"}</span>
                    <span className={`mt-1 inline-flex rounded-full border px-1.5 py-0.5 text-[8.5px] font-semibold ${statusClass}`}>{riskLabel(holding.riskStatus)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {!loading && previewHoldings.length === 0 && (
        <section className="mone-home-card p-3.5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="mone-home-section-title">보유종목</h2>
            <span className="font-mono text-[10px] text-slate-400">0개</span>
          </div>
          <div className="mone-home-inset mt-3 flex min-h-[132px] flex-col items-center justify-center rounded-[10px] border border-dashed px-4 py-5 text-center">
            <BriefcaseBusiness size={22} className="text-teal-300" />
            <p className="mt-2 text-[13px] font-semibold text-slate-100">보유종목을 등록해주세요</p>
            <p className="mt-1 text-[10.5px] leading-5 text-slate-400">직접 입력하거나 증권사 데이터를 연동해 시작할 수 있습니다.</p>
            <div className="mt-3 grid w-full max-w-[300px] grid-cols-2 gap-2">
              <button type="button" onClick={() => setShowAdd(true)} className="mone-selection-brand min-h-9 rounded-[8px] px-3 text-[11px] font-semibold">직접 등록</button>
              <button type="button" onClick={() => onNavigate?.("broker")} className="rounded-[8px] border border-slate-700 bg-slate-950 px-3 text-[11px] font-semibold text-slate-300 hover:bg-slate-900">증권사 연동</button>
            </div>
          </div>
        </section>
      )}

      {holdingsDetailOpen && (
        <>
      {riskFocus !== "all" && (
        <div className="flex flex-col gap-2 border-y border-amber-500/25 bg-amber-500/10 px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs font-semibold text-amber-100">{riskFocusLabel[riskFocus]} 종목만 보고 있습니다</div>
            <p className="mt-0.5 text-[10.5px] text-amber-100/75">현재 조건에 해당하는 {focusedHoldings.length}개 보유 종목을 위험도 순으로 정렬했습니다.</p>
          </div>
          <button
            type="button"
            onClick={() => setRiskFocus("all")}
            className="inline-flex min-h-9 shrink-0 items-center justify-center rounded-lg border border-amber-400/35 px-3 text-xs font-semibold text-amber-100 hover:bg-amber-500/10"
          >
            전체 보유 보기
          </button>
        </div>
      )}
      {(individualStocks.length > 0 || etfHoldings.length > 0) && (
        <div id="holdings-detail" className="mone-home-inset grid grid-cols-3 gap-1 rounded-[10px] border p-1">
          {([
            { key: "all", label: `전체 (${individualStocks.length + etfHoldings.length})` },
            { key: "stock", label: `개별주 (${individualStocks.length})` },
            { key: "etf", label: `ETF (${etfHoldings.length})` },
          ] as const).map((tab) => (
            <button key={tab.key} onClick={() => setHoldingsViewTab(tab.key)}
              className={`min-h-9 rounded-[7px] px-2 text-[11px] font-semibold transition-[background-color,color,transform] active:scale-[0.96] ${
                holdingsViewTab === tab.key ? "mone-selection-brand" : "text-slate-400 hover:text-slate-300"
              }`}>
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {/* 개별주 카드 */}
      {individualStocks.length > 0 && holdingsViewTab !== "etf" && (
        <div>
          <div className="mb-2 flex items-baseline gap-2">
            <h2 className="mone-home-section-title">개별주 보유</h2>
            <span className="font-mono text-[10px] text-slate-400 tabular-nums">{individualStocks.length}개 · 위험도 순</span>
          </div>
          <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
            {individualStocks.map((holding: any) => {
          const key = editableKey(holding);
          const isEditing = editKey === key && !!editDraft;
          const assetType = normalizedHoldingAssetType(holding);
          const isEtf = assetType.includes("etf");
          const holdingPurpose = String(holding.holdingPurpose || holding.strategyType || "");
          const downsideLabel = String(holding.downsideLineLabel || (isEtf ? "리스크 기준선" : "손절선"));
          const upsideLabel = String(holding.upsideLineLabel || (isEtf ? "수익실현 기준선" : "목표가"));
          const downsideValue = Number(holding.downsideLine ?? holding.stopPrice ?? holding.stop ?? 0);
          const upsideValue = Number(holding.upsideLine ?? holding.targetPrice ?? holding.target ?? 0);
          const hasStopPrice = downsideValue > 0;
          const hasTargetPrice = upsideValue > 0;
          const stopMissing = !hasStopPrice;
          const targetMissing = !hasTargetPrice;
          const stopGapPct = holding.downsideGapPct != null ? Number(holding.downsideGapPct) : holding.stopGapPct != null ? Number(holding.stopGapPct) : null;
          const targetGapPct = holding.targetGapPct != null ? Number(holding.targetGapPct) : null;
          const holdingBroker = brokerLabel(holding.broker || holding.sourceBroker || holding.sourceType || holding.priceSource);
          const weightText = holding.weightText || holding.weightPctText || holding.portfolioWeightText || (holding.weightPct != null ? `${Number(holding.weightPct).toFixed(1)}%` : "계산 대기");
          const pnlText = `${holding.pnlText || "계산 대기"}${holding.pnlPctText && holding.pnlPctText !== "-" ? ` / ${holding.pnlPctText}` : ""}`;
          const holdingMarket = cleanHoldingMarket(holding.market);
          const downsideText = stopMissing ? `${downsideLabel} 없음` : formatHoldingMoney(downsideValue, holdingMarket);
          const upsideText = targetMissing ? `${upsideLabel} 없음` : formatHoldingMoney(upsideValue, holdingMarket);
          const holdingSourceText = humanDataSourceLabel(holding.broker || holding.sourceBroker || holding.sourceType || holding.source || data.authority, "개인 보유");
          const holdingDateText = shortSourceDate(holding.latestDataDate || holding.priceDate || holding.updatedAt);
          const holdingPriceSourceText = priceSourceLabel(holding.quoteSource || holding.priceSource || holding.currentPriceSource);
          return (
            <div key={`${holding.market}-${holding.symbol}`} className="mone-home-card p-3.5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <h2 className="max-w-[8rem] break-keep text-base font-bold leading-snug text-slate-100 sm:max-w-none">{displayName(holding)}</h2>
                    <span className="font-mono text-xs text-slate-400">{holding.symbol}</span>
                    <span className="whitespace-nowrap rounded-md bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">{holding.market === "kr" ? "국장" : "미장"}</span>
                    <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-300">{holdingAssetLabel(assetType)}</span>
                    <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">{holdingPurposeLabel(holdingPurpose)}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-slate-400">{holdingBroker} · {String(holding.market || "").toUpperCase()}</div>
                  <div className="mt-0.5 flex flex-wrap gap-1 text-[10px] text-slate-600">
                    <span>{holdingSourceText}</span>
                    {holdingDateText && <span>기준 {holdingDateText}</span>}
                    {holdingPriceSourceText && <span>가격 {holdingPriceSourceText}</span>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(() => {
                      const status = String(holding.dataStatus || "");
                      const missing = Array.isArray(holding.missingFields) ? holding.missingFields : [];
                      if (status === "OK" || status === "NORMAL") return <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">정상</span>;
                      if (!holding.currentPrice || holding.currentPrice <= 0) return <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">갱신 필요</span>;
                      if (missing.length > 0) return <span className="rounded-md border border-slate-600/40 bg-slate-700/20 px-2 py-0.5 text-[10px] text-slate-400">OHLCV 기준가 ({missing.slice(0,2).join("·")} 없음)</span>;
                      return <span className="rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-300">일부 제한</span>;
                    })()}
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  <span className={`rounded-xl border px-2.5 py-1 text-xs font-bold ${riskBadgeClass(holding.riskStatus)}`}>
                    {riskLabel(holding.riskStatus)}
                  </span>
                  {(() => {
                    const sig = exitSignals[`${holding.market}-${holding.symbol}`];
                    if (!sig || sig.signal === "HOLD" || sig.signal === "NO_DATA" || sig.urgency <= 0) return null;
                    const cfg: Record<string, { cls: string; label: string }> = {
                      SELL_STRONG: { cls: "border-red-500/60 bg-red-500/20 text-red-200", label: normalizeAction("SELL_STRONG").label },
                      SELL:        { cls: "border-orange-500/60 bg-orange-500/20 text-orange-200", label: normalizeAction("SELL").label },
                      PARTIAL_EXIT:{ cls: "border-yellow-500/50 bg-yellow-500/15 text-yellow-200", label: normalizeAction("REDUCE").label },
                      MONITOR:     { cls: "border-blue-500/40 bg-blue-500/10 text-blue-300", label: normalizeAction("MONITOR").label },
                    };
                    const c = cfg[sig.signal] || { cls: "border-slate-600 bg-slate-800 text-slate-300", label: sig.signal };
                    return (
                      <span className={`rounded-xl border px-2.5 py-1 text-xs font-bold ${c.cls}`}
                        title={Array.isArray(sig.reasons) ? sig.reasons.join(" · ") : ""}>
                        {c.label}
                      </span>
                    );
                  })()}
                  {!isEditing && (
                    <>
                      <button onClick={() => refreshOneQuote(holding)} disabled={savingKey === key}
                        className="inline-flex items-center gap-1 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-300 hover:bg-blue-500/20 disabled:opacity-50" title="빠른점검: 현재가 새로고침" aria-label="빠른점검: 현재가 새로고침">
                        <Zap size={11} />
                        <span>빠른점검</span>
                      </button>
                      <button onClick={() => { setEditKey(key); setEditDraft(toEditableHolding(holding)); setDeleteConfirmKey(null); setMessage(""); }}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800">
                        <Pencil size={11} /> 수정
                      </button>
                      {deleteConfirmKey === key ? (
                        <>
                          <button onClick={() => deleteHolding(holding)} disabled={savingKey === key}
                            className="inline-flex items-center gap-1 rounded-lg border border-red-500/60 bg-red-500/20 px-2 py-1 text-xs font-bold text-red-300 hover:bg-red-500/30 disabled:opacity-50">
                            <Trash2 size={11} /> 확인
                          </button>
                          <button onClick={() => setDeleteConfirmKey(null)} aria-label="삭제 취소" title="취소"
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800">
                            <X size={11} />
                          </button>
                        </>
                      ) : (
                        <button onClick={() => setDeleteConfirmKey(key)} disabled={savingKey === key}
                          className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-300 hover:bg-red-500/20 disabled:opacity-50">
                          <Trash2 size={11} /> 삭제
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                <Mini
                  label={`${downsideLabel}까지`}
                  value={stopGapPct !== null ? `${stopGapPct >= 0 ? "+" : ""}${stopGapPct.toFixed(1)}%` : stopMissing ? `${downsideLabel} 필요` : "현재가 필요"}
                  accent={stopGapPct !== null && stopGapPct <= 2 ? "text-red-300" : stopGapPct !== null && stopGapPct <= 5 ? "text-amber-300" : "text-emerald-300"}
                />
                <Mini label="평가손익" value={pnlText} accent={Number(holding.pnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                <Mini label="보유 비중" value={weightText} />
                <Mini label="MONE 리스크" value={riskLabel(holding.riskStatus)} accent={["HIGH","STOP_LOSS_DELAY"].includes(normalizeRiskStatus(holding.riskStatus)) ? "text-red-300" : normalizeRiskStatus(holding.riskStatus) === "WATCH" ? "text-amber-300" : "text-emerald-300"} />
                <button
                  type="button"
                  onClick={() => {
                    window.localStorage.setItem("mone_chart_symbol", String(holding.symbol || ""));
                    window.localStorage.setItem("mone_chart_market", cleanHoldingMarket(holding.market));
                    window.localStorage.setItem("mone_chart_name", displayName(holding));
                    window.localStorage.setItem("mone_chart_price", String(holding.currentPrice || ""));
                    window.localStorage.setItem("mone_chart_price_text", holding.currentPriceText || "");
                    window.dispatchEvent(new CustomEvent("mone-open-chart", { detail: holding }));
                    onNavigate?.("chart");
                  }}
                  className="col-span-2 inline-flex min-h-[52px] items-center justify-center rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-bold text-blue-200 hover:bg-blue-500/20 sm:col-span-1"
                >
                  분석 보기
                </button>
              </div>

              {isEditing && editDraft && (
                <div className="mt-4 rounded-2xl border border-blue-500/30 bg-blue-500/10 p-4">
                  <div className="mb-3 text-sm font-bold text-blue-200">보유종목 수정</div>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                    {(["name","symbol","quantity","avgPrice"] as const).map((field) => (
                      <label key={field} className="text-xs text-slate-400">
                        {field === "name" ? "종목명" : field === "symbol" ? "종목코드/티커" : field === "quantity" ? "수량" : "평균단가"}
                        <input type={field === "quantity" || field === "avgPrice" ? "number" : "text"}
                          value={editDraft[field]}
                          onChange={(e) => setEditDraft({ ...editDraft, [field]: e.target.value })}
                          className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400" />
                      </label>
                    ))}
                    <label className="text-xs text-slate-400">
                      손절가
                      <input
                        type="number"
                        value={editDraft.stopPrice || ""}
                        onChange={(e) => setEditDraft({ ...editDraft, stopPrice: e.target.value })}
                        className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                      />
                    </label>
                    <label className="text-xs text-slate-400">
                      목표가
                      <input
                        type="number"
                        value={editDraft.targetPrice || ""}
                        onChange={(e) => setEditDraft({ ...editDraft, targetPrice: e.target.value })}
                        className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                      />
                    </label>
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button onClick={() => saveEdit(holding)} disabled={savingKey === key}
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-50">
                      <Save size={12} /> 저장
                    </button>
                    <button onClick={() => { setEditKey(null); setEditDraft(null); }}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800">
                      <X size={12} /> 취소
                    </button>
                  </div>
                </div>
              )}

              {(stopMissing || targetMissing) && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {stopMissing && <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">{downsideLabel} 필요</span>}
                  {targetMissing && <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">{upsideLabel} 필요</span>}
                </div>
              )}

              <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
                <Mini label="수량" value={String(holding.quantity || "-")} />
                <Mini label="평단" value={holding.avgPriceText || "-"} />
                <Mini label="현재가" value={holding.currentPriceText || "현재가 대기"} />
                <Mini label="등락률" value={holding.changePctText || "-"}
                  accent={String(holding.changePctText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"} />
                <Mini label="평가금액" value={holding.valuationText || holding.marketValueText || "-"} />
                <Mini label="손익" value={holding.pnlText || "0"}
                  accent={Number(holding.pnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                <Mini label={downsideLabel} value={downsideText} accent={stopMissing ? "text-amber-300" : "text-red-300"} />
                <Mini label={upsideLabel} value={upsideText} accent={targetMissing ? "text-amber-300" : "text-emerald-300"} />
              </div>

              <div className="mt-4 space-y-2">
                <div className="rounded-xl bg-slate-950 px-3 py-2.5">
                  <div className="flex justify-between text-[10px] text-slate-400">
                    <span>{downsideLabel} 여유</span>
                    <span className="font-mono">{stopGapPct !== null ? `${stopGapPct.toFixed(2)}% 여유` : stopMissing ? `${downsideLabel} 없음` : "현재가 필요"}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div className={`h-full rounded-full ${stopGapPct !== null && stopGapPct <= 2 ? "bg-red-500" : stopGapPct !== null && stopGapPct <= 5 ? "bg-amber-400" : "bg-emerald-500"}`}
                      style={{ width: `${Math.max(4, Math.min(100, (stopGapPct ?? 0) * 8))}%` }} />
                  </div>
                </div>
                {targetGapPct !== null && targetGapPct > 0 && (
                  <div className="rounded-xl bg-slate-950 px-3 py-2.5">
                    <div className="flex justify-between text-[10px] text-slate-400">
                      <span>{upsideLabel} 여유</span>
                      <span className="font-mono">{targetGapPct.toFixed(2)}% 남음</span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                      <div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.max(4, Math.min(100, targetGapPct * 3))}%` }} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
            })}
            {individualStocks.length === 0 && !loading && etfHoldings.length === 0 && (
              <div className="col-span-full rounded-2xl border border-dashed border-slate-800 p-12 text-center">
                <p className="text-slate-400">{showPersonalEmptyNotice ? "개인 보유종목이 아직 없습니다." : "보유 종목이 없습니다."}</p>
                {showPersonalEmptyNotice && (
                  <p className="mx-auto mt-2 max-w-md text-xs leading-5 text-slate-400">공용 데이터가 있더라도 이 화면에는 이 브라우저의 개인 보유만 표시합니다.</p>
                )}
                <button onClick={() => setShowAdd(true)}
                  className="mone-primary-action mt-4 inline-flex min-h-10 items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-[background-color,box-shadow,transform] active:scale-[0.96]">
                  <Plus size={14} /> 첫 종목 직접 추가
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ETF 카드 */}
      {etfHoldings.length > 0 && holdingsViewTab !== "stock" && (
        <div>
          <div className="mb-2 flex items-baseline gap-2">
            <h2 className="text-lg font-bold text-slate-100">ETF 적립 ({etfHoldings.length})</h2>
            <span className="text-xs text-slate-400">평가금액 기준 정렬</span>
          </div>
          <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
            {etfHoldings.map((holding: any) => {
              const key = editableKey(holding);
              const isEditing = editKey === key && !!editDraft;
              const assetType = normalizedHoldingAssetType(holding);
              const holdingPurpose = String(holding.holdingPurpose || holding.strategyType || "");
              const holdingBroker = brokerLabel(holding.broker || holding.sourceBroker || holding.sourceType || holding.priceSource);
              const holdingMarket = cleanHoldingMarket(holding.market);
              const weightText = holding.weightText || holding.weightPctText || holding.portfolioWeightText || (holding.weightPct != null ? `${Number(holding.weightPct).toFixed(1)}%` : "계산 대기");
              const pnlText = `${holding.pnlText || "계산 대기"}${holding.pnlPctText && holding.pnlPctText !== "-" ? ` / ${holding.pnlPctText}` : ""}`;
              const costBasis = Number(holding.avgPrice || 0) * Number(holding.quantity || 0);
              const currentValue = Number(holding.valuation || holding.marketValue || 0);
              const accumulationGapPct = costBasis > 0 ? ((currentValue - costBasis) / costBasis) * 100 : 0;
              const holdingSourceText = humanDataSourceLabel(holding.broker || holding.sourceBroker || holding.sourceType || holding.source || data.authority, "개인 보유");
              const holdingDateText = shortSourceDate(holding.latestDataDate || holding.priceDate || holding.updatedAt);
              const holdingPriceSourceText = priceSourceLabel(holding.quoteSource || holding.priceSource || holding.currentPriceSource);

              return (
                <div key={`${holding.market}-${holding.symbol}`} className="mone-home-card p-3.5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <h2 className="max-w-[8rem] break-keep text-base font-bold leading-snug text-slate-100 sm:max-w-none">{displayName(holding)}</h2>
                        <span className="font-mono text-xs text-slate-400">{holding.symbol}</span>
                        <span className="whitespace-nowrap rounded-md bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">{holding.market === "kr" ? "국장" : "미장"}</span>
                        <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-300">{holdingAssetLabel(assetType)}</span>
                        <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">{holdingPurposeLabel(holdingPurpose)}</span>
                      </div>
                      <div className="mt-0.5 text-xs text-slate-400">{holdingBroker} · {String(holding.market || "").toUpperCase()}</div>
                      <div className="mt-0.5 flex flex-wrap gap-1 text-[10px] text-slate-600">
                        <span>{holdingSourceText}</span>
                        {holdingDateText && <span>기준 {holdingDateText}</span>}
                        {holdingPriceSourceText && <span>가격 {holdingPriceSourceText}</span>}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {(() => {
                          const status = String(holding.dataStatus || "");
                          const missing = Array.isArray(holding.missingFields) ? holding.missingFields : [];
                          if (status === "OK" || status === "NORMAL") return <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">정상</span>;
                          if (!holding.currentPrice || holding.currentPrice <= 0) return <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">갱신 필요</span>;
                          if (missing.length > 0) return <span className="rounded-md border border-slate-600/40 bg-slate-700/20 px-2 py-0.5 text-[10px] text-slate-400">OHLCV 기준가 ({missing.slice(0,2).join("·")} 없음)</span>;
                          return <span className="rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-300">일부 제한</span>;
                        })()}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                      {!isEditing && (
                        <>
                          <button onClick={() => refreshOneQuote(holding)} disabled={savingKey === key}
                            className="inline-flex items-center gap-1 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-300 hover:bg-blue-500/20 disabled:opacity-50" title="빠른점검: 현재가 새로고침" aria-label="빠른점검: 현재가 새로고침">
                            <Zap size={11} />
                            <span>빠른점검</span>
                          </button>
                          <button onClick={() => { setEditKey(key); setEditDraft(toEditableHolding(holding)); setDeleteConfirmKey(null); setMessage(""); }}
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800">
                            <Pencil size={11} /> 수정
                          </button>
                          {deleteConfirmKey === key ? (
                            <>
                              <button onClick={() => deleteHolding(holding)} disabled={savingKey === key}
                                className="inline-flex items-center gap-1 rounded-lg border border-red-500/60 bg-red-500/20 px-2 py-1 text-xs font-bold text-red-300 hover:bg-red-500/30 disabled:opacity-50">
                                <Trash2 size={11} /> 확인
                              </button>
                              <button onClick={() => setDeleteConfirmKey(null)} aria-label="삭제 취소" title="취소"
                                className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-400 hover:bg-slate-800">
                                <X size={11} />
                              </button>
                            </>
                          ) : (
                            <button onClick={() => setDeleteConfirmKey(key)} disabled={savingKey === key}
                              className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-300 hover:bg-red-500/20 disabled:opacity-50">
                              <Trash2 size={11} /> 삭제
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <Mini label="포트폴리오 비중" value={weightText} />
                    <Mini label="평가손익" value={pnlText} accent={Number(holding.pnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                    <Mini label="적립 수익률" value={accumulationGapPct >= 0 ? `+${accumulationGapPct.toFixed(1)}%` : `${accumulationGapPct.toFixed(1)}%`} accent={accumulationGapPct >= 0 ? "text-emerald-300" : "text-amber-300"} />
                    <button
                      type="button"
                      onClick={() => {
                        window.localStorage.setItem("mone_chart_symbol", String(holding.symbol || ""));
                        window.localStorage.setItem("mone_chart_market", cleanHoldingMarket(holding.market));
                        window.localStorage.setItem("mone_chart_name", displayName(holding));
                        window.localStorage.setItem("mone_chart_price", String(holding.currentPrice || ""));
                        window.localStorage.setItem("mone_chart_price_text", holding.currentPriceText || "");
                        window.dispatchEvent(new CustomEvent("mone-open-chart", { detail: holding }));
                        onNavigate?.("chart");
                      }}
                      className="col-span-2 inline-flex min-h-[52px] items-center justify-center rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-bold text-blue-200 hover:bg-blue-500/20 sm:col-span-2"
                    >
                      분석 보기
                    </button>
                  </div>

                  {isEditing && editDraft && (
                    <div className="mt-4 rounded-2xl border border-blue-500/30 bg-blue-500/10 p-4">
                      <div className="mb-3 text-sm font-bold text-blue-200">보유종목 수정</div>
                      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                        {(["name","symbol","quantity","avgPrice"] as const).map((field) => (
                          <label key={field} className="text-xs text-slate-400">
                            {field === "name" ? "종목명" : field === "symbol" ? "종목코드/티커" : field === "quantity" ? "수량" : "평균단가"}
                            <input type={field === "quantity" || field === "avgPrice" ? "number" : "text"}
                              value={editDraft[field]}
                              onChange={(e) => setEditDraft({ ...editDraft, [field]: e.target.value })}
                              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400" />
                          </label>
                        ))}
                      </div>
                      <div className="mt-3 flex gap-2">
                        <button onClick={() => saveEdit(holding)} disabled={savingKey === key}
                          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-50">
                          <Save size={12} /> 저장
                        </button>
                        <button onClick={() => { setEditKey(null); setEditDraft(null); }}
                          className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800">
                          <X size={12} /> 취소
                        </button>
                      </div>
                    </div>
                  )}

                  <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
                    <Mini label="수량" value={String(holding.quantity || "-")} />
                    <Mini label="평단" value={holding.avgPriceText || "-"} />
                    <Mini label="현재가" value={holding.currentPriceText || "현재가 대기"} />
                    <Mini label="등락률" value={holding.changePctText || "-"}
                      accent={String(holding.changePctText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"} />
                    <Mini label="평가금액" value={holding.valuationText || holding.marketValueText || "-"} />
                    <Mini label="손익" value={holding.pnlText || "0"}
                      accent={Number(holding.pnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                    <Mini label="총 투입금액" value={formatHoldingMoney(costBasis, holdingMarket)} />
                    <Mini label="평가금액" value={formatHoldingMoney(currentValue, holdingMarket)} />
                  </div>

                  <div className="mt-4 rounded-xl bg-slate-950 px-3 py-2.5">
                    <div className="flex justify-between text-[10px] text-slate-400">
                      <span>적립 수익률</span>
                      <span className="font-mono">{accumulationGapPct >= 0 ? `+${accumulationGapPct.toFixed(2)}%` : `${accumulationGapPct.toFixed(2)}%`}</span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                      <div className={`h-full rounded-full ${accumulationGapPct >= 10 ? "bg-emerald-500" : accumulationGapPct >= 0 ? "bg-sky-500" : "bg-amber-400"}`}
                        style={{ width: `${Math.max(4, Math.min(100, (accumulationGapPct ?? 0) * 5))}%` }} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {holdingsViewTab === "stock" && individualStocks.length === 0 && etfHoldings.length > 0 && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-400">보유 중인 개별주가 없습니다.</div>
      )}
      {holdingsViewTab === "etf" && etfHoldings.length === 0 && individualStocks.length > 0 && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-400">보유 중인 ETF가 없습니다.</div>
      )}

      {/* Kelly 포지션 사이즈 가이드 */}
      {false && kellySizes && Object.keys(kellySizes).length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50">
          <button
            type="button"
            onClick={() => setKellyOpen((v) => !v)}
            className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
          >
            <span className="text-sm font-semibold text-slate-200">Kelly 포지션 사이즈 가이드</span>
            <ChevronDown size={16} className={`shrink-0 text-slate-400 transition-transform duration-200 ${kellyOpen ? "rotate-180" : ""}`} />
          </button>
          {kellyOpen && (
            <div className="border-t border-slate-800 px-5 pb-5 pt-4">
              <div className="grid grid-cols-3 gap-2 text-[11px] sm:grid-cols-3 lg:grid-cols-9">
                {(["conservative","balanced","aggressive"] as const).map((mode) =>
                  (["short","swing","mid"] as const).map((horizon) => {
                    const k = `${mode}_${horizon}`;
                    const entry = kellySizes[k];
                    if (!entry) return null;
                    const hk = entry.recommendedPct != null ? `${Number(entry.recommendedPct).toFixed(1)}%` : entry.kellyHalf != null ? `${(entry.kellyHalf * 100).toFixed(1)}%` : "—";
                    const modeLabel = { conservative: "보수", balanced: "균형", aggressive: "공격" }[mode];
                    const horizonLabel = { short: "단기", swing: "스윙", mid: "중기" }[horizon];
                    const color = mode === "conservative" ? "text-sky-300" : mode === "balanced" ? "text-emerald-300" : "text-orange-300";
                    return (
                      <div key={k} className="rounded-xl border border-slate-800 bg-slate-950/60 px-2 py-2 text-center">
                        <div className={`font-semibold ${color}`}>{modeLabel}</div>
                        <div className="text-slate-400">{horizonLabel}</div>
                        <div className="mt-1 font-mono font-bold text-slate-100">{hk}</div>
                        {entry.winRate != null && (
                          <div className="mt-0.5 text-[10px] text-slate-400">승률 {(entry.winRate * 100).toFixed(0)}%</div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
              <p className="mt-2 text-[10px] text-slate-400">Half-Kelly 상한 20% · VTJ 실적 기반 — 해당 전략으로 진입 검토 시 권장 비중입니다.</p>
            </div>
          )}
        </div>
      )}

      {false && riskBudget && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50">
          <button
            type="button"
            onClick={() => setRiskBudgetOpen((v) => !v)}
            className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
          >
            <span className="text-sm font-semibold text-slate-200">
              포트폴리오 리스크 예산
              <span className={`ml-2 text-xs font-normal ${riskBudget.status === "OVER_BUDGET" ? "text-red-300" : "text-emerald-300"}`}>
                {riskBudget.status === "OVER_BUDGET" ? "예산 초과" : "정상"}
              </span>
            </span>
            <ChevronDown size={16} className={`shrink-0 text-slate-400 transition-transform duration-200 ${riskBudgetOpen ? "rotate-180" : ""}`} />
          </button>
          {riskBudgetOpen && (
            <div className="border-t border-slate-800 px-5 pb-5 pt-4">
              <p className="mb-3 text-[11px] text-slate-400">손절가와 Kelly 한도 기준으로 과대 비중 종목을 표시합니다.</p>
              <div className="grid gap-2 text-[11px] sm:grid-cols-3">
                <Mini label="예상 손실 예산" value={`${Number(riskBudget.totalLossBudgetPct || 0).toFixed(1)}%`} accent={Number(riskBudget.totalLossBudgetPct || 0) > Number(riskBudget.policy?.maxPortfolioLossPct || 6) ? "text-red-300" : "text-emerald-300"} />
                <Mini label="허용 한도" value={`${Number(riskBudget.policy?.maxPortfolioLossPct || 0).toFixed(0)}%`} />
                <Mini label="기본 손절 사용" value={`${riskBudget.missingStopCount || 0}개`} accent={Number(riskBudget.missingStopCount || 0) > 0 ? "text-amber-300" : "text-emerald-300"} />
              </div>
              {(riskBudget.warnings || []).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {riskBudget.warnings.map((warning: string) => (
                    <span key={warning} className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] text-amber-200">{warning}</span>
                  ))}
                </div>
              )}
              {(riskBudget.correlation?.highCorrelationPairs || []).length > 0 && (
                <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-950/10 px-3 py-2 text-[11px]">
                  <div className="mb-1.5 font-semibold text-amber-200">상관계수 높은 종목 묶음 (섹터 라벨과 무관하게 같이 움직일 가능성)</div>
                  <div className="space-y-1">
                    {riskBudget.correlation.highCorrelationPairs.slice(0, 5).map((pair: any) => (
                      <div key={`${pair.symbolA}-${pair.symbolB}`} className="flex items-center justify-between text-slate-400">
                        <span>{pair.symbolA} · {pair.symbolB}</span>
                        <span className="font-mono text-amber-300">r={pair.correlation.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                  <div className="mt-1.5 text-[10px] text-slate-600">
                    최근 {riskBudget.correlation.lookbackDays}거래일 일간수익률 기준 · |r|≥{riskBudget.policy?.highCorrelationThreshold ?? 0.7} 이상만 표시
                  </div>
                </div>
              )}
              {(riskBudget.items || []).filter((item: any) => item.action === "REDUCE").length > 0 && (
                <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {(riskBudget.items || []).filter((item: any) => item.action === "REDUCE").slice(0, 6).map((item: any) => (
                    <div key={`${item.market}-${item.symbol}`} className="rounded-xl border border-red-500/20 bg-slate-950/60 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-slate-100">{item.name}</span>
                        <span className="font-mono text-red-300">{Number(item.lossBudgetPct || 0).toFixed(1)}%</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-400">
                        <span>{item.symbol}</span>
                        <span>현재 비중 {Number(item.weightPct || 0).toFixed(1)}%</span>
                        <span>목표 비중 {Number(item.recommendedWeightPct || 0).toFixed(1)}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {summary.mixedCurrency && (
        <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-4 py-3 text-xs text-blue-200 space-y-1">
          <div>KR/US 혼합 보유 — 평가금액·손익은 통화별로 분리 표시합니다.</div>
          {(() => {
            const usBucket = summary.marketBreakdown?.find((b: any) => b.market === "us") || {};
            const krBucket = summary.marketBreakdown?.find((b: any) => b.market === "kr") || {};
            return (
              <div className="grid gap-2 pt-2 sm:grid-cols-2 lg:grid-cols-4">
                <Mini label="원화 평가금액" value={`${Math.round(Number(krBucket.totalValue || 0)).toLocaleString("ko-KR")}원`} />
                <Mini label="달러 평가금액" value={`$${Number(usBucket.totalValue || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`} />
                <Mini label="원화 평가손익" value={`${Number(krBucket.totalPnl || 0) >= 0 ? "+" : ""}${Math.round(Number(krBucket.totalPnl || 0)).toLocaleString("ko-KR")}원`} accent={Number(krBucket.totalPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                <Mini label="달러 평가손익" value={`${Number(usBucket.totalPnl || 0) >= 0 ? "+$" : "-$"}${Math.abs(Number(usBucket.totalPnl || 0)).toLocaleString(undefined, { maximumFractionDigits: 2 })}`} accent={Number(usBucket.totalPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
              </div>
            );
          })()}
          {usdToKrw ? (() => {
            const usBucket = summary.marketBreakdown?.find((b: any) => b.market === "us");
            const krBucket = summary.marketBreakdown?.find((b: any) => b.market === "kr");
            const usValueKrw = usBucket ? Math.round((usBucket.totalValue || 0) * usdToKrw.rate) : 0;
            const krValue = krBucket ? (krBucket.totalValue || 0) : 0;
            const combined = krValue + usValueKrw;
            const usPnlKrw = usBucket ? Math.round((usBucket.totalPnl || 0) * usdToKrw.rate) : 0;
            const krPnl = krBucket ? (krBucket.totalPnl || 0) : 0;
            const combinedPnl = krPnl + usPnlKrw;
            return (
              <div className="font-mono text-blue-100">
                환율 기준 합산 ({usdToKrw.rate.toLocaleString("ko-KR")}원/USD · {usdToKrw.date}){" "}
                평가금액 <span className="font-bold">{combined.toLocaleString("ko-KR")}원</span>
                {" "}· 손익{" "}
                <span className={combinedPnl >= 0 ? "text-emerald-300 font-bold" : "text-red-300 font-bold"}>
                  {combinedPnl >= 0 ? "+" : ""}{combinedPnl.toLocaleString("ko-KR")}원
                </span>
              </div>
            );
          })() : (
            <div className="text-blue-300/60">환율 API 연결 시 합산 KRW 값을 표시합니다. (.env에 KOREAEXIM_API_KEY 추가)</div>
          )}
        </div>
      )}

      {/* 청산 신호 요약 배너 */}
      {(() => {
        const urgentSigs = Object.values(exitSignals).filter(
          (s) => s.signal === "SELL_STRONG" || s.signal === "SELL"
        );
        if (urgentSigs.length === 0) return null;
        return (
          <div className="rounded-2xl border border-orange-500/30 bg-orange-500/5 p-4">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-sm font-bold text-orange-300">청산 신호 감지 — {urgentSigs.length}종목</span>
              <span className="rounded-full border border-orange-500/40 bg-orange-500/10 px-2 py-0.5 text-[10px] text-orange-300">AI 자동 계산</span>
            </div>
            <div className="space-y-1.5">
              {urgentSigs.map((sig) => (
                <div key={`${sig.market}-${sig.symbol}`} className="flex flex-wrap items-center gap-2 rounded-xl bg-slate-950/50 px-3 py-2 text-xs">
                  <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold ${
                    sig.signal === "SELL_STRONG"
                      ? "border-red-500/60 bg-red-500/20 text-red-200"
                      : "border-orange-500/60 bg-orange-500/20 text-orange-200"
                  }`}>
                    {normalizeAction(sig.signal).label}
                  </span>
                  <span className="font-semibold text-slate-200">{sig.name}</span>
                  <span className="font-mono text-slate-400">{sig.symbol}</span>
                  <span className="text-slate-400">{Array.isArray(sig.reasons) ? sig.reasons[0] : ""}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {riskNote && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/70 px-4 py-3 text-xs text-slate-300">
          {riskNote}
        </div>
      )}

      {data.error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">{data.error}</div>}

      {/* NAV 곡선 */}
      <NavCurve />

      {/* 포트폴리오 구성 바 (개별주만, ETF 제외) */}
      {individualStocks.length > 0 && <PortfolioCompositionBar items={individualStocks} />}
        </>
      )}

      <div className={`${items.length === 0 ? "hidden" : ""} mone-home-card space-y-3 p-3.5`}>
        <div className="flex items-center gap-2">
          <h2 className="mone-home-section-title">포트폴리오 분석</h2>
        </div>
        <div className="mone-home-inset grid grid-cols-4 gap-1 rounded-[10px] border p-1">
          {([
            { key: "benchmark", label: "벤치마크" },
            { key: "correlation", label: "상관" },
            { key: "sector", label: "섹터" },
            { key: "optimize", label: "최적화" },
          ] as const).map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setPortfolioAnalysisTab(tab.key)}
              className={`min-h-9 rounded-[7px] px-1 text-[10.5px] font-semibold transition-[background-color,color,transform] active:scale-[0.96] ${
                portfolioAnalysisTab === tab.key
                  ? "mone-selection-brand"
                  : "text-slate-400 hover:text-slate-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {portfolioAnalysisTab === "benchmark" && (
          <PortfolioSnapshot
            holdingCount={items.length}
            top5Pct={portfolioSnapshot.top5Pct}
            middlePct={portfolioSnapshot.middlePct}
            lowerPct={portfolioSnapshot.lowerPct}
            benchmarkName={benchmarkData?.benchmark || "벤치마크"}
            averageAlpha={portfolioSnapshot.averageAlpha}
          />
        )}

        {portfolioAnalysisTab === "benchmark" && holdingsDetailOpen && (
          personalBenchmarkItems.length > 0 ? (
            <div className="mone-home-inset rounded-[10px] border p-3">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-slate-100">벤치마크 비교 ({benchmarkData.benchmark})</h2>
                  <p className="text-xs text-slate-400">{benchmarkData.benchmarkLatestDate} 기준</p>
                </div>
                <div className={`font-mono text-base font-bold ${(portfolioSnapshot.averageAlpha ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                  알파 {(portfolioSnapshot.averageAlpha ?? 0) >= 0 ? "+" : ""}{portfolioSnapshot.averageAlpha?.toFixed(1)}%p
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead><tr className="border-b border-slate-800 text-slate-400">
                    <th className="pb-2 text-left">종목</th>
                    <th className="pb-2 text-right">내 수익률</th>
                    <th className="pb-2 text-right">{benchmarkData.benchmark}</th>
                    <th className="pb-2 text-right">알파</th>
                  </tr></thead>
                  <tbody>
                    {personalBenchmarkItems.map((item: any) => (
                      <tr key={item.symbol} className="border-b border-slate-900">
                        <td className="py-1.5 pr-3"><div className="font-medium text-slate-200">{item.name}</div><div className="text-slate-400">{item.symbol}</div></td>
                        <td className={`py-1.5 pr-3 text-right font-mono ${(item.portfolioReturn ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                          {item.portfolioReturn >= 0 ? "+" : ""}{item.portfolioReturn?.toFixed(1)}%
                        </td>
                        <td className="py-1.5 pr-3 text-right font-mono text-slate-400">
                          {item.benchmarkReturn != null ? `${item.benchmarkReturn >= 0 ? "+" : ""}${item.benchmarkReturn.toFixed(1)}%` : "—"}
                        </td>
                        <td className={`py-1.5 text-right font-mono font-semibold ${(item.alpha ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                          {item.alpha != null ? `${item.alpha >= 0 ? "+" : ""}${item.alpha.toFixed(1)}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <PortfolioAnalysisEmptyCard
              title="벤치마크 비교"
              detail={benchmarkData?.status === "ERROR" ? "벤치마크 가격 데이터를 불러오지 못했습니다." : "선택한 시장의 보유 종목 또는 벤치마크 가격 데이터가 아직 없습니다."}
            />
          )
        )}

        {portfolioAnalysisTab === "correlation" && (
          riskBudget?.correlation?.status === "OK" ? (
            <div className="mone-home-inset rounded-[10px] border p-3">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-100">종목 간 상관관계 (60일)</h2>
                <span className="rounded-full border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">보유종목 기준</span>
              </div>
              {(riskBudget.correlation.highCorrelationPairs || []).length > 0 ? (
                <div className="max-h-48 space-y-1.5 overflow-y-auto">
                  {riskBudget.correlation.highCorrelationPairs.slice(0, 15).map((pair: any) => (
                    <div key={`${pair.symbolA}-${pair.symbolB}`} className="flex items-center justify-between rounded-lg bg-slate-950/50 px-3 py-1.5 text-[11px]">
                    <span className="text-slate-300">{pair.symbolA} <span className="text-slate-400">vs</span> {pair.symbolB}</span>
                    <div className="flex items-center gap-2">
                      <div className="w-20 overflow-hidden rounded-full bg-slate-800">
                        <div className="h-1.5 rounded-full bg-red-500" style={{ width: `${Math.abs(Number(pair.correlation || 0)) * 100}%` }} />
                      </div>
                      <span className="w-10 text-right font-mono text-red-300">
                        {Number(pair.correlation || 0) > 0 ? "+" : ""}{Number(pair.correlation || 0).toFixed(2)}
                      </span>
                    </div>
                  </div>
                  ))}
                </div>
              ) : (
                <p className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-3 text-[11px] text-emerald-200">현재 기준으로 상관계수 0.70 이상의 고상관 보유 묶음은 없습니다.</p>
              )}
            </div>
          ) : (
            <PortfolioAnalysisEmptyCard
              title="종목 간 상관관계 (60일)"
              detail="상관관계 계산에 필요한 보유 종목 또는 60일 가격 데이터가 부족합니다."
            />
          )
        )}

        {portfolioAnalysisTab === "sector" && (
          portfolioSectors.length > 0 ? (
            <div className="mone-home-inset rounded-[10px] border p-3">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-100">섹터 노출도 히트맵</h2>
                {portfolioSectors.some((sector: any) => sector.status === "OVER" || Number(sector.pct || 0) > Number(riskBudget?.policy?.maxSectorWeightPct || 35)) && (
                  <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">섹터 비중 점검</span>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {portfolioSectors.map((s: any) => {
                  const intensity = s.pct >= 30 ? "bg-red-700/60" : s.pct >= 20 ? "bg-orange-700/50" : s.pct >= 10 ? "bg-amber-700/40" : "bg-slate-700/50";
                  return (
                    <div key={s.sector} className={`rounded-xl ${intensity} px-3 py-2 text-center`} style={{ minWidth: `${Math.max(70, s.pct * 3)}px` }}>
                      <div className="max-w-[120px] truncate text-[11px] font-semibold text-slate-200">{s.sector}</div>
                      <div className="mt-0.5 font-mono text-sm font-bold text-white">{s.pct.toFixed(1)}%</div>
                      <div className="text-[10px] text-slate-300">{Array.isArray(s.symbols) && s.symbols.length > 0 ? `${s.symbols.slice(0, 2).join(", ")}${s.symbols.length > 2 ? ` 외 ${s.symbols.length - 2}` : ""}` : "보유 비중 기준"}</div>
                    </div>
                  );
                })}
              </div>
              {visibleRiskSummary.total > 0 && (
                <div className="mt-4 rounded-xl border border-red-800/30 bg-red-950/20 p-3 text-[11px]">
                  <span className="font-semibold text-red-300">전 종목 손절 시뮬레이션</span>
                  <span className="ml-3 font-mono font-bold text-red-300">
                    {Math.round(visibleRiskSummary.lossAmount).toLocaleString()}원 ({visibleRiskLossPct.toFixed(1)}%)
                  </span>
                  <div className="mt-1 text-[10px] text-slate-400">손절가 미설정 종목은 ATR 기반 추산값으로 계산됩니다. 직접 설정 시 그 값이 우선합니다.</div>
                </div>
              )}
            </div>
          ) : (
            <PortfolioAnalysisEmptyCard
              title="섹터 노출도 히트맵"
              detail="선택한 시장의 보유 종목에 연결된 섹터 데이터가 아직 없습니다."
            />
          )
        )}

        {portfolioAnalysisTab === "optimize" && (
          <div className="mone-home-inset rounded-[10px] border p-3">
            <PortfolioOptimizePanel market={market} riskBudget={riskBudget} />
          </div>
        )}
      </div>
    </div>
  );
}

function PortfolioAnalysisEmptyCard({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="mone-home-inset rounded-[10px] border p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      </div>
      <div className="rounded-xl border border-dashed border-slate-700 bg-slate-950/50 px-4 py-5 text-xs leading-relaxed text-slate-400">
        {detail}
      </div>
    </div>
  );
}

function PortfolioSnapshot({
  holdingCount,
  top5Pct,
  middlePct,
  lowerPct,
  benchmarkName,
  averageAlpha,
}: {
  holdingCount: number;
  top5Pct: number;
  middlePct: number;
  lowerPct: number;
  benchmarkName: string;
  averageAlpha: number | null;
}) {
  const total = Math.max(top5Pct + middlePct + lowerPct, 0);
  const upper = total > 0 ? (top5Pct / total) * 100 : 100;
  const middle = total > 0 ? (middlePct / total) * 100 : 0;
  const lower = Math.max(0, 100 - upper - middle);
  const alphaText = averageAlpha == null ? "계산 대기" : `${averageAlpha >= 0 ? "+" : ""}${averageAlpha.toFixed(2)}%p`;
  const ringStyle = {
    background: `conic-gradient(#22d3c5 0 ${upper}%, #38bdf8 ${upper}% ${upper + middle}%, #2563eb ${upper + middle}% ${upper + middle + lower}%, #232529 ${upper + middle + lower}% 100%)`,
  };
  return (
    <div className="mone-home-inset grid grid-cols-[1fr_auto] items-center gap-3 rounded-[10px] border p-3">
      <div className="min-w-0 border-r border-slate-800/80 pr-3">
        <div className="text-[10px] text-slate-400">집중도 (상위 5개)</div>
        <div className="mt-1 font-mono text-[22px] font-semibold tabular-nums text-teal-300">{top5Pct.toFixed(1)}%</div>
        <div className="mt-1 text-[10px] text-slate-400">보유 비중 기준</div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
          <div className="h-full rounded-full bg-teal-400" style={{ width: `${Math.min(100, top5Pct)}%` }} />
        </div>
        <div className="mt-4 text-[10px] text-slate-400">{benchmarkName} 대비</div>
        <div className={`mt-1 font-mono text-[17px] font-semibold tabular-nums ${averageAlpha == null ? "text-slate-300" : averageAlpha >= 0 ? "text-teal-300" : "text-red-300"}`}>{alphaText}</div>
      </div>
      <div className="flex min-w-[142px] items-center gap-2">
        <div className="relative grid size-[78px] shrink-0 place-items-center rounded-full" style={ringStyle}>
          <div className="grid size-[57px] place-items-center rounded-full bg-slate-950 text-center">
            <span className="block font-mono text-[17px] font-semibold text-slate-100">{holdingCount}개</span>
            <span className="block text-[8.5px] text-slate-400">보유 종목</span>
          </div>
        </div>
        <div className="space-y-1.5 text-[9.5px] text-slate-400">
          <div className="flex items-center justify-between gap-2"><span><i className="mr-1 inline-block size-2 rounded-full bg-teal-400" />상위 5개</span><b className="font-mono font-medium text-slate-300">{top5Pct.toFixed(1)}%</b></div>
          <div className="flex items-center justify-between gap-2"><span><i className="mr-1 inline-block size-2 rounded-full bg-sky-400" />6~10개</span><b className="font-mono font-medium text-slate-300">{middlePct.toFixed(1)}%</b></div>
          <div className="flex items-center justify-between gap-2"><span><i className="mr-1 inline-block size-2 rounded-full bg-blue-600" />그 외</span><b className="font-mono font-medium text-slate-300">{lowerPct.toFixed(1)}%</b></div>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  accent = "text-slate-100",
  subValue,
  visual,
}: {
  label: string;
  value: string;
  accent?: string;
  subValue?: string;
  visual: "value" | "pnl" | "holdings" | "risk";
}) {
  const icon = visual === "value" ? <Eye size={16} className="text-slate-400" />
    : visual === "holdings" ? <BriefcaseBusiness size={18} className="text-teal-300" />
      : visual === "risk" ? <TriangleAlert size={18} className="text-amber-300" />
        : null;
  return (
    <div className="mone-home-card min-w-0 p-3">
      <div className="flex min-h-5 items-center gap-1.5">
        <div className="truncate text-[10px] text-slate-400">{label}</div>
        {visual === "value" && icon}
      </div>
      {visual === "pnl" ? (
        <>
          <div className={`mt-2 min-w-0 break-words font-mono text-[clamp(0.92rem,4.2vw,1.18rem)] font-semibold leading-tight tabular-nums ${accent}`}>{value}</div>
          <div className={`mt-2 font-mono text-[10px] font-semibold tabular-nums ${accent}`}>{subValue || "수익률 확인 중"}</div>
        </>
      ) : visual === "value" ? (
        <>
          <div className={`mt-2 min-w-0 break-words font-mono text-[clamp(0.92rem,4.2vw,1.18rem)] font-semibold leading-tight tabular-nums ${accent}`}>{value}</div>
          <svg viewBox="0 0 92 18" className="mt-2 h-[18px] w-full text-teal-300" aria-label="평가금액 추이">
            <polyline points="0,15 8,12 16,14 24,8 32,11 40,5 48,9 56,4 64,7 72,3 82,6 92,1" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </>
      ) : (
        <>
          <div className="mt-3">{icon}</div>
          <div className={`mt-2 min-w-0 break-words font-mono text-[clamp(1.05rem,5vw,1.3rem)] font-semibold leading-tight tabular-nums ${accent}`}>{value}</div>
        </>
      )}
    </div>
  );
}

function SourceMini({ label, value, accent = "text-slate-200" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="mone-home-inset min-w-0 rounded-[8px] border px-2.5 py-2">
      <div className="text-[10px] text-slate-400">{label}</div>
      <div className={`mt-0.5 min-w-0 truncate text-xs font-semibold ${accent}`}>{value || "확인 대기"}</div>
    </div>
  );
}

function Mini({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="mone-home-inset min-w-0 rounded-[8px] border px-2.5 py-2">
      <div className="text-[10px] text-slate-400">{label}</div>
      <div className={`mt-1 min-w-0 break-keep font-mono text-[11px] font-bold leading-tight sm:text-sm ${accent}`}>{value}</div>
    </div>
  );
}
