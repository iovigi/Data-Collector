# Admin Dashboard Architecture & Trust Boundaries

```text
Browser (untrusted)
  |  Same-origin HTTPS + HttpOnly Session Cookie (sid) + CSRF Token
  v
Next.js App Router + BFF (/api/auth/*, /api/backend/*)
  |  Server-side Redis Session Store (access_token + refresh_token)
  |  Allowlisted path forwarding + single-flight refresh lock
  v
Flask REST API (/api/v1/*)
  |  JWT verification + RBAC policy engine + tenant isolation
  v
Application Services -> MongoDB / Redis / ArtifactStore
```

## Key Decisions
1. **Same-origin BFF:** Browser JavaScript never receives `access_token` or `refresh_token`. Tokens live exclusively in the Next.js server-side session store (Redis in production, in-memory fallback in local dev/unit tests).
2. **CSRF Defense:** State-changing requests to `/api/auth/*` and `/api/backend/*` require a double-submit CSRF token (`dc_csrf` cookie + `X-CSRF-Token` header) verified with constant-time comparison.
3. **Allowlisted Proxy:** `/api/backend/[...path]` validates the target path against an explicit regex allowlist of `/api/v1/*` routes and rejects `..`, `http://`, and non-allowlisted paths.
4. **Tenant Cache Isolation:** TanStack Query keys include `workspaceId`. Switching workspaces cancels in-flight queries and clears stale tenant data.
