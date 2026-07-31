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

/**
 * 검증·보정 파이프라인이 내는 실패 원인 코드의 한국어 라벨.
 *
 * 원래 VirtualJournalPage.tsx 안의 지역 상수였는데, 관리자 대시보드의
 * 자가보정 탭(`topFailureReasons`)도 같은 코드를 그리면서 **원문 그대로**
 * 노출하고 있었다(STOP_TOO_TIGHT 등). 같은 어휘를 두 화면이 서로 다르게
 * 말하지 않도록 여기로 올린다.
 */
export const FAILURE_REASON_LABELS: Record<string, string> = {

  UNKNOWN: "원인 미분류",
  DATA_MISSING: "데이터 부족",
  PRICE_INVALID: "가격 오류",
  ENTRY_NOT_TOUCHED: "진입가 미도달",
  TARGET_BEFORE_STOP: "목표가 선도달",
  STOP_BEFORE_TARGET: "손절 선도달",
  TARGET_NOT_REACHED: "목표가 미도달",
  DIRECTION_FAILED: "방향성 실패",
  STOP_TOO_TIGHT: "손절폭 과소",
  OVEREXTENDED_ENTRY: "과열 구간 진입",
  MARKET_GAP: "갭 변동 영향",
  MISSED_PROFIT_CAPTURE: "수익 구간 포착 실패",
  DATA_QUALITY_PROBLEM: "데이터 품질 문제",
  ENTRY_PRICE_TOO_DEEP: "진입가 과도 보수",
  TARGET_TOO_FAR_OR_MOMENTUM_WEAK: "목표가 과대 또는 모멘텀 약함",
  WEAK_CANDIDATE_SIGNAL: "후보 선정 신호 약함",
  HIGH_DRAWDOWN_BEFORE_SUCCESS: "진입 후 역행폭 과대",
  NO_FUTURE_BARS_YET: "평가 대기",
  INSUFFICIENT_HOLDING_PERIOD: "평가 기간 부족",
  ENTRY_TOUCHED_BUT_NO_EXIT: "진입 후 미청산",
  MISSING_ENTRY_PRICE: "진입가 누락",
  MISSING_TARGET_OR_STOP: "목표/손절가 누락",
  INVALID_PRICE_PATH: "가격 경로 오류",
  SYMBOL_OR_DATE_MISMATCH: "종목/날짜 매칭 실패",
  PENDING_EVALUATION: "평가 대기",
  UNCLASSIFIED_PRICE_PATH: "가격 경로 미분류",
};

/** 모르는 코드를 사용자에게 그대로 보이지 않게 감싼다. */
export function failureReasonLabel(raw: unknown): string {
  const code = up(raw) || "UNKNOWN";
  return FAILURE_REASON_LABELS[code] || "원인 미분류";
}
