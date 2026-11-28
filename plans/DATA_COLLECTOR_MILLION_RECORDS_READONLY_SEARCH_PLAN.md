# Data Collector 2.0 - Million-Record Safe Search, Counts, and Nested Data Explorer

**Implementation specification for Gemini**  
**Repository:** `https://github.com/iovigi/Data-Collector`  
**Audit baseline:** `main` commit `b82a8ef1ddab5afa3d1aa2bf2a20d1341f69a03b` (verify the current HEAD before coding)  
**Priority:** Protect existing production data above all other objectives  
**Execution mode:** Implement end-to-end, test on synthetic data, do not stop between milestones unless an operator decision is essential.

---

## 0. NON-NEGOTIABLE DATA PROTECTION CONTRACT - READ FIRST

The owner has **millions of existing records** and explicitly requires **NO modification whatsoever** to existing data or data schemas. This instruction overrides convenience, migrations, optimization shortcuts, and any preexisting code paths that would alter stored data.

### 0.1 Hard prohibitions

1. Never delete, truncate, drop, rename, compact, rewrite, normalize, bulk-update, or re-import existing MongoDB documents to implement this plan.
2. Do not change any field value, shape, type, BSON representation, identifier, timestamps, retention setting, `schema_json`, `searchable_fields`, `sortable_fields`, `schema_version`, membership, or collection metadata in existing production collections.
3. Do not create, drop, rebuild, or modify **any index on existing MongoDB collections** without a separate explicit written approval. An index is not a document schema change, but building one on millions of records may cause significant resource pressure; therefore this plan deliberately prohibits automatic source-index changes.
4. Do not run `db.records.createIndex`, `db.records.dropIndex`, MongoDB `$text` index construction, collection-wide `$regex` scans, Atlas Search index construction on existing data, unbounded `$lookup`, or any unrestricted exact `count_documents()` just to render UI cards.
5. Do not call existing collection deletion, schema migration `apply`, record delete, TTL reconfiguration, or import replay paths from new read-only features.
6. Do not write to the source records or metadata as part of search indexing. Derived indexes and count caches must live in an **isolated auxiliary store** outside the source MongoDB database/collections. No schema extensions to `records` or `collections`.
7. Do not auto-run `ensure_indexes()` or any implicit migration against production source databases from a new search/index worker; audit existing startup behavior and fail safe if an existing index bootstrap would mutate source indexes.
8. Do not require a maintenance window, MongoDB restart, data copy-back, or re-ingestion of source records as a deployment prerequisite.
9. Do not assume a replica set, oplog, change streams, managed Atlas Search, MongoDB administrative privileges, or a particular external search service is already available.
10. Never use invented count numbers, misleading approximate totals labeled as exact, silent result truncation, or search results from a different tenant.

### 0.2 Allowed actions

- Read existing MongoDB records using tightly bounded, authorized, index-aware queries.
- Inspect current index definitions with `list_indexes()` and use bounded `explain()`/execution statistics against representative **non-destructive** queries.
- Create **new application code**, isolated configuration, new REST endpoints, frontend components, test files, and operational documentation.
- Store derived full-text index entries, optional cached counts, indexing cursors, and metrics **only in separately configured auxiliary storage** (for example dedicated search engine plus Redis or a separate dedicated MongoDB auxiliary database, provided permissions and connection are isolated).
- Build an external search index incrementally with strict resource budgets; no source writes.
- Use existing compound source indexes where available, without changing them.
- Run all data-modifying integration tests exclusively against throwaway test databases populated with synthetic data. Never target a real shared environment.

### 0.3 Operator permission boundaries

- It is permitted to deploy the new code only after read-only safeguards and tests pass.
- Enabling a high-volume initial external indexing/backfill requires an explicit operator-controlled feature flag and separate manual invocation. The code may be installed with full-text unavailable until indexed safely.
- Installing an external search engine, increasing memory/disk, changing IIS settings, granting permissions, or altering source MongoDB indexes requires the appropriate operator approval; do not assume the runtime permits it.
- If existing source indexes do not support safe, bounded reads, **stop that affected feature and report the blocker**. Do not silently run a collection scan or create an index.
- The user wants one autonomous implementation; only stop for actual external access/authorization decisions, never for normal coding choices.

### 0.4 Proof of non-modification

Before and after validation, capture source database inventory, relevant collection counts where obtainable safely, index specifications, schema registry snapshots and document samples/hashes from a carefully bounded random selection. Source counts should never be computed with unbounded scans to establish the audit baseline. Compare snapshots, source operation command traces, and database profiler evidence where available. Require a dedicated read-only MongoDB credential for the indexing reader (read-only role on the source DB) and preferably for the new count/search read endpoints. The service's existing write-capable credential can remain for existing functionality; do not use it to index.

**A production backup and restore plan must be documented before rollout. Do not use the backup as a substitute for the no-write invariant.**

---

## 1. User goals and done definition

The user wants:

1. **Record count on every logical collection** in the collection list/cards and inside Data Explorer, with a precise indication of exact versus cached/estimated/stale counts, without blocking the interface or scanning millions of records.
2. **More flexible searching** over existing fields and nested fields, including typed filters, compound AND/OR/NOT, ranges, exact matches, field existence, arrays, dates, sensible sort, and saved searches, while preserving Safe Query DSL protections.
3. **Readable nested JSON/BSON visualization** when opening a collection, with expandable objects/arrays, paths, type badges, useful preview columns, detailed tree view, safe copy/export, and virtualized rendering.
4. **Full-text search across millions of existing records** that does not cause MongoDB collection scans, unpredictable memory consumption, database stalls, or unbounded fan-out. Full-text must work over existing data without rewriting it.
5. Backward compatibility: REST APIs, MCP tools, IIS/Windows hosting route, existing Vite admin SPA, existing auth, and current records must continue to work.

**Done:** green CI, realistic independent integration tests, the primary MongoDB source shows no writes by new features, source read budgets demonstrably bounded, new UI validated against nested synthetic examples and at least one multi-million *synthetic* load/performance scenario or a carefully documented staged equivalent, and full-text results always tenant-authorized and clearly show indexing freshness.

---

## 2. Confirmed repository architecture and code-specific audit

