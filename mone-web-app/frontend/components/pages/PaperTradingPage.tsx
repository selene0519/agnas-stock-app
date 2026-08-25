"use client";

import { useEffect, useState } from "react";
import { mone, type Market } from "@/lib/api";
import { ShadowCapitalGate } from "@/components/ShadowCapitalGate";
import { RefreshCw, History, BarChart3, AlertTriangle, CheckCircle2 } from "lucide-react";

type Position = {
  market: string;
  symbol: string;
  name: string;
  quantity: number;
  avgPrice: number;
  currentPrice: number | null;
  cost: number;
  valuation: number;
  pnl: number;
  pnlPct: number;
  stopPrice?: number | null;
  targetPrice?: number | null;
};

type Trade = {
  id: string;
  createdAt: string;
  market: string;
  symbol: string;
  name: string;
  action: "BUY" | "SELL";
  price: number;
  quantity: number;
  totalValue: number;
  memo: string;
};

type Summary = {
  agentLabel?: string;
  seed: number;
  cash: number;
  invested: number;
  valuation: number;
  portfolioValue: number;
  unrealizedPnl: number;
  totalPnl: number;
  totalReturnPct: number;
  positionCount: number;
  tradeCount: number;
};

type TabId = "positions" | "history";

function fmt(v: number, market: string) {
  if (!isFinite(v)) return "—";
  return market === "us"
    ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : `${Math.round(v).toLocaleString("ko-KR")}원`;
}

function PnlBadge({ pct, abs }: { pct: number; abs: number }) {
  const pos = pct >= 0;
  return (
    <div className={`text-right ${pos ? "text-emerald-400" : "text-red-400"}`}>
      <div className="text-xs font-bold font-mono">{pos ? "+" : ""}{pct.toFixed(2)}%</div>
      <div className="text-[10px] opacity-80">{pos ? "+" : ""}{Math.round(abs).toLocaleString("ko-KR")}</div>
    </div>
  );
}

function SummaryBar({ summary, market }: { summary: Summary; market: string }) {
  const returnPos = summary.totalReturnPct >= 0;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {[
        { label: "시드", value: fmt(summary.seed, market) },
        { label: "현금 잔고", value: fmt(summary.cash, market) },
        { label: "평가금액", value: fmt(summary.valuation, market) },
        {
          label: "총 수익률",
          value: `${returnPos ? "+" : ""}${summary.totalReturnPct.toFixed(2)}%`,
          color: returnPos ? "text-emerald-400" : "text-red-400",
        },
      ].map(({ label, value, color }) => (
        <div key={label} className="rounded-xl border border-slate-700/40 bg-slate-800/30 px-3 py-2.5 text-center">
          <div className="text-[10px] text-slate-400">{label}</div>
          <div className={`mt-0.5 text-sm font-bold font-mono ${color || "text-slate-200"}`}>{value}</div>
        </div>
      ))}
    </div>
  );
}

type DrawdownInfo = {
  drawdownPct: number;
  peakValue: number;
  portfolioValue: number;
  alertLevel: "GREEN" | "YELLOW" | "RED";
};

