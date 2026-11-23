# Data Collector 2.0 — Final Hardening & Production Readiness

**Implementation specification for Gemini worker**  
**Repository:** https://github.com/iovigi/Data-Collector  
**Audited revision:** `main` at `7bd8d4b663111077d7b1a616a1a916d8883bdaa4` (2026-11-23)  
**Current declared version:** `2.0.0rc1`  
**Execution mode:** Complete all work in one continuous assignment; track incremental commits and evidence.  
**Document status:** Action plan based on source review, not a completed security audit or deployed environment validation.

## 0. Mission and non-negotiable rules

Turn the existing release candidate into a demonstrably production-ready, securely deployable data platform supporting REST and MCP integration with Claude and ChatGPT. Fix findings without gratuitously rewriting the layered Flask/MongoDB architecture. Complete deferred functionality (M11) as part of this assignment, unless it directly conflicts with established documented scope; document scope reconciliation in that case.

1. Inspect the actual current HEAD before editing. Treat all file references and findings below as starting hypotheses to verify against the current code. Do not assume that a green CI pipeline proves the full platform is production-ready.
2. **Perform the entire plan, not just the first phase.** Move automatically through workstreams when gates pass. Do not request intermediate approval. Never perform live deployments, change real production data, disclose secrets, or configure paid external services without explicit authorization; use isolated test environments and leave externally gated steps documented.
3. Fix the root cause rather than suppress tests or security checks. No `TODO`, dummy endpoints, fabricated test results, intentionally misleading documentation, or blanket `noqa` / `type: ignore` for new code.
4. Ensure REST and MCP always share authorization, validation, tenant isolation, auditing, and application services. Do not introduce raw direct DB access through MCP.
5. Choose and document an OAuth deployment strategy **before** implementing it. Prefer integrating a standards-compliant external authorization server / identity provider where feasible over building an identity provider from scratch. Support standards-compliant discovery and a verified token-validation path.
6. Default MCP to read-only. Mutating actions require least-privilege scopes and suitable user/host authorization. Never claim that a server-issued deletion token substitutes for user approval in a client UI.
7. All long-running imports/exports and operational data must survive restarts; demonstrate this with tests.
8. Keep the change set organized in reviewable commits and update `IMPLEMENTATION_PROGRESS.md`, `CHANGELOG.md`, and documentation after each completed workstream.
9. Record exact commands, outcomes, test counts and coverage, known limitations, and unmet external dependencies. Mark anything not executed as **NOT VERIFIED**.

## 1. Verified baseline and specific findings

Initial code review shows a layered `data_collector/` package (domain, services, repositories, API v1, MCP, workers), MongoDB, Redis/RQ, tenant-aware record repositories, safe query DSL, API keys/JWT, Docker, GitHub Actions and tests. A GitHub Actions CI run for `7bd8d4b` passed Ruff, Mypy, Pytest, Bandit, pip-audit and Docker image build. This is positive, but not proof of functional deployment or end-to-end client OAuth.

### Confirmed findings to investigate and resolve

| ID | Priority | Finding and evidence | Completion expectation |
|---|---|---|---|
| AUTH-01 | P0 | `data_collector/mcp/auth.py` advertises OAuth authorization/token/revocation/JWKS URLs, while inspected HTTP routes did not implement these provider endpoints. Current MCP bearer/API key validation is **not** a complete OAuth authorization flow. | Integrate working compliant authorization server or implement fully tested standards-compliant flow; metadata must point to actual reachable endpoints. |
| MCP-01 | P0 | `data_collector/mcp/server_http.py` uses Starlette `BaseHTTPMiddleware` to set/reset a `ContextVar` actor consumed by tool handlers. Cross-task propagation and concurrent request isolation require verification; do not presume safe behavior from simple unit tests. | Strong identity isolation under parallel MCP sessions and async execution; explicit tests including mixed principals. |
| MCP-02 | P0 | `tests/integration/test_mcp_server.py` checks MCP tools and metadata but does not prove successful end-to-end ChatGPT or Claude authorization and remote client handshakes. | Real protocol-level E2E, token acquisition, discovery, HTTP transport, reconnect and failure tests; client-specific smoke-test steps and honest proof for unavailable services. |
| OPS-01 | P0/P1 | `compose.yaml` publishes 8000/8001 without bundled TLS termination. Public remote MCP needs HTTPS and appropriate proxying. | Reference HTTPS ingress, hardened exposure, exact `MCP_PUBLIC_URL`, trustworthy forwarding and redirect config. |
| OPS-02 | P0/P1 | Import/export services use `Path(settings.storage_dir)` and workers operate separately; `compose.yaml` has Mongo persistence but no explicitly shared durable storage for job artifacts. | Shared persistent volume or object storage abstraction with per-tenant access control, retention, cleanup and restart recovery. |
| DATA-01 | P1 | `data_collector/services/export_service.py` calls record search with `limit=10000`, risking an incomplete export with no guarantee of continuation. | Correct streaming/batched full export, deterministic order, meaningful bounds, completeness metadata and resumability where feasible. |
| API-01 | P1 | `data_collector/app.py` OpenAPI generator enumerates routes but uses generic 200 responses and lacks full parameters, body schemas and security definitions. | Valid complete OpenAPI 3.1 spec with proper endpoint schema, errors, permissions, examples and contract tests. |
| SCOPE-01 | P1/P2 | `IMPLEMENTATION_PROGRESS.md` marks M11 as deferred: saved queries, webhooks, schema migration assistant, usage analytics. | Implement according to agreed original plan; security/operational considerations included. |

