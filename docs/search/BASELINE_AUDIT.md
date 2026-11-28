# Baseline Audit — Million-Record Safe Search, Counts, and Nested Data Explorer

**Audit Date:** 2026-11-28  
**Git Branch:** `main`  
**Audit HEAD SHA:** `b82a8ef1ddab5afa3d1aa2bf2a20d1341f69a03b`  

---

## 1. Runtime Modes & Application Topology

| Mode | Entrypoint | Notes |
|---|---|---|
| **IIS FastCGI / WSGI** | `data_collector/hosting/iis_app.py:build_application()` | Single-process WSGI: `CloudflareClientIPMiddleware` -> `PathDispatcher` (`/mcp`, `/oauth/*`, `/.well-known/*` -> ASGI bridge) -> Flask (`REST /api/v1`, BFF `/api/auth` + `/api/backend`, SPA static `web/dist`). No Node SSR server. |
| **Flask API** | `data_collector/app.py:create_app()` (`dc-api`) | Registers REST v1 blueprints (`data_collector/api/v1/__init__.py`), `/health/live`, `/health/ready`, `/metrics`, `/api/v1/openapi.json`. `ensure_indexes` defaults to `False` in `create_app()` and is `True` only in `run_api()` / `data-collector ensure-indexes`. |
| **Admin SPA** | `web/` (Vite 6 + React 19 + TypeScript + React Query + TanStack Table) | Built to `web/dist` (`npm run build`), served statically by `data_collector/bff/spa.py`, and communicates with Flask via `/api/backend/*` gated by `data_collector/bff/allowlist.py`. |
| **CLI & Worker** | `data_collector/cli.py` (`data-collector`), `data_collector/workers/main.py` (`dc-worker`) | Explicit CLI for `admin bootstrap`, `ensure-indexes`, `migrate-legacy`, and RQ worker. |

---

## 2. Storage Model & Source MongoDB Indexes

All logical collections share a single physical MongoDB `records` collection (`data_collector/infrastructure/mongo.py`):
- **Tenant & scope fields:** `workspace_id`, `project_id`, `collection_id`, `deleted_at` (`None` for active, timestamp for trashed), `data` (nested user payload), `version`, `created_at`, `updated_at`, `created_by`, `source`.
- **Existing `records` indexes (`data_collector/infrastructure/mongo.py`):**
  1. `(workspace_id ASC, project_id ASC, collection_id ASC, deleted_at ASC, _id ASC)`
  2. `(workspace_id ASC, project_id ASC, collection_id ASC, deleted_at ASC, created_at DESC, _id DESC)`
- **Invariant:** No source index modifications (`createIndex`, `dropIndex`, `$text`), no document rewrites, and no schema changes are permitted by this plan.

---

## 3. High-Risk Existing Queries & Routes

| Query / Method | Location | Callers / Routes | Risk at Million-Record Scale | Mitigation Plan |
|---|---|---|---|---|
| `RecordRepository.count_for_collection()` | `data_collector/infrastructure/repositories/record_repo.py` | `CollectionDeletionService._dependents()` -> `POST /collections/<cid>/prepare-delete` | Runs two `count_documents()` calls (`active` and `trashed`) with no `maxTimeMS`. | Leave deletion preflight isolated; **never** call it from UI collection cards or list endpoints. |
| `RecordRepository.count()` | `data_collector/infrastructure/repositories/record_repo.py` | `RecordService.count_records()` | `count_documents()` can still scan millions of index keys under concurrent fan-out. | Introduce tiered cache-first `CollectionCountService` with Redis TTL, `SET NX EX` stampede lock, global concurrency cap (`1`), and `COLLECTION_COUNT_MAX_TIME_MS`. |
| `compile_filter()` `contains` operator | `data_collector/services/query_dsl.py` | `POST /collections/<cid>/records/search`, `dc_query_records` | Compiles `contains` to `{"$regex": re.escape(val), "$options": "i"}` on `data.<field>`, which causes unindexed collection/IXSCAN scans over millions of records. | Add `search_planner.py` to reject broad unindexed `contains`/unindexed sorts when `STRUCTURED_SEARCH_BLOCK_BROAD_CONTAINS=true` (HTTP 422 `QUERY_NOT_INDEXED`), routing full-text needs to external `SearchBackend`. |
| `RecordRepository.find_page()` | `data_collector/infrastructure/repositories/record_repo.py` | `GET /collections/<cid>/records`, `POST /collections/<cid>/records/search` | Uses `contextlib.suppress(Exception)` around `cur.max_time_ms(...)`; arbitrary sort on unindexed `data.<field>` can exceed memory limits. | New search planner validates sort fields against indexed fields (`created_at`, `id`) or `sortable_fields` with strict bounds and explicit timeout handling (no fail-open). |
| `AnalyticsService` | `data_collector/services/analytics_service.py` | `POST /collections/<cid>/analytics/*` | Uses `allowDiskUse=False` and `analytics_max_time_ms`. | Keep isolated; do **not** call `analytics/fields` or aggregations to render collection count cards. |

---

## 4. Non-Modification & Credential Boundaries

- **Zero source writes:** All new count, structured search, full-text search, and indexer read pathways use read-only operations against `records` and `collections`.
- **Isolated auxiliary storage:** Cached counts and indexing checkpoints/locks live in Redis (`dc:counts:v1:...`) and/or a separate auxiliary store (`SEARCH_AUXILIARY_MONGODB_DB`), while full-text documents live in the external `SearchBackend` (`disabled` by default).
- **Separate read-only source credential:** `SEARCH_SOURCE_MONGODB_URI` supports a dedicated MongoDB user with `read`-only role on the source DB (`MONGODB_DB`) for the indexer and read-only search/count paths.
- **Safe defaults:** `FULLTEXT_SEARCH_ENABLED=false`, `FULLTEXT_SEARCH_BACKEND=disabled`, `SEARCH_BACKFILL_ENABLED=false`, `COLLECTION_COUNT_BACKGROUND_REFRESH=false`, `STRUCTURED_SEARCH_BLOCK_BROAD_CONTAINS=true`.
