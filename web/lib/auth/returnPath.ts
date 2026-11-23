/** Only same-origin absolute paths are allowed as post-login redirect targets. */
export function sanitizeReturnPath(raw: string | null | undefined, fallback = "/"): string {
  if (!raw) return fallback;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.includes("://") || raw.includes("\\")) {
    return fallback;
  }
  return raw;
}