### Additional code areas requiring targeted review (not yet confirmed defects)

- `data_collector/services/auth_service.py`: refresh-token rotation race safety, replay detection transactionality, JWT tenant/scope semantics, token revocation, key expiry and collection-level restrictions (`allowed_collection_ids`).
- `data_collector/domain/policies.py` and `data_collector/services/*`: verify API key collection restrictions and scope checks on every read/write/job route, including indirect actions and MCP resources.
- `data_collector/infrastructure/repositories/record_repo.py`: deny unbounded operators; ensure `maxTimeMS` is never silently skipped in production. Reassess index strategy and compound predicate isolation at scale.
- `data_collector/mcp/tools.py`: generic exception mapping; ensure no sensitive exception details escape, no accidental write/tool exposure, strict response-size limits and timeout handling.
- `data_collector/services/import_service.py`: large file parse memory, content-size enforcement, CSV/JSON edge cases, partial failures, row-level error capping, cancellation and retries.
- `data_collector/services/export_service.py`: CSV formula sanitization, cancellation, artifact ownership/expiry, resource exhaustion, cross-tenant result access, concurrent exports and checksums.
- `data_collector/api/v1/jobs.py`: authorization on downloads and binding of downloads to their initiating tenant; safe filenames and content types.
- `data_collector/config.py`, `.env.example`: all production secrets, TLS expectations, cookie/token configuration and origin allowlisting.
- `.github/workflows/ci.yml`: use current patched runtime versions, pinned actions as appropriate, lock/reproducibility and integration testing with real MongoDB/Redis.

## 2. Target architecture and expected end-user scenarios

Maintain this data path:

```text
Claude / ChatGPT / Claude Code / other MCP clients
      |  MCP stdio or HTTPS Streamable HTTP
      v
MCP tool layer + identity context + per-tool scopes
      |
      v
Application services <---- REST /api/v1 endpoints
      |
      v
Validation + tenant policy + audit + query budget
      |
      +---- MongoDB (structured records and metadata)
      +---- Redis/RQ (queuing, rate limits)
      +---- durable artifact storage (imports/exports)
      +---- IdP / OAuth authorization service (remote clients)
```

### End-to-end user stories (must be demonstrated)

1. **Claude Code local read-only**: configure `dc-mcp-stdio`, authenticate via scoped API key, list collections, inspect schema and safely search records; write denied by default.
2. **Remote ChatGPT**: connect an HTTPS MCP server using a supported authorization flow, discover tools, fetch results only from permitted workspace; reconnect and refresh correctly. A service requiring OAuth must have real working authorize/token endpoints through its chosen IdP.
3. **Remote Claude**: connect via supported remote MCP capabilities, authorize, list and query; repeated and concurrent requests never leak another principal's data.
4. **Controlled mutation**: authorized agent creates/updates a record with idempotency and version conflict handling. Delete requires correctly scoped permission and server-side preflight; document that any UI approval is client-controlled and not guaranteed by the MCP server alone.
5. **Import/export**: upload a large test dataset, run job with worker, retrieve artifact from API, validate row count/hash, restart app/worker and retrieve artifact again.
6. **Tenant isolation**: user A with all own-tenant permissions cannot infer or read/write any B resource, including MCP resources, jobs, download endpoints and pagination cursors.
7. **Observability**: trace an MCP call through services, job and audit entries using correlation/request IDs without logging tokens, PII unnecessarily or record payloads.

