"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowRight, Bell, Bot, ChevronDown, Clock, History, RefreshCw,
} from "lucide-react";
import type { PageId } from "../Sidebar";
import { mone, type Horizon, type Mode } from "@/lib/api";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { SentimentBadge } from "@/components/SentimentBadge";
import FearGreedWidget from "@/components/FearGreedWidget";
import {
  getDefaultMarketBySession, getMarketSessionStatus, getSessionCountdown, type SessionPhase,
} from "@/lib/marketSession";
import {
  dataFreshnessBadgeClass, dataFreshnessInfo, dataTrustBadgeClass, dataTrustLabel, dataTrustNotice,
  dedupeBySymbol, displayName, firstText, horizonLabel, modeLabel, moneReasonLines, normalizeMarket,
  priceText, probabilityText,
} from "@/lib/moneDisplay";
import type { BootPreloadData, BootStatus } from "@/lib/bootPreload";

const MODES: Mode[] = ["conservative", "balanced", "aggressive"];
const HORIZONS: Horizon[] = ["short", "swing", "mid"];
type StrategyCell = { mode: Mode; horizon: Horizon; items: any[]; count: number; status: string };
type MarketChoice = "auto" | "kr" | "us";
type DecisionTab = "entry" | "watch" | "risk";

type BriefingPayload = {
  title: string;
  detail: string;
  tone: "emerald" | "amber" | "red" | "blue";
  chips: string[];
  topItem?: any;
};
type AlertTrackingRow = {
  key: string;
  name: string;
  symbol: string;
  recordedAt: string;
  alertPriceText: string;
  currentPriceText: string;
  changeText: string;
  changeTone: "up" | "down" | "neutral";
  status: "추적중" | "목표도달" | "손절도달" | "목표근접" | "리스크확인" | "데이터부족";
  detail: string;
};
type EngineHistoryRow = {
  key: string;
  date: string;
  title: string;
  detail: string;
  status: "적용" | "검증중" | "LOW_SAMPLE" | "대기";
  tone: "emerald" | "amber" | "slate";
};

// ── 캐시 (HomePage.tsx와 동일한 키를 써서 데스크톱/모바일 간 캐시를 공유한다)
const HOME_PAGE_CACHE_TTL = 14 * 60 * 60 * 1000;
const HOME_PAGE_REVALIDATE_TTL = 20 * 60 * 1000;
const HOME_PAGE_STORAGE_PREFIX = "mone:home-summary:v4:";
type HomeCacheEntry = {
  matrix: StrategyCell[];
  holdings: any[];
  summary: any;
  marketRegime: any;
  dataHealth: any;
  allItems: any[];
  ts: number;
};
const _homeCache: Partial<Record<"kr" | "us", HomeCacheEntry>> = {};

function isUsableHomeCache(c: HomeCacheEntry | null | undefined): c is HomeCacheEntry {
  return Boolean(c && Number.isFinite(c.ts) && Date.now() - c.ts < HOME_PAGE_CACHE_TTL);
}
function homeCacheKey(market: "kr" | "us") {
  return `${HOME_PAGE_STORAGE_PREFIX}${market}`;
}
function readStoredHomeCache(market: "kr" | "us"): HomeCacheEntry | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(homeCacheKey(market));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return isUsableHomeCache(parsed) ? parsed : null;
  } catch {
    return null;
  }
}
function readHomeCache(market: "kr" | "us"): HomeCacheEntry | null {
  const c = _homeCache[market];
  if (isUsableHomeCache(c)) return c;
  const stored = readStoredHomeCache(market);
  if (stored) _homeCache[market] = stored;
  return stored;
}
function writeHomeCache(market: "kr" | "us", e: Omit<HomeCacheEntry, "ts">) {
  const entry = { ...e, ts: Date.now() };
  _homeCache[market] = entry;
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(homeCacheKey(market), JSON.stringify(entry));
    } catch {
      // best-effort cache only
    }
  }
}
function shouldReuseHomeCache(c: HomeCacheEntry | null) {
  return Boolean(c && Date.now() - c.ts < HOME_PAGE_REVALIDATE_TTL);
}

function normalizeDateText(value: any) {
  const raw = String(value || "").trim();
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  return raw;
}
function normalizeMarketRegime(raw: any, market: "kr" | "us") {
  if (!raw || typeof raw !== "object") return null;
  const benchmark = String(raw.benchmark || (market === "kr" ? "KOSPI" : "NASDAQ"));
  return {
    ...raw,
    benchmark,
    current: raw.current ?? raw.kospiLatest ?? null,
    ma20: raw.ma20 ?? raw.kospiMa20 ?? null,
    ma60: raw.ma60 ?? raw.kospiMa60 ?? null,
    distanceMa20Pct: raw.distanceMa20Pct ?? raw.distanceToMa20Pct ?? null,
  };
}
function normalizeDataHealth(raw: any) {
  if (!raw || typeof raw !== "object") return null;
  return { ...raw, ohlcvLatestDate: normalizeDateText(raw.ohlcvLatestDate) };
}
function safeNumber(value: any): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const text = String(value ?? "").replace(/,/g, "").replace(/[^0-9.-]/g, "").trim();
  if (!text || text === "-" || text === ".") return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}
function signedPct(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "대기";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}
function shortDateTime(value: any) {
  const text = String(value || "").trim();
  if (!text) return "-";
  return text.slice(5, 16).replace("T", " ");
}
function rowMarket(item: any, fallback: "kr" | "us") {
  return normalizeMarket(item?.market || item?._market || fallback, item?.symbol || item?.code || item?.ticker);
}
function marketLabel(market: "kr" | "us") {
  return market === "kr" ? "국장" : "미장";
}

function pickTopObservation(todayEntries: any[], watchItems: any[], allItems: any[]) {
  return todayEntries[0] || watchItems[0] || [...allItems]
    .sort((a, b) => Number(b.finalScore || b.finalRankScore || 0) - Number(a.finalScore || a.finalRankScore || 0))[0] || null;
}

function buildDailyBriefing(args: {
  topItem: any;
  regime: any;
  dataHealth: any;
  todayCount: number;
  watchCount: number;
  riskCount: number;
  selectedMarket: "kr" | "us";
}): BriefingPayload {
  const { topItem, regime, dataHealth, todayCount, watchCount, riskCount, selectedMarket } = args;
  const freshness = dataFreshnessInfo({
    latestDataDate: dataHealth?.ohlcvLatestDate,
    recoGeneratedAt: dataHealth?.recoGeneratedAt,
    dataStatus: dataHealth?.dataStatus || dataHealth?.status,
  });
  const dataChip = freshness.state === "fresh" ? "데이터 정상" : freshness.state === "old" ? "데이터 확인" : "데이터 제한";
  const regimeChip = regime?.regime === "BULL" ? "강세장" : regime?.regime === "BEAR" ? "약세장" : "중립장";

  if (!topItem) {
    return {
      title: "오늘의 관찰 1순위",
      detail: `${marketLabel(selectedMarket)} 기준으로 신규 후보가 충분하지 않습니다. 보유 종목의 손절가와 데이터 기준을 먼저 확인하세요.`,
      tone: riskCount > 0 ? "red" : "amber",
      chips: [regimeChip, dataChip, "보유종목 확인"],
    };
  }

  const name = displayName(topItem);
  const decision = firstText(topItem.decisionBucket, topItem.newEntryDecision, topItem.moneDecision, "관찰");
  const score = safeNumber(topItem.finalScore ?? topItem.finalRankScore ?? topItem.recommendationScore);
  const ev = safeNumber(topItem.expectedValue ?? topItem.ev);
  const risk = String(topItem.riskStatus || topItem.tradeBlockStatus || "").toUpperCase();
  const isRisk = risk && !["NONE", "OK", "NORMAL", "LOW"].includes(risk);
  const isBear = regime?.regime === "BEAR";
  const scoreText = score != null ? `점수 ${score.toFixed(0)}` : "점수 확인";
  const evText = ev != null ? `EV ${signedPct(ev, 1)}` : "EV 대기";
  const basis = freshness.state === "fresh" ? "현재 기준" : "기준일 확인 필요";
  let detail = `${name}이 ${decision} 후보 중 우선 확인 대상입니다. ${scoreText}, ${evText}이며 ${basis}입니다.`;
  let tone: BriefingPayload["tone"] = "blue";

  if (isBear || isRisk) {
    tone = isRisk ? "red" : "amber";
    detail = `${name}은 신호가 있지만 시장/리스크 조건 확인이 우선입니다. 진입보다 손절가와 기준가 이격을 먼저 보세요.`;
  } else if (String(topItem.decisionBucket || "").includes("오늘")) {
    tone = "emerald";
    detail = `${name}이 오늘 우선 확인 후보입니다. 기준가 접근 여부와 손익비를 확인한 뒤 검토하세요.`;
  } else if (String(topItem.decisionBucket || "").includes("대기")) {
    tone = "amber";
    detail = `${name}은 아직 대기 관찰 구간입니다. 타이밍 조건이 충족되는지 추적하세요.`;
  }

  return {
    title: "오늘의 관찰 1순위",
    detail,
    tone,
    chips: [regimeChip, dataChip, `${todayCount}개 검토`, `${watchCount}개 대기`],
    topItem,
  };
}

