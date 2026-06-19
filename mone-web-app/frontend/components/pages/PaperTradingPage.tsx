"use client";

import { useEffect, useState } from "react";
import { mone, type Market } from "@/lib/api";
import { TrendingUp, TrendingDown, RefreshCw, Plus, Minus, RotateCcw, History, BarChart3 } from "lucide-react";

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

type TabId = "positions" | "history" | "trade";

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
          <div className="text-[10px] text-slate-500">{label}</div>
          <div className={`mt-0.5 text-sm font-bold font-mono ${color || "text-slate-200"}`}>{value}</div>
        </div>
      ))}
    </div>
  );
}

function TradeForm({
  market,
  action,
  onDone,
  initialValues,
}: {
  market: Market;
  action: "buy" | "sell";
  onDone: () => void;
  initialValues?: { symbol?: string; name?: string; price?: string };
}) {
  const [symbol, setSymbol] = useState(initialValues?.symbol ?? "");
  const [name, setName] = useState(initialValues?.name ?? "");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState(initialValues?.price ?? "");
  const [memo, setMemo] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  async function submit() {
    if (!symbol || !quantity) return;
    setLoading(true);
    setResult(null);
    try {
      const qty = parseFloat(quantity);
      const prc = price ? parseFloat(price) : undefined;
      const res: any =
        action === "buy"
          ? await mone.paperBuy({ symbol: symbol.trim(), market, quantity: qty, price: prc, name: name.trim(), memo })
          : await mone.paperSell({ symbol: symbol.trim(), market, quantity: qty, price: prc, memo });
      setResult({ ok: res.ok === true, message: res.message || res.error || "완료" });
      if (res.ok) {
        setSymbol(""); setName(""); setQuantity(""); setPrice(""); setMemo("");
        setTimeout(onDone, 800);
      }
    } catch {
      setResult({ ok: false, message: "네트워크 오류" });
    } finally {
      setLoading(false);
    }
  }

  const isBuy = action === "buy";
  const accentBg = isBuy ? "bg-emerald-600 hover:bg-emerald-500" : "bg-red-600 hover:bg-red-500";

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="space-y-1">
          <span className="text-[10px] text-slate-500">종목 코드 *</span>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder={market === "kr" ? "005930" : "AAPL"}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-slate-500 focus:outline-none"
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] text-slate-500">종목명 (선택)</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="삼성전자"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-slate-500 focus:outline-none"
          />
        </label>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="space-y-1">
          <span className="text-[10px] text-slate-500">수량 *</span>
          <input
            type="number"
            min="0.0001"
            step="1"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="10"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-slate-500 focus:outline-none"
          />
        </label>
        <label className="space-y-1">
          <span className="text-[10px] text-slate-500">체결가 (비워두면 현재가)</span>
          <input
            type="number"
            min="0"
            step="1"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="자동"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-slate-500 focus:outline-none"
          />
        </label>
      </div>
      <label className="block space-y-1">
        <span className="text-[10px] text-slate-500">메모 (선택)</span>
        <input
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          placeholder="매수 이유 등 자유 기록"
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-slate-500 focus:outline-none"
        />
      </label>
      <button
        onClick={submit}
        disabled={loading || !symbol || !quantity}
        className={`w-full rounded-xl py-2.5 text-sm font-bold text-white transition-colors disabled:opacity-40 ${accentBg}`}
      >
        {loading ? "처리 중..." : isBuy ? "가상 매수" : "가상 매도"}
      </button>
      {result && (
        <div
          className={`rounded-xl border px-3 py-2 text-xs ${result.ok ? "border-emerald-500/20 bg-emerald-950/10 text-emerald-300" : "border-red-500/20 bg-red-950/10 text-red-300"}`}
        >
          {result.message}
        </div>
      )}
    </div>
  );
}

