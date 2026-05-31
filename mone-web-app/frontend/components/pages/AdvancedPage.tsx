"use client";

import { useMemo, useState } from "react";

type TabId = "scanner" | "calculator" | "montecarlo" | "correlation";

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="text-base font-semibold text-slate-100">{title}</h2>
      <div className="mt-4">{children}</div>
    </div>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-2 text-lg font-bold text-slate-100">{value}</div>
    </div>
  );
}

export default function AdvancedPage() {
  const [tab, setTab] = useState<TabId>("scanner");
  const [entry, setEntry] = useState(70000);
  const [stop, setStop] = useState(66500);
  const [target, setTarget] = useState(80500);
  const [winRate, setWinRate] = useState(55);
  const [riskPct, setRiskPct] = useState(1);

  const rr = useMemo(() => {
    const risk = Math.max(entry - stop, 0);
    const reward = Math.max(target - entry, 0);
    return risk > 0 ? reward / risk : 0;
  }, [entry, stop, target]);

  const kelly = useMemo(() => {
    const p = winRate / 100;
    const b = rr;
    if (b <= 0) return 0;
    return Math.max(((p * (b + 1) - 1) / b) * 100, 0);
  }, [winRate, rr]);

  const tabs: { id: TabId; label: string }[] = [
    { id: "scanner", label: "스캐너" },
    { id: "calculator", label: "계산기" },
    { id: "montecarlo", label: "몬테카를로" },
    { id: "correlation", label: "상관관계" },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h1 className="text-xl font-bold text-white">고급분석</h1>
        <p className="mt-1 text-xs text-slate-400">
          스캐너, 리스크 계산기, 몬테카를로, 상관관계 도구를 확인합니다.
        </p>
      </div>

      <div className="flex w-fit flex-wrap gap-1 rounded-lg bg-slate-800/50 p-1">
        {tabs.map((item) => (
          <button
            key={item.id}
            onClick={() => setTab(item.id)}
            className={`rounded-md px-4 py-2 text-sm transition-colors ${
              tab === item.id ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "scanner" && (
        <Card title="스캐너">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Metric label="신호 상태" value="준비됨" />
            <Metric label="리스크 필터" value="균형" />
            <Metric label="데이터 모드" value="실제 API" />
          </div>

          <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">
            스캐너 결과는 추천 API와 연결되어야 합니다. 일반 사용자 화면에는 명확한 후보만 보여주고,
            상세 진단값은 관리자 영역에서 확인합니다.
          </div>
        </Card>
      )}

      {tab === "calculator" && (
        <Card title="리스크 계산기">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <label className="space-y-2 text-sm text-slate-400">
              진입가
              <input
                type="number"
                value={entry}
                onChange={(event) => setEntry(Number(event.target.value))}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="space-y-2 text-sm text-slate-400">
              손절가
              <input
                type="number"
                value={stop}
                onChange={(event) => setStop(Number(event.target.value))}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="space-y-2 text-sm text-slate-400">
              목표가
              <input
                type="number"
                value={target}
                onChange={(event) => setTarget(Number(event.target.value))}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              />
            </label>

            <label className="space-y-2 text-sm text-slate-400">
              승률 %
              <input
                type="number"
                value={winRate}
                onChange={(event) => setWinRate(Number(event.target.value))}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100"
              />
            </label>
          </div>

          <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-4">
            <Metric label="손익비" value={rr.toFixed(2)} />
            <Metric label="켈리 추정" value={`${kelly.toFixed(2)}%`} />
            <Metric label="1회 거래 리스크" value={`${riskPct.toFixed(2)}%`} />
            <Metric label="모드" value="균형" />
          </div>

          <div className="mt-4">
            <label className="space-y-2 text-sm text-slate-400">
              1회 거래 리스크 %
              <input
                type="number"
                value={riskPct}
                onChange={(event) => setRiskPct(Number(event.target.value))}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 md:w-64"
              />
            </label>
          </div>
        </Card>
      )}

      {tab === "montecarlo" && (
        <Card title="몬테카를로">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Metric label="시뮬레이션 상태" value="API 대기" />
            <Metric label="기본 반복 횟수" value="1000" />
            <Metric label="출력" value="리스크 범위" />
          </div>

          <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">
            포트폴리오 단위 시뮬레이션을 위한 영역입니다. 과거 수익률 데이터 API가 연결되면 기본값으로도 사용할 수 있습니다.
          </div>
        </Card>
      )}

      {tab === "correlation" && (
        <Card title="상관관계">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Metric label="시장" value="국장 / 미장" />
            <Metric label="데이터 출처" value="OHLCV" />
            <Metric label="상태" value="API 대기" />
          </div>

          <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">
            상관관계 분석은 정제된 가격 이력을 사용하고, 누락되었거나 오래된 OHLCV 종목은 제외해야 합니다.
          </div>
        </Card>
      )}
    </div>
  );
}
