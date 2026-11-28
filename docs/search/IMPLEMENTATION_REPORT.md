# Implementation Report — Million-Record Safe Search, Counts, and Nested Data Explorer

**Baseline SHA:** `b82a8ef1ddab5afa3d1aa2bf2a20d1341f69a03b`  
**Date:** 2026-11-28  

## Stage Checklist (S0–S10)
- [x] **S0** — Baseline audit (`docs/search/BASELINE_AUDIT.md`) and safe-by-default config flags (`data_collector/config.py`)
- [x] **S1** — Tiered count service (`CollectionCountService`), `AuxiliaryCache` (Redis `MGET` + `SET NX EX` locks), and `/api/v1/collections/{cid}/record-count`, `/collections/counts`, `/record-count/refresh`
- [x] **S2** — `CountBadge` in `web/components/data/CountBadge.tsx`, batch-fetched on Collections cards and Data Explorer header
- [x] **S3** — `search_planner.py`, `array_contains` & `between` DSL operators, `422 QUERY_NOT_INDEXED` for broad `contains`, and `/api/v1/collections/{cid}/search/plan`
- [x] **S4** — Read-only nested viewer: `JsonTree.tsx` (50-item array chunking, XSS-safe escaping, depth cap), `NestedValuePreview.tsx`, `RecordDetailDrawer.tsx`, `FieldVisibilityPicker.tsx`
- [x] **S5–S7** — `SearchBackend` (`disabled`, `memory`, `meilisearch`), `search_document_builder.py`, `SearchIndexer` (`dc-search-indexer` CLI), `FulltextSearchService` with authoritative MongoDB hydration, `/records/fulltext`, `/search/status`, and `FullTextSearchBar.tsx`
- [x] **S8** — Read-only MCP tools `dc_get_collection_count` and `dc_fulltext_search`
- [x] **S9–S10** — Synthetic benchmark (`scripts/bench_search_and_counts.py`), unit/integration/component tests, and `docs/search/*` runbooks

## Remaining Risks & Unverified Gates
- **Million-record physical MongoDB + Meilisearch benchmark:** Not executed against a 1,000,000-record physical MongoDB + Meilisearch instance (`UNVERIFIED_AT_MILLION_SCALE`).
- **Incremental change-stream sync:** Explicitly disabled (`incremental_sync_supported=false`); periodic `dc-search-indexer backfill` is required after bulk writes until replica-set change streams are provisioned.
- **Operator activation:** `FULLTEXT_SEARCH_ENABLED=false` and `SEARCH_BACKFILL_ENABLED=false` remain off by default until operator provisioning.
