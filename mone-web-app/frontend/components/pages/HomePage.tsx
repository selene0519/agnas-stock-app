"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, TrendingUp, Clock, Eye, AlertTriangle, X, Info, Calculator, ArrowRight } from "lucide-react";
import type { PageId } from "../Sidebar";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { CardSkeleton } from "@/components/ui/Skeleton";
import { SentimentBadge } from "@/components/SentimentBadge";
import FearGreedWidget from "@/components/FearGreedWidget";
import {
  getDefaultMarketBySession, getMarketSessionStatus, getSessionCountdown,
  kstNowParts, type SessionPhase,
} from "@/lib/marketSession";
import {
  dedupeBySymbol,
  dataFreshnessBadgeClass,
  dataFreshnessInfo,
  dataTrustBadgeClass,
  dataTrustLabel,
  dataTrustNotice,
  displayName,
  firstText,
  horizonLabel,
  moneReasonLines,
  modeLabel,
  normalizeMarket,
  priceText,
  probabilityText,
  strategyTagLabel,
} from "@/lib/moneDisplay";
import { RecommendationBadges } from "@/components/RecommendationBadges";
import { dataSourceLabel } from "@/lib/dataSourceLabel";
import type { BootPreloadData, BootStatus } from "@/lib/bootPreload";

const MODES: Mode[] = ["conservative", "balanced", "aggressive"];
const HORIZONS: Horizon[] = ["short", "swing", "mid"];

type StrategyCell = { mode: Mode; horizon: Horizon; items: any[]; count: number; status: string };
type MarketChoice = "auto" | "kr" | "us";

function bootMarketHomeSummary(bootData: BootPreloadData | null | undefined, market: "kr" | "us"): any | null {
  if (!bootData) return null;
  return market === "kr" ? (bootData.krHomeSummary ?? null) : (bootData.usHomeSummary ?? null);
}

// Module-level re-entry cache: preserves data when user navigates away and back
const HOME_PAGE_CACHE_TTL = 5 * 60 * 1000; // 5 min
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

function readHomeCache(market: "kr" | "us"): HomeCacheEntry | null {
  const c = _homeCache[market];
  return c && Date.now() - c.ts < HOME_PAGE_CACHE_TTL ? c : null;
}
function writeHomeCache(market: "kr" | "us", e: Omit<HomeCacheEntry, "ts">) {
  _homeCache[market] = { ...e, ts: Date.now() };
}

function normalizeDateText(value: any) {
  const raw = String(value || "").trim();
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  return raw;
}

function normalizeMarketRegime(raw: any, market: "kr" | "us") {
  if (!raw || typeof raw !== "object") return null;
  const benchmark = String(raw.benchmark || (market === "kr" ? "KOSPI" : "NASDAQ"));
  const normalized = {
    ...raw,
    benchmark,
    current: raw.current ?? raw.kospiLatest ?? null,
    ma20: raw.ma20 ?? raw.kospiMa20 ?? null,
    ma60: raw.ma60 ?? raw.kospiMa60 ?? null,
    distanceMa20Pct: raw.distanceMa20Pct ?? raw.distanceToMa20Pct ?? null,
  };
  return normalized;
}

function normalizeDataHealth(raw: any) {
  if (!raw || typeof raw !== "object") return null;
  return {
    ...raw,
    ohlcvLatestDate: normalizeDateText(raw.ohlcvLatestDate),
  };
}

function shortDate(value: any) {
  const normalized = normalizeDateText(value);
  return normalized ? String(normalized).slice(0, 10) : "";
}

function operationBasisWarning(operationSummary: any) {
  if (!operationSummary || typeof operationSummary !== "object") return null;
  const status = String(operationSummary.basisAlignmentStatus || "").toUpperCase();
  const dates = operationSummary.basisDates || {};
  const recommendation = shortDate(operationSummary.recommendationDate || dates.recommendation);
  const current = shortDate(operationSummary.currentPriceBasisDate || dates.currentPrice);
  const ohlcv = shortDate(operationSummary.ohlcvLatestDate || dates.ohlcv);
  const knownDates = [recommendation, current, ohlcv].filter(Boolean);
  const mixed = status.includes("MIXED") || new Set(knownDates).size > 1;
  if (!mixed) return null;
  return { recommendation, current, ohlcv };
}

function getSessionContext(session: SessionPhase) {
  switch (session) {
    case "장전":    return { focus: "today",    hint: "장 시작 전 — 오늘 진입 후보를 미리 확인하고 알림을 등록하세요." };
    case "장중":    return { focus: "intraday", hint: "장중 — 기준가에 근접한 종목을 우선 확인하세요." };
    case "장마감":  return { focus: "review",   hint: "오늘 결과를 반영해 내일 볼 후보를 정리했습니다." };
    case "개장 전": return { focus: "today",    hint: "미장 개장 전 — 오늘 미장 진입 후보와 포지션을 점검하세요." };
    case "마감 후": return { focus: "review",   hint: "미장 마감 후 — 결과 검토 및 다음 날 전략을 준비하세요." };
    case "휴장":    return { focus: "rest",     hint: "오늘은 휴장입니다. 다음 거래일 전략을 미리 준비하세요." };
    default:        return { focus: "today",    hint: "오늘 진입 후보와 대기 관찰 종목을 확인하세요." };
  }
}

function getRegimeStance(regime: string, market: "kr" | "us"): string {
  if (regime === "BULL") return market === "kr" ? "균형·공격형 전략 유효" : "성장주 모멘텀 전략 유효";
  if (regime === "BEAR") return market === "kr" ? "보수형 전략 우선 · 포지션 축소" : "방어주·현금 비중 확대";
  return "중립 — 선별적 진입";
}

