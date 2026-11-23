import { describe, expect, it } from "vitest";
import { createCsrfToken, sanitizeReturnPath, verifyCsrfToken } from "@/lib/auth/csrf";
import { isAllowedBackendPath } from "@/lib/api/allowlist";

describe("BFF security helpers", () => {
  it("validates double-submit CSRF tokens in constant time", () => {
    const tok = createCsrfToken();
    expect(verifyCsrfToken(tok, tok)).toBe(true);
    expect(verifyCsrfToken(tok, "tampered.sig")).toBe(false);
    expect(verifyCsrfToken(undefined, tok)).toBe(false);
  });

  it("blocks open redirects in return paths", () => {
    expect(sanitizeReturnPath("/w/123/overview")).toBe("/w/123/overview");
    expect(sanitizeReturnPath("https://evil.example.com")).toBe("/");
    expect(sanitizeReturnPath("//evil.example.com")).toBe("/");
  });

  it("enforces strict BFF path allowlist", () => {
    const wid = "507f1f77bcf86cd799439011";
    expect(isAllowedBackendPath("me")).toBe(true);
    expect(isAllowedBackendPath(`workspaces/${wid}/capabilities`)).toBe(true);
    expect(isAllowedBackendPath(`collections/${wid}/records/search`)).toBe(true);
    expect(isAllowedBackendPath("http://evil.example/steal")).toBe(false);
    expect(isAllowedBackendPath("../internal/system")).toBe(false);
    expect(isAllowedBackendPath("internal/admin")).toBe(false);
  });
});
