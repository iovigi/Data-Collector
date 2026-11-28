# Rollout and Rollback Plan

## 1. Staged Rollout
1. **Deploy code with safe defaults:** `FULLTEXT_SEARCH_ENABLED=false`, `SEARCH_BACKFILL_ENABLED=false`, `COLLECTION_COUNT_BACKGROUND_REFRESH=false`.
2. **Verify Collections & Data Explorer UI:** Confirm batch counts return `pending` on cold cache without triggering N source DB scans, and nested JSON tree renders safely.
3. **Canary single-collection count refresh:** Trigger `POST /api/v1/collections/{cid}/record-count/refresh` on one collection and monitor MongoDB latency.
4. **Provision external engine (optional):** Start Meilisearch locally (`127.0.0.1:7700`), run `dc-search-indexer plan`, then pilot `dc-search-indexer backfill` on one small collection with a `read`-only MongoDB credential (`SEARCH_SOURCE_MONGODB_URI`).
5. **Enable full-text reads:** Set `FULLTEXT_SEARCH_ENABLED=true` after pilot coverage is verified.

## 2. Immediate Rollback
- Set `FULLTEXT_SEARCH_ENABLED=false`, `SEARCH_BACKFILL_ENABLED=false`, `COLLECTION_COUNTS_ENABLED=false` and recycle IIS/app pool.
- Stop `dc-search-indexer` if running.
- Existing CRUD, structured search, MCP core tools, and source MongoDB data remain completely unaffected (no source schema or index changes were applied).