function DrawdownBanner({ dd, market }: { dd: DrawdownInfo; market: string }) {
  const { drawdownPct, peakValue, portfolioValue, alertLevel } = dd;
  const cfg = {
    GREEN: {
      bar: "bg-emerald-500/15 border-emerald-500/30",
      text: "text-emerald-400",
      icon: <CheckCircle2 size={14} className="text-emerald-400" />,
      label: "정상",
    },
    YELLOW: {
      bar: "bg-amber-500/15 border-amber-500/30",
      text: "text-amber-400",
      icon: <AlertTriangle size={14} className="text-amber-400" />,
      label: "주의",
    },
    RED: {
      bar: "bg-red-500/15 border-red-500/30",
      text: "text-red-400",
      icon: <AlertTriangle size={14} className="text-red-400" />,
      label: "경고",
    },
  }[alertLevel];

  const fmtVal = (v: number) =>
    market === "us"
      ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
      : `${Math.round(v).toLocaleString("ko-KR")}원`;

  return (
    <div className={`flex items-center justify-between rounded-xl border px-3 py-2 ${cfg.bar}`}>
      <div className="flex items-center gap-2">
        {cfg.icon}
        <span className="text-xs text-slate-400">드로다운</span>
        <span className={`text-xs font-bold font-mono ${cfg.text}`}>
          {drawdownPct > 0 ? `-${drawdownPct.toFixed(2)}%` : "0.00%"}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cfg.text} ${alertLevel === "RED" ? "bg-red-500/15" : alertLevel === "YELLOW" ? "bg-amber-500/15" : "bg-emerald-500/15"}`}>
          {cfg.label}
        </span>
      </div>
      <div className="flex gap-3 text-[10px] text-slate-400">
        <span>피크 {fmtVal(peakValue)}</span>
        <span>현재 {fmtVal(portfolioValue)}</span>
      </div>
    </div>
  );
}

function PositionCard({ p, market }: { p: Position; market: string }) {
  const cur = p.currentPrice ?? p.avgPrice;
  const stopDist = p.stopPrice ? ((cur - p.stopPrice) / p.stopPrice * 100) : null;
  const targetDist = p.targetPrice ? ((p.targetPrice - cur) / cur * 100) : null;
  const stopAlert = stopDist !== null && stopDist < 5;
  const targetAlert = targetDist !== null && targetDist < 5;

  return (
    <div className={`rounded-2xl border bg-slate-900/50 px-4 py-3 ${stopAlert ? "border-red-500/50" : targetAlert ? "border-emerald-500/40" : "border-slate-700/60"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-slate-100">{p.name}</span>
            <span className="text-[11px] font-mono text-slate-400">{p.symbol}</span>
            {stopAlert && <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-red-400">손절 근접 {stopDist!.toFixed(1)}%</span>}
            {targetAlert && !stopAlert && <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400">목표 근접 {targetDist!.toFixed(1)}%</span>}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-400">
            {p.quantity}주 · 평균 {fmt(p.avgPrice, market)}
            {p.currentPrice && <span className="ml-2">현재 {fmt(p.currentPrice, market)}</span>}
          </div>
          {(p.stopPrice || p.targetPrice) && (
            <div className="mt-1 flex gap-3 text-[10px]">
              {p.stopPrice && <span className="text-red-400">손절 {fmt(p.stopPrice, market)}</span>}
              {p.targetPrice && <span className="text-emerald-400">목표 {fmt(p.targetPrice, market)}</span>}
            </div>
          )}
        </div>
        <PnlBadge pct={p.pnlPct} abs={p.pnl} />
      </div>
    </div>
  );
}

export default function PaperTradingPage({
  initialOrder,
}: {
  initialOrder?: { symbol: string; name: string; price: number; market: "kr" | "us"; quantity?: number };
} = {}) {
  const [market, setMarket] = useState<Market>(initialOrder?.market ?? "kr");
  const [tab, setTab] = useState<TabId>("positions");
  const [positions, setPositions] = useState<Position[]>([]);
  const [history, setHistory] = useState<Trade[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [drawdown, setDrawdown] = useState<DrawdownInfo | null>(null);
  const [accountMeta, setAccountMeta] = useState({
    agentLabel: "",
    proofStatus: "WARMING_UP",
    lastNavDate: "",
    closedTradeCount: 0,
  });

  async function loadAll() {
    setLoading(true);
    setError("");
    try {
      const response: any = await mone.aiPaperStatus({ market });
      const account = response?.markets?.[market];
      if (!account) throw new Error("AI Paper account missing");
      const accountSummary = account.summary as Summary;
      const metrics = account.liveMetrics || {};
      setPositions((account.positions || []) as Position[]);
      setHistory((account.tradeHistory || []) as Trade[]);
      setSummary(accountSummary || null);
      const mdd = Math.abs(Number(metrics.mddPct || 0));
      setDrawdown({
        drawdownPct: mdd,
        peakValue: Number(metrics.peakValue || accountSummary?.seed || 0),
        portfolioValue: Number(metrics.currentValue || accountSummary?.portfolioValue || 0),
        alertLevel: mdd >= 10 ? "RED" : mdd >= 5 ? "YELLOW" : "GREEN",
      });
      setAccountMeta({
        agentLabel: String(account.activeAgent?.label || accountSummary?.agentLabel || ""),
        proofStatus: String(metrics.proofStatus || "WARMING_UP"),
        lastNavDate: String(metrics.lastNavDate || ""),
        closedTradeCount: Number(account.realizedTrades?.closedTradeCount || 0),
      });
    } catch {
      setPositions([]);
      setHistory([]);
      setSummary(null);
      setDrawdown(null);
      setError("AI 검증계좌 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setTab("positions");
    void loadAll();
  }, [market]);

  return (
    <div className="space-y-5 animate-fade-in">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-primary)]">AI Paper 검증 계좌</h1>
          <p className="mt-1 text-xs text-slate-400">실제 주문 없이 AI 추천을 동일 원장에 가상 체결해 손익·낙폭을 검증합니다.</p>
        </div>
        <div className="flex items-center gap-2">
          {(["kr", "us"] as Market[]).map((mk) => (
            <button
              key={mk}
              onClick={() => setMarket(mk)}
              className={`min-h-11 rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors ${market === mk ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}
            >
              {mk === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button
            onClick={loadAll}
            disabled={loading}
            type="button"
            title="새로고침"
            aria-label="AI 가상투자 데이터 새로고침"
            className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-slate-700 px-2 py-1.5 text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            <RefreshCw size={14} aria-hidden="true" className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      <ShadowCapitalGate market={market} />

      {initialOrder && (
        <div className="rounded-xl border border-teal-500/25 bg-teal-500/10 px-3 py-2 text-xs text-teal-200">
          {initialOrder.name || initialOrder.symbol} 후보는 수동으로 성과 원장에 섞지 않고 다음 AI Paper 주기에서 동일한 검증 게이트를 통과할 때만 반영됩니다.
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>
      )}

      {summary && (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-slate-700/50 bg-slate-900/40 px-3 py-2 text-[11px] text-slate-400">
            <span className="font-semibold text-slate-200">{accountMeta.agentLabel}</span>
            <span>검증 {accountMeta.proofStatus}</span>
            <span>청산 {accountMeta.closedTradeCount}건</span>
            <span>최근 NAV {accountMeta.lastNavDate || "준비 중"}</span>
          </div>
          <SummaryBar summary={summary} market={market} />
        </>
      )}

      {drawdown && <DrawdownBanner dd={drawdown} market={market} />}

      <div className="flex w-fit gap-1 rounded-lg bg-slate-800/50 p-1">
        {([
          { id: "positions" as TabId, label: "AI 포지션", icon: <BarChart3 size={12} /> },
          { id: "history" as TabId, label: "AI 체결", icon: <History size={12} /> },
        ]).map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex min-h-11 items-center gap-1.5 rounded-md px-3 py-2 text-xs font-semibold transition-colors ${tab === id ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}
          >
            {icon}{label}
          </button>
        ))}
      </div>

      {tab === "positions" && (
        <div className="space-y-2">
          {positions.length === 0 ? (
            <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-8 text-center">
              <div className="text-sm font-semibold text-slate-200">현재 AI 보유 포지션이 없습니다</div>
              <p className="mt-1 text-xs leading-5 text-slate-400">추천이 비용차감 기대값·독립검증·위험예산 게이트를 통과할 때만 자동으로 가상 기록됩니다.</p>
            </div>
          ) : positions.map((position) => (
            <PositionCard key={`${position.market}:${position.symbol}`} p={position} market={market} />
          ))}
        </div>
      )}

      {tab === "history" && (
        <div className="space-y-2">
          {history.length === 0 ? (
            <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-8 text-center text-sm text-slate-400">AI 체결 내역 없음</div>
          ) : history.map((trade) => (
            <div key={trade.id} className="flex items-center justify-between rounded-xl border border-slate-700/40 bg-slate-800/30 px-3 py-2.5">
              <div className="flex items-center gap-2">
                <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${trade.action === "BUY" ? "border-emerald-500/30 text-emerald-400" : "border-red-500/30 text-red-400"}`}>
                  {trade.action === "BUY" ? "가상 매수" : "가상 매도"}
                </span>
                <div>
                  <span className="text-xs font-semibold text-slate-200">{trade.name}</span>
                  <span className="ml-1.5 text-[10px] text-slate-400">{trade.symbol}</span>
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs font-mono text-slate-200">{trade.quantity}주 × {fmt(Number(trade.price), market)}</div>
                <div className="text-[10px] text-slate-400">{String(trade.createdAt).slice(0, 16)}{trade.memo && ` · ${trade.memo}`}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
