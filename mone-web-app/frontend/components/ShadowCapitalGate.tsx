"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, BarChart3, BrainCircuit, Check, CircleDollarSign, RefreshCw, ShieldAlert } from "lucide-react";
import { mone, type Market, type QuantShadowStatus } from "@/lib/api";

const REASON_LABELS: Record<string, string> = {
  MISSING_REPORTS: "검증 보고서가 일부 누락됨",
  ALPHA_NOT_PROVEN: "시장 대비 잔차 알파가 아직 입증되지 않음",
  RESIDUAL_ALPHA_MODEL_NOT_PROVEN: "개별 후보의 잔차 알파 예측력이 아직 OOS에서 입증되지 않음",
  NO_POSITIVE_SLEEVE: "양의 자본곡선을 만든 전략 셀이 없음",
  NO_APPROVED_RISK_EXPOSURE: "위험 한도를 통과한 포지션이 없음",
  CHALLENGER_NOT_PROMOTABLE: "새 전략이 기존 전략 대비 우월성을 아직 입증하지 못함",
  WALKFORWARD_NOT_PROMOTION_GRADE: "walk-forward가 생존편향 없는 승격 기준을 아직 충족하지 못함",
};

function number(value: number | null | undefined, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function percent(value: number | null | undefined, digits = 1) {
  return typeof value === "number" && Number.isFinite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(digits)}%` : "—";
}

function GateStep({ icon: Icon, label, value, detail, passed }: {
  icon: typeof Activity;
  label: string;
  value: string;
  detail: string;
  passed: boolean;
}) {
  return (
    <div className="relative min-w-0 px-3 py-3 sm:px-4">
      <div className="flex items-center gap-2 text-[11px] font-semibold tracking-wide text-slate-400">
        <span className={`inline-flex size-6 items-center justify-center rounded-full border ${passed ? "border-emerald-400/35 bg-emerald-400/10 text-emerald-300" : "border-amber-400/35 bg-amber-400/10 text-amber-300"}`}>
          {passed ? <Check size={13} aria-hidden="true" /> : <Icon size={13} aria-hidden="true" />}
        </span>
        {label}
      </div>
      <div className="mt-2 font-mono text-sm font-semibold tabular-nums text-slate-100">{value}</div>
      <p className="mt-1 text-[10px] leading-4 text-slate-400">{detail}</p>
    </div>
  );
}

export function ShadowCapitalGate({ market }: { market: Market }) {
  const [row, setRow] = useState<QuantShadowStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await mone.quantShadowStatus();
      if (!payload || payload.status === "ERROR") throw new Error(payload?.error || "Shadow 검증 상태를 불러오지 못했습니다.");
      setRow(payload);
    } catch (caught) {
      setRow(null);
      setError(caught instanceof Error ? caught.message : "Shadow 검증 상태를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const summary = row?.summary;
  const ci = summary?.d20AlphaCi95;
  const alphaPassed = row?.decisionReasons?.includes("ALPHA_NOT_PROVEN") === false;
  const residualModelPassed = row?.decisionReasons?.includes("RESIDUAL_ALPHA_MODEL_NOT_PROVEN") === false;
  const sleevePassed = row?.decisionReasons?.includes("NO_POSITIVE_SLEEVE") === false;
  const riskPassed = row?.decisionReasons?.includes("NO_APPROVED_RISK_EXPOSURE") === false;
  const evidencePassed = !row?.missingReports?.length && (summary?.independentDecisions ?? 0) >= 200;
  const marketLabel = market === "kr" ? "국장" : market === "us" ? "미장" : "전체 시장";

  return (
    <section className="overflow-hidden rounded-xl border border-slate-700/80 bg-slate-950/55" aria-labelledby="quant-capital-gate-title">
      <div className="flex flex-col gap-4 border-b border-slate-800 px-4 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-1 text-[10px] font-bold tracking-[0.12em] text-amber-300">
              <ShieldAlert size={12} aria-hidden="true" /> SHADOW ONLY
            </span>
            <span className="text-[10px] font-medium text-slate-400">{marketLabel} · 실주문 미허용</span>
          </div>
          <h2 id="quant-capital-gate-title" className="mt-3 text-base font-bold text-slate-100">{row?.decision === "SHADOW_TAKE" ? "검증용 진입 후보 있음" : "자본 투입 보류"}</h2>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-slate-400">추천 수가 아니라 독립 표본, 후보별 잔차 알파 예측, 실제 초과성과, 자본곡선과 위험예산을 모두 통과해야 진입합니다.</p>
        </div>
        <button type="button" onClick={load} disabled={loading} aria-label="퀀트 자본 게이트 새로고침" className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center self-end rounded-lg border border-slate-700 text-slate-400 transition-colors hover:border-slate-600 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-400 disabled:opacity-50 sm:self-auto">
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} aria-hidden="true" />
        </button>
      </div>

      {loading && !row ? (
        <div className="grid grid-cols-2 divide-x divide-y divide-slate-800 md:grid-cols-5 md:divide-y-0" aria-label="검증 상태 불러오는 중" role="status" aria-live="polite">
          {[0, 1, 2, 3, 4].map((item) => <div key={item} className="h-24 animate-pulse bg-slate-900/50" />)}
        </div>
      ) : error ? (
        <div className="flex items-start gap-3 bg-red-400/5 px-4 py-4 text-sm text-red-200" role="alert">
          <AlertTriangle size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
          <div><div className="font-semibold">검증 상태 확인 실패 — 자본 투입 차단</div><p className="mt-1 text-xs leading-5 text-red-200/70">{error}</p></div>
        </div>
      ) : row && summary ? (
        <>
          <div className="grid grid-cols-2 divide-x divide-y divide-slate-800 md:grid-cols-5 md:divide-y-0">
            <GateStep icon={Activity} label="01 독립 증거" value={`${summary.independentDecisions ?? 0}건`} detail="승격 최소 200건 · 날짜 기준은 별도 검증" passed={evidencePassed} />
            <GateStep icon={BrainCircuit} label="02 알파 예측" value={`${summary.residualAlphaForwardSettledPredictions ?? 0}건`} detail={`Forward OOS ${summary.residualAlphaForwardSettledSignalDates ?? 0}일 · ${summary.residualAlphaModelEvidence || "미검증"}`} passed={residualModelPassed} />
            <GateStep icon={BarChart3} label="03 실현 알파" value={percent(summary.d20BlockMeanCarPct, 2)} detail={`D+20 블록 CI ${ci ? `${number(ci[0], 2)} ~ ${number(ci[1], 2)}%` : "—"}`} passed={alphaPassed} />
            <GateStep icon={CircleDollarSign} label="04 자본곡선" value={percent(summary.topSleeveReturnPct, 2)} detail={`${summary.topSleeve || "최상위 sleeve 없음"} · PF ${number(summary.topSleeveProfitFactor, 2)}`} passed={sleevePassed} />
            <GateStep icon={ShieldAlert} label="05 위험예산" value={`현금 ${number(summary.cashWeightPct, 0)}%`} detail={`총 노출 ${number(summary.grossExposurePct, 1)}% · β ${number(summary.portfolioBeta, 2)}`} passed={riskPassed} />
          </div>

          <div className="border-t border-slate-800 px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px]">
              <span className="font-semibold text-slate-300">오늘의 결정</span>
              <span className="font-mono font-bold text-amber-300">TAKE {summary.take} · WAIT {summary.wait} · REJECT {summary.reject}</span>
              <span className="text-slate-400">후보 {summary.candidates}개</span>
            </div>
            {row.decisionReasons?.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="자본 투입 차단 근거">
                {row.decisionReasons.map((reason) => <li key={reason} className="rounded-md border border-slate-700/80 bg-slate-900/70 px-2 py-1 text-[10px] text-slate-300">{REASON_LABELS[reason] || reason}</li>)}
              </ul>
            )}
            <details className="mt-3 text-[10px] text-slate-400">
              <summary className="w-fit cursor-pointer rounded-sm py-1 hover:text-slate-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-400">검증 원장 보기</summary>
              <div className="mt-2 grid gap-1 font-mono sm:grid-cols-2">
                {Object.entries(row.sources || {}).map(([name, source]) => <div key={name}>{name}: {source}</div>)}
              </div>
            </details>
          </div>
        </>
      ) : null}
    </section>
  );
}
