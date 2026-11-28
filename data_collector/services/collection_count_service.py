"""Tiered, million-record-safe collection count service.

Never runs unbounded exact count_documents() fan-outs. Uses:
  Tier 0: Fresh auxiliary cache (Redis)
  Tier 1: Index-verified, maxTimeMS-bounded exact count on explicit demand/single miss
  Tier 2: Batch multi-get returning cached or 'pending' (never N concurrent DB scans)
  Tier 3: 'unavailable' with reason when no safe index exists or query times out
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from pymongo.database import Database
from pymongo.errors import OperationFailure, PyMongoError

from data_collector.config import Settings
from data_collector.domain.exceptions import ValidationError
from data_collector.domain.identities import Actor, Scope
from data_collector.infrastructure.auxiliary_cache import AuxiliaryCache
from data_collector.services.collection_service import CollectionService

_REQUIRED_PREFIX = ("workspace_id", "project_id", "collection_id", "deleted_at")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _age_seconds(as_of: str | None) -> int | None:
    if not as_of:
        return None
    try:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return max(0, int((datetime.now(UTC) - dt).total_seconds()))
    except Exception:
        return None


def _count_bucket(
    *,
    value: int | None,
    accuracy: str,
    as_of: str | None,
    source: str,
    reason: str | None = None,
) -> dict[str, Any]:
    bucket: dict[str, Any] = {
        "value": value,
        "accuracy": accuracy,
        "as_of": as_of,
        "age_seconds": _age_seconds(as_of),
        "source": source,
    }
    if reason:
        bucket["reason"] = reason
    return bucket


class CollectionCountService:
    """Read-only, cache-first logical collection counter."""

    def __init__(
        self,
        *,
        settings: Settings,
        source_db: Database[Any],
        collections: CollectionService,
        cache: AuxiliaryCache,
    ) -> None:
        self._settings = settings
        self._records_col = source_db.records
        self._collections = collections
        self._cache = cache
        self._sem = threading.BoundedSemaphore(settings.collection_count_max_concurrent)
        self._index_verified: bool | None = None
        self._index_lock = threading.Lock()

    def has_safe_count_index(self) -> bool:
        """Inspect existing source indexes read-only; never creates or modifies indexes."""
        with self._index_lock:
            if self._index_verified is not None:
                return self._index_verified
            try:
                indexes = list(self._records_col.list_indexes())
            except Exception:
                # If index metadata cannot be inspected safely, fail closed to unavailable.
                return False
            matched = False
            for idx in indexes:
                keys = idx.get("key")
                if not keys:
                    continue
                key_names = (
                    tuple(keys.keys()) if hasattr(keys, "keys") else tuple(k for k, _ in keys)
                )
                if len(key_names) >= len(_REQUIRED_PREFIX) and key_names[:4] == _REQUIRED_PREFIX:
                    matched = True
                    break
            self._index_verified = matched
            return matched

    def reset_index_cache(self) -> None:
        with self._index_lock:
            self._index_verified = None

    def _compute_bounded_exact(
        self,
        *,
        workspace_id: str,
        project_id: str,
        collection_id: str,
        kind: str,
    ) -> dict[str, Any]:
        if not self._settings.collection_counts_enabled:
            return _count_bucket(
                value=None,
                accuracy="unavailable",
                as_of=_utc_now_iso(),
                source="planner",
                reason="COLLECTION_COUNTS_ENABLED is false",
            )
        if not self.has_safe_count_index():
            bucket = _count_bucket(
                value=None,
                accuracy="unavailable",
                as_of=_utc_now_iso(),
                source="planner",
                reason="No safe compound index covering tenant scope and deleted_at",
            )
            self._cache.set_json(
                self._cache.count_key(workspace_id, project_id, collection_id, kind),
                bucket,
                ttl_seconds=60,
            )
            return bucket

        lock_key = self._cache.count_lock_key(workspace_id, project_id, collection_id, kind)
        lock_token = self._cache.acquire_lock(lock_key, ttl_seconds=15)
        if lock_token is None:
            return _count_bucket(
                value=None,
                accuracy="pending",
                as_of=None,
                source="background",
                reason="Count refresh already in flight",
            )

        acquired_sem = self._sem.acquire(blocking=False)
        if not acquired_sem:
            self._cache.release_lock(lock_key, lock_token)
            return _count_bucket(
                value=None,
                accuracy="pending",
                as_of=None,
                source="background",
                reason="Global count concurrency budget reached",
            )

        try:
            query: dict[str, Any] = {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "collection_id": collection_id,
                "deleted_at": None if kind == "active" else {"$ne": None},
            }
            max_ms = self._settings.collection_count_max_time_ms
            try:
                count_val = int(self._records_col.count_documents(query, maxTimeMS=max_ms))
            except TypeError:
                # mongomock compatibility in unit/integration tests
                count_val = int(self._records_col.count_documents(query))
            now_iso = _utc_now_iso()
            bucket = _count_bucket(
                value=count_val,
                accuracy="exact_as_of",
                as_of=now_iso,
                source="source_indexed",
            )
            self._cache.set_json(
                self._cache.count_key(workspace_id, project_id, collection_id, kind),
                {**bucket, "source": "cache"},
                ttl_seconds=self._settings.collection_count_cache_ttl_seconds,
            )
            return bucket
        except OperationFailure as exc:
            max_ms = self._settings.collection_count_max_time_ms
            reason = (
                f"Source count exceeded {max_ms}ms budget"
                if exc.code == 50
                else f"Source count failed safely: {type(exc).__name__}"
            )
            bucket = _count_bucket(
                value=None,
                accuracy="unavailable",
                as_of=_utc_now_iso(),
                source="planner",
                reason=reason,
            )
            self._cache.set_json(
                self._cache.count_key(workspace_id, project_id, collection_id, kind),
                bucket,
                ttl_seconds=60,
            )
            return bucket
        except PyMongoError as exc:
            return _count_bucket(
                value=None,
                accuracy="unavailable",
                as_of=_utc_now_iso(),
                source="planner",
                reason=f"Source count failed safely: {type(exc).__name__}",
            )
        finally:
            self._sem.release()
            self._cache.release_lock(lock_key, lock_token)

    def get_collection_count(
        self,
        actor: Actor,
        collection_id: str,
        *,
        include_trash: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.RECORDS_READ
        )
        ws_id = col["workspace_id"]
        proj_id = col["project_id"]

        active_key = self._cache.count_key(ws_id, proj_id, collection_id, "active")
        cached_active = None if refresh else self._cache.get_json(active_key)
        if cached_active is not None:
            cached_active["age_seconds"] = _age_seconds(cached_active.get("as_of"))
            active_bucket = cached_active
        else:
            active_bucket = self._compute_bounded_exact(
                workspace_id=ws_id, project_id=proj_id, collection_id=collection_id, kind="active"
            )

        trashed_bucket: dict[str, Any] | None = None
        if include_trash:
            trash_key = self._cache.count_key(ws_id, proj_id, collection_id, "trashed")
            cached_trash = None if refresh else self._cache.get_json(trash_key)
            if cached_trash is not None:
                cached_trash["age_seconds"] = _age_seconds(cached_trash.get("as_of"))
                trashed_bucket = cached_trash
            else:
                trashed_bucket = self._compute_bounded_exact(
                    workspace_id=ws_id,
                    project_id=proj_id,
                    collection_id=collection_id,
                    kind="trashed",
                )

        total_bucket: dict[str, Any] | None = None
        if (
            include_trash
            and active_bucket.get("value") is not None
            and trashed_bucket is not None
            and trashed_bucket.get("value") is not None
            and active_bucket.get("accuracy") == "exact_as_of"
            and trashed_bucket.get("accuracy") == "exact_as_of"
        ):
            total_bucket = _count_bucket(
                value=int(active_bucket["value"]) + int(trashed_bucket["value"]),
                accuracy="exact_as_of",
                as_of=active_bucket.get("as_of"),
                source=active_bucket.get("source", "cache"),
            )

        status = "ready"
        if active_bucket.get("accuracy") == "pending":
            status = "pending"
        elif active_bucket.get("accuracy") == "unavailable":
            status = "unavailable"

        return {
            "collection_id": collection_id,
            "active": active_bucket,
            "trashed": trashed_bucket,
            "total": total_bucket,
            "status": status,
            "refresh_available": self._settings.collection_counts_enabled
            and self.has_safe_count_index(),
        }

    def get_batch_counts(
        self,
        actor: Actor,
        collection_ids: list[str],
        *,
        include_trash: bool = False,
    ) -> dict[str, Any]:
        max_batch = self._settings.collection_count_batch_max
        if len(collection_ids) > max_batch:
            raise ValidationError(f"collection_ids exceeds max batch size of {max_batch}")

        authorized_cols: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cid in collection_ids:
            if not cid or cid in seen:
                continue
            seen.add(cid)
            try:
                col = self._collections.get_collection(
                    actor, cid, required_scope=Scope.RECORDS_READ
                )
                authorized_cols.append(col)
            except Exception:  # noqa: S112
                # Never leak existence or counts of unauthorized/missing collections.
                continue

        if not authorized_cols:
            return {"items": []}

        active_keys = [
            self._cache.count_key(c["workspace_id"], c["project_id"], c["id"], "active")
            for c in authorized_cols
        ]
        cached_actives = self._cache.get_many_json(active_keys)

        cached_trashes: list[dict[str, Any] | None] = [None] * len(authorized_cols)
        if include_trash:
            trash_keys = [
                self._cache.count_key(c["workspace_id"], c["project_id"], c["id"], "trashed")
                for c in authorized_cols
            ]
            cached_trashes = self._cache.get_many_json(trash_keys)

        items: list[dict[str, Any]] = []
        for idx, col in enumerate(authorized_cols):
            act = cached_actives[idx]
            if act is None:
                counts_on = self._settings.collection_counts_enabled
                act = _count_bucket(
                    value=None,
                    accuracy="pending" if counts_on else "unavailable",
                    as_of=None,
                    source="background" if counts_on else "planner",
                )
                status = "pending" if counts_on else "unavailable"
            else:
                act["age_seconds"] = _age_seconds(act.get("as_of"))
                status = (
                    "unavailable"
                    if act.get("accuracy") == "unavailable"
                    else "ready"
                )

            tr: dict[str, Any] | None = None
            if include_trash:
                tr = cached_trashes[idx]
                if tr is None:
                    tr = _count_bucket(
                        value=None,
                        accuracy="pending",
                        as_of=None,
                        source="background",
                    )
                else:
                    tr["age_seconds"] = _age_seconds(tr.get("as_of"))

            items.append(
                {
                    "collection_id": col["id"],
                    "active": act,
                    "trashed": tr,
                    "total": None,
                    "status": status,
                }
            )
        return {"items": items}

    def trigger_refresh(
        self,
        actor: Actor,
        collection_id: str,
        *,
        include_trash: bool = False,
    ) -> tuple[dict[str, Any], int]:
        """Explicitly refresh one collection count within strict concurrency bounds."""
        if not self._settings.collection_counts_enabled:
            return {
                "collection_id": collection_id,
                "status": "unavailable",
                "reason": "Collection counts are disabled",
            }, 503

        res = self.get_collection_count(
            actor, collection_id, include_trash=include_trash, refresh=True
        )
        if res["status"] == "pending":
            return res, 429
        if res["status"] == "unavailable":
            return res, 503
        return {**res, "status": "accepted"}, 202

    def invalidate_collection(self, workspace_id: str, project_id: str, collection_id: str) -> None:
        self._cache.delete(
            self._cache.count_key(workspace_id, project_id, collection_id, "active"),
            self._cache.count_key(workspace_id, project_id, collection_id, "trashed"),
        )
