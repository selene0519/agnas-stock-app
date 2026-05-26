export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export type Market = "kr" | "us";

export type Security = {
  symbol: string;
  name: string;
  market: Market;
  marketLabel: string;
  currentPrice: number | null;
  currentPriceText: string;
  priceTime: string;
  priceSource: string;
  dataStatus: string;
  entry?: number | null;
  stop?: number | null;
  target?: number | null;
  confidence?: number | null;
  reason?: string;
  warning?: string;
  nextAction?: string;
  category?: string;
  raw?: Record<string, unknown>;
};

export type ApiList<T> = {
  market?: Market;
  count: number;
  source?: string;
  items: T[];
};

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function money(value?: number | null, market: Market = "kr") {
  if (!value) return "기준가 없음";
  return market === "us" ? `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `${value.toLocaleString()}원`;
}
