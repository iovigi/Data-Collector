# Data Collector 2.0 — Production Implementation Blueprint for Gemini Worker

**Repository:** https://github.com/iovigi/Data-Collector  
**Baseline:** `main`, reviewed 2026-11-23  
**Document status:** Single-file end-to-end implementation specification; not evidence of completed work  
**Primary implementer:** Gemini worker model  
**Objective:** Transform the existing Flask/MongoDB data API into a secure, production-ready, multi-tenant data platform with REST API, async ingest/export, and Model Context Protocol (MCP) integrations for OpenAI ChatGPT/OpenAI API and Claude. **Execute the complete scope in one continuous agent assignment, not one milestone per user prompt.**

## 0. Operating instructions for Gemini

You are a senior staff engineer and implementation agent with full repository access. **Execute ALL milestones M0–M11 as one continuous assignment, without pausing for approval after M0, M1, or any other milestone.** Implement in small, verifiable increments rather than rewriting everything at once. Inspect repository and current versions/docs before changing code. Verify all claims by reading files and running tests. Use Git feature branches and small reviewable commits/PRs. Do not claim functionality works until tested. Do not commit secrets or real production data. **Never deploy, delete production data, rotate real credentials, or expose an endpoint publicly without explicit operator authorization.**

Execution behavior (mandatory):
- Read this entire file once, then inspect the repository. This document is the full implementation mandate, **not a prompt template**.
- Start at M0 and automatically advance through M1, M2, M3, M4, M5, M6, M7, M8, M9, M10 and M11. Preserve dependencies and do not skip acceptance gates.
- Do not ask the user to write a new prompt, choose the next milestone, or approve routine technical decisions. Use the specified defaults and document decisions.
- A milestone is an internal checkpoint, not a reason to terminate the assignment. Provide the **final consolidated result after all feasible work is executed**.
- If context/time/tool limits interrupt execution, first write `IMPLEMENTATION_PROGRESS.md` to the repository with completed milestones, branch/SHA, evidence, exact next command, and blockers, then resume automatically if the environment allows. A follow-up model can resume without re-planning. Never pretend to work in the background.
- Do not claim all features are complete unless their acceptance gates have actually passed. Clearly identify blockers requiring operator access, especially live client OAuth and production deployment.
- Production credentials, paid external resources, DNS changes, public exposure, destructive migrations and release deployment are **explicit operator-approval boundaries**; complete everything else locally without waiting.

At the beginning of each milestone:
1. Record current SHA, dependency versions, file tree, test baseline, and security constraints.
2. List exact files to modify, migrations required, and potential backwards-compatibility breaks.
3. Implement vertical end-to-end functionality; add tests alongside features.
4. Run `ruff check`, `ruff format --check`, `mypy` (with justified targeted exclusions), `pytest`, integration tests, dependency and secret scans, and build the container.
5. Provide changes summary, commands executed, actual results, limitations, and next-step recommendation.
6. Preserve `/api/*` legacy endpoints during migration behind a flag and deprecation headers; never silently change their semantics. If a legacy endpoint is unsafe, fail closed until secured.
7. Do not conflate user identity, workspace/tenant identity, service account identity, and MCP client identity.
8. For any unspecified choice use the defaults in this document; log material deviations in ADR files.

**Definition of done for each milestone:** code merged only after acceptance tests, documentation, and rollback strategy are present. No mocks or placeholder success responses in production paths. Every new endpoint has authentication, authorization, input schema, rate limits, and failure tests.

## 1. Verified baseline (repository review)

### Existing files
- `app.py`: Flask factory, permissive `CORS(app)`, Flask-RESTX, JWT config with hardcoded fallback secret, eagerly calls `seed_users()` on app import.
- `api/database.py`: creates a new MongoClient per `get_db()` call.
- `api/utils/db.py`: separately creates a global MongoClient during import.
- `api/auth/decorators.py`: accepts `X-System-Auth` on simple equality; JWT fallback; no substantive RBAC enforcement.
- `api/utils/seeder.py`: defaults to `admin/admin123`, seeded on application startup.
- `api/routes/auth.py`: login endpoint; no rate limiting, token lifecycle management, or uniform login failure.
- `api/routes/query.py`: user-controlled MongoDB query operators, collection and sort fields; offset pagination; only `_id` ObjectId conversion.
- `api/routes/insert.py`, `update.py`, `delete.py`: direct DB operations with collection names supplied by clients, broad exception disclosure.
- `api/routes/index.py`: arbitrary index creation for authenticated callers.
- `api/routes/base.py`, `api/models/*`: Flask-RESTX route/model infrastructure.
- `README.md`, `setup.py`, `requirements.txt`, `.gitignore`.

### Current endpoints
`POST /api/insert`, `POST /api/bulk_insert`, `GET /api/query`, `PUT /api/update`, `PUT /api/bulk_update`, `DELETE /api/delete`, `POST /api/create_index`, `POST /api/login`.

### Observations
There are no committed automated tests, Docker artifacts, CI workflows, or explicit MCP module in the reviewed tree. A GitHub license file was not present in the reviewed repository; **do not assume it is open source under an OSI-approved license simply because it is public**. Decide licensing before publishing derivative packages.

### Critical remediation tickets
SEC-001 fail startup when signing secret missing/weak; SEC-002 remove default admin seeding and introduce explicit bootstrap; SEC-003 prohibit anonymous/public system-key bypass; SEC-004 enforce tenant and collection authorization at service layer; SEC-005 prohibit raw MongoDB operators and unsupported field/path names; SEC-006 enforce strict CORS origins; SEC-007 generic external errors plus request IDs; SEC-008 centralized MongoDB client lifecycle; SEC-009 login throttling and audit trail; SEC-010 safe MCP write/delete approval and authorization.

## 2. Target product, scope, and non-goals

