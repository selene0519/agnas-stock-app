"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, money, type Market } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { displayName, normalizeMarket, normalizeSymbol, priceText } from "@/lib/moneDisplay";

type ToggleKey = "ma5" | "ma20" | "ma60" | "bb" | "volume" | "rsi" | "macd" | "index"
              | "zigzag" | "trendline" | "retracement" | "supply" | "fakeBreak";

const PERIODS: { label: string; bars: number | null }[] = [
  { label: "1M", bars: 21 },
  { label: "3M", bars: 63 },
  { label: "6M", bars: 126 },
  { label: "1Y", bars: 252 },
  { label: "전체", bars: null },
];

type ChartLoadState = {
  ohlcvStatus: string;
  ohlcvCount: number;
  recStatus: string;
  recCount: number;
  newsCount: number;
  disclosureCount: number;
  companyStatus: string;
  errors: string[];
  updatedAt: string;
  recoDate: string;  // 추천 CSV 생성일 (YYYY-MM-DD)
};

function toSymbol(item: any, index = 0): MoneSymbol | null {
  const symbol = normalizeSymbol(item);
  if (!symbol) return null;
  const market = normalizeMarket(item?.market, symbol);
  const name = displayName(item);
  return { id: String(item?.id || `${market}-${symbol}-${index}`), symbol, name, market, label: `${name} (${symbol})`, isWatch: Boolean(item?.isWatch || item?.watch) };
}
function fallbackSymbol(market: Market): MoneSymbol {
  if (market === "us") return { id: "us-NVDA", symbol: "NVDA", name: "NVIDIA", market: "us", label: "NVIDIA (NVDA)", isWatch: true };
  return { id: "kr-005930", symbol: "005930", name: "삼성전자", market: "kr", label: "삼성전자 (005930)", isWatch: true };
}

function num(value: any) {
  const n = Number(String(value ?? "").replace(/[$,%원,\s]/g, ""));
  return Number.isFinite(n) ? n : null;
}
function positiveNum(value: any) { const n = num(value); return n !== null && n > 0 ? n : null; }
function closeOf(row: any) { return num(row.close ?? row.Close ?? row.closePrice ?? row.currentPrice) || 0; }
function highOf(row: any)  { return num(row.high ?? row.High ?? row.highPrice) || closeOf(row); }
function lowOf(row: any)   { return num(row.low ?? row.Low ?? row.lowPrice) || closeOf(row); }
function calcAtr14(rows: any[]) {
  const recent = rows.slice(-14);
  if (recent.length < 14) return null;
  const trs = recent.map((r, i) => {
    const prev = i > 0 ? recent[i - 1] : rows[rows.length - recent.length - 1];
    const range = highOf(r) - lowOf(r);
    if (!prev) return range;
    return Math.max(range, Math.abs(highOf(r) - closeOf(prev)), Math.abs(lowOf(r) - closeOf(prev)));
  }).filter((v) => Number.isFinite(v) && v >= 0);
  return trs.length >= 14 ? trs.reduce((s, v) => s + v, 0) / trs.length : null;
}
function calcMdd20(rows: any[]) {
  const closes = rows.slice(-20).map(closeOf).filter((v) => Number.isFinite(v) && v > 0);
  if (closes.length < 20) return null;
  let peak = closes[0];
  let mdd = 0;
  for (const close of closes) {
    peak = Math.max(peak, close);
    mdd = Math.min(mdd, ((close - peak) / peak) * 100);
  }
  return mdd;
}
function chartTime(row: any): string {
  const raw = String(row?.date ?? row?.Date ?? row?.tradeDate ?? row?.일자 ?? "").trim();
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10);
  return raw;
}

function levelValue(levels: any, key: "entry"|"stop"|"target"|"expected"|"base") {
  const keys: Record<typeof key, string[]> = {
    entry: ["entry","entryPrice"], stop: ["stop","stopLoss","stopPrice"],
    target: ["target","targetPrice"], expected: ["expectedPrice","expected"], base: ["basePrice","base"],
  };
  for (const name of keys[key]) { const v = num(levels?.[name]); if (v && v > 0) return v; }
  return 0;
}

function average(values: number[]) {
  const clean = values.filter((v) => Number.isFinite(v) && v > 0);
  return clean.length ? clean.reduce((s, v) => s + v, 0) / clean.length : null;
}
function rsi(values: number[], period = 14) {
  if (values.length <= period) return null;
  let gain = 0, loss = 0;
  for (let i = values.length - period; i < values.length; i++) {
    const diff = values[i] - values[i - 1];
    if (diff >= 0) gain += diff; else loss += Math.abs(diff);
  }
  if (loss === 0) return 100;
  const rs = gain / period / (loss / period);
  return 100 - 100 / (1 + rs);
}

function derivedIndicators(rows: any[], latest: any, recInd: any) {
  const close = positiveNum(latest?.close ?? latest?.Close ?? latest?.closePrice ?? latest?.currentPrice);
  const ma20 = positiveNum(recInd?.ma20 ?? latest?.ma20 ?? latest?.MA20);
  const bbUpper = positiveNum(recInd?.bbUpper ?? latest?.bbUpper ?? latest?.BBUpper);
  const bbLower = positiveNum(recInd?.bbLower ?? latest?.bbLower ?? latest?.BBLower);
  const latestVol = positiveNum(latest?.volume ?? latest?.Volume);
  const volAvg20 = average(rows.slice(-20).map((r) => positiveNum(r.volume ?? r.Volume) || 0));
  const high52w = Math.max(...rows.slice(-260).map(highOf).filter(Boolean), 0);
  return {
    ...recInd,
    rsi14: positiveNum(recInd?.rsi14 ?? latest?.rsi ?? latest?.RSI),
    atr14: positiveNum(recInd?.atr14 ?? latest?.atr14 ?? latest?.ATR14) ?? calcAtr14(rows),
    mdd20: num(recInd?.mdd20 ?? latest?.mdd20 ?? latest?.MDD20) ?? calcMdd20(rows),
    distanceToMa20: recInd?.distanceToMa20 ?? (close && ma20 ? ((close - ma20) / ma20) * 100 : null),
    bbPercentB: recInd?.bbPercentB ?? (close && bbUpper && bbLower && bbUpper !== bbLower ? (close - bbLower) / (bbUpper - bbLower) : null),
    volumeRatio20: recInd?.volumeRatio20 ?? (latestVol && volAvg20 ? latestVol / volAvg20 : null),
    distanceTo52wHigh: recInd?.distanceTo52wHigh ?? (close && high52w ? ((close - high52w) / high52w) * 100 : null),
  };
}

function relatedItems(items: any[], selected: MoneSymbol | null) {
  if (!selected) return [];
  const sym = selected.symbol.toLowerCase();
  const nameParts = selected.name.toLowerCase().split(/[\s·\-]+/).filter((p) => p.length >= 2);

  // 1순위: symbol 정확 매칭 (공시는 symbol 컬럼 있음)
  const bySymbol = items.filter((item) => String(item.symbol || "").toLowerCase() === sym);
  if (bySymbol.length) return bySymbol.slice(0, 5);

  // 2순위: 종목명 텍스트 포함 매칭
  return items.filter((item) => {
    const text = [item.symbol, item.name, item.company, item.title, item.reportName, item.summary]
      .filter(Boolean).join(" ").toLowerCase();
    return sym === text.slice(0, sym.length) // 심볼로 시작하거나
      || nameParts.some((p) => text.includes(p)); // 종목명 단어 포함
  }).slice(0, 5);
}

// fallback 제거 — 혼란스러운 "Recommendation report" 항목 대신 빈 상태 표시
function reportNewsFallback(_levels: any) { return []; }
function reportDisclosureFallback(_levels: any) { return []; }

function companyFallback(levels: any) {
  if (!levels) return null;
  const keys = ["per", "pbr", "peg", "roe", "debtRatio", "operatingMargin", "qualityScore", "earningsScore"];
  return {
    ...levels,
    dataStatus: keys.some((key) => levels[key] != null && levels[key] !== "") ? "REPORT_FALLBACK" : "SOURCE_CONTEXT",
    summary: levels.financialSummary || levels.decisionReason || "No separate company-analysis file was attached; using recommendation/validation source context.",
  };
}

function companyOneLine(company: any): string {
  const roe = Number(company?.roe);
  const margin = Number(company?.operatingMargin);
  const per = Number(company?.per);
  const peg = Number(company?.peg);
  const profit =
    (Number.isFinite(roe) && roe >= 15) || (Number.isFinite(margin) && margin >= 15)
      ? "수익성 양호"
      : (Number.isFinite(roe) && roe < 5) || (Number.isFinite(margin) && margin < 5)
        ? "수익성 확인 필요"
        : "수익성 중립";
  const valuation =
    (Number.isFinite(peg) && peg > 2) || (Number.isFinite(per) && per > 30)
      ? "밸류에이션 부담 높음"
      : Number.isFinite(peg) && peg > 0 && peg < 1
        ? "밸류에이션 매력 있음"
        : "밸류에이션 중립";
  return `${profit}, ${valuation}.`;
}

function loadStatusText(status: any) {
  const s = String(status || "").toUpperCase();
  if (s === "OK" || s === "NORMAL") return "정상";
  if (s === "PARTIAL") return "부분";
  if (s === "STALE") return "오래됨";
  if (s === "ERROR") return "오류";
  if (s === "TIMEOUT") return "시간초과";
  if (s === "NO_DATA") return "없음";
  return status ? String(status) : "확인 필요";
}

function statusTone(kind: "ok" | "warn" | "bad" | "neutral") {
  if (kind === "ok") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (kind === "warn") return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  if (kind === "bad") return "border-red-500/30 bg-red-500/10 text-red-300";
  return "border-slate-700 bg-slate-950 text-slate-300";
}

function coverageTone(count: number, required = 1) {
  return count >= required ? statusTone("ok") : statusTone("warn");
}

function dateOf(row: any) {
  return row?.date || row?.Date || row?.tradeDate || row?.time || "";
}