Inspect at current HEAD before implementation; this is a code-based baseline, not a license to assume the code has not changed.

### 2.1 Storage model

- All logical collections' records are stored in the shared physical MongoDB `records` collection, with `workspace_id`, `project_id`, `collection_id`, `deleted_at`, `data`, `_id`, and timestamps.
- Existing source compound indexes in `data_collector/infrastructure/mongo.py` include `(workspace_id, project_id, collection_id, deleted_at, _id)` and `(workspace_id, project_id, collection_id, deleted_at, created_at DESC, _id DESC)`.
- Do not interpret one logical collection as a separate MongoDB collection. Search/count predicates must retain **all three tenant scope IDs** and active/trashed semantics.
- `RecordRepository.count_for_collection()` currently performs two `count_documents()` operations with no explicit max-time cap; the destructive `CollectionDeletionService._dependents()` calls it for deletion preflight. Do not reuse this as an eager UI count provider.
- `RecordRepository.count()` uses `count_documents(query,maxTimeMS=...)`, but this is an expensive exact count in some circumstances; time budget does not make it safe to call hundreds of times concurrently.
- `RecordRepository.find_page()` uses keyset cursors and maxTimeMS, but it contains `contextlib.suppress(Exception)` around `cur.max_time_ms(...)`; remove fail-open timeout configuration for new paths and test all failure paths.
- `compile_filter()` in `data_collector/services/query_dsl.py` already supports `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `exists`, `contains` plus logical AND/OR/NOT, dotted-path syntax, depth/predicate limits, and typed date metadata. `contains` compiles to an escaped case-insensitive regex; this is **not scalable full-text** and must not be used as a fallback over millions of records.
- `RecordService.search_records()` supports projections, sort and cursor pagination, and `GET/POST /api/v1/collections/<cid>/records[/search]`.
- `AnalyticsService` uses bounded aggregations, maxTimeMS, allowDiskUse=False; keep the safety rules and avoid invoking heavy aggregations for count cards.
- The admin client now uses a **Vite SPA served through the Python API/IIS hosting path**, rather than a permanently running Next.js server. Verify current `web` tooling; do not reintroduce a Node production server or reverse proxy.
- `web/app/w/[workspaceId]/collections/page.tsx` lists cards without counts; `web/app/w/[workspaceId]/collections/[collectionId]/data/page.tsx` has schema-driven table columns limited to the first six top-level fields, a safe filter UI, and flat JSON editing.
- `data_collector/api/v1/collections.py` currently provides collection get/list/edit and destructive delete endpoints. New read-only work must be kept separate from deletion flows.
- MCP and REST authorization rely on shared policy services, including workspace/collection restrictions; do not bypass these by querying MongoDB directly from routes.

### 2.2 Baseline deliverables

Produce `docs/search/BASELINE_AUDIT.md` with:
- Current HEAD SHA, branch, runtime modes (IIS WSGI bridge, CLI, Vite), application dependency graph.
- Actual current paths/routes, method contracts, query DSL, response types, list pagination, auth behavior, relevant source indexes, expected record sizes, and server capabilities.
- A table of high-risk existing queries (`contains`, exact counts, arbitrary sort, aggregate, deletion preflight), whether they can become collection scans, and which route calls each.
- Evidence that no production source MongoDB write permissions are needed for newly introduced read-only features.

If earlier conclusions conflict with current code, adapt implementation and document the difference.

---

## 3. Architecture decision: separated source-of-truth and derived search layer

### 3.1 Principles

- MongoDB remains the **sole authoritative data store**.
- A **separate full-text index** is a derived, replaceable, eventually consistent read model.
- The external index stores the minimum necessary text and references, never canonical records.
- Search engine candidates: self-hosted **OpenSearch** or **Meilisearch** (pick based on observed Windows/IIS environment, available RAM/disk, feature requirements and operational feasibility). Do not require Atlas Search or modify source Mongo indexes.
- The implementation MUST expose a `SearchBackend` abstraction so the backend can run with `disabled` backend, test fake backend, and one real backend. Do not implement multiple production search engines unless time permits after core validation.
- If the server cannot host a search engine safely, ship the indexed-search integration behind a disabled-by-default feature flag with clear setup steps. Do **not** substitute a broad MongoDB regex query.

### 3.2 Logical topology

```text
Browser Vite SPA (served by existing Python/IIS application)
    |
    +-- GET  /api/v1/collections/{cid}/record-count
    +-- POST /api/v1/collections/counts
    +-- POST /api/v1/collections/{cid}/records/search  [safe structured DSL]
    +-- POST /api/v1/collections/{cid}/records/fulltext  [external indexed search]
    +-- GET  /api/v1/collections/{cid}/search/status
    |        |
    |        v
    |      Flask auth/policy + bounded query planner
    |        |                          |
    |        v                          v
    |    MongoDB (READ ONLY for new     SearchBackend (external index)
    |    search/count pathways)           |
    |        ^                          Redis/dedicated auxiliary store
    |        |                          (count cache, indexing checkpoints)
    +-- Data Explorer nested read-only visualization

Separate opt-in low-priority indexer with read-only Mongo credential
  -> deterministic tenant-scoped keyset incremental scan, strict throttling
  -> external search index (documents derived from source)
  -> progress/freshness metrics; optional independently configured incremental sync
