"use client";

import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, type Horizon, type Market, type Mode } from "@/lib/api";
import { dedupeBySymbol, displayName, firstText, formatMoney, horizonLabel, modeLabel, priceText, probabilityText, toNumber } from "@/lib/moneDisplay";

function Cell({ label, value, tone = "normal" }: { label: string; value?: string; tone?: "normal" | "blue" | "red" | "green" | "amber" }) {
  const color = tone === "blue" ? "text-blue-300" : tone === "red" ? "text-red-400" : tone === "green" ? "text-emerald-400" : tone === "amber" ? "text-amber-300" : "text-slate-100";
  return (
    <div className="rounded-xl bg-slate-950 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`font-mono ${color}`}>{value || "-"}</div>
    </div>
  );
}

function qtyText(item: any, mode: Mode) {
  if (typeof window === "undefined") return "";
  const cash = Number(window.localStorage.getItem("mone_cash_amount") || "0");
  const price = toNumber(item.entryPrice || item.entry || item.entryText || item.currentPrice || item.currentPriceText);
  if (!Number.isFinite(cash) || cash <= 0 || price === null || price <= 0) return "";
  const ratio = mode === "conservative" ? 0.02 : mode === "aggressive" ? 0.12 : 0.05;
  const qty = Math.floor((cash * ratio) / price);
  return qty > 0 ? `${qty.toLocaleString("ko-KR")}주` : "1주 미만";
}

function adjustedText(item: any, key: "stop" | "target" | "entry", mode: Mode, market: string) {
  const base = toNumber(key === "stop" ? item.stopPrice || item.stop || item.stopText : key === "target" ? item.targetPrice || item.target || item.targetText : item.entryPrice || item.entry || item.entryText);
  const current = toNumber(item.currentPrice || item.currentPriceText || item.entryPrice || item.entryText);
  const price = base ?? current;
  if (price === null || price <= 0) return "-";
  if (key === "entry") return formatMoney(price, market);
  const modeAdj = mode === "conservative" ? (key === "stop" ? 0.985 : 0.97) : mode === "aggressive" ? (key === "stop" ? 0.97 : 1.05) : 1;
  return formatMoney(price * modeAdj, market);
}

