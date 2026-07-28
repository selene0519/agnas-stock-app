import type { DataStatus, Market, PriceSession, RiskLevel } from "./types";

export function fmt(n: number | null | undefined, decimals = 0, suffix = "") {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return "-";
  return (
    Number(n).toLocaleString("ko-KR", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }) + suffix
  );
}

export function fmtPct(n: number | null | undefined) {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return "-";
  const sign = Number(n) > 0 ? "+" : "";
  return `${sign}${Number(n).toFixed(2)}%`;
}

export function normalizeMarket(market: Market | string | undefined): "KR" | "US" {
  return String(market || "KR").toUpperCase() === "US" ? "US" : "KR";
}

export function fmtPrice(n: number | null | undefined, market: Market | string = "KR") {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return "-";
  if (normalizeMarket(market) === "US") {
    return `$${Number(n).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
  return `${Math.round(Number(n)).toLocaleString("ko-KR")}원`;
}

export function normalizeDisplaySymbol(symbol: string, market: Market | string = "KR") {
  const raw = String(symbol || "").trim().toUpperCase();
  if (normalizeMarket(market) === "US") return raw;
  const digits = raw.replace(/\D/g, "");
  return digits ? digits.padStart(6, "0") : raw;
}

export function stockLabel(symbol: string, name: string, market: Market | string = "KR") {
  const code = normalizeDisplaySymbol(symbol, market);
  const cleanName = String(name || "").trim();
  if (!cleanName || cleanName === code || cleanName === symbol) return code;
  return normalizeMarket(market) === "KR" ? `${cleanName} (${code})` : `${cleanName} (${code})`;
}

export function fmtVolume(n: number | null | undefined) {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return "-";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

export function fmtBigNum(n: number | null | undefined) {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return "-";
  const value = Number(n);
  if (Math.abs(value) >= 1_000_000_000_000) return `${(value / 1_000_000_000_000).toFixed(1)}조`;
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(0)}억`;
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}백만`;
  return String(value);
}

export function changeColor(v: number | null | undefined) {
  if (v === null || v === undefined) return "text-slate-400";
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-red-400";
  return "text-slate-400";
}

// 백엔드가 실제로 내보내는 상태 코드 전부에 한국어 라벨을 붙인다.
// 예전엔 매핑에 없으면 코드를 그대로 반환해서 세션 배너에 "EMPTY_RESULT" 같은
// 기계 코드가 사용자에게 노출됐다(2026-07-26 홈 화면에서 실제 확인).
const STATUS_LABELS: Record<string, string> = {
  NORMAL: "정상",
  OK: "정상",
  PARTIAL: "일부 누락",
  STALE: "오래된 데이터",
  NO_DATA: "데이터 없음",
  EMPTY: "데이터 없음",
  EMPTY_RESULT: "결과 없음",
  NOT_FOUND: "데이터 없음",
  MISSING: "데이터 없음",
  ERROR: "오류",
  NETWORK_ERROR: "동기화 지연",
  PENDING: "확인 중",
  PRICE_PENDING: "현재가 대기",
  DATA_PENDING: "데이터 축적 중",
  DATA_SHORT: "데이터 부족",
  DATA_INSUFFICIENT: "데이터 부족",
  LOW_SAMPLE: "표본 부족",
  FALLBACK: "대체 데이터",
  CAUTION: "주의",
  BLOCKED: "차단됨",
  DISABLED: "비활성",
  SKIPPED: "건너뜀",
  SKIP: "건너뜀",
  VALIDATION_UNAVAILABLE: "검증 불가",
  NOT_AVAILABLE: "제공 불가",
  MISSING_KEY: "설정 누락",
  // 운용 게이트(quant_operating_governor)가 내는 값. 화면에 "DEFERRED"가
  // 그대로 떠 있었다 — 밑줄 없는 단독 대문자라 앞선 기계코드 스캔에서 놓쳤다.
  DEFERRED: "판정 보류",
  CHECK: "확인 필요",
};

export function statusLabel(s: DataStatus | string): string {
  const value = String(s || "NO_DATA").toUpperCase();
  const mapped = STATUS_LABELS[value];
  if (mapped) return mapped;
  // 모르는 코드는 그대로 노출하지 않는다. 진단은 개발자 도구에서.
  if (/^[A-Z][A-Z0-9_]*$/.test(value)) return "상태 확인 중";
  return value;
}

export function statusClass(s: DataStatus | string): string {
  const value = String(s || "NO_DATA").toUpperCase();
  const map: Record<string, string> = {
    NORMAL: "status-normal",
    PARTIAL: "status-partial",
    STALE: "status-stale",
    NO_DATA: "status-nodata",
    ERROR: "status-error",
  };
  return map[value] ?? "status-nodata";
}

export function priceSessionLabel(s: PriceSession | string): string {
  const map: Record<string, string> = {
    kr_premarket: "국장 장전 · 전일 OHLCV 기준",
    kr_intraday: "국장 장중 · KIS 현재가 기준",
    kr_after_close: "국장 장마감 후 · 마감 업데이트 기준",
    kr_closed: "국장 휴장 · 지난 운용 복기 모드",
    kr_closed_weekend: "국장 주말 휴장 · 지난 운용 복기 모드",
    kr_closed_holiday: "국장 공휴일 · 지난 운용 복기 모드",
    us_premarket: "미장 장전 · 프리마켓 기준",
    us_intraday: "미장 장중 · KIS 현재가 기준",
    us_after_close: "미장 장마감 후 · 마감 업데이트 기준",
    us_closed: "미장 휴장 · 지난 운용 복기 모드",
    us_closed_weekend: "미장 주말 휴장 · 지난 운용 복기 모드",
    us_closed_holiday: "미장 공휴일 · 지난 운용 복기 모드",
    UNKNOWN: "가격 기준 확인 중",
  };
  return map[String(s)] ?? "가격 기준 확인 중";
}

export function riskColor(r: RiskLevel | string) {
  const map: Record<string, string> = {
    안전: "text-emerald-400",
    LOW: "text-emerald-400",
    주의: "text-amber-400",
    WATCH: "text-amber-400",
    위험: "text-red-400",
    HIGH: "text-red-400",
    손절필요: "text-red-500",
  };
  return map[String(r)] ?? "text-slate-400";
}

export function riskBg(r: RiskLevel | string) {
  const map: Record<string, string> = {
    안전: "risk-low",
    LOW: "risk-low",
    주의: "risk-mid",
    WATCH: "risk-mid",
    위험: "risk-high",
    HIGH: "risk-high",
    손절필요: "risk-high",
  };
  return map[String(r)] ?? "risk-mid";
}

export function timeAgo(dateStr: string) {
  const d = new Date(String(dateStr || "").replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return "업데이트 대기";
  const diff = Date.now() - d.getTime();
  const minutes = Math.max(0, Math.floor(diff / 60000));
  if (minutes < 1) return "방금 전";
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  return `${Math.floor(hours / 24)}일 전`;
}