### Product promise
Data Collector is a general purpose collection/workspace data platform. Humans, applications, automation workers and AI assistants can define data collections, ingest records, query records, update records with permission, export data, and track operations. MCP clients see strongly typed, policy-scoped tools, not raw database access.

### P0 (production v1)
- Multi-tenant workspaces with projects, collections, ownership, memberships, RBAC and API keys.
- JSON Schema validation, typed records, metadata, indexes, full CRUD and bulk writes.
- Safe filtering/search, stable cursor pagination, sorting, projection, counts, and export.
- Idempotency, optimistic concurrency, soft delete, retention policy, change audit.
- Async import/export and job status via Redis + worker.
- REST API v1 with OpenAPI; standard error envelope.
- MCP server with remote HTTPS Streamable HTTP and local stdio adapters, discovery, read and guarded write tools.
- Health/readiness, structured logs, metrics, traces, rate limits, backups, deployment manifests.
- Developer docs, tests, Docker Compose, CI, release/runbook.

### P1
- Collection templates, saved queries, query presets, webhooks, batch upsert, data quality reports, deduplication, schema-version upgrades, background TTL cleanup, detailed usage dashboard.
- Optional CSV, JSONL and NDJSON ingestion; optional scheduled imports from approved sources.

### P2 (explicitly out of first production release)
- General-purpose arbitrary web scraping/browser automation, unrestricted MongoDB aggregations, LLM-generated raw DB queries, user-supplied Python execution, arbitrary SQL gateway, billing, public marketplace, row-level sharing to unauthenticated parties, untrusted workflow scripts, vector search until a concrete use case arises.

## 3. Recommended architecture

**Decision: keep Flask for the REST HTTP surface for initial delivery** to minimize migration risk. Use Python 3.12+ (pin supported minor version after compatibility testing), Flask maintained compatible versions, PyMongo, Pydantic v2 for boundary DTOs, `jsonschema` for dynamic record schemas, Redis with RQ (or Celery with ADR if features demand it), and official Python MCP SDK in a separate adapter/service process. Introduce a shared application/service domain package. Avoid requiring FastAPI migration solely for MCP.

```text
ChatGPT / OpenAI Responses API   Claude / Claude Desktop   CLI/SDK clients
           |                           |                     |
           +---------- HTTPS /mcp ----+                     |
                         |                        local stdio MCP
                    MCP Gateway                         |
                         +----------+------------------+
                                    |
                           Auth + policy engine
                                    |
REST /api/v1 ---> Flask API ---> Application Services <--- Worker
                                    |
                       Repositories + validation
                           |                |
                    MongoDB          Redis queue/cache
                           |
                   Backups + monitoring
```

**Hard boundary:** MCP tools and HTTP routes call the exact same services; **no direct MongoDB calls inside route or MCP functions**. Maintain separate internal metadata collections and user-defined data collections. No code path may derive a physical database collection name from an unvalidated user string.

### Proposed repository layout
```text
data_collector/
  __init__.py
  config.py
  app.py                       # Flask application factory
  api/
    v1/
      auth.py
      workspaces.py
      projects.py
      collections.py
      records.py
      queries.py
      imports.py
      exports.py
      jobs.py
      keys.py
      audit.py
    errors.py
    middleware.py
    schemas.py
  domain/
    identities.py
    policies.py
    entities.py
    exceptions.py
  services/
    auth_service.py
    collection_service.py
    record_service.py
    query_service.py
    import_service.py
    export_service.py
    audit_service.py
  infrastructure/
    mongo.py
    redis.py
    repositories/
    logging.py
    metrics.py
    crypto.py
  mcp/
    tools.py
    resources.py
    prompts.py
    server_http.py
    server_stdio.py
    auth.py
    contracts.py
  workers/
    jobs.py
    main.py
  migrations/
  cli.py
tests/
  unit/
  integration/
  security/
  contract/
  e2e/
docs/
  architecture/
  api/
  mcp/
  operations/
  adr/
.github/workflows/
deploy/
  docker/
  k8s/                      # optional, only if actual target is Kubernetes
pyproject.toml
Dockerfile
compose.yaml
compose.dev.yaml
.env.example
README.md
CHANGELOG.md
SECURITY.md
LICENSE                       # select explicitly with owner
```

Keep legacy `app.py` import path and old route modules as compatibility shims initially. No silent one-shot code rewrite.

## 4. Identity, tenancy and permissions

### Metadata model
- `users`: `_id`, email (normalized unique), password_hash (only if local auth), status, MFA state (optional), created_at, updated_at.
- `workspaces`: `_id`, slug, name, owner_id, limits, status, created_at.
- `memberships`: `_id`, workspace_id, principal_id, role (`owner|admin|editor|viewer`), created_at; unique workspace/principal.
- `projects`: `_id`, workspace_id, slug, name, status.
- `collections`: `_id`, workspace_id, project_id, slug, schema_json, schema_version, index_definitions, retention_settings, status.
- `api_keys`: `_id`, workspace_id, principal_id, prefix, key_hash, scopes, expires_at, last_used_at, revoked_at; plaintext shown only once.
- `oauth_clients`/`oauth_grants` (if owned authorization service is implemented), access token metadata where necessary, revoke controls.
- `jobs`: `_id`, workspace_id, initiator_id, type, state, progress, checkpoint, output_ref, error_summary, created_at, started_at, finished_at.
- `audit_events`: `_id`, tenant, actor, action, target, decision, request_id, timestamp, metadata; never store secrets or full sensitive payloads.
- `idempotency_keys`: scope, method, request path, key hash, request digest, response reference, expiration.

