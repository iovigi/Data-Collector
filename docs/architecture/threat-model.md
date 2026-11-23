# Threat Model — Data Collector 2.0

## 1. Assets to Protect
- Tenant record data (`records` collection)
- Workspace, project, collection metadata and JSON schemas
- User credentials, JWT signing keys, API key hashes, OAuth tokens
- Audit logs (`audit_events`) and async import/export artifacts

## 2. Threat Scenarios & Mitigations
| ID | Threat | Mitigation |
|---|---|---|
| T1 | **Cross-tenant data access** via forged IDs or collection names | Mandatory `(workspace_id, project_id, collection_id)` filter in repository; 404 on unauthorized resource; no physical collection name from user input |
| T2 | **NoSQL / MongoDB operator injection** (`$where`, `$regex`, `$ne`, `__proto__`) | Safe Query DSL AST compiler with strict operator allowlist, field name validation, depth/branch caps, `maxTimeMS` |
| T3 | **Credential / secret compromise** (default `admin123`, fallback JWT key) | Fail-fast startup in non-dev/test without strong secrets; explicit `data-collector admin bootstrap` CLI; Argon2id hashing |
| T4 | **API key / token theft or replay** | High-entropy prefixed keys hashed with SHA-256 + constant-time compare; short-lived JWTs; refresh rotation & revocation |
| T5 | **Brute-force login & user enumeration** | Redis-backed rate limiting (fail-closed on mutations); uniform `401 Invalid credentials` response |
| T6 | **CSV formula injection on export** | Prefix cells starting with `=`, `+`, `-`, `@`, `\t`, `\r` with `'` on CSV export |
| T7 | **Prompt injection via stored records in MCP** | Tool outputs are structured JSON data; no credentials in descriptions/resources; strict schema validation and output size caps (256 KiB) |
| T8 | **Unauthorized destructive MCP actions** | Read-only default; two-stage delete (`dc_prepare_delete_record` short-lived signed intent token bound to actor, tenant, collection, record, version) |
| T9 | **SSRF via import sources or webhooks** | Reject arbitrary URLs/filesystem paths in MCP; only pre-approved source refs with private-IP/loopback blocking |
| T10 | **DoS via oversized payloads or unbounded queries** | 1 MiB JSON cap, 5 MiB / 500 items batch cap, 50 MiB import cap, page size <= 100, distributed rate limits |
