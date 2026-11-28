"""Authenticated external full-text search with bounded canonical record hydration."""

from __future__ import annotations

import re
import threading
from typing import Any

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import ExecutionTimeout

from data_collector.config import Settings
from data_collector.domain.exceptions import SearchBackendUnavailableError, ValidationError
from data_collector.domain.identities import Actor, Scope
from data_collector.infrastructure.auxiliary_cache import AuxiliaryCache
from data_collector.infrastructure.repositories.base import serialize_doc
from data_collector.infrastructure.search_backend import SearchBackend
from data_collector.services.collection_service import CollectionService
from data_collector.services.query_dsl import (
    decode_cursor_payload,
    encode_cursor,
    query_signature,
    validate_field_name,
)


class FulltextSearchService:
    """Search the external index and hydrate only current, authorized records."""

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

    def _checkpoint(self, collection_id: str) -> dict[str, Any]:
        namespace = self._settings.search_external_auxiliary_namespace
        return self._cache.get_json(f"{namespace}:checkpoint:{collection_id}") or {}

    def _coverage(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        return {
            "coverage": checkpoint.get("coverage", "none"),
            "indexed_records": int(checkpoint.get("processed_count", 0)),
            "as_of": checkpoint.get("updated_at"),
            "backend": self._backend.backend_name,
        }

    def get_status(self, actor: Actor, collection_id: str) -> dict[str, Any]:
        self._collections.get_collection(actor, collection_id, required_scope=Scope.RECORDS_READ)
        checkpoint = self._checkpoint(collection_id)
        enabled = self._settings.fulltext_search_enabled
        available = enabled and self._backend.is_ready()
        if not enabled:
            state = "disabled"
        elif not available:
            state = "unavailable"
        elif not checkpoint.get("updated_at"):
            state = "not_indexed"
        else:
            state = checkpoint["state"]
        return {
            "collection_id": collection_id,
            "enabled": enabled,
            "ready": available and bool(checkpoint.get("updated_at")),
            "state": state,
            **self._coverage(checkpoint),
            "index_generation": self._settings.search_external_auxiliary_namespace,
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
        if not self._settings.fulltext_search_enabled:
            raise SearchBackendUnavailableError("External full-text search is disabled")

        q_clean = query.strip()
        if not q_clean or not any(character.isalnum() for character in q_clean):
            raise ValidationError("Full-text query must contain a letter or number")
        max_q = self._settings.fulltext_search_max_query_length
        if len(q_clean) > max_q:
            raise ValidationError(f"Full-text query exceeds max length of {max_q} chars")

        if fields:
            props = col.get("schema_json", {}).get("properties")
            allowed = set(col.get("searchable_fields") or [])
            if isinstance(props, dict):
                allowed.update(props)
            for field in fields:
                validate_field_name(re.sub(r"\[\](?=\.|$)", "", field), allowed or None)

        page_limit = min(
            limit or self._settings.default_query_page_size,
            self._settings.fulltext_search_batch_hydrate_max,
            self._settings.max_query_page_size,
        )
        checkpoint = self._checkpoint(collection_id)
        if not checkpoint.get("updated_at"):
            raise SearchBackendUnavailableError("This collection has no searchable index yet")

        index_name = self._settings.search_external_auxiliary_namespace
        signature = query_signature(
            col["workspace_id"],
            collection_id,
            {
                "project": col["project_id"],
                "query": q_clean,
                "fields": sorted(set(fields or [])),
                "limit": page_limit,
                "backend": self._backend.backend_name,
                "generation": index_name,
                "started_at": checkpoint.get("started_at"),
            },
            "fulltext",
            sort,
        )
        secret = self._settings.jwt_secret_key
        backend_cursor = None
        if cursor is not None:
            backend_cursor = decode_cursor_payload(
                cursor=cursor, secret=secret, expected_sig=signature
            )["v"]

        if not self._sem.acquire(blocking=False):
            raise SearchBackendUnavailableError(
                "Full-text search concurrency limit reached; retry shortly",
                retry_after=5,
            )

        try:
            result = self._backend.search(
                index_name,
                workspace_id=col["workspace_id"],
                project_id=col["project_id"],
                collection_id=collection_id,
                query=q_clean,
                fields=fields,
                active_only=True,
                limit=page_limit,
                cursor=backend_cursor,
                sort=sort,
            )
            hits = result.hits[:page_limit]
            oids = {ObjectId(hit.source_id) for hit in hits if ObjectId.is_valid(hit.source_id)}
            hydrated: dict[str, dict[str, Any]] = {}
            if oids:
                cursor_docs = (
                    self._records_col.find(
                        {
                            "workspace_id": col["workspace_id"],
                            "project_id": col["project_id"],
                            "collection_id": collection_id,
                            "deleted_at": None,
                            "_id": {"$in": list(oids)},
                        }
                    )
                    .hint("_id_")
                    .limit(len(oids))
                    .max_time_ms(self._settings.max_query_time_ms)
                )
                for raw in cursor_docs:
                    ser = serialize_doc(raw)
                    if ser is not None:
                        hydrated[ser["id"]] = ser
        except ExecutionTimeout as exc:
            raise SearchBackendUnavailableError(
                "Timed out while loading full-text matches; retry shortly"
            ) from exc
        finally:
            self._sem.release()

        items: list[dict[str, Any]] = []
        for hit in hits:
            rec = hydrated.get(hit.source_id)
            if rec is None or (
                hit.source_version is not None and hit.source_version != rec.get("version")
            ):
                continue
            items.append({"record": rec, "highlights": hit.highlights, "score": hit.score})

        next_cursor = None
        if result.has_more and result.next_cursor is not None:
            next_cursor = encode_cursor(
                secret=secret, sig=signature, sort_value=result.next_cursor, last_id=""
            )
        return {
            "items": items,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
            "index_status": {"state": checkpoint["state"], **self._coverage(checkpoint)},
            "result_total": {"value": None, "accuracy": "unavailable"},
            "result_window_limited": result.result_window_limited,
        }
