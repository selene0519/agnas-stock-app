"use client";

import { useEffect, useMemo, useState } from "react";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { dedupeBySymbol, displayName, firstText, formatMoney, horizonLabel, modeLabel, pctText, priceText, probabilityText, toNumber } from "@/lib/moneDisplay";

type Tab = "premarket" | "intraday" | "closing" | "virtual" | "validation";

function Metric({ label, value, accent = false }: { label: string; value: any; accent?: boolean }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-3 font-mono text-2xl font-bold ${accent ? "text-emerald-400" : "text-slate-100"}`}>{value}</div>
    </div>
  );
}

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
    const task = tab === "virtual" || tab === "closing" || tab === "validation"
      ? mone.backtestTrades({ market, mode, horizon, limit: 300 })
      : mone.report(tab as "premarket" | "intraday", { market, mode, horizon, limit: 300 });

    task.then((response) => active && setData(response || { status: "OK", items: [] }))
      .catch((error) => active && setData({ status: "ERROR", error: String(error), items: [] }));
    mone.backtestSummary({ market, mode, horizon }).then((response) => active && setVirtual(response || {})).catch(() => active && setVirtual({}));
    mone.virtualLedger({ market, mode, horizon, limit: 300 }).then((response) => active && setVirtualLedger(response || { items: [] })).catch(() => active && setVirtualLedger({ items: [] }));
    mone.virtualValidation({ market, mode, horizon, limit: 300 }).then((response) => active && setVirtualValidation(response || { items: [] })).catch(() => active && setVirtualValidation({ items: [] }));
    mone.holdingsClean({ market, limit: 500 }).then((response) => active && setHoldings(response || { items: [] })).catch(() => active && setHoldings({ items: [] }));
    if (tab === "validation") {
      mone.validationDashboard({ market }).then((r) => active && setValDashboard(r || null)).catch(() => active && setValDashboard(null));
    }
    return () => {
      active = false;
    };
  }, [market, mode, horizon, tab]);

  const rawItems = Array.isArray(data.items) ? data.items : [];
  const items = useMemo(() => (tab === "closing" || tab === "virtual" ? rawItems : dedupeBySymbol(rawItems)), [rawItems, tab]);
  const todayItems = useMemo(() => latestOnly(items), [items]);
  const closing = tab === "closing";
  const virtualTab = tab === "virtual";
  const intraday = tab === "intraday";
  const holdingItems = Array.isArray(holdings.items) ? holdings.items : [];
  const holdingValue = holdingItems.reduce((sum: number, item: any) => sum + (toNumber(item.valuation) || 0), 0);
  const holdingPnl = holdingItems.reduce((sum: number, item: any) => sum + (toNumber(item.pnl) || 0), 0);
  const holdingCost = holdingItems.reduce((sum: number, item: any) => sum + (toNumber(item.cost) || 0), 0);
  const holdingDayPnl = holdingItems.reduce((sum: number, item: any) => {
    const current = toNumber(item.currentPrice);
    const prev = toNumber(item.prevClose);
    const qty = toNumber(item.quantity);
    return current && prev && qty ? sum + (current - prev) * qty : sum;
  }, 0);
  const holdingPnlPct = holdingCost > 0 ? (holdingPnl / holdingCost) * 100 : 0;
  const holdingDayPnlPct = holdingValue - holdingDayPnl > 0 ? (holdingDayPnl / (holdingValue - holdingDayPnl)) * 100 : 0;

  const tabs: { id: Tab; label: string; desc: string }[] = [
    { id: "premarket", label: "장전 리포트", desc: "오늘 추천 후보와 매매 계획" },
    { id: "intraday", label: "장중 체크", desc: "현재가 기준 접근·위험 상태" },
    { id: "closing", label: "장마감 검증", desc: "실제 OHLCV 기준 체결 검증" },
    { id: "virtual", label: "가상운용", desc: "누적 체결률·승률·수익률" },
    { id: "validation", label: "검증 대시보드", desc: "9개 전략 승률·수익률 매트릭스" },
  ];

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">운용 리포트</h1>
          <p className="mt-1 text-sm text-slate-400">장전 계획, 장중 접근도, 장마감 검증, 가상운용을 분리해서 확인합니다.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(["kr", "us"] as Market[]).map((item) => (
            <button key={item} onClick={() => setMarket(item)} className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>
              {marketLabel(item)}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 rounded-2xl bg-slate-900/60 p-2 md:grid-cols-4">
        {tabs.map((item) => (
          <button key={item.id} onClick={() => setTab(item.id)} className={`rounded-xl p-3 text-left text-sm ${tab === item.id ? "bg-blue-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"}`}>
            <div className="font-bold">{item.label}</div>
            <div className="mt-1 text-[11px] opacity-75">{item.desc}</div>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {(["conservative", "balanced", "aggressive"] as Mode[]).map((item) => (
          <button key={item} onClick={() => setMode(item)} className={`rounded-xl px-3 py-1.5 text-xs ${mode === item ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"}`}>{modeLabel(item)}</button>
        ))}
        {(["short", "swing", "mid"] as Horizon[]).map((item) => (
          <button key={item} onClick={() => setHorizon(item)} className={`rounded-xl px-3 py-1.5 text-xs ${horizon === item ? "bg-cyan-600 text-white" : "bg-slate-900 text-slate-400"}`}>{horizonLabel(item)}</button>
        ))}
      </div>

      {(closing || virtualTab) && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
            <div className="mb-3 text-sm font-semibold text-slate-200">보유종목 실제 평가손익</div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <Metric label="보유 평가금액" value={formatMoney(holdingValue, market)} />
              <Metric label="보유 평가손익" value={signedMoney(holdingPnl, market)} accent={holdingPnl >= 0} />
              <Metric label="보유 수익률" value={pctText(holdingPnlPct)} />
              <Metric label="보유 당일손익" value={`${signedMoney(holdingDayPnl, market)} · ${pctText(holdingDayPnlPct)}`} />
            </div>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
            <div className="mb-3 flex flex-col gap-1 text-sm text-slate-400 md:flex-row md:items-center md:justify-between">
              <span className="font-semibold text-slate-200">추천/가상운용 검증 수익률</span>
              <span>{virtual.returnBasis || "체결 종목 기준, 미체결 제외"}</span>
            </div>
            {virtual.todayStatus === "NO_DATA" && (
              <div className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                {virtual.todayDate} {virtual.todayMessage || "오늘 장마감 원본 없음"}
              </div>
            )}
            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <Metric label="추천 수" value={virtual.latestRecommendations ?? virtual.totalRecommendations ?? data.totalRecommendations ?? items.length} />
              <Metric label="체결 수" value={virtual.latestExecutedTrades ?? virtual.executedTrades ?? data.executedTrades ?? 0} />
              <Metric label="미체결 수" value={virtual.latestUnexecutedCount ?? virtual.unexecutedCount ?? 0} />
              <Metric label="체결률" value={`${Number(virtual.latestExecutionRate ?? virtual.executionRate ?? 0).toFixed(2)}%`} />
              <Metric label="체결 기준 승률" value={`${Number(virtual.latestWinRate ?? virtual.winRate ?? data.winRate ?? 0).toFixed(2)}%`} />
              <Metric label="체결 기준 수익률" value={`${Number(virtual.latestCumulativeReturnPct ?? virtual.executedReturnPct ?? virtual.cumulativeReturnPct ?? data.cumulativeReturnPct ?? 0).toFixed(2)}%`} accent />
              <Metric label="누적 검증" value={virtual.totalRecommendations ?? data.totalRecommendations ?? items.length} />
              <Metric label="누적 체결" value={virtual.executedTrades ?? data.executedTrades ?? 0} />
            </div>
            {virtualTab && (
              <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                  <div className="text-xs font-semibold text-slate-400">가상 예측 저장</div>
                  <div className="mt-2 text-sm text-slate-200">기록 {Number(virtualLedger.count ?? virtualLedger.items?.length ?? 0).toLocaleString("ko-KR")}건 · 상태 {virtualLedger.status || "확인 중"}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                  <div className="text-xs font-semibold text-slate-400">검증 결과</div>
                  <div className="mt-2 text-sm text-slate-200">결과 {Number(virtualValidation.count ?? virtualValidation.items?.length ?? 0).toLocaleString("ko-KR")}건 · 보류 {Number(virtualValidation.pendingCount ?? 0).toLocaleString("ko-KR")}건</div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {closing && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-3 text-sm font-semibold text-slate-200">당일 검증 요약 · 기준일 {latestDate(items)}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <Metric label="당일 후보" value={todayItems.length} />
            <Metric label="당일 체결" value={todayItems.filter((item) => item.executionStatus === "executed" || item.is_executed === true || item.executed === true).length} />
            <Metric label="미체결" value={todayItems.filter((item) => String(item.executionStatus || item.result || "").includes("not_executed")).length} />
            <Metric label="체결 기준 당일 수익률" value={`${todayItems.filter((item) => !String(item.executionStatus || item.result || "").includes("not_executed")).reduce((sum, item) => sum + Number(item.realizedReturnPct || item.returnPct || 0), 0).toFixed(2)}%`} accent />
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50">
        <div className="border-b border-slate-800 px-5 py-4 text-sm text-slate-400">
          {marketLabel(market)} · {modeLabel(mode)} · {horizonLabel(horizon)} · 기준일 {latestDate(items)} · {items.length.toLocaleString("ko-KR")}건
        </div>
        {items.length === 0 ? (
          <div className="p-12 text-center text-slate-500">{data.status === "ERROR" ? `데이터 로딩 오류: ${data.error}` : "표시할 리포트 데이터가 없습니다."}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-left text-sm">
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
                  <tr key={`${item.id || item.symbol || "report"}-${index}`} className="border-t border-slate-800/70">
                    <td className="px-4 py-4">
                      <div className="font-semibold text-slate-100">{displayName(item)}</div>
                      <div className="font-mono text-xs text-slate-500">{item.symbol || "-"} · {(item.market || market).toUpperCase()}</div>
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
                            <td className="px-4 py-4 font-mono text-slate-300">{item.date || item.tradeDate || "-"}</td>
                            <td className={`px-4 py-4 font-medium ${isExec ? "text-emerald-400" : "text-slate-500"}`}>{execLabel}</td>
                            <td className="px-4 py-4 text-slate-200">{item.outcomeResult || item.result || "검증 대기"}</td>
                            <td className={`px-4 py-4 font-mono ${retColor}`}>{retPct !== 0 ? `${retPct >= 0 ? "+" : ""}${retPct.toFixed(2)}%` : "-"}</td>
                            <td className="px-4 py-4 text-xs text-slate-500">{item.sourceFile || item.source || "-"}</td>
                          </>
                        );
                      })()
                    ) : intraday ? (
                      <>
                        <td className="px-4 py-4 font-mono text-slate-100">{priceText(item, "current", "-")}</td>
                        <td className="px-4 py-4 font-mono text-blue-300">{firstText(item.entryDistanceText, "-")}</td>
                        <td className="px-4 py-4 font-mono text-red-300">{firstText(item.stopDistanceText, "-")}</td>
                        <td className="px-4 py-4 font-mono text-emerald-300">{firstText(item.targetDistanceText, "-")}</td>
                        <td className="px-4 py-4"><span className={`rounded border px-2 py-1 text-xs ${statusTone(String(item.intradayStatus || ""))}`}>{item.intradayStatus || "관망"}</span></td>
                        <td className="px-4 py-4 text-xs text-slate-500">{item.intradayReason || item.priceSource || "-"}</td>
                      </>
                    ) : (
                      <>
                        <td className="px-4 py-4 font-mono text-slate-100">{priceText(item, "current", "-")}</td>
                        <td className="px-4 py-4 font-mono text-blue-300">{priceText(item, "entry", "-")}</td>
                        <td className="px-4 py-4 font-mono text-red-300">{priceText(item, "stop", "-")}</td>
                        <td className="px-4 py-4 font-mono text-emerald-300">{priceText(item, "target", "-")}</td>
                        <td className="px-4 py-4 font-mono text-amber-300">{probabilityText(item, "-")}</td>
                        <td className="px-4 py-4 font-mono text-violet-300">{priceText(item, "expected", "-")}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── 검증 대시보드 탭 */}
      {tab === "validation" && (
        <div className="space-y-6">
          {!valDashboard ? (
            <div className="py-12 text-center text-slate-500">불러오는 중...</div>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "전체 승률", value: valDashboard.summary?.overallWinRate != null ? `${valDashboard.summary.overallWinRate}%` : "—" },
                  { label: "완료 검증", value: `${valDashboard.summary?.totalCompleted ?? 0}건` },
                  { label: "검증 대기", value: `${valDashboard.summary?.totalPending ?? 0}건` },
                ].map(({ label, value }) => (
                  <div key={label} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-center">
                    <div className="text-xs text-slate-500">{label}</div>
                    <div className="mt-2 text-xl font-bold text-slate-100">{value}</div>
                  </div>
                ))}
              </div>
              <div>
                <h3 className="mb-3 text-sm font-semibold text-slate-300">전략별 승률 매트릭스</h3>
                <div className="overflow-x-auto rounded-2xl border border-slate-800">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-800 bg-slate-900/80">
                        <th className="px-3 py-2.5 text-left text-slate-500">전략</th>
                        {["단기", "스윙", "중기"].map((h) => <th key={h} className="px-3 py-2.5 text-center text-slate-500">{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {(["conservative", "balanced", "aggressive"] as const).map((m) => (
                        <tr key={m} className="border-b border-slate-900">
                          <td className="px-3 py-3 font-semibold text-slate-300">{modeLabel(m)}</td>
                          {(["short", "swing", "mid"] as const).map((h) => {
                            const s = valDashboard.stats?.[`${m}_${h}`];
                            const wr = s?.winRate;
                            return (
                              <td key={h} className="px-3 py-3 text-center">
                                <div className={`text-base font-bold ${wr == null ? "text-slate-600" : wr >= 55 ? "text-emerald-300" : wr >= 45 ? "text-amber-300" : "text-red-300"}`}>
                                  {wr != null ? `${wr}%` : "—"}
                                </div>
                                <div className="mt-0.5 text-slate-500">{s?.completed ? `${s.wins}/${s.completed}` : `대기 ${s?.pendingCount ?? 0}`}</div>
                                {s?.avgReturn != null && <div className={`text-[10px] font-mono ${s.avgReturn >= 0 ? "text-emerald-400" : "text-red-400"}`}>avg {s.avgReturn >= 0 ? "+" : ""}{s.avgReturn.toFixed(1)}%</div>}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              {Array.isArray(valDashboard.lifecycle) && valDashboard.lifecycle.length > 0 && (
                <div>
                  <h3 className="mb-3 text-sm font-semibold text-slate-300">추천 생애주기</h3>
                  <div className="max-h-96 space-y-2 overflow-y-auto">
                    {valDashboard.lifecycle.map((lc: any) => {
                      const s = String(lc.status || "PENDING");
                      const sc = s === "PENDING" ? "bg-slate-700 text-slate-300" : s.includes("WIN") || s.includes("목표") ? "bg-emerald-700 text-white" : s.includes("LOSS") || s.includes("손절") ? "bg-red-700 text-white" : "bg-blue-700 text-white";
                      return (
                        <div key={lc.predictionId} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2 text-[11px]">
                          <div className="min-w-0 flex-1">
                            <span className="font-semibold text-slate-200">{lc.name || lc.symbol}</span>
                            <span className="ml-1.5 text-slate-500">{lc.symbol} · {modeLabel(lc.mode as Mode)} · {horizonLabel(lc.horizon as Horizon)}</span>
                          </div>
                          <div className="flex shrink-0 items-center gap-2">
                            <span className="text-slate-500">{String(lc.createdAt || "").slice(0, 10)}</span>
                            {lc.returnPct != null && <span className={`font-mono ${lc.returnPct >= 0 ? "text-emerald-300" : "text-red-300"}`}>{lc.returnPct >= 0 ? "+" : ""}{lc.returnPct.toFixed(1)}%</span>}
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
