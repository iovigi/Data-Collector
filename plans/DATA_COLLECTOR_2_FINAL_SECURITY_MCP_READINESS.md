# Data Collector 2.0 — Final Security & MCP Production Readiness Plan

**Target repository:** https://github.com/iovigi/Data-Collector  
**Audit baseline:** `main` at `e1233770461c894130689febf1d7dc4a428e23ed` (2026-11-23)  
**Audience:** Gemini implementation worker / senior backend, security and DevOps engineer  
**Deliverable:** One fully implemented, tested, documented release candidate, not another plan  
**Priority:** P0 security blockers first; P1 reliability and interoperability next  

> This is an implementation specification based on a static source review and GitHub CI inspection. The last observed CI run passed, but no real ChatGPT/Claude remote connector session or production deployment was verified. Re-check the latest branch before changing anything.

## 0. Execution contract for Gemini

Implement **all** workstreams below in a single continuous execution, without stopping for approval after each workstream. Break implementation into small, reviewable commits and continue automatically after passing each gate. Do not merely rewrite this specification, provide pseudocode, or declare code generation equivalent to deployment verification. If a task requires credentials, DNS, an external client or production infrastructure not available in your environment, implement everything independently testable, explicitly mark the external portion `BLOCKED_EXTERNAL_VALIDATION`, and continue.

**Safety and change control:** Do not deploy to production, rotate active secrets, delete real data, alter externally managed identity providers or connect a real customer tenant without explicit authorization. Do not commit secrets, access tokens, generated private keys, test customer records or `.env` files. Preserve the current Flask/MongoDB/Redis-RQ architecture and the shared REST/MCP service layer; avoid a wholesale rewrite. Confirm repository licensing before redistribution.

Before editing:
1. `git status`, branch, latest SHA, file inventory and current test baseline.
2. Read `PRODUCTION_READINESS_REPORT.md`, `IMPLEMENTATION_PROGRESS.md`, `docs/architecture/oauth-deployment.md`, `SECURITY.md`, CI configuration and all relevant sources.
3. Confirm whether findings below remain valid at HEAD. Mark each as `CONFIRMED`, `ALREADY_FIXED`, or `NOT_REPRODUCIBLE` with source/test evidence.
4. Save an initial audit entry in `docs/operations/final-security-verification.md` (no secrets).
5. Create feature branch `hardening/final-security-mcp` unless the repository workflow requires a different branch; do not force push.

Run quality checks after every workstream and fix failures before continuing. Keep a machine-readable checklist in `IMPLEMENTATION_PROGRESS.md` and an evidence matrix in `PRODUCTION_READINESS_REPORT.md`.

## 1. Baseline findings to validate

| ID | Severity | Source | Observed issue / risk | Acceptance evidence |
|---|---|---|---|---|
| SEC-01 | P0 | `data_collector/infrastructure/oauth.py` | Without `OAUTH_RSA_PRIVATE_KEY_PEM`, OAuth RSA signing key is generated per process startup; tokens may become invalid after restart and multiple replicas may disagree. | Persisted key/key provider tests and production fail-fast test |
| SEC-02 | P0 | `data_collector/mcp/server_http.py`, `data_collector/infrastructure/oauth.py` | Authorization form accepts requested scopes and creates code after password verification; explicit per-client scope enforcement, consent and authorization binding require verification/hardening. | Negative consent/scope tests and user authorization flow |
| SEC-03 | P1 | `data_collector/mcp/server_http.py` | `/oauth/token` processes authorization-code grant only; builtin refresh-token grant is not implemented. | Rotation/replay/revocation integration tests |
| SEC-04 | P1 | `data_collector/infrastructure/ssrf.py`, `data_collector/services/m11_service.py` | URL DNS prevalidation may be bypassed by DNS rebinding between validation and connection, and redirect behavior must be explicitly constrained. | Controlled DNS/redirect adversarial tests |
| MCP-01 | P0 release gate | `docs/mcp/*`, `PRODUCTION_READINESS_REPORT.md` | Live ChatGPT/Claude remote connector compatibility has not been verified. | Redacted end-to-end logs or clearly flagged external blocker |
| OPS-01 | P1 | Deployment/operations docs | Backups and restoration must be rehearsed; TLS/DNS/IdP are operator prerequisites. | Staging restore report and deployment smoke tests |

