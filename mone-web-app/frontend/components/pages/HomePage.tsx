"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone, type Horizon, type Mode } from "@/lib/api";
import {
  dedupeBySymbol,
  displayName,
  firstText,
  horizonLabel,
  modeLabel,
  priceText,
  probabilityText,
  sortByValue,
} from "@/lib/moneDisplay";

const MODES: Mode[] = ["conservative", "balanced", "aggressive"];
const HORIZONS: Horizon[] = ["short", "swing", "mid"];

type StrategyCell = {
  mode: Mode;
  horizon: Horizon;
  items: any[];
  count: number;
  status: string;
};

function Info({ label, value, accent = "text-slate-200" }: { label: string; value: any; accent?: string }) {
  return (
    <div>
      <div className="text-slate-500">{label}</div>
      <div className={`mt-1 font-mono ${accent}`}>{value}</div>
    </div>
  );
}

function Metric({ label, value, accent = false }: { label: string; value: any; accent?: boolean }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-2 text-xl font-bold ${accent ? "text-emerald-400" : "text-slate-100"}`}>{value}</div>
    </div>
  );
}

function cellSourceBadge(cell: StrategyCell) {
  const items = cell.items || [];
  if (!items.length) return { label: "후보 없음", tone: "border-slate-700 bg-slate-800/70 text-slate-400" };

  const mismatched = items.some((item) => {
    const sourceMode = String(item.sourceMode || item.mode || "").toLowerCase();
    const sourceHorizon = String(item.sourceHorizon || item.horizon || "").toLowerCase();
    const requestedMode = String(cell.mode).toLowerCase();
    const requestedHorizon = String(cell.horizon).toLowerCase();
    return (sourceMode && sourceMode !== requestedMode) || (sourceHorizon && sourceHorizon !== requestedHorizon);
  });

  const fallback = items.some((item) => String(item.sourceStatus || "").toUpperCase() === "FALLBACK");
  if (mismatched || fallback) return { label: "동일 소스 확인", tone: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
  return { label: "전략 소스 일치", tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
}

function avgProbability(items: any[]) {
  const nums = items
    .map((item) => Number(String(firstText(item.probabilityText, item.prob5dText, "")).replace(/[^0-9.-]/g, "")))
    .filter((n) => Number.isFinite(n) && n > 0);
  if (!nums.length) return "-";
  return `${(nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(1)}%`;
}

function StrategyCellCard({ cell }: { cell: StrategyCell }) {
  const badge = cellSourceBadge(cell);
  const topItems = (cell.items || []).slice(0, 3);

  return (
    <div className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-950/50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-100">
            {modeLabel(cell.mode)} · {horizonLabel(cell.horizon)}
          </div>
          <div className="mt-1 text-xs text-slate-500">후보 {cell.count || topItems.length}개 · 평균 {avgProbability(topItems)}</div>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-1 text-[11px] ${badge.tone}`}>{badge.label}</span>
      </div>

      {topItems.length === 0 ? (
        <div className="mt-8 rounded-xl border border-dashed border-slate-800 p-4 text-center text-sm text-slate-500">표시할 후보가 없습니다.</div>
      ) : (
        <div className="mt-4 space-y-2">
          {topItems.map((item) => (
            <div key={`${cell.mode}-${cell.horizon}-${item.market}-${item.symbol}`} className="rounded-xl bg-slate-900/70 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-100">{displayName(item)}</div>
                  <div className="mt-0.5 font-mono text-[11px] text-slate-500">{item.symbol} · {String(item.market || "").toUpperCase()}</div>
                </div>
                <div className="font-mono text-xs text-emerald-300">{probabilityText(item, "확률 확인")}</div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                <Info label="진입" value={priceText(item, "entry", "-")} accent="text-sky-300" />
                <Info label="손절" value={priceText(item, "stop", "-")} accent="text-red-300" />
                <Info label="목표" value={priceText(item, "target", "-")} accent="text-emerald-300" />
                <Info label="현재" value={priceText(item, "current", "-")} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StrategyMatrix({ cells, loading }: { cells: StrategyCell[]; loading: boolean }) {
  const byKey = new Map(cells.map((cell) => [`${cell.mode}-${cell.horizon}`, cell]));
  const allSymbols = cells.map((cell) => (cell.items || []).map((item) => item.symbol).join("|"));
  const uniqueSymbolSets = new Set(allSymbols.filter(Boolean));
  const allSame = cells.length > 1 && uniqueSymbolSets.size === 1;

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="mb-4 flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">전략 × 기간 한눈에 보기</h2>
          <p className="mt-1 text-sm text-slate-500">
            보수·균형·공격과 단기·스윙·중기 조합을 같은 화면에서 비교합니다. 현재가는 같아도 되지만, 후보·진입·손절·목표·확률은 조합별로 달라질 수 있습니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-slate-700 px-3 py-1 text-slate-400">{loading ? "불러오는 중" : "9개 조합 비교"}</span>
          {allSame ? <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-amber-300">후보 조합 동일 가능성</span> : null}
        </div>
      </div>

      <div className="mb-3 hidden grid-cols-[120px_repeat(3,minmax(0,1fr))] gap-3 text-xs text-slate-500 xl:grid">
        <div />
        {HORIZONS.map((horizon) => (
          <div key={horizon} className="rounded-xl bg-slate-950/60 px-3 py-2 text-center font-semibold text-slate-300">{horizonLabel(horizon)}</div>
        ))}
      </div>

      <div className="space-y-3">
        {MODES.map((mode) => (
          <div key={mode} className="grid grid-cols-1 gap-3 xl:grid-cols-[120px_repeat(3,minmax(0,1fr))]">
            <div className="flex items-center rounded-2xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm font-semibold text-slate-100 xl:justify-center">
              {modeLabel(mode)}
            </div>
            {HORIZONS.map((horizon) => {
              const cell = byKey.get(`${mode}-${horizon}`) || { mode, horizon, items: [], count: 0, status: "NO_DATA" };
              return <StrategyCellCard key={`${mode}-${horizon}`} cell={cell} />;
            })}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function HomePage() {
  const [holdings, setHoldings] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [matrix, setMatrix] = useState<StrategyCell[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const matrixRequests = MODES.flatMap((mode) =>
        HORIZONS.map(async (horizon) => {
          const result = await mone.recommendations({ market: "all", mode, horizon, limit: 12 });
          const items = dedupeBySymbol(Array.isArray(result.items) ? result.items : []).slice(0, 3);
          return {
            mode,
            horizon,
            items,
            count: Number(result.count || items.length || 0),
            status: String(result.status || "OK"),
          } satisfies StrategyCell;
        })
      );

      const [h, r, matrixResult] = await Promise.all([
        mone.holdingsClean({ market: "all", limit: 50 }),
        mone.recommendations({ market: "all", mode: "balanced", horizon: "swing", limit: 20 }),
        Promise.all(matrixRequests),
      ]);

      setHoldings(dedupeBySymbol(Array.isArray(h.items) ? h.items : []));
      setSummary(h.summary || null);
      setRecommendations(dedupeBySymbol(Array.isArray(r.items) ? r.items : []).slice(0, 5));
      setMatrix(matrixResult);
    } catch {
      setHoldings([]);
      setSummary(null);
      setRecommendations([]);
      setMatrix([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const topHoldings = useMemo(() => sortByValue(holdings).slice(0, 5), [holdings]);
  const riskCount = useMemo(() => holdings.filter((item) => ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""))).length, [holdings]);
  const missingCount = useMemo(() => holdings.filter((item) => Array.isArray(item.missingFields) && item.missingFields.length > 0).length, [holdings]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">시장 홈</h1>
          <p className="mt-1 text-sm text-slate-400">보유요약, 전략별 후보, 위험 신호를 한 화면에서 확인합니다.</p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric label="보유종목" value={`${holdings.length}개`} />
        <Metric label="위험/주의 종목" value={summary?.riskCount ?? riskCount} />
        <Metric label="데이터 누락" value={summary?.missingCount ?? missingCount} />
        <Metric label="총 평가손익" value={summary?.totalPnlText ?? "0"} accent />
      </div>

      <StrategyMatrix cells={matrix} loading={loading} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">주요 보유종목</h2>
              <p className="text-sm text-slate-500">보유종목 {holdings.length}개 중 평가금액 기준 상위 5개입니다.</p>
            </div>
            <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">{loading ? "불러오는 중" : "상위 5개"}</span>
          </div>

          {loading ? (
            <div className="py-12 text-center text-slate-500">보유종목을 불러오는 중...</div>
          ) : topHoldings.length === 0 ? (
            <div className="py-12 text-center text-slate-500">표시할 보유종목이 없습니다.</div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {topHoldings.map((item) => {
                const change = firstText(item.changePctText, "변동률 확인 필요");
                return (
                  <div key={`${item.market}-${item.symbol}`} className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-slate-100">{displayName(item)}</div>
                        <div className="mt-1 font-mono text-xs text-slate-500">{item.symbol} · {String(item.market || "").toUpperCase()}</div>
                      </div>
                      <span className="rounded-full border border-slate-700 px-2 py-1 text-xs text-slate-400">{item.riskStatus || "정상"}</span>
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                      <Info label="수량" value={item.quantity ?? "-"} />
                      <Info label="현재가" value={priceText(item, "current", "가격 확인 필요")} />
                      <Info label="평가손익" value={firstText(item.pnlText, "0")} accent={String(item.pnlText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"} />
                      <Info label="등락률" value={change} accent={String(change).startsWith("-") ? "text-red-300" : "text-emerald-300"} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-100">균형·스윙 핵심 후보</h2>
            <p className="text-sm text-slate-500">기본 조건의 상위 후보입니다. 전체 비교는 위 전략×기간 매트릭스에서 확인합니다.</p>
          </div>
          {recommendations.length === 0 ? (
            <div className="py-12 text-center text-slate-500">추천 후보를 불러오는 중이거나 표시할 후보가 없습니다.</div>
          ) : (
            <div className="space-y-3">
              {recommendations.map((item) => (
                <div key={`${item.market}-${item.symbol}`} className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-slate-100">{displayName(item)}</div>
                      <div className="mt-1 font-mono text-xs text-slate-500">{item.symbol} · {String(item.market).toUpperCase()}</div>
                    </div>
                    <div className="font-mono text-sm text-emerald-300">{probabilityText(item, "확률 확인")}</div>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                    <Info label="현재가" value={priceText(item, "current", "가격 확인")} />
                    <Info label="진입가" value={priceText(item, "entry", "진입 확인")} accent="text-sky-300" />
                    <Info label="손절가" value={priceText(item, "stop", "손절 확인")} accent="text-red-300" />
                    <Info label="목표가" value={priceText(item, "target", "목표 확인")} accent="text-emerald-300" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
