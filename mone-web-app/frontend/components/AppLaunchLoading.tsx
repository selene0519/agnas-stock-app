"use client";

type LoadingStatus = "done" | "active" | "pending";

export type AppLaunchLoadingStep = {
  label: string;
  status: LoadingStatus;
};

type AppLaunchLoadingProps = {
  progress: number;
  message: string;
  steps?: AppLaunchLoadingStep[];
  delayed?: boolean;
};

const DEFAULT_STEPS: AppLaunchLoadingStep[] = [
  { label: "서버 연결 확인", status: "done" },
  { label: "최신 데이터 동기화", status: "done" },
  { label: "추천 후보 계산", status: "active" },
];

export default function AppLaunchLoading({
  progress,
  message,
  delayed = false,
  steps = DEFAULT_STEPS,
}: AppLaunchLoadingProps) {
  const safeProgress = Math.min(100, Math.max(0, Math.round(progress)));

  return (
    <div className="fixed inset-0 z-[9999] overflow-hidden bg-[#02070b] text-white">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_18%,rgba(63,224,214,0.18),transparent_34%),linear-gradient(180deg,#061118_0%,#02070b_62%,#010306_100%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-[33%] h-44 opacity-20">
        <svg viewBox="0 0 430 150" className="h-full w-full" aria-hidden="true">
          <path
            d="M0 112 C45 94, 72 119, 118 82 C158 50, 195 82, 232 43 C270 4, 312 33, 345 14 C382 -6, 402 8, 430 0"
            fill="none"
            stroke="rgba(63,224,214,0.48)"
            strokeWidth="2"
          />
          <path
            d="M0 138 C55 120, 92 132, 135 108 C185 78, 226 92, 274 61 C322 30, 360 42, 430 18"
            fill="none"
            stroke="rgba(63,224,214,0.14)"
            strokeWidth="2"
          />
        </svg>
      </div>

      <div className="relative mx-auto flex h-full max-w-md flex-col items-center px-6 pt-[9vh]">
        <img
          src="/loading/mone-logo.png"
          alt="MONE"
          className="w-64 max-w-[78vw] object-contain drop-shadow-[0_0_28px_rgba(63,224,214,0.28)]"
        />

        <div className="mt-[9vh] w-full">
          <div className="relative z-10 flex justify-center">
            <img
              src="/loading/mone-bear.png"
              alt="MONE bear"
              className="mb-[-22px] w-28 max-w-[34vw] object-contain drop-shadow-[0_12px_30px_rgba(0,0,0,0.5)]"
            />
          </div>

          <div className="rounded-[28px] border border-cyan-300/25 bg-white/[0.055] px-7 pb-8 pt-12 shadow-[0_0_42px_rgba(0,255,230,0.1)] backdrop-blur-xl">
            <div className="text-center">
              <h1 className="text-[28px] font-bold tracking-tight text-white sm:text-3xl">
                MONE 준비 중... <span className="text-[#42dfd4]">{safeProgress}%</span>
              </h1>
              <p className="mt-3 text-[15px] text-white/68">{message}</p>
            </div>

            <div className="mt-8 h-3 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-[#42dfd4] shadow-[0_0_18px_rgba(66,223,212,0.65)] transition-all duration-500 ease-out"
                style={{ width: `${safeProgress}%` }}
              />
            </div>

            <div className="mt-7 space-y-4">
              {steps.map((step) => (
                <div key={step.label} className="flex items-center gap-3">
                  <div
                    className={[
                      "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border",
                      step.status === "done"
                        ? "border-[#42dfd4] bg-[#42dfd4] text-[#021014]"
                        : step.status === "active"
                          ? "border-[#42dfd4] text-[#42dfd4]"
                          : "border-white/18 text-white/25",
                    ].join(" ")}
                  >
                    {step.status === "done" ? (
                      <span className="text-sm font-bold">✓</span>
                    ) : step.status === "active" ? (
                      <span className="h-2 w-2 rounded-full bg-[#42dfd4]" />
                    ) : (
                      <span className="h-2 w-2 rounded-full bg-white/20" />
                    )}
                  </div>
                  <span className={step.status === "pending" ? "text-sm text-white/35" : "text-sm text-white/78"}>
                    {step.label}
                  </span>
                </div>
              ))}
            </div>

            <p className="mt-7 text-center text-sm text-white/42">
              {delayed
                ? "데이터 확인이 지연되고 있어요. 서버가 깨어나는 중일 수 있어요."
                : "잠시만 기다려 주세요"}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
