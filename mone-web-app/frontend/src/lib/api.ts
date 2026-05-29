export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "http://127.0.0.1:8050";

export type Market = "kr" | "us";

export type Security = {
  symbol?: string;
  code?: string;
  name?: string;
  market?: Market | string;
  [key: string]: any;
};

export type ApiList<T = any> = {
  status?: string;
  count?: number;
  items: T[];
  data?: T[];
  source?: string;
  sources?: string[];
  missingReason?: string;
  requiredFiles?: string[];
  [key: string]: any;
};

function toUrl(path: string) {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (path.startsWith("/")) return `${API_BASE}${path}`;
  return `${API_BASE}/${path}`;
}

async function requestJson<T = any>(
  method: string,
  path: string,
  body?: any,
  timeoutMs = 60000
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(toUrl(path), {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`${method} ${path} failed: ${res.status}`);
    }

    return (await res.json()) as T;
  } finally {
    window.clearTimeout(timer);
  }
}

export function getJson<T = any>(path: string, timeoutMs = 60000) {
  return requestJson<T>("GET", path, undefined, timeoutMs);
}

export function postJson<T = any>(path: string, body?: any) {
  return requestJson<T>("POST", path, body);
}

export function patchJson<T = any>(path: string, body?: any) {
  return requestJson<T>("PATCH", path, body);
}

export function deleteJson<T = any>(path: string, body?: any) {
  return requestJson<T>("DELETE", path, body);
}

export function fetchVirtualPortfolio<T = any>(market: Market = "kr", mode = "balanced") {
  return getJson<T>(`/api/virtual/portfolio?market=${market}&mode=${mode}`, 60000);
}

export function money(value: any, market: Market | string = "kr") {
  const num = Number(value);
  if (!Number.isFinite(num)) return "현재가 없음";

  if (market === "us") {
    return `$${num.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  return `${Math.round(num).toLocaleString("ko-KR")}원`;
}
