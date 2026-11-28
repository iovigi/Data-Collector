# Architecture — Million-Record Safe Search, Counts, and Nested Explorer

## 1. Core Separation Principle
MongoDB remains the **sole authoritative data store** for `records` and `collections`.
All new search, count, and nested-exploration features are strictly **read-only** on the source MongoDB database:
- **Tiered Counts (`CollectionCountService`)**: Redis-backed cache (`dc:counts:v1:...`) with `SET NX EX` stampede locks and a global concurrency semaphore (`COLLECTION_COUNT_MAX_CONCURRENT=1`). Falls back to index-verified, `maxTimeMS`-bounded exact counts on explicit single-collection demand, and `pending`/`unavailable` in batch mode (never N concurrent `count_documents()` calls).
- **Structured Query Planner (`search_planner.py`)**: Inspects existing source indexes via `list_indexes()` (read-only), enforces `workspace_id`, `project_id`, `collection_id`, `deleted_at` scope, blocks unindexed broad `contains` regex scans (`422 QUERY_NOT_INDEXED`), and rejects unapproved sort fields.
- **External Full-Text (`SearchBackend` + `FulltextSearchService`)**: Pluggable isolated engine (`disabled` by default; `memory` for tests/local dev; `meilisearch` for self-hosted Windows/Docker/Linux). Why MongoDB `$text` was rejected: building a `$text` index on millions of existing `records` causes heavy write/lock/RAM pressure and violates the no-source-index-modification contract.
- **Authoritative Rehydration**: Every external full-text hit is re-fetched by `_id` from MongoDB `records` with `(workspace_id, project_id, collection_id, deleted_at=None)` so soft-deleted or unauthorized records are never returned even if the external index is stale.
- **Windows / IIS Hosting**: Served through the existing single-process WSGI pipeline (`data_collector/hosting/iis_app.py`) and Vite SPA (`web/dist`), with no Node SSR server or public search-engine exposure.
