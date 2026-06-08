"use client";

import { useEffect, useState } from "react";
import { mone } from "@/lib/api";
import { adminAuthHeaders } from "@/lib/adminAuth";
import AdvancedPage from "./AdvancedPage";
import NewsPage from "./NewsPage";
import PredictionPage from "./PredictionPage";

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  OK:             { text: "정상",              cls: "text-emerald-400" },
  LOCAL_CHANGES:  { text: "로컬 수정사항 있음",   cls: "text-amber-300" },
  BEHIND_REMOTE:  { text: "원격보다 뒤처짐",      cls: "text-sky-300" },
  CONFLICT_RISK:  { text: "충돌 위험",           cls: "text-red-400" },
  NETWORK_ERROR:  { text: "네트워크 오류",        cls: "text-orange-400" },
  NOT_GIT_REPO:   { text: "Git 저장소 아님",      cls: "text-red-400" },
  NOT_RUN:        { text: "미실행",              cls: "text-slate-500" },
  SYNC_STARTED:   { text: "동기화 시작됨",        cls: "text-blue-300" },
  ERROR:          { text: "오류",               cls: "text-red-400" },
};

function syncStatusDisplay(status: string) {
  return STATUS_LABEL[status] ?? { text: status, cls: "text-slate-400" };
}

