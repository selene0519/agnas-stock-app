"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronRight, ChevronUp, WalletCards } from "lucide-react";

const CASH_KEY = "mone_cash_amount";

function fmtWon(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "-";
  return `${Math.round(value).toLocaleString("ko-KR")}원`;
}

export default function CashInputBar() {
  const [cash, setCash] = useState<number>(0);
  const [raw, setRaw] = useState<string>("");
  const [collapsed, setCollapsed] = useState(true);

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
    <div className="mone-home-card overflow-hidden">
      <button
        type="button"
        className="flex min-h-[92px] w-full items-center gap-3 px-3.5 text-left transition-colors hover:bg-slate-900/35"
        onClick={() => setCollapsed((v) => !v)}
      >
        <span className="mone-home-inset grid size-11 shrink-0 place-items-center rounded-[10px] border text-teal-300">
          <WalletCards size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[12px] text-slate-400">가용 예수금</div>
          <div className="mt-1 font-mono text-[20px] font-semibold tabular-nums text-slate-100">{cash > 0 ? fmtWon(cash) : "입력 필요"}</div>
        </div>
        <span className="shrink-0 text-slate-500">
          {collapsed ? <ChevronRight size={18} /> : <ChevronUp size={18} />}
        </span>
      </button>

      <div className={`${collapsed ? "hidden" : "block"} border-t border-slate-800/80 px-3.5 pb-3.5 pt-3`}>
        <p className="mb-2 text-[10.5px] text-slate-500">
          입력값은 브라우저에만 저장되며, 추천 카드의 성향별 매수 수량 계산에 사용됩니다.
        </p>
        <div className="flex flex-col gap-2 md:flex-row md:items-center">
          <input
            value={raw}
            onChange={(event) => applyCash(event.target.value)}
            placeholder="예: 10000000"
            className="mone-home-inset h-10 w-full rounded-[8px] border px-3 text-sm font-mono text-white outline-none focus:border-teal-400 md:w-52"
          />
          <div className="grid grid-cols-3 gap-1 text-center text-[11px]">
            <div className="mone-home-inset rounded-[8px] border px-2 py-1.5">
              <div className="text-slate-500">보수 2%</div>
              <div className="font-mono text-sky-300">{fmtWon(allocation.conservative)}</div>
            </div>
            <div className="mone-home-inset rounded-[8px] border px-2 py-1.5">
              <div className="text-slate-500">균형 5%</div>
              <div className="font-mono text-violet-300">{fmtWon(allocation.balanced)}</div>
            </div>
            <div className="mone-home-inset rounded-[8px] border px-2 py-1.5">
              <div className="text-slate-500">공격 12%</div>
              <div className="font-mono text-orange-300">{fmtWon(allocation.aggressive)}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
