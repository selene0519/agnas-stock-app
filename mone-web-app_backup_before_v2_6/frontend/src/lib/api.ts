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
  prob1d?: string;
  prob3d?: string;
  prob5d?: string;
  prob20d?: string;
  probShort?: string;
  probSwing?: string;
  probMid?: string;
  expectedPrice1dText?: string;
  expectedPrice3dText?: string;
  expectedPrice5dText?: string;
  expectedPrice20dText?: string;
  expectedPriceShortText?: string;
  expectedPriceSwingText?: string;
  expectedPriceMidText?: string;
  expectedOpenText?: string;
  expectedCloseText?: string;
  swingGrade?: string;
  swingGradeCode?: string;
  recommendationModes?: string[];
  recommendationModeText?: string;
  virtualPlans?: Record<string, {
    mode?: string;
    modeLabel?: string;
    status?: string;
    capitalText?: string;
    entryText?: string;
    sharesText?: string;
    investedText?: string;
    cashText?: string;
    lossPctText?: string;
    profitPctText?: string;
    lossTotalText?: string;
    profitTotalText?: string;
    accountLossPctText?: string;
    accountProfitPctText?: string;
    buyRule?: string;
    holdDays?: number | string;
    sellRule?: string;
    summary?: string;
  }>;
  predictionModelNote?: string;
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
  if (value === undefined || value === null || !Number.isFinite(Number(value))) return "가격 없음";
  const num = Number(value);
  const sign = num > 0 ? "" : num < 0 ? "-" : "";
  const abs = Math.abs(num);
  if (market === "us") return `${sign}$${abs.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return `${sign}${Math.trunc(abs).toLocaleString()}원`;
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
