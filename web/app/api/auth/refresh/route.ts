import { NextRequest, NextResponse } from "next/server";
import {
  CSRF_COOKIE_NAME,
  SESSION_COOKIE_NAME,
  verifyCsrfToken,
} from "@/lib/auth/csrf";
import { refreshSessionSingleFlight } from "@/lib/auth/session";

export async function POST(req: NextRequest): Promise<NextResponse> {
  const sid = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (!sid) {
    return NextResponse.json(
      { error: { code: "UNAUTHENTICATED", message: "No active session" } },
      { status: 401 }
    );
  }

  const csrfCookie = req.cookies.get(CSRF_COOKIE_NAME)?.value;
  const csrfHeader = req.headers.get("X-CSRF-Token");
  if (!verifyCsrfToken(csrfCookie, csrfHeader)) {
    return NextResponse.json(
      { error: { code: "FORBIDDEN", message: "Invalid CSRF token" } },
      { status: 403 }
    );
  }

  const updated = await refreshSessionSingleFlight(sid);
  if (!updated) {
    const out = NextResponse.json(
      { error: { code: "UNAUTHENTICATED", message: "Session expired" } },
      { status: 401 }
    );
    out.cookies.delete(SESSION_COOKIE_NAME);
    out.cookies.delete(CSRF_COOKIE_NAME);
    return out;
  }

  return NextResponse.json({ authenticated: true, expires_at: updated.expiresAt });
}
