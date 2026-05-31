"use client";

import { Clock } from "lucide-react";
import { priceSessionLabel } from "@/lib/utils";
import type { PriceSession } from "@/lib/types";

export default function PriceSessionBadge({ session }: { session: PriceSession }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded border border-slate-700 bg-slate-800/60 px-2 py-1 text-xs text-slate-400">
      <Clock size={11} />
      <span>가격 기준: {priceSessionLabel(session)}</span>
    </span>
  );
}
