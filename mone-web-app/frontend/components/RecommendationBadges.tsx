"use client";

/**
 * 6차: 추천 카드 배지 컴포넌트
 * - dataSourceType, chartSignalUsed, trendlineUsed, supportUsed, resistanceUsed,
 *   fakeBreakoutRiskUsed, eventRiskScore, adaptiveScoreUsed, adaptiveLearningStatus
 * - 최대 5개 표시, 나머지 +N 접기
 * - 필드 없거나 null이면 배지 생략 (오류 없이 처리)
 */

import { dataSourceLabel } from "@/lib/dataSourceLabel";

interface BadgeItem {
  key: string;
  label: string;
  cls: string; // tailwind chip class (border + bg + text)
}

function buildBadges(item: any): BadgeItem[] {
  const badges: BadgeItem[] = [];

  // ── 1. 데이터 신뢰도
  if (item?.dataSourceType != null) {
    const { label, badgeClass } = dataSourceLabel(item.dataSourceType);
    if (label) {
      badges.push({ key: "dataSource", label, cls: badgeClass });
    }
  }

  // ── 2. 차트 신호 반영 여부
  if (item?.chartSignalUsed === true) {
    badges.push({ key: "chart", label: "차트반영", cls: "border-sky-500/30 bg-sky-500/10 text-sky-300" });
  } else if (item?.chartSignalUsed === false) {
    badges.push({ key: "chart", label: "차트표시만", cls: "border-slate-600 bg-slate-800/70 text-slate-400" });
  }

  // ── 3. 빗각 (trendline)
  if (item?.trendlineUsed === true) {
    if (item?.trendlineLearningStatus === "VERIFIED") {
      badges.push({ key: "trendline", label: "빗각반영", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" });
    } else {
      badges.push({ key: "trendline", label: "빗각참고", cls: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300" });
    }
  }

  // ── 4. 지지선
  if (item?.supportUsed === true) {
    badges.push({ key: "support", label: "지지근접", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" });
  }

  // ── 5. 저항선
  if (item?.resistanceUsed === true) {
    badges.push({ key: "resistance", label: "저항돌파", cls: "border-violet-500/30 bg-violet-500/10 text-violet-300" });
  }

  // ── 6. 가짜돌파 위험 (적색 — 위험 신호 먼저)
  if (item?.fakeBreakoutRiskUsed === true) {
    badges.push({ key: "fakeBreakout", label: "가짜돌파주의", cls: "border-red-500/40 bg-red-500/10 text-red-300" });
  }

  // ── 7. 이벤트 위험도
  const eventRisk = typeof item?.eventRiskScore === "number" ? item.eventRiskScore : null;
  if (eventRisk !== null) {
    if (eventRisk > 6) {
      badges.push({ key: "eventRisk", label: "이벤트위험", cls: "border-red-500/40 bg-red-500/10 text-red-300" });
    } else if (eventRisk >= 3) {
      badges.push({ key: "eventRisk", label: "이벤트주의", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" });
    }
  }

  // ── 8. Adaptive 보정 적용
  if (item?.adaptiveScoreUsed === true && item?.adaptiveLearningStatus === "ACTIVE") {
    badges.push({ key: "adaptive", label: "AI보정", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" });
  }

  // ── 9. 검증 부족 (LOW_SAMPLE)
  if (item?.adaptiveLearningStatus === "LOW_SAMPLE") {
    badges.push({ key: "lowSample", label: "검증부족", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" });
  }

  return badges;
}

interface RecommendationBadgesProps {
  item: any;
  maxVisible?: number;
  className?: string;
}

export function RecommendationBadges({ item, maxVisible = 5, className = "" }: RecommendationBadgesProps) {
  if (!item) return null;

  const badges = buildBadges(item);
  if (badges.length === 0) return null;

  const visible = badges.slice(0, maxVisible);
  const overflow = badges.length - maxVisible;

  return (
    <div className={`flex flex-wrap items-center gap-1 ${className}`}>
      {visible.map((b) => (
        <span
          key={b.key}
          className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[10px] font-medium leading-none ${b.cls}`}
        >
          {b.label}
        </span>
      ))}
      {overflow > 0 && (
        <span className="inline-flex items-center rounded-full border border-slate-700 bg-slate-800/60 px-1.5 py-0.5 text-[10px] font-medium leading-none text-slate-500">
          +{overflow}
        </span>
      )}
    </div>
  );
}

export default RecommendationBadges;
