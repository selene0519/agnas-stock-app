"use client";

import { useEffect, useState } from "react";
import { mone } from "@/lib/api";
import { Scale } from "lucide-react";

/**
 * 추천의 **시장 대비** 성적을 보여준다.
 *
 * 왜 필요한가: 화면이 원시 수익률만 보여주면 사용자는 "-14%"를 앱 실패로 읽는다.
 * 그런데 같은 구간에 KOSPI가 -24% 빠졌다면 선택은 오히려 시장을 이긴 것이다.
 * 원시 / 시장 몫 / 알파를 나란히 놓아야 같은 숫자가 정직하게 읽힌다.
 *
 * 동시에 **과대 해석도 막아야 한다.** 이벤트가 며칠에 몰려 있으면 통계적
 * 유의성을 주장할 수 없고, 알파가 (+)여도 계좌는 줄 수 있다. 그 두 가지를
 * 숫자 옆에 같이 그린다.
 */

type WindowStat = {
  events: number;
  meanCarPct: number;
  meanRawReturnPct: number;
  marketComponentPct: number;
  pValue: number;
  significant: boolean;
  significanceUsable?: boolean;
  sampleWarning?: string | null;
};

type AlphaData = {
  status: string;
  message?: string;
  events?: number;
  avgBeta?: number;
  eventDateRange?: { min?: string; max?: string };
  windows?: Record<string, WindowStat>;
  clustering?: {
    distinctEventDates?: number;
    eventsPerDate?: number;
    isClustered?: boolean;
    note?: string;
  };
  caveats?: string[];
};

function pct(v?: number | null, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "-";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function toneOf(v?: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "text-slate-400";
  return v > 0 ? "text-emerald-300" : v < 0 ? "text-red-300" : "text-slate-300";
}

export default function AlphaPanel() {
  const [data, setData] = useState<AlphaData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res: any = await mone.edgeAlpha();
        if (alive) setData(res);
      } catch {
        if (alive) setData({ status: "ERROR" });
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  if (loading) {
    return (
      <div className="rounded-xl bg-slate-900/50 px-4 py-5 text-center text-xs text-slate-400">
        시장 대비 성적 계산 중...
      </div>
    );
  }

  // 데이터가 없으면 숫자를 지어내지 않고 왜 없는지만 말한다.
  if (!data || data.status !== "OK" || !data.windows) {
    return (
      <div className="rounded-xl bg-slate-900/50 px-4 py-4 text-[11.5px] text-slate-400">
        <p className="mb-1 font-semibold text-slate-300">시장 대비 성적</p>
        <p>{data?.message || "아직 계산된 결과가 없습니다."}</p>
      </div>
    );
  }

  const clustered = Boolean(data.clustering?.isClustered);
  const entries = Object.entries(data.windows);

  return (
    <section className="rounded-xl bg-slate-900/60 p-4 shadow-[inset_0_0_0_1px_rgba(148,163,184,0.10)]">
      <div className="mb-1 flex items-center gap-2">
        <Scale size={14} className="text-teal-400" />
        <h3 className="text-xs font-bold text-slate-100">시장 대비 성적 (알파)</h3>
      </div>
      <p className="mb-3 text-[11px] leading-relaxed text-slate-400">
        추천 수익률에서 <strong className="text-slate-300">시장이 끌고 간 몫</strong>을 빼고
        남은 부분입니다. 시장이 빠진 구간의 손실은 종목 선택 실패가 아닙니다.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[300px] text-[11px]">
          <thead>
            <tr className="text-slate-500">
              <th className="py-1 text-left font-medium">기간</th>
              <th className="py-1 text-right font-medium">추천</th>
              <th className="py-1 text-right font-medium">시장</th>
              <th className="py-1 text-right font-medium">차이</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([name, w]) => (
              <tr key={name} className="border-t border-slate-800/70">
                <td className="py-1.5 text-slate-300">{name}</td>
                <td className={`py-1.5 text-right tabular-nums ${toneOf(w.meanRawReturnPct)}`}>
                  {pct(w.meanRawReturnPct)}
                </td>
                <td className={`py-1.5 text-right tabular-nums ${toneOf(w.marketComponentPct)}`}>
                  {pct(w.marketComponentPct)}
                </td>
                <td className={`py-1.5 text-right font-semibold tabular-nums ${toneOf(w.meanCarPct)}`}>
                  {pct(w.meanCarPct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 알파가 (+)라고 돈을 번 게 아니다. 이 문장이 빠지면 카드가 낙관을 판다. */}
      <p className="mt-3 text-[10.5px] leading-relaxed text-amber-300/90">
        &lsquo;차이&rsquo;가 (+)여도 <strong>시장보다 덜 빠졌다</strong>는 뜻이지 수익이 났다는
        뜻이 아닙니다. 실제 계좌는 &lsquo;추천&rsquo; 열을 따릅니다.
      </p>

      {clustered && (
        <p className="mt-2 text-[10.5px] leading-relaxed text-amber-300/90">
          ⚠ 분석에 쓰인 추천 {data.events}건이 서로 다른{" "}
          {data.clustering?.distinctEventDates}일에 몰려 있어(하루 평균{" "}
          {data.clustering?.eventsPerDate}건) 모두 같은 시장 상황을 겪었습니다.
          <strong> 통계적 유의성은 주장할 수 없습니다.</strong>
        </p>
      )}

      <p className="mt-2 text-[10px] text-slate-500">
        표본 {data.events}건
        {data.eventDateRange?.min && ` · ${data.eventDateRange.min}~${data.eventDateRange.max}`}
        {data.avgBeta !== undefined && ` · 평균 베타 ${data.avgBeta}`}
      </p>
    </section>
  );
}