## 3. Workstream A — OAuth and remote MCP interoperability (P0)

### A1. Produce an explicit OAuth architecture decision record

- List precise client requirements currently documented for ChatGPT custom MCP apps/connectors, OpenAI API remote MCP tools and Claude connectors. Verify fresh official documentation before implementation; platforms and requirements change.
- Decide: existing external IdP (e.g. an OIDC/OAuth-compliant provider), managed identity, or first-party OAuth server. **Do not advertise a fake issuer**. Describe authorization-server ownership and boundaries, client registration model, consent, redirect URI behavior, resource indicators, scopes, and token semantics.
- Configure `AUTH_ISSUER`, audience and `MCP_PUBLIC_URL` with consistent externally accessible URLs; ensure metadata locations satisfy the MCP protected-resource and authorization-server discovery rules.
- Support OAuth authorization code with PKCE S256 where appropriate, refresh/revocation when applicable, exact redirect URI validation, state safety, CSRF defenses, proper access token scope and audience, and suitable registration support (including client metadata/documented options as applicable to each client).
- For an external IdP: configure discovery and verify JWKS signatures, `iss`, `aud`, `exp`, `nbf`, scopes, authorized party/client where applicable, and key rotation. Current symmetric HS256 local JWTs must not be blindly interpreted as external OAuth tokens.
- Prefer a dedicated trusted issuer; do not expose `/authorize` endpoints without real handlers.

### A2. Fix metadata, authentication and error responses

- Ensure `/.well-known/oauth-protected-resource` and authorization server metadata accurately reflect live URLs and supported scopes.
- Add protected-resource `WWW-Authenticate` challenge and metadata links to appropriate 401 responses; return correct HTTP status semantics for malformed/insufficient/expired credentials.
- Make bearer auth, API-key auth, and local stdio auth explicitly distinguishable and policy consistent. API keys are not OAuth tokens.
- Validate bearer token resource/audience binding to the MCP server. Remove acceptance of tokens minted for unrelated resources.
- Add request IDs and safe structured audit for authentication successes/failures.

### A3. Correct actor lifecycle and concurrent request isolation

- Examine the `BaseHTTPMiddleware` / `ContextVar` crossing task boundary in Starlette and MCP SDK. Prefer an ASGI-scope-aware auth mechanism or official SDK auth components that supply a request-bound verified principal.
- Remove global mutable identity state. Ensure no principal persists across sessions, tasks, background work, or exceptions.
- Verify transport startup/shutdown lifecycle, stateless vs stateful session mode, SSE/streaming expectations, GET/POST/DELETE semantics, proxy buffering and connection idle timeouts.
- Add concurrent identity tests (A/B different tokens, parallel tool calls, reconnects, expired tokens, cancellation).

### A4. Protocol and client validation

Automate checks using MCP SDK client (not only internal `mcp.call_tool`):

- `initialize` handshake and negotiated capabilities
- `tools/list`, `tools/call`, resource and prompt discovery
- successful 401 metadata discovery and login (or OAuth provider simulation in CI)
- full authorization code + PKCE flow with actual issuer in an integration environment
- multi-session isolation and connection restart
- write/tool permissions with read-only defaults
- no raw secrets in tool results or logs
- representative error handling, output cap and timeout

Provide tested configurations and visual/manual acceptance checklist for Claude Code, Claude Desktop and ChatGPT connector setup. If accounts/UI access are unavailable, mark client smoke tests **PENDING EXTERNAL VALIDATION**, not passed. Document any ChatGPT plan/workspace feature constraints instead of asserting universal availability.

**Gate A:** All protocol tests and OAuth integration tests pass; current metadata does not advertise nonexistent endpoints; remote authorization succeeds with a test client and identity remains isolated across concurrent connections.

## 4. Workstream B — Security and authorization closure (P0)

### B1. Build a permission matrix

Document requirements for roles (`owner`, `admin`, `editor`, `viewer`), scopes and resources (`workspace`, `project`, `collection`, `record`, `job`, `API key`, `audit`). Add explicit unit/integration coverage for each permitted and denied cell.

