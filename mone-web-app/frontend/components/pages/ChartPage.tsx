"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { RefreshCw } from "lucide-react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, money, type Market } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { displayName, normalizeMarket, normalizeSymbol, priceText } from "@/lib/moneDisplay";

type ToggleKey = "ma5" | "ma20" | "ma60" | "bb" | "volume" | "rsi" | "macd" | "index";

const PERIODS: { label: string; bars: number | null }[] = [
  { label: "1M", bars: 21 },
  { label: "3M", bars: 63 },
  { label: "6M", bars: 126 },
  { label: "1Y", bars: 252 },
  { label: "전체", bars: null },
];

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
    atr14: positiveNum(recInd?.atr14 ?? latest?.atr14 ?? latest?.ATR14),
    mdd20: positiveNum(recInd?.mdd20 ?? latest?.mdd20 ?? latest?.MDD20),
    distanceToMa20: recInd?.distanceToMa20 ?? (close && ma20 ? ((close - ma20) / ma20) * 100 : null),
    bbPercentB: recInd?.bbPercentB ?? (close && bbUpper && bbLower && bbUpper !== bbLower ? (close - bbLower) / (bbUpper - bbLower) : null),
    volumeRatio20: recInd?.volumeRatio20 ?? (latestVol && volAvg20 ? latestVol / volAvg20 : null),
    distanceTo52wHigh: recInd?.distanceTo52wHigh ?? (close && high52w ? ((close - high52w) / high52w) * 100 : null),
  };
}