function parseDate(value: any) {
  if (!value) return null;
  const raw = String(value).trim();
  const normalized = /^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : raw;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function freshnessInfo(rows: any[]) {
  const last = dateOf(rows.at(-1));
  const date = parseDate(last);
  if (!date) {
    return { label: "최근일 없음", detail: "날짜 필드가 들어오면 자동 계산됩니다.", cls: statusTone("warn") };
  }
  const days = Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
  if (days <= 4) return { label: "신선", detail: `${last} 기준`, cls: statusTone("ok") };
  if (days <= 10) return { label: "확인 필요", detail: `${days}일 전 OHLCV`, cls: statusTone("warn") };
  return { label: "오래됨", detail: `${days}일 전 OHLCV`, cls: statusTone("bad") };
}

function firstTouch(rows: any[], price: number, fromIndex = 0) {
  if (!price || price <= 0) return null;
  for (let i = Math.max(0, fromIndex); i < rows.length; i += 1) {
    if (lowOf(rows[i]) <= price && highOf(rows[i]) >= price) {
      return { index: i, date: dateOf(rows[i]) || `${i + 1}번째 봉` };
    }
  }
  return null;
}

function recommendationTouchReview(rows: any[], levels: any, currentPrice: number, market: Market, recoDate?: string) {
  const entry = levelValue(levels, "entry");
  const stop = levelValue(levels, "stop");
  const target = levelValue(levels, "target");
  if (!levels || !entry || rows.length < 5) {
    return {
      label: "검증 대기",
      detail: "추천선과 OHLCV가 충분해지면 기준가/목표/손절 터치를 자동 판정합니다.",
      cls: statusTone("neutral"),
      cards: [
        { label: "기준가 터치", value: "-", sub: "추천선 필요" },
        { label: "목표 터치", value: "-", sub: "추천선 필요" },
        { label: "손절 터치", value: "-", sub: "추천선 필요" },
      ],
    };
  }

  // 추천 생성일 기준으로 시작봉 결정
  let fromIndex = Math.max(0, rows.length - 80); // 기본값: 최근 80봉
  let rangeLabel = "최근 80봉";
  if (recoDate) {
    const recoDay = recoDate.slice(0, 10);
    const idx = rows.findIndex((r) => dateOf(r) >= recoDay);
    if (idx >= 0) {
      fromIndex = idx;
      const barsFromReco = rows.length - idx;
      rangeLabel = `추천일(${recoDay}) 이후 ${barsFromReco}봉`;
    }
  }
  const reviewRows = rows.slice(fromIndex);
  const entryTouch = firstTouch(reviewRows, entry);
  const fromEntry = entryTouch ? entryTouch.index : 0;
  const targetTouch = firstTouch(reviewRows, target, fromEntry);
  const stopTouch = firstTouch(reviewRows, stop, fromEntry);
  const gapPct = currentPrice > 0 ? ((currentPrice - entry) / entry) * 100 : null;
  const gapText = gapPct == null ? "현재가 없음" : `${gapPct >= 0 ? "+" : ""}${gapPct.toFixed(1)}%`;

  if (!entryTouch) {
    return {
      label: "기준가 대기",
      detail: `기준가까지 ${gapText}. 실제 저가/고가가 닿으면 자동으로 기준가 터치로 전환됩니다.`,
      cls: statusTone("warn"),
      cards: [
        { label: "기준가 터치", value: "대기", sub: money(entry, market) },
        { label: "목표 터치", value: "-", sub: target ? money(target, market) : "목표 없음" },
        { label: "손절 터치", value: "-", sub: stop ? money(stop, market) : "손절 없음" },
      ],
    };
  }
  const stoppedBeforeTarget = stopTouch && (!targetTouch || stopTouch.index <= targetTouch.index);
  if (stoppedBeforeTarget) {
    return {
      label: "손절선 터치",
      detail: `${entryTouch.date} 기준가 터치 후 ${stopTouch.date} 손절선에 닿았습니다.`,
      cls: statusTone("bad"),
      cards: [
        { label: "기준가 터치", value: entryTouch.date, sub: money(entry, market) },
        { label: "목표 터치", value: targetTouch?.date || "미도달", sub: target ? money(target, market) : "목표 없음" },
        { label: "손절 터치", value: stopTouch.date, sub: stop ? money(stop, market) : "손절 없음" },
      ],
    };
  }
  if (targetTouch) {
    return {
      label: "목표선 터치",
      detail: `${entryTouch.date} 기준가 터치 후 ${targetTouch.date} 목표선에 닿았습니다.`,
      cls: statusTone("ok"),
      cards: [
        { label: "기준가 터치", value: entryTouch.date, sub: money(entry, market) },
        { label: "목표 터치", value: targetTouch.date, sub: target ? money(target, market) : "목표 없음" },
        { label: "손절 터치", value: stopTouch?.date || "미터치", sub: stop ? money(stop, market) : "손절 없음" },
      ],
    };
  }
  return {
    label: "기준가 터치 후 진행",
    detail: `${entryTouch.date} 기준가 터치 후 목표/손절 미확정입니다.`,
    cls: statusTone("neutral"),
    cards: [
      { label: "기준가 터치", value: entryTouch.date, sub: money(entry, market) },
      { label: "목표 터치", value: "미도달", sub: target ? money(target, market) : "목표 없음" },
      { label: "손절 터치", value: "미터치", sub: stop ? money(stop, market) : "손절 없음" },
    ],
  };
}

function withTimeout<T>(promise: Promise<T>, ms: number, fallback: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(fallback), ms);
    promise.then((v) => resolve(v)).catch(() => resolve(fallback)).finally(() => window.clearTimeout(timer));
  });
}

