// 종목 탐색 렌즈(Exploration Lens) 분류 체계
//
// 목적: 종목 탐색 화면을 단순 점수 필터가 아니라, 투자 기회 유형별로
//       고를 수 있는 "발굴형 탐색"으로 확장한다.
//
// 중요(구현 원칙):
// - 이 파일은 화면 표시/필터링 전용이다. finalScore·추천 정렬·entry/target/stop
//   계산식에는 전혀 관여하지 않는다.
// - 렌즈 분류는 두 가지 근거를 함께 본다:
//   (1) strategyTags(영문 코드) — 기술적 전략 신호
//   (2) 백엔드 표시 태그(discoveryTags/styleTags/pricePositionTags/liquidityTags,
//       한글) — 발굴형·재무·가격 위치 신호
//   둘 중 하나라도 렌즈 조건에 맞으면 후보로 본다(OR).
// - 렌즈 조건에 맞는 종목이 0개가 되지 않도록, 필터 사용처에서 fallback을 둔다.

export type ExplorationLensId =
  | "leader" // 주도주
  | "discovery" // 발굴주
  | "pullback" // 눌림주
  | "recovery" // 회복주
  | "balance"; // 밸런스

export interface ExplorationLensDef {
  id: ExplorationLensId;
  label: string; // 버튼 표시명 (주도주 등)
  short: string; // 한 줄 짧은 설명 (버튼 아래)
  description: string; // 상세 화면 문구
  /** strategyTags(영문 코드) — 하나라도 포함되면 후보 */
  strategyTagCodes: string[];
  /**
   * 백엔드 표시 태그(한글) — discoveryTags/styleTags/pricePositionTags/
   * liquidityTags 중 하나라도 포함되면 후보. quant_scanner._display_taxonomy_tags
   * 가 내려주는 라벨과 정확히 일치해야 한다.
   */
  displayTags: string[];
  /** 전체를 종합해서 보는 렌즈(밸런스)면 true */
  matchAll?: boolean;
  /** 버튼 강조 색상 계열 (tailwind class) */
  accent: string;
}

// 실제 백엔드 strategyTags 코드 (quant_scanner._strategy_tags 기준)
// GOLDEN_CROSS / MID_GOLDEN_CROSS / DEATH_CROSS / MID_DEATH_CROSS
// BREAKOUT_52W / NEAR_52W_HIGH / BB_SQUEEZE / MA_CONVERGENCE
// PULLBACK_BUY / VOLUME_BREAKOUT / MOMENTUM / STABLE_LOW_RISK
// UNDERVALUED_GROWTH / DOUBLE_BOTTOM / INV_HEAD_SHOULDERS / BULL_FLAG
// SYMM_TRIANGLE_UP / TRAILING_STOP_ALERT / CAUTION / EV_NEGATIVE

export const EXPLORATION_LENSES: ExplorationLensDef[] = [
  {
    id: "leader",
    label: "주도주",
    short: "강한 흐름이 이어지는 종목",
    description:
      "이미 강한 흐름이 확인된 종목입니다. 추세는 강하지만 과열 구간에서는 추격매수 주의가 필요합니다.",
    strategyTagCodes: [
      "MOMENTUM",
      "VOLUME_BREAKOUT",
      "BREAKOUT_52W",
      "NEAR_52W_HIGH",
      "GOLDEN_CROSS",
      "MID_GOLDEN_CROSS",
      "BULL_FLAG",
      "SYMM_TRIANGLE_UP",
    ],
    // 강한 참여(거래대금)와 고점 접근을 보조 근거로 사용
    displayTags: ["거래대금 충분", "박스권 상단 접근"],
    accent: "border-orange-500/50 bg-orange-500/10 text-orange-300",
  },
  {
    id: "discovery",
    label: "발굴주",
    short: "아직 덜 알려진 초기 변화 후보",
    description:
      "아직 시장 관심은 크지 않지만, 초기 수급 전환·거래대금 증가·섹터 후발주 등에서 변화가 감지되는 종목입니다.",
    strategyTagCodes: ["BB_SQUEEZE", "MA_CONVERGENCE"],
    // 발굴형 태그 실데이터를 1순위 근거로 사용
    displayTags: [
      "언더레이더",
      "초기 수급 전환",
      "거래대금 증가 초기",
      "박스권 돌파 직전",
      "변화 감지",
      "소외 성장",
      "섹터 후발주",
      "아직 덜 오름",
    ],
    accent: "border-sky-500/50 bg-sky-500/10 text-sky-300",
  },
  {
    id: "pullback",
    label: "눌림주",
    short: "조정 후 다시 갈 수 있는 종목",
    description:
      "상승 추세는 유지 중이나 현재는 조정 구간입니다. 지지 확인 후 진입이 유리합니다.",
    strategyTagCodes: ["PULLBACK_BUY", "MA_CONVERGENCE"],
    // 과열 해소 구간을 보조 근거로 사용
    displayTags: ["과열 전 구간"],
    accent: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
  },
  {
    id: "recovery",
    label: "회복주",
    short: "저평가에서 회복 신호가 있는 종목",
    description:
      "저평가·재무 안정 상태에서 실적·수급·거래량 회복 신호가 보이는 종목입니다.",
    strategyTagCodes: ["UNDERVALUED_GROWTH", "DOUBLE_BOTTOM", "INV_HEAD_SHOULDERS"],
    // 저평가·재무 스타일 태그를 회복 후보 근거로 사용
    displayTags: ["저평가 가치", "저PER", "저PBR", "재무 안정", "현금흐름 우수", "소외 성장"],
    accent: "border-violet-500/50 bg-violet-500/10 text-violet-300",
  },
  {
    id: "balance",
    label: "밸런스",
    short: "점수와 리스크를 종합한 후보",
    description:
      "점수·리스크·진입 적시성을 종합해 균형 있게 선별한 후보입니다.",
    strategyTagCodes: [],
    displayTags: [],
    matchAll: true,
    accent: "border-slate-500/50 bg-slate-500/10 text-slate-200",
  },
];

