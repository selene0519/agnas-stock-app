"use client";

import { useEffect, useState, type ReactNode } from "react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, money, type Market } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { displayName, normalizeMarket, normalizeSymbol, priceText } from "@/lib/moneDisplay";

type ToggleKey = "ma5" | "ma20" | "rsi";

function toSymbol(item: any, index = 0): MoneSymbol | null {
  const symbol = normalizeSymbol(item);
  if (!symbol) return null;
  const market = normalizeMarket(item?.market, symbol);
  const name = displayName(item);
  return {
    id: String(item?.id || `${market}-${symbol}-${index}`),
    symbol,
    name,
    market,
    label: `${name} (${symbol})`,
    isWatch: Boolean(item?.isWatch || item?.watch),
  };
}

function fallbackSymbol(market: Market): MoneSymbol {
  if (market === "us") return { id: "us-NVDA", symbol: "NVDA", name: "NVIDIA", market: "us", label: "NVIDIA (NVDA)", isWatch: true };
  return { id: "kr-005930", symbol: "005930", name: "삼성전자", market: "kr", label: "삼성전자 (005930)", isWatch: true };
}

function num(value: any) {
  const n = Number(String(value ?? "").replace(/[$,%원,\s]/g, ""));
  return Number.isFinite(n) ? n : null;
}

function positiveNum(value: any) {
  const n = num(value);
  return n !== null && n > 0 ? n : null;
}

function closeOf(row: any) {
  return num(row.close ?? row.Close ?? row.closePrice ?? row.currentPrice) || 0;
}

function highOf(row: any) {
  return num(row.high ?? row.High ?? row.highPrice) || closeOf(row);
}

function lowOf(row: any) {
  return num(row.low ?? row.Low ?? row.lowPrice) || closeOf(row);
}

function levelValue(levels: any, key: "entry" | "stop" | "target" | "expected" | "base") {
  const keys: Record<typeof key, string[]> = {
    entry: ["entry", "entryPrice"],
    stop: ["stop", "stopLoss", "stopPrice"],
    target: ["target", "targetPrice"],
    expected: ["expectedPrice", "expected"],
    base: ["basePrice", "base"],
  };
  for (const name of keys[key]) {
    const value = num(levels?.[name]);
    if (value && value > 0) return value;
  }
  return 0;
}

function movingAverage(values: number[], period: number) {
  return values.map((_, index) => {
    if (index + 1 < period) return null;
    const slice = values.slice(index + 1 - period, index + 1);
    return slice.reduce((sum, value) => sum + value, 0) / period;
  });
}

function average(values: number[]) {
  const clean = values.filter((value) => Number.isFinite(value) && value > 0);
  return clean.length ? clean.reduce((sum, value) => sum + value, 0) / clean.length : null;
}

function rsi(values: number[], period = 14) {
  if (values.length <= period) return null;
  let gain = 0;
  let loss = 0;
  for (let i = values.length - period; i < values.length; i += 1) {
    const diff = values[i] - values[i - 1];
    if (diff >= 0) gain += diff;
    else loss += Math.abs(diff);
  }
  if (loss === 0) return 100;
  const rs = gain / period / (loss / period);
  return 100 - 100 / (1 + rs);
}

function derivedIndicators(rows: any[], latest: any, recommendationIndicators: any) {
  const close = positiveNum(latest?.close ?? latest?.Close ?? latest?.closePrice ?? latest?.currentPrice);
  const ma20 = positiveNum(recommendationIndicators?.ma20 ?? latest?.ma20 ?? latest?.MA20);
  const bbUpper = positiveNum(recommendationIndicators?.bbUpper ?? latest?.bbUpper ?? latest?.BBUpper ?? latest?.bollingerUpper);
  const bbLower = positiveNum(recommendationIndicators?.bbLower ?? latest?.bbLower ?? latest?.BBLower ?? latest?.bollingerLower);
  const latestVolume = positiveNum(latest?.volume ?? latest?.Volume);
  const volumeAvg20 = average(rows.slice(-20).map((row) => positiveNum(row.volume ?? row.Volume) || 0));
  const high52w = Math.max(...rows.slice(-260).map(highOf).filter(Boolean), 0);

  return {
    ...recommendationIndicators,
    rsi14: positiveNum(recommendationIndicators?.rsi14 ?? latest?.rsi ?? latest?.RSI),
    atr14: positiveNum(recommendationIndicators?.atr14 ?? latest?.atr14 ?? latest?.ATR14),
    mdd20: positiveNum(recommendationIndicators?.mdd20 ?? latest?.mdd20 ?? latest?.MDD20),
    distanceToMa20:
      recommendationIndicators?.distanceToMa20 ?? (close && ma20 ? ((close - ma20) / ma20) * 100 : null),
    bbPercentB:
      recommendationIndicators?.bbPercentB ?? (close && bbUpper && bbLower && bbUpper !== bbLower ? (close - bbLower) / (bbUpper - bbLower) : null),
    volumeRatio20:
      recommendationIndicators?.volumeRatio20 ?? (latestVolume && volumeAvg20 ? latestVolume / volumeAvg20 : null),
    distanceTo52wHigh:
      recommendationIndicators?.distanceTo52wHigh ?? (close && high52w ? ((close - high52w) / high52w) * 100 : null),
  };
}