function buildAlertTrackingRows(args: {
  signalLedger: any;
  nearAlerts: any[];
  allItems: any[];
  todayEntries: any[];
  watchItems: any[];
  selectedMarket: "kr" | "us";
}): AlertTrackingRow[] {
  const { signalLedger, nearAlerts, allItems, todayEntries, watchItems, selectedMarket } = args;
  const bySymbol = new Map<string, any>();
  [...allItems, ...todayEntries, ...watchItems].forEach((item) => {
    const symbol = String(item.symbol || "").toUpperCase();
    if (symbol) bySymbol.set(`${rowMarket(item, selectedMarket)}-${symbol}`, item);
  });
  const nearMap = new Map<string, any>();
  nearAlerts.forEach((alert) => {
    const symbol = String(alert.symbol || "").toUpperCase();
    if (symbol) nearMap.set(`${rowMarket(alert, selectedMarket)}-${symbol}`, alert);
  });

  const rows: AlertTrackingRow[] = [];
  const ledgerItems = Array.isArray(signalLedger?.items) ? signalLedger.items : [];
  ledgerItems.slice(0, 8).forEach((row: any) => {
    const symbol = String(row.symbol || "").toUpperCase();
    if (!symbol) return;
    const market = rowMarket(row, selectedMarket);
    const match = bySymbol.get(`${market}-${symbol}`) || {};
    const near = nearMap.get(`${market}-${symbol}`);
    const alertPrice = safeNumber(row.entry ?? row.entryPrice);
    const currentPrice = safeNumber(match.currentPrice ?? match.price ?? near?.currentPrice);
    const target = safeNumber(row.target ?? match.target ?? match.targetPrice ?? near?.targetPrice);
    const stop = safeNumber(row.stop ?? match.stop ?? match.stopPrice ?? near?.stopPrice);
    const change = alertPrice && currentPrice ? ((currentPrice - alertPrice) / alertPrice) * 100 : null;
    const outcomes = Array.isArray(row.outcomes) ? row.outcomes : [];
    const hitTarget = outcomes.some((outcome: any) => String(outcome.hit_target).toLowerCase() === "true") || (currentPrice != null && target != null && currentPrice >= target);
    const hitStop = outcomes.some((outcome: any) => String(outcome.hit_stop).toLowerCase() === "true") || (currentPrice != null && stop != null && currentPrice <= stop);
    const nearType = String(near?.type || "").toUpperCase();
    const status: AlertTrackingRow["status"] = hitTarget ? "목표도달"
      : hitStop ? "손절도달"
      : nearType === "TARGET" ? "목표근접"
      : nearType === "STOP" ? "리스크확인"
      : currentPrice == null || alertPrice == null ? "데이터부족"
      : "추적중";
    rows.push({
      key: `ledger-${row.id || symbol}-${row.recorded_at || rows.length}`,
      name: displayName({ ...match, ...row, symbol, market }),
      symbol,
      recordedAt: shortDateTime(row.recorded_at || row.recordedAt || row.recorded_date),
      alertPriceText: alertPrice != null ? priceText({ ...row, market, entry: alertPrice }, "entry") : "-",
      currentPriceText: currentPrice != null ? priceText({ ...match, market, currentPrice }, "current") : "-",
      changeText: signedPct(change, 1),
      changeTone: change == null ? "neutral" : change >= 0 ? "up" : "down",
      status,
      detail: `${modeLabel(String(row.mode || match._mode || "balanced") as Mode)} · ${horizonLabel(String(row.horizon || match._horizon || "swing") as Horizon)}`,
    });
  });

  if (rows.length < 3) {
    [...todayEntries, ...watchItems].slice(0, 5).forEach((item) => {
      const symbol = String(item.symbol || "").toUpperCase();
      if (!symbol || rows.some((row) => row.symbol === symbol)) return;
      const market = rowMarket(item, selectedMarket);
      const entry = safeNumber(item.entry ?? item.entryPrice);
      const current = safeNumber(item.currentPrice ?? item.price);
      const change = entry && current ? ((current - entry) / entry) * 100 : null;
      rows.push({
        key: `fallback-${market}-${symbol}`,
        name: displayName(item),
        symbol,
        recordedAt: "오늘",
        alertPriceText: entry != null ? priceText(item, "entry") : "-",
        currentPriceText: current != null ? priceText(item, "current") : "-",
        changeText: signedPct(change, 1),
        changeTone: change == null ? "neutral" : change >= 0 ? "up" : "down",
        status: current == null || entry == null ? "데이터부족" : "추적중",
        detail: `${modeLabel(String(item._mode || item.mode || "balanced") as Mode)} · ${horizonLabel(String(item._horizon || item.horizon || "swing") as Horizon)}`,
      });
    });
  }

  return rows.slice(0, 3);
}

function buildEngineHistoryRows(adaptiveWeights: any, selfLearningStatus: any): EngineHistoryRow[] {
  const rows: EngineHistoryRow[] = [];
  const applications = Array.isArray(selfLearningStatus?.lastApplications) ? selfLearningStatus.lastApplications : [];
  applications.slice(0, 2).forEach((item: any, index: number) => {
    const statusText = String(item.status || "").toUpperCase();
    rows.push({
      key: `self-${item.applied_at || item.version || index}`,
      date: shortDateTime(item.applied_at || item.appliedAt || selfLearningStatus?.generatedAt),
      title: `${modeLabel(String(item.mode || "balanced") as Mode)} ${horizonLabel(String(item.horizon || "swing") as Horizon)} 보정 적용`,
      detail: `version ${item.version || selfLearningStatus?.correctionVersion || "-"} · ${item.market || "all"}`,
      status: statusText === "APPLIED" ? "적용" : "검증중",
      tone: statusText === "APPLIED" ? "emerald" : "amber",
    });
  });

  const signalRows = Array.isArray(adaptiveWeights?.bySignalKey) ? adaptiveWeights.bySignalKey : [];
  signalRows.slice(0, 4).forEach((item: any, index: number) => {
    const sample = Number(item.sampleCount || 0);
    const eligible = Boolean(item.learningEligible);
    rows.push({
      key: `weight-${item.signalKey || index}`,
      date: shortDateTime(item.lastUpdated || adaptiveWeights?.generatedAt),
      title: `${item.signalKey || "adaptive weight"} 가중치 ${eligible ? "검증" : "대기"}`,
      detail: `sample ${sample} · weight ${Number(item.weight ?? item.currentWeight ?? 0).toFixed(2)}`,
      status: sample > 0 && !eligible ? "LOW_SAMPLE" : eligible ? "검증중" : "대기",
      tone: eligible ? "amber" : "slate",
    });
  });

  if (!rows.length) {
    const lowSample = Number(selfLearningStatus?.lowSampleCount || 0);
    rows.push({
      key: "engine-waiting",
      date: shortDateTime(selfLearningStatus?.generatedAt || adaptiveWeights?.generatedAt),
      title: "AI 엔진 변경 이력 대기",
      detail: lowSample > 0 ? `LOW_SAMPLE ${lowSample}건 · 검증 표본 축적 중` : "검증 표본이 쌓이면 보정 이력이 표시됩니다.",
      status: lowSample > 0 ? "LOW_SAMPLE" : "대기",
      tone: lowSample > 0 ? "amber" : "slate",
    });
  }
  return rows.slice(0, 3);
}

