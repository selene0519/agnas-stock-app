/**
 * statusLabels.ts — 상태·행동·신뢰도·데이터상태의 "정규 어휘" 단일 소스.
 *
 * 배경(UX 보고서 8.1/8.3, P0 "언어를 먼저 고정"): 현재 화면마다 정상/양호/보통/주의 필요/
 * 위험 보류/대기/모니터링/CAUTION 등이 혼재해 같은 개념이 다른 단어로 보인다.
 * 이 모듈은 다양한 원본 문자열을 4개 축의 정규 라벨로 수렴시킨다:
 *   - 상태(status): 정상 / 주의 / 위험 / 데이터 제한   (객관적 상태)
 *   - 행동(action): 관찰 / 대기 / 진입 검토 / 보유 / 축소 / 청산   (다음 행동)
 *   - 신뢰도(confidence): 낮음 / 보통 / 높음   (데이터 충분성·일관성)
 *   - 데이터상태(dataStatus): 최신 / 일부 제한 / 갱신 필요 / 분석 대기
 *
 * 순수 함수 — 화면에서 라벨/톤을 이 함수로 통일해 표기한다. tone은 색상 클래스 매핑용.
 */

export type Tone = "positive" | "neutral" | "caution" | "danger" | "muted";

export interface Labeled {
  label: string;
  tone: Tone;
}

const up = (raw: unknown) => String(raw ?? "").trim().toUpperCase();

/** 상태: 시장·종목·데이터의 객관적 상태 → 정상 / 주의 / 위험 / 데이터 제한 */
export function normalizeStatus(raw: unknown): Labeled {
  const s = up(raw);
  if (!s) return { label: "확인 중", tone: "muted" };
  if (/(DATA_PENDING|PRICE_PENDING|PARTIAL|STALE|FALLBACK|데이터\s*제한|부분\s*데이터|미반영|수집\s*대기)/.test(s))
    return { label: "데이터 제한", tone: "muted" };
  if (/(위험|RISK|DANGER|보류|BLOCK|NO_TRADE)/.test(s)) return { label: "위험", tone: "danger" };
  if (/(주의|CAUTION|WATCH|WARN|과열|OVERHEAT)/.test(s)) return { label: "주의", tone: "caution" };
  if (/(정상|양호|보통|NORMAL|^OK$|LOW|안정|STABLE|SAFE)/.test(s)) return { label: "정상", tone: "positive" };
  return { label: "확인", tone: "neutral" };
}

/** 행동: 사용자의 다음 행동 → 관찰 / 대기 / 진입 검토 / 보유 / 축소 / 청산 */
export function normalizeAction(raw: unknown): Labeled {
  const s = up(raw);
  if (!s) return { label: "관찰", tone: "neutral" };
  if (/(청산|매도|SELL|EXIT|LIQUIDATE)/.test(s)) return { label: "청산", tone: "danger" };
  if (/(축소|REDUCE|TRIM|비중\s*축소)/.test(s)) return { label: "축소", tone: "caution" };
  // "진입 자제"는 진입이 아니라 대기 축
  if (/(HOLD_CASH|진입\s*자제|현금\s*대기|관망|NO_TRADE|거래\s*금지)/.test(s)) return { label: "대기", tone: "caution" };
  if (/(보유|유지|HOLD|보유자)/.test(s)) return { label: "보유", tone: "positive" };
  if (/(진입|매수|BUY|TRADE_CANDIDATE|오늘\s*진입|조건부)/.test(s)) return { label: "진입 검토", tone: "positive" };
  if (/(대기|WAIT|PENDING)/.test(s)) return { label: "대기", tone: "neutral" };
  if (/(관찰|모니터링|MONITOR|중립|WATCH|관심)/.test(s)) return { label: "관찰", tone: "neutral" };
  return { label: "관찰", tone: "neutral" };
}

/** 신뢰도: 데이터 충분성·일관성 → 낮음 / 보통 / 높음 (+ 원래 수치는 호출부에서 병기) */
export function confidenceLabel(pct: number | null | undefined): Labeled {
  if (pct == null || Number.isNaN(pct)) return { label: "확인 중", tone: "muted" };
  if (pct >= 60) return { label: "높음", tone: "positive" };
  if (pct >= 45) return { label: "보통", tone: "caution" };
  return { label: "낮음", tone: "danger" };
}

/** 데이터 상태: 최신 / 일부 제한 / 갱신 필요 / 분석 대기 */
export function dataStatusLabel(raw: unknown): Labeled {
  const s = up(raw);
  if (!s) return { label: "확인 중", tone: "muted" };
  if (/(DATA_PENDING|분석\s*대기|OHLCV.*부족|표본\s*부족)/.test(s)) return { label: "분석 대기", tone: "muted" };
  if (/(STALE|PRICE_PENDING|갱신\s*필요|오래|FALLBACK)/.test(s)) return { label: "갱신 필요", tone: "caution" };
  if (/(PARTIAL|일부\s*제한|부분|미반영)/.test(s)) return { label: "일부 제한", tone: "caution" };
  if (/(NORMAL|최신|정상|LIVE|^OK$)/.test(s)) return { label: "최신", tone: "positive" };
  return { label: "확인", tone: "neutral" };
}

/** tone → Tailwind 텍스트 색상 클래스 (화면 공통) */
export function toneTextClass(tone: Tone): string {
  switch (tone) {
    case "positive": return "text-emerald-300";
    case "caution": return "text-amber-300";
    case "danger": return "text-red-300";
    case "muted": return "text-slate-400";
    default: return "text-slate-200";
  }
}

/** tone → Tailwind badge class (화면 공통) */
export function toneBadgeClass(tone: Tone): string {
  switch (tone) {
    case "positive": return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
    case "caution": return "border-amber-500/30 bg-amber-500/10 text-amber-300";
    case "danger": return "border-red-500/40 bg-red-500/10 text-red-300";
    case "muted": return "border-slate-700 bg-slate-950 text-slate-400";
    default: return "border-slate-700 bg-slate-950 text-slate-300";
  }
}