Test across REST, MCP tools **and MCP resources/prompts**:
- read/write/delete/restore
- batch and async jobs
- import/export and artifact download
- collection schema and metadata
- API key creation/revocation and optional `allowed_collection_ids`
- cross-workspace and cross-project operations
- system admin and service account handling

### B2. Enforce secrets and token security

- Hash secrets and refresh tokens; prevent plaintext secrets in logs.
- Ensure refresh token rotation and replay detection are atomic under concurrency; revoke family consistently on replay.
- Prevent stale privileges: define token revocation, account disable, workspace removal and key revocation behavior; test active tokens/keys after permission changes.
- Enforce API-key least privilege including collection restrictions, expiry and revocation for all access paths.
- Make token audience/issuer validation unconditional for remote OAuth.

### B3. Validate inputs and quotas

- Bounded query AST depth, total predicates, filter operators, sort fields, limits and projected fields.
- Reject MongoDB operator injection including nested `$` keys, dangerous path syntax and prohibited regex/aggregation constructs.
- Strict schema enforcement, protected immutable fields, max payload sizes and nested object depth.
- Query execution timeouts and index-aware performance checks; do not silently drop database-enforced timeouts.
- Per-principal and per-tenant rate limits, concurrency limits and job quotas.
- Protect against SSRF in any future webhook delivery and reject private/internal IP destinations where required.

### B4. Security evaluation

- Add tests for horizontal privilege escalation, NoSQL injection, BOLA/IDOR, confused-deputy actions, OAuth redirect abuse, token replay, cursor tampering, hostile tool data and CSV formula injection.
- Run dependency auditing, SAST, secret scanning, dependency pin/lock strategy and container image scanning.
- Document all threat mitigations, residual risks and security configuration in `SECURITY.md`.

**Gate B:** No known exploitable P0 vulnerability; every high-impact data path has authorization tests; negative test evidence demonstrates cross-tenant isolation and credential revocation.

## 5. Workstream C — Reliable import/export jobs and storage (P0/P1)

### C1. Durable file storage

- Define `ArtifactStore` abstraction with `put/get/delete`, metadata and access control; select object storage for production or durable shared volume for single-host deployment. MinIO/S3-compatible storage is acceptable if implemented, tested and properly configured; preserve local mode for development.
- Ensure API and worker both access the *same* durable content. Do not rely on separate container writable layers.
- Store only opaque server-created artifact IDs/keys in MongoDB, never trust client-supplied filesystem paths.
- Enforce storage boundaries, file size limits, content type restrictions, retention/expiry, cleanup and quota limits.
- Implement access controlled download with correct tenant ownership, expiration and integrity hash.
- Verify restart recovery and multiple worker behavior.

### C2. Full-data export

- Remove implicit `limit=10000` data truncation.
- Export using deterministic keyset pagination or database cursor streaming with tenant predicate and bounded batch size, stable ordering and explicit consistency semantics.
- Record exported count, optional total estimate, bytes, hash, format, started/completed timestamps, warnings and failure details.
- Stream output to storage without building the entire output in RAM; cap worker memory.
- Support JSONL and CSV at minimum; JSON arrays can be streamed safely. Preserve CSV formula injection protection.
- Define cancellation, retry and deduplication behavior. Fail transparently on limits; never silently return incomplete exports.

### C3. Robust import

- Stream parse files where feasible, enforce size and row caps, validate schema and encoding, provide bounded per-row error reports, duplicates and idempotency handling.
- Define partial success and retry semantics. Ensure repeated jobs do not duplicate already committed records without explicit intent.
- Ensure cancellation and retries update durable job state correctly.
- Add sample 100k+ record tests and file-size/memory tests within documented limits.

**Gate C:** Test imports/exports across container restart and worker restart; export counts and checksums match source fixtures; no missing artifacts, silent truncation or cross-tenant downloads.

## 6. Workstream D — Accurate API contracts and quality (P1)

- Replace the route-enumeration placeholder OpenAPI with a complete OpenAPI 3.1 description, preferably generated from validated typed request/response models and route annotations.
- Include authentication schemes, scopes, operation IDs, parameters, body types, success/error schemas, pagination/cursors, examples, job lifecycle, idempotency headers and rate limits.
- Validate generated schema in CI with a standard OpenAPI validator.
- Generate typed client samples or full Python SDK as appropriate; verify samples against running dev stack.
- Publish a standard API error schema with `code`, `message`, `request_id`, optional field errors; sanitize internal failures.
- Normalize HTTP status codes (`201`, `202`, `400`, `401`, `403`, `404`, `409`, `422`, `429`, `503`) and test compatibility.
- Document legacy API migration. Avoid claiming full backwards compatibility if legacy endpoints were intentionally disabled.

