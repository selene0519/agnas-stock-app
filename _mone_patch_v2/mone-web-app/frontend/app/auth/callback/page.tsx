"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { setAuthenticatedUser } from "@/lib/userId";

function AuthCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [message, setMessage] = useState("로그인 처리 중...");

  useEffect(() => {
    const error = searchParams.get("error");
    if (error) {
      const detail = searchParams.get("detail") || "";
      const msgMap: Record<string, string> = {
        oauth_state:    "인증 상태(state) 검증 실패 — Kakao에서 오류가 반환됐거나 세션이 만료됐습니다.",
        oauth_failed:   "토큰 교환 또는 사용자 정보 조회 실패",
        oauth_callback: "백엔드 URL 미설정 (MONE_BACKEND_URL 확인 필요)",
      };
      const base = msgMap[error] ?? `로그인 오류 (${error})`;
      setMessage(detail ? `${base}\n세부: ${decodeURIComponent(detail)}` : base);
      return;
    }

    const token = searchParams.get("token") || "";
    const userId = searchParams.get("userId") || "";
    if (!token || !userId) {
      setMessage("로그인 응답이 올바르지 않습니다.");
      return;
    }

    setAuthenticatedUser(
      {
        userId,
        provider: searchParams.get("provider") || "",
        email: searchParams.get("email") || "",
        name: searchParams.get("name") || "",
        expiresAt: Number(searchParams.get("expiresAt") || 0),
      },
      token,
    );
    setMessage("로그인 완료. 홈으로 이동합니다.");
    window.setTimeout(() => router.replace("/"), 600);
  }, [router, searchParams]);

  const isError = message.includes("실패") || message.includes("오류") || message.includes("검증") || message.includes("미설정");

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6 text-slate-100">
      <div className={`rounded-2xl border px-5 py-4 text-sm shadow-2xl ${isError ? "border-red-500/40 bg-red-950/40" : "border-slate-800 bg-slate-900/80"}`}>
        <pre className="whitespace-pre-wrap font-sans">{message}</pre>
        {isError && (
          <button
            type="button"
            onClick={() => window.history.back()}
            className="mt-3 rounded-lg border border-slate-700 bg-slate-800 px-4 py-1.5 text-xs text-slate-300 hover:bg-slate-700"
          >
            돌아가기
          </button>
        )}
      </div>
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6 text-slate-100">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/80 px-5 py-4 text-sm shadow-2xl">
            로그인 처리 중...
          </div>
        </div>
      }
    >
      <AuthCallbackInner />
    </Suspense>
  );
}