function getMarketGateInfo(regime: any, dataHealth: any) {
  const base = regime?.regime === "BULL" ? 70 : regime?.regime === "BEAR" ? 22 : 50;
  const maDist = Number(regime?.distanceMa20Pct ?? regime?.distanceToMa20Pct ?? 0);
  const maAdj = maDist >= 3 ? 10 : maDist >= 1 ? 5 : maDist >= -1 ? 0 : maDist >= -3 ? -8 : -15;

  const recoAt = dataHealth?.recoGeneratedAt ? new Date(dataHealth.recoGeneratedAt) : null;
  const hoursOld = recoAt ? (Date.now() - recoAt.getTime()) / 3600000 : null;
  const liveRatio = (dataHealth?.kisTargetCount ?? 0) > 0
    ? (dataHealth?.kisLiveCount ?? 0) / dataHealth.kisTargetCount : 1;
  const hasOhlcv = Number(dataHealth?.ohlcvCount ?? 0) > 0;
  const dataAdj = hoursOld != null && hoursOld > 24 ? -15 : liveRatio < 0.1 ? (hasOhlcv ? -8 : -20) : liveRatio < 0.5 ? -5 : 0;

  const strength = Math.max(0, Math.min(100, base + maAdj + dataAdj));
  const levelText = strength >= 75 ? "적극 진입" : strength >= 55 ? "정상 진입" : strength >= 35 ? "선별 진입" : "진입 자제";
  const isHigh = strength >= 55;
  const isMid = strength >= 35 && strength < 55;
  const isLow = strength < 35;

  return { strength, levelText, isHigh, isMid, isLow, maDist, dataAdj, hasOhlcv };
}

function getHoldingJudgment(item: any): { text: string; cls: string } {
  const risk = String(item.riskStatus || "");
  if (["HIGH", "위험"].includes(risk)) return { text: "손절 검토", cls: "bg-red-900/40 border-red-700/40 text-red-300" };
  if (["WATCH", "주의"].includes(risk)) return { text: "주의 필요", cls: "bg-amber-900/30 border-amber-700/40 text-amber-300" };

  const current = Number(item.currentPrice || 0);
  const avg = Number(item.avgPrice || item.avgBuyPrice || 0);
  const target = Number(item.targetPrice || 0);
  if (current > 0 && avg > 0 && target > avg) {
    const progress = (current - avg) / (target - avg);
    if (progress >= 0.8) return { text: "일부익절 검토", cls: "bg-emerald-900/30 border-emerald-700/40 text-emerald-300" };
    if (progress >= 0.5) return { text: "목표가 근접", cls: "bg-sky-900/30 border-sky-700/40 text-sky-300" };
  }
  return { text: "유지", cls: "bg-slate-800/60 border-slate-700/40 text-slate-400" };
}

const MODE_CAPS: Record<string, number> = { conservative: 0.05, balanced: 0.10, aggressive: 0.15 };
const PORTFOLIO_SIZING_CAP = 0.8;

interface SizingRow {
  symbol: string;
  name: string;
  mode: string;
  horizon: string;
  entry: number;
  prob: number;
  rr: number;
  halfKelly: number;
  amount: number;
  rawAmount: number;
  effectivePct: number;
  scaled: boolean;
  qty: number;
  ev: number;
}

function calcSizing(items: any[], capital: number): SizingRow[] {
  const seen = new Set<string>();
  const rawRows = items
    .filter((i) => i.decisionBucket === "오늘 진입")
    .flatMap((i) => {
      const key = `${i.symbol}-${i._mode}-${i._horizon}`;
      if (seen.has(key)) return [];
      seen.add(key);

      const entry = Number(i.entry || i.entryPrice || 0);
      const prob = Math.min(Math.max(Number(i.probability || 55) / 100, 0.3), 0.8);
      const rr = Math.max(Number(i.rrActual || i.rr || 1.5), 0.5);
      const mode = String(i._mode || i.mode || "balanced");
      if (entry <= 0 || capital <= 0) return [];

      const kelly = Math.max(0, prob - (1 - prob) / rr);
      const cap = MODE_CAPS[mode] ?? 0.10;
      const halfKelly = Math.min(kelly / 2, cap);
      const rawAmount = Math.floor(capital * halfKelly);
      const qty = Math.floor(rawAmount / entry);

      return [{
        symbol: String(i.symbol || ""),
        name: String(i.name || i.companyName || i.symbol || ""),
        mode,
        horizon: String(i._horizon || i.horizon || ""),
        entry, prob, rr, halfKelly,
        amount: qty * entry,
        rawAmount,
        effectivePct: capital > 0 ? (qty * entry) / capital : 0,
        scaled: false,
        qty,
        ev: Number(i.expectedValue || 0),
      }];
    });

  const totalRawAmount = rawRows.reduce((sum, row) => sum + row.rawAmount, 0);
  const capAmount = Math.floor(capital * PORTFOLIO_SIZING_CAP);
  const scale = totalRawAmount > capAmount && capAmount > 0 ? capAmount / totalRawAmount : 1;

  return rawRows
    .map((row) => {
      const cappedAmount = Math.floor(row.rawAmount * scale);
      const qty = Math.floor(cappedAmount / row.entry);
      const amount = qty * row.entry;
      return { ...row, amount, effectivePct: capital > 0 ? amount / capital : 0, qty, scaled: scale < 0.999 };
    })
    .filter((row) => row.qty > 0)
    .sort((a, b) => b.halfKelly - a.halfKelly);
}

