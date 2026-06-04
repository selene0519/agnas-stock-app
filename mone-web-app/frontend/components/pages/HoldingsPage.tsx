"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Pencil, Plus, RefreshCw, Save, Trash2, X, Zap } from "lucide-react";

type Market = "all" | "kr" | "us";

type EditableHolding = {
  market: "kr" | "us";
  symbol: string;
  name: string;
  quantity: string;
  avgPrice: string;
};

function apiUrl(path: string) { return `/mone-api${path}`; }

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
    method: "POST", cache: "no-store",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const text = await res.text().catch(() => "");
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} ${text.slice(0, 500)}`.trim());
  return text ? JSON.parse(text) : {};
}

function dedupe(items: any[]) {
  const seen = new Set<string>();
  return (items || []).filter((item) => {
    const key = `${item.market}-${item.symbol}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}

function displayName(item: any) {
  const name = String(item.name || item.company || "").trim();
  const sym = String(item.symbol || "").toUpperCase();
  return name && name !== sym ? name : sym;
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
  const m = cleanHoldingMarket(item.market);
  return `${m}-${cleanHoldingSymbol(item.symbol, m)}`;
}
function toEditableHolding(item: any): EditableHolding {
  const market = cleanHoldingMarket(item.market);
  return {
    market,
    symbol: cleanHoldingSymbol(item.symbol, market),
    name: String(item.name || "").trim(),
    quantity: String(item.quantity ?? "").replace(/[^0-9.]/g, ""),
    avgPrice: String(item.avgPrice ?? "").replace(/[^0-9.]/g, ""),
  };
}
function normalizeForSave(item: EditableHolding) {
  const market = cleanHoldingMarket(item.market);
  return {
    market, symbol: cleanHoldingSymbol(item.symbol, market),
    name: item.name.trim(),
    quantity: Number(String(item.quantity).replace(/,/g, "")),
    avgPrice: Number(String(item.avgPrice).replace(/,/g, "")),
  };
}
function validateHoldingDraft(item: EditableHolding) {
  const n = normalizeForSave(item);
  if (!n.symbol) return "종목코드/티커가 필요합니다.";
  if (n.market === "kr" && !/^\d{6}$/.test(n.symbol)) return "국장 종목코드는 6자리여야 합니다.";
  if (!Number.isFinite(n.quantity) || n.quantity <= 0) return "수량은 0보다 커야 합니다.";
  if (!Number.isFinite(n.avgPrice) || n.avgPrice <= 0) return "평균단가는 0보다 커야 합니다.";
  return "";
}
function riskBadgeClass(risk: string) {
  if (risk === "HIGH") return "border-red-500/40 bg-red-500/15 text-red-300";
  if (risk === "WATCH") return "border-amber-500/40 bg-amber-500/15 text-amber-300";
  return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
}
function riskLabel(risk: string) {
  if (risk === "HIGH") return "위험";
  if (risk === "WATCH") return "주의";
  return "정상";
}

