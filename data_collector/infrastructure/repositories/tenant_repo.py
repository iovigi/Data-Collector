"""Repositories for tenancy, auth, keys, jobs, audit, and idempotency."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from data_collector.domain.entities import utc_now
from data_collector.domain.exceptions import ConflictError
from data_collector.infrastructure.repositories.base import serialize_doc, to_object_id


class UserRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.users

    def find_by_email(self, email: str) -> dict[str, Any] | None:
        return self._col.find_one({"email": email.strip().lower()})

    def find_by_id(self, user_id: str) -> dict[str, Any] | None:
        return self._col.find_one({"_id": to_object_id(user_id, "user_id")})

    def create(
        self, email: str, password_hash: str, *, is_superadmin: bool = False
    ) -> dict[str, Any]:
        now = utc_now()
        doc = {
            "email": email.strip().lower(),
            "password_hash": password_hash,
            "status": "active",
            "is_superadmin": is_superadmin,
            "created_at": now,
            "updated_at": now,
        }
        try:
            res = self._col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ConflictError("User already exists") from exc
        doc["_id"] = res.inserted_id
        return serialize_doc(doc)  # type: ignore[return-value]

    def update_password_hash(self, user_id: str, new_hash: str) -> None:
        self._col.update_one(
            {"_id": to_object_id(user_id, "user_id")},
            {"$set": {"password_hash": new_hash, "updated_at": utc_now()}},
        )


class WorkspaceRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._ws = db.workspaces
        self._members = db.memberships

    def create(self, slug: str, name: str, owner_id: str) -> dict[str, Any]:
        now = utc_now()
        doc = {
            "slug": slug,
            "name": name,
            "owner_id": owner_id,
            "status": "active",
            "limits": {},
            "created_at": now,
        }
        try:
            res = self._ws.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ConflictError("Workspace slug already exists") from exc
        ws_id = str(res.inserted_id)
        self._members.insert_one(
            {
                "workspace_id": ws_id,
                "principal_id": owner_id,
                "role": "owner",
                "created_at": now,
            }
        )
        doc["_id"] = res.inserted_id
        return serialize_doc(doc)  # type: ignore[return-value]

    def get_by_id(self, workspace_id: str) -> dict[str, Any] | None:
        doc = self._ws.find_one({"_id": to_object_id(workspace_id, "workspace_id")})
        return serialize_doc(doc)

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        return serialize_doc(self._ws.find_one({"slug": slug}))

    def list_for_principal(
        self, principal_id: str, limit: int = 25, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        memberships = list(self._members.find({"principal_id": principal_id}))
        ws_ids = [to_object_id(m["workspace_id"], "workspace_id") for m in memberships]
        if not ws_ids:
            return []
        query: dict[str, Any] = {"_id": {"$in": ws_ids}}
        if cursor:
            query["_id"]["$gt"] = to_object_id(cursor, "cursor")
        docs = list(self._ws.find(query).sort("_id", 1).limit(limit))
        return [s for d in docs if (s := serialize_doc(d)) is not None]

    def get_membership_role(self, workspace_id: str, principal_id: str) -> str | None:
        m = self._members.find_one({"workspace_id": workspace_id, "principal_id": principal_id})
        return str(m["role"]) if m else None

    def set_membership(self, workspace_id: str, principal_id: str, role: str) -> None:
        self._members.update_one(
            {"workspace_id": workspace_id, "principal_id": principal_id},
            {"$set": {"role": role}, "$setOnInsert": {"created_at": utc_now()}},
            upsert=True,
        )


class ProjectRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.projects

    def create(self, workspace_id: str, slug: str, name: str) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "workspace_id": workspace_id,
            "slug": slug,
            "name": name,
            "status": "active",
            "created_at": utc_now(),
        }
        try:
            res = self._col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ConflictError("Project slug already exists in workspace") from exc
        doc["_id"] = res.inserted_id
        return serialize_doc(doc)  # type: ignore[return-value]

    def get_by_id(self, project_id: str) -> dict[str, Any] | None:
        return serialize_doc(self._col.find_one({"_id": to_object_id(project_id, "project_id")}))

    def list_by_workspace(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        docs = list(self._col.find({"workspace_id": workspace_id}).sort("_id", 1).limit(limit))
        return [s for d in docs if (s := serialize_doc(d)) is not None]


class CollectionRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.collections

    def create(
        self,
        workspace_id: str,
        project_id: str,
        slug: str,
        schema_json: dict[str, Any],
        searchable_fields: list[str] | None = None,
        sortable_fields: list[str] | None = None,
        retention_days: int = 30,
    ) -> dict[str, Any]:
        now = utc_now()
        doc: dict[str, Any] = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "slug": slug,
            "schema_json": schema_json,
            "schema_version": 1,
            "searchable_fields": searchable_fields or [],
            "sortable_fields": sortable_fields or ["created_at", "updated_at"],
            "retention_days": retention_days,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        try:
            res = self._col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ConflictError("Collection slug already exists in project") from exc
        doc["_id"] = res.inserted_id
        return serialize_doc(doc)  # type: ignore[return-value]

    def get_by_id(self, collection_id: str) -> dict[str, Any] | None:
        return serialize_doc(
            self._col.find_one({"_id": to_object_id(collection_id, "collection_id")})
        )

    def list_by_project(
        self, workspace_id: str, project_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        docs = list(
            self._col.find({"workspace_id": workspace_id, "project_id": project_id})
            .sort("_id", 1)
            .limit(limit)
        )
        return [s for d in docs if (s := serialize_doc(d)) is not None]

    def update_schema(
        self,
        workspace_id: str,
        collection_id: str,
        *,
        schema_json: dict[str, Any] | None = None,
        searchable_fields: list[str] | None = None,
        sortable_fields: list[str] | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {"updated_at": utc_now()}
        inc: dict[str, int] = {}
        if schema_json is not None:
            updates["schema_json"] = schema_json
            inc["schema_version"] = 1
        if searchable_fields is not None:
            updates["searchable_fields"] = searchable_fields
        if sortable_fields is not None:
            updates["sortable_fields"] = sortable_fields
        if retention_days is not None:
            updates["retention_days"] = retention_days
        op: dict[str, Any] = {"$set": updates}
        if inc:
            op["$inc"] = inc
        doc = self._col.find_one_and_update(
            {"_id": to_object_id(collection_id, "collection_id"), "workspace_id": workspace_id},
            op,
            return_document=ReturnDocument.AFTER,
        )
        return serialize_doc(doc)


class ApiKeyRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.api_keys

    def create(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        name: str,
        prefix: str,
        key_hash: str,
        scopes: list[str],
        allowed_collection_ids: list[str] | None,
        expires_at: Any,
    ) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "workspace_id": workspace_id,
            "principal_id": principal_id,
            "name": name,
            "prefix": prefix,
            "key_hash": key_hash,
            "scopes": scopes,
            "allowed_collection_ids": allowed_collection_ids,
            "expires_at": expires_at,
            "last_used_at": None,
            "revoked_at": None,
            "created_at": utc_now(),
        }
        res = self._col.insert_one(doc)
        doc["_id"] = res.inserted_id
        out = serialize_doc(doc)
        assert out is not None
        out.pop("key_hash", None)
        return out

    def find_by_prefix(self, prefix: str) -> dict[str, Any] | None:
        return self._col.find_one({"prefix": prefix})

    def touch_last_used(self, key_id: ObjectId) -> None:
        self._col.update_one({"_id": key_id}, {"$set": {"last_used_at": utc_now()}})

    def list_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        docs = list(self._col.find({"workspace_id": workspace_id}).sort("created_at", DESCENDING))
        out = []
        for d in docs:
            s = serialize_doc(d)
            if s:
                s.pop("key_hash", None)
                out.append(s)
        return out

    def revoke(self, workspace_id: str, key_id: str) -> dict[str, Any] | None:
        doc = self._col.find_one_and_update(
            {"_id": to_object_id(key_id, "key_id"), "workspace_id": workspace_id},
            {"$set": {"revoked_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        s = serialize_doc(doc)
        if s:
            s.pop("key_hash", None)
        return s


class RefreshTokenRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.refresh_tokens

    def store(self, token_hash: str, user_id: str, family_id: str, expires_at: Any) -> None:
        self._col.insert_one(
            {
                "token_hash": token_hash,
                "user_id": user_id,
                "family_id": family_id,
                "revoked_at": None,
                "expires_at": expires_at,
                "created_at": utc_now(),
            }
        )

    def find_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self._col.find_one({"token_hash": token_hash})

    def revoke_hash(self, token_hash: str) -> None:
        self._col.update_one({"token_hash": token_hash}, {"$set": {"revoked_at": utc_now()}})

    def revoke_family(self, family_id: str) -> None:
        self._col.update_many({"family_id": family_id}, {"$set": {"revoked_at": utc_now()}})


class AuditRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.audit_events

    def append(
        self,
        *,
        tenant: str | None,
        actor_id: str,
        action: str,
        target: str,
        decision: str,
        request_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._col.insert_one(
            {
                "tenant": tenant,
                "actor": actor_id,
                "action": action,
                "target": target,
                "decision": decision,
                "request_id": request_id,
                "timestamp": utc_now(),
                "metadata": metadata or {},
            }
        )

    def list_by_tenant(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        docs = list(
            self._col.find({"tenant": workspace_id}).sort("timestamp", DESCENDING).limit(limit)
        )
        return [s for d in docs if (s := serialize_doc(d)) is not None]


class IdempotencyRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.idempotency_keys

    def get(self, scope: str, method: str, path: str, key_hash: str) -> dict[str, Any] | None:
        return self._col.find_one(
            {"scope": scope, "method": method, "path": path, "key_hash": key_hash}
        )

    def save(
        self,
        *,
        scope: str,
        method: str,
        path: str,
        key_hash: str,
        request_digest: str,
        status_code: int,
        response_body: dict[str, Any],
        ttl_hours: int = 24,
    ) -> None:
        now = utc_now()
        self._col.update_one(
            {"scope": scope, "method": method, "path": path, "key_hash": key_hash},
            {
                "$setOnInsert": {
                    "request_digest": request_digest,
                    "status_code": status_code,
                    "response_body": response_body,
                    "created_at": now,
                    "expires_at": now + timedelta(hours=ttl_hours),
                }
            },
            upsert=True,
        )


class JobRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.jobs

    def create(
        self,
        *,
        workspace_id: str,
        initiator_id: str,
        job_type: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        doc: dict[str, Any] = {
            "workspace_id": workspace_id,
            "initiator_id": initiator_id,
            "type": job_type,
            "state": "queued",
            "progress": {"processed": 0, "succeeded": 0, "failed": 0, "total": 0},
            "params": params,
            "output_ref": None,
            "errors": [],
            "error_summary": None,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
        }
        res = self._col.insert_one(doc)
        doc["_id"] = res.inserted_id
        return serialize_doc(doc)  # type: ignore[return-value]

    def get_by_id(self, job_id: str) -> dict[str, Any] | None:
        return serialize_doc(self._col.find_one({"_id": to_object_id(job_id, "job_id")}))

    def update_state(
        self,
        job_id: str,
        state: str,
        *,
        progress: dict[str, Any] | None = None,
        output_ref: dict[str, Any] | None = None,
        errors: list[dict[str, Any]] | None = None,
        error_summary: str | None = None,
        started_at: Any = None,
        finished_at: Any = None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {"state": state}
        if progress is not None:
            updates["progress"] = progress
        if output_ref is not None:
            updates["output_ref"] = output_ref
        if errors is not None:
            updates["errors"] = errors[:100]
        if error_summary is not None:
            updates["error_summary"] = error_summary
        if started_at is not None:
            updates["started_at"] = started_at
        if finished_at is not None:
            updates["finished_at"] = finished_at
        doc = self._col.find_one_and_update(
            {"_id": to_object_id(job_id, "job_id")},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        return serialize_doc(doc)


class DeleteIntentRepository:
    def __init__(self, db: Database[Any]) -> None:
        self._col = db.delete_intents

    def record_intent(self, jti: str, expires_at: Any) -> None:
        self._col.insert_one({"jti": jti, "consumed": False, "expires_at": expires_at})

    def consume(self, jti: str) -> bool:
        doc = self._col.find_one_and_update(
            {"jti": jti, "consumed": False},
            {"$set": {"consumed": True}},
            return_document=ReturnDocument.AFTER,
        )
        return doc is not None
