"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, TrendingUp, Clock, Eye, AlertTriangle } from "lucide-react";
import { mone, type Horizon, type Mode } from "@/lib/api";
import {
  dedupeBySymbol,
  displayName,
  firstText,
  horizonLabel,
  modeLabel,
  priceText,
  probabilityText,
} from "@/lib/moneDisplay";

const MODES: Mode[] = ["conservative", "balanced", "aggressive"];
const HORIZONS: Horizon[] = ["short", "swing", "mid"];

type StrategyCell = { mode: Mode; horizon: Horizon; items: any[]; count: number; status: string };
type MarketChoice = "auto" | "kr" | "us";

// ── 시간대 유틸
function kstNowParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(now);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value || 0);
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour"), minute: get("minute") };
}

function getDefaultMarketBySession(now = new Date()): "kr" | "us" {
  const { hour, minute } = kstNowParts(now);
  const t = hour * 60 + minute;
  return (t >= 7 * 60 && t < 17 * 60) ? "kr" : "us";
}

function getMarketSessionStatus(market: "kr" | "us", now = new Date()) {
  const { hour, minute } = kstNowParts(now);
  const t = hour * 60 + minute;
  if (market === "kr") {
    if (t >= 9 * 60 && t <= 15 * 60 + 30) return "장중";
    if (t > 15 * 60 + 30) return "장마감";
    return "장전";
  }
  if (t >= 22 * 60 + 30 || t <= 5 * 60) return "장중";
  if (t > 15 * 60 + 30 && t < 22 * 60 + 30) return "개장 전";
  return "마감 후";
}

// ── 점수 바
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

