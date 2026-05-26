"use client";

const MENU = [
  "시장 홈",
  "장전 리포트",
  "장중 체크",
  "장마감 검증",
  "선택 종목",
  "관심종목 / 후보군",
  "매수 후보",
  "매수금지 / 주의",
  "보유 관리",
  "손절·목표가",
  "차트 보기",
  "뉴스·공시·기업분석",
  "확률 예측",
  "백테스트",
  "스캐너",
  "계산기",
  "몬테카를로",
  "상관관계 / 히트맵",
  "리포트 센터",
  "데이터 점검",
  "API / 자동화 상태"
];

export function Sidebar({
  active,
  onSelect
}: {
  active: string;
  onSelect: (value: string) => void;
}) {
  return (
    <aside className="fixed inset-y-0 left-0 z-20 w-72 border-r border-line bg-ink">
      <div className="flex h-full flex-col">
        <div className="border-b border-line px-5 py-4">
          <div className="text-xl font-black tracking-wide text-white">MONE</div>
          <div className="mt-1 text-xs text-muted">Next.js + FastAPI v1</div>
        </div>
        <nav className="scrollbar-thin flex-1 overflow-y-auto px-3 py-4">
          {MENU.map((item) => (
            <button
              key={item}
              onClick={() => onSelect(item)}
              className={[
                "mb-1 w-full rounded-md px-3 py-2 text-left text-sm transition",
                active === item
                  ? "bg-accent/14 text-accent ring-1 ring-accent/35"
                  : "text-slate-300 hover:bg-white/5 hover:text-white"
              ].join(" ")}
            >
              {item}
            </button>
          ))}
        </nav>
        <div className="border-t border-line px-4 py-3 text-xs text-muted">
          기존 CSV/JSON read-only
        </div>
      </div>
    </aside>
  );
}
