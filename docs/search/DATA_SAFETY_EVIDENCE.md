# Data Safety Evidence & Non-Modification Proof

1. **Zero Source Writes in New Code:**
   - `CollectionCountService` only calls `list_indexes()` and `count_documents(..., maxTimeMS=...)` on `source_db.records`.
   - `SearchPlanner` only calls `list_indexes()` (read-only).
   - `FulltextSearchService` only calls `find()` by `_id` with `(workspace_id, project_id, collection_id, deleted_at=None)`.
   - `SearchIndexer` only calls `find()` with keyset `_id > last_id` and `sort([("_id", ASCENDING)])` using the existing `(workspace_id, project_id, collection_id, deleted_at, _id)` index.
   - `create_app()` defaults `ensure_indexes=False` so API startup never mutates source indexes.
2. **Isolated Auxiliary Storage:**
   - Count cache and locks live in Redis (`dc:counts:v1:...`).
   - Full-text checkpoints live in Redis (`dc_search_v1:checkpoint:...`).
   - Derived full-text documents live only in the external `SearchBackend` (`disabled` by default).
3. **Dedicated Read-Only Credential Support:**
   - `SEARCH_SOURCE_MONGODB_URI` configures a separate MongoDB connection for `CollectionCountService`, `FulltextSearchService`, and `SearchIndexer`.
   - Recommended MongoDB role on source DB: built-in `read` role only (no `insert`, `update`, `remove`, `createIndex`, or `dropIndex`).
4. **Test Verification:**
   - `tests/unit/test_million_record_search.py`: verifies `build_search_document` does not mutate source records, strips secrets/base64 blobs, and `plan_search` rejects broad `contains` / unindexed sorts.
   - `tests/integration/test_counts_and_fulltext.py`: verifies batch counts do not leak cross-tenant data, `contains` returns `422 QUERY_NOT_INDEXED`, disabled fulltext returns `503 SEARCH_INDEX_NOT_READY`, and soft-deleted source records are suppressed during hydration.
