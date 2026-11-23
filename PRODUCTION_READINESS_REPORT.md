# Data Collector 2.0 — Production Readiness Report

**Branch:** `hardening/production-readiness`  
**Base SHA:** `7bd8d4b663111077d7b1a616a1a916d8883bdaa4`  
**Date:** 2026-11-23  
**Version:** `2.0.0rc1`

## 1. Evidence Summary
| Check | Command | Result | Status |
|---|---|---|---|
| **Test Suite & Coverage** | `pytest tests --cov=data_collector --cov-report=term-missing` | `39 passed`, `82%` overall coverage (`domain` 93–100%, `record_service` 91%, `export_service` 83%, `m11_service` 84%) | **Verified (in-memory mongomock/fakeredis)** |
| **Lint & Format** | `ruff check data_collector tests` | `All checks passed!` | **Verified** |
| **Typecheck** | `mypy data_collector` | `Success: no issues found in 56 source files` | **Verified** |
| **SAST Security Scan** | `bandit -r data_collector -ll` | `No issues identified` (5,658 lines scanned, 0 medium/high) | **Verified** |
| **Dependency Audit** | `pip-audit` | `No known vulnerabilities found` | **Verified** |
| **Container Build** | `docker build -t data-collector:rc2 .` | Exit 0, non-root multi-stage image | **Verified** |
| **OAuth 2.1 PKCE S256 & JWKS** | `test_oauth_21_pkce_full_flow_and_revocation` | Discovery, DCR, PKCE S256, RS256 token, revocation pass | **Verified (builtin test issuer)** |
| **Concurrent MCP Isolation** | `test_concurrent_mcp_actor_context_isolation` | Pure ASGI middleware + `ContextVar` token reset | **Verified** |
| **>10k Streaming Export + Restart** | `test_streaming_export_over_10k_and_restart_recovery` | 10,500 records streamed via `ArtifactStore`, recovered after container rebuild | **Verified** |
| **Live ChatGPT / Claude Remote** | — | Requires public HTTPS domain & external OAuth client registration | **PENDING EXTERNAL VALIDATION** |

## 2. Known Risks & Operator Prerequisites
1. **External IdP / Public HTTPS:** Deploy behind Caddy TLS (`compose.yaml --profile tls`) or cloud ingress; configure `OAUTH_MODE=external` with production `AUTH_ISSUER` and `AUTH_JWKS_URL`.
2. **Real MongoDB + Redis CI:** Added `real-db-integration` job to `.github/workflows/ci.yml`; executes on GitHub Actions push.
3. **Licensing:** Add explicit `LICENSE` file before publishing packages.

## 3. Go / No-Go Recommendation
- **Staging / Controlled Pilot:** **GO** — all P0/P1 hardening workstreams (OAuth 2.1 PKCE, pure ASGI MCP isolation, `allowed_collection_ids` enforcement, `ArtifactStore`, >10,000-record streaming export, OpenAPI 3.1, Caddy TLS, M11 features) are implemented and verified.
- **Public Production Cutover:** **CONDITIONAL** — gated on operator DNS/TLS setup, external IdP registration, live ChatGPT/Claude remote connector smoke tests, and MongoDB backup/restore rehearsal.
