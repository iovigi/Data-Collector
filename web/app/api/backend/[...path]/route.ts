import { NextRequest, NextResponse } from "next/server";
import { isAllowedBackendPath } from "@/lib/api/allowlist";
import {
  CSRF_COOKIE_NAME,
  SESSION_COOKIE_NAME,
  verifyCsrfToken,
} from "@/lib/auth/csrf";
import {
  backendBaseUrl,
  deleteSession,
  getSession,
  refreshSessionSingleFlight,
} from "@/lib/auth/session";

async function handleProxy(
  req: NextRequest,
  context: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path } = await context.params;
  const joined = path.join("/");
  if (!isAllowedBackendPath(joined)) {
    return NextResponse.json(
      { error: { code: "FORBIDDEN", message: "Backend path is not allowlisted" } },
      { status: 403 }
    );
  }

  const sid = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!sid) {
    return NextResponse.json(
      { error: { code: "UNAUTHENTICATED", message: "Authentication required" } },
      { status: 401 }
    );
  }

  const method = req.method.toUpperCase();
  if (!["GET", "HEAD"].includes(method)) {
    const csrfCookie = req.cookies.get(CSRF_COOKIE_NAME)?.value;
    const csrfHeader = req.headers.get("X-CSRF-Token");
    if (!verifyCsrfToken(csrfCookie, csrfHeader)) {
      return NextResponse.json(
        { error: { code: "FORBIDDEN", message: "Invalid or missing CSRF token" } },
        { status: 403 }
      );
    }
  }

  let session = await getSession(sid);
  if (!session) {
    return NextResponse.json(
      { error: { code: "UNAUTHENTICATED", message: "Session expired" } },
      { status: 401 }
    );
  }

  if (Date.now() > session.expiresAt - 15_000) {
    const refreshed = await refreshSessionSingleFlight(sid);
    if (!refreshed) {
      await deleteSession(sid);
      return NextResponse.json(
        { error: { code: "UNAUTHENTICATED", message: "Session expired" } },
        { status: 401 }
      );
    }
    session = refreshed;
  }

  const qs = req.nextUrl.searchParams.toString();
  const targetUrl = `${backendBaseUrl()}/api/v1/${joined}${qs ? `?${qs}` : ""}`;

  const forwardHeaders = new Headers();
  forwardHeaders.set("Authorization", `Bearer ${session.accessToken}`);
  const passthroughHeaders = ["content-type", "idempotency-key", "if-match", "accept"];
  for (const h of passthroughHeaders) {
    const val = req.headers.get(h);
    if (val) forwardHeaders.set(h, val);
  }

  const bodyBuffer = ["GET", "HEAD"].includes(method) ? undefined : await req.arrayBuffer();

  let upstream = await fetch(targetUrl, {
    method,
    headers: forwardHeaders,
    body: bodyBuffer,
    cache: "no-store",
  });

  if (upstream.status === 401 && (method === "GET" || req.headers.has("idempotency-key"))) {
    const refreshed = await refreshSessionSingleFlight(sid);
    if (refreshed) {
      forwardHeaders.set("Authorization", `Bearer ${refreshed.accessToken}`);
      upstream = await fetch(targetUrl, {
        method,
        headers: forwardHeaders,
        body: bodyBuffer,
        cache: "no-store",
      });
    }
  }

  const respHeaders = new Headers();
  for (const h of ["content-type", "content-disposition", "x-request-id", "x-content-sha256", "retry-after"]) {
    const val = upstream.headers.get(h);
    if (val) respHeaders.set(h, val);
  }
  respHeaders.set("Cache-Control", "no-store");

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

export const GET = handleProxy;
export const POST = handleProxy;
export const PATCH = handleProxy;
export const PUT = handleProxy;
export const DELETE = handleProxy;
