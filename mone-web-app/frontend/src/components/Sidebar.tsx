"use client";

export type NavGroup = {
  title: string;
  items: string[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    title: "시장 홈",
    items: ["요약", "오늘 체크", "운영 대시보드"]
  },
  {
    title: "운용 리포트",
    items: ["장전 리포트", "장중 체크", "장마감 검증", "리포트 센터"]
  },
  {
    title: "종목 탐색",
    items: ["선택 종목", "관심종목", "후보군", "매수 후보", "매수금지 / 주의"]
  },
  {
    title: "보유·리스크",
    items: ["보유 관리", "손절·목표가", "평가손익", "포지션 계산"]
  },
  {
    title: "차트·기술분석",
    items: ["차트 보기", "기술지표", "지지·저항", "예측선 / 주문선"]
  },
  {
    title: "뉴스·기업분석",
    items: ["뉴스 요약", "공시", "기업분석", "종목 내러티브"]
  },
  {
    title: "예측·검증",
    items: ["확률 예측", "예측 기록", "결과 검증", "실패 복기", "자동 보정"]
  },
  {
    title: "고급 분석",
    items: ["백테스트", "스캐너", "계산기", "몬테카를로", "상관관계 / 히트맵"]
  },
  {
    title: "관리",
    items: ["데이터 점검", "API 상태", "자동화 상태", "로그 / 백업"]
  }
];

export function firstSubPage(category: string) {
  return NAV_GROUPS.find((group) => group.title === category)?.items[0] ?? "요약";
}

export function Sidebar({
  activeCategory,
  onSelectCategory
}: {
  activeCategory: string;
  onSelectCategory: (value: string) => void;
}) {
  return (
    <aside className="fixed inset-y-0 left-0 z-20 w-64 border-r border-line bg-ink md:w-72">
      <div className="flex h-full flex-col">
        <div className="border-b border-line px-5 py-4">
          <div className="text-xl font-black tracking-wide text-white">MONE</div>
          <div className="mt-1 text-xs text-muted">Next.js + FastAPI v1.2</div>
        </div>
        <nav className="flex-1 px-3 py-4">
          {NAV_GROUPS.map((group) => (
            <button
              key={group.title}
              onClick={() => onSelectCategory(group.title)}
              className={[
                "mb-1 w-full rounded-md px-3 py-2.5 text-left text-sm font-bold transition",
                activeCategory === group.title
                  ? "bg-accent/14 text-accent ring-1 ring-accent/35"
                  : "text-slate-300 hover:bg-white/5 hover:text-white"
              ].join(" ")}
            >
              {group.title}
            </button>
          ))}
        </nav>
        <div className="border-t border-line px-4 py-3 text-xs leading-5 text-muted">
          기존 CSV/JSON read-only
        </div>
      </div>
    </aside>
  );
}
