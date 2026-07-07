// 종목 탐색 고급 필터 분류 체계
//
// 기획서(MONE 종목 탐색 화면 개선안) 4장 고급 필터 구성을 반영한다.
//
// 중요:
// - 이 파일은 화면 표시/필터 UI 구성 전용이다. 추천 점수/정렬/tradeParams에는
//   전혀 관여하지 않는다.
// - 백엔드(quant_scanner._display_taxonomy_tags)가 styleTags/liquidityTags/
//   pricePositionTags/discoveryTags/freshnessTags 를 표시 전용으로 내려준다.
//   activeChips 는 실제 필터로 동작하고, comingSoonChips 는 아직 데이터 원천이
//   없어 "준비 중"으로 표시만 한다(예: 시가총액·배당·섹터 상대강도 기반 태그).

export interface AdvancedFilterGroup {
  id: string;
  label: string;
  /** 이 그룹이 매칭하는 아이템 필드명 (RecommendationItem 의 태그 배열) */
  field: "styleTags" | "liquidityTags" | "pricePositionTags" | "discoveryTags" | "freshnessTags";
  /** 백엔드가 실제로 내려주는 칩 — 필터로 동작 */
  activeChips: string[];
  /** 아직 데이터 원천이 없어 표시만 하는 칩 */
  comingSoonChips: string[];
}

export const ADVANCED_FILTER_GROUPS: AdvancedFilterGroup[] = [
  {
    id: "style",
    label: "종목 스타일",
    field: "styleTags",
    activeChips: [
      "저평가 가치",
      "고성장",
      "고ROE",
      "저PER",
      "저PBR",
      "고마진",
      "재무 안정",
      "현금흐름 우수",
      "퀄리티 우량",
      "고배당",
      "배당 안정",
    ],
    // 대형/중형/소형: 백엔드 코드는 준비됨. market_cap 컬럼이 다음 재무
    // 재수집(fetch_kr_financial_data.py) 후 채워지면 activeChips 로 옮긴다.
    comingSoonChips: ["대형 안정", "중형 성장", "소형 성장", "섹터 대표주", "테마 주도주"],
  },
  {
    id: "discovery",
    label: "발굴형 태그",
    field: "discoveryTags",
    activeChips: [
      "언더레이더",
      "초기 수급 전환",
      "거래대금 증가 초기",
      "박스권 돌파 직전",
      "아직 덜 오름",
      "변화 감지",
      "소외 성장",
      "섹터 후발주",
    ],
    comingSoonChips: [],
  },
  {
    id: "pricePosition",
    label: "가격 반영도",
    field: "pricePositionTags",
    activeChips: [
      "아직 덜 오름",
      "과열 전 구간",
      "박스권 상단 접근",
      "대표주 대비 후행",
      "섹터 대비 후행",
    ],
    comingSoonChips: ["최근 급등 제외"],
  },
  {
    id: "liquidity",
    label: "유동성 / 탈출 가능성",
    field: "liquidityTags",
    activeChips: ["거래대금 충분", "유동성 부족", "급등락 위험"],
    comingSoonChips: ["호가 공백 주의", "소형주 비중 제한"],
  },
  {
    id: "freshness",
    label: "재료 신선도",
    field: "freshnessTags",
    activeChips: ["신규 재료", "공시 확인 필요", "선반영 가능성", "루머성 재료"],
    comingSoonChips: ["반복 재료"],
  },
];

// 선택된 고급 태그 → 어떤 아이템 필드를 봐야 하는지 역인덱스
const CHIP_TO_FIELD: Record<string, AdvancedFilterGroup["field"]> = (() => {
  const map: Record<string, AdvancedFilterGroup["field"]> = {};
  for (const group of ADVANCED_FILTER_GROUPS) {
    for (const chip of group.activeChips) {
      map[chip] = group.field;
    }
  }
  return map;
})();

/**
 * 아이템이 선택된 고급 태그를 모두(AND) 보유하는지 판단한다.
 * 선택이 없으면 항상 통과.
 */
export function itemMatchesAdvancedTags(
  item: Record<string, unknown>,
  selected: readonly string[],
): boolean {
  for (let i = 0; i < selected.length; i += 1) {
    const chip = selected[i];
    const field = CHIP_TO_FIELD[chip];
    if (!field) continue; // 알 수 없는 칩은 무시(방어)
    const tags = item[field];
    if (!Array.isArray(tags) || !tags.includes(chip)) return false;
  }
  return true;
}