function relatedItems(items: any[], selected: MoneSymbol | null) {
  if (!selected) return [];
  const query = `${selected.symbol} ${selected.name}`.toLowerCase();
  return items
    .filter((item) => {
      const text = [item.symbol, item.name, item.company, item.title, item.reportName, item.summary].filter(Boolean).join(" ").toLowerCase();
      return query.split(" ").some((part) => part && text.includes(part));
    })
    .slice(0, 4);
}

function withTimeout<T>(promise: Promise<T>, ms: number, fallback: T): Promise<T> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(fallback), ms);
    promise
      .then((value) => resolve(value))
      .catch(() => resolve(fallback))
      .finally(() => window.clearTimeout(timer));
  });
}

export default function ChartPage() {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [rows, setRows] = useState<any[]>([]);
  const [levels, setLevels] = useState<any | null>(null);
  const [news, setNews] = useState<any[]>([]);
  const [disclosures, setDisclosures] = useState<any[]>([]);
  const [company, setCompany] = useState<any | null>(null);
  const [toggles, setToggles] = useState<Record<ToggleKey, boolean>>({ ma5: true, ma20: true, rsi: true });
  const [loading, setLoading] = useState(false);
  const [seedLoading, setSeedLoading] = useState(false);

  useEffect(() => {
    let active = true;
    if (selected) return;

    async function selectInitialSymbol() {
      setSeedLoading(true);
      try {
        const holdings = await mone.holdingsClean({ market, limit: 20 });
        if (!active || selected) return;
        const holding = Array.isArray(holdings.items) ? holdings.items.map(toSymbol).find(Boolean) : null;
        if (holding) {
          setSelected(holding);
          return;
        }

        const recommendations = await mone.recommendations({ market, mode: "balanced", horizon: "swing", limit: 20 });
        if (!active || selected) return;
        const candidate = Array.isArray(recommendations.items) ? recommendations.items.map(toSymbol).find(Boolean) : null;
        setSelected(candidate || fallbackSymbol(market));
      } finally {
        if (active) setSeedLoading(false);
      }
    }

    selectInitialSymbol();
    return () => {
      active = false;
    };
  }, [market, selected]);

  useEffect(() => {
    if (!selected) {
      setRows([]);
      setLevels(null);
      setNews([]);
      setDisclosures([]);
      setCompany(null);
      return;
    }

    let active = true;
    setLoading(true);
    Promise.allSettled([
      mone.ohlcv({ market: selected.market, symbol: selected.symbol, limit: 260 }),
      mone.recommendations({ market: selected.market, mode: "balanced", horizon: "swing", limit: 300 }),
      mone.news({ market: selected.market, limit: 200 }),
      mone.disclosures({ market: selected.market, limit: 200 }),
      withTimeout(mone.companyAnalysis({ market: selected.market, q: selected.symbol, limit: 20 }), 6000, { status: "TIMEOUT", items: [] }),
    ])
      .then((results) => {
        if (!active) return;
        const [chartData, recommendationData, newsData, disclosureData, companyData] = results.map((result) =>
          result.status === "fulfilled" ? result.value : { items: [] },
        );
        setRows(Array.isArray(chartData.items) ? chartData.items : []);
        const matched = Array.isArray(recommendationData.items)
          ? recommendationData.items.find((item: any) => normalizeSymbol(item) === selected.symbol)
          : null;
        setLevels(matched || null);
        setNews(relatedItems(Array.isArray(newsData.items) ? newsData.items : [], selected));
        setDisclosures(relatedItems(Array.isArray(disclosureData.items) ? disclosureData.items : [], selected));
        const companyMatch = Array.isArray(companyData.items)
          ? companyData.items.find((item: any) => normalizeSymbol(item) === selected.symbol) || companyData.items[0]
          : null;
        setCompany(companyMatch || null);
      })
      .finally(() => active && setLoading(false));

    return () => {
      active = false;
    };
  }, [selected]);

  const latest = rows.at(-1);
  const display = rows.slice(-90);
  const closes = display.map(closeOf);
  const ma5 = movingAverage(closes, 5);
  const ma20 = movingAverage(closes, 20);
  const indicators = derivedIndicators(rows, latest, levels?.indicators || {});
  const latestRsi = indicators.rsi14 ?? rsi(rows.map(closeOf).filter(Boolean));
  const levelNumbers = ["base", "entry", "stop", "target", "expected"].map((key) => levelValue(levels, key as any)).filter(Boolean);
  const maNumbers = [...ma5, ...ma20].filter((value): value is number => Number.isFinite(value as number));
  const max = Math.max(...display.map(highOf), ...levelNumbers, ...maNumbers, 1);
  const min = Math.min(...display.map((row) => lowOf(row) || max), ...levelNumbers, ...maNumbers, max);
  const y = (value: number) => (max === min ? 120 : 220 - ((value - min) / (max - min)) * 190);
  const x = (index: number) => 20 + (index / Math.max(display.length - 1, 1)) * 900;
  const points = closes.map((close, index) => `${x(index)},${y(close)}`).join(" ");
  const maPoints = (series: Array<number | null>) => series.map((value, index) => (value ? `${x(index)},${y(value)}` : "")).filter(Boolean).join(" ");
  const lines = [
    { key: "base", label: "기준가", color: "rgb(148 163 184)", value: levelValue(levels, "base") },
    { key: "entry", label: "진입가", color: "rgb(16 185 129)", value: levelValue(levels, "entry") },
    { key: "stop", label: "손절가", color: "rgb(248 113 113)", value: levelValue(levels, "stop") },
    { key: "target", label: "목표가", color: "rgb(34 211 238)", value: levelValue(levels, "target") },
    { key: "expected", label: "예상가", color: "rgb(168 85 247)", value: levelValue(levels, "expected") },
  ].filter((line) => line.value > 0);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">차트·기술분석</h1>
        <p className="mt-1 text-sm text-slate-400">실제 OHLCV, 추천 기준선, 기술지표, 관련 뉴스·공시·기업분석 연결 상태를 함께 확인합니다.</p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(["kr", "us", "all"] as Market[]).map((item) => (
          <button
            key={item}
            onClick={() => {
              setMarket(item);
              setSelected(null);
            }}
            className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}
          >
            {marketLabel(item)}
          </button>
        ))}
        <span className="text-xs text-slate-500">현재 기본값: {marketLabel(getDefaultMarketBySession())}</span>
      </div>

      <SymbolSearchSelect market={market} value={selected?.symbol || ""} onChange={setSelected} />

      {!selected && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
          {seedLoading ? "기본 종목을 불러오는 중..." : "종목명 또는 종목코드로 검색하거나 목록에서 종목을 선택하세요."}
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

            <div className="mb-3 flex flex-wrap gap-2">
              {(["ma5", "ma20", "rsi"] as ToggleKey[]).map((key) => (
                <button
                  key={key}
                  onClick={() => setToggles((prev) => ({ ...prev, [key]: !prev[key] }))}
                  className={`rounded-lg border px-3 py-1.5 text-xs ${toggles[key] ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : "border-slate-800 bg-slate-950 text-slate-500"}`}
                >
                  {key === "ma5" ? "MA5" : key === "ma20" ? "MA20" : "RSI"}
                </button>
              ))}
            </div>

            {loading && <div className="py-20 text-center text-slate-500">차트 데이터를 불러오는 중...</div>}

            {!loading && rows.length === 0 && (
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-8 text-center text-amber-200">
                이 종목의 OHLCV 데이터가 아직 연결되지 않았습니다. `data/market/ohlcv` 또는 `/api/ohlcv` 연결 상태를 확인해야 합니다.
              </div>
            )}

            {!loading && rows.length > 0 && (
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                  <svg viewBox="0 0 960 260" className="h-80 w-full">
                    {[0, 1, 2, 3].map((grid) => (
                      <line key={grid} x1="20" x2="920" y1={35 + grid * 55} y2={35 + grid * 55} stroke="rgb(51 65 85)" strokeDasharray="4 4" />
                    ))}
                    {lines.map((line) => {
                      const yy = y(line.value);
                      return (
                        <g key={line.key}>
                          <line x1="20" x2="920" y1={yy} y2={yy} stroke={line.color} strokeDasharray={line.key === "entry" ? "0" : "6 5"} strokeWidth="1.5" />
                          <text x="925" y={yy + 4} fill={line.color} fontSize="12">{line.label}</text>
                        </g>
                      );
                    })}
                    {toggles.ma20 && <polyline points={maPoints(ma20)} fill="none" stroke="rgb(250 204 21)" strokeWidth="1.5" opacity="0.8" />}
                    {toggles.ma5 && <polyline points={maPoints(ma5)} fill="none" stroke="rgb(45 212 191)" strokeWidth="1.5" opacity="0.8" />}
                    <polyline points={points} fill="none" stroke="rgb(59 130 246)" strokeWidth="3" />
                  </svg>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500 md:grid-cols-5">
                    <div>데이터: {rows.length}개</div>
                    <div>최근 일자: {latest?.date || "-"}</div>
                    <div>고가: {latest ? money(latest.high, selected.market) : "-"}</div>
                    <div>저가: {latest ? money(latest.low, selected.market) : "-"}</div>
                    <div>거래량: {Number(latest?.volume || 0).toLocaleString("ko-KR")}</div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
                  <Info label="기준가" value={levels && levelValue(levels, "base") ? money(levelValue(levels, "base"), selected.market) : "추천 기준 없음"} />
                  <Info label="진입가" value={levels ? priceText(levels, "entry", "추천 기준 없음") : "추천 기준 없음"} />
                  <Info label="손절가" value={levels ? priceText(levels, "stop", "추천 기준 없음") : "추천 기준 없음"} />
                  <Info label="목표가" value={levels ? priceText(levels, "target", "추천 기준 없음") : "추천 기준 없음"} />
                  <Info label="예상가" value={levels ? priceText(levels, "expected", "추천 기준 없음") : "추천 기준 없음"} />
                </div>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Panel title="고급 기술지표">
              <Info label="MA20 이격도" value={indicators.distanceToMa20 != null ? `${Number(indicators.distanceToMa20).toFixed(2)}%` : "데이터 부족"} />
              <Info label="볼린저 %B" value={indicators.bbPercentB != null ? Number(indicators.bbPercentB).toFixed(2) : "데이터 부족"} />
              <Info label="20일 거래량비" value={indicators.volumeRatio20 != null ? `${Number(indicators.volumeRatio20).toFixed(2)}x` : "데이터 부족"} />
              <Info label="52주 고점 이격" value={indicators.distanceTo52wHigh != null ? `${Number(indicators.distanceTo52wHigh).toFixed(2)}%` : "데이터 부족"} />
            </Panel>

            <Panel title="호가·수급">
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-400">
                호가/체결강도/기관·외국인 수급 원본이 아직 이 종목 화면에 연결되지 않았습니다. 데이터가 들어오면 이 영역에 실시간 수급과 매도·매수 잔량을 표시합니다.
              </div>
            </Panel>

            <Panel title="기업분석">
              <Info label="EPS" value={company?.eps ? Number(company.eps).toLocaleString("ko-KR") : company?.connectionStatus || "재무 원본 확인 필요"} />
              <Info label="PER" value={company?.per ? Number(company.per).toFixed(2) : company?.missingReason || "값 비어 있음"} />
              <Info label="PBR" value={company?.pbr ? Number(company.pbr).toFixed(2) : company?.dataStatus || "값 비어 있음"} />
              <Info label="ROE" value={company?.roe ? `${Number(company.roe).toFixed(2)}%` : "값 비어 있음"} />
              {Array.isArray(company?.missingFields) && company.missingFields.length > 0 && (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-200">
                  누락 필드: {company.missingFields.slice(0, 6).join(", ")}
                </div>
              )}
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Panel title="관련 뉴스">
              {news.length === 0 ? (
                <Empty text="연결된 뉴스가 없습니다." />
              ) : (
                news.map((item, index) => <Related key={`news-${index}`} item={item} />)
              )}
            </Panel>
            <Panel title="관련 공시·리서치">
              {disclosures.length === 0 ? (
                <Empty text="연결된 공시/리서치 원본이 없습니다." />
              ) : (
                disclosures.map((item, index) => <Related key={`disc-${index}`} item={item} />)
              )}
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
