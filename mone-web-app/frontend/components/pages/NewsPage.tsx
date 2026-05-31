"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Building2, ExternalLink, RefreshCw, Search } from "lucide-react";
import { mone, type Market } from "@/lib/api";

type Tab = "news" | "disclosures" | "company";

function fmtNum(value: any, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "데이터 없음";
  return `${n.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}${suffix}`;
}

function statusCls(status: string) {
  if (status === "OK" || status === "NORMAL") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (status === "ERROR" || status === "NO_DATA") return "border-red-500/30 bg-red-500/10 text-red-300";
  return "border-amber-500/30 bg-amber-500/10 text-amber-300";
}

function statusLabel(status?: string) {
  if (status === "NORMAL" || status === "OK") return "정상";
  if (status === "PARTIAL") return "일부 누락";
  if (status === "NO_DATA") return "데이터 없음";
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

function titleOf(item: any, tab: Tab) {
  if (tab === "company") return item.name || item.company || item.symbol || "-";
  if (tab === "disclosures") return item.title || item.reportName || item.company || "-";
  return item.title || item.headline || item.summary || "-";
}

export default function NewsPage() {
  const [market, setMarket] = useState<Market>("kr");
  const [tab, setTab] = useState<Tab>("company");
  const [query, setQuery] = useState("");
  const [data, setData] = useState<any>({ items: [] });
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const loader =
        tab === "news"
          ? mone.news({ market, limit: 200 })
          : tab === "disclosures"
            ? mone.disclosures({ market, limit: 200 })
            : mone.companyAnalysis({ market, limit: 500, q: query || undefined });
      const result = await loader;
      setData(result);
    } catch (error) {
      setData({ status: "ERROR", error: String(error), items: [] });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [market, tab]);

  const items = useMemo(() => {
    const source = Array.isArray(data.items) ? data.items : [];
    const q = query.trim().toLowerCase();
    if (!q) return source;
    return source.filter((item: any) => {
      const haystack = [item.symbol, item.name, item.company, item.title, item.summary, item.source]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [data.items, query]);

  const selected = items[0];

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">뉴스·기업분석</h1>
          <p className="mt-1 text-sm text-slate-400">뉴스, 공시, 기업분석 데이터와 결손 원인을 함께 확인합니다.</p>
        </div>
        <button onClick={load} className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["kr", "us"] as Market[]).map((item) => (
          <button key={item} onClick={() => setMarket(item)} className={`rounded-xl px-4 py-2 text-sm ${market === item ? "bg-blue-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {item === "kr" ? "국장" : "미장"}
          </button>
        ))}
        {(["news", "disclosures", "company"] as Tab[]).map((item) => (
          <button key={item} onClick={() => setTab(item)} className={`rounded-xl px-4 py-2 text-sm ${tab === item ? "bg-emerald-600 text-white" : "bg-slate-900 text-slate-400"}`}>
            {item === "news" ? "뉴스 요약" : item === "disclosures" ? "공시" : "기업분석"}
          </button>
        ))}
      </div>

      <div className="relative max-w-xl">
        <Search size={15} className="absolute left-3 top-3.5 text-slate-500" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && load()}
          placeholder="종목명, 코드, 키워드 검색"
          className="h-11 w-full rounded-xl border border-slate-700 bg-slate-950 pl-9 pr-3 text-sm text-slate-100 outline-none placeholder:text-slate-500"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[380px_1fr]">
        <div className="space-y-2">
          {items.length === 0 && (
            <div className="rounded-2xl border border-dashed border-slate-800 p-8 text-center text-slate-500">
              데이터가 없습니다.
            </div>
          )}
          {items.map((item: any, index: number) => (
            <div key={`${tab}-${item.id || item.symbol || item.title || index}-${index}`} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="line-clamp-2 font-semibold text-slate-100">{titleOf(item, tab)}</div>
                {tab === "company" && (
                  <span className={`shrink-0 rounded-lg border px-2 py-1 text-[10px] font-bold ${statusCls(item.dataStatus)}`}>
                    {statusLabel(item.dataStatus)}
                  </span>
                )}
              </div>
              <div className="mt-1 font-mono text-xs text-slate-500">
                {item.symbol || item.company || ""} · {(item.market || market).toString().toUpperCase()}
              </div>
              {tab === "company" && Array.isArray(item.missingFields) && item.missingFields.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {item.missingFields.slice(0, 4).map((field: string) => (
                    <span key={field} className="rounded-md bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                      {field} 없음
                    </span>
                  ))}
                </div>
              )}
              {tab !== "company" && (
                <div className="mt-2 text-xs text-slate-500">
                  {item.source || item.publisher || "출처 미확인"} · {dateText(item.publishedAt || item.disclosedAt || item.date)}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
          {!selected ? (
            <div className="py-20 text-center text-slate-500">왼쪽에서 항목을 선택하거나 검색하세요.</div>
          ) : tab === "company" ? (
            <CompanyDetail selected={selected} />
          ) : tab === "news" ? (
            <NewsDetail selected={selected} />
          ) : (
            <DisclosureDetail selected={selected} />
          )}
        </div>
      </div>
    </div>
  );
}

function CompanyDetail({ selected }: { selected: any }) {
  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-bold text-slate-100">
            <Building2 size={20} />
            {selected.name || selected.symbol}
          </h2>
          <div className="mt-1 font-mono text-sm text-slate-500">{selected.symbol} · {selected.market}</div>
        </div>
        <div className={`rounded-xl border px-3 py-2 text-xs font-bold ${statusCls(selected.dataStatus)}`}>
          {selected.missingReason || statusLabel(selected.dataStatus)}
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-3">
        <Metric label="EPS" value={fmtNum(selected.eps)} />
        <Metric label="PER" value={fmtNum(selected.per)} />
        <Metric label="PBR" value={fmtNum(selected.pbr)} />
        <Metric label="ROE" value={fmtNum(selected.roe, "%")} />
        <Metric label="매출" value={fmtNum(selected.revenue)} />
        <Metric label="영업이익" value={fmtNum(selected.operatingProfit)} />
        <Metric label="순이익" value={fmtNum(selected.netIncome)} />
        <Metric label="부채비율" value={fmtNum(selected.debtRatio, "%")} />
        <Metric label="펀더멘털 점수" value={fmtNum(selected.fundamentalScore, "점")} />
      </div>

      {Array.isArray(selected.missingFields) && selected.missingFields.length > 0 && (
        <div className="mt-5 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
          <div className="mb-2 flex items-center gap-2 font-semibold">
            <AlertTriangle size={15} />
            누락 데이터
          </div>
          {selected.missingFields.join(", ")} 항목이 비어 있습니다. 보수/균형 추천에서는 리스크 감점 대상으로 처리해야 합니다.
        </div>
      )}

      <div className="mt-5 text-xs text-slate-500">출처: {selected.source || "local csv/json"}</div>
    </div>
  );
}

function NewsDetail({ selected }: { selected: any }) {
  const tags = Array.isArray(selected.tags) ? selected.tags : selected.tag ? [selected.tag] : [];
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-slate-100">{selected.title || selected.headline || "뉴스 제목 없음"}</h2>
        <p className="mt-2 text-sm text-slate-500">
          {selected.source || selected.publisher || "출처 미확인"} · {dateText(selected.publishedAt || selected.date)}
        </p>
      </div>
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tags.map((tag: string) => (
            <span key={tag} className="rounded-lg bg-blue-500/10 px-2 py-1 text-xs text-blue-300">{tag}</span>
          ))}
        </div>
      )}
      <p className="rounded-2xl bg-slate-950 p-4 text-sm leading-6 text-slate-300">
        {selected.summary || selected.description || "요약 데이터가 없습니다."}
      </p>
      {selected.url && (
        <a href={selected.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">
          <ExternalLink size={14} />
          원문 보기
        </a>
      )}
    </div>
  );
}

function DisclosureDetail({ selected }: { selected: any }) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-bold text-slate-100">{selected.title || selected.reportName || "공시 제목 없음"}</h2>
        <p className="mt-2 text-sm text-slate-500">
          {selected.company || selected.name || selected.symbol || "-"} · {selected.source || "DART/SEC"} · {dateText(selected.disclosedAt || selected.date)}
        </p>
      </div>
      {selected.isWarning && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-200">
          주의 공시로 분류되었습니다. 신규 진입 전 내용 확인이 필요합니다.
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Metric label="회사" value={selected.company || selected.name || "-"} />
        <Metric label="종목코드" value={selected.symbol || "-"} />
        <Metric label="출처" value={selected.source || "-"} />
        <Metric label="공시일" value={dateText(selected.disclosedAt || selected.date)} />
      </div>
      {selected.url && (
        <a href={selected.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">
          <ExternalLink size={14} />
          공시 원문 보기
        </a>
      )}
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