const LENS_BY_ID: Record<ExplorationLensId, ExplorationLensDef> = EXPLORATION_LENSES.reduce(
  (acc, lens) => {
    acc[lens.id] = lens;
    return acc;
  },
  {} as Record<ExplorationLensId, ExplorationLensDef>,
);

export function getLensDef(id: ExplorationLensId): ExplorationLensDef {
  return LENS_BY_ID[id];
}

function normalizeTags(strategyTags: unknown): string[] {
  if (!Array.isArray(strategyTags)) return [];
  return strategyTags
    .map((t) => String(t || "").trim().toUpperCase())
    .filter(Boolean);
}

// 아이템의 백엔드 표시 태그(한글)를 한 배열로 모은다.
const DISPLAY_TAG_FIELDS = [
  "styleTags",
  "liquidityTags",
  "pricePositionTags",
  "discoveryTags",
  "freshnessTags",
] as const;

function collectDisplayTags(item: Record<string, unknown>): string[] {
  const out: string[] = [];
  DISPLAY_TAG_FIELDS.forEach((field) => {
    const arr = item[field];
    if (Array.isArray(arr)) {
      arr.forEach((t) => {
        const s = String(t || "").trim();
        if (s) out.push(s);
      });
    }
  });
  return out;
}

function numericValue(item: Record<string, unknown>, keys: string[]): number {
  for (const key of keys) {
    const raw = item[key];
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
    if (typeof raw === "string") {
      const parsed = Number(raw.replace(/[^0-9.+-]/g, ""));
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return 0;
}

function scoreHeuristicMatches(
  item: Record<string, unknown>,
  lensId: ExplorationLensId,
  strategyTags: string[],
): boolean {
  const has = (...needles: string[]) =>
    strategyTags.some((tag) => needles.some((needle) => tag.includes(needle)));
  const finalScore = numericValue(item, ["finalScore", "finalRankScore", "recommendationScore", "score"]);
  const ev = numericValue(item, ["expectedValue", "expectedReturnPct", "evPct"]);
  const momentum = numericValue(item, ["momentumScore", "momentumContinuationScore", "relativeStrengthScore"]);
  const upside = numericValue(item, ["upsideScore", "opportunityScore"]);
  const rr = numericValue(item, ["rrScore", "riskRewardScore"]);
  const entry = numericValue(item, ["entryScore", "entryAccessibilityScore"]);
  const riskStable = numericValue(item, ["riskStabilityScore", "riskScore", "stabilityScore"]);

  if (lensId === "leader") {
    return has("MOMENTUM", "BREAKOUT", "GOLDEN_CROSS", "RELATIVE_STRENGTH")
      || momentum >= 60
      || (finalScore >= 65 && ev > 0);
  }
  if (lensId === "discovery") {
    return has("UNDERVALUED", "BB_SQUEEZE", "MA_CONVERGENCE", "VOLATILITY")
      || ev >= 5
      || upside >= 55
      || (rr >= 55 && finalScore >= 50);
  }
  if (lensId === "pullback") {
    return has("PULLBACK", "RETEST", "SUPPORT", "MA_CONVERGENCE")
      || entry >= 65
      || (finalScore >= 50 && riskStable >= 60 && ev > 0);
  }
  if (lensId === "recovery") {
    return has("RECOVERY", "REBOUND", "TURNAROUND", "GOLDEN_CROSS", "STABLE_LOW_RISK")
      || (momentum >= 55 && riskStable >= 55)
      || (finalScore >= 55 && ev > 0 && rr >= 45);
  }
  return false;
}

/**
 * 종목이 특정 렌즈에 해당하는지 판단한다.
 * strategyTags(영문) 또는 표시 태그(한글) 중 하나라도 맞으면 true.
 * balance(matchAll) 는 항상 true.
 */
export function itemMatchesLens(
  item: Record<string, unknown>,
  lensId: ExplorationLensId,
): boolean {
  const lens = LENS_BY_ID[lensId];
  if (!lens) return true;
  if (lens.matchAll) return true;
  const strat = normalizeTags(item?.strategyTags);
  if (strat.length > 0 && lens.strategyTagCodes.some((code) => strat.includes(code))) {
    return true;
  }
  if (lens.displayTags.length > 0) {
    const disp = collectDisplayTags(item || {});
    if (disp.length > 0 && lens.displayTags.some((t) => disp.includes(t))) {
      return true;
    }
  }
  if (scoreHeuristicMatches(item || {}, lensId, strat)) return true;
  return false;
}

// 카드 배지용 렌즈 우선순위 (한 종목이 여러 렌즈에 걸릴 때 대표 1개 선택)
const LENS_PRIORITY: ExplorationLensId[] = [
  "leader",
  "pullback",
  "discovery",
  "recovery",
];

/**
 * 카드에 표시할 대표 렌즈 1개. 매칭되는 렌즈가 없으면 null.
 * (밸런스는 전체 렌즈이므로 대표 배지로는 쓰지 않는다.)
 */
export function primaryLensForItem(
  item: Record<string, unknown>,
): ExplorationLensDef | null {
  for (let i = 0; i < LENS_PRIORITY.length; i += 1) {
    if (itemMatchesLens(item, LENS_PRIORITY[i])) return LENS_BY_ID[LENS_PRIORITY[i]];
  }
  return null;
}
