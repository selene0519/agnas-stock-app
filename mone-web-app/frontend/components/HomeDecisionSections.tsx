"use client";

import { ArrowRight, ChevronRight } from "lucide-react";
import {
  dataFreshnessBadgeClass, dataFreshnessInfo, displayName, entryPlanStale,
  firstText, horizonLabel, modeLabel, moneReasonLines, priceText, toNumber,
} from "@/lib/moneDisplay";

type Candidate = Record<string, any>;

function text(...values: any[]) {
  const value = firstText(...values);
  return value === "-" ? "" : value;
}

function PlanCard({ item, observation, marketReady, onSelect, onAnalyze }: {
  item: Candidate;
  observation: boolean;
  marketReady: boolean;
  onSelect: (item: Candidate) => void;
  onAnalyze: (item: Candidate) => void;
}) {
  const freshness = dataFreshnessInfo(item);
  const stalePlan = entryPlanStale(priceText(item, "current"), priceText(item, "entry")).stale;
  const blocked = item.isTradeBlocked || item.isBlocked || item.reviewOnly
    || String(item.publicTradeStatus || "").toUpperCase() === "NO_TRADE";
  const suppressed = stalePlan || freshness.state === "old";
  const available = marketReady && !blocked && !suppressed;
  const label = observation ? "관찰 · 진입 대기" : available ? "진입 계획" : "진입 보류";
  const reasons = moneReasonLines(item).slice(0, 2);
  const plan = item.positionPlan || item.quantTraderVerdict?.positionPlan || {};
  const weight = toNumber(plan.suggestedWeightPct);
  const timing = text(item.timingLabel);
  const cancel = text(item.invalidationReason, item.invalidation, item.cancelCondition);
  const validity = text(item.validUntil, item.expiresAt);
  const condition = observation
    ? text(item.entryCondition, item.timingReason, item.decisionReason)
    : "";

  return (
    <article className="mone-home-inset flex min-w-0 flex-col rounded-xl border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`text-xs font-semibold ${observation || !available ? "text-amber-300" : "text-teal-300"}`}>{label}</span>
        <span className={`rounded-md border px-2 py-1 text-[10px] ${dataFreshnessBadgeClass(freshness.state)}`}>{freshness.label}</span>
      </div>
      <div className="mt-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="break-keep text-lg font-bold text-slate-100">{displayName(item)}</h3>
          <p className="mt-1 text-xs text-slate-400">{item.symbol} · {modeLabel(item._mode || item.mode)} · {horizonLabel(item._horizon || item.horizon)}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] text-slate-400">기준 현재가</div>
          <div className="mt-1 font-mono text-xs font-semibold tabular-nums text-slate-200">{priceText(item, "current", "—")}</div>
        </div>
      </div>
      <dl className="my-4 grid grid-cols-3 gap-2 border-y border-slate-800/70 py-3">
        {(["entry", "stop", "target"] as const).map((key) => (
          <div key={key} className="min-w-0">
            <dt className="text-[10px] text-slate-400">{key === "entry" ? observation ? "관찰 기준가" : "진입 기준가" : key === "stop" ? "손절가" : "목표가"}</dt>
            <dd className={`mt-1 break-words font-mono text-xs font-semibold tabular-nums ${suppressed ? "text-slate-400" : key === "stop" ? "text-red-300" : key === "target" ? "text-emerald-300" : "text-teal-300"}`}>
              {suppressed ? "재산출 대기" : priceText(item, key, "미제공")}
            </dd>
          </div>
        ))}
      </dl>
      <div className="flex-1 space-y-2 text-xs leading-5 text-slate-300">
        {reasons.length ? reasons.map((reason, index) => <p key={`${index}-${reason}`}>{reason}</p>) : <p className="text-slate-400">추천 근거 수집 대기</p>}
        {condition && <p><span className="text-slate-400">대기 이유 · </span>{condition}</p>}
        {timing && observation && <p className="text-amber-300">{timing}</p>}
        {!observation && !available && <p className="text-amber-300">{suppressed ? "가격 또는 데이터 기준 갱신 후 진입 계획을 다시 확인합니다." : blocked ? "진입 차단 사유가 해소되기 전까지 관찰합니다." : "시장 판단이 확인되거나 개선되기 전까지 진입을 보류합니다."}</p>}
        {observation && <p className="text-slate-400">관찰 기준가 도달만으로 매수 신호가 확정되지 않습니다.</p>}
      </div>
      <div className="mt-4 space-y-1 border-t border-slate-800/70 pt-3 text-[11px] leading-5 text-slate-400">
        {!observation && <p>권장 비중 {weight != null ? `${weight.toFixed(1)}%` : "미제공"} · 유효기한 {validity || "미제공"}</p>}
        {cancel && <p>취소 조건 · {cancel}</p>}
        <p>{freshness.basisText}</p>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button type="button" onClick={() => onSelect(item)} className="min-h-11 rounded-lg border border-slate-700 px-2 text-xs font-semibold text-slate-300 hover:bg-slate-800/40">선정 근거</button>
        <button type="button" onClick={() => onAnalyze(item)} className="flex min-h-11 items-center justify-center gap-1 rounded-lg border border-teal-400/25 px-2 text-xs font-semibold text-teal-300 hover:bg-teal-400/10">상세 분석 <ArrowRight size={13} aria-hidden="true" /></button>
      </div>
    </article>
  );
}

