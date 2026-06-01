"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { mone, type Market } from "@/lib/api";

type HoldingRow = {
  market: Market;
  symbol: string;
  name: string;
  quantity: string;
  avgPrice: string;
};

type WatchRow = {
  market: Market;
  symbol: string;
  name: string;
};

function cleanMarket(value: any): Market {
  const v = String(value || "kr").toLowerCase();
  return v === "us" ? "us" : "kr";
}

function cleanSymbol(symbol: string, market: Market) {
  const raw = String(symbol || "").trim();
  if (market === "kr") return raw.replace(/[^0-9]/g, "").padStart(6, "0").slice(-6);
  return raw.toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
}

function normalizeHolding(item: any): HoldingRow {
  const market = cleanMarket(item.market);
  return {
    market,
    symbol: cleanSymbol(item.symbol || item.code || item.ticker, market),
    name: String(item.name || item.companyName || "").trim(),
    quantity: String(item.quantity ?? item.qty ?? ""),
    avgPrice: String(item.avgPrice ?? item.avg_price ?? item.averagePrice ?? ""),
  };
}

function normalizeWatch(item: any): WatchRow {
  const market = cleanMarket(item.market);
  return {
    market,
    symbol: cleanSymbol(item.symbol || item.code || item.ticker, market),
    name: String(item.name || item.companyName || "").trim(),
  };
}

function emptyHolding(market: Market = "kr"): HoldingRow {
  return { market, symbol: "", name: "", quantity: "", avgPrice: "" };
}

function emptyWatch(market: Market = "kr"): WatchRow {
  return { market, symbol: "", name: "" };
}

function Field({
  value,
  onChange,
  placeholder,
  className = "",
  type = "text",
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  type?: string;
}) {
  return (
    <input
      value={value}
      type={type}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className={`w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-blue-500 ${className}`}
    />
  );
}

function MarketSelect({ value, onChange }: { value: Market; onChange: (value: Market) => void }) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value as Market)}
      className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-500"
    >
      <option value="kr">국장</option>
      <option value="us">미장</option>
    </select>
  );
}

