import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const CONFIGURED_BACKEND_URL = (
  process.env.MONE_BACKEND_URL ||
  process.env.NEXT_PUBLIC_MONE_BACKEND_URL ||
  ""
).trim();

const BACKEND_URL =
  CONFIGURED_BACKEND_URL ||
  (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8050");

type RouteContext = {
  params: Promise<{ path?: string[] }>;
};

async function getPathSegments(context: RouteContext): Promise<string[]> {
  const params = await context.params;
  return Array.isArray(params?.path) ? params.path : [];
}

function buildTargetUrl(pathSegments: string[], request: NextRequest): string {
  if (!BACKEND_URL) {
    throw new Error("MONE_BACKEND_URL is not configured for the frontend proxy");
  }

  const incomingUrl = new URL(request.url);
  const joinedPath = pathSegments.join("/");

  // /mone-api/api/xxx  -> backend /api/xxx
  // /mone-api/xxx      -> backend /api/xxx
  // /mone-api/health   -> backend /health
  const targetPath = joinedPath === "health"
    ? "/health"
    : joinedPath.startsWith("api/")
    ? `/${joinedPath}`
    : `/api/${joinedPath}`;

  const targetUrl = new URL(targetPath, BACKEND_URL);
  targetUrl.search = incomingUrl.search;

  return targetUrl.toString();
}

// Render free tier cold-start: 첫 요청 최대 60초 소요
// Vercel nodejs 함수 최대 실행 60초 → 55초 제한으로 여유 확보
const PROXY_TIMEOUT_MS = 55000;

// 전달할 헤더 목록 (사용자 식별 포함)
const FORWARDED_HEADERS = [
  "accept",
  "content-type",
  "authorization",
  "x-mone-user",   // 사용자별 SQLite 데이터 격리에 필요
  "x-forwarded-for",
];

async function proxyRequest(request: NextRequest, context: RouteContext) {
  try {
    const pathSegments = await getPathSegments(context);
    const targetUrl = buildTargetUrl(pathSegments, request);

    const headers = new Headers();
    for (const name of FORWARDED_HEADERS) {
      const val = request.headers.get(name);
      if (val) headers.set(name, val);
    }

    const method = request.method.toUpperCase();

    // timeout: 25초 — Render cold-start가 길어지면 클라이언트에 503 반환
    const timeoutController = new AbortController();
    const timeoutId = setTimeout(() => timeoutController.abort(), PROXY_TIMEOUT_MS);

    const init: RequestInit = {
      method,
      headers,
      cache: "no-store",
      signal: timeoutController.signal,
    };

    if (!["GET", "HEAD"].includes(method)) {
      init.body = await request.text();
    }

    let backendRes: Response;
    try {
      backendRes = await fetch(targetUrl, init);
    } finally {
      clearTimeout(timeoutId);
    }

    const body = await backendRes.arrayBuffer();
    const responseHeaders = new Headers();

    const backendContentType = backendRes.headers.get("content-type");
    if (backendContentType) {
      responseHeaders.set("content-type", backendContentType);
    } else {
      responseHeaders.set("content-type", "application/json; charset=utf-8");
    }
    responseHeaders.set("cache-control", "no-store");

    return new NextResponse(body, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    const isTimeout = String(error).includes("abort") || String(error).includes("AbortError");
    const status = isTimeout ? 503 : 502;
    return NextResponse.json(
      {
        status: "ERROR",
        error: isTimeout ? "BACKEND_COLD_START_TIMEOUT" : "FRONTEND_PROXY_FAILED",
        detail: isTimeout
          ? "백엔드 서버가 초기화 중입니다. 잠시 후 다시 시도해 주세요. (Render cold-start)"
          : String(error),
        retryAfter: isTimeout ? 15 : 0,
        backendConfigured: Boolean(BACKEND_URL),
      },
      { status }
    );
  }
}

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}

export async function HEAD(request: NextRequest, context: RouteContext) {
  return proxyRequest(request, context);
}