```

### 3.3 Data boundaries

Source Mongo read-only connection: `SEARCH_SOURCE_MONGODB_URI` (or separate limited secret) and `MONGODB_DB` pointing only to production source database for reads. The indexer credential must not have insert/update/delete/index privileges there.

External search document shape is internal and ephemeral, e.g. `{search_doc_id, workspace_id, project_id, collection_id, source_id, indexed_source_version, source_updated_at, active, text_fields, path_tokens, display_snippet}`. The index may not return a record to a caller until MongoDB record authorization and canonical active/version checks pass. Prefer minimize PII and allow configurable excluded fields. Avoid logging actual sensitive search terms or document bodies.

Protect the external index from direct public network exposure. Query it only through the authenticated API; enforce tenant filter in index query and **repeat scope check when hydrating MongoDB canonical docs**. Recheck `deleted_at=None`; stale hits must not reveal soft-deleted documents.

### 3.4 Non-goals

- No replacement of MongoDB with the search engine.
- No embeddings, AI search, vector index, OCR, document attachment extraction, or semantic search unless separately requested.
- No automatic rewriting/normalizing source documents.
- No MongoDB schema migration or new source indexes.
- No eager exact count on all collections on every page load.
- No uncontrolled wildcard indexing of every unknown field by default.

---

## 4. Collection count design (highest priority)

### 4.1 Requirements

Display active, trashed (optional), and total count for each logical collection with precise `accuracy` and freshness metadata, while supporting collections with 0 to millions of records.

Use a **tiered count mechanism**, not one `count_documents()` call per card:

- **Tier 0 - Fresh cached count:** from an existing isolated auxiliary cache, with TTL and version/timestamp; return immediately. Fields `value`, `accuracy`, `as_of`, `age_seconds`, `source`.
- **Tier 1 - Index-backed bounded exact:** on explicit refresh or low-cardinality bounded workloads only, after validating an appropriate existing compound index via index inventory/query plan. Use `maxTimeMS`, strict concurrency, cached result, and a per-request cost budget. A cached exact count is exact **as of** its timestamp, not necessarily live.
- **Tier 2 - Background low-priority computation:** when exact count would be expensive, schedule a deduplicated job with a per-tenant and global budget, return last-known cached count or `pending`. Do not block list calls. Existing count APIs must not be called in a fan-out.
- **Tier 3 - Unavailable/unknown:** when source read plan is not safe, return `value:null`, `accuracy:"unavailable"`, and reason. Never display `0` for unknown.

An optional **sidecar count materialization** can maintain counts from the external indexer or a dedicated auxiliary count ledger when indexing coverage is complete; mark as `indexed` and `as_of`, not automatically exact/latest. If a truly exact count is computed at a consistent snapshot, label accordingly; do not assert snapshot consistency without proper semantics.

**Important:** `estimated_document_count()` on the physical `records` MongoDB collection is NOT a per-logical-collection count and is prohibited as a substitute.

### 4.2 Count semantics

- `active`: `deleted_at == None` matches current application semantics (including missing field if Mongo interprets accordingly; document this).
- `trashed`: `deleted_at != None`; do not infer `total` by mixing inconsistent snapshots without labeling.
- Include `workspace_id`, `project_id`, and `collection_id` in all source queries, obtaining IDs from the authorized collection metadata.
- List counts should default to active only; optionally include trashed when selected.
- `total = active + trashed` only when both values come from comparable, documented scopes/freshness; otherwise `null`.
- A count influenced by ongoing writes is time-dependent; supply an `as_of` timestamp and allow stale labels.
- Access to trashed counts must satisfy the same policy as trash browsing.

### 4.3 Proposed REST contracts

**GET** `/api/v1/collections/{cid}/record-count?include_trash=false&refresh=false`

```json
{
  "collection_id": "...",
  "active": {"value": 2450317, "accuracy": "exact_as_of", "as_of": "2026-11-28T00:00:00Z", "source": "cache"},
  "trashed": null,
  "total": null,
  "status": "ready",
  "refresh_available": true
}
```

**POST** `/api/v1/collections/counts` with `{ "collection_ids": ["..."], "include_trash": false }` (max 25 or configurable hard cap). Must authorize each ID; return only allowed counts; use batch cache multi-get, never N concurrent source count scans.

```json
{"items":[{"collection_id":"...","active":{"value":null,"accuracy":"pending","as_of":null,"source":"background"},"status":"pending"}]}
```

**POST** `/api/v1/collections/{cid}/record-count/refresh` returns `202 Accepted` when a queued bounded refresh is allowed and `429` or `503` with clear `Retry-After` if not. Explicitly authenticated read permission; this endpoint schedules auxiliary-only work, never writes source data.

Contracts should use Pydantic response models, typed TypeScript client, OpenAPI update, request-id support, and role-based rate limiting.

### 4.4 Caching and stampede protection

- Prefer existing Redis when available; namespaced keys `dc:counts:v1:{workspace}:{project}:{collection}:{kind}`; no sensitive global cache key collisions.
- Cache TTL: e.g. 5-30 minutes configurable; negative cache for unavailable source-index plans; no misleading instant precision.
- Batch API should not fan out more than e.g. 2 outstanding exact source count requests globally and 1 per tenant. Configure from environment, default conservative.
- Use Redis `SET NX EX` locks or equivalent deduplication to prevent thundering herd; lock ownership and timeout handled safely.
- Implement count jobs via existing RQ or dedicated worker only after proving API itself never issues unbounded expensive query on page load.
- On known application mutations, invalidate or mark auxiliary counts stale without modifying existing source documents. Do not silently add an unverified `$inc` ledger that can drift under external ingestion.
- If existing external writers bypass the application, design reconciliation and freshness; never rely solely on UI mutation events.

### 4.5 Protection against expensive count queries

- Inventory existing source indexes using read-only API. Verify the compound prefix matches scope and deleted status.
- Define safe plan as an **observed** index-bounded, controlled operation, not merely a syntactically matching filter.
- For a massive count, even an IXSCAN may touch millions of keys. Enforce maxTimeMS, work-concurrency cap, query cancellation where supported, and fallback to `pending/unavailable`.
- Never run `count_documents()` on every request to `GET /projects/{pid}/collections`, `GET /workspaces`, or the Collections cards screen.
- Disable or rate-limit source exact refresh if DB is under sustained load; instrumentation must expose cost without leaking data.
- Explicit acceptance: opening a page with 100 collections should never generate 100 source count queries.

---

## 5. Flexible structured search without full scans

### 5.1 Preserve Safe Query DSL

Extend existing `compile_filter()` and Pydantic request schemas only with validated operations that can execute safely on supported source indexes or via the external index; do not accept raw Mongo operators from users.

Support, as appropriate:
- Exact scalar comparisons, numeric and ISO date ranges, `in`, `exists`, `not`, `and`, `or`, `ne`.
- Nested dotted paths with field-specific allowlists and configurable maximum depth.
- Array membership (`array_contains` for scalar membership, optionally `elem_match` with a constrained subpredicate), carefully validate element semantics and value types.
- Null vs missing distinction, boolean type-aware inputs, date UTC handling, ObjectId, escaped strings, and explicit default operator semantics.
- Prefix match only where an appropriate index exists; prohibit arbitrary case-insensitive regex over huge source records.
- A source-text `contains` query must be rejected (HTTP 422 `QUERY_NOT_INDEXED` / HTTP 409 depending existing envelope conventions) when no bounded safe index path exists; offer external full-text instead.
- Add `between` only as a validated translation into supported range filters; no raw `$expr`, `$where`, arbitrary regex, or user-supplied aggregation pipelines.

### 5.2 Query planner / safety gates

Introduce `data_collector/services/search_planner.py`:

`plan_search(actor, collection, normalized_filter, sort, requested_fields) -> SearchPlan` with explicit `mode` (`source_indexed`, `external_fulltext`, `rejected`), selected existing index evidence, estimated bound, maxTimeMS, pagination strategy, and refusal reason. Plans must never contain a source write.

- Whitelist `workspace_id`, `project_id`, `collection_id`, `deleted_at` constraints and apply them before user predicates.
- Validate `searchable_fields` and nested property paths; **avoid treating every descendant path as automatically indexed**. Field allowed by schema is not the same as query indexed. Present UI operator availability by field.
- Validate sort field against `sortable_fields` and available safe index. Prevent arbitrarily sorting millions of rows in memory; no `allowDiskUse=True` fallback.
- Set hard query budgets and limits (`maxTimeMS`, <=100 records/page default 25, max filter bytes, depth, branches, field projection size, output bytes).
- Use stable deterministic keyset cursors bound to workspace/collection/filter/sort; no offset/skip pagination for deep pages.
- No unlimited result counts for structured search. `matched_count` should be omitted or labeled unavailable unless independently safe.
- Make failures predictable: 422 (invalid/unindexed field), 429 (rate limit), 503 (backend overloaded), 504/appropriate typed timeout error. No silent broadening.

### 5.3 Explain and load diagnostics (admin only)

Provide a sanitized `POST /api/v1/collections/{cid}/search/plan` for authorized admins; returns source/external mode, planned index and safety status, no raw Mongo pipeline or secret paths. Optional bounded `explain` only when enabled and safe. Never expose source DB admin endpoints to browser.

### 5.4 UI search builder

- Collection-aware field autocomplete (including discovered nested paths) grouped by type.
- Type-aware controls: bool dropdown, number editor, date range picker, arrays/value list, text query, null/missing toggles.
- Visual AND/OR groups with max nesting and per-group validation; ability to remove/reorder clauses.
- Clear difference between `Structured filters` and `Full-text search` tabs; display why a filter is unavailable.
- Optional JSON DSL advanced editor with pre-submit validation, examples and no raw Mongo syntax.
- Applied filter chips, clear-all, debounce, enter-to-submit, safe sorting, cursor state resets on filter changes.
- Save query integration using current Saved Query functionality without persisting unexpected schema changes.
- Keyboard and screen reader access; loading/timeout/empty/partial states.

---

## 6. Full-text search: external index only, bounded by design

### 6.1 Search capabilities

- Exact phrase search, multiword relevance, optional field-scoped search, conservative typo tolerance where supported, prefix/autocomplete only as separately rate-limited feature.
- Filters by authorized `workspace_id`, `project_id`, `collection_id`, `active`, safe scalar facets where indexed in external engine.
- Search nested arrays and objects via deterministic flattening into path-tagged textual fields, not indiscriminately stringify arbitrary enormous documents.
- Return per-hit field path, small escaped snippet, score (optional), record ID, and freshness context. Do not expose sensitive, unauthorized fields in snippet or index query response.
- Pagination via stable search-after/cursor primitives where available; never deep `from/size` paging with huge offsets. Cursor signed/bound to tenant/filter/query/engine/index generation.

### 6.2 Full-text data extraction and type handling

Implement `data_collector/services/search_document_builder.py`:

- Traversal maximum depth e.g. 8, max fields e.g. 200, max array elements e.g. 100, max single string e.g. 4 KiB, max extracted text per record e.g. 32 KiB. All limits configurable and tested.
- Preserve map path semantics: `details.address.city`, `tags[]`, `orders[].product.name`, escaped path segments for keys containing dots or special characters.
- Support dict, list, string, BSON ObjectId, dates, numbers, bool and null; index text values and optional human-readable numeric/date strings only if suitable. Skip binary/blob, base64 large values, secrets, and configured excluded path patterns.
- Prevent recursive/invalid structures causing stack or memory overflow; truncate safely and record `extraction_truncated` metadata **in external index only**.
- Normalize Unicode and whitespace for search terms without changing Mongo originals; casefold only in external index.
- Do not blindly index all PII. Implement configuration: allowed fields, excluded fields, opt-in sensitivity review per collection, and redacted snippets.
- Use bounded batch memory; no in-memory list of all records.

### 6.3 Index names and isolation

Namespaced external indexes, e.g. `dc-{env}-{schema_generation}` with an unambiguous immutable internal ID and separate tenant filtering. If engine supports one index per tenant/collection, evaluate shard/metadata overhead at scale; default to bounded index count, not millions of indexes.

Never trust client-supplied `workspace_id` as authorization. Search route derives scope from the collection service after validating actor membership and allowed_collection_ids. During hydration, fetch only IDs explicitly returned by the search engine and validate exact source scope. Restrict maximum IDs per batch and strip stale/mismatched hits.

### 6.4 Full-text endpoint

**POST** `/api/v1/collections/{cid}/records/fulltext`

```json
{
  "query": "payment failed",
  "fields": ["details.message", "tags"],
  "filters": {"and": [{"field":"created_at","op":"gte","value":"2026-01-01T00:00:00Z"}]},
  "limit": 25,
  "cursor": null,
  "sort": "relevance"
}
```

Illustrative response:

```json
{
  "items": [
    {
      "record": {"id":"...","data":{"details":{"message":"Payment failed"}},"version":1},
      "highlights": [{"path":"details.message","text":"Payment failed"}],
      "score": 2.43
    }
  ],
  "next_cursor": null,
  "has_more": false,
  "index_status": {"state":"ready","coverage":"partial","indexed_records":1234,"as_of":"2026-11-28T00:00:00Z"},
  "result_total": {"value":null,"accuracy":"unavailable"}
}
```

- If indexing not enabled: return structured 503/409 `SEARCH_INDEX_NOT_READY`, no source-wide regex fallback.
- Cap query length e.g. 256 chars, tokens, concurrent requests, timeout, response size. Search backend queries should have circuit breakers and retry policy (bounded retries only for safe idempotent reads).
- Do not treat partial index coverage as exhaustive results; clearly display `coverage: partial`.
- Hydration is the final authoritative permission check, including `deleted_at` and optional workspace membership that may have changed since indexing.
- Do not silently change existing `records/search` semantics for API/MCP consumers; provide a new endpoint or explicitly compatible opt-in mode.

### 6.5 Initial index build, millions of records

- **Default off.** `SEARCH_BACKFILL_ENABLED=false` and `SEARCH_READS_ENABLED=false` until operator enables after checking disk, memory, network, DB CPU and IOPS.
- `dc-search-indexer plan --collection ... --dry-run` prints estimated cost and safe index choice, no writes to source or external engine.
- `dc-search-indexer backfill --collection ... --rate ... --batch-size ... --max-runtime ...` manually starts/resumes a bounded background job. Support a tenant/collection allowlist and global concurrency 1 by default.
- Query source with the existing compound `(workspace_id,project_id,collection_id,deleted_at,_id)` index using keyset `_id > checkpoint`; **never `.skip(n)`**.
- Project only required fields; use source read-only credentials; limit batch size e.g. 100-500 depending average payload. Hard-max bytes per batch, docs/sec, MB/sec, CPU threshold, memory watermark, server latency, and in-flight work.
- Persist `(collection_id,last_id,processed_count,attempts,checksum,started_at,updated_at,index_generation)` checkpoints in the **separate auxiliary database**. Do not store checkpoints in source `jobs` or `collections` if that violates no-source-writes requirement.
- Idempotent UPSERT keyed by tenant+collection+record ID in external index; retries must not duplicate results.
- Use exponential backoff+jitter, circuit breaker and automatic pause on source latency/503/CPU/IO pressure. Expose pause/resume/cancel through admin-only auxiliary controls.
- Rebuild new external index generation beside old generation and alias-swap only when coverage and counts reconcile; never touch source.
- Export a report of throughput, indexed count, skipped/oversize docs, source query time, search disk usage, index generation and freshness.
- Indexing can take hours/days; no requirement to finish in a single request or worker lifespan. UI must remain responsive.

### 6.6 Continuous updates and consistency

- Preferred incremental sync when source is a replica set and change streams are available with **read-only compatible privileges**: use resume tokens persisted externally; consume inserts, updates, soft deletes and hard deletes, carefully consider full-document lookup for updates and source read permissions.
- If change streams unavailable, use conservative bounded reconciliation via indexed `updated_at` and `_id` where the **existing** source index actually supports it; otherwise explicitly report incremental sync unsupported and require bounded scheduled re-scan/index refresh, never a hidden broad scan.
- **Important:** the currently observed indexes do not guarantee an efficient source-wide `updated_at` walk. Do not assume it is indexed.
- Handle events lost during backfill: initial scan + change stream catch-up with captured resume token (if supported) or non-overclaiming consistency mode. Never mark index `complete/current` when missed writes are possible.
- Handle source record deletions and revocations: search hits always rehydrated from source; stale entries filtered and eventually removed from external index.
- Source soft deletes map to `active=false` externally but source still controls truth.
- On changes of membership, source authorization at query/hydration time must take precedence over index state.

### 6.7 Operational safeguards

- Search engine and cache never exposed as public IIS routes or public ports.
- Separate resource quotas, retention for derived indexes, disk watermarks (pause indexing at high watermark), bounded heap/memory and CPU usage.
- Disable indexer if no spare capacity; never compete with source primary at unlimited speed.
- Health readiness: source DB readiness independent from external full-text readiness; degraded full-text must not bring down existing REST, UI or MCP core APIs.
- Background indexing must be independently restartable, with checkpoint and recovery tests.
- Graceful failure: backend search timeout produces typed error and user-friendly retry, no Mongo regex fallback.

---

## 7. Nested document visualization (read-only, no schema writes)

### 7.1 UX goals

Replace current table-first flat preview with **hybrid table + detail tree** optimized for heterogeneous nested records. Keep existing edit/create controls working as before, but visual inspection must never require editing or mutate records.

Recommended main layout:

```text
Collection: events  |  Active records: ~2,450,317 (cached, as of 04:10)
[Structured filters] [Full-text] [Saved queries]    [Search...]
[Field selector] [View: Table / Tree cards] [Page size: 25] [Export]

