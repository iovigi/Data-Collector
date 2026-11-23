import crypto from "crypto";

export const SESSION_COOKIE_NAME = "dc_sid";
export const CSRF_COOKIE_NAME = "dc_csrf";

function csrfSecret(): string {
  return process.env.SESSION_SECRET || "dev-only-ephemeral-csrf-secret-32chars!";
}

export function createCsrfToken(): string {
  const nonce = crypto.randomBytes(16).toString("hex");
  const sig = crypto.createHmac("sha256", csrfSecret()).update(nonce).digest("hex");
  return `${nonce}.${sig}`;
}

export function verifyCsrfToken(cookieVal: string | undefined, headerVal: string | null): boolean {
  if (!cookieVal || !headerVal) return false;
  const a = Buffer.from(cookieVal);
  const b = Buffer.from(headerVal);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return false;

  const parts = headerVal.split(".");
  if (parts.length !== 2) return false;
  const [nonce, sig] = parts;
  if (!nonce || !sig) return false;
  const expected = crypto.createHmac("sha256", csrfSecret()).update(nonce).digest("hex");
  const sigBuf = Buffer.from(sig);
  const expBuf = Buffer.from(expected);
  return sigBuf.length === expBuf.length && crypto.timingSafeEqual(sigBuf, expBuf);
}

export function sanitizeReturnPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw) return fallback;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("://")) {
    return fallback;
  }
  return raw;
}
