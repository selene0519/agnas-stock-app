/**
 * 6차: 데이터 신뢰도 / 이벤트 데이터 소스 / adaptive 학습 상태 레이블 유틸
 * 모든 함수는 undefined/null 안전하게 처리
 */

export interface LabelResult {
  label: string;
  color: string; // tailwind text color class
  badgeClass: string; // tailwind border+bg+text chip class
}

const NEUTRAL = "border-slate-600 bg-slate-800/70 text-slate-400";
const POSITIVE = "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
const INFO = "border-sky-500/30 bg-sky-500/10 text-sky-300";
const WARN = "border-amber-500/30 bg-amber-500/10 text-amber-300";
const DANGER = "border-red-500/40 bg-red-500/10 text-red-300";

/**
 * dataSourceType 필드 → 한국어 레이블 + 배지 스타일
 * actual_ohlcv | csv | fallback | close_history_fallback | mock | placeholder | unavailable
 */
export function dataSourceLabel(type: string | undefined): LabelResult {
  const t = String(type ?? "").toLowerCase().trim();
  if (t === "actual_ohlcv" || t === "actual") {
    return { label: "실측", color: "text-emerald-300", badgeClass: POSITIVE };
  }
  if (t === "csv") {
    return { label: "CSV", color: "text-sky-300", badgeClass: INFO };
  }
  if (t === "fallback" || t === "close_history_fallback") {
    return { label: "Fallback", color: "text-amber-300", badgeClass: WARN };
  }
  if (t === "mock" || t === "placeholder") {
    return { label: "Mock", color: "text-red-300", badgeClass: DANGER };
  }
  if (t === "unavailable" || t === "none") {
    return { label: "데이터없음", color: "text-red-300", badgeClass: DANGER };
  }
  if (!t) {
    return { label: "", color: "text-slate-400", badgeClass: NEUTRAL };
  }
  return { label: t, color: "text-slate-400", badgeClass: NEUTRAL };
}

/**
 * eventDataSourceType 필드 → 한국어 레이블 + 배지 스타일
 */
export function eventDataSourceLabel(type: string | undefined): LabelResult {
  const t = String(type ?? "").toLowerCase().trim();
  if (t === "live" || t === "api") {
    return { label: "실시간 이벤트", color: "text-emerald-300", badgeClass: POSITIVE };
  }
  if (t === "cached" || t === "cache") {
    return { label: "캐시 이벤트", color: "text-sky-300", badgeClass: INFO };
  }
  if (t === "fallback") {
    return { label: "이벤트 Fallback", color: "text-amber-300", badgeClass: WARN };
  }
  if (t === "none" || t === "unavailable") {
    return { label: "이벤트없음", color: "text-slate-400", badgeClass: NEUTRAL };
  }
  if (!t) {
    return { label: "", color: "text-slate-400", badgeClass: NEUTRAL };
  }
  return { label: t, color: "text-slate-400", badgeClass: NEUTRAL };
}

/**
 * adaptiveLearningStatus 필드 → 한국어 레이블 + 배지 스타일
 * ACTIVE | LOW_SAMPLE | DISABLED | DATA_INSUFFICIENT
 */
export function adaptiveLearningLabel(status: string | undefined): LabelResult {
  const t = String(status ?? "").toUpperCase().trim();
  if (t === "ACTIVE") {
    return { label: "AI학습 활성", color: "text-emerald-300", badgeClass: POSITIVE };
  }
  if (t === "LOW_SAMPLE") {
    return { label: "검증부족", color: "text-amber-300", badgeClass: WARN };
  }
  if (t === "DISABLED") {
    return { label: "AI학습 비활성", color: "text-slate-400", badgeClass: NEUTRAL };
  }
  if (t === "DATA_INSUFFICIENT") {
    return { label: "데이터부족", color: "text-amber-300", badgeClass: WARN };
  }
  if (!t) {
    return { label: "", color: "text-slate-400", badgeClass: NEUTRAL };
  }
  return { label: t, color: "text-slate-400", badgeClass: NEUTRAL };
}
