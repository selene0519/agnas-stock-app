export type Tone = "safe" | "warning" | "danger" | "info" | "neutral";

/** mone-tone-* CSS 변수를 소비하는 Tailwind 클래스 문자열. 기존 인라인
 * 하드코딩 컬러(`border-emerald-500/30 bg-emerald-500/10 text-emerald-300` 등)를
 * 대체할 때 그대로 className에 꽂아 쓴다. */
export function toneClassName(tone: Tone): string {
  return `mone-tone-${tone} border-[var(--tone-border)] bg-[var(--tone-bg)] text-[var(--tone-fg)]`;
}

/** 점수/비율처럼 숫자 기준으로 안전·주의·위험을 가르는 공통 로직.
 * invert: true면 낮을수록 안전(예: 리스크 점수). */
export function getTone(
  value: number,
  thresholds: { safe: number; warning: number },
  opts: { invert?: boolean } = {}
): Tone {
  const { safe, warning } = thresholds;
  if (opts.invert) {
    if (value <= safe) return "safe";
    if (value <= warning) return "warning";
    return "danger";
  }
  if (value >= safe) return "safe";
  if (value >= warning) return "warning";
  return "danger";
}

/** VTJ/알림추적 등에서 쓰는 결과 라벨(한글/영문 혼용) → 톤 매핑. */
export function outcomeTone(outcome: string): Tone {
  const key = String(outcome || "").toUpperCase();
  if (["TARGET_HIT", "목표도달", "목표달성"].includes(key)) return "safe";
  if (["STOP_HIT", "TIME_EXIT_NEAR_STOP", "손절도달", "손절"].includes(key)) return "danger";
  if (key.startsWith("TIME_EXIT") || key === "리스크확인" || key === "주의") return "warning";
  if (["PENDING", "DATA_PENDING", "추적중", "데이터부족"].includes(key)) return "info";
  return "neutral";
}