**Additional concern to inspect:** The `OAuthService.exchange_code()` code in the inspected baseline consumes an authorization code using `find_one_and_update({code_hash, used: false})` *before* validating client ID, redirect URI and PKCE. This is fail-safe against reuse but may allow unauthenticated code invalidation if the code leaks. Evaluate whether validation can occur before an atomic compare-and-consume without enabling replay or races; add explicit tests. Do not weaken single-use semantics.

**Additional concern to inspect:** `OAuthService.revoke_token()` parses JWT without signature verification when extracting `jti`. Ensure an unauthenticated caller cannot revoke a different user's valid token by forging a token with the same `jti`. Require client ownership or validated token binding and an appropriate RFC 7009 response policy. Add attacker-victim tests.

## 2. Workstream A — Durable OAuth signing keys (P0)

### Required behavior

- In **production builtin OAuth mode**, reject startup when neither a durable, explicitly configured signing key nor a vetted key-management backend exists. Never silently create a volatile key.
- Keep ephemeral key generation only for local development/test, gated explicitly and documented. Do not permit this default in `APP_ENV=production`.
- Support a secure deployment path for a persisted PEM secret or a KMS-compatible signer; avoid forcing KMS integration if unsupported by current infrastructure, but design a clean signer abstraction if appropriate.
- Validate key type, algorithm, minimum RSA modulus length (>=2048 bits), parsing, and `kid` consistency. Prevent accidental private-key exposure in logs or API JSON.
- Separate key loading from creation; startup of multiple replicas with the same config must produce the same public JWKS key material.
- Document rotation policy: multiple public verification keys during overlap, active signing key, grace period, token lifetime, revocation and safe rollback. If multi-key rotation is not implemented, clearly label it as a deployment limitation and require planned maintenance for key rotation.
- Ensure external IdP mode does not unnecessarily create an independent local signing key and that production settings validate `AUTH_ISSUER`, `AUTH_JWKS_URL`, `MCP_PUBLIC_URL` and HTTPS as relevant.

### Tests

1. Two process/container instances with the same private key validate each other's OAuth access tokens.
2. Restart preserves `kid`, JWKS and access-token validation.
3. Production startup fails without a durable key in builtin mode.
4. Malformed/weak key fails startup with a safe error (no PEM output).
5. Incorrect issuer or audience fails token verification.
6. External mode uses only the configured trusted JWKS issuer and does not accept local HS256 API tokens as remote OAuth tokens.

**Done when:** tests pass with real process restart (not just reused in-memory objects), docs give a reproducible secret provisioning recipe, and CI includes the negative production-config test.

## 3. Workstream B — OAuth scope restrictions, consent and code security (P0)

### Required behavior

- Treat `scope` from the authorization request as untrusted. Compute an intersection of supported scopes, the registered client's permitted scopes, the user's actual RBAC/workspace authorization and any consented scopes. Reject escalation instead of silently adding privileges.
- Validate scope strings strictly; do not issue unknown scopes. Record client ID, `resource`, requested scopes, granted scopes, redirect URI, `state` and code challenge in a safe authorization transaction.
- Build a real **consent page** showing verified client name, application origin, requested effective privileges and data-access scope; clearly distinguish read, write, delete and export. Provide Approve and Deny actions.
- Default third-party client access to read-only. Writes require both explicit client scopes and user consent; deletes additionally require the existing two-step signed intent workflow.
- Prevent login-form CSRF, consent CSRF, login CSRF, open redirects and client impersonation. Use signed, short-lived authorization request state plus secure session/cookie strategy, CSRF tokens, `SameSite`, `Secure` and `HttpOnly` as applicable.
- If credentials are entered directly into the authorization page, review risks and ensure they are not echoed, logged or included in a redirect. Prefer a dedicated authenticated session rather than re-posting passwords for approval.
- Enforce exact redirect URI match against registered values; support only safe local-development exceptions. Enforce PKCE S256, verifier entropy/length, short code expiry, one-time use, issuer/resource/audience binding and client binding.
- Validate registration of redirect URIs to avoid wildcard/fragment/credential injection, Unicode spoofing and query confusion. Add registration rate limits and abuse controls.
- Evaluate explicit tenant/workspace selection for the OAuth grant where the actor belongs to more than one workspace. Tenant authorization must remain enforced by services on **every tool call**, not just at login.
- Store only hashes of authorization codes and refresh tokens. Audit security decisions without secrets or password material.
- Preserve compatibility with approved external IdPs and respect the OAuth/MCP specification version used by clients.

### Negative tests (mandatory)

