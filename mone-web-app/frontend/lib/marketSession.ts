import type { Market } from "./api";

export type SessionMarket = "kr" | "us";
export type SessionPhase = "장전" | "장중" | "장마감" | "개장 전" | "마감 후" | "휴장";

// ── KST 날짜/시간 ─────────────────────────────────────────────────────
export function kstNowParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).formatToParts(now);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value || 0);
  return {
    year: get("year"), month: get("month"), day: get("day"),
    hour: get("hour") % 24, minute: get("minute"),
  };
}

function kstDateStr(now = new Date()): string {
  const { year, month, day } = kstNowParts(now);
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function kstDayOfWeek(now = new Date()): number {
  // 0=일, 6=토
  return new Date(kstDateStr(now) + "T12:00:00+09:00").getDay();
}

// ── 휴장일 (KRX / NYSE) 2026–2027 ────────────────────────────────────
const KR_HOLIDAYS = new Set([
  // 2026
  "2026-01-01","2026-02-16","2026-02-17","2026-02-18",
  "2026-03-02","2026-05-01","2026-05-05","2026-05-25",
  "2026-06-03","2026-07-17","2026-08-17","2026-09-24",
  "2026-09-25","2026-10-05","2026-10-09","2026-12-25","2026-12-31",
  // 2027
  "2027-01-01","2027-02-08","2027-02-09","2027-03-01",
  "2027-05-03","2027-05-05","2027-05-13","2027-07-19",
  "2027-08-16","2027-09-14","2027-09-15","2027-09-16",
  "2027-10-04","2027-10-11","2027-12-27","2027-12-31",
]);

const US_HOLIDAYS = new Set([
  // 2026
  "2026-01-01","2026-01-19","2026-02-16","2026-04-03",
  "2026-05-25","2026-06-19","2026-07-03","2026-09-07",
  "2026-11-26","2026-12-25",
  // 2027
  "2027-01-01","2027-01-18","2027-02-15","2027-03-26",
  "2027-05-31","2027-06-18","2027-07-05","2027-09-06",
  "2027-11-25","2027-12-24",
]);

export function isMarketClosed(market: "kr" | "us", now = new Date()): boolean {
  const dow = kstDayOfWeek(now);
  if (dow === 0 || dow === 6) return true; // 주말
  const d = kstDateStr(now);
  return market === "kr" ? KR_HOLIDAYS.has(d) : US_HOLIDAYS.has(d);
}

// ── 다음 거래일 ───────────────────────────────────────────────────────
export function nextTradingDay(market: "kr" | "us", from = new Date()): string {
  const d = new Date(from.getTime());
  for (let i = 0; i < 14; i++) {
    d.setTime(d.getTime() + 86400000); // +1일
    const str = kstDateStr(d);
    const dow = new Date(str + "T12:00:00+09:00").getDay();
    const weekend = dow === 0 || dow === 6;
    const holiday = market === "kr" ? KR_HOLIDAYS.has(str) : US_HOLIDAYS.has(str);
    if (!weekend && !holiday) return str;
  }
  return kstDateStr(d);
}

// ── 세션 상태 ─────────────────────────────────────────────────────────
export function getMarketSessionStatus(market: "kr" | "us", now = new Date()): SessionPhase {
  if (isMarketClosed(market, now)) return "휴장";
  const { hour, minute } = kstNowParts(now);
  const t = hour * 60 + minute;
  if (market === "kr") {
    if (t >= 9 * 60 && t <= 15 * 60 + 30) return "장중";
    if (t > 15 * 60 + 30) return "장마감";
    return "장전";
  }
  // 미장: 22:30 ~ 익일 05:00 KST
  if (t >= 22 * 60 + 30 || t <= 5 * 60) return "장중";
  if (t > 15 * 60 + 30 && t < 22 * 60 + 30) return "개장 전";
  return "마감 후";
}

// ── 카운트다운 ────────────────────────────────────────────────────────
export function getSessionCountdown(market: "kr" | "us", now = new Date()): string {
  const fmt = (rem: number) => {
    const h = Math.floor(rem / 60), m = rem % 60;
    return h > 0 ? `${h}시간 ${m}분` : `${m}분`;
  };

  if (isMarketClosed(market, now)) {
    const next = nextTradingDay(market, now);
    const label = market === "kr" ? "국장" : "미장";
    return `다음 ${label} 거래일 ${next}`;
  }

  const { hour, minute } = kstNowParts(now);
  const t = hour * 60 + minute;

  if (market === "kr") {
    const open = 9 * 60, close = 15 * 60 + 30;
    if (t < open) return `국장 시작까지 ${fmt(open - t)}`;
    if (t <= close) return `장마감까지 ${fmt(close - t)}`;
    return `다음 국장 거래일 ${nextTradingDay(market, now)}`;
  }
  const usOpen = 22 * 60 + 30, usClose = 5 * 60;
  if (t < usClose) return `미장 마감까지 ${fmt(usClose - t)}`;
  if (t < usOpen) return `미장 시작까지 ${fmt(usOpen - t)}`;
  return `미장 마감까지 ${fmt(24 * 60 - t + usClose)}`;
}

// ── 자동 마켓 선택 (사용자 지정 시간 규칙) ─────────────────────────────
// 자동 모드 기준:
// - KST 08:00 이상 20:00 미만 → KR
// - KST 20:00 이상 또는 08:00 미만 → US
// - 수동 KR/US 선택은 자동보다 우선
// - 탐색 화면은 실제 시장 개장 여부와 무관하게 시간대 기준으로 결정
//   (주말/공휴일이라도 20:00~08:00 KST이면 US 예측 데이터를 보여줌)
export function resolveAutoMarket(
  now = new Date(),
  manualMarket?: Market | SessionMarket | "auto" | null,
): SessionMarket {
  if (manualMarket === "kr" || manualMarket === "us") return manualMarket;

  const { hour, minute } = kstNowParts(now);
  const total = hour * 60 + minute;
  const dow = kstDayOfWeek(now); // 0=일, 1=월, ..., 6=토

  // 토 08:00 ~ 월 20:00: 전 구간 국장
  //   일요일 전체, 월요일 20:00 이전, 토요일 08:00 이후
  if (dow === 0) return "kr";                            // 일 전체
  if (dow === 1 && total < 20 * 60) return "kr";        // 월 ~20:00
  if (dow === 6 && total >= 8 * 60) return "kr";        // 토 08:00~

  // 그 외: 시간 기반 (월~토 08:00~20:00 → KR, 나머지 → US)
  return total >= 8 * 60 && total < 20 * 60 ? "kr" : "us";
}

// ── 기본 마켓 선택 (세션 기반) ────────────────────────────────────────
export function getDefaultMarketBySession(now = new Date()): SessionMarket {
  return resolveAutoMarket(now);
}

export function marketLabel(market: Market | SessionMarket | "auto") {
  if (market === "kr") return "국장";
  if (market === "us") return "미장";
  return "자동";
}

export function marketSessionNote(market: Market | SessionMarket | "auto") {
  if (market === "kr") return "08:00~20:00 KST 기본 국장 모드";
  if (market === "us") return "20:00~08:00 KST 기본 미장 모드";
  return "자동: 08:00~20:00 국장 · 20:00~08:00 미장 · 휴장/공휴일은 국장 기준";
}
