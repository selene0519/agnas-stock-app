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
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center overflow-hidden bg-[#0b1220] text-white">
      {/* 상단 은은한 teal glow */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_90%_45%_at_50%_0%,rgba(20,180,175,0.18),transparent)]" />

      {/* 배경 차트 라인 패턴 */}
      <div className="pointer-events-none absolute inset-x-0 top-[30%] h-[40vh] opacity-20">
        <svg viewBox="0 0 945 360" className="h-full w-full" aria-hidden="true" preserveAspectRatio="none">
          <path
            d="M0 86 C100 136 114 224 236 248 C347 270 405 201 510 195 C642 187 695 160 756 83 C813 14 851 42 945 0"
            fill="none"
            stroke="rgba(22,181,190,0.35)"
            strokeWidth="2"
          />
          <path
            d="M0 209 C112 235 155 312 281 315 C405 318 446 262 562 251 C681 240 758 167 823 129 C873 101 905 112 945 70"
            fill="none"
            stroke="rgba(22,181,190,0.18)"
            strokeWidth="2"
          />
          <g fill="rgba(22,181,190,0.30)">
            <circle cx="760" cy="86" r="6" />
            <circle cx="823" cy="129" r="6" />
          </g>
        </svg>
      </div>

      {/* 메인 콘텐츠 */}
      <div className="relative flex w-full max-w-[360px] flex-col items-center px-6 sm:max-w-[420px]">
        {/* MONE 로고 (헬릭스 심볼) */}
        <img
          src="/loading/mone-logo.png"
          alt=""
          className="w-[min(52vw,200px)] object-contain drop-shadow-[0_0_28px_rgba(66,223,212,0.28)] sm:w-[min(46vw,220px)]"
        />

        {/* MONE 텍스트 */}
        <p
          className="mt-1 tracking-[0.35em] text-white drop-shadow-[0_0_18px_rgba(66,223,212,0.25)] sm:mt-1"
          style={{
            fontFamily: "'Orbitron', sans-serif",
            fontWeight: 300,
            fontSize: "clamp(22px, 7vw, 32px)",
            letterSpacing: "0.35em",
          }}
        >
          MONE
        </p>

        {/* 태그라인 */}
        <p
          className="mb-24 mt-1 text-[#3dd8d0]/70 sm:mb-28"
          style={{
            fontFamily: "'Orbitron', sans-serif",
            fontWeight: 300,
            fontSize: "clamp(7px, 2vw, 9px)",
            letterSpacing: "0.25em",
          }}
        >
          WHERE MOMENTUM BEGINS.
        </p>

        {/* 곰돌이 + 카드 */}
        <div className="flex w-full flex-col items-center">
          {/* 곰돌이 - 카드 위에 살짝 겹치게 */}
          <img
            src="/loading/mone-bear.png"
            alt="MONE bear"
            className="relative z-10 mb-[-20px] w-[min(44vw,175px)] object-contain drop-shadow-[0_10px_28px_rgba(0,0,0,0.65)] sm:mb-[-22px] sm:w-[min(40vw,190px)]"
          />

          {/* 진행 카드 */}
          <div className="w-full rounded-[22px] bg-[#1a2a3a] px-6 pb-7 pt-7 shadow-[0_4px_40px_rgba(0,0,0,0.55)] sm:px-8 sm:pb-8 sm:pt-8">
            {/* 제목 + 퍼센트 */}
            <p className="text-[20px] font-extrabold leading-snug text-white sm:text-[24px]">
              MONE 준비 중...{" "}
              <span className="text-[#3dd8d0]">{safeProgress}%</span>
            </p>

            {/* 상태 메시지 */}
            <p className="mt-[6px] text-[13px] font-medium text-white/55 sm:text-[15px]">
              {message}
            </p>

            {/* 진행바 */}
            <div className="mt-5 h-[6px] w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-[#3dd8d0] shadow-[0_0_10px_rgba(61,216,208,0.7)] transition-all duration-500 ease-out"
                style={{ width: `${safeProgress}%` }}
              />
            </div>

            {/* 하단 안내 문구 */}
            <p className="mt-5 text-center text-[12px] font-medium text-white/30 sm:text-[13px]">
              {delayed ? "데이터 확인이 조금 지연되고 있어요" : "잠시만 기다려 주세요."}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
