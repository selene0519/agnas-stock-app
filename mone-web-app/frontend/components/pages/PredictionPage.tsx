"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone, type Market } from "@/lib/api";
import { dedupeBySymbol, displayName, firstText, horizonLabel, modeLabel, pctText, priceText, probabilityText, toNumber } from "@/lib/moneDisplay";
import { getDefaultMarketBySession } from "@/lib/marketSession";

type Strategy = "conservative" | "balanced" | "aggressive";
type Term = "short" | "swing" | "mid";

function avg(items: any[], getter: (item: any) => number | null) {
  const nums = items.map(getter).filter((value): value is number => Number.isFinite(value as number));
  if (!nums.length) return 0;
  return nums.reduce((a, b) => a + b, 0) / nums.length;
}

type ValidationStatus = "검증대기" | "미체결" | "체결" | "목표도달" | "손절" | "보류" | "오류";

function fieldText(item: any, keys: string[]) {
  for (const key of keys) {
    const value = item?.[key];
    if (value !== undefined && value !== null && String(value).trim() !== "") return String(value).trim();
  }
  return "";
}

function lowerToken(value: string) {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

function isTruthyExecution(value: any) {
  return ["true", "1", "yes", "y", "체결", "executed", "hit", "완료"].includes(lowerToken(String(value ?? "")));
}

function resolveStatus(item: any): ValidationStatus {
  const bucket = lowerToken(fieldText(item, ["decisionBucket", "decision_bucket", "bucket"]));
  const block = String(item.tradeBlockStatus || item.trade_block_status || "").toUpperCase();
  const outcome = lowerToken(fieldText(item, ["outcome", "result", "status", "virtualResult", "executionStatus", "execution_status"]));
  const executed = fieldText(item, ["isExecuted", "is_executed", "executed"]);

  if (["data_pending", "pending", "validatable"].includes(outcome)) return "검증대기";
  if (["not_executed", "no_touch", "missed_entry", "unexecuted", "미체결", "진입가_미터치"].includes(outcome)) return "미체결";
  if (outcome.includes("target") || outcome.includes("tp") || outcome.includes("win") || outcome.includes("목표")) return "목표도달";
  if (outcome.includes("stop") || outcome.includes("loss") || outcome.includes("손절")) return "손절";
  if (isTruthyExecution(executed) || ["executed", "hit", "체결", "완료"].includes(outcome)) return "체결";
  if (bucket === "보류" || bucket === "제외" || block === "CAUTION" || block === "BLOCK") return "보류";
  if (bucket === "실행" || bucket === "즉시실행") return "체결";
  if (bucket === "대기") return "미체결";
  return "검증대기";
}

const STATUS_STYLE: Record<ValidationStatus, string> = {
  "검증대기": "border-slate-700 bg-slate-800/60 text-slate-400",
  "미체결":   "border-amber-600/30 bg-amber-900/20 text-amber-300",
  "체결":     "border-blue-500/30 bg-blue-900/20 text-blue-300",
  "목표도달": "border-emerald-500/30 bg-emerald-900/20 text-emerald-300",
  "손절":     "border-red-500/30 bg-red-900/20 text-red-300",
  "보류":     "border-slate-600/30 bg-slate-800/40 text-slate-500",
  "오류":     "border-red-700/30 bg-red-950/20 text-red-400",
};

function scoreOf(item: any) {
  const direct = toNumber(item.score ?? item.finalScore ?? item.totalScore ?? item.riskScore);
  if (direct !== null && direct > 0) return direct;
  const p = toNumber(item.probability ?? item.probabilityText ?? item.prob5d);
  return p !== null ? Math.max(1, Math.min(100, p)) : null;
}

function mergeBySymbol(predictions: any[], recommendations: any[]) {
  const recMap = new Map<string, any>();
  for (const item of dedupeBySymbol(recommendations)) recMap.set(`${item.market}-${item.symbol}`, item);
  return dedupeBySymbol(predictions).map((item) => {
    const rec = recMap.get(`${item.market}-${item.symbol}`) || {};
    return { ...rec, ...item, name: displayName({ ...rec, ...item }), recommendation: rec };
  });
}

function keyOf(item: any) {
  const market = String(item?.market || "").toLowerCase();
  const symbol = String(item?.symbol || item?.code || item?.ticker || "").trim().toUpperCase();
  return `${market}-${symbol}`;
}

function fulfilled<T>(result: PromiseSettledResult<T>, fallback: T): T {
  return result.status === "fulfilled" ? result.value : fallback;
}

function combineValidationDashboards(results: any[]) {
  const dashboards = results.filter((item) => item?.summary || item?.stats);
  if (!dashboards.length) return null;
  const stats: Record<string, any> = {};
  const keys = new Set<string>();
  dashboards.forEach((dash) => Object.keys(dash.stats || {}).forEach((key) => keys.add(key)));
  keys.forEach((key) => {
    const rows = dashboards.map((dash) => dash.stats?.[key]).filter(Boolean);
    const completed = rows.reduce((sum, row) => sum + Number(row.completed || 0), 0);
    const wins = rows.reduce((sum, row) => sum + Number(row.wins || 0), 0);
    const pendingCount = rows.reduce((sum, row) => sum + Number(row.pendingCount || 0), 0);
    const returns = rows.map((row) => Number(row.avgReturn)).filter(Number.isFinite);
    stats[key] = {
      completed,
      wins,
      pendingCount,
      winRate: completed > 0 ? Number(((wins / completed) * 100).toFixed(1)) : null,
      avgReturn: returns.length ? returns.reduce((a, b) => a + b, 0) / returns.length : null,
    };
  });
  const totalCompleted = dashboards.reduce((sum, dash) => sum + Number(dash.summary?.totalCompleted || 0), 0);
  const totalPending = dashboards.reduce((sum, dash) => sum + Number(dash.summary?.totalPending || 0), 0);
  const totalWins = dashboards.reduce((sum, dash) => sum + Number(dash.summary?.totalWins || 0), 0);
  return {
    status: "OK",
    market: dashboards.length > 1 ? "all" : dashboards[0].market,
    stats,
    summary: {
      totalCompleted,
      totalPending,
      overallWinRate: totalCompleted > 0 ? Number(((totalWins / totalCompleted) * 100).toFixed(1)) : null,
    },
  };
}

const PLAYBOOK: Record<Strategy, { enter: string; avoid: string; size: string; regime: string; failure: string }> = {
  conservative: {
    enter: "시장 변동성이 낮고 손절폭이 좁으며 진입가가 현재가와 가까울 때",
    avoid: "거래대금 부족, 손절폭 과다, DATA_PENDING, 진입가 괴리 확대",
    size: "기본 3~5%, half-Kelly가 낮으면 더 줄임",
    regime: "BEAR/NEUTRAL에서도 우선 확인",
    failure: "미체결이 많으면 진입가를 보수적으로 낮추고 목표 기간을 늘림",
  },
  balanced: {
    enter: "확률·EV·손익비가 동시에 양호하고 최근 검증 승률이 45~55% 이상일 때",
    avoid: "뉴스 리스크, 반복 손절, 목표가 대비 기대수익 부족",
    size: "기본 5~10%, 손절폭과 승률로 자동 축소",
    regime: "NEUTRAL/BULL에서 기본 전략",
    failure: "목표 도달 전에 기간 만료가 많으면 보유 기간과 목표폭을 재조정",
  },
  aggressive: {
    enter: "BULL 또는 강한 모멘텀에서 확률·거래대금·상승 여지가 모두 맞을 때",
    avoid: "BEAR 레짐, 변동성 과열, 최근 공격형 반복 실패, 현재가가 진입가에서 멀 때",
    size: "기본 10~15%, 과열·손절폭 확대 시 자동 보류 또는 축소",
    regime: "BULL 적합, BEAR에서는 공격 보류",
    failure: "손절 선행이 많으면 목표가 과대 추정과 진입 밴드를 동시에 보정",
  },
};

function touchEvidence(row: any) {
  if (!row) {
    return {
      label: "검증대기",
      detail: "검증 행 없음",
      style: "border-slate-700 bg-slate-800/60 text-slate-400",
    };
  }
  const result = lowerToken(fieldText(row, ["result", "status", "outcome", "executionStatus", "execution_status"]));
  const reason = fieldText(row, ["reason", "dataStatus", "data_status", "validationRule", "validation_rule"]);
  if (result === "data_pending" || String(row.dataStatus || row.data_status || "").toUpperCase() === "DATA_PENDING") {
    return { label: "DATA_PENDING", detail: reason || "OHLCV 수집 필요", style: "border-amber-500/30 bg-amber-500/10 text-amber-200" };
  }
  if (["not_executed", "no_touch", "missed_entry", "unexecuted"].includes(result)) {
    return { label: "미터치", detail: reason || "실제 저가/고가가 진입가를 통과하지 않음", style: "border-slate-600/40 bg-slate-800/50 text-slate-300" };
  }
  if (isTruthyExecution(row.isExecuted ?? row.is_executed ?? row.executed) || ["target", "tp1", "win", "stop", "loss", "executed"].some((key) => result.includes(key))) {
    return { label: "터치 확인", detail: reason || "entry_touch_only", style: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
  }
  return { label: "검증대기", detail: reason || "결과 대기", style: "border-slate-700 bg-slate-800/60 text-slate-400" };
}

function StrategyPlaybookPanel({ strategy, term, data, valDash }: { strategy: Strategy; term: Term; data: any; valDash: any }) {
  const book = PLAYBOOK[strategy];
  const active = valDash?.stats?.[`${strategy}_${term}`];
  const correction = data?.selfCorrection || {};
  const penalty = correction.selfCorrectionPenaltyPct ?? correction.penaltyPct ?? correction.recentNotExecutedRate;
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-5">
      {[
        ["진입 조건", book.enter],
        ["진입 금지", book.avoid],
        ["포지션 크기", book.size],
        ["레짐 적합도", book.regime],
        ["실패 보정", penalty != null ? `최근 검증 기준 보정값 ${Number(penalty).toFixed(2)}% 반영` : book.failure],
      ].map(([label, value]) => (
        <div key={label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="text-xs font-semibold text-slate-500">{label}</div>
          <div className="mt-2 text-sm leading-5 text-slate-200">{value}</div>
        </div>
      ))}
      {active?.winRate != null && (
        <div className="xl:col-span-5 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-xs text-emerald-100">
          현재 전략 검증: 완료 {active.completed ?? 0}건, 대기 {active.pendingCount ?? 0}건, 승률 {active.winRate}%입니다. DATA_PENDING과 미체결은 승률 계산에서 제외하고 진입가 보정 신호로만 봅니다.
        </div>
      )}
    </div>
  );
}

function ValidationPolicyPanel({ market, data, validationRows }: { market: Market; data: any; validationRows: any[] }) {
  const pending = validationRows.filter((row) => resolveStatus(row) === "검증대기").length;
  const noTouch = validationRows.filter((row) => resolveStatus(row) === "미체결").length;
  const policy = data?.validationPolicy || {};
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-200">검증 정책</div>
        <div className="text-xs text-slate-500">행 단위 검증 {validationRows.length.toLocaleString("ko-KR")}건 · DATA_PENDING/대기 {pending}건 · 진입 미터치 {noTouch}건</div>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">실제 저가 ≤ 진입가 ≤ 실제 고가일 때만 체결</div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">미체결은 승률·수익률에서 제외</div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">목표·손절 동시 터치 시 손절 우선</div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">OHLCV 누락은 DATA_PENDING으로 보류</div>
      </div>
      <div className="mt-3 text-[11px] text-slate-500">
        {market === "all" ? "전체 탭은 KR/US 검증을 분리 호출한 뒤 합산합니다." : `${market.toUpperCase()} 검증 기준입니다.`}
        {policy.executionRule && <span className="ml-2">{policy.executionRule}</span>}
      </div>
    </div>
  );
}

export default function PredictionPage() {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [strategy, setStrategy] = useState<Strategy>("balanced");
  const [term, setTerm] = useState<Term>("swing");
  const [data, setData] = useState<any>({ items: [] });
  const [accuracy, setAccuracy] = useState<any>(null);
  const [valDash, setValDash] = useState<any>(null);
  const [btItems, setBtItems] = useState<any[]>([]);
  const [validationRows, setValidationRows] = useState<any[]>([]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ValidationStatus | "all">("all");
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setData((prev: any) => ({ ...prev, status: "LOADING" }));
    try {
      const validationMarkets = market === "all" ? (["kr", "us"] as const) : ([market] as const);
      const predPromise = mone.predictions({ market, mode: strategy, horizon: term, limit: 300 });
      const recPromise = mone.recommendations({ market, mode: strategy, horizon: term, limit: 300 });
      const accPromise = mone.predictionAccuracy({ market: market === "all" ? "all" : market });
      const vdPromise = Promise.all(validationMarkets.map((mk) => mone.validationDashboard({ market: mk }))).then(combineValidationDashboards);
      const btPromise = Promise.all(validationMarkets.map((mk) => mone.backtestTrades({ market: mk, mode: strategy, horizon: term, limit: 200 })))
        .then((rows) => rows.flatMap((row) => Array.isArray(row.items) ? row.items : []));
      const validationPromise = mone.virtualValidation({ market, mode: strategy, horizon: term, limit: 300 });

      const [predResult, recResult] = await Promise.allSettled([predPromise, recPromise]);
      const pred = fulfilled(predResult, { status: "ERROR", items: [] });
      const rec = fulfilled(recResult, { status: "ERROR", items: [] });
      const predItems = Array.isArray(pred.items) ? pred.items : [];
      const recItems = Array.isArray(rec.items) ? rec.items : [];
      const merged = predItems.length ? mergeBySymbol(predItems, recItems) : dedupeBySymbol(recItems);
      setData({
        ...pred,
        items: merged,
        recommendationCount: recItems.length,
        validationPolicy: pred.validationPolicy || rec.validationPolicy,
        selfCorrection: pred.selfCorrection || rec.selfCorrection,
        scanCoverage: rec.scanCoverage || pred.scanCoverage,
      });

      const [accResult, vdResult, btResult, validationResult] = await Promise.allSettled([accPromise, vdPromise, btPromise, validationPromise]);
      const acc = fulfilled(accResult, null);
      const vd = fulfilled(vdResult, null);
      const bt = fulfilled(btResult, []);
      const vv = fulfilled(validationResult, { status: "ERROR", items: [] });
      setAccuracy(acc?.status === "OK" ? acc : null);
      setValDash(vd?.summary ? vd : null);
      setBtItems(Array.isArray(bt) ? bt : []);
      setValidationRows(Array.isArray(vv.items) ? vv.items : []);
    } catch (error) {
      setData({ status: "ERROR", error: String(error), items: [] });
      setAccuracy(null);
      setValDash(null);
      setBtItems([]);
      setValidationRows([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, strategy, term]);

  const items = Array.isArray(data.items) ? data.items : [];
  const validationBySymbol = useMemo(() => {
    const map = new Map<string, any>();
    validationRows.forEach((row) => {
      const key = keyOf(row);
      if (key !== "-") map.set(key, row);
    });
    return map;
  }, [validationRows]);
  const enrichedItems = useMemo(() => items.map((item) => {
    const validation = validationBySymbol.get(keyOf(item));
    return validation ? { ...item, validation } : item;
  }), [items, validationBySymbol]);
  const top = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return enrichedItems
      .filter((item) => {
        if (statusFilter !== "all" && resolveStatus(item.validation || item) !== statusFilter) return false;
        if (!needle) return true;
        return `${displayName(item)} ${item.symbol}`.toLowerCase().includes(needle);
      })
      .slice(0, 30);
  }, [enrichedItems, query, statusFilter]);

  // 수익률 분포 (btItems 기반)
  const retDist = useMemo(() => {
    const rets = btItems
      .map((r: any) => Number(r.returnPct ?? r.virtual_return_pct ?? 0))
      .filter((v: number) => v !== 0);
    if (!rets.length) return null;
    const buckets = [
      { label: "< -5%", min: -Infinity, max: -5 },
      { label: "-5~0%", min: -5, max: 0 },
      { label: "0~5%", min: 0, max: 5 },
      { label: "5~10%", min: 5, max: 10 },
      { label: "> 10%", min: 10, max: Infinity },
    ].map((b) => ({ ...b, count: rets.filter((v: number) => v >= b.min && v < b.max).length }));
    const maxCount = Math.max(...buckets.map((b) => b.count), 1);
    const executed = btItems.filter((r: any) => String(r.executed ?? "").toLowerCase() === "true").length;
    const wins = btItems.filter((r: any) => Number(r.returnPct ?? r.virtual_return_pct ?? 0) > 0).length;
    return { buckets, maxCount, total: rets.length, executed, wins, winRate: rets.length > 0 ? (wins / rets.length * 100).toFixed(1) : "0.0" };
  }, [btItems]);

  const stats = useMemo(() => {
    if (!top.length) return null;
    const statuses = top.map((item) => resolveStatus(item.validation || item));
    const targetCount = statuses.filter((s) => s === "목표도달").length;
    const stopCount = statuses.filter((s) => s === "손절").length;
    const executedCount = statuses.filter((s) => s === "체결" || s === "목표도달" || s === "손절").length;
    const winRate = executedCount > 0 ? (targetCount / executedCount) * 100 : 0;
    const avgEv = avg(top, (item) => toNumber(item.expectedValue ?? item.ev));
    return { targetCount, stopCount, executedCount, winRate, avgEv, statusCounts: Object.fromEntries(["검증대기","미체결","체결","목표도달","손절","보류"].map((s) => [s, statuses.filter((x) => x === s).length])) };
  }, [top]);

  const strategyTabs: { id: Strategy; label: string }[] = [
    { id: "conservative", label: "보수" },
    { id: "balanced", label: "균형" },
    { id: "aggressive", label: "공격" },
  ];
  const termTabs: { id: Term; label: string }[] = [
    { id: "short", label: "단기" },
    { id: "swing", label: "스윙" },
    { id: "mid", label: "중기" },
  ];

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-100 sm:text-2xl">예측·검증</h1>
          <p className="mt-1 text-xs text-slate-400 sm:text-sm">확률 예측, 예상가, 진입/손절/목표를 기간과 성향별로 확인합니다.</p>
        </div>
        <button onClick={load} disabled={loading} className="inline-flex shrink-0 flex-col items-center gap-1 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-[11px] font-medium text-slate-300 disabled:opacity-50">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          <span>새로<br />고침</span>
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "kr", "us"] as Market[]).map((item) => (
          <button key={item} onClick={() => setMarket(item)} className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>{item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}</button>
        ))}
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">투자 성향</div>
            <div className="flex flex-wrap gap-2">
              {strategyTabs.map((item) => (
                <button key={item.id} onClick={() => setStrategy(item.id)} className={`rounded-xl px-4 py-2 text-sm ${strategy === item.id ? "bg-emerald-600 text-white" : "bg-slate-950 text-slate-400"}`}>{item.label}</button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">투자 기간</div>
            <div className="flex flex-wrap gap-2">
              {termTabs.map((item) => (
                <button key={item.id} onClick={() => setTerm(item.id)} className={`rounded-xl px-4 py-2 text-sm ${term === item.id ? "bg-cyan-600 text-white" : "bg-slate-950 text-slate-400"}`}>{item.label}</button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <StrategyPlaybookPanel strategy={strategy} term={term} data={data} valDash={valDash} />

      <ValidationPolicyPanel market={market} data={data} validationRows={validationRows} />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card label="표시 후보" value={`${top.length}개`} />
        <Card label="현재 조건" value={`${modeLabel(strategy)} · ${horizonLabel(term)}`} />
        <Card label="평균 확률" value={`${avg(top, (item) => toNumber(item.probability ?? item.probabilityText ?? item.prob5d)).toFixed(1)}%`} />
        <Card label="평균 점수" value={`${avg(top, scoreOf).toFixed(1)}점`} />
      </div>

      {accuracy && <AccuracyPanel accuracy={accuracy} />}

      {/* ── 백테스트 9전략 매트릭스 ──────────────────────────────────── */}
      {valDash && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-200">9전략 백테스트 매트릭스</div>
            <div className="text-xs text-slate-500">완료 {valDash.summary?.totalCompleted ?? 0}건 · 대기 {valDash.summary?.totalPending ?? 0}건 · 전략평균 승률 {valDash.summary?.overallWinRate != null ? `${valDash.summary.overallWinRate}%` : "—"}</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800">
                  <th className="py-2 pr-4 text-left text-slate-500">전략</th>
                  {["단기", "스윙", "중기"].map((h) => <th key={h} className="px-3 py-2 text-center text-slate-500">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {(["conservative", "balanced", "aggressive"] as const).map((m) => (
                  <tr key={m} className={`border-b border-slate-800/60 ${m === strategy ? "bg-slate-800/30" : ""}`}>
                    <td className={`py-2.5 pr-4 font-semibold ${m === strategy ? "text-emerald-300" : "text-slate-300"}`}>{modeLabel(m)}</td>
                    {(["short", "swing", "mid"] as const).map((h) => {
                      const s = valDash.stats?.[`${m}_${h}`];
                      const wr = s?.winRate;
                      const isActive = m === strategy && h === term;
                      return (
                        <td key={h} className={`px-3 py-2.5 text-center ${isActive ? "ring-1 ring-inset ring-emerald-500/40" : ""}`}>
                          <div className={`text-base font-bold ${wr == null ? "text-slate-600" : wr >= 55 ? "text-emerald-300" : wr >= 45 ? "text-amber-300" : "text-red-300"}`}>
                            {wr != null ? `${wr}%` : "—"}
                          </div>
                          <div className="mt-0.5 text-slate-500">{s?.completed ? `${s.wins}/${s.completed}` : `대기 ${s?.pendingCount ?? 0}`}</div>
                          {s?.avgReturn != null && <div className={`text-[10px] font-mono ${s.avgReturn >= 0 ? "text-emerald-400" : "text-red-400"}`}>{s.avgReturn >= 0 ? "+" : ""}{s.avgReturn.toFixed(1)}%</div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── 수익률 분포 히스토그램 ────────────────────────────────────── */}
      {retDist && retDist.total > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold text-slate-200">수익률 분포 ({modeLabel(strategy)} · {horizonLabel(term)})</div>
            <div className="flex gap-3 text-xs">
              <span className="text-slate-400">체결 {retDist.executed}건</span>
              <span className="text-emerald-400">수익 {retDist.wins}건</span>
              <span className={retDist.wins / retDist.total >= 0.5 ? "font-bold text-emerald-300" : "font-bold text-amber-300"}>승률 {retDist.winRate}%</span>
            </div>
          </div>
          <div className="flex items-end gap-2 h-24">
            {retDist.buckets.map((b: any) => {
              const heightPct = retDist.maxCount > 0 ? (b.count / retDist.maxCount) * 100 : 0;
              const isPos = b.min >= 0;
              return (
                <div key={b.label} className="flex flex-1 flex-col items-center gap-1">
                  <span className="text-[10px] font-mono text-slate-400">{b.count > 0 ? b.count : ""}</span>
                  <div className="w-full rounded-t" style={{ height: `${Math.max(heightPct, b.count > 0 ? 8 : 0)}%`, background: isPos ? "#10b981" : "#ef4444", opacity: 0.7 + heightPct * 0.003 }} />
                  <span className="text-[9px] text-slate-500 whitespace-nowrap">{b.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {stats && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
          <div className="mb-3 text-xs font-semibold text-slate-400">상태별 분포</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.statusCounts).map(([status, count]) => count > 0 && (
              <span key={status} className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${STATUS_STYLE[status as ValidationStatus]}`}>
                {status} {count}
              </span>
            ))}
          </div>
          {stats.executedCount > 0 && (
            <div className="mt-3 grid grid-cols-3 gap-3 text-center text-xs">
              <div className="rounded-xl bg-slate-950/60 py-2">
                <div className="text-slate-500">체결 승률</div>
                <div className={`mt-1 font-mono font-bold ${stats.winRate >= 50 ? "text-emerald-300" : "text-amber-300"}`}>{stats.winRate.toFixed(1)}%</div>
              </div>
              <div className="rounded-xl bg-slate-950/60 py-2">
                <div className="text-slate-500">목표 / 손절</div>
                <div className="mt-1 font-mono font-bold"><span className="text-emerald-300">{stats.targetCount}</span> / <span className="text-red-300">{stats.stopCount}</span></div>
              </div>
              <div className="rounded-xl bg-slate-950/60 py-2">
                <div className="text-slate-500">평균 EV</div>
                <div className={`mt-1 font-mono font-bold ${stats.avgEv >= 0 ? "text-emerald-300" : "text-red-300"}`}>{stats.avgEv >= 0 ? "+" : ""}{stats.avgEv.toFixed(1)}%</div>
              </div>
            </div>
          )}
          {stats.executedCount === 0 && (
            <p className="mt-2 text-[11px] text-slate-600">체결/결과 데이터가 없습니다. decisionBucket이 "실행"인 종목이 없거나 outcome 필드가 채워지지 않았습니다.</p>
          )}
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60">
        <div className="border-b border-slate-800 px-4 py-3 sm:px-5 sm:py-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="text-xs text-slate-400 sm:text-sm">
              예측·추천 데이터를 종목 기준으로 통합합니다. 진입·손절·목표가가 없으면 추천값으로 자동 보강됩니다.
            </div>
            <div className="flex flex-wrap gap-2">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="종목 검색"
                className="w-36 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none sm:w-44"
              />
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as ValidationStatus | "all")}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none"
              >
                <option value="all">상태 전체</option>
                {(["검증대기", "미체결", "체결", "목표도달", "손절", "보류"] as ValidationStatus[]).map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* 모바일 카드 뷰 */}
        <div className="block sm:hidden divide-y divide-slate-800/60">
          {top.map((item: any, index: number) => {
            const score = scoreOf(item);
            const current = priceText(item, "current", priceText(item.recommendation || {}, "current", "확인"));
            const entry = priceText(item, "entry", priceText(item.recommendation || {}, "entry", current));
            const stop = priceText(item, "stop", priceText(item.recommendation || {}, "stop", "-"));
            const target = priceText(item, "target", priceText(item.recommendation || {}, "target", "-"));
            const evidence = touchEvidence(item.validation);
            const status = resolveStatus(item.validation || item);
            return (
              <div key={`m-${item.market}-${item.symbol}-${index}`} className="p-3 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold text-slate-100 text-sm">{displayName(item)}</div>
                    <div className="font-mono text-[10px] text-slate-500">{item.symbol} · {String(item.market || "").toUpperCase()}</div>
                  </div>
                  <span className={`shrink-0 rounded-lg border px-2 py-0.5 text-[10px] font-bold ${STATUS_STYLE[status]}`}>{status}</span>
                </div>
                <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                  <div className="rounded-lg bg-slate-950/60 px-2 py-1.5">
                    <div className="text-slate-500">확률 / 점수</div>
                    <div className="font-mono text-emerald-300">{probabilityText(item, "-")} / {score !== null ? `${score.toFixed(0)}` : "-"}</div>
                  </div>
                  <div className="rounded-lg bg-slate-950/60 px-2 py-1.5">
                    <div className="text-slate-500">현재가 / 진입가</div>
                    <div className="font-mono text-slate-200">{current} / <span className="text-sky-300">{entry}</span></div>
                  </div>
                  <div className="rounded-lg bg-slate-950/60 px-2 py-1.5">
                    <div className="text-slate-500">손절 / 목표</div>
                    <div className="font-mono"><span className="text-red-300">{stop}</span> / <span className="text-emerald-300">{target}</span></div>
                  </div>
                  <div className="rounded-lg bg-slate-950/60 px-2 py-1.5">
                    <div className="text-slate-500">터치 검증</div>
                    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-bold ${evidence.style}`}>{evidence.label}</span>
                  </div>
                </div>
                {evidence.detail && evidence.detail !== "결과 대기" && (
                  <div className="text-[10px] text-slate-500">{evidence.detail}</div>
                )}
              </div>
            );
          })}
          {top.length === 0 && <div className="px-4 py-10 text-center text-sm text-slate-500">예측 데이터가 없습니다.</div>}
        </div>

        {/* 데스크톱 테이블 뷰 */}
        <div className="hidden overflow-x-auto sm:block">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="border-b border-slate-800 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3">종목</th>
                <th className="px-4 py-3">확률/점수</th>
                <th className="px-4 py-3">현재가</th>
                <th className="px-4 py-3">진입가</th>
                <th className="px-4 py-3">손절가</th>
                <th className="px-4 py-3">목표가</th>
                <th className="px-4 py-3">터치 검증</th>
                <th className="px-4 py-3">상태</th>
              </tr>
            </thead>
            <tbody>
              {top.map((item: any, index: number) => {
                const score = scoreOf(item);
                const current = priceText(item, "current", priceText(item.recommendation || {}, "current", "가격 확인"));
                const entry = priceText(item, "entry", priceText(item.recommendation || {}, "entry", current));
                const stop = priceText(item, "stop", priceText(item.recommendation || {}, "stop", "손절 확인"));
                const target = priceText(item, "target", priceText(item.recommendation || {}, "target", "목표 확인"));
                const evidence = touchEvidence(item.validation);
                const status = resolveStatus(item.validation || item);
                return (
                  <tr key={`${item.market}-${item.symbol}-${index}`} className="border-b border-slate-800/60">
                    <td className="px-4 py-3"><div className="font-semibold text-slate-100">{displayName(item)}</div><div className="font-mono text-xs text-slate-500">{item.symbol} · {String(item.market || "").toUpperCase()}</div></td>
                    <td className="px-4 py-3 font-mono"><span className="text-emerald-300">{probabilityText(item, "-")}</span><span className="text-slate-600"> / </span><span className="text-cyan-300">{score !== null ? score.toFixed(1) : "-"}</span></td>
                    <td className="px-4 py-3 font-mono">{current}</td>
                    <td className="px-4 py-3 font-mono text-sky-300">{entry}</td>
                    <td className="px-4 py-3 font-mono text-red-300">{stop}</td>
                    <td className="px-4 py-3 font-mono text-emerald-300">{target}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-lg border px-2 py-1 text-[10px] font-bold ${evidence.style}`}>{evidence.label}</span>
                      <div className="mt-0.5 max-w-[180px] text-[10px] text-slate-500 truncate">{evidence.detail}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-lg border px-2 py-1 text-[10px] font-bold ${STATUS_STYLE[status]}`}>{status}</span>
                    </td>
                  </tr>
                );
              })}
              {top.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-slate-500">예측 데이터가 없습니다.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"><div className="text-sm text-slate-500">{label}</div><div className="mt-2 font-mono text-2xl font-bold text-slate-100">{value}</div></div>;
}

function StatBar({ label, value, color = "bg-blue-500" }: { label: string; value: number | null; color?: string }) {
  if (value === null || value === undefined) return null;
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono font-bold text-slate-200">{value.toFixed(1)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  );
}

function AccuracyPanel({ accuracy }: { accuracy: any }) {
  const from = accuracy.dateRange?.from?.slice(0, 10) ?? "";
  const to = accuracy.dateRange?.to?.slice(0, 10) ?? "";
  const buckets: any[] = accuracy.byConfidenceBucket ?? [];
  const dist: Record<string, number> = accuracy.virtualResultDist ?? {};
  const totalResult = Object.values(dist).reduce((a: number, b: unknown) => a + Number(b), 0);

  return (
    <div className="rounded-2xl border border-indigo-800/40 bg-indigo-950/20 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-indigo-300">과거 예측 성과</div>
          <div className="mt-0.5 text-xs text-slate-500">
            {from} ~ {to} · 검증 {accuracy.validatedRows?.toLocaleString()}건 / 전체 {accuracy.totalRows?.toLocaleString()}건
          </div>
          {to && to < new Date().toISOString().slice(0, 10) && (
            <div className="mt-0.5 text-[10px] text-amber-400/70">
              최신까지 반영하려면 실제 OHLCV 검증 파이프라인 재실행 필요
            </div>
          )}
        </div>
        <span className="rounded-lg border border-indigo-700/40 bg-indigo-900/30 px-2 py-1 text-[10px] text-indigo-300">
          3주 누적
        </span>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <StatBar label="방향 적중률" value={accuracy.directionHitRate} color="bg-emerald-500" />
          <StatBar label="시초가 예측 범위" value={accuracy.openInRangeRate} color="bg-blue-500" />
          <StatBar label="종가 예측 범위" value={accuracy.closeInRangeRate} color="bg-cyan-500" />
          <StatBar label="진입가 도달률" value={accuracy.entryTouchedRate} color="bg-amber-500" />
          <StatBar label="1차 목표 도달" value={accuracy.tp1TouchedRate} color="bg-violet-500" />
          <StatBar label="손절 도달" value={accuracy.stopTouchedRate} color="bg-red-500" />
        </div>

        <div className="space-y-4">
          {accuracy.avgVirtualReturn !== null && accuracy.avgVirtualReturn !== undefined && (
            <div className="rounded-xl border border-slate-700/50 bg-slate-900/60 p-3">
              <div className="text-xs text-slate-500">평균 가상수익률</div>
              <div className={`mt-1 font-mono text-xl font-bold ${accuracy.avgVirtualReturn >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                {accuracy.avgVirtualReturn >= 0 ? "+" : ""}{accuracy.avgVirtualReturn.toFixed(2)}%
              </div>
              {accuracy.positiveReturnRate !== null && (
                <div className="mt-1 text-xs text-slate-500">수익 거래 {accuracy.positiveReturnRate}%</div>
              )}
            </div>
          )}

          {buckets.length > 0 && (
            <div>
              <div className="mb-2 text-xs text-slate-500">신뢰도 구간별 방향 적중</div>
              <div className="space-y-1.5">
                {buckets.map((b: any) => (
                  <div key={b.bucket} className="flex items-center gap-2 text-xs">
                    <span className="w-16 shrink-0 text-slate-400">{b.bucket}</span>
                    <div className="flex-1 overflow-hidden rounded-full bg-slate-800 h-1.5">
                      <div className="h-full rounded-full bg-emerald-600" style={{ width: `${Math.min(100, b.directionHitRate)}%` }} />
                    </div>
                    <span className="w-12 text-right font-mono text-slate-300">{b.directionHitRate}%</span>
                    <span className="text-slate-600">({b.count})</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {totalResult > 0 && (
            <div>
              <div className="mb-2 text-xs text-slate-500">가상 결과 분포</div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(dist).map(([label, cnt]) => (
                  <span key={label} className="rounded border border-slate-700 bg-slate-800/60 px-2 py-0.5 text-[10px] text-slate-300">
                    {label} <span className="font-mono text-slate-400">{cnt}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