export default function HoldingsWatchlistManager() {
  const [tab, setTab] = useState<"holdings" | "watchlist">("holdings");
  const [holdings, setHoldings] = useState<HoldingRow[]>([]);
  const [watchlist, setWatchlist] = useState<WatchRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const holdingErrors = useMemo(() => {
    return holdings
      .map((row, index) => {
        const symbol = cleanSymbol(row.symbol, row.market);
        const qty = Number(String(row.quantity).replace(/,/g, ""));
        const avg = Number(String(row.avgPrice).replace(/,/g, ""));
        if (!symbol) return `${index + 1}행: 종목코드/티커 필요`;
        if (row.market === "kr" && !/^\d{6}$/.test(symbol)) return `${index + 1}행: 국장 코드는 6자리`;
        if (!Number.isFinite(qty) || qty <= 0) return `${index + 1}행: 수량은 0보다 커야 함`;
        if (!Number.isFinite(avg) || avg <= 0) return `${index + 1}행: 평균단가는 0보다 커야 함`;
        return "";
      })
      .filter(Boolean);
  }, [holdings]);

  const watchErrors = useMemo(() => {
    return watchlist
      .map((row, index) => {
        const symbol = cleanSymbol(row.symbol, row.market);
        if (!symbol) return `${index + 1}행: 종목코드/티커 필요`;
        if (row.market === "kr" && !/^\d{6}$/.test(symbol)) return `${index + 1}행: 국장 코드는 6자리`;
        return "";
      })
      .filter(Boolean);
  }, [watchlist]);

  const load = async () => {
    setLoading(true);
    setMessage("");
    try {
      const [h, w] = await Promise.all([
        (mone as any).holdingsEdit?.({ market: "all" }) ?? mone.get("/api/holdings-edit", { market: "all" }),
        (mone as any).watchlistEdit?.({ market: "all" }) ?? mone.get("/api/watchlist-edit", { market: "all" }),
      ]);
      setHoldings(Array.isArray(h?.items) ? h.items.map(normalizeHolding) : []);
      setWatchlist(Array.isArray(w?.items) ? w.items.map(normalizeWatch) : []);
      setMessage("보유/관심종목을 불러왔습니다.");
    } catch (error) {
      setMessage(`불러오기 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const saveHoldings = async () => {
    if (holdingErrors.length) {
      setMessage(holdingErrors[0]);
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const items = holdings.map((row) => ({
        market: row.market,
        symbol: cleanSymbol(row.symbol, row.market),
        name: row.name.trim(),
        quantity: Number(String(row.quantity).replace(/,/g, "")),
        avgPrice: Number(String(row.avgPrice).replace(/,/g, "")),
      }));
      const result = await ((mone as any).saveHoldingsEdit?.({ items }) ?? mone.get("/api/holdings-edit/save", {}));
      if (result?.status === "ERROR") throw new Error(result.error || "저장 실패");
      setMessage(`보유종목 저장 완료 · 백업 ${result?.backupCount ?? 0}개`);
      window.dispatchEvent(new CustomEvent("mone-holdings-updated"));
    } catch (error) {
      setMessage(`저장 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSaving(false);
    }
  };

  const saveWatchlist = async () => {
    if (watchErrors.length) {
      setMessage(watchErrors[0]);
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      const items = watchlist.map((row) => ({
        market: row.market,
        symbol: cleanSymbol(row.symbol, row.market),
        name: row.name.trim(),
      }));
      const result = await ((mone as any).saveWatchlistEdit?.({ items }) ?? mone.get("/api/watchlist-edit/save", {}));
      if (result?.status === "ERROR") throw new Error(result.error || "저장 실패");
      setMessage(`관심종목 저장 완료 · 백업 ${result?.backupCount ?? 0}개`);
      window.dispatchEvent(new CustomEvent("mone-watchlist-updated"));
    } catch (error) {
      setMessage(`저장 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-lg font-bold text-slate-100">보유·관심종목 관리</div>
          <p className="mt-1 text-sm text-slate-400">
            앱에서 직접 보유종목과 관심종목을 추가·수정·삭제합니다. 저장 전 기존 CSV는 자동 백업됩니다.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50"
        >
          <RefreshCw size={16} /> 다시 불러오기
        </button>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          onClick={() => setTab("holdings")}
          className={`rounded-xl px-4 py-2 text-sm ${tab === "holdings" ? "bg-blue-600 text-white" : "bg-slate-950 text-slate-400"}`}
        >
          보유종목 수정
        </button>
        <button
          onClick={() => setTab("watchlist")}
          className={`rounded-xl px-4 py-2 text-sm ${tab === "watchlist" ? "bg-blue-600 text-white" : "bg-slate-950 text-slate-400"}`}
        >
          관심종목 수정
        </button>
      </div>

      {message && (
        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 text-sm text-slate-300">{message}</div>
      )}

      {tab === "holdings" ? (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-12 gap-2 px-1 text-xs text-slate-500">
            <div className="col-span-2">시장</div>
            <div className="col-span-2">종목코드/티커</div>
            <div className="col-span-3">종목명</div>
            <div className="col-span-2">수량</div>
            <div className="col-span-2">평균단가</div>
            <div className="col-span-1"></div>
          </div>
          {holdings.map((row, index) => (
            <div key={`${row.market}-${row.symbol}-${index}`} className="grid grid-cols-12 gap-2">
              <div className="col-span-2">
                <MarketSelect
                  value={row.market}
                  onChange={(market) => setHoldings((rows) => rows.map((r, i) => (i === index ? { ...r, market, symbol: cleanSymbol(r.symbol, market) } : r)))}
                />
              </div>
              <div className="col-span-2">
                <Field value={row.symbol} onChange={(symbol) => setHoldings((rows) => rows.map((r, i) => (i === index ? { ...r, symbol } : r)))} placeholder="005930" />
              </div>
              <div className="col-span-3">
                <Field value={row.name} onChange={(name) => setHoldings((rows) => rows.map((r, i) => (i === index ? { ...r, name } : r)))} placeholder="삼성전자" />
              </div>
              <div className="col-span-2">
                <Field value={row.quantity} onChange={(quantity) => setHoldings((rows) => rows.map((r, i) => (i === index ? { ...r, quantity } : r)))} placeholder="10" type="number" />
              </div>
              <div className="col-span-2">
                <Field value={row.avgPrice} onChange={(avgPrice) => setHoldings((rows) => rows.map((r, i) => (i === index ? { ...r, avgPrice } : r)))} placeholder="70000" type="number" />
              </div>
              <button
                onClick={() => setHoldings((rows) => rows.filter((_, i) => i !== index))}
                className="col-span-1 rounded-xl border border-red-500/30 text-red-300 hover:bg-red-500/10"
                aria-label="보유종목 삭제"
              >
                <Trash2 className="mx-auto" size={16} />
              </button>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setHoldings((rows) => [...rows, emptyHolding("kr")])} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">
              <Plus size={16} /> 국장 보유 추가
            </button>
            <button onClick={() => setHoldings((rows) => [...rows, emptyHolding("us")])} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">
              <Plus size={16} /> 미장 보유 추가
            </button>
            <button onClick={saveHoldings} disabled={saving || holdingErrors.length > 0} className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50">
              <Save size={16} /> 보유종목 저장
            </button>
          </div>
          {holdingErrors.length > 0 && <div className="text-sm text-amber-300">{holdingErrors[0]}</div>}
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-10 gap-2 px-1 text-xs text-slate-500">
            <div className="col-span-2">시장</div>
            <div className="col-span-3">종목코드/티커</div>
            <div className="col-span-4">종목명</div>
            <div className="col-span-1"></div>
          </div>
          {watchlist.map((row, index) => (
            <div key={`${row.market}-${row.symbol}-${index}`} className="grid grid-cols-10 gap-2">
              <div className="col-span-2">
                <MarketSelect
                  value={row.market}
                  onChange={(market) => setWatchlist((rows) => rows.map((r, i) => (i === index ? { ...r, market, symbol: cleanSymbol(r.symbol, market) } : r)))}
                />
              </div>
              <div className="col-span-3">
                <Field value={row.symbol} onChange={(symbol) => setWatchlist((rows) => rows.map((r, i) => (i === index ? { ...r, symbol } : r)))} placeholder="005930" />
              </div>
              <div className="col-span-4">
                <Field value={row.name} onChange={(name) => setWatchlist((rows) => rows.map((r, i) => (i === index ? { ...r, name } : r)))} placeholder="삼성전자" />
              </div>
              <button
                onClick={() => setWatchlist((rows) => rows.filter((_, i) => i !== index))}
                className="col-span-1 rounded-xl border border-red-500/30 text-red-300 hover:bg-red-500/10"
                aria-label="관심종목 삭제"
              >
                <Trash2 className="mx-auto" size={16} />
              </button>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setWatchlist((rows) => [...rows, emptyWatch("kr")])} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">
              <Plus size={16} /> 국장 관심 추가
            </button>
            <button onClick={() => setWatchlist((rows) => [...rows, emptyWatch("us")])} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">
              <Plus size={16} /> 미장 관심 추가
            </button>
            <button onClick={saveWatchlist} disabled={saving || watchErrors.length > 0} className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50">
              <Save size={16} /> 관심종목 저장
            </button>
          </div>
          {watchErrors.length > 0 && <div className="text-sm text-amber-300">{watchErrors[0]}</div>}
        </div>
      )}
    </section>
  );
}
