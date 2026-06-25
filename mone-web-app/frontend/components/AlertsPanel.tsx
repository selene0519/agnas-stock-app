"use client";

import { useEffect, useState } from "react";
import { mone } from "@/lib/api";
import { Bell, BellOff, RefreshCw, Send, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { toneClassName } from "@/lib/tone";

type AlertStatus = {
  enabled: boolean;
  botTokenSet: boolean;
  chatIdSet: boolean;
  thresholdPct: number;
  intervalMin: number;
  cooldownHours: number;
  lastCheck?: {
    checkedAt?: string;
    total?: number;
    sent?: number;
    skipped?: number;
    items?: Array<{
      type: "STOP" | "TARGET";
      symbol: string;
      name: string;
      market: string;
      currentPrice: number;
      stopPrice?: number;
      targetPrice?: number;
      gapPct: number;
    }>;
  };
};

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-emerald-400" : "bg-red-400"}`} />
  );
}

export default function AlertsPanel() {
  const [status, setStatus] = useState<AlertStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [checkResult, setCheckResult] = useState<{ sent: number; total: number } | null>(null);

  async function fetchStatus() {
    setLoading(true);
    try {
      const res = await mone.alertsStatus();
      setStatus(res as AlertStatus);
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const res: any = await mone.alertsTest();
      setTestResult({
        ok: res?.ok === true,
        msg: res?.ok ? "메시지 발송 성공" : (res?.error || "발송 실패"),
      });
    } catch {
      setTestResult({ ok: false, msg: "네트워크 오류" });
    } finally {
      setTesting(false);
    }
  }

  async function handleCheck(force = false) {
    setChecking(true);
    setCheckResult(null);
    try {
      const res: any = await mone.alertsCheck({ force });
      setCheckResult({ sent: res?.sent ?? 0, total: res?.total ?? 0 });
      await fetchStatus();
    } catch {
      setCheckResult(null);
    } finally {
      setChecking(false);
    }
  }

  useEffect(() => {
    fetchStatus();
  }, []);

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell size={16} className="text-violet-400" />
          <h2 className="text-sm font-bold text-slate-200">Telegram 알림</h2>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loading}
          className="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 disabled:opacity-50"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          새로고침
        </button>
      </div>

      {/* 설정 상태 카드 */}
      <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-4 space-y-3">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">연결 상태</p>

        {status ? (
          <>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="flex items-center gap-2">
                <StatusDot ok={status.botTokenSet} />
                <span className="text-slate-400">Bot Token</span>
                <span className={`ml-auto font-mono text-[11px] ${status.botTokenSet ? "text-emerald-400" : "text-red-400"}`}>
                  {status.botTokenSet ? "설정됨" : "미설정"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <StatusDot ok={status.chatIdSet} />
                <span className="text-slate-400">Chat ID</span>
                <span className={`ml-auto font-mono text-[11px] ${status.chatIdSet ? "text-emerald-400" : "text-red-400"}`}>
                  {status.chatIdSet ? "설정됨" : "미설정"}
                </span>
              </div>
            </div>

            {status.enabled ? (
              <div className={`flex items-center gap-2 rounded-xl px-3 py-2 ${toneClassName("safe")}`}>
                <Bell size={13} />
                <span className="text-xs font-semibold">알림 활성화됨</span>
                <span className="ml-auto text-[11px] text-slate-500">
                  {status.thresholdPct}% 이내 / {status.intervalMin}분 주기
                </span>
              </div>
            ) : (
              <div className={`rounded-xl px-3 py-2 space-y-1 ${toneClassName("warning")}`}>
                <div className="flex items-center gap-2">
                  <BellOff size={13} />
                  <span className="text-xs font-semibold">알림 비활성화</span>
                </div>
                <p className="text-[11px] text-slate-400">
                  Render 환경변수에 아래 항목을 추가하세요:
                </p>
                <div className="rounded-lg bg-slate-900 px-3 py-2 font-mono text-[10px] text-slate-300 space-y-0.5">
                  <div>TELEGRAM_BOT_TOKEN=<span className="text-amber-400">your-bot-token</span></div>
                  <div>TELEGRAM_CHAT_ID=<span className="text-amber-400">your-chat-id</span></div>
                </div>
                <p className="text-[10px] text-slate-500">
                  봇 토큰: @BotFather에서 발급 · Chat ID: @userinfobot에서 확인
                </p>
              </div>
            )}

            {/* 설정값 요약 */}
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: "임계값", value: `${status.thresholdPct}%` },
                { label: "체크 주기", value: `${status.intervalMin}분` },
                { label: "쿨다운", value: `${status.cooldownHours}시간` },
              ].map(({ label, value }) => (
                <div key={label} className="rounded-xl border border-slate-700/40 bg-slate-800/30 px-2 py-1.5 text-center">
                  <div className="text-[10px] text-slate-500">{label}</div>
                  <div className="mt-0.5 text-xs font-bold text-slate-200">{value}</div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="text-center text-xs text-slate-500 py-4">
            {loading ? "불러오는 중..." : "상태 조회 실패"}
          </div>
        )}
      </div>

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        <button
          onClick={handleTest}
          disabled={testing || !status?.enabled}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-slate-700 bg-slate-800/50 py-2.5 text-xs font-semibold text-slate-300 hover:bg-slate-700 disabled:opacity-40"
        >
          <Send size={12} />
          {testing ? "발송 중..." : "테스트 메시지"}
        </button>
        <button
          onClick={() => handleCheck(false)}
          disabled={checking || !status?.enabled}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-violet-500/30 bg-violet-950/20 py-2.5 text-xs font-semibold text-violet-300 hover:bg-violet-900/30 disabled:opacity-40"
        >
          <Bell size={12} />
          {checking ? "체크 중..." : "즉시 알림 체크"}
        </button>
      </div>

      {/* 테스트 결과 */}
      {testResult && (
        <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs ${toneClassName(testResult.ok ? "safe" : "danger")}`}>
          {testResult.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
          {testResult.msg}
        </div>
      )}

      {checkResult !== null && (
        <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs ${toneClassName(checkResult.sent > 0 ? "info" : "neutral")}`}>
          <Bell size={13} />
          {checkResult.total === 0
            ? "근접 알림 없음"
            : `총 ${checkResult.total}건 중 ${checkResult.sent}건 발송`}
        </div>
      )}

      {/* 마지막 체크 내역 */}
      {status?.lastCheck?.items && status.lastCheck.items.length > 0 && (
        <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 p-4 space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            마지막 체크 근접 알림
            {status.lastCheck.checkedAt && (
              <span className="ml-2 normal-case font-normal text-slate-600">
                {status.lastCheck.checkedAt}
              </span>
            )}
          </p>
          {status.lastCheck.items.map((item, i) => (
            <div
              key={i}
              className={`flex items-center justify-between rounded-xl px-3 py-2 ${toneClassName(item.type === "STOP" ? "danger" : "safe")}`}
            >
              <div className="flex items-center gap-2">
                {item.type === "STOP" ? (
                  <AlertTriangle size={12} />
                ) : (
                  <CheckCircle2 size={12} />
                )}
                <div>
                  <span className="text-xs font-semibold text-slate-200">{item.name}</span>
                  <span className="ml-1.5 text-[10px] text-slate-500">{item.symbol}</span>
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs font-bold">
                  {item.gapPct}%
                </div>
                <div className="text-[10px] text-slate-500">
                  {item.type === "STOP" ? "손절까지" : "목표까지"}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
