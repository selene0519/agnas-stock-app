"use client";

import { useEffect, useMemo, useState } from "react";
import { Calculator } from "lucide-react";
import type { Horizon, Mode } from "@/lib/api";
import { displayName, horizonLabel, modeLabel, shouldHideSizingForTrust } from "@/lib/moneDisplay";

const LS_CAPITAL_KEY = "mone:capital";
const LEGACY_CASH_KEY = "mone_cash_amount";

const MODE_CAPS: Record<string, number> = {
  conservative: 0.05,
  balanced: 0.10,
  aggressive: 0.15,
};

interface SizingRow {
  symbol: string;
  name: string;
  mode: string;
  horizon: string;
  entry: number;
  probability: number;
  rr: number;
  halfKelly: number;
  amount: number;
  qty: number;
  ev: number;
}

function isEntryCandidate(item: any) {
  const bucket = String(item.decisionBucket || item.bucket || "");
  const decision = String(item.decision || item.action || "");
  return (
    bucket.includes("오늘") ||
    bucket.toLowerCase().includes("today") ||
    decision.toUpperCase() === "BUY"
  );
}

function calcSizing(items: any[], capital: number): SizingRow[] {
  const seen = new Set<string>();
  return (items || [])
    .filter(isEntryCandidate)
    .filter((item) => !shouldHideSizingForTrust(item))
    .flatMap((item) => {
      const mode = String(item._mode || item.mode || "balanced");
      const horizon = String(item._horizon || item.horizon || "swing");
      const key = `${item.symbol}-${mode}-${horizon}`;
      if (seen.has(key)) return [];
      seen.add(key);

      const entry = Number(item.entry || item.entryPrice || item.entry_price || 0);
      const probability = Math.min(Math.max(Number(item.probability || item.winRate || 55) / 100, 0.3), 0.8);
      const rr = Math.max(Number(item.rrActual || item.rr || item.riskReward || 1.5), 0.5);
      if (entry <= 0 || capital <= 0) return [];

      const kelly = Math.max(0, probability - (1 - probability) / rr);
      const halfKelly = Math.min(kelly / 2, MODE_CAPS[mode] ?? 0.1);
      const qty = Math.floor(Math.floor(capital * halfKelly) / entry);
      const amount = qty * entry;

      return [{
        symbol: String(item.symbol || ""),
        name: displayName(item),
        mode,
        horizon,
        entry,
        probability,
        rr,
        halfKelly,
        amount,
        qty,
        ev: Number(item.expectedValue || item.ev || 0),
      }];
    })
    .filter((row) => row.qty > 0)
    .sort((a, b) => b.halfKelly - a.halfKelly);
}

