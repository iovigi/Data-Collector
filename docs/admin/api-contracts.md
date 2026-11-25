# Admin Dashboard API Contracts

All existing `/api/v1/*` endpoints are preserved. The following extensions were added in Stage S1:

## Capabilities & Membership
- `GET /api/v1/workspaces/{wid}/capabilities` — server-computed role, effective scopes, and UI feature flags.
- `GET /api/v1/workspaces/{wid}/members` — paginated workspace members with resolved email and role.
- `PATCH /api/v1/workspaces/{wid}/members/{principalId}` — update member role (last-owner protected).
- `DELETE /api/v1/workspaces/{wid}/members/{principalId}` — remove member (last-owner protected).
- `POST /api/v1/workspaces/{wid}/transfer-ownership` — transfer workspace ownership.
- `POST /api/v1/workspaces/{wid}/invitations` — create 7-day single-use hashed invitation link.
- `GET /api/v1/workspaces/{wid}/invitations` — list workspace invitations.
- `POST /api/v1/invitations/{invitationId}/accept` — accept invitation with token.
- `POST /api/v1/invitations/{invitationId}/revoke` — revoke pending invitation.

## Lifecycle, Jobs, Audit, Trash & M11 Management
- `PATCH /api/v1/workspaces/{wid}`, `POST /api/v1/workspaces/{wid}/archive`, `POST /api/v1/workspaces/{wid}/restore`
- `GET /api/v1/projects/{pid}`, `PATCH /api/v1/projects/{pid}`, `POST /api/v1/projects/{pid}/archive`, `POST /api/v1/projects/{pid}/restore`
- `GET /api/v1/workspaces/{wid}/jobs?status=&type=&limit=&cursor=`
- `GET /api/v1/workspaces/{wid}/audit?actor_id=&action=&decision=&limit=&cursor=`
- `GET /api/v1/collections/{cid}/records/trash?limit=&cursor=`
- `GET/PATCH/DELETE /api/v1/saved-queries/{sqid}`
- `GET/PATCH/DELETE /api/v1/workspaces/{wid}/webhooks/{hookId}`, `POST .../rotate-secret`, `GET .../deliveries`
- `GET /api/v1/workspaces/{wid}/dashboard/summary`

## Collection deletion (two-step, hard delete)
- `POST /api/v1/collections/{cid}/prepare-delete` — preflight, no data changes (counted as a **read** by the rate limiter). Returns
  `slug`, `status`, `records {active, trashed, total}`, `saved_queries {count, items[≤50]}`,
  `active_jobs {count, items[≤50]}` (queued/running jobs whose `params.collection_id` is this collection),
  `api_keys_restricted_to_collection`, a `confirmation_token` valid for 300 s and single-use, and a `correlation_id`.
- `DELETE /api/v1/collections/{cid}` with body `{"confirmation_token": "...", "confirm_slug": "<slug typed back>"}` —
  one request = **one write** against the per-principal write limit, regardless of record count. Returns
  `{collection_id, slug, deleted, correlation_id, records_deleted, saved_queries_deleted, jobs_cancelled, api_keys_detached, idempotency_keys_deleted}`.
- Errors: `404` collection not found or caller not a member · `403` missing `collection:delete`, collection-scoped API key,
  MCP actor, invalid/expired/foreign/already-used token · `422` typed slug does not match (token is **not** consumed; retype and retry).
- Authorization: new scope `collection:delete`. Granted to **owner** (all scopes) and **admin** roles; not to editor or viewer.
  An API key needs the scope explicitly in its `scopes` list *and* must not carry an `allowed_collection_ids` allowlist.
  Read-only MCP strips it, and the service refuses every MCP actor regardless of `MCP_ALLOW_WRITES` (no MCP tool exists for it).
- What is removed, in this order: collection flagged `status="deleting"` (hidden from listings, reads and writes return 404) →
  queued/running jobs set to `cancelled` → all records, active and trashed, in one `deleteMany({workspace_id, collection_id})` →
  saved queries → collection id `$pull`ed from API-key allowlists (a key left with `[]` keeps access to nothing; never widened to "all") →
  idempotency keys → the collection document → a final `deleteMany` sweep for records that raced in.
  Webhooks are workspace-scoped and schema migrations are not persisted, so neither holds a per-collection reference.
  If the process dies midway the collection stays hidden in `deleting`; run prepare + delete again to finish.
- Audit: `collection.delete_prepare` and `collection.delete` events with actor, slug, record count and `correlation_id`
  (shared by prepare and delete). Refusals are audited with `decision="deny"` and a `reason`; failures mid-delete with `decision="error"`.
- Capabilities: `features.can_delete_collections` is true only for owner/admin sessions that are not collection-scoped keys or MCP.
