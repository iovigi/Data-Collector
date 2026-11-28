# Operations Runbook — Counts & External Full-Text Search

## 1. Environment Flags (Safe Defaults)
```env
COLLECTION_COUNTS_ENABLED=true
COLLECTION_COUNT_CACHE_TTL_SECONDS=900
COLLECTION_COUNT_MAX_TIME_MS=1000
COLLECTION_COUNT_MAX_CONCURRENT=1
COLLECTION_COUNT_BATCH_MAX=25

STRUCTURED_SEARCH_MAX_TIME_MS=1500
STRUCTURED_SEARCH_BLOCK_BROAD_CONTAINS=true

FULLTEXT_SEARCH_ENABLED=false
FULLTEXT_SEARCH_BACKEND=disabled
SEARCH_BACKFILL_ENABLED=false
SEARCH_SOURCE_MONGODB_URI=mongodb://dc_search_ro:<password>@<host>:27017/data_collector?authSource=data_collector
```

## 2. Dry-Run Plan & Manual Backfill (PowerShell)
```powershell
# 1. Inspect source index safety (zero writes)
.\.venv\Scripts\dc-search-indexer.exe plan --collection <COLLECTION_ID> --dry-run

# 2. Run throttled, resumable backfill (requires SEARCH_BACKFILL_ENABLED=true or --force)
.\.venv\Scripts\dc-search-indexer.exe backfill --collection <COLLECTION_ID> --batch-size 100 --rate 50 --max-runtime 300
```

## 3. External Search Engine (Optional Self-Hosted Meilisearch)
- Run Meilisearch bound to `127.0.0.1:7700` (never expose publicly through IIS).
- Set `FULLTEXT_SEARCH_ENABLED=true`, `FULLTEXT_SEARCH_BACKEND=meilisearch`, `FULLTEXT_SEARCH_URL=http://127.0.0.1:7700`, and `FULLTEXT_SEARCH_API_KEY=<master-key>`.
- Minimum recommended resources for millions of records: 4+ GB RAM dedicated to Meilisearch and SSD storage >= 2x raw text size.

## 4. Incremental Sync Limitation
- `incremental_sync_supported` is explicitly reported as `false` until replica-set change streams are provisioned; re-run `dc-search-indexer backfill` on a schedule or after bulk ingestion.
