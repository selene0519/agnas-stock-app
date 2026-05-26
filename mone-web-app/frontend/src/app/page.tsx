"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { Sidebar } from "@/components/Sidebar";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyReason, Section, StatCard } from "@/components/Cards";
import { API_BASE, getJson, money, type ApiList, type Market, type Security } from "@/lib/api";

type FileItem = {
  path: string;
  exists: boolean;
  status: "OK" | "MISSING";
  bytes: number;
  rows: number;
  updatedAt: string;
};

type EnvItem = { key: string; status: "OK" | "MISSING" };
type NewsItem = {
  title: string;
  summary: string;
  sourceName: string;
  publishedAt: string;
  symbol: string;
  name: string;
  url?: string;
  nextAction?: string;
};

type MarketSummary = {
  market: Market;
  marketLabel: string;
  cards: Record<string, string>[];
  dataStatus: Record<string, string>[];
  dashboard: Record<string, string>[];
  sources: string[];
  updatedAt: string;
  automation?: Record<string, unknown>;
};

type HistoryResponse = {
  count: number;
  source: string;
  items: Record<string, string>[];
};

const implemented = new Set([
  "시장 홈",
  "선택 종목",
  "관심종목 / 후보군",
  "매수 후보",
  "매수금지 / 주의",
  "보유 관리",
  "손절·목표가",
  "뉴스·공시·기업분석",
  "확률 예측",
  "차트 보기",
  "리포트 센터",
  "데이터 점검",
  "API / 자동화 상태"
]);

const candidateTabs = [
  ["action", "오늘 확인"],
  ["pullback", "눌림목"],
  ["flow", "수급"],
  ["risk", "주의"]
] as const;

const sourceLabel = (source?: string) => source || "소스 없음";