**Gate D:** OpenAPI validator passes; every documented request/response example passes contract tests; docs and implementation match.

## 7. Workstream E — Operations, deployment and observability (P1)

### E1. Production topology

- Keep app and worker in separate isolated containers; add reference reverse proxy (Caddy, Nginx or Traefik) with automatic HTTPS certificate support or documented deployment behind trusted ingress.
- By default bind private service ports to internal networks or loopback rather than exposing unauthenticated infrastructure publicly.
- Set `MCP_PUBLIC_URL` and canonical API URL to external HTTPS origins; trust forwarding headers only from known proxies.
- Make health probes meaningful and include Mongo/Redis/IdP/storage dependency states. Do not expose sensitive dependency details publicly.
- Ensure non-root container, read-only mounts where feasible, resource limits, graceful shutdown, restart policies and minimal capabilities.
- Specify database credentials, MongoDB authentication, Redis ACL/password/TLS as appropriate, network policies and secrets injection.

### E2. Monitoring and logs

- Structured logs and correlation IDs across REST/MCP/jobs.
- Prometheus metrics: request rate, error rate, latency, job queue depth, job duration, OAuth auth failures, database latency, rejected quota requests and MCP tool usage.
- Avoid per-user high-cardinality metric labels and plaintext tokens/PII in logs.
- Document alert thresholds and how to diagnose queue congestion, failed OAuth discovery, expired certificates and storage failures.

### E3. Recovery and deployment tests

- Document MongoDB backups/restore (with encrypted/offsite backups and restoration drills), persistent artifact backup strategy and Redis role (cache/queue) reliability.
- Run a repeatable isolated production-like smoke test: HTTPS API + HTTPS MCP, auth, seeded data, job execution, restart, restore, metrics and clean shutdown.
- Pin/lock dependencies reproducibly; update `README.md`, runbook and `.env.example` with secure values/placeholders only.
- CI must include real MongoDB/Redis integration stages, full protocol tests, security gates and Docker Compose smoke test in addition to existing unit/mocked tests.

**Gate E:** Fresh clone can boot full stack with documented commands; an isolated production-like deployment passes the smoke test and restart/restore exercises.

## 8. Workstream F — Finish M11 (P1/P2)

Implement **all four deferred enhancements** with permissions, schema, APIs, MCP exposure only where safe, and tests:

1. **Saved queries:** owner/workspace-scoped named query definitions, safe DSL only, CRUD, execution, versioning, duplicate naming policy, no credential storage, read-only MCP discover/run tools.
2. **Webhooks:** managed endpoints, allowlisted event types, HMAC signatures, delivery queue, retry/backoff, delivery logs, dead-letter and replay tools, secret rotation, strict SSRF protections, per-workspace quota, no raw secret exposure.
3. **Schema migration assistant:** preview/dry-run, validation of existing records, version transitions, impact report, staged apply, safe rollback policy, audit, deterministic failures; no unapproved destructive schema transformation.
4. **Usage analytics:** per-tenant counts for API/MCP operations, storage, job execution and failures; time aggregation with bounded cardinality, retention controls, access restrictions and dashboard-compatible API output.

Implement these after the P0 workstreams, but **do not stop work** after P0. Update original milestones and release notes transparently.

**Gate F:** Every enhancement has a documented end-to-end example and automated positive/negative permission tests.

## 9. Required testing matrix

| Suite | Required assertions |
|---|---|
| Unit | Policy, query compiler, auth/token verification, schema, cursor, exports, webhook signing and SSRF validation |
| REST integration | Real MongoDB + Redis, all API v1 routes, scopes, error contracts, idempotency, pagination |
| MCP protocol integration | Actual stdio and HTTP transport; initialize, tools/resources/prompts, auth failures, concurrent principals |
| OAuth integration | Discovery, authorization code+PKCE with real test issuer, token exchange, refresh, revocation, audience/scope isolation |
| Tenant isolation | Cross-workspace/project/collection/record/job/export access rejected across REST and MCP |
| Jobs | Large imports, full export >10k, checksums, retry, cancel, restart and persistent artifact availability |
| Security | NoSQL injection, BOLA/IDOR, token replay, hostile content, SSRF, CSV formula injection, sensitive log scanning |
| Operational | Fresh Docker Compose boot, readiness, HTTPS ingress, worker, proxy forwarding, backups and restore |
| Performance | Bounded queries and exports, load and concurrency checks with clearly defined test dataset |

