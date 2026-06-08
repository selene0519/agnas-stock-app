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
      setMessage("로그인에 실패했습니다. 환경변수와 OAuth redirect URI를 확인해주세요.");
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

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-6 text-slate-100">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/80 px-5 py-4 text-sm shadow-2xl">
        {message}
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
