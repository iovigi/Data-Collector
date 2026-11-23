import { afterEach, describe, expect, it } from "vitest";
import { sanitizeReturnPath } from "@/lib/auth/returnPath";
import { readCsrfToken } from "@/lib/api/client";

// CSRF token creation/verification and the backend path allowlist moved to the Python BFF
// (data_collector/bff) and are covered by tests/integration/test_iis_bff.py.

function clearCookies() {
  for (const c of document.cookie.split("; ")) {
    const name = c.split("=")[0];
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

describe("browser security helpers", () => {
  afterEach(clearCookies);

  it("blocks open redirects in return paths", () => {
    expect(sanitizeReturnPath("/w/123/overview")).toBe("/w/123/overview");
    expect(sanitizeReturnPath("https://evil.example.com")).toBe("/");
    expect(sanitizeReturnPath("//evil.example.com")).toBe("/");
    expect(sanitizeReturnPath("/\\evil.example.com")).toBe("/");
    expect(sanitizeReturnPath(null)).toBe("/");
  });

  it("reads the double-submit CSRF cookie", () => {
    expect(readCsrfToken()).toBe("");
    document.cookie = "dc_csrf=abc.def; path=/";
    expect(readCsrfToken()).toBe("abc.def");
  });
});