Table: ID | created_at | details.status | actor.name | tags | ... | View
Row click -> right-side details panel

Details panel:
  Metadata (id, version, timestamps, source)
  data  {object, 6 properties}
    details  {object, 3 properties}
      address  {object, 2 properties}
        city  "Sofia"  [copy]
    items  [array, 1,200 elements]  [expand first 50]
      [0] {object} ...
  [Copy value] [Copy path] [Copy JSON] [Expand one level] [Collapse]
```

### 7.2 Components

Create reusable typed components, e.g.:
- `web/components/data/JsonTree.tsx`
- `web/components/data/JsonTreeNode.tsx`
- `web/components/data/RecordDetailDrawer.tsx`
- `web/components/data/NestedValuePreview.tsx`
- `web/components/data/SchemaPathPicker.tsx`
- `web/components/data/FieldVisibilityPicker.tsx`
- `web/components/data/CountBadge.tsx`
- `web/components/data/FullTextSearchBar.tsx`
- `web/components/data/IndexStatusBadge.tsx`

Adapt current Vite/React module conventions, router, React Query, data API helper and CSS tokens. Do not reintroduce Next.js APIs or Node SSR.

### 7.3 Type-aware rendering

- Objects: collapsible, property count, visible key/path, preserve property ordering, distinguish missing/null/empty object.
- Arrays: length badge, first N elements by default, virtualize or chunk further elements, show nested objects compactly.
- Scalars: string safely escaped, numeric locale formatting toggle, booleans, null, dates ISO + localized, ObjectId, extended JSON when received.
- Very long strings: collapsed preview + expand, capped DOM render and copy controls.
- Deeply nested values: max initial depth and hard recursion limit, explicit `View more` rather than rendering all nodes.
- Inconsistent fields between documents: dynamic column discovery from bounded page sample, no source-wide schema inference; use existing `analytics/fields` only if its bounded behavior has been verified.
- Metadata separated from `data`, avoid mixing fields with identical names.
- Preserve exact underlying JSON for copy/export (subject to JSON/BSON serialization), never roundtrip through display formatting for write operations.
- Avoid rendering raw HTML from record values; prevent XSS, prototype pollution, path injection and huge clipboard memory spikes.

### 7.4 Table improvements

- Frozen ID/actions columns, optional horizontal scroll, column hide/reorder, nested path columns, responsive compact cards on mobile.
- Column selection persisted in browser local state keyed by workspace+collection+user (no source schema writes).
- Record drawer deep links where safe, accessible dialog focus trap, breadcrumbs by JSON path, search within **currently loaded record** only.
- Optional compare two records for read-only inspection using locally loaded documents; never load entire collection.
- Explicit `View raw JSON` and `View tree` tabs; raw JSON editor only under existing edit permissions, separate from read-only tree.
- Preserve working version conflict checks and existing schema validation on edits.
- Do not auto-expand 10,000 nested array nodes.

### 7.5 Field discovery and safe sampling

- Use schema_json for suggested fields where available, plus a bounded sample from the **current page** for heterogeneous structures.
- The field list must indicate `defined in schema`, `sampled`, `searchable in source`, and `available for external fulltext` separately.
- No automatic per-collection full-document scan for nested paths.
- Limit suggestions to e.g. 200 paths/depth 6 and cap sampled docs <=100, sampling reads within already retrieved page where possible.

---

## 8. Backend code changes - expected layout

Follow repository conventions; adjust names if current HEAD has changed.

```text
data_collector/
  api/v1/counts.py
  api/v1/fulltext.py
  api/v1/search_diagnostics.py
  api/schemas.py                  # add models; no source schema changes
  services/collection_count_service.py
  services/search_planner.py
  services/fulltext_search_service.py
  services/search_document_builder.py
  services/search_indexer.py
  infrastructure/search_backend.py
  infrastructure/search_backends/{disabled.py, chosen_engine.py}
  infrastructure/auxiliary_cache.py
  workers/search_indexer_main.py  # optional separate low-priority process
  config.py                       # additional flags with safe defaults
