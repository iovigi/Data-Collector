"""M11 services: Saved Queries, Webhooks (SSRF defense), Schema Migrations, Usage Analytics."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError as JsonSchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pymongo import DESCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from data_collector.domain.entities import utc_now
from data_collector.domain.exceptions import ConflictError, NotFoundError, ValidationError
from data_collector.domain.identities import Actor, Scope
from data_collector.domain.policies import require_workspace_membership
from data_collector.infrastructure.repositories.base import serialize_doc, to_object_id
from data_collector.infrastructure.repositories.record_repo import RecordRepository
from data_collector.infrastructure.repositories.tenant_repo import WorkspaceRepository
from data_collector.infrastructure.ssrf import post_webhook_safe, validate_outbound_url
from data_collector.services.audit_service import AuditService
from data_collector.services.collection_service import CollectionService
from data_collector.services.query_dsl import compile_filter
from data_collector.services.record_service import RecordService, _allowed_fields_for_collection

ALLOWED_WEBHOOK_EVENTS = frozenset(
    {
        "record.created",
        "record.updated",
        "record.deleted",
        "job.completed",
        "job.failed",
    }
)


class SavedQueryService:
    """Owner/workspace-scoped named query definitions using the Safe Query DSL."""

    def __init__(
        self,
        *,
        db: Database[Any],
        collections: CollectionService,
        records: RecordService,
        audit: AuditService,
    ) -> None:
        self._col = db.saved_queries
        self._collections = collections
        self._records = records
        self._audit = audit

    def create(
        self,
        actor: Actor,
        collection_id: str,
        *,
        name: str,
        filter_ast: dict[str, Any] | None = None,
        sort: list[dict[str, str]] | None = None,
        fields: list[str] | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.COLLECTION_MANAGE
        )
        allowed = _allowed_fields_for_collection(col)
        compile_filter(filter_ast, allowed_fields=allowed)
        now = utc_now()
        doc = {
            "workspace_id": col["workspace_id"],
            "collection_id": collection_id,
            "name": name.strip(),
            "filter": filter_ast,
            "sort": sort,
            "fields": fields,
            "limit": min(max(1, limit), 100),
            "version": 1,
            "created_by": actor.principal_id,
            "created_at": now,
            "updated_at": now,
        }
        if self._col.find_one({"collection_id": collection_id, "name": doc["name"]}) is not None:
            raise ConflictError("Saved query with this name already exists in collection")
        try:
            res = self._col.insert_one(doc)
        except DuplicateKeyError as exc:
            raise ConflictError("Saved query name conflict") from exc
        doc["_id"] = res.inserted_id
        self._audit.record(
            tenant=col["workspace_id"],
            actor_id=actor.principal_id,
            action="saved_query.create",
            target=f"saved_query:{res.inserted_id}",
            decision="allow",
        )
        return serialize_doc(doc)  # type: ignore[return-value]

    def list_for_collection(self, actor: Actor, collection_id: str) -> list[dict[str, Any]]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.COLLECTION_READ
        )
        docs = list(
            self._col.find(
                {"workspace_id": col["workspace_id"], "collection_id": collection_id}
            ).sort("_id", 1)
        )
        return [s for d in docs if (s := serialize_doc(d)) is not None]

    def run(
        self, actor: Actor, saved_query_id: str, *, cursor: str | None = None
    ) -> dict[str, Any]:
        sq = serialize_doc(
            self._col.find_one({"_id": to_object_id(saved_query_id, "saved_query_id")})
        )
        if sq is None:
            raise NotFoundError("Saved query not found")
        return self._records.search_records(
            actor,
            sq["collection_id"],
            filter_ast=sq.get("filter"),
            sort=sq.get("sort"),
            fields=sq.get("fields"),
            limit=sq.get("limit", 25),
            cursor=cursor,
        )


class WebhookService:
    """Managed workspace webhooks with SSRF defense, HMAC-SHA256 signatures, and delivery logs."""

    def __init__(
        self,
        *,
        db: Database[Any],
        workspaces: WorkspaceRepository,
        audit: AuditService,
        allow_localhost_dev: bool = False,
    ) -> None:
        self._hooks = db.webhooks
        self._deliveries = db.webhook_deliveries
        self._workspaces = workspaces
        self._audit = audit
        self._allow_localhost_dev = allow_localhost_dev

    def create(
        self,
        actor: Actor,
        workspace_id: str,
        *,
        name: str,
        url: str,
        events: list[str],
    ) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_MANAGE)
        if self._hooks.count_documents({"workspace_id": workspace_id}) >= 20:
            raise ValidationError("Workspace webhook quota (20) exceeded")
        for ev in events:
            if ev not in ALLOWED_WEBHOOK_EVENTS:
                raise ValidationError(f"Unsupported webhook event '{ev}'")
        validate_outbound_url(url, allow_localhost_dev=self._allow_localhost_dev)
        signing_secret = f"whsec_{secrets.token_urlsafe(32)}"
        doc = {
            "workspace_id": workspace_id,
            "name": name.strip(),
            "url": url,
            "events": list(dict.fromkeys(events)),
            "secret_hash": hashlib.sha256(signing_secret.encode("utf-8")).hexdigest(),
            "signing_secret_enc": signing_secret,
            "status": "active",
            "created_at": utc_now(),
        }
        res = self._hooks.insert_one(doc)
        doc["_id"] = res.inserted_id
        out = serialize_doc(doc)
        assert out is not None
        out.pop("secret_hash", None)
        out.pop("signing_secret_enc", None)
        out["signing_secret"] = signing_secret
        self._audit.record(
            tenant=workspace_id,
            actor_id=actor.principal_id,
            action="webhook.create",
            target=f"webhook:{out['id']}",
            decision="allow",
        )
        return out

    def list_for_workspace(self, actor: Actor, workspace_id: str) -> list[dict[str, Any]]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_READ)
        docs = list(self._hooks.find({"workspace_id": workspace_id}).sort("created_at", DESCENDING))
        out = []
        for d in docs:
            s = serialize_doc(d)
            if s:
                s.pop("secret_hash", None)
                s.pop("signing_secret_enc", None)
                out.append(s)
        return out

    @staticmethod
    def sign_payload(secret: str, body: bytes) -> str:
        return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def dispatch_event(
        self,
        workspace_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        http_client: httpx.Client | None = None,
    ) -> list[dict[str, Any]]:
        hooks = list(
            self._hooks.find(
                {"workspace_id": workspace_id, "status": "active", "events": event_type}
            )
        )
        results: list[dict[str, Any]] = []
        body = json.dumps({"event": event_type, "data": payload}, default=str).encode("utf-8")
        ts = str(int(utc_now().timestamp()))
        for h in hooks:
            delivery_id = secrets.token_hex(12)
            signed_input = f"{ts}.".encode() + body
            sig = self.sign_payload(h["signing_secret_enc"], signed_input)
            status = "delivered"
            code = 0
            try:
                code = post_webhook_safe(
                    h["url"],
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-DC-Event": event_type,
                        "X-DC-Timestamp": ts,
                        "X-DC-Delivery-Id": delivery_id,
                        "X-DC-Signature": sig,
                    },
                    allow_localhost_dev=self._allow_localhost_dev,
                    http_client=http_client,
                )
                if code >= 400 or (300 <= code < 400):
                    status = "failed"
            except Exception:
                status = "failed"
            entry = {
                "delivery_id": delivery_id,
                "webhook_id": str(h["_id"]),
                "workspace_id": workspace_id,
                "event": event_type,
                "status": status,
                "http_status": code,
                "created_at": utc_now(),
            }
            self._deliveries.insert_one(entry)
            results.append(serialize_doc(entry) or {})
        return results


class SchemaMigrationService:
    """Preview and safely apply JSON Schema version transitions."""

    def __init__(
        self,
        *,
        collections: CollectionService,
        records: RecordRepository,
        audit: AuditService,
    ) -> None:
        self._collections = collections
        self._records = records
        self._audit = audit

    def preview(
        self,
        actor: Actor,
        collection_id: str,
        candidate_schema: dict[str, Any],
    ) -> dict[str, Any]:
        col = self._collections.get_collection(
            actor, collection_id, required_scope=Scope.COLLECTION_MANAGE
        )
        try:
            Draft202012Validator.check_schema(candidate_schema)
        except JsonSchemaError as exc:
            raise ValidationError(f"Invalid candidate schema: {exc.message}") from exc

        validator = Draft202012Validator(candidate_schema)
        rows = self._records.find_page(
            workspace_id=col["workspace_id"],
            project_id=col["project_id"],
            collection_id=collection_id,
            mongo_filter={},
            sort_field="_id",
            sort_direction=1,
            limit=5000,
        )
        failures: list[dict[str, Any]] = []
        for r in rows:
            try:
                validator.validate(r["data"])
            except JsonSchemaValidationError as exc:
                if len(failures) < 50:
                    failures.append({"record_id": r["id"], "reason": exc.message})
        return {
            "collection_id": collection_id,
            "current_version": col["schema_version"],
            "checked_records": len(rows),
            "failing_records": len(failures),
            "compatible": len(failures) == 0,
            "failures": failures,
        }

    def apply(
        self,
        actor: Actor,
        collection_id: str,
        candidate_schema: dict[str, Any],
    ) -> dict[str, Any]:
        report = self.preview(actor, collection_id, candidate_schema)
        if not report["compatible"]:
            raise ConflictError(
                f"Schema migration aborted: {report['failing_records']} records fail validation"
            )
        updated = self._collections.update_collection(
            actor, collection_id, schema_json=candidate_schema
        )
        self._audit.record(
            tenant=updated["workspace_id"],
            actor_id=actor.principal_id,
            action="schema_migration.apply",
            target=f"collection:{collection_id}",
            decision="allow",
            metadata={"new_version": updated["schema_version"]},
        )
        return updated


class UsageAnalyticsService:
    """Bounded-cardinality per-workspace usage counters."""

    def __init__(self, *, db: Database[Any], workspaces: WorkspaceRepository) -> None:
        self._db = db
        self._workspaces = workspaces

    def summary(self, actor: Actor, workspace_id: str) -> dict[str, Any]:
        role = self._workspaces.get_membership_role(workspace_id, actor.principal_id)
        require_workspace_membership(actor, workspace_id, role, Scope.WORKSPACE_READ)
        records_count = self._db.records.count_documents(
            {"workspace_id": workspace_id, "deleted_at": None}
        )
        collections_count = self._db.collections.count_documents({"workspace_id": workspace_id})
        jobs_completed = self._db.jobs.count_documents(
            {"workspace_id": workspace_id, "state": "completed"}
        )
        jobs_failed = self._db.jobs.count_documents(
            {"workspace_id": workspace_id, "state": "failed"}
        )
        audit_count = self._db.audit_events.count_documents({"tenant": workspace_id})
        return {
            "workspace_id": workspace_id,
            "records_active": records_count,
            "collections": collections_count,
            "jobs_completed": jobs_completed,
            "jobs_failed": jobs_failed,
            "audit_events": audit_count,
        }
