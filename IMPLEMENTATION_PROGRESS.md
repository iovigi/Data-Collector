# Data Collector 2.0 — Implementation Progress

**Branch:** `feat/data-collector-2.0`  
**Baseline SHA:** `e18eaa61a052ed62666183a5b5f85bf334b8f20b`  
**Updated:** 2026-11-23

## Milestone Checklist
- [x] **M0** — Audit and baseline (`current-state.md`, `target-state.md`, `threat-model.md`, `ADR-001`, baseline tests)
- [x] **M1** — Security emergency fixes (removed default admin seeding & weak fallback JWT secret, added `admin bootstrap` CLI, fail-fast config, strict CORS, generic error handler, disabled unsafe legacy `/api/*` by default)
- [x] **M2** — Application service architecture (`data_collector/` layered package, `MongoManager` pooling, `RedisManager`, DI `Container`, repositories)
- [x] **M3** — Multi-tenancy, RBAC, collection/schema registry (workspaces, projects, collections with JSON Schema 2020-12, shared `records` collection with mandatory tenant predicates)
- [x] **M4** — Data API v1 + query DSL (`/api/v1/*`, Safe Query DSL AST compiler, HMAC-bound keyset cursors, optimistic concurrency, soft delete/restore, idempotency)
- [x] **M5** — Authentication hardening and key management (Argon2id + bcrypt migration, short-lived JWTs, refresh rotation + replay revocation, scoped API keys, scrubbed audit trail)
- [x] **M6** — Background jobs + import/export (RQ worker `dc-worker`, JSON/JSONL/CSV import with row errors, async export with CSV formula sanitization + SHA-256)
- [x] **M7** — MCP local stdio / core read tools (`dc-mcp-stdio`, `FastMCP` tools, resources, prompts, response size caps)
- [x] **M8** — MCP remote HTTP + OAuth + write tools (`dc-mcp-http`, Streamable HTTP `/mcp`, RFC 9728/8414 OAuth metadata, origin/auth middleware, two-stage signed delete intent)
- [x] **M9** — Production packaging, CI/CD, telemetry (`Dockerfile`, `compose.yaml`, `.github/workflows/ci.yml`, `/health/live`, `/health/ready`, `/metrics`, runbooks)
- [x] **M10** — Release candidate verification (unit/integration/security/contract test suite, `ruff`, `mypy`, `bandit` verified locally)
- [ ] **M11** — P1 enhancements (deferred post-`v1.0.0` per plan: saved queries, webhooks, schema migration assistant, usage analytics)
