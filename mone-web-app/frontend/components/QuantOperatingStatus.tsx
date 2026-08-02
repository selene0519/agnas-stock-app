"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Eye, RefreshCw, ShieldCheck } from "lucide-react";
import { mone, type Market } from "@/lib/api";
import { statusLabel } from "@/lib/utils";

const STATE_STYLE: Record<string, { label: string; className: string; icon: typeof ShieldCheck }> = {
  RECOMMENDATION_READY: { label: "추천 검토 가능", className: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200", icon: CheckCircle2 },
  TRADEABLE: { label: "추천 검토 가능", className: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200", icon: CheckCircle2 },
  WATCH: { label: "관찰", className: "border-cyan-400/30 bg-cyan-400/10 text-cyan-200", icon: Eye },
  ABSTAIN: { label: "신규 진입 보류", className: "border-amber-400/30 bg-amber-400/10 text-amber-200", icon: ShieldCheck },
  BLOCKED: { label: "안전장치 차단", className: "border-red-400/30 bg-red-400/10 text-red-200", icon: AlertTriangle },
};

export function QuantOperatingStatus({ market }: { market: Market }) {
  const [row, setRow] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const payload = await mone.quantOperatingStatus({ market });
      setRow(payload?.markets?.[market] ?? null);
    } catch {
      setRow(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [market]);

  if (!row && !loading) return null;
  const state = STATE_STYLE[row?.operatingState] ?? STATE_STYLE.BLOCKED;
  const StateIcon = state.icon;
  const risk = row?.riskBudget ?? {};
  const journal = row?.journal ?? {};

  return (
    <section className="border-y border-slate-800/80 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} className="text-teal-300" />
            <h2 className="text-sm font-semibold text-slate-100">AI 퀀트 추천 판정</h2>
            {row && (
              <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold ${state.className}`}>
                <StateIcon size={12} /> {state.label}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-400">실현 성과, 독립 검증, 추천 일지, 보유 위험예산을 통과한 신호만 사용자 검토 대상으로 표시합니다.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} aria-label="운용 판정 새로고침" className="shrink-0 min-h-11 min-w-11 inline-flex items-center justify-center rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100 disabled:opacity-50">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-teal-400/20 bg-teal-400/[0.06] px-3 py-2 text-[11px]">
        <span className="font-semibold text-teal-200">AI는 분석하고 추천합니다</span>
        <span className="text-slate-400">사용자가 결정하고 증권사에서 직접 실행 · 실계좌 주문 연결 없음</span>
      </div>

      {loading && !row ? <div className="mt-3 h-16 animate-pulse rounded-lg bg-slate-800/50" /> : row && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { label: "검증 후보", value: `${row.candidateCount ?? 0}개` },
              // 원시 코드(DEFERRED/CHECK/OK)를 그대로 찍지 않는다.
              { label: "일지 기록", value: journal.recordingStatus ? statusLabel(journal.recordingStatus) : "-" },
              { label: "평가 상태", value: journal.evaluationStatus ? statusLabel(journal.evaluationStatus) : "-" },
              { label: "손실 예산", value: `${Number(risk.totalLossBudgetPct ?? 0).toFixed(1)}% / ${risk.maxPortfolioLossPct ?? "-"}%` },
            ].map((item) => (
              <div key={item.label} className="rounded-md bg-slate-900/70 px-3 py-2">
                <div className="text-[10px] text-slate-500">{item.label}</div>
                <div className="mt-1 truncate font-mono text-xs font-semibold text-slate-200">{item.value}</div>
              </div>
            ))}
          </div>
          {row.reasons?.length > 0 && (
            <div className="mt-3 rounded-md border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs leading-5 text-slate-300">
              {row.reasons[0]}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-1.5">
            {(row.checks ?? []).map((check: any) => (
              <span key={check.id} className={`rounded-md px-2 py-1 text-[10px] font-medium ${check.passed === true ? "bg-emerald-400/10 text-emerald-300" : check.passed === null ? "bg-amber-400/10 text-amber-300" : "bg-slate-800 text-slate-400"}`}>
                {check.passed === true ? "통과" : check.passed === null ? "확인 대기" : "보류"} · {check.label}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