// ── 전략 태그 렌더
function TagChips({ item }: { item: any }) {
  const surgeLabel = String(item.surgeLabel || "");
  const tags = surgeLabel !== "판단 대기" && surgeLabel
    ? surgeLabel.split("|").map((t) => t.trim()).filter(Boolean)
    : [];

  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {item.evNegative && <span className="rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[10px] text-red-300">EV음수</span>}
      {item.maConvergence && <span className="rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] text-violet-300">이격도수렴</span>}
      {item.isUndervaluedGrowth === "True" && <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-300">저평가성장주</span>}
      {item.supplySignal === "STRONG_BUY" && <span className="rounded-full border border-blue-400/40 bg-blue-400/10 px-2 py-0.5 text-[10px] text-blue-300">기관+외국인</span>}
      {item.supplySignal === "INST_BUY" && <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[10px] text-sky-300">기관매수</span>}
      {tags.filter((t) => !["저평가성장주", "공시주의"].includes(t)).slice(0, 2).map((t) => (
        <span key={t} className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-200">{t}</span>
      ))}
      {Number(item.newsRiskPenalty) >= 10 && <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2 py-0.5 text-[10px] text-orange-300">공시주의</span>}
    </div>
  );
}

// ── 오늘 진입 카드 (상세)
function TodayEntryCard({ item, rank }: { item: any; rank: number }) {
  const ev = Number(item.expectedValue || 0);
  const score = Number(item.finalScore || 0);
  const mode = String(item.mode || item._mode || "");
  const horizon = String(item.horizon || item._horizon || "");

  return (
    <div className="relative rounded-2xl border border-emerald-800/50 bg-gradient-to-br from-emerald-950/30 to-slate-950 p-4">
      <div className="absolute -top-2 -left-2 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-[11px] font-bold text-white">{rank}</div>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold text-slate-100">{displayName(item)}</div>
          <div className="mt-0.5 text-[11px] text-slate-500">{item.symbol} · {modeLabel(mode as Mode)} · {horizonLabel(horizon as Horizon)}</div>
        </div>
        <div className="shrink-0 text-right">
          <div className={`font-mono text-sm font-bold ${ev >= 2 ? "text-emerald-300" : ev >= 0 ? "text-slate-300" : "text-red-300"}`}>
            EV {ev >= 0 ? "+" : ""}{ev.toFixed(1)}%
          </div>
          <div className="text-[11px] text-slate-500">종합 {score.toFixed(0)}점</div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-4 gap-2 text-[11px]">
        <div><div className="text-slate-500">현재가</div><div className="font-mono text-slate-200">{priceText(item, "current", "-")}</div></div>
        <div><div className="text-slate-500">진입가</div><div className="font-mono text-sky-300">{priceText(item, "entry", "-")}</div></div>
        <div><div className="text-slate-500">손절가</div><div className="font-mono text-red-300">{priceText(item, "stop", "-")}</div></div>
        <div><div className="text-slate-500">목표가</div><div className="font-mono text-emerald-300">{priceText(item, "target", "-")}</div></div>
      </div>

      <div className="mt-3 space-y-1">
        {mode === "conservative" && <>
          <ScoreBar label="리스크 안정성" value={item.riskScore} color="bg-sky-500" />
          <ScoreBar label="진입 접근성" value={item.entryScore} color="bg-emerald-500" />
        </>}
        {mode === "balanced" && <>
          <ScoreBar label="상승 여력" value={item.upsideScore} color="bg-emerald-500" />
          <ScoreBar label="리스크" value={item.riskScore} color="bg-sky-500" />
        </>}
        {mode === "aggressive" && <>
          <ScoreBar label="상승 여력" value={item.upsideScore} color="bg-orange-500" />
          <ScoreBar label="모멘텀" value={item.momentumScore} color="bg-yellow-500" />
        </>}
        <ScoreBar label="손익비" value={item.rrScore} color="bg-violet-500" />
      </div>

      <TagChips item={item} />

      {item.timingLabel && (
        <div className={`mt-2 rounded-lg px-2 py-1 text-[10px] ${
          item.timingLabel === "돌파 진입" ? "bg-orange-950/40 text-orange-400"
          : item.timingLabel === "스퀴즈 돌파" ? "bg-violet-950/40 text-violet-400"
          : item.timingLabel === "수렴 진입" ? "bg-cyan-950/40 text-cyan-400"
          : "bg-emerald-950/40 text-emerald-400"
        }`}>
          {item.timingLabel === "돌파 진입" ? "🚀" : item.timingLabel === "스퀴즈 돌파" ? "💥" : "✓"}{" "}
          {item.timingReason || item.timingLabel}
        </div>
      )}
    </div>
  );
}

// ── 대기 관찰 카드 (간결)
function WatchCard({ item }: { item: any }) {
  const mode = String(item.mode || item._mode || "");
  const horizon = String(item.horizon || item._horizon || "");
  const timingLabel = String(item.timingLabel || "대기");
  const timingReason = String(item.timingReason || "");
  const expectedEntry = String(item.expectedEntryPrice || "");

  const timingColor =
    timingLabel.includes("1~2일") ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
    : timingLabel.includes("3~5일") ? "border-orange-500/40 bg-orange-500/10 text-orange-300"
    : timingLabel.includes("다음 주") ? "border-slate-600 bg-slate-800/60 text-slate-400"
    : "border-cyan-500/30 bg-cyan-500/10 text-cyan-300";

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <span className="font-semibold text-slate-200">{displayName(item)}</span>
          <span className="ml-2 text-[10px] text-slate-500">{item.symbol} · {modeLabel(mode as Mode)} · {horizonLabel(horizon as Horizon)}</span>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${timingColor}`}>{timingLabel}</span>
      </div>
      {timingReason && <div className="mt-1 text-[11px] text-slate-400">{timingReason}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px]">
        <span className="text-slate-500">현재 <span className="font-mono text-slate-300">{priceText(item, "current", "-")}</span></span>
        {expectedEntry && <span className="text-slate-500">예상 진입 <span className="font-mono text-sky-400">{expectedEntry}</span></span>}
        <span className="text-slate-500">목표 <span className="font-mono text-emerald-400">{priceText(item, "target", "-")}</span></span>
        <span className={`font-mono ${Number(item.expectedValue || 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
          EV {Number(item.expectedValue || 0) >= 0 ? "+" : ""}{Number(item.expectedValue || 0).toFixed(1)}%
        </span>
      </div>
      <TagChips item={item} />
    </div>
  );
}

// ── 3×3 매트릭스 셀 (간결 버전)
function MatrixCell({ cell }: { cell: StrategyCell }) {
  const top = (cell.items || []).slice(0, 3);
  const todayIn = top.filter((i) => i.decisionBucket === "오늘 진입");
  const watching = top.filter((i) => i.decisionBucket === "대기 관찰");

  return (
    <div className="min-h-[140px] rounded-2xl border border-slate-800 bg-slate-950/50 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-300">{modeLabel(cell.mode)} · {horizonLabel(cell.horizon)}</span>
        <span className="text-[10px] text-slate-500">{cell.count}개</span>
      </div>
      {top.length === 0 ? (
        <div className="py-4 text-center text-[11px] text-slate-600">후보 없음</div>
      ) : (
        <div className="space-y-1.5">
          {top.map((item) => {
            const isToday = item.decisionBucket === "오늘 진입";
            const isWatch = item.decisionBucket === "대기 관찰";
            const ev = Number(item.expectedValue || 0);
            return (
              <div key={item.symbol} className={`flex items-center justify-between rounded-lg px-2 py-1.5 ${
                isToday ? "bg-emerald-950/40 border border-emerald-800/30" : isWatch ? "bg-slate-900/60" : "bg-slate-950/50 opacity-60"
              }`}>
                <div className="min-w-0 flex-1">
                  <span className="truncate text-[11px] font-medium text-slate-200">{displayName(item)}</span>
                  {isToday && <span className="ml-1 rounded bg-emerald-700/50 px-1 text-[9px] text-emerald-300">진입</span>}
                  {isWatch && item.timingLabel && <span className="ml-1 rounded bg-amber-900/40 px-1 text-[9px] text-amber-400">{item.timingLabel}</span>}
                </div>
                <span className={`font-mono text-[10px] ${ev >= 1 ? "text-emerald-400" : ev >= 0 ? "text-slate-400" : "text-red-400"}`}>
                  {ev >= 0 ? "+" : ""}{ev.toFixed(1)}%
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── 메인 컴포넌트
export default function HomePage() {
  const [allItems, setAllItems] = useState<any[]>([]);
  const [matrix, setMatrix] = useState<StrategyCell[]>([]);
  const [holdings, setHoldings] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [marketRegime, setMarketRegime] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [marketChoice, setMarketChoice] = useState<MarketChoice>("auto");
  const [clientReady, setClientReady] = useState(false);
  const [clock, setClock] = useState<Date | null>(null);
  const sessionClock = clock || new Date();
  const selectedMarket = marketChoice === "auto" ? (clientReady ? getDefaultMarketBySession(sessionClock) : "kr") : marketChoice;
  const sessionStatus = clientReady ? getMarketSessionStatus(selectedMarket, sessionClock) : "확인 중";
  const marketChoiceLabel = clientReady && marketChoice !== "auto" ? "수동" : "자동";

  function updateMarketChoice(next: MarketChoice) {
    setMarketChoice(next);
    if (typeof window !== "undefined") window.localStorage.setItem("mone:selectedMarketMode", next);
  }

  async function load() {
    setLoading(true);
    setMarketRegime(null);
    let nextMarketRegime: any = null;
    try {
      // 9개 조합 전부 로드
      const matrixRequests = MODES.flatMap((mode) =>
        HORIZONS.map(async (horizon) => {
          const result = await mone.recommendations({ market: selectedMarket, mode, horizon, limit: 12 });
          const items = dedupeBySymbol(Array.isArray(result.items) ? result.items : [])
            .slice(0, 5)
            .map((item: any) => ({ ...item, _mode: mode, _horizon: horizon }));
          if (result.marketRegime?.regime && !nextMarketRegime) nextMarketRegime = result.marketRegime;
          return { mode, horizon, items, count: Number(result.count || items.length || 0), status: String(result.status || "OK") } satisfies StrategyCell;
        })
      );

      const [h, matrixResult] = await Promise.all([
        mone.holdingsClean({ market: selectedMarket, limit: 20 }),
        Promise.all(matrixRequests),
      ]);

      setHoldings(dedupeBySymbol(Array.isArray(h.items) ? h.items : []));
      setSummary(h.summary || null);
      setMatrix(matrixResult);
      setMarketRegime(nextMarketRegime);

      // 전체 후보 통합 (중복 제거 — 같은 종목이 여러 조합에 있을 수 있음)
      const all = matrixResult.flatMap((cell) => cell.items);
      setAllItems(all);
    } catch {
      setHoldings([]); setSummary(null); setMatrix([]); setAllItems([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setClientReady(true);
    const saved = window.localStorage.getItem("mone:selectedMarketMode");
    if (saved === "kr" || saved === "us" || saved === "auto") setMarketChoice(saved);
    const refreshClock = () => setClock(new Date());
    refreshClock();
    const timer = window.setInterval(refreshClock, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (clientReady) load();
  }, [clientReady, selectedMarket]);

  // ── 오늘 진입 후보: EV 높은 순, 종목 중복 제거
  const todayEntries = useMemo(() => {
    const seen = new Set<string>();
    return allItems
      .filter((i) => i.decisionBucket === "오늘 진입" && Number(i.expectedValue || 0) > 0)
      .sort((a, b) => Number(b.expectedValue || 0) - Number(a.expectedValue || 0))
      .filter((i) => {
        const key = `${i.symbol}-${i._mode}-${i._horizon}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }, [allItems]);

  // ── 대기 관찰 후보: 타이밍 임박 순 (1~2일 > 3~5일 > 다음 주)
  const watchItems = useMemo(() => {
    const timingOrder: Record<string, number> = { "1~2일 후 진입": 0, "3~5일 후 진입": 1, "눌림 대기": 2, "다음 주 진입": 3 };
    const seen = new Set<string>();
    return allItems
      .filter((i) => i.decisionBucket === "대기 관찰")
      .sort((a, b) => {
        const ao = timingOrder[a.timingLabel] ?? 9;
        const bo = timingOrder[b.timingLabel] ?? 9;
        if (ao !== bo) return ao - bo;
        return Number(b.finalScore || 0) - Number(a.finalScore || 0);
      })
      .filter((i) => {
        const key = `${i.symbol}-${i._mode}-${i._horizon}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, 6);
  }, [allItems]);

  const riskCount = holdings.filter((h) => ["위험", "주의", "HIGH", "WATCH"].includes(String(h.riskStatus || ""))).length;

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* 헤더 */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-100">시장 홈</h1>
          <p className="text-xs text-slate-500">
            {marketChoiceLabel}: <span className="text-slate-300">{selectedMarket === "kr" ? "국장" : "미장"}</span>
            {" · "}{sessionStatus}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(["auto", "kr", "us"] as MarketChoice[]).map((choice) => (
            <button key={choice} onClick={() => updateMarketChoice(choice)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${marketChoice === choice ? "bg-blue-600 text-white" : "border border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}>
              {choice === "auto" ? "자동" : choice === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button onClick={load} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> 새로고침
          </button>
        </div>
      </div>

      {/* 마켓 레짐 배지 */}
      {marketRegime && (
        <div className={`flex flex-wrap items-center gap-2 rounded-2xl border px-4 py-3 text-sm ${
          marketRegime.regime === "BULL" ? "border-emerald-800/60 bg-emerald-950/20 text-emerald-300"
          : marketRegime.regime === "BEAR" ? "border-red-800/60 bg-red-950/20 text-red-300"
          : "border-slate-700 bg-slate-900/40 text-slate-400"}`}>
          <span className="font-bold">
            {marketRegime.regime === "BULL" ? "📈" : marketRegime.regime === "BEAR" ? "📉" : "➡️"}{" "}
            {marketRegime.label}
          </span>
          <span className="text-xs opacity-70">{marketRegime.description}</span>
          {marketRegime.regime === "BEAR" && <span className="ml-auto rounded bg-red-900/60 px-2 py-0.5 text-xs text-red-200">공격형 비활성화</span>}
        </div>
      )}

      {/* 요약 지표 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: "오늘 진입 후보", value: loading ? "—" : `${todayEntries.length}개`, color: "text-emerald-400" },
          { label: "대기 관찰 중", value: loading ? "—" : `${watchItems.length}개`, color: "text-amber-400" },
          { label: "위험/주의 보유", value: loading ? "—" : `${riskCount}개`, color: riskCount > 0 ? "text-red-400" : "text-slate-300" },
          { label: "총 평가손익", value: loading ? "—" : (summary?.totalPnlText ?? "0"), color: "text-slate-100" },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs text-slate-500">{label}</div>
            <div className={`mt-2 text-xl font-bold ${color}`}>{value}</div>
          </div>
        ))}
      </div>

      {/* ━━ 오늘 진입 후보 ━━ */}
      <section className="rounded-2xl border border-emerald-900/50 bg-emerald-950/10 p-5">
        <div className="mb-4 flex items-center gap-2">
          <TrendingUp size={18} className="text-emerald-400" />
          <div>
            <h2 className="text-base font-semibold text-slate-100">오늘 진입 후보</h2>
            <p className="text-xs text-slate-500">진입 구간 + EV 양수 + 추세 조건을 동시에 충족한 종목입니다.</p>
          </div>
          <span className="ml-auto rounded-full border border-emerald-800/50 bg-emerald-900/30 px-3 py-1 text-xs text-emerald-400">
            {loading ? "..." : `${todayEntries.length}개`}
          </span>
        </div>
        {loading ? (
          <div className="py-8 text-center text-slate-500">불러오는 중...</div>
        ) : todayEntries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 py-8 text-center text-sm text-slate-500">
            {marketRegime?.regime === "BEAR" ? "약세장 — 진입 기준 상향 적용 중" : "현재 즉시 진입 후보가 없습니다."}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {todayEntries.map((item, i) => (
              <TodayEntryCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} rank={i + 1} />
            ))}
          </div>
        )}
      </section>

      {/* ━━ 대기 관찰 후보 ━━ */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Eye size={18} className="text-amber-400" />
          <div>
            <h2 className="text-base font-semibold text-slate-100">대기 관찰 후보</h2>
            <p className="text-xs text-slate-500">지금보다 1~수일 후 진입 타이밍이 더 유리할 것으로 예상됩니다. 예상가에 알림 등록 권장.</p>
          </div>
          <span className="ml-auto rounded-full border border-amber-800/50 bg-amber-900/20 px-3 py-1 text-xs text-amber-400">
            {loading ? "..." : `${watchItems.length}개`}
          </span>
        </div>
        {loading ? (
          <div className="py-6 text-center text-slate-500">불러오는 중...</div>
        ) : watchItems.length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-500">대기 관찰 종목이 없습니다.</div>
        ) : (
          <div className="space-y-2">
            {watchItems.map((item) => (
              <WatchCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} />
            ))}
          </div>
        )}
      </section>

      {/* ━━ 3×3 전략 매트릭스 (상세 비교) ━━ */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-100">전략 × 기간 매트릭스</h2>
            <p className="text-xs text-slate-500">보수·균형·공격 × 단기·스윙·중기 9개 조합 전체 비교</p>
          </div>
          <span className="text-xs text-slate-500">{loading ? "불러오는 중" : "9개 조합"}</span>
        </div>

        {/* 헤더 행 */}
        <div className="mb-2 hidden grid-cols-[100px_repeat(3,1fr)] gap-2 xl:grid">
          <div />
          {HORIZONS.map((h) => (
            <div key={h} className="rounded-xl bg-slate-950/60 py-2 text-center text-xs font-semibold text-slate-400">{horizonLabel(h)}</div>
          ))}
        </div>

        <div className="space-y-2">
          {MODES.map((mode) => (
            <div key={mode} className="grid grid-cols-1 gap-2 xl:grid-cols-[100px_repeat(3,1fr)]">
              <div className="flex items-center justify-center rounded-2xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs font-semibold text-slate-300">
                {modeLabel(mode)}
              </div>
              {HORIZONS.map((horizon) => {
                const cell = matrix.find((c) => c.mode === mode && c.horizon === horizon) || { mode, horizon, items: [], count: 0, status: "NO_DATA" };
                return <MatrixCell key={`${mode}-${horizon}`} cell={cell as StrategyCell} />;
              })}
            </div>
          ))}
        </div>
      </section>

      {/* ━━ 보유종목 요약 ━━ */}
      {holdings.length > 0 && (
        <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <div className="mb-3 flex items-center gap-2">
            {riskCount > 0 && <AlertTriangle size={16} className="text-red-400" />}
            <h2 className="text-base font-semibold text-slate-100">보유종목</h2>
            <span className="ml-auto text-xs text-slate-500">{holdings.length}개 · 위험/주의 {riskCount}개</span>
          </div>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {holdings.slice(0, 6).map((item) => {
              const change = firstText(item.changePctText, "");
              const down = String(change).startsWith("-");
              const isRisk = ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""));
              return (
                <div key={`${item.market}-${item.symbol}`} className={`flex items-center justify-between rounded-xl border p-3 ${isRisk ? "border-red-800/40 bg-red-950/10" : "border-slate-800 bg-slate-950/50"}`}>
                  <div>
                    <div className="text-sm font-medium text-slate-200">{displayName(item)}</div>
                    <div className="text-[11px] text-slate-500">{item.symbol} · {probabilityText(item, "-")}</div>
                  </div>
                  <div className="text-right">
                    <div className={`font-mono text-sm ${String(item.pnlText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"}`}>
                      {firstText(item.pnlText, "0")}
                    </div>
                    {change && <div className={`font-mono text-[11px] ${down ? "text-red-400" : "text-emerald-400"}`}>{change}</div>}
                    {isRisk && <div className="text-[10px] text-red-400">{item.riskStatus}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