export default function HomeDecisionSections({ entries, watchItems, riskItems, marketReady, dataAvailable, nextSession, onSelect, onAnalyze, onExplore }: {
  entries: Candidate[];
  watchItems: Candidate[];
  riskItems: Candidate[];
  marketReady: boolean;
  dataAvailable: boolean;
  nextSession: boolean;
  onSelect: (item: Candidate) => void;
  onAnalyze: (item: Candidate) => void;
  onExplore: () => void;
}) {
  return (
    <>
      <section className="mone-home-card p-4 sm:p-5" aria-labelledby="home-entry-title">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id="home-entry-title" className="mone-home-section-title">{nextSession ? "다음 거래일 진입 계획" : "오늘의 진입 계획"}</h2>
            <p className="mt-1 text-xs leading-5 text-slate-400">선정 이유와 가격 계획을 함께 확인합니다.</p>
          </div>
          <span className="shrink-0 font-mono text-xs text-slate-400">{dataAvailable ? `${entries.length}종목` : "확인 중"}</span>
        </div>
        {entries.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {entries.map((item) => <PlanCard key={`${item.market}-${item.symbol}`} item={item} observation={false} marketReady={marketReady} onSelect={onSelect} onAnalyze={onAnalyze} />)}
          </div>
        ) : (
          <div className="mone-home-inset rounded-xl border px-4 py-6">
            <p className="text-base font-semibold text-slate-100">{dataAvailable ? "신규 진입 보류" : "추천 데이터 확인 필요"}</p>
            <p className="mt-2 text-xs leading-6 text-slate-400">{dataAvailable ? "현재 제공된 추천 중 진입 조건을 통과한 종목이 없습니다. 아래 관찰 후보와 보유종목 대응을 확인합니다." : "추천 데이터를 확인하지 못했습니다. 상단 새로고침으로 다시 불러올 수 있습니다."}</p>
          </div>
        )}
      </section>
      <section className="mone-home-card p-4 sm:p-5" aria-labelledby="home-watch-title">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id="home-watch-title" className="mone-home-section-title">관찰 후보</h2>
            <p className="mt-1 text-xs leading-5 text-slate-400">아직 진입 신호가 확정되지 않은 후보입니다.</p>
          </div>
          <span className="shrink-0 font-mono text-xs text-slate-400">{dataAvailable ? `${watchItems.length}종목` : "확인 중"}</span>
        </div>
        {watchItems.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {watchItems.map((item) => <PlanCard key={`${item.market}-${item.symbol}`} item={item} observation marketReady={marketReady} onSelect={onSelect} onAnalyze={onAnalyze} />)}
          </div>
        ) : <p className="py-4 text-xs leading-6 text-slate-400">{dataAvailable ? "관찰 조건을 통과한 후보가 없습니다. 종목 분석에서 추천되지 않은 종목도 검색할 수 있습니다." : "관찰 후보를 불러오지 못했습니다. 추천 데이터 갱신 후 다시 표시합니다."}</p>}
        <button type="button" onClick={onExplore} className="mt-3 flex min-h-11 w-full items-center justify-between border-t border-slate-800/70 pt-2 text-xs font-semibold text-teal-300">종목 검색·분석으로 이동 <ChevronRight size={15} aria-hidden="true" /></button>
        {riskItems.length > 0 && (
          <details className="mt-2 border-t border-slate-800/70 text-xs">
            <summary className="min-h-11 cursor-pointer py-3 text-slate-400">진입 제외·주의 종목 {riskItems.length}개</summary>
            {riskItems.map((item) => <button type="button" key={`${item.market}-${item.symbol}`} onClick={() => onSelect(item)} className="flex min-h-11 w-full items-center justify-between gap-3 border-t border-slate-800/50 py-3 text-left text-slate-300"><span>{displayName(item)}</span><span className="text-amber-300">제외 근거 <ChevronRight className="inline" size={12} aria-hidden="true" /></span></button>)}
          </details>
        )}
      </section>
    </>
  );
}
