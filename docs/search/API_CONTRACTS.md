# API Contracts — Counts, Structured Search Plan, and Full-Text Search

All endpoints require authentication (`Authorization: Bearer ...`, `X-API-Key`, or BFF session) and enforce `Scope.RECORDS_READ` (or `Scope.WORKSPACE_MANAGE` for `/search/plan`) plus collection allowlists.

## 1. `GET /api/v1/collections/{cid}/record-count?include_trash=false&refresh=false`
Returns cache-first count with precision (`exact_as_of` | `cached` | `indexed` | `pending` | `unavailable`), `as_of`, `age_seconds`, and `source`. Never returns `0` for unknown (`value: null`).

## 2. `POST /api/v1/collections/counts`
Request: `{ "collection_ids": ["..."], "include_trash": false }` (capped at `COLLECTION_COUNT_BATCH_MAX`, default 25).
Uses a single Redis `MGET`; omits unauthorized collection IDs; returns `pending` on cache miss (never fans out N source DB scans).

## 3. `POST /api/v1/collections/{cid}/record-count/refresh`
Returns `202 Accepted` when bounded refresh succeeds, `429` (`Retry-After: 15`) when concurrency/lock is busy, or `503` when counts are disabled or unsafe.

## 4. `POST /api/v1/collections/{cid}/records/search`
Existing Safe Query DSL endpoint, now gated by `search_planner.py`:
- Supports `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `exists`, `array_contains`, `between`, `and`, `or`, `not`.
- Rejects broad `contains` regex queries when `STRUCTURED_SEARCH_BLOCK_BROAD_CONTAINS=true` with `422 QUERY_NOT_INDEXED`.

## 5. `POST /api/v1/collections/{cid}/records/fulltext`
Request: `{ "query": "...", "fields": ["..."], "limit": 25, "cursor": null, "sort": "relevance" }`.
- Returns `503 SEARCH_INDEX_NOT_READY` when `FULLTEXT_SEARCH_ENABLED=false` or backend is unavailable (never falls back to MongoDB regex).
- Returns hydrated `items` (`record`, `highlights`, `score`), `index_status` (`state`, `coverage`, `indexed_records`, `as_of`), and `result_total: {"value": null, "accuracy": "unavailable"}`.

## 6. `GET /api/v1/collections/{cid}/search/status`
Returns `{ "enabled", "backend", "ready", "state", "coverage", "indexed_records", "as_of", "incremental_sync_supported": false }`.

## 7. `POST /api/v1/collections/{cid}/search/plan` (Admin / `WORKSPACE_MANAGE`)
Returns sanitized `SearchPlan` (`mode`, `selected_index`, `estimated_bound`, `max_time_ms`, `pagination_strategy`, `refusal_reason`, `warnings`).
