"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Clock3, Link2, RefreshCw, ShieldCheck, Unplug } from "lucide-react";
import mone from "@/lib/api";

interface BrokerStatus {
  broker: string;
  connected: boolean;
  status: string;
  connectionMode?: string;
  lastSync?: number | null;
  connectedAt?: number | null;
  accountNoHint?: string;
  itemCount?: number;
  legacyCredential?: boolean;
}

interface BrokerPageProps {
  userToken?: string | null;
  onLogin?: () => void;
  onNavigate?: (page: string) => void;
}

const BROKERS = [
  { id: "toss", name: "토스증권", tone: "sky" },
  { id: "kis", name: "한국투자", tone: "amber" },
] as const;

function fmtTime(ts?: number | null) {
  if (!ts) return "없음";
  return new Date(ts * 1000).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusLabel(status?: string, connected?: boolean) {
  if (connected) return "연결됨";
  if (status === "LOCAL_BRIDGE_REQUIRED") return "브릿지 필요";
  if (status === "LOAD_ERROR") return "상태 오류";
  return "미연결";
}

function statusTone(status?: string, connected?: boolean) {
  if (connected) return "text-emerald-300";
  if (status === "LOCAL_BRIDGE_REQUIRED") return "text-amber-300";
  if (status === "LOAD_ERROR") return "text-red-300";
  return "text-slate-500";
}

function BridgeCard({
  token,
  status,
  broker,
  onRefresh,
}: {
  token: string;
  status: BrokerStatus;
  broker: (typeof BROKERS)[number];
  onRefresh: () => void;
}) {
  const [loading, setLoading] = useState<"check" | "disconnect" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const connected = Boolean(status.connected);

  async function checkSnapshot() {
    setLoading("check");
    setMessage(null);
    try {
      const res = await mone.brokerSyncHoldings(token, { broker: broker.id });
      if (res?.ok) {
        setMessage({ ok: true, text: res.message || "최근 로컬 브릿지 스냅샷이 반영되어 있습니다." });
      } else {
        setMessage({ ok: false, text: res?.message || res?.error || "아직 업로드된 브릿지 스냅샷이 없습니다." });
      }
      onRefresh();
    } catch {
      setMessage({ ok: false, text: "브릿지 상태 확인에 실패했습니다. 잠시 후 다시 시도해주세요." });
    } finally {
      setLoading(null);
    }
  }

  async function disconnect() {
    if (!confirm(`${broker.name} 로컬 브릿지 연결 상태를 해제할까요? 저장된 App Secret은 서버에 없으며, 상태 기록만 삭제됩니다.`)) return;
    setLoading("disconnect");
    setMessage(null);
    try {
      const res = await mone.brokerDisconnect(token, { broker: broker.id });
      setMessage({ ok: Boolean(res?.ok), text: res?.message || (res?.ok ? "연결 상태를 해제했습니다." : "해제에 실패했습니다.") });
      onRefresh();
    } catch {
      setMessage({ ok: false, text: "연결 해제에 실패했습니다." });
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-100">{broker.name}</div>
          <div className={`mt-1 text-xs font-semibold ${statusTone(status.status, connected)}`}>
            {statusLabel(status.status, connected)}
            {status.accountNoHint ? ` · ${status.accountNoHint}` : ""}
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            마지막 업로드 {fmtTime(status.lastSync)}
            {connected && status.itemCount != null ? ` · ${status.itemCount}종목` : ""}
          </div>
        </div>
        {connected ? (
          <CheckCircle2 className="mt-0.5 text-emerald-400" size={18} />
        ) : (
          <Clock3 className="mt-0.5 text-slate-500" size={18} />
        )}
      </div>

      {status.legacyCredential && (
        <div className="mt-3 rounded-xl border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs leading-5 text-amber-100">
          이전 방식의 서버 저장 인증정보가 감지됐습니다. 이제 서버에서는 사용하지 않으며, 연결 해제를 누르면 상태 기록과 함께 삭제됩니다.
        </div>
      )}

      <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
        <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Local Bridge</div>
        <ol className="mt-2 space-y-1.5 text-xs leading-5 text-slate-400">
          <li>1. 내 PC 작업스케줄러가 {broker.name} API를 호출합니다.</li>
          <li>2. App Key/App Secret은 PC 환경변수나 로컬 설정에만 둡니다.</li>
          <li>3. 앱에는 종목, 수량, 평균단가, 평가손익 스냅샷만 업로드합니다.</li>
        </ol>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={checkSnapshot}
          disabled={loading === "check"}
          className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-xl border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading === "check" ? "animate-spin" : ""} />
          상태 확인
        </button>
        <button
          type="button"
          onClick={connected || status.legacyCredential ? disconnect : onRefresh}
          disabled={loading === "disconnect"}
          className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-xl border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-50"
        >
          <Unplug size={14} />
          {connected || status.legacyCredential ? "연결 해제" : "새로고침"}
        </button>
      </div>

      {message && (
        <div className={`mt-3 rounded-xl px-3 py-2 text-xs ${message.ok ? "bg-emerald-950/50 text-emerald-300" : "bg-red-950/50 text-red-300"}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}

export default function BrokerPage({ userToken, onLogin, onNavigate }: BrokerPageProps) {
  const [connections, setConnections] = useState<BrokerStatus[]>([]);
  const [loading, setLoading] = useState(false);

  async function fetchConnections() {
    if (!userToken) return;
    setLoading(true);
    try {
      const res = await mone.brokerConnections(userToken);
      setConnections(Array.isArray(res) ? res : res?.connections || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (userToken) fetchConnections();
  }, [userToken]);

  const byBroker = useMemo(() => {
    const map = new Map(connections.map((item) => [item.broker, item]));
    return (broker: string): BrokerStatus =>
      map.get(broker) || { broker, connected: false, status: "NOT_CONNECTED", connectionMode: "local_bridge" };
  }, [connections]);

  if (!userToken) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 px-4 text-center">
        <div className="space-y-2">
          <div className="text-base font-semibold text-slate-200">계좌 연동</div>
          <div className="text-sm leading-relaxed text-slate-500">
            로그인 후 계좌 연동을 사용할 수 있습니다.
            <br />
            계좌를 연동하면 MONE이 보유종목, 평가손익, 손절 기준, 위험 상태를 자동으로 점검합니다.
          </div>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {onLogin && (
            <button
              type="button"
              onClick={onLogin}
              className="rounded-xl bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white active:bg-blue-700"
            >
              로그인하기
            </button>
          )}
          <button
            type="button"
            onClick={() => onNavigate?.("holdings")}
            className="rounded-xl border border-slate-700 bg-slate-900 px-6 py-2.5 text-sm font-semibold text-slate-200 active:bg-slate-800"
          >
            직접 추가로 체험하기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-24">
      <div>
        <div className="text-base font-bold text-slate-100">계좌 연동</div>
        <div className="mt-1 text-xs leading-relaxed text-slate-500">
          증권사 API는 내 PC의 로컬 브릿지에서만 호출합니다. Render 서버에는 App Key/App Secret을 저장하지 않고,
          보유종목 스냅샷만 HTTPS로 업로드합니다.
        </div>
      </div>

      <div className="rounded-2xl border border-emerald-500/25 bg-emerald-500/10 p-4">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 shrink-0 text-emerald-300" size={18} />
          <div>
            <div className="text-sm font-semibold text-emerald-100">보안 구조</div>
            <div className="mt-1 text-xs leading-5 text-emerald-100/80">
              Secret은 브라우저, localStorage, sessionStorage, URL, Render 환경에 두지 않습니다.
              작업스케줄러가 로컬에서 조회한 결과만 앱에 반영합니다.
            </div>
          </div>
        </div>
      </div>

      {loading && <div className="py-2 text-center text-xs text-slate-600">연동 상태 조회 중...</div>}

      <div className="space-y-3">
        {BROKERS.map((broker) => (
          <BridgeCard
            key={broker.id}
            token={userToken}
            broker={broker}
            status={byBroker(broker.id)}
            onRefresh={fetchConnections}
          />
        ))}
      </div>

      <div className="rounded-2xl border border-slate-800/60 bg-slate-900/30 p-4">
        <div className="flex items-start gap-3">
          <Link2 className="mt-0.5 shrink-0 text-slate-500" size={16} />
          <div>
            <div className="text-xs font-semibold text-slate-300">작업스케줄러 연결 방식</div>
            <div className="mt-1 text-[11px] leading-5 text-slate-500">
              로컬 브릿지 스크립트가 실행되면 `/api/broker/local-bridge/upload`로 보유종목을 업로드합니다.
              업로드 후 보유·리스크 화면에서 토스증권/한국투자 출처와 마지막 동기화 시간이 표시됩니다.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
