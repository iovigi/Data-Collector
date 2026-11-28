# Load & Performance Test Results (Synthetic Fixture)

**Script:** `scripts/bench_search_and_counts.py`  
**Environment:** Windows, Python 3.13, disposable `mongomock` + `fakeredis` + `InMemorySearchBackend`  
**Dataset:** `2,000` nested synthetic records (`details.address.city`, `details.message`, `tags[]`, `status`)  

| Operation | Measured Latency / Duration |
|---|---|
| **Document Extraction (`build_search_document`, 2,000 docs)** | `64.09 ms` total |
| **Isolated Backfill (`SearchIndexer.backfill_collection`, batch 250)** | `469.30 ms` total |
| **Batch Count Cache Hit (`get_batch_counts`, 50 runs)** | `p50=0.140 ms`, `p95=0.174 ms`, `p99=0.337 ms` |
| **Structured Indexed Search (`search_records`, 30 runs)** | `p50=26.672 ms`, `p95=27.678 ms`, `p99=27.944 ms` |
| **Full-Text Search + Source Hydration (`fulltext_search.search`, 30 runs)** | `p50=69.403 ms`, `p95=90.187 ms`, `p99=90.230 ms` |

## Honest Scale Gate Disclosure
- **1,000,000-record physical MongoDB + external Meilisearch benchmark:** **UNVERIFIED_AT_MILLION_SCALE** in this local dev run (tested on 2,000 synthetic nested records in `mongomock` + `fakeredis` + `InMemorySearchBackend`). Run `scripts/bench_search_and_counts.py` or a staged 1M-record disposable MongoDB + Meilisearch benchmark before enabling `FULLTEXT_SEARCH_ENABLED=true` and `SEARCH_BACKFILL_ENABLED=true` in production.