- Client requests `records:delete` when only `records:read` was registered -> denied.
- Viewer approves `records:write` -> cannot write records.
- Consent denied -> no code and no token issued.
- Forged/expired CSRF token -> authorization rejected.
- Redirect mismatch -> no redirect to attacker-controlled URL.
- Code redeemed with wrong client, wrong verifier, wrong redirect, expired code or second redemption -> rejected.
- OAuth token from another resource/issuer -> rejected.
- Two workspaces belonging to different users -> no cross-tenant access despite broad OAuth scope.
- Tampered `state` -> rejected or passed back only through validated authorization context, per protocol.
- Token revocation cannot target a victim token by sending an unauthenticated forged JWT containing a copied `jti`.

**Done when:** all authorization flows are observable in an integration test from registration through approval, token, MCP call and revocation, with a reviewable test matrix.

## 4. Workstream C — Refresh tokens, rotation and revocation (P1)

**Decision:** For builtin OAuth, implement refresh-token support end-to-end and advertise it only once genuinely supported. Do not borrow the application's existing Flask-local refresh-token implementation without checking separate OAuth client/audience semantics.

- Implement `grant_type=refresh_token` with client binding, resource binding, effective scope non-escalation, server-side hashed token storage, expiry and rotation.
- Atomically consume a refresh token; prevent simultaneous replays producing two valid descendants. On confirmed reuse, revoke the token family or equivalent securely.
- Bind refresh family to client ID and user ID; honor user disabled status, client revocation, consent revocation and workspace access changes.
- Add user/client session inventory and explicit revocation pathways if needed; avoid persistent valid tokens after permissions are removed.
- Ensure token endpoint rejects public-client impersonation via client secret assumptions. Follow OAuth rules for public PKCE clients.
- Align discovery metadata, documentation and actual runtime behavior.

**Tests:** success refresh; one-time rotation; concurrent refresh race; replay-family revocation; expired/revoked token; wrong client; invalid scope; permission downgrade; token grant discovery agreement.

## 5. Workstream D — Webhook SSRF and delivery safety (P1)

Audit `data_collector/infrastructure/ssrf.py` and `data_collector/services/m11_service.py` fully.

- Enforce HTTPS for production webhooks; reject userinfo, invalid port, encoded IP formats, local/metadata/private/loopback/link-local/reserved addresses, IPv4-mapped IPv6 and other ambiguous host forms.
- **Close DNS validation-to-connect gaps.** Ensure the actual transport connects only to a validated resolved IP, while preserving expected TLS SNI and hostname certificate validation. A normal preflight `socket.getaddrinfo()` followed by default independent HTTP client DNS resolution is insufficient.
- Disable redirects by default. If following redirects is required, re-validate every hop and cap hop count; never follow to unsafe/internal origins.
- Restrict outbound network egress at container/network/firewall level as defense in depth. DNS rebinding and split-horizon DNS must not permit access to metadata services or internal APIs.
- Apply connection, total request, read and write timeouts; strict maximum response bytes; bounded retries with exponential backoff and jitter; webhook concurrency and rate limits; circuit breaker/dead-letter status where practical.
- Do not log HMAC signing secrets or full sensitive payloads. Implement idempotent delivery IDs, verifiable HMAC signatures and timestamped anti-replay headers.
- Validate user-supplied webhook endpoints both at creation and **at dispatch**; ensure tests mock the real transport layer and exercise redirects/resolved IP behavior, rather than only `validate_outbound_url()`.
- For local development, isolate localhost exceptions to explicit non-production configuration; never allow them under production.

**Security tests:** DNS switch after validation, redirect to `127.0.0.1`, cloud metadata target, IPv6 loopback and mapped IPv4, TLS invalid certificate, timeout/retry limit, huge response body, webhook secret leakage, disallowed production localhost bypass.

## 6. Workstream E — MCP compatibility and authorization E2E (release blocker)

### Technical expectations

