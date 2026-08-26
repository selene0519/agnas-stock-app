"use client";

function numberOrZero(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function BiotechEvidencePanel({ item }: { item: any }) {
  const summary = item?.biotechEvidenceSummary;
  const evidence = item?.biotechEvidence;
  if (!summary || !evidence) return null;

  const validation = item?.biotechEvidenceValidation || {};
  const applied = item?.biotechEvidenceScoreApplied === true;
  const adjustment = Number(item?.biotechEvidenceScoreAdjustment || 0);
  const clinical = evidence?.clinicalTrials || {};
  const pubMed = evidence?.pubMed || {};
  const pubMedReady = pubMed?.status === "OK";
  const riskCount = numberOrZero(summary.riskClinicalStudies);
  const validationLabel = applied
    ? `홀드아웃 검증 반영 ${adjustment > 0 ? "+" : ""}${adjustment.toFixed(1)}점`
    : `점수 미반영 · ${validation.promotionStatus === "REJECTED" ? "검증 탈락" : "전방 검증 중"}`;

  return (
    <div className={`mb-3 rounded-xl border px-3 py-3 tabular-nums ${riskCount > 0 ? "border-amber-500/35 bg-amber-500/5" : "border-cyan-500/25 bg-cyan-500/5"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-cyan-300">공식 바이오 근거</div>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold tabular-nums ${applied ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-slate-600 bg-slate-900 text-slate-400"}`}>
          {validationLabel}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div><div className="text-slate-400">검증 임상</div><div className="mt-0.5 font-mono font-bold text-slate-100">{numberOrZero(summary.verifiedClinicalStudies)}건</div></div>
        <div><div className="text-slate-400">진행 중</div><div className="mt-0.5 font-mono font-bold text-teal-300">{numberOrZero(summary.activeClinicalStudies)}건</div></div>
        <div><div className="text-slate-400">3상</div><div className="mt-0.5 font-mono font-bold text-violet-300">{numberOrZero(summary.phase3ClinicalStudies)}건</div></div>
        <div><div className="text-slate-400">중단·위험</div><div className={`mt-0.5 font-mono font-bold ${riskCount > 0 ? "text-amber-300" : "text-slate-300"}`}>{riskCount}건</div></div>
      </div>
      <div className="mt-2 border-t border-slate-800/80 pt-2 text-[11px] leading-5 text-slate-400">
        PubMed {pubMedReady ? `최근 5년 검색 ${numberOrZero(summary.recentPublicationCount).toLocaleString("ko-KR")}건` : "수집 대기"}
        {summary.asOfDate ? ` · 기준 ${String(summary.asOfDate).slice(0, 10)}` : ""}
      </div>
      <div className="mt-1 text-pretty text-[10px] leading-4 text-slate-400">
        임상·논문 수는 방향성 신호가 아닙니다. 다음 거래일부터 시장조정 수익을 검증한 이벤트만 제한적으로 점수에 반영합니다.
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
        {clinical?.sourceUrl && <a href={clinical.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center rounded-lg px-2 text-cyan-300 underline decoration-cyan-500/40 underline-offset-2 transition-transform duration-150 ease-out active:scale-[0.96]">ClinicalTrials.gov</a>}
        {pubMed?.sourceUrl && <a href={pubMed.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center rounded-lg px-2 text-cyan-300 underline decoration-cyan-500/40 underline-offset-2 transition-transform duration-150 ease-out active:scale-[0.96]">PubMed</a>}
      </div>
    </div>
  );
}

export default BiotechEvidencePanel;
