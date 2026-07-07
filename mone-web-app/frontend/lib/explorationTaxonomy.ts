// 종목 탐색 렌즈(Exploration Lens) 분류 체계
//
// 목적: 종목 탐색 화면을 단순 점수 필터가 아니라, 투자 기회 유형별로
//       고를 수 있는 "발굴형 탐색"으로 확장한다.
//
// 중요(구현 원칙):
// - 이 파일은 화면 표시/필터링 전용이다. finalScore·추천 정렬·entry/target/stop
//   계산식에는 전혀 관여하지 않는다.
// - 백엔드가 explorationLens 필드를 아직 내려주지 않으므로, 프론트에서 기존
//   strategyTags(영문 코드)를 기준으로 렌즈를 근사 분류한다.
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
  /**
   * 이 렌즈에 해당하는 strategyTags(영문 코드) 집합.
   * 종목의 strategyTags 중 하나라도 포함되면 해당 렌즈 후보로 본다.
   * balance 는 전체를 보는 기본 렌즈이므로 비워 둔다(matchAll).
   */
  strategyTagCodes: string[];
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
    accent: "border-orange-500/50 bg-orange-500/10 text-orange-300",
  },
  {
    id: "discovery",
    label: "발굴주",
    short: "아직 덜 알려진 초기 변화 후보",
    description:
      "아직 시장 관심은 크지 않지만, 변동성 압축·이격도 수렴 등에서 변화가 감지되는 종목입니다.",
    // 발굴형 태그(언더레이더/초기 수급 전환 등)는 아직 백엔드에 없으므로,
    // 변동성 압축·수렴 신호를 초기 변화 후보의 근사치로 사용한다.
    strategyTagCodes: ["BB_SQUEEZE", "MA_CONVERGENCE"],
    accent: "border-sky-500/50 bg-sky-500/10 text-sky-300",
  },
  {
    id: "pullback",
    label: "눌림주",
    short: "조정 후 다시 갈 수 있는 종목",
    description:
      "상승 추세는 유지 중이나 현재는 조정 구간입니다. 지지 확인 후 진입이 유리합니다.",
    strategyTagCodes: ["PULLBACK_BUY", "MA_CONVERGENCE"],
    accent: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300",
  },
  {
    id: "recovery",
    label: "회복주",
    short: "저평가에서 회복 신호가 있는 종목",
    description:
      "저평가 상태에서 실적·수급·거래량 회복 신호가 보이는 종목입니다.",
    strategyTagCodes: ["UNDERVALUED_GROWTH", "DOUBLE_BOTTOM", "INV_HEAD_SHOULDERS"],
    accent: "border-violet-500/50 bg-violet-500/10 text-violet-300",
  },
  {
    id: "balance",
    label: "밸런스",
    short: "점수와 리스크를 종합한 후보",
    description:
      "점수·리스크·진입 적시성을 종합해 균형 있게 선별한 후보입니다.",
    strategyTagCodes: [],
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

/**
 * 종목의 strategyTags 가 특정 렌즈에 해당하는지 판단한다.
 * balance(matchAll) 는 항상 true.
 */
export function itemMatchesLens(
  strategyTags: unknown,
  lensId: ExplorationLensId,
): boolean {
  const lens = LENS_BY_ID[lensId];
  if (!lens) return true;
  if (lens.matchAll) return true;
  const tags = normalizeTags(strategyTags);
  if (tags.length === 0) return false;
  return lens.strategyTagCodes.some((code) => tags.includes(code));
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
  strategyTags: unknown,
): ExplorationLensDef | null {
  for (const id of LENS_PRIORITY) {
    if (itemMatchesLens(strategyTags, id)) return LENS_BY_ID[id];
  }
  return null;
}
