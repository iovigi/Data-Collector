import { NextRequest, NextResponse } from "next/server";
import {
  CSRF_COOKIE_NAME,
  SESSION_COOKIE_NAME,
  verifyCsrfToken,
} from "@/lib/auth/csrf";
import { backendBaseUrl, deleteSession, getSession } from "@/lib/auth/session";

export async function POST(req: NextRequest): Promise<NextResponse> {
  const sid = req.cookies.get(SESSION_COOKIE_NAME)?.value;
  const csrfCookie = req.cookies.get(CSRF_COOKIE_NAME)?.value;
  const csrfHeader = req.headers.get("X-CSRF-Token");

  if (sid && !verifyCsrfToken(csrfCookie, csrfHeader)) {
    return NextResponse.json(
      { error: { code: "FORBIDDEN", message: "Invalid CSRF token" } },
      { status: 403 }
    );
  }

  if (sid) {
    const sess = await getSession(sid);
    if (sess?.refreshToken) {
      await fetch(`${backendBaseUrl()}/api/v1/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: sess.refreshToken }),
        cache: "no-store",
      }).catch(() => {});
    }
    await deleteSession(sid);
  }

  const out = NextResponse.json({ status: "logged_out" });
  out.cookies.delete(SESSION_COOKIE_NAME);
  out.cookies.delete(CSRF_COOKIE_NAME);
  return out;
}