web/components/data/...           # nested viewer/search/count components
web/app/w/[workspaceId]/collections/page.tsx
web/app/w/[workspaceId]/collections/[collectionId]/data/page.tsx
web/lib/api/types.ts
web/lib/api/client.ts
tests/unit/...                     # planner, flattening, counts, limits
tests/integration/...              # auth, query safety, test engine
scripts/...                       # profiling, smoke test, audit

docs/search/
  BASELINE_AUDIT.md
  ARCHITECTURE.md
  API_CONTRACTS.md
  DATA_SAFETY_EVIDENCE.md
  LOAD_TEST_RESULTS.md
  OPERATIONS.md
  ROLLOUT_AND_ROLLBACK.md
  IMPLEMENTATION_REPORT.md
```

### 8.1 Dependency injection

- Extend `Container` with count service/search service read-only clients and independent connection lifecycle.
- Do not construct search client per request. Keep pool sizes conservative.
- Search feature disabled -> existing APIs/health still start; no missing DLL or service should crash the API.
- New endpoints use `require_auth(is_mutation=False)` and enforce `Scope.RECORDS_READ` plus collection policy. Scheduling refresh/index jobs should have stronger management scope.
- Resource restriction via API keys and OAuth workspace-bound MCP identities must be honored identically.
- Register new blueprints in `data_collector/api/v1/__init__.py`; update OpenAPI and tests.

### 8.2 Suggested config knobs (names illustrative)

```env
COLLECTION_COUNTS_ENABLED=true
COLLECTION_COUNT_CACHE_TTL_SECONDS=900
COLLECTION_COUNT_MAX_TIME_MS=1000
COLLECTION_COUNT_MAX_CONCURRENT=1
COLLECTION_COUNT_BATCH_MAX=25
COLLECTION_COUNT_BACKGROUND_REFRESH=false

