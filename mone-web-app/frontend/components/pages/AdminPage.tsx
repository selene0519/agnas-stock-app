"use client";

import { useEffect, useState } from "react";
import { mone } from "@/lib/api";

function Metric({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: any;
  accent?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-2 text-xl font-bold ${accent ? "text-emerald-400" : "text-slate-100"}`}>
        {value}
      </div>
    </div>
  );
}

export default function AdminPage() {
  const [audit, setAudit] = useState<any>({ status: "LOADING", items: [] });
  const [github, setGithub] = useState<any>({ status: "LOADING" });
  const [virtualSummary, setVirtualSummary] = useState<any>({ status: "LOADING" });
  const [syncStatus, setSyncStatus] = useState<any>(null);
  const [syncing, setSyncing] = useState(false);

  async function load() {
    setAudit({ status: "LOADING", items: [] });
    setGithub({ status: "LOADING" });
    setVirtualSummary({ status: "LOADING" });

    try {
      const [a, g, v, s] = await Promise.all([
        mone.audit(),
        mone.github(),
        mone.virtualSummary({ market: "all" }),
        fetch("/mone-api/api/admin/sync-status").then((r) => r.json()).catch(() => null),
      ]);

      setAudit(a || { status: "ERROR", items: [] });
      setGithub(g || { status: "ERROR" });
      setVirtualSummary(v || { status: "ERROR" });
      setSyncStatus(s);
    } catch (error) {
      setAudit({ status: "ERROR", items: [] });
      setGithub({ status: "ERROR", error: String(error) });
      setVirtualSummary({ status: "ERROR" });
    }
  }

  async function syncNow() {
    setSyncing(true);
    try {
      const res = await fetch("/mone-api/api/admin/sync-now", { method: "POST" });
      const data = await res.json();
      setSyncStatus(data);
    } catch (e) {
      setSyncStatus({ status: "ERROR", error: String(e) });
    } finally {
      setSyncing(false);
      load();
    }
  }

  useEffect(() => {
    load();
  }, []);

  const items = Array.isArray(audit.items) ? audit.items : [];
  const githubOk = github.status === "OK" && github.isGitRepo === true;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">
            관리자 대시보드{" "}
            <span className="rounded bg-amber-500/20 px-2 py-1 text-xs text-amber-400">
              관리자
            </span>
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            데이터 파이프라인, GitHub 상태, 가상운용 결과를 점검합니다.
          </p>
        </div>

        <button
          onClick={load}
          className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800"
        >
          새로고침
        </button>
      </div>

      {/* GitHub 동기화 패널 */}
      <div className="rounded-2xl border border-blue-900/60 bg-blue-950/10 p-5">
        <div className="flex items-center justify-between">
          <div className="text-sm text-slate-400">GitHub 데이터 동기화</div>
          <button
            onClick={syncNow}
            disabled={syncing}
            className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {syncing ? "동기화 중..." : "지금 동기화"}
          </button>
        </div>
        {syncStatus && (
          <div className="mt-3 space-y-1 text-xs">
            <div className={syncStatus.status === "OK" ? "text-emerald-400" : "text-red-400"}>
              상태: {syncStatus.status}
            </div>
            {syncStatus.lastSyncAt && (
              <div className="text-slate-500">마지막 동기화: {syncStatus.lastSyncAt}</div>
            )}
            {syncStatus.filesChanged !== undefined && (
              <div className="text-slate-400">
                변경 파일: {syncStatus.filesChanged}개 · 캐시 초기화: {syncStatus.cachesCleared ?? 0}개
              </div>
            )}
            {syncStatus.afterCommit && (
              <div className="font-mono text-slate-500">커밋: {syncStatus.afterCommit}</div>
            )}
            {syncStatus.error && (
              <div className="break-all text-red-300">{syncStatus.error}</div>
            )}
          </div>
        )}
        <div className="mt-2 text-xs text-slate-600">
          백그라운드 자동 동기화: 30분 간격 · GIT_AUTO_SYNC_INTERVAL_MIN 환경변수로 조정
        </div>
      </div>

      <div className={`rounded-2xl border p-5 ${githubOk ? "border-emerald-900/60 bg-emerald-950/10" : "border-red-900/60 bg-red-950/10"}`}>
        <div className="text-sm text-slate-500">GitHub 상태</div>
        <div className={`mt-3 font-mono text-lg ${githubOk ? "text-emerald-400" : "text-red-400"}`}>
          {github.status === "LOADING"
            ? "확인 중..."
            : githubOk
              ? "Git 저장소가 감지되었습니다"
              : "Git 저장소가 감지되지 않았습니다"}
        </div>

        <div className="mt-2 break-all text-xs text-slate-500">
          브랜치: {github.branch || "-"} · 원격 저장소: {github.remote || "-"}
        </div>

        {github.error && <div className="mt-2 break-all text-xs text-red-300">{github.error}</div>}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Metric label="전체 추천" value={virtualSummary.totalRecommendations ?? "-"} />
        <Metric label="가상 체결" value={virtualSummary.executedTrades ?? "-"} />
        <Metric
          label="승률"
          value={virtualSummary.winRate !== undefined ? `${Number(virtualSummary.winRate).toFixed(2)}%` : "-"}
        />
        <Metric
          label="누적 수익률"
          value={virtualSummary.cumulativeReturnPct !== undefined ? `${Number(virtualSummary.cumulativeReturnPct).toFixed(2)}%` : "-"}
          accent
        />
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">데이터 점검</h2>
            <p className="text-sm text-slate-500">
              백엔드 루트, 데이터 상태, 감지된 파일을 표시합니다.
            </p>
          </div>
          <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">
            {audit.status || "UNKNOWN"}
          </span>
        </div>

        <div className="grid grid-cols-1 gap-2 text-xs text-slate-500 md:grid-cols-2">
          <div>
            백엔드 루트: <span className="font-mono text-slate-300">{audit.root || "-"}</span>
          </div>
          <div>
            상태: <span className="font-mono text-slate-300">{audit.status || "-"}</span>
          </div>
        </div>

        {Array.isArray(audit.searchRoots) && (
          <div className="mt-4">
            <div className="mb-2 text-xs font-semibold text-slate-400">검색 경로</div>
            <div className="space-y-1">
              {audit.searchRoots.slice(0, 12).map((root: string, idx: number) => (
                <div key={`${root}-${idx}`} className="break-all rounded-lg bg-slate-950/50 px-3 py-2 font-mono text-xs text-slate-400">
                  {root}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="border-b border-slate-800 text-slate-500">
              <tr>
                <th className="py-2 pr-3">항목</th>
                <th className="py-2 pr-3">상태</th>
                <th className="py-2 pr-3">건수</th>
                <th className="py-2 pr-3">경로</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td className="py-4 text-slate-500" colSpan={4}>
                    표시할 점검 항목이 없습니다.
                  </td>
                </tr>
              ) : (
                items.map((item: any, idx: number) => (
                  <tr key={`${item.name || "item"}-${idx}`} className="border-b border-slate-900">
                    <td className="py-2 pr-3 text-slate-300">{item.name || item.label || "-"}</td>
                    <td className="py-2 pr-3 text-slate-400">{item.status || "-"}</td>
                    <td className="py-2 pr-3 text-slate-400">{item.count ?? "-"}</td>
                    <td className="break-all py-2 pr-3 font-mono text-slate-500">{item.path || item.file || "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
