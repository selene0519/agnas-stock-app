import type { Market, Mode, Horizon } from "@/lib/api";

export const KR_NAME_MAP: Record<string, string> = {
  "005930": "삼성전자",
  "000660": "SK하이닉스",
  "005380": "현대차",
  "131970": "두산테스나",
  "222800": "심텍",
  "035420": "NAVER",
  "207940": "삼성바이오로직스",
  "000100": "유한양행",
  "058470": "리노공업",
  "006400": "삼성SDI",
  "196170": "알테오젠",
  "055550": "신한지주",
  "375500": "DL이앤씨",
  "086520": "에코프로",
  "214150": "클래시스",
  "267260": "HD현대일렉트릭",
  "001440": "대한전선",
  "003490": "대한항공",
  "090360": "로보스타",
  "247540": "에코프로비엠",
  "403870": "HPSP",
  "012450": "한화에어로스페이스",
  "079550": "LIG넥스원",
  "064350": "현대로템",
  "034020": "두산에너빌리티",
  "103590": "일진전기",
  "373220": "LG에너지솔루션",
  "015760": "한국전력",
  "035720": "카카오",
};

export const US_NAME_MAP: Record<string, string> = {
  NVDA: "NVIDIA",
  GOOGL: "Alphabet",
  GOOG: "Alphabet",
  TSLA: "Tesla",
  AAPL: "Apple",
  MSFT: "Microsoft",
  AMZN: "Amazon",
  SOXX: "Semiconductor ETF",
  VRT: "Vertiv",
  CAT: "Caterpillar",
  CRCL: "Circle",
  NBIS: "Nebius",
  SNDK: "SanDisk",
  RKLB: "Rocket Lab",
  ASTS: "AST SpaceMobile",
  AAOI: "AAOI",
  BMNR: "BMNR",
  INTC: "Intel",
  LITE: "Lumentum",
  SIMO: "SIMO",
  TMDX: "TMDX",
  COHR: "Coherent",
  META: "Meta Platforms",
};

export function normalizeMarket(value: any, symbol?: string): "kr" | "us" {
  const raw = String(value || "").toLowerCase();
  if (raw === "kr" || raw === "kospi" || raw === "kosdaq") return "kr";
  if (raw === "us" || raw === "nasdaq" || raw === "nyse" || raw === "amex") return "us";
  return String(symbol || "").match(/^\d{6}$/) ? "kr" : "us";
}

export function normalizeSymbol(item: any): string {
  return String(item?.symbol || item?.code || item?.ticker || "").trim().toUpperCase();
}

export function displayName(itemOrSymbol: any, maybeMarket?: string, maybeRaw?: string): string {
  const symbol = typeof itemOrSymbol === "string" ? itemOrSymbol.toUpperCase() : normalizeSymbol(itemOrSymbol);
  const market = normalizeMarket(typeof itemOrSymbol === "string" ? maybeMarket : itemOrSymbol?.market, symbol);
  const raw = String(typeof itemOrSymbol === "string" ? maybeRaw || "" : itemOrSymbol?.name || itemOrSymbol?.company || itemOrSymbol?.companyName || "").trim();
  const mapped = market === "kr" ? KR_NAME_MAP[symbol] : US_NAME_MAP[symbol];
  if (mapped) return mapped;
  if (raw && raw !== symbol && raw.toLowerCase() !== "nan" && raw !== "-") return raw;
  return symbol || "-";
}

export function itemKey(item: any): string {
  const symbol = normalizeSymbol(item);
  const market = normalizeMarket(item?.market, symbol);
  return `${market}-${symbol}`;
}

export function dedupeBySymbol<T extends Record<string, any>>(items: T[] = []): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const raw of items || []) {
    const symbol = normalizeSymbol(raw);
    if (!symbol) continue;
    const market = normalizeMarket(raw.market, symbol);
    const key = `${market}-${symbol}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ ...raw, symbol, market, name: displayName(raw) } as T);
  }
  return out;
}

export function toNumber(value: any): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const text = String(value ?? "").replace(/,/g, "").replace(/[^0-9.-]/g, "");
  if (!text || text === "-" || text === ".") return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value: any, market: string = "kr", fallback = "-"): string {
  const n = toNumber(value);
  if (n === null || n <= 0) return fallback;
  return normalizeMarket(market) === "us"
    ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : `${Math.round(n).toLocaleString("ko-KR")}원`;
}

export function firstText(...values: any[]): string {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text && text !== "-" && text !== "NaN" && text !== "null" && text !== "undefined") return text;
  }
  return "-";
}

export function priceText(item: any, key: "current" | "entry" | "stop" | "target" | "expected", fallback = "-"): string {
  const market = normalizeMarket(item?.market, normalizeSymbol(item));
  const candidates: Record<string, any[]> = {
    current: [item?.currentPriceText, item?.priceText, item?.currentText, item?.currentPrice, item?.price],
    entry: [item?.entryText, item?.entryPriceText, item?.entryPrice, item?.entry],
    stop: [item?.stopText, item?.stopPriceText, item?.stopPrice, item?.stop],
    target: [item?.targetText, item?.targetPriceText, item?.targetPrice, item?.target],
    expected: [item?.expectedPriceText, item?.expectedText, item?.expectedPrice, item?.expected],
  };
  for (const value of candidates[key]) {
    const text = String(value ?? "").trim();
    if (text && text !== "-" && /[₩$원]|\d/.test(text)) {
      if (/[₩$원]/.test(text)) return text.replace(/₩/g, "");
      return formatMoney(value, market, fallback);
    }
  }
  return fallback;
}

export function pctText(value: any, fallback = "-"): string {
  const text = String(value ?? "").trim();
  if (text && text !== "-" && text.includes("%")) return text;
  const n = toNumber(value);
  if (n === null) return fallback;
  const signed = n > 0 ? "+" : "";
  return `${signed}${n.toFixed(2)}%`;
}

export function probabilityText(item: any, fallback = "-"): string {
  return firstText(item?.probabilityText, item?.probText, item?.probability ? pctText(item.probability) : null, item?.prob5d ? pctText(item.prob5d) : null, fallback);
}

export function modeLabel(mode: Mode | string): string {
  if (mode === "conservative") return "보수";
  if (mode === "aggressive") return "공격";
  if (mode === "balanced") return "균형";
  return String(mode || "-");
}

export function horizonLabel(horizon: Horizon | string): string {
  if (horizon === "short") return "단기";
  if (horizon === "swing") return "스윙";
  if (horizon === "mid") return "중기";
  if (horizon === "long") return "장기";
  return String(horizon || "-");
}

export function statusBadge(status?: string): string {
  const value = String(status || "").toUpperCase();
  if (["OK", "NORMAL", "MATCH", "EXECUTED", "WIN"].includes(value)) return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (["ERROR", "NO_DATA", "LOSS", "HIGH"].includes(value)) return "border-red-500/30 bg-red-500/10 text-red-300";
  return "border-amber-500/30 bg-amber-500/10 text-amber-300";
}

export function sortByValue(items: any[]): any[] {
  return [...items].sort((a, b) => {
    const av = toNumber(a.valuation || a.valuationText || a.currentPrice) || 0;
    const bv = toNumber(b.valuation || b.valuationText || b.currentPrice) || 0;
    return bv - av;
  });
}
