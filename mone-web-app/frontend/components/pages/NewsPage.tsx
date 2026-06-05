"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Building2, ExternalLink, RefreshCw, Search } from "lucide-react";
import { mone, type Market } from "@/lib/api";
import { getDefaultMarketBySession, marketLabel } from "@/lib/marketSession";
import { displayName, statusBadge } from "@/lib/moneDisplay";

type Tab = "news" | "disclosures" | "company" | "calendar";

function fmtNum(value: any, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "값 비어 있음";
  return `${n.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}${suffix}`;
}

const POS_KEYWORDS = ["상승", "급등", "돌파", "신고가", "호실적", "흑자", "성장", "수주", "배당", "목표가 상향", "매수", "긍정", "수혜", "강세", "인수", "확대", "개선", "증가"];
const NEG_KEYWORDS = ["하락", "급락", "하한가", "손실", "적자", "부진", "매도", "하향", "위기", "리스크", "불확실", "주의", "감소", "축소", "악화", "소송", "과징금", "조사", "제재"];
const IMPACT_KEYWORDS = ["실적", "가이던스", "합병", "인수", "유상증자", "감자", "배당", "자사주", "소송", "제재", "공급계약", "수주", "임상", "승인", "리콜", "파산", "상장폐지", "10-K", "10-Q", "8-K", "FORM 4"];
const FIN_FIELDS = ["eps", "per", "pbr", "roe", "revenue", "operatingIncome", "operatingProfit", "netIncome", "debtRatio"];

