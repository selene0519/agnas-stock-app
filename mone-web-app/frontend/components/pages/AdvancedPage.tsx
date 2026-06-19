"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { mone, type Market, type Mode, type Horizon } from "@/lib/api";
import { getDefaultMarketBySession } from "@/lib/marketSession";
import { toNumber } from "@/lib/moneDisplay";
import BacktestComparePanel from "@/components/BacktestComparePanel";
import PaperTradingPage from "@/components/pages/PaperTradingPage";
import VirtualJournalPage from "@/components/pages/VirtualJournalPage";

type TabId = "paper" | "journal" | "calculator" | "montecarlo" | "backtest";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="text-base font-semibold text-slate-100">{title}</h2>
      <div className="mt-4">{children}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-2 text-lg font-bold text-slate-100">{value}</div>
    </div>
  );
}

function pickNumber(item: any, keys: string[]) {
  for (const key of keys) {
    const value = toNumber(item?.[key]);
    if (value !== null) return value;
  }
  return null;
}

function strategyCap(mode: Mode) {
  if (mode === "conservative") return 5;
  if (mode === "aggressive") return 15;
  return 10;
}

function formatAmount(value: number, market: Market) {
  if (!Number.isFinite(value) || value <= 0) return "-";
  return market === "us"
    ? `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : `${Math.round(value).toLocaleString("ko-KR")}원`;
}

export default function AdvancedPage({
  initialOrder,
  onOrderConsumed,
}: {
  initialOrder?: { symbol: string; name: string; price: number; market: "kr" | "us"; quantity?: number };
  onOrderConsumed?: () => void;
} = {}) {
  const [tab, setTab] = useState<TabId>("paper");

  useEffect(() => {
    if (initialOrder) onOrderConsumed?.();
  // onOrderConsumed intentionally excluded — only run once when initialOrder arrives
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialOrder]);
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [entry, setEntry] = useState(100);
  const [stop, setStop] = useState(96);
  const [target, setTarget] = useState(108);
  const [winRate, setWinRate] = useState(55);
  const [riskPct, setRiskPct] = useState(1);
  const [capital, setCapital] = useState(10_000_000);
  const [calcResult, setCalcResult] = useState<any>(null);

  // 몬테카를로
  const [mcPrice, setMcPrice] = useState(100000);
  const [mcReturn, setMcReturn] = useState(8);
  const [mcVol, setMcVol] = useState(25);
  const [mcDays, setMcDays] = useState(60);
  const [mcSims, setMcSims] = useState(500);
  const [mcResult, setMcResult] = useState<any>(null);
  const [mcLoading, setMcLoading] = useState(false);

  const [dropdownOpen, setDropdownOpen] = useState(false);

  const rr = useMemo(() => {
    const risk = Math.max(entry - stop, 0);
    const reward = Math.max(target - entry, 0);
    return risk > 0 ? reward / risk : 0;
  }, [entry, stop, target]);

  const expectedValue = useMemo(() => {
    const p = winRate / 100;
    const rewardPct = entry > 0 ? ((target - entry) / entry) * 100 : 0;
    const riskPctValue = entry > 0 ? ((entry - stop) / entry) * 100 : 0;
    return p * rewardPct - (1 - p) * riskPctValue;
  }, [entry, stop, target, winRate]);

  const kelly = useMemo(() => {
    const p = winRate / 100;
    const b = rr;
    if (b <= 0) return 0;
    return Math.max(((p * (b + 1) - 1) / b) * 100, 0);
  }, [winRate, rr]);

  const position = useMemo(() => {
    const perShareRisk = Math.max(entry - stop, 0);
    const maxLossAmount = Math.max(capital * (riskPct / 100), 0);
    const qty = perShareRisk > 0 ? Math.floor(maxLossAmount / perShareRisk) : 0;
    const amount = qty * entry;
    const halfKellyPct = Math.min(kelly / 2, strategyCap(mode === "all" ? "balanced" : mode));
    return {
      maxLossAmount,
      qty,
      amount,
      halfKellyPct,
      halfKellyAmount: capital * (halfKellyPct / 100),
    };
  }, [capital, entry, stop, riskPct, kelly, mode]);

  useEffect(() => {
    let active = true;
    Promise.allSettled([
      mone.calculatorKelly({ winRate, payoffRatio: rr, capital }),
      mone.calculatorRiskReward({ entry, stop, target }),
    ]).then(([kellyResult, rrResult]) => {
      if (!active) return;
      setCalcResult({
        kelly: kellyResult.status === "fulfilled" ? kellyResult.value : null,
        riskReward: rrResult.status === "fulfilled" ? rrResult.value : null,
      });
    });
    return () => { active = false; };
  }, [entry, stop, target, winRate, rr, capital]);


  async function runMonteCarlo() {
    setMcLoading(true);
    try {
      const r = await mone.monteCarlo({ currentPrice: mcPrice, expectedReturn: mcReturn, volatility: mcVol, days: mcDays, simulations: mcSims });
      setMcResult(r);
    } catch { setMcResult(null); }
    finally { setMcLoading(false); }
  }

  function applyCandidate(item: any, targetTab: "calculator" | "montecarlo") {
    const source = { ...(item.recommendation || {}), ...item };
    const nextCurrent = pickNumber(source, ["currentPrice", "price", "current"]);
    const nextEntry = pickNumber(source, ["entryPrice", "entry"]);
    const nextStop = pickNumber(source, ["stopLoss", "stopPrice", "stop"]);
    const nextTarget = pickNumber(source, ["targetPrice", "target", "expectedPrice"]);
    const nextProb = pickNumber(source, ["probability", "prob5d", "confidence", "score"]);

    if (nextEntry !== null) setEntry(nextEntry);
    if (nextStop !== null) setStop(nextStop);
    if (nextTarget !== null) setTarget(nextTarget);
    if (nextProb !== null) setWinRate(Math.max(1, Math.min(95, nextProb)));

    const basePrice = nextCurrent ?? nextEntry;
    if (basePrice !== null) setMcPrice(basePrice);
    if (basePrice && nextTarget) setMcReturn(((nextTarget - basePrice) / basePrice) * 100);
    setMcVol(mode === "aggressive" ? 35 : mode === "conservative" ? 18 : 25);
    setTab(targetTab);
  }

  const tabs: { id: TabId; label: string }[] = [
    { id: "paper", label: "모의투자" },
    { id: "journal", label: "AI 매매일지" },
    { id: "calculator", label: "계산기" },
    { id: "montecarlo", label: "몬테카를로" },
    { id: "backtest", label: "전략 검증" },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h1 className="text-xl font-bold text-white">MONE 트레이딩</h1>
        <p className="mt-1 text-xs text-slate-400">모의투자, AI 매매일지, 계산기, 몬테카를로, 전략 검증을 한 곳에서.</p>
      </div>

      {/* 탭 드롭다운 */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setDropdownOpen((v) => !v)}
          className="flex w-full items-center justify-between rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-slate-800"
        >
          <span>{tabs.find((t) => t.id === tab)?.label}</span>
          <ChevronDown size={15} className={`shrink-0 text-slate-400 transition-transform duration-150 ${dropdownOpen ? "rotate-180" : ""}`} />
        </button>
        {dropdownOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
            <div className="absolute left-0 right-0 top-full z-20 mt-1 rounded-xl border border-slate-700 bg-slate-900 py-1 shadow-xl">
              {tabs.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => { setTab(item.id); setDropdownOpen(false); }}
                  className={`flex w-full items-center px-4 py-2.5 text-left text-sm transition-colors ${tab === item.id ? "bg-slate-700/60 font-semibold text-white" : "text-slate-300 hover:bg-slate-800"}`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {tab === "calculator" && (
        <Card title="EV 기반 리스크 계산기">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            {[
              ["진입가", entry, setEntry],
              ["손절가", stop, setStop],
              ["목표가", target, setTarget],
              ["승률 %", winRate, setWinRate],
              ["운용 자본", capital, setCapital],
            ].map(([label, value, setter]: any) => (
              <label key={label} className="space-y-2 text-sm text-slate-400">
                {label}
                <input type="number" value={value} onChange={(event) => setter(Number(event.target.value))} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100" />
              </label>
            ))}
          </div>
          <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-4">
            <Metric label="손익비" value={calcResult?.riskReward?.ratioText || rr.toFixed(2)} />
            <Metric label="기댓값(EV)" value={`${expectedValue.toFixed(2)}%`} />
            <Metric label="켈리 추정" value={calcResult?.kelly?.kellyText || `${kelly.toFixed(2)}%`} />
            <Metric label="1회 거래 리스크" value={`${riskPct.toFixed(2)}%`} />
            <Metric label="최대 손실 금액" value={formatAmount(position.maxLossAmount, market)} />
            <Metric label="추천 수량" value={position.qty > 0 ? `${position.qty.toLocaleString("ko-KR")}주` : "가격 확인"} />
            <Metric label="포지션 금액" value={formatAmount(position.amount, market)} />
            <Metric label="Half-Kelly 한도" value={`${position.halfKellyPct.toFixed(2)}% · ${formatAmount(position.halfKellyAmount, market)}`} />
          </div>
          <div className="mt-4 flex flex-wrap gap-4">
            <label className="space-y-2 text-sm text-slate-400">
              1회 거래 리스크 %
              <input type="number" value={riskPct} onChange={(event) => setRiskPct(Number(event.target.value))} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 md:w-64" />
            </label>
            <div className="max-w-xl self-end text-xs leading-5 text-slate-500">
              계산은 백엔드 Kelly/RiskReward API 결과를 우선 표시하고, 수량은 입력한 자본과 손절폭 기준으로 산출합니다. 자동 주문은 하지 않습니다.
            </div>
          </div>
        </Card>
      )}

      {tab === "montecarlo" && (
        <Card title="몬테카를로 시뮬레이션">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {([
              ["현재가", mcPrice, setMcPrice, 1],
              ["기대수익률 %", mcReturn, setMcReturn, 0.1],
              ["변동성 %", mcVol, setMcVol, 0.1],
              ["기간(일)", mcDays, setMcDays, 1],
              ["시뮬레이션 수", mcSims, setMcSims, 100],
            ] as [string, number, (v: number) => void, number][]).map(([label, val, setter, step]) => (
              <label key={label} className="space-y-1.5 text-xs text-slate-400">
                {label}
                <input type="number" step={step} value={val}
                  onChange={(e) => setter(Number(e.target.value))}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" />
              </label>
            ))}
          </div>
          <button onClick={runMonteCarlo} disabled={mcLoading}
            className="mt-4 rounded-xl bg-blue-600 px-5 py-2 text-sm font-bold text-white hover:bg-blue-500 disabled:opacity-50">
            {mcLoading ? "시뮬레이션 중..." : "시뮬레이션 실행"}
          </button>
          <div className="mt-3 text-xs text-slate-500">
            스캐너 표의 MC 버튼을 누르면 선택 종목의 현재가·목표가를 기준으로 기대수익률을 자동 채웁니다. 변동성은 전략 성향 기본값을 넣고 필요하면 직접 조정합니다.
          </div>
          {mcResult && (
            <div className="mt-5 space-y-4">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Metric label="상승 확률" value={mcResult.upProbability} />
                <Metric label="P50 (중간값)" value={Number(mcResult.p50).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} />
                <Metric label="P5 (하방)" value={Number(mcResult.p5).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} />
                <Metric label="P95 (상방)" value={Number(mcResult.p95).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} />
                <Metric label="VaR (5%)" value={mcResult.varText} />
                <Metric label="CVaR" value={mcResult.cvarText} />
                <Metric label="기대 최종가" value={Number(mcResult.expectedFinalPrice).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} />
                <Metric label="기간" value={`${mcResult.inputs?.days}일`} />
              </div>
              {Array.isArray(mcResult.chart) && mcResult.chart.length > 0 && (() => {
                const pts = mcResult.chart;
                const allVals = pts.flatMap((p: any) => [p.p5, p.p50, p.p95]);
                const minV = Math.min(...allVals), maxV = Math.max(...allVals);
                const H = 140, W = 100;
                const scaleY = (v: number) => H - ((v - minV) / (maxV - minV + 0.0001)) * (H - 10);
                const mkPath = (key: string) => pts.map((p: any, i: number) =>
                  `${i === 0 ? "M" : "L"}${(i / (pts.length - 1)) * W},${scaleY(p[key]).toFixed(1)}`
                ).join(" ");
                return (
                  <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
                    <div className="mb-2 flex items-center gap-4 text-[10px]">
                      {[["P95 (상방)", "#10b981"], ["P50 (중간)", "#60a5fa"], ["P5 (하방)", "#f87171"]].map(([l, c]) => (
                        <span key={l} className="flex items-center gap-1"><span className="h-2 w-4 rounded" style={{ background: c }} /><span className="text-slate-400">{l}</span></span>
                      ))}
                    </div>
                    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-36 w-full">
                      <path d={mkPath("p95")} fill="none" stroke="#10b981" strokeWidth="0.8" />
                      <path d={mkPath("p50")} fill="none" stroke="#60a5fa" strokeWidth="1.2" strokeDasharray="2 1" />
                      <path d={mkPath("p5")} fill="none" stroke="#f87171" strokeWidth="0.8" />
                    </svg>
                    <div className="mt-1 flex justify-between text-[9px] text-slate-600">
                      <span>0일</span><span>{mcResult.inputs?.days}일</span>
                    </div>
                  </div>
                );
              })()}
            </div>
          )}
        </Card>
      )}

      {tab === "backtest" && (
        <Card title="전략 검증 (9전략)">
          <BacktestComparePanel />
        </Card>
      )}

      {tab === "paper" && <PaperTradingPage initialOrder={initialOrder} />}

      {tab === "journal" && <VirtualJournalPage />}

    </div>
  );
}
