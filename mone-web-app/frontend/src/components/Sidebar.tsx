"use client";

export type NavGroup = {
  title: string;
  items: string[];
  mode?: "general" | "admin";
};

export type AppMode = "general" | "admin";

export const NAV_GROUPS: NavGroup[] = [
  {
    title: "시장 홈",
    items: ["요약"],
    mode: "general"
  },
  {
    title: "운용 리포트",
    items: ["장전 리포트", "장중 체크", "장마감 검증"],
    mode: "general"
  },
  {
    title: "종목 탐색",
    items: ["종목 검색 / 관심", "오늘 매수 검토", "매수금지 / 주의"],
    mode: "general"
  },
  {
    title: "보유·리스크",
    items: ["보유 현황"],
    mode: "general"
  },
  {
    title: "차트·기술분석",
    items: ["차트 보기"],
    mode: "general"
  },
  {
    title: "뉴스·기업분석",
    items: ["뉴스 요약", "공시", "기업분석"],
    mode: "general"
  },
  {
    title: "예측·검증",
    items: ["확률 예측"],
    mode: "general"
  },
  {
    title: "고급 분석",
    items: ["스캐너", "계산기", "몬테카를로", "상관관계 / 히트맵"],
    mode: "general"
  },
  {
    title: "관리",
    items: ["데이터 점검", "데이터 소스", "API 상태", "자동화 상태", "백테스트", "예측 기록", "결과 검증", "실패 복기", "자동 보정", "로그 / 백업"],
    mode: "admin"
  }
];

export function visibleGroups(appMode: AppMode) {
  return NAV_GROUPS.filter((group) => (appMode === "admin" ? group.mode === "admin" : group.mode !== "admin"));
}

export function firstSubPage(category: string) {
  return NAV_GROUPS.find((group) => group.title === category)?.items[0] ?? "요약";
}

export function Sidebar({
  activeCategory,
  onSelectCategory,
  appMode
}: {
  activeCategory: string;
  onSelectCategory: (value: string) => void;
  appMode: AppMode;
}) {
  const groups = visibleGroups(appMode);
  return (
    <aside className="fixed inset-y-0 left-0 z-20 w-64 border-r border-line bg-ink md:w-72">
      <div className="flex h-full flex-col">
        <div className="border-b border-line px-5 py-4">
          <div className="text-xl font-black tracking-wide text-white">MONE</div>
          <div className="mt-1 text-xs text-muted">Next.js + FastAPI v3.5.6</div>
          <div className="mt-2 inline-flex rounded-full border border-line bg-panel px-2 py-1 text-[11px] font-black text-accent">
            {appMode === "admin" ? "관리자 모드" : "일반 모드"}
          </div>
        </div>
        <nav className="flex-1 px-3 py-4">
          {groups.map((group) => (
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
          {appMode === "admin" ? "데이터·자동화·검증 관리" : "일반 화면은 매매 판단 중심"}
        </div>
      </div>
    </aside>
  );
}
