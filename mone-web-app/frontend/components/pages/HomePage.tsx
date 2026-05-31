"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone } from "@/lib/api";
import { dedupeBySymbol, displayName, firstText, priceText, sortByValue } from "@/lib/moneDisplay";

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

export default function HomePage() {
  const [holdings, setHoldings] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const [h, r] = await Promise.all([
        mone.holdingsClean({ market: "all", limit: 50 }),
        mone.recommendations({ market: "all", mode: "balanced", horizon: "swing", limit: 20 }),
      ]);
      setHoldings(dedupeBySymbol(Array.isArray(h.items) ? h.items : []));
      setSummary(h.summary || null);
      setRecommendations(dedupeBySymbol(Array.isArray(r.items) ? r.items : []).slice(0, 5));
    } catch {
      setHoldings([]);
      setSummary(null);
      setRecommendations([]);
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
          <p className="mt-1 text-sm text-slate-400">보유요약, 진입 후보, 위험 신호를 한 화면에서 확인합니다.</p>
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
            <h2 className="text-lg font-semibold text-slate-100">오늘 매수 검토</h2>
            <p className="text-sm text-slate-500">균형·스윙 기준 추천 후보 상위 5개입니다. 세부 변경은 종목 탐색에서 확인합니다.</p>
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
                    <div className="font-mono text-sm text-emerald-300">{firstText(item.probabilityText, item.prob5dText, "확률 확인")}</div>
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