### Record schema
```json
{
  "_id":"ObjectId",
  "workspace_id":"ObjectId",
  "project_id":"ObjectId",
  "collection_id":"ObjectId",
  "data":{"arbitrary":"JSON Schema validated user data"},
  "version":1,
  "created_at":"UTC datetime",
  "updated_at":"UTC datetime",
  "created_by":"principal_id",
  "deleted_at":null,
  "source":{"type":"api|mcp|import","request_id":"..."}
}
```

### Physical storage choice
Default production design: one shared `records` MongoDB collection with mandatory indexed `workspace_id + project_id + collection_id` predicates. The repository layer must always inject all three scope filters and tests must prove no cross-tenant access even if user supplies confusing input. This model simplifies tenant controls and prevents arbitrary collection names. If scale requires per-collection physical isolation later, introduce a storage mapper under an ADR rather than rebuilding APIs.

### RBAC
- Owner: manage workspace, keys, members, collections and records.
- Admin: manage collections and records; cannot transfer ownership; sensitive key administration per policy.
- Editor: create/read/update records, bulk import, limited indexes via managed schema/index workflow.
- Viewer: read and export only if permitted.
- Service account: explicit collection-specific capabilities and expiration.
- MCP client: **inherits the authenticated human/service principal's permissions**, and may be further restricted by OAuth scopes. No global admin system key.

Explicit scopes: `workspace:read`, `collection:read`, `collection:manage`, `records:read`, `records:write`, `records:delete`, `jobs:read`, `jobs:create`, `export:read`, `keys:manage`, `audit:read`.

Enforcement order: authenticate -> resolve workspace/project -> verify membership and scope -> collection policy -> validate arguments -> execute under repository tenant filters -> append audit event. Return 404 instead of exposing existence of inaccessible resources where appropriate.

## 5. Data API contracts

### Versioning & error format
All new endpoints `/api/v1/...` with `application/json`. UUID-style request ID (server-generated), `created_at` ISO 8601 UTC, RFC 3339, Mongo ObjectIDs as strings outside persistence layer. Typed Pydantic request/response models and generated OpenAPI file validated by contract tests.

Error:
```json
{"error":{"code":"VALIDATION_ERROR","message":"Invalid filter","details":[{"path":"filter.field","reason":"not allowed"}],"request_id":"req_..."}}
```

Map errors to 400, 401, 403, 404, 409, 413, 422, 429, 500, 503. Never return raw traceback/database exceptions to users. Support `Retry-After` for 429 and 503 where applicable.

### Core endpoints
```
POST   /api/v1/auth/login                    # only if local auth configured
POST   /api/v1/auth/refresh                  # rotation/replay protection
POST   /api/v1/auth/logout                   # revocation
GET    /api/v1/me
GET    /api/v1/workspaces
POST   /api/v1/workspaces
GET    /api/v1/workspaces/{wid}
POST   /api/v1/workspaces/{wid}/projects
GET    /api/v1/workspaces/{wid}/projects
POST   /api/v1/projects/{pid}/collections
GET    /api/v1/projects/{pid}/collections
GET    /api/v1/collections/{cid}
PATCH  /api/v1/collections/{cid}
POST   /api/v1/collections/{cid}/records
POST   /api/v1/collections/{cid}/records/batch
GET    /api/v1/collections/{cid}/records
POST   /api/v1/collections/{cid}/records/search
GET    /api/v1/collections/{cid}/records/{rid}
PATCH  /api/v1/collections/{cid}/records/{rid}
DELETE /api/v1/collections/{cid}/records/{rid}
POST   /api/v1/collections/{cid}/records/{rid}/restore
POST   /api/v1/collections/{cid}/imports
POST   /api/v1/collections/{cid}/exports
GET    /api/v1/jobs/{jid}
GET    /api/v1/jobs/{jid}/result
POST   /api/v1/jobs/{jid}/cancel
GET    /api/v1/audit
POST   /api/v1/keys
GET    /api/v1/keys
POST   /api/v1/keys/{kid}/revoke
GET    /health/live
GET    /health/ready
GET    /metrics                            # internal-only, authenticated/network restricted
```

### Mutation semantics
- Insert: validate against collection JSON Schema, add metadata, return `201` with id, version.
- Update: reject changing `_id`, tenant metadata, `created_at`, `created_by`, and Mongo `$`/dot keys unless explicitly modeled; allow JSON Merge Patch only for `data`, version precondition (`If-Match` or expected_version) mandatory for modifications.
- Delete: default soft-delete plus retention; hard purge in separate privileged admin operation with explicit confirmation and test coverage; restore within retention window.
- Batch: request size/count caps, per-item outcome; all-or-nothing only if MongoDB transactions properly configured; otherwise document partial success and retries. Never claim atomicity without testing replica-set/transactions.
- Idempotency: `Idempotency-Key` supported on create/batch/import; same key+same digest returns original response, same key+different payload 409.
- Pagination: stable cursor bound to collection, filter, sort and tenant; use `(sort_key,_id)` tie-break, avoid exposing cross-tenant cursors; cap page size 100 default 25. Document snapshot consistency limitations.
- Serialization: ObjectId, datetime, Decimal128, binary types handled by deterministic serialization or explicitly rejected by policy; never leak Python representations.

