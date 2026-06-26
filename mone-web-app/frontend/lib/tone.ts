export type Tone = "safe" | "warning" | "danger" | "info" | "neutral";

/** mone-tone-* CSS 변수를 소비하는 Tailwind 클래스 문자열. 기존 인라인
 * 하드코딩 컬러(`border-emerald-500/30 bg-emerald-500/10 text-emerald-300` 등)를
 * 대체할 때 그대로 className에 꽂아 쓴다. */
export function toneClassName(tone: Tone): string {
  return `mone-tone-${tone} border border-[var(--tone-border)] bg-[var(--tone-bg)] text-[var(--tone-fg)]`;
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

/** VTJ(가상매매일지) 결과 라벨 → 톤 매핑. */
export function outcomeTone(outcome: string): Tone {
  const key = String(outcome || "").toUpperCase();
  if (key === "TARGET_HIT") return "safe";
  if (key === "STOP_HIT" || key === "TIME_EXIT_NEAR_STOP") return "danger";
  if (key.startsWith("TIME_EXIT")) return "warning";
  if (key === "PENDING" || key === "DATA_PENDING") return "info";
  return "neutral";
}

/** 홈 화면 알림 추적(목표도달/손절도달 등) 상태 라벨 → 톤 매핑. */
export function alertStatusTone(status: string): Tone {
  if (status === "목표도달" || status === "목표근접") return "safe";
  if (status === "손절도달" || status === "리스크확인") return "danger";
  if (status === "데이터부족") return "neutral";
  return "info";
}
