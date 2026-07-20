"use client";

import { useEffect, useState } from "react";
import { mone, type Market } from "@/lib/api";
import { AlertTriangle, CheckCircle2, TrendingDown } from "lucide-react";
import { displayName } from "@/lib/moneDisplay";
import { toneClassName } from "@/lib/tone";

const PORTFOLIO_CACHE_KEY = "mone:portfolio-optimize-cache:v2";
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
  sector?: string;
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

function normalizeHoldingMarket(value: any, symbol: string, fallback: Market): "kr" | "us" {
  const rawMarket = String(value || "").toLowerCase();
  if (rawMarket === "kr" || rawMarket === "us") return rawMarket;
  if (fallback === "kr" || fallback === "us") return fallback;
  return /^\d+$/.test(String(symbol || "").trim()) ? "kr" : "us";
}

function cleanHoldingSymbol(symbol: string, market: Market | "kr" | "us") {
  const raw = String(symbol || "").trim();
  if (market === "kr" || (market === "all" && /^\d+$/.test(raw))) return raw.replace(/[^0-9]/g, "").padStart(6, "0").slice(-6);
  return raw.toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
}

function buildSectorLookup(market: Market, rows: any[]) {
  const lookup: Record<string, string> = {};
  for (const row of rows || []) {
    const sector = String(row?.sector || "").trim();
    if (!sector) continue;
    const symbols = Array.isArray(row?.symbols) ? row.symbols : [];
    for (const entry of symbols) {
      const symbol = typeof entry === "string" ? entry : entry?.symbol;
      const entryMarket = normalizeHoldingMarket(typeof entry === "object" ? entry?.market : "", symbol, market);
      lookup[`${entryMarket}:${cleanHoldingSymbol(symbol, entryMarket as Market)}`] = sector;
    }
  }
  return lookup;
}

function buildPortfolioData(holdings: Holding[]): PortfolioData {
  const totalValue = holdings.reduce((sum, h) => sum + h.valuation, 0);
  const bySector: Record<string, SectorRow> = {};

  for (const h of holdings) {
    const sector = String(h.sector || "기타").trim() || "기타";
    if (!bySector[sector]) {
      bySector[sector] = { sector, value: 0, pct: 0, symbols: [], maxLoss: 0 };
    }
    bySector[sector].value += h.valuation;
    bySector[sector].symbols.push(h.symbol);
    if (h.currentPrice > 0 && h.quantity > 0 && h.stop && h.stop > 0) {
      bySector[sector].maxLoss += Math.max(0, (h.currentPrice - h.stop) * h.quantity);
    }
  }

  const sectors = Object.values(bySector)
    .map((row) => ({
      ...row,
      value: Math.round(row.value),
      maxLoss: Math.round(row.maxLoss),
      pct: totalValue > 0 ? Number(((row.value / totalValue) * 100).toFixed(1)) : 0,
    }))
    .sort((a, b) => b.value - a.value);
  const totalLoss = sectors.reduce((sum, row) => sum + row.maxLoss, 0);
  const top1 = sectors[0]?.pct || 0;

  return {
    sectors,
    concentration: { top1Pct: top1, warning: top1 > 40 },
    maxLossSimulation: {
      totalLoss,
      totalLossPct: totalValue > 0 ? Number(((totalLoss / totalValue) * 100).toFixed(1)) : 0,
    },
    holdings,
    totalValue,
  };
}

function fallbackSector(holding: Pick<Holding, "name" | "symbol" | "sector">) {
  const existing = String(holding.sector || "").trim();
  const korean: Record<string, string> = { "Consumer Cyclical": "경기소비재", Technology: "기술", "Financial Services": "금융", "Communication Services": "커뮤니케이션", Industrials: "산업재", Healthcare: "헬스케어", Energy: "에너지", Utilities: "유틸리티", "Real Estate": "부동산", "Basic Materials": "소재" };
  if (korean[existing]) return korean[existing];
  if (existing && !/^(other|기타|미분류|unknown)$/i.test(existing)) return existing;
  const label = `${holding.name} ${holding.symbol}`.toUpperCase();
  if (/(TIGER|KODEX|ACE |ETF|ETN|SPY|QQQ|IWM|SCHD)/.test(label)) return "ETF";
  return "개별주";
}