### Safe search DSL (no arbitrary MongoDB)
```json
{
  "filter":{"and":[
    {"field":"status","op":"eq","value":"active"},
    {"field":"score","op":"gte","value":10}
  ]},
  "sort":[{"field":"created_at","direction":"desc"}],
  "fields":["name","status","score"],
  "limit":25,
  "cursor":null
}
```
Allowed operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in` (bounded length), `exists`, `contains` (bounded text; only indexed/searchable fields if necessary). Depth <= 4, branches <= 20, filter serialized length <= 16 KB, page size <= 100, max query duration <= 5 seconds configurable. Disallow `$where`, `$expr`, `$function`, `$lookup`, JavaScript, user-supplied raw Mongo objects, uncontrolled regex and aggregation pipelines. Allow sort/filter/projection only on configured schema fields or safe built-in metadata. Reject `__proto__`, `$` and reserved/dangerous field paths; enforce schema allowlists. Add query complexity limits, request size limits, maxTimeMS and indexes.

### Limits defaults (configurable; document and test)
- JSON request body: 1 MiB; batch records: max 500 and <= 5 MiB separate endpoint (with streaming/buffering safeguards).
- Export asynchronous if > 1000 records or > 5 MiB; maximum export scope configured by deployment.
- Default retention 30 days for soft-deleted records, configurable.
- Default per API key 60 requests/minute; per workspace 600/minute; separate weighted budgets for export/import and MCP tools. Distributed Redis-backed limiter; fail-closed for mutations if enforcement unavailable.
- Limit response sizes and truncation explicitly, including MCP outputs.

## 6. Authentication and authorization engineering

1. Replace unsafe defaults. Startup fails in production without secure JWT/OAuth config, DB URI, required allowed origins and encryption secrets. Separate `APP_ENV=dev|test|prod`, never infer security from `DEBUG` alone.
2. Bootstrap admin only via interactive/explicit CLI `data-collector admin bootstrap` using required externally supplied credentials; never seed on import/startup. If account exists, do not silently reset password.
3. Password hashing: Argon2id for new passwords, password verification migration from bcrypt if needed. Strong password and throttling rules. No user enumeration on login.
4. Use unique user identifiers in JWT subject, short access-token life, refresh rotation and revocation. Explicit issuer, audience, expiry and key ID validation.
5. For service-to-service API keys use high entropy random value, prefix ID, hash at rest, scope, expiry, rotation and last-used; constant-time hash verification where appropriate.
6. CORS: configured allowed origins, allowed headers/methods, credential policy; not `CORS(app)` globally.
7. Authorization: all routes and MCP tools use shared policy functions. Deny-by-default. Authorization checks cannot be bypassed by internal module calls.
8. Exclude sensitive headers, tokens, passwords, PII fields and full raw payloads from logs, traces, errors, audit records.
9. Scrub user data from unexpected downstream tool/model output; do not include credentials in MCP resources or prompts.
10. Define abuse protection and account/key revocation, incident response and logs retention.

## 7. MCP integration (major deliverable)

### Compatibility target
Use the maintained official Python MCP SDK with pinned compatible versions. Implement `stdio` for local Claude Desktop/Claude Code and local developer agents, plus **remote HTTP MCP over HTTPS** for ChatGPT, Claude remote custom connectors, and OpenAI Responses API. Confirm exact SDK implementation and published protocol versions during milestone execution; protocol compatibility must be proven against clients. Treat Streamable HTTP changes (including the 2026-07-28 revision) explicitly; don't assume obsolete session/SSE GET behavior. Do not invent OAuth semantics; follow the current MCP authorization specification. OpenAI/Claude UI availability depends on plan and workspace policies.

### MCP public endpoint & security
- `POST https://YOUR_DOMAIN/mcp` with validated MCP content types and JSON-RPC shape; additional supported methods only if protocol version requires them.
- OAuth 2.1 Authorization Code + PKCE for interactive remote clients; published authorization-server metadata and protected-resource metadata; choose a maintained identity provider rather than hand-roll a full authorization server unless absolutely necessary.
- Access tokens bound to correct resource (`aud`), issuer, expiry, scopes, user/workspace grants and revocation policy. Prevent confused deputy and token forwarding. Restrict CORS and verify Origin as required by MCP security guidance; protect localhost stdio from unwanted network exposure.
- Per-tool permission checks, explicit collection allowlisting and cross-tenant isolation. Default MCP mode `read-only`, write tools enabled only by user's granted scopes and policy.
- No credentials in tool descriptions. Validate all tool input and output schemas. Tool responses are data, never trusted instructions; defend against prompt injection in record contents.
- Log request ID, tool name, actor, collection, duration, result counts, and authorization decision without recording payloads/secrets.
- OAuth callback, refresh, revocation and metadata discovery tested separately for ChatGPT and Claude.
- Important: ChatGPT's workspace plugin tool snapshots may need republishing after tool/schema changes. Prefer stable names and backwards-compatible parameter changes.

### MCP tools — P0
| Name | Permission | Inputs | Result |
|---|---|---|---|
| `dc_list_workspaces` | workspace:read | limit,cursor | scoped workspaces |
| `dc_list_projects` | workspace:read | workspace_id | scoped projects |
| `dc_list_collections` | collection:read | project_id | metadata, schemas summary |
| `dc_describe_collection` | collection:read | collection_id | fields, schema, searchable filters |
| `dc_get_record` | records:read | collection_id,record_id | record, version |
| `dc_search_records` | records:read | collection_id,filter,sort,fields,limit,cursor | bounded page |
| `dc_count_records` | records:read | collection_id,filter | count (budgeted) |
| `dc_create_record` | records:write | collection_id,data,idempotency_key | id, version |
| `dc_update_record` | records:write | collection_id,record_id,patch,expected_version | updated version |
| `dc_delete_record` | records:delete | collection_id,record_id,expected_version,confirmation_token | soft-deletion receipt |
| `dc_create_import_job` | jobs:create | collection_id,approved_source_ref,format,idempotency_key | job_id |
| `dc_create_export_job` | export:read | collection_id,filter,format | job_id |
| `dc_get_job` | jobs:read | job_id | status/progress |

**Do not expose raw `run_mongodb_query`, `execute_python`, arbitrary shell, arbitrary URL fetch, bypass-auth, or broad administrative maintenance tools.**

### MCP tools — P1
`dc_batch_upsert`, `dc_validate_record`, `dc_list_saved_queries`, `dc_run_saved_query`, `dc_get_schema`, `dc_get_data_quality_report`, `dc_list_audit_events` (privileged), `dc_get_export_link` (short-lived, authorized).

