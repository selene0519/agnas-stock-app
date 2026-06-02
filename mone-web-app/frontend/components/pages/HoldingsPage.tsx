"use client";

import { useEffect, useMemo, useState } from "react";
import { Pencil, RefreshCw, Save, Trash2, X } from "lucide-react";

type Market = "all" | "kr" | "us";

type EditableHolding = {
  market: "kr" | "us";
  symbol: string;
  name: string;
  quantity: string;
  avgPrice: string;
};

function apiUrl(path: string) {
  return `/mone-api${path}`;
}

async function getJson(path: string) {
  const res = await fetch(apiUrl(path), { cache: "no-store" });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText} ${detail}`.trim());
  }
  return res.json();
}

async function postJson(path: string, body: any) {
  const res = await fetch(apiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} ${text.slice(0, 500)}`.trim());
  }
  return text ? JSON.parse(text) : {};
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

function valueText(value: any, fallback = "-") {
  if (value === undefined || value === null || value === "") return fallback;
  if (value === "-") return fallback;
  return String(value);
}

function displayName(item: any) {
  const symbol = String(item.symbol || "").toUpperCase();
  const name = String(item.name || item.company || "").trim();
  return name && name !== symbol ? name : symbol;
}

function cleanHoldingMarket(value: any): "kr" | "us" {
  return String(value || "kr").toLowerCase() === "us" ? "us" : "kr";
}

function cleanHoldingSymbol(symbol: any, market: "kr" | "us") {
  const raw = String(symbol || "").trim();
  if (market === "kr") return raw.replace(/[^0-9]/g, "").padStart(6, "0").slice(-6);
  return raw.toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
}

function editableKey(item: { market?: any; symbol?: any }) {
  const market = cleanHoldingMarket(item.market);
  return `${market}-${cleanHoldingSymbol(item.symbol, market)}`;
}

function numberString(value: any) {
  return String(value ?? "").replace(/[^0-9.]/g, "");
}

function toEditableHolding(item: any): EditableHolding {
  const market = cleanHoldingMarket(item.market);
  return {
    market,
    symbol: cleanHoldingSymbol(item.symbol || item.code || item.ticker, market),
    name: String(item.name || item.company || item.companyName || item.displayName || "").trim(),
    quantity: numberString(item.quantity ?? item.qty ?? ""),
    avgPrice: numberString(item.avgPrice ?? item.avg_price ?? item.averagePrice ?? item.avgPriceText ?? ""),
  };
}

function normalizeForSave(item: EditableHolding) {
  const market = cleanHoldingMarket(item.market);
  return {
    market,
    symbol: cleanHoldingSymbol(item.symbol, market),
    name: item.name.trim(),
    quantity: Number(String(item.quantity).replace(/,/g, "")),
    avgPrice: Number(String(item.avgPrice).replace(/,/g, "")),
  };
}

function validateHoldingDraft(item: EditableHolding) {
  const normalized = normalizeForSave(item);
  if (!normalized.symbol) return "종목코드/티커가 필요합니다.";
  if (normalized.market === "kr" && !/^\d{6}$/.test(normalized.symbol)) return "국장 종목코드는 6자리여야 합니다.";
  if (!Number.isFinite(normalized.quantity) || normalized.quantity <= 0) return "수량은 0보다 커야 합니다.";
  if (!Number.isFinite(normalized.avgPrice) || normalized.avgPrice <= 0) return "평균단가는 0보다 커야 합니다.";
  return "";
}


function riskClass(risk: string) {
  if (risk === "위험" || risk === "HIGH") return "border-red-500/30 bg-red-500/10 text-red-300";
  if (risk === "주의" || risk === "WATCH") return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
}

