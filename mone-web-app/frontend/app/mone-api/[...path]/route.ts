import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_URL =
  process.env.MONE_BACKEND_URL ||
  process.env.NEXT_PUBLIC_MONE_BACKEND_URL ||
  "http://127.0.0.1:8050";

type RouteContext = {
  params: Promise<{ path?: string[] }> | { path?: string[] };
};

async function getPathSegments(context: RouteContext): Promise<string[]> {
  const rawParams = context?.params;
  const params =
    rawParams && typeof (rawParams as Promise<{ path?: string[] }>).then === "function"
      ? await (rawParams as Promise<{ path?: string[] }>)
      : (rawParams as { path?: string[] } | undefined);

  return Array.isArray(params?.path) ? params.path : [];
}

function buildTargetUrl(pathSegments: string[], request: NextRequest): string {
  const incomingUrl = new URL(request.url);
  const joinedPath = pathSegments.join("/");

  // /mone-api/api/xxx  -> backend /api/xxx
  // /mone-api/xxx      -> backend /api/xxx
  const targetPath = joinedPath.startsWith("api/")
    ? `/${joinedPath}`
    : `/api/${joinedPath}`;

  const targetUrl = new URL(targetPath, BACKEND_URL);
  targetUrl.search = incomingUrl.search;

  return targetUrl.toString();
}

async function proxyRequest(request: NextRequest, context: RouteContext) {
  const pathSegments = await getPathSegments(context);
  const targetUrl = buildTargetUrl(pathSegments, request);

  const headers = new Headers();
  const accept = request.headers.get("accept");
  const contentType = request.headers.get("content-type");
  const authorization = request.headers.get("authorization");

  if (accept) headers.set("accept", accept);
  if (contentType) headers.set("content-type", contentType);
  if (authorization) headers.set("authorization", authorization);

  const method = request.method.toUpperCase();
  const init: RequestInit = {
    method,
    headers,
    cache: "no-store",
  };

  if (!["GET", "HEAD"].includes(method)) {
    init.body = await request.text();
  }

  try {
    const backendRes = await fetch(targetUrl, init);
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
    return NextResponse.json(
      {
        status: "ERROR",
        error: "FRONTEND_PROXY_FAILED",
        detail: String(error),
        targetUrl,
      },
      { status: 502 }
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