function ConcentrationBar({ pct, label, count }: { pct: number; label: string; count: number }) {
  const isHigh = pct > 40;
  const isMed = pct > 25;
  const tone = isHigh ? "danger" : isMed ? "warning" : "safe";
  return (
    <div className={`space-y-1 mone-tone-${tone}`}>
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-slate-300 font-medium">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-slate-500">{count}종목</span>
          <span className={`font-bold ${isHigh || isMed ? "" : "text-slate-200"}`} style={isHigh || isMed ? { color: "var(--tone-fg)" } : undefined}>
            {pct.toFixed(1)}%
          </span>
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-slate-800">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.min(pct, 100)}%`, background: "var(--tone-fg)" }}
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

export default function PortfolioOptimizePanel({ market, riskBudget }: { market: "all" | "kr" | "us"; riskBudget?: any }) {
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
      const [sectorListResult, holdingsResult] = await Promise.allSettled([
        mone.sectorsList({ market }) as Promise<any>,
        mone.holdingsClean({ market, limit: 200 }) as Promise<any>,
      ]);
      const sectorList = sectorListResult.status === "fulfilled" && Array.isArray(sectorListResult.value?.items)
        ? sectorListResult.value.items
        : [];
      const holdingsRes = holdingsResult.status === "fulfilled" ? holdingsResult.value : null;
      setHoldingSource(
        holdingsRes?.authRequired ? "로그인 필요"
        : String(holdingsRes?.sourceSummary || holdingsRes?.authority || "").trim()
      );
      const sectorLookup = buildSectorLookup(market, sectorList);
      const items = (holdingsRes?.items || []) as any[];
      const parsed: Holding[] = items.map((h: any) => {
        const holdingMarket = normalizeHoldingMarket(h.market, h.symbol || "", market);
        return {
          symbol: h.symbol || "",
          name: displayName({ ...h, market: holdingMarket }) || h.symbol || "",
          market: holdingMarket,
          sector: fallbackSector({
            name: displayName({ ...h, market: holdingMarket }) || h.symbol || "",
            symbol: h.symbol || "",
            sector: h.sector || h.sectorLabel || h.industry || sectorLookup[`${holdingMarket}:${cleanHoldingSymbol(h.symbol || "", holdingMarket)}`],
          }),
          currentPrice: Number(h.currentPrice || 0),
          quantity: Number(h.quantity || 0),
          avgPrice: Number(h.avgPrice || h.averagePrice || 0),
          valuation: Number(h.valuation || h.marketValue || (Number(h.currentPrice || 0) * Number(h.quantity || 0))),
          pnlPct: Number(h.pnlPct || h.returnPct || 0),
          stop: h.stop || h.stopPrice ? Number(h.stop || h.stopPrice) : undefined,
          target: h.target || h.targetPrice ? Number(h.target || h.targetPrice) : undefined,
        };
      });
      const filteredHoldings = parsed.filter((h) => h.valuation > 0);
      const portfolioData = buildPortfolioData(filteredHoldings);
      setSectorData(portfolioData);
      setHoldings(filteredHoldings);
      writePortfolioCache(market, { sectorData: portfolioData, holdings: filteredHoldings });
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

  const displayHoldingByKey = new Map(holdings.map((holding) => [`${holding.market}:${holding.symbol}`, holding]));
  const budgetHoldings: Holding[] = Array.isArray(riskBudget?.items) ? riskBudget.items.map((item: any) => {
    const itemMarket = String(item.market || market);
    const itemSymbol = String(item.symbol || "");
    const displayHolding = displayHoldingByKey.get(`${itemMarket}:${itemSymbol}`);
    const displayedPnl = Number(displayHolding?.pnlPct ?? 0);
    return {
      symbol: itemSymbol, name: String(item.name || itemSymbol), market: itemMarket,
      sector: fallbackSector({ name: String(item.name || itemSymbol), symbol: itemSymbol, sector: item.sector }),
      currentPrice: Number(item.currentPrice || displayHolding?.currentPrice || 0), quantity: 0, avgPrice: Number(displayHolding?.avgPrice || 0),
      valuation: Number(item.value || 0), pnlPct: Number.isFinite(displayedPnl) ? displayedPnl : 0,
      stop: Number(item.stopPrice || 0) || undefined,
    };
  }) : [];
  const budgetByHolding = new Map<string, any>((Array.isArray(riskBudget?.items) ? riskBudget.items : []).map((item: any) => [
    `${String(item.market || market)}:${String(item.symbol || "")}`,
    item,
  ]));
  const baseHoldings = market === "all" && budgetHoldings.length > 0
    ? budgetHoldings.filter((holding) => holding.valuation > 0)
    : holdings.length > 0 ? holdings : budgetHoldings.filter((holding) => holding.valuation > 0);
  const analysisHoldings = baseHoldings.map((holding) => {
    const budgetItem = budgetByHolding.get(`${holding.market}:${holding.symbol}`);
    return {
      ...holding,
      sector: fallbackSector({
        name: holding.name,
        symbol: holding.symbol,
        sector: budgetItem?.sector || holding.sector,
      }),
    };
  });
  const fallbackPortfolio = buildPortfolioData(analysisHoldings);
  const totalValue = analysisHoldings.reduce((s, h) => s + h.valuation, 0);
  const maxPositionWeightPct = Number(riskBudget?.policy?.maxPositionWeightPct || 20);
  const heavyPositions = analysisHoldings.filter((h) => totalValue > 0 && (h.valuation / totalValue) * 100 > maxPositionWeightPct);
  const budgetSectors: SectorRow[] = (Array.isArray(riskBudget?.sectors) ? riskBudget.sectors : []).map((sector: any) => {
    const label = fallbackSector({ name: "", symbol: "", sector: sector.sector });
    const members = (Array.isArray(riskBudget?.items) ? riskBudget.items : [])
      .filter((item: any) => fallbackSector({ name: "", symbol: "", sector: item.sector }) === label)
      .map((item: any) => String(item.symbol || ""));
    return {
      sector: label,
      value: Number(riskBudget?.totalValue || totalValue) * Number(sector.weightPct || 0) / 100,
      pct: Number(sector.weightPct || 0),
      symbols: members,
      maxLoss: 0,
    };
  });
  const sectors: SectorRow[] = budgetSectors.length ? budgetSectors : (sectorData?.sectors?.length ? sectorData.sectors : fallbackPortfolio.sectors);
  const concentration = budgetSectors.length
    ? { top1Pct: Math.max(...budgetSectors.map((sector) => sector.pct), 0), warning: budgetSectors.some((sector) => sector.pct > 40) }
    : (sectorData?.sectors?.length ? sectorData.concentration : fallbackPortfolio.concentration);
  const calculatedMaxLoss = sectorData?.sectors?.length ? sectorData.maxLossSimulation : fallbackPortfolio.maxLossSimulation;
  const maxLoss = riskBudget?.status && !riskBudget?.authRequired
    ? {
        totalLoss: Number(riskBudget.totalLossAmount ?? (Number(riskBudget.totalValue || totalValue) * Number(riskBudget.totalLossBudgetPct || 0) / 100)),
        totalLossPct: Number(riskBudget.totalLossBudgetPct || 0),
      }
    : calculatedMaxLoss;
  const rebalancingItems = Array.isArray(riskBudget?.items)
    ? riskBudget.items.filter((item: any) => item.action === "REDUCE" || Number(item.weightPct || 0) > maxPositionWeightPct)
    : [];
  const moneyText = (value: number) => market === "us"
    ? `$${Math.round(value).toLocaleString("en-US")}`
    : `${Math.round(value).toLocaleString("ko-KR")}원`;

  const riskScore =
    (concentration.warning ? 2 : concentration.top1Pct > 25 ? 1 : 0) +
    (heavyPositions.length > 0 ? 1 : 0) +
    (maxLoss.totalLossPct > 15 ? 2 : maxLoss.totalLossPct > 8 ? 1 : 0);
  const riskLabel =
    riskScore >= 4 ? { text: "집중 위험", cls: toneClassName("danger") } :
    riskScore >= 2 ? { text: "주의", cls: toneClassName("warning") } :
    { text: "양호", cls: toneClassName("safe") };

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="text-sm font-bold text-slate-200">포트폴리오 분석</div>

      {loading && analysisHoldings.length === 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-6 text-center text-xs text-slate-500">
          분석 중...
        </div>
      )}

      {!loading && analysisHoldings.length === 0 && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-6 text-center text-xs text-slate-500">
          보유 종목 없음 — holdings-clean 기준으로 확인했습니다{holdingSource ? ` (${holdingSource})` : ""}.
        </div>
      )}

      {analysisHoldings.length > 0 && (
        <>
          {/* 리스크 종합 */}
          <div className={`flex items-center gap-2 rounded-xl px-3 py-2.5 ${riskLabel.cls}`}>
            {riskScore >= 3 ? (
              <AlertTriangle size={13} />
            ) : (
              <CheckCircle2 size={13} />
            )}
            <div>
              <span className="text-xs font-bold">{riskLabel.text}</span>
              <span className="ml-2 text-[11px] text-slate-400">
                총 {analysisHoldings.length}종목 ·{" "}
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
                -{moneyText(maxLoss.totalLoss)} · {maxLoss.totalLossPct.toFixed(1)}%
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
              {(rebalancingItems.length > 0 || heavyPositions.length > 0) && (
                <span className="text-[10px] text-amber-400 font-semibold">
                  {Math.max(rebalancingItems.length, heavyPositions.length)}종목 비중 조정
                </span>
              )}
            </div>
            <div className="space-y-1.5">
              {[...analysisHoldings]
                .sort((a, b) => b.valuation - a.valuation)
                .map((h) => (
                  <HoldingRow key={h.symbol} h={h} totalValue={totalValue} />
                ))}
            </div>
          </div>

          {/* 리밸런싱 제안 */}
          {(concentration.warning || heavyPositions.length > 0 || rebalancingItems.length > 0) && (
            <div className="rounded-2xl border border-amber-500/20 bg-amber-950/10 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <TrendingDown size={13} className="text-amber-400" />
                <p className="text-xs font-bold text-amber-300">리밸런싱 제안</p>
              </div>
              <ul className="space-y-1 text-[11px] text-slate-400">
                {concentration.warning && (
                  <li>• 최대 섹터 비중 {concentration.top1Pct.toFixed(0)}% → 40% 이하로 분산 권장</li>
                )}
                {rebalancingItems.map((item: any) => (
                  <li key={`${item.market}-${item.symbol}`}>
                    • {item.name || item.symbol}: {Number(item.weightPct || 0).toFixed(1)}% → {Number(item.recommendedWeightPct || maxPositionWeightPct).toFixed(1)}% 조정 제안
                  </li>
                ))}
                {rebalancingItems.length === 0 && heavyPositions.map((h) => (
                  <li key={h.symbol}>
                    • {h.name || h.symbol}: {((h.valuation / totalValue) * 100).toFixed(0)}% → {maxPositionWeightPct.toFixed(0)}% 이하로 비중 조정 권장
                  </li>
                ))}
                {maxLoss.totalLossPct > 15 && (
                  <li>• 손절가 기준 포트폴리오 최대 손실 {moneyText(maxLoss.totalLoss)} ({maxLoss.totalLossPct.toFixed(1)}%) — 포지션 축소 또는 손절가 조정</li>
                )}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
