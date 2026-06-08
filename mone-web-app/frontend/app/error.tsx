"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[GlobalError]", error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-slate-950 text-slate-100">
      <div className="text-center">
        <p className="text-5xl font-bold text-red-800">!</p>
        <h1 className="mt-3 text-xl font-semibold">예기치 못한 오류가 발생했습니다</h1>
        <p className="mt-2 max-w-sm text-sm text-slate-400">{error?.message || "알 수 없는 오류"}</p>
        {error?.digest && (
          <p className="mt-1 font-mono text-xs text-slate-600">Ref: {error.digest}</p>
        )}
      </div>
      <div className="flex gap-3">
        <button
          onClick={reset}
          className="rounded-xl bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-500"
        >
          다시 시도
        </button>
        <a
          href="/"
          className="rounded-xl border border-slate-700 bg-slate-800 px-5 py-2 text-sm font-medium text-slate-300 hover:bg-slate-700"
        >
          홈으로
        </a>
      </div>
    </div>
  );
}
