"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, TrendingUp, Clock, Eye, AlertTriangle, X, Info, Calculator, ArrowRight } from "lucide-react";
import type { PageId } from "../Sidebar";
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

function getSessionCountdown(market: "kr" | "us", now = new Date()): string {
  const { hour, minute } = kstNowParts(now);
  const t = hour * 60 + minute;

  const fmt = (rem: number) => {
    const h = Math.floor(rem / 60);
    const m = rem % 60;
    return h > 0 ? `${h}시간 ${m}분` : `${m}분`;
  };

  if (market === "kr") {
    const open = 9 * 60, close = 15 * 60 + 30;
    if (t < open)  return `국장 시작까지 ${fmt(open - t)}`;
    if (t <= close) return `장마감까지 ${fmt(close - t)}`;
    const nextOpen = (24 + open) - t;   // 다음 날 09:00까지
    return `다음 국장 시작까지 ${fmt(nextOpen)}`;
  }
  // 미장 22:30 ~ 05:00 KST
  const usOpen = 22 * 60 + 30, usClose = 5 * 60;
  if (t < usClose)  return `미장 마감까지 ${fmt(usClose - t)}`;
  if (t < usOpen)   return `미장 시작까지 ${fmt(usOpen - t)}`;
  return `미장 마감까지 ${fmt(24 * 60 - t + usClose)}`;
}

type SessionPhase = "장전" | "장중" | "장마감" | "개장 전" | "마감 후";

function getSessionContext(session: SessionPhase) {
  switch (session) {
    case "장전":   return { focus: "today",    hint: "장 시작 전 — 오늘 진입 후보를 미리 확인하고 알림을 등록하세요." };
    case "장중":   return { focus: "intraday", hint: "장중 — 진입가에 근접한 종목을 우선 확인하세요." };
    case "장마감": return { focus: "review",   hint: "장마감 후 — 오늘 결과를 검증하고 내일 후보를 보강하세요." };
    case "개장 전": return { focus: "today",   hint: "미장 개장 전 — 오늘 미장 진입 후보와 포지션을 점검하세요." };
    case "마감 후": return { focus: "review",  hint: "미장 마감 후 — 결과 검토 및 다음 날 전략을 준비하세요." };
    default:       return { focus: "today",    hint: "오늘 진입 후보와 대기 관찰 종목을 확인하세요." };
  }
}

function getRegimeStance(regime: string, market: "kr" | "us"): string {
  if (regime === "BULL") return market === "kr" ? "균형·공격형 전략 유효" : "성장주 모멘텀 전략 유효";
  if (regime === "BEAR") return market === "kr" ? "보수형 전략 우선 · 포지션 축소" : "방어주·현금 비중 확대";
  return "중립 — 선별적 진입";
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
      {item.financialDataStatus === "DATA_PENDING" && <span className="rounded-full border border-slate-600 bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">재무미확보</span>}
      {item.finReason && item.financialDataStatus !== "DATA_PENDING" && item.finValueScore > 0 && <span className="rounded-full border border-teal-500/30 bg-teal-500/10 px-2 py-0.5 text-[10px] text-teal-300">재무확인</span>}
    </div>
  );
}

