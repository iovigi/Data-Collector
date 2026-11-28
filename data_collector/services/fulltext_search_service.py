"""Authenticated, tenant-isolated external full-text search service.

Always rehydrates canonical documents from MongoDB `records` with strict
tenant scope and active (`deleted_at=None`) checks. Never falls back to
MongoDB collection-wide regex scans.
"""

from __future__ import annotations

import threading
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from data_collector.config import Settings
from data_collector.domain.exceptions import (
    SearchBackendUnavailableError,
    ValidationError,
)
from data_collector.domain.identities import Actor, Scope
from data_collector.infrastructure.auxiliary_cache import AuxiliaryCache
from data_collector.infrastructure.repositories.base import serialize_doc
from data_collector.infrastructure.search_backend import SearchBackend
from data_collector.services.collection_service import CollectionService
from data_collector.services.query_dsl import validate_field_name


class FulltextSearchService:
    """Orchestrates external full-text queries and authoritative source hydration."""

    def __init__(
        self,
        *,
        settings: Settings,
        source_db: Database[Any],
        collections: CollectionService,
        backend: SearchBackend,
        cache: AuxiliaryCache,
    ) -> None:
        self._settings = settings
        self._records_col = source_db.records
        self._collections = collections
        self._backend = backend
        self._cache = cache
        self._sem = threading.BoundedSemaphore(settings.fulltext_search_max_concurrent)

    def _checkpoint_key(self, collection_id: str) -> str:
        return f"{self._settings.search_external_auxiliary_namespace}:checkpoint:{collection_id}"

    def get_status(self, actor: Actor, collection_id: str) -> dict[str, Any]:
        self._collections.get_collection(actor, collection_id, required_scope=Scope.RECORDS_READ)
        cp = self._cache.get_json(self._checkpoint_key(collection_id)) or {}
        enabled = self._settings.fulltext_search_enabled
        ready = enabled and self._backend.is_ready()
        state = cp.get("state") or ("ready" if ready else "disabled")
        return {
            "collection_id": collection_id,
            "enabled": enabled,
            "backend": self._backend.backend_name,
            "ready": ready,
            "state": state,
            "coverage": cp.get("coverage", "none" if not cp else "partial"),
            "indexed_records": int(cp.get("processed_count", 0)),
            "as_of": cp.get("updated_at"),
            "index_generation": cp.get(
                "index_generation", self._settings.search_external_auxiliary_namespace
            ),
            "incremental_sync_supported": False,
        }

    def search(
        self,
        actor: Actor,
        collection_id: str,
        *,
        query: str,
        fields: list[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        sort: str = "relevance",
    ) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_READ
        )
        if not self._settings.fulltext_search_enabled or not self._backend.is_ready():
            raise SearchBackendUnavailableError(
                "External full-text search is disabled or not ready"
            )

        q_clean = query.strip()
        if not q_clean:
            raise ValidationError("Full-text query must not be empty")
        max_q = self._settings.fulltext_search_max_query_length
        if len(q_clean) > max_q:
            raise ValidationError(
                f"Full-text query exceeds max length of {max_q} chars"
            )

        if fields:
            props = col.get("schema_json", {}).get("properties")
            searchable = set(col.get("searchable_fields") or [])
            allowed = (set(props.keys()) | searchable) if isinstance(props, dict) and props else (
                searchable or None
            )
            for f in fields:
                validate_field_name(f, allowed)

        page_limit = min(
            limit or self._settings.default_query_page_size,
            self._settings.fulltext_search_batch_hydrate_max,
            self._settings.max_query_page_size,
        )

        acquired = self._sem.acquire(blocking=False)
        if not acquired:
            raise SearchBackendUnavailableError(
                "Full-text search concurrency limit reached; retry shortly",
                retry_after=5,
            )

        try:
            index_name = self._settings.search_external_auxiliary_namespace
            result = self._backend.search(
                index_name,
                workspace_id=col["workspace_id"],
                project_id=col["project_id"],
                collection_id=collection_id,
                query=q_clean,
                fields=fields,
                active_only=True,
                limit=page_limit,
                cursor=cursor,
                sort=sort,
            )
        finally:
            self._sem.release()

        # Authoritative hydration from MongoDB source with strict tenant + deleted_at=None checks.
        oids: list[ObjectId] = []
        hit_by_id: dict[str, Any] = {}
        for hit in result.hits:
            try:
                oids.append(ObjectId(hit.source_id))
                hit_by_id[hit.source_id] = hit
            except Exception:  # noqa: S112
                continue

        hydrated: dict[str, dict[str, Any]] = {}
        if oids:
            cursor_docs = self._records_col.find(
                {
                    "workspace_id": col["workspace_id"],
                    "project_id": col["project_id"],
                    "collection_id": collection_id,
                    "deleted_at": None,
                    "_id": {"$in": oids},
                }
            )
            for raw in cursor_docs:
                ser = serialize_doc(raw)
                if ser is not None:
                    hydrated[ser["id"]] = ser

        items: list[dict[str, Any]] = []
        for hit in result.hits:
            rec = hydrated.get(hit.source_id)
            if rec is None:
                # Stale/soft-deleted/mismatched-tenant hit: suppress silently.
                continue
            items.append(
                {
                    "record": rec,
                    "highlights": hit.highlights,
                    "score": hit.score,
                }
            )

        status = self.get_status(actor, collection_id)
        return {
            "items": items,
            "next_cursor": result.next_cursor,
            "has_more": result.has_more,
            "index_status": {
                "state": status["state"],
                "coverage": status["coverage"],
                "indexed_records": status["indexed_records"],
                "as_of": status["as_of"],
                "backend": status["backend"],
            },
            "result_total": {"value": None, "accuracy": "unavailable"},
        }
