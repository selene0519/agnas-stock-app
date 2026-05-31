"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

type Market = "all" | "kr" | "us";

function apiUrl(path: string) {
  return `/mone-api${path}`;
}

async function getJson(path: string) {
  const res = await fetch(apiUrl(path), { cache: "no-store" });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${detail}`.trim());
  }
  return res.json();
}

function dedupe(items: any[]) {
  const seen = new Set<string>();
  const out: any[] = [];
  for (const item of items || []) {
    const symbol = String(item.symbol || item.code || item.ticker || "").toUpperCase();
    const market = String(item.market || (symbol.match(/^\d{6}$/) ? "kr" : "us")).toLowerCase();
    const key = `${market}-${symbol}`;
    if (!symbol || seen.has(key)) continue;
    seen.add(key);
    out.push({ ...item, symbol, market });
  }
  return out;
}

function valueText(value: any, fallback = "-") {
  if (value === undefined || value === null || value === "") return fallback;
  if (value === "-") return fallback;
  return String(value);
}

function displayName(item: any) {
  const symbol = String(item.symbol || "").toUpperCase();
  const name = String(item.name || item.company || "").trim();
  return name && name !== symbol ? name : symbol;
}

function riskClass(risk: string) {
  if (risk === "위험" || risk === "HIGH") return "border-red-500/30 bg-red-500/10 text-red-300";
  if (risk === "주의" || risk === "WATCH") return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
}

export default function HoldingsPage() {
  const [market, setMarket] = useState<Market>("all");
  const [data, setData] = useState<any>({ items: [], summary: {} });
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const result = await getJson(`/api/holdings-clean?market=${market}&limit=500`);
      setData(result);
    } catch (error) {
      setData({ status: "ERROR", error: String(error), items: [], summary: {} });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [market]);

  const items = useMemo(() => dedupe(Array.isArray(data.items) ? data.items : []), [data.items]);
  const summary = data.summary || {};
  const riskCount = items.filter((item) => ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""))).length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">보유·리스크</h1>
          <p className="mt-1 text-sm text-slate-400">
            국장/미장 보유 현황, 중복 제거, 전일 종가 기준 등락률과 손절가 근접도를 확인합니다.
          </p>
          <p className="mt-1 font-mono text-xs text-slate-600">route: {data.routeVersion || data.status || "-"}</p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "kr", "us"] as Market[]).map((item) => (
          <button
            key={item}
            onClick={() => setMarket(item)}
            className={`rounded-xl px-4 py-2 text-sm ${
              market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"
            }`}
          >
            {item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card label="평가금액 합계" value={summary.totalValueText || "-"} />
        <Card label="총 평가손익" value={summary.totalPnlText || "0"} accent={Number(summary.totalPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
        <Card label="보유 종목" value={`${items.length}개`} />
        <Card label="주의/위험" value={`${riskCount}개`} accent={riskCount > 0 ? "text-amber-300" : "text-emerald-300"} />
      </div>

      {data.error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-300">{data.error}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((holding: any) => {
          const stopMissing = !holding.stopText || holding.stopText === "-";
          const targetMissing = !holding.targetText || holding.targetText === "-";
          return (
            <div key={`${holding.market}-${holding.symbol}`} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-slate-100">{displayName(holding)}</h2>
                    <span className="font-mono text-xs text-slate-500">{holding.symbol}</span>
                    <span className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-400">
                      {holding.market === "kr" ? "한국주식" : "미국주식"}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    출처: {holding.source || "-"} · 현재가: {holding.quoteSource || "-"} · OHLCV: {holding.ohlcvSource || "-"}
                  </p>
                </div>
                <span className={`rounded-xl border px-3 py-1 text-xs font-bold ${riskClass(holding.riskStatus)}`}>
                  {holding.riskStatus || "정상"}
                </span>
              </div>

              {(Array.isArray(holding.missingFields) && holding.missingFields.length > 0) || stopMissing || targetMissing ? (
                <div className="mt-3 flex flex-wrap gap-1">
                  {stopMissing && (
                    <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                      손절가 산출 필요
                    </span>
                  )}
                  {targetMissing && (
                    <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                      목표가 산출 필요
                    </span>
                  )}
                  {(holding.missingFields || []).map((field: string) => (
                    <span key={field} className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                      {field} 없음
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <Mini label="수량" value={valueText(holding.quantity)} />
                <Mini label="현재가" value={valueText(holding.currentPriceText, "현재가 산출 필요")} />
                <Mini label="등락률" value={valueText(holding.changePctText, "+0.00%")} accent={String(holding.changePctText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"} />
                <Mini label="평단" value={valueText(holding.avgPriceText)} />
                <Mini label="평가금액" value={valueText(holding.valuationText, "0")} />
                <Mini label="손익" value={valueText(holding.pnlText, "0")} accent={Number(holding.pnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                <Mini label="손절가" value={valueText(holding.stopText, "산출 필요")} accent={stopMissing ? "text-amber-300" : "text-red-300"} />
                <Mini label="목표가" value={valueText(holding.targetText, "산출 필요")} accent={targetMissing ? "text-amber-300" : "text-emerald-300"} />
              </div>

              <div className="mt-4 rounded-xl bg-slate-950 p-3">
                <div className="flex justify-between text-xs text-slate-400">
                  <span>손절가 근접도</span>
                  <span>
                    {holding.stopGapPct === null || holding.stopGapPct === undefined ? "손절가 없음" : `${Number(holding.stopGapPct).toFixed(2)}% 여유`}
                  </span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className={`h-full rounded-full ${Number(holding.stopGapPct || 99) <= 3 ? "bg-amber-400" : "bg-emerald-500"}`}
                    style={{ width: `${Math.max(8, Math.min(100, Number(holding.stopGapPct || 0) * 10))}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}

        {items.length === 0 && (
          <div className="col-span-full rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
            보유 종목이 없습니다.
          </div>
        )}
      </div>
    </div>
  );
}

function Card({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-2 font-mono text-2xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function Mini({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-xl bg-slate-950 p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-2 font-mono text-base font-bold ${accent}`}>{value}</div>
    </div>
  );
}
