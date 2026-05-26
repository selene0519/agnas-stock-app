export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8010";

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
  entryText?: string;
  stop?: number | null;
  stopText?: string;
  target?: number | null;
  targetText?: string;
  quantity?: number | null;
  quantityText?: string;
  avgPrice?: number | null;
  avgPriceText?: string;
  marketValue?: number | null;
  marketValueText?: string;
  costBasis?: number | null;
  costBasisText?: string;
  returnPct?: number | null;
  returnPctText?: string;
  pnl?: number | null;
  pnlText?: string;
  confidence?: number | string | null;
  reason?: string;
  warning?: string;
  nextAction?: string;
  category?: string;
  scores?: {
    supply?: string;
    earnings?: string;
    valuation?: string;
    chart?: string;
  };
  statuses?: {
    data?: string;
    price?: string;
    earnings?: string;
    valuation?: string;
    flow?: string;
  };
  raw?: Record<string, unknown>;
};

export type ApiList<T> = {
  market?: Market;
  count: number;
  source?: string;
  sources?: string[];
  items: T[];
};

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store"
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function money(value?: number | null, market: Market = "kr") {
  if (!value) return "기준가 없음";
  return market === "us" ? `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `${value.toLocaleString()}원`;
}


export async function deleteJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    cache: "no-store"
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store"
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}