export default function HoldingsPage() {
  const [market, setMarket] = useState<Market>("all");
  const [data, setData] = useState<any>({ items: [], summary: {} });
  const [loading, setLoading] = useState(false);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [sectorData, setSectorData] = useState<any>(null);
  const [editDraft, setEditDraft] = useState<EditableHolding | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [editMessage, setEditMessage] = useState("");

  async function load() {
    setLoading(true);
    try {
      const m = market === "all" ? "kr" : market;
      const [result, sector] = await Promise.all([
        getJson(`/api/holdings-clean?market=${market}&limit=500`),
        getJson(`/api/risk/sector-exposure?market=${m}`).catch(() => null),
      ]);
      setData(result);
      setSectorData(sector);
    } catch (error) {
      setData({ status: "ERROR", error: String(error), items: [], summary: {} });
    } finally {
      setLoading(false);
    }
  }

  function startEdit(holding: any) {
    setEditKey(editableKey(holding));
    setEditDraft(toEditableHolding(holding));
    setEditMessage("");
  }

  function cancelEdit() {
    setEditKey(null);
    setEditDraft(null);
    setEditMessage("");
  }

  async function loadEditableHoldings() {
    const result = await getJson("/api/holdings-edit?market=all");
    return Array.isArray(result.items) ? result.items.map(toEditableHolding) : [];
  }

  async function saveEdit(original: any) {
    if (!editDraft) return;
    const error = validateHoldingDraft(editDraft);
    if (error) {
      setEditMessage(error);
      return;
    }

    const key = editableKey(original);
    setSavingKey(key);
    setEditMessage("");
    try {
      const rows = await loadEditableHoldings();
      const normalized = normalizeForSave(editDraft);
      const nextRows = rows.filter((row) => editableKey(row) !== key);
      nextRows.push({
        market: normalized.market,
        symbol: normalized.symbol,
        name: normalized.name,
        quantity: String(normalized.quantity),
        avgPrice: String(normalized.avgPrice),
      });
      const result = await postJson("/api/holdings-edit/save", { items: nextRows });
      if (result?.status === "ERROR") throw new Error(result.error || "보유종목 저장 실패");
      setEditKey(null);
      setEditDraft(null);
      setEditMessage("보유종목을 저장했습니다.");
      await load();
    } catch (error) {
      setEditMessage(`저장 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSavingKey(null);
    }
  }

  async function deleteHolding(holding: any) {
    const key = editableKey(holding);
    const label = `${displayName(holding)} ${holding.symbol || ""}`.trim();
    if (typeof window !== "undefined" && !window.confirm(`${label} 보유종목을 삭제할까요?`)) return;

    setSavingKey(key);
    setEditMessage("");
    try {
      const rows = await loadEditableHoldings();
      const nextRows = rows.filter((row) => editableKey(row) !== key);
      const result = await postJson("/api/holdings-edit/save", { items: nextRows });
      if (result?.status === "ERROR") throw new Error(result.error || "보유종목 삭제 실패");
      if (editKey === key) cancelEdit();
      setEditMessage("보유종목을 삭제했습니다.");
      await load();
    } catch (error) {
      setEditMessage(`삭제 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSavingKey(null);
    }
  }

  useEffect(() => {
    load();
  }, [market]);

  const items = useMemo(() => dedupe(Array.isArray(data.items) ? data.items : []), [data.items]);
  const summary = data.summary || {};
  const riskCount = items.filter((item) => ["위험", "주의", "HIGH", "WATCH"].includes(String(item.riskStatus || ""))).length;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">보유·리스크</h1>
          <p className="mt-1 text-sm text-slate-400">
            국장/미장 보유 현황, 중복 제거, 전일 종가 기준 등락률과 손절가 근접도를 확인합니다.
          </p>
          <p className="mt-1 font-mono text-xs text-slate-600">route: {data.routeVersion || data.status || "-"}</p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["all", "kr", "us"] as Market[]).map((item) => (
          <button
            key={item}
            onClick={() => setMarket(item)}
            className={`rounded-xl px-4 py-2 text-sm ${
              market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"
            }`}
          >
            {item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Card label="평가금액 합계" value={summary.totalValueText || "-"} />
        <Card label="총 평가손익" value={summary.totalPnlText || "0"} accent={Number(summary.totalPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
        <Card label="보유 종목" value={`${items.length}개`} />
        <Card label="주의/위험" value={`${riskCount}개`} accent={riskCount > 0 ? "text-amber-300" : "text-emerald-300"} />
      </div>

      {data.error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-red-300">{data.error}</div>}
      {editMessage && <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-300">{editMessage}</div>}

      {/* 리스크 히트맵 */}
      {sectorData && Array.isArray(sectorData.sectors) && sectorData.sectors.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">섹터 노출도 히트맵</h2>
            {sectorData.concentration?.warning && (
              <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">⚠ 집중도 높음 ({sectorData.concentration.top1Pct}%)</span>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {sectorData.sectors.map((s: any) => {
              const intensity = s.pct >= 30 ? "bg-red-700/60" : s.pct >= 20 ? "bg-orange-700/50" : s.pct >= 10 ? "bg-amber-700/40" : "bg-slate-700/50";
              return (
                <div key={s.sector} className={`rounded-xl ${intensity} px-3 py-2 text-center`} style={{ minWidth: `${Math.max(70, s.pct * 3)}px` }}>
                  <div className="text-[11px] font-semibold text-slate-200 truncate max-w-[120px]">{s.sector}</div>
                  <div className="mt-0.5 font-mono text-sm font-bold text-white">{s.pct.toFixed(1)}%</div>
                  <div className="text-[10px] text-slate-300">{s.symbols.slice(0, 2).join(", ")}{s.symbols.length > 2 ? ` 외 ${s.symbols.length - 2}` : ""}</div>
                </div>
              );
            })}
          </div>
          {sectorData.maxLossSimulation && (
            <div className="mt-4 rounded-xl border border-red-800/30 bg-red-950/20 p-3 text-[11px]">
              <span className="font-semibold text-red-300">최대 동시 손실 시뮬레이션</span>
              <span className="ml-2 text-slate-400">(전 종목 손절가 터치 시)</span>
              <span className="ml-3 font-mono font-bold text-red-300">
                {sectorData.maxLossSimulation.totalLoss.toLocaleString()}원 ({sectorData.maxLossSimulation.totalLossPct.toFixed(1)}%)
              </span>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((holding: any) => {
          const stopMissing = !holding.stopText || holding.stopText === "-";
          const targetMissing = !holding.targetText || holding.targetText === "-";
          const key = editableKey(holding);
          const isEditing = editKey === key && editDraft;
          return (
            <div key={`${holding.market}-${holding.symbol}`} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-slate-100">{displayName(holding)}</h2>
                    <span className="font-mono text-xs text-slate-500">{holding.symbol}</span>
                    <span className="rounded-md bg-slate-800 px-2 py-1 text-xs text-slate-400">
                      {holding.market === "kr" ? "한국주식" : "미국주식"}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    출처: {holding.source || "-"} · 현재가: {holding.quoteSource || "-"} · OHLCV: {holding.ohlcvSource || "-"}
                  </p>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <span className={`rounded-xl border px-3 py-1 text-xs font-bold ${riskClass(holding.riskStatus)}`}>
                    {holding.riskStatus || "정상"}
                  </span>
                  {!isEditing ? (
                    <>
                      <button
                        onClick={() => startEdit(holding)}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
                      >
                        <Pencil size={12} /> 수정
                      </button>
                      <button
                        onClick={() => deleteHolding(holding)}
                        disabled={savingKey === key}
                        className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                      >
                        <Trash2 size={12} /> 삭제
                      </button>
                    </>
                  ) : null}
                </div>
              </div>

              {isEditing && editDraft ? (
                <div className="mt-4 rounded-2xl border border-blue-500/30 bg-blue-500/10 p-4">
                  <div className="mb-3 text-sm font-bold text-blue-200">보유종목 수정</div>
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                    <label className="text-xs text-slate-400">
                      종목명
                      <input
                        value={editDraft.name}
                        onChange={(event) => setEditDraft({ ...editDraft, name: event.target.value })}
                        className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                      />
                    </label>
                    <label className="text-xs text-slate-400">
                      종목코드/티커
                      <input
                        value={editDraft.symbol}
                        onChange={(event) => setEditDraft({ ...editDraft, symbol: event.target.value })}
                        className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                      />
                    </label>
                    <label className="text-xs text-slate-400">
                      수량
                      <input
                        type="number"
                        value={editDraft.quantity}
                        onChange={(event) => setEditDraft({ ...editDraft, quantity: event.target.value })}
                        className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                      />
                    </label>
                    <label className="text-xs text-slate-400">
                      평균단가
                      <input
                        type="number"
                        value={editDraft.avgPrice}
                        onChange={(event) => setEditDraft({ ...editDraft, avgPrice: event.target.value })}
                        className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400"
                      />
                    </label>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      onClick={() => saveEdit(holding)}
                      disabled={savingKey === key}
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-50"
                    >
                      <Save size={13} /> 저장
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800"
                    >
                      <X size={13} /> 취소
                    </button>
                  </div>
                </div>
              ) : null}

              {(Array.isArray(holding.missingFields) && holding.missingFields.length > 0) || stopMissing || targetMissing ? (
                <div className="mt-3 flex flex-wrap gap-1">
                  {stopMissing && (
                    <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                      손절가 산출 필요
                    </span>
                  )}
                  {targetMissing && (
                    <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                      목표가 산출 필요
                    </span>
                  )}
                  {(holding.missingFields || []).map((field: string) => (
                    <span key={field} className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">
                      {field} 없음
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                <Mini label="수량" value={valueText(holding.quantity)} />
                <Mini label="현재가" value={valueText(holding.currentPriceText, "현재가 산출 필요")} />
                <Mini label="등락률" value={valueText(holding.changePctText, "+0.00%")} accent={String(holding.changePctText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"} />
                <Mini label="평단" value={valueText(holding.avgPriceText)} />
                <Mini label="평가금액" value={valueText(holding.valuationText, "0")} />
                <Mini label="손익" value={valueText(holding.pnlText, "0")} accent={Number(holding.pnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                <Mini label="손절가" value={valueText(holding.stopText, "산출 필요")} accent={stopMissing ? "text-amber-300" : "text-red-300"} />
                <Mini label="목표가" value={valueText(holding.targetText, "산출 필요")} accent={targetMissing ? "text-amber-300" : "text-emerald-300"} />
              </div>

              <div className="mt-4 rounded-xl bg-slate-950 p-3">
                <div className="flex justify-between text-xs text-slate-400">
                  <span>손절가 근접도</span>
                  <span>
                    {holding.stopGapPct === null || holding.stopGapPct === undefined ? "손절가 없음" : `${Number(holding.stopGapPct).toFixed(2)}% 여유`}
                  </span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800">
                  <div
                    className={`h-full rounded-full ${Number(holding.stopGapPct || 99) <= 3 ? "bg-amber-400" : "bg-emerald-500"}`}
                    style={{ width: `${Math.max(8, Math.min(100, Number(holding.stopGapPct || 0) * 10))}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}

        {items.length === 0 && (
          <div className="col-span-full rounded-2xl border border-dashed border-slate-800 p-12 text-center text-slate-500">
            보유 종목이 없습니다.
          </div>
        )}
      </div>
    </div>
  );
}

function Card({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-2 font-mono text-2xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function Mini({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-xl bg-slate-950 p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-2 font-mono text-base font-bold ${accent}`}>{value}</div>
    </div>
  );
}
