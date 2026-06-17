"use client";

import { useEffect, useState } from "react";
import { mone, type Market } from "@/lib/api";
import { PieChart, RefreshCw, AlertTriangle, CheckCircle2, TrendingDown } from "lucide-react";

const PORTFOLIO_CACHE_KEY = "mone:portfolio-optimize-cache";
const PORTFOLIO_CACHE_TTL = 30 * 60 * 1000;

function readPortfolioCache(market: Market): { sectorData: any; holdings: any[] } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(PORTFOLIO_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed.market !== market) return null;
    if (Date.now() - (parsed.ts || 0) > PORTFOLIO_CACHE_TTL) return null;
    return parsed.data || null;
  } catch {
    return null;
  }
}

function writePortfolioCache(market: Market, data: { sectorData: any; holdings: any[] }) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(PORTFOLIO_CACHE_KEY, JSON.stringify({ market, data, ts: Date.now() }));
  } catch {}
}

type SectorRow = {
  sector: string;
  value: number;
  pct: number;
  symbols: string[];
  maxLoss: number;
};

type Holding = {
  symbol: string;
  name: string;
  market: string;
  currentPrice: number;
  quantity: number;
  avgPrice: number;
  valuation: number;
  pnlPct: number;
  stop?: number;
  target?: number;
};

type PortfolioData = {
  sectors: SectorRow[];
  concentration: { top1Pct: number; warning: boolean };
  maxLossSimulation: { totalLoss: number; totalLossPct: number };
  holdings: Holding[];
  totalValue: number;
};

function ConcentrationBar({ pct, label, count }: { pct: number; label: string; count: number }) {
  const isHigh = pct > 40;
  const isMed = pct > 25;
  const barColor = isHigh ? "bg-red-500" : isMed ? "bg-amber-400" : "bg-emerald-400";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-slate-300 font-medium">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-slate-500">{count}종목</span>
          <span className={`font-bold ${isHigh ? "text-red-400" : isMed ? "text-amber-400" : "text-slate-200"}`}>
            {pct.toFixed(1)}%
          </span>
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}

function HoldingRow({ h, totalValue }: { h: Holding; totalValue: number }) {
  const weight = totalValue > 0 ? (h.valuation / totalValue) * 100 : 0;
  const isHeavy = weight > 20;
  const pnlColor = h.pnlPct > 0 ? "text-emerald-400" : h.pnlPct < 0 ? "text-red-400" : "text-slate-400";

  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-700/40 bg-slate-800/30 px-3 py-2">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold text-slate-200 truncate">{h.name || h.symbol}</span>
          {isHeavy && (
            <span className="shrink-0 rounded border border-amber-500/30 bg-amber-950/20 px-1 py-0.5 text-[9px] font-bold text-amber-400">
              집중
            </span>
          )}
        </div>
        <span className="text-[10px] text-slate-500">{h.symbol}</span>
      </div>
      <div className="text-right shrink-0">
        <div className={`text-xs font-bold ${pnlColor}`}>
          {h.pnlPct > 0 ? "+" : ""}{h.pnlPct.toFixed(1)}%
        </div>
        <div className="text-[10px] text-slate-500">{weight.toFixed(1)}% 비중</div>
      </div>
    </div>
  );
}

