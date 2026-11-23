# Changelog

## 2.0.0rc1 (2026-11-23)
- **Security (M1)**: Removed automatic `admin/admin123` startup seeding and hardcoded fallback JWT secret; added `data-collector admin bootstrap` CLI, fail-fast production config, strict CORS, generic error envelopes with `X-Request-Id`, and disabled unsafe legacy `/api/*` routes by default.
- **Architecture (M2)**: Introduced `data_collector/` layered architecture (`domain`, `services`, `infrastructure`, `api`, `mcp`, `workers`) with centralized `MongoManager` pooling and `RedisManager` rate limiting.
- **Multi-Tenancy & RBAC (M3)**: Added workspaces, projects, collections with JSON Schema 2020-12 registry, memberships (`owner|admin|editor|viewer`), and strict `(workspace_id, project_id, collection_id)` repository isolation.
- **Data API v1 & Query DSL (M4)**: Added `/api/v1/*` endpoints, Safe Query DSL AST compiler (rejecting `$where`, `$regex`, `$expr`, `__proto__`), HMAC-bound keyset cursor pagination, optimistic concurrency (`expected_version`/`If-Match`), soft delete/restore, and `Idempotency-Key` support.
- **Auth Hardening (M5)**: Argon2id password hashing with transparent bcrypt migration, short-lived JWTs, refresh token rotation with replay detection, scoped/revocable API keys, and scrubbed audit trail.
- **Background Jobs (M6)**: Added Redis/RQ worker (`dc-worker`), JSON/JSONL/CSV import with per-row validation reporting, and async export with CSV formula-injection sanitization and SHA-256 checksums.
- **MCP Integration (M7-M8)**: Added official `mcp` Python SDK adapters (`dc-mcp-stdio` and `dc-mcp-http` Streamable HTTP), OAuth 2.1 metadata endpoints, read-only default mode, and two-stage delete confirmation (`dc_prepare_delete_record` -> `dc_delete_record`).
- **Packaging & Telemetry (M9-M10)**: Added multi-stage non-root `Dockerfile`, `compose.yaml`, GitHub Actions CI, `/health/live`, `/health/ready`, `/metrics`, and operational runbooks.