// ── 오늘 진입 카드 (상세)
function TodayEntryCard({ item, rank, onSelect }: { item: any; rank: number; onSelect: (item: any) => void }) {
  const ev = Number(item.expectedValue || 0);
  const score = Number(item.finalScore || 0);
  const mode = String(item.mode || item._mode || "");
  const horizon = String(item.horizon || item._horizon || "");

  return (
    <div onClick={() => onSelect(item)} className="relative cursor-pointer rounded-2xl border border-emerald-800/50 bg-gradient-to-br from-emerald-950/30 to-slate-950 p-4 transition-colors hover:border-emerald-600/70 hover:bg-emerald-950/20">
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
function WatchCard({ item, onSelect }: { item: any; onSelect: (item: any) => void }) {
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
    <div onClick={() => onSelect(item)} className="cursor-pointer rounded-xl border border-slate-700/60 bg-slate-900/50 p-3 transition-colors hover:border-amber-700/50 hover:bg-slate-900/80">
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

// ── 포지션 사이징 ──────────────────────────────────────────────────────────────

const MODE_CAPS: Record<string, number> = {
  conservative: 0.05,   // 최대 5%
  balanced:     0.10,   // 최대 10%
  aggressive:   0.15,   // 최대 15%
};

interface SizingRow {
  symbol:   string;
  name:     string;
  mode:     string;
  horizon:  string;
  entry:    number;
  prob:     number;      // 0~1
  rr:       number;
  kelly:    number;      // full kelly fraction
  halfKelly: number;     // capped half kelly
  amount:   number;      // 원화 금액
  qty:      number;
  ev:       number;
}

function calcSizing(items: any[], capital: number): SizingRow[] {
  const seen = new Set<string>();
  return items
    .filter((i) => i.decisionBucket === "오늘 진입")
    .flatMap((i) => {
      const key = `${i.symbol}-${i._mode}-${i._horizon}`;
      if (seen.has(key)) return [];
      seen.add(key);

      const entry = Number(i.entry || i.entryPrice || 0);
      const prob  = Math.min(Math.max(Number(i.probability || 55) / 100, 0.3), 0.8);
      const rr    = Math.max(Number(i.rrActual || i.rr || 1.5), 0.5);
      const mode  = String(i._mode || i.mode || "balanced");
      if (entry <= 0 || capital <= 0) return [];

      const kelly    = Math.max(0, prob - (1 - prob) / rr);
      const cap      = MODE_CAPS[mode] ?? 0.10;
      const halfKelly = Math.min(kelly / 2, cap);
      const amount   = Math.floor(capital * halfKelly);
      const qty      = Math.floor(amount / entry);

      return [{
        symbol: String(i.symbol || ""),
        name:   String(i.name || i.companyName || i.symbol || ""),
        mode,
        horizon: String(i._horizon || i.horizon || ""),
        entry,
        prob,
        rr,
        kelly,
        halfKelly,
        amount: qty * entry,
        qty,
        ev: Number(i.expectedValue || 0),
      }];
    })
    .sort((a, b) => b.halfKelly - a.halfKelly);
}

function PositionSizingSection({
  items,
  capital,
  setCapital,
}: {
  items: any[];
  capital: number;
  setCapital: (v: number) => void;
}) {
  const [inputVal, setInputVal] = useState(capital > 0 ? String(capital) : "");

  function handleCapitalChange(raw: string) {
    const clean = raw.replace(/[^0-9]/g, "");
    setInputVal(clean);
    const n = Number(clean);
    if (n >= 100_000) {
      setCapital(n);
      if (typeof window !== "undefined") window.localStorage.setItem("mone:capital", String(n));
    }
  }

  const rows = useMemo(() => calcSizing(items, capital), [items, capital]);
  const totalAllocated = rows.reduce((s, r) => s + r.amount, 0);
  const allocPct = capital > 0 ? (totalAllocated / capital) * 100 : 0;
  const remaining = capital - totalAllocated;

  if (rows.length === 0 && capital <= 0) return null;

  return (
    <section className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Calculator size={18} className="text-violet-400 shrink-0" />
        <div className="flex-1">
          <h2 className="text-base font-semibold text-slate-100">포지션 사이징</h2>
          <p className="text-xs text-slate-500">Half-Kelly 공식으로 종목별 적정 투자금을 계산합니다.</p>
        </div>
        {/* 자본 입력 */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">총 자본</span>
          <input
            type="text"
            inputMode="numeric"
            placeholder="예: 10000000"
            value={inputVal ? Number(inputVal).toLocaleString() : ""}
            onChange={(e) => handleCapitalChange(e.target.value.replace(/,/g, ""))}
            className="w-36 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-right font-mono text-sm text-slate-100 placeholder-slate-600 focus:border-violet-500 focus:outline-none"
          />
          <span className="text-xs text-slate-500">원</span>
        </div>
      </div>

      {capital <= 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">총 자본을 입력하면 종목별 권장 수량과 금액을 계산합니다.</div>
      ) : rows.length === 0 ? (
        <div className="py-6 text-center text-sm text-slate-500">오늘 진입 후보가 없습니다.</div>
      ) : (
        <>
          {/* 포트폴리오 요약 바 */}
          <div className="mb-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
            <div className="mb-2 flex justify-between text-[11px] text-slate-400">
              <span>총 배분: <span className="font-mono text-slate-200">{totalAllocated.toLocaleString()}원</span> ({allocPct.toFixed(1)}%)</span>
              <span>잔여 현금: <span className={`font-mono ${remaining >= 0 ? "text-emerald-300" : "text-red-300"}`}>{remaining.toLocaleString()}원</span></span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
              <div
                className={`h-2 rounded-full transition-all ${allocPct > 90 ? "bg-red-500" : allocPct > 60 ? "bg-amber-500" : "bg-violet-500"}`}
                style={{ width: `${Math.min(100, allocPct)}%` }}
              />
            </div>
            <div className="mt-1.5 flex gap-3 text-[10px] text-slate-500">
              <span>{rows.length}개 종목</span>
              <span>포트폴리오 노출 {allocPct.toFixed(1)}%</span>
              {allocPct > 80 && <span className="text-amber-400">⚠ 집중도 높음 — 분산 권장</span>}
            </div>
          </div>

          {/* 종목별 테이블 */}
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500">
                  <th className="pb-2 text-left font-medium">종목</th>
                  <th className="pb-2 text-left font-medium">전략</th>
                  <th className="pb-2 text-right font-medium">승률</th>
                  <th className="pb-2 text-right font-medium">RR</th>
                  <th className="pb-2 text-right font-medium">½Kelly</th>
                  <th className="pb-2 text-right font-medium">금액</th>
                  <th className="pb-2 text-right font-medium">수량</th>
                  <th className="pb-2 text-right font-medium">EV</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.symbol}-${r.mode}-${r.horizon}`} className="border-b border-slate-900 hover:bg-slate-900/40">
                    <td className="py-2 pr-3">
                      <div className="font-medium text-slate-200">{r.name}</div>
                      <div className="text-slate-500">{r.symbol}</div>
                    </td>
                    <td className="py-2 pr-3 text-slate-400">
                      {modeLabel(r.mode as Mode)}<span className="text-slate-600"> · </span>{horizonLabel(r.horizon as Horizon)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-300">{(r.prob * 100).toFixed(0)}%</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-300">{r.rr.toFixed(1)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-violet-300">{(r.halfKelly * 100).toFixed(1)}%</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-100">{r.amount.toLocaleString()}</td>
                    <td className="py-2 pr-3 text-right font-mono text-slate-100">{r.qty > 0 ? `${r.qty}주` : "—"}</td>
                    <td className={`py-2 text-right font-mono ${r.ev >= 2 ? "text-emerald-300" : r.ev >= 0 ? "text-slate-400" : "text-red-400"}`}>
                      {r.ev >= 0 ? "+" : ""}{r.ev.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-[10px] text-slate-600">
            Half-Kelly = min(max(0, p − (1−p)/RR) ÷ 2, 전략한도)  ·  보수형 최대 5% / 균형형 10% / 공격형 15%  ·  참고용이며 자동주문은 지원하지 않습니다.
          </p>
        </>
      )}
    </section>
  );
}

// ── 운용 일지 모달 ─────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = { BUY: "매수", SELL: "매도", NOTE: "메모" };
const RESULT_LABELS: Record<string, string> = { WIN: "수익", LOSS: "손실", BREAK_EVEN: "본전", "": "미입력" };

function JournalModal({ onClose }: { onClose: () => void }) {
  const [entries, setEntries]   = useState<any[]>([]);
  const [loading, setLoading]   = useState(true);
  const [form, setForm]         = useState({ symbol: "", name: "", action: "BUY", price: "", qty: "", memo: "", review: "", result: "", returnPct: "" });
  const [saving, setSaving]     = useState(false);
  const [editId, setEditId]     = useState<string | null>(null);
  const [reviewText, setReviewText] = useState("");

  useEffect(() => {
    mone.journalGet({ market: "all" })
      .then((r) => setEntries(Array.isArray(r.items) ? r.items : []))
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, []);

  async function addEntry() {
    if (!form.memo.trim()) return;
    setSaving(true);
    try {
      const r = await mone.journalAdd({
        symbol: form.symbol, name: form.name, action: form.action,
        price: Number(form.price) || undefined, qty: Number(form.qty) || undefined,
        memo: form.memo, result: form.result,
        returnPct: Number(form.returnPct) || undefined,
      });
      if (r.entry) setEntries((prev) => [r.entry, ...prev]);
      setForm({ symbol: "", name: "", action: "BUY", price: "", qty: "", memo: "", review: "", result: "", returnPct: "" });
    } finally {
      setSaving(false);
    }
  }

  async function saveReview(id: string) {
    await mone.journalUpdate(id, { review: reviewText, result: entries.find((e) => e.id === id)?.result });
    setEntries((prev) => prev.map((e) => e.id === id ? { ...e, review: reviewText } : e));
    setEditId(null);
  }

  async function deleteEntry(id: string) {
    await mone.journalDelete(id);
    setEntries((prev) => prev.filter((e) => e.id !== id));
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col bg-slate-950 shadow-2xl ring-1 ring-slate-800">
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-5 py-4 backdrop-blur">
          <h2 className="font-bold text-slate-100">운용 일지</h2>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-800"><X size={18} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* 새 기록 입력 */}
          <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-4 space-y-3">
            <div className="text-xs font-semibold text-slate-400">새 기록 추가</div>
            <div className="grid grid-cols-3 gap-2">
              {(["BUY", "SELL", "NOTE"] as const).map((a) => (
                <button key={a} onClick={() => setForm((f) => ({ ...f, action: a }))}
                  className={`rounded-lg py-1.5 text-xs font-semibold ${form.action === a ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
                  {ACTION_LABELS[a]}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input placeholder="종목코드" value={form.symbol} onChange={(e) => setForm((f) => ({ ...f, symbol: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
              <input placeholder="종목명" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
              <input placeholder="가격" type="number" value={form.price} onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
              <input placeholder="수량" type="number" value={form.qty} onChange={(e) => setForm((f) => ({ ...f, qty: e.target.value }))}
                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500" />
            </div>
            <textarea placeholder="진입 근거 (최대 100자)" maxLength={100} value={form.memo} onChange={(e) => setForm((f) => ({ ...f, memo: e.target.value }))}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 resize-none" rows={2} />
            <button onClick={addEntry} disabled={saving || !form.memo.trim()}
              className="w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white disabled:opacity-50 hover:bg-blue-700">
              {saving ? "저장 중..." : "기록 추가"}
            </button>
          </div>

          {/* 기록 목록 */}
          {loading ? (
            <div className="text-center text-sm text-slate-500">불러오는 중...</div>
          ) : entries.length === 0 ? (
            <div className="text-center text-sm text-slate-500">기록이 없습니다.</div>
          ) : (
            <div className="space-y-3">
              {entries.map((e) => (
                <div key={e.id} className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-[11px]">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${e.action === "BUY" ? "bg-emerald-800 text-emerald-200" : e.action === "SELL" ? "bg-red-800 text-red-200" : "bg-slate-700 text-slate-300"}`}>{ACTION_LABELS[e.action] ?? e.action}</span>
                      {" "}<span className="font-semibold text-slate-200">{e.name || e.symbol || "—"}</span>
                      {e.price > 0 && <span className="ml-1.5 font-mono text-slate-400">{e.price.toLocaleString()}원</span>}
                      {e.qty > 0 && <span className="ml-1 text-slate-500">{e.qty}주</span>}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-slate-500">{String(e.createdAt || "").slice(0, 10)}</span>
                      <button onClick={() => { setEditId(e.id); setReviewText(e.review || ""); }} className="text-slate-500 hover:text-slate-300">복기</button>
                      <button onClick={() => deleteEntry(e.id)} className="text-slate-600 hover:text-red-400">✕</button>
                    </div>
                  </div>
                  <p className="mt-1.5 text-slate-300">{e.memo}</p>
                  {e.result && <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] ${e.result === "WIN" ? "bg-emerald-900 text-emerald-300" : e.result === "LOSS" ? "bg-red-900 text-red-300" : "bg-slate-800 text-slate-400"}`}>{RESULT_LABELS[e.result] ?? e.result}</span>}
                  {e.returnPct !== 0 && e.returnPct != null && <span className={`ml-1.5 font-mono text-[10px] ${e.returnPct >= 0 ? "text-emerald-400" : "text-red-400"}`}>{e.returnPct >= 0 ? "+" : ""}{e.returnPct.toFixed(1)}%</span>}
                  {e.review && <p className="mt-1.5 border-t border-slate-800 pt-1.5 text-slate-400">복기: {e.review}</p>}
                  {editId === e.id && (
                    <div className="mt-2 space-y-2">
                      <textarea placeholder="청산 후 복기 (뭘 놓쳤나?)" value={reviewText} onChange={(ev) => setReviewText(ev.target.value)}
                        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-slate-100 placeholder-slate-600 focus:outline-none resize-none" rows={2} />
                      <div className="flex gap-2">
                        <button onClick={() => saveReview(e.id)} className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white">저장</button>
                        <button onClick={() => setEditId(null)} className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-400">취소</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── 추천 근거 패널 (슬라이드오버)
const SCORE_ITEMS = [
  { key: "upsideScore",    label: "상승 여력",   color: "bg-emerald-500" },
  { key: "riskScore",      label: "리스크 안정성", color: "bg-sky-500" },
  { key: "momentumScore",  label: "모멘텀",       color: "bg-yellow-500" },
  { key: "entryScore",     label: "진입 접근성",  color: "bg-cyan-500" },
  { key: "rrScore",        label: "손익비",       color: "bg-violet-500" },
  { key: "qualityScore",   label: "기업 안정성",  color: "bg-teal-500" },
];

const SUPPLY_LABEL: Record<string, string> = {
  STRONG_BUY:    "기관+외국인 동시 매수",
  INST_BUY:      "기관 매수 추정",
  SELL_PRESSURE: "매도 압력 감지",
  NEUTRAL:       "중립",
};

const RISK_FLAG_LABEL: Record<string, string> = {
  RSI_OVERHEATED:        "RSI 80+ 과열",
  BOLLINGER_UPPER_BREAK: "볼린저 상단 이탈",
  FIVE_DAY_UP_STREAK:    "5일 연속 상승 후 거래량 감소",
  GAP_UP_15PCT:          "갭상승 15%+ 추격금지",
  EV_NEGATIVE:           "기댓값 음수",
  NEWS_DISCLOSURE_RISK:  "공시/뉴스 리스크",
};

function WhyPanel({ item, onClose }: { item: any; onClose: () => void }) {
  const mode    = String(item.mode || item._mode || "balanced") as Mode;
  const horizon = String(item.horizon || item._horizon || "swing") as Horizon;
  const ev      = Number(item.expectedValue ?? 0);
  const rr      = Number(item.rrActual ?? 0);
  const score   = Number(item.finalScore ?? 0);
  const tags    = Array.isArray(item.strategyTags) ? item.strategyTags : [];
  const riskFlags = Array.isArray(item.riskFlags) ? item.riskFlags : [];
  const decisionBucket = String(item.decisionBucket || "관찰");
  const decisionReason = String(item.decisionReason || "");
  const supplySignal   = String(item.supplySignal || "NEUTRAL");
  const maConv         = Boolean(item.maConvergence);
  const cautionReasons = Array.isArray(item.cautionReasons) ? item.cautionReasons : [];

  const bucketColor =
    decisionBucket === "오늘 진입"  ? "bg-emerald-600 text-white"
    : decisionBucket === "대기 관찰" ? "bg-amber-600 text-white"
    : decisionBucket === "매수금지"  ? "bg-red-700 text-white"
    : "bg-slate-700 text-slate-300";

  // EV 근거 (백엔드 probability 필드 활용)
  const prob = Number(item.probability ?? 0);
  const evBase = prob > 0 ? prob / 100 : null;

  return (
    <>
      {/* 배경 오버레이 */}
      <div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      {/* 패널 */}
      <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col overflow-y-auto bg-slate-950 shadow-2xl ring-1 ring-slate-800">
        {/* 헤더 */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-5 py-4 backdrop-blur">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-slate-100">{displayName(item)}</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${bucketColor}`}>{decisionBucket}</span>
            </div>
            <div className="mt-0.5 text-xs text-slate-500">
              {item.symbol} · {modeLabel(mode)} · {horizonLabel(horizon)}
              {decisionReason && <span className="ml-2 text-slate-400">{decisionReason}</span>}
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 space-y-5 px-5 py-5">
          {/* 가격 그리드 */}
          <div className="grid grid-cols-4 gap-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-center text-[11px]">
            {[
              { label: "현재가", key: "current", color: "text-slate-200" },
              { label: "진입가", key: "entry",   color: "text-sky-300" },
              { label: "손절가", key: "stop",    color: "text-red-300" },
              { label: "목표가", key: "target",  color: "text-emerald-300" },
            ].map(({ label, key, color }) => (
              <div key={key}>
                <div className="text-slate-500">{label}</div>
                <div className={`mt-1 font-mono font-semibold ${color}`}>{priceText(item, key as any, "—")}</div>
              </div>
            ))}
          </div>

          {/* EV + RR 요약 */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-center">
              <div className="text-[10px] text-slate-500">기댓값 EV</div>
              <div className={`mt-1 text-lg font-bold font-mono ${ev >= 2 ? "text-emerald-300" : ev >= 0 ? "text-slate-200" : "text-red-300"}`}>
                {ev >= 0 ? "+" : ""}{ev.toFixed(1)}%
              </div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-center">
              <div className="text-[10px] text-slate-500">손익비 RR</div>
              <div className={`mt-1 text-lg font-bold font-mono ${rr >= 2 ? "text-emerald-300" : rr >= 1.5 ? "text-amber-300" : "text-red-300"}`}>
                {rr > 0 ? rr.toFixed(1) : "—"}
              </div>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-center">
              <div className="text-[10px] text-slate-500">종합 점수</div>
              <div className={`mt-1 text-lg font-bold font-mono ${score >= 65 ? "text-emerald-300" : score >= 50 ? "text-amber-300" : "text-slate-400"}`}>
                {score.toFixed(0)}점
              </div>
            </div>
          </div>

          {/* EV 계산 근거 */}
          {evBase !== null && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px]">
              <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-300">
                <Info size={13} /> EV 계산 근거
              </div>
              <div className="space-y-1 font-mono text-slate-400">
                <div>승률 <span className="text-emerald-400">{(evBase * 100).toFixed(0)}%</span>
                  {" × "}목표 <span className="text-emerald-400">{priceText(item, "target", "—")}</span>
                </div>
                <div>패율 <span className="text-red-400">{((1 - evBase) * 100).toFixed(0)}%</span>
                  {" × "}손절 <span className="text-red-400">{priceText(item, "stop", "—")}</span>
                </div>
                <div className={`border-t border-slate-700 pt-1 font-bold ${ev >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                  EV = {ev >= 0 ? "+" : ""}{ev.toFixed(2)}%
                </div>
              </div>
            </div>
          )}

          {/* 세부 점수 분해 */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
            <div className="mb-3 text-xs font-semibold text-slate-300">점수 분해</div>
            <div className="space-y-2">
              {SCORE_ITEMS.map(({ key, label, color }) => {
                const val = Number((item as any)[key] ?? null);
                if (isNaN(val)) return null;
                return (
                  <div key={key} className="flex items-center gap-2 text-[11px]">
                    <span className="w-20 shrink-0 text-slate-400">{label}</span>
                    <div className="flex-1 overflow-hidden rounded-full bg-slate-800">
                      <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${Math.max(0, Math.min(100, val))}%` }} />
                    </div>
                    <span className="w-8 text-right font-mono text-slate-300">{val.toFixed(0)}</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 전략 태그 */}
          {tags.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
              <div className="mb-2 text-xs font-semibold text-slate-300">전략 태그</div>
              <div className="flex flex-wrap gap-1.5">
                {tags.map((tag: string, ti: number) => {
                  const labelMap: Record<string, string> = {
                    CAUTION:"⚠ 주의", MA_CONVERGENCE:"이격도 수렴", PULLBACK_BUY:"눌림목",
                    MOMENTUM:"모멘텀", VOLUME_BREAKOUT:"거래량 증가", BREAKOUT_52W:"52주 신고가 돌파",
                    NEAR_52W_HIGH:"신고가 근접", BB_SQUEEZE:"볼린저 스퀴즈", STABLE_LOW_RISK:"안정형",
                    UNDERVALUED_GROWTH:"저평가 성장주", GOLDEN_CROSS:"🔼 골든크로스",
                    DEATH_CROSS:"🔽 데드크로스", MID_GOLDEN_CROSS:"📈 중기 골든크로스",
                    MID_DEATH_CROSS:"📉 중기 데드크로스", TRAILING_STOP_ALERT:"⚡ 트레일링 손절",
                  };
                  const colorMap: Record<string, string> = {
                    CAUTION:"border-red-600/40 bg-red-600/10 text-red-300",
                    DEATH_CROSS:"border-red-600/40 bg-red-600/10 text-red-300",
                    MID_DEATH_CROSS:"border-red-700/40 bg-red-700/10 text-red-400",
                    TRAILING_STOP_ALERT:"border-amber-500/40 bg-amber-500/10 text-amber-300",
                    GOLDEN_CROSS:"border-emerald-400/40 bg-emerald-400/10 text-emerald-300",
                    MID_GOLDEN_CROSS:"border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
                    MA_CONVERGENCE:"border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
                    PULLBACK_BUY:"border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
                    MOMENTUM:"border-orange-500/40 bg-orange-500/10 text-orange-300",
                    VOLUME_BREAKOUT:"border-yellow-500/40 bg-yellow-500/10 text-yellow-300",
                    BREAKOUT_52W:"border-violet-500/40 bg-violet-500/10 text-violet-300",
                    NEAR_52W_HIGH:"border-violet-400/30 bg-violet-400/5 text-violet-400",
                    BB_SQUEEZE:"border-sky-500/40 bg-sky-500/10 text-sky-300",
                    STABLE_LOW_RISK:"border-teal-500/40 bg-teal-500/10 text-teal-300",
                    UNDERVALUED_GROWTH:"border-green-500/40 bg-green-500/10 text-green-300",
                  };
                  const tagLabels = Array.isArray(item.strategyTagLabels) ? item.strategyTagLabels as string[] : [];
                  const lbl = labelMap[tag] ?? tagLabels[ti] ?? tag;
                  const cls = colorMap[tag] ?? "border-slate-600 bg-slate-800 text-slate-300";
                  return <span key={tag} className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}>{lbl}</span>;
                })}
              </div>
            </div>
          )}

          {/* MA 수렴 신호 */}
          {maConv && (
            <div className="rounded-xl border border-cyan-800/40 bg-cyan-950/20 p-3 text-[11px] text-cyan-300">
              이격도 수렴 — 5일/20일/60일선이 근접 구간에 있습니다. 변동성 확대 이전 진입 적기입니다.
            </div>
          )}

          {/* 골든크로스 / 데드크로스 배너 */}
          {item.goldenCross && (
            <div className="rounded-xl border border-emerald-700/40 bg-emerald-950/20 p-3 text-[11px] text-emerald-300">
              🔼 골든크로스 — MA5가 MA20을 상향 돌파했습니다. 단기 상승 모멘텀 전환 신호.
            </div>
          )}
          {item.midGoldenCross && (
            <div className="rounded-xl border border-emerald-600/40 bg-emerald-950/20 p-3 text-[11px] text-emerald-200">
              📈 중기 골든크로스 — MA20이 MA60을 상향 돌파했습니다. 중기 추세 전환 신호.
            </div>
          )}
          {item.deathCross && (
            <div className="rounded-xl border border-red-800/40 bg-red-950/20 p-3 text-[11px] text-red-300">
              🔽 데드크로스 — MA5가 MA20을 하향 이탈했습니다. 단기 하락 전환 주의.
            </div>
          )}
          {item.midDeathCross && (
            <div className="rounded-xl border border-red-700/40 bg-red-950/20 p-3 text-[11px] text-red-400">
              📉 중기 데드크로스 — MA20이 MA60을 하향 이탈했습니다. 중기 약세 전환 주의.
            </div>
          )}

          {/* 트레일링 스탑 패널 */}
          {item.trailingStop != null && item.trailingStop > 0 && (
            <div className="rounded-xl border border-amber-800/40 bg-amber-950/20 p-3 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-amber-300">⚡ 트레일링 스탑</span>
                <span className="font-mono text-amber-200">
                  {item.market === "us"
                    ? `$${Number(item.trailingStop).toLocaleString(undefined, {maximumFractionDigits: 2})}`
                    : `${Math.round(Number(item.trailingStop)).toLocaleString()}원`}
                </span>
              </div>
              <div className="mt-1 text-slate-400">
                20일 최고가 기준 ATR×2 하락선 — 현재가로부터{" "}
                {item.trailingStopPct != null ? (
                  <span className={`font-mono font-bold ${Number(item.trailingStopPct) <= 3 ? "text-red-400" : "text-amber-300"}`}>
                    -{Number(item.trailingStopPct).toFixed(1)}%
                  </span>
                ) : "-"}
              </div>
            </div>
          )}

          {/* 수급 신호 */}
          {supplySignal !== "NEUTRAL" && (
            <div className={`rounded-xl border p-3 text-[11px] ${
              supplySignal === "STRONG_BUY" ? "border-blue-600/40 bg-blue-900/20 text-blue-300"
              : supplySignal === "INST_BUY"  ? "border-sky-600/40 bg-sky-900/20 text-sky-300"
              : "border-red-600/40 bg-red-900/20 text-red-300"
            }`}>
              수급 신호 — {SUPPLY_LABEL[supplySignal] ?? supplySignal}
            </div>
          )}

          {/* 리스크 플래그 */}
          {(riskFlags.length > 0 || cautionReasons.length > 0) && (
            <div className="rounded-xl border border-red-800/40 bg-red-950/20 p-4">
              <div className="mb-2 text-xs font-semibold text-red-400">주의사항</div>
              <ul className="space-y-1 text-[11px] text-red-300">
                {riskFlags.map((f: string) => (
                  <li key={f}>• {RISK_FLAG_LABEL[f] ?? f}</li>
                ))}
                {cautionReasons.filter((r: string) => !riskFlags.some((f: string) => RISK_FLAG_LABEL[f] === r)).map((r: string) => (
                  <li key={r}>• {r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ── 3×3 매트릭스 셀 (간결 버전)
function MatrixCell({ cell, onSelect }: { cell: StrategyCell; onSelect: (item: any) => void }) {
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
              <div key={item.symbol} onClick={() => onSelect(item)} className={`flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 transition-colors hover:brightness-125 ${
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
export default function HomePage({ onNavigate }: { onNavigate?: (page: PageId) => void }) {
  const [allItems, setAllItems] = useState<any[]>([]);
  const [matrix, setMatrix] = useState<StrategyCell[]>([]);
  const [holdings, setHoldings] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [marketRegime, setMarketRegime] = useState<any>(null);
  const [dataHealth, setDataHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [marketChoice, setMarketChoice] = useState<MarketChoice>("auto");
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [capital, setCapital] = useState<number>(0);
  const [showJournal, setShowJournal] = useState(false);
  const [clientReady, setClientReady] = useState(false);
  const [clock, setClock] = useState<Date | null>(null);
  const sessionClock = clock || new Date();
  const selectedMarket = marketChoice === "auto" ? (clientReady ? getDefaultMarketBySession(sessionClock) : "kr") : marketChoice;
  const sessionStatus = clientReady ? getMarketSessionStatus(selectedMarket, sessionClock) : "확인 중";
  const sessionPhase = sessionStatus as SessionPhase;
  const countdown = clientReady ? getSessionCountdown(selectedMarket, sessionClock) : "";
  const sessionCtx = getSessionContext(sessionPhase);
  const marketChoiceLabel = clientReady && marketChoice !== "auto" ? "수동" : "자동";

  function updateMarketChoice(next: MarketChoice) {
    setMarketChoice(next);
    if (typeof window !== "undefined") window.localStorage.setItem("mone:selectedMarketMode", next);
  }

  async function load() {
    setLoading(true);
    setMarketRegime(null);
    try {
      // 단일 통합 API 호출 (기존 10회 → 1회)
      const result = await mone.homeSummary({ market: selectedMarket, limit: 12 });

      // matrix: { conservative_short: {items, count, status}, ... } → StrategyCell[]
      const matrixResult: StrategyCell[] = MODES.flatMap((mode) =>
        HORIZONS.map((horizon) => {
          const cell = (result.matrix as any)?.[`${mode}_${horizon}`] || {};
          const items = dedupeBySymbol(Array.isArray(cell.items) ? cell.items : [])
            .slice(0, 5)
            .map((item: any) => ({ ...item, _mode: mode, _horizon: horizon }));
          return { mode, horizon, items, count: Number(cell.count || items.length || 0), status: String(cell.status || "OK") } satisfies StrategyCell;
        })
      );

      const h = result.holdings || {};
      setHoldings(dedupeBySymbol(Array.isArray(h.items) ? h.items : []));
      setSummary(h.summary || null);
      setMatrix(matrixResult);
      setMarketRegime(result.marketRegime || null);
      setDataHealth(result.dataHealth || null);
      setAllItems(matrixResult.flatMap((cell) => cell.items));
    } catch {
      setHoldings([]); setSummary(null); setMatrix([]); setAllItems([]); setDataHealth(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setClientReady(true);
    const saved = window.localStorage.getItem("mone:selectedMarketMode");
    if (saved === "kr" || saved === "us" || saved === "auto") setMarketChoice(saved);
    const savedCapital = Number(window.localStorage.getItem("mone:capital") || 0);
    if (savedCapital >= 100_000) setCapital(savedCapital);
    const refreshClock = () => setClock(new Date());
    refreshClock();
    const timer = window.setInterval(refreshClock, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (clientReady) load();
  }, [clientReady, selectedMarket]);

  // ── 브라우저 알림: 장중 진입 임박 종목 감지 (1분 주기)
  useEffect(() => {
    if (!clientReady) return;
    if (typeof window === "undefined" || !("Notification" in window)) return;

    const notifiedKeys = new Set<string>();

    function checkAndNotify() {
      const phase = getMarketSessionStatus(selectedMarket, new Date()) as SessionPhase;
      if (phase !== "장중") return;                    // 장중에만 작동
      if (Notification.permission !== "granted") return;

      allItems
        .filter((i) => i.decisionBucket === "오늘 진입")
        .forEach((item) => {
          const key = `${item.symbol}-${item._mode}-${item._horizon}`;
          if (notifiedKeys.has(key)) return;

          const current = Number(item.currentPrice || 0);
          const entry   = Number(item.entry || 0);
          if (current <= 0 || entry <= 0) return;

          const gapPct = Math.abs((entry - current) / current * 100);
          if (gapPct <= 2.0) {
            notifiedKeys.add(key);
            new Notification(`🎯 진입 임박 — ${item.name || item.symbol}`, {
              body: `현재가 ${current.toLocaleString()}원  진입가 ${entry.toLocaleString()}원 (±${gapPct.toFixed(1)}%)`,
              tag: key,
            });
          }
        });
    }

    // 권한 요청 후 주기 체크
    Notification.requestPermission().then((perm) => {
      if (perm !== "granted") return;
      checkAndNotify();
      const id = window.setInterval(checkAndNotify, 60_000);
      return () => window.clearInterval(id);
    });
  }, [clientReady, allItems, selectedMarket]);

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
      {/* 추천 근거 패널 */}
      {selectedItem && <WhyPanel item={selectedItem} onClose={() => setSelectedItem(null)} />}
      {/* 운용 일지 모달 */}
      {showJournal && <JournalModal onClose={() => setShowJournal(false)} />}

      {/* 헤더 */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-100">시장 홈</h1>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
            <span>{marketChoiceLabel}: <span className="text-slate-300">{selectedMarket === "kr" ? "국장" : "미장"}</span></span>
            <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
              sessionPhase === "장중" ? "bg-emerald-900/50 text-emerald-300"
              : sessionPhase === "장마감" ? "bg-blue-900/50 text-blue-300"
              : "bg-slate-800 text-slate-400"
            }`}>{sessionStatus}</span>
            {countdown && <span className="flex items-center gap-1 text-slate-400"><Clock size={11} />{countdown}</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {(["auto", "kr", "us"] as MarketChoice[]).map((choice) => (
            <button key={choice} onClick={() => updateMarketChoice(choice)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${marketChoice === choice ? "bg-blue-600 text-white" : "border border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}>
              {choice === "auto" ? "자동" : choice === "kr" ? "국장" : "미장"}
            </button>
          ))}
          <button onClick={() => setShowJournal(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
            일지
          </button>
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
          <span className={`ml-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
            marketRegime.regime === "BULL" ? "bg-emerald-900/50 text-emerald-200"
            : marketRegime.regime === "BEAR" ? "bg-red-900/50 text-red-200"
            : "bg-slate-800 text-slate-300"}`}>
            {getRegimeStance(marketRegime.regime, selectedMarket)}
          </span>
          {marketRegime.regime === "BEAR" && <span className="ml-auto rounded bg-red-900/60 px-2 py-0.5 text-xs text-red-200">공격형 비활성화</span>}
        </div>
      )}

      {/* 데이터 상태 바 */}
      {dataHealth && !loading && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2.5 text-[11px] text-slate-400">
          <span className="flex items-center gap-1">
            <span className={`h-1.5 w-1.5 rounded-full ${(dataHealth.kisLiveCount ?? 0) >= 50 ? "bg-emerald-400" : (dataHealth.kisLiveCount ?? 0) >= 10 ? "bg-amber-400" : "bg-red-400"}`} />
            현재가 <span className="font-mono text-slate-200">{dataHealth.kisLiveCount ?? 0}</span>
            <span className="text-slate-600">/{dataHealth.kisTargetCount ?? 0}</span>
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
            OHLCV <span className="font-mono text-slate-200">{dataHealth.ohlcvCount ?? 0}종목</span>
            {dataHealth.ohlcvLatestDate && <span className="text-slate-500">({dataHealth.ohlcvLatestDate})</span>}
          </span>
          {dataHealth.recoGeneratedAt && (
            <span className="flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
              추천 생성 <span className="font-mono text-slate-300">{String(dataHealth.recoGeneratedAt).slice(0, 16).replace("T", " ")}</span>
            </span>
          )}
          <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-medium ${dataHealth.scanScope === "FULL_MARKET_READY" ? "bg-emerald-900/40 text-emerald-400" : "bg-slate-800 text-slate-400"}`}>
            {dataHealth.scanScope === "FULL_MARKET_READY" ? "전종목" : "선별 유니버스"}
          </span>
        </div>
      )}

      {/* 요약 지표 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: "오늘 진입 후보", value: loading ? null : `${todayEntries.length}개`, color: "text-emerald-400" },
          { label: "대기 관찰 중", value: loading ? null : `${watchItems.length}개`, color: "text-amber-400" },
          { label: "위험/주의 보유", value: loading ? null : `${riskCount}개`, color: riskCount > 0 ? "text-red-400" : "text-slate-300" },
          { label: "총 평가손익", value: loading ? null : (summary?.totalPnlText ?? "0"), color: "text-slate-100" },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs text-slate-500">{label}</div>
            {value === null
              ? <div className="mt-2 h-7 w-16 animate-pulse rounded-md bg-slate-800" />
              : <div className={`mt-2 text-xl font-bold ${color}`}>{value}</div>}
          </div>
        ))}
      </div>

      {/* ━━ 오늘 진입 후보 ━━ */}
      <section className="rounded-2xl border border-emerald-900/50 bg-emerald-950/10 p-5">
        <div className="mb-4 flex items-center gap-2">
          <TrendingUp size={18} className="text-emerald-400" />
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-slate-100">
              {sessionPhase === "장중" ? "진입가 근접 종목" : "오늘 진입 후보"}
            </h2>
            <p className="text-xs text-slate-500">
              {sessionCtx.hint || "진입 구간 + EV 양수 + 추세 조건을 동시에 충족한 종목입니다."}
            </p>
          </div>
          <span className="shrink-0 rounded-full border border-emerald-800/50 bg-emerald-900/30 px-3 py-1 text-xs text-emerald-400">
            {loading ? "..." : `${todayEntries.length}개`}
          </span>
          {onNavigate && (
            <button onClick={() => onNavigate("stocks")} className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">
              종목 탐색 <ArrowRight size={12} />
            </button>
          )}
        </div>
        {loading ? (
          <div className="py-8 text-center text-slate-500">불러오는 중...</div>
        ) : todayEntries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700 py-6 text-center text-sm">
            <p className="text-slate-500">
              {marketRegime?.regime === "BEAR" ? "약세장 — 진입 기준 상향 적용 중" : "현재 즉시 진입 후보가 없습니다."}
            </p>
            <p className="mt-2 text-[11px] text-slate-600">
              기준: finalScore ≥ 50 + EV 양수 + tradeBlockStatus OK.{" "}
              {allItems.length === 0 ? "추천 데이터가 없습니다 — GitHub Actions 실행을 확인하세요." : `전략 매트릭스에는 ${allItems.length}개 종목이 있으나 즉시 진입 조건을 충족하지 않습니다.`}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {todayEntries.map((item, i) => (
              <TodayEntryCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} rank={i + 1} onSelect={setSelectedItem} />
            ))}
          </div>
        )}
      </section>

      {/* ━━ 포지션 사이징 ━━ */}
      {!loading && <PositionSizingSection items={allItems} capital={capital} setCapital={setCapital} />}

      {/* ━━ 대기 관찰 후보 ━━ */}
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center gap-2">
          <Eye size={18} className="text-amber-400" />
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-slate-100">대기 관찰 후보</h2>
            <p className="text-xs text-slate-500">지금보다 1~수일 후 진입 타이밍이 더 유리할 것으로 예상됩니다.</p>
          </div>
          <span className="shrink-0 rounded-full border border-amber-800/50 bg-amber-900/20 px-3 py-1 text-xs text-amber-400">
            {loading ? "..." : `${watchItems.length}개`}
          </span>
          {onNavigate && (
            <button onClick={() => onNavigate("stocks")} className="flex shrink-0 items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">
              종목 탐색 <ArrowRight size={12} />
            </button>
          )}
        </div>
        {loading ? (
          <div className="py-6 text-center text-slate-500">불러오는 중...</div>
        ) : watchItems.length === 0 ? (
          <div className="py-6 text-center text-sm text-slate-500">대기 관찰 종목이 없습니다.</div>
        ) : (
          <div className="space-y-2">
            {watchItems.map((item) => (
              <WatchCard key={`${item.symbol}-${item._mode}-${item._horizon}`} item={item} onSelect={setSelectedItem} />
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
                return <MatrixCell key={`${mode}-${horizon}`} cell={cell as StrategyCell} onSelect={setSelectedItem} />;
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
            {summary?.totalPnl != null && (
              <span className={`ml-1 font-mono text-sm font-bold ${Number(summary.totalPnl) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {summary.totalPnlText ?? (Number(summary.totalPnl) >= 0 ? "+" : "") + Number(summary.totalPnl).toLocaleString("ko-KR") + "원"}
              </span>
            )}
            <span className="ml-auto text-xs text-slate-500">{holdings.length}개{riskCount > 0 && ` · 위험/주의 ${riskCount}개`}</span>
            {onNavigate && (
              <button onClick={() => onNavigate("holdings")} className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-slate-200">
                {holdings.length > 6 ? "전체 보기" : "상세"} <ArrowRight size={12} />
              </button>
            )}
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
          {holdings.length > 6 && onNavigate && (
            <button onClick={() => onNavigate("holdings")} className="mt-3 w-full rounded-xl border border-slate-700 py-2 text-xs text-slate-400 hover:bg-slate-800">
              나머지 {holdings.length - 6}개 보유종목 →
            </button>
          )}
        </section>
      )}
    </div>
  );
}