function relatedItems(items: any[], selected: MoneSymbol | null) {
  if (!selected) return [];
  const query = `${selected.symbol} ${selected.name}`.toLowerCase();
  return items.filter((item) => {
    const text = [item.symbol, item.name, item.company, item.title, item.reportName, item.summary].filter(Boolean).join(" ").toLowerCase();
    return query.split(" ").some((p) => p && text.includes(p));
  }).slice(0, 4);
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
    const closes = rows.map(closeOf).filter((v) => v > 0);
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
      const row = rows[i]; const date = row?.date || row?.Date;
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
    const dates = rows.slice(-macdLine.length).map((r: any) => r.date || r.Date).filter(Boolean);
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

// ── TvChart (캔들 + 지수 비교선) ─────────────────────────────────────
function TvChart({ rows, levels, market, toggles, indexRows = [] }: {
  rows: any[]; levels: any; market: string;
  toggles: Record<ToggleKey, boolean>; indexRows?: any[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || rows.length === 0) return;
    async function init() {
      try {
        const LW = await import("lightweight-charts");
        if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }
        const chartRaw = LW.createChart(containerRef.current!, {
          width: containerRef.current!.clientWidth, height: 380,
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
        const candleData = rows.filter((r) => r.date || r.Date)
          .map((r) => ({ time: (r.date || r.Date) as string, open: Number(r.open || r.Open || r.close || r.Close) || 0, high: Number(r.high || r.High || r.close || r.Close) || 0, low: Number(r.low || r.Low || r.close || r.Close) || 0, close: Number(r.close || r.Close) || 0 }))
          .filter((d) => d.close > 0).sort((a, b) => a.time < b.time ? -1 : 1);
        candleSeries.setData(candleData);

        if (toggles.volume) {
          const volSeries = chart.addHistogramSeries({ color: "#334155", priceFormat: { type: "volume" }, priceScaleId: "volume" });
          chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
          volSeries.setData(candleData.map((d, i) => ({ time: d.time, value: Number((rows[i] || {}).volume || (rows[i] || {}).Volume || 0), color: d.close >= d.open ? "#16a34a55" : "#dc262655" })));
        }

        const closes = candleData.map((d) => d.close);
        const calcMA = (period: number) => candleData.map((d, i) => {
          if (i < period - 1) return null;
          return { time: d.time, value: closes.slice(i - period + 1, i + 1).reduce((s, v) => s + v, 0) / period };
        }).filter(Boolean) as { time: string; value: number }[];

        const apiMA5  = rows.filter(r => r.date && r.ma5  > 0).map(r => ({ time: r.date as string, value: Number(r.ma5) }));
        const apiMA20 = rows.filter(r => r.date && r.ma20 > 0).map(r => ({ time: r.date as string, value: Number(r.ma20) }));
        const apiMA60 = rows.filter(r => r.date && r.ma60 > 0).map(r => ({ time: r.date as string, value: Number(r.ma60) }));

        if (toggles.ma5)  { const s = chart.addLineSeries({ color: "#2dd4bf", lineWidth: 1, priceLineVisible: false }); s.setData(apiMA5.length > 5 ? apiMA5 : calcMA(5)); }
        if (toggles.ma20) { const s = chart.addLineSeries({ color: "#facc15", lineWidth: 1.5, priceLineVisible: false }); s.setData(apiMA20.length > 5 ? apiMA20 : calcMA(20)); }
        if (toggles.ma60) { const s = chart.addLineSeries({ color: "#f97316", lineWidth: 1.5, priceLineVisible: false }); s.setData(apiMA60.length > 5 ? apiMA60 : calcMA(60)); }

        if (toggles.bb) {
          const apiBBU = rows.filter(r => r.date && r.bbUpper > 0).map(r => ({ time: r.date as string, value: Number(r.bbUpper) }));
          const apiBBL = rows.filter(r => r.date && r.bbLower > 0).map(r => ({ time: r.date as string, value: Number(r.bbLower) }));
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
            const d = r.date || r.Date;
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
                  return [r.date || r.Date, close > 0 ? (close / baseClose) * baseStock : null];
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
          addLine(levelValue(levels, "entry"), "#22c55e", "진입");
          addLine(levelValue(levels, "stop"),  "#ef4444", "손절");
          addLine(levelValue(levels, "target"), "#06b6d4", "목표");
        }

        chart.timeScale().fitContent();
        const ro = new ResizeObserver(() => { if (containerRef.current && chartRef.current) chartRef.current.resize(containerRef.current.clientWidth, 380); });
        ro.observe(containerRef.current!);
        return () => ro.disconnect();
      } catch (err) { console.error("chart error:", err); }
    }
    init();
    return () => { if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; } };
  }, [rows, levels, toggles, indexRows]);

  return <div ref={containerRef} className="h-[380px] w-full overflow-hidden rounded-xl" />;
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

// ── ATR 기반 진입 계획 ────────────────────────────────────────────────
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

// ── 메인 ─────────────────────────────────────────────────────────────
export default function ChartPage() {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [levels, setLevels] = useState<any | null>(null);
  const [news, setNews] = useState<any[]>([]);
  const [disclosures, setDisclosures] = useState<any[]>([]);
  const [company, setCompany] = useState<any | null>(null);
  const [toggles, setToggles] = useState<Record<ToggleKey, boolean>>({ ma5: true, ma20: true, ma60: false, bb: false, volume: true, rsi: true, macd: false, index: true });
  const [period, setPeriod] = useState<number | null>(126);
  const [indexRows, setIndexRows] = useState<any[]>([]);
  const [atrMode, setAtrMode] = useState<"conservative"|"balanced"|"aggressive">("balanced");
  const [atrHorizon, setAtrHorizon] = useState<"short"|"swing"|"mid">("swing");
  const [loading, setLoading] = useState(false);
  const [seedLoading, setSeedLoading] = useState(false);

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
    let active = true; setLoading(true);
    Promise.allSettled([
      mone.ohlcv({ market: selected.market, symbol: selected.symbol, limit: 260 }),
      mone.recommendations({ market: selected.market, mode: "balanced", horizon: "swing", limit: 300 }),
      mone.news({ market: selected.market, limit: 200 }),
      mone.disclosures({ market: selected.market, limit: 200 }),
      withTimeout(mone.companyAnalysis({ market: selected.market, q: selected.symbol, limit: 20 }), 6000, { status: "TIMEOUT", items: [] }),
    ]).then((results) => {
      if (!active) return;
      const [cd, rd, nd, dd, company_d] = results.map((r) => r.status === "fulfilled" ? r.value : { items: [] });
      setRows(Array.isArray(cd.items) ? cd.items : []);
      const matched = Array.isArray(rd.items) ? rd.items.find((item: any) => normalizeSymbol(item) === selected.symbol) : null;
      setLevels(matched || null);
      setNews(relatedItems(Array.isArray(nd.items) ? nd.items : [], selected));
      setDisclosures(relatedItems(Array.isArray(dd.items) ? dd.items : [], selected));
      const cm = Array.isArray(company_d.items) ? company_d.items.find((item: any) => normalizeSymbol(item) === selected.symbol) || company_d.items[0] : null;
      setCompany(cm || null);
    }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [selected]);

  // 지수 비교 데이터 (날짜 기반 join)
  useEffect(() => {
    if (!selected) { setIndexRows([]); return; }
    const indexSym = selected.market === "us" ? "SPY" : "KOSPI";
    mone.chartIndex({ indexSymbol: indexSym, market: selected.market as any, limit: 520 })
      .then((d) => setIndexRows(Array.isArray(d.items) ? d.items : []))
      .catch(() => setIndexRows([]));
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

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">차트·기술분석</h1>
        <p className="mt-1 text-sm text-slate-400">OHLCV, 추천 기준선, 기술지표, 관련 뉴스·공시·기업분석</p>
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
              </div>
              <div className="grid grid-cols-2 gap-2 text-right sm:grid-cols-4">
                <Info label="최근 종가" value={latest ? money(latest.close, selected.market) : "-"} />
                <Info label="RSI14" value={latestRsi ? Number(latestRsi).toFixed(1) : "데이터 부족"} />
                <Info label="ATR14" value={indicators.atr14 ? money(indicators.atr14, selected.market) : "데이터 부족"} />
                <Info label="MDD20" value={indicators.mdd20 ? `${Number(indicators.mdd20).toFixed(2)}%` : "데이터 부족"} />
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
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-8 text-center text-amber-200">
                OHLCV 데이터가 없습니다. GitHub Actions 실행 후 다시 확인하세요.
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
                      {levels && <><span style={{ color: "#22c55e" }}>-- 진입</span><span style={{ color: "#ef4444" }}>-- 손절</span><span style={{ color: "#06b6d4" }}>-- 목표</span></>}
                    </span>
                  </div>
                </div>
                {toggles.rsi  && <RsiChart rows={filteredRows} />}
                {toggles.macd && <MacdChart rows={filteredRows} />}
                <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
                  <Info label="기준가" value={levels && levelValue(levels,"base") ? money(levelValue(levels,"base"), selected.market) : "-"} />
                  <Info label="진입가" value={levels ? priceText(levels,"entry","-") : "-"} />
                  <Info label="손절가" value={levels ? priceText(levels,"stop","-") : "-"} />
                  <Info label="목표가" value={levels ? priceText(levels,"target","-") : "-"} />
                  <Info label="예상가" value={levels ? priceText(levels,"expected","-") : "-"} />
                </div>
              </div>
            )}
          </div>

          {/* ATR 진입 계획 */}
          <div className="rounded-2xl border border-blue-900/50 bg-blue-950/10 p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold text-slate-100">ATR 기반 진입 계획</h3>
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
                    { label: "1차 진입 (50%)", value: money(atrPlan.entry, selected.market), color: "text-emerald-300", sub: "현재가 기준" },
                    { label: "2차 진입 (30%)", value: money(atrPlan.split2Price, selected.market), color: "text-sky-300", sub: `-${(atrPlan.atr * 0.5 / atrPlan.entry * 100).toFixed(1)}%` },
                    { label: "3차 진입 (20%)", value: money(atrPlan.split3Price, selected.market), color: "text-violet-300", sub: `-${(atrPlan.atr / atrPlan.entry * 100).toFixed(1)}%` },
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
              ) : (
                <div className="text-sm text-slate-500">기업분석 데이터를 불러오는 중...</div>
              )}
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel title="관련 뉴스">
              {news.length === 0 ? <Empty text="연결된 뉴스가 없습니다." /> : news.map((item, i) => <Related key={`news-${i}`} item={item} />)}
            </Panel>
            <Panel title="관련 공시·리서치">
              {disclosures.length === 0 ? <Empty text="연결된 공시/리서치 원본이 없습니다." /> : disclosures.map((item, i) => <Related key={`disc-${i}`} item={item} />)}
            </Panel>
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
function Related({ item }: { item: any }) {
  const title = item.title || item.reportName || item.headline || item.summary || "제목 없음";
  const date = item.date || item.publishedAt || item.disclosedAt || "";
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <div className="line-clamp-2 text-sm font-medium text-slate-100">{title}</div>
      <div className="mt-1 text-xs text-slate-500">{item.source || item.publisher || "출처 확인 필요"} · {date || "날짜 없음"}</div>
    </div>
  );
}
