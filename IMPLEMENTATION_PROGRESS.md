# Data Collector 2.0 — Implementation Progress

**Branch:** `hardening/production-readiness`  
**Base SHA:** `7bd8d4b663111077d7b1a616a1a916d8883bdaa4`  
**Updated:** 2026-11-23

## Hardening Workstreams
- [x] **Workstream A** — OAuth 2.1 (`builtin` RS256/PKCE S256 + `external` JWKS), RFC 9728/8414/7591 metadata, pure ASGI `MCPAuthASGIMiddleware`, concurrent isolation tests
- [x] **Workstream B** — `allowed_collection_ids` enforcement on `CollectionService`, atomic refresh token consumption, SSRF validator (`validate_outbound_url`)
- [x] **Workstream C** — `ArtifactStore` (`LocalVolumeArtifactStore`), shared `artifacts_data` volume in `compose.yaml`, keyset-paginated streaming export (>10,500 records verified across restart)
- [x] **Workstream D** — Complete OpenAPI 3.1.0 generator (`data_collector/api/openapi.py`) with Pydantic component schemas & security schemes
- [x] **Workstream E** — Caddy TLS reverse proxy (`deploy/caddy/Caddyfile`), internal Docker network, real MongoDB+Redis CI stage (`.github/workflows/ci.yml`), deployment & MCP guides
- [x] **Workstream F (M11)** — Saved Queries (REST + MCP), Webhooks (SSRF-safe + HMAC-SHA256), Schema Migration Assistant (preview + apply), Usage Analytics
- [x] **Final Qualification** — `39 passed`, `ruff` 0 errors, `mypy` 0 errors (56 files), `bandit` 0 medium/high, `pip-audit` 0 CVEs, `docker build` green; `PRODUCTION_READINESS_REPORT.md` published
