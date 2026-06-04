import type { Market } from "./api";

export type SessionMarket = "kr" | "us";

export function kstNowParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value || 0);
  return { hour: get("hour") % 24, minute: get("minute") };
}

export function getDefaultMarketBySession(now = new Date()): SessionMarket {
  const { hour, minute } = kstNowParts(now);
  const total = hour * 60 + minute;
  return total >= 7 * 60 && total < 17 * 60 ? "kr" : "us";
}

export function marketLabel(market: Market | SessionMarket) {
  if (market === "kr") return "국장";
  if (market === "us") return "미장";
  return "전체";
}

export function marketSessionNote(market: Market | SessionMarket) {
  if (market === "kr") return "07:00~17:00 KST 기본 국장 모드";
  if (market === "us") return "17:00~07:00 KST 기본 미장 모드";
  return "국장·미장 통합 보기";
}
