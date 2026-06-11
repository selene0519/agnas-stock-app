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
  NO_GIT_REMOTE:  { text: "원격 없음",            cls: "text-amber-300" },
  DEPLOYMENT_NO_GIT: { text: "배포 pull 생략",     cls: "text-sky-300" },
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
type AdminTab = "overview" | "prediction" | "news" | "advanced" | "correction";

const ADMIN_TABS: { id: AdminTab; label: string }[] = [
  { id: "overview", label: "운영" },
  { id: "prediction", label: "예측분석" },
  { id: "news", label: "뉴스·공시" },
  { id: "advanced", label: "전략도구" },
  { id: "correction", label: "자가보정" },
];

function pct(value: any) {
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : "-";
}

interface CorrectionTabProps {
  authToken: string;
  market: string; mode: string; horizon: string;
  dash: any; preview: any;
  loading: boolean; rebuildLoading: boolean;
  onMarketChange: (m: string) => void;
  onModeChange: (m: string) => void;
  onHorizonChange: (h: string) => void;
  onLoadDash: () => void;
  onLoadPreview: () => void;
  onRebuild: () => void;
  message: string;
  setMessage: (m: string) => void;
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  const color = pct >= 60 ? "bg-emerald-500" : pct >= 35 ? "bg-amber-400" : "bg-red-500/60";
  return (
    <div className="mt-1 h-1.5 w-full rounded-full bg-slate-800">
      <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function CorrectionTab({ market, mode, horizon, dash, preview, loading, rebuildLoading,
  onMarketChange, onModeChange, onHorizonChange, onLoadDash, onLoadPreview, onRebuild }: CorrectionTabProps) {

  const MODES = ["conservative", "balanced", "aggressive"];
  const HORIZONS = ["short", "swing", "mid"];

  const corr = dash?.correctionsByKey ?? {};
  const perf = dash?.performanceStats ?? {};
  const enabledStr = dash?.correctionEnabled === false ? "비활성" : "활성";
  const enabledCls = dash?.correctionEnabled === false ? "text-red-400" : "text-emerald-400";
  const strength = dash?.correctionStrength ?? 1.0;

  return (
    <div className="space-y-6">
      {/* 헤더 & 컨트롤 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-100">자가보정 대시보드</h2>
          <p className="text-sm text-slate-400">가상검증 결과 기반 추천 파라미터 자동 보정 현황을 점검합니다.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {["kr", "us"].map((m) => (
            <button key={m} onClick={() => onMarketChange(m)}
              className={`rounded-xl border px-3 py-1.5 text-sm font-medium ${market === m ? "border-blue-500 bg-blue-600 text-white" : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"}`}>
              {m.toUpperCase()}
            </button>
          ))}
          <button onClick={onLoadDash} disabled={loading}
            className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50">
            {loading ? "불러오는 중..." : "대시보드 갱신"}
          </button>
          <button onClick={onRebuild} disabled={rebuildLoading}
            className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-sm text-amber-200 hover:bg-amber-500/20 disabled:opacity-50">
            {rebuildLoading ? "재계산 중..." : "보정 파라미터 재계산"}
          </button>
        </div>
      </div>

      {!dash && !loading && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-8 text-center text-slate-400">
          대시보드를 불러오려면 &quot;대시보드 갱신&quot; 버튼을 누르세요.
        </div>
      )}
      {loading && (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-8 text-center text-slate-400">불러오는 중...</div>
      )}

      {dash && !loading && (
        <>
          {/* 킬스위치 & 환경 상태 */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Metric label="킬스위치" value={<span className={enabledCls}>{enabledStr}</span>} />
            <Metric label="보정 강도" value={`${(strength * 100).toFixed(0)}%`} />
            <Metric label="파라미터 버전" value={`v${dash.paramsVersion ?? "-"}`} />
            <Metric label="전체 샘플" value={dash.totalSamples ?? "-"} />
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3 text-xs text-slate-400 space-y-1">
            <div><span className="text-amber-300 font-semibold">킬스위치 제어:</span> Render 환경변수 <code className="font-mono bg-slate-800 px-1 rounded">SELF_CORRECTION_ENABLED=false</code> → 즉시 비활성</div>
            <div><span className="text-amber-300 font-semibold">보정 강도:</span> <code className="font-mono bg-slate-800 px-1 rounded">CORRECTION_STRENGTH=0.25</code> (0.0~1.0, 기본 1.0)</div>
            <div className="text-slate-500">파라미터 생성: {dash.paramsGeneratedAt ? new Date(dash.paramsGeneratedAt).toLocaleString("ko-KR") : "-"}</div>
          </div>

          {/* 성과 지표 */}
          {perf.settledCount > 0 && (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <h3 className="mb-3 text-sm font-semibold text-slate-300">가상검증 성과 지표</h3>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Metric label="체결 / 정산" value={`${perf.executedCount ?? 0} / ${perf.settledCount ?? 0}`} />
                <Metric label="승률" value={`${perf.winRate ?? 0}%`} accent />
                <Metric label="손절률" value={`${perf.stopRate ?? 0}%`} />
                <Metric label="미체결률" value={`${perf.missRate ?? 0}%`} />
              </div>
              {perf.avgNetPnl !== undefined && (
                <div className={`mt-3 text-sm font-semibold ${perf.avgNetPnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  평균 수익률: {perf.avgNetPnl >= 0 ? "+" : ""}{Number(perf.avgNetPnl).toFixed(2)}%
                </div>
              )}
            </div>
          )}

          {/* 전략별 보정 현황 */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <h3 className="mb-4 text-sm font-semibold text-slate-300">{market.toUpperCase()} 전략별 보정 상태</h3>
            <div className="space-y-3">
              {Object.entries(corr).length === 0 && (
                <div className="text-sm text-slate-500">데이터 없음 — 보정 파라미터를 재계산해 주세요.</div>
              )}
              {Object.entries(corr).map(([key, c]: [string, any]) => {
                const parts = key.split("_");
                const keyMode = parts[1] ?? "";
                const keyHorizon = parts[2] ?? "";
                const isActive = c.correctionActive && dash?.correctionEnabled !== false;
                return (
                  <div key={key} className={`rounded-xl border p-4 ${isActive ? "border-emerald-800/50 bg-emerald-950/10" : "border-slate-800 bg-slate-900/40"}`}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <span className="font-mono text-sm font-semibold text-slate-200">{keyMode} / {keyHorizon}</span>
                        <span className={`ml-2 rounded-full px-2 py-0.5 text-[10px] font-medium ${isActive ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-700 text-slate-400"}`}>
                          {isActive ? "보정 적용 중" : "보정 미적용"}
                        </span>
                      </div>
                      <div className="text-right text-xs text-slate-400">
                        <div>샘플 {c.sampleCount ?? 0}건 (학습 {c.learnableSampleCount ?? 0}건)</div>
                        <div>신뢰도 {((c.confidence ?? 0) * 100).toFixed(0)}%</div>
                      </div>
                    </div>
                    <ConfidenceBar value={c.confidence ?? 0} />
                    {c.topFailureReasons?.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {c.topFailureReasons.map((r: string) => (
                          <span key={r} className="rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-300 border border-red-500/20">{r}</span>
                        ))}
                      </div>
                    )}
                    {c.priceAdjustments && Object.keys(c.priceAdjustments).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-slate-400">
                        {Object.entries(c.priceAdjustments).map(([k, v]: [string, any]) => (
                          <span key={k}>{k}: <span className={Number(v) >= 0 ? "text-emerald-400" : "text-red-400"}>{Number(v) >= 0 ? "+" : ""}{Number(v).toFixed(3)}</span></span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* 전후 미리보기 */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-300">보정 전/후 미리보기</h3>
              <div className="flex flex-wrap gap-2">
                {MODES.map((m) => (
                  <button key={m} onClick={() => onModeChange(m)}
                    className={`rounded-lg border px-2.5 py-1 text-xs ${mode === m ? "border-blue-500 bg-blue-600 text-white" : "border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}>
                    {m}
                  </button>
                ))}
                {HORIZONS.map((h) => (
                  <button key={h} onClick={() => onHorizonChange(h)}
                    className={`rounded-lg border px-2.5 py-1 text-xs ${horizon === h ? "border-purple-500 bg-purple-600 text-white" : "border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}>
                    {h}
                  </button>
                ))}
                <button onClick={onLoadPreview}
                  className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-200 hover:bg-slate-800">
                  미리보기 로드
                </button>
              </div>
            </div>

            {!preview && <div className="text-sm text-slate-500">전략을 선택하고 &quot;미리보기 로드&quot;를 누르세요.</div>}
            {preview?.status === "ERROR" && <div className="text-sm text-red-400">{preview.error}</div>}
            {preview?.items?.length > 0 && (
              <>
                <div className="mb-2 flex gap-3 text-xs text-slate-400">
                  <span>보정 적용: <span className={preview.correctionEnabled ? "text-emerald-400" : "text-red-400"}>{preview.correctionEnabled ? "ON" : "OFF"}</span></span>
                  <span>강도: {((preview.correctionStrength ?? 1) * 100).toFixed(0)}%</span>
                  <span>신뢰도: {((preview.confidence ?? 0) * 100).toFixed(0)}%</span>
                  <span>샘플: {preview.sampleCount ?? 0}건</span>
                </div>
                {preview.topFailureReasons?.length > 0 && (
                  <div className="mb-3 flex flex-wrap gap-1">
                    {preview.topFailureReasons.map((r: string) => (
                      <span key={r} className="rounded bg-orange-500/10 px-1.5 py-0.5 text-[10px] text-orange-300 border border-orange-500/20">{r}</span>
                    ))}
                  </div>
                )}
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-slate-800 text-slate-500">
                      <tr>
                        <th className="py-2 pr-3">종목</th>
                        <th className="py-2 pr-3 text-right">진입 전</th>
                        <th className="py-2 pr-3 text-right">진입 후</th>
                        <th className="py-2 pr-3 text-right">Δ%</th>
                        <th className="py-2 pr-3 text-right">목표 Δ%</th>
                        <th className="py-2 pr-3 text-right">손절 Δ%</th>
                        <th className="py-2 pr-3">비고</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.items.map((item: any, idx: number) => (
                        <tr key={idx} className="border-b border-slate-900 hover:bg-slate-900/40">
                          <td className="py-2 pr-3 font-mono text-slate-300">{item.symbol}<br /><span className="text-slate-500">{item.name}</span></td>
                          <td className="py-2 pr-3 text-right text-slate-400">{Number(item.before?.entry || 0).toLocaleString()}</td>
                          <td className={`py-2 pr-3 text-right font-semibold ${item.correctionApplied ? "text-emerald-300" : "text-slate-400"}`}>{Number(item.after?.entry || 0).toLocaleString()}</td>
                          <td className={`py-2 pr-3 text-right ${(item.entryDeltaPct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{(item.entryDeltaPct ?? 0) >= 0 ? "+" : ""}{Number(item.entryDeltaPct ?? 0).toFixed(2)}%</td>
                          <td className={`py-2 pr-3 text-right ${(item.targetDeltaPct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{(item.targetDeltaPct ?? 0) >= 0 ? "+" : ""}{Number(item.targetDeltaPct ?? 0).toFixed(2)}%</td>
                          <td className={`py-2 pr-3 text-right ${(item.stopDeltaPct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>{(item.stopDeltaPct ?? 0) >= 0 ? "+" : ""}{Number(item.stopDeltaPct ?? 0).toFixed(2)}%</td>
                          <td className="py-2 pr-3 text-slate-500 text-[10px] max-w-[120px] truncate">{item.correctionSummary || (item.correctionApplied ? "보정됨" : "미보정")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            {preview?.items?.length === 0 && <div className="text-sm text-slate-500">해당 전략 추천 데이터가 없습니다.</div>}
          </div>

          {/* 롤백 안내 */}
          <div className="rounded-xl border border-slate-700 bg-slate-900/40 px-4 py-3 text-xs text-slate-400 space-y-1">
            <div className="font-semibold text-slate-300 mb-1">롤백 방법</div>
            <div>1. Render 환경변수 <code className="font-mono bg-slate-800 px-1 rounded">SELF_CORRECTION_ENABLED=false</code> 설정 후 재배포 → 즉시 전체 비활성</div>
            <div>2. 백업 버전 복원: <code className="font-mono bg-slate-800 px-1 rounded">reports/self_correction_params_v{"{N}"}.json</code> → <code className="font-mono bg-slate-800 px-1 rounded">self_correction_params.json</code> 으로 복사</div>
            <div>3. <code className="font-mono bg-slate-800 px-1 rounded">CORRECTION_STRENGTH=0.0</code> 설정 → 보정 계산은 하되 실제 반영 없음 (soft disable)</div>
          </div>
        </>
      )}
    </div>
  );
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
  const [correctionDash, setCorrectionDash] = useState<any>(null);
  const [correctionPreview, setCorrectionPreview] = useState<any>(null);
  const [correctionMarket, setCorrectionMarket] = useState<"kr" | "us">("kr");
  const [correctionMode, setCorrectionMode] = useState("balanced");
  const [correctionHorizon, setCorrectionHorizon] = useState("swing");
  const [correctionLoading, setCorrectionLoading] = useState(false);
  const [rebuildLoading, setRebuildLoading] = useState(false);
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
    mone.trendlineAccuracy({ market: "all", futureBars: 5, symbolLimit: 30, maxCutoffs: 12, includeItems: false })
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

  async function loadCorrectionDash(market: string) {
    setCorrectionLoading(true);
    try {
      const res = await fetch(`/mone-api/api/admin/correction-dashboard?market=${market}`, { headers: adminAuthHeaders(authToken) });
      const data = await res.json();
      setCorrectionDash(data);
    } catch (e) {
      setCorrectionDash({ status: "ERROR", error: String(e) });
    } finally {
      setCorrectionLoading(false);
    }
  }

  async function loadCorrectionPreview(market: string, mode: string, horizon: string) {
    try {
      const res = await fetch(`/mone-api/api/admin/correction-preview?market=${market}&mode=${mode}&horizon=${horizon}&limit=8`, { headers: adminAuthHeaders(authToken) });
      const data = await res.json();
      setCorrectionPreview(data);
    } catch (e) {
      setCorrectionPreview({ status: "ERROR", error: String(e) });
    }
  }

  async function rebuildCorrection() {
    setRebuildLoading(true);
    try {
      const res = await fetch("/mone-api/api/validation/self-correction/rebuild", { method: "POST", headers: adminAuthHeaders(authToken) });
      const data = await res.json();
      setMessage(`보정 파라미터 재계산 완료: 버전 ${data.version ?? "-"}, ${data.totalSamples ?? "-"}개 샘플`);
      await loadCorrectionDash(correctionMarket);
    } catch (e) {
      setMessage(`재계산 실패: ${e}`);
    } finally {
      setRebuildLoading(false);
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
      {tab === "correction" && (
        <CorrectionTab
          authToken={authToken}
          market={correctionMarket}
          mode={correctionMode}
          horizon={correctionHorizon}
          dash={correctionDash}
          preview={correctionPreview}
          loading={correctionLoading}
          rebuildLoading={rebuildLoading}
          onMarketChange={(m) => { setCorrectionMarket(m as "kr" | "us"); setCorrectionDash(null); setCorrectionPreview(null); loadCorrectionDash(m); }}
          onModeChange={setCorrectionMode}
          onHorizonChange={setCorrectionHorizon}
          onLoadDash={() => loadCorrectionDash(correctionMarket)}
          onLoadPreview={() => loadCorrectionPreview(correctionMarket, correctionMode, correctionHorizon)}
          onRebuild={rebuildCorrection}
          message={message}
          setMessage={setMessage}
        />
      )}
      {tab !== "overview" && tab !== "correction" && null}
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
            <p className="text-sm text-slate-500">과거 시점에서 그은 지지·저항 빗각을 다음 5봉 실제 고저가와 뉴스 리스크로 검증합니다.</p>
          </div>
          <span className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-400">{trendlineAccuracy.status || "UNKNOWN"}</span>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Metric label="표본" value={trendlineAccuracy.sampleCount ?? "-"} />
          <Metric label="전체 존중률" value={pct(trendlineAccuracy.respectRatePct)} accent />
          <Metric label="VERIFIED_90" value={trendlineAccuracy.verified90Count ?? "-"} accent />
          <Metric label="검증선 존중률" value={pct(trendlineAccuracy.verified90RespectRatePct)} accent />
          <Metric label="뉴스 차단" value={trendlineAccuracy.newsBlockedCount ?? "-"} />
        </div>
        {trendlineAccuracy.verifiedPolicy && <div className="mt-3 text-xs text-amber-200/80">{trendlineAccuracy.verifiedPolicy}</div>}
        {trendlineAccuracy.policy && <div className="mt-2 text-xs text-slate-500">{trendlineAccuracy.policy}</div>}
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