### Minimum release gates

- CI fully green on current HEAD with exact link and commit SHA.
- No unresolved P0 issues or high-severity known vulnerabilities; document any lower severity risks with mitigation and owner.
- Coverage target **>= 85%** of the new `data_collector` code (raise as appropriate); **100% critical authorization branches exercised** through explicit positive and negative tests. Report actual numbers, not estimates.
- Fully functional local MCP, remote MCP protocol tests and verified OAuth with a deployed test issuer.
- Real ChatGPT/Claude connector smoke tests where access exists; otherwise release status must explicitly state **EXTERNAL CLIENT VALIDATION PENDING**.
- Confirm >10,000-record export without truncation and successful artifact recovery after restart.
- Documentation, manifests and runtime settings match the released code.
- Never label the project universally production-ready while required end-to-end external integrations remain unverified.

## 10. Execution sequence for Gemini (one autonomous assignment)

**Preflight:** check HEAD, status, dependencies, current tests and documented work. Create an implementation branch from current HEAD and a concise findings delta. Avoid overwriting user changes.

**Step 1 — P0:** complete A1-A4 and B1-B4; do not expose MCP publicly until bearer validation and OAuth integration are correct. Commit after tests.

**Step 2 — Data safety:** complete C1-C3; test with real MongoDB/Redis and durable storage under restart. Commit after tests.

**Step 3 — Public API quality:** complete D, document schemas and validate contract. Commit.

**Step 4 — Operational readiness:** complete E, including isolated integration deployment with HTTPS. Commit.

**Step 5 — Deferred scope:** complete F, security test all new features and commit.

**Step 6 — Final qualification:** run entire test matrix, security scanning, build, deployment smoke, performance checks, documentation validation and create a release candidate report. Do not claim real external services were tested if they were not. Do not self-merge or deploy to public production without authorization.

### Worker agent delegation

If Gemini can delegate work, parallelize only independent modules behind stable contracts (API docs, storage adapter, saved queries, webhooks, analytics, tests). Keep OAuth architecture/auth changes and permissions centrally owned. Require a single integration owner to review, merge, run all tests and validate cross-module behavior. Parallel work must not result in inconsistent policy implementations.

### On interruption / context limit

Persist progress in `IMPLEMENTATION_PROGRESS.md`, including current SHA, completed workstreams, failures and exact next command. Resume automatically when execution continues. Never mark a workstream completed based only on code being written.

## 11. Required final deliverables

1. Implementation code and reviewed commit history.
2. `docs/architecture/oauth-deployment.md`: real issuer choice, discovery, PKCE and clients.
3. `docs/mcp/chatgpt-setup.md`, `docs/mcp/claude-setup.md`: accurate walkthroughs and tested examples.
4. `docs/operations/deployment.md`, `backup-restore.md`, `storage.md`, observability runbook.
5. Complete OpenAPI 3.1 specification and working examples.
6. Automated integration, security, performance and restart tests with scripts.
7. Updated `README.md`, `SECURITY.md`, `CHANGELOG.md`, `IMPLEMENTATION_PROGRESS.md` and original plan status.
8. `PRODUCTION_READINESS_REPORT.md` with evidence table:
   - git SHA and branch
   - exact tests/commands, counts, pass/fail and coverage
   - security and dependency audit results
   - MCP SDK protocol test result
   - test OAuth issuer and discovery result (no secrets)
   - actual ChatGPT/Claude results or pending validation reason
   - large export and restart-recovery proof
   - known risks, launch blockers, manual steps, rollback and go/no-go recommendation.

## 12. Completion directive

**Execute this specification end-to-end in a single assignment.** Keep milestone boundaries for testing and commits, not for requesting the user's approval. Do not stop after drafting the plan, after an initial audit, or after only fixing OAuth. Implement and verify all applicable workstreams. For operations requiring accounts, DNS, live credentials, cloud resources or explicit authorization, provide runnable setup plus a narrowly scoped checklist of missing external prerequisites; continue everything else. Final response must clearly distinguish **implemented**, **automatically verified**, **manually verified**, and **not verified**, and must not declare production readiness without the release gates above.