export default function PaperTradingPage({
  initialOrder,
}: {
  initialOrder?: { symbol: string; name: string; price: number; market: "kr" | "us" };
} = {}) {
  const [market, setMarket] = useState<Market>(initialOrder?.market ?? "kr");
  const [tab, setTab] = useState<TabId>(initialOrder ? "trade" : "positions");
  const [tradeAction, setTradeAction] = useState<"buy" | "sell">("buy");
  const [positions, setPositions] = useState<Position[]>([]);
  const [history, setHistory] = useState<Trade[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [cash, setCash] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [resetConfirm, setResetConfirm] = useState(false);
  const [seedInput, setSeedInput] = useState<string>("");
  const [showSeedInput, setShowSeedInput] = useState(false);

  async function loadAll() {
    setLoading(true);
    try {
      const [posRes, histRes, sumRes] = await Promise.all([
        mone.paperPositions({ market }) as Promise<any>,
        mone.paperHistory({ market, limit: 50 }) as Promise<any>,
        mone.paperSummary({ market }) as Promise<any>,
      ]);
      setPositions((posRes?.items || []) as Position[]);
      setCash((posRes?.cash || {}) as Record<string, number>);
      setHistory((histRes?.items || []) as Trade[]);
      const mktSummary = sumRes?.markets?.[market] as Summary | undefined;
      setSummary(mktSummary || null);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  async function handleReset() {
    if (!resetConfirm) { setResetConfirm(true); setShowSeedInput(true); return; }
    const seedVal = parseFloat(seedInput);
    const opts = market === "kr"
      ? { seedKr: isFinite(seedVal) && seedVal > 0 ? seedVal : undefined }
      : { seedUs: isFinite(seedVal) && seedVal > 0 ? seedVal : undefined };
    await mone.paperReset(market, opts);
    setResetConfirm(false);
    setShowSeedInput(false);
    setSeedInput("");
    loadAll();
  }

  useEffect(() => {
    loadAll();
    setResetConfirm(false);
    setShowSeedInput(false);
    setSeedInput("");
  }, [market]);

  const cashVal = cash[market] ?? 0;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* 헤더 */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">모의투자</h1>
          <p className="mt-1 text-xs text-slate-400">가상 자금으로 실전처럼 매매 연습 — 현재가 기준 자동 체결</p>
        </div>
        <div className="flex items-center gap-2">
          {(["kr", "us"] as Market[]).map((mk) => (
            <button
              key={mk}
              onClick={() => setMarket(mk)}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors ${market === mk ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}
            >
              {mk === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button
            onClick={loadAll}
            disabled={loading}
            className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1.5 text-[11px] text-slate-400 hover:bg-slate-800 disabled:opacity-50"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* 요약 */}
      {summary && <SummaryBar summary={summary} market={market} />}

      {/* 탭 */}
      <div className="flex w-fit gap-1 rounded-lg bg-slate-800/50 p-1">
        {([
          { id: "positions" as TabId, label: "포지션", icon: <BarChart3 size={12} /> },
          { id: "history" as TabId, label: "체결 내역", icon: <History size={12} /> },
          { id: "trade" as TabId, label: "주문", icon: <Plus size={12} /> },
        ]).map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-semibold transition-colors ${tab === id ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}
          >
            {icon}{label}
          </button>
        ))}
      </div>

      {/* 포지션 탭 */}
      {tab === "positions" && (
        <div className="space-y-2">
          {positions.length === 0 ? (
            <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-8 text-center text-sm text-slate-500">
              보유 포지션 없음 — 주문 탭에서 가상 매수를 시작하세요
            </div>
          ) : (
            positions.map((p) => (
              <div
                key={p.symbol}
                className="flex items-center justify-between rounded-2xl border border-slate-700/60 bg-slate-900/50 px-4 py-3"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-slate-100">{p.name}</span>
                    <span className="text-[11px] font-mono text-slate-500">{p.symbol}</span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-slate-400">
                    {p.quantity}주 · 평균 {Math.round(p.avgPrice).toLocaleString("ko-KR")}원
                    {p.currentPrice && (
                      <span className="ml-2">현재가 {Math.round(p.currentPrice).toLocaleString("ko-KR")}원</span>
                    )}
                  </div>
                </div>
                <PnlBadge pct={p.pnlPct} abs={p.pnl} />
              </div>
            ))
          )}
        </div>
      )}

      {/* 체결 내역 탭 */}
      {tab === "history" && (
        <div className="space-y-2">
          {history.length === 0 ? (
            <div className="rounded-xl border border-slate-700 bg-slate-900/50 px-4 py-8 text-center text-sm text-slate-500">
              체결 내역 없음
            </div>
          ) : (
            history.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between rounded-xl border border-slate-700/40 bg-slate-800/30 px-3 py-2.5"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${t.action === "BUY" ? "border-emerald-500/30 text-emerald-400" : "border-red-500/30 text-red-400"}`}
                  >
                    {t.action === "BUY" ? "매수" : "매도"}
                  </span>
                  <div>
                    <span className="text-xs font-semibold text-slate-200">{t.name}</span>
                    <span className="ml-1.5 text-[10px] text-slate-500">{t.symbol}</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-mono text-slate-200">
                    {t.quantity}주 × {Math.round(Number(t.price)).toLocaleString("ko-KR")}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    {String(t.createdAt).slice(0, 16)} {t.memo && `· ${t.memo}`}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* 주문 탭 */}
      {tab === "trade" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-xl border border-slate-700/40 bg-slate-800/30 px-3 py-2">
            <span className="text-xs text-slate-400">
              {market === "kr" ? "현금 잔고" : "Cash"}
            </span>
            <span className="font-mono text-sm font-bold text-slate-200">
              {fmt(cashVal, market)}
            </span>
          </div>

          <div className="flex gap-2">
            {(["buy", "sell"] as const).map((a) => (
              <button
                key={a}
                onClick={() => setTradeAction(a)}
                className={`flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2.5 text-sm font-bold transition-colors ${tradeAction === a
                  ? a === "buy"
                    ? "bg-emerald-600 text-white"
                    : "bg-red-600 text-white"
                  : "bg-slate-800/60 text-slate-400 hover:text-white"
                }`}
              >
                {a === "buy" ? <Plus size={13} /> : <Minus size={13} />}
                {a === "buy" ? "매수" : "매도"}
              </button>
            ))}
          </div>

          <TradeForm
            key={initialOrder ? `${initialOrder.symbol}-${initialOrder.market}` : "manual"}
            market={market}
            action={tradeAction}
            onDone={loadAll}
            initialValues={initialOrder ? {
              symbol: initialOrder.symbol,
              name: initialOrder.name,
              price: initialOrder.price > 0 ? String(Math.round(initialOrder.price)) : "",
            } : undefined}
          />
        </div>
      )}

      {/* 초기화 */}
      <div className="flex flex-col items-end gap-2 pt-2">
        {showSeedInput && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-500">새 시드 금액</span>
            <input
              type="number"
              min="1"
              value={seedInput}
              onChange={(e) => setSeedInput(e.target.value)}
              placeholder={market === "kr" ? "5000000" : "5000"}
              className="w-36 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-100 placeholder-slate-600 focus:border-slate-500 focus:outline-none"
            />
            <button
              onClick={() => { setShowSeedInput(false); setResetConfirm(false); setSeedInput(""); }}
              className="text-[11px] text-slate-600 hover:text-slate-400"
            >
              취소
            </button>
          </div>
        )}
        <button
          onClick={handleReset}
          className="flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] text-slate-500 hover:border-red-500/40 hover:text-red-400"
        >
          <RotateCcw size={11} />
          {resetConfirm ? "정말 초기화하시겠습니까? (한 번 더 클릭)" : `${market.toUpperCase()} 페이퍼 초기화`}
        </button>
      </div>
    </div>
  );
}