// ── 점수 바
function ScoreBar({ label, value, color = "bg-emerald-500" }: { label: string; value: number | null | undefined; color?: string }) {
  if (value == null) return null;
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div>
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>{label}</span>
        <span className="font-mono text-slate-400">{pct.toFixed(0)}</span>
      </div>
      <div className="mt-0.5 h-1 w-full rounded-full bg-slate-800">
        <div className={`h-1 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── 전략 태그 렌더
function TagChips({ item }: { item: any }) {
  const surgeLabel = String(item.surgeLabel || "");
  const tags = surgeLabel !== "판단 대기" && surgeLabel
    ? surgeLabel.split("|").map((t) => t.trim()).filter(Boolean)
    : [];

  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {item.evNegative && <span className="rounded-full border border-red-500/50 bg-red-500/15 px-2 py-1 text-xs font-semibold text-red-300">EV음수</span>}
      {item.maConvergence && <span className="rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-xs text-violet-300">이격도수렴</span>}
      {item.isUndervaluedGrowth === "True" && <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">저평가성장주</span>}
      {item.supplySignal === "STRONG_BUY" && <span className="rounded-full border border-blue-400/40 bg-blue-400/10 px-2 py-1 text-xs text-blue-300">기관+외국인</span>}
      {item.supplySignal === "INST_BUY" && <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-xs text-sky-300">기관매수</span>}
      {tags.filter((t) => !["저평가성장주", "공시주의"].includes(t)).slice(0, 2).map((t) => (
        <span key={t} className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-1 text-xs text-cyan-200">{strategyTagLabel(t)}</span>
      ))}
      {Number(item.newsRiskPenalty) >= 10 && <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2 py-1 text-xs text-orange-300">공시주의</span>}
      {item.financialDataStatus === "DATA_PENDING" && <span className="rounded-full border border-slate-600 bg-slate-800 px-2 py-1 text-xs text-slate-400">재무미확보</span>}
      {item.finReason && item.financialDataStatus !== "DATA_PENDING" && item.finValueScore > 0 && <span className="rounded-full border border-teal-500/30 bg-teal-500/10 px-2 py-1 text-xs text-teal-300">재무확인</span>}
    </div>
  );
}

// ── 실적발표 D-day 뱃지
function EarningsBadge({ dday }: { dday: number }) {
  const color = dday <= 2
    ? "border-red-500/50 bg-red-500/15 text-red-300"
    : dday <= 5
      ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
      : "border-slate-600 bg-slate-800 text-slate-400";
  return (
    <span className={`rounded-full border px-2 py-1 text-xs font-bold ${color}`}>
      실적 D-{dday}
    </span>
  );
}

// ── 매크로/실적 이벤트 배너 ──────────────────────────────────────────────
function EventBanner({ alert }: { alert: any }) {
  const [dismissed, setDismissed] = useState(false);
  if (!alert || dismissed) return null;

  const highMacro: any[] = alert.todayHighMacro || [];
  const allMacro: any[] = alert.todayAllMacro || [];
  const todayEarnings: any[] = alert.todayEarnings || [];
  const tmrwHigh: any[] = alert.tomorrowHighMacro || [];
  const tmrwEarnings: any[] = alert.tomorrowEarnings || [];

  const hasHigh   = highMacro.length > 0;
  const hasMed    = allMacro.length > 0 || todayEarnings.length > 0;
  const hasTomorrow = tmrwHigh.length > 0 || tmrwEarnings.length > 0;

  if (!hasHigh && !hasMed && !hasTomorrow) return null;

  const bgClass = hasHigh
    ? "border-red-500/40 bg-red-500/10"
    : hasMed
    ? "border-amber-500/40 bg-amber-500/10"
    : "border-slate-600/60 bg-slate-800/60";
  const textClass = hasHigh ? "text-red-300" : hasMed ? "text-amber-300" : "text-slate-400";
  const iconClass = hasHigh ? "text-red-400" : hasMed ? "text-amber-400" : "text-slate-500";

  return (
    <div className={`relative flex items-start gap-3 rounded-xl border px-3.5 py-2.5 text-sm ${bgClass}`}>
      <AlertTriangle size={15} className={`mt-0.5 shrink-0 ${iconClass}`} />
      <div className="min-w-0 flex-1">
        {/* 오늘 HIGH 매크로 */}
        {highMacro.length > 0 && (
          <div className="font-semibold text-red-200">
            🔴 오늘 주요 지표:
            {highMacro.slice(0, 3).map((e: any, i: number) => (
              <span key={i} className="ml-1 rounded-full border border-red-500/30 bg-red-500/15 px-1.5 py-0.5 text-[11px]">
                {e.event}
                {e.forecast ? ` (예상 ${e.forecast})` : ""}
              </span>
            ))}
          </div>
        )}
        {/* 오늘 MEDIUM 매크로 (HIGH가 없을 때) */}
        {!hasHigh && allMacro.length > 0 && (
          <div className={`font-medium ${textClass}`}>
            ⚠️ 오늘 경제지표:
            {allMacro.slice(0, 3).map((e: any, i: number) => (
              <span key={i} className="ml-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[11px] text-amber-200">
                {e.event}
              </span>
            ))}
          </div>
        )}
        {/* 오늘 실적발표 */}
        {todayEarnings.length > 0 && (
          <div className={`mt-0.5 text-xs ${textClass}`}>
            📊 오늘 실적:
            {todayEarnings.slice(0, 5).map((e: any, i: number) => (
              <span key={i} className="ml-1 font-semibold">{e.symbol || e.name}</span>
            ))}
          </div>
        )}
        {/* 내일 예고 */}
        {!hasHigh && !hasMed && (tmrwHigh.length > 0 || tmrwEarnings.length > 0) && (
          <div className="text-xs text-slate-400">
            📅 내일 예정:
            {[...tmrwHigh.slice(0, 2), ...tmrwEarnings.slice(0, 2)].map((e: any, i: number) => (
              <span key={i} className="ml-1">{e.event || e.symbol || e.name}</span>
            ))}
          </div>
        )}
        <div className="mt-1 text-[10px] text-slate-500">
          오늘 진입 시 리스크 관리 강화 권고 · 변동성 확대 구간
        </div>
      </div>
      <button
        onClick={() => setDismissed(true)}
        className="absolute top-1.5 right-1.5 rounded-lg p-2 text-slate-500 hover:bg-slate-700/50 hover:text-slate-300"
        aria-label="닫기"
      >
        <X size={14} />
      </button>
    </div>
  );
}

// ── 오늘 검토 후보 카드 (홈 압축형)
function TodayEntryCard({ item, rank, onAnalyze, earningsMap }: { item: any; rank: number; onAnalyze: (item: any) => void; earningsMap?: Record<string, number> }) {
  const score = Number(item.finalScore || 0);
  const mode = String(item.mode || item._mode || "");
  const horizon = String(item.horizon || item._horizon || "");
  const decision = firstText(
    item.patternStrategy?.action,
    item.moneDecision,
    item.newEntryDecision,
    item.decision,
    item.decisionBucket,
    "분석 필요",
  );
  const riskRaw = String(item.riskStatus || item.tradeBlockStatus || item.riskLevel || "").toUpperCase();
  const riskText = !riskRaw || ["NONE", "OK", "NORMAL", "LOW"].includes(riskRaw) ? "위험 낮음" : riskRaw.includes("WATCH") || riskRaw.includes("주의") ? "주의" : "위험 확인";
  const riskClass = riskText === "위험 낮음" ? "text-emerald-300" : riskText === "주의" ? "text-amber-300" : "text-red-300";
  const confidence = probabilityText(item, score > 0 ? `${score.toFixed(0)}점` : "-");
  const reasons = moneReasonLines(item).slice(0, 3);

  // 앙상블/실증 뱃지 — 샘플 수 5개 이상일 때만 표시
  const calibCount = Number(item.calibrationCount ?? 0);
  const showCalibBadges = calibCount >= 5;
  const ensembleScore = item.ensembleScore != null ? Number(item.ensembleScore) : null;
  const calibratedWinRate = item.calibratedWinRate != null ? Number(item.calibratedWinRate) : null;

  return (
    <div className="relative rounded-2xl border border-emerald-800/50 bg-gradient-to-br from-emerald-950/25 to-slate-950 p-4">
      <div className="absolute -top-2 -left-2 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-[11px] font-bold text-white">{rank}</div>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate font-semibold text-slate-100">{displayName(item)}</span>
            {earningsMap && earningsMap[item.symbol] != null && (
              <EarningsBadge dday={earningsMap[item.symbol]} />
            )}
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${dataTrustBadgeClass(item)}`}>
              {dataTrustLabel(item)}
            </span>
            <SentimentBadge
              symbol={item.symbol}
              market={(String(item.market || item._market || "kr")).toLowerCase() === "us" ? "us" : "kr"}
              name={String(item.name || "")}
            />
            {showCalibBadges && calibratedWinRate != null && (
              <span className="rounded-full border border-slate-600 bg-slate-700/60 px-2 py-0.5 text-[10px] font-medium text-slate-300 [font-variant-numeric:tabular-nums]">
                실증 {calibratedWinRate.toFixed(0)}%
              </span>
            )}
            {showCalibBadges && ensembleScore != null && (
              <span className="rounded-full border border-slate-600 bg-slate-700/60 px-2 py-0.5 text-[10px] font-medium text-slate-300 [font-variant-numeric:tabular-nums]">
                앙상블 {ensembleScore.toFixed(0)}
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-500">{item.symbol} · {modeLabel(mode as Mode)} · {horizonLabel(horizon as Horizon)}</div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] text-slate-500">MONE 판단</div>
          <div className="text-sm font-bold text-emerald-300">{decision}</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-1.5 text-[11px] sm:grid-cols-5 sm:gap-2">
        <div className="min-w-0"><div className="text-slate-500">현재가</div><div className="break-keep font-mono text-slate-200">{priceText(item, "current", "-")}</div></div>
        <div className="min-w-0"><div className="text-slate-500">기준가</div><div className="break-keep font-mono text-sky-300">{priceText(item, "entry", "-")}</div></div>
        <div className="min-w-0"><div className="text-slate-500">목표가</div><div className="break-keep font-mono text-emerald-300">{priceText(item, "target", "-")}</div></div>
        <div className="min-w-0"><div className="text-slate-500">신뢰도</div><div className="break-keep font-mono text-blue-300">{confidence}</div></div>
        <div className="min-w-0"><div className="text-slate-500">위험 상태</div><div className={`font-semibold ${riskClass}`}>{riskText}</div></div>
      </div>

      <div className="mt-3 rounded-xl border border-slate-800/70 bg-slate-950/50 px-3 py-2">
        <div className="text-[11px] font-semibold text-slate-300">MONE 판단 이유</div>
        <ol className="mt-1 space-y-0.5 text-[11px] leading-5 text-slate-400">
          {reasons.map((reason, index) => <li key={reason}>{index + 1}. {reason}</li>)}
        </ol>
      </div>

      {dataTrustNotice(item) && (
        <div className="mt-2 rounded-lg border border-amber-800/40 bg-amber-950/20 px-2.5 py-2 text-[10px] text-amber-300">
          {dataTrustNotice(item)}
        </div>
      )}

      <button
        type="button"
        onClick={() => onAnalyze(item)}
        className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-500"
      >
        분석 보기 <ArrowRight size={14} />
      </button>
    </div>
  );
}

// ── 대기 관찰 카드 (간결)
function WatchCard({ item, onSelect }: { item: any; onSelect: (item: any) => void }) {
  const mode = String(item.mode || item._mode || "");
  const horizon = String(item.horizon || item._horizon || "");
  const timingLabel = String(item.timingLabel || "대기");
  const timingReason = String(item.timingReason || "");
  const expectedEntry = String(item.expectedEntryPrice || "");

  const timingColor =
    timingLabel.includes("1~2일") ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
    : timingLabel.includes("3~5일") ? "border-orange-500/40 bg-orange-500/10 text-orange-300"
    : timingLabel.includes("다음 주") ? "border-slate-600 bg-slate-800/60 text-slate-400"
    : "border-cyan-500/30 bg-cyan-500/10 text-cyan-300";

  return (
    <div onClick={() => onSelect(item)} className="cursor-pointer rounded-xl border border-slate-700/60 bg-slate-900/50 p-3 transition-colors hover:border-amber-700/50 hover:bg-slate-900/80">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <span className="font-semibold text-slate-200">{displayName(item)}</span>
          <span className="ml-2 text-[10px] text-slate-500">{item.symbol} · {modeLabel(mode as Mode)} · {horizonLabel(horizon as Horizon)}</span>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${timingColor}`}>{timingLabel}</span>
      </div>
      {timingReason && <div className="mt-1 text-[11px] text-slate-400">{timingReason}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px]">
        <span className="text-slate-500">현재 <span className="font-mono text-slate-300">{priceText(item, "current", "-")}</span></span>
        {expectedEntry && <span className="text-slate-500">예상 진입 <span className="font-mono text-sky-400">{expectedEntry}</span></span>}
        <span className="text-slate-500">목표 <span className="font-mono text-emerald-400">{priceText(item, "target", "-")}</span></span>
        <span className={`font-mono ${Number(item.expectedValue || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          EV {Number(item.expectedValue || 0) >= 0 ? "+" : ""}{Number(item.expectedValue || 0).toFixed(1)}%
        </span>
        <SentimentBadge
          symbol={item.symbol}
          market={(String(item.market || item._market || "kr")).toLowerCase() === "us" ? "us" : "kr"}
          name={String(item.name || "")}
        />
      </div>
      <TagChips item={item} />
    </div>
  );
}

// ── 포지션 사이징 ──────────────────────────────────────────────────────────────

const MODE_CAPS: Record<string, number> = {
  conservative: 0.05,   // 최대 5%
  balanced:     0.10,   // 최대 10%
  aggressive:   0.15,   // 최대 15%
};

interface SizingRow {
  symbol:   string;
  name:     string;
  mode:     string;
  horizon:  string;
  entry:    number;
  prob:     number;      // 0~1
  rr:       number;
  kelly:    number;      // full kelly fraction
  halfKelly: number;     // capped half kelly
  amount:   number;      // 원화 금액
  qty:      number;
  ev:       number;
}

function calcSizing(items: any[], capital: number): SizingRow[] {
  const seen = new Set<string>();
  return items
    .filter((i) => i.decisionBucket === "오늘 진입")
    .flatMap((i) => {
      const key = `${i.symbol}-${i._mode}-${i._horizon}`;
      if (seen.has(key)) return [];
      seen.add(key);

      const entry = Number(i.entry || i.entryPrice || 0);
      const prob  = Math.min(Math.max(Number(i.probability || 55) / 100, 0.3), 0.8);
      const rr    = Math.max(Number(i.rrActual || i.rr || 1.5), 0.5);
      const mode  = String(i._mode || i.mode || "balanced");
      if (entry <= 0 || capital <= 0) return [];

      const kelly    = Math.max(0, prob - (1 - prob) / rr);
      const cap      = MODE_CAPS[mode] ?? 0.10;
      const halfKelly = Math.min(kelly / 2, cap);
      const amount   = Math.floor(capital * halfKelly);
      const qty      = Math.floor(amount / entry);

      return [{
        symbol: String(i.symbol || ""),
        name:   String(i.name || i.companyName || i.symbol || ""),
        mode,
        horizon: String(i._horizon || i.horizon || ""),
        entry,
        prob,
        rr,
        kelly,
        halfKelly,
        amount: qty * entry,
        qty,
        ev: Number(i.expectedValue || 0),
      }];
    })
    .sort((a, b) => b.halfKelly - a.halfKelly);
}

function PositionSizingSection({
  items,
  capital,
  setCapital,
}: {
  items: any[];
  capital: number;
  setCapital: (v: number) => void;
}) {
  const [inputVal, setInputVal] = useState(capital > 0 ? String(capital) : "");

  function handleCapitalChange(raw: string) {
    const clean = raw.replace(/[^0-9]/g, "");
    setInputVal(clean);
    const n = Number(clean);
    if (n >= 100_000) {
      setCapital(n);
      if (typeof window !== "undefined") window.localStorage.setItem("mone:capital", String(n));
    }
  }

  const rows = useMemo(() => calcSizing(items, capital), [items, capital]);
  const totalAllocated = rows.reduce((s, r) => s + r.amount, 0);
  const allocPct = capital > 0 ? (totalAllocated / capital) * 100 : 0;
  const remaining = capital - totalAllocated;

  if (rows.length === 0 && capital <= 0) return null;

  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Calculator size={18} className="text-violet-400 shrink-0" />
        <div className="flex-1">
          <h2 className="text-base font-semibold text-slate-100">포지션 사이징</h2>
          <p className="text-xs text-slate-500">Half-Kelly 공식으로 종목별 적정 투자금을 계산합니다.</p>
        </div>
        {/* 자본 입력 */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">총 자본</span>
          <input
            type="text"
            inputMode="numeric"
            placeholder="예: 10000000"
            value={inputVal ? Number(inputVal).toLocaleString() : ""}
            onChange={(e) => handleCapitalChange(e.target.value.replace(/,/g, ""))}
            className="w-36 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-right font-mono text-sm text-slate-100 placeholder-slate-600 focus:border-violet-500 focus:outline-none"
          />
          <span className="text-xs text-slate-500">원</span>
        </div>
      </div>

      {capital <= 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">총 자본을 입력하면 종목별 권장 수량과 금액을 계산합니다.</div>
      ) : rows.length === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">오늘 진입 후보가 없습니다.</div>
      ) : (
        <>
          {/* 포트폴리오 요약 바 */}
          <div className="mb-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
            <div className="mb-2 flex justify-between text-[11px] text-slate-400">
              <span>총 배분: <span className="font-mono text-slate-200">{totalAllocated.toLocaleString()}원</span> ({allocPct.toFixed(1)}%)</span>
              <span>잔여 현금: <span className={`font-mono ${remaining >= 0 ? "text-emerald-300" : "text-red-300"}`}>{remaining.toLocaleString()}원</span></span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className={`h-2 rounded-full transition-all ${allocPct > 90 ? "bg-red-500" : allocPct > 60 ? "bg-amber-500" : "bg-violet-500"}`}
                style={{ width: `${Math.min(100, allocPct)}%` }}
              />
            </div>
            <div className="mt-1.5 flex gap-3 text-[10px] text-slate-500">
              <span>{rows.length}개 종목</span>
              <span>포트폴리오 노출 {allocPct.toFixed(1)}%</span>
              {allocPct > 80 && <span className="text-amber-400">⚠ 집중도 높음 — 분산 권장</span>}
            </div>
          </div>

          {/* 종목별 테이블 */}
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500">
                  <th className="pb-2 text-left font-medium">종목</th>
                  <th className="pb-2 text-left font-medium">전략</th>
                  <th className="pb-2 text-right font-medium">승률</th>
                  <th className="pb-2 text-right font-medium">RR</th>
                  <th className="pb-2 text-right font-medium">½Kelly</th>
                  <th className="pb-2 text-right font-medium">금액</th>
                  <th className="pb-2 text-right font-medium">수량</th>
                  <th className="pb-2 text-right font-medium">EV</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.symbol}-${r.mode}-${r.horizon}`} className="border-b border-slate-900 hover:bg-slate-900/40">
                    <td className="py-2 pr-3">
                      <div className="font-medium text-slate-200">{r.name}</div>
                      <div className="text-slate-500">{r.symbol}</div>
                    </td>
                    <td className="py-2 pr-3 text-slate-400">
                      {modeLabel(r.mode as Mode)}<span className="text-slate-600"> · </span>{horizonLabel(r.horizon as Horizon)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-300">{(r.prob * 100).toFixed(0)}%</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-300">{r.rr.toFixed(1)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-violet-300">{(r.halfKelly * 100).toFixed(1)}%</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-100">{r.amount.toLocaleString()}</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-100">{r.qty > 0 ? `${r.qty}주` : "—"}</td>
                    <td className={`py-2 text-right font-mono ${r.ev >= 2 ? "text-emerald-300" : r.ev >= 0 ? "text-slate-400" : "text-red-400"}`}>
                      {r.ev >= 0 ? "+" : ""}{r.ev.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-[10px] text-slate-600">
            Half-Kelly = min(max(0, p − (1−p)/RR) ÷ 2, 전략한도)  ·  보수형 최대 5% / 균형형 10% / 공격형 15%  ·  참고용이며 자동주문은 지원하지 않습니다.
          </p>
        </>
      )}
    </section>
  );
}

// ── 운용 일지 모달 ─────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = { BUY: "매수", SELL: "매도", NOTE: "메모" };
const RESULT_LABELS: Record<string, string> = { WIN: "수익", LOSS: "손실", BREAK_EVEN: "본전", "": "미입력" };

function JournalModal({ onClose }: { onClose: () => void }) {
  const [entries, setEntries]   = useState<any[]>([]);
  const [loading, setLoading]   = useState(true);
  const [form, setForm]         = useState({ symbol: "", name: "", action: "BUY", price: "", qty: "", memo: "", review: "", result: "", returnPct: "" });
  const [saving, setSaving]     = useState(false);
  const [editId, setEditId]     = useState<string | null>(null);
  const [reviewText, setReviewText] = useState("");

  useEffect(() => {
    mone.journalGet({ market: "all" })
      .then((r) => setEntries(Array.isArray(r.items) ? r.items : []))
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, []);

  async function addEntry() {
    if (!form.memo.trim()) return;
    setSaving(true);
    try {
      const r = await mone.journalAdd({
        symbol: form.symbol, name: form.name, action: form.action,
        price: Number(form.price) || undefined, qty: Number(form.qty) || undefined,
        memo: form.memo, result: form.result,
        returnPct: Number(form.returnPct) || undefined,
      });
      if (r.entry) setEntries((prev) => [r.entry, ...prev]);
      setForm({ symbol: "", name: "", action: "BUY", price: "", qty: "", memo: "", review: "", result: "", returnPct: "" });
    } finally {
      setSaving(false);
    }
  }

  async function saveReview(id: string) {
    await mone.journalUpdate(id, { review: reviewText, result: entries.find((e) => e.id === id)?.result });
    setEntries((prev) => prev.map((e) => e.id === id ? { ...e, review: reviewText } : e));
    setEditId(null);
  }

  async function deleteEntry(id: string) {
    await mone.journalDelete(id);
    setEntries((prev) => prev.filter((e) => e.id !== id));
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col bg-slate-950 shadow-2xl ring-1 ring-slate-800">
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-5 py-4 backdrop-blur">
          <h2 className="font-bold text-slate-100">운용 일지</h2>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-800"><X size={18} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* 새 기록 입력 */}
          <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-4 space-y-3">
            <div className="text-xs font-semibold text-slate-400">새 기록 추가</div>
            <div className="grid grid-cols-3 gap-2">
              {(["BUY", "SELL", "NOTE"] as const).map((a) => (
                <button key={a} onClick={() => setForm((f) => ({ ...f, action: a }))}
                  className={`rounded-lg py-1.5 text-xs font-semibold ${form.action === a ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
                  {ACTION_LABELS[a]}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input placeholder="종목코드" value={form.symbol} onChange={(e) => setForm((f) => ({ ...f, symbol: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
              <input placeholder="종목명" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
              <input placeholder="가격" type="number" value={form.price} onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
              <input placeholder="수량" type="number" value={form.qty} onChange={(e) => setForm((f) => ({ ...f, qty: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
            </div>
            <textarea placeholder="진입 근거 (최대 100자)" maxLength={100} value={form.memo} onChange={(e) => setForm((f) => ({ ...f, memo: e.target.value }))}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 resize-none" rows={2} />
            <button onClick={addEntry} disabled={saving || !form.memo.trim()}
              className="w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white disabled:opacity-50 hover:bg-blue-700">
              {saving ? "저장 중..." : "기록 추가"}
            </button>
          </div>

          {/* 기록 목록 */}
          {loading ? (
            <div className="text-center text-sm text-slate-500">불러오는 중...</div>
          ) : entries.length === 0 ? (
            <div className="text-center text-sm text-slate-500">기록이 없습니다.</div>
          ) : (
            <div className="space-y-3">
              {entries.map((e) => (
                <div key={e.id} className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-[11px]">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${e.action === "BUY" ? "bg-emerald-800 text-emerald-200" : e.action === "SELL" ? "bg-red-800 text-red-200" : "bg-slate-700 text-slate-300"}`}>{ACTION_LABELS[e.action] ?? e.action}</span>
                      {" "}<span className="font-semibold text-slate-200">{e.name || e.symbol || "—"}</span>
                      {e.price > 0 && <span className="ml-1.5 font-mono text-slate-400">{e.price.toLocaleString()}원</span>}
                      {e.qty > 0 && <span className="ml-1 text-slate-500">{e.qty}주</span>}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-slate-500">{String(e.createdAt || "").slice(0, 10)}</span>
                      <button onClick={() => { setEditId(e.id); setReviewText(e.review || ""); }} className="text-slate-500 hover:text-slate-300">복기</button>
                      <button onClick={() => deleteEntry(e.id)} className="text-slate-600 hover:text-red-400">✕</button>
                    </div>
                  </div>
                  <p className="mt-1.5 text-slate-300">{e.memo}</p>
                  {e.result && <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] ${e.result === "WIN" ? "bg-emerald-900 text-emerald-300" : e.result === "LOSS" ? "bg-red-900 text-red-300" : "bg-slate-800 text-slate-400"}`}>{RESULT_LABELS[e.result] ?? e.result}</span>}
                  {e.returnPct !== 0 && e.returnPct != null && <span className={`ml-1.5 font-mono text-[10px] ${e.returnPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>{e.returnPct >= 0 ? "+" : ""}{e.returnPct.toFixed(1)}%</span>}
                  {e.review && <p className="mt-1.5 border-t border-slate-800 pt-1.5 text-slate-400">복기: {e.review}</p>}
                  {editId === e.id && (
                    <div className="mt-2 space-y-2">
                      <textarea placeholder="청산 후 복기 (뭘 놓쳤나?)" value={reviewText} onChange={(ev) => setReviewText(ev.target.value)}
                        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-100 placeholder-slate-600 focus:outline-none resize-none" rows={2} />
                      <div className="flex gap-2">
                        <button onClick={() => saveReview(e.id)} className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white">저장</button>
                        <button onClick={() => setEditId(null)} className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-400">취소</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── 추천 근거 패널 (슬라이드오버)
const SCORE_ITEMS = [
  { key: "upsideScore",    label: "상승 여력",   color: "bg-emerald-500" },
  { key: "riskScore",      label: "리스크 안정성", color: "bg-sky-500" },
  { key: "momentumScore",  label: "모멘텀",       color: "bg-yellow-500" },
  { key: "entryScore",     label: "진입 접근성",  color: "bg-cyan-500" },
  { key: "rrScore",        label: "손익비",       color: "bg-violet-500" },
  { key: "qualityScore",   label: "기업 안정성",  color: "bg-teal-500" },
];

const SUPPLY_LABEL: Record<string, string> = {
  STRONG_BUY:    "기관+외국인 동시 매수",
  INST_BUY:      "기관 매수 추정",
  SELL_PRESSURE: "매도 압력 감지",
  NEUTRAL:       "중립",
};

const RISK_FLAG_LABEL: Record<string, string> = {
  RSI_OVERHEATED:        "RSI 80+ 과열",
  BOLLINGER_UPPER_BREAK: "볼린저 상단 이탈",
  FIVE_DAY_UP_STREAK:    "5일 연속 상승 후 거래량 감소",
  GAP_UP_15PCT:          "갭상승 15%+ 추격금지",
  EV_NEGATIVE:           "기댓값 음수",
  NEWS_DISCLOSURE_RISK:  "공시/뉴스 리스크",
};

// ── 백테스트 뱃지
function BacktestBadge({ item, badgeMap }: { item: any; badgeMap: Record<string, any> }) {
  const horizon = String(item._horizon || item.horizon || "swing");
  const mode    = String(item._mode    || item.mode    || "balanced");
  const key = `${item.symbol}::${horizon}::${mode}`;
  const badge = badgeMap[key];
  if (!badge) return null;

  if (badge.pending) {
    return (
      <span className="rounded-full border border-slate-700 bg-slate-800/80 px-2 py-0.5 text-[10px] text-slate-500">
        검증 준비 중 ({badge.sample}회)
      </span>
    );
  }
  const wr  = Number(badge.winRate ?? 0);
  const avg = Number(badge.avgReturn ?? 0);
  const wrCls  = wr  >= 60 ? "text-emerald-300" : wr  >= 50 ? "text-amber-300" : "text-red-300";
  const avgCls = avg >= 2  ? "text-emerald-300" : avg >= 0  ? "text-slate-300"  : "text-red-300";

  return (
    <span className="flex items-center gap-1 rounded-full border border-slate-700/60 bg-slate-800/70 px-2 py-0.5 text-[10px]">
      <span className="text-slate-500">과거</span>
      <span className={`font-mono font-semibold ${wrCls}`}>{wr}%</span>
      <span className="text-slate-600">·</span>
      <span className={`font-mono ${avgCls}`}>{avg >= 0 ? "+" : ""}{avg}%</span>
      <span className="text-slate-600">·</span>
      <span className="text-slate-500">{badge.sample}회 (D+{badge.windowDays})</span>
    </span>
  );
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

// ── 시장 컨디션 게이트
function MarketGateCard({ regime, dataHealth }: { regime: any; dataHealth: any }) {
  const { strength, levelText, isHigh, isMid, isLow, maDist, dataAdj, hasOhlcv } = getMarketGateInfo(regime, dataHealth);

  const borderCls = isHigh ? "border-emerald-800/40 bg-emerald-950/15" : isMid ? "border-amber-800/40 bg-amber-950/15" : "border-red-800/40 bg-red-950/15";
  const textCls   = isHigh ? "text-emerald-300" : isMid ? "text-amber-300" : "text-red-300";
  const barCls    = isHigh ? "bg-emerald-500" : isMid ? "bg-amber-500" : "bg-red-500";

  return (
    <div className={`rounded-2xl border p-4 ${borderCls}`}>
      <div className="flex items-start justify-between gap-4 mb-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">시장 컨디션 게이트</div>
          <div className={`mt-1 text-lg font-bold ${textCls}`}>{levelText}</div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            {isHigh ? "시장 상태 양호 — 조건을 충족한 종목은 정상 진입 가능합니다."
             : isMid ? "선별 진입 구간 — EV·손익비 조건을 더 엄격하게 확인하세요."
             : "진입 자제 구간 — 신규 매수보다 보유 종목 관리에 집중하세요."}
          </div>
        </div>
        <div className={`shrink-0 text-right font-mono font-black ${textCls}`}>
          <span className="text-4xl">{strength}</span>
          <span className="text-base text-slate-500">/100</span>
        </div>
      </div>

      <div className="h-2 w-full rounded-full bg-slate-800 mb-3">
        <div className={`h-2 rounded-full transition-all duration-500 ${barCls}`} style={{ width: `${strength}%` }} />
      </div>

      <div className="grid grid-cols-3 gap-2 text-[11px]">
        <div className="rounded-lg bg-slate-900/60 px-2 py-2 text-center">
          <div className="text-slate-500">시장 추세</div>
          <div className={`mt-0.5 font-semibold ${regime?.regime === "BULL" ? "text-emerald-300" : regime?.regime === "BEAR" ? "text-red-300" : "text-slate-300"}`}>
            {regime?.regime === "BULL" ? "강세" : regime?.regime === "BEAR" ? "약세" : "중립"}
          </div>
        </div>
        <div className="rounded-lg bg-slate-900/60 px-2 py-2 text-center">
          <div className="text-slate-500">MA20 이격</div>
          <div className={`mt-0.5 font-mono font-semibold ${maDist >= 0 ? "text-emerald-300" : "text-red-300"}`}>
            {maDist >= 0 ? "+" : ""}{maDist.toFixed(1)}%
          </div>
        </div>
        <div className="rounded-lg bg-slate-900/60 px-2 py-2 text-center">
          <div className="text-slate-500">데이터</div>
          <div className={`mt-0.5 font-semibold ${dataAdj === 0 ? "text-emerald-300" : dataAdj <= -15 ? "text-red-300" : "text-amber-300"}`}>
            {dataAdj === 0 ? "정상" : dataAdj <= -15 ? "오류" : hasOhlcv ? "종가 기준" : "부분"}
          </div>
        </div>
      </div>

      {(() => {
        const freshness = dataFreshnessInfo({
          latestDataDate: dataHealth?.ohlcvLatestDate,
          recoGeneratedAt: dataHealth?.recoGeneratedAt,
          dataStatus: dataHealth?.dataStatus || dataHealth?.status,
        });
        return (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-800/70 pt-3 text-[11px] text-slate-500">
            <span className={`rounded-full border px-2 py-0.5 ${dataFreshnessBadgeClass(freshness.state)}`}>
              {freshness.label}
            </span>
            <span>{freshness.basisText}</span>
            {dataHealth?.recoGeneratedAt && (
              <span>데이터 기준: {String(dataHealth.recoGeneratedAt).slice(0, 16).replace("T", " ")}</span>
            )}
          </div>
        );
      })()}

      {isLow && (
        <div className="mt-3 rounded-lg border border-red-800/40 bg-red-950/30 px-3 py-2 text-[11px] text-red-300">
          ⚠ 신규 진입 시 평소보다 엄격한 기준을 적용하세요. 보유 손절가를 재확인하세요.
        </div>
      )}
    </div>
  );
}

function TodayConclusionCard({
  regime,
  dataHealth,
  todayCount,
  watchCount,
  riskCount,
}: {
  regime: any;
  dataHealth: any;
  todayCount: number;
  watchCount: number;
  riskCount: number;
}) {
  const gate = getMarketGateInfo(regime, dataHealth);
  const freshness = dataFreshnessInfo({
    latestDataDate: dataHealth?.ohlcvLatestDate,
    recoGeneratedAt: dataHealth?.recoGeneratedAt,
    dataStatus: dataHealth?.dataStatus || dataHealth?.status,
  });
  const dataBasis = dataHealth?.recoGeneratedAt
    ? String(dataHealth.recoGeneratedAt).slice(0, 16).replace("T", " ")
    : freshness.latestDate || "확인 필요";
  const priceCount = `${dataHealth?.kisLiveCount ?? 0}/${dataHealth?.kisTargetCount ?? 0}`;
  const ohlcvCount = `${dataHealth?.ohlcvCount ?? 0}종목`;
  const title = gate.isLow || riskCount > 0
    ? "오늘은 선별 진입만 허용"
    : gate.isMid
      ? "오늘은 조건 충족 종목만 선별"
      : "오늘은 기준가 근접 후보 우선";
  const subtitle = gate.isLow
    ? "시장 약세로 보수적 기준을 적용하세요."
    : riskCount > 0
      ? "보유 종목 리스크도 함께 점검하세요."
      : gate.isMid
        ? "EV·손익비 조건을 더 엄격히 확인하세요."
        : "검토 후보의 기준가 접근 여부를 확인하세요.";
  const textCls = gate.isHigh ? "text-emerald-200" : gate.isMid ? "text-amber-200" : "text-red-200";
  const barCls = gate.isHigh ? "bg-emerald-500" : gate.isMid ? "bg-amber-500" : "bg-red-500";

  return (
    <section className="rounded-2xl border border-blue-500/30 bg-blue-950/20 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-blue-300/80">오늘의 MONE 결론</div>
          <h2 className={`mt-1 text-2xl font-black tracking-normal ${textCls}`}>{title}</h2>
          <p className="mt-1 text-sm font-semibold text-slate-200">{subtitle}</p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-slate-300">
              검토 후보 {todayCount}개
            </span>
            <span className="rounded-full border border-slate-700 bg-slate-950/60 px-3 py-1 text-slate-300">
              대기 후보 {watchCount}개
            </span>
            <span className={`rounded-full border px-3 py-1 ${riskCount > 0 ? "border-red-500/40 bg-red-500/10 text-red-300" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"}`}>
              위험 보유 {riskCount}개
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span className={`rounded-full border px-2 py-0.5 ${dataFreshnessBadgeClass(freshness.state)}`}>{freshness.label}</span>
            <span>데이터 기준: {dataBasis}</span>
            <span>가격 데이터: {priceCount}</span>
            <span>OHLCV: {ohlcvCount}</span>
          </div>
        </div>
        <div className="w-full shrink-0 rounded-2xl border border-slate-800 bg-slate-950/50 p-4 lg:w-72">
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="text-xs text-slate-500">시장 컨디션</div>
              <div className={`mt-0.5 text-lg font-bold ${textCls}`}>{gate.levelText}</div>
            </div>
            <div className={`font-mono text-4xl font-black ${textCls}`}>
              {gate.strength}<span className="text-base text-slate-500">/100</span>
            </div>
          </div>
          <div className="mt-3 h-2 rounded-full bg-slate-800">
            <div className={`h-2 rounded-full ${barCls}`} style={{ width: `${gate.strength}%` }} />
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 text-center text-[11px]">
            <div>
              <div className="text-slate-500">시장 추세</div>
              <div className={regime?.regime === "BULL" ? "text-emerald-300" : regime?.regime === "BEAR" ? "text-red-300" : "text-slate-300"}>
                {regime?.regime === "BULL" ? "강세" : regime?.regime === "BEAR" ? "약세" : "중립"}
              </div>
            </div>
            <div>
              <div className="text-slate-500">MA20 이격</div>
              <div className={`font-mono ${gate.maDist >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                {gate.maDist >= 0 ? "+" : ""}{gate.maDist.toFixed(1)}%
              </div>
            </div>
            <div>
              <div className="text-slate-500">데이터</div>
              <div className={gate.dataAdj === 0 ? "text-emerald-300" : gate.dataAdj <= -15 ? "text-red-300" : "text-amber-300"}>
                {gate.dataAdj === 0 ? "정상" : gate.dataAdj <= -15 ? "확인 필요" : gate.hasOhlcv ? "종가 기준" : "부분"}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MarketRegimeSummaryCard({
  regime,
  selectedMarket,
  expanded,
  onToggle,
}: {
  regime: any;
  selectedMarket: "kr" | "us";
  expanded: boolean;
  onToggle: () => void;
}) {
  const maDist = Number(regime?.distanceMa20Pct ?? regime?.distanceToMa20Pct ?? 0);
  const isBear = regime?.regime === "BEAR";
  const isBull = regime?.regime === "BULL";
  const title = isBear ? "시장 경고" : "시장 요약";
  const regimeText = isBear ? "약세장" : isBull ? "강세장" : "중립";
  const recommendation = isBear ? "보수적 접근 권장" : isBull ? "조건 충족 후보 우선" : "선별 접근 권장";
  const borderCls = isBear
    ? "border-amber-700/40 bg-amber-950/15"
    : isBull
      ? "border-emerald-800/40 bg-emerald-950/15"
      : "border-slate-800 bg-slate-900/40";
  const textCls = isBear ? "text-amber-200" : isBull ? "text-emerald-200" : "text-slate-200";

  return (
    <section className={`rounded-2xl border px-4 py-3 ${borderCls}`}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className={`text-sm font-bold ${textCls}`}>{title}</div>
          <div className="mt-0.5 text-xs text-slate-400">
            {regimeText} · MA20 {maDist >= 0 ? "+" : ""}{maDist.toFixed(1)}% · {recommendation}
          </div>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="shrink-0 rounded-lg border border-slate-700 bg-slate-950/50 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-900"
        >
          {expanded ? "접기" : "자세히"}
        </button>
      </div>
      {expanded && (
        <div className="mt-3 border-t border-slate-800 pt-3 text-xs leading-5 text-slate-400">
          <div className="font-semibold text-slate-200">{regime?.label || regimeText}</div>
          {regime?.description && <div className="mt-1">{regime.description}</div>}
          <div className="mt-2 flex flex-wrap gap-2">
            <span className="rounded-full bg-slate-950/60 px-3 py-1">{getRegimeStance(regime?.regime, selectedMarket)}</span>
            {isBear && <span className="rounded-full bg-amber-900/30 px-3 py-1 text-amber-200">공격형 진입 보류 권장</span>}
            {isBull && <span className="rounded-full bg-emerald-900/30 px-3 py-1 text-emerald-200">균형·공격형 전략 정상 작동 중</span>}
          </div>
        </div>
      )}
    </section>
  );
}

// ── 보유종목 판단 함수
function getHoldingJudgment(item: any): { text: string; cls: string } {
  const risk = String(item.riskStatus || "");
  if (["HIGH", "위험"].includes(risk)) return { text: "손절 검토", cls: "bg-red-900/40 border-red-700/40 text-red-300" };
  if (["WATCH", "주의"].includes(risk)) return { text: "주의 필요", cls: "bg-amber-900/30 border-amber-700/40 text-amber-300" };

  const current = Number(item.currentPrice || 0);
  const avg     = Number(item.avgPrice || item.avgBuyPrice || 0);
  const target  = Number(item.targetPrice || 0);
  if (current > 0 && avg > 0 && target > avg) {
    const progress = (current - avg) / (target - avg);
    if (progress >= 0.8) return { text: "일부익절 검토", cls: "bg-emerald-900/30 border-emerald-700/40 text-emerald-300" };
    if (progress >= 0.5) return { text: "목표가 근접", cls: "bg-sky-900/30 border-sky-700/40 text-sky-300" };
  }
  return { text: "유지", cls: "bg-slate-800/60 border-slate-700/40 text-slate-400" };
}

// ── 온보딩 패널 (보유종목 없을 때)
function OnboardingPanel({ onNavigate }: { onNavigate?: (page: PageId) => void }) {
  return (
    <section className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-center">
      <div className="mx-auto max-w-sm">
        <div className="mb-2 text-2xl">📋</div>
        <h2 className="text-base font-semibold text-slate-100">보유종목을 등록해주세요</h2>
        <p className="mt-2 text-sm text-slate-400 leading-relaxed">
          내 종목을 기준으로 오늘의 위험과 기회를 1분 안에 점검해드립니다.<br />
          <span className="text-slate-500 text-xs">MONE은 추천보다 먼저 하면 안 되는 거래를 알려줍니다.</span>
        </p>
        <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-center">
          <button
            onClick={() => onNavigate?.("holdings")}
            className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-500 transition-colors"
          >
            보유종목 등록하기
          </button>
          <button
            onClick={() => onNavigate?.("stocks")}
            className="rounded-xl border border-slate-700 bg-slate-900 px-5 py-2.5 text-sm text-slate-300 hover:bg-slate-800 transition-colors"
          >
            종목 탐색 먼저 보기
          </button>
        </div>
      </div>
    </section>
  );
}

// ── 6차: 반영 여부 배지 + Score Breakdown 아코디언 패널
function ScoreBreakdownPanel({ item }: { item: any }) {
  const [open, setOpen] = useState(false);
  if (!item) return null;

  const hasBreakdown = (
    item.baseScore != null ||
    item.chartScoreAdjustment != null ||
    item.eventScoreAdjustment != null ||
    item.adaptiveScoreAdjustment != null ||
    item.finalScore != null ||
    item.chartSignalSummary ||
    item.eventSummary ||
    item.adaptiveScoreSummary ||
    item.entryBasis ||
    item.targetBasis ||
    item.stopBasis ||
    item.dataSourceType ||
    item.eventDataSourceType ||
    item.validationConfidence != null
  );

  if (!hasBreakdown) return null;

  function row(label: string, value: any, unit?: string) {
    const v = value ?? null;
    const display = v === null || v === undefined || v === "" ? "-"
      : unit ? `${typeof v === "number" ? v.toFixed(typeof v === "number" && Math.abs(v) < 10 ? 2 : 0) : v}${unit}`
      : String(v);
    return (
      <div key={label} className="flex items-start justify-between gap-2 text-[11px]">
        <span className="shrink-0 text-slate-500">{label}</span>
        <span className="text-right font-mono text-slate-300">{display}</span>
      </div>
    );
  }

  const { label: dsLabel, badgeClass: dsBadge } = dataSourceLabel(item.dataSourceType);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40">
      {/* 헤더 + 배지 행 */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold text-slate-300">반영 상세</span>
          {/* 인라인 핵심 배지 미리보기 */}
          <RecommendationBadges item={item} maxVisible={3} />
        </div>
        <span className="ml-2 shrink-0 text-[10px] text-slate-500">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t border-slate-800 px-4 pb-4 pt-3 space-y-2">
          {/* Score breakdown */}
          {(item.baseScore != null || item.finalScore != null || item.chartScoreAdjustment != null || item.eventScoreAdjustment != null || item.adaptiveScoreAdjustment != null) && (
            <div className="rounded-lg bg-slate-950/50 p-3 space-y-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-2">점수 흐름</div>
              {row("기본 점수 (baseScore)", item.baseScore != null ? Number(item.baseScore).toFixed(1) : null)}
              {row("차트 조정 (chartScoreAdjustment)", item.chartScoreAdjustment != null ? (Number(item.chartScoreAdjustment) >= 0 ? "+" : "") + Number(item.chartScoreAdjustment).toFixed(1) : null)}
              {row("이벤트 조정 (eventScoreAdjustment)", item.eventScoreAdjustment != null ? (Number(item.eventScoreAdjustment) >= 0 ? "+" : "") + Number(item.eventScoreAdjustment).toFixed(1) : null)}
              {row("Adaptive 조정 (adaptiveScoreAdjustment)", item.adaptiveScoreAdjustment != null ? (Number(item.adaptiveScoreAdjustment) >= 0 ? "+" : "") + Number(item.adaptiveScoreAdjustment).toFixed(1) : null)}
              {item.finalScore != null && (
                <div className="flex items-center justify-between border-t border-slate-800 pt-1.5 text-[11px]">
                  <span className="font-semibold text-slate-300">최종 점수 (finalScore)</span>
                  <span className={`font-mono font-bold ${Number(item.finalScore) >= 60 ? "text-emerald-300" : Number(item.finalScore) >= 45 ? "text-amber-300" : "text-slate-400"}`}>
                    {Number(item.finalScore).toFixed(1)}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* 요약 문자열 */}
          {(item.chartSignalSummary || item.eventSummary || item.adaptiveScoreSummary) && (
            <div className="rounded-lg bg-slate-950/50 p-3 space-y-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-2">신호 요약</div>
              {item.chartSignalSummary && <div className="text-[11px] text-slate-400"><span className="text-sky-400 font-medium">차트 </span>{item.chartSignalSummary}</div>}
              {item.eventSummary && <div className="text-[11px] text-slate-400"><span className="text-amber-400 font-medium">이벤트 </span>{item.eventSummary}</div>}
              {item.adaptiveScoreSummary && <div className="text-[11px] text-slate-400"><span className="text-emerald-400 font-medium">AI보정 </span>{item.adaptiveScoreSummary}</div>}
            </div>
          )}

          {/* 진입·목표·손절 근거 */}
          {(item.entryBasis || item.targetBasis || item.stopBasis) && (
            <div className="rounded-lg bg-slate-950/50 p-3 space-y-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-2">가격 근거</div>
              {item.entryBasis && <div className="text-[11px] text-slate-400"><span className="text-sky-400 font-medium">진입 </span>{item.entryBasis}</div>}
              {item.targetBasis && <div className="text-[11px] text-slate-400"><span className="text-emerald-400 font-medium">목표 </span>{item.targetBasis}</div>}
              {item.stopBasis && <div className="text-[11px] text-slate-400"><span className="text-red-400 font-medium">손절 </span>{item.stopBasis}</div>}
            </div>
          )}

          {/* 데이터 소스 + 검증 신뢰도 */}
          <div className="rounded-lg bg-slate-950/50 p-3 space-y-1.5">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-2">데이터 상태</div>
            {item.dataSourceType && (
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-slate-500">데이터 소스</span>
                {dsLabel ? (
                  <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${dsBadge}`}>{dsLabel}</span>
                ) : (
                  <span className="font-mono text-slate-400">{item.dataSourceType}</span>
                )}
              </div>
            )}
            {item.eventDataSourceType && row("이벤트 소스", item.eventDataSourceType)}
            {item.validationConfidence != null && row("검증 신뢰도", `${(Number(item.validationConfidence) * 100).toFixed(0)}%`)}
          </div>
        </div>
      )}
    </div>
  );
}

function WhyPanel({ item, onClose, marketRegime }: { item: any; onClose: () => void; marketRegime?: any }) {
  const [conflict, setConflict] = useState<any>(null);
  useEffect(() => {
    if (!item.symbol) return;
    mone.portfolioConflict({
      symbol: item.symbol,
      market: item.market || "kr",
      sector: item.sector || "",
    }).then(setConflict).catch(() => {});
  }, [item.symbol]);
  const mode    = String(item.mode || item._mode || "balanced") as Mode;
  const horizon = String(item.horizon || item._horizon || "swing") as Horizon;
  const ev      = Number(item.expectedValue ?? 0);
  const rr      = Number(item.rrActual ?? 0);
  const score   = Number(item.finalScore ?? 0);
  const tags    = Array.isArray(item.strategyTags) ? item.strategyTags : [];
  const riskFlags = Array.isArray(item.riskFlags) ? item.riskFlags : [];
  const decisionBucket = String(item.decisionBucket || "관찰");
  const decisionReason = String(item.decisionReason || "");
  const supplySignal   = String(item.supplySignal || "NEUTRAL");
  const maConv         = Boolean(item.maConvergence);
  const cautionReasons = Array.isArray(item.cautionReasons) ? item.cautionReasons : [];
  const newsSentimentTag     = String(item.newsSentimentTag || "NEUTRAL");
  const newsSentimentReasons = Array.isArray(item.newsSentimentReasons) ? item.newsSentimentReasons : [];

  const bucketColor =
    decisionBucket === "오늘 진입"  ? "bg-emerald-600 text-white"
    : decisionBucket === "기다림"   ? "bg-sky-600 text-white"
    : decisionBucket === "다음 진입" ? "bg-blue-600 text-white"
    : decisionBucket === "관찰"     ? "bg-slate-500 text-slate-100"
    : decisionBucket === "대기 관찰" ? "bg-amber-600 text-white"
    : decisionBucket === "매수금지"  ? "bg-red-700 text-white"
    : decisionBucket === "주의"     ? "bg-red-700/80 text-white"
    : "bg-slate-700 text-slate-300";

  // EV 근거 (백엔드 probability 필드 활용)
  const prob = Number(item.probability ?? 0);
  const evBase = prob > 0 ? prob / 100 : null;

  return (
    <>
      {/* 배경 오버레이 */}
      <div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* 패널 */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col overflow-y-auto bg-slate-950 shadow-2xl ring-1 ring-slate-800">
        {/* 헤더 */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-5 py-4 backdrop-blur">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-slate-100">{displayName(item)}</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${bucketColor}`}>{decisionBucket}</span>
            </div>
            <div className="mt-0.5 text-xs text-slate-500">
              {item.symbol} · {modeLabel(mode)} · {horizonLabel(horizon)}
              {decisionReason && <span className="ml-2 text-slate-400">{decisionReason}</span>}
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 px-5 py-5">
          {/* 가격 그리드 */}
          <div className="grid grid-cols-4 gap-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-center text-[11px]">
            {[
              { label: "현재가", key: "current", color: "text-slate-200" },
              { label: "기준가", key: "entry",   color: "text-sky-300" },
              { label: "손절가", key: "stop",    color: "text-red-300" },
              { label: "목표가", key: "target",  color: "text-emerald-300" },
            ].map(({ label, key, color }) => (
              <div key={key}>
                <div className="text-slate-500">{label}</div>
                <div className={`mt-1 font-mono font-semibold ${color}`}>{priceText(item, key as any, "—")}</div>
              </div>
            ))}
          </div>

          {/* EV + RR 요약 */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-center">
              <div className="text-[10px] text-slate-500">기댓값 EV</div>
              <div className={`mt-1 text-lg font-bold font-mono ${ev >= 2 ? "text-emerald-300" : ev >= 0 ? "text-slate-200" : "text-red-300"}`}>
                {ev >= 0 ? "+" : ""}{ev.toFixed(1)}%
              </div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-center">
              <div className="text-[10px] text-slate-500">손익비 RR</div>
              <div className={`mt-1 text-lg font-bold font-mono ${rr >= 2 ? "text-emerald-300" : rr >= 1.5 ? "text-amber-300" : "text-red-300"}`}>
                {rr > 0 ? rr.toFixed(1) : "—"}
              </div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-center">
              <div className="text-[10px] text-slate-500">종합 점수</div>
              <div className={`mt-1 text-lg font-bold font-mono ${score >= 65 ? "text-emerald-300" : score >= 50 ? "text-amber-300" : "text-slate-400"}`}>
                {score.toFixed(0)}점
              </div>
            </div>
          </div>

          {/* 가격 레벨 경고 (손절가≥기준가 등) */}
          {item.priceLevelWarning && (
            <div className="flex items-center gap-2 rounded-xl border border-red-600/40 bg-red-950/20 px-4 py-2.5 text-[11px]">
              <span className="text-red-400">⚠</span>
              <span className="font-semibold text-red-300">가격 설정 오류: {item.priceLevelWarning}</span>
            </div>
          )}

          {/* 검토 체크리스트 */}
          {(() => {
            const current = Number(item.currentPrice || 0);
            const entry   = Number(item.entry || 0);
            // mode별 허용 최대 이격 (MODE_RULES와 동기화)
            const modeMaxGap = mode === "conservative" ? 3.5 : mode === "aggressive" ? 13 : 7.5;
            const gapPct  = entry > 0 && current > 0 ? Math.abs((current - entry) / entry * 100) : null;
            const inRange = gapPct != null && gapPct <= modeMaxGap;
            const evOk    = ev > 0;
            const regimeOk = !marketRegime || marketRegime.regime !== "BEAR";
            const dataOk  = !["STALE", "ERROR", "DATA_PENDING"].includes(String(item.dataStatus || ""));
            const noCaution = !Array.isArray(item.cautionReasons) || item.cautionReasons.length === 0;
            const noPlWarning = !item.priceLevelWarning;

            const checks = [
              { label: "EV 양수", ok: evOk, detail: evOk ? `+${ev.toFixed(1)}%` : `${ev.toFixed(1)}% (음수)` },
              { label: "기준가 범위", ok: inRange, detail: gapPct != null ? `현재가 ±${gapPct.toFixed(1)}% (한도 ${modeMaxGap}%)` : "가격 데이터 확인 중" },
              { label: "시장 레짐", ok: regimeOk, detail: marketRegime ? (marketRegime.regime === "BULL" ? "강세장 정상" : marketRegime.regime === "BEAR" ? "약세장 — 주의" : "중립") : "확인 불가" },
              { label: "데이터 상태", ok: dataOk, detail: dataOk ? (item.dataAsOf ? `정상 · 기준일 ${item.dataAsOf}` : "정상") : String(item.dataStatus || "미확인") },
              { label: "주의사항", ok: noCaution && noPlWarning, detail: !noPlWarning ? item.priceLevelWarning : (noCaution ? "없음" : `${item.cautionReasons?.length}개`) },
            ];
            const passCount = checks.filter((c) => c.ok).length;

            return (
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-xs font-semibold text-slate-300">검토 체크리스트</div>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                    passCount === checks.length ? "bg-emerald-900/50 text-emerald-300"
                    : passCount >= 3 ? "bg-amber-900/40 text-amber-300"
                    : "bg-red-900/40 text-red-300"
                  }`}>
                    {passCount}/{checks.length} 통과
                  </span>
                </div>
                <div className="space-y-1.5">
                  {checks.map(({ label, ok, detail }) => (
                    <div key={label} className="flex items-center justify-between text-[11px]">
                      <div className="flex items-center gap-2">
                        <span className={ok ? "text-emerald-400" : "text-red-400"}>{ok ? "✓" : "✗"}</span>
                        <span className={ok ? "text-slate-300" : "text-slate-400"}>{label}</span>
                      </div>
                      <span className={`font-mono ${ok ? "text-slate-400" : "text-amber-400"}`}>{detail}</span>
                    </div>
                  ))}
                </div>
                {/* 데이터 출처 + 기준일 */}
                {(item.dataAsOf || item.currentPriceSource) && (
                  <div className="mt-3 border-t border-slate-800 pt-2.5 space-y-0.5 text-[10px] text-slate-500">
                    {item.dataAsOf && <div>데이터 기준일 <span className="text-slate-400 font-mono">{item.dataAsOf}</span></div>}
                    {item.currentPriceSource && (
                      <div>현재가 소스 <span className="text-slate-400 font-mono">{
                        item.currentPriceSource === "actual_ohlcv" ? "OHLCV 종가" :
                        item.currentPriceSource === "api" ? "KIS API 실시간" :
                        item.currentPriceSource === "csv" ? "보고서 기준" :
                        item.currentPriceSource === "close_history_fallback" ? "이전 종가 대체" :
                        item.currentPriceSource
                      }</span></div>
                    )}
                  </div>
                )}
                {passCount < 3 && (
                  <div className="mt-2 rounded-lg bg-red-950/30 px-2.5 py-1.5 text-[10px] text-red-300">
                    조건 미충족이 많습니다. 신규 판단 전 충분히 검토하세요.
                  </div>
                )}
              </div>
            );
          })()}

          {/* 리스크 근거 */}
          {item.riskReason && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px]">
              <div className="mb-1.5 text-xs font-semibold text-slate-400">리스크 근거</div>
              <div className="text-slate-300">{item.riskReason}</div>
            </div>
          )}

          {/* 포트폴리오 충돌 검사 */}
          {conflict && Array.isArray(conflict.conflicts) && conflict.conflicts.length > 0 && (
            <div className="rounded-xl border border-amber-800/40 bg-amber-950/20 p-4">
              <div className="mb-2 text-xs font-semibold text-amber-400">포트폴리오 충돌 감지</div>
              <div className="mb-2 text-[11px] text-amber-300">{conflict.message}</div>
              <div className="space-y-1">
                {conflict.conflicts.map((c: any) => (
                  <div key={c.symbol} className="flex items-center gap-2 text-[11px] text-amber-400">
                    <span className="text-amber-600">•</span>
                    <span>{c.name} ({c.symbol})</span>
                    <span className="ml-auto rounded-full bg-amber-900/40 px-1.5 py-0.5 text-[10px]">{c.type}</span>
                  </div>
                ))}
              </div>
              <div className="mt-2 text-[10px] text-slate-500">같은 섹터에 집중하면 분산 효과가 줄어듭니다.</div>
            </div>
          )}

          {/* 위험 예산 기반 수량 계산 */}
          {(() => {
            const entryP = Number(item.entry || 0);
            const stopP  = Number(item.stop  || 0);
            const riskPerShare = entryP > stopP && stopP > 0 ? entryP - stopP : 0;
            if (riskPerShare <= 0) return null;
            const scenarios = [
              { label: "50만원", budget: 500_000 },
              { label: "100만원", budget: 1_000_000 },
              { label: "200만원", budget: 2_000_000 },
            ];
            return (
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
                <div className="mb-1 text-xs font-semibold text-slate-300">위험 예산 기반 수량</div>
                <div className="mb-3 text-[11px] text-slate-500">
                  손절가 기준 주당 손실 <span className="font-mono text-red-300">{riskPerShare.toLocaleString()}원</span>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {scenarios.map(({ label, budget }) => {
                    const qty = Math.floor(budget / riskPerShare);
                    const totalAmt = qty * entryP;
                    return (
                      <div key={label} className="rounded-lg bg-slate-900/60 p-2 text-center">
                        <div className="text-[10px] text-slate-500">최대손실 {label}</div>
                        <div className="mt-0.5 font-mono text-base font-bold text-slate-200">{qty}주</div>
                        <div className="text-[10px] text-slate-500">{totalAmt > 0 ? `${Math.round(totalAmt / 10000)}만원` : "—"}</div>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-2 text-[10px] text-slate-600">최대 손실 금액 ÷ (기준가 − 손절가) · 참고용 모의 계산</div>
              </div>
            );
          })()}

          {/* Walk-Forward 전략 검증 */}
          {item.walkforwardMetrics && typeof item.walkforwardMetrics === "object" && (item.walkforwardMetrics as any).winRate !== undefined && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px]">
              <div className="mb-2 flex items-center justify-between text-xs font-semibold text-slate-300">
                <span>Walk-Forward 전략 검증</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  (item.walkforwardMetrics as any).confidence === "HIGH" ? "bg-emerald-900/50 text-emerald-300"
                  : (item.walkforwardMetrics as any).confidence === "LOW"  ? "bg-red-900/40 text-red-300"
                  : "bg-slate-700 text-slate-400"
                }`}>
                  {(item.walkforwardMetrics as any).confidence === "HIGH" ? "전략 신뢰 ↑" : (item.walkforwardMetrics as any).confidence === "LOW" ? "전략 부진 ↓" : "보통"}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 font-mono text-[10px]">
                <div>
                  <div className="text-slate-500">승률 (최근 3W)</div>
                  <div className={`mt-0.5 font-semibold ${Number((item.walkforwardMetrics as any).winRate) >= 55 ? "text-emerald-300" : Number((item.walkforwardMetrics as any).winRate) < 35 ? "text-red-300" : "text-slate-300"}`}>
                    {Number((item.walkforwardMetrics as any).winRate).toFixed(1)}%
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">평균수익</div>
                  <div className={`mt-0.5 font-semibold ${Number((item.walkforwardMetrics as any).avgReturn) > 0 ? "text-emerald-300" : "text-red-300"}`}>
                    {Number((item.walkforwardMetrics as any).avgReturn) >= 0 ? "+" : ""}{Number((item.walkforwardMetrics as any).avgReturn).toFixed(2)}%
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">점수 보정</div>
                  <div className={`mt-0.5 font-semibold ${Number(item.walkforwardAdjustment) > 0 ? "text-emerald-300" : Number(item.walkforwardAdjustment) < 0 ? "text-red-300" : "text-slate-400"}`}>
                    {Number(item.walkforwardAdjustment) >= 0 ? "+" : ""}{Number(item.walkforwardAdjustment)}점
                  </div>
                </div>
              </div>
              {(item.walkforwardMetrics as any).lastWindow && (
                <div className="mt-1.5 text-[10px] text-slate-600">기준: {(item.walkforwardMetrics as any).windows}개 윈도우 · 최근 {(item.walkforwardMetrics as any).lastWindow}</div>
              )}
            </div>
          )}

          {/* EV 계산 근거 */}
          {evBase !== null && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px]">
              <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-300">
                <Info size={13} /> EV 계산 근거
              </div>
              <div className="space-y-1 font-mono text-slate-400">
                <div>승률 <span className="text-emerald-400">{(evBase * 100).toFixed(0)}%</span>
                  {" × "}목표 <span className="text-emerald-400">{priceText(item, "target", "—")}</span>
                </div>
                <div>패율 <span className="text-red-400">{((1 - evBase) * 100).toFixed(0)}%</span>
                  {" × "}손절 <span className="text-red-400">{priceText(item, "stop", "—")}</span>
                </div>
                <div className={`border-t border-slate-700 pt-1 font-bold ${ev >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                  EV = {ev >= 0 ? "+" : ""}{ev.toFixed(2)}%
                </div>
              </div>
            </div>
          )}

          {/* 세부 점수 분해 */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <div className="mb-3 text-xs font-semibold text-slate-300">점수 분해</div>
            <div className="space-y-2">
              {SCORE_ITEMS.map(({ key, label, color }) => {
                const val = Number((item as any)[key] ?? null);
                if (isNaN(val)) return null;
                return (
                  <div key={key} className="flex items-center gap-2 text-[11px]">
                    <span className="w-20 shrink-0 text-slate-400">{label}</span>
                    <div className="flex-1 overflow-hidden rounded-full bg-slate-800">
                      <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${Math.max(0, Math.min(100, val))}%` }} />
                    </div>
                    <span className="w-8 text-right font-mono text-slate-300">{val.toFixed(0)}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 6차: 반영 여부 배지 + 상세 breakdown */}
          <ScoreBreakdownPanel item={item} />

          {/* 전략 태그 */}
          {tags.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <div className="mb-2 text-xs font-semibold text-slate-300">전략 태그</div>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tag: string, ti: number) => {
                  const labelMap: Record<string, string> = {
                    CAUTION:"⚠ 주의", MA_CONVERGENCE:"이격도 수렴", PULLBACK_BUY:"눌림목",
                    MOMENTUM:"모멘텀", VOLUME_BREAKOUT:"거래량 증가", BREAKOUT_52W:"52주 신고가 돌파",
                    NEAR_52W_HIGH:"신고가 근접", BB_SQUEEZE:"변동성 압축", STABLE_LOW_RISK:"안정형",
                    UNDERVALUED_GROWTH:"저평가 성장주", GOLDEN_CROSS:"🔼 골든크로스",
                    DEATH_CROSS:"🔽 데드크로스", MID_GOLDEN_CROSS:"📈 중기 골든크로스",
                    MID_DEATH_CROSS:"📉 중기 데드크로스", TRAILING_STOP_ALERT:"⚡ 트레일링 손절",
                  };
                  const colorMap: Record<string, string> = {
                    CAUTION:"border-red-600/40 bg-red-600/10 text-red-300",
                    DEATH_CROSS:"border-red-600/40 bg-red-600/10 text-red-300",
                    MID_DEATH_CROSS:"border-red-700/40 bg-red-700/10 text-red-400",
                    TRAILING_STOP_ALERT:"border-amber-500/40 bg-amber-500/10 text-amber-300",
                    GOLDEN_CROSS:"border-emerald-400/40 bg-emerald-400/10 text-emerald-300",
                    MID_GOLDEN_CROSS:"border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
                    MA_CONVERGENCE:"border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
                    PULLBACK_BUY:"border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
                    MOMENTUM:"border-orange-500/40 bg-orange-500/10 text-orange-300",
                    VOLUME_BREAKOUT:"border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
                    BREAKOUT_52W:"border-violet-500/40 bg-violet-500/10 text-violet-300",
                    NEAR_52W_HIGH:"border-violet-400/30 bg-violet-400/5 text-violet-400",
                    BB_SQUEEZE:"border-sky-500/40 bg-sky-500/10 text-sky-300",
                    STABLE_LOW_RISK:"border-teal-500/40 bg-teal-500/10 text-teal-300",
                    UNDERVALUED_GROWTH:"border-green-500/40 bg-green-500/10 text-green-300",
                  };
                  const tagLabels = Array.isArray(item.strategyTagLabels) ? item.strategyTagLabels as string[] : [];
                  const lbl = labelMap[tag] ?? tagLabels[ti] ?? tag;
                  const cls = colorMap[tag] ?? "border-slate-600 bg-slate-800 text-slate-300";
                  return <span key={tag} className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}>{lbl}</span>;
                })}
              </div>
            </div>
          )}

          {/* MA 수렴 신호 */}
          {maConv && (
            <div className="rounded-xl border border-cyan-800/40 bg-cyan-950/20 p-3 text-[11px] text-cyan-300">
              이격도 수렴 — 5일/20일/60일선이 근접 구간에 있습니다. 변동성 확대 이전 진입 적기입니다.
            </div>
          )}

          {/* 골든크로스 / 데드크로스 배너 */}
          {item.goldenCross && (
            <div className="rounded-xl border border-emerald-700/40 bg-emerald-950/20 p-3 text-[11px] text-emerald-300">
              🔼 골든크로스 — MA5가 MA20을 상향 돌파했습니다. 단기 상승 모멘텀 전환 신호.
            </div>
          )}
          {item.midGoldenCross && (
            <div className="rounded-xl border border-emerald-600/40 bg-emerald-950/20 p-3 text-[11px] text-emerald-200">
              📈 중기 골든크로스 — MA20이 MA60을 상향 돌파했습니다. 중기 추세 전환 신호.
            </div>
          )}
          {item.deathCross && (
            <div className="rounded-xl border border-red-800/40 bg-red-950/20 p-3 text-[11px] text-red-300">
              🔽 데드크로스 — MA5가 MA20을 하향 이탈했습니다. 단기 하락 전환 주의.
            </div>
          )}
          {item.midDeathCross && (
            <div className="rounded-xl border border-red-700/40 bg-red-950/20 p-3 text-[11px] text-red-400">
              📉 중기 데드크로스 — MA20이 MA60을 하향 이탈했습니다. 중기 약세 전환 주의.
            </div>
          )}

          {/* 트레일링 스탑 패널 */}
          {item.trailingStop != null && item.trailingStop > 0 && (
            <div className="rounded-xl border border-amber-800/40 bg-amber-950/20 p-3 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-amber-300">⚡ 트레일링 스탑</span>
                <span className="font-mono text-amber-200">
                  {item.market === "us"
                    ? `$${Number(item.trailingStop).toLocaleString(undefined, {maximumFractionDigits: 2})}`
                    : `${Math.round(Number(item.trailingStop)).toLocaleString()}원`}
                </span>
              </div>
              <div className="mt-1 text-slate-400">
                20일 최고가 기준 ATR×2 하락선 — 현재가로부터{" "}
                {item.trailingStopPct != null ? (
                  <span className={`font-mono font-bold ${Number(item.trailingStopPct) <= 3 ? "text-red-400" : "text-amber-300"}`}>
                    -{Number(item.trailingStopPct).toFixed(1)}%
                  </span>
                ) : "-"}
              </div>
            </div>
          )}

          {/* 수급 신호 */}
          {supplySignal !== "NEUTRAL" && (
            <div className={`rounded-xl border p-3 text-[11px] ${
              supplySignal === "STRONG_BUY" ? "border-blue-600/40 bg-blue-900/20 text-blue-300"
              : supplySignal === "INST_BUY"  ? "border-sky-600/40 bg-sky-900/20 text-sky-300"
              : "border-red-600/40 bg-red-900/20 text-red-300"
            }`}>
              수급 신호 — {SUPPLY_LABEL[supplySignal] ?? supplySignal}
            </div>
          )}

          {/* 뉴스/공시 감성 신호 */}
          {(newsSentimentTag === "HIGH_RISK" || newsSentimentTag === "POSITIVE") && (
            <div className={`rounded-xl border p-4 ${
              newsSentimentTag === "HIGH_RISK"
                ? "border-orange-800/40 bg-orange-950/20"
                : "border-emerald-800/40 bg-emerald-950/20"
            }`}>
              <div className={`mb-1 text-xs font-semibold ${newsSentimentTag === "HIGH_RISK" ? "text-orange-400" : "text-emerald-400"}`}>
                {newsSentimentTag === "HIGH_RISK" ? "⚠ 공시 리스크 감지" : "✓ 긍정 공시 감지"}
              </div>
              <ul className="space-y-0.5 text-[11px]">
                {newsSentimentReasons.map((r: string) => (
                  <li key={r} className={newsSentimentTag === "HIGH_RISK" ? "text-orange-300" : "text-emerald-300"}>
                    • {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 레버리지 ETF 경고 */}
          {item.isLeveragedEtf && item.leverageWarning && (
            <div className="rounded-xl border border-orange-600/40 bg-orange-950/20 p-3 text-[11px]">
              <div className="mb-1 font-semibold text-orange-300">⚡ 레버리지/인버스 ETF</div>
              <div className="text-orange-400/90">{item.leverageWarning}</div>
            </div>
          )}

          {/* 리스크 플래그 */}
          {(riskFlags.length > 0 || cautionReasons.length > 0) && (
            <div className="rounded-xl border border-red-800/40 bg-red-950/20 p-4">
              <div className="mb-2 text-xs font-semibold text-red-400">주의사항</div>
              <ul className="space-y-1 text-[11px] text-red-300">
                {riskFlags.map((f: string) => (
                  <li key={f}>• {RISK_FLAG_LABEL[f] ?? f}</li>
                ))}
                {cautionReasons.filter((r: string) => !riskFlags.some((f: string) => RISK_FLAG_LABEL[f] === r)).map((r: string) => (
                  <li key={r}>• {r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── 3×3 매트릭스 셀 (간결 버전)
function MatrixCell({ cell, onSelect }: { cell: StrategyCell; onSelect: (item: any) => void }) {
  const top = (cell.items || []).slice(0, 3);
  const todayIn = top.filter((i) => i.decisionBucket === "오늘 진입");
  const watching = top.filter((i) => i.decisionBucket === "대기 관찰");

  return (
    <div className="min-h-[140px] rounded-2xl border border-slate-800 bg-slate-950/50 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-300">{modeLabel(cell.mode)} · {horizonLabel(cell.horizon)}</span>
        <span className="text-[10px] text-slate-500">{cell.count}개</span>
      </div>
      {top.length === 0 ? (
        <div className="py-4 text-center text-[11px] text-slate-600">현재 조건 없음</div>
      ) : (
        <div className="space-y-1.5">
          {top.map((item) => {
            const bucket = String(item.decisionBucket || "");
            const isToday  = bucket === "오늘 진입";
            const isWait   = bucket === "기다림";
            const isNext   = bucket === "다음 진입";
            const isWatch  = bucket === "관찰" || bucket === "대기 관찰";
            const isCaution = bucket === "주의";
            const ev = Number(item.expectedValue || 0);
            const rowCls = isToday  ? "bg-emerald-950/40 border border-emerald-800/30"
              : isWait   ? "bg-sky-950/40 border border-sky-800/30"
              : isNext   ? "bg-blue-950/40 border border-blue-800/20"
              : isWatch  ? "bg-slate-900/60"
              : isCaution ? "bg-red-950/30 border border-red-900/20 opacity-50"
              : "bg-slate-950/50 opacity-60";
            return (
              <div key={item.symbol} onClick={() => onSelect(item)} className={`flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 transition-colors hover:brightness-125 ${rowCls}`}>
                <div className="min-w-0 flex-1">
                  <span className="truncate text-[11px] font-medium text-slate-200">{displayName(item)}</span>
                  {isToday  && <span className="ml-1 rounded bg-emerald-700/50 px-1 text-[9px] text-emerald-300">검토</span>}
                  {isWait   && <span className="ml-1 rounded bg-sky-700/50 px-1 text-[9px] text-sky-300">대기</span>}
                  {isNext   && <span className="ml-1 rounded bg-blue-700/50 px-1 text-[9px] text-blue-300">다음</span>}
                  {isCaution && <span className="ml-1 rounded bg-red-700/50 px-1 text-[9px] text-red-300">주의</span>}
                  {isWatch && item.timingLabel && <span className="ml-1 rounded bg-amber-900/40 px-1 text-[9px] text-amber-400">{item.timingLabel}</span>}
                </div>
                <span className={`font-mono text-[10px] ${ev >= 1 ? "text-emerald-400" : ev >= 0 ? "text-slate-400" : "text-red-400"}`}>
                  {ev >= 0 ? "+" : ""}{ev.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── 메인 컴포넌트
function ReportDigestCard({ digest, loading }: { digest: any; loading: boolean }) {
  const premarket = digest?.premarket || {};
  const closing = digest?.closing || {};
  const backtest = digest?.backtest || {};
  const preItems = Array.isArray(premarket.items) ? premarket.items : [];
  const closingItems = Array.isArray(closing.items) ? closing.items : [];
  const stat = backtest.summary || backtest.stats || backtest;
  const winRate = Number(stat.winRate ?? stat.win_rate ?? stat.accuracy ?? NaN);
  const avgReturn = Number(stat.avgReturn ?? stat.avg_return ?? stat.averageReturn ?? NaN);
  const sample = Number(stat.totalTrades ?? stat.total ?? stat.count ?? stat.sample ?? 0);
  const top = preItems[0] || {};

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-100">오늘 운용 요약</h2>
          <p className="mt-0.5 text-xs text-slate-500">오늘 검토 후보, 검증 완료, 전략 성과를 홈에서 바로 확인합니다.</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${
          loading ? "border-slate-700 bg-slate-800 text-slate-400" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
        }`}>
          {loading ? "갱신 중" : "요약"}
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
          <div className="text-[11px] text-slate-500">오늘 검토 후보</div>
          <div className="mt-1 font-mono text-lg font-bold text-emerald-300">{loading ? "-" : `${preItems.length}개`}</div>
          <div className="mt-1 truncate text-[11px] text-slate-400">
            {top.name || top.companyName || top.symbol ? `상위 후보: ${top.name || top.companyName || top.symbol}` : "상위 후보: 없음"}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
          <div className="text-[11px] text-slate-500">검증 완료</div>
          <div className="mt-1 font-mono text-lg font-bold text-sky-300">{loading ? "-" : `${closingItems.length}건`}</div>
          <div className="mt-1 text-[11px] text-slate-400">
            {!loading && (
              String(closing.status || "").toUpperCase() === "OK" ? "이상 없음"
              : String(closing.status || "").includes("확인") ? "검토 필요"
              : closing.status || "대기"
            )}
          </div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
          <div className="text-[11px] text-slate-500">성과 통계</div>
          <div className="mt-1 font-mono text-lg font-bold text-violet-300">{sample > 0 && Number.isFinite(winRate) ? `${winRate.toFixed(1)}%` : "대기"}</div>
          <div className="mt-1 text-[11px] text-slate-400">{sample > 0 ? `${sample}회 표본 누적 후 표시` : "성과 통계는 표본 누적 후 표시"}</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
          <div className="text-[11px] text-slate-500">평균 수익률</div>
          <div className={`mt-1 font-mono text-lg font-bold ${Number.isFinite(avgReturn) && avgReturn < 0 ? "text-red-300" : "text-emerald-300"}`}>
            {Number.isFinite(avgReturn) ? `${avgReturn >= 0 ? "+" : ""}${avgReturn.toFixed(2)}%` : "-"}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">balanced / swing</div>
        </div>
      </div>
    </section>
  );
}

export default function HomePage({
  onNavigate,
  bootData,
  bootStatus = "idle",
  booting = false,
}: {
  onNavigate?: (page: PageId) => void;
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
  const [operationSummary, setOperationSummary] = useState<any>(null);
  // While the boot overlay is still showing, stay silent (no spinner) — boot data arrives before overlay lifts
  const [loading, setLoading] = useState(booting ? false : (!bootData || !Object.keys(bootData).length));
  const [refreshing, setRefreshing] = useState(false);
  const [refreshWarning, setRefreshWarning] = useState("");
  const [marketChoice, setMarketChoice] = useState<MarketChoice>("auto");
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [showJournal, setShowJournal] = useState(false);
  const [showMatrix, setShowMatrix] = useState(false);
  const [badgeMap, setBadgeMap] = useState<Record<string, any>>({});
  const [reportDigest, setReportDigest] = useState<any>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showDigest, setShowDigest] = useState(false);
  const [storyMap, setStoryMap] = useState<Record<string, any>>({});
  const [editStory, setEditStory] = useState<string | null>(null);
  const [storyForm, setStoryForm] = useState({ why: "", invalidation: "", reviewDate: "" });
  const [clientReady, setClientReady] = useState(false);
  const [clock, setClock] = useState<Date | null>(null);
  const [alertsExpanded, setAlertsExpanded] = useState(false);
  const [marketDetailExpanded, setMarketDetailExpanded] = useState(false);
  // 실적발표 일정 맵: symbol → D-day
  const [earningsMap, setEarningsMap] = useState<Record<string, number>>({});
  // 데이터 소스 신선도
  const [dataSources, setDataSources] = useState<any>(null);
  // 매크로/실적 이벤트 배너
  const [calendarAlert, setCalendarAlert] = useState<any>(null);
  // 손절/목표가 근접 알림
  const [nearAlerts, setNearAlerts] = useState<any[]>([]);
  const sessionClock = clock || new Date();
  const selectedMarket = marketChoice === "auto" ? (clientReady ? getDefaultMarketBySession(sessionClock) : "kr") : marketChoice;
  const sessionStatus = clientReady ? getMarketSessionStatus(selectedMarket, sessionClock) : "확인 중";
  const sessionPhase = sessionStatus as SessionPhase;
  const countdown = clientReady ? getSessionCountdown(selectedMarket, sessionClock) : "";
  const sessionCtx = getSessionContext(sessionPhase);
  const marketChoiceLabel = clientReady && marketChoice !== "auto" ? "수동" : "자동";

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

  const applyCachedOrBootState = useCallback((market: "kr" | "us") => {
    // 1. Re-entry: use module-level cache (user navigated away and came back)
    const cached = readHomeCache(market);
    if (cached) {
      setMatrix(cached.matrix);
      setHoldings(cached.holdings);
      setSummary(cached.summary);
      setMarketRegime(cached.marketRegime);
      setDataHealth(cached.dataHealth);
      setAllItems(cached.allItems);
      setLoading(false);
      setRefreshWarning("");
      return true;
    }
    // 2. First load: use boot preload data from the loading screen
    const result = bootMarketHomeSummary(bootData, market);
    if (!result) return false;
    const matrixResult: StrategyCell[] = MODES.flatMap((mode) =>
      HORIZONS.map((horizon) => {
        const cell = (result.matrix as any)?.[`${mode}_${horizon}`] || {};
        const cellItems = dedupeBySymbol(Array.isArray(cell.items) ? cell.items : [])
          .slice(0, 5)
          .map((item: any) => ({ ...item, _mode: mode, _horizon: horizon }));
        return { mode, horizon, items: cellItems, count: Number(cell.count || cellItems.length || 0), status: String(cell.status || "OK") } satisfies StrategyCell;
      })
    );
    const h = result.holdings || {};
    setHoldings(dedupeBySymbol(Array.isArray(h.items) ? h.items : []));
    setSummary(h.summary || null);
    setMatrix(matrixResult);
    setMarketRegime(normalizeMarketRegime(result.marketRegime, market));
    setDataHealth(normalizeDataHealth(result.dataHealth));
    setAllItems(matrixResult.flatMap((cell) => cell.items));
    setLoading(false);
    setRefreshWarning("");
    return true;
  }, [bootData]);

  async function load(options: { background?: boolean } = {}) {
    const hasCurrentData = options.background || allItems.length > 0 || matrix.length > 0 || Boolean(dataHealth);
    if (hasCurrentData) {
      setRefreshing(true);
      setLoading(false);
    } else {
      setLoading(true);
    }
    setRefreshWarning("");
    try {
      // 단일 통합 API 호출 (기존 10회 → 1회)
      const result = await mone.homeSummary({ market: selectedMarket, limit: 12 });

      // matrix: { conservative_short: {items, count, status}, ... } → StrategyCell[]
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
      // Save to module cache so re-entry is instant
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
    try {
      const savedStories = JSON.parse(window.localStorage.getItem("mone:stories") || "{}");
      setStoryMap(savedStories);
    } catch {};
    const refreshClock = () => setClock(new Date());
    refreshClock();
    const timer = window.setInterval(refreshClock, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    // Don't fetch while the boot overlay is still showing — boot data will seed us on dismiss
    if (clientReady && !booting) {
      const hadCache = applyCachedOrBootState(selectedMarket);
      load({ background: hadCache });
    }
  }, [clientReady, selectedMarket, booting]);

  useEffect(() => {
    if (!clientReady) return;
    setReportLoading(!reportDigest);
    Promise.allSettled([
      mone.report("premarket", { market: selectedMarket, mode: "balanced", horizon: "swing", limit: 20 }),
      mone.report("closing", { market: selectedMarket, mode: "balanced", horizon: "swing", limit: 20 }),
      mone.backtestSummary({ market: selectedMarket, mode: "balanced", horizon: "swing" }),
    ]).then(([premarket, closing, backtest]) => {
      setReportDigest({
        premarket: premarket.status === "fulfilled" ? premarket.value : null,
        closing: closing.status === "fulfilled" ? closing.value : null,
        backtest: backtest.status === "fulfilled" ? backtest.value : null,
      });
    }).catch(() => {
      if (!reportDigest) setReportDigest(null);
    })
      .finally(() => setReportLoading(false));
  }, [clientReady, selectedMarket]);

  useEffect(() => {
    if (!clientReady) return;
    let active = true;
    mone.operationSummary({ market: selectedMarket, mode: "balanced", horizon: "swing" })
      .then((res) => {
        if (active) setOperationSummary(res || null);
      })
      .catch(() => {
        if (active) setOperationSummary(null);
      });
    return () => { active = false; };
  }, [clientReady, selectedMarket]);

  // 실적발표 일정 로드 + earningsMap 구성
  useEffect(() => {
    mone.earningsCalendar({ market: selectedMarket as any, days: 14 })
      .then((res) => {
        const map: Record<string, number> = {};
        const today = new Date();
        for (const e of (res.items || [])) {
          const diff = Math.ceil((new Date(e.date).getTime() - today.getTime()) / 86400000);
          if (diff >= 0 && diff <= 14) map[e.symbol] = diff;
        }
        setEarningsMap(map);
      })
      .catch(() => {});
  }, [selectedMarket]);

  // 매크로/실적 이벤트 배너 로드 (마운트 1회, 시장 변경 시 갱신)
  useEffect(() => {
    if (!clientReady) return;
    mone.calendarToday({ market: selectedMarket as any })
      .then((res) => {
        if (res?.status === "OK") setCalendarAlert(res);
      })
      .catch(() => {});
  }, [clientReady, selectedMarket]);

  // 손절/목표가 근접 알림 로드
  useEffect(() => {
    if (!clientReady) return;
    mone.nearAlerts({ market: selectedMarket, thresholdPct: 5 })
      .then((res) => {
        setNearAlerts(Array.isArray(res.alerts) ? res.alerts : []);
      })
      .catch(() => setNearAlerts([]));
  }, [clientReady, selectedMarket]);

  // 데이터 소스 신선도 로드 (마운트 1회)
  useEffect(() => {
    if (!clientReady) return;
    fetch("/api/health/data-sources")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setDataSources(d); })
      .catch(() => {});
  }, [clientReady]);

  // ── 브라우저 알림: 장중 진입 임박 종목 감지 (1분 주기)
  useEffect(() => {
    if (!clientReady) return;
    if (typeof window === "undefined" || !("Notification" in window)) return;

    const notifiedKeys = new Set<string>();

    function checkAndNotify() {
      const phase = getMarketSessionStatus(selectedMarket, new Date()) as SessionPhase;
      if (phase !== "장중") return;                    // 장중에만 작동
      if (Notification.permission !== "granted") return;

      allItems
        .filter((i) => i.decisionBucket === "오늘 진입")
        .forEach((item) => {
          const key = `${item.symbol}-${item._mode}-${item._horizon}`;
          if (notifiedKeys.has(key)) return;

          const current = Number(item.currentPrice || 0);
          const entry   = Number(item.entry || 0);
          if (current <= 0 || entry <= 0) return;

          const gapPct = Math.abs((entry - current) / current * 100);
          if (gapPct <= 2.0) {
            notifiedKeys.add(key);
            new Notification(`🎯 진입 임박 — ${item.name || item.symbol}`, {
              body: `현재가 ${current.toLocaleString()}원  기준가 ${entry.toLocaleString()}원 (±${gapPct.toFixed(1)}%)`,
              tag: key,
            });
          }
        });
    }

    // 권한 요청 후 주기 체크 — cleanup은 useEffect 반환값으로 등록
    let intervalId: number | null = null;

    Notification.requestPermission().then((perm) => {
      if (perm !== "granted") return;
      checkAndNotify();
      intervalId = window.setInterval(checkAndNotify, 60_000) as unknown as number;
    });

    return () => {
      if (intervalId !== null) window.clearInterval(intervalId);
    };
  }, [clientReady, allItems, selectedMarket]);

  // ── 오늘 진입 후보: EV 높은 순, 종목 중복 제거
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

  // ── 대기 관찰 후보: 타이밍 임박 순 (1~2일 > 3~5일 > 다음 주)
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

  // ── 신호 자동 기록 (매수 검토 후보 로드 시)
  const dashboardAlerts = useMemo(() => {
    const alerts: { key: string; title: string; detail: string; tone: "amber" | "red" | "emerald" }[] = [];
    const add = (key: string, title: string, detail: string, tone: "amber" | "red" | "emerald" = "amber") => {
      if (alerts.some((alert) => alert.key === key)) return;
      alerts.push({ key, title, detail, tone });
    };

    [...todayEntries, ...watchItems].forEach((item) => {
      const symbol = String(item.symbol || "");
      const current = Number(item.currentPrice || item.price || 0);
      const entry = Number(item.entry || item.entryPrice || 0);
      const target = Number(item.target || item.targetPrice || 0);
      if (symbol && current > 0 && entry > 0) {
        const gap = Math.abs((current - entry) / entry) * 100;
        if (gap <= 3) add(`entry-${symbol}`, `${displayName(item)}이 기준가에 근접했습니다.`, `현재가와 기준가 차이 ${gap.toFixed(1)}%`, "emerald");
      }
      if (symbol && current > 0 && target > 0) {
        const gap = Math.abs((target - current) / target) * 100;
        if (gap <= 3) add(`target-${symbol}`, `${displayName(item)}이 목표가에 근접했습니다.`, `목표가까지 ${gap.toFixed(1)}%`, "amber");
      }
      const action = firstText(item.patternStrategy?.action, item.patternStrategyAction, item.newEntryDecision, "");
      if (symbol && action !== "-") add(`action-${symbol}`, `${displayName(item)}의 MONE 판단이 ${action}로 변경되었습니다.`, "분석 화면에서 진입·손절 계획을 확인하세요.", "amber");
      const risk = String(item.riskStatus || item.tradeBlockStatus || "").toUpperCase();
      if (symbol && risk && risk !== "NONE" && risk !== "OK" && risk !== "NORMAL") add(`risk-${symbol}`, `${displayName(item)}에 위험 패턴이 감지되었습니다.`, `상태: ${risk}`, "red");
    });

    const stopNear = holdings.filter((item: any) => {
      const current = Number(item.currentPrice || 0);
      const stop = Number(item.stopPrice || item.stop || 0);
      return current > 0 && stop > 0 && Math.abs((current - stop) / stop) * 100 <= 3;
    }).length;
    if (stopNear > 0) add("holdings-stop", `보유 종목 중 ${stopNear}개가 손절 기준에 가까워졌습니다.`, "보유 탭에서 손절가와 비중을 재점검하세요.", "red");

    const freshness = dataFreshnessInfo({
      latestDataDate: dataHealth?.ohlcvLatestDate,
      recoGeneratedAt: dataHealth?.recoGeneratedAt,
      dataStatus: dataHealth?.dataStatus || dataHealth?.status,
    });
    if (freshness.state === "old" || freshness.state === "unknown") {
      add("freshness", "관심종목/보유종목 데이터 신선도 확인이 필요합니다.", freshness.basisText, "amber");
    }

    return alerts.slice(0, 4);
  }, [todayEntries, watchItems, holdings, dataHealth]);

  const basisWarning = useMemo(() => operationBasisWarning(operationSummary), [operationSummary]);

  useEffect(() => {
    if (!todayEntries.length) return;
    todayEntries.forEach((item) => {
      mone.signalsRecord({
        market: item.market || selectedMarket,
        symbol: item.symbol,
        name: item.name || item.companyName || "",
        mode: item._mode || item.mode || "balanced",
        horizon: item._horizon || item.horizon || "swing",
        entry: Number(item.entry || 0),
        stop: Number(item.stop || 0),
        target: Number(item.target || 0),
        ev: Number(item.expectedValue || 0),
        probability: Number(item.probability || 0),
        score: Number(item.finalScore || 0),
        decisionBucket: item.decisionBucket || "",
        sector: item.sector || "",
      }).catch(() => {});
    });
  }, [todayEntries]);

  // ── 백테스트 뱃지 fetch (매수 검토 + 대기 관찰 종목)
  useEffect(() => {
    const items = [...todayEntries, ...watchItems];
    if (!items.length) return;
    const unique = Array.from(new Set(items.map((i) =>
      `${i.symbol}::${i._horizon || i.horizon || "swing"}::${i._mode || i.mode || "balanced"}`
    )));
    Promise.all(
      unique.map((key) => {
        const [symbol, horizon, mode] = key.split("::");
        return mone.signalsBadge({ symbol, horizon, mode })
          .then((res: any) => ({ key, data: res }))
          .catch(() => ({ key, data: null }));
      })
    ).then((results) => {
      const map: Record<string, any> = {};
      results.forEach(({ key, data }) => {
        if (data && (data.sample > 0 || data.pending)) map[key] = data;
      });
      setBadgeMap(map);
    });
  }, [todayEntries, watchItems]);

  const riskCount = holdings.filter((h) => ["위험", "주의", "HIGH", "WATCH"].includes(String(h.riskStatus || ""))).length;

  if (loading && !allItems.length) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <svg className="h-8 w-8 animate-spin text-slate-600" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm text-slate-500">데이터 불러오는 중...</span>
        </div>
      </div>
    );
  }

  return (
    <ErrorBoundary>
    <div className="space-y-6">
      {/* 추천 근거 패널 */}
      {selectedItem && <WhyPanel item={selectedItem} onClose={() => setSelectedItem(null)} marketRegime={marketRegime} />}
      {/* 운용 일지 모달 */}
      {showJournal && <JournalModal onClose={() => setShowJournal(false)} />}

      {/* 헤더 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">시장 홈</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
            <span>{marketChoiceLabel}: <span className="text-slate-300">{selectedMarket === "kr" ? "국장" : "미장"}</span></span>
            <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
              sessionPhase === "장중" ? "bg-emerald-900/50 text-emerald-300"
              : sessionPhase === "장마감" ? "bg-blue-900/50 text-blue-300"
              : sessionPhase === "휴장" ? "bg-slate-800 text-slate-400"
              : "bg-slate-800 text-slate-400"
            }`}>{sessionStatus}</span>
            {countdown && <span className="flex items-center gap-1 text-slate-400"><Clock size={11} />{countdown}</span>}
          </div>
        </div>
        <div className="grid w-full grid-cols-5 gap-1.5 sm:w-auto sm:grid-cols-none sm:flex sm:flex-wrap sm:justify-end">
          {(["auto", "kr", "us"] as MarketChoice[]).map((choice) => (
            <button key={choice} onClick={() => updateMarketChoice(choice)}
              className={`min-w-0 rounded-lg px-2 py-1.5 text-xs font-semibold sm:px-2.5 ${marketChoice === choice ? "bg-blue-600 text-white" : "border border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}>
              {choice === "auto" ? "자동" : choice === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button onClick={() => setShowJournal(true)} className="min-w-0 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800 sm:px-2.5">
            일지
          </button>
          <button onClick={() => load()} title="새로고침" className="flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800">
            <RefreshCw size={13} className={loading || refreshing ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {(refreshWarning || bootStatus === "degraded") && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {refreshWarning || "일부 초기 데이터를 불러오지 못해 사용 가능한 캐시와 기본 화면을 먼저 표시합니다."}
        </div>
      )}

      {/* 마켓 레짐 배너 */}
      {marketRegime && (
        <div className={`flex items-center gap-2.5 rounded-xl border px-3 py-2 text-xs ${
          marketRegime.regime === "BULL"
            ? "border-emerald-500/25 bg-emerald-500/8"
            : marketRegime.regime === "BEAR"
              ? "border-red-500/25 bg-red-500/8"
              : "border-amber-500/25 bg-amber-500/8"
        }`}>
          <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full font-bold ${
            marketRegime.regime === "BULL" ? "bg-emerald-500/20 text-emerald-300"
            : marketRegime.regime === "BEAR" ? "bg-red-500/20 text-red-300"
            : "bg-amber-500/20 text-amber-300"
          }`}>
            {marketRegime.regime === "BULL" ? "↑" : marketRegime.regime === "BEAR" ? "↓" : "→"}
          </span>
          <span className={`font-semibold ${
            marketRegime.regime === "BULL" ? "text-emerald-300"
            : marketRegime.regime === "BEAR" ? "text-red-300"
            : "text-amber-300"
          }`}>
            {marketRegime.regime === "BULL" ? "강세장" : marketRegime.regime === "BEAR" ? "약세장" : "중립장"}
          </span>
          <span className="text-slate-500">{marketRegime.benchmark}</span>
          {marketRegime.distanceMa20Pct != null && (
            <span className={`font-mono ${Number(marketRegime.distanceMa20Pct) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              20MA {Number(marketRegime.distanceMa20Pct) >= 0 ? "+" : ""}{Number(marketRegime.distanceMa20Pct).toFixed(1)}%
            </span>
          )}
          {marketRegime.regime === "BEAR" && (
            <span className="ml-auto font-medium text-red-300">진입 기준 강화 적용 중</span>
          )}
        </div>
      )}

      {/* 공포·탐욕 지수 */}
      <FearGreedWidget market={selectedMarket} />

      {!loading && (
        <TodayConclusionCard
          regime={marketRegime}
          dataHealth={dataHealth}
          todayCount={todayEntries.length}
          watchCount={watchItems.length}
          riskCount={riskCount}
        />
      )}

      {!loading && dashboardAlerts.length > 0 && (() => {
        const first = dashboardAlerts[0];
        const summary = dashboardAlerts.length > 1
          ? `${first.title.replace(/[.。]$/, "")} 외 ${dashboardAlerts.length - 1}개 알림`
          : first.title;
        const visibleAlerts = alertsExpanded ? dashboardAlerts : dashboardAlerts.slice(0, 1);
        return (
          <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="text-sm font-bold text-amber-100">MONE 알림 {dashboardAlerts.length}개</div>
                <div className="mt-0.5 text-xs text-amber-100/80">{summary}</div>
              </div>
              <button
                type="button"
                onClick={() => setAlertsExpanded((value) => !value)}
                className="shrink-0 rounded-lg border border-amber-400/30 bg-slate-950/40 px-3 py-1.5 text-xs font-semibold text-amber-100 hover:bg-slate-950/70"
              >
                {alertsExpanded ? "접기" : "알림 보기"}
              </button>
            </div>
            {alertsExpanded && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {visibleAlerts.map((alert) => (
                  <div key={alert.key} className={`rounded-xl border px-3 py-2 text-xs ${
                    alert.tone === "red"
                      ? "border-red-500/30 bg-red-500/10 text-red-100"
                      : alert.tone === "emerald"
                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
                        : "border-amber-500/30 bg-slate-950/30 text-amber-100"
                  }`}>
                    <div className="font-semibold">{alert.title}</div>
                    <div className="mt-0.5 text-[11px] opacity-75">{alert.detail}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      {/* 매크로/실적 이벤트 배너 */}
      <EventBanner alert={calendarAlert} />

      {/* 손절/목표가 근접 알림 패널 */}
      {nearAlerts.length > 0 && (
        <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-3 space-y-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 px-0.5">가격 근접 알림</div>
          {nearAlerts.map((alert: any) => {
            const isStop = alert.type === "STOP";
            const gapSign = isStop ? "-" : "+";
            const currentFmt = Number(alert.currentPrice ?? 0).toLocaleString("ko-KR");
            const priceFmt = isStop
              ? Number(alert.stopPrice ?? 0).toLocaleString("ko-KR")
              : Number(alert.targetPrice ?? 0).toLocaleString("ko-KR");
            const priceLabel = isStop ? "손절" : "목표";
            const gapPct = Number(alert.gapPct ?? 0).toFixed(1);
            return (
              <div
                key={`${alert.symbol}-${alert.type}`}
                className={`flex items-center justify-between gap-3 rounded-xl border px-3 py-2 text-[11px] ${
                  isStop
                    ? "border-red-700/40 bg-red-950/20 text-red-200"
                    : "border-emerald-700/40 bg-emerald-950/20 text-emerald-200"
                }`}
              >
                <span className="font-semibold truncate min-w-0">{alert.name || alert.symbol}</span>
                <span className="shrink-0 text-[10px] opacity-80 [font-variant-numeric:tabular-nums]">
                  {priceLabel}가 근접 (현재 {currentFmt} / {priceLabel} {priceFmt}, {gapSign}{gapPct}%)
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* 데이터 신선도 배지 */}
      {dataSources && (() => {
        const freshness = dataSources.recommendationFreshness as Record<string, { ageHours: number; fresh: boolean }> | undefined;
        if (!freshness) return null;
        const ages = Object.values(freshness).map((v) => v.ageHours);
        if (!ages.length) return null;
        const maxAge = Math.max(...ages);
        const allFresh = ages.every((a) => a < 6);
        const anyStale = ages.some((a) => a >= 24);
        const dot = allFresh ? "bg-emerald-400" : anyStale ? "bg-red-400" : "bg-yellow-400";
        const label = allFresh ? "신선" : anyStale ? "오래됨" : "보통";
        const textClass = allFresh ? "text-emerald-300" : anyStale ? "text-red-300" : "text-yellow-300";
        const src = dataSources.sources?.local_collector ? "로컬 수집기" : dataSources.sources?.github_actions ? "GitHub Actions" : null;
        return (
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 ${anyStale ? "border-red-800/50 bg-red-950/30" : allFresh ? "border-emerald-800/50 bg-emerald-950/20" : "border-yellow-800/50 bg-yellow-950/20"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
              <span className={textClass}>데이터 {label}</span>
              <span className="text-slate-500">({maxAge.toFixed(0)}h 전)</span>
            </span>
            {src && <span className="text-slate-600">{src}</span>}
          </div>
        );
      })()}

      {marketRegime && (
        <MarketRegimeSummaryCard
          regime={marketRegime}
          selectedMarket={selectedMarket}
          expanded={marketDetailExpanded}
          onToggle={() => setMarketDetailExpanded((value) => !value)}
        />
      )}

      {/* 데이터 상태 카드 */}
      {!loading && (() => {
        if (!dataHealth) return null;
        const recoAt = dataHealth.recoGeneratedAt ? new Date(dataHealth.recoGeneratedAt) : null;
        const hoursOld = recoAt ? (Date.now() - recoAt.getTime()) / 3600000 : null;
        const isStale = hoursOld != null && hoursOld > 24;
        const isError = (dataHealth.kisLiveCount ?? 0) === 0 && (dataHealth.ohlcvCount ?? 0) === 0;
        const liveRatio = dataHealth.kisTargetCount > 0 ? (dataHealth.kisLiveCount ?? 0) / dataHealth.kisTargetCount : 1;
        const hasOhlcv = (dataHealth.ohlcvCount ?? 0) > 0;
        const priceStatus = liveRatio >= 0.5 ? "NORMAL" : liveRatio >= 0.1 ? "PARTIAL" : "ERROR";

        return (
          <div className={`rounded-xl border px-4 py-3 text-[11px] ${
            isError ? "border-red-800/60 bg-red-950/20"
            : isStale ? "border-amber-800/40 bg-amber-950/15"
            : "border-slate-800 bg-slate-900/40"
          }`}>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
              {/* 가격 데이터 상태 */}
              <span className="flex items-center gap-1.5">
                <span className={`h-1.5 w-1.5 rounded-full ${priceStatus === "NORMAL" ? "bg-emerald-400" : priceStatus === "PARTIAL" ? "bg-amber-400" : "bg-red-400"}`} />
                <span className="text-slate-500">실시간 가격</span>
                <span className={`font-mono font-medium ${priceStatus === "NORMAL" ? "text-slate-200" : priceStatus === "PARTIAL" ? "text-amber-300" : "text-red-300"}`}>
                  {dataHealth.kisLiveCount ?? 0}<span className="text-slate-600">/{dataHealth.kisTargetCount ?? 0}종목</span>
                </span>
                {priceStatus === "PARTIAL" && <span className="text-amber-500">부분 수집</span>}
                {priceStatus === "ERROR" && <span className={hasOhlcv ? "text-amber-400" : "text-red-400"}>{hasOhlcv ? "실시간 미수집 · 종가 기준" : "장외/KIS 미수집"}</span>}
              </span>

              {/* OHLCV 상태 */}
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                <span className="text-slate-500">차트 데이터</span>
                <span className="font-mono text-slate-200">{dataHealth.ohlcvCount ?? 0}종목</span>
                {dataHealth.ohlcvLatestDate && <span className="text-slate-500">· {dataHealth.ohlcvLatestDate}</span>}
              </span>

              {/* 데이터 기준 시각 */}
              {recoAt && (
                <span className="flex items-center gap-1.5">
                  <span className={`h-1.5 w-1.5 rounded-full ${isStale ? "bg-amber-400" : "bg-violet-400"}`} />
                  <span className="text-slate-500">데이터 기준</span>
                  <span className={`font-mono ${isStale ? "text-amber-300" : "text-slate-300"}`}>
                    {String(dataHealth.recoGeneratedAt).slice(0, 16).replace("T", " ")}
                  </span>
                  {isStale && <span className="text-amber-400">({Math.floor(hoursOld!)}h 전)</span>}
                </span>
              )}

              {/* 스캔 범위 + 경고 */}
              <div className="ml-auto flex items-center gap-2">
                {isError && <span className="rounded-full border border-red-700/60 bg-red-900/30 px-2 py-0.5 text-[10px] font-medium text-red-300">데이터 오류</span>}
                {isStale && !isError && <span className="rounded-full border border-amber-700/40 bg-amber-900/20 px-2 py-0.5 text-[10px] font-medium text-amber-300">데이터 오래됨</span>}
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${dataHealth.scanScope === "FULL_MARKET_READY" ? "bg-emerald-900/40 text-emerald-400" : "bg-slate-800 text-slate-400"}`}>
                  {dataHealth.scanScope === "FULL_MARKET_READY" ? "전종목" : "선별 유니버스"}
                </span>
              </div>
            </div>
          </div>
        );
      })()}

      {basisWarning && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-100 shadow-[0_10px_30px_rgba(0,0,0,0.12)]">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 font-semibold text-amber-200">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>기준일이 혼합되어 있습니다</span>
              </div>
              <p className="mt-1 text-amber-100/80">
                추천·현재가·차트/OHLCV 기준일이 서로 달라 장중에는 일부 판단이 전일 종가 기준으로 보일 수 있습니다.
              </p>
            </div>
            <div className="grid shrink-0 grid-cols-3 gap-1.5 font-mono text-[11px] tabular-nums sm:min-w-[310px]">
              <span className="rounded-lg border border-amber-400/20 bg-slate-950/40 px-2 py-1 text-center">추천 {basisWarning.recommendation || "-"}</span>
              <span className="rounded-lg border border-amber-400/20 bg-slate-950/40 px-2 py-1 text-center">현재가 {basisWarning.current || "-"}</span>
              <span className="rounded-lg border border-amber-400/20 bg-slate-950/40 px-2 py-1 text-center">OHLCV {basisWarning.ohlcv || "-"}</span>
            </div>
          </div>
        </div>
      )}

      {/* 오늘 운용 요약 — 접힘 가능 */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/40">
        <button
          type="button"
          className="flex w-full items-center justify-between px-4 py-3 text-left"
          onClick={() => setShowDigest((v) => !v)}
        >
          <span className="text-xs font-semibold text-slate-400">오늘 운용 요약</span>
          <span className="text-[10px] text-slate-600">{showDigest ? "▲ 닫기" : "▼ 펼치기"}</span>
        </button>
        {showDigest && (
          <div className="border-t border-slate-800 px-4 pb-4 pt-3">
            <ReportDigestCard digest={reportDigest} loading={reportLoading && !reportDigest} />
          </div>
        )}
      </div>

      {/* ━━ 오늘 진입 후보 ━━ */}
      <section className="rounded-2xl border border-emerald-900/50 bg-emerald-950/10 p-5">
        <div className="mb-4 flex items-center gap-2">
          <TrendingUp size={18} className="text-emerald-400" />
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-slate-100">
              {sessionPhase === "장중" ? "기준가 근접 종목" : "검토 후보"}
            </h2>
            <p className="text-xs text-slate-500">
              {sessionCtx.hint || "진입 구간 + EV 양수 + 추세 조건을 동시에 충족한 종목입니다."}
            </p>
          </div>
          <span className="shrink-0 rounded-full border border-emerald-800/50 bg-emerald-900/30 px-3 py-1 text-xs text-emerald-400">
            {loading ? "..." : `${todayEntries.length}개`}
          </span>
          {onNavigate && (
            <button onClick={() => onNavigate("stocks")} className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">
              종목 탐색 <ArrowRight size={12} />
            </button>
          )}
        </div>
        {loading ? (
          <div className="py-8 text-center text-slate-500">데이터 확인 중...</div>
        ) : todayEntries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 py-6 text-center text-sm">
            <p className="text-slate-500">
              {marketRegime?.regime === "BEAR" ? "약세장 — 진입 기준 상향 적용 중" : "현재 즉시 진입 후보가 없습니다."}
            </p>
            <p className="mt-2 text-[11px] text-slate-600">
              {allItems.length === 0 ? "오늘 추천 데이터가 아직 없습니다. 오전 데이터 갱신 후 다시 확인해 주세요." : `현재 조건에 맞는 진입 후보가 없습니다. 전략 매트릭스에 ${allItems.length}개 종목이 있으나 EV 양수 + 진입 조건을 충족하지 않습니다.`}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {todayEntries.map((item, i) => (
              <TodayEntryCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} rank={i + 1} onAnalyze={openAnalysis} earningsMap={earningsMap} />
            ))}
          </div>
        )}
      </section>

      {/* ━━ 대기 관찰 후보 ━━ */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Eye size={18} className="text-amber-400" />
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-slate-100">대기 관찰 후보</h2>
            <p className="text-xs text-slate-500">지금은 기다리고, 눌림 후 다시 볼 후보입니다.</p>
          </div>
          <span className="shrink-0 rounded-full border border-amber-800/50 bg-amber-900/20 px-3 py-1 text-xs text-amber-400">
            {loading ? "..." : `${watchItems.length}개`}
          </span>
          {onNavigate && (
            <button onClick={() => onNavigate("stocks")} className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">
              종목 탐색 <ArrowRight size={12} />
            </button>
          )}
        </div>
        {loading ? (
          <div className="py-6 text-center text-slate-500">데이터 확인 중...</div>
        ) : watchItems.length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-500">대기 관찰 종목이 없습니다.</div>
        ) : (
          <div className="space-y-2">
            {watchItems.map((item) => (
              <WatchCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} onSelect={setSelectedItem} />
            ))}
          </div>
        )}
      </section>

      {/* ━━ 3×3 전략 매트릭스 (상세 비교) ━━ */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <button
          className="flex w-full items-center justify-between text-left"
          onClick={() => setShowMatrix((v) => !v)}
        >
          <div>
            <h2 className="text-base font-semibold text-slate-100">전략 × 기간 매트릭스</h2>
            <p className="text-xs text-slate-500">보수·균형·공격 × 단기·스윙·중기 9개 조합 전체 비교</p>
          </div>
          <span className="ml-4 shrink-0 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-400 hover:bg-slate-800">
            {showMatrix ? "접기 ▲" : "펼치기 ▼"}
          </span>
        </button>

        {showMatrix && (
          <div className="mt-4">
            {/* 헤더 행 */}
            <div className="mb-2 hidden grid-cols-[100px_repeat(3,1fr)] gap-2 xl:grid">
              <div />
              {HORIZONS.map((h) => (
                <div key={h} className="rounded-xl bg-slate-950/60 py-2 text-center text-xs font-semibold text-slate-400">{horizonLabel(h)}</div>
              ))}
            </div>

            {loading ? (
              <div className="space-y-2">
                {MODES.map((mode) => (
                  <div key={mode} className="grid grid-cols-1 gap-2 xl:grid-cols-[100px_repeat(3,1fr)]">
                    <div className="flex items-center justify-center rounded-2xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs font-semibold text-slate-600">{modeLabel(mode)}</div>
                    {HORIZONS.map((horizon) => (
                      <div key={horizon} className="animate-pulse rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
                        <div className="h-3 w-16 rounded bg-slate-800" />
                        <div className="mt-2 h-5 w-10 rounded bg-slate-800" />
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {MODES.map((mode) => (
                  <div key={mode} className="grid grid-cols-1 gap-2 xl:grid-cols-[100px_repeat(3,1fr)]">
                    <div className="flex items-center justify-center rounded-2xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs font-semibold text-slate-300">
                      {modeLabel(mode)}
                    </div>
                    {HORIZONS.map((horizon) => {
                      const cell = matrix.find((c) => c.mode === mode && c.horizon === horizon) || { mode, horizon, items: [], count: 0, status: "NO_DATA" };
                      return <MatrixCell key={`${mode}-${horizon}`} cell={cell as StrategyCell} onSelect={setSelectedItem} />;
                    })}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* ━━ 온보딩 패널 (보유종목 없을 때) ━━ */}
      {false && !loading && holdings.length === 0 && (
        <OnboardingPanel onNavigate={onNavigate} />
      )}

      {/* ━━ 보유종목 요약 ━━ */}
      {false && holdings.length > 0 && (
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="mb-3 flex items-center gap-2">
            {riskCount > 0 && <AlertTriangle size={16} className="text-red-400" />}
            <h2 className="text-base font-semibold text-slate-100">보유종목</h2>
            {summary?.totalPnl != null && (
              <span className={`ml-1 font-mono text-sm font-bold ${Number(summary.totalPnl) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {summary.totalPnlText ?? (Number(summary.totalPnl) >= 0 ? "+" : "") + Number(summary.totalPnl).toLocaleString("ko-KR") + "원"}
              </span>
            )}
            <span className="ml-auto text-xs text-slate-500">{holdings.length}개{riskCount > 0 && ` · 위험/주의 ${riskCount}개`}</span>
            {onNavigate && (
              <button onClick={() => onNavigate("holdings")} className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">
                {holdings.length > 6 ? "전체 보기" : "상세"} <ArrowRight size={12} />
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {holdings.slice(0, 6).map((item) => {
              const change = firstText(item.changePctText, "");
              const down = String(change).startsWith("-");
              const isRisk = ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""));
              const judgment = getHoldingJudgment(item);
              return (
                <div key={`${item.market}-${item.symbol}`} className={`rounded-xl border p-3 ${isRisk ? "border-red-800/40 bg-red-950/10" : "border-slate-800 bg-slate-950/50"}`}>
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-200">{displayName(item)}</div>
                      <div className="text-[11px] text-slate-500">{item.symbol} · {probabilityText(item, "-")}</div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className={`font-mono text-sm ${String(item.pnlText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"}`}>
                        {firstText(item.pnlText, "0")}
                      </div>
                      {change && <div className={`font-mono text-[11px] ${down ? "text-red-400" : "text-emerald-400"}`}>{change}</div>}
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${judgment.cls}`}>
                      {judgment.text}
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); const k = `${item.market}-${item.symbol}`; setEditStory(k); setStoryForm(storyMap[k] || { why: "", invalidation: "", reviewDate: "" }); }}
                      className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800"
                    >
                      {storyMap[`${item.market}-${item.symbol}`] ? "스토리 수정" : "+ 스토리"}
                    </button>
                  </div>
                  {editStory === `${item.market}-${item.symbol}` && (
                    <div className="mt-2 space-y-2 rounded-xl border border-slate-700 bg-slate-900/60 p-3 text-[11px]">
                      <input
                        placeholder="왜 샀는지 (진입 근거)"
                        value={storyForm.why}
                        onChange={(e) => setStoryForm((f) => ({ ...f, why: e.target.value }))}
                        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                      />
                      <input
                        placeholder="무효화 조건 (이 가격 깨지면 틀린 것)"
                        value={storyForm.invalidation}
                        onChange={(e) => setStoryForm((f) => ({ ...f, invalidation: e.target.value }))}
                        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500"
                      />
                      <input
                        type="date"
                        value={storyForm.reviewDate}
                        onChange={(e) => setStoryForm((f) => ({ ...f, reviewDate: e.target.value }))}
                        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-slate-100 focus:outline-none focus:border-blue-500"
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => {
                            const k = `${item.market}-${item.symbol}`;
                            const updated = { ...storyMap, [k]: storyForm };
                            setStoryMap(updated);
                            window.localStorage.setItem("mone:stories", JSON.stringify(updated));
                            setEditStory(null);
                          }}
                          className="rounded-lg bg-blue-600 px-3 py-1 text-[11px] font-semibold text-white hover:bg-blue-500"
                        >저장</button>
                        <button onClick={() => setEditStory(null)} className="rounded-lg bg-slate-800 px-3 py-1 text-[11px] text-slate-400">취소</button>
                      </div>
                      {storyMap[`${item.market}-${item.symbol}`] && (
                        <div className="border-t border-slate-700 pt-2 text-slate-400">
                          <div>근거: {storyMap[`${item.market}-${item.symbol}`].why || "—"}</div>
                          <div>무효화: {storyMap[`${item.market}-${item.symbol}`].invalidation || "—"}</div>
                          {storyMap[`${item.market}-${item.symbol}`].reviewDate && (
                            <div>재점검: {storyMap[`${item.market}-${item.symbol}`].reviewDate}</div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {holdings.length > 6 && onNavigate && (
            <button onClick={() => onNavigate("holdings")} className="mt-3 w-full rounded-xl border border-slate-700 py-2 text-xs text-slate-400 hover:bg-slate-800">
              나머지 {holdings.length - 6}개 보유종목 →
            </button>
          )}
        </section>
      )}
    </div>
    </ErrorBoundary>
  );
}
