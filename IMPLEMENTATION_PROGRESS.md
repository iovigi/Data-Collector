# Data Collector 2.0 — Implementation Progress

**Branch:** `hardening/final-security-mcp`  
**Audit Baseline SHA:** `e1233770461c894130689febf1d7dc4a428e23ed`  
**Updated:** 2026-11-23

## Final Security & MCP Readiness Checklist
- [x] **SEC-01**: Durable OAuth RSA signing key (>=2048-bit) required in production builtin mode; external JWKS validated
- [x] **SEC-02**: OAuth consent page (`Approve`/`Deny`), signed `HttpOnly` CSRF protection, strict client scope intersection, strict redirect URI validation
- [x] **SEC-03**: Builtin OAuth `grant_type=refresh_token` with atomic rotation, replay-family revocation, and scope non-escalation
- [x] **SEC-04**: DNS-pinned webhook transport (`post_webhook_safe`) closing DNS-rebinding TOCTOU, redirects disabled, IPv4-mapped IPv6 blocked
- [x] **SEC-05**: Code PKCE/client validation before atomic consume; signature-verified `client_id`-bound token revocation
- [x] **MCP-01 / MCP-02 / MCP-03**: Real MCP SDK `ClientSession` over `dc-mcp-stdio` (stderr-only logs) and live `uvicorn` Streamable HTTP with concurrent Alice/Bob isolation
- [x] **OPS-01 / OPS-02**: `docker compose config --quiet` valid; real MongoDB 7 + Redis 7 + `mongodump`/`mongorestore` drill passed
- [ ] **MCP-04 (External)**: Live ChatGPT / Claude remote connector UI smoke test — `BLOCKED_EXTERNAL_VALIDATION` (requires public HTTPS hostname & external OAuth client)
