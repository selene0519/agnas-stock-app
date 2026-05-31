"use client";

import { useEffect, useMemo, useState } from "react";
import { ExternalLink } from "lucide-react";
import SymbolSearchSelect, { type MoneSymbol } from "../SymbolSearchSelect";
import { mone, type Market, type Mode } from "@/lib/api";

function Cell({
  label,
  value,
  tone = "normal",
}: {
  label: string;
  value?: string;
  tone?: "normal" | "blue" | "red" | "green" | "amber";
}) {
  const color =
    tone === "blue"
      ? "text-blue-300"
      : tone === "red"
        ? "text-red-400"
        : tone === "green"
          ? "text-emerald-400"
          : tone === "amber"
            ? "text-amber-300"
            : "text-slate-100";

  return (
    <div className="rounded-xl bg-slate-950 p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`font-mono ${color}`}>{value || "-"}</div>
    </div>
  );
}

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

function modeLabel(mode: Mode) {
  if (mode === "conservative") return "보수";
  if (mode === "aggressive") return "공격";
  return "균형";
}

function qtyText(item: any, mode: Mode) {
  if (typeof window === "undefined") return "";
  const cash = Number(window.localStorage.getItem("mone_cash_amount") || "0");
  const price = Number(item.entryPrice || item.entry || item.currentPrice || 0);
  if (!Number.isFinite(cash) || cash <= 0 || !Number.isFinite(price) || price <= 0) return "";
  const ratio = mode === "conservative" ? 0.02 : mode === "aggressive" ? 0.12 : 0.05;
  const qty = Math.floor((cash * ratio) / price);
  return qty > 0 ? `${qty.toLocaleString("ko-KR")}주` : "1주 미만";
}

export default function StocksPage() {
  const [market, setMarket] = useState<Market>("all");
  const [mode, setMode] = useState<Mode>("balanced");
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
      .recommendations({
        market,
        mode,
        horizon: "swing",
        limit: 500,
        watchOnly,
      })
      .then((data) => {
        if (!active) return;
        setItems(dedupe(Array.isArray(data.items) ? data.items : []));
      })
      .catch(() => {
        if (!active) return;
        setItems([]);
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [market, mode, watchOnly]);

  const visible = useMemo(() => {
    if (!selected) return items;
    return items.filter((item) => item.symbol === selected.symbol);
  }, [items, selected]);

  const marketTabs: { id: Market; label: string }[] = [
    { id: "all", label: "전체" },
    { id: "kr", label: "국장" },
    { id: "us", label: "미장" },
  ];

  const modeTabs: { id: Mode; label: string }[] = [
    { id: "conservative", label: "보수" },
    { id: "balanced", label: "균형" },
    { id: "aggressive", label: "공격" },
  ];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">종목 탐색</h1>
        <p className="mt-1 text-sm text-slate-400">
          관심종목과 전체 후보를 시장, 투자 성향 기준으로 탐색합니다.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {marketTabs.map((item) => (
          <button
            key={item.id}
            onClick={() => {
              setMarket(item.id);
              setSelected(null);
            }}
            className={`rounded-xl px-4 py-2 text-sm ${
              market === item.id ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"
            }`}
          >
            {item.label}
          </button>
        ))}

        {modeTabs.map((item) => (
          <button
            key={item.id}
            onClick={() => setMode(item.id)}
            className={`rounded-xl px-4 py-2 text-sm ${
              mode === item.id ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"
            }`}
          >
            {item.label}
          </button>
        ))}

        <button
          onClick={() => setWatchOnly(!watchOnly)}
          className={`rounded-xl px-4 py-2 text-sm ${
            watchOnly ? "bg-amber-500 text-slate-950" : "bg-slate-900 text-slate-400"
          }`}
        >
          관심종목만 보기
        </button>
      </div>

      <SymbolSearchSelect
        market={market}
        watchOnly={watchOnly}
        value={selected?.symbol || ""}
        onChange={setSelected}
      />

      <div className="text-sm text-slate-500">
        {loading
          ? "후보를 불러오는 중..."
          : `표시 ${visible.length.toLocaleString("ko-KR")}개 / 전체 ${items.length.toLocaleString("ko-KR")}개`}
      </div>

      {visible.length === 0 && !loading && (
        <div className="rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
          현재 조건에 맞는 후보가 없습니다. 시장, 관심종목, 투자 성향 필터를 변경해보세요.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {visible.map((item: any, index: number) => {
          const quantity = qtyText(item, mode);
          const missingPrice = !item.currentPriceText || item.currentPriceText === "-";
          return (
            <div
              key={`${item.market}-${item.symbol}-${index}`}
              className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5"
            >
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-bold text-slate-100">
                    {item.isWatch ? "★ " : ""}
                    {displayName(item)}
                  </h3>
                  <p className="font-mono text-sm text-slate-500">
                    {item.symbol} · {String(item.market || market).toUpperCase()}
                  </p>
                  {item.sourceMode || item.sourceHorizon ? (
                    <p className="mt-1 text-[11px] text-slate-600">
                      소스: {item.sourceMode || modeLabel(mode)} / {item.sourceHorizon || "swing"}
                    </p>
                  ) : null}
                </div>

                <div className="flex flex-col items-end gap-1">
                  {item.highlightKeyword && (
                    <span className="rounded bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">
                      {item.highlightKeyword}
                    </span>
                  )}
                  {(item.warning_reason || item.warningReason) && (
                    <span className="rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-400">
                      주의
                    </span>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <Cell label="현재가" value={missingPrice ? "현재가 산출 필요" : item.currentPriceText} tone={missingPrice ? "amber" : "normal"} />
                <Cell label="진입가" value={item.entryText} tone="blue" />
                <Cell label="손절가" value={item.stopText || "산출 필요"} tone={item.stopText ? "red" : "amber"} />
                <Cell label="목표가" value={item.targetText || "산출 필요"} tone={item.targetText ? "green" : "amber"} />
              </div>

              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-slate-500">확률</span>
                <span className="font-mono text-slate-100">{item.probabilityText || "-"}</span>
              </div>
              {quantity && (
                <div className="mt-2 flex items-center justify-between text-sm">
                  <span className="text-slate-500">{modeLabel(mode)} 비중 기준 수량</span>
                  <span className="font-mono text-emerald-300">{quantity}</span>
                </div>
              )}
              {(item.warning_reason || item.warningReason || item.fallbackReason) && (
                <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-200">
                  {item.warning_reason || item.warningReason || item.fallbackReason}
                </div>
              )}
              <button
                type="button"
                className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-bold text-slate-200 hover:bg-slate-700"
                onClick={() => window.location.assign(item.market === "kr" ? "mstock://" : "tossinvest://")}
              >
                <ExternalLink size={13} />
                MTS 열기
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