STRUCTURED_SEARCH_MAX_TIME_MS=1500
STRUCTURED_SEARCH_MAX_PAGE_SIZE=100
STRUCTURED_SEARCH_ALLOW_UNINDEXED=false
STRUCTURED_SEARCH_BLOCK_BROAD_CONTAINS=true

FULLTEXT_SEARCH_ENABLED=false
FULLTEXT_SEARCH_BACKEND=disabled
FULLTEXT_SEARCH_URL=
FULLTEXT_SEARCH_API_KEY=
FULLTEXT_SEARCH_TIMEOUT_MS=2000
FULLTEXT_SEARCH_MAX_CONCURRENT=4
FULLTEXT_SEARCH_MAX_QUERY_LENGTH=256
FULLTEXT_SEARCH_BATCH_HYDRATE_MAX=50
SEARCH_SOURCE_MONGODB_URI=
SEARCH_BACKFILL_ENABLED=false
SEARCH_BACKFILL_BATCH_SIZE=100
SEARCH_BACKFILL_MAX_DOCS_PER_SECOND=50
SEARCH_BACKFILL_MAX_BYTES_PER_SECOND=1048576
SEARCH_BACKFILL_MAX_CONCURRENT_COLLECTIONS=1
SEARCH_BACKFILL_PAUSE_ON_HIGH_DB_LATENCY=true
SEARCH_EXTERNAL_AUXILIARY_NAMESPACE=dc_search_v1
```

- These are conservative **starting values**, not performance guarantees; profile before increasing.
- Never print secrets in logs; redact URLs and key values in diagnostics.
- Validate all critical limits at process startup; fail closed on invalid configs.
- Do not make full-text engine required for API process startup.

---

## 9. Detailed acceptance test matrix

### 9.1 Data non-modification

1. Source credential used by indexer cannot `insert`, `update`, `delete`, `createIndexes`, `dropIndexes`, or modify collection validator. Prove with negative permission tests against a temporary disposable database, never by attempting destructive commands on production.
2. Source pre/post relevant index definitions identical.
3. Source user records/collection metadata unchanged after fulltext index/rebuild/query and count operations on **synthetic fixture DB**.
4. No automatic migration or `ensure_indexes()` with a write-capable source user on new feature startup.
5. Search index deletion or cache flush leaves source MongoDB fully intact and existing APIs functioning.

### 9.2 Counts

6. Count semantics active/trashed/unknown are correct on synthetic fixtures.
7. 1/100/1000 collection cards: no N source count queries in browser path; cache multi-get and in-flight deduplication verified.
8. Very large synthetic collection -> time-bounded exact count or `pending/unavailable`, never blocked UI/DB.
9. Empty collection => exact zero only if actually established; cache miss must not display zero.
10. Rate-limited refresh and inaccessible-collection IDs cannot leak counts.
11. Source counting obeys global concurrency and maxTimeMS; failures do not poison all UI cards.
12. Counts include freshness labels; screen readers announce exact/cached/pending.

### 9.3 Search security/correctness

13. Existing safe DSL compatibility; nested dotted syntax, operators, input type validation.
14. Any unindexed contains/prefix/sort plan is rejected or routed externally; never collection scan.
15. Huge query text, nested AND/OR > bound, `$where`, `$regex`, `$expr`, prototype paths, invalid cursor -> controlled 4xx.
16. Tenant A cannot search/count/inspect Tenant B; API keys with collection allowlists cannot access other collections; OAuth tokens with narrower scope cannot elevate.
17. Deleted records do not appear in active fulltext results even when external search index stale.
18. Exact query with a bounded index returns same ordered records as legacy safe search.
19. No leak through facets, total counts, snippets or error messages.
20. Search engine down => typed, fast error, source data unaffected, existing CRUD continues.

### 9.4 Nested renderer

21. Objects, arrays of objects, mixed arrays, null/missing, Unicode, dates, ObjectId, large strings and deeply nested payloads render correctly.
22. Nested values containing HTML/JS are escaped (XSS test).
23. Arrays 100k elements in a locally generated fixture do not create 100k DOM nodes; virtualization/chunking tested.
24. Copy JSON and path correctness; expanding/collapsing causes no API mutation.
25. Keyboard navigation, focus handling and mobile layouts tested; no massive render loops.
26. Pagination, edit version conflict, import/export and saved queries still work.

### 9.5 Indexer resiliency

27. Backfill defaults OFF; starting API does not automatically start scanning records.
28. Explicit controlled backfill reads source through existing index with bounded keyset pagination.
29. Checkpoint resume after interruption and duplicate retry is idempotent; rebuild external index without source writes.
30. 5xx/429/network errors trigger bounded retry/backoff/pause, not tight retry loops.
31. Missing source read index or excessive source latency causes safe pause/refusal.
32. Oversized records are truncated or skipped with visible metrics and no memory overflow.
33. Change stream unavailable -> operationally clear degraded freshness; no false `complete` status.
34. Run fulltext search during partial backfill; UI displays partial coverage and freshness.

### 9.6 Scale/performance gates

35. Use a disposable synthetic load fixture with a meaningful range, ideally >=1,000,000 records, without loading all docs into RAM at once. If hardware prevents such test, publish a rigorously measured smaller-scale profile and mark million-scale gate unverified.
36. Measure p50/p95/p99 API count-cache response, structured indexed search, fulltext query, document hydration, source Mongo query duration, peak memory, index size, CPU and IO.
37. During controlled backfill, measure Mongo baseline vs increased query latency and set explicit stop thresholds jointly with operator. Never claim hard 99p latency target without environment benchmarking.
38. Query stress with concurrent authorized tenants and large nested documents; assert strict resource caps.
39. No `COLLSCAN` in default approved source query plans; any failed plan must reject operation and log sanitized diagnostics.

### 9.7 Regression and deployment

40. `ruff`, `mypy`, `pytest`, dependency/security scans green.
41. Frontend `npm ci`, lint, TypeScript, unit tests, Vite production build green.
42. Backend API Docker build and IIS/WSGI deployment route smoke tested; no Node SSR requirement.
43. Playwright real browser: cards/counts, structured search, fulltext disabled/partial/ready, nested viewer, auth, mobile, accessibility.
44. Existing MCP tools continue working; optionally expose new tools for counts/fulltext only with read-only scopes and output size caps.
45. CI must include new jobs without weakening earlier checks; validate clean checkout and build.

---

## 10. Implementation stages and required artifacts

### S0 - Baseline, safety audit, verification

- Read all repository code paths listed above and actual current git HEAD.
- Record source schema/index snapshots via safe read-only tooling.
- Add feature flags default off for source-expensive operations and fulltext.
- Document no-write safety and test credential roles.
- **Gate:** no existing source data changed; baseline documentation committed.

### S1 - Count service and batch REST API

- Implement cache-first count service, exact-on-demand with planner and bounded timeouts, auxiliary background refresh, batch endpoint, auth tests.
- Audit deletion preflight count code separately: do not modify deletion semantics or invoke destructive endpoints.
- **Gate:** no per-card source count fan-out; safe semantics proven.

### S2 - Collection cards + Data Explorer header counts

- Add `CountBadge` with exact/cached/pending/unavailable indicators, as-of tooltip, manual refresh.
- Batch query count cards; do not render counts by re-requesting one URL per card on every re-render.
- **Gate:** responsive on 100 cards, bounded network/query load.

### S3 - Query planner and typed structured search

- Implement safe validation, field availability, nested type-aware filters, index awareness, cursor enforcement and deterministic failure paths.
- Keep existing API behavior unless it would violate production safety; introduce safer opt-in mode or flag and clearly document any changed errors.
- **Gate:** no unindexed scan in approved query set.

### S4 - Nested read-only viewer

- Reusable JSON tree with virtualization, table nested paths, detail drawer, raw JSON display, keyboard access, performance tests.
- **Gate:** nested arrays and huge local fixtures render without freezing browser.

### S5 - Search backend and safe extraction

- Implement interface, disabled fake and chosen real engine, strict field flattening, external index scope and hydration safeguards.
- Include storage and security resource notes for Windows/IIS.
- **Gate:** isolated index can be destroyed/rebuilt without source modification.

### S6 - Backfill and freshness

- Add explicit manual indexing CLI/worker, safe rate limits, checkpoint/resume, status, partial coverage, optional change streams only if supported.
- **Gate:** zero source writes and predictable bounded Mongo reads during synthetic backfill.

### S7 - Full-text endpoint and UI

- Build authenticated search endpoint, result snippets/path badges, search/status UI, missing-index and degraded-state behaviors.
- **Gate:** no Mongo regex fallback, stale/soft-deleted hits suppressed, tenant isolation.

### S8 - MCP/read-only parity (optional but preferred)

- Where useful, add `dc_get_collection_count` and `dc_fulltext_search` read-only tools, reusing same service authorization, output cap and freshness semantics. Update MCP contracts and guides.
- Do not bypass search limits or allow full-text tool to execute arbitrary Mongo queries.

### S9 - Performance testing and operational readiness

- Benchmark read load, external indexing impact, cache hit rate, failure degradation, and restore of auxiliary index from scratch.
- Test real MongoDB + Redis + external search engine integration using synthetic fixture; optional Windows/IIS staging validation.
- **Gate:** demonstrate source remains stable and search can be disabled instantly.

### S10 - CI, docs, safe rollout

- Green all CI jobs; document architecture, backups, exclusion/PII decisions, indexer runbook, rollback, and final report.
- No production backfill without explicit operator control.
- **Gate:** all tests pass, honest limitations reported, source untouched.

---

## 11. Rollout plan (operator-controlled)

1. **Code deployment only:** Deploy read-only counts UI, nested viewer and structured search improvements; keep external fulltext and backfill flags OFF.
2. **Count canary:** Enable cached counts for one workspace; examine Mongo slow query log and CPU, abort exact count refresh if expensive.
3. **Search engine provisioning:** Operator installs/approves external engine and secure local/network access; confirm disk/RAM budgets.
4. **Pilot index:** Explicitly index one small logical collection with a read-only Mongo credential, low rate, source latency alarms.
5. **Large index rollout:** Index larger collections one at a time; pause if source primary latency, IO, CPU or external disk pressure rises.
6. **Enable fulltext reads:** When index ready (or clearly labeled partial) enable UI/API only for indexed workspaces; perform cross-tenant/redaction checks.
7. **Continuous sync:** Activate only when change streams or provably safe alternative available; otherwise publish refresh limitations.
8. **Operational acceptance:** Review measured performance, cost, failure recovery and no-write evidence.

### Rollback

- Immediate flags: `FULLTEXT_SEARCH_ENABLED=false`, `SEARCH_BACKFILL_ENABLED=false`, `COLLECTION_COUNT_BACKGROUND_REFRESH=false`.
- Stop external index worker and disconnect external search service; existing records/CRUD must remain unaffected.
- Roll back application binary only if needed; no source schema migration rollback should exist because none was applied.
- Delete only isolated auxiliary index/cache if an operator approves. Never execute `dropDatabase`, `delete_many`, or `drop` against source DB.

---

## 12. Delivery and reporting contract for Gemini

On completion, commit code and deliver:

1. `docs/search/BASELINE_AUDIT.md` and `docs/search/DATA_SAFETY_EVIDENCE.md` proving the source read-only path and unchanged source schema/indexes.
2. `docs/search/ARCHITECTURE.md` with precise search engine selection, tradeoffs, why Mongo native text indexes were rejected, index read consistency, and Windows/IIS impact.
3. `docs/search/API_CONTRACTS.md` with real request/response payloads, errors, exact vs cached counts, cursor semantics, and auth rules.
4. `docs/search/OPERATIONS.md` with tested commands (PowerShell where relevant), external engine setup options, minimum resource requirements, read-only Mongo DB role, feature flags, pause/resume, dashboards, and failure modes.
5. `docs/search/LOAD_TEST_RESULTS.md` with hardware, dataset size, p50/p95/p99, source DB query stats, max memory, source index usage, and pass/fail (no fabricated results).
6. `docs/search/ROLLOUT_AND_ROLLBACK.md` with safe defaults and explicit operator approval points.
7. `docs/search/IMPLEMENTATION_REPORT.md`: checklist S0-S10, files changed, tests run and results, unverified gates, CI links, remaining risks, and production enabling steps.
8. Screenshots or Playwright artifact of Collections cards, fulltext state, tree view, nested arrays, filtered results, and mobile view if test environment supports rendering.

**Definition of completion:** working UI + backend + tests + documentation + green CI, with new high-volume features disabled safely by default until operator activation. Do NOT report 'production-ready at million-record scale' unless backed by real measured million-record evidence.

### 12.1 Final checklist before claiming DONE

- [ ] Existing MongoDB source documents unchanged.
- [ ] Existing schemas and source indexes unchanged.
- [ ] New index/cache only in separate auxiliary storage.
- [ ] Read-only Mongo credential enforced for indexing.
- [ ] No destructive operational commands.
- [ ] No 1-count-per-card synchronous database scan.
- [ ] Count precision, freshness, and unknown states visible.
- [ ] Typed structured search and nested field UI work.
- [ ] No unindexed broad regex/contains fallback.
- [ ] Nested tree handles huge records gracefully.
- [ ] Fulltext search is tenant-isolated and rehydrated from source.
- [ ] Indexer is off by default, resumable, throttled and pausable.
- [ ] Change capture or limitations are explicit.
- [ ] Search engine outage leaves normal application functional.
- [ ] Windows/IIS SPA hosting remains supported, no reverse proxy required.
- [ ] Backend, frontend, CI, security, and E2E regressions pass.
- [ ] Honest evidence published, and unverified gates labeled.

**Owner's overriding instruction:** "Do not change existing records or their schema in any way. There are already millions of valuable records and all of them must remain intact. Improve counts, search, full-text, and nested visualization without jeopardizing the database." 