// ── 매크로/실적 이벤트 배너 (HomePage.tsx의 EventBanner와 동등)
function AlertBanner({ alert }: { alert: any }) {
  const [dismissed, setDismissed] = useState(false);
  if (!alert || dismissed) return null;
  const highMacro: any[] = alert.todayHighMacro || [];
  const allMacro: any[] = alert.todayAllMacro || [];
  const todayEarnings: any[] = alert.todayEarnings || [];
  const tmrwHigh: any[] = alert.tomorrowHighMacro || [];
  const tmrwEarnings: any[] = alert.tomorrowEarnings || [];
  const hasHigh = highMacro.length > 0;
  const hasMed = allMacro.length > 0 || todayEarnings.length > 0;
  const hasTomorrow = tmrwHigh.length > 0 || tmrwEarnings.length > 0;
  if (!hasHigh && !hasMed && !hasTomorrow) return null;
  const bgClass = hasHigh ? "border-red-500/40 bg-red-500/10" : hasMed ? "border-amber-500/40 bg-amber-500/10" : "border-slate-600/60 bg-slate-800/60";
  const iconClass = hasHigh ? "text-red-400" : hasMed ? "text-amber-400" : "text-slate-500";

  return (
    <div className={`relative flex items-start gap-3 rounded-xl border px-3.5 py-2.5 text-xs ${bgClass}`}>
      <AlertTriangle size={14} className={`mt-0.5 shrink-0 ${iconClass}`} />
      <div className="min-w-0 flex-1">
        {highMacro.length > 0 && (
          <div className="font-semibold text-red-200">
            🔴 오늘 주요 지표:
            {highMacro.slice(0, 2).map((e: any, i: number) => (
              <span key={i} className="ml-1 rounded-full border border-red-500/30 bg-red-500/15 px-1.5 py-0.5 text-[10px]">{e.event}</span>
            ))}
          </div>
        )}
        {!hasHigh && allMacro.length > 0 && (
          <div className="font-medium text-amber-300">
            ⚠️ 오늘 경제지표:
            {allMacro.slice(0, 2).map((e: any, i: number) => (
              <span key={i} className="ml-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200">{e.event}</span>
            ))}
          </div>
        )}
        {todayEarnings.length > 0 && (
          <div className="mt-0.5 text-[11px] text-slate-300">
            📊 오늘 실적: {todayEarnings.slice(0, 4).map((e: any) => e.symbol || e.name).join(", ")}
          </div>
        )}
        {!hasHigh && !hasMed && (tmrwHigh.length > 0 || tmrwEarnings.length > 0) && (
          <div className="text-[11px] text-slate-400">
            📅 내일 예정: {[...tmrwHigh.slice(0, 2), ...tmrwEarnings.slice(0, 2)].map((e: any) => e.event || e.symbol || e.name).join(", ")}
          </div>
        )}
      </div>
      <button onClick={() => setDismissed(true)} className="absolute right-1.5 top-1.5 rounded-lg p-1.5 text-slate-500 hover:bg-slate-700/50 hover:text-slate-300" aria-label="닫기">×</button>
    </div>
  );
}

// ── 오늘의 관찰 1순위 / AI 브리핑
function GuideCard({ briefing, onAnalyze }: { briefing: BriefingPayload; onAnalyze?: (item: any) => void }) {
  const tone = {
    emerald: { shell: "border-emerald-500/25 bg-emerald-500/10", icon: "bg-emerald-500/15 text-emerald-300", text: "text-emerald-100", chip: "border-emerald-400/20 bg-slate-950/35 text-emerald-100" },
    amber: { shell: "border-amber-500/25 bg-amber-500/10", icon: "bg-amber-500/15 text-amber-300", text: "text-amber-100", chip: "border-amber-400/20 bg-slate-950/35 text-amber-100" },
    red: { shell: "border-red-500/25 bg-red-500/10", icon: "bg-red-500/15 text-red-300", text: "text-red-100", chip: "border-red-400/20 bg-slate-950/35 text-red-100" },
    blue: { shell: "border-sky-500/25 bg-sky-500/10", icon: "bg-sky-500/15 text-sky-300", text: "text-sky-100", chip: "border-sky-400/20 bg-slate-950/35 text-sky-100" },
  }[briefing.tone];

  return (
    <section className={`rounded-2xl border px-4 py-3.5 ${tone.shell}`}>
      <div className="flex gap-3">
        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl ${tone.icon}`}>
          <Activity size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">AI 한 줄 브리핑</div>
          <h2 className={`mt-0.5 text-sm font-bold ${tone.text}`}>{briefing.title}</h2>
          <p className="mt-1 text-[13px] leading-5 text-slate-300">{briefing.detail}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {briefing.chips.slice(0, 4).map((chip) => (
              <span key={chip} className={`rounded-full border px-2 py-0.5 text-[10px] ${tone.chip}`}>{chip}</span>
            ))}
          </div>
          {briefing.topItem && onAnalyze && (
            <button
              type="button"
              onClick={() => onAnalyze(briefing.topItem)}
              className="mt-2 flex items-center gap-1 text-[11px] font-semibold text-slate-300 hover:text-white"
            >
              근거 보기 <ArrowRight size={12} />
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

// ── 시장 컨디션 게이트
function MarketGateCard({ regime, dataHealth, selectedMarket }: { regime: any; dataHealth: any; selectedMarket: "kr" | "us" }) {
  const { strength, levelText, isHigh, isMid, isLow, maDist, dataAdj, hasOhlcv } = getMarketGateInfo(regime, dataHealth);
  const borderCls = isHigh ? "border-emerald-800/40 bg-emerald-950/15" : isMid ? "border-amber-800/40 bg-amber-950/15" : "border-red-800/40 bg-red-950/15";
  const textCls = isHigh ? "text-emerald-300" : isMid ? "text-amber-300" : "text-red-300";
  const barCls = isHigh ? "bg-emerald-500" : isMid ? "bg-amber-500" : "bg-red-500";
  const freshness = dataFreshnessInfo({
    latestDataDate: dataHealth?.ohlcvLatestDate,
    recoGeneratedAt: dataHealth?.recoGeneratedAt,
    dataStatus: dataHealth?.dataStatus || dataHealth?.status,
  });

  return (
    <div className="space-y-3">
      <div className={`rounded-2xl border p-4 ${borderCls}`}>
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">시장 컨디션 게이트</div>
            <div className={`mt-1 text-base font-bold ${textCls}`}>{levelText}</div>
          </div>
          <div className={`shrink-0 text-right font-mono font-black ${textCls}`}>
            <span className="text-3xl">{strength}</span>
            <span className="text-sm text-slate-500">/100</span>
          </div>
        </div>
        <div className="mb-3 h-2 w-full rounded-full bg-slate-800">
          <div className={`h-2 rounded-full transition-all duration-500 ${barCls}`} style={{ width: `${strength}%` }} />
        </div>
        <div className="grid grid-cols-3 gap-2 text-[10px]">
          <div className="rounded-lg bg-slate-900/60 px-2 py-1.5 text-center">
            <div className="text-slate-500">시장 추세</div>
            <div className={`mt-0.5 font-semibold ${regime?.regime === "BULL" ? "text-emerald-300" : regime?.regime === "BEAR" ? "text-red-300" : "text-slate-300"}`}>
              {regime?.regime === "BULL" ? "강세" : regime?.regime === "BEAR" ? "약세" : "중립"}
            </div>
          </div>
          <div className="rounded-lg bg-slate-900/60 px-2 py-1.5 text-center">
            <div className="text-slate-500">MA20 이격</div>
            <div className={`mt-0.5 font-mono font-semibold ${maDist >= 0 ? "text-emerald-300" : "text-red-300"}`}>
              {maDist >= 0 ? "+" : ""}{maDist.toFixed(1)}%
            </div>
          </div>
          <div className="rounded-lg bg-slate-900/60 px-2 py-1.5 text-center">
            <div className="text-slate-500">데이터</div>
            <div className={`mt-0.5 font-semibold ${dataAdj === 0 ? "text-emerald-300" : dataAdj <= -15 ? "text-red-300" : "text-amber-300"}`}>
              {dataAdj === 0 ? "정상" : dataAdj <= -15 ? "오류" : hasOhlcv ? "종가 기준" : "부분"}
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-800/70 pt-3 text-[10px] text-slate-500">
          <span className={`rounded-full border px-2 py-0.5 ${dataFreshnessBadgeClass(freshness.state)}`}>{freshness.label}</span>
          <span>{freshness.basisText}</span>
        </div>
        {isLow && (
          <div className="mt-3 rounded-lg border border-red-800/40 bg-red-950/30 px-3 py-2 text-[10px] text-red-300">
            ⚠ 신규 진입 시 평소보다 엄격한 기준을 적용하세요.
          </div>
        )}
      </div>
      <FearGreedWidget market={selectedMarket} />
    </div>
  );
}

// ── 후보 카드 (오늘 진입)
function EntryCandidateCard({ item, rank, onAnalyze, onTradePaper }: { item: any; rank: number; onAnalyze: (item: any) => void; onTradePaper?: (item: any) => void }) {
  const score = Number(item.finalScore || 0);
  const confidence = probabilityText(item, score > 0 ? `${score.toFixed(0)}점` : "-");
  const reasons = moneReasonLines(item).slice(0, 2);
  const riskRaw = String(item.riskStatus || item.tradeBlockStatus || item.riskLevel || "").toUpperCase();
  const riskText = !riskRaw || ["NONE", "OK", "NORMAL", "LOW"].includes(riskRaw) ? "위험 낮음" : riskRaw.includes("WATCH") || riskRaw.includes("주의") ? "주의" : "위험 확인";
  const riskClass = riskText === "위험 낮음" ? "text-emerald-300" : riskText === "주의" ? "text-amber-300" : "text-red-300";

  return (
    <div className="relative w-[78vw] max-w-[300px] shrink-0 snap-start rounded-2xl border border-emerald-800/50 bg-gradient-to-br from-emerald-950/25 to-slate-950 p-3.5">
      <div className="absolute -left-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-[11px] font-bold text-white">{rank}</div>
      <div className="flex items-center gap-1.5">
        <span className="truncate text-sm font-semibold text-slate-100">{displayName(item)}</span>
        <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${dataTrustBadgeClass(item)}`}>{dataTrustLabel(item)}</span>
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-500">
        <span>{item.symbol} · {modeLabel(String(item._mode || item.mode) as Mode)} · {horizonLabel(String(item._horizon || item.horizon) as Horizon)}</span>
        <SentimentBadge symbol={item.symbol} market={normalizeMarket(item.market || item._market, item.symbol)} name={String(item.name || "")} />
      </div>
      <div className="mt-2.5 grid grid-cols-3 gap-1.5 text-[10px]">
        <div><div className="text-slate-500">현재가</div><div className="font-mono text-slate-200">{priceText(item, "current", "-")}</div></div>
        <div><div className="text-slate-500">기준가</div><div className="font-mono text-sky-300">{priceText(item, "entry", "-")}</div></div>
        <div><div className="text-slate-500">목표가</div><div className="font-mono text-emerald-300">{priceText(item, "target", "-")}</div></div>
      </div>
      <div className="mt-1.5 flex items-center gap-3 text-[10px]">
        <span className="text-slate-500">신뢰도 <span className="font-mono text-blue-300">{confidence}</span></span>
        <span className="text-slate-500">위험 <span className={`font-semibold ${riskClass}`}>{riskText}</span></span>
      </div>
      {reasons.length > 0 && (
        <div className="mt-2 rounded-lg border border-slate-800/70 bg-slate-950/50 px-2.5 py-1.5 text-[10px] leading-4 text-slate-400">
          {reasons.map((r, i) => <div key={r}>{i + 1}. {r}</div>)}
        </div>
      )}
      <div className="mt-2.5 flex gap-1.5">
        <button onClick={() => onAnalyze(item)} className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-blue-600 px-2 py-1.5 text-xs font-semibold text-white hover:bg-blue-500">
          분석 보기 <ArrowRight size={12} />
        </button>
        {onTradePaper && (
          <button onClick={() => onTradePaper(item)} className="rounded-lg border border-emerald-700/50 bg-emerald-900/30 px-2 py-1.5 text-[11px] font-semibold text-emerald-300 hover:bg-emerald-900/60">
            모의투자
          </button>
        )}
      </div>
    </div>
  );
}

