"""Tenant-isolated Records repository.

Every operation unconditionally injects workspace_id, project_id, and collection_id.
"""

from __future__ import annotations

import contextlib
from typing import Any

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.database import Database

from data_collector.domain.entities import utc_now
from data_collector.domain.exceptions import ConflictError
from data_collector.infrastructure.repositories.base import serialize_doc, to_object_id


class RecordRepository:
    """Repository over the shared `records` collection with strict tenant scope."""

    def __init__(self, db: Database[Any]) -> None:
        self._col = db.records

    @staticmethod
    def _scope(workspace_id: str, project_id: str, collection_id: str) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "collection_id": collection_id,
        }

    def insert_one(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        data: dict[str, Any],
        created_by: str,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        doc = {
            **self._scope(workspace_id, project_id, collection_id),
            "data": data,
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "created_by": created_by,
            "deleted_at": None,
            "source": source,
        }
        res = self._col.insert_one(doc)
        doc["_id"] = res.inserted_id
        return serialize_doc(doc)  # type: ignore[return-value]

    def get_by_id(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        record_id: str,
        include_deleted: bool = False,
    ) -> dict[str, Any] | None:
        query: dict[str, Any] = {
            **self._scope(workspace_id, project_id, collection_id),
            "_id": to_object_id(record_id, "record_id"),
        }
        if not include_deleted:
            query["deleted_at"] = None
        return serialize_doc(self._col.find_one(query))

    def update_with_version(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        record_id: str,
        expected_version: int,
        new_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        oid = to_object_id(record_id, "record_id")
        scope = {
            **self._scope(workspace_id, project_id, collection_id),
            "_id": oid,
            "deleted_at": None,
        }
        doc = self._col.find_one_and_update(
            {**scope, "version": expected_version},
            {
                "$set": {"data": new_data, "updated_at": utc_now()},
                "$inc": {"version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            existing = self._col.find_one(scope, {"version": 1})
            if existing is not None:
                raise ConflictError(
                    f"Version conflict: expected {expected_version}, "
                    f"current {existing.get('version')}"
                )
            return None
        return serialize_doc(doc)

    def soft_delete_with_version(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        record_id: str,
        expected_version: int,
    ) -> dict[str, Any] | None:
        oid = to_object_id(record_id, "record_id")
        scope = {
            **self._scope(workspace_id, project_id, collection_id),
            "_id": oid,
            "deleted_at": None,
        }
        doc = self._col.find_one_and_update(
            {**scope, "version": expected_version},
            {
                "$set": {"deleted_at": utc_now(), "updated_at": utc_now()},
                "$inc": {"version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            existing = self._col.find_one(scope, {"version": 1})
            if existing is not None:
                raise ConflictError(
                    f"Version conflict: expected {expected_version}, "
                    f"current {existing.get('version')}"
                )
            return None
        return serialize_doc(doc)

    def restore(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        oid = to_object_id(record_id, "record_id")
        doc = self._col.find_one_and_update(
            {
                **self._scope(workspace_id, project_id, collection_id),
                "_id": oid,
                "deleted_at": {"$ne": None},
            },
            {
                "$set": {"deleted_at": None, "updated_at": utc_now()},
                "$inc": {"version": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        return serialize_doc(doc)

    def find_page(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        mongo_filter: dict[str, Any],
        sort_field: str,
        sort_direction: int,
        limit: int,
        cursor_filter: dict[str, Any] | None = None,
        projection: dict[str, int] | None = None,
        max_time_ms: int = 5000,
    ) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = [
            self._scope(workspace_id, project_id, collection_id),
            {"deleted_at": None},
        ]
        if mongo_filter:
            parts.append(mongo_filter)
        if cursor_filter:
            parts.append(cursor_filter)
        query: dict[str, Any] = {"$and": parts} if len(parts) > 1 else parts[0]

        sort_dir = ASCENDING if sort_direction >= 0 else DESCENDING
        sort_spec = [(sort_field, sort_dir), ("_id", sort_dir)]
        if sort_field == "_id":
            sort_spec = [("_id", sort_dir)]

        cur = self._col.find(query, projection).sort(sort_spec).limit(limit)
        with contextlib.suppress(TypeError, NotImplementedError):
            cur = cur.max_time_ms(max_time_ms)
        return [s for d in cur if (s := serialize_doc(d)) is not None]

    def count(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        mongo_filter: dict[str, Any],
        max_time_ms: int = 5000,
    ) -> int:
        query: dict[str, Any] = {
            **self._scope(workspace_id, project_id, collection_id),
            "deleted_at": None,
        }
        if mongo_filter:
            query = {"$and": [query, mongo_filter]}
        try:
            return int(self._col.count_documents(query, maxTimeMS=max_time_ms))
        except TypeError:
            return int(self._col.count_documents(query))

    def count_for_collection(self, *, workspace_id: str, collection_id: str) -> dict[str, int]:
        """Active and trashed (soft-deleted) record counts for one collection."""
        scope = {"workspace_id": workspace_id, "collection_id": collection_id}
        active = int(self._col.count_documents({**scope, "deleted_at": None}))
        trashed = int(self._col.count_documents({**scope, "deleted_at": {"$ne": None}}))
        return {"active": active, "trashed": trashed, "total": active + trashed}

    def delete_all_for_collection(self, *, workspace_id: str, collection_id: str) -> int:
        """Hard-delete every record (active and trashed) of one collection in a single
        deleteMany. Scoped by workspace_id AND collection_id; never call without both."""
        if not workspace_id or not collection_id:
            raise ValueError("workspace_id and collection_id are required")
        res = self._col.delete_many({"workspace_id": workspace_id, "collection_id": collection_id})
        return int(res.deleted_count)
