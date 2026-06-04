"use client";

import { useEffect, useMemo, useState } from "react";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { dedupeBySymbol, displayName, firstText, formatMoney, horizonLabel, modeLabel, pctText, priceText, probabilityText, toNumber } from "@/lib/moneDisplay";

type Tab = "premarket" | "intraday" | "closing" | "virtual" | "validation";

// ── Metric 카드 ────────────────────────────────────────────────────────

function Metric({ label, value, accent = false }: { label: string; value: any; accent?: boolean }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-2 font-mono text-xl font-bold leading-tight ${accent ? "text-emerald-400" : "text-slate-100"}`}>{value}</div>
    </div>
  );
}

// ── 유틸 ──────────────────────────────────────────────────────────────

function signedMoney(value: number, market: Market) {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (market === "us") return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  return `${sign}${Math.round(abs).toLocaleString("ko-KR")}원`;
}

function latestDate(items: any[]) {
  const dates = items.map((item) => item.date || item.asOf || item.tradeDate || item.validationDate).filter(Boolean).sort();
  return dates.at(-1) || "-";
}

function latestOnly(items: any[]) {
  const latest = latestDate(items);
  return latest === "-" ? [] : items.filter((item) => (item.date || item.tradeDate || item.validationDate) === latest);
}

function statusTone(status: string) {
  if (status.includes("손절")) return "border-red-500/30 bg-red-500/10 text-red-300";
  if (status.includes("목표")) return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (status.includes("진입")) return "border-blue-500/30 bg-blue-500/10 text-blue-300";
  return "border-slate-700 bg-slate-800 text-slate-300";
}

function parseRet(r: any): number | null {
  const v = parseFloat(String(r.returnPct ?? r.virtual_return_pct ?? r.return_pct ?? ""));
  return isNaN(v) ? null : v;
}

function isPending(r: any) {
  const s = String(r.result || r.status || "").toUpperCase();
  return s === "PENDING" || s === "DATA_PENDING" || s === "";
}

// ── 누적 PnL 곡선 (SVG, 외부 라이브러리 없음) ─────────────────────────

function PnlCurve({ items }: { items: any[] }) {
  const { points, totalReturn } = useMemo(() => {
    const valid = items
      .filter((r) => !isPending(r) && parseRet(r) !== null)
      .sort((a, b) =>
        String(a.createdAt || a.created_at || a.date || "").localeCompare(
          String(b.createdAt || b.created_at || b.date || "")
        )
      );

    let cum = 0;
    const pts = valid.map((r) => {
      cum += parseRet(r)!;
      return {
        y: parseFloat(cum.toFixed(2)),
        label: String(r.createdAt || r.created_at || r.date || "").slice(5, 10),
      };
    });
    return { points: pts, totalReturn: cum };
  }, [items]);

  if (points.length < 2) {
    return (
      <div className="flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/60 py-6 text-xs text-slate-500">
        누적 PnL 곡선 — 검증 완료 데이터 부족 ({points.length}건, 최소 2건 필요)
      </div>
    );
  }

  const W = 600, H = 130;
  const pad = { top: 14, right: 16, bottom: 16, left: 48 };
  const w = W - pad.left - pad.right;
  const h = H - pad.top - pad.bottom;
  const n = points.length;

  const ys = points.map((p) => p.y);
  const minY = Math.min(...ys, 0);
  const maxY = Math.max(...ys, 0);
  const rangeY = maxY - minY || 1;

  const px = (i: number) => pad.left + (i / Math.max(n - 1, 1)) * w;
  const py = (y: number) => pad.top + ((maxY - y) / rangeY) * h;
  const zero = py(0);

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${px(i).toFixed(1)} ${py(p.y).toFixed(1)}`).join(" ");
  const fillD = `${pathD} L ${px(n - 1).toFixed(1)} ${zero} L ${px(0).toFixed(1)} ${zero} Z`;

  const isPos = totalReturn >= 0;
  const stroke = isPos ? "#34d399" : "#f87171";
  const fillColor = isPos ? "rgba(52,211,153,0.10)" : "rgba(248,113,113,0.10)";

  const tickSet = new Set([minY, 0, maxY]);
  const ticks = Array.from(tickSet);
  const xTicks =
    n <= 5
      ? Array.from({ length: n }, (_, i) => i)
      : [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor((3 * n) / 4), n - 1];

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 sm:p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-400">누적 PnL 곡선</span>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">{n}건</span>
          <span className={`font-mono font-semibold ${isPos ? "text-emerald-300" : "text-red-300"}`}>
            {isPos ? "+" : ""}{totalReturn.toFixed(2)}%
          </span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
        {ticks.map((v) => (
          <line key={v} x1={pad.left} y1={py(v)} x2={W - pad.right} y2={py(v)} stroke="#1e293b" strokeWidth={1} />
        ))}
        <line x1={pad.left} y1={zero} x2={W - pad.right} y2={zero} stroke="#334155" strokeWidth={1.5} strokeDasharray="5 3" />
        <path d={fillD} fill={fillColor} />
        <path d={pathD} fill="none" stroke={stroke} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {ticks.map((v) => (
          <text key={v} x={pad.left - 4} y={py(v) + 3.5} textAnchor="end" fontSize={9} fill="#64748b">
            {v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1)}%
          </text>
        ))}
        {xTicks.map((i) => (
          <text key={i} x={px(i)} y={H - 1} textAnchor="middle" fontSize={8} fill="#475569">
            {points[i]?.label || ""}
          </text>
        ))}
      </svg>
    </div>
  );
}