function Metric({ label, value, accent = false }: { label: string; value: any; accent?: boolean }) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-2 text-xl font-bold ${accent ? "text-emerald-400" : "text-slate-100"}`}>{value}</div>
    </div>
  );
}

function ActionBtn({ label, onClick, loading, variant = "default" }: {
  label: string; onClick: () => void; loading?: boolean; variant?: "default" | "danger" | "blue" | "green";
}) {
  const cls = {
    default: "border-slate-700 bg-slate-900 text-slate-200 hover:bg-slate-800",
    danger:  "border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20",
    blue:    "border-blue-500/30 bg-blue-600 text-white hover:bg-blue-500",
    green:   "border-emerald-500/30 bg-emerald-600 text-white hover:bg-emerald-500",
  }[variant];
  return (
    <button onClick={onClick} disabled={loading} className={`rounded-xl border px-4 py-2 text-sm font-medium disabled:opacity-50 ${cls}`}>
      {loading ? "처리 중..." : label}
    </button>
  );
}

const USER_FILES = ["holdings_kr.csv", "holdings_us.csv", "watchlist_kr.csv", "watchlist_us.csv"];
type AdminTab = "overview" | "prediction" | "news" | "advanced";

const ADMIN_TABS: { id: AdminTab; label: string }[] = [
  { id: "overview", label: "운영" },
  { id: "prediction", label: "예측분석" },
  { id: "news", label: "뉴스·공시" },
  { id: "advanced", label: "고급분석" },
];

function pct(value: any) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : "-";
}

interface AdminPageProps {
  authToken: string;
  onLogout?: () => void;
}

export default function AdminPage({ authToken, onLogout }: AdminPageProps) {
  const [tab, setTab] = useState<AdminTab>("overview");
  const [audit, setAudit] = useState<any>({ status: "LOADING", items: [] });
  const [github, setGithub] = useState<any>({ status: "LOADING" });
  const [virtualSummary, setVirtualSummary] = useState<any>({ status: "LOADING" });
  const [trendlineAccuracy, setTrendlineAccuracy] = useState<any>({ status: "LOADING" });
  const [syncStatus, setSyncStatus] = useState<any>(null);
  const [syncing, setSyncing] = useState(false);
  const [cacheClearing, setCacheClearing] = useState(false);
  const [quoteRefreshing, setQuoteRefreshing] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    setGithub({ status: "LOADING" });
    setVirtualSummary({ status: "LOADING" });
    try {
      const [g, v, s] = await Promise.all([
        mone.github(),
        mone.virtualSummary({ market: "all" }),
        fetch("/mone-api/api/admin/sync-status", { headers: adminAuthHeaders(authToken) }).then((r) => r.json()).catch(() => null),
      ]);
      setGithub(g || { status: "ERROR" });
      setVirtualSummary(v || { status: "ERROR" });
      setSyncStatus(s);
    } catch (error) {
      setGithub({ status: "ERROR", error: String(error) });
      setVirtualSummary({ status: "ERROR" });
    }
    mone.trendlineAccuracy({ market: "all", futureBars: 20, symbolLimit: 12, maxCutoffs: 6 })
      .then((a) => setTrendlineAccuracy(a || { status: "ERROR" }))
      .catch((error) => setTrendlineAccuracy({ status: "ERROR", error: String(error) }));
    setAudit({ status: "LOADING", items: [] });
    mone.audit()
      .then((a) => setAudit(a || { status: "ERROR", items: [] }))
      .catch(() => setAudit({ status: "ERROR", items: [] }));
  }

  async function syncNow() {
    setSyncing(true);
    setMessage("");
    try {
      const res = await fetch("/mone-api/api/admin/sync-now", { method: "POST", headers: adminAuthHeaders(authToken) });
      const data = await res.json();
      setSyncStatus(data);
      setMessage(data.statusLabel || (data.status === "OK" ? "동기화 완료" : `동기화 실패: ${data.status}`));
    } catch (e) {
      setSyncStatus({ status: "ERROR", error: String(e) });
    } finally {
      setSyncing(false);
      load();
    }
  }

  async function clearCache() {
    setCacheClearing(true);
    setMessage("");
    try {
      const res = await fetch("/mone-api/api/admin/cache-clear", { method: "POST", headers: adminAuthHeaders(authToken) });
      const data = await res.json();
      setMessage(`캐시 ${data.cachesCleared ?? 0}개 초기화 완료`);
    } catch (e) {
      setMessage(`캐시 초기화 실패: ${e}`);
    } finally {
      setCacheClearing(false);
    }
  }

  async function refreshQuotes() {
    setQuoteRefreshing(true);
    setMessage("");
    try {
      const res = await fetch("/mone-api/api/quotes/refresh-targets", { method: "POST", headers: { "Content-Type": "application/json", ...adminAuthHeaders(authToken) }, body: JSON.stringify({ market: "all", limit: 100 }) });
      const data = await res.json();
      setMessage(`현재가 갱신 완료: 성공 ${data.successCount ?? 0} / 실패 ${data.failureCount ?? 0}`);
    } catch (e) {
      setMessage(`현재가 갱신 실패: ${e}`);
    } finally {
      setQuoteRefreshing(false);
    }
  }

  useEffect(() => { load(); }, [authToken]);

  const items = Array.isArray(audit.items) ? audit.items : [];
  const githubOk = github.status === "OK" && github.isGitRepo === true;
  const syncDisp = syncStatusDisplay(syncStatus?.status || "NOT_RUN");

  const userItems = items.filter((item: any) => USER_FILES.some((f) => (item.path || item.file || "").includes(f)));
  const autoItems = items.filter((item: any) => !USER_FILES.some((f) => (item.path || item.file || "").includes(f)));

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">
            관리자 대시보드{" "}
            <span className="rounded bg-amber-500/20 px-2 py-1 text-xs text-amber-400">관리자</span>
          </h1>
          <p className="mt-1 text-sm text-slate-400">데이터 파이프라인, GitHub 상태, 가상운용 결과를 점검합니다.</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button onClick={load} className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">새로고침</button>
          {onLogout && (
            <button onClick={onLogout} className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200 hover:bg-red-500/20">
              로그아웃
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
        {ADMIN_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={`rounded-xl border px-3 py-2 text-sm font-medium ${tab === item.id ? "border-blue-500 bg-blue-600 text-white" : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "prediction" && <PredictionPage />}
      {tab === "news" && <NewsPage />}
      {tab === "advanced" && <AdvancedPage />}
      {tab !== "overview" && null}
      {tab === "overview" && (
        <>

      {message && (
        <div className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-300">
          {message}
          <button onClick={() => setMessage("")} className="ml-3 text-slate-600 hover:text-slate-400">✕</button>
        </div>
      )}

      {/* 액션 버튼 묶음 */}
      <div className="flex flex-wrap gap-2">
        <ActionBtn label={syncing ? "동기화 중..." : "GitHub 동기화"} onClick={syncNow} loading={syncing} variant="blue" />
        <ActionBtn label={cacheClearing ? "초기화 중..." : "캐시 초기화"} onClick={clearCache} loading={cacheClearing} />
        <ActionBtn label={quoteRefreshing ? "갱신 중..." : "현재가 갱신"} onClick={refreshQuotes} loading={quoteRefreshing} variant="green" />
      </div>

      {/* GitHub 동기화 상태 */}
      <div className={`rounded-2xl border p-5 ${syncStatus?.status === "OK" ? "border-blue-900/50 bg-blue-950/10" : syncStatus?.status ? "border-amber-900/50 bg-amber-950/10" : "border-slate-800 bg-slate-900/40"}`}>
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-semibold text-slate-300">GitHub 데이터 동기화</div>
          <span className={`font-mono text-sm font-bold ${syncDisp.cls}`}>{syncDisp.text}</span>
        </div>
        {syncStatus && (
          <div className="mt-3 space-y-1 text-xs">
            {syncStatus.statusLabel && <div className="text-slate-400">{syncStatus.statusLabel}</div>}
            {syncStatus.lastSyncAt && <div className="text-slate-500">마지막 동기화: {syncStatus.lastSyncAt}</div>}
            {syncStatus.filesChanged !== undefined && (
              <div className="text-slate-400">변경 파일: {syncStatus.filesChanged}개 · 캐시 초기화: {syncStatus.cachesCleared ?? 0}개</div>
            )}
            {syncStatus.afterCommit && <div className="font-mono text-slate-500">현재 커밋: {syncStatus.afterCommit}</div>}
            {syncStatus.error && <div className="break-all text-red-300">{syncStatus.error}</div>}
            {syncStatus.status === "LOCAL_CHANGES" && (
              <div className="mt-1 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-amber-200">
                로컬에 커밋되지 않은 변경사항이 있습니다. 보유종목/관심종목 파일이 수정됐을 수 있으니 그대로 유지됩니다.
              </div>
            )}
          </div>
        )}
        <div className="mt-2 text-xs text-slate-600">백그라운드 자동 동기화: 30분 간격 · GIT_AUTO_SYNC_INTERVAL_MIN 환경변수로 조정</div>
      </div>

      {/* GitHub 저장소 상태 */}
      <div className={`rounded-2xl border p-5 ${githubOk ? "border-emerald-900/60 bg-emerald-950/10" : "border-red-900/60 bg-red-950/10"}`}>
        <div className="text-sm text-slate-500">GitHub 저장소 상태</div>
        <div className={`mt-3 font-mono text-lg ${githubOk ? "text-emerald-400" : "text-red-400"}`}>
          {github.status === "LOADING" ? "확인 중..." : githubOk ? "Git 저장소 감지됨" : "Git 저장소 미감지"}
        </div>
        <div className="mt-2 break-all text-xs text-slate-500">
          브랜치: {github.branch || "-"} · 원격 저장소: {github.remote || "-"}
        </div>
        {github.error && <div className="mt-2 break-all text-xs text-red-300">{github.error}</div>}
      </div>

      {/* 가상운용 요약 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric label="전체 추천" value={virtualSummary.totalRecommendations ?? "-"} />
        <Metric label="가상 체결" value={virtualSummary.executedTrades ?? "-"} />
        <Metric label="승률" value={virtualSummary.winRate !== undefined ? `${Number(virtualSummary.winRate).toFixed(2)}%` : "-"} />
        <Metric label="누적 수익률" value={virtualSummary.cumulativeReturnPct !== undefined ? `${Number(virtualSummary.cumulativeReturnPct).toFixed(2)}%` : "-"} accent />
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">빗각 과거 검증</h2>
            <p className="text-sm text-slate-500">과거 시점에서 그은 지지·저항 빗각을 다음 20봉 실제 고저가로 검증합니다.</p>
          </div>
          <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">{trendlineAccuracy.status || "UNKNOWN"}</span>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Metric label="표본" value={trendlineAccuracy.sampleCount ?? "-"} />
          <Metric label="전체 존중률" value={pct(trendlineAccuracy.respectRatePct)} accent />
          <Metric label="지지선 존중률" value={pct(trendlineAccuracy.supportRespectRatePct)} />
          <Metric label="저항선 존중률" value={pct(trendlineAccuracy.resistanceRespectRatePct)} />
          <Metric label="고신뢰 존중률" value={pct(trendlineAccuracy.highConfidenceRespectRatePct)} accent />
        </div>
        {trendlineAccuracy.policy && <div className="mt-3 text-xs text-slate-500">{trendlineAccuracy.policy}</div>}
        {trendlineAccuracy.error && <div className="mt-3 break-all text-xs text-red-300">{trendlineAccuracy.error}</div>}
      </div>

      {/* 데이터 점검 */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">데이터 점검</h2>
            <p className="text-sm text-slate-500">백엔드 루트, 데이터 상태, 파일 구분을 표시합니다.</p>
          </div>
          <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">{audit.status || "UNKNOWN"}</span>
        </div>

        <div className="grid grid-cols-1 gap-2 text-xs text-slate-500 md:grid-cols-2">
          <div>백엔드 루트: <span className="font-mono text-slate-300">{audit.root || "-"}</span></div>
          <div>상태: <span className="font-mono text-slate-300">{audit.status || "-"}</span></div>
        </div>

        {/* 사용자 원장 파일 */}
        {userItems.length > 0 && (
          <div className="mt-5">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-emerald-400">
              <span>사용자 입력 파일</span>
              <span className="rounded-full border border-emerald-500/30 px-2 py-0.5 text-[10px]">보호 대상 — pull 시 덮이지 않음</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-slate-800 text-slate-500"><tr><th className="py-2 pr-3">항목</th><th className="py-2 pr-3">상태</th><th className="py-2 pr-3">건수</th><th className="py-2 pr-3">경로</th></tr></thead>
                <tbody>
                  {userItems.map((item: any, idx: number) => (
                    <tr key={idx} className="border-b border-slate-900">
                      <td className="py-2 pr-3 text-emerald-300">{item.name || item.label || "-"}</td>
                      <td className="py-2 pr-3 text-slate-400">{item.status || "-"}</td>
                      <td className="py-2 pr-3 text-slate-400">{item.count ?? "-"}</td>
                      <td className="break-all py-2 pr-3 font-mono text-slate-500">{item.path || item.file || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* 자동 생성 파일 */}
        <div className="mt-5">
          <div className="mb-2 text-xs font-semibold text-slate-400">자동 생성 파일 (GitHub Actions)</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-800 text-slate-500"><tr><th className="py-2 pr-3">항목</th><th className="py-2 pr-3">상태</th><th className="py-2 pr-3">건수</th><th className="py-2 pr-3">경로</th></tr></thead>
              <tbody>
                {autoItems.length === 0 && items.length > 0 && (
                  <tr><td colSpan={4} className="py-4 text-slate-500">자동 생성 파일이 없습니다.</td></tr>
                )}
                {autoItems.length === 0 && items.length === 0 && (
                  <tr><td colSpan={4} className="py-4 text-slate-500">{audit.status === "LOADING" ? "불러오는 중..." : "점검 항목이 없습니다."}</td></tr>
                )}
                {autoItems.map((item: any, idx: number) => (
                  <tr key={idx} className="border-b border-slate-900">
                    <td className="py-2 pr-3 text-slate-300">{item.name || item.label || "-"}</td>
                    <td className="py-2 pr-3 text-slate-400">{item.status || "-"}</td>
                    <td className="py-2 pr-3 text-slate-400">{item.count ?? "-"}</td>
                    <td className="break-all py-2 pr-3 font-mono text-slate-500">{item.path || item.file || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
        </>
      )}
    </div>
  );
}
