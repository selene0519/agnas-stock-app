"use client";

import { useEffect, useMemo, useState } from "react";
import { Pencil, RefreshCw, Save, Trash2, X } from "lucide-react";
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

type EditableHolding = {
  market: string;
  symbol: string;
  name: string;
  quantity: string;
  avgPrice: string;
};

function holdingKey(item: any) {
  return `${String(item.market || "kr").toLowerCase()}-${String(item.symbol || "").trim()}`;
}

function normalizeEditableHolding(item: any): EditableHolding {
  const market = String(item.market || "kr").toLowerCase();
  const symbol = market === "kr" ? String(item.symbol || "").replace(/[^0-9]/g, "").padStart(6, "0").slice(-6) : String(item.symbol || "").trim().toUpperCase();
  return {
    market,
    symbol,
    name: String(item.name || item.companyName || item.displayName || "").trim(),
    quantity: String(item.quantity ?? item.qty ?? ""),
    avgPrice: String(item.avgPrice ?? item.avg_price ?? item.averagePrice ?? item.avgPriceText ?? "").replace(/[^0-9.]/g, ""),
  };
}

function normalizeHoldingForSave(item: EditableHolding) {
  const market = String(item.market || "kr").toLowerCase();
  const symbol = market === "kr" ? String(item.symbol || "").replace(/[^0-9]/g, "").padStart(6, "0").slice(-6) : String(item.symbol || "").trim().toUpperCase();
  return {
    market,
    symbol,
    name: item.name,
    quantity: Number(String(item.quantity).replace(/,/g, "")),
    avgPrice: Number(String(item.avgPrice).replace(/,/g, "")),
  };
}

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
  const adjusted = items.some((item) =>
    Array.isArray(item.computedFields) && item.computedFields.some((field: string) => String(field).includes("strategy_horizon"))
  );
  if (mismatched || fallback) return { label: "대체 소스 조정", tone: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
  if (adjusted) return { label: "전략 기준 조정", tone: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300" };
  return { label: "원본 소스 일치", tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
}

function avgProbability(items: any[]) {
  const nums = items
    .map((item) => Number(String(firstText(item.probabilityText, item.prob5dText, "")).replace(/[^0-9.-]/g, "")))
    .filter((n) => Number.isFinite(n) && n > 0);
  if (!nums.length) return "-";
  return `${(nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(1)}%`;
}

function ScoreBar({ label, value, color = "bg-emerald-500" }: { label: string; value: number | null | undefined; color?: string }) {
  if (value == null) return null;
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div>
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>{label}</span>
        <span className="font-mono text-slate-400">{pct.toFixed(0)}</span>
      </div>
      <div className="mt-0.5 h-1 w-full rounded-full bg-slate-800">
        <div className={`h-1 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
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
          {topItems.map((item) => {
            const ev = item.expectedValue ?? item.ev;
            const evText = typeof ev === "number" ? (ev >= 0 ? `EV +${ev.toFixed(1)}%` : `EV ${ev.toFixed(1)}%`) : null;
            const evColor = typeof ev === "number" ? (ev >= 1 ? "text-emerald-300" : ev >= 0 ? "text-slate-400" : "text-red-300") : "text-slate-500";
            const finalScore = item.finalScore ?? item.quantScore;
            return (
              <div key={`${cell.mode}-${cell.horizon}-${item.market}-${item.symbol}`} className="rounded-xl bg-slate-900/70 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-slate-100">{displayName(item)}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-slate-500">{item.symbol} · {String(item.market || "").toUpperCase()}</div>
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <div className="font-mono text-xs text-emerald-300">{probabilityText(item, "확률 확인")}</div>
                    {evText && <div className={`font-mono text-[10px] ${evColor}`}>{evText}</div>}
                  </div>
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                  <Info label="진입" value={priceText(item, "entry", "-")} accent="text-sky-300" />
                  <Info label="손절" value={priceText(item, "stop", "-")} accent="text-red-300" />
                  <Info label="목표" value={priceText(item, "target", "-")} accent="text-emerald-300" />
                  <Info label="현재" value={priceText(item, "current", "-")} />
                </div>

                {/* 세부 점수 바 */}
                {finalScore != null && (
                  <div className="mt-3 space-y-1">
                    {cell.mode === "conservative" && (
                      <>
                        <ScoreBar label="리스크 안정성" value={item.riskScore} color="bg-sky-500" />
                        <ScoreBar label="진입 접근성" value={item.entryScore} color="bg-emerald-500" />
                        <ScoreBar label="손익비" value={item.rrScore} color="bg-violet-500" />
                      </>
                    )}
                    {cell.mode === "balanced" && (
                      <>
                        <ScoreBar label="상승 여력" value={item.upsideScore} color="bg-emerald-500" />
                        <ScoreBar label="리스크" value={item.riskScore} color="bg-sky-500" />
                        <ScoreBar label="손익비" value={item.rrScore} color="bg-violet-500" />
                      </>
                    )}
                    {cell.mode === "aggressive" && (
                      <>
                        <ScoreBar label="상승 여력" value={item.upsideScore} color="bg-orange-500" />
                        <ScoreBar label="모멘텀" value={item.momentumScore} color="bg-yellow-500" />
                        <ScoreBar label="손익비" value={item.rrScore} color="bg-violet-500" />
                      </>
                    )}
                    <div className="flex items-center justify-between pt-0.5">
                      <span className="text-[10px] text-slate-600">종합점수</span>
                      <span className="font-mono text-[10px] text-slate-300">{finalScore.toFixed(0)}점</span>
                    </div>
                  </div>
                )}

                {Array.isArray(item.strategyTags) && item.strategyTags.length > 0 ? (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {item.strategyTags.slice(0, 3).map((tag: string, tagIndex: number) => (
                      <span key={tag} className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-200">
                        {Array.isArray(item.strategyTagLabels) ? item.strategyTagLabels[tagIndex] || tag : tag}
                      </span>
                    ))}
                    {Array.isArray(item.priceBandWarnings) && item.priceBandWarnings.length > 0 && (
                      <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                        가격대 확인
                      </span>
                    )}
                  </div>
                ) : item.candidateTypeLabel ? (
                  <div className="mt-3">
                    <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-200">
                      {item.candidateTypeLabel}
                    </span>
                  </div>
                ) : null}
              </div>
            );
          })}
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


type MarketChoice = "auto" | "kr" | "us";

function kstNowParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value || 0);
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour"), minute: get("minute") };
}

function getDefaultMarketBySession(now = new Date()): "kr" | "us" {
  const { hour, minute } = kstNowParts(now);
  const total = hour * 60 + minute;
  // KST 07:00~17:00은 국장, 그 외 시간은 미장 기준으로 시작합니다.
  if (total >= 7 * 60 && total < 17 * 60) return "kr";
  return "us";
}

function getMarketSessionStatus(market: "kr" | "us", now = new Date()) {
  const { hour, minute } = kstNowParts(now);
  const total = hour * 60 + minute;
  if (market === "kr") {
    if (total >= 9 * 60 && total <= 15 * 60 + 30) return "장중";
    if (total > 15 * 60 + 30) return "장마감";
    return "장전";
  }
  // 우선 KST 기준 단순 버전. 서머타임은 이후 거래소 캘린더와 연결해 고도화.
  if (total >= 22 * 60 + 30 || total <= 5 * 60) return "장중";
  if (total > 15 * 60 + 30 && total < 22 * 60 + 30) return "개장 전";
  return "마감 후";
}

function marketChoiceInitial(): MarketChoice {
  if (typeof window === "undefined") return "auto";
  const saved = window.localStorage.getItem("mone:selectedMarketMode");
  return saved === "kr" || saved === "us" || saved === "auto" ? saved : "auto";
}

function marketLabel(market: "kr" | "us") {
  return market === "kr" ? "국장" : "미장";
}

export default function HomePage() {
  const [holdings, setHoldings] = useState<any[]>([]);
  const [editableHoldings, setEditableHoldings] = useState<EditableHolding[]>([]);
  const [editingHoldingKey, setEditingHoldingKey] = useState<string | null>(null);
  const [holdingDraft, setHoldingDraft] = useState<EditableHolding | null>(null);
  const [holdingMessage, setHoldingMessage] = useState("");
  const [holdingSaving, setHoldingSaving] = useState(false);
  const [summary, setSummary] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [matrix, setMatrix] = useState<StrategyCell[]>([]);
  const [loading, setLoading] = useState(true);
  const [marketChoice, setMarketChoice] = useState<MarketChoice>(marketChoiceInitial);
  const selectedMarket = marketChoice === "auto" ? getDefaultMarketBySession() : marketChoice;
  const sessionStatus = getMarketSessionStatus(selectedMarket);

  function updateMarketChoice(next: MarketChoice) {
    setMarketChoice(next);
    if (typeof window !== "undefined") window.localStorage.setItem("mone:selectedMarketMode", next);
  }

  async function load() {
    setLoading(true);
    try {
      const matrixRequests = MODES.flatMap((mode) =>
        HORIZONS.map(async (horizon) => {
          const result = await mone.recommendations({ market: selectedMarket, mode, horizon, limit: 12 });
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

      const [h, r, matrixResult, editable] = await Promise.all([
        mone.holdingsClean({ market: selectedMarket, limit: 50 }),
        mone.recommendations({ market: selectedMarket, mode: "balanced", horizon: "swing", limit: 20 }),
        Promise.all(matrixRequests),
        mone.holdingsEdit({ market: selectedMarket }),
      ]);

      setHoldings(dedupeBySymbol(Array.isArray(h.items) ? h.items : []));
      setEditableHoldings(Array.isArray(editable.items) ? editable.items.map(normalizeEditableHolding) : []);
      setSummary(h.summary || null);
      setRecommendations(dedupeBySymbol(Array.isArray(r.items) ? r.items : []).slice(0, 5));
      setMatrix(matrixResult);
    } catch {
      setHoldings([]);
      setEditableHoldings([]);
      setSummary(null);
      setRecommendations([]);
      setMatrix([]);
    } finally {
      setLoading(false);
    }
  }

  function startEditHolding(item: any) {
    const key = holdingKey(item);
    const existing = editableHoldings.find((row) => holdingKey(row) === key);
    const draft = existing || normalizeEditableHolding({
      ...item,
      avgPrice: item.avgPrice || item.avgPriceText || item.purchasePrice || item.entryPrice || "",
    });
    setEditingHoldingKey(key);
    setHoldingDraft(draft);
    setHoldingMessage("");
  }

  function cancelEditHolding() {
    setEditingHoldingKey(null);
    setHoldingDraft(null);
  }

  async function saveEditableHoldings(nextRows: EditableHolding[], message: string) {
    setHoldingSaving(true);
    setHoldingMessage("");
    try {
      const items = nextRows.map(normalizeHoldingForSave);
      const invalid = items.find((item) => !item.symbol || item.quantity <= 0 || item.avgPrice <= 0 || !Number.isFinite(item.quantity) || !Number.isFinite(item.avgPrice));
      if (invalid) {
        setHoldingMessage("종목코드, 수량, 평균단가를 확인해 주세요.");
        return;
      }
      const result = await mone.saveHoldingsEdit({ items });
      if (result?.status === "ERROR") throw new Error(result.error || "보유종목 저장 실패");
      setHoldingMessage(message);
      cancelEditHolding();
      await load();
    } catch (error) {
      setHoldingMessage(`저장 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setHoldingSaving(false);
    }
  }

  async function saveHoldingDraft() {
    if (!holdingDraft) return;
    const key = holdingKey(holdingDraft);
    const exists = editableHoldings.some((row) => holdingKey(row) === key);
    const nextRows = exists
      ? editableHoldings.map((row) => (holdingKey(row) === key ? holdingDraft : row))
      : [...editableHoldings, holdingDraft];
    await saveEditableHoldings(nextRows, `${holdingDraft.name || holdingDraft.symbol} 보유종목을 수정했습니다.`);
  }

  async function deleteHolding(item: any) {
    const key = holdingKey(item);
    const name = item.name || item.symbol;
    const nextRows = editableHoldings.filter((row) => holdingKey(row) !== key);
    await saveEditableHoldings(nextRows, `${name} 보유종목을 삭제했습니다.`);
  }

  useEffect(() => {
    load();
  }, [selectedMarket]);

  const topHoldings = useMemo(() => sortByValue(holdings).slice(0, 5), [holdings]);
  const riskCount = useMemo(() => holdings.filter((item) => ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""))).length, [holdings]);
  const missingCount = useMemo(() => holdings.filter((item) => Array.isArray(item.missingFields) && item.missingFields.length > 0).length, [holdings]);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">시장 홈</h1>
          <p className="mt-1 text-sm text-slate-400">보유요약, 전략별 후보, 위험 신호를 한 화면에서 확인합니다. 국장 마감 후에는 자동으로 미장 기준을 우선 표시합니다.</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex flex-wrap justify-end gap-2">
            {(["auto", "kr", "us"] as MarketChoice[]).map((choice) => {
              const active = marketChoice === choice;
              const label = choice === "auto" ? "자동" : marketLabel(choice);
              return (
                <button
                  key={choice}
                  type="button"
                  onClick={() => updateMarketChoice(choice)}
                  className={`rounded-xl px-3 py-2 text-xs font-semibold ${active ? "bg-blue-600 text-white" : "border border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"}`}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <div className="text-xs text-slate-500">
            {marketChoice === "auto" ? "자동 선택" : "수동 선택"}: {marketLabel(selectedMarket)} · {sessionStatus}
          </div>
          <button onClick={load} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            새로고침
          </button>
        </div>
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

          {holdingMessage ? <div className="mb-3 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300">{holdingMessage}</div> : null}

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
                      <div className="flex flex-col items-end gap-2">
                        <span className="rounded-full border border-slate-700 px-2 py-1 text-xs text-slate-400">{item.riskStatus || "정상"}</span>
                        <div className="flex gap-1">
                          <button
                            type="button"
                            onClick={() => startEditHolding(item)}
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-300 hover:bg-slate-800"
                          >
                            <Pencil size={12} /> 수정
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteHolding(item)}
                            disabled={holdingSaving}
                            className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/10 disabled:opacity-50"
                          >
                            <Trash2 size={12} /> 삭제
                          </button>
                        </div>
                      </div>
                    </div>

                    {editingHoldingKey === holdingKey(item) && holdingDraft ? (
                      <div className="mt-4 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3">
                        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                          <label className="text-xs text-slate-500">
                            종목명
                            <input
                              value={holdingDraft.name}
                              onChange={(event) => setHoldingDraft({ ...holdingDraft, name: event.target.value })}
                              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-100"
                            />
                          </label>
                          <label className="text-xs text-slate-500">
                            수량
                            <input
                              type="number"
                              value={holdingDraft.quantity}
                              onChange={(event) => setHoldingDraft({ ...holdingDraft, quantity: event.target.value })}
                              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-100"
                            />
                          </label>
                          <label className="text-xs text-slate-500">
                            평균단가
                            <input
                              type="number"
                              value={holdingDraft.avgPrice}
                              onChange={(event) => setHoldingDraft({ ...holdingDraft, avgPrice: event.target.value })}
                              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-100"
                            />
                          </label>
                        </div>
                        <div className="mt-3 flex flex-wrap justify-end gap-2">
                          <button
                            type="button"
                            onClick={cancelEditHolding}
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800"
                          >
                            <X size={13} /> 취소
                          </button>
                          <button
                            type="button"
                            onClick={saveHoldingDraft}
                            disabled={holdingSaving}
                            className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-50"
                          >
                            <Save size={13} /> 저장
                          </button>
                        </div>
                      </div>
                    ) : null}

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