### MCP resources
- `dc://workspaces/{wid}/projects/{pid}/collections` — collection catalog.
- `dc://collections/{cid}/schema` — bounded JSON schema + descriptions.
- `dc://collections/{cid}/records/{rid}` — one authorized resource only.
No unbounded resource enumeration or large payloads.

### MCP prompts
- `explore_collection` (read-only field discovery and example query),
- `summarize_records` (read-only query and summary; always cite retrieved record IDs),
- `prepare_import_mapping` (create a suggested mapping; no mutation).
Prompts never grant privileges; all resulting tool calls independently checked.

### Tool behavior contract
- Descriptive names and stable JSON schemas; always explicit `collection_id`, no implicit “current workspace” for destructive mutations.
- Read tools must enforce result <= 25 records by default, max 100, response payload maximum 256 KiB (configurable), proper pagination and truncation flag.
- Write tools return operation receipt, not a dump of the mutated collection. Idempotency for create/import and expected_version for update/delete.
- Delete requires two-stage confirmation: short-lived server-generated intent token bound to actor, tenant, collection, record, operation, expected version and expiration. Provide `dc_prepare_delete_record` read/preflight tool; `dc_delete_record` consumes token. Never treat a boolean parameter as proof of user consent. The host may also require confirmation; server-side controls remain mandatory.
- Structured errors: `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `INVALID_ARGUMENT`, `CONFLICT`, `RATE_LIMITED`, `TEMPORARY_UNAVAILABLE` mapped to correct MCP tool result/error semantics.
- Every tool tested for valid request, invalid schema, missing scopes, cross-tenant ID, oversized response, expired token, duplicate request, and failed DB.

### Required demo journeys
1. ChatGPT: “List collections available in workspace X” -> only permitted metadata.
2. ChatGPT: “Find 10 active leads and summarize by category” -> safe filter, no raw query.
3. Claude: “Describe customers schema, then insert one validated record” -> permission-bound creation.
4. Both clients: attempt delete without confirmed intent -> blocked; confirmed specific soft delete -> succeeds.
5. Both clients: request unauthorized collection -> denied, no information leakage.
6. Simultaneous users from two workspaces -> strict isolation.
7. Repeated import request with idempotency key -> one logical job.

## 8. Import, export and background jobs

- Redis queue with worker process (`rq` recommended first), worker max concurrency, retry with exponential backoff, dead-letter handling, visibility/timeouts, cancellation checkpoints.
- Supported imports P0: JSON, JSONL/NDJSON and CSV; file size cap 50 MiB configurable. Validate file MIME by content and extension, sanitize CSV injection on export, reject archives initially unless explicit safe unpacking.
- Upload via authenticated POST with streaming to bounded temp/object storage; never let MCP pass arbitrary filesystem paths or URLs. For external sources, register a safe approved source object with SSRF checks and permission first (P1).
- Import mapping: schema fields mapping, duplicate policy (`reject|skip|upsert` with declared key), dry-run validation, per-row errors, progress counters, final report.
- Export: permission-scoped query, streaming output to private object storage, expiring download link scoped to initiator, checksum and audit event; configurable redaction for sensitive fields.
- Jobs: deterministic transitions queued->running->completed|failed|cancelled, ownership checks, requeue/recovery semantics, idempotent retries. MongoDB job metadata is authoritative; Redis is transport only.
- Webhooks P1: HTTPS only, signature, retry & replay windows, allowlist, SSRF defense, clear event types, no secret leakage.

## 9. Indexing and performance

- Internal compound indexes: `records(workspace_id, project_id, collection_id, deleted_at, _id)` plus commonly sorted keys and bounded index templates. Membership unique pair, collection unique `(project_id, slug)`, API key prefix unique, jobs tenant/state/created_at.
- User-defined indexes created only through validated administrative schema/index management with an allowlist and safeguards against index explosion.
- Avoid synchronous `count_documents` for every page by default; return optional total/count separately or document cost.
- Every query includes maxTimeMS, limit, explicit sort; expensive queries get rejection/async jobs.
- Mongo connection reuse: one client per process via factory, proper connection pool, timeouts, ping on readiness, close on shutdown; tune settings through configuration.
- No cache of private results without tenant+auth+query scope; invalidate on mutation.
- Test realistic sample datasets of 10K, 100K and 1M rows; compare p50/p95 and memory under reproducible local benchmark settings.

## 10. Config & deployment

### Environment configuration contract
```
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
MONGODB_URI=mongodb://mongo:27017/?replicaSet=rs0
MONGODB_DB=data_collector
REDIS_URL=redis://redis:6379/0
AUTH_ISSUER=https://auth.example.com/
AUTH_AUDIENCE=data-collector-api
MCP_PUBLIC_URL=https://collector.example.com/mcp
ALLOWED_ORIGINS=https://app.example.com
LOG_LEVEL=INFO
RATE_LIMIT_READ_PER_MINUTE=60
RATE_LIMIT_WRITE_PER_MINUTE=30
MAX_QUERY_PAGE_SIZE=100
# Only provide secure secrets via secret manager; never commit values.
```

### Delivery artifacts
- Multi-stage non-root Dockerfile, health check, constrained resources, minimal base, no secrets in layers.
- Docker Compose development stack: API, MCP server, worker, MongoDB (test replica set where transactions are tested), Redis, optional metrics collector. No default exposed DB/Redis ports in production manifest.
- Production deployment reference: reverse proxy ingress HTTPS, auth provider, private database/network, object storage, secrets store, MongoDB backup and restore, observability.
- Separate processes `dc-api`, `dc-mcp-http`, `dc-worker`; stdio entrypoint `dc-mcp-stdio`.
- Configuration validated on boot (no weak secrets in production), config docs, health endpoints and graceful SIGTERM.
- Database migrations executed explicitly by release process with dry-run and recovery; no schema-destructive startup mutation.
- TLS, HSTS, secure cookies where applicable, body and request timeouts, network egress controls.

### Observability
- JSON logs with request_id and trace_id, no sensitive payloads.
- OpenTelemetry HTTP/MCP/worker spans with policy-safe attributes.
- Metrics: request count/latency/error, authentication failure, rate-limit hit, queue age, job failure, Mongo pool usage, MCP tool calls/errors/output sizes, tenant-scoped usage without sensitive labels.
- Alerts: elevated 5xx, readiness failure, queue backlog, high DB latency, auth abuse, failed backups.
- SLO targets for v1 **proposed and subject to load validation:** >=99.9% availability after initial stabilization, p95 read API < 500ms for indexed small pages, p95 MCP read < 1.5s excluding model overhead; restore drills and documented RPO/RTO set by operator.

## 11. Testing and security gates

### Automated coverage
- Unit: Pydantic DTOs, schema validator, filter AST compiler, RBAC, idempotency, cursor parser, error mapper, serializers.
- Integration: MongoDB + Redis testcontainers/compose, replica set transaction cases, CRUD, uniqueness, indexes, worker retry, restore.
- Security: unauthorized read/write/delete, expired key/token, cross-tenant references, operator injection (`$where`, `$ne`, `$regex`), oversized payload, XSS strings, CSV formula injection, brute force, CORS, CSRF if cookie auth, SSRF for optional connectors, OAuth redirect/audience checks, prompt injection in stored records.
- Contract: OpenAPI validation, JSON response shape, backwards-compat legacy tests.
- MCP protocol: tool list discovery, schema compatibility, HTTP transport, stdio, auth refresh/expiry, error handling; official inspector where appropriate; actual ChatGPT and Claude smoke scripts/checklist.
- E2E: operator bootstraps tenant -> creates collection/schema -> writes/queries via REST -> reads via MCP -> updates via Claude -> exports job -> audits event.
- Load: k6/Locust workload with reproducible fixtures, reasonable concurrency; record real observed numbers rather than invent benchmark claims.

### Minimum gates
- All changed code lint/format pass, typecheck materially enforced, all unit/integration/security tests green.
- >= 85% coverage on new domain/service modules; 100% test coverage of critical authorization policy branches and deliberate negative cases.
- Dependency audit / container scan / secret scan no unresolved critical/high production findings unless documented accepted risk approved by owner.
- No default credentials, no plaintext secrets in repo, no unauthenticated data endpoints.
- MCP remote demo on compatible OpenAI and Claude clients; local stdio demo.
- Backup restored successfully in rehearsal before production release.

## 12. Milestone backlog — execution order

### M0 — Audit and baseline (no feature refactor)
**Tasks:** confirm exact SHA/tree, run current app in isolated local env, identify imports that connect on startup, build endpoint behavior matrix, dependency and license inventory, make a risk register, create baseline tests before modifying semantics, write `docs/architecture/current-state.md` and ADR-001. Confirm target Python/Mongo/MCP SDK versions. **Deliverable:** audit report + minimal reproducible dev environment. **Accept:** repo can be installed/tested from README; risks linked to tickets; no deployment. **Rollback:** docs-only changes.

### M1 — Security emergency fixes
**Tasks:** eliminate fallback admin password and JWT secret; explicit bootstrap command; fail-fast config; secure CORS; generic error handler; secure system token deprecation/rotation; login rate limit; replace user-defined unrestricted operator behavior with allowlisted safe filtering or disable legacy unsafe functions until migrated; prohibit arbitrary index management; add regression tests. Keep legacy path compatibility only when safe. **Accept:** default credentials cannot authenticate; no permission bypass; malicious filter denied; no secrets in errors. **Rollback:** config-controlled route cutover, no migration data loss.

### M2 — Application service architecture
**Tasks:** introduce config, dependency factory, centralized Mongo connection, domain exceptions, logging/request ID, repository protocols, collection policy, DTO validation. Move CRUD behind `RecordService`, routes become thin adapters. **Accept:** API and service tests pass; only repository talks to Mongo; no DB calls from MCP/routes; connection pooling verified. **Rollback:** toggle legacy adapters only if secured.

### M3 — Multi-tenancy, RBAC, collection/schema registry
**Tasks:** workspace/project/collection metadata, membership and service-account model, migration/seed plan for existing records, JSON Schema registry, per-collection scopes and permissions, secure tenant-bound indexes. Define migration path for legacy collections: inventory -> export backup -> map to workspace/project -> transform -> reconciliation -> cutover; no silent data rehoming. **Accept:** two-workspace isolation tested for all operations; schema validation and unauthorized schema update denied. **Rollback:** backup and compatible read path, no destructive DB migration.

### M4 — Data API v1 + query DSL
**Tasks:** CRUD/search, cursor pagination, version conflict semantics, soft delete/restore, idempotency, batch, OpenAPI and typed serialization. Define query AST allowlist; bounds/timeouts; legacy API migration shims. **Accept:** stable pagination, injection tests, update conflicts and restore behavior green; no unrestricted Mongo expressions. **Rollback:** feature flags + schema compatible writes.

### M5 — Authentication hardening and key management
**Tasks:** scoped API keys, rotation/revocation, short JWT sessions, refresh logic (if local login used), dedicated auth service policy, audit events and rate limits. Choose OIDC provider and document key discovery/rotation. **Accept:** revoked keys fail immediately within documented cache TTL; scopes enforced; login abuse blocked; audit lacks PII/secrets. **Rollback:** revoke new clients and keep secured local auth.

### M6 — Background jobs + import/export
**Tasks:** Redis queues, worker entrypoints, job lifecycle, JSON/CSV/JSONL import and validation reports, async filtered export and secure download. **Accept:** malformed input produces row errors not worker crash; re-run is idempotent; cancellation and failed job recovery tested. **Rollback:** disable job submission, safely drain queue.

### M7 — MCP local stdio / core read tools
**Tasks:** official MCP SDK, local server adapter, tool schemas for discovery/description/read/search/count; resources and prompt templates; actor context resolution from local least-privileged API key in environment/secret store. **Accept:** MCP inspector and Claude Desktop/Claude Code local smoke tests, no direct DB access, denied collection invisible. **Rollback:** remove local config/disable entrypoint.

### M8 — MCP remote HTTP + OAuth + write tools
**Tasks:** HTTPS Streamable HTTP, OAuth/OIDC resource metadata, resource audience/scopes, ChatGPT/Claude compatibility matrix, server-side delete intent, write tools, per-tool throttling, tool output cap, tool snapshot/version policy. **Accept:** both remote clients successfully connect and perform read/write with appropriate approval; forbidden action denied; revocation and token refresh tested; record prompt injection cannot escalate tool privileges. **Rollback:** revoke OAuth client grants + disable `/mcp` ingress while REST continues.

### M9 — Production packaging, CI/CD, telemetry
**Tasks:** secure Docker and compose, environment example, GitHub Actions lint/types/tests/scans/build, release tags and changelog, health/ready, metrics/traces/alerts, secrets docs, backup/restore, runbooks, security policy, dependency update policy. **Accept:** green pipeline on clean checkout; deploy staging from immutable tag; recover from backup in test. **Rollback:** redeploy previous image and restore compatible metadata if required.

### M10 — Release candidate / end-to-end certification
**Tasks:** threat model review, test matrix, performance and chaos drills, migration rehearsal, SLO validation, authorized staging remote connector tests in ChatGPT and Claude, documentation and release checklist, versioned release `v1.0.0` only when gates pass. **Accept:** all P0 conditions demonstrated with actual logs/results; owner signs off before production. **Rollback:** documented tested cutback sequence.

### M11 — P1 enhancements (only after stable release)
**Tasks:** saved queries, configurable webhooks, schema migration assistant, data quality, deduplication, batch upsert, usage analytics and scheduled imports from approved sources. **Accept:** per-feature ADR/tests and no expansion of tool permissions by default.

## 13. Detailed issue decomposition

Each issue includes *implementation + tests + docs*, has an owner and PR. Suggested issue IDs:
- `SEC-001` Secret validation and bootstrap removal (M1)
- `SEC-002` Auth and policy middleware, deny-by-default (M1/M2)
- `SEC-003` Safe query DSL compiler and injection tests (M1/M4)
- `ARCH-001` Config and unified DB lifecycle (M2)
- `ARCH-002` Service and repository interfaces (M2)
- `TEN-001` Workspace and project registry (M3)
- `TEN-002` Membership, roles, scoped keys (M3/M5)
- `TEN-003` Collection schemas, indexes, migrations (M3)
- `API-001` Record CRUD, versioning, soft delete (M4)
- `API-002` Search, cursors, projection (M4)
- `API-003` Batch, idempotency and quotas (M4)
- `AUTH-001` OAuth provider integration decision and implementation (M5/M8)
- `OPS-001` Worker queue, retry and cancellation (M6)
- `OPS-002` CSV/JSON/JSONL import (M6)
- `OPS-003` Export and signed downloads (M6)
- `MCP-001` SDK adapter, stdio read tools (M7)
- `MCP-002` Resources, prompts, tool schema/version tests (M7)
- `MCP-003` Remote HTTP and OAuth discovery (M8)
- `MCP-004` Write/delete intent and cross-client tests (M8)
- `REL-001` Docker/CI/scan/release (M9)
- `REL-002` Observability and health (M9)
- `REL-003` Runbooks, backups, restore drill (M9/M10)
- `REL-004` E2E acceptance and release report (M10)

Use dependencies: M0 -> M1 -> M2 -> M3 -> M4; M5 and M6 after M3/M4; M7 after M4/M5; M8 after M5/M7; M9 can begin after M2 but release blocked by M8; M10 after all P0.

## 14. Key architectural decisions and open operator-only choices

Gemini should use these defaults without repeated clarification:
1. Keep Python/Flask/MongoDB; refactor, do not rewrite in Node or .NET.
2. Single organization may create multiple workspaces; strict logical tenant isolation.
3. REST remains available separately from MCP.
4. HTTPS remote MCP is mandatory for ChatGPT/Claude cloud clients; stdio optional for local use but delivered in P0.
5. Read-only MCP default; destructive operations require granular scopes and server-side intent.
6. The product is API-first; **no comprehensive admin web UI in v1**. CLI and REST admin management are sufficient. A minimal dashboard may follow in P1.
7. Use a maintained external OIDC/OAuth authorization server if possible, not custom cryptography or login flows.
8. Authenticated users must explicitly select/work with authorized workspace/project IDs; never infer arbitrary access from record content.
9. Reject unsafe or unsupported legacy use cases rather than compromising isolation.
10. Avoid feature creep such as scraping, vector search or billing until v1 stable.

Only these decisions require operator approval before material external action: public hostname and cloud provider, production secrets and identity-provider configuration, production database migration/data deletion, third-party OAuth client registration, licensing policy, DNS/public exposure, and production deployment. Implement safe defaults and local mock/test configuration without waiting for these approvals.

## 15. Gemini checkpoint/report template

```markdown
# Milestone M<N> result
- Baseline SHA: ...
- Branch / PR: ...
- Summary of work: ...
- Files changed: ...
- Decisions / ADR links: ...
- Migrations: ...
- Security considerations: ...
- Tests executed (exact command and result): ...
- Lint / typecheck / scans (exact result): ...
- Compatibility impact: ...
- Screenshots / logs / test outputs (where useful): ...
- Unresolved blockers: ...
- Rollback procedure: ...
- Acceptance checklist (pass/fail): ...
- Next milestone: ...
```

## 16. Release acceptance checklist

- [ ] No fallback credentials or secrets; explicit one-time bootstrap only.
- [ ] Scoped tenant authorization for every REST path, job, and MCP tool.
- [ ] Defined JSON Schema validation, no unrestricted Mongo operators.
- [ ] Create/get/search/update/soft-delete/restore all tested with version conflicts.
- [ ] Idempotent bulk and job workflows; import/export with caps.
- [ ] OAuth 2.1 and secure MCP remote transport tested with real OpenAI and Claude clients.
- [ ] Local MCP stdio tools work with local compatible clients.
- [ ] Tool schemas stable, bounded outputs, guarded destructive actions.
- [ ] GitHub Actions tests/scans pass; release image built reproducibly.
- [ ] No unresolved critical/high vulnerability without approved exception.
- [ ] Backup and restore rehearsal successfully completed.
- [ ] Rate limits, audit events, request IDs, metrics and alerts confirmed.
- [ ] Documentation: install, API, MCP setup for ChatGPT/Claude, deployment, upgrade, rollback, security.
- [ ] Production cutover performed only after explicit operator sign-off.

## 17. Reference documents to verify during implementation

- Source repository: https://github.com/iovigi/Data-Collector
- MCP protocol specification (select implemented revision and test against clients): https://modelcontextprotocol.io/specification
- MCP official Python SDK: https://github.com/modelcontextprotocol/python-sdk
- OpenAI custom MCP connections: https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt
- OpenAI MCP API tooling: https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- Claude remote MCP custom connector: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp

**Important:** Product UI, supported protocol revision and OAuth registration details change. Verify exact current docs at the time of integration, then freeze a compatibility matrix with tested versions; don't blindly implement outdated blog examples.

## 18. Execution contract — complete in one assignment

This file is the **sole master plan**. Do not split it into separate plans or require the operator to paste prompts for each phase. Execute the entire project sequentially with the milestones acting as internal quality checkpoints.

**First actions:**
1. Inspect the actual checked-out repository and capture commit SHA, dependencies, tree, tests, lint, and current behavior.
2. Produce `docs/architecture/current-state.md`, `docs/architecture/target-state.md`, `docs/architecture/threat-model.md`, and `docs/adr/0001-incremental-flask-mongodb-refactor.md`.
3. Establish development bootstrap and baseline tests for every legacy route. Do not rewrite insecure code without either isolating it or adding regression coverage.
4. Complete M0 criteria, commit, and **immediately proceed to M1** without asking for another prompt.
5. Continue in dependency order through **M11**, including code, tests, migrations, Docker/CI, MCP local and remote transports, docs, and a release-candidate checklist.
6. Keep `IMPLEMENTATION_PROGRESS.md` updated **after each milestone**; include completed/remaining scope, actual test commands and outcomes, commit SHA, failure details, and exact next steps.
7. Finish by delivering one consolidated implementation report with: implemented features; all milestone results; test summaries with real evidence; actual ChatGPT/Claude connector validation versus simulated-only cases; open risks; security decisions; local startup and deployment commands; connection configuration for MCP; changelog; and production-operator actions that still require explicit authorization.

**Non-negotiable:** Do not conclude with only plans, scaffolding, TODOs, code snippets, or an M0 report. Produce functioning, integrated software for all feasible requirements within this assignment. If a hard runtime or access limit prevents further work, state precisely what was actually delivered and persist a continuation checkpoint. Never claim unexecuted tests passed or remote connectors worked when they were not tested.

## 19. Worker handoff and context-resilience protocol

For long-running worker executions, avoid losing progress or making contradictory edits:

- Track implementation state in `IMPLEMENTATION_PROGRESS.md` with checklist entries for M0–M11 and a timestamped changelog.
- Keep all architecture decisions in `docs/adr/`; do not silently change the stack or the chosen tenant isolation strategy.
- Before changing a route or contract, locate related tests and update them in the same commit. Preserve backward compatibility unless the old behavior is unsafe; document intentionally blocked legacy behaviors.
- After each milestone, run the relevant test pyramid and preserve the real output in concise evidence summaries; do not manufacture pass rates or coverage metrics.
- When parallel workers are supported, delegate isolated tasks only after interfaces are fixed; ensure one integrator resolves conflicts, runs integration tests, and verifies acceptance. Do not allow concurrent schema migrations or conflicting changes to core auth policy.
- Classify status as `implemented + verified`, `implemented + not externally verified`, `blocked by operator`, or `not implemented`. Never mark a feature complete based only on generated code.
- The final target is a production-capable release candidate. **Actual public deployment** requires separate human authorization and is not implied by this master plan.

## 20. Final completion report format

Produce a single final report, not one completion message after every milestone:

```markdown
# Data Collector 2.0 — Final delivery report
## Source and version
- Base SHA / final SHA / branch / release tag
## Implemented and verified features
- Feature | files or component | test evidence | status
## Milestones
- M0 through M11: status and SHA
## Security and tenant isolation
- Threat model, key controls, security scans and residual risks
## MCP integration
- stdio, Streamable HTTP, OAuth, supported protocol revision
- Tested client/version/transport/auth mode and actual result
- ChatGPT live test status and Claude live test status (never assume)
## Reproducible commands
- bootstrap; test; run; compose; smoke-test; import/export; MCP validation
## Migration and rollback
- changes, backup proof, recovery steps
## Outstanding blockers and operator-only steps
- hostname, identity provider, external client registration, secrets, DNS, deployment
## Completion verdict
- Production release candidate: yes/no and supporting evidence
```