- Verify current supported MCP SDK and protocol behavior rather than assuming previously generated examples are current. Keep official SDK and client compatibility documented by tested versions.
- Validate `POST /mcp` initialization and tool discovery, proper `Accept` and protocol headers, Streamable HTTP session behavior, long-running calls and cancellation, error mapping, tool output caps, and safe cleanup of session/context state.
- Prove `ContextVar` actor isolation **through concurrent HTTP MCP requests**, not only two manually set coroutine context variables. Verify request lifecycle on exceptions and streaming response termination.
- Check OAuth discovery at both well-known endpoints, challenge headers, relative/absolute issuer paths and exact MCP resource audience.
- Confirm `dc-mcp-stdio` never writes logs or banners to stdout (only protocol messages); use stderr for diagnostics.
- Use the same authorization checks for REST, MCP read/write and resources. Test `allowed_collection_ids` on every relevant MCP tool and resource, not only list endpoints.
- Verify `MCP_ALLOW_WRITES=false` disables all mutations even if token scopes allow them.
- Keep two-step delete confirmation bound to actor, record ID, version, collection, intent and expiry; test replay and cross-user use.
- Test malicious record content containing instructions to agent: records remain data, with no elevation of trust.

### Minimum integration matrix

| Client/transport | Test | Required outcome |
|---|---|---|
| SDK local stdio | initialize -> list tools -> read resource -> call read tool | pass |
| Remote generic MCP HTTP client | OAuth discovery -> authorization -> MCP initialize -> tools/list -> tools/call | pass |
| Remote generic MCP HTTP client | 2 simultaneous users and 2 workspaces | no actor/data crossover |
| Remote generic MCP HTTP client | unauthorized, revoked, wrong audience, read-only write attempt | all rejected safely |
| ChatGPT custom connector | actual connector login, discovery and read tool | PASS or `BLOCKED_EXTERNAL_VALIDATION` with exact prerequisite |
| Claude remote connector | actual connector login, discovery and read tool | PASS or `BLOCKED_EXTERNAL_VALIDATION` with exact prerequisite |
| Claude Code local MCP | configure -> start -> list tools -> read | PASS or clearly documented missing environment |

Do **not** claim actual ChatGPT or Claude compatibility based only on a mocked callback URL or generic SDK test. Capture sanitized date, client version where visible, tested endpoint, tool name, status and reason for failure. Never include OAuth tokens in screenshots or logs.

## 7. Workstream F — Infrastructure, recovery and production safety

- Validate the current `compose.yaml`, `deploy/caddy/Caddyfile` and TLS profile. Confirm API/MCP internal binding, correct public routing and discovery behind reverse proxy, forwarded headers, request body limits and safe HTTP-to-HTTPS redirects.
- Check MongoDB and Redis credentials, network segmentation, firewall rules, persistence, version pinning, health probes, startup ordering and non-root images. Use a secret store or environment-injected secrets; production `.env` must not be committed.
- Verify shared `artifacts_data` path for API and worker, durable import/export file access after process/container restart and path traversal prevention.
- Stream exports via bounded keyset/cursor pagination; verify exactly-once/complete collection handling under concurrent mutations or explicitly document snapshot consistency guarantees.
- Verify large imports do not load unbounded data into memory, report row errors safely, and handle worker retry/cancel/restart without duplicate writes where idempotency is expected.
- Add or run a **staging MongoDB backup + restore rehearsal** and confirm recovered API data/tenant membership. Test disaster recovery steps for artifacts and Redis job state as relevant. Document RPO/RTO as operational targets, not unverified promises.
- Check Prometheus metrics do not leak high-cardinality private data and that `/metrics` is private/authenticated in deployment.
- Add request tracing, correlation IDs and sensitive log redaction. Define retention policy for audit logs, exports, imports, OAuth auth codes and token records.
- Add production readiness probes and startup failure tests for missing critical secrets or inconsistent OAuth URLs.
- Evaluate dependency pinning/lock strategy, base-image scans and scheduled vulnerability scans; do not rely on only one historical `pip-audit` run.

### Production gate

No production GO until DNS/TLS, issuer/JWKS, durable keys, backup/restore and end-to-end external integrations are validated by the operator. Staging can be GO if local/integration gates pass and risks are clearly disclosed.

## 8. CI/CD and coverage requirements

Run and retain evidence for:

```bash
python -m pip install -e '.[dev]'
ruff check data_collector tests
mypy data_collector
bandit -r data_collector -ll
pip-audit
pytest tests --cov=data_collector --cov-report=term-missing
# Additional real MongoDB/Redis integration and adversarial OAuth/SSRF suites
# (use exact commands added by implementation to CI)
docker build -t data-collector:final-check .
docker compose config
```

