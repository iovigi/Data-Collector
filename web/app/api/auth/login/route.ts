import { NextRequest, NextResponse } from "next/server";
import { CSRF_COOKIE_NAME, SESSION_COOKIE_NAME, createCsrfToken } from "@/lib/auth/csrf";
import { backendBaseUrl, generateSessionId, saveSession } from "@/lib/auth/session";

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: { email?: string; password?: string };
  try {
    body = (await req.json()) as { email?: string; password?: string };
  } catch {
    return NextResponse.json(
      { error: { code: "BAD_REQUEST", message: "Invalid JSON body" } },
      { status: 400 }
    );
  }

  const resp = await fetch(`${backendBaseUrl()}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email ?? "", password: body.password ?? "" }),
    cache: "no-store",
  });

  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({
      error: { code: "UNAUTHENTICATED", message: "Invalid credentials" },
    }));
    return NextResponse.json(errBody, { status: resp.status });
  }

  const tokens = (await resp.json()) as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  };

  // Fetch /api/v1/me to populate session identity
  const meResp = await fetch(`${backendBaseUrl()}/api/v1/me`, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
    cache: "no-store",
  });
  const me = meResp.ok
    ? ((await meResp.json()) as { principal_id: string; email?: string | null })
    : { principal_id: "unknown", email: body.email ?? null };

  const sid = generateSessionId();
  await saveSession({
    id: sid,
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + tokens.expires_in * 1000,
    userId: me.principal_id,
    email: me.email ?? body.email,
  });

  const csrfToken = createCsrfToken();
  const isProd = process.env.NODE_ENV === "production";
  const out = NextResponse.json({
    authenticated: true,
    user: { principal_id: me.principal_id, email: me.email ?? body.email },
  });
  out.cookies.set(SESSION_COOKIE_NAME, sid, {
    httpOnly: true,
    sameSite: "lax",
    secure: isProd,
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
  out.cookies.set(CSRF_COOKIE_NAME, csrfToken, {
    httpOnly: false, // readable by same-origin JS for double-submit X-CSRF-Token header
    sameSite: "lax",
    secure: isProd,
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });
  return out;
}
