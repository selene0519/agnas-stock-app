"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { mone, type Market, type Mode, type Horizon } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { dedupeBySymbol, displayName, horizonLabel, modeLabel, priceText, probabilityText } from "@/lib/moneDisplay";

type TabId = "scanner" | "calculator" | "montecarlo" | "correlation";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="text-base font-semibold text-slate-100">{title}</h2>
      <div className="mt-4">{children}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-2 text-lg font-bold text-slate-100">{value}</div>
    </div>
  );
}

function firstRisk(item: any) {
  const flags = Array.isArray(item.riskFlags) ? item.riskFlags : [];
  if (flags.length) return flags.slice(0, 2).join(", ");
  if (item.financialDataStatus === "DATA_PENDING") {
    const market = String(item.market || "kr").toLowerCase();
    return market === "us" ? "재무 미수집 (Finnhub/SEC 연결 필요)" : "재무 미수집 (DART 연결 필요)";
  }
  const block = String(item.tradeBlockStatus || "").toUpperCase();
  if (block === "CAUTION") return "진입 주의 (RSI 과열 또는 EV 음수)";
  if (block === "BLOCK") return "진입 차단";
  return item.warningReason || item.warning_reason || "특이 리스크 없음";
}

export default function AdvancedPage() {
  const [tab, setTab] = useState<TabId>("scanner");
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [entry, setEntry] = useState(100);
  const [stop, setStop] = useState(96);
  const [target, setTarget] = useState(108);
  const [winRate, setWinRate] = useState(55);
  const [riskPct, setRiskPct] = useState(1);
  const [scanItems, setScanItems] = useState<any[]>([]);
  const [scanCoverage, setScanCoverage] = useState<any>(null);
  const [scanLoading, setScanLoading] = useState(false);

  const rr = useMemo(() => {
    const risk = Math.max(entry - stop, 0);
    const reward = Math.max(target - entry, 0);
    return risk > 0 ? reward / risk : 0;
  }, [entry, stop, target]);

  const expectedValue = useMemo(() => {
    const p = winRate / 100;
    const rewardPct = entry > 0 ? ((target - entry) / entry) * 100 : 0;
    const riskPctValue = entry > 0 ? ((entry - stop) / entry) * 100 : 0;
    return p * rewardPct - (1 - p) * riskPctValue;
  }, [entry, stop, target, winRate]);

  const kelly = useMemo(() => {
    const p = winRate / 100;
    const b = rr;
    if (b <= 0) return 0;
    return Math.max(((p * (b + 1) - 1) / b) * 100, 0);
  }, [winRate, rr]);

  useEffect(() => {
    if (tab !== "scanner") return;
    let active = true;
    setScanLoading(true);
    mone.recommendations({ market, mode, horizon, limit: 40 })
      .then((data) => {
        if (!active) return;
        setScanCoverage(data.scanCoverage || null);
        setScanItems(dedupeBySymbol(Array.isArray(data.items) ? data.items : []).slice(0, 20));
      })
      .finally(() => active && setScanLoading(false));
    return () => {
      active = false;
    };
  }, [tab, market, mode, horizon]);

  const tabs: { id: TabId; label: string }[] = [
    { id: "scanner", label: "스캐너" },
    { id: "calculator", label: "계산기" },
    { id: "montecarlo", label: "몬테카를로" },
    { id: "correlation", label: "상관관계" },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <div>
        <h1 className="text-xl font-bold text-white">고급분석</h1>
        <p className="mt-1 text-xs text-slate-400">추천 API의 퀀트 오버레이를 스캐너로 보고, EV·손익비·포지션 리스크를 점검합니다.</p>
      </div>

      <div className="flex w-fit flex-wrap gap-1 rounded-lg bg-slate-800/50 p-1">
        {tabs.map((item) => (
          <button key={item.id} onClick={() => setTab(item.id)} className={`rounded-md px-4 py-2 text-sm transition-colors ${tab === item.id ? "bg-slate-100 text-slate-950" : "text-slate-400 hover:text-white"}`}>
            {item.label}
          </button>
        ))}
      </div>

      {tab === "scanner" && (
        <Card title="실전 스캐너">
          <div className="mb-4 flex flex-wrap gap-2">
            {(["kr", "us"] as Market[]).map((item) => (
              <button key={item} onClick={() => setMarket(item)} className={`rounded-xl px-3 py-1.5 text-xs ${market === item ? "bg-blue-600 text-white" : "bg-slate-950 text-slate-400"}`}>{marketLabel(item)}</button>
            ))}
            {(["conservative", "balanced", "aggressive"] as Mode[]).map((item) => (
              <button key={item} onClick={() => setMode(item)} className={`rounded-xl px-3 py-1.5 text-xs ${mode === item ? "bg-emerald-600 text-white" : "bg-slate-950 text-slate-400"}`}>{modeLabel(item)}</button>
            ))}
            {(["short", "swing", "mid"] as Horizon[]).map((item) => (
              <button key={item} onClick={() => setHorizon(item)} className={`rounded-xl px-3 py-1.5 text-xs ${horizon === item ? "bg-cyan-600 text-white" : "bg-slate-950 text-slate-400"}`}>{horizonLabel(item)}</button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <Metric label="신호 상태" value={scanLoading ? "불러오는 중" : "추천 API 연결"} />
            <Metric label="리스크 필터" value={`${modeLabel(mode)}·${horizonLabel(horizon)}`} />
            <Metric label="표시 후보" value={`${scanItems.length}개`} />
            <Metric label="기본 시장" value={marketLabel(market)} />
          </div>
          {scanCoverage && (
            <div className={`mt-4 rounded-xl border px-4 py-3 text-sm ${scanCoverage.isFullMarket ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100" : "border-amber-500/30 bg-amber-500/10 text-amber-100"}`}>
              스캔 범위: {scanCoverage.universeScope === "FULL_MARKET_READY" ? "전체시장 준비 완료" : "큐레이션 유니버스"} ·
              로컬 스캔 {Number(scanCoverage.localScanUniverseCount || 0).toLocaleString("ko-KR")}개 ·
              OHLCV {Number(scanCoverage.ohlcvSymbolCount || 0).toLocaleString("ko-KR")}개 ·
              현재가 커버 {Number(scanCoverage.quoteCoveragePct || 0).toFixed(1)}%
              {!scanCoverage.isFullMarket && <span className="ml-2">전체시장 스캔 전환에는 종목 마스터와 현재가/OHLCV 수집 확대가 필요합니다.</span>}
            </div>
          )}
          {!scanLoading && scanItems.length === 0 && (
            <div className="mt-4 rounded-xl border border-dashed border-slate-700 px-5 py-8 text-center text-sm text-slate-500">
              <p>스캐너 결과가 없습니다.</p>
              <p className="mt-1 text-[11px] text-slate-600">추천 파일({modeLabel(mode)}/{horizonLabel(horizon)}/{marketLabel(market)})이 비어있거나 GitHub Actions 실행이 필요합니다.</p>
            </div>
          )}
          <div className="mt-5 overflow-hidden rounded-xl border border-slate-800">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="bg-slate-950/60 text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2">종목</th>
                  <th className="px-3 py-2">전략 태그</th>
                  <th className="px-3 py-2">현재가</th>
                  <th className="px-3 py-2">진입가</th>
                  <th className="px-3 py-2">확률</th>
                  <th className="px-3 py-2">EV</th>
                  <th className="px-3 py-2">리스크</th>
                </tr>
              </thead>
              <tbody>
                {scanItems.map((item) => (
                  <tr key={`${item.market}-${item.symbol}`} className="border-t border-slate-800">
                    <td className="px-3 py-2">
                      <div className="font-semibold text-slate-100">{displayName(item)}</div>
                      <div className="font-mono text-xs text-slate-500">{item.symbol}</div>
                    </td>
                    <td className="px-3 py-2 text-xs text-sky-200">{(item.strategyTagLabels || item.strategyTags || []).slice(0, 2).join(", ") || item.candidateTypeLabel || "-"}</td>
                    <td className="px-3 py-2 font-mono">{priceText(item, "current", "가격 확인")}</td>
                    <td className="px-3 py-2 font-mono text-sky-300">{priceText(item, "entry", "진입 확인")}</td>
                    <td className="px-3 py-2 font-mono text-emerald-300">{probabilityText(item, "확률 확인")}</td>
                    <td className="px-3 py-2 font-mono text-violet-300">{item.expectedValuePct != null ? `${Number(item.expectedValuePct).toFixed(2)}%` : item.expectedValue != null ? `${Number(item.expectedValue).toFixed(2)}%` : "-"}</td>
                    <td className="px-3 py-2 text-xs text-amber-200">{firstRisk(item)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {tab === "calculator" && (
        <Card title="EV 기반 리스크 계산기">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            {[
              ["진입가", entry, setEntry],
              ["손절가", stop, setStop],
              ["목표가", target, setTarget],
              ["승률 %", winRate, setWinRate],
            ].map(([label, value, setter]: any) => (
              <label key={label} className="space-y-2 text-sm text-slate-400">
                {label}
                <input type="number" value={value} onChange={(event) => setter(Number(event.target.value))} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100" />
              </label>
            ))}
          </div>
          <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-4">
            <Metric label="손익비" value={rr.toFixed(2)} />
            <Metric label="기댓값(EV)" value={`${expectedValue.toFixed(2)}%`} />
            <Metric label="켈리 추정" value={`${kelly.toFixed(2)}%`} />
            <Metric label="1회 거래 리스크" value={`${riskPct.toFixed(2)}%`} />
          </div>
          <div className="mt-4">
            <label className="space-y-2 text-sm text-slate-400">
              1회 거래 리스크 %
              <input type="number" value={riskPct} onChange={(event) => setRiskPct(Number(event.target.value))} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 md:w-64" />
            </label>
          </div>
        </Card>
      )}

      {tab === "montecarlo" && (
        <Card title="몬테카를로">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Metric label="시뮬레이션 상태" value="가상운용 수익률 연결 필요" />
            <Metric label="기본 반복 횟수" value="1000" />
            <Metric label="출력" value="리스크 범위" />
          </div>
          <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">
            포트폴리오 단위 시뮬레이션 영역입니다. 백테스트/가상운용 수익률 데이터가 충분히 쌓이면 기본 분포로 사용할 수 있습니다.
          </div>
        </Card>
      )}

      {tab === "correlation" && (
        <Card title="상관관계">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Metric label="시장" value="국장 / 미장" />
            <Metric label="데이터 출처" value="OHLCV" />
            <Metric label="상태" value="상관계수 계산 연결 필요" />
          </div>
          <div className="mt-5 rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-sm text-slate-400">
            상관관계 분석은 정제된 가격 이력을 사용하고, 누락되었거나 오래된 OHLCV 종목은 제외해야 합니다.
          </div>
        </Card>
      )}
    </div>
  );
}
