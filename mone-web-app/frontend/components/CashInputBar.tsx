"use client";

import { useEffect, useMemo, useState } from "react";
import { Calculator, WalletCards } from "lucide-react";

const CASH_KEY = "mone_cash_amount";

function fmtWon(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "-";
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

export default function CashInputBar() {
  const [cash, setCash] = useState<number>(0);
  const [raw, setRaw] = useState<string>("");

  useEffect(() => {
    const saved = Number(window.localStorage.getItem(CASH_KEY) || "0");
    if (Number.isFinite(saved) && saved > 0) {
      setCash(saved);
      setRaw(String(saved));
    }
  }, []);

  const allocation = useMemo(
    () => ({
      conservative: Math.floor(cash * 0.02),
      balanced: Math.floor(cash * 0.05),
      aggressive: Math.floor(cash * 0.12),
    }),
    [cash]
  );

  function applyCash(nextRaw: string) {
    const onlyNumber = nextRaw.replace(/[^\d]/g, "");
    setRaw(onlyNumber);
    const next = Number(onlyNumber || "0");
    setCash(next);
    window.localStorage.setItem(CASH_KEY, String(next));
    window.dispatchEvent(new CustomEvent("mone-cash-updated", { detail: { cash: next } }));
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/40 px-4 py-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-xl bg-blue-500/10 p-2 text-blue-300">
            <WalletCards size={16} />
          </div>
          <div>
            <div className="text-sm font-bold text-white">가용 예수금</div>
            <p className="mt-0.5 text-xs text-slate-400">
              입력값은 브라우저에만 저장되며, 추천 카드의 성향별 매수 수량 계산에 사용됩니다.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-2 md:flex-row md:items-center">
          <div className="relative">
            <Calculator size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={raw}
              onChange={(event) => applyCash(event.target.value)}
              placeholder="예: 10000000"
              className="h-10 w-full rounded-xl border border-slate-700 bg-slate-950/60 pl-9 pr-3 text-sm font-mono text-white outline-none focus:border-blue-500 md:w-52"
            />
          </div>
          <div className="grid grid-cols-3 gap-1 text-center text-[11px]">
            <div className="rounded-lg bg-slate-950/50 px-2 py-1.5">
              <div className="text-slate-500">보수 2%</div>
              <div className="font-mono text-sky-300">{fmtWon(allocation.conservative)}</div>
            </div>
            <div className="rounded-lg bg-slate-950/50 px-2 py-1.5">
              <div className="text-slate-500">균형 5%</div>
              <div className="font-mono text-violet-300">{fmtWon(allocation.balanced)}</div>
            </div>
            <div className="rounded-lg bg-slate-950/50 px-2 py-1.5">
              <div className="text-slate-500">공격 12%</div>
              <div className="font-mono text-orange-300">{fmtWon(allocation.aggressive)}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