- Existing CI at baseline: 3 successful jobs, and `PRODUCTION_READINESS_REPORT.md` reported 39 tests / 82% coverage. Treat these as baseline claims; record actual new totals after execution.
- Add multi-process signing-key persistence, genuine HTTP MCP concurrency, scope/consent denial, OAuth refresh races, forged revocation, webhook DNS rebinding, redirect and restore tests.
- Tests must not depend on external sites or live credentials in normal PR CI. Place optional external smoke tests behind explicit secret-gated workflows with clear manual trigger.
- Use real MongoDB+Redis for critical integration tests; `mongomock`/`fakeredis` alone are insufficient for atomicity and lifetime claims.
- Cover security-sensitive branches rather than maximizing an arbitrary aggregate coverage percentage. Target >=85% overall where feasible, but a passing coverage number must not substitute for negative tests.
- Report any flaky tests, skipped tests and coverage gaps; do not mask failures with blanket `xfail`/skip.

## 9. Documentation deliverables

Update existing files rather than creating scattered contradictory guides:

- `README.md`: concise supported features, installation, quickstart and current limitations.
- `SECURITY.md`: OAuth, scope/consent, secret handling, SSRF model, private disclosure instructions.
- `docs/architecture/oauth-deployment.md`: builtin vs external identity provider, flows, key lifecycle, security trade-offs and threat model.
- `docs/mcp/chatgpt-setup.md`: required HTTPS deployment and concrete connector instructions with known limitations.
- `docs/mcp/claude-setup.md`: remote and stdio configuration, token and transport troubleshooting.
- `docs/operations/deployment.md`: secrets, TLS, containers, maintenance and rollback.
- `docs/operations/runbook.md`: incidents, token compromise, key rotation, webhook abuse, failed exports and data restore.
- `docs/operations/final-security-verification.md`: evidence for each issue, tests and conclusions.
- `IMPLEMENTATION_PROGRESS.md`: each workstream marked completed/blocked with links to commits.
- `PRODUCTION_READINESS_REPORT.md`: objective, current GO/NO-GO and explicit outstanding external prerequisites.
- `CHANGELOG.md`: user-visible changes, migrations and compatibility impacts.

Do not state any live integration passed if no external client was used.

## 10. Definition of done / acceptance checklist

- [ ] SEC-01: production builtin OAuth has a durable signing key and fail-fast checks.
- [ ] SEC-02: client scope enforcement, user consent and CSRF safety are tested.
- [ ] SEC-03: refresh token rotation, replay handling and revocation are tested, or documented as unsupported without advertising the grant.
- [ ] SEC-04: webhook transport resists DNS rebinding, disallowed redirects and internal IP connections.
- [ ] SEC-05: authorization-code consumption and token revocation cannot be abused to affect other users/clients.
- [ ] MCP-01: stdio protocol works against a real local client or SDK.
- [ ] MCP-02: remote HTTP MCP works end-to-end against a real SDK with OAuth.
- [ ] MCP-03: concurrent remote requests maintain actor/tenant isolation.
- [ ] MCP-04: ChatGPT and Claude actual integration outcomes are recorded honestly.
- [ ] OPS-01: TLS routing, secrets, persistent artifacts and safe restart are checked.
- [ ] OPS-02: staging backup and restore rehearsal passes or remains an explicit production blocker.
- [ ] QA-01: full CI green with real MongoDB+Redis integration and security tests.
- [ ] QA-02: current docs, changelog, migration notes and operational runbooks committed.
- [ ] QA-03: no known P0 production blockers remain.

## 11. Final response required from Gemini

Provide a final machine-checkable report with:

1. Baseline and final commit SHAs, branch and ordered commit summaries.
2. Each confirmed issue, its root cause, code files changed and test demonstrating the fix.
3. Full list of test commands with **actual** totals, coverage, CI run URLs and skipped tests.
4. Security validations and any accepted residual risks.
5. Working local development, Docker staging and public HTTPS configuration examples (all secrets redacted).
6. MCP and OAuth endpoint URLs and one safe example flow for stdio, generic HTTP client, ChatGPT and Claude.
7. Explicit external-client status: `VERIFIED`, `FAILED`, or `BLOCKED_EXTERNAL_VALIDATION` for each client.
8. An evidence-based recommendation: `NO_GO`, `STAGING_GO`, or `PRODUCTION_GO`, including missing operator actions.
9. Any features not completed, why they are blocked, and exact follow-up work.

**Execution directive:** Implement all independently actionable tasks now. Continue through every workstream without requiring a new prompt. Stop only before actions that would modify a live production environment or require user-supplied credentials/approval. The final product must be verified working software, not merely a description of intended improvements.