// ── 전략별 검증 성과 (가상운용 탭용) ─────────────────────────────────

function StrategyBreakdown({ items }: { items: any[] }) {
  const stats = useMemo(() => {
    const map: Record<string, { total: number; wins: number; returns: number[] }> = {};
    for (const r of items) {
      if (isPending(r)) continue;
      const ret = parseRet(r);
      if (ret === null) continue;
      const key = `${r.mode || "balanced"}_${r.horizon || "swing"}`;
      if (!map[key]) map[key] = { total: 0, wins: 0, returns: [] };
      map[key].total++;
      if (ret > 0) map[key].wins++;
      map[key].returns.push(ret);
    }
    return map;
  }, [items]);

  const modes: Mode[] = ["conservative", "balanced", "aggressive"];
  const horizons: Horizon[] = ["short", "swing", "mid"];
  if (!Object.values(stats).some((s) => s.total > 0)) return null;

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 sm:p-5">
      <div className="mb-3 text-sm font-semibold text-slate-200">전략별 검증 성과</div>
      <div className="overflow-x-auto -mx-1">
        <table className="w-full min-w-[260px] text-[11px]">
          <thead>
            <tr className="border-b border-slate-800">
              <th className="pb-2 text-left text-slate-500">전략</th>
              {horizons.map((h) => (
                <th key={h} className="pb-2 text-center text-slate-500">{horizonLabel(h)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {modes.map((m) => (
              <tr key={m} className="border-b border-slate-900/60">
                <td className="py-2.5 pr-3 font-semibold text-slate-300">{modeLabel(m)}</td>
                {horizons.map((h) => {
                  const s = stats[`${m}_${h}`];
                  if (!s || s.total === 0) return <td key={h} className="py-2.5 text-center text-slate-700">—</td>;
                  const wr = (s.wins / s.total) * 100;
                  const avg = s.returns.reduce((a, b) => a + b, 0) / s.returns.length;
                  const wrColor = wr >= 55 ? "text-emerald-300" : wr >= 45 ? "text-amber-300" : "text-red-300";
                  const barColor = wr >= 55 ? "bg-emerald-500" : wr >= 45 ? "bg-amber-500" : "bg-red-500";
                  return (
                    <td key={h} className="py-2.5 text-center">
                      <div className={`text-sm font-bold ${wrColor}`}>{wr.toFixed(0)}%</div>
                      <div className="mx-auto mt-1 h-1.5 w-12 rounded-full bg-slate-800">
                        <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${Math.min(wr, 100)}%` }} />
                      </div>
                      <div className={`mt-0.5 font-mono text-[10px] ${avg >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        avg {avg >= 0 ? "+" : ""}{avg.toFixed(1)}%
                      </div>
                      <div className="text-slate-600">{s.wins}/{s.total}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── 빈 상태 ────────────────────────────────────────────────────────────

const EMPTY_MSGS: Record<Tab, string> = {
  premarket: "장전 추천 데이터가 없습니다. GitHub Actions가 최신 추천 CSV를 생성했는지 확인하세요.",
  intraday: "장중 데이터가 없습니다. 장 중에 현재가를 수집한 후 다시 확인하세요.",
  closing: "장마감 검증 데이터가 없습니다. 장 마감 후 체결 검증이 실행되어야 합니다.",
  virtual: "가상운용 데이터가 없습니다. 추천이 생성되면 자동으로 기록됩니다.",
  validation: "검증 대시보드 데이터가 없습니다.",
};

function EmptyState({ tab, error }: { tab: Tab; error?: string }) {
  return (
    <div className="px-5 py-14 text-center text-sm text-slate-500">
      {error ? `오류: ${error}` : EMPTY_MSGS[tab]}
    </div>
  );
}

// ── 메인 컴포넌트 ──────────────────────────────────────────────────────

export default function ReportPage() {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [tab, setTab] = useState<Tab>("premarket");
  const [data, setData] = useState<any>({ status: "LOADING", items: [] });
  const [virtual, setVirtual] = useState<any>({ status: "LOADING" });
  const [holdings, setHoldings] = useState<any>({ status: "LOADING", items: [] });
  const [virtualLedger, setVirtualLedger] = useState<any>({ status: "LOADING", items: [] });
  const [virtualValidation, setVirtualValidation] = useState<any>({ status: "LOADING", items: [] });
  const [valDashboard, setValDashboard] = useState<any>(null);

  useEffect(() => {
    let active = true;
    setData({ status: "LOADING", items: [] });
    setValDashboard(null); // 탭/마켓 변경 시 stale 데이터 방지
    const task =
      tab === "virtual" || tab === "closing" || tab === "validation"
        ? mone.backtestTrades({ market, mode, horizon, limit: 300 })
        : mone.report(tab as "premarket" | "intraday", { market, mode, horizon, limit: 300 });

    task
      .then((r) => active && setData(r || { status: "OK", items: [] }))
      .catch((e) => active && setData({ status: "ERROR", error: String(e), items: [] }));

    mone.backtestSummary({ market, mode, horizon })
      .then((r) => active && setVirtual(r || {})).catch(() => active && setVirtual({}));
    mone.virtualLedger({ market, mode, horizon, limit: 300 })
      .then((r) => active && setVirtualLedger(r || { items: [] })).catch(() => active && setVirtualLedger({ items: [] }));
    // mode/horizon 없이 전체 — StrategyBreakdown이 9개 전략 전체 집계용
    mone.virtualValidation({ market, limit: 300 })
      .then((r) => active && setVirtualValidation(r || { items: [] })).catch(() => active && setVirtualValidation({ items: [] }));
    mone.holdingsClean({ market, limit: 500 })
      .then((r) => active && setHoldings(r || { items: [] })).catch(() => active && setHoldings({ items: [] }));
    if (tab === "validation") {
      mone.validationDashboard({ market })
        .then((r) => active && setValDashboard(r || null)).catch(() => active && setValDashboard(null));
    }
    return () => { active = false; };
  }, [market, mode, horizon, tab]);

  const rawItems = Array.isArray(data.items) ? data.items : [];
  const items = useMemo(() => (tab === "closing" || tab === "virtual" ? rawItems : dedupeBySymbol(rawItems)), [rawItems, tab]);
  const todayItems = useMemo(() => latestOnly(items), [items]);
  const closing = tab === "closing";
  const virtualTab = tab === "virtual";
  const intraday = tab === "intraday";

  const holdingItems = Array.isArray(holdings.items) ? holdings.items : [];
  // v3 backend: marketValue (not valuation), avgPrice*quantity for cost
  const holdingValue = holdingItems.reduce((s: number, i: any) => s + (toNumber(i.marketValue) || toNumber(i.valuation) || 0), 0);
  const holdingPnl   = holdingItems.reduce((s: number, i: any) => s + (toNumber(i.pnl) || 0), 0);
  const holdingCost  = holdingItems.reduce((s: number, i: any) => {
    const avg = toNumber(i.avgPrice) || 0;
    const qty = toNumber(i.quantity) || 0;
    return s + (avg * qty) || (toNumber(i.cost) || 0);
  }, 0);
  const holdingDayPnl = holdingItems.reduce((s: number, i: any) => {
    const cur = toNumber(i.currentPrice), prev = toNumber(i.prevClose), qty = toNumber(i.quantity);
    return cur && prev && qty ? s + (cur - prev) * qty : s;
  }, 0);
  const holdingPnlPct    = holdingCost > 0 ? (holdingPnl / holdingCost) * 100 : 0;
  const holdingDayPnlPct = holdingValue > 0 ? (holdingDayPnl / (holdingValue - holdingDayPnl || holdingValue)) * 100 : 0;

  // 당일 체결 기준 평균 수익률 (합계 아닌 평균)
  const todayExecuted = todayItems.filter((i) => !String(i.executionStatus || i.result || "").includes("not_executed"));
  const todayAvgReturn =
    todayExecuted.length > 0
      ? todayExecuted.reduce((s, i) => s + Number(i.realizedReturnPct || i.returnPct || 0), 0) / todayExecuted.length
      : 0;

  const virtualItems = Array.isArray(virtualValidation.items) ? virtualValidation.items : [];

  const tabs: { id: Tab; label: string; desc: string }[] = [
    { id: "premarket",  label: "장전 리포트",   desc: "오늘 추천 후보와 매매 계획" },
    { id: "intraday",   label: "장중 체크",      desc: "현재가 기준 접근·위험 상태" },
    { id: "closing",    label: "장마감 검증",    desc: "실제 OHLCV 기준 체결 검증" },
    { id: "virtual",    label: "가상운용",       desc: "누적 체결률·승률·수익률" },
    { id: "validation", label: "검증 대시보드",  desc: "9개 전략 승률·수익률 매트릭스" },
  ];

  return (
    <div className="space-y-5 p-4 sm:p-6">

      {/* ── 헤더 ── */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100 sm:text-2xl">운용 리포트</h1>
          <p className="mt-1 text-xs text-slate-400 sm:text-sm">장전 계획, 장중 접근도, 장마감 검증, 가상운용을 분리해서 확인합니다.</p>
        </div>
        <div className="flex gap-2">
          {(["kr", "us"] as Market[]).map((m) => (
            <button key={m} onClick={() => setMarket(m)}
              className={`rounded-xl px-4 py-1.5 text-sm font-medium ${market === m ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>
              {marketLabel(m)}
            </button>
          ))}
        </div>
      </div>

      {/* ── 탭 — 모바일 2열, 태블릿 3열, 데스크톱 5열 ── */}
      <div className="grid grid-cols-2 gap-1.5 rounded-2xl bg-slate-900/60 p-1.5 sm:grid-cols-3 md:grid-cols-5">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`rounded-xl px-2 py-2.5 text-left text-xs sm:text-sm ${tab === t.id ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`}>
            <div className="font-bold leading-tight">{t.label}</div>
            <div className="mt-0.5 hidden text-[10px] opacity-70 sm:block">{t.desc}</div>
          </button>
        ))}
      </div>

      {/* ── 전략·기간 필터 ── */}
      <div className="flex flex-wrap gap-1.5">
        {(["conservative", "balanced", "aggressive"] as Mode[]).map((m) => (
          <button key={m} onClick={() => setMode(m)}
            className={`rounded-xl px-3 py-1.5 text-xs font-medium ${mode === m ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {modeLabel(m)}
          </button>
        ))}
        {(["short", "swing", "mid"] as Horizon[]).map((h) => (
          <button key={h} onClick={() => setHorizon(h)}
            className={`rounded-xl px-3 py-1.5 text-xs font-medium ${horizon === h ? "bg-cyan-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {horizonLabel(h)}
          </button>
        ))}
      </div>

      {/* ── 보유종목 + 가상운용 요약 (장마감·가상운용 탭) ── */}
      {(closing || virtualTab) && (
        <div className="space-y-4">
          {/* 보유종목 실제 평가손익 */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 sm:p-5">
            <div className="mb-3 text-sm font-semibold text-slate-200">보유종목 실제 평가손익</div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Metric label="보유 평가금액" value={formatMoney(holdingValue, market)} />
              <Metric label="보유 평가손익" value={signedMoney(holdingPnl, market)} accent={holdingPnl >= 0} />
              <Metric label="보유 수익률" value={pctText(holdingPnlPct)} />
              <Metric label="보유 당일손익" value={`${signedMoney(holdingDayPnl, market)} · ${pctText(holdingDayPnlPct)}`} />
            </div>
          </div>

          {/* 검증 수익률 요약 */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 sm:p-5">
            <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <span className="text-sm font-semibold text-slate-200">추천/가상운용 검증 수익률</span>
              <span className="text-xs text-slate-500">{virtual.returnBasis || "체결 종목 기준, 미체결 제외"}</span>
            </div>
            {virtual.todayStatus === "NO_DATA" && (
              <div className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-xs text-amber-200 sm:text-sm">
                {virtual.todayDate} {virtual.todayMessage || "오늘 장마감 원본 없음"}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Metric label="추천 수" value={virtual.latestRecommendations ?? virtual.totalRecommendations ?? data.totalRecommendations ?? items.length} />
              <Metric label="체결 수" value={virtual.latestExecutedTrades ?? virtual.executedTrades ?? data.executedTrades ?? 0} />
              <Metric label="미체결 수" value={virtual.latestUnexecutedCount ?? virtual.unexecutedCount ?? 0} />
              <Metric label="체결률" value={`${Number(virtual.latestExecutionRate ?? virtual.executionRate ?? 0).toFixed(2)}%`} />
              <Metric label="체결 기준 승률" value={`${Number(virtual.latestWinRate ?? virtual.winRate ?? data.winRate ?? 0).toFixed(2)}%`} />
              <Metric label="체결 기준 수익률" accent
                value={`${Number(virtual.latestCumulativeReturnPct ?? virtual.executedReturnPct ?? virtual.cumulativeReturnPct ?? data.cumulativeReturnPct ?? 0).toFixed(2)}%`} />
              <Metric label="누적 검증" value={virtual.totalRecommendations ?? data.totalRecommendations ?? items.length} />
              <Metric label="누적 체결" value={virtual.executedTrades ?? data.executedTrades ?? 0} />
            </div>

            {/* 가상운용 탭: 누적 PnL 곡선 + 원장 카드 */}
            {virtualTab && (
              <div className="mt-4 space-y-3">
                <PnlCurve items={virtualItems} />
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 sm:p-4">
                    <div className="text-xs font-semibold text-slate-400">가상 예측 저장</div>
                    <div className="mt-1.5 text-sm text-slate-200">
                      기록 {Number(virtualLedger.count ?? virtualLedger.items?.length ?? 0).toLocaleString("ko-KR")}건 · 상태 {virtualLedger.status || "확인 중"}
                    </div>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 sm:p-4">
                    <div className="text-xs font-semibold text-slate-400">검증 결과</div>
                    <div className="mt-1.5 text-sm text-slate-200">
                      결과 {Number(virtualValidation.count ?? virtualValidation.items?.length ?? 0).toLocaleString("ko-KR")}건 · 보류 {Number(virtualValidation.pendingCount ?? 0).toLocaleString("ko-KR")}건
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* 가상운용 탭: 전략별 성과 브레이크다운 */}
          {virtualTab && virtualItems.length > 0 && <StrategyBreakdown items={virtualItems} />}
        </div>
      )}

      {/* ── 당일 요약 (장마감 탭) ── */}
      {closing && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 sm:p-5">
          <div className="mb-3 text-sm font-semibold text-slate-200">당일 검증 요약 · 기준일 {latestDate(items)}</div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="당일 후보" value={todayItems.length} />
            <Metric label="당일 체결" value={todayExecuted.length} />
            <Metric label="미체결" value={todayItems.length - todayExecuted.length} />
            <Metric accent={todayAvgReturn >= 0}
              label="체결 기준 평균 수익률"
              value={`${todayAvgReturn >= 0 ? "+" : ""}${todayAvgReturn.toFixed(2)}%`} />
          </div>
        </div>
      )}

      {/* ── 종목 테이블 ── */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/50">
        <div className="border-b border-slate-800 px-4 py-3 text-xs text-slate-400 sm:px-5 sm:py-4 sm:text-sm">
          {marketLabel(market)} · {modeLabel(mode)} · {horizonLabel(horizon)} · 기준일 {latestDate(items)} · {items.length.toLocaleString("ko-KR")}건
        </div>

        {data.status === "LOADING" ? (
          <div className="py-12 text-center text-slate-500">불러오는 중...</div>
        ) : items.length === 0 ? (
          <EmptyState tab={tab} error={data.status === "ERROR" ? data.error : undefined} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="bg-slate-950/50 text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-3">종목</th>
                  {closing || virtualTab ? (
                    <>
                      <th className="px-4 py-3">일자</th>
                      <th className="px-4 py-3">체결</th>
                      <th className="px-4 py-3">결과</th>
                      <th className="px-4 py-3">수익률</th>
                      <th className="px-4 py-3">출처</th>
                    </>
                  ) : intraday ? (
                    <>
                      <th className="px-4 py-3">현재가</th>
                      <th className="px-4 py-3">진입가까지</th>
                      <th className="px-4 py-3">손절가까지</th>
                      <th className="px-4 py-3">목표가까지</th>
                      <th className="px-4 py-3">장중 상태</th>
                      <th className="px-4 py-3">근거</th>
                    </>
                  ) : (
                    <>
                      <th className="px-4 py-3">현재가</th>
                      <th className="px-4 py-3">진입가</th>
                      <th className="px-4 py-3">손절가</th>
                      <th className="px-4 py-3">목표가</th>
                      <th className="px-4 py-3">확률</th>
                      <th className="px-4 py-3">예상가</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((item: any, index: number) => (
                  <tr key={`${item.id || item.symbol || "r"}-${index}`} className="border-t border-slate-800/70 hover:bg-slate-900/30">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-slate-100">{displayName(item)}</div>
                      <div className="mt-0.5 font-mono text-xs text-slate-500">{item.symbol || "-"} · {(item.market || market).toUpperCase()}</div>
                    </td>
                    {closing || virtualTab ? (
                      (() => {
                        const execRaw = item.executionStatus || item.executed;
                        const isExec = execRaw === "체결" || execRaw === "true" || execRaw === true || execRaw === "1";
                        const execLabel = item.executionStatus || (isExec ? "체결" : execRaw === "false" || execRaw === false ? "미체결" : execRaw || "조건 확인");
                        const retPct = Number(item.realizedReturnPct ?? item.returnPct ?? item.virtual_return_pct ?? 0);
                        const retColor = retPct > 0 ? "text-emerald-400" : retPct < 0 ? "text-red-400" : "text-slate-400";
                        return (
                          <>
                            <td className="px-4 py-3 font-mono text-xs text-slate-300">{item.date || item.tradeDate || "-"}</td>
                            <td className={`px-4 py-3 text-sm font-medium ${isExec ? "text-emerald-400" : "text-slate-500"}`}>{execLabel}</td>
                            <td className="px-4 py-3 text-sm text-slate-200">{item.outcomeResult || item.result || "검증 대기"}</td>
                            <td className={`px-4 py-3 font-mono text-sm ${retColor}`}>{retPct !== 0 ? `${retPct >= 0 ? "+" : ""}${retPct.toFixed(2)}%` : "-"}</td>
                            <td className="px-4 py-3 text-xs text-slate-500">{item.sourceFile || item.source || "-"}</td>
                          </>
                        );
                      })()
                    ) : intraday ? (
                      <>
                        <td className="px-4 py-3 font-mono text-sm text-slate-100">{priceText(item, "current", "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-blue-300">{firstText(item.entryDistanceText, "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-red-300">{firstText(item.stopDistanceText, "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-emerald-300">{firstText(item.targetDistanceText, "-")}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded border px-2 py-0.5 text-xs ${statusTone(String(item.intradayStatus || ""))}`}>
                            {item.intradayStatus || "관망"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500">{item.intradayReason || item.priceSource || "-"}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-3 font-mono text-sm text-slate-100">{priceText(item, "current", "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-blue-300">{priceText(item, "entry", "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-red-300">{priceText(item, "stop", "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-emerald-300">{priceText(item, "target", "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-amber-300">{probabilityText(item, "-")}</td>
                        <td className="px-4 py-3 font-mono text-sm text-violet-300">{priceText(item, "expected", "-")}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── 검증 대시보드 탭 ── */}
      {tab === "validation" && (
        <div className="space-y-5">
          {!valDashboard ? (
            <div className="py-12 text-center text-slate-500">불러오는 중...</div>
          ) : (
            <>
              {/* 요약 카드 */}
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "전체 승률", value: valDashboard.summary?.overallWinRate != null ? `${valDashboard.summary.overallWinRate}%` : "—" },
                  { label: "완료 검증", value: `${valDashboard.summary?.totalCompleted ?? 0}건` },
                  { label: "검증 대기", value: `${valDashboard.summary?.totalPending ?? 0}건` },
                ].map(({ label, value }) => (
                  <div key={label} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3 text-center sm:p-4">
                    <div className="text-xs text-slate-500">{label}</div>
                    <div className="mt-1.5 text-lg font-bold text-slate-100 sm:text-xl">{value}</div>
                  </div>
                ))}
              </div>

              {/* 전략별 승률 매트릭스 + 바 */}
              <div>
                <h3 className="mb-2 text-sm font-semibold text-slate-300">전략별 승률 매트릭스</h3>
                <div className="overflow-x-auto rounded-2xl border border-slate-800">
                  <table className="w-full min-w-[300px] text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-800 bg-slate-900/80">
                        <th className="px-3 py-2.5 text-left text-slate-500">전략</th>
                        {(["단기", "스윙", "중기"] as const).map((h) => (
                          <th key={h} className="px-3 py-2.5 text-center text-slate-500">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(["conservative", "balanced", "aggressive"] as const).map((m) => (
                        <tr key={m} className="border-b border-slate-900">
                          <td className="px-3 py-3 font-semibold text-slate-300">{modeLabel(m)}</td>
                          {(["short", "swing", "mid"] as const).map((h) => {
                            const s = valDashboard.stats?.[`${m}_${h}`];
                            const wr = s?.winRate;
                            const barColor = wr == null ? "" : wr >= 55 ? "bg-emerald-500" : wr >= 45 ? "bg-amber-500" : "bg-red-500";
                            return (
                              <td key={h} className="px-3 py-3 text-center">
                                <div className={`text-base font-bold ${wr == null ? "text-slate-600" : wr >= 55 ? "text-emerald-300" : wr >= 45 ? "text-amber-300" : "text-red-300"}`}>
                                  {wr != null ? `${wr}%` : "—"}
                                </div>
                                {wr != null && (
                                  <div className="mx-auto mt-1 h-1.5 w-12 rounded-full bg-slate-800">
                                    <div className={`h-1.5 rounded-full ${barColor}`} style={{ width: `${Math.min(wr, 100)}%` }} />
                                  </div>
                                )}
                                <div className="mt-0.5 text-slate-500">
                                  {s?.completed ? `${s.wins}/${s.completed}` : `대기 ${s?.pendingCount ?? 0}`}
                                </div>
                                {s?.avgReturn != null && (
                                  <div className={`text-[10px] font-mono ${s.avgReturn >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                                    avg {s.avgReturn >= 0 ? "+" : ""}{s.avgReturn.toFixed(1)}%
                                  </div>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* 추천 생애주기 */}
              {Array.isArray(valDashboard.lifecycle) && valDashboard.lifecycle.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-slate-300">추천 생애주기</h3>
                  <div className="max-h-80 space-y-1.5 overflow-y-auto sm:max-h-96">
                    {valDashboard.lifecycle.map((lc: any) => {
                      const s = String(lc.status || "PENDING");
                      const sc =
                        s === "PENDING" ? "bg-slate-700 text-slate-300"
                        : s.includes("WIN") || s.includes("목표") ? "bg-emerald-700 text-white"
                        : s.includes("LOSS") || s.includes("손절") ? "bg-red-700 text-white"
                        : "bg-blue-700 text-white";
                      return (
                        <div key={lc.predictionId} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2 text-[11px]">
                          <div className="min-w-0 flex-1 overflow-hidden">
                            <span className="font-semibold text-slate-200">{lc.name || lc.symbol}</span>
                            <span className="ml-1.5 hidden text-slate-500 sm:inline">
                              {lc.symbol} · {modeLabel(lc.mode as Mode)} · {horizonLabel(lc.horizon as Horizon)}
                            </span>
                          </div>
                          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
                            <span className="hidden text-slate-500 sm:inline">{String(lc.createdAt || "").slice(0, 10)}</span>
                            {lc.returnPct != null && (
                              <span className={`font-mono ${lc.returnPct >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                                {lc.returnPct >= 0 ? "+" : ""}{lc.returnPct.toFixed(1)}%
                              </span>
                            )}
                            <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${sc}`}>{s}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