// ── RSI 오실레이터 서브차트 ──────────────────────────────────────────
function RsiChart({ rows }: { rows: any[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  const rsiData = useMemo(() => {
    // close > 0 인 행만 추려 closes와 날짜가 1:1로 대응되게 함
    const validRows = rows.filter((r) => closeOf(r) > 0);
    const closes = validRows.map(closeOf);
    if (closes.length < 16) return [];
    const period = 14;
    const result: { time: string; value: number }[] = [];
    for (let i = period; i < closes.length; i++) {
      let gain = 0, loss = 0;
      for (let j = i - period + 1; j <= i; j++) {
        const diff = closes[j] - closes[j - 1];
        if (diff > 0) gain += diff; else loss += Math.abs(diff);
      }
      const rs = loss === 0 ? 100 : (gain / period) / (loss / period);
      const rsiVal = loss === 0 ? 100 : 100 - 100 / (1 + rs);
      const date = chartTime(validRows[i]);
      if (date) result.push({ time: date as string, value: Math.round(rsiVal * 10) / 10 });
    }
    return result;
  }, [rows]);

  useEffect(() => {
    if (!containerRef.current || rsiData.length === 0) return;
    async function init() {
      try {
        const LW = await import("lightweight-charts");
        if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
        const chart = LW.createChart(containerRef.current!, {
          width: containerRef.current!.clientWidth, height: 100,
          layout: { background: { color: "#020617" }, textColor: "#64748b" },
          grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
          rightPriceScale: { borderColor: "#334155", scaleMargins: { top: 0.1, bottom: 0.1 } },
          timeScale: { borderColor: "#334155", visible: false },
          handleScroll: false, handleScale: false,
        });
        chartRef.current = chart;
        const c = chart as any;
        const line = c.addLineSeries({ color: "#94a3b8", lineWidth: 1.5, priceLineVisible: false });
        line.setData(rsiData);
        const times = rsiData.map(({ time }) => time);
        const ob = c.addLineSeries({ color: "#ef444440", lineWidth: 1, priceLineVisible: false, lineStyle: 2 });
        const os = c.addLineSeries({ color: "#22c55e40", lineWidth: 1, priceLineVisible: false, lineStyle: 2 });
        ob.setData(times.map((time) => ({ time, value: 70 })));
        os.setData(times.map((time) => ({ time, value: 30 })));
        chart.timeScale().fitContent();
        const ro = new ResizeObserver(() => { if (containerRef.current && chartRef.current) chartRef.current.resize(containerRef.current.clientWidth, 100); });
        ro.observe(containerRef.current!);
        return () => ro.disconnect();
      } catch {}
    }
    init();
    return () => { if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; } };
  }, [rsiData]);

  if (rsiData.length === 0) return null;
  const latest = rsiData.at(-1);
  const rsiColor = latest ? (latest.value >= 70 ? "text-red-400" : latest.value <= 30 ? "text-emerald-400" : "text-slate-400") : "text-slate-400";
  return (
    <div className="rounded-xl border border-slate-800 bg-[#020617]">
      <div className="flex items-center gap-3 px-3 pt-2 pb-1">
        <span className="text-[10px] font-medium text-slate-500">RSI(14)</span>
        {latest && <span className={`font-mono text-xs font-bold ${rsiColor}`}>{latest.value.toFixed(1)}</span>}
        {latest?.value >= 70 && <span className="text-[10px] text-red-400">과매수</span>}
        {latest?.value <= 30 && <span className="text-[10px] text-emerald-400">과매도</span>}
        <span className="ml-auto text-[10px] text-slate-600">70 / 30 기준선</span>
      </div>
      <div ref={containerRef} className="h-[100px] w-full" />
    </div>
  );
}

// ── MACD 서브차트 ────────────────────────────────────────────────────
function MacdChart({ rows }: { rows: any[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  const macdData = useMemo(() => {
    const closes = rows.map(closeOf).filter((v) => v > 0);
    if (closes.length < 27) return { macd: [], signal: [], hist: [] };
    const ema = (arr: number[], period: number) => {
      const k = 2 / (period + 1);
      const result: (number | null)[] = [];
      let prev = arr.slice(0, period).reduce((a, b) => a + b, 0) / period;
      result.push(...Array(period - 1).fill(null), prev);
      for (let i = period; i < arr.length; i++) { prev = arr[i] * k + prev * (1 - k); result.push(prev); }
      return result;
    };
    const ema12 = ema(closes, 12), ema26 = ema(closes, 26);
    const macdLine = closes.map((_, i) => ema12[i] != null && ema26[i] != null ? (ema12[i] as number) - (ema26[i] as number) : null).filter((v): v is number => v !== null);
    const signalLine = ema(macdLine, 9);
    const dates = rows.slice(-macdLine.length).map((r: any) => chartTime(r)).filter(Boolean);
    const macd = dates.map((t, i) => ({ time: t as string, value: macdLine[i] }));
    const signal = dates.map((t, i) => signalLine[i] != null ? { time: t as string, value: signalLine[i] as number } : null).filter(Boolean) as { time: string; value: number }[];
    const hist = dates.map((t, i) => ({
      time: t as string,
      value: signalLine[i] != null ? macdLine[i] - (signalLine[i] as number) : 0,
      color: (signalLine[i] != null ? macdLine[i] - (signalLine[i] as number) : 0) >= 0 ? "#22c55e60" : "#ef444460",
    }));
    return { macd, signal, hist };
  }, [rows]);

  useEffect(() => {
    if (!containerRef.current || macdData.macd.length < 2) return;
    async function init() {
      try {
        const LW = await import("lightweight-charts");
        if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
        const chart = LW.createChart(containerRef.current!, {
          width: containerRef.current!.clientWidth, height: 100,
          layout: { background: { color: "#020617" }, textColor: "#64748b" },
          grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
          rightPriceScale: { borderColor: "#334155", scaleMargins: { top: 0.1, bottom: 0.1 } },
          timeScale: { borderColor: "#334155", visible: false },
          handleScroll: false, handleScale: false,
        });
        chartRef.current = chart;
        const mc = chart as any;
        const histSeries = mc.addHistogramSeries({ priceScaleId: "macd" });
        histSeries.setData(macdData.hist);
        const macdSeries = mc.addLineSeries({ color: "#38bdf8", lineWidth: 1.5, priceLineVisible: false, priceScaleId: "macd" });
        macdSeries.setData(macdData.macd);
        const signalSeries = mc.addLineSeries({ color: "#f97316", lineWidth: 1, priceLineVisible: false, lineStyle: 2, priceScaleId: "macd" });
        signalSeries.setData(macdData.signal);
        chart.timeScale().fitContent();
        const ro = new ResizeObserver(() => { if (containerRef.current && chartRef.current) chartRef.current.resize(containerRef.current.clientWidth, 100); });
        ro.observe(containerRef.current!);
        return () => ro.disconnect();
      } catch {}
    }
    init();
    return () => { if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; } };
  }, [macdData]);

  if (macdData.macd.length < 2) return null;
  const lastMacd = macdData.macd.at(-1)?.value ?? 0;
  const lastSignal = macdData.signal.at(-1)?.value ?? 0;
  const isBullish = lastMacd > lastSignal;
  return (
    <div className="rounded-xl border border-slate-800 bg-[#020617]">
      <div className="flex items-center gap-3 px-3 pt-2 pb-1">
        <span className="text-[10px] font-medium text-slate-500">MACD(12,26,9)</span>
        <span className={`text-[10px] font-semibold ${isBullish ? "text-emerald-300" : "text-red-400"}`}>
          {isBullish ? "골든크로스" : "데드크로스"}
        </span>
        <span className="ml-auto text-[10px] text-slate-600">
          <span style={{ color: "#38bdf8" }}>━ MACD</span>
          <span className="ml-2" style={{ color: "#f97316" }}>- - Signal</span>
        </span>
      </div>
      <div ref={containerRef} className="h-[100px] w-full" />
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════
// Phase 6 — 고급 차트 분석 (빗각 · 지그재그 · 매물대 · 0.868 되돌림)
//
// 4개 요소의 연계 구조:
//   ① ZigZag     → 단기 조정 구간 확인, 고점/저점 구조 파악
//   ② 빗각       → 추세선 (저점 연결 / 고점 연결) + 돌파 감지
//   ③ 매물대     → 거래 집중 구간 = 진입·청산·스톱 기준
//   ④ 0.868      → 가장 최근 ZigZag 스윙의 피보나치 되돌림 레벨
//                  매물대와 겹칠 때 = 강력 진입/청산 신호
// ══════════════════════════════════════════════════════════════════════

type CandleBar   = { time: string; open: number; high: number; low: number; close: number };
type ZigZagPoint = { time: string; value: number; type: "H" | "L" };

// ── ① ZigZag ──────────────────────────────────────────────────────────
/**
 * ZigZag 계산 — % 임계값 방식
 *
 * 알고리즘:
 *   1) 로컬 고점/저점 후보 추출 (winSize 좌우 봉 기준)
 *   2) 방향 전환 시 threshold% 이상일 때만 새 피벗으로 인정 (노이즈 제거)
 *   3) 연속 같은 방향이면 더 극단적인 값으로 교체
 *   4) 마지막 확정 피벗 이후 최근봉 극값 추가 (선 끊김 방지)
 *
 * @param threshold  최소 반전 비율 (기본 5%) — 변동성 큰 종목은 8~10% 권장
 * @param winSize    로컬 극값 확인 좌우 봉 수 (기본 3)
 */
function calcZigZagFull(data: CandleBar[], threshold = 0.05, winSize = 3): ZigZagPoint[] {
  if (data.length < winSize * 2 + 2) return [];

  // 1단계: 로컬 고점/저점 후보
  const candidates: ZigZagPoint[] = [];
  for (let i = winSize; i < data.length - winSize; i++) {
    const h = data[i].high, l = data[i].low;
    let isH = true, isL = true;
    for (let j = i - winSize; j <= i + winSize; j++) {
      if (j === i) continue;
      if (data[j].high > h) isH = false;
      if (data[j].low  < l) isL = false;
    }
    if      (isH && !isL) candidates.push({ time: data[i].time, value: h, type: "H" });
    else if (isL && !isH) candidates.push({ time: data[i].time, value: l, type: "L" });
  }

  // 2단계: 임계값 필터 + 연속 같은 방향 병합
  const filtered: ZigZagPoint[] = [];
  for (const p of candidates) {
    const last = filtered[filtered.length - 1];
    if (!last) { filtered.push(p); continue; }
    if (last.type === p.type) {
      if ((p.type === "H" && p.value > last.value) ||
          (p.type === "L" && p.value < last.value))
        filtered[filtered.length - 1] = p;
    } else {
      const chg = Math.abs(p.value - last.value) / last.value;
      if (chg >= threshold) filtered.push(p);
      else if ((p.type === "H" && p.value > last.value) ||
               (p.type === "L" && p.value < last.value))
        filtered[filtered.length - 1] = p;
    }
  }

  // 3단계: 마지막 피벗 이후 최근봉 극값 추가
  if (filtered.length > 0) {
    const lastPivot = filtered[filtered.length - 1];
    const lastBar   = data[data.length - 1];
    if (lastPivot.time !== lastBar.time) {
      const recentSlice = data.slice(-Math.min(winSize + 2, data.length));
      filtered.push(lastPivot.type === "H"
        ? { time: lastBar.time, value: Math.min(...recentSlice.map(d => d.low)),  type: "L" }
        : { time: lastBar.time, value: Math.max(...recentSlice.map(d => d.high)), type: "H" });
    }
  }
  return filtered;
}

// ── ② 빗각 (대각 추세선) ──────────────────────────────────────────────
/**
 * 빗각 추세선 계산
 *
 * - 상승 추세선: ZigZag 저점(L) 중 최근 2개를 직선으로 연결 → 현재봉까지 연장
 * - 하락 추세선: ZigZag 고점(H) 중 최근 2개를 직선으로 연결 → 현재봉까지 연장
 *
 * 활용:
 *   - 상승 추세선 하향 이탈 → 단기 하락 전환 신호
 *   - 하락 추세선 상향 돌파 → 단기 상승 전환 신호
 *   - 돌파 후 추세선 부근으로 리트레이스 → 빗각 패턴 진입 구간
 *
 * 주의: 피벗이 2개 미만이면 null 반환 (추세선 없음)
 */
function calcTrendlines(data: CandleBar[], pivots: ZigZagPoint[]): {
  uptrend:   { time: string; value: number }[] | null;  // 저점 연결 (상승)
  downtrend: { time: string; value: number }[] | null;  // 고점 연결 (하락)
  uptrendVal:   number | null;  // 현재봉 기준 상승 추세선 값
  downtrendVal: number | null;  // 현재봉 기준 하락 추세선 값
} {
  const timeToIdx = new Map(data.map((d, i) => [d.time, i]));
  const lows  = pivots.filter(p => p.type === "L");
  const highs = pivots.filter(p => p.type === "H");

  /**
   * p1 → p2 직선을 p1 위치에서 데이터 끝까지 연장
   * 값이 0 이하이거나 가격 범위 대비 크게 벗어나면 해당 점 제외
   */
  const makeLine = (p1: ZigZagPoint, p2: ZigZagPoint) => {
    const i1 = timeToIdx.get(p1.time), i2 = timeToIdx.get(p2.time);
    if (i1 == null || i2 == null || i1 >= i2) return null;
    const slope = (p2.value - p1.value) / (i2 - i1);
    const priceRange = Math.max(...data.map(d => d.high)) - Math.min(...data.map(d => d.low));
    const segment = data.slice(i1).map((d, j) => ({
      time:  d.time,
      value: p1.value + slope * j,
    })).filter(pt => pt.value > 0 && pt.value < p1.value + priceRange * 3);
    return segment.length >= 2 ? segment : null;
  };

  const upLine   = lows.length  >= 2 ? makeLine(lows[lows.length - 2],   lows[lows.length - 1])   : null;
  const downLine = highs.length >= 2 ? makeLine(highs[highs.length - 2], highs[highs.length - 1]) : null;

  return {
    uptrend:      upLine,
    downtrend:    downLine,
    uptrendVal:   upLine   ? upLine[upLine.length - 1].value   : null,
    downtrendVal: downLine ? downLine[downLine.length - 1].value : null,
  };
}

// ── ③ 0.868 되돌림 (피보나치 + 핵심 레벨) ────────────────────────────
/**
 * 피보나치 되돌림 계산 — 가장 최근 완성된 ZigZag 스윙 기준
 *
 * 레벨:
 *   0.236, 0.382, 0.500, 0.618, 0.786 — 표준 피보나치
 *   0.868 — 핵심 레벨 (매물대와 겹치면 강력 진입/청산 신호)
 *
 * 산출 방법:
 *   상승 스윙(저점→고점) 이후 되돌림 = 고점 - ratio × (고점 - 저점)
 *   하락 스윙(고점→저점) 이후 되돌림 = 저점 + ratio × (고점 - 저점)
 *
 * 주의: 마지막 미완성 피벗(현재봉 쪽 꼬리)은 제외하고 확정 스윙만 사용
 */
function calcRetracements(pivots: ZigZagPoint[]): {
  price: number; ratio: number; label: string; color: string; isKey: boolean;
}[] {
  // 마지막 피벗은 현재봉 연장값이므로 제외, 확정 스윙 2개 필요
  const confirmed = pivots.slice(0, -1);
  if (confirmed.length < 2) return [];

  const swingEnd   = confirmed[confirmed.length - 1];
  const swingStart = confirmed[confirmed.length - 2];

  const high  = swingEnd.type === "H" ? swingEnd.value : swingStart.value;
  const low   = swingEnd.type === "L" ? swingEnd.value : swingStart.value;
  const swing = high - low;
  if (swing <= 0) return [];

  // isUpSwing: 최근 스윙이 상승(저점→고점)이면 true → 되돌림은 아래 방향
  const isUpSwing = swingEnd.type === "H";

  const LEVELS: { ratio: number; label: string; color: string; isKey: boolean }[] = [
    { ratio: 0.236, label: "23.6%", color: "#64748b", isKey: false },
    { ratio: 0.382, label: "38.2%", color: "#94a3b8", isKey: false },
    { ratio: 0.500, label: "50.0%", color: "#94a3b8", isKey: false },
    { ratio: 0.618, label: "61.8%", color: "#f97316", isKey: false },
    { ratio: 0.786, label: "78.6%", color: "#fbbf24", isKey: false },
    { ratio: 0.868, label: "86.8%", color: "#06b6d4", isKey: true  },  // 핵심
  ];

  return LEVELS.map(({ ratio, label, color, isKey }) => {
    const price = isUpSwing
      ? high - ratio * swing   // 상승 스윙 후 하향 되돌림
      : low  + ratio * swing;  // 하락 스윙 후 상향 되돌림
    return { price, ratio, label, color, isKey };
  });
}

// ── ④ 매물대 ──────────────────────────────────────────────────────────
/**
 * 매물대 계산 — 거래량 가중 가격 밀집 구간
 *
 * 알고리즘:
 *   1) 전체 가격 범위를 60개 bin으로 분할
 *   2) 각 캔들의 고-저 범위에 걸쳐 거래량을 균등 분산 (일봉 근사)
 *   3) 볼륨 데이터 없으면 캔들 수로 fallback
 *   4) 강도 35% 이상 bin만 추출
 *   5) 인접 bin 병합 → 실제 매물대 구간
 *
 * 활용:
 *   - 매물대 상단: 저항 → 청산/스톱 기준
 *   - 매물대 하단: 지지 → 진입/스톱 기준
 *   - 스톱은 매물대 바깥에 위치시킴
 */
function calcSupplyZones(
  data: CandleBar[], volumes: number[], topN = 3
): { upper: number; lower: number; center: number; strength: number }[] {
  if (data.length < 10) return [];
  const allPrices = data.flatMap(d => [d.high, d.low]);
  const minP = Math.min(...allPrices), maxP = Math.max(...allPrices);
  if (maxP <= minP) return [];

  const bins    = 60;
  const binSize = (maxP - minP) / bins;
  const buckets = Array.from({ length: bins }, () => 0);
  const totalVol = volumes.reduce((s, v) => s + v, 0);
  const useVol   = totalVol > 0;

  data.forEach((d, i) => {
    const lo   = Math.max(0, Math.floor((d.low  - minP) / binSize));
    const hi   = Math.min(bins, Math.ceil ((d.high - minP) / binSize));
    const span = Math.max(1, hi - lo);
    const w    = useVol ? (volumes[i] || 0) : 1;
    for (let b = lo; b < hi; b++) buckets[b] += w / span;
  });

  const maxVol = Math.max(...buckets);
  if (maxVol <= 0) return [];

  const hot = buckets
    .map((v, idx) => ({ idx, strength: v / maxVol }))
    .filter(b => b.strength > 0.35);

  type Zone = { lower: number; upper: number; center: number; strength: number };
  const merged: Zone[] = [];
  for (const b of hot) {
    const lower = minP + b.idx * binSize;
    const upper = lower + binSize;
    const last  = merged[merged.length - 1];
    if (last && lower <= last.upper + binSize * 1.5) {
      last.upper    = Math.max(last.upper, upper);
      last.center   = (last.lower + last.upper) / 2;
      last.strength = Math.max(last.strength, b.strength);
    } else {
      merged.push({ lower, upper, center: (lower + upper) / 2, strength: b.strength });
    }
  }
  return merged.sort((a, b) => b.strength - a.strength).slice(0, topN);
}

// ── 연계 신호: 0.868 되돌림 × 매물대 겹침 ────────────────────────────
/**
 * 0.868 되돌림 레벨이 매물대 zone 안에 있는지 확인
 * → 겹치면 진입/청산 강력 신호
 * (공차 ±0.5% 허용)
 */
function findOverlapSignals(
  rets: { price: number; ratio: number; isKey: boolean }[],
  zones: { upper: number; lower: number; strength: number }[]
): { price: number; ratio: number; isKey: boolean; strength: number }[] {
  const out: { price: number; ratio: number; isKey: boolean; strength: number }[] = [];
  for (const r of rets) {
    for (const z of zones) {
      const tol = r.price * 0.005;
      if (r.price >= z.lower - tol && r.price <= z.upper + tol) {
        out.push({ price: r.price, ratio: r.ratio, isKey: r.isKey, strength: z.strength });
      }
    }
  }
  return out;
}

// ── ⑤ 가짜 돌파 (False Breakout) ─────────────────────────────────────
/**
 * 가짜 돌파 감지
 *
 * 정의:
 *   "종가"가 전 lookback봉 고점 대비 minPct% 이상 돌파
 *   → confirmBars봉 내에 다시 돌파 기준선 아래로 종가 복귀
 *
 * 제외:
 *   장중 고점만 넘고 음봉 마감 (저항 거부/Rejection) → 가짜돌파 아님
 *   → 반드시 종가 기준으로 돌파 확인
 *
 * 파라미터:
 *   lookback    = 20봉 (단기 저항 기준)
 *   minPct      = 0.3% (최소 의미있는 돌파폭)
 *   confirmBars = 3봉  (복귀 확인 기간)
 */
function calcFakeBreakouts(
  data: CandleBar[], lookback = 20, minPct = 0.003, confirmBars = 3
): { time: string; position: "aboveBar"; shape: "arrowDown"; color: string; text: string }[] {
  type Marker = { time: string; position: "aboveBar"; shape: "arrowDown"; color: string; text: string };
  const markers: Marker[] = [];
  const used = new Set<number>();

  for (let i = lookback; i < data.length - 1; i++) {
    const prevHigh   = Math.max(...data.slice(i - lookback, i).map(d => d.high));
    const breakLevel = prevHigh * (1 + minPct);
    if (data[i].close <= breakLevel) continue;
    for (let k = 1; k <= confirmBars && i + k < data.length; k++) {
      if (data[i + k].close < prevHigh && !used.has(i + k)) {
        markers.push({ time: data[i + k].time, position: "aboveBar", shape: "arrowDown", color: "#ef4444", text: "FB" });
        used.add(i + k);
        break;
      }
    }
  }
  return markers.sort((a, b) => a.time < b.time ? -1 : 1);
}

// ── TvChart (캔들 + 지수 비교선) ─────────────────────────────────────
function TvChart({ rows, levels, market, toggles, indexRows = [] }: {
  rows: any[]; levels: any; market: string;
  toggles: Record<ToggleKey, boolean>; indexRows?: any[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const [renderError, setRenderError] = useState("");

  const candleData = useMemo(() => rows
    .map((r) => {
      const time = chartTime(r);
      const close = Number(r.close || r.Close) || 0;
      if (!time || close <= 0) return null;
      return {
        time,
        open: Number(r.open || r.Open || r.close || r.Close) || close,
        high: Number(r.high || r.High || r.close || r.Close) || close,
        low: Number(r.low || r.Low || r.close || r.Close) || close,
        close,
      };
    })
    .filter(Boolean)
    .sort((a: any, b: any) => a.time < b.time ? -1 : 1) as {
      time: string; open: number; high: number; low: number; close: number;
    }[], [rows]);

  useEffect(() => {
    setRenderError("");
    if (!containerRef.current || candleData.length < 2) return;
    async function init() {
      try {
        const LW = await import("lightweight-charts");
        if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
        const chartHeight = containerRef.current!.clientHeight || 320;
        const chartRaw = LW.createChart(containerRef.current!, {
          width: containerRef.current!.clientWidth, height: chartHeight,
          layout: { background: { color: "#020617" }, textColor: "#94a3b8" },
          grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
          crosshair: { mode: LW.CrosshairMode.Normal },
          rightPriceScale: { borderColor: "#334155" },
          timeScale: { borderColor: "#334155", timeVisible: true },
        });
        chartRef.current = chartRaw;
        const chart = chartRaw as any;
        const candleSeries = chart.addCandlestickSeries({
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#22c55e", borderDownColor: "#ef4444",
          wickUpColor: "#22c55e", wickDownColor: "#ef4444",
        });
        candleSeries.setData(candleData);

        if (toggles.volume) {
          const volSeries = chart.addHistogramSeries({ color: "#334155", priceFormat: { type: "volume" }, priceScaleId: "volume" });
          chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
          const rowByDate = new Map(rows.map((r) => [chartTime(r), r]));
          volSeries.setData(candleData.map((d) => {
            const r = rowByDate.get(d.time) || {};
            return { time: d.time, value: Number(r.volume || r.Volume || 0), color: d.close >= d.open ? "#16a34a55" : "#dc262655" };
          }));
        }

        const closes = candleData.map((d) => d.close);
        const calcMA = (period: number) => candleData.map((d, i) => {
          if (i < period - 1) return null;
          return { time: d.time, value: closes.slice(i - period + 1, i + 1).reduce((s, v) => s + v, 0) / period };
        }).filter(Boolean) as { time: string; value: number }[];

        const apiMA5  = rows.filter(r => chartTime(r) && r.ma5  > 0).map(r => ({ time: chartTime(r), value: Number(r.ma5) }));
        const apiMA20 = rows.filter(r => chartTime(r) && r.ma20 > 0).map(r => ({ time: chartTime(r), value: Number(r.ma20) }));
        const apiMA60 = rows.filter(r => chartTime(r) && r.ma60 > 0).map(r => ({ time: chartTime(r), value: Number(r.ma60) }));

        if (toggles.ma5)  { const s = chart.addLineSeries({ color: "#2dd4bf", lineWidth: 1, priceLineVisible: false }); s.setData(apiMA5.length > 5 ? apiMA5 : calcMA(5)); }
        if (toggles.ma20) { const s = chart.addLineSeries({ color: "#facc15", lineWidth: 1.5, priceLineVisible: false }); s.setData(apiMA20.length > 5 ? apiMA20 : calcMA(20)); }
        if (toggles.ma60) { const s = chart.addLineSeries({ color: "#f97316", lineWidth: 1.5, priceLineVisible: false }); s.setData(apiMA60.length > 5 ? apiMA60 : calcMA(60)); }

        if (toggles.bb) {
          const apiBBU = rows.filter(r => chartTime(r) && r.bbUpper > 0).map(r => ({ time: chartTime(r), value: Number(r.bbUpper) }));
          const apiBBL = rows.filter(r => chartTime(r) && r.bbLower > 0).map(r => ({ time: chartTime(r), value: Number(r.bbLower) }));
          let bbU = apiBBU, bbL = apiBBL;
          if (bbU.length < 5 && closes.length >= 20) {
            const calc = candleData.map((d, i) => {
              if (i < 19) return null;
              const slice = closes.slice(i - 19, i + 1);
              const mean = slice.reduce((s, v) => s + v, 0) / 20;
              const std = Math.sqrt(slice.reduce((s, v) => s + (v - mean) ** 2, 0) / 20);
              return { time: d.time, upper: mean + std * 2, lower: mean - std * 2 };
            }).filter(Boolean) as { time: string; upper: number; lower: number }[];
            bbU = calc.map(d => ({ time: d.time, value: d.upper }));
            bbL = calc.map(d => ({ time: d.time, value: d.lower }));
          }
          const sU = chart.addLineSeries({ color: "#7c3aed66", lineWidth: 1, priceLineVisible: false, lineStyle: 3 });
          const sL = chart.addLineSeries({ color: "#7c3aed66", lineWidth: 1, priceLineVisible: false, lineStyle: 3 });
          sU.setData(bbU); sL.setData(bbL);
        }

        // ── 지수 비교선 (날짜 기반 join — row index 매칭 아님)
        if (toggles.index && indexRows.length > 5 && candleData.length > 5) {
          const startDate = candleData[0].time as string;
          // 날짜 문자열로 필터링 (국장/미장 휴장일 무관하게 교집합만)
          const indexFiltered = indexRows.filter((r: any) => {
            const d = chartTime(r);
            return d && d >= startDate;
          });
          if (indexFiltered.length > 2) {
            const baseClose = Number(indexFiltered[0].close || indexFiltered[0].Close || 0);
            const baseStock = candleData[0].close;
            if (baseClose > 0 && baseStock > 0) {
              // 날짜 → 정규화 값 매핑
              const indexByDate = new Map(
                indexFiltered.map((r: any) => {
                  const close = Number(r.close || r.Close || 0);
                  return [chartTime(r), close > 0 ? (close / baseClose) * baseStock : null];
                })
              );
              // candleData 날짜에 지수 값 대응 (없는 날짜 건너뜀)
              const indexNorm = candleData
                .map((d) => { const v = indexByDate.get(d.time); return v != null ? { time: d.time, value: v } : null; })
                .filter(Boolean) as { time: string; value: number }[];
              if (indexNorm.length > 2) {
                const idxSeries = chart.addLineSeries({ color: "#64748b80", lineWidth: 1, priceLineVisible: false, lineStyle: 2, title: market === "us" ? "SPY" : "KOSPI" });
                idxSeries.setData(indexNorm);
              }
            }
          }
        }

        // 진입/손절/목표 수평선
        if (levels) {
          const addLine = (price: number, color: string, title: string) => {
            if (!price || price <= 0) return;
            candleSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title });
          };
          addLine(levelValue(levels, "entry"), "#22c55e", "기준");
          addLine(levelValue(levels, "stop"),  "#ef4444", "손절");
          addLine(levelValue(levels, "target"), "#06b6d4", "목표");
        }

        // ══ Phase 6 — 고급 차트 분석 ══════════════════════════════════════
        // 공통 데이터: ZigZag + 매물대 (다른 기능들이 참조)
        const volMap = new Map(rows.map((row: any) => [chartTime(row), Number(row.volume || row.Volume || 0)]));
        const vols   = candleData.map(d => volMap.get(d.time) || 0);
        const pivots = candleData.length >= 12 ? calcZigZagFull(candleData, 0.05, 3) : [];
        const zones  = candleData.length >= 20 ? calcSupplyZones(candleData, vols, 3) : [];
        const rets   = pivots.length >= 2 ? calcRetracements(pivots) : [];
        const overlaps = rets.length > 0 && zones.length > 0 ? findOverlapSignals(rets, zones) : [];

        // ① ZigZag 선
        if (toggles.zigzag && pivots.length >= 2) {
          const zzData = pivots.map(({ time, value }) => ({ time, value }));
          const zzSeries = chart.addLineSeries({
            color: "#f472b6", lineWidth: 1.5, priceLineVisible: false,
            crosshairMarkerVisible: false, lastValueVisible: false,
          });
          zzSeries.setData(zzData);
        }

        // ② 빗각 (대각 추세선) — 상승/하락 추세선 + 돌파 감지
        if (toggles.trendline && pivots.length >= 4) {
          const tl = calcTrendlines(candleData, pivots);
          if (tl.uptrend && tl.uptrend.length >= 2) {
            const s = chart.addLineSeries({
              color: "#22c55e", lineWidth: 1.5, priceLineVisible: false,
              crosshairMarkerVisible: false, lastValueVisible: false,
              lineStyle: 2,  // Dashed
            });
            s.setData(tl.uptrend);
            // 현재 종가 < 상승 추세선 → 이탈 표시
            if (tl.uptrendVal != null) {
              const lastClose = candleData[candleData.length - 1].close;
              if (lastClose < tl.uptrendVal * 0.998) {
                candleSeries.createPriceLine({ price: tl.uptrendVal, color: "#22c55e44", lineWidth: 1, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title: "빗각↑" });
              }
            }
          }
          if (tl.downtrend && tl.downtrend.length >= 2) {
            const s = chart.addLineSeries({
              color: "#ef4444", lineWidth: 1.5, priceLineVisible: false,
              crosshairMarkerVisible: false, lastValueVisible: false,
              lineStyle: 2,
            });
            s.setData(tl.downtrend);
            if (tl.downtrendVal != null) {
              const lastClose = candleData[candleData.length - 1].close;
              if (lastClose > tl.downtrendVal * 1.002) {
                candleSeries.createPriceLine({ price: tl.downtrendVal, color: "#ef444444", lineWidth: 1, lineStyle: LW.LineStyle.Dashed, axisLabelVisible: true, title: "빗각↓" });
              }
            }
          }
        }

        // ③ 되돌림 레벨 (0.868 포함)
        if (toggles.retracement && rets.length > 0) {
          rets.forEach(ret => {
            candleSeries.createPriceLine({
              price: ret.price,
              color: ret.isKey ? "#06b6d4" : ret.color + "99",
              lineWidth: ret.isKey ? 2 : 1,
              lineStyle: ret.isKey ? LW.LineStyle.Solid : LW.LineStyle.Dashed,
              axisLabelVisible: true,
              title: ret.isKey ? `0.868★` : ret.label,
            });
          });
        }

        // ④ 매물대 (진입/청산/스톱 기준)
        if (toggles.supply && zones.length > 0) {
          zones.forEach(zone => {
            const alpha = Math.round(zone.strength * 160).toString(16).padStart(2, "0");
            const color = `#f59e0b${alpha}`;
            candleSeries.createPriceLine({ price: zone.upper, color, lineWidth: 1, lineStyle: LW.LineStyle.Dotted, axisLabelVisible: false, title: zone.strength > 0.8 ? "매물대" : "" });
            candleSeries.createPriceLine({ price: zone.lower, color, lineWidth: 1, lineStyle: LW.LineStyle.Dotted, axisLabelVisible: false, title: "" });
          });
        }

        // ★ 겹침 신호: 0.868 되돌림 × 매물대 → 강력 진입/청산 포인트
        if ((toggles.retracement || toggles.supply) && overlaps.length > 0) {
          overlaps.forEach(sig => {
            candleSeries.createPriceLine({
              price: sig.price,
              color: sig.isKey ? "#06b6d4" : "#a78bfa",
              lineWidth: 3,
              lineStyle: LW.LineStyle.Solid,
              axisLabelVisible: true,
              title: sig.isKey ? "★0.868+매물대" : `★${(sig.ratio * 100).toFixed(0)}%+매물대`,
            });
          });
        }

        // ⑤ 가짜 돌파
        if (toggles.fakeBreak && candleData.length >= 25) {
          const markers = calcFakeBreakouts(candleData, 20);
          if (markers.length > 0) candleSeries.setMarkers(markers);
        }

        chart.timeScale().fitContent();
        const ro = new ResizeObserver(() => {
          if (containerRef.current && chartRef.current) {
            chartRef.current.resize(containerRef.current.clientWidth, containerRef.current.clientHeight || 320);
          }
        });
        ro.observe(containerRef.current!);
        return () => ro.disconnect();
      } catch (err) {
        console.error("chart error:", err);
        setRenderError("차트를 표시하는 중 오류가 발생했습니다. 다른 종목을 선택하거나 재조회해 주세요.");
      }
    }
    init();
    return () => { if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; } };
  }, [candleData, rows, levels, toggles, indexRows]);

  if (candleData.length < 2) {
    return (
      <div className="flex h-[220px] w-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-slate-700 bg-slate-950/60 p-6 text-center">
        <div className="text-2xl">📊</div>
        <div className="text-sm font-medium text-slate-300">차트 데이터 수집 중</div>
        <div className="text-xs text-slate-500">이 종목의 OHLCV가 아직 수집되지 않았습니다. 상단의 "재조회" 버튼을 눌러 데이터 수집을 시작하거나, 잠시 후 다시 확인해 주세요.</div>
      </div>
    );
  }

  return (
    <div className="relative">
      <div ref={containerRef} className="h-[320px] w-full overflow-hidden rounded-xl sm:h-[380px]" />
      {renderError && (
        <div className="absolute inset-0 flex items-center justify-center rounded-xl border border-amber-500/20 bg-slate-950/90 p-4 text-center text-sm text-amber-100">
          {renderError}
        </div>
      )}
    </div>
  );
}

// ── 호가창 + 투자자 동향 패널 ─────────────────────────────────────────
function OrderbookPanel({ symbol, market }: { symbol: string; market: string }) {
  const [ob, setOb] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [lastFetch, setLastFetch] = useState(0);
  const [investor, setInvestor] = useState<any>(null);
  const [invLoading, setInvLoading] = useState(false);

  async function fetchOb() {
    if (market !== "kr") return;
    setLoading(true);
    try {
      const res = await mone.orderbook({ symbol, market: market as any });
      setOb(res); setLastFetch(Date.now());
    } catch { setOb(null); } finally { setLoading(false); }
  }

  async function fetchInvestor() {
    if (market !== "kr") return;
    setInvLoading(true);
    try {
      const res = await mone.investor({ symbol, market: market as any });
      setInvestor(res);
    } catch { setInvestor(null); } finally { setInvLoading(false); }
  }

  useEffect(() => { setOb(null); setInvestor(null); }, [symbol, market]);

  if (market !== "kr") {
    return (
      <Panel title="호가·수급">
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-400">
          호가창은 국장(KR)만 지원합니다.
        </div>
      </Panel>
    );
  }

  const asks: any[] = ob?.asks ?? [];
  const bids: any[] = ob?.bids ?? [];
  const bidRatio: number | null = ob?.bidRatio ?? null;
  const maxQty = Math.max(...[...asks, ...bids].map((r) => r.qty), 1);

  return (
    <Panel title="호가·수급">
      {/* 버튼 영역 */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <button onClick={fetchOb} disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50">
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          {loading ? "조회 중..." : ob ? "호가 새로고침" : "호가 조회"}
        </button>
        <button onClick={fetchInvestor} disabled={invLoading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-300 hover:bg-blue-500/20 disabled:opacity-50">
          <RefreshCw size={11} className={invLoading ? "animate-spin" : ""} />
          {invLoading ? "조회 중..." : "투자자 동향"}
        </button>
        {lastFetch > 0 && <span className="text-[10px] text-slate-600">{new Date(lastFetch).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>}
      </div>

      {/* 호가창 */}
      {!ob && !loading && <div className="rounded-xl border border-dashed border-slate-700 p-4 text-center text-sm text-slate-500">버튼을 눌러 호가창을 조회하세요.</div>}
      {ob && !ob.ok && <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-300">{ob.error || "호가 조회 실패"}</div>}
      {ob?.ok && (
        <div className="space-y-3">
          {bidRatio !== null && (
            <div>
              <div className="flex justify-between text-[10px] text-slate-500 mb-1">
                <span className="text-red-400">매도 {(100 - bidRatio).toFixed(1)}%</span>
                <span className={`font-mono font-bold ${bidRatio >= 50 ? "text-emerald-400" : "text-red-400"}`}>{bidRatio >= 50 ? "매수세 우위" : "매도세 우위"}</span>
                <span className="text-emerald-400">매수 {bidRatio.toFixed(1)}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-red-900/40">
                <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${bidRatio}%` }} />
              </div>
            </div>
          )}
          <div className="overflow-hidden rounded-xl border border-slate-800">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/60">
                  <th className="py-1.5 pl-3 text-left text-slate-500 font-medium">매도 잔량</th>
                  <th className="py-1.5 text-center text-slate-400 font-medium">호가</th>
                  <th className="py-1.5 pr-3 text-right text-slate-500 font-medium">매수 잔량</th>
                </tr>
              </thead>
              <tbody>
                {[...asks].reverse().slice(0, 5).map((row, i) => (
                  <tr key={`ask-${i}`} className="border-b border-slate-900/50">
                    <td className="py-1 pl-3">
                      <div className="flex items-center gap-1.5">
                        <div className="h-1.5 rounded-sm bg-red-500/50" style={{ width: `${(row.qty / maxQty) * 64}px`, minWidth: "2px" }} />
                        <span className="font-mono text-red-300">{row.qty.toLocaleString()}</span>
                      </div>
                    </td>
                    <td className="py-1 text-center font-mono font-semibold text-slate-200">{row.price.toLocaleString()}</td>
                    <td className="py-1 pr-3 text-right text-slate-700">—</td>
                  </tr>
                ))}
                {bids.slice(0, 5).map((row, i) => (
                  <tr key={`bid-${i}`} className="border-b border-slate-900/50">
                    <td className="py-1 pl-3 text-left text-slate-700">—</td>
                    <td className="py-1 text-center font-mono font-semibold text-slate-200">{row.price.toLocaleString()}</td>
                    <td className="py-1 pr-3">
                      <div className="flex items-center justify-end gap-1.5">
                        <span className="font-mono text-emerald-300">{row.qty.toLocaleString()}</span>
                        <div className="h-1.5 rounded-sm bg-emerald-500/50" style={{ width: `${(row.qty / maxQty) * 64}px`, minWidth: "2px" }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-slate-800 bg-slate-900/40">
                  <td className="py-1.5 pl-3 font-mono text-[10px] text-red-400">{ob.totalAskQty?.toLocaleString()}</td>
                  <td className="py-1.5 text-center text-[10px] text-slate-500">총 잔량</td>
                  <td className="py-1.5 pr-3 text-right font-mono text-[10px] text-emerald-400">{ob.totalBidQty?.toLocaleString()}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}

      {/* 투자자 동향 — 보수적 문구, 데이터 제공 시에만 표시 */}
      {investor?.ok && investor.today && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-semibold text-slate-400">
              투자자별 순매수 ({investor.today.date || "당일"})
            </span>
            <span className="rounded-full border border-slate-700 bg-slate-800 px-2 py-0.5 text-[9px] text-slate-500">
              장중 누적 · 제공 가능 시 표시
            </span>
          </div>
          {investor.signal && investor.signal !== "NEUTRAL" && (
            <div className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold ${
              investor.signal === "STRONG_BUY" ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" :
              investor.signal === "BUY" ? "border-blue-500/40 bg-blue-500/15 text-blue-300" :
              "border-red-500/40 bg-red-500/15 text-red-300"
            }`}>
              {investor.signal === "STRONG_BUY" ? "기관+외국인 동반 순매수" :
               investor.signal === "BUY" ? "기관 또는 외국인 순매수" : "기관+외국인 동반 순매도"}
            </div>
          )}
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            {[
              { label: "기관", qty: investor.today.instQty, amt: investor.today.instAmt },
              { label: "외국인", qty: investor.today.foreignQty, amt: investor.today.foreignAmt },
              { label: "개인", qty: investor.today.indivQty, amt: investor.today.indivAmt },
            ].map(({ label, qty, amt }) => (
              <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/60 p-2 text-center">
                <div className="text-[9px] text-slate-500">{label}</div>
                <div className={`mt-0.5 font-mono font-bold ${(qty ?? 0) > 0 ? "text-emerald-300" : (qty ?? 0) < 0 ? "text-red-400" : "text-slate-400"}`}>
                  {qty != null ? `${qty > 0 ? "+" : ""}${qty.toLocaleString()}` : "—"}
                </div>
                {amt != null && amt !== 0 && (
                  <div className={`text-[9px] font-mono ${amt > 0 ? "text-emerald-600" : "text-red-700"}`}>
                    {amt > 0 ? "+" : ""}{(amt / 1e6).toFixed(0)}백만
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {investor && !investor.ok && (
        <div className="mt-2 rounded-lg border border-slate-700 bg-slate-900 p-2 text-[10px] text-slate-500">
          투자자 데이터 미제공: {investor.error || "조회 실패"}
        </div>
      )}
    </Panel>
  );
}

// ── ATR 기반 관찰 계획 ────────────────────────────────────────────────
function calcAtrPlan(currentPrice: number, atr: number, mode: "conservative"|"balanced"|"aggressive", horizon: "short"|"swing"|"mid") {
  if (!currentPrice || !atr) return null;
  const stopMult  = { conservative: 1.5, balanced: 2.0, aggressive: 2.5 }[mode];
  const tgt1Mult  = { short: 2.0, swing: 3.0, mid: 4.5 }[horizon];
  const tgt2Mult  = { short: 3.0, swing: 5.0, mid: 7.0 }[horizon];
  const entry = Math.round(currentPrice), stop = Math.round(entry - atr * stopMult);
  const target1 = Math.round(entry + atr * tgt1Mult), target2 = Math.round(entry + atr * tgt2Mult);
  const rr1 = (target1 - entry) / (entry - stop), rr2 = (target2 - entry) / (entry - stop);
  return {
    entry, stop, target1, target2, rr1: rr1.toFixed(2), rr2: rr2.toFixed(2),
    stopPct: ((entry - stop) / entry * 100).toFixed(1), tgt1Pct: ((target1 - entry) / entry * 100).toFixed(1),
    split2Price: Math.round(entry - atr * 0.5), split3Price: Math.round(entry - atr * 1.0),
    atr: Math.round(atr),
  };
}

function technicalStance(rows: any[], indicators: any, latestRsi: number | null, atrPlan: ReturnType<typeof calcAtrPlan>) {
  if (rows.length < 20) {
    return {
      label: "판단 대기",
      detail: "OHLCV 20일 이상이 필요합니다.",
      cls: statusTone("neutral"),
    };
  }
  const distance = Number(indicators.distanceToMa20);
  const volumeRatio = Number(indicators.volumeRatio20);
  const rr = atrPlan ? Number(atrPlan.rr1) : 0;
  const rsiValue = latestRsi ?? Number.NaN;
  const bullish = Number.isFinite(distance) && distance > 0 && rsiValue >= 45 && rsiValue <= 68;
  const overheated = rsiValue >= 72 || (Number.isFinite(distance) && distance > 12);
  const weak = Number.isFinite(distance) && distance < -5 && rsiValue < 45;

  if (overheated) {
    return {
      label: "과열 주의",
      detail: "추격 매수보다 눌림·분할 기준 확인이 우선입니다.",
      cls: statusTone("warn"),
    };
  }
  if (bullish && rr >= 1.8) {
    return {
      label: volumeRatio >= 1.2 ? "상승 우위" : "조건부 유효",
      detail: volumeRatio >= 1.2 ? "추세·거래량·손익비가 같이 맞습니다." : "추세와 손익비는 양호하나 거래량 확인이 필요합니다.",
      cls: statusTone("ok"),
    };
  }
  if (weak) {
    return {
      label: "방어 우선",
      detail: "MA20 하회와 약한 RSI 구간입니다.",
      cls: statusTone("bad"),
    };
  }
  return {
    label: "중립 관찰",
    detail: "기준가 터치, 거래량, 공시 이벤트를 같이 확인하세요.",
    cls: statusTone("neutral"),
  };
}

// ── 메인 ─────────────────────────────────────────────────────────────
export default function ChartPage() {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [levels, setLevels] = useState<any | null>(null);
  const [news, setNews] = useState<any[]>([]);
  const [disclosures, setDisclosures] = useState<any[]>([]);
  const [company, setCompany] = useState<any | null>(null);
  const [toggles, setToggles] = useState<Record<ToggleKey, boolean>>({
    ma5: true, ma20: true, ma60: false, bb: false, volume: true, rsi: true, macd: false, index: true,
    zigzag: false, trendline: false, retracement: false, supply: false, fakeBreak: false,
  });
  const [period, setPeriod] = useState<number | null>(126);
  const [indexRows, setIndexRows] = useState<any[]>([]);
  const [atrMode, setAtrMode] = useState<"conservative"|"balanced"|"aggressive">("balanced");
  const [atrHorizon, setAtrHorizon] = useState<"short"|"swing"|"mid">("swing");
  const [loading, setLoading] = useState(false);
  const [seedLoading, setSeedLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [loadState, setLoadState] = useState<ChartLoadState>({
    ohlcvStatus: "IDLE",
    ohlcvCount: 0,
    recStatus: "IDLE",
    recCount: 0,
    newsCount: 0,
    disclosureCount: 0,
    companyStatus: "IDLE",
    errors: [],
    updatedAt: "",
    recoDate: "",
  });

  function readStoredChartSymbol(): MoneSymbol | null {
    if (typeof window === "undefined") return null;
    const symbol = normalizeSymbol({ symbol: window.localStorage.getItem("mone_chart_symbol") || "" });
    if (!symbol) return null;
    const storedMarket = normalizeMarket(window.localStorage.getItem("mone_chart_market"), symbol) as Market;
    const name = window.localStorage.getItem("mone_chart_name") || symbol;
    const currentPrice = window.localStorage.getItem("mone_chart_price") || null;
    const currentPriceText = window.localStorage.getItem("mone_chart_price_text") || "";
    return {
      id: `${storedMarket}-${symbol}`,
      symbol,
      name,
      market: storedMarket,
      label: `${name} (${symbol})`,
      isWatch: true,
      currentPrice,
      currentPriceText,
    };
  }

  useEffect(() => {
    const picked = readStoredChartSymbol();
    if (picked) {
      setMarket(picked.market);
      setSelected(picked);
    }
    const onOpenChart = () => {
      const next = readStoredChartSymbol();
      if (next) {
        setMarket(next.market);
        setSelected(next);
      }
    };
    window.addEventListener("mone-open-chart", onOpenChart);
    return () => window.removeEventListener("mone-open-chart", onOpenChart);
  }, []);

  useEffect(() => {
    let active = true;
    if (selected) return;
    async function seed() {
      setSeedLoading(true);
      try {
        let picked: MoneSymbol | null = null;
        try {
          const holdings = await mone.holdingsClean({ market, limit: 20 });
          if (!active) return;
          picked = Array.isArray(holdings.items) ? (holdings.items.map(toSymbol).find(Boolean) ?? null) : null;
        } catch { /* try recommendations next */ }
        if (!active) return;
        if (!picked) {
          try {
            const rec = await mone.recommendations({ market, mode: "balanced", horizon: "swing", limit: 20 });
            if (!active) return;
            picked = Array.isArray(rec.items) ? (rec.items.map(toSymbol).find(Boolean) ?? null) : null;
          } catch { /* use fallback */ }
        }
        if (active) setSelected(picked ?? fallbackSymbol(market));
      } finally { if (active) setSeedLoading(false); }
    }
    seed();
    return () => { active = false; };
  }, [market, selected]);

  useEffect(() => {
    if (!selected) { setRows([]); setLevels(null); setNews([]); setDisclosures([]); setCompany(null); return; }
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setLoadState((prev) => ({ ...prev, errors: [], updatedAt: "" }));
    Promise.allSettled([
      mone.ohlcv({ market: selected.market, symbol: selected.symbol, limit: 260 }, controller.signal),
      mone.recommendationDetail({ market: selected.market, symbol: selected.symbol }, controller.signal),
      mone.news({ market: selected.market, limit: 200 }, controller.signal),
      mone.disclosures({ market: selected.market, limit: 200, watchOnly: false }, controller.signal),
      withTimeout(mone.companyAnalysis({ market: selected.market, q: selected.symbol, limit: 20 }, controller.signal), 15000, { status: "TIMEOUT", items: [] }),
    ]).then((results) => {
      if (!active) return;
      const [cd, rd, nd, dd, company_d] = results.map((r) => r.status === "fulfilled" ? r.value : { items: [] }) as any[];
      const chartRows = Array.isArray(cd.items) ? cd.items : [];
      const recItems = Array.isArray(rd.items) ? rd.items : [];
      const newsItems = Array.isArray(nd.items) ? nd.items : [];
      const disclosureItems = Array.isArray(dd.items) ? dd.items : [];
      const errors = [cd, rd, nd, dd, company_d]
        .map((item: any) => item?.status === "ERROR" ? item.error || "API 오류" : "")
        .filter(Boolean);
      setRows(chartRows);
      const detailItem = rd?.item || recItems.find((item: any) => normalizeSymbol(item) === selected.symbol) || null;
      const matched = detailItem && normalizeSymbol(detailItem) === selected.symbol ? detailItem : null;
      setLevels(matched || null);
      const displayNews = relatedItems(newsItems, selected);
      const displayDisclosures = relatedItems(disclosureItems, selected);
      setNews(displayNews);
      setDisclosures(displayDisclosures);
      const cm = Array.isArray(company_d.items) ? company_d.items.find((item: any) => normalizeSymbol(item) === selected.symbol) || company_d.items[0] : null;
      const fallbackCompany = companyFallback(matched);
      setCompany(cm || fallbackCompany);
      // 추천 생성일: dataHealth.recoGeneratedAt (날짜 부분만)
      const recoDate = String(rd?.item?.generatedAt || rd?.generatedAt || rd?.dataHealth?.recoGeneratedAt || "").slice(0, 10);
      setLoadState({
        ohlcvStatus: cd.status || (chartRows.length ? "OK" : "NO_DATA"),
        ohlcvCount: chartRows.length,
        recStatus: rd.status || (matched ? "OK" : "NO_DATA"),
        recCount: Number(rd.count ?? recItems.length ?? (matched ? 1 : 0)),
        newsCount: displayNews.length,
        disclosureCount: displayDisclosures.length,
        companyStatus: company_d.status || (cm ? (cm.dataStatus || "OK") : fallbackCompany ? "REPORT_FALLBACK" : "NO_DATA"),
        errors,
        updatedAt: new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        recoDate,
      });
    }).finally(() => active && setLoading(false));
    return () => { active = false; controller.abort(); };
  }, [selected, reloadKey]);

  // 지수 비교 데이터 (날짜 기반 join)
  useEffect(() => {
    if (!selected) { setIndexRows([]); return; }
    const controller = new AbortController();
    const indexSym = selected.market === "us" ? "SPY" : "KOSPI";
    mone.chartIndex({ indexSymbol: indexSym, market: selected.market as any, limit: 520 }, controller.signal)
      .then((d) => setIndexRows(Array.isArray(d.items) ? d.items : []))
      .catch(() => setIndexRows([]));
    return () => controller.abort();
  }, [selected?.symbol, selected?.market]);

  const filteredRows = period ? rows.slice(-period) : rows;
  const latest = rows.at(-1);
  const indicators = derivedIndicators(rows, latest, levels?.indicators || {});
  const latestRsi = positiveNum(latest?.rsi) ?? indicators.rsi14 ?? rsi(rows.map(closeOf).filter(Boolean));
  const currentPrice = positiveNum(latest?.close) || positiveNum(latest?.Close) || levelValue(levels, "entry") || 0;
  const atrValue = (() => {
    const recent = rows.slice(-14);
    if (recent.length < 5) return indicators.atr14 || 0;
    const trs = recent.map((r, i) => {
      if (i === 0) return highOf(r) - lowOf(r);
      const prev = recent[i - 1];
      return Math.max(highOf(r) - lowOf(r), Math.abs(highOf(r) - closeOf(prev)), Math.abs(lowOf(r) - closeOf(prev)));
    });
    return trs.reduce((s, v) => s + v, 0) / trs.length;
  })();
  const atrPlan = atrValue > 0 && currentPrice > 0 ? calcAtrPlan(currentPrice, atrValue, atrMode, atrHorizon) : null;
  const stance = technicalStance(rows, indicators, latestRsi ?? null, atrPlan);
  const freshness = freshnessInfo(rows);
  const touchReview = recommendationTouchReview(rows, levels, currentPrice, selected?.market || market, loadState.recoDate || undefined);
  const dataCards = [
    { label: "OHLCV", value: `${loadState.ohlcvCount}봉`, sub: `${loadStatusText(loadState.ohlcvStatus)} · ${freshness.label}`, cls: loadState.ohlcvCount >= 20 ? freshness.cls : loadState.ohlcvCount > 0 ? statusTone("warn") : statusTone("bad") },
    { label: "추천선", value: levels ? "연결됨" : "없음", sub: `${loadState.recCount}개 후보 검색`, cls: levels ? statusTone("ok") : statusTone("warn") },
    { label: "뉴스·공시", value: `${loadState.newsCount}건 · ${loadState.disclosureCount}건`, sub: "선택 종목 관련", cls: coverageTone(loadState.newsCount + loadState.disclosureCount) },
    {
      label: "기업분석",
      value: String(loadState.companyStatus || "").toUpperCase() === "TIMEOUT" ? "시간초과" : company?.dataStatus === "SOURCE_CONTEXT" || company?.dataStatus === "REPORT_FALLBACK" ? "보조" : company ? "연결됨" : "없음",
      sub: String(loadState.companyStatus || "").toUpperCase() === "TIMEOUT" ? "기업분석 API 응답 지연" : company?.dataStatus === "SOURCE_CONTEXT" || company?.dataStatus === "REPORT_FALLBACK" ? "추천 원본 기준" : loadStatusText(loadState.companyStatus),
      cls: String(loadState.companyStatus || "").toUpperCase() === "TIMEOUT" || company?.dataStatus === "SOURCE_CONTEXT" || company?.dataStatus === "REPORT_FALLBACK" ? statusTone("warn") : company ? statusTone("ok") : statusTone("warn"),
    },
  ];

  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-bold text-slate-100 sm:text-2xl">차트·기술분석</h1>
        <p className="mt-1 text-xs text-slate-400 sm:text-sm">OHLCV, 추천 기준선, 기술지표, 관련 뉴스·공시·기업분석</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(["kr","us","all"] as Market[]).map((item) => (
          <button key={item} onClick={() => { setMarket(item); setSelected(null); }}
            className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {marketLabel(item)}
          </button>
        ))}
        <span className="text-xs text-slate-500">기본값: {marketLabel(getDefaultMarketBySession())}</span>
      </div>

      <SymbolSearchSelect market={market} value={selected?.symbol || ""} onChange={setSelected} />

      {!selected && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
          {seedLoading ? "기본 종목을 불러오는 중..." : "종목명 또는 코드로 검색하세요."}
        </div>
      )}

      {selected && (
        <div className="space-y-5">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
            <div className="mb-4 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h2 className="text-xl font-bold text-slate-100">{selected.name}</h2>
                <p className="font-mono text-sm text-slate-500">{selected.symbol} · {selected.market.toUpperCase()}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className={`rounded-xl border px-3 py-1.5 text-xs font-bold ${stance.cls}`}>{stance.label}</span>
                  <span className="text-xs text-slate-500">{stance.detail}</span>
                  {loadState.updatedAt && <span className="text-[11px] text-slate-600">갱신 {loadState.updatedAt}</span>}
                  <button
                    onClick={() => setReloadKey((v) => v + 1)}
                    disabled={loading}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                  >
                    <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
                    재조회
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-right sm:grid-cols-4">
                <Info label="최근 종가" value={latest ? money(latest.close, selected.market) : "-"} />
                <Info label="RSI14" value={latestRsi ? Number(latestRsi).toFixed(1) : "데이터 부족"} />
                <Info label="ATR14" value={indicators.atr14 ? money(indicators.atr14, selected.market) : "추가 데이터 필요 · 최소 14봉 필요"} />
                <Info label="MDD20" value={indicators.mdd20 ? `${Number(indicators.mdd20).toFixed(2)}%` : "추가 데이터 필요 · 최소 20봉 필요"} />
              </div>
            </div>

            <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-5">
              {dataCards.map((card) => (
                <div key={card.label} className={`rounded-xl border px-3 py-2 ${card.cls}`}>
                  <div className="text-[10px] font-semibold uppercase tracking-wide opacity-80">{card.label}</div>
                  <div className="mt-1 font-mono text-sm font-bold">{card.value}</div>
                  <div className="text-[10px] opacity-75">{card.sub}</div>
                </div>
              ))}
            </div>
            {loadState.errors.length > 0 && (
              <div className="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-300">
                일부 데이터 API 오류: {loadState.errors.slice(0, 2).join(" / ")}
              </div>
            )}
            <div className="mb-4 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-slate-200">추천선 터치 검증</div>
                  <div className="mt-1 text-xs text-slate-500">{touchReview.detail}</div>
                </div>
                <span className={`rounded-xl border px-3 py-1.5 text-xs font-bold ${touchReview.cls}`}>{touchReview.label}</span>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                {touchReview.cards.map((card) => (
                  <div key={card.label} className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                    <div className="text-[10px] text-slate-500">{card.label}</div>
                    <div className="mt-1 break-words font-mono text-sm font-bold text-slate-100">{card.value}</div>
                    <div className="text-[10px] text-slate-600">{card.sub}</div>
                  </div>
                ))}
              </div>
              <div className="mt-2 text-[10px] text-slate-600">
                OHLCV 최근일: {freshness.detail}
                {loadState.recoDate && <span className="ml-3 text-violet-400/70">추천 생성: {loadState.recoDate.slice(0, 10)}</span>}
              </div>
            </div>

            {/* 기간 필터 + 인디케이터 토글 */}
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <div className="flex gap-1 rounded-lg border border-slate-800 bg-slate-950 p-0.5">
                {PERIODS.map(({ label, bars }) => (
                  <button key={label} onClick={() => setPeriod(bars)}
                    className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${period === bars ? "bg-blue-600 text-white" : "text-slate-400 hover:text-slate-200"}`}>
                    {label}
                  </button>
                ))}
              </div>
              <span className="text-slate-700">|</span>
              {([
                ["ma5","MA5","#2dd4bf"],["ma20","MA20","#facc15"],["ma60","MA60","#f97316"],
                ["bb","BB","#a855f7"],["volume","거래량","#64748b"],["rsi","RSI","#38bdf8"],
                ["macd","MACD","#f97316"],
                ["index", selected?.market === "us" ? "vs SPY" : "vs KOSPI", "#94a3b8"],
                ["zigzag",    "ZigZag", "#f472b6"],
                ["trendline", "빗각",   "#22c55e"],
                ["retracement","되돌림","#06b6d4"],
                ["supply",    "매물대", "#f59e0b"],
                ["fakeBreak", "가짜돌파","#ef4444"],
              ] as [ToggleKey, string, string][]).map(([key, label, color]) => (
                <button key={key} onClick={() => setToggles((prev) => ({ ...prev, [key]: !prev[key] }))}
                  className={`rounded-lg border px-3 py-1.5 text-xs font-medium ${toggles[key] ? "border-current bg-slate-900" : "border-slate-800 bg-slate-950 text-slate-600"}`}
                  style={toggles[key] ? { color, borderColor: color + "66" } : {}}>
                  {label}
                </button>
              ))}
            </div>

            {loading && <div className="py-20 text-center text-slate-500">차트 데이터를 불러오는 중...</div>}
            {!loading && rows.length === 0 && (
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-6 text-amber-100">
                <div className="font-semibold">OHLCV 원본이 없어 차트를 그릴 수 없습니다.</div>
                <div className="mt-1 text-sm text-amber-200/80">
                  추천선·뉴스·기업분석은 별도 원본이므로 위 상태판에서 연결 여부를 확인하세요. 가격 수집은 GitHub Actions 또는 KIS/시세 수집 실행 후 복구됩니다.
                </div>
                {selected?.market === "kr" && (
                  <div className="mt-2 text-xs text-amber-300/70">
                    국장 OHLCV: <code className="font-mono">data/market/ohlcv/kr_{selected.symbol}_daily.csv</code> 파일 확인 필요.
                    탐색 → 현재가 새로고침을 누르면 KIS API로 자동 수집됩니다.
                  </div>
                )}
              </div>
            )}

            {!loading && rows.length > 0 && (
              <div className="space-y-2">
                <div className="rounded-xl border border-slate-800 bg-[#020617] p-2">
                  <TvChart rows={filteredRows} levels={levels} market={selected.market} toggles={toggles} indexRows={indexRows} />
                  <div className="mt-2 flex flex-wrap gap-3 px-2 text-xs text-slate-500">
                    <span>봉: {filteredRows.length}개 (전체 {rows.length})</span>
                    <span>최근: {latest?.date || "-"}</span>
                    <span className="ml-auto flex gap-3">
                      {toggles.ma5  && <span style={{ color: "#2dd4bf" }}>━ MA5</span>}
                      {toggles.ma20 && <span style={{ color: "#facc15" }}>━ MA20</span>}
                      {toggles.ma60 && <span style={{ color: "#f97316" }}>━ MA60</span>}
                      {toggles.bb   && <span style={{ color: "#a855f7" }}>- - BB</span>}
                      {toggles.index && <span className="text-slate-500">- - {selected.market === "us" ? "SPY" : "KOSPI"}</span>}
                      {toggles.zigzag     && <span style={{ color: "#f472b6" }}>━ ZigZag</span>}
                      {toggles.trendline  && <span style={{ color: "#22c55e" }}>╌ 빗각</span>}
                      {toggles.retracement && <span style={{ color: "#06b6d4" }}>── 0.868</span>}
                      {toggles.supply     && <span style={{ color: "#f59e0b" }}>··· 매물대</span>}
                      {toggles.fakeBreak  && <span style={{ color: "#ef4444" }}>▼ 가짜돌파</span>}
                      {levels && <><span style={{ color: "#22c55e" }}>-- 기준</span><span style={{ color: "#ef4444" }}>-- 손절</span><span style={{ color: "#06b6d4" }}>-- 목표</span></>}
                    </span>
                  </div>
                </div>
                {toggles.rsi  && <RsiChart rows={filteredRows} />}
                {toggles.macd && <MacdChart rows={filteredRows} />}
                <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
                  <Info label="기준가" value={levels && levelValue(levels,"base") ? money(levelValue(levels,"base"), selected.market) : "-"} />
                  <Info label="기준가" value={levels ? priceText(levels,"entry","-") : "-"} />
                  <Info label="손절가" value={levels ? priceText(levels,"stop","-") : "-"} />
                  <Info label="목표가" value={levels ? priceText(levels,"target","-") : "-"} />
                  <Info label="예상가" value={levels ? priceText(levels,"expected","-") : "-"} />
                </div>
              </div>
            )}
          </div>

          {/* ATR 관찰 계획 */}
          <div className="rounded-2xl border border-blue-900/50 bg-blue-950/10 p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold text-slate-100">ATR 기반 관찰 계획</h3>
                <p className="text-xs text-slate-500">ATR(14) = {atrValue > 0 ? money(Math.round(atrValue), selected.market) : "데이터 부족"} · 분할매수 50/30/20</p>
              </div>
              <div className="flex gap-2">
                {(["conservative","balanced","aggressive"] as const).map((m) => (
                  <button key={m} onClick={() => setAtrMode(m)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium ${atrMode === m ? "bg-blue-600 text-white" : "border border-slate-700 text-slate-400 hover:bg-slate-800"}`}>
                    {m === "conservative" ? "보수" : m === "balanced" ? "균형" : "공격"}
                  </button>
                ))}
                <span className="text-slate-700">|</span>
                {(["short","swing","mid"] as const).map((h) => (
                  <button key={h} onClick={() => setAtrHorizon(h)}
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium ${atrHorizon === h ? "bg-blue-600 text-white" : "border border-slate-700 text-slate-400 hover:bg-slate-800"}`}>
                    {h === "short" ? "단기" : h === "swing" ? "스윙" : "중기"}
                  </button>
                ))}
              </div>
            </div>
            {atrPlan ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                  {[
                    { label: "1차 관찰 기준 (50%)", value: money(atrPlan.entry, selected.market), color: "text-emerald-300", sub: "현재가 기준" },
                    { label: "2차 관찰 기준 (30%)", value: money(atrPlan.split2Price, selected.market), color: "text-sky-300", sub: `-${(atrPlan.atr * 0.5 / atrPlan.entry * 100).toFixed(1)}%` },
                    { label: "3차 관찰 기준 (20%)", value: money(atrPlan.split3Price, selected.market), color: "text-violet-300", sub: `-${(atrPlan.atr / atrPlan.entry * 100).toFixed(1)}%` },
                    { label: "손절가", value: money(atrPlan.stop, selected.market), color: "text-red-300", sub: `-${atrPlan.stopPct}%` },
                  ].map(({ label, value, color, sub }) => (
                    <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                      <div className="text-xs text-slate-500">{label}</div>
                      <div className={`mt-1 font-mono font-bold ${color}`}>{value}</div>
                      <div className="text-[10px] text-slate-600">{sub}</div>
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                  {[
                    { label: `1차 목표 (+${atrPlan.tgt1Pct}%)`, value: money(atrPlan.target1, selected.market), color: "text-cyan-300", sub: `RR ${atrPlan.rr1}` },
                    { label: "2차 목표", value: money(atrPlan.target2, selected.market), color: "text-emerald-300", sub: `RR ${atrPlan.rr2}` },
                    { label: "ATR 단위", value: money(atrPlan.atr, selected.market), color: "text-slate-300", sub: "14일 평균 변동폭" },
                    { label: "목표1 손익비", value: `1 : ${atrPlan.rr1}`, color: Number(atrPlan.rr1) >= 1.8 ? "text-emerald-400" : "text-amber-400", sub: Number(atrPlan.rr1) >= 1.8 ? "기준 충족" : "기준 미달 (1.8↑)" },
                  ].map(({ label, value, color, sub }) => (
                    <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                      <div className="text-xs text-slate-500">{label}</div>
                      <div className={`mt-1 font-mono font-bold ${color}`}>{value}</div>
                      <div className="text-[10px] text-slate-600">{sub}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-700 p-6 text-center text-sm text-slate-500">ATR 데이터 부족 (OHLCV 30일 이상 필요)</div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Panel title="고급 기술지표">
              <Info label="MA20 이격도" value={indicators.distanceToMa20 != null ? `${Number(indicators.distanceToMa20).toFixed(2)}%` : "데이터 부족"} />
              <Info label="볼린저 %B" value={indicators.bbPercentB != null ? Number(indicators.bbPercentB).toFixed(2) : "데이터 부족"} />
              <Info label="20일 거래량비" value={indicators.volumeRatio20 != null ? `${Number(indicators.volumeRatio20).toFixed(2)}x` : "데이터 부족"} />
              <Info label="52주 고점 이격" value={indicators.distanceTo52wHigh != null ? `${Number(indicators.distanceTo52wHigh).toFixed(2)}%` : "데이터 부족"} />
            </Panel>

            <OrderbookPanel symbol={selected.symbol} market={selected.market} />

            <Panel title="거래량·모멘텀 분석">
              {rows.length >= 20 ? (() => {
                const r20 = rows.slice(-20).map((r: any) => Number(r.volume || r.Volume || 0));
                const r5  = rows.slice(-5).map((r: any)  => Number(r.volume || r.Volume || 0));
                const avg20 = r20.reduce((a: number, b: number) => a + b, 0) / r20.length;
                const avg5  = r5.reduce((a: number, b: number)  => a + b, 0) / r5.length;
                const ratio = avg20 > 0 ? avg5 / avg20 : 0;
                const maxVol = Math.max(...r20);
                const c5d = rows.slice(-6).map(closeOf); const ret5d = c5d.length >= 2 ? ((c5d.at(-1)! - c5d[0]) / c5d[0]) * 100 : 0;
                const c20d = rows.slice(-21).map(closeOf); const ret20d = c20d.length >= 2 ? ((c20d.at(-1)! - c20d[0]) / c20d[0]) * 100 : 0;
                return (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <div className="text-[10px] text-slate-500">5일 거래량비 (vs 20일 평균)</div>
                        <div className={`mt-1 font-mono text-sm font-bold ${ratio >= 1.5 ? "text-emerald-300" : ratio <= 0.5 ? "text-red-400" : "text-slate-300"}`}>{ratio.toFixed(2)}x</div>
                        <div className="text-[10px] text-slate-600">{ratio >= 1.5 ? "거래 급증" : ratio >= 1.0 ? "평균 이상" : "거래 감소"}</div>
                      </div>
                      <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <div className="text-[10px] text-slate-500">5일 / 20일 수익률</div>
                        <div className={`mt-1 font-mono text-sm font-bold ${ret5d >= 0 ? "text-emerald-300" : "text-red-400"}`}>{ret5d >= 0 ? "+" : ""}{ret5d.toFixed(1)}%</div>
                        <div className={`text-[10px] ${ret20d >= 0 ? "text-emerald-600" : "text-red-600"}`}>20일: {ret20d >= 0 ? "+" : ""}{ret20d.toFixed(1)}%</div>
                      </div>
                    </div>
                    <div>
                      <div className="mb-1 text-[10px] text-slate-500">최근 20일 거래량</div>
                      <div className="flex h-12 items-end gap-px">
                        {r20.map((vol: number, i: number) => (
                          <div key={i} className={`flex-1 rounded-sm ${i >= 15 ? "bg-blue-500/70" : "bg-slate-700/60"}`}
                            style={{ height: `${Math.max(4, maxVol > 0 ? (vol / maxVol) * 100 : 0)}%` }} />
                        ))}
                      </div>
                      <div className="mt-1 flex justify-between text-[10px] text-slate-600"><span>20일 전</span><span>최근 5일</span><span>오늘</span></div>
                    </div>
                  </div>
                );
              })() : <div className="text-sm text-slate-500">OHLCV 20일 이상 필요합니다.</div>}
            </Panel>

            <Panel title={`기업분석${company?.hasDartData ? ` · DART ${company.dartYear || ""}` : ""}`}>
              {company ? (
                <>
                  <div className="mb-3 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2 text-xs text-slate-300">
                    {companyOneLine(company)}
                  </div>
                  <div className="grid grid-cols-3 gap-2 mb-2">
                    {[{ label: "PER", value: company.per }, { label: "PBR", value: company.pbr }, { label: "PEG", value: company.peg }].map(({ label, value }) => (
                      <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/60 p-2 text-center">
                        <div className="text-[10px] text-slate-500">{label}</div>
                        <div className={`mt-0.5 font-mono text-sm font-bold ${label === "PEG" && value && Number(value) < 1.0 ? "text-emerald-400" : label === "PEG" && value && Number(value) > 2.0 ? "text-red-400" : "text-slate-100"}`}>
                          {value && !String(value).includes("데이터 없음") ? Number(value).toFixed(2) : "-"}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="grid grid-cols-3 gap-2 mb-2">
                    {[
                      { label: "ROE", value: company.roe, suffix: "%", good: (v: number) => v >= 15, bad: (v: number) => v < 5 },
                      { label: "부채비율", value: company.debtRatio, suffix: "%", good: (v: number) => v < 100, bad: (v: number) => v > 200 },
                      { label: "영업이익률", value: company.operatingMargin, suffix: "%", good: (v: number) => v >= 15, bad: (v: number) => v < 5 },
                    ].map(({ label, value, suffix, good, bad }) => {
                      const n = value ? Number(value) : null;
                      return (
                        <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/60 p-2 text-center">
                          <div className="text-[10px] text-slate-500">{label}</div>
                          <div className={`mt-0.5 font-mono text-sm font-bold ${n !== null && !isNaN(n) ? (good(n) ? "text-emerald-400" : bad(n) ? "text-red-400" : "text-slate-100") : "text-slate-600"}`}>
                            {n !== null && !isNaN(n) ? `${n.toFixed(1)}${suffix}` : "-"}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {[{ label: "매출 성장률", value: company.revenueGrowth }, { label: "EPS 성장률", value: company.epsGrowth }].map(({ label, value }) => {
                      const n = value ? Number(value) : null;
                      return (
                        <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/60 p-2">
                          <div className="text-[10px] text-slate-500">{label}</div>
                          <div className={`mt-0.5 font-mono text-sm font-bold ${n !== null && !isNaN(n) ? (n >= 15 ? "text-emerald-400" : n >= 0 ? "text-slate-300" : "text-red-400") : "text-slate-600"}`}>
                            {n !== null && !isNaN(n) ? `${n >= 0 ? "+" : ""}${n.toFixed(1)}%` : "-"}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  {company.peg && Number(company.peg) < 1.0 && Number(company.roe) >= 15 && (
                    <div className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
                      저평가 성장주 — PEG {Number(company.peg).toFixed(2)} · ROE {Number(company.roe).toFixed(1)}%
                    </div>
                  )}
                  {!company.hasDartData && <div className="mt-2 text-[10px] text-slate-600">DART 재무 데이터 수집 대기 (매주 월요일 자동 갱신)</div>}
                </>
              ) : loading ? (
                <div className="text-sm text-slate-500">불러오는 중...</div>
              ) : (
                <div className="space-y-2 text-sm text-slate-500">
                  <div>
                    기업분석 데이터 없음 —{" "}
                    {loadState.companyStatus === "TIMEOUT"
                      ? "조회 시간 초과입니다."
                      : "DART / Finnhub 수집 후 자동으로 연결됩니다."}
                  </div>
                  {loadState.companyStatus === "TIMEOUT" && (
                    <button
                      onClick={() => setReloadKey((v) => v + 1)}
                      disabled={loading}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                    >
                      <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
                      재조회
                    </button>
                  )}
                </div>
              )}
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {!loading && news.length === 0 && disclosures.length === 0 ? (
              <div className="lg:col-span-2">
                <Panel title="뉴스·공시">
                  <Empty text="뉴스 0건 · 공시 0건입니다. 뉴스는 장전·장후, 공시는 주기적으로 자동 수집됩니다." />
                </Panel>
              </div>
            ) : (
              <>
                <Panel title="관련 뉴스">
                  {loading
                    ? <Empty text="데이터 확인 중..." />
                    : news.length === 0
                      ? <Empty text="뉴스 0건" />
                      : <div className="space-y-2">{news.map((item, i) => <Related key={`news-${i}`} item={item} />)}</div>}
                </Panel>
                <Panel title="관련 공시 (DART)">
                  {loading
                    ? <Empty text="데이터 확인 중..." />
                    : disclosures.length === 0
                      ? (
                        <div className="space-y-2">
                          <Empty text="공시 0건" />
                          {selected && (
                            <a
                              href={`https://dart.fss.or.kr/dsab007/main.do`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-sky-400 hover:bg-slate-800 transition-colors"
                            >
                              <span>DART 전자공시 바로가기 →</span>
                            </a>
                          )}
                        </div>
                      )
                      : <div className="space-y-2">{disclosures.map((item, i) => <Related key={`disc-${i}`} item={item} />)}</div>}
                </Panel>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-1 break-words font-mono font-semibold text-slate-100">{value}</div>
    </div>
  );
}
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-3 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
      <div className="text-sm font-semibold text-slate-200">{title}</div>
      {children}
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-slate-800 p-4 text-sm text-slate-500">{text}</div>;
}
function formatKoreanDate(raw: string): string {
  if (!raw) return "";
  const s = String(raw).replace(/[^0-9]/g, "");
  if (s.length === 8) return `${s.slice(0,4)}.${s.slice(4,6)}.${s.slice(6,8)}`;
  const d = raw.slice(0, 10);
  return d || raw;
}

function Related({ item }: { item: any }) {
  const title = item.title || item.reportName || item.headline || item.summary || "제목 없음";
  const rawDate = item.date || item.publishedAt || item.disclosedAt || "";
  const date = formatKoreanDate(rawDate);
  const link = item.url || item.link || item.articleUrl || "";
  const source = item.source || item.sourceName || item.publisher || "";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 space-y-1.5">
      <div className="line-clamp-2 text-sm font-medium text-slate-100 leading-snug">{title}</div>
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs text-slate-500">
          {source && <span className="text-slate-400">{source}</span>}
          {source && date && <span className="mx-1 text-slate-700">·</span>}
          {date && <span>{date}</span>}
        </div>
        {link ? (
          <a
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="shrink-0 rounded-lg border border-slate-700 bg-slate-800 px-2 py-0.5 text-[10px] text-sky-400 hover:bg-slate-700 hover:text-sky-300 transition-colors"
          >
            원문 →
          </a>
        ) : (
          <span className="shrink-0 text-[10px] text-slate-600">링크 없음</span>
        )}
      </div>
    </div>
  );
}
