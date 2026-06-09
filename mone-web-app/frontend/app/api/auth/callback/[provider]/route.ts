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
  params: Promise<{ provider?: string }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const { provider = "" } = await context.params;
  const cleanProvider = provider.toLowerCase().trim();
  const frontendUrl = new URL("/auth/callback", request.url);

  if (!["google", "kakao"].includes(cleanProvider) || !BACKEND_URL) {
    frontendUrl.searchParams.set("error", "oauth_callback");
    return NextResponse.redirect(frontendUrl);
  }

  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(`/api/auth/oauth/${cleanProvider}/callback`, BACKEND_URL);
  targetUrl.search = incomingUrl.search;

  try {
    const backendRes = await fetch(targetUrl, {
      method: "GET",
      cache: "no-store",
      redirect: "manual",
      headers: {
        accept: "application/json,text/html,*/*",
        "x-forwarded-host": request.headers.get("host") || incomingUrl.host,
        "x-forwarded-proto": incomingUrl.protocol.replace(":", "") || "https",
      },
    });

    const location = backendRes.headers.get("location");
    if (location && backendRes.status >= 300 && backendRes.status < 400) {
      return NextResponse.redirect(location, { status: backendRes.status });
    }

    const body = await backendRes.arrayBuffer();
    return new NextResponse(body, {
      status: backendRes.status,
      headers: {
        "content-type": backendRes.headers.get("content-type") || "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  } catch (error) {
    frontendUrl.searchParams.set("error", "oauth_failed");
    frontendUrl.searchParams.set("detail", String(error).slice(0, 120));
    return NextResponse.redirect(frontendUrl);
  }
}
