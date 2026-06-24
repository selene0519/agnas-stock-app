"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Download, FileText, Link2, Pencil, Plus, RefreshCw, Save, Trash2, X, Zap } from "lucide-react";
import CashInputBar from "../CashInputBar";
import PortfolioOptimizePanel from "../PortfolioOptimizePanel";
import AlertsPanel from "../AlertsPanel";
import { mone } from "@/lib/api";
import { dataFreshnessBadgeClass, dataFreshnessInfo } from "@/lib/moneDisplay";
import { getUserId, getUserProfile, getUserToken } from "@/lib/userId";
import type { BootPreloadData } from "@/lib/bootPreload";

type Market = "all" | "kr" | "us";
const HOLDINGS_API_TIMEOUT_MS = 90000;

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
    const id = getUserId();
    return id ? { "x-mone-user": id } : {};
  } catch { return {}; }
}

const LS_HOLDINGS_KEY = "mone:personal_holdings_v2";

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

function displayName(item: any) {
  const name = String(item.name || item.company || "").trim();
  const sym = String(item.symbol || "").toUpperCase();
  return name && name !== sym ? name : sym;
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
function riskBadgeClass(risk: string) {
  if (risk === "HIGH") return "border-red-500/40 bg-red-500/15 text-red-300";
  if (risk === "WATCH") return "border-amber-500/40 bg-amber-500/15 text-amber-300";
  return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
}
function riskLabel(risk: string) {
  if (risk === "HIGH") return "위험";
  if (risk === "WATCH") return "주의";
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
    ctx.strokeStyle = "#334155"; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
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
            ctx.strokeStyle = "#64748b80"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
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
    ctx.fillStyle = "#475569"; ctx.font = "10px monospace";
    ctx.textAlign = "left";
    const firstDate = navRows[0]?.date ?? "";
    const lastDate = navRows.at(-1)?.date ?? "";
    if (firstDate) ctx.fillText(firstDate, pad.l, H - 4);
    if (lastDate) { ctx.textAlign = "right"; ctx.fillText(lastDate, W - pad.r, H - 4); }
  }, [navRows, kospiRows]);

  if (loginRequired) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 px-5 py-4">
        <div className="text-sm font-semibold text-slate-200">NAV 누적 수익률</div>
        <p className="mt-1.5 text-xs text-slate-500">로그인 후 본인 포트폴리오 추이를 확인할 수 있습니다.</p>
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
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50">
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
        <ChevronDown size={16} className={`shrink-0 text-slate-500 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      <div className={open ? "border-t border-slate-800 px-5 pb-5 pt-4" : "hidden"}>
        <div className="mb-3 flex items-center gap-2 text-[10px] text-slate-500">
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
    return { items: withValue, total };
  }, [items]);

  if (sorted.total <= 0) return null;
  const colors = ["bg-blue-500","bg-emerald-500","bg-violet-500","bg-amber-500","bg-cyan-500","bg-rose-500","bg-teal-500","bg-orange-500"];

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">포트폴리오 구성 (개별주)</h2>
      <div className="flex h-4 w-full overflow-hidden rounded-full">
        {sorted.items.map((item, i) => {
          const pct = (item._val / sorted.total) * 100;
          return (
            <div key={`${item.market}-${item.symbol}`}
              className={`${colors[i % colors.length]} transition-[width] duration-300`}
              style={{ width: `${pct}%` }}
              title={`${displayName(item)} ${pct.toFixed(1)}%`} />
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {sorted.items.map((item, i) => {
          const pct = (item._val / sorted.total) * 100;
          return (
            <div key={`${item.market}-${item.symbol}`} className="flex items-center gap-1.5">
              <div className={`h-2 w-2 shrink-0 rounded-full ${colors[i % colors.length]}`} />
              <span className="text-[11px] text-slate-300">{displayName(item)}</span>
              <span className="font-mono text-[11px] text-slate-500">{pct.toFixed(1)}%</span>
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
      <p className="mt-2 text-[11px] text-slate-500">손절가·목표가는 선택 입력입니다. 비워 두면 현재가만 저장됩니다.</p>
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
  const _bootHoldings = (() => {
    const bc = bootData?.holdingsCache;
    if (bc && Array.isArray(bc.items) && bc.items.length > 0) return bc;
    return readHoldingsCache("all")?.data ?? null;
  })();

  const [market, setMarket] = useState<Market>("all");
  const [holdingsViewTab, setHoldingsViewTab] = useState<"all" | "stock" | "etf">("all");
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
  const [corrData, setCorrData] = useState<any>(null);
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
  const [brokerConnections, setBrokerConnections] = useState<BrokerStatus[]>([]);
  const items = useMemo(() => dedupe(Array.isArray(data.items) ? data.items : []), [data.items]);

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
      if (serverItems.length === 0 && localItems.length > 0) {
        finalData = localHoldingsPayload(localItems, market);
        setData(finalData);
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
        if (res?.status) setRiskBudget(res);
      }).catch(() => setRiskBudget(null));
      if (market === "all") {
        setSectorData(null);
        setBenchmarkData(null);
        setCorrData(null);
        setRiskNote("전체 보기에서는 KR/US 통화와 벤치마크가 달라 리스크 패널을 합산하지 않습니다. 국장 또는 미장 탭에서 개별 리스크를 확인하세요.");
        return;
      }
      setRiskNote("");
      // 리스크 데이터는 백그라운드 로딩
      Promise.all([
        getJson(`/api/risk/sector-exposure?market=${market}`).catch((error) => ({ status: "ERROR", error: String(error), sectors: [] })),
        getJson(`/api/risk/benchmark?market=${market}`).catch((error) => ({ status: "ERROR", error: String(error), items: [] })),
        getJson(`/api/risk/correlation?market=${market}&days=60`).catch((error) => ({ status: "ERROR", error: String(error), matrix: [] })),
      ]).then(([sector, bench, corr]) => {
        setSectorData(sector); setBenchmarkData(bench); setCorrData(corr);
      });
    } catch (error) {
      const localItems = loadHoldingsFromLocalStorage();
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
  }, [market]);

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
    try {
      const result = await getJson("/api/holdings-edit?market=all");
      return Array.isArray(result.items) ? mergeEditableRows(result.items.map(toEditableHolding)) : [];
    } catch {
      return loadHoldingsFromLocalStorage().map(toEditableHolding);
    }
  }

  async function saveRows(nextRows: any[], successMsg: string) {
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
  const holdingFreshness = dataFreshnessInfo({
    latestDataDate: summary.latestDataDate || summary.ohlcvLatestDate || items[0]?.latestDataDate || items[0]?.priceDate || items[0]?.date,
    recoGeneratedAt: summary.updatedAt || data.updatedAt || holdingsLoadedAt,
    dataStatus: data.status,
  });
  const riskCount = Number(summary.riskCount ?? items.filter((item) => ["HIGH","WATCH"].includes(String(item.riskStatus || ""))).length);
  const totalValueText = summary.totalValueText || (items.length > 0 ?
    items.reduce((acc: number, item: any) => acc + Number(item.valuation || item.marketValue || 0), 0).toLocaleString("ko-KR") + "원" : "-");

  const { individualStocks, etfHoldings } = useMemo(() => {
    const stocks: any[] = [];
    const etfs: any[] = [];

    for (const item of items) {
      const assetType = String(item.assetType || item.instrumentType || "stock").toLowerCase();
      const isEtf = assetType.includes("etf");
      if (isEtf) {
        etfs.push(item);
      } else {
        stocks.push(item);
      }
    }

    stocks.sort((a, b) => {
      const riskA = String(a.riskStatus || "").toUpperCase();
      const riskB = String(b.riskStatus || "").toUpperCase();
      const stopGapA = a.downsideGapPct != null ? Number(a.downsideGapPct) : a.stopGapPct != null ? Number(a.stopGapPct) : null;
      const stopGapB = b.downsideGapPct != null ? Number(b.downsideGapPct) : b.stopGapPct != null ? Number(b.stopGapPct) : null;
      const hasPriceA = a.currentPrice && Number(a.currentPrice) > 0;
      const hasPriceB = b.currentPrice && Number(b.currentPrice) > 0;
      const hasStopA = (a.downsideLine ?? a.stopPrice ?? a.stop ?? 0) > 0;
      const hasStopB = (b.downsideLine ?? b.stopPrice ?? b.stop ?? 0) > 0;
      const hasTargetA = (a.upsideLine ?? a.targetPrice ?? a.target ?? 0) > 0;
      const hasTargetB = (b.upsideLine ?? b.targetPrice ?? b.target ?? 0) > 0;
      const totalValueA = Number(a.valuation || a.marketValue || 0);
      const totalValueB = Number(b.valuation || b.marketValue || 0);
      const portTotalValue = items.reduce((s, x) => s + Number(x.valuation || x.marketValue || 0), 0);
      const weightA = portTotalValue > 0 ? totalValueA / portTotalValue : 0;
      const weightB = portTotalValue > 0 ? totalValueB / portTotalValue : 0;

      const getRiskScore = (risk: string, stopGap: number | null, hasPrice: boolean, hasStop: boolean, hasTarget: boolean, weight: number) => {
        let score = 0;
        if (risk === "HIGH") score += 1000;
        else if (risk === "WATCH") score += 500;

        if (stopGap !== null && stopGap <= 2) score += 400;
        else if (stopGap !== null && stopGap <= 5) score += 200;

        if (!hasPrice) score += 300;
        if (!hasStop) score += 150;
        if (!hasTarget) score += 100;
        if (weight > 0.2) score += 50;

        return score;
      };

      const scoreA = getRiskScore(riskA, stopGapA, hasPriceA, hasStopA, hasTargetA, weightA);
      const scoreB = getRiskScore(riskB, stopGapB, hasPriceB, hasStopB, hasTargetB, weightB);

      return scoreB - scoreA;
    });

    etfs.sort((a, b) => {
      const totalValueA = Number(a.valuation || a.marketValue || 0);
      const totalValueB = Number(b.valuation || b.marketValue || 0);
      return totalValueB - totalValueA;
    });

    return { individualStocks: stocks, etfHoldings: etfs };
  }, [items]);
  const actionItems = useMemo(() => {
    const rows: { key: string; tone: "red" | "amber" | "blue"; title: string; detail: string; action?: "stop" | "target" }[] = [];
    for (const holding of items) {
      const name = displayName(holding);
      const symbol = String(holding.symbol || "");
      const assetType = String(holding.assetType || holding.instrumentType || "stock");
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
        rows.push({ key: `${symbol}-price`, tone: "amber", title: `${name} 현재가 없음`, detail: "수동 갱신 또는 다음 수집 필요" });
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

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-[19px] font-black leading-none text-slate-100">보유·리스크</h1>
          <p className="mt-1 text-sm text-slate-400">보유종목 현황, 리스크 지표, 포트폴리오 구성 분석</p>
        </div>
        <div className="grid w-full grid-cols-3 gap-2 sm:w-auto">
          <button onClick={() => onNavigate?.("broker")}
            className="inline-flex min-h-12 items-center justify-center gap-1.5 rounded-xl border border-sky-500/30 bg-sky-500/10 px-2 py-2 text-xs font-semibold text-sky-200 hover:bg-sky-500/20 sm:text-sm">
            <Link2 size={14} /> 토스증권 연결
          </button>
          <button onClick={() => onNavigate?.("broker")}
            className="inline-flex min-h-12 items-center justify-center gap-1.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-2 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-500/20 sm:text-sm">
            <Download size={14} /> 한국투자 연결
          </button>
          <button onClick={() => { setShowAdd(!showAdd); setShowImport(false); setMessage(""); }}
            className="mone-primary-action inline-flex min-h-12 items-center justify-center gap-1.5 rounded-xl px-2 py-2 text-xs font-semibold transition-[background-color,box-shadow,transform] active:scale-[0.96] sm:text-sm">
            <Plus size={14} /> 직접 추가
          </button>
        </div>
      </div>

      {/* 마켓 필터 */}
      <div className="flex gap-2">
        {(["all","kr","us"] as Market[]).map((item) => (
          <button key={item} onClick={() => setMarket(item)}
            className={`min-h-10 rounded-xl border px-4 py-2 text-sm font-medium transition-[background-color,border-color,color,transform] active:scale-[0.96] ${market === item ? "mone-selection-brand font-semibold" : "border-slate-800 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}>
            {item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}
          </button>
        ))}
      </div>

      {/* 가용 예수금 — 포지션 크기 계산 보조 */}
      <CashInputBar />

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-3 sm:p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">계좌 연동</h2>
            <p className="mt-0.5 text-xs text-slate-500">보유종목, 평가손익, 손절 기준, 위험 상태를 자동 점검합니다.</p>
          </div>
          <button
            type="button"
            onClick={() => onNavigate?.("broker")}
            className="shrink-0 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:bg-slate-800"
          >
            관리
          </button>
        </div>
        {!userToken ? (
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-3 text-xs text-slate-400">
            로그인 후 계좌 연동을 사용할 수 있습니다.
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              { broker: "toss", name: "토스증권", status: tossStatus, tone: "sky" },
              { broker: "kis", name: "한국투자", status: kisStatus, tone: "amber" },
            ].map(({ broker, name, status, tone }) => {
              const connected = Boolean(status?.connected);
              return (
                <div key={broker} className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-slate-100">{name}</div>
                      <div className={`mt-0.5 text-xs ${connected ? "text-emerald-300" : "text-slate-500"}`}>
                        {brokerStatusLabel(status)}
                        {connected && status?.accountNoHint ? ` · ${status.accountNoHint}` : ""}
                      </div>
                      {connected && brokerSyncText(status) && <div className="mt-0.5 text-[10px] text-slate-600">{brokerSyncText(status)}</div>}
                    </div>
                    {connected ? (
                      <button
                        type="button"
                        disabled={brokerSyncing === broker}
                        onClick={() => syncBrokerHoldings(broker)}
                        className="rounded-lg border border-slate-700 px-2.5 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                      >
                        {brokerSyncing === broker ? "확인 중" : "스냅샷 확인"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => onNavigate?.("broker")}
                        className={`rounded-lg border px-2.5 py-1 text-[11px] font-semibold ${
                          tone === "sky"
                            ? "border-sky-500/30 bg-sky-500/10 text-sky-200"
                            : "border-amber-500/30 bg-amber-500/10 text-amber-200"
                        }`}
                      >
                        연결하기
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

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
            ? "border-red-500/40 bg-red-500/10 text-red-200"
            : "border-slate-700 bg-slate-900 text-slate-300"
        }`}>
          <span>{message}</span>
          <button onClick={() => setMessage("")} className="ml-3 shrink-0 text-slate-500 hover:text-slate-300"><X size={14} /></button>
        </div>
      )}

      {/* 요약 카드 */}
      {loading ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-xl border border-slate-800 bg-slate-900 px-4 py-4">
              <div className="h-3 w-16 rounded bg-slate-700" />
              <div className="mt-2 h-6 w-24 rounded bg-slate-700" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <SummaryCard label="평가금액 합계" value={totalValueText} />
          <SummaryCard label="총 평가손익" value={summary.totalPnlText || "-"}
            accent={
              summary.mixedCurrency
                ? "text-slate-300"
                : Number(summary.totalPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"
            } />
          <SummaryCard label="보유 종목" value={`${items.length}개`} />
          <SummaryCard label="주의/위험" value={`${riskCount}개`}
            accent={riskCount > 0 ? "text-amber-300" : "text-emerald-300"} />
        </div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-xs text-slate-400">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-slate-200">보유종목 데이터</span>
          <span className={`rounded-full border px-2 py-0.5 ${dataFreshnessBadgeClass(holdingFreshness.state)}`}>
            {holdingFreshness.label}
          </span>
          <span>{holdingFreshness.basisText}</span>
          {holdingsLoadedAt && <span>현재가 갱신: {holdingsLoadedAt}</span>}
          <span className="flex-1" />
          <button onClick={() => load()}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-300 hover:bg-slate-800">
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> 새로고침
          </button>
          <button onClick={refreshVisibleQuotes} disabled={refreshingAllQuotes}
            className="inline-flex items-center gap-1 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-[11px] text-blue-200 hover:bg-blue-500/20 disabled:opacity-50">
            <Zap size={12} className={refreshingAllQuotes ? "animate-pulse" : ""} /> 현재가 갱신
          </button>
        </div>
      </div>

      {/* 개별주/ETF 보기 전환 */}
      {(individualStocks.length > 0 || etfHoldings.length > 0) && (
        <div className="inline-flex rounded-xl border border-slate-800 bg-slate-900/50 p-1">
          {([
            { key: "all", label: `전체 (${individualStocks.length + etfHoldings.length})` },
            { key: "stock", label: `개별주 (${individualStocks.length})` },
            { key: "etf", label: `ETF (${etfHoldings.length})` },
          ] as const).map((tab) => (
            <button key={tab.key} onClick={() => setHoldingsViewTab(tab.key)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                holdingsViewTab === tab.key ? "bg-emerald-600 text-white" : "text-slate-400 hover:text-slate-200"
              }`}>
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {/* 개별주 카드 */}
      {individualStocks.length > 0 && holdingsViewTab !== "etf" && (
        <div>
          <div className="mb-4 flex items-center gap-2">
            <h2 className="text-lg font-bold text-slate-100">개별주 ({individualStocks.length})</h2>
            <span className="text-xs text-slate-500">위험도·손절 근접 순 정렬</span>
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {individualStocks.map((holding: any) => {
          const key = editableKey(holding);
          const isEditing = editKey === key && !!editDraft;
          const assetType = String(holding.assetType || holding.instrumentType || "stock");
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
          const weightText = holding.weightText || holding.weightPctText || holding.portfolioWeightText || (holding.weightPct != null ? `${Number(holding.weightPct).toFixed(1)}%` : "-");
          const pnlText = `${holding.pnlText || "-"}${holding.pnlPctText && holding.pnlPctText !== "-" ? ` / ${holding.pnlPctText}` : ""}`;
          const holdingMarket = cleanHoldingMarket(holding.market);
          const downsideText = formatHoldingMoney(downsideValue, holdingMarket);
          const upsideText = formatHoldingMoney(upsideValue, holdingMarket);
          return (
            <div key={`${holding.market}-${holding.symbol}`} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3 sm:p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <h2 className="max-w-[8rem] break-keep text-base font-bold leading-snug text-slate-100 sm:max-w-none">{displayName(holding)}</h2>
                    <span className="font-mono text-xs text-slate-500">{holding.symbol}</span>
                    <span className="whitespace-nowrap rounded-md bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">{holding.market === "kr" ? "국장" : "미장"}</span>
                    <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-300">{holdingAssetLabel(assetType)}</span>
                    <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">{holdingPurposeLabel(holdingPurpose)}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-slate-500">{holdingBroker} · {String(holding.market || "").toUpperCase()}</div>
                  <div className="mt-0.5 flex flex-wrap gap-1 text-[10px] text-slate-600">
                    {(holding.currentPriceSource || holding.priceSource || holding.quoteSource) && <span>source: {holding.currentPriceSource || holding.priceSource || holding.quoteSource}</span>}
                    {(holding.priceDataStatus || holding.dataStatus) && <span>status: {(() => {
                      const s = String(holding.priceDataStatus || holding.dataStatus || "");
                      if (s === "LOCAL_ONLY") return "로컬 임시";
                      if (s === "DATA_PENDING") return "데이터 수집 대기";
                      if (s === "STALE") return "시세 갱신 필요";
                      if (s === "NORMAL" || s === "OK") return "정상";
                      return s;
                    })()}</span>}
                    {(holding.latestDataDate || holding.priceDate || holding.updatedAt) && <span>date: {holding.latestDataDate || holding.priceDate || String(holding.updatedAt).slice(0, 10)}</span>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(() => {
                      const status = String(holding.dataStatus || "");
                      const missing = Array.isArray(holding.missingFields) ? holding.missingFields : [];
                      if (status === "OK" || status === "NORMAL") return <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">현재가 정상</span>;
                      if (!holding.currentPrice || holding.currentPrice <= 0) return <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">현재가 없음</span>;
                      if (missing.length > 0) return <span className="rounded-md border border-slate-600/40 bg-slate-700/20 px-2 py-0.5 text-[10px] text-slate-400">OHLCV 기준가 ({missing.slice(0,2).join("·")} 없음)</span>;
                      return <span className="rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-300">부분 데이터</span>;
                    })()}
                    {holding.quoteSource && <span className="text-[10px] text-slate-600">출처: {holding.quoteSource}</span>}
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
                      SELL_STRONG: { cls: "border-red-500/60 bg-red-500/20 text-red-200", label: "매도강력" },
                      SELL:        { cls: "border-orange-500/60 bg-orange-500/20 text-orange-200", label: "매도검토" },
                      PARTIAL_EXIT:{ cls: "border-yellow-500/50 bg-yellow-500/15 text-yellow-200", label: "부분청산" },
                      MONITOR:     { cls: "border-blue-500/40 bg-blue-500/10 text-blue-300", label: "모니터링" },
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
                          <button onClick={() => setDeleteConfirmKey(null)}
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
                <Mini label="MONE 리스크" value={riskLabel(holding.riskStatus)} accent={String(holding.riskStatus) === "HIGH" ? "text-red-300" : String(holding.riskStatus) === "WATCH" ? "text-amber-300" : "text-emerald-300"} />
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
                <Mini label="현재가" value={holding.currentPriceText || "수집 대기"} />
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
                <p className="text-slate-500">보유 종목이 없습니다.</p>
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
          <div className="mb-4 flex items-center gap-2">
            <h2 className="text-lg font-bold text-slate-100">ETF 적립 ({etfHoldings.length})</h2>
            <span className="text-xs text-slate-500">평가금액 기준 정렬</span>
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {etfHoldings.map((holding: any) => {
              const key = editableKey(holding);
              const isEditing = editKey === key && !!editDraft;
              const assetType = String(holding.assetType || holding.instrumentType || "etf");
              const holdingPurpose = String(holding.holdingPurpose || holding.strategyType || "");
              const holdingBroker = brokerLabel(holding.broker || holding.sourceBroker || holding.sourceType || holding.priceSource);
              const holdingMarket = cleanHoldingMarket(holding.market);
              const weightText = holding.weightText || holding.weightPctText || holding.portfolioWeightText || (holding.weightPct != null ? `${Number(holding.weightPct).toFixed(1)}%` : "-");
              const pnlText = `${holding.pnlText || "-"}${holding.pnlPctText && holding.pnlPctText !== "-" ? ` / ${holding.pnlPctText}` : ""}`;
              const costBasis = Number(holding.avgPrice || 0) * Number(holding.quantity || 0);
              const currentValue = Number(holding.valuation || holding.marketValue || 0);
              const accumulationGapPct = costBasis > 0 ? ((currentValue - costBasis) / costBasis) * 100 : 0;

              return (
                <div key={`${holding.market}-${holding.symbol}`} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3 sm:p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <h2 className="max-w-[8rem] break-keep text-base font-bold leading-snug text-slate-100 sm:max-w-none">{displayName(holding)}</h2>
                        <span className="font-mono text-xs text-slate-500">{holding.symbol}</span>
                        <span className="whitespace-nowrap rounded-md bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">{holding.market === "kr" ? "국장" : "미장"}</span>
                        <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-300">{holdingAssetLabel(assetType)}</span>
                        <span className="whitespace-nowrap rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">{holdingPurposeLabel(holdingPurpose)}</span>
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500">{holdingBroker} · {String(holding.market || "").toUpperCase()}</div>
                      <div className="mt-0.5 flex flex-wrap gap-1 text-[10px] text-slate-600">
                        {(holding.currentPriceSource || holding.priceSource || holding.quoteSource) && <span>source: {holding.currentPriceSource || holding.priceSource || holding.quoteSource}</span>}
                        {(holding.priceDataStatus || holding.dataStatus) && <span>status: {(() => {
                          const s = String(holding.priceDataStatus || holding.dataStatus || "");
                          if (s === "LOCAL_ONLY") return "로컬 임시";
                          if (s === "DATA_PENDING") return "데이터 수집 대기";
                          if (s === "STALE") return "시세 갱신 필요";
                          if (s === "NORMAL" || s === "OK") return "정상";
                          return s;
                        })()}</span>}
                        {(holding.latestDataDate || holding.priceDate || holding.updatedAt) && <span>date: {holding.latestDataDate || holding.priceDate || String(holding.updatedAt).slice(0, 10)}</span>}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {(() => {
                          const status = String(holding.dataStatus || "");
                          const missing = Array.isArray(holding.missingFields) ? holding.missingFields : [];
                          if (status === "OK" || status === "NORMAL") return <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">현재가 정상</span>;
                          if (!holding.currentPrice || holding.currentPrice <= 0) return <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">현재가 없음</span>;
                          if (missing.length > 0) return <span className="rounded-md border border-slate-600/40 bg-slate-700/20 px-2 py-0.5 text-[10px] text-slate-400">OHLCV 기준가 ({missing.slice(0,2).join("·")} 없음)</span>;
                          return <span className="rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-300">부분 데이터</span>;
                        })()}
                        {holding.quoteSource && <span className="text-[10px] text-slate-600">출처: {holding.quoteSource}</span>}
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
                              <button onClick={() => setDeleteConfirmKey(null)}
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
                    <Mini label="현재가" value={holding.currentPriceText || "수집 대기"} />
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
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">보유 중인 개별주가 없습니다.</div>
      )}
      {holdingsViewTab === "etf" && etfHoldings.length === 0 && individualStocks.length > 0 && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">보유 중인 ETF가 없습니다.</div>
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
            <ChevronDown size={16} className={`shrink-0 text-slate-500 transition-transform duration-200 ${kellyOpen ? "rotate-180" : ""}`} />
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
                        <div className="text-slate-500">{horizonLabel}</div>
                        <div className="mt-1 font-mono font-bold text-slate-100">{hk}</div>
                        {entry.winRate != null && (
                          <div className="mt-0.5 text-[10px] text-slate-500">승률 {(entry.winRate * 100).toFixed(0)}%</div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
              <p className="mt-2 text-[10px] text-slate-500">Half-Kelly 상한 20% · VTJ 실적 기반 — 해당 전략으로 신규 진입 시 권장 비중입니다.</p>
            </div>
          )}
        </div>
      )}

      {riskBudget && (
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
            <ChevronDown size={16} className={`shrink-0 text-slate-500 transition-transform duration-200 ${riskBudgetOpen ? "rotate-180" : ""}`} />
          </button>
          {riskBudgetOpen && (
            <div className="border-t border-slate-800 px-5 pb-5 pt-4">
              <p className="mb-3 text-[11px] text-slate-500">손절가와 Kelly 한도 기준으로 과대 비중 종목을 표시합니다.</p>
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
              {(riskBudget.items || []).filter((item: any) => item.action === "REDUCE").length > 0 && (
                <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {(riskBudget.items || []).filter((item: any) => item.action === "REDUCE").slice(0, 6).map((item: any) => (
                    <div key={`${item.market}-${item.symbol}`} className="rounded-xl border border-red-500/20 bg-slate-950/60 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-slate-100">{item.name}</span>
                        <span className="font-mono text-red-300">{Number(item.lossBudgetPct || 0).toFixed(1)}%</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-500">
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
                    {sig.signal === "SELL_STRONG" ? "매도강력" : "매도검토"}
                  </span>
                  <span className="font-semibold text-slate-200">{sig.name}</span>
                  <span className="font-mono text-slate-500">{sig.symbol}</span>
                  <span className="text-slate-400">{Array.isArray(sig.reasons) ? sig.reasons[0] : ""}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {actionItems.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">오늘 확인할 보유 리스크</h2>
            <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">{actionItems.length}건</span>
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {actionItems.map((item) => (
              <div key={item.key} className={`rounded-xl border px-3 py-2 ${
                item.tone === "red" ? "border-red-500/30 bg-red-500/10" :
                item.tone === "blue" ? "border-blue-500/30 bg-blue-500/10" :
                "border-amber-500/30 bg-amber-500/10"
              }`}>
                <div className={`text-xs font-bold ${
                  item.tone === "red" ? "text-red-300" :
                  item.tone === "blue" ? "text-blue-300" :
                  "text-amber-300"
                }`}>{item.title}</div>
                <div className="mt-1 text-[11px] text-slate-400">{item.detail}</div>
                {item.action && (
                  <button
                    type="button"
                    onClick={() => openEditFromAction(item.key)}
                    className="mt-2 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-800"
                  >
                    {item.action === "stop" ? "손절가 설정" : "목표가 설정"}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

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

      {/* 벤치마크 비교 */}
      {benchmarkData?.status === "OK" && Array.isArray(benchmarkData.items) && benchmarkData.items.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-100">벤치마크 비교 ({benchmarkData.benchmark})</h2>
              <p className="text-xs text-slate-500">{benchmarkData.benchmarkLatestDate} 기준</p>
            </div>
            <div className={`font-mono text-base font-bold ${benchmarkData.totalPortfolioReturn >= 0 ? "text-emerald-300" : "text-red-300"}`}>
              포트 {benchmarkData.totalPortfolioReturn >= 0 ? "+" : ""}{benchmarkData.totalPortfolioReturn?.toFixed(1)}%
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead><tr className="border-b border-slate-800 text-slate-500">
                <th className="pb-2 text-left">종목</th>
                <th className="pb-2 text-right">내 수익률</th>
                <th className="pb-2 text-right">{benchmarkData.benchmark}</th>
                <th className="pb-2 text-right">알파</th>
              </tr></thead>
              <tbody>
                {benchmarkData.items.map((item: any) => (
                  <tr key={item.symbol} className="border-b border-slate-900">
                    <td className="py-1.5 pr-3"><div className="font-medium text-slate-200">{item.name}</div><div className="text-slate-500">{item.symbol}</div></td>
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
      )}

      {/* 상관관계 */}
      {corrData?.status === "OK" && Array.isArray(corrData.matrix) && corrData.matrix.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">종목 간 상관관계 (60일)</h2>
            {corrData.warning && <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">⚠ 높은 상관 쌍</span>}
          </div>
          <div className="max-h-48 space-y-1.5 overflow-y-auto">
            {corrData.matrix.slice(0, 15).map((pair: any) => (
              <div key={`${pair.sym1}-${pair.sym2}`} className="flex items-center justify-between rounded-lg bg-slate-950/50 px-3 py-1.5 text-[11px]">
                <span className="text-slate-300">{pair.name1} <span className="text-slate-500">vs</span> {pair.name2}</span>
                <div className="flex items-center gap-2">
                  <div className="w-20 overflow-hidden rounded-full bg-slate-800">
                    <div className={`h-1.5 rounded-full ${Math.abs(pair.corr) >= 0.7 ? "bg-red-500" : Math.abs(pair.corr) >= 0.4 ? "bg-amber-500" : "bg-emerald-500"}`}
                      style={{ width: `${Math.abs(pair.corr) * 100}%` }} />
                  </div>
                  <span className={`w-10 text-right font-mono ${Math.abs(pair.corr) >= 0.7 ? "text-red-300" : Math.abs(pair.corr) >= 0.4 ? "text-amber-300" : "text-emerald-300"}`}>
                    {pair.corr > 0 ? "+" : ""}{pair.corr.toFixed(2)}
                  </span>
                  <span className="text-slate-500">{pair.level}</span>
                </div>
              </div>
            ))}
          </div>
          {corrData.highCorrelationPairs?.length > 0 && (
            <p className="mt-2 text-[10px] text-amber-400">상관계수 0.7↑ 쌍 {corrData.highCorrelationPairs.length}개 — 동일 방향 집중 리스크</p>
          )}
        </div>
      )}

      {/* 섹터 노출도 */}
      {sectorData && Array.isArray(sectorData.sectors) && sectorData.sectors.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">섹터 노출도 히트맵</h2>
            {sectorData.concentration?.warning && (
              <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">⚠ 집중도 높음 ({sectorData.concentration.top1Pct}%)</span>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {sectorData.sectors.map((s: any) => {
              const intensity = s.pct >= 30 ? "bg-red-700/60" : s.pct >= 20 ? "bg-orange-700/50" : s.pct >= 10 ? "bg-amber-700/40" : "bg-slate-700/50";
              return (
                <div key={s.sector} className={`rounded-xl ${intensity} px-3 py-2 text-center`} style={{ minWidth: `${Math.max(70, s.pct * 3)}px` }}>
                  <div className="max-w-[120px] truncate text-[11px] font-semibold text-slate-200">{s.sector}</div>
                  <div className="mt-0.5 font-mono text-sm font-bold text-white">{s.pct.toFixed(1)}%</div>
                  <div className="text-[10px] text-slate-300">{s.symbols.slice(0, 2).join(", ")}{s.symbols.length > 2 ? ` 외 ${s.symbols.length - 2}` : ""}</div>
                </div>
              );
            })}
          </div>
          {sectorData.maxLossSimulation && (
            <div className="mt-4 rounded-xl border border-red-800/30 bg-red-950/20 p-3 text-[11px]">
              <span className="font-semibold text-red-300">전 종목 손절 시뮬레이션</span>
              <span className="ml-3 font-mono font-bold text-red-300">
                {sectorData.maxLossSimulation.totalLoss.toLocaleString()}원 ({sectorData.maxLossSimulation.totalLossPct.toFixed(1)}%)
              </span>
            </div>
          )}
        </div>
      )}

      {/* 포트폴리오 최적화 + 알림 — 접기 아코디언 */}
      <CollapsibleSection title="포트폴리오 최적화">
        <PortfolioOptimizePanel />
      </CollapsibleSection>

      <CollapsibleSection title="Telegram 알림 설정">
        <AlertsPanel />
      </CollapsibleSection>
    </div>
  );
}

function CollapsibleSection({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
      >
        <span className="text-sm font-semibold text-slate-200">{title}</span>
        <ChevronDown size={16} className={`shrink-0 text-slate-500 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="border-t border-slate-800 px-5 pb-5 pt-4">{children}</div>}
    </div>
  );
}

function SummaryCard({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 sm:p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-2 min-w-0 break-words font-mono text-[clamp(1rem,4.8vw,1.25rem)] font-bold leading-tight ${accent}`}>{value}</div>
    </div>
  );
}

function Mini({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-slate-950 px-2.5 py-2">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className={`mt-1 min-w-0 break-keep font-mono text-[11px] font-bold leading-tight sm:text-sm ${accent}`}>{value}</div>
    </div>
  );
}