export default function Home() {
  const [active, setActive] = useState("시장 홈");
  const [market, setMarket] = useState<Market>("kr");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<MarketSummary | null>(null);
  const [symbols, setSymbols] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [positions, setPositions] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [news, setNews] = useState<ApiList<NewsItem>>({ count: 0, items: [] });
  const [predictions, setPredictions] = useState<ApiList<Security>>({ count: 0, items: [] });
  const [candidates, setCandidates] = useState<Record<string, ApiList<Security>>>({});
  const [files, setFiles] = useState<FileItem[]>([]);
  const [env, setEnv] = useState<EnvItem[]>([]);
  const [predictionHistory, setPredictionHistory] = useState<HistoryResponse>({ count: 0, source: "", items: [] });
  const [outcomeHistory, setOutcomeHistory] = useState<HistoryResponse>({ count: 0, source: "", items: [] });
  const [query, setQuery] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState<Security | null>(null);
  const [candidateType, setCandidateType] = useState<(typeof candidateTabs)[number][0]>("action");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const [summaryData, symbolData, positionData, newsData, predictionData, fileData, envData, predHistory, outcomes] =
          await Promise.all([
            getJson<MarketSummary>(`/api/market/summary?market=${market}`),
            getJson<ApiList<Security>>(`/api/symbols?market=${market}`),
            getJson<ApiList<Security>>(`/api/positions?market=${market}`),
            getJson<ApiList<NewsItem>>(`/api/news?market=${market}`),
            getJson<ApiList<Security>>(`/api/predictions?market=${market}`),
            getJson<{ items: FileItem[] }>("/api/status/files"),
            getJson<{ items: EnvItem[] }>("/api/status/env"),
            getJson<HistoryResponse>("/api/history/predictions"),
            getJson<HistoryResponse>("/api/history/outcomes")
          ]);
        const candidateData = await Promise.all(
          candidateTabs.map(([type]) => getJson<ApiList<Security>>(`/api/candidates?market=${market}&type=${type}`))
        );
        if (cancelled) return;
        setSummary(summaryData);
        setSymbols(symbolData);
        setPositions(positionData);
        setNews(newsData);
        setPredictions(predictionData);
        setFiles(fileData.items);
        setEnv(envData.items);
        setPredictionHistory(predHistory);
        setOutcomeHistory(outcomes);
        setCandidates(Object.fromEntries(candidateTabs.map(([type], idx) => [type, candidateData[idx]])));
        setSelectedSymbol(symbolData.items[0] ?? null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "데이터 로딩 실패");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [market]);

  const filteredSymbols = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return symbols.items;
    return symbols.items.filter((item) => `${item.symbol} ${item.name}`.toLowerCase().includes(needle));
  }, [query, symbols.items]);

  const marketName = market === "kr" ? "국장" : "미장";
  const updatedAt = summary?.updatedAt ?? "기준시각 없음";
  const apiOk = env.filter((item) => item.status === "OK").length;
  const apiMissing = env.filter((item) => item.status === "MISSING").length;
  const filesMissing = files.filter((item) => item.status === "MISSING").length;

  const symbolColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "symbol", header: "코드", render: (row) => row.symbol },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} /> },
    { key: "entry", header: "기준가", render: (row) => money(row.entry, market) },
    { key: "stop", header: "손절", render: (row) => money(row.stop, market) },
    { key: "target", header: "목표", render: (row) => money(row.target, market) },
    { key: "status", header: "상태", render: (row) => row.dataStatus || "상태 없음" }
  ];

  const compactSymbolColumns: Column<Security>[] = [
    { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
    { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
    { key: "action", header: "다음 행동", render: (row) => row.nextAction || "다음 행동 없음" },
    { key: "reason", header: "근거", render: (row) => row.reason || row.warning || "근거 없음" }
  ];

  const historyChart = outcomeHistory.items.slice(-40).map((row, idx) => ({
    idx: idx + 1,
    date: row.date ?? `${idx + 1}`,
    value: Number(row.return_5d ?? row.return_3d ?? row.return_1d ?? 0)
  }));

  return (
    <main>
      <Sidebar active={active} onSelect={setActive} />
      <div className="min-h-screen pl-72">
        <header className="sticky top-0 z-10 border-b border-line bg-ink/95 backdrop-blur">
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3">
            <div>
              <div className="text-xs font-bold text-muted">데이터 기준시각</div>
              <div className="text-sm font-semibold text-slate-100">{updatedAt}</div>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-line bg-panel p-1">
              <button
                className={`rounded-md px-4 py-2 text-sm font-bold ${market === "kr" ? "bg-accent text-ink" : "text-slate-300"}`}
                onClick={() => setMarket("kr")}
              >
                국장
              </button>
              <button
                className={`rounded-md px-4 py-2 text-sm font-bold ${market === "us" ? "bg-accent text-ink" : "text-slate-300"}`}
                onClick={() => setMarket("us")}
              >
                미장
              </button>
            </div>
          </div>
        </header>

        <div className="px-6 py-5">
          <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-sm font-bold text-accent">{marketName}</div>
              <h1 className="mt-1 text-3xl font-black text-white">{active}</h1>
            </div>
            <div className="rounded-lg border border-line bg-panel px-4 py-3 text-sm text-muted">
              API {apiOk} OK / {apiMissing} MISSING · 파일 누락 {filesMissing}
            </div>
          </div>

          {loading ? <EmptyReason text="데이터를 읽는 중입니다." /> : null}
          {error ? <EmptyReason text={`API 연결 확인 필요: ${error}. backend 실행 주소는 ${API_BASE} 입니다.`} /> : null}
          {!loading && !error ? renderPage() : null}
        </div>
      </div>
    </main>
  );

  function renderPage() {
    if (!implemented.has(active)) return <ComingSoon title={active} />;
    if (active === "시장 홈") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <StatCard label="선택 종목" value={symbols.count} note={sourceLabel(symbols.source)} tone="accent" />
            <StatCard label="보유 종목" value={positions.count} note={sourceLabel(positions.source)} tone="good" />
            <StatCard label="뉴스" value={news.count || "뉴스 없음"} note={sourceLabel(news.source)} tone={news.count ? "accent" : "warn"} />
            <StatCard label="예측 이력" value={predictionHistory.count} note={predictionHistory.source} />
          </div>
          <Section title="오늘 요약">
            {summary?.cards?.length ? (
              <div className="grid gap-3 md:grid-cols-5">
                {summary.cards.map((card, idx) => (
                  <StatCard
                    key={idx}
                    label={String(card["카드"] ?? card["category"] ?? `요약 ${idx + 1}`)}
                    value={String(card["건수"] ?? card["count"] ?? "-")}
                    note={String(card["TOP"] ?? card["설명"] ?? "요약 없음")}
                    tone={idx === 0 ? "good" : "neutral"}
                  />
                ))}
              </div>
            ) : (
              <EmptyReason text="오늘 요약 파일이 없습니다." />
            )}
          </Section>
          <Section title="운영 대시보드">
            <SimpleRecords rows={summary?.dashboard ?? []} empty="운영 대시보드 데이터 없음" />
          </Section>
        </>
      );
    }

    if (active === "선택 종목" || active === "관심종목 / 후보군") {
      return (
        <>
          <Section
            title={`${marketName} 선택 종목`}
            right={<span className="text-xs text-muted">{symbols.count}개 · {sourceLabel(symbols.source)}</span>}
          >
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="종목명 또는 코드 검색"
              className="mb-3 w-full rounded-lg border border-line bg-panel px-4 py-3 text-sm outline-none focus:border-accent"
            />
            <DataTable rows={filteredSymbols} columns={symbolColumns} onRowClick={setSelectedSymbol} />
          </Section>
          <Section title="상세 카드">
            {selectedSymbol ? <SymbolDetailCard item={selectedSymbol} /> : <EmptyReason text="선택된 종목이 없습니다." />}
          </Section>
        </>
      );
    }

    if (active === "매수 후보" || active === "매수금지 / 주의") {
      const type = active === "매수금지 / 주의" ? "risk" : candidateType;
      const list = candidates[type]?.items ?? [];
      return (
        <>
          <div className="flex flex-wrap gap-2">
            {candidateTabs.map(([typeId, label]) => (
              <button
                key={typeId}
                onClick={() => setCandidateType(typeId)}
                className={`rounded-md border px-3 py-2 text-sm font-bold ${
                  type === typeId ? "border-accent bg-accent/15 text-accent" : "border-line bg-panel text-slate-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <Section title={`${marketName} ${active === "매수금지 / 주의" ? "주의 후보" : "매수 후보"}`}>
            <DataTable rows={list} columns={compactSymbolColumns} onRowClick={setSelectedSymbol} />
          </Section>
        </>
      );
    }

    if (active === "보유 관리" || active === "손절·목표가") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="보유 종목" value={positions.count} note={sourceLabel(positions.source)} tone="good" />
            <StatCard label="손절·목표 기준" value="표시" note="현재가·기준시각·출처 포함" tone="accent" />
            <StatCard label="데이터 모드" value="Read-only" note="기존 holdings 파일 미수정" />
          </div>
          <Section title={`${marketName} 보유 현황`}>
            <DataTable rows={positions.items} columns={symbolColumns} onRowClick={setSelectedSymbol} />
          </Section>
        </>
      );
    }

    if (active === "뉴스·공시·기업분석") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="뉴스" value={news.count || "뉴스 없음"} note={sourceLabel(news.source)} tone={news.count ? "accent" : "warn"} />
            <StatCard label="기업분석" value={symbols.count ? "연결됨" : "기준가 없음"} note="company_integrated report" />
            <StatCard label="시장" value={marketName} note="뉴스·공시·재무 통합 화면" />
          </div>
          <Section title="뉴스">
            {news.items.length ? (
              <div className="grid gap-3 lg:grid-cols-2">
                {news.items.map((item, idx) => (
                  <a
                    key={idx}
                    href={item.url || undefined}
                    target="_blank"
                    className="rounded-lg border border-line bg-card p-4 hover:border-accent/50"
                  >
                    <div className="text-xs text-muted">{item.sourceName} · {item.publishedAt}</div>
                    <div className="mt-2 font-black text-white">{item.title}</div>
                    <p className="mt-2 text-sm leading-6 text-slate-300">{item.summary || "요약 없음"}</p>
                    <div className="mt-3 text-xs text-accent">{item.name || item.symbol || "연결 종목 없음"}</div>
                  </a>
                ))}
              </div>
            ) : (
              <EmptyReason text="뉴스 없음" />
            )}
          </Section>
        </>
      );
    }

    if (active === "확률 예측") {
      return (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="확률 행" value={predictions.count} note={sourceLabel(predictions.source)} tone="accent" />
            <StatCard label="prediction_history" value={predictionHistory.count} note={predictionHistory.source} />
            <StatCard label="outcome_history" value={outcomeHistory.count} note={outcomeHistory.source} />
          </div>
          <Section title="확률 예측">
            <DataTable
              rows={predictions.items}
              columns={[
                { key: "name", header: "종목", render: (row) => <b>{row.name}</b> },
                { key: "price", header: "현재가", render: (row) => <PriceBlock item={row} compact /> },
                { key: "confidence", header: "신뢰도", render: (row) => String(row.confidence ?? "신뢰도 없음") },
                { key: "action", header: "다음 행동", render: (row) => row.nextAction || "다음 행동 없음" }
              ]}
              onRowClick={setSelectedSymbol}
            />
          </Section>
        </>
      );
    }

    if (active === "차트 보기") {
      return (
        <>
          <Section title="차트 보기">
            {historyChart.length ? (
              <div className="h-72 rounded-lg border border-line bg-panel p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={historyChart}>
                    <defs>
                      <linearGradient id="returnGradient" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.7} />
                        <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.05} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="rgba(148,163,184,.16)" />
                    <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid rgba(148,163,184,.25)" }} />
                    <Area type="monotone" dataKey="value" stroke="#38bdf8" fill="url(#returnGradient)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyReason text="차트 데이터 부족" />
            )}
          </Section>
          <Section title="선택 종목 가격 기준">
            <DataTable rows={symbols.items.slice(0, 20)} columns={symbolColumns} onRowClick={setSelectedSymbol} />
          </Section>
        </>
      );
    }

    if (active === "리포트 센터" || active === "데이터 점검") {
      return (
        <Section title="필수 파일 상태">
          <DataTable
            rows={files}
            columns={[
              { key: "path", header: "파일", render: (row) => row.path },
              { key: "status", header: "상태", render: (row) => <StatusPill status={row.status} /> },
              { key: "rows", header: "rows", render: (row) => row.rows },
              { key: "updated", header: "수정시각", render: (row) => row.updatedAt || "기준시각 없음" }
            ]}
          />
        </Section>
      );
    }

    if (active === "API / 자동화 상태") {
      const ok = env.filter((item) => item.status === "OK").length;
      const missing = env.filter((item) => item.status === "MISSING").length;
      const chart = [
        { name: "OK", value: ok },
        { name: "MISSING", value: missing }
      ];
      return (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="API OK" value={ok} tone="good" />
            <StatCard label="API MISSING" value={missing} tone={missing ? "warn" : "good"} />
            <StatCard label="Backend" value="OK" note={API_BASE} tone="accent" />
          </div>
          <Section title="환경 변수 상태">
            <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
              <DataTable
                rows={env}
                columns={[
                  { key: "key", header: "키", render: (row) => row.key },
                  { key: "status", header: "상태", render: (row) => <StatusPill status={row.status} /> }
                ]}
              />
              <div className="h-64 rounded-lg border border-line bg-panel p-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chart}>
                    <CartesianGrid stroke="rgba(148,163,184,.16)" />
                    <XAxis dataKey="name" stroke="#94a3b8" />
                    <YAxis allowDecimals={false} stroke="#94a3b8" />
                    <Tooltip contentStyle={{ background: "#0b1220", border: "1px solid rgba(148,163,184,.25)" }} />
                    <Bar dataKey="value" fill="#38bdf8" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </Section>
        </>
      );
    }
  }
}

function PriceBlock({ item, compact = false }: { item: Security; compact?: boolean }) {
  return (
    <div>
      <div className={compact ? "font-bold text-white" : "text-base font-black text-white"}>{item.currentPriceText || "기준가 없음"}</div>
      <div className="mt-1 text-xs leading-5 text-muted">
        {item.priceTime || "기준시각 없음"} · {item.priceSource || "가격출처 없음"}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const ok = status === "OK";
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-black ${ok ? "bg-good/15 text-good" : "bg-warn/15 text-warn"}`}>
      {status}
    </span>
  );
}

function SymbolDetailCard({ item }: { item: Security }) {
  return (
    <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr]">
      <div className="rounded-lg border border-line bg-card p-4">
        <div className="text-sm text-muted">{item.marketLabel} · {item.symbol}</div>
        <div className="mt-1 text-2xl font-black text-white">{item.name}</div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <StatCard label="현재가" value={item.currentPriceText} note={`${item.priceTime} · ${item.priceSource}`} tone="accent" />
          <StatCard label="기준가" value={money(item.entry, item.market)} />
          <StatCard label="손절 / 목표" value={`${money(item.stop, item.market)} / ${money(item.target, item.market)}`} tone="warn" />
        </div>
      </div>
      <div className="rounded-lg border border-line bg-panel p-4">
        <div className="text-sm font-black text-white">상태</div>
        <p className="mt-2 text-sm leading-6 text-slate-300">{item.dataStatus || "상태 없음"}</p>
        <div className="mt-4 text-xs text-muted">값이 없으면 기준가 없음 또는 가격출처 없음으로 표시합니다.</div>
      </div>
    </div>
  );
}

function SimpleRecords({ rows, empty }: { rows: Record<string, string>[]; empty: string }) {
  if (!rows.length) return <EmptyReason text={empty} />;
  const keys = Object.keys(rows[0] ?? {}).slice(0, 5);
  return (
    <DataTable<Record<string, string>>
      rows={rows}
      columns={keys.map((key) => ({
        key,
        header: key,
        render: (row) => String(row[key] ?? "-")
      }))}
    />
  );
}

function ComingSoon({ title }: { title: string }) {
  return (
    <div className="rounded-lg border border-line bg-card p-8">
      <div className="text-sm font-bold text-accent">준비 중</div>
      <h2 className="mt-2 text-2xl font-black text-white">{title}</h2>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">
        메뉴는 v1 정보 구조에 포함했습니다. 기존 Streamlit 기능과 reports 산출물 연결을 확인한 뒤 순차적으로 실제 화면으로 확장합니다.
      </p>
    </div>
  );
}
