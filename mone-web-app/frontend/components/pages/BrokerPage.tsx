"use client";

import { useEffect, useState } from "react";
import mone from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

interface BrokerStatus {
  broker: string;
  connected: boolean;
  status: string;
  lastSync?: number | null;
  connectedAt?: number | null;
  accountNoHint?: string;
}

interface BrokerPageProps {
  userToken?: string | null;
  onLogin?: () => void;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtTime(ts?: number | null) {
  if (!ts) return "없음";
  return new Date(ts * 1000).toLocaleString("ko-KR", {
    month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

const STATUS_LABEL: Record<string, string> = {
  NOT_CONNECTED: "미연결",
  IDLE: "연결됨",
  OK: "동기화 완료",
  SYNCING: "동기화 중",
  ERROR: "동기화 실패",
  LOAD_ERROR: "오류",
};
const STATUS_COLOR: Record<string, string> = {
  NOT_CONNECTED: "text-slate-500",
  IDLE: "text-emerald-400",
  OK: "text-emerald-400",
  SYNCING: "text-yellow-400",
  ERROR: "text-red-400",
  LOAD_ERROR: "text-red-400",
};

// ── Sub-components ─────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-3 text-[11px] font-bold uppercase tracking-widest text-slate-500">
      {children}
    </div>
  );
}

function StatusChip({ status }: { status: string }) {
  return (
    <span className={`text-xs font-semibold ${STATUS_COLOR[status] ?? "text-slate-400"}`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

// ── TossConnectForm ────────────────────────────────────────────────────────

function TossConnectForm({
  token,
  status,
  onRefresh,
}: {
  token: string;
  status: BrokerStatus;
  onRefresh: () => void;
}) {
  const [appKey, setAppKey] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncLoading, setSyncLoading] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const handleConnect = async () => {
    if (!appKey.trim() || !appSecret.trim() || !accountNo.trim()) {
      setMsg({ ok: false, text: "App Key, App Secret, 계좌번호를 모두 입력해 주세요." });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const res = await mone.brokerConnect(token, {
        broker: "toss",
        appKey: appKey.trim(),
        appSecret: appSecret.trim(),
        accountNo: accountNo.trim(),
      });
      if (res.ok) {
        setMsg({ ok: true, text: res.message ?? "토스증권 연동이 완료되었습니다." });
        setAppKey("");
        setAppSecret("");
        setAccountNo("");
        onRefresh();
      } else {
        setMsg({ ok: false, text: res.error ?? res.message ?? "연동 실패" });
      }
    } catch {
      setMsg({ ok: false, text: "서버 오류가 발생했습니다." });
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncLoading(true);
    setMsg(null);
    try {
      const res = await mone.brokerSyncHoldings(token, { broker: "toss" });
      if (res.ok) {
        setMsg({ ok: true, text: `동기화 완료 — ${res.count ?? 0}개 종목` });
        onRefresh();
      } else {
        setMsg({ ok: false, text: res.error ?? "동기화 실패" });
      }
    } catch {
      setMsg({ ok: false, text: "서버 오류가 발생했습니다." });
    } finally {
      setSyncLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("토스증권 연동을 해제하면 저장된 API 키가 완전히 삭제됩니다. 계속하시겠습니까?")) return;
    setLoading(true);
    setMsg(null);
    try {
      const res = await mone.brokerDisconnect(token, { broker: "toss" });
      if (res.ok) {
        setMsg({ ok: true, text: "연동이 해제되었습니다." });
        onRefresh();
      } else {
        setMsg({ ok: false, text: res.error ?? "해제 실패" });
      }
    } catch {
      setMsg({ ok: false, text: "서버 오류가 발생했습니다." });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-200">토스증권</div>
          {status.connected && status.accountNoHint && (
            <div className="text-[11px] text-slate-500 mt-0.5">
              계좌 {status.accountNoHint} · 마지막 동기화 {fmtTime(status.lastSync)}
            </div>
          )}
        </div>
        <StatusChip status={status.status} />
      </div>

      {!status.connected ? (
        <div className="space-y-3">
          <div className="rounded-lg bg-slate-800/60 px-3 py-2 text-[11px] text-slate-400 leading-relaxed">
            토스증권 Open API에서 발급받은 App Key / App Secret을 입력하세요.
            입력한 Secret은 서버에 암호화 저장되며 이후 화면에 다시 표시되지 않습니다.
          </div>
          <div className="space-y-2">
            <input
              type="text"
              placeholder="App Key"
              value={appKey}
              onChange={(e) => setAppKey(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
              autoComplete="off"
            />
            <input
              type="password"
              placeholder="App Secret"
              value={appSecret}
              onChange={(e) => setAppSecret(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
              autoComplete="new-password"
            />
            <input
              type="text"
              placeholder="계좌번호 (예: 12345678901)"
              value={accountNo}
              onChange={(e) => setAccountNo(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
              autoComplete="off"
            />
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={handleConnect}
            className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-semibold text-white disabled:opacity-50 active:bg-blue-700"
          >
            {loading ? "연결 테스트 중…" : "연결 테스트 후 저장"}
          </button>
        </div>
      ) : (
        <div className="flex gap-2">
          <button
            type="button"
            disabled={syncLoading}
            onClick={handleSync}
            className="flex-1 rounded-xl border border-slate-700 py-2 text-sm font-semibold text-slate-200 disabled:opacity-50 active:bg-slate-800"
          >
            {syncLoading ? "동기화 중…" : "보유종목 동기화"}
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={handleDisconnect}
            className="rounded-xl border border-red-900 px-4 py-2 text-sm font-semibold text-red-400 disabled:opacity-50 active:bg-red-900/20"
          >
            연동 해제
          </button>
        </div>
      )}

      {msg && (
        <div className={`rounded-lg px-3 py-2 text-xs ${msg.ok ? "bg-emerald-950/50 text-emerald-400" : "bg-red-950/50 text-red-400"}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}

// ── KisConnectForm ─────────────────────────────────────────────────────────

function KisConnectForm({
  token,
  status,
  onRefresh,
}: {
  token: string;
  status: BrokerStatus;
  onRefresh: () => void;
}) {
  const [appKey, setAppKey] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const handleConnect = async () => {
    if (!appKey.trim() || !appSecret.trim() || !accountNo.trim()) {
      setMsg({ ok: false, text: "App Key, App Secret, 계좌번호를 모두 입력해 주세요." });
      return;
    }
    setLoading(true);
    setMsg(null);
    try {
      const res = await mone.brokerConnect(token, {
        broker: "kis",
        appKey: appKey.trim(),
        appSecret: appSecret.trim(),
        accountNo: accountNo.trim(),
      });
      if (res.ok) {
        setMsg({ ok: true, text: res.message ?? "KIS 연동이 완료되었습니다." });
        setAppKey("");
        setAppSecret("");
        setAccountNo("");
        onRefresh();
      } else {
        setMsg({ ok: false, text: res.error ?? res.message ?? "연동 실패" });
      }
    } catch {
      setMsg({ ok: false, text: "서버 오류가 발생했습니다." });
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("KIS 연동을 해제하면 저장된 API 키가 완전히 삭제됩니다. 계속하시겠습니까?")) return;
    setLoading(true);
    setMsg(null);
    try {
      const res = await mone.brokerDisconnect(token, { broker: "kis" });
      if (res.ok) {
        setMsg({ ok: true, text: "연동이 해제되었습니다." });
        onRefresh();
      } else {
        setMsg({ ok: false, text: res.error ?? "해제 실패" });
      }
    } catch {
      setMsg({ ok: false, text: "서버 오류가 발생했습니다." });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-200">한국투자증권 (KIS)</div>
          {status.connected && status.accountNoHint && (
            <div className="text-[11px] text-slate-500 mt-0.5">
              계좌 {status.accountNoHint} · 연결 {fmtTime(status.connectedAt)}
            </div>
          )}
        </div>
        <StatusChip status={status.status} />
      </div>

      {!status.connected ? (
        <div className="space-y-3">
          <div className="rounded-lg bg-slate-800/60 px-3 py-2 text-[11px] text-slate-400 leading-relaxed">
            한국투자증권 Open API에서 발급받은 App Key / App Secret을 입력하세요.
            보유종목 조회는 추후 지원 예정입니다.
          </div>
          <div className="space-y-2">
            <input
              type="text"
              placeholder="App Key"
              value={appKey}
              onChange={(e) => setAppKey(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
              autoComplete="off"
            />
            <input
              type="password"
              placeholder="App Secret"
              value={appSecret}
              onChange={(e) => setAppSecret(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
              autoComplete="new-password"
            />
            <input
              type="text"
              placeholder="계좌번호"
              value={accountNo}
              onChange={(e) => setAccountNo(e.target.value)}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-slate-500"
              autoComplete="off"
            />
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={handleConnect}
            className="w-full rounded-xl bg-blue-600 py-2.5 text-sm font-semibold text-white disabled:opacity-50 active:bg-blue-700"
          >
            {loading ? "연결 테스트 중…" : "연결 테스트 후 저장"}
          </button>
        </div>
      ) : (
        <div className="flex gap-2">
          <div className="flex-1 rounded-xl border border-slate-700/50 px-3 py-2 text-xs text-slate-500 flex items-center">
            주문·자동매매는 지원하지 않습니다
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={handleDisconnect}
            className="rounded-xl border border-red-900 px-4 py-2 text-sm font-semibold text-red-400 disabled:opacity-50 active:bg-red-900/20"
          >
            연동 해제
          </button>
        </div>
      )}

      {msg && (
        <div className={`rounded-lg px-3 py-2 text-xs ${msg.ok ? "bg-emerald-950/50 text-emerald-400" : "bg-red-950/50 text-red-400"}`}>
          {msg.text}
        </div>
      )}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function BrokerPage({ userToken, onLogin }: BrokerPageProps) {
  const [connections, setConnections] = useState<BrokerStatus[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchConnections = async () => {
    if (!userToken) return;
    setLoading(true);
    try {
      const res = await mone.brokerConnections(userToken);
      if (Array.isArray(res)) setConnections(res);
      else if (res?.connections) setConnections(res.connections);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (userToken) fetchConnections();
  }, [userToken]);

  const getStatus = (broker: string): BrokerStatus =>
    connections.find((c) => c.broker === broker) ?? {
      broker,
      connected: false,
      status: "NOT_CONNECTED",
    };

  // ── 비로그인 ─────────────────────────────────────────────────────────────
  if (!userToken) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 px-6 text-center">
        <div className="space-y-2">
          <div className="text-base font-semibold text-slate-200">계좌 연동</div>
          <div className="text-sm text-slate-500 leading-relaxed">
            로그인 후 계좌 연동을 사용할 수 있습니다.
          </div>
        </div>
        {onLogin && (
          <button
            type="button"
            onClick={onLogin}
            className="rounded-xl bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white active:bg-blue-700"
          >
            로그인하기
          </button>
        )}
        <div className="mt-2 rounded-2xl border border-slate-800 bg-slate-900/40 p-4 text-left w-full max-w-sm">
          <div className="text-xs font-semibold text-slate-400 mb-2">계좌 연동으로 할 수 있는 것</div>
          <ul className="space-y-1.5 text-xs text-slate-500">
            <li className="flex items-start gap-2"><span className="text-emerald-500 mt-0.5">✓</span>토스증권 보유종목 자동 불러오기</li>
            <li className="flex items-start gap-2"><span className="text-emerald-500 mt-0.5">✓</span>MONE 추천과 내 보유종목 비교 분석</li>
            <li className="flex items-start gap-2"><span className="text-slate-600 mt-0.5">–</span><span className="text-slate-600">주문·자동매매는 지원하지 않습니다</span></li>
          </ul>
        </div>
      </div>
    );
  }

  // ── 로그인 상태 ───────────────────────────────────────────────────────────
  return (
    <div className="space-y-6 px-4 py-6 pb-24">
      <div>
        <div className="text-base font-bold text-slate-100">계좌 연동</div>
        <div className="mt-1 text-xs text-slate-500">
          API 키는 서버에 암호화 저장됩니다. 저장 후 Secret은 다시 확인할 수 없습니다.
          주문·자동매매 기능은 제공하지 않습니다.
        </div>
      </div>

      {loading && (
        <div className="text-xs text-slate-600 text-center py-4">연동 상태 조회 중…</div>
      )}

      <div className="space-y-3">
        <SectionTitle>증권사 연동</SectionTitle>
        <TossConnectForm
          token={userToken}
          status={getStatus("toss")}
          onRefresh={fetchConnections}
        />
        <KisConnectForm
          token={userToken}
          status={getStatus("kis")}
          onRefresh={fetchConnections}
        />
      </div>

      <div className="rounded-2xl border border-slate-800/60 bg-slate-900/30 p-4 space-y-2">
        <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-widest">보안 안내</div>
        <ul className="space-y-1 text-[11px] text-slate-500 leading-relaxed">
          <li>• App Key/Secret은 HTTPS를 통해 전송되며, 서버에서 사용자 ID 기반 암호화 후 저장됩니다.</li>
          <li>• 브라우저(localStorage/sessionStorage)에는 일체 저장되지 않습니다.</li>
          <li>• 연동 해제 시 저장된 키가 즉시 삭제됩니다.</li>
          <li>• 현재 1차 지원 범위: 보유종목 조회 전용. 주문·자동매매 없음.</li>
        </ul>
      </div>
    </div>
  );
}
