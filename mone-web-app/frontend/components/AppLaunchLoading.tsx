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

export default function AppLaunchLoading({
  progress,
  message,
  delayed = false,
}: AppLaunchLoadingProps) {
  const safeProgress = Math.min(100, Math.max(0, Math.round(progress)));

  return (
    <div className="fixed inset-0 z-[9999] overflow-hidden bg-[#020811] text-white">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_31%,rgba(29,207,198,0.16),transparent_28%),radial-gradient(circle_at_50%_71%,rgba(66,223,212,0.11),transparent_28%),linear-gradient(180deg,#030815_0%,#06101a_44%,#02060d_100%)]" />
      <div className="pointer-events-none absolute inset-x-0 top-[37%] h-[28vh] opacity-30">
        <svg viewBox="0 0 945 360" className="h-full w-full" aria-hidden="true" preserveAspectRatio="none">
          <path
            d="M0 86 C100 136 114 224 236 248 C347 270 405 201 510 195 C642 187 695 160 756 83 C813 14 851 42 945 0"
            fill="none"
            stroke="rgba(22,181,190,0.24)"
            strokeWidth="3"
          />
          <path
            d="M0 209 C112 235 155 312 281 315 C405 318 446 262 562 251 C681 240 758 167 823 129 C873 101 905 112 945 70"
            fill="none"
            stroke="rgba(22,181,190,0.13)"
            strokeWidth="3"
          />
          <g fill="rgba(22,181,190,0.22)">
            <circle cx="760" cy="86" r="9" />
            <circle cx="823" cy="129" r="9" />
            <circle cx="846" cy="42" r="9" />
            <circle cx="865" cy="49" r="9" />
          </g>
        </svg>
      </div>

      <div className="relative mx-auto flex h-full w-full max-w-[945px] flex-col items-center px-6 pt-[18vh] sm:pt-[15vh]">
        <img
          src="/loading/mone-logo.png"
          alt="MONE"
          className="w-[min(68vw,430px)] object-contain drop-shadow-[0_0_34px_rgba(66,223,212,0.22)]"
        />

        <div className="mt-[8vh] flex w-full flex-col items-center sm:mt-[9vh]">
          <div className="relative z-10 flex justify-center">
            <img
              src="/loading/mone-bear.png"
              alt="MONE bear"
              className="mb-[-30px] w-[min(39vw,190px)] object-contain drop-shadow-[0_18px_36px_rgba(0,0,0,0.58)] sm:mb-[-38px]"
            />
          </div>

          <div className="w-[min(82vw,760px)] rounded-[38px] border border-cyan-200/28 bg-[#101b26]/72 px-8 pb-9 pt-16 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_0_48px_rgba(18,217,209,0.1)] backdrop-blur-xl sm:px-16 sm:pb-14 sm:pt-20">
            <div className="text-center">
              <h1 className="text-[30px] font-extrabold tracking-tight text-white sm:text-[46px]">
                MONE 준비 중... <span className="text-[#58d8d2]">{safeProgress}%</span>
              </h1>
              <p className="mt-4 text-[16px] font-medium text-white/64 sm:text-[22px]">{message}</p>
            </div>

            <div className="mx-auto mt-9 h-4 w-full max-w-[630px] overflow-hidden rounded-full bg-white/12 sm:mt-12">
              <div
                className="h-full rounded-full bg-[#52ded6] shadow-[0_0_22px_rgba(82,222,214,0.82)] transition-all duration-500 ease-out"
                style={{ width: `${safeProgress}%` }}
              />
            </div>

            <p className="mt-11 text-center text-[16px] font-medium text-white/35 sm:text-[22px]">
              {delayed ? "데이터 확인이 조금 지연되고 있어요" : "잠시만 기다려 주세요"}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