export default function PortfolioOptimizePanel() {
  const [market, setMarket] = useState<Market>("kr");
  const [sectorData, setSectorData] = useState<any>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [holdingSource, setHoldingSource] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function load(force = false) {
    if (!force) {
      const cached = readPortfolioCache(market);
      if (cached) {
        setSectorData(cached.sectorData);
        setHoldings(cached.holdings);
        setLoading(false);
        setIsRefreshing(true);
      } else {
        setLoading(true);
      }
    }

    if (force) setIsRefreshing(true);

    try {
      const [sectorResult, holdingsResult] = await Promise.allSettled([
        mone.sectorExposure({ market }) as Promise<any>,
        mone.holdingsClean({ market, limit: 200 }) as Promise<any>,
      ]);
      const sectorRes = sectorResult.status === "fulfilled" ? sectorResult.value : null;
      const holdingsRes = holdingsResult.status === "fulfilled" ? holdingsResult.value : null;
      setSectorData(sectorRes);
      setHoldingSource(String(holdingsRes?.authority || holdingsRes?.routeVersion || ""));
      const items = (holdingsRes?.items || []) as any[];
      const parsed: Holding[] = items.map((h: any) => ({
        symbol: h.symbol || "",
        name: h.name || h.symbol || "",
        market: h.market || market,
        currentPrice: Number(h.currentPrice || 0),
        quantity: Number(h.quantity || 0),
        avgPrice: Number(h.avgPrice || h.averagePrice || 0),
        valuation: Number(h.valuation || h.marketValue || (Number(h.currentPrice || 0) * Number(h.quantity || 0))),
        pnlPct: Number(h.pnlPct || h.returnPct || 0),
        stop: h.stop || h.stopPrice ? Number(h.stop || h.stopPrice) : undefined,
        target: h.target || h.targetPrice ? Number(h.target || h.targetPrice) : undefined,
      }));
      const filteredHoldings = parsed.filter((h) => h.valuation > 0);
      setHoldings(filteredHoldings);
      writePortfolioCache(market, { sectorData: sectorRes, holdings: filteredHoldings });
    } catch {
      setSectorData(null);
      setHoldingSource("");
      setHoldings([]);
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    load(false);
  }, [market]);

  const totalValue = holdings.reduce((s, h) => s + h.valuation, 0);
  const heavyPositions = holdings.filter((h) => totalValue > 0 && (h.valuation / totalValue) * 100 > 20);
  const sectors: SectorRow[] = sectorData?.sectors || [];
  const concentration = sectorData?.concentration || { top1Pct: 0, warning: false };
  const maxLoss = sectorData?.maxLossSimulation || { totalLoss: 0, totalLossPct: 0 };

  const riskScore =
    (concentration.warning ? 2 : concentration.top1Pct > 25 ? 1 : 0) +
    (heavyPositions.length > 0 ? 1 : 0) +
    (maxLoss.totalLossPct > 15 ? 2 : maxLoss.totalLossPct > 8 ? 1 : 0);
  const riskLabel =
    riskScore >= 4 ? { text: "집중 위험", color: "text-red-400", bg: "border-red-500/20 bg-red-950/10" } :
    riskScore >= 2 ? { text: "주의", color: "text-amber-400", bg: "border-amber-500/20 bg-amber-950/10" } :
    { text: "양호", color: "text-emerald-400", bg: "border-emerald-500/20 bg-emerald-950/10" };

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <PieChart size={14} className="text-violet-400" />
          <span className="text-sm font-bold text-slate-200">포트폴리오 분석</span>
        </div>
        <div className="flex items-center gap-2">
          {(["kr", "us"] as Market[]).map((mk) => (
            <button
              key={mk}
              onClick={() => setMarket(mk)}
              className={`rounded-lg px-3 py-1 text-xs font-semibold transition-colors ${market === mk ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}
            >
              {mk === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button
            onClick={() => load(true)}
            disabled={loading || isRefreshing}
            className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            <RefreshCw size={11} className={(loading || isRefreshing) ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {loading && holdings.length === 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-6 text-center text-xs text-slate-500">
          분석 중...
        </div>
      )}

      {!loading && holdings.length === 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-6 text-center text-xs text-slate-500">
          보유 종목 없음 — holdings-clean 기준으로 확인했습니다{holdingSource ? ` (${holdingSource})` : ""}.
        </div>
      )}

      {holdings.length > 0 && (
        <>
          {/* 리스크 종합 */}
          <div className={`flex items-center gap-2 rounded-xl border px-3 py-2.5 ${riskLabel.bg}`}>
            {riskScore >= 3 ? (
              <AlertTriangle size={13} className={riskLabel.color} />
            ) : (
              <CheckCircle2 size={13} className={riskLabel.color} />
            )}
            <div>
              <span className={`text-xs font-bold ${riskLabel.color}`}>{riskLabel.text}</span>
              <span className="ml-2 text-[11px] text-slate-400">
                총 {holdings.length}종목 ·{" "}
                {totalValue > 0
                  ? totalValue >= 1_000_000
                    ? `${(totalValue / 1_000_000).toFixed(1)}백만원`
                    : `${totalValue.toLocaleString()}원`
                  : "—"}
              </span>
            </div>
            <div className="ml-auto text-right">
              <div className="text-[10px] text-slate-500">손절 시 최대 손실</div>
              <div className={`text-xs font-bold ${maxLoss.totalLossPct > 10 ? "text-red-400" : "text-slate-300"}`}>
                -{maxLoss.totalLossPct.toFixed(1)}%
              </div>
            </div>
          </div>

          {/* 섹터 집중도 */}
          {sectors.length > 0 && (
            <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">섹터 집중도</p>
                {concentration.warning && (
                  <span className="text-[10px] text-red-400 font-semibold">
                    ⚠ 1개 섹터 {concentration.top1Pct}% 집중
                  </span>
                )}
              </div>
              <div className="space-y-2.5">
                {sectors.map((s) => (
                  <ConcentrationBar
                    key={s.sector}
                    label={s.sector}
                    pct={s.pct}
                    count={s.symbols.length}
                  />
                ))}
              </div>
            </div>
          )}

          {/* 개별 종목 비중 */}
          <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">종목별 비중</p>
              {heavyPositions.length > 0 && (
                <span className="text-[10px] text-amber-400 font-semibold">
                  {heavyPositions.length}종목 20% 초과
                </span>
              )}
            </div>
            <div className="space-y-1.5">
              {[...holdings]
                .sort((a, b) => b.valuation - a.valuation)
                .map((h) => (
                  <HoldingRow key={h.symbol} h={h} totalValue={totalValue} />
                ))}
            </div>
          </div>

          {/* 리밸런싱 제안 */}
          {(concentration.warning || heavyPositions.length > 0) && (
            <div className="rounded-2xl border border-amber-500/20 bg-amber-950/10 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <TrendingDown size={13} className="text-amber-400" />
                <p className="text-xs font-bold text-amber-300">리밸런싱 제안</p>
              </div>
              <ul className="space-y-1 text-[11px] text-slate-400">
                {concentration.warning && (
                  <li>• 최대 섹터 비중 {concentration.top1Pct.toFixed(0)}% → 40% 이하로 분산 권장</li>
                )}
                {heavyPositions.map((h) => (
                  <li key={h.symbol}>
                    • {h.name || h.symbol}: {((h.valuation / totalValue) * 100).toFixed(0)}% → 20% 이하로 비중 조정 권장
                  </li>
                ))}
                {maxLoss.totalLossPct > 15 && (
                  <li>• 손절가 기준 포트폴리오 최대 손실 {maxLoss.totalLossPct.toFixed(1)}% — 포지션 축소 또는 손절가 조정</li>
                )}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
