"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { mone } from "@/lib/api";

function dedupe(items: any[]) {
  const seen = new Set<string>();
  const out: any[] = [];
  for (const item of items || []) {
    const symbol = String(item.symbol || item.code || item.ticker || "").toUpperCase();
    const market = String(item.market || (symbol.match(/^\d{6}$/) ? "kr" : "us")).toLowerCase();
    const key = `${market}-${symbol}`;
    if (!symbol || seen.has(key)) continue;
    seen.add(key);
    out.push({ ...item, symbol, market });
  }
  return out;
}

function displayName(item: any) {
  const symbol = String(item.symbol || "").toUpperCase();
  const name = String(item.name || item.company || "").trim();
  return name && name !== symbol ? name : symbol;
}

export default function HomePage() {
  const [holdings, setHoldings] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await mone.holdingsClean({ market: "all", limit: 50 });
      setHoldings(dedupe(Array.isArray(data.items) ? data.items : []));
      setSummary(data.summary || null);
    } catch {
      setHoldings([]);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const topHoldings = holdings.slice(0, 5);
  const riskCount = useMemo(
    () => holdings.filter((item) => ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""))).length,
    [holdings]
  );
  const missingCount = useMemo(
    () => holdings.filter((item) => Array.isArray(item.missingFields) && item.missingFields.length > 0).length,
    [holdings]
  );

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">시장 홈</h1>
          <p className="mt-1 text-sm text-slate-400">
            보유종목, 위험 신호, 현재 포트폴리오 상태를 요약해서 보여줍니다.
          </p>
        </div>

        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric label="보유종목" value={holdings.length} />
        <Metric label="위험/주의 종목" value={summary?.riskCount ?? riskCount} />
        <Metric label="데이터 누락" value={summary?.missingCount ?? missingCount} />
        <Metric label="총 평가손익" value={summary?.totalPnlText ?? "0"} accent />
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">주요 보유종목</h2>
            <p className="text-sm text-slate-500">
              정리된 보유종목 데이터를 기준으로 표시합니다.
            </p>
          </div>

          <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">
            {loading ? "불러오는 중" : "준비됨"}
          </span>
        </div>

        {loading ? (
          <div className="py-12 text-center text-slate-500">보유종목을 불러오는 중...</div>
        ) : topHoldings.length === 0 ? (
          <div className="py-12 text-center text-slate-500">표시할 보유종목이 없습니다.</div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {topHoldings.map((item) => (
              <div
                key={`${item.market}-${item.symbol}`}
                className="rounded-xl border border-slate-800 bg-slate-950/50 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-slate-100">
                      {displayName(item)}
                    </div>
                    <div className="mt-1 font-mono text-xs text-slate-500">
                      {item.symbol} · {String(item.market || "").toUpperCase()}
                    </div>
                  </div>

                  <span className="rounded-full border border-slate-700 px-2 py-1 text-xs text-slate-400">
                    {item.riskStatus || "정상"}
                  </span>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <Info label="수량" value={item.quantity ?? "-"} />
                  <Info label="현재가" value={item.currentPriceText ?? "현재가 산출 필요"} />
                  <Info label="전일 종가" value={item.prevCloseText ?? "-"} />
                  <Info label="등락률" value={item.changePctText ?? "-"} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: any;
  accent?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-2 text-xl font-bold ${accent ? "text-emerald-400" : "text-slate-100"}`}>
        {value}
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <div className="text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-slate-200">{value}</div>
    </div>
  );
}