export default function StocksPage() {
  const [market, setMarket] = useState<Market>("all");
  const [mode, setMode] = useState<Mode>("balanced");
  const [horizon, setHorizon] = useState<Horizon>("swing");
  const [selected, setSelected] = useState<MoneSymbol | null>(null);
  const [watchOnly, setWatchOnly] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [, setCashVersion] = useState(0);

  useEffect(() => {
    const onCash = () => setCashVersion((value) => value + 1);
    window.addEventListener("mone-cash-updated", onCash);
    return () => window.removeEventListener("mone-cash-updated", onCash);
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    mone
      .recommendations({ market, mode, horizon, limit: 500, watchOnly })
      .then((data) => {
        if (!active) return;
        setItems(dedupeBySymbol(Array.isArray(data.items) ? data.items : []));
      })
      .catch(() => active && setItems([]))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [market, mode, horizon, watchOnly]);

  const visible = useMemo(() => {
    if (!selected) return items;
    return items.filter((item) => item.symbol === selected.symbol && (market === "all" || item.market === market));
  }, [items, selected, market]);

  const marketTabs: { id: Market; label: string }[] = [
    { id: "all", label: "전체" },
    { id: "kr", label: "국장" },
    { id: "us", label: "미장" },
  ];
  const modeTabs: { id: Mode; label: string; desc: string }[] = [
    { id: "conservative", label: "보수", desc: "좁은 손절·안정 우선" },
    { id: "balanced", label: "균형", desc: "기회와 위험 균형" },
    { id: "aggressive", label: "공격", desc: "목표폭·모멘텀 우선" },
  ];
  const horizonTabs: { id: Horizon; label: string; desc: string }[] = [
    { id: "short", label: "단기", desc: "1~3일" },
    { id: "swing", label: "스윙", desc: "3~10일" },
    { id: "mid", label: "중기", desc: "2주 이상" },
  ];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">종목 탐색</h1>
        <p className="mt-1 text-sm text-slate-400">관심종목과 전체 후보를 시장, 투자 성향, 투자 기간 기준으로 탐색합니다.</p>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">시장</div>
        <div className="flex flex-wrap gap-2">
          {marketTabs.map((item) => (
            <button key={item.id} onClick={() => { setMarket(item.id); setSelected(null); }} className={`rounded-xl px-4 py-2 text-sm ${market === item.id ? "bg-blue-600 text-white" : "bg-slate-950 text-slate-400"}`}>{item.label}</button>
          ))}
          <button onClick={() => setWatchOnly(!watchOnly)} className={`rounded-xl px-4 py-2 text-sm ${watchOnly ? "bg-amber-500 text-slate-950" : "bg-slate-950 text-slate-400"}`}>관심종목만 보기</button>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">투자 성향</div>
            <div className="grid grid-cols-3 gap-2">
              {modeTabs.map((item) => (
                <button key={item.id} onClick={() => setMode(item.id)} className={`rounded-xl border p-3 text-left ${mode === item.id ? "border-emerald-500 bg-emerald-500/10 text-white" : "border-slate-800 bg-slate-950 text-slate-400"}`}>
                  <div className="font-bold">{item.label}</div>
                  <div className="mt-1 text-[11px] text-slate-500">{item.desc}</div>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-2 text-xs font-bold uppercase tracking-[0.2em] text-slate-500">투자 기간</div>
            <div className="grid grid-cols-3 gap-2">
              {horizonTabs.map((item) => (
                <button key={item.id} onClick={() => setHorizon(item.id)} className={`rounded-xl border p-3 text-left ${horizon === item.id ? "border-cyan-500 bg-cyan-500/10 text-white" : "border-slate-800 bg-slate-950 text-slate-400"}`}>
                  <div className="font-bold">{item.label}</div>
                  <div className="mt-1 text-[11px] text-slate-500">{item.desc}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <SymbolSearchSelect market={market} watchOnly={watchOnly} value={selected?.symbol || ""} onChange={setSelected} />

      <div className="text-sm text-slate-500">
        {loading ? "후보를 불러오는 중..." : `${modeLabel(mode)} · ${horizonLabel(horizon)} 조건 / 표시 ${visible.length.toLocaleString("ko-KR")}개 / 전체 ${items.length.toLocaleString("ko-KR")}개`}
      </div>

      {visible.length === 0 && !loading && <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">현재 조건에 맞는 후보가 없습니다. 시장, 관심종목, 투자 성향, 기간 필터를 변경해보세요.</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {visible.map((item: any, index: number) => {
          const quantity = qtyText(item, mode);
          const marketValue = String(item.market || market);
          const current = priceText(item, "current", priceText(item, "entry", "가격 확인 필요"));
          const entry = adjustedText(item, "entry", mode, marketValue);
          const stop = adjustedText(item, "stop", mode, marketValue);
          const target = adjustedText(item, "target", mode, marketValue);
          const prob = probabilityText(item, "확률 확인 필요");
          return (
            <div key={`${item.market}-${item.symbol}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-bold text-slate-100">{item.isWatch ? "★ " : ""}{displayName(item)}</h3>
                  <p className="font-mono text-sm text-slate-500">{item.symbol} · {String(item.market || market).toUpperCase()}</p>
                  <p className="mt-1 text-[11px] text-slate-600">요청: {modeLabel(mode)} / {horizonLabel(horizon)} · 소스: {modeLabel(item.sourceMode || item.mode || mode)} / {horizonLabel(item.sourceHorizon || item.horizon || horizon)}</p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300">{item.sourceStatus || "MATCH"}</span>
                  {(item.warning_reason || item.warningReason) && <span className="rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-400">주의</span>}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <Cell label="현재가" value={current} tone={current.includes("확인") ? "amber" : "normal"} />
                <Cell label="진입가" value={entry} tone="blue" />
                <Cell label="손절가" value={stop} tone="red" />
                <Cell label="목표가" value={target} tone="green" />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <Cell label="확률" value={prob} tone="green" />
                <Cell label="예상가" value={priceText(item, "expected", target)} tone="blue" />
              </div>
              {quantity && <div className="mt-2 flex items-center justify-between text-sm"><span className="text-slate-500">{modeLabel(mode)} 비중 기준 수량</span><span className="font-mono text-emerald-300">{quantity}</span></div>}
              {(item.computedFields || item.fallbackReason) && <div className="mt-3 rounded-xl border border-slate-700 bg-slate-950/60 p-3 text-xs text-slate-400">자동/보강: {Array.isArray(item.computedFields) ? item.computedFields.join(", ") : item.fallbackReason || "계산값 포함"}</div>}
              <button type="button" className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-bold text-slate-200 hover:bg-slate-700" onClick={() => window.location.assign(item.market === "kr" ? "mstock://" : "tossinvest://")}>
                <ExternalLink size={13} /> MTS 열기
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
