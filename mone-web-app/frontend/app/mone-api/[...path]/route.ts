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
  const targetPath = joinedPath.startsWith("api/")
    ? `/${joinedPath}`
    : `/api/${joinedPath}`;

  const targetUrl = new URL(targetPath, BACKEND_URL);
  targetUrl.search = incomingUrl.search;

  return targetUrl.toString();
}

async function proxyRequest(request: NextRequest, context: RouteContext) {
  try {
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
        backendConfigured: Boolean(BACKEND_URL),
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
