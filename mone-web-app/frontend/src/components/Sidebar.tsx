"use client";

export type AppMode = "general" | "admin";

export const NAV_GROUPS = [
  {
    title: "시장 홈",
    adminOnly: false,
    items: ["요약"],
  },
  {
    title: "운용 리포트",
    adminOnly: false,
    items: ["장전 리포트", "장중 체크", "장마감 검증"],
  },
  {
    title: "종목 탐색",
    adminOnly: false,
    items: ["종목 검색 / 관심", "오늘 매수 검토", "매수금지 / 주의"],
  },
  {
    title: "보유·리스크",
    adminOnly: false,
    items: ["보유 현황"],
  },
  {
    title: "차트·기술분석",
    adminOnly: false,
    items: ["차트 보기"],
  },
  {
    title: "뉴스·기업분석",
    adminOnly: false,
    items: ["뉴스 요약", "공시", "기업분석"],
  },
  {
    title: "예측·검증",
    adminOnly: false,
    items: ["확률 예측"],
  },
  {
    title: "고급 분석",
    adminOnly: false,
    items: ["스캐너", "계산기", "몬테카를로", "상관관계 / 히트맵"],
  },
  {
    title: "관리",
    adminOnly: true,
    items: ["자동화 상태", "백테스트", "예측 기록", "결과 검증", "실패 복기", "자동 보정", "데이터 점검", "데이터 소스", "API 상태"],
  },
];

export function visibleGroups(mode: AppMode = "general") {
  return NAV_GROUPS.filter((group) => mode === "admin" || !group.adminOnly);
}

export function firstSubPage(category?: string, mode: AppMode = "general") {
  const group = visibleGroups(mode).find((item) => item.title === category) ?? visibleGroups(mode)[0] ?? NAV_GROUPS[0];
  return group.items[0] ?? "요약";
}

export function Sidebar({
  activeCategory,
  onSelectCategory,
  appMode = "general",
}: {
  activeCategory?: string;
  onSelectCategory?: (category: string) => void;
  appMode?: AppMode;
}) {
  const groups = visibleGroups(appMode);

  return (
    <aside className="fixed left-0 top-0 z-20 h-screen w-64 overflow-y-auto border-r border-slate-800 bg-slate-950 p-4 text-slate-100 md:w-72">
      <div className="mb-6">
        <div className="text-2xl font-black tracking-widest text-white">MONE</div>
        <div className="mt-1 text-xs text-slate-500">AGNAS decision board</div>
      </div>

      <nav className="space-y-2">
        {groups.map((group) => (
          <button
            key={group.title}
            type="button"
            onClick={() => onSelectCategory?.(group.title)}
            className={`w-full rounded-xl px-4 py-3 text-left text-sm font-black transition ${
              activeCategory === group.title
                ? "border border-sky-500/60 bg-sky-500/10 text-sky-300"
                : "border border-transparent text-slate-300 hover:bg-slate-900 hover:text-white"
            }`}
          >
            {group.title}
          </button>
        ))}
      </nav>
    </aside>
  );
}