// ── NAV 수익률 곡선 (실제/추정 구분) ─────────────────────────────────
function NavCurve() {
  const [navRows, setNavRows] = useState<any[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [kospiRows, setKospiRows] = useState<any[]>([]);

  useEffect(() => {
    fetch("/mone-api/api/portfolio/nav", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setNavRows(Array.isArray(d.items) ? d.items : []))
      .catch(() => setNavRows([]));
    fetch("/mone-api/api/chart/index/KOSPI?market=kr&limit=365", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setKospiRows(Array.isArray(d.items) ? d.items : []))
      .catch(() => setKospiRows([]));
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || navRows.length < 2) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);

    // 실제/추정 분리
    const actual = navRows.filter((r) => String(r.is_backfill || "false").toLowerCase() !== "true");
    const backfill = navRows.filter((r) => String(r.is_backfill || "false").toLowerCase() === "true");
    const allReturns = navRows.map((r) => Number(r.cumulative_return ?? 0));

    const minR = Math.min(...allReturns, 0);
    const maxR = Math.max(...allReturns, 0);
    const range = maxR - minR || 1;
    const pad = { t: 14, b: 22, l: 8, r: 8 };
    const chartW = W - pad.l - pad.r;
    const chartH = H - pad.t - pad.b;

    const dateIndex = new Map(navRows.map((r, i) => [r.date, i]));
    const toX = (date: string) => {
      const i = dateIndex.get(date) ?? 0;
      return pad.l + (i / (navRows.length - 1)) * chartW;
    };
    const toY = (v: number) => pad.t + chartH - ((v - minR) / range) * chartH;

    // 기준선 (0%)
    const zeroY = toY(0);
    ctx.strokeStyle = "#334155"; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(pad.l, zeroY); ctx.lineTo(W - pad.r, zeroY); ctx.stroke();
    ctx.setLineDash([]);

    // KOSPI 비교선 (날짜 기반 join)
    if (kospiRows.length > 2 && navRows.length > 2) {
      const startDate = navRows[0].date;
      const filtered = kospiRows.filter((r) => (r.date || r.Date) >= startDate);
      if (filtered.length > 2) {
        const baseClose = Number(filtered[0].close || filtered[0].Close || 0);
        if (baseClose > 0) {
          // navRows의 날짜 범위에 맞춰 KOSPI 수익률 계산
          const kospiByDate = new Map(
            filtered.map((r) => [
              r.date || r.Date,
              ((Number(r.close || r.Close || 0) - baseClose) / baseClose) * 100,
            ])
          );
          const kospiPoints: [number, number][] = [];
          for (const row of navRows) {
            const kRet = kospiByDate.get(row.date);
            if (kRet !== undefined) kospiPoints.push([toX(row.date), toY(kRet)]);
          }
          if (kospiPoints.length > 2) {
            ctx.strokeStyle = "#64748b80"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
            ctx.beginPath();
            ctx.moveTo(kospiPoints[0][0], kospiPoints[0][1]);
            for (let i = 1; i < kospiPoints.length; i++) ctx.lineTo(kospiPoints[i][0], kospiPoints[i][1]);
            ctx.stroke();
            ctx.setLineDash([]);
          }
        }
      }
    }

    // 추정 백필 구간 (연한 색 + 대시)
    if (backfill.length > 1) {
      ctx.strokeStyle = "#38bdf840"; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
      ctx.beginPath();
      backfill.forEach((row, i) => {
        const x = toX(row.date); const y = toY(Number(row.cumulative_return ?? 0));
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke(); ctx.setLineDash([]);
    }

    // 실제 구간 (solid)
    if (actual.length > 1) {
      const lastReturn = Number(actual.at(-1)?.cumulative_return ?? 0);
      const isPos = lastReturn >= 0;
      ctx.strokeStyle = isPos ? "#22c55e" : "#ef4444";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      actual.forEach((row, i) => {
        const x = toX(row.date); const y = toY(Number(row.cumulative_return ?? 0));
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    // 날짜 레이블
    ctx.fillStyle = "#475569"; ctx.font = "10px monospace";
    ctx.textAlign = "left";
    const firstDate = navRows[0]?.date ?? "";
    const lastDate = navRows.at(-1)?.date ?? "";
    if (firstDate) ctx.fillText(firstDate, pad.l, H - 4);
    if (lastDate) { ctx.textAlign = "right"; ctx.fillText(lastDate, W - pad.r, H - 4); }
  }, [navRows, kospiRows]);

  if (navRows.length < 2) return null;

  const lastRow = navRows.filter((r) => String(r.is_backfill || "false").toLowerCase() !== "true").at(-1)
    ?? navRows.at(-1);
  const cumReturn = Number(lastRow?.cumulative_return ?? 0);
  const isPos = cumReturn >= 0;
  const actualCount = navRows.filter((r) => String(r.is_backfill || "false").toLowerCase() !== "true").length;
  const backfillCount = navRows.length - actualCount;

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-100">NAV 누적 수익률</h2>
        <div className="flex items-center gap-3">
          <span className={`font-mono text-base font-bold ${isPos ? "text-emerald-300" : "text-red-400"}`}>
            {isPos ? "+" : ""}{cumReturn.toFixed(2)}%
          </span>
          <div className="flex items-center gap-2 text-[10px] text-slate-500">
            <span className="flex items-center gap-1">
              <span className="inline-block h-1.5 w-4 rounded bg-emerald-500"></span>
              실제 {actualCount}일
            </span>
            {backfillCount > 0 && (
              <span className="flex items-center gap-1">
                <span className="inline-block h-px w-4 border-t-2 border-dashed border-sky-400/60"></span>
                추정 백필 {backfillCount}일
              </span>
            )}
            {kospiRows.length > 0 && (
              <span className="flex items-center gap-1">
                <span className="inline-block h-px w-4 border-t border-dashed border-slate-500/60"></span>
                KOSPI
              </span>
            )}
          </div>
        </div>
      </div>
      {backfillCount > 0 && (
        <div className="mb-2 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-1.5 text-[10px] text-sky-400">
          ℹ 추정 백필: 현재 보유종목 기준 과거 OHLCV로 역산한 추정값입니다. 실제 과거 포트폴리오 수익률과 다를 수 있습니다.
        </div>
      )}
      <canvas ref={canvasRef} width={800} height={110} className="w-full rounded-lg" style={{ height: "110px" }} />
    </div>
  );
}

// ── 포트폴리오 구성 바 ─────────────────────────────────────────────────
function PortfolioCompositionBar({ items }: { items: any[] }) {
  const sorted = useMemo(() => {
    const withValue = items
      .map((item) => ({ ...item, _val: Number(item.valuation || item.marketValue || 0) }))
      .filter((item) => item._val > 0)
      .sort((a, b) => b._val - a._val);
    const total = withValue.reduce((acc, item) => acc + item._val, 0);
    return { items: withValue, total };
  }, [items]);

  if (sorted.total <= 0) return null;
  const colors = ["bg-blue-500","bg-emerald-500","bg-violet-500","bg-amber-500","bg-cyan-500","bg-rose-500","bg-teal-500","bg-orange-500"];

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">포트폴리오 구성</h2>
      <div className="flex h-4 w-full overflow-hidden rounded-full">
        {sorted.items.map((item, i) => {
          const pct = (item._val / sorted.total) * 100;
          return (
            <div key={`${item.market}-${item.symbol}`}
              className={`${colors[i % colors.length]} transition-all`}
              style={{ width: `${pct}%` }}
              title={`${displayName(item)} ${pct.toFixed(1)}%`} />
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {sorted.items.map((item, i) => {
          const pct = (item._val / sorted.total) * 100;
          return (
            <div key={`${item.market}-${item.symbol}`} className="flex items-center gap-1.5">
              <div className={`h-2 w-2 shrink-0 rounded-full ${colors[i % colors.length]}`} />
              <span className="text-[11px] text-slate-300">{displayName(item)}</span>
              <span className="font-mono text-[11px] text-slate-500">{pct.toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 종목 추가 폼 ───────────────────────────────────────────────────────
function AddHoldingForm({ onSave, onCancel, saving }: { onSave: (d: EditableHolding) => void; onCancel: () => void; saving: boolean }) {
  const [draft, setDraft] = useState<EditableHolding>({ market: "kr", symbol: "", name: "", quantity: "", avgPrice: "" });
  const [error, setError] = useState("");
  function handleSave() {
    const err = validateHoldingDraft(draft);
    if (err) { setError(err); return; }
    setError(""); onSave(draft);
  }
  return (
    <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5">
      <div className="mb-4 text-sm font-bold text-emerald-200">새 보유 종목 추가</div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <label className="text-xs text-slate-400">마켓
          <select value={draft.market} onChange={(e) => setDraft({ ...draft, market: e.target.value as "kr"|"us" })}
            className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400">
            <option value="kr">국장 (KR)</option>
            <option value="us">미장 (US)</option>
          </select>
        </label>
        {(["symbol","name","quantity","avgPrice"] as const).map((field) => (
          <label key={field} className="text-xs text-slate-400">
            {field === "symbol" ? "종목코드/티커" : field === "name" ? "종목명" : field === "quantity" ? "수량" : "평균단가"}
            <input type={field === "quantity" || field === "avgPrice" ? "number" : "text"}
              value={draft[field]}
              onChange={(e) => setDraft({ ...draft, [field]: e.target.value })}
              placeholder={field === "symbol" ? (draft.market === "kr" ? "005930" : "NVDA") : ""}
              className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-400" />
          </label>
        ))}
      </div>
      {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      <div className="mt-4 flex gap-2">
        <button onClick={handleSave} disabled={saving}
          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white hover:bg-emerald-500 disabled:opacity-50">
          <Save size={13} /> 추가
        </button>
        <button onClick={onCancel}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800">
          <X size={13} /> 취소
        </button>
      </div>
    </div>
  );
}

// ── 메인 페이지 ────────────────────────────────────────────────────────
export default function HoldingsPage() {
  const [market, setMarket] = useState<Market>("all");
  const [data, setData] = useState<any>({ items: [], summary: {} });
  const [loading, setLoading] = useState(false);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<EditableHolding | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [addSaving, setAddSaving] = useState(false);
  const [sectorData, setSectorData] = useState<any>(null);
  const [benchmarkData, setBenchmarkData] = useState<any>(null);
  const [corrData, setCorrData] = useState<any>(null);

  async function load() {
    setLoading(true);
    const m = market === "all" ? "kr" : market;
    try {
      // 보유목록 먼저 — 빠르게 표시
      const result = await getJson(`/api/holdings-clean?market=${market}&limit=500`);
      setData(result);
      setLoading(false);
      // 리스크 데이터는 백그라운드 로딩
      Promise.all([
        getJson(`/api/risk/sector-exposure?market=${m}`).catch(() => null),
        getJson(`/api/risk/benchmark?market=${m}`).catch(() => null),
        getJson(`/api/risk/correlation?market=${m}&days=60`).catch(() => null),
      ]).then(([sector, bench, corr]) => {
        setSectorData(sector); setBenchmarkData(bench); setCorrData(corr);
      });
    } catch (error) {
      setData({ status: "ERROR", error: String(error), items: [], summary: {} });
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // 백그라운드 현재가 새로고침
    const m = market === "all" ? "kr" : market;
    postJson("/api/quotes/refresh-targets", { market: m, limit: 30 })
      .then(() => load())
      .catch(() => {});
  }, [market]);

  async function loadEditableHoldings() {
    const result = await getJson("/api/holdings-edit?market=all");
    return Array.isArray(result.items) ? result.items.map(toEditableHolding) : [];
  }

  async function saveRows(nextRows: any[], successMsg: string) {
    const result = await postJson("/api/holdings-edit/save", { items: nextRows });
    if (result?.status === "ERROR") throw new Error(result.error || "저장 실패");
    setMessage(successMsg);
    await load();
  }

  async function saveEdit(original: any) {
    if (!editDraft) return;
    const err = validateHoldingDraft(editDraft);
    if (err) { setMessage(err); return; }
    const key = editableKey(original);
    setSavingKey(key); setMessage("");
    try {
      const rows = await loadEditableHoldings();
      const n = normalizeForSave(editDraft);
      const nextRows = rows.filter((r) => editableKey(r) !== key)
        .concat([{ market: n.market, symbol: n.symbol, name: n.name, quantity: String(n.quantity), avgPrice: String(n.avgPrice) }]);
      await saveRows(nextRows, "보유종목을 저장했습니다.");
      setEditKey(null); setEditDraft(null);
    } catch (error) {
      setMessage(`저장 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setSavingKey(null); }
  }

  async function deleteHolding(holding: any) {
    const key = editableKey(holding);
    if (typeof window !== "undefined" && !window.confirm(`${displayName(holding)} 보유종목을 삭제할까요?`)) return;
    setSavingKey(key); setMessage("");
    try {
      const rows = await loadEditableHoldings();
      const nextRows = rows.filter((r) => editableKey(r) !== key);
      await saveRows(nextRows, "보유종목을 삭제했습니다.");
      if (editKey === key) { setEditKey(null); setEditDraft(null); }
    } catch (error) {
      setMessage(`삭제 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setSavingKey(null); }
  }

  async function refreshOneQuote(holding: any) {
    const key = editableKey(holding);
    setSavingKey(key); setMessage("");
    try {
      const res = await postJson("/api/quotes/refresh-one", { symbol: holding.symbol, market: holding.market, name: displayName(holding) });
      if (res?.status === "OK" || res?.quote?.ok) {
        setMessage(`${displayName(holding)} 현재가 새로고침 완료`);
        await load();
      } else {
        setMessage(`현재가 조회 실패: ${res?.error || res?.quote?.error || "알 수 없는 오류"}`);
      }
    } catch (error) {
      setMessage(`새로고침 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setSavingKey(null); }
  }

  async function addHolding(draft: EditableHolding) {
    setAddSaving(true); setMessage("");
    try {
      const rows = await loadEditableHoldings();
      const n = normalizeForSave(draft);
      const key = `${n.market}-${n.symbol}`;
      const nextRows = rows.filter((r) => editableKey(r) !== key)
        .concat([{ market: n.market, symbol: n.symbol, name: n.name, quantity: String(n.quantity), avgPrice: String(n.avgPrice) }]);
      await saveRows(nextRows, `${n.name || n.symbol} 종목을 추가했습니다.`);
      setShowAdd(false);
    } catch (error) {
      setMessage(`추가 실패: ${error instanceof Error ? error.message : String(error)}`);
    } finally { setAddSaving(false); }
  }

  const items = useMemo(() => dedupe(Array.isArray(data.items) ? data.items : []), [data.items]);
  const summary = data.summary || {};
  const riskCount = items.filter((item) => ["HIGH","WATCH"].includes(String(item.riskStatus || ""))).length;
  const totalValueText = summary.totalValueText || (items.length > 0 ?
    items.reduce((acc: number, item: any) => acc + Number(item.valuation || item.marketValue || 0), 0).toLocaleString("ko-KR") + "원" : "-");

  return (
    <div className="space-y-6 p-6">
      {/* 헤더 */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">보유·리스크</h1>
          <p className="mt-1 text-sm text-slate-400">보유종목 현황, 리스크 지표, 포트폴리오 구성 분석</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => { setShowAdd(!showAdd); setMessage(""); }}
            className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500">
            <Plus size={14} /> 종목 추가
          </button>
          <button onClick={load}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> 새로고침
          </button>
        </div>
      </div>

      {/* 마켓 필터 */}
      <div className="flex gap-2">
        {(["all","kr","us"] as Market[]).map((item) => (
          <button key={item} onClick={() => setMarket(item)}
            className={`rounded-xl px-4 py-2 text-sm font-medium ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400 hover:bg-slate-800"}`}>
            {item === "all" ? "전체" : item === "kr" ? "국장" : "미장"}
          </button>
        ))}
      </div>

      {/* 종목 추가 폼 */}
      {showAdd && <AddHoldingForm onSave={addHolding} onCancel={() => setShowAdd(false)} saving={addSaving} />}

      {/* 메시지 */}
      {message && (
        <div className="flex items-center justify-between rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-300">
          <span>{message}</span>
          <button onClick={() => setMessage("")} className="text-slate-500 hover:text-slate-300"><X size={14} /></button>
        </div>
      )}

      {/* 요약 카드 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <SummaryCard label="평가금액 합계" value={totalValueText} />
        <SummaryCard label="총 평가손익" value={summary.totalPnlText || "-"}
          accent={Number(summary.totalPnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
        <SummaryCard label="보유 종목" value={`${items.length}개`} />
        <SummaryCard label="주의/위험" value={`${riskCount}개`}
          accent={riskCount > 0 ? "text-amber-300" : "text-emerald-300"} />
      </div>

      {data.error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">{data.error}</div>}

      {/* NAV 곡선 */}
      <NavCurve />

      {/* 포트폴리오 구성 바 */}
      {items.length > 0 && <PortfolioCompositionBar items={items} />}

      {/* 벤치마크 비교 */}
      {benchmarkData?.status === "OK" && Array.isArray(benchmarkData.items) && benchmarkData.items.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-slate-100">벤치마크 비교 ({benchmarkData.benchmark})</h2>
              <p className="text-xs text-slate-500">{benchmarkData.benchmarkLatestDate} 기준</p>
            </div>
            <div className={`font-mono text-base font-bold ${benchmarkData.totalPortfolioReturn >= 0 ? "text-emerald-300" : "text-red-300"}`}>
              포트 {benchmarkData.totalPortfolioReturn >= 0 ? "+" : ""}{benchmarkData.totalPortfolioReturn?.toFixed(1)}%
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead><tr className="border-b border-slate-800 text-slate-500">
                <th className="pb-2 text-left">종목</th>
                <th className="pb-2 text-right">내 수익률</th>
                <th className="pb-2 text-right">{benchmarkData.benchmark}</th>
                <th className="pb-2 text-right">알파</th>
              </tr></thead>
              <tbody>
                {benchmarkData.items.map((item: any) => (
                  <tr key={item.symbol} className="border-b border-slate-900">
                    <td className="py-1.5 pr-3"><div className="font-medium text-slate-200">{item.name}</div><div className="text-slate-500">{item.symbol}</div></td>
                    <td className={`py-1.5 pr-3 text-right font-mono ${(item.portfolioReturn ?? 0) >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                      {item.portfolioReturn >= 0 ? "+" : ""}{item.portfolioReturn?.toFixed(1)}%
                    </td>
                    <td className="py-1.5 pr-3 text-right font-mono text-slate-400">
                      {item.benchmarkReturn != null ? `${item.benchmarkReturn >= 0 ? "+" : ""}${item.benchmarkReturn.toFixed(1)}%` : "—"}
                    </td>
                    <td className={`py-1.5 text-right font-mono font-semibold ${(item.alpha ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {item.alpha != null ? `${item.alpha >= 0 ? "+" : ""}${item.alpha.toFixed(1)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 상관관계 */}
      {corrData?.status === "OK" && Array.isArray(corrData.matrix) && corrData.matrix.length > 0 && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100">종목 간 상관관계 (60일)</h2>
            {corrData.warning && <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">⚠ 높은 상관 쌍</span>}
          </div>
          <div className="max-h-48 space-y-1.5 overflow-y-auto">
            {corrData.matrix.slice(0, 15).map((pair: any) => (
              <div key={`${pair.sym1}-${pair.sym2}`} className="flex items-center justify-between rounded-lg bg-slate-950/50 px-3 py-1.5 text-[11px]">
                <span className="text-slate-300">{pair.name1} <span className="text-slate-500">vs</span> {pair.name2}</span>
                <div className="flex items-center gap-2">
                  <div className="w-20 overflow-hidden rounded-full bg-slate-800">
                    <div className={`h-1.5 rounded-full ${Math.abs(pair.corr) >= 0.7 ? "bg-red-500" : Math.abs(pair.corr) >= 0.4 ? "bg-amber-500" : "bg-emerald-500"}`}
                      style={{ width: `${Math.abs(pair.corr) * 100}%` }} />
                  </div>
                  <span className={`w-10 text-right font-mono ${Math.abs(pair.corr) >= 0.7 ? "text-red-300" : Math.abs(pair.corr) >= 0.4 ? "text-amber-300" : "text-emerald-300"}`}>
                    {pair.corr > 0 ? "+" : ""}{pair.corr.toFixed(2)}
                  </span>
                  <span className="text-slate-500">{pair.level}</span>
                </div>
              </div>
            ))}
          </div>
          {corrData.highCorrelationPairs?.length > 0 && (
            <p className="mt-2 text-[10px] text-amber-400">상관계수 0.7↑ 쌍 {corrData.highCorrelationPairs.length}개 — 동일 방향 집중 리스크</p>
          )}
        </div>
      )}

      {/* 섹터 노출도 */}
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
                  <div className="max-w-[120px] truncate text-[11px] font-semibold text-slate-200">{s.sector}</div>
                  <div className="mt-0.5 font-mono text-sm font-bold text-white">{s.pct.toFixed(1)}%</div>
                  <div className="text-[10px] text-slate-300">{s.symbols.slice(0, 2).join(", ")}{s.symbols.length > 2 ? ` 외 ${s.symbols.length - 2}` : ""}</div>
                </div>
              );
            })}
          </div>
          {sectorData.maxLossSimulation && (
            <div className="mt-4 rounded-xl border border-red-800/30 bg-red-950/20 p-3 text-[11px]">
              <span className="font-semibold text-red-300">전 종목 손절 시뮬레이션</span>
              <span className="ml-3 font-mono font-bold text-red-300">
                {sectorData.maxLossSimulation.totalLoss.toLocaleString()}원 ({sectorData.maxLossSimulation.totalLossPct.toFixed(1)}%)
              </span>
            </div>
          )}
        </div>
      )}

      {/* 보유종목 카드 */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {items.map((holding: any) => {
          const key = editableKey(holding);
          const isEditing = editKey === key && !!editDraft;
          const stopMissing = !holding.stopText || holding.stopText === "-";
          const targetMissing = !holding.targetText || holding.targetText === "-";
          const stopGapPct = holding.stopGapPct != null ? Number(holding.stopGapPct) : null;
          const targetGapPct = holding.targetGapPct != null ? Number(holding.targetGapPct) : null;
          return (
            <div key={`${holding.market}-${holding.symbol}`} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-slate-100">{displayName(holding)}</h2>
                    <span className="font-mono text-xs text-slate-500">{holding.symbol}</span>
                    <span className="rounded-md bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">{holding.market === "kr" ? "국장" : "미장"}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(() => {
                      const status = String(holding.dataStatus || "");
                      const missing = Array.isArray(holding.missingFields) ? holding.missingFields : [];
                      if (status === "OK") return <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-400">현재가 정상</span>;
                      if (!holding.currentPrice || holding.currentPrice <= 0) return <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">현재가 없음</span>;
                      if (missing.length > 0) return <span className="rounded-md border border-slate-600/40 bg-slate-700/20 px-2 py-0.5 text-[10px] text-slate-400">OHLCV 기준가 ({missing.slice(0,2).join("·")} 없음)</span>;
                      return <span className="rounded-md border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] text-blue-300">부분 데이터</span>;
                    })()}
                    {holding.quoteSource && <span className="text-[10px] text-slate-600">출처: {holding.quoteSource}</span>}
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  <span className={`rounded-xl border px-2.5 py-1 text-xs font-bold ${riskBadgeClass(holding.riskStatus)}`}>
                    {riskLabel(holding.riskStatus)}
                  </span>
                  {!isEditing && (
                    <>
                      <button onClick={() => refreshOneQuote(holding)} disabled={savingKey === key}
                        className="inline-flex items-center gap-1 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-300 hover:bg-blue-500/20 disabled:opacity-50" title="현재가 새로고침">
                        <Zap size={11} />
                      </button>
                      <button onClick={() => { setEditKey(key); setEditDraft(toEditableHolding(holding)); setMessage(""); }}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800">
                        <Pencil size={11} /> 수정
                      </button>
                      <button onClick={() => deleteHolding(holding)} disabled={savingKey === key}
                        className="inline-flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1 text-xs text-red-300 hover:bg-red-500/20 disabled:opacity-50">
                        <Trash2 size={11} /> 삭제
                      </button>
                    </>
                  )}
                </div>
              </div>

              {isEditing && editDraft && (
                <div className="mt-4 rounded-2xl border border-blue-500/30 bg-blue-500/10 p-4">
                  <div className="mb-3 text-sm font-bold text-blue-200">보유종목 수정</div>
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    {(["name","symbol","quantity","avgPrice"] as const).map((field) => (
                      <label key={field} className="text-xs text-slate-400">
                        {field === "name" ? "종목명" : field === "symbol" ? "종목코드/티커" : field === "quantity" ? "수량" : "평균단가"}
                        <input type={field === "quantity" || field === "avgPrice" ? "number" : "text"}
                          value={editDraft[field]}
                          onChange={(e) => setEditDraft({ ...editDraft, [field]: e.target.value })}
                          className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-blue-400" />
                      </label>
                    ))}
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button onClick={() => saveEdit(holding)} disabled={savingKey === key}
                      className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:opacity-50">
                      <Save size={12} /> 저장
                    </button>
                    <button onClick={() => { setEditKey(null); setEditDraft(null); }}
                      className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800">
                      <X size={12} /> 취소
                    </button>
                  </div>
                </div>
              )}

              {(stopMissing || targetMissing) && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {stopMissing && <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">손절가 필요</span>}
                  {targetMissing && <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-300">목표가 필요</span>}
                </div>
              )}

              <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
                <Mini label="수량" value={String(holding.quantity || "-")} />
                <Mini label="평단" value={holding.avgPriceText || "-"} />
                <Mini label="현재가" value={holding.currentPriceText || "수집 대기"} />
                <Mini label="등락률" value={holding.changePctText || "-"}
                  accent={String(holding.changePctText || "").startsWith("-") ? "text-red-300" : "text-emerald-300"} />
                <Mini label="평가금액" value={holding.valuationText || holding.marketValueText || "-"} />
                <Mini label="손익" value={holding.pnlText || "0"}
                  accent={Number(holding.pnl || 0) >= 0 ? "text-emerald-300" : "text-red-300"} />
                <Mini label="손절가" value={holding.stopText || "-"} accent={stopMissing ? "text-amber-300" : "text-red-300"} />
                <Mini label="목표가" value={holding.targetText || "-"} accent={targetMissing ? "text-amber-300" : "text-emerald-300"} />
              </div>

              <div className="mt-4 space-y-2">
                <div className="rounded-xl bg-slate-950 px-3 py-2.5">
                  <div className="flex justify-between text-[10px] text-slate-400">
                    <span>손절 여유</span>
                    <span className="font-mono">{stopGapPct === null ? "손절가 없음" : `${stopGapPct.toFixed(2)}% 여유`}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div className={`h-full rounded-full ${stopGapPct !== null && stopGapPct <= 2 ? "bg-red-500" : stopGapPct !== null && stopGapPct <= 5 ? "bg-amber-400" : "bg-emerald-500"}`}
                      style={{ width: `${Math.max(4, Math.min(100, (stopGapPct ?? 0) * 8))}%` }} />
                  </div>
                </div>
                {targetGapPct !== null && targetGapPct > 0 && (
                  <div className="rounded-xl bg-slate-950 px-3 py-2.5">
                    <div className="flex justify-between text-[10px] text-slate-400">
                      <span>목표 여유</span>
                      <span className="font-mono">{targetGapPct.toFixed(2)}% 남음</span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                      <div className="h-full rounded-full bg-blue-500" style={{ width: `${Math.max(4, Math.min(100, targetGapPct * 3))}%` }} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {items.length === 0 && !loading && (
          <div className="col-span-full rounded-2xl border border-dashed border-slate-800 p-12 text-center">
            <p className="text-slate-500">보유 종목이 없습니다.</p>
            <button onClick={() => setShowAdd(true)}
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500">
              <Plus size={14} /> 첫 종목 추가하기
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function SummaryCard({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="text-sm text-slate-500">{label}</div>
      <div className={`mt-2 font-mono text-xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

function Mini({ label, value, accent = "text-slate-100" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-xl bg-slate-950 p-3">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className={`mt-1.5 font-mono text-sm font-bold ${accent}`}>{value}</div>
    </div>
  );
}