function newsSentiment(item: any): { label: string; cls: string } | null {
  const text = [item.title, item.headline, item.summary].filter(Boolean).join(" ");
  const posHit = POS_KEYWORDS.filter((k) => text.includes(k)).length;
  const negHit = NEG_KEYWORDS.filter((k) => text.includes(k)).length;
  if (posHit === 0 && negHit === 0) return null;
  if (negHit > posHit) return { label: "부정", cls: "border-red-500/40 bg-red-500/10 text-red-300" };
  if (posHit > negHit) return { label: "긍정", cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" };
  return { label: "혼재", cls: "border-amber-500/40 bg-amber-500/10 text-amber-300" };
}

function statusLabel(status?: string) {
  if (status === "NORMAL" || status === "OK" || status === "정상") return "정상";
  if (status === "PARTIAL" || status === "값 비어 있음") return "값 비어 있음";
  if (status === "NO_DATA" || status === "재무 원본 없음") return "재무 원본 없음";
  if (status === "ERROR") return "오류";
  if (status === "STALE") return "오래된 데이터";
  return status || "확인 필요";
}

function dateText(value: any) {
  if (!value) return "-";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

function itemDateValue(item: any) {
  return item.publishedAt || item.disclosedAt || item.date || item.reportDate || "";
}

function ageDays(value: any) {
  const raw = itemDateValue({ date: value }) || value;
  if (!raw) return null;
  const text = String(raw).trim();
  const normalized = /^\d{8}$/.test(text) ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}` : text;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
}

function freshnessLabel(value: any) {
  const days = ageDays(value);
  if (days == null) return "날짜 없음";
  if (days <= 3) return "신규";
  if (days <= 14) return `${days}일 전`;
  return `오래됨 ${days}일`;
}

function titleOf(item: any, tab: Tab) {
  if (tab === "company") return displayName(item);
  if (tab === "disclosures") return item.title || item.reportName || item.formType || item.company || "공시 제목 확인";
  return item.title || item.headline || item.summary || "뉴스 제목 확인";
}

function secFormExplain(form: string) {
  const f = String(form || "").toUpperCase();
  if (f.includes("FORM 4") || f === "4") return "임원·내부자 거래 보고";
  if (f.includes("144")) return "제한주식 매각 예정 신고";
  if (f.includes("SD")) return "분쟁광물·공급망 관련 공시";
  if (f.includes("10-K")) return "연간보고서";
  if (f.includes("10-Q")) return "분기보고서";
  if (f.includes("8-K")) return "주요 이벤트 보고";
  return "SEC 공시";
}

function impactScore(item: any, tab: Tab) {
  const text = [titleOf(item, tab), item.summary, item.description, item.formType, item.reportName].filter(Boolean).join(" ").toUpperCase();
  let score = 10;
  score += IMPACT_KEYWORDS.reduce((sum, key) => sum + (text.includes(key.toUpperCase()) ? 14 : 0), 0);
  if (tab === "disclosures") score += 15;
  if (item.isWarning) score += 25;
  const sentiment = newsSentiment(item)?.label;
  if (sentiment === "부정" || sentiment === "혼재") score += 10;
  const days = ageDays(itemDateValue(item));
  if (days != null && days <= 3) score += 15;
  if (days != null && days > 30) score -= 10;
  return Math.max(0, Math.min(100, score));
}

function impactLabel(score: number) {
  if (score >= 70) return "높음";
  if (score >= 40) return "중간";
  return "낮음";
}

function impactTone(score: number) {
  if (score >= 70) return "border-red-500/40 bg-red-500/10 text-red-300";
  if (score >= 40) return "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return "border-slate-700 bg-slate-800 text-slate-300";
}

function companyReadiness(item: any) {
  const present = FIN_FIELDS.filter((key) => {
    const value = item?.[key];
    return value !== undefined && value !== null && value !== "" && Number(value) !== 0;
  }).length;
  const missing = Array.isArray(item?.missingFields) ? item.missingFields.length : Math.max(0, FIN_FIELDS.length - present);
  const pct = Math.round((present / FIN_FIELDS.length) * 100);
  const label = pct >= 75 ? "분석 가능" : pct >= 35 ? "부분 분석" : "원본 대기";
  return { present, missing, pct, label };
}

function dataAction(item: any) {
  const mkt = String(item?.market || "").toLowerCase();
  const sym = String(item?.symbol || "").toUpperCase();
  if (companyReadiness(item).pct >= 75) return "재무·퀀트가 충분합니다. 밸류에이션과 기술 점수를 함께 보세요.";
  if (sym.includes("ETF") || sym.match(/^(SPY|QQQ|SCHD|VTI|IVV|VOO|TQQQ|SOXL)$/)) return "ETF는 개별 재무 지표 대신 가격·보유 비중·변동성 중심으로 판단하세요.";
  if (mkt === "us") return "FINNHUB/SEC 원본이 채워지면 EPS·PER·ROE 카드가 자동으로 정상 전환됩니다.";
  return "DART 원본이 채워지면 재무 커버리지와 누락 배지가 자동으로 정상 전환됩니다.";
}

function tabLabel(tab: Tab) {
  if (tab === "news") return "뉴스";
  if (tab === "disclosures") return "공시";
  if (tab === "calendar") return "공시 캘린더";
  return "기업분석";
}

function emptyMessage(tab: Tab, data: any, query: string, watchOnly: boolean) {
  if (data?.status === "ERROR") return `API 오류: ${data.error || "원인을 확인하세요."}`;
  if (query.trim()) return "검색 조건과 일치하는 항목이 없습니다.";
  if (tab === "news") return "뉴스 원본이 비어 있습니다. 수집 전에는 관련 뉴스 카드만 비어 있는 것이 정상입니다.";
  if (tab === "disclosures" && watchOnly) return "보유·관심 종목에 연결된 공시가 없습니다. 전체 보기로 원본 존재 여부를 확인할 수 있습니다.";
  if (tab === "disclosures") return "공시 원본이 비어 있습니다. DART/SEC 수집 후 다시 확인하세요.";
  return "기업분석 원본이 비어 있습니다. 재무 원본 부족은 수집/API 영역이며, 화면은 누락 상태를 그대로 표시합니다.";
}

export default function NewsPage() {
  const [market, setMarket] = useState<Market>(getDefaultMarketBySession());
  const [tab, setTab] = useState<Tab>("company");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<any>({ items: [] });
  const [calendarData, setCalendarData] = useState<any>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [watchOnly, setWatchOnly] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (tab === "calendar") {
      const controller = new AbortController();
      setLoading(true);
      mone.disclosureCalendar({ market, days: 30 }, controller.signal)
        .then((r) => setCalendarData(r))
        .catch(() => setCalendarData(null))
        .finally(() => setLoading(false));
      return () => controller.abort();
    }
  }, [tab, market, reloadKey]);

  async function load(signal?: AbortSignal) {
    if (tab === "calendar") return;
    setLoading(true);
    try {
      const loader =
        tab === "news"
          ? mone.news({ market, limit: 200, watchOnly }, signal)
          : tab === "disclosures"
            ? mone.disclosures({ market, limit: 200, watchOnly }, signal)
            : mone.companyAnalysis({ market, limit: 240, q: query || undefined }, signal);
      const result = await loader;
      if (signal?.aborted) return;
      setData(result);
      setSelectedIndex(0);
    } catch (error) {
      setData({ status: "ERROR", error: String(error), items: [] });
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [market, tab, watchOnly, reloadKey]);

  const items = useMemo(() => {
    const source = Array.isArray(data.items) ? data.items : [];
    const q = query.trim().toLowerCase();
    const filtered = !q ? source : source.filter((item: any) =>
      [item.symbol, displayName(item), item.company, item.title, item.summary, item.source, item.formType]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
    if (tab === "news" || tab === "disclosures") {
      return [...filtered].sort((a, b) => {
        const impactDiff = impactScore(b, tab) - impactScore(a, tab);
        if (impactDiff !== 0) return impactDiff;
        return String(itemDateValue(b)).localeCompare(String(itemDateValue(a)));
      });
    }
    return [...filtered].sort((a, b) => companyReadiness(b).pct - companyReadiness(a).pct);
  }, [data.items, query, tab]);
  const selected = items[Math.min(selectedIndex, Math.max(items.length - 1, 0))];
  const sourceItems = Array.isArray(data.items) ? data.items : [];
  const sourceFiles = Array.isArray(data.sourceFiles) ? data.sourceFiles : [];
  const sentimentCounts = useMemo(() => {
    return sourceItems.reduce((acc: Record<string, number>, item: any) => {
      const sentiment = newsSentiment(item)?.label || "중립";
      acc[sentiment] = (acc[sentiment] || 0) + 1;
      return acc;
    }, {});
  }, [sourceItems]);
  const latestDate = useMemo(() => {
    const values = sourceItems
      .map((item: any) => item.publishedAt || item.disclosedAt || item.date)
      .filter(Boolean)
      .sort();
    return values.at(-1) || "";
  }, [sourceItems]);
  const summaryCards = [
    { label: "상태", value: statusLabel(data.status), sub: data.message || `${tabLabel(tab)} 데이터 연결`, tone: data.status === "ERROR" ? "border-red-500/30 bg-red-500/10 text-red-300" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
    { label: "표시", value: `${items.length}건`, sub: `원본 ${sourceItems.length}건`, tone: items.length > 0 ? "border-sky-500/30 bg-sky-500/10 text-sky-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300" },
    tab === "company"
      ? { label: "재무 커버리지", value: `정상 ${data.normalCount ?? 0}`, sub: `부분 ${data.partialCount ?? 0} · 없음 ${data.noDataCount ?? 0}`, tone: "border-violet-500/30 bg-violet-500/10 text-violet-300" }
      : tab === "news"
        ? { label: "감성·중요도", value: `긍정 ${sentimentCounts["긍정"] || 0}`, sub: `높은 영향 ${sourceItems.filter((item: any) => impactScore(item, tab) >= 70).length}건`, tone: "border-violet-500/30 bg-violet-500/10 text-violet-300" }
        : { label: "필터", value: watchOnly ? "보유·관심" : "전체", sub: data.relevantSymbols != null ? `연결 심볼 ${data.relevantSymbols}개` : "원본 기준", tone: "border-violet-500/30 bg-violet-500/10 text-violet-300" },
    { label: "원본", value: sourceFiles.length ? `${sourceFiles.length}개` : "로컬/API", sub: latestDate ? `${freshnessLabel(latestDate)} · ${dateText(latestDate)}` : "최근일 확인 필요", tone: "border-slate-700 bg-slate-950 text-slate-300" },
  ];

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">뉴스·기업분석</h1>
          <p className="mt-1 text-sm text-slate-400">뉴스, 공시, 기업분석 데이터의 연결 상태와 누락 사유를 분리해서 확인합니다.</p>
        </div>
        <button onClick={() => setReloadKey((v) => v + 1)} disabled={loading} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300 disabled:opacity-50">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      <div className="flex flex-col gap-2">
        {/* 시장 + 컨텐츠 탭 한 줄 */}
        <div className="flex flex-wrap gap-1.5">
          {(["kr", "us"] as Market[]).map((item) => (
            <button key={item} onClick={() => setMarket(item)} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${market === item ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400"}`}>
              {marketLabel(item)}
            </button>
          ))}
          <span className="self-center text-slate-700">|</span>
          {(["news", "disclosures", "company", "calendar"] as Tab[]).map((item) => (
            <button key={item} onClick={() => setTab(item)} className={`rounded-lg px-3 py-1.5 text-xs font-medium ${tab === item ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-400"}`}>
              {item === "news" ? "뉴스" : item === "disclosures" ? "공시" : item === "calendar" ? "캘린더" : "기업분석"}
            </button>
          ))}
          {(tab === "disclosures" || tab === "news") && (
            <button
              onClick={() => setWatchOnly(!watchOnly)}
              className={`rounded-lg px-3 py-1.5 text-xs font-bold ${watchOnly ? "bg-amber-500 text-slate-950" : "bg-slate-800 text-slate-400"}`}
            >
              {watchOnly ? "보유·관심" : "전체"}
            </button>
          )}
        </div>
      </div>

      <div className="relative max-w-xl">
        <Search size={15} className="absolute left-3 top-3.5 text-slate-500" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && setReloadKey((v) => v + 1)}
          placeholder="종목명, 코드, 키워드 검색"
          className="h-11 w-full rounded-xl border border-slate-700 bg-slate-950 pl-9 pr-3 text-sm text-slate-100 outline-none placeholder:text-slate-500"
        />
      </div>

      {tab !== "calendar" && (
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          {summaryCards.map((card) => (
            <div key={card.label} className={`rounded-xl border px-3 py-2 ${card.tone}`}>
              <div className="text-[10px] font-semibold uppercase tracking-wide opacity-80">{card.label}</div>
              <div className="mt-1 font-mono text-sm font-bold">{card.value}</div>
              <div className="line-clamp-1 text-[10px] opacity-75">{card.sub}</div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[420px_1fr]">
        <div className="space-y-2">
          {items.length === 0 && (
            <div className="rounded-2xl border border-dashed border-slate-800 p-8 text-center text-slate-500">
              {loading ? "불러오는 중..." : emptyMessage(tab, data, query, watchOnly)}
            </div>
          )}
          {items.map((item: any, index: number) => (
            <button
              key={`${tab}-${item.id || item.symbol || item.title || index}-${index}`}
              onClick={() => setSelectedIndex(index)}
              className={`block w-full rounded-2xl border p-4 text-left ${index === selectedIndex ? "border-blue-500/50 bg-blue-500/10" : "border-slate-800 bg-slate-900/60"}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="line-clamp-2 font-semibold text-slate-100">{titleOf(item, tab)}</div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  {tab === "company" && <span className={`rounded-lg border px-2 py-1 text-[10px] font-bold ${statusBadge(item.dataStatus)}`}>{statusLabel(item.connectionStatus || item.dataStatus)}</span>}
                  {(tab === "news" || tab === "disclosures") && (() => { const score = impactScore(item, tab); return <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-bold ${impactTone(score)}`}>영향 {impactLabel(score)}</span>; })()}
                  {tab === "news" && (() => { const s = newsSentiment(item); return s ? <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-bold ${s.cls}`}>{s.label}</span> : null; })()}
                </div>
              </div>
              <div className="mt-1 font-mono text-xs text-slate-500">{item.symbol || item.company || ""} · {(item.market || market).toString().toUpperCase()}</div>
              {tab === "disclosures" && <div className="mt-2 text-xs text-amber-300">{secFormExplain(item.formType || item.title || item.reportName)}</div>}
              {tab === "company" && (
                <div className="mt-2 flex flex-wrap gap-1">
                  <span className="rounded-md border border-slate-700 bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300">준비도 {companyReadiness(item).pct}%</span>
                  {item.hasQuantData && <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-300">퀀트 {item.quantScore != null ? Math.round(item.quantScore) + "점" : "분석 가능"}</span>}
                  {Array.isArray(item.missingFields) && item.missingFields.length > 0 && item.missingFields.slice(0, 3).map((field: string) => (
                    <span key={field} className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">{field} 누락</span>
                  ))}
                </div>
              )}
              {tab !== "company" && <div className="mt-2 text-xs text-slate-500">{item.source || item.publisher || "출처 미확인"} · {freshnessLabel(itemDateValue(item))} · {dateText(itemDateValue(item))}</div>}
            </button>
          ))}
        </div>

        <div className={`rounded-2xl border border-slate-800 bg-slate-900/60 p-4 md:p-6 ${!selected ? "hidden lg:block" : ""}`}>
          {!selected ? (
            <div className="py-20 text-center text-slate-500">목록에서 항목을 선택하거나 검색하세요.</div>
          ) : tab === "company" ? (
            <CompanyDetail selected={selected} />
          ) : tab === "news" ? (
            <NewsDetail selected={selected} />
          ) : (
            <DisclosureDetail selected={selected} />
          )}
        </div>
      </div>

      {/* ── 공시 캘린더 탭 */}
      {tab === "calendar" && (
        <div className="space-y-4">
          {loading ? (
            <div className="py-12 text-center text-slate-500">불러오는 중...</div>
          ) : !calendarData || calendarData.status === "NO_DATA" ? (
            <div className="rounded-2xl border border-dashed border-slate-700 py-12 text-center text-slate-500">
              공시 데이터가 없습니다. DART API 수집 후 다시 확인하세요.
            </div>
          ) : (
            <>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span>총 {calendarData.totalDisclosures}건</span>
                {calendarData.watchedCount > 0 && <span className="text-amber-300">관심/보유 종목 {calendarData.watchedCount}건 포함</span>}
                <span>{calendarData.fromDate} ~ {calendarData.toDate}</span>
              </div>
              {(calendarData.calendar || []).map((day: any) => (
                <div key={day.date} className={`rounded-2xl border p-4 ${day.isToday ? "border-blue-600/50 bg-blue-950/20" : day.isPast ? "border-slate-800 opacity-60" : "border-slate-700"}`}>
                  <div className="mb-2 flex items-center gap-2">
                    <span className={`font-semibold ${day.isToday ? "text-blue-300" : "text-slate-200"}`}>
                      {day.date}{day.isToday && " (오늘)"}
                    </span>
                    <span className="text-xs text-slate-500">{day.count}건</span>
                    {day.watched > 0 && <span className="rounded-full bg-amber-700/40 px-2 py-0.5 text-[10px] text-amber-300">관심 {day.watched}</span>}
                  </div>
                  <div className="space-y-1.5">
                    {day.items.map((item: any, idx: number) => (
                      <div key={idx} className={`flex items-center justify-between rounded-lg px-3 py-1.5 text-[11px] ${item.inWatchlist ? "bg-amber-950/30 border border-amber-800/30" : "bg-slate-950/50"}`}>
                        <div>
                          <span className={`font-medium ${item.inWatchlist ? "text-amber-200" : "text-slate-300"}`}>{item.name || item.symbol}</span>
                          <span className="ml-1.5 text-slate-500">{item.symbol}</span>
                          {item.kind !== "기타" && <span className={`ml-2 rounded-full px-1.5 py-0.5 text-[10px] ${item.kind === "실적" ? "bg-emerald-900/50 text-emerald-300" : item.kind === "주요공시" ? "bg-red-900/50 text-red-300" : "bg-slate-800 text-slate-400"}`}>{item.kind}</span>}
                        </div>
                        <span className="max-w-[200px] truncate text-slate-400">{item.title}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function QuantBar({ label, score }: { label: string; score: number | null | undefined }) {
  if (score == null || !Number.isFinite(score)) return null;
  const pct = Math.max(0, Math.min(100, score));
  const barColor = pct >= 60 ? "bg-emerald-500" : pct >= 40 ? "bg-amber-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-[11px] text-slate-500">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 shrink-0 text-right font-mono text-[11px] text-slate-300">{Math.round(pct)}</span>
    </div>
  );
}

function CompanyDetail({ selected }: { selected: any }) {
  const hasFinData = Array.isArray(selected.missingFields) ? selected.missingFields.length < 4 : false;
  const hasQuant = selected.hasQuantData || selected.quantScore != null;
  const connStatus = selected.connectionStatus || statusLabel(selected.dataStatus);
  const readiness = companyReadiness(selected);

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-bold text-slate-100"><Building2 size={20} />{displayName(selected)}</h2>
          <div className="mt-1 font-mono text-sm text-slate-500">{selected.symbol} · {String(selected.market || "").toUpperCase()}</div>
        </div>
        <div className={`rounded-xl border px-3 py-2 text-xs font-bold ${statusBadge(selected.dataStatus)}`}>{connStatus}</div>
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-slate-200">분석 준비도</div>
            <div className="mt-1 text-xs text-slate-500">{dataAction(selected)}</div>
          </div>
          <span className={`rounded-xl border px-3 py-1.5 text-xs font-bold ${readiness.pct >= 75 ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : readiness.pct >= 35 ? "border-amber-500/30 bg-amber-500/10 text-amber-300" : "border-slate-700 bg-slate-800 text-slate-300"}`}>
            {readiness.label} · {readiness.pct}%
          </span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800">
          <div className={`h-full rounded-full ${readiness.pct >= 75 ? "bg-emerald-500" : readiness.pct >= 35 ? "bg-amber-400" : "bg-slate-500"}`} style={{ width: `${readiness.pct}%` }} />
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-slate-600">
          <span>채워진 지표 {readiness.present}/{FIN_FIELDS.length}</span>
          <span>{hasFinData ? "재무 분석 가능" : "재무 원본 보강 대기"}</span>
        </div>
      </div>

      {/* ── 퀀트 분석 섹션 ─────────────────────────────────────────── */}
      {hasQuant && (
        <div className="rounded-2xl border border-slate-700 bg-slate-950/60 p-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-widest text-slate-500">퀀트 기술분석</span>
            {selected.quantProbability > 0 && (
              <span className="font-mono text-sm font-bold text-emerald-300">{Number(selected.quantProbability).toFixed(1)}% 확률</span>
            )}
          </div>
          <div className="space-y-2">
            <QuantBar label="종합 점수" score={selected.quantScore} />
            <QuantBar label="진입 적기" score={selected.quantEntryScore} />
            <QuantBar label="리스크" score={selected.quantRiskScore} />
            <QuantBar label="상승여력" score={selected.quantGrowthScore} />
          </div>
          {selected.surgeLabel && selected.surgeLabel !== "판단 대기" && (
            <div className="mt-3 flex flex-wrap gap-1">
              {String(selected.surgeLabel).split("|").map((t: string) => t.trim()).filter(Boolean).map((t: string) => (
                <span key={t} className={`rounded-md border px-2 py-1 text-[11px] font-bold ${
                  t.includes("주의") ? "border-red-500/30 bg-red-500/10 text-red-300"
                  : t.includes("저평가") ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                  : t.includes("수렴") ? "border-violet-500/30 bg-violet-500/10 text-violet-300"
                  : t.includes("기관") || t.includes("외국인") ? "border-blue-500/30 bg-blue-500/10 text-blue-300"
                  : "border-slate-700 bg-slate-800 text-slate-300"
                }`}>{t}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── 재무 지표 ──────────────────────────────────────────────── */}
      <div>
        <div className="mb-2 text-xs font-bold uppercase tracking-widest text-slate-500">재무 지표</div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <Metric label="EPS" value={fmtNum(selected.eps)} />
          <Metric label="PER" value={fmtNum(selected.per)} />
          <Metric label="PBR" value={fmtNum(selected.pbr)} />
          <Metric label="ROE" value={fmtNum(selected.roe, "%")} />
          <Metric label="매출" value={fmtNum(selected.revenue)} />
          <Metric label="영업이익" value={fmtNum(selected.operatingIncome || selected.operatingProfit)} />
          <Metric label="순이익" value={fmtNum(selected.netIncome)} />
          <Metric label="부채비율" value={fmtNum(selected.debtRatio, "%")} />
          {selected.qualityScore && <Metric label="펀더멘털 점수" value={fmtNum(selected.qualityScore, "점")} />}
        </div>
      </div>

      {/* ── 재무 데이터 누락 안내 ──────────────────────────────────── */}
      {Array.isArray(selected.missingFields) && selected.missingFields.length > 0 && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
          <div className="mb-2 flex items-center gap-2 font-semibold"><AlertTriangle size={15} />재무 데이터 누락</div>
          <p className="mb-2">{selected.missingFields.join(", ")} 항목이 비어 있습니다.</p>
          {(() => {
            const sym = String(selected.symbol || "").toUpperCase();
            const mkt = String(selected.market || "kr").toLowerCase();
            if (sym.includes("ETF") || sym.match(/^(SPY|QQQ|SCHD|VTI|IVV|VOO|TQQQ|SOXL)$/)) return <p className="text-[11px] text-amber-300/70">ETF는 EPS/PER/ROE 등 개별 재무 지표가 제공되지 않습니다.</p>;
            if (mkt === "us") return <p className="text-[11px] text-amber-300/70">미국 주식: Finnhub 또는 SEC API 수집 필요. FINNHUB_API_KEY 설정 여부를 확인하세요.</p>;
            return <p className="text-[11px] text-amber-300/70">국장: DART API 수집 필요. DART_API_KEY 설정 여부를 확인하거나 신규상장/소형주는 재무 데이터가 없을 수 있습니다.</p>;
          })()}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span>출처:</span>
        {(selected.dataSources || [selected.source]).filter(Boolean).map((src: string, i: number) => (
          <span key={i} className="rounded-md border border-slate-700 bg-slate-800 px-2 py-0.5 font-mono">{src}</span>
        ))}
        {!selected.source && !selected.dataSources && <span className="italic text-slate-600">출처 정보 없음 (local CSV/json)</span>}
        {selected.dartYear && <span className="rounded-md border border-blue-700/40 bg-blue-800/20 px-2 py-0.5 text-blue-300">DART {selected.dartYear}년</span>}
      </div>
    </div>
  );
}

function NewsDetail({ selected }: { selected: any }) {
  const tags = Array.isArray(selected.tags) ? selected.tags : selected.tag ? [selected.tag] : [];
  const sentiment = newsSentiment(selected);
  const score = impactScore(selected, "news");
  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-xl font-bold text-slate-100">{selected.title || selected.headline || "뉴스 제목 없음"}</h2>
          {sentiment && <span className={`shrink-0 rounded-xl border px-3 py-1.5 text-xs font-bold ${sentiment.cls}`}>{sentiment.label}</span>}
        </div>
        <p className="mt-2 text-sm text-slate-500">{selected.source || selected.publisher || "출처 미확인"} · {dateText(selected.publishedAt || selected.date)}</p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Metric label="영향도" value={`${impactLabel(score)} (${score}점)`} />
        <Metric label="신선도" value={freshnessLabel(itemDateValue(selected))} />
      </div>
      {tags.length > 0 && <div className="flex flex-wrap gap-2">{tags.map((tag: string) => <span key={tag} className="rounded-lg bg-blue-500/10 px-2 py-1 text-xs text-blue-300">{tag}</span>)}</div>}
      <p className="rounded-2xl bg-slate-950 p-4 text-sm leading-6 text-slate-300">{selected.summary || selected.description || "요약 데이터가 없습니다."}</p>
      {selected.url && <a href={selected.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"><ExternalLink size={14} />원문 보기</a>}
    </div>
  );
}

function DisclosureDetail({ selected }: { selected: any }) {
  const form = selected.formType || selected.title || selected.reportName;
  const score = impactScore(selected, "disclosures");
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-slate-100">{selected.title || selected.reportName || "공시 제목 없음"}</h2>
        <p className="mt-2 text-sm text-slate-500">{selected.company || selected.name || selected.symbol || "-"} · {selected.source || "DART/SEC"} · {dateText(selected.disclosedAt || selected.date)}</p>
      </div>
      <div className="rounded-xl border border-sky-500/20 bg-sky-500/10 p-4 text-sm text-sky-100">
        <b>{secFormExplain(form)}</b><br />미장 공시는 SEC Form 유형을 먼저 해석해 보여줍니다. 투자 판단 전 원문 확인이 필요합니다.
      </div>
      {selected.isWarning && <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">주의 공시로 분류되었습니다. 신규 진입 전 내용 확인이 필요합니다.</div>}
      <div className="grid grid-cols-2 gap-3">
        <Metric label="회사" value={selected.company || selected.name || "-"} />
        <Metric label="종목코드" value={selected.symbol || "-"} />
        <Metric label="공시 유형" value={String(form || "-")} />
        <Metric label="공시일" value={dateText(selected.disclosedAt || selected.date)} />
        <Metric label="영향도" value={`${impactLabel(score)} (${score}점)`} />
        <Metric label="신선도" value={freshnessLabel(itemDateValue(selected))} />
      </div>
      {selected.url && <a href={selected.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800"><ExternalLink size={14} />공시 원문 보기</a>}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-slate-950 p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-2 break-words font-mono text-lg font-semibold text-slate-100">{value}</div>
    </div>
  );
}
