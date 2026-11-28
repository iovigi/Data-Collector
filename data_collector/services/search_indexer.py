"""Opt-in, throttled, checkpointed external search backfill indexer.

Strictly read-only against source MongoDB:
  - Uses keyset pagination `_id > last_id` over the existing compound index
    `(workspace_id, project_id, collection_id, deleted_at, _id)`.
  - Never calls `.skip()`, never writes to source MongoDB, and never creates indexes.
  - Persists checkpoints in isolated auxiliary storage (Redis or auxiliary DB).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING
from pymongo.database import Database
from pymongo.errors import PyMongoError

from data_collector.config import Settings
from data_collector.infrastructure.auxiliary_cache import AuxiliaryCache
from data_collector.infrastructure.search_backend import SearchBackend
from data_collector.services.search_document_builder import build_search_document

_KEYSET_FIELDS = ("workspace_id", "project_id", "collection_id", "deleted_at", "_id")


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class SearchIndexer:
    """Reads source records in bounded keyset batches and upserts into SearchBackend."""

    def __init__(
        self,
        *,
        settings: Settings,
        source_db: Database[Any],
        backend: SearchBackend,
        cache: AuxiliaryCache,
    ) -> None:
        self._settings = settings
        self._source_db = source_db
        self._backend = backend
        self._cache = cache

    def _checkpoint_key(self, collection_id: str) -> str:
        return f"{self._settings.search_external_auxiliary_namespace}:checkpoint:{collection_id}"

    def plan_backfill(self, collection_id: str) -> dict[str, Any]:
        """Dry-run inspection: checks source collection metadata and indexes with zero writes."""
        col = self._source_db.collections.find_one({"_id": ObjectId(collection_id)})
        if col is None:
            return {"collection_id": collection_id, "found": False, "safe_to_index": False}
        selected_index = None
        try:
            for index in self._source_db.records.list_indexes():
                keys = list(index["key"].items())
                if (
                    tuple(key for key, _ in keys[:5]) == _KEYSET_FIELDS
                    and all(direction in (1, -1) for _, direction in keys[:5])
                    and not any(
                        index.get(flag)
                        for flag in ("sparse", "partialFilterExpression", "hidden", "collation")
                    )
                ):
                    selected_index = index["name"]
                    break
        except PyMongoError:
            pass
        return {
            "collection_id": collection_id,
            "workspace_id": col["workspace_id"],
            "project_id": col["project_id"],
            "found": True,
            "safe_to_index": selected_index is not None,
            "selected_index": selected_index,
            "batch_size": self._settings.search_backfill_batch_size,
            "max_docs_per_second": self._settings.search_backfill_max_docs_per_second,
            "backend": self._backend.backend_name,
            "backfill_enabled": self._settings.search_backfill_enabled,
        }

    def backfill_collection(
        self,
        collection_id: str,
        *,
        batch_size: int | None = None,
        max_docs_per_second: int | None = None,
        max_runtime_seconds: float | None = None,
        reset: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        """Execute bounded, resumable backfill into external SearchBackend."""
        if not force and not self._settings.search_backfill_enabled:
            raise RuntimeError("SEARCH_BACKFILL_ENABLED is false; pass --force or enable in config")

        plan = self.plan_backfill(collection_id)
        if not plan.get("found"):
            raise ValueError(f"Collection '{collection_id}' not found")
        if not plan.get("safe_to_index"):
            raise RuntimeError(
                "Source records collection lacks required keyset index; refusing to scan"
            )

        ws_id = str(plan["workspace_id"])
        proj_id = str(plan["project_id"])
        index_name = self._settings.search_external_auxiliary_namespace
        if not self._backend.is_ready():
            raise RuntimeError("Configure an available external search backend before indexing")
        self._backend.ensure_index(index_name)

        cp_key = self._checkpoint_key(collection_id)
        saved_checkpoint = self._cache.get_json(cp_key) or {}
        cp = {} if reset else saved_checkpoint
        last_id_str: str | None = cp.get("last_id")
        processed_count = int(cp.get("processed_count", 0))
        truncated_count = int(cp.get("truncated_count", 0))
        started_at = cp.get("started_at") or _utc_iso()

        eff_batch = max(1, min(batch_size or self._settings.search_backfill_batch_size, 1000))
        eff_rate = max(1, max_docs_per_second or self._settings.search_backfill_max_docs_per_second)
        start_mono = time.monotonic()
        paused_reason: str | None = None

        while True:
            if (
                max_runtime_seconds is not None
                and (time.monotonic() - start_mono) >= max_runtime_seconds
            ):
                paused_reason = "max_runtime_reached"
                break

            query: dict[str, Any] = {
                "workspace_id": ws_id,
                "project_id": proj_id,
                "collection_id": collection_id,
                "deleted_at": None,
            }
            if last_id_str:
                query["_id"] = {"$gt": ObjectId(last_id_str)}

            q_start = time.monotonic()
            docs = list(
                self._source_db.records.find(query)
                .hint(plan["selected_index"])
                .sort([("_id", ASCENDING)])
                .max_time_ms(self._settings.max_query_time_ms)
                .limit(eff_batch)
            )
            q_ms = (time.monotonic() - q_start) * 1000.0
            if (
                self._settings.search_backfill_pause_on_high_db_latency
                and q_ms > self._settings.search_backfill_max_db_latency_ms
            ):
                paused_reason = f"high_source_latency_{int(q_ms)}ms"
                break

            if not docs:
                cp_payload = {
                    "collection_id": collection_id,
                    "last_id": last_id_str,
                    "processed_count": processed_count,
                    "truncated_count": truncated_count,
                    "started_at": started_at,
                    "updated_at": cp.get("updated_at") or _utc_iso(),
                    "index_generation": index_name,
                    "state": "ready",
                    "coverage": "complete",
                }
                self._save_checkpoint(cp_key, cp_payload)
                return cp_payload

            extracted: list[dict[str, Any]] = []
            for raw in docs:
                doc_out = build_search_document(raw)
                if doc_out.extraction_truncated:
                    truncated_count += 1
                extracted.append(doc_out.to_index_payload())

            self._backend.upsert_batch(index_name, extracted)
            processed_count += len(docs)
            last_id_str = str(docs[-1]["_id"])

            cp_payload = {
                "collection_id": collection_id,
                "last_id": last_id_str,
                "processed_count": processed_count,
                "truncated_count": truncated_count,
                "started_at": started_at,
                "updated_at": _utc_iso(),
                "index_generation": index_name,
                "state": "indexing",
                "coverage": "partial",
            }
            self._save_checkpoint(cp_key, cp_payload)
            cp = cp_payload

            min_batch_secs = len(docs) / float(eff_rate)
            elapsed = time.monotonic() - q_start
            if elapsed < min_batch_secs:
                time.sleep(min_batch_secs - elapsed)

        if cp.get("state") == "ready":
            return cp
        # A reset that has not indexed a batch yet must leave the old checkpoint intact.
        if reset and not cp and saved_checkpoint:
            return saved_checkpoint

        final_cp = {
            "collection_id": collection_id,
            "last_id": last_id_str,
            "processed_count": processed_count,
            "truncated_count": truncated_count,
            "started_at": started_at,
            "updated_at": cp.get("updated_at"),
            "index_generation": index_name,
            "state": "paused",
            "coverage": "partial",
            "paused_reason": paused_reason,
        }
        self._save_checkpoint(cp_key, final_cp)
        return final_cp

    def _save_checkpoint(self, key: str, checkpoint: dict[str, Any]) -> None:
        if not self._cache.set_json(key, checkpoint, ttl_seconds=None):
            raise RuntimeError("Could not persist the search checkpoint in Redis")