// ── 후보 카드 (대기 관찰)
function WatchCandidateCard({ item, onAnalyze }: { item: any; onAnalyze: (item: any) => void }) {
  const timingLabel = String(item.timingLabel || "대기");
  const timingColor =
    timingLabel.includes("1~2일") ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
    : timingLabel.includes("3~5일") ? "border-orange-500/40 bg-orange-500/10 text-orange-300"
    : timingLabel.includes("다음 주") ? "border-slate-600 bg-slate-800/60 text-slate-400"
    : "border-cyan-500/30 bg-cyan-500/10 text-cyan-300";

  return (
    <div onClick={() => onAnalyze(item)} className="w-[78vw] max-w-[300px] shrink-0 cursor-pointer snap-start rounded-2xl border border-slate-700/60 bg-slate-900/50 p-3.5 transition-colors hover:border-amber-700/50">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-slate-200">{displayName(item)}</span>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${timingColor}`}>{timingLabel}</span>
      </div>
      <div className="mt-0.5 text-[10px] text-slate-500">{item.symbol} · {modeLabel(String(item._mode || item.mode) as Mode)} · {horizonLabel(String(item._horizon || item.horizon) as Horizon)}</div>
      {item.timingReason && <div className="mt-1.5 text-[11px] text-slate-400">{item.timingReason}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-2.5 text-[10px]">
        <span className="text-slate-500">현재 <span className="font-mono text-slate-300">{priceText(item, "current", "-")}</span></span>
        <span className="text-slate-500">목표 <span className="font-mono text-emerald-400">{priceText(item, "target", "-")}</span></span>
        <span className={`font-mono ${Number(item.expectedValue || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          EV {Number(item.expectedValue || 0) >= 0 ? "+" : ""}{Number(item.expectedValue || 0).toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

// ── 후보 카드 (위험 보류)
function RiskCandidateCard({ item, onAnalyze }: { item: any; onAnalyze: (item: any) => void }) {
  return (
    <div onClick={() => onAnalyze(item)} className="w-[78vw] max-w-[300px] shrink-0 cursor-pointer snap-start rounded-2xl border border-red-900/40 bg-red-950/15 p-3.5 opacity-90 transition-colors hover:opacity-100">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-slate-200">{displayName(item)}</span>
        <span className="shrink-0 rounded-full border border-red-700/40 bg-red-900/30 px-2 py-0.5 text-[10px] font-semibold text-red-300">{item.decisionBucket || "주의"}</span>
      </div>
      <div className="mt-0.5 text-[10px] text-slate-500">{item.symbol} · {modeLabel(String(item._mode || item.mode) as Mode)} · {horizonLabel(String(item._horizon || item.horizon) as Horizon)}</div>
      {dataTrustNotice(item) ? (
        <div className="mt-1.5 text-[11px] text-amber-300">{dataTrustNotice(item)}</div>
      ) : (
        <div className="mt-1.5 text-[11px] text-slate-400">EV·리스크 조건 미달로 보류된 후보입니다.</div>
      )}
      <div className="mt-2 flex items-center gap-2.5 text-[10px]">
        <span className="text-slate-500">현재 <span className="font-mono text-slate-300">{priceText(item, "current", "-")}</span></span>
        <span className={`font-mono ${Number(item.expectedValue || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          EV {Number(item.expectedValue || 0) >= 0 ? "+" : ""}{Number(item.expectedValue || 0).toFixed(1)}%
        </span>
      </div>
    </div>
  );
}

// ── 3×3 전략 타일 (간략)
function StrategyTile({ cell }: { cell: StrategyCell }) {
  const top = (cell.items || []).slice(0, 2);
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-2.5">
      <div className="flex items-center justify-between text-[10px]">
        <span className="font-semibold text-slate-300">{modeLabel(cell.mode)} · {horizonLabel(cell.horizon)}</span>
        <span className="text-slate-500">{cell.count}개</span>
      </div>
      {top.length === 0 ? (
        <div className="mt-1.5 text-[10px] text-slate-600">조건 없음</div>
      ) : (
        <div className="mt-1.5 space-y-1">
          {top.map((item) => (
            <div key={item.symbol} className="truncate text-[10px] text-slate-400">{displayName(item)}</div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function HomePageMobile({
  onNavigate,
  onTradePaper,
  bootStatus = "idle",
}: {
  onNavigate?: (page: PageId) => void;
  onTradePaper?: (order: { symbol: string; name: string; price: number; market: "kr" | "us"; quantity?: number }) => void;
  bootData?: BootPreloadData | null;
  bootStatus?: BootStatus;
  booting?: boolean;
}) {
  const [allItems, setAllItems] = useState<any[]>([]);
  const [matrix, setMatrix] = useState<StrategyCell[]>([]);
  const [holdings, setHoldings] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [marketRegime, setMarketRegime] = useState<any>(null);
  const [dataHealth, setDataHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshWarning, setRefreshWarning] = useState("");
  const [marketChoice, setMarketChoice] = useState<MarketChoice>("auto");
  const [clientReady, setClientReady] = useState(false);
  const [clock, setClock] = useState<Date | null>(null);
  const [decisionTab, setDecisionTab] = useState<DecisionTab>("entry");
  const [moreOpen, setMoreOpen] = useState(false);
  const [calendarAlert, setCalendarAlert] = useState<any>(null);
  const [nearAlerts, setNearAlerts] = useState<any[]>([]);
  const [signalLedger, setSignalLedger] = useState<any>(null);
  const [adaptiveWeights, setAdaptiveWeights] = useState<any>(null);
  const [selfLearningStatus, setSelfLearningStatus] = useState<any>(null);
  const [capital, setCapital] = useState<number>(() => {
    if (typeof window === "undefined") return 0;
    return Number(window.localStorage.getItem("mone:capital") || "0");
  });
  const [capitalInput, setCapitalInput] = useState("");

  const sessionClock = clock || new Date();
  const selectedMarket = marketChoice === "auto" ? (clientReady ? getDefaultMarketBySession(sessionClock) : "kr") : marketChoice;
  const sessionStatus = clientReady ? getMarketSessionStatus(selectedMarket, sessionClock) : "확인 중";
  const sessionPhase = sessionStatus as SessionPhase;
  const countdown = clientReady ? getSessionCountdown(selectedMarket, sessionClock) : "";

  function updateMarketChoice(next: MarketChoice) {
    setMarketChoice(next);
    if (typeof window !== "undefined") window.localStorage.setItem("mone:selectedMarketMode", next);
  }

  const openAnalysis = useCallback((item: any) => {
    const symbol = String(item.symbol || item.code || item.ticker || "").trim();
    if (typeof window !== "undefined" && symbol) {
      const market = normalizeMarket(item.market || selectedMarket, symbol);
      window.localStorage.setItem("mone_chart_symbol", symbol);
      window.localStorage.setItem("mone_chart_market", market);
      window.localStorage.setItem("mone_chart_name", displayName(item));
      window.localStorage.setItem("mone_chart_price", String(item.currentPrice || item.price || ""));
      window.localStorage.setItem("mone_chart_price_text", priceText(item, "current", ""));
      window.dispatchEvent(new CustomEvent("mone-open-chart", { detail: { symbol, market } }));
    }
    onNavigate?.("chart");
  }, [onNavigate, selectedMarket]);

  async function load(options: { background?: boolean } = {}) {
    const hasCurrentData = options.background || allItems.length > 0 || matrix.length > 0;
    if (hasCurrentData) { setRefreshing(true); setLoading(false); } else { setLoading(true); }
    setRefreshWarning("");
    try {
      const result = await mone.homeSummary({ market: selectedMarket, limit: 12 });
      const matrixResult: StrategyCell[] = MODES.flatMap((mode) =>
        HORIZONS.map((horizon) => {
          const cell = (result.matrix as any)?.[`${mode}_${horizon}`] || {};
          const items = dedupeBySymbol(Array.isArray(cell.items) ? cell.items : [])
            .slice(0, 5)
            .map((item: any) => ({ ...item, _mode: mode, _horizon: horizon }));
          return { mode, horizon, items, count: Number(cell.count || items.length || 0), status: String(cell.status || "OK") } satisfies StrategyCell;
        })
      );
      const h = result.holdings || {};
      const holdingItems = dedupeBySymbol(Array.isArray(h.items) ? h.items : []);
      const holdingSummary = h.summary || null;
      const regime = normalizeMarketRegime(result.marketRegime, selectedMarket);
      const health = normalizeDataHealth(result.dataHealth);
      const allItemsFlat = matrixResult.flatMap((cell) => cell.items);
      setHoldings(holdingItems);
      setSummary(holdingSummary);
      setMatrix(matrixResult);
      setMarketRegime(regime);
      setDataHealth(health);
      setAllItems(allItemsFlat);
      writeHomeCache(selectedMarket, { matrix: matrixResult, holdings: holdingItems, summary: holdingSummary, marketRegime: regime, dataHealth: health, allItems: allItemsFlat });
    } catch {
      if (!hasCurrentData) {
        setHoldings([]); setSummary(null); setMatrix([]); setAllItems([]); setDataHealth(null);
      } else {
        setRefreshWarning("데이터 갱신에 실패해 기존 값을 유지합니다.");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    setClientReady(true);
    const saved = window.localStorage.getItem("mone:selectedMarketMode");
    if (saved === "kr" || saved === "us" || saved === "auto") setMarketChoice(saved);
    setCapitalInput(capital > 0 ? String(capital) : "");
    const refreshClock = () => setClock(new Date());
    refreshClock();
    const timer = window.setInterval(refreshClock, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!clientReady) return;
    const cached = readHomeCache(selectedMarket);
    if (cached) {
      setMatrix(cached.matrix);
      setHoldings(cached.holdings);
      setSummary(cached.summary);
      setMarketRegime(cached.marketRegime);
      setDataHealth(cached.dataHealth);
      setAllItems(cached.allItems);
      setLoading(false);
      setRefreshWarning("");
      if (shouldReuseHomeCache(cached)) return;
      load({ background: true });
      return;
    }
    load();
  }, [clientReady, selectedMarket]);

  useEffect(() => {
    if (!clientReady) return;
    let active = true;
    const timer = window.setTimeout(() => {
      mone.calendarToday({ market: selectedMarket as any })
        .then((res) => { if (active && res?.status === "OK") setCalendarAlert(res); })
        .catch(() => {});
    }, 2500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [clientReady, selectedMarket]);

  useEffect(() => {
    if (!clientReady) return;
    let active = true;
    const timer = window.setTimeout(() => {
      mone.nearAlerts({ market: selectedMarket, thresholdPct: 5 })
        .then((res) => { if (active) setNearAlerts(Array.isArray(res.alerts) ? res.alerts : []); })
        .catch(() => { if (active) setNearAlerts([]); });
    }, 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [clientReady, selectedMarket]);

  useEffect(() => {
    if (!clientReady) return;
    let active = true;
    const timer = window.setTimeout(() => {
      Promise.allSettled([
        mone.signalsLedger({ market: selectedMarket, limit: 12 }),
        mone.adaptiveWeights({ limit: 12 }),
        mone.journalSelfLearningStatus({ market: selectedMarket }),
      ]).then(([ledger, weights, learning]) => {
        if (!active) return;
        setSignalLedger(ledger.status === "fulfilled" ? ledger.value : null);
        setAdaptiveWeights(weights.status === "fulfilled" ? weights.value : null);
        setSelfLearningStatus(learning.status === "fulfilled" ? learning.value : null);
      }).catch(() => {});
    }, 2800);
    return () => { active = false; window.clearTimeout(timer); };
  }, [clientReady, selectedMarket]);

  const todayEntries = useMemo(() => {
    const seen = new Set<string>();
    return allItems
      .filter((i) => i.decisionBucket === "오늘 진입" && Number(i.expectedValue || 0) > 0)
      .sort((a, b) => Number(b.expectedValue || 0) - Number(a.expectedValue || 0))
      .filter((i) => {
        const key = `${i.symbol}-${i._mode}-${i._horizon}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }, [allItems]);

  const watchItems = useMemo(() => {
    const timingOrder: Record<string, number> = { "1~2일 후 진입": 0, "3~5일 후 진입": 1, "눌림 대기": 2, "다음 주 진입": 3 };
    const seen = new Set<string>();
    return allItems
      .filter((i) => i.decisionBucket === "대기 관찰")
      .sort((a, b) => {
        const ao = timingOrder[a.timingLabel] ?? 9;
        const bo = timingOrder[b.timingLabel] ?? 9;
        if (ao !== bo) return ao - bo;
        return Number(b.finalScore || 0) - Number(a.finalScore || 0);
      })
      .filter((i) => {
        const key = `${i.symbol}-${i._mode}-${i._horizon}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }, [allItems]);

  const riskHeldItems = useMemo(() => {
    const seen = new Set<string>();
    return allItems
      .filter((i) => ["주의", "매수금지"].includes(String(i.decisionBucket || "")))
      .filter((i) => {
        const key = `${i.symbol}-${i._mode}-${i._horizon}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }, [allItems]);

  const riskCount = holdings.filter((h) => ["위험", "주의", "HIGH", "WATCH"].includes(String(h.riskStatus || ""))).length;

  const topObservation = useMemo(() => pickTopObservation(todayEntries, watchItems, allItems), [todayEntries, watchItems, allItems]);

  const dailyBriefing = useMemo(
    () => buildDailyBriefing({ topItem: topObservation, regime: marketRegime, dataHealth, todayCount: todayEntries.length, watchCount: watchItems.length, riskCount, selectedMarket }),
    [topObservation, marketRegime, dataHealth, todayEntries.length, watchItems.length, riskCount, selectedMarket],
  );

  const alertTrackingRows = useMemo(
    () => buildAlertTrackingRows({ signalLedger, nearAlerts, allItems, todayEntries, watchItems, selectedMarket }),
    [signalLedger, nearAlerts, allItems, todayEntries, watchItems, selectedMarket],
  );

  const engineHistoryRows = useMemo(() => buildEngineHistoryRows(adaptiveWeights, selfLearningStatus), [adaptiveWeights, selfLearningStatus]);

  const sizingRows = useMemo(() => calcSizing(todayEntries, capital), [todayEntries, capital]);

  function handleCapitalChange(raw: string) {
    const clean = raw.replace(/[^0-9]/g, "");
    setCapitalInput(clean);
    const n = Number(clean);
    if (n >= 100_000) {
      setCapital(n);
      if (typeof window !== "undefined") window.localStorage.setItem("mone:capital", String(n));
    }
  }

  const freshness = dataFreshnessInfo({
    latestDataDate: dataHealth?.ohlcvLatestDate,
    recoGeneratedAt: dataHealth?.recoGeneratedAt,
    dataStatus: dataHealth?.dataStatus || dataHealth?.status,
  });

  const activeCandidates = decisionTab === "entry" ? todayEntries : decisionTab === "watch" ? watchItems : riskHeldItems;

  if (loading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="flex items-center gap-2">
          <RefreshCw size={16} className="animate-spin text-slate-500" />
          <span className="text-sm text-slate-500">데이터 불러오는 중...</span>
        </div>
      </div>
    );
  }

  return (
    <ErrorBoundary>
      <div className="space-y-4">
        {/* 페이지 헤더 */}
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <h1 className="text-lg font-bold text-slate-100">홈</h1>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-500">
              <span className={`rounded-full px-1.5 py-0.5 font-medium ${
                sessionPhase === "장중" ? "bg-emerald-900/50 text-emerald-300"
                : sessionPhase === "장마감" ? "bg-blue-900/50 text-blue-300"
                : sessionPhase === "휴장" ? "bg-slate-800 text-slate-400"
                : "bg-slate-800 text-slate-400"
              }`}>{sessionStatus}</span>
              {countdown && <span className="flex items-center gap-1"><Clock size={10} />{countdown}</span>}
            </div>
          </div>
          <button onClick={() => load()} title="새로고침" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-slate-300">
            <RefreshCw size={13} className={loading || refreshing ? "animate-spin" : ""} />
          </button>
        </div>

        {/* 마켓 탭 */}
        <div className="grid grid-cols-3 gap-1.5">
          {(["auto", "kr", "us"] as MarketChoice[]).map((choice) => (
            <button
              key={choice}
              onClick={() => updateMarketChoice(choice)}
              className={`rounded-lg px-2 py-1.5 text-xs font-semibold ${marketChoice === choice ? "bg-blue-600 text-white" : "border border-slate-700 bg-slate-900 text-slate-400"}`}
            >
              {choice === "auto" ? "자동" : choice === "kr" ? "국장" : "미장"}
            </button>
          ))}
        </div>

        {(refreshWarning || bootStatus === "degraded") && (
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            {refreshWarning || "일부 초기 데이터를 불러오지 못해 사용 가능한 캐시와 기본 화면을 먼저 표시합니다."}
          </div>
        )}

        {/* 알림 배너 */}
        <AlertBanner alert={calendarAlert} />

        {/* AI 브리핑 */}
        <GuideCard briefing={dailyBriefing} onAnalyze={openAnalysis} />

        {/* 시장 컨디션 게이트 + 투자심리 */}
        <MarketGateCard regime={marketRegime} dataHealth={dataHealth} selectedMarket={selectedMarket} />

        {/* 오늘의 후보 */}
        <section>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">오늘의 후보</h2>
            <span className="text-[11px] text-slate-500">{activeCandidates.length}개</span>
          </div>
          <div className="mb-2.5 grid grid-cols-3 gap-1.5">
            {([
              { key: "entry", label: "오늘 진입", count: todayEntries.length },
              { key: "watch", label: "대기 관찰", count: watchItems.length },
              { key: "risk", label: "위험 보류", count: riskHeldItems.length },
            ] as { key: DecisionTab; label: string; count: number }[]).map((tab) => (
              <button
                key={tab.key}
                onClick={() => setDecisionTab(tab.key)}
                className={`rounded-lg px-2 py-1.5 text-[11px] font-semibold ${decisionTab === tab.key ? "bg-slate-100 text-slate-900" : "border border-slate-700 bg-slate-900 text-slate-400"}`}
              >
                {tab.label} {tab.count > 0 && <span className="opacity-70">{tab.count}</span>}
              </button>
            ))}
          </div>
          {activeCandidates.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-700 px-3 py-6 text-center text-xs text-slate-500">
              현재 조건에 해당하는 후보가 없습니다.
            </div>
          ) : (
            <div className="-mx-3 flex gap-3 overflow-x-auto px-3 pb-1 snap-x snap-mandatory">
              {decisionTab === "entry" && todayEntries.map((item, i) => (
                <EntryCandidateCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} rank={i + 1} onAnalyze={openAnalysis} onTradePaper={onTradePaper ? () => onTradePaper({ symbol: item.symbol, name: displayName(item), price: Number(item.entry || item.currentPrice || 0), market: normalizeMarket(item.market || selectedMarket, item.symbol) }) : undefined} />
              ))}
              {decisionTab === "watch" && watchItems.map((item) => (
                <WatchCandidateCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} onAnalyze={openAnalysis} />
              ))}
              {decisionTab === "risk" && riskHeldItems.map((item) => (
                <RiskCandidateCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} onAnalyze={openAnalysis} />
              ))}
            </div>
          )}
        </section>

        {/* 포지션 사이징 미리보기 */}
        <section className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-4">
          <div className="mb-2.5 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-100">포지션 사이징 미리보기</h2>
            <input
              type="text"
              inputMode="numeric"
              placeholder="총 자본"
              value={capitalInput ? Number(capitalInput).toLocaleString() : ""}
              onChange={(e) => handleCapitalChange(e.target.value.replace(/,/g, ""))}
              className="w-28 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-right font-mono text-xs text-slate-100 placeholder-slate-600 focus:border-violet-500 focus:outline-none"
            />
          </div>
          {capital <= 0 ? (
            <div className="py-4 text-center text-xs text-slate-500">총 자본을 입력하면 종목별 권장 금액을 계산합니다.</div>
          ) : sizingRows.length === 0 ? (
            <div className="py-4 text-center text-xs text-slate-500">오늘 진입 후보가 없습니다.</div>
          ) : (
            <div className="space-y-1.5">
              {sizingRows.slice(0, 3).map((r) => (
                <div key={`${r.symbol}-${r.mode}-${r.horizon}`} className="flex items-center justify-between rounded-lg bg-slate-950/50 px-2.5 py-2 text-[11px]">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-slate-200">{r.name}</div>
                    <div className="text-slate-500">{modeLabel(r.mode as Mode)} · ½Kelly {(r.halfKelly * 100).toFixed(1)}%</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="font-mono text-slate-100">{r.amount.toLocaleString()}원</div>
                    <div className="text-slate-500">{r.qty > 0 ? `${r.qty}주` : "—"}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 보유종목 */}
        {holdings.length > 0 && (
          <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="mb-2.5 flex items-center gap-2">
              {riskCount > 0 && <AlertTriangle size={14} className="text-red-400" />}
              <h2 className="text-sm font-semibold text-slate-100">보유종목</h2>
              {summary?.totalPnl != null && (
                <span className={`font-mono text-xs font-bold ${Number(summary.totalPnl) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {summary.totalPnlText ?? (Number(summary.totalPnl) >= 0 ? "+" : "") + Number(summary.totalPnl).toLocaleString("ko-KR") + "원"}
                </span>
              )}
              <span className="ml-auto text-[11px] text-slate-500">{holdings.length}개{riskCount > 0 && ` · 위험/주의 ${riskCount}개`}</span>
            </div>
            <div className="space-y-2">
              {holdings.slice(0, 6).map((item) => {
                const rawChange = firstText(item.changePctText, "");
                const change = rawChange && rawChange !== "-" ? rawChange : "";
                const down = String(change).startsWith("-");
                const currentText = firstText(item.currentPriceText, item.priceText, item.currentText, "");
                const isRisk = ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""));
                const judgment = getHoldingJudgment(item);
                return (
                  <div key={`${item.market}-${item.symbol}`} className={`rounded-xl border p-2.5 ${isRisk ? "border-red-800/40 bg-red-950/10" : "border-slate-800 bg-slate-950/50"}`}>
                    <div className="flex items-center justify-between">
                      <div className="min-w-0">
                        <div className="text-[13px] font-medium text-slate-200">{displayName(item)}</div>
                        <div className="text-[10px] text-slate-500">{item.symbol} · {item.market === "kr" ? "국장" : "미장"}{currentText ? ` · ${currentText}` : ""}</div>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className={`font-mono text-xs ${String(item.pnlText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"}`}>{firstText(item.pnlText, "손익 대기")}</div>
                        {change && <div className={`font-mono text-[10px] ${down ? "text-red-400" : "text-emerald-400"}`}>{change}</div>}
                      </div>
                    </div>
                    <span className={`mt-1.5 inline-block rounded-full border px-2 py-0.5 text-[9px] font-semibold ${judgment.cls}`}>{judgment.text}</span>
                  </div>
                );
              })}
            </div>
            {holdings.length > 6 && onNavigate && (
              <button onClick={() => onNavigate("holdings")} className="mt-3 w-full rounded-xl border border-slate-700 py-2 text-xs text-slate-400">
                나머지 {holdings.length - 6}개 보유종목 →
              </button>
            )}
          </section>
        )}

        {/* 전략·기록 아코디언 */}
        <section className="rounded-2xl border border-slate-800 bg-slate-900/40">
          <button onClick={() => setMoreOpen((v) => !v)} className="flex w-full items-center justify-between px-4 py-3">
            <span className="text-sm font-semibold text-slate-200">⚙️ 전략·기록</span>
            <ChevronDown size={16} className={`text-slate-500 transition-transform ${moreOpen ? "rotate-180" : ""}`} />
          </button>
          {moreOpen && (
            <div className="space-y-4 px-4 pb-4">
              <div>
                <div className="mb-2 text-xs font-semibold text-slate-400">3×3 전략 매트릭스</div>
                <div className="grid grid-cols-3 gap-1.5">
                  {matrix.map((cell) => (
                    <StrategyTile key={`${cell.mode}-${cell.horizon}`} cell={cell} />
                  ))}
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-400">
                  <Bell size={12} className="text-sky-300" /> 알림 추적
                </div>
                {alertTrackingRows.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-700 px-3 py-4 text-center text-[11px] text-slate-500">
                    기록된 알림이 쌓이면 추적 결과가 표시됩니다.
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {alertTrackingRows.map((row) => (
                      <div key={row.key} className="rounded-lg bg-slate-950/50 px-2.5 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-[11px] font-semibold text-slate-200">{row.name} <span className="font-mono text-[9px] text-slate-500">{row.symbol}</span></span>
                          <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${row.changeTone === "up" ? "text-emerald-300" : row.changeTone === "down" ? "text-red-300" : "text-slate-400"}`}>{row.status}</span>
                        </div>
                        <div className="mt-0.5 text-[10px] text-slate-500">{row.recordedAt} · {row.alertPriceText} → {row.currentPriceText} ({row.changeText})</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-400">
                  <Bot size={12} className="text-emerald-300" /> AI 엔진 변경 이력
                </div>
                <div className="space-y-1.5">
                  {engineHistoryRows.map((row) => (
                    <div key={row.key} className="flex items-start gap-2 rounded-lg bg-slate-950/50 px-2.5 py-2">
                      <div className="w-10 shrink-0 pt-0.5 font-mono text-[9px] text-slate-500">{row.date}</div>
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] font-semibold text-slate-200">{row.title}</div>
                        <div className="text-[10px] text-slate-500">{row.detail}</div>
                      </div>
                      <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${row.tone === "emerald" ? "text-emerald-300 border-emerald-500/25" : row.tone === "amber" ? "text-amber-300 border-amber-500/25" : "text-slate-400 border-slate-600/40"}`}>{row.status}</span>
                    </div>
                  ))}
                </div>
              </div>

              {onNavigate && (
                <button onClick={() => onNavigate("stocks")} className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 py-2 text-xs text-slate-300">
                  종목 탐색에서 더 보기 <ArrowRight size={12} />
                </button>
              )}
            </div>
          )}
        </section>

        {/* 데이터 기준 안내 */}
        <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2 text-[10px] text-slate-500">
          <History size={12} className="shrink-0" />
          <span className={`rounded-full border px-1.5 py-0.5 ${dataFreshnessBadgeClass(freshness.state)}`}>{freshness.label}</span>
          <span className="truncate">{freshness.basisText}</span>
        </div>
      </div>
    </ErrorBoundary>
  );
}