export default function PositionManager({ items, loading = false }: { items: any[]; loading?: boolean }) {
  const [capital, setCapital] = useState(0);
  const [inputVal, setInputVal] = useState("");

  useEffect(() => {
    try {
      const saved = Number(window.localStorage.getItem(LS_CAPITAL_KEY) || window.localStorage.getItem(LEGACY_CASH_KEY) || 0);
      if (saved >= 100_000) {
        setCapital(saved);
        setInputVal(String(saved));
      }
    } catch {}
  }, []);

  function handleCapitalChange(raw: string) {
    const clean = raw.replace(/[^0-9]/g, "");
    setInputVal(clean);
    const value = Number(clean);
    setCapital(value);
    if (value >= 100_000) {
      try {
        window.localStorage.setItem(LS_CAPITAL_KEY, String(value));
        window.localStorage.setItem(LEGACY_CASH_KEY, String(value));
        window.dispatchEvent(new CustomEvent("mone-cash-updated", { detail: { cash: value } }));
      } catch {}
    }
  }

  const rows = useMemo(() => calcSizing(items, capital), [items, capital]);
  const totalAllocated = rows.reduce((sum, row) => sum + row.amount, 0);
  const remaining = capital - totalAllocated;
  const allocPct = capital > 0 ? (totalAllocated / capital) * 100 : 0;

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <Calculator size={18} className="shrink-0 text-violet-300" />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-100">포지션 매니저</h2>
            <p className="text-xs text-slate-500">후보별 참고 금액과 모의 수량을 계산합니다.</p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-500">
          가용 예수금
          <input
            type="text"
            inputMode="numeric"
            value={inputVal ? Number(inputVal).toLocaleString("ko-KR") : ""}
            onChange={(event) => handleCapitalChange(event.target.value.replace(/,/g, ""))}
            placeholder="10,000,000"
            className="w-36 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-right font-mono text-sm text-slate-100 placeholder-slate-600 outline-none focus:border-violet-500"
          />
          원
        </label>
      </div>

      {loading ? (
        <div className="py-6 text-center text-sm text-slate-500">후보를 불러오는 중입니다.</div>
      ) : capital <= 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">가용 예수금을 입력하면 후보별 참고 금액과 모의 수량을 계산합니다.</div>
      ) : rows.length === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">현재 계산 가능한 관찰 후보가 없습니다. 지연/오류 데이터 후보는 모의 수량에서 제외됩니다.</div>
      ) : (
        <>
          <div className="mb-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
            <div className="mb-2 flex flex-wrap justify-between gap-2 text-[11px] text-slate-400">
              <span>계획 배분 <span className="font-mono text-slate-200">{Math.round(totalAllocated).toLocaleString("ko-KR")}원</span> ({allocPct.toFixed(1)}%)</span>
              <span>잔여 예수금 <span className={`font-mono ${remaining >= 0 ? "text-emerald-300" : "text-red-300"}`}>{Math.round(remaining).toLocaleString("ko-KR")}원</span></span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-800">
              <div
                className={`h-full rounded-full ${allocPct > 90 ? "bg-red-500" : allocPct > 60 ? "bg-amber-500" : "bg-violet-500"}`}
                style={{ width: `${Math.min(100, Math.max(0, allocPct))}%` }}
              />
            </div>
            <div className="mt-1.5 text-[10px] text-slate-500">자동 주문은 없고, 모의 수량 산출만 제공합니다.</div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500">
                  <th className="pb-2 text-left font-medium">종목</th>
                  <th className="pb-2 text-left font-medium">전략</th>
                  <th className="pb-2 text-right font-medium">기준가</th>
                  <th className="pb-2 text-right font-medium">확률</th>
                  <th className="pb-2 text-right font-medium">Half-Kelly</th>
                  <th className="pb-2 text-right font-medium">금액</th>
                  <th className="pb-2 text-right font-medium">모의 수량</th>
                  <th className="pb-2 text-right font-medium">EV</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.symbol}-${row.mode}-${row.horizon}`} className="border-b border-slate-900">
                    <td className="py-2 pr-3">
                      <div className="font-medium text-slate-200">{row.name}</div>
                      <div className="font-mono text-slate-500">{row.symbol}</div>
                    </td>
                    <td className="py-2 pr-3 text-slate-400">
                      {modeLabel(row.mode as Mode)} <span className="text-slate-600">/</span> {horizonLabel(row.horizon as Horizon)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-300">{row.entry.toLocaleString("ko-KR")}</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-300">{(row.probability * 100).toFixed(0)}%</td>
                    <td className="py-2 pr-3 text-right font-mono text-violet-300">{(row.halfKelly * 100).toFixed(1)}%</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-100">{Math.round(row.amount).toLocaleString("ko-KR")}</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-100">{row.qty.toLocaleString("ko-KR")}</td>
                    <td className={`py-2 text-right font-mono ${row.ev >= 2 ? "text-emerald-300" : row.ev >= 0 ? "text-slate-400" : "text-red-400"}`}>
                      {row.ev >= 0 ? "+" : ""}{row.ev.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
