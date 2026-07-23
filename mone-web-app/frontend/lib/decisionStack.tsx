// Decision Stack — 시장 → 종목 → 최종 행동을 한 줄로 정렬해 화면 간 결론 충돌을
// 사용자에게 설명하는 공통 표현(UX 보고서 3.1/4.2). 홈·탐색·분석이 동일 컴포넌트를
// 써서 "같은 종목이 화면마다 다르게 보이는" 혼란을 없앤다.
// 시장 환경(게이트)은 전역 값이라 화면마다 한 번만 계산해 넘긴다.

export type MarketGate = {
  strength: number;
  levelText: string;
  isHigh: boolean;
  isMid: boolean;
  isLow: boolean;
  maDist: number;
  dataAdj: number;
  hasOhlcv: boolean;
  hasRegimeMa: boolean;
};

// 원래 HomePage에 있던 로직을 공유로 승격(홈·모바일홈 중복 제거 대상).
export function getMarketGateInfo(regime: any, dataHealth: any): MarketGate {
  const base = regime?.regime === "BULL" ? 70 : regime?.regime === "BEAR" ? 22 : 50;
  const hasRegimeMa = regime?.distanceMa20Pct != null || regime?.distanceToMa20Pct != null;
  const maDist = Number(regime?.distanceMa20Pct ?? regime?.distanceToMa20Pct ?? 0);
  const maAdj = maDist >= 3 ? 10 : maDist >= 1 ? 5 : maDist >= -1 ? 0 : maDist >= -3 ? -8 : -15;

  const recoAt = dataHealth?.recoGeneratedAt ? new Date(dataHealth.recoGeneratedAt) : null;
  const hoursOld = recoAt ? (Date.now() - recoAt.getTime()) / 3600000 : null;
  const liveRatio = (dataHealth?.kisTargetCount ?? 0) > 0
    ? (dataHealth?.kisLiveCount ?? 0) / dataHealth.kisTargetCount : 1;
  const hasOhlcv = Number(dataHealth?.ohlcvCount ?? 0) > 0;
  const dataAdj = hoursOld != null && hoursOld > 24 ? -15 : liveRatio < 0.1 ? (hasOhlcv ? -8 : -20) : liveRatio < 0.5 ? -5 : 0;

  const strength = Math.max(0, Math.min(100, base + maAdj + dataAdj));
  // 상태어만 쓴다("진입 검토" 같은 행동어 금지) — 행동은 최종 행동 칸에서만 말한다.
  const levelText = strength >= 55 ? "양호" : strength >= 35 ? "중립" : "대기";
  return {
    strength,
    levelText,
    isHigh: strength >= 55,
    isMid: strength >= 35 && strength < 55,
    isLow: strength < 35,
    maDist,
    dataAdj,
    hasOhlcv,
    hasRegimeMa,
  };
}

// 홈 homeSummary 응답의 marketRegime/dataHealth를 게이트 입력 형태로 정규화.
export function normalizeMarketRegime(raw: any, market: string): any {
  if (!raw || typeof raw !== "object") return null;
  const benchmark = String(raw.benchmark || (market === "us" ? "NASDAQ" : "KOSPI"));
  return {
    ...raw,
    benchmark,
    distanceMa20Pct: raw.distanceMa20Pct ?? raw.distanceToMa20Pct ?? null,
  };
}
export function normalizeDataHealth(raw: any): any {
  if (!raw || typeof raw !== "object") return null;
  return { ...raw };
}

function signalTextOf(score: number): string {
  return score >= 75 ? "양호" : score >= 60 ? "보통" : score > 0 ? "약함" : "-";
}

// 3열 요약: 종목 신호(점수) · 시장 환경(게이트) · 최종 행동(정규 어휘).
export function DecisionStack({
  score,
  gate,
  actionLabel,
  actionToneClass = "text-slate-200",
  className = "",
}: {
  score: number;
  gate: MarketGate | null;
  actionLabel: string;
  actionToneClass?: string;
  className?: string;
}) {
  const signal = signalTextOf(score);
  const gateClass = !gate ? "text-slate-400" : gate.isLow ? "text-red-300" : gate.isMid ? "text-amber-300" : "text-emerald-300";
  return (
    <div className={`grid grid-cols-3 gap-2 rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2 text-[11px] ${className}`}>
      <div>
        <div className="text-[10px] text-slate-400">종목 신호</div>
        <div className="font-semibold text-slate-200">{signal}{score > 0 ? ` · ${Math.round(score)}점` : ""}</div>
      </div>
      <div>
        <div className="text-[10px] text-slate-400">시장 환경</div>
        <div className={`font-semibold ${gateClass}`}>{gate ? `${gate.levelText} ${gate.strength}/100` : "확인 중"}</div>
      </div>
      <div>
        <div className="text-[10px] text-slate-400">최종 행동</div>
        <div className={`font-semibold ${actionToneClass}`}>{actionLabel || "-"}</div>
      </div>
    </div>
  );
}
